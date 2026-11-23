"""bgm_analyze.py — 默认单曲测拍卡点器（纯 numpy + FFmpeg 9.0.2，零外部 API）。

用法：
  python tools\\bgm_analyze.py
      -> 自动探测 assets/bgm/bgm.{m4a,mp3,wav,flac}
  python tools\\bgm_analyze.py <audio_path> [--out <json_path>]
      -> 在音频同目录生成 <stem>.beats.json（默认单曲即 bgm.beats.json）

算法（全部 numpy，无 librosa/scipy 依赖）：
  - FFmpeg 解码 22050Hz 单声道 f32 PCM
  - 分块 STFT -> 对数压缩幅度 -> 半波整流频谱通量起音包络
  - FFT 自相关 + 谐波和评分估 BPM（优先区间 90–140，自动倍频/半频校正，
    精准捕获 ~113 BPM 氛围曲）
  - 起音相位搜索 -> beat_times，4/4 强拍投票 -> bar_times
  - 0.25s 滑窗 RMS dB 曲线 -> Top 3 能量骤升 Drop（对齐到最近拍点）+
    低分位静谧段 quiet_spans + 1s 分辨率 rms_profile_1s
"""
from __future__ import annotations

from bgm_common import sha256_file
import os
import tempfile
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bgm_common import (  # noqa: E402
    DEFAULT_EXT_ORDER, DEFAULT_STEM, SUPPORTED_EXT, decode_f32,
    default_bgm_dir, locate_tools, version_line,
)

SR = 22050
N_FFT = 1024
HOP = 256
FPS_ENV = SR / HOP                      # 86.1328125 帧/秒
BPM_PREF = (90.0, 140.0)               # 优先区间（~113 BPM 氛围曲）
BPM_ALL = (60.0, 150.0)                # 兜底全区间
BPM_STEP = 0.1
RMS_WIN = 0.25
RMS_HOP = 0.125
DROP_HEAD_SKIP_SEC = 2.0          # 片头「起始进入」不算高潮重进（之前无低谷段落）
DROP_BASELINE_FLOOR_RATIO = 0.02  # baseline 地板，避免片头静音把 rise_db 放大成伪影


# --------------------------------------------------------------------------
# STFT / 起音包络 / 自相关
# --------------------------------------------------------------------------
def stft_mag(x: np.ndarray, n_fft: int = N_FFT, hop: int = HOP,
             chunk_frames: int = 2048) -> np.ndarray:
    win = np.hanning(n_fft).astype(np.float32)
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x) + 1))
    n_frames = 1 + (len(x) - n_fft) // hop
    cols = np.arange(n_fft)
    out = []
    for s in range(0, n_frames, chunk_frames):
        rows = np.arange(s, min(s + chunk_frames, n_frames))
        idx = rows[:, None] * hop + cols[None, :]
        frames = x[idx] * win
        out.append(np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32))
    return np.concatenate(out, axis=0)


def onset_envelope(mag: np.ndarray) -> np.ndarray:
    m = np.log1p(mag * 8.0)
    # 用零帧 prepend（而非 m[:1]）：否则第 0 帧的起音会被 diff 抹掉，
    # 首个可见峰落到第二拍，导致整条节拍网格相位偏移一个拍周期。
    d = np.diff(m, axis=0, prepend=np.zeros((1, m.shape[1]), dtype=m.dtype))
    flux = np.maximum(d, 0.0).sum(axis=1)
    flux = flux - np.median(flux)
    k = 3
    flux = np.convolve(flux, np.ones(k, dtype=np.float64) / k, mode="same")
    flux = np.maximum(flux, 0.0)
    if flux.max() > 0:
        flux = flux / flux.max()
    return flux.astype(np.float64)


def autocorr(e: np.ndarray) -> np.ndarray:
    e = e - e.mean()
    n = 1 << (2 * len(e) - 1).bit_length()
    f = np.fft.rfft(e, n=n)
    ac = np.fft.irfft(f * np.conj(f), n=n)[:len(e)]
    if ac[0] <= 0:
        return np.zeros_like(e)
    return (ac / ac[0]).astype(np.float64)


def score_bpm(ac: np.ndarray, fps: float, bpm: float) -> float:
    """谐波和自相关评分：真周期的 1/2/3/4 倍 lag 同时落在起音峰上得分最高，
    天然抑制半频/倍频歧义。lag 用精确线性插值取值（不用 ±N 帧取最大值，
    否则相邻 BPM 得分会被抹平而失去分辨率）。"""
    period = 60.0 * fps / bpm
    weights = (1.0, 0.65, 0.45, 0.30)
    grid = np.arange(len(ac), dtype=np.float64)
    total = 0.0
    for k, w in enumerate(weights, start=1):
        lag = k * period
        if lag >= len(ac) - 1:
            continue
        total += w * max(0.0, float(np.interp(lag, grid, ac)))
    return total


def refine_peak(ac: np.ndarray, bpm: float, fps: float = FPS_ENV) -> float:
    """对自相关主峰做抛物线亚帧插值，把 BPM 精度从 ±1.5 提升到 ±0.1。"""
    period = 60.0 * fps / bpm
    L = int(round(period))
    if L < 2 or L + 1 >= len(ac):
        return bpm
    y0, y1, y2 = float(ac[L - 1]), float(ac[L]), float(ac[L + 1])
    denom = y0 - 2.0 * y1 + y2
    if abs(denom) < 1e-12:
        return bpm
    delta = 0.5 * (y0 - y2) / denom
    if abs(delta) > 1.0:
        return bpm
    refined = 60.0 * fps / (L + delta)
    return refined if abs(refined - bpm) <= 3.0 else bpm


def estimate_bpm(ac: np.ndarray, fps: float = FPS_ENV):
    """返回 (bpm, score, note)。优先 90–140，自动倍频/半频校正 + 亚帧细化。"""
    def sweep(lo, hi):
        best_score, best_bpm = -1.0, lo
        for bpm in np.arange(lo, hi + 1e-9, BPM_STEP):
            s = score_bpm(ac, fps, float(bpm))
            if s > best_score:
                best_score, best_bpm = s, float(bpm)
        return best_score, best_bpm

    s_all, b_all = sweep(*BPM_ALL)
    s_pref, b_pref = sweep(*BPM_PREF)

    if BPM_PREF[0] <= b_all <= BPM_PREF[1]:
        bpm, score = b_all, s_all
        note = "落在优先区间 90–140 BPM"
    else:
        # 倍频 / 半频 / 3:2 校正：把全区间最优拉回优先区间
        cands = []
        for factor, tag in ((2.0, "半频×2 校正"), (0.5, "倍频÷2 校正"),
                            (1.5, "2:3 校正"), (2.0 / 3.0, "3:2 校正")):
            b2 = b_all * factor
            if BPM_PREF[0] <= b2 <= BPM_PREF[1]:
                cands.append((score_bpm(ac, fps, b2), round(b2, 2), tag))
        if cands and max(cands)[0] >= 0.88 * s_all:
            s, bpm2, tag = max(cands)
            bpm, score = bpm2, s
            note = f"由 {b_all:.1f} BPM {tag} → {bpm:.1f} BPM"
        else:
            bpm, score = b_pref, s_pref
            note = (f"全区间最优 {b_all:.1f} BPM 在优先区间外且无可信倍频关系，"
                    "取优先区间最优")

    refined = refine_peak(ac, bpm, fps)
    if abs(refined - bpm) > 1e-6:
        note += f"；自相关峰抛物线细化 {bpm:.1f} → {refined:.2f} BPM"
        bpm = refined
    return round(bpm, 2), round(score, 4), note


# --------------------------------------------------------------------------
# 拍点 / 小节强拍网格
# --------------------------------------------------------------------------
def best_phase(env: np.ndarray, period_frames: float) -> float:
    n = len(env)
    grid = np.arange(n, dtype=np.float64)
    best_v, best_phi = -1.0, 0.0
    ks = np.arange(0, int(n / period_frames) + 2)
    for phi in np.arange(0.0, period_frames, 0.25):
        idx = phi + ks * period_frames
        idx = idx[idx < n - 1]
        if idx.size == 0:
            continue
        v = float(np.interp(idx, grid, env).sum())
        if v > best_v:
            best_v, best_phi = v, float(phi)
    return best_phi


def beat_grid(env: np.ndarray, bpm: float, duration: float):
    period_frames = 60.0 * FPS_ENV / bpm
    # STFT 前视补偿：1024 长窗 / 256 hop 使频谱通量峰比真实拍点早约
    # (N_FFT//HOP - 1) 帧。不补偿会把相位锁到「提前一拍」的等效相位上。
    comp = N_FFT // HOP - 1
    phi = (best_phase(env, period_frames) + comp) % period_frames
    # 规范到 [-T/2, T/2)，消除取模造成的「首拍落在 0 还是落在 1 拍后」歧义
    if phi > period_frames / 2.0:
        phi -= period_frames
    beats = []
    k = -2
    while k < 50000:
        t = (phi + k * period_frames) / FPS_ENV
        if t > duration + 1e-6:
            break
        if t >= -0.01:
            beats.append(round(max(0.0, float(t)), 4))
        k += 1

    # 4/4 小节强拍：4 个候选相位里选平均起音最强者
    grid = np.arange(len(env), dtype=np.float64)
    scores = []
    for off in range(4):
        idx = np.array([b * FPS_ENV for b in beats[off::4]], dtype=np.float64)
        idx = idx[idx < len(env) - 1]
        scores.append(float(np.interp(idx, grid, env).mean()) if idx.size else 0.0)
    off = int(np.argmax(scores))
    bars = beats[off::4]
    return beats, bars, round(4 * 60.0 / bpm, 6)


# --------------------------------------------------------------------------
# 能量曲线 / Drop / 静谧段
# --------------------------------------------------------------------------
def rms_curve(x: np.ndarray, sr: int = SR, win: float = RMS_WIN,
              hop: float = RMS_HOP):
    w, h = int(round(win * sr)), int(round(hop * sr))
    if len(x) < w:
        x = np.pad(x, (0, w - len(x) + 1))
    c = np.cumsum(np.concatenate([[0.0], x.astype(np.float64) ** 2]))
    starts = np.arange(0, len(x) - w + 1, h)
    ms = (c[starts + w] - c[starts]) / w
    rms = np.sqrt(np.maximum(ms, 1e-20))
    db = 20.0 * np.log10(rms + 1e-12)
    t = starts / sr + win / 2
    return t, db, rms


def rms_profile_1s(t, rms, duration):
    prof = []
    for s in range(int(np.ceil(duration))):
        m = (t >= s) & (t < s + 1)
        if m.any():
            v = 20.0 * np.log10(float(rms[m].mean()) + 1e-12)
        else:
            v = -120.0
        prof.append([s, round(float(v), 2)])
    return prof


def detect_drops(t, db, rms, beats, top: int = 3):
    """Top-N 高潮重进点：能量由低谷骤升幅度最大者（对齐到最近拍点）。

    两处稳健化（真实 184.6s 曲目实测所得）：
      1. 跳过片头 DROP_HEAD_SKIP_SEC：曲子「起始进入」之前没有低谷段落，
         不算「重进」，否则会把 1.3s 的开头误判成最强 Drop；
      2. baseline 加地板（峰值的一定比例），避免片头静音分母趋零把
         rise_db 放大成 90 dB 级数值伪影。
    """
    hop_sec = float(t[1] - t[0]) if len(t) > 1 else RMS_HOP
    k = max(1, int(round(0.5 / hop_sec)))
    ker = np.ones(k, dtype=np.float64) / k
    sm = np.convolve(rms, ker, mode="same")
    shift = max(1, int(round(1.5 / hop_sec)))
    baseline = np.empty_like(sm)
    baseline[:shift] = sm[0]
    baseline[shift:] = sm[:-shift]

    rise = np.convolve(sm - baseline, ker, mode="same")  # 线性 rise 定峰位置（绝对能量骤升）

    floor = max(1e-9, DROP_BASELINE_FLOOR_RATIO * float(sm.max()))
    base_f = np.maximum(baseline, floor)
    rise_db = 20.0 * np.log10((sm + floor) / (base_f + floor))

    thr = max(1e-6, 0.06 * float(sm.max()))
    cands = []
    for i in range(1, len(rise) - 1):
        if t[i] < DROP_HEAD_SKIP_SEC:
            continue
        if (rise[i] > rise[i - 1] and rise[i] >= rise[i + 1]
                and rise[i] > thr):
            # 排序分用带地板的 rise_db（描述用），峰位置由线性 rise 决定
            cands.append((float(rise_db[i]), i))
    cands.sort(key=lambda z: -z[0])

    picked = []
    for s, i in cands:
        if all(abs(t[i] - t[j]) >= 2.0 for _, j in picked):
            picked.append((s, i))
        if len(picked) >= top:
            break

    drops = []
    for _, i in picked:
        raw_t = float(t[i])
        tt = min(beats, key=lambda b: abs(b - raw_t)) if beats else raw_t
        drops.append({
            "t": round(float(tt), 3),
            "rise_db": round(float(rise_db[i]), 2),
            "energy_db": round(float(db[i]), 2),
            "source_t": round(raw_t, 3),
            "aligned_to_beat": bool(beats),
        })
    drops.sort(key=lambda d: -d["rise_db"])
    return drops


def detect_quiet(t, db, rms):
    valid = db[db > -110]
    if valid.size == 0:
        return []
    thr = float(np.percentile(valid, 30))
    q = db < thr
    spans, i = [], 0
    while i < len(q):
        if q[i]:
            j = i
            while j + 1 < len(q) and q[j + 1]:
                j += 1
            start, end = float(t[i]), float(t[j]) + RMS_HOP
            if end - start >= 0.75:
                m = (t >= start) & (t <= end)
                mean_db = (20.0 * np.log10(float(rms[m].mean()) + 1e-12)
                           if m.any() else -120.0)
                spans.append({"start": round(start, 3), "end": round(end, 3),
                              "mean_db": round(float(mean_db), 2)})
            i = j + 1
        else:
            i += 1
    return spans


# --------------------------------------------------------------------------
# 主分析流程
# --------------------------------------------------------------------------
def analyze(audio_path, out_json=None, ffmpeg=None, print_summary=True) -> dict:
    ff, probe, ver = locate_tools(ffmpeg)
    ap = Path(audio_path).resolve()
    if not ap.exists():
        raise SystemExit(f"[BGM] 音频不存在：{ap}")
    if ap.suffix.lower() not in SUPPORTED_EXT:
        print(f"[warn] 非标准扩展名 {ap.suffix}，仍尝试解码。", file=sys.stderr)

    x = decode_f32(ff, ap, sr=SR, channels=1)
    duration = len(x) / SR
    if duration < 1.0:
        raise SystemExit(f"[BGM] 音频过短（{duration:.2f}s），无法测拍。")

    mag = stft_mag(x)
    env = onset_envelope(mag)
    ac = autocorr(env)
    bpm, bpm_score, bpm_note = estimate_bpm(ac)
    beats, bars, bar_sec = beat_grid(env, bpm, duration)

    t, db, rms = rms_curve(x)
    drops = detect_drops(t, db, rms, beats)
    quiet = detect_quiet(t, db, rms)
    profile = rms_profile_1s(t, rms, duration)

    out = Path(out_json).resolve() if out_json else ap.with_suffix(".beats.json")
    result = {
        "file": str(ap),
        "file_name": ap.name,
        "source_sha256": sha256_file(ap),
        "duration_sec": round(duration, 3),
        "bpm": bpm,
        "bpm_score": bpm_score,
        "bpm_note": bpm_note,
        "beat_sec": round(60.0 / bpm, 6),
        "bar_sec": bar_sec,
        "beats_per_bar": 4,
        "bar_times": bars,
        "beat_times": beats,
        "drops": drops,
        "quiet_spans": quiet,
        "rms_profile_1s": profile,
        "analysis": {
            "sample_rate": SR,
            "n_fft": N_FFT,
            "hop": HOP,
            "onset": "log-compressed spectral flux + FFT autocorrelation",
            "bpm_preferred_range": list(BPM_PREF),
            "bpm_fallback_range": list(BPM_ALL),
            "rms_win_sec": RMS_WIN,
            "rms_hop_sec": RMS_HOP,
            "drop_head_skip_sec": DROP_HEAD_SKIP_SEC,
            "drop_baseline_floor_ratio": DROP_BASELINE_FLOOR_RATIO,
            "ffmpeg": ver,
            "tool": "tools/bgm_analyze.py",
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=out.parent,mode="w",encoding="utf-8",delete=False) as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
    os.replace(f.name,out)

    if print_summary:
        _print_summary(result, out, ver)
    return result


def _print_summary(d: dict, out: Path, ver: str):
    line = "=" * 74
    print(line)
    print(f" BGM 节拍速查 · {d['file_name']}")
    print("-" * 74)
    print(f" 文件        : {d['file']}")
    print(f" 时长        : {d['duration_sec']:.2f} s")
    print(f" FFmpeg      : {ver.splitlines()[0] if ver else '9.0.2'}")
    print(f" 主 BPM      : {d['bpm']:.2f}   ({d['bpm_note']})")
    print(f" 每拍        : {d['beat_sec']:.3f} s   |   每小节(4/4) : {d['bar_sec']:.3f} s")
    print(f" 拍点 / 小节 : {len(d['beat_times'])} 拍 / {len(d['bar_times'])} 小节")
    print("-" * 74)
    bars = d["bar_times"][:12]
    print(" 小节强拍 bar_times（前 12 个）:")
    print("   " + "  ".join(f"#{i} {v:.3f}" for i, v in enumerate(bars)))
    print(" 拍点 beat_times（前 16 个）:")
    print("   " + "  ".join(f"{v:.3f}" for v in d["beat_times"][:16]))
    print("-" * 74)
    print(" 高潮 Drop（Top 3，幅度降序；--bgm-drop-index 0 即最强）:")
    if d["drops"]:
        for i, dr in enumerate(d["drops"]):
            print(f"   #{i}  t={dr['t']:.3f}s   Δ{dr['rise_db']:+.1f} dB   "
                  f"能量 {dr['energy_db']:.1f} dB   (原始 {dr['source_t']:.3f})")
    else:
        print("   （未检出显著能量骤升）")
    print(" 静谧段 quiet_spans:")
    if d["quiet_spans"]:
        for q in d["quiet_spans"]:
            print(f"   [{q['start']:.3f} – {q['end']:.3f}]  mean {q['mean_db']:.1f} dB")
    else:
        print("   （无）")
    print("-" * 74)
    print(" 分镜用法：硬切/反转对齐 bar_times；最高潮对齐 drops[0].t")
    print(f" 节拍档案：{out.name}   （一次测拍，永久复用）")
    print(line)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(
        description="默认单曲测拍卡点器（纯 numpy + FFmpeg 9.0.2）")
    p.add_argument("audio", nargs="?", default=None,
                   help="音频路径；不传则自动探测 assets/bgm/bgm.*")
    p.add_argument("--out", default=None, help="输出 beats.json 路径（默认同目录 <stem>.beats.json）")
    p.add_argument("--ffmpeg", default=None, help="显式指定 9.0.2 的 ffmpeg.exe")
    a = p.parse_args(argv)

    if a.audio:
        audio = Path(a.audio).resolve()
    else:
        d = default_bgm_dir()
        audio = None
        for ext in DEFAULT_EXT_ORDER:
            c = d / (DEFAULT_STEM + ext)
            if c.exists():
                audio = c
                break
        if audio is None:
            raise SystemExit(
                "[BGM] 未找到默认单曲。请把音频放到：\n"
                f"        {d}\\bgm.m4a"
                "   （自动探测 .m4a -> .mp3 -> .wav -> .flac）\n"
                "        也可直接传参：tools\\bgm_analyze.py <audio_path>"
            )
    analyze(audio, a.out, a.ffmpeg, print_summary=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
