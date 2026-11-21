"""mix_bgm.py — 交付自动混音（卡 Drop + 前段铺底 + 断层自检，视频流零损直通）。

用法（交付阶段 · 单成片）：
  python tools/mix_bgm.py --video out/<中间片>.mp4 \
      --bgm assets/bgm/<track>.m4a \
      --sfx examples/nim_game/src/sfx_mix.wav \
      --output "output/<slug>/<主题>.mp4" \
      --align-climax 122.0 --sfx-out "output/<slug>/src/sfx_only.wav"

用法（阶段 1 快审片 · 带 BGM 合成 30 秒）：
  python tools/mix_bgm.py --video out/<stage1>.mp4 \
      --preview-duration 30 --align-climax 122.0 --output out/<stage1>_bgm.mp4

微音效轨来源（优先级从高到低）：
  1. `--sfx <wav>`：显式指定微音效母带，按输入视频实际时长裁剪/补零对齐；
  2. 输入视频自带音轨：直接从渲染中间片无损提取；
  3. 都没有：按静音基线处理（`--sfx-out` 会同时给出近似静音的 warning）。

不传 --bgm 时自动锁定 assets/bgm/bgm.* 与其 .beats.json；
节拍档案缺失会先自动跑一次 bgm_analyze.py；音频未放入则打印路径并报错退出。

处理链（音频全在 numpy 采样级完成，FFmpeg 只负责一次解码 + 一次封装）：
  1. 精确卡点：offset = align_climax - drops[idx].t，误差 0.000s（≤0.03s）
  2. 正偏移前段铺底（v1.1 新增，根治长片前段无 BGM）：
     offset > 0 时不再把 [0, offset) 留白，而是从同曲里挑一段**整数小节（4/8/16 bars）**
     的最低能量乐段，做等功率交叉淡化循环铺满前段；音量按主高潮段实测 RMS 压低 5 dB
     （可调 4–6 dB），可加温和低通；0.0s 起 0.4s 柔和淡入，末尾 0.30s 交叉淡化
     精准落回主轨第 0 采样（主轨随即进入 Drop）。
  3. 整小节 bar_sec 循环体 + 1.5s 等功率 cos/sin 交叉淡化；片头柔和淡入、
     片尾 --fade-out（默认 2.5s）对数淡出至静音
  4. 反转落点前 0.45s 余弦洼谷（--duck-db），落点顺滑回弹
  5. 原 48kHz 立体声微音效轨 + BGM（-13.5dB）混合 -> FFmpeg alimiter 真峰值
     -1.0 dBFS -> ebur128 实测 LUFS / True Peak（自适应收紧以保证 TP ≤ -1.0 dBTP）
  6. 全片 BGM 断层自检：在 [0.5s, total-2.0s] 内找 >1.5s 的异常空白，写入报告
  7. -c:v copy（绝不重编码画面） + AAC 256k 单成片出片；可选导出轻量 sfx_only.wav
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bgm_common import (  # noqa: E402
    decode_f32, has_audio_stream, locate_tools, probe_duration,
    repo_root, resolve_default_bgm,
)
import bgm_analyze  # noqa: E402  （节拍档案缺失时自动调用）

SR = 48000
FADE_IN_SEC = 0.15
FADE_OUT_SEC = 2.5
LOOP_FADE_SEC = 1.5
DUCK_PRE_SEC = 0.45
DUCK_RAMP_SEC = 0.15
DUCK_RELEASE_SEC = 0.35
TARGET_TP_DBTP = -1.0
LIMIT_START_DBFS = -1.0

# --- 前段铺底（v1.1） -------------------------------------------------------
FILL_FADE_IN_SEC = 0.40        # 0.0s 起的极短柔和淡入
FILL_SEAM_XFADE_SEC = 0.35     # 循环接缝等功率交叉淡化
FILL_JOIN_XFADE_SEC = 0.30     # 铺底尾 → 主轨首采样的交叉淡化
FILL_BELOW_CLIMAX_DB = 5.0     # 相对主高潮段压低 5 dB（规范 4–6 dB）
FILL_LOWPASS_HZ = 2400.0       # 温和低通（0 = 关闭）

# --- 断层自检（v1.1） -------------------------------------------------------
GAP_WINDOW_START_SEC = 0.5
GAP_WINDOW_END_MARGIN_SEC = 2.0
GAP_MAX_SEC = 1.5
GAP_HOP_SEC = 0.05
GAP_WIN_SEC = 0.10


# --------------------------------------------------------------------------
# 节拍档案 / 视频分幕 duck 点
# --------------------------------------------------------------------------
def ensure_beats(bgm: Path, ffmpeg: str) -> tuple[dict, Path]:
    p = bgm.with_suffix(".beats.json")
    if not p.exists():
        print(f"[beats] 节拍档案不存在，自动先跑一次 bgm_analyze.py：{p.name}")
        bgm_analyze.analyze(bgm, out_json=p, ffmpeg=ffmpeg, print_summary=False)
    d = json.loads(p.read_text(encoding="utf-8"))
    if not d.get("bar_times") or not d.get("bpm"):
        raise SystemExit(f"[beats] 节拍档案字段不完整：{p}")
    return d, p


def extract_duck_points(video_beats: Path | None, video: Path):
    """从视频分幕 beats.json 读硬切 / 反转 / duck 标注点（startSec）。"""
    path = video_beats
    if path is None:
        guess = video.with_name("beats.json")
        path = guess if guess.exists() else None
    if path is None:
        return [], None
    path = Path(path).resolve()
    if not path.exists():
        print(f"[duck] --beats 指定的文件不存在：{path}", file=sys.stderr)
        return [], None
    d = json.loads(path.read_text(encoding="utf-8"))
    pts = []
    for b in d.get("beats", []):
        if not isinstance(b, dict):
            continue
        t = b.get("startSec")
        if t is None:
            continue
        if (b.get("duck") is True or b.get("hardCut") is True
                or b.get("duckAt") is True or b.get("isClimax") is True):
            pts.append(float(t))
    for key in ("duck_points", "duckPoints", "duckAt", "hard_cuts", "hardCuts"):
        v = d.get(key)
        if isinstance(v, list):
            for it in v:
                if isinstance(it, (int, float)):
                    pts.append(float(it))
                elif isinstance(it, dict):
                    for k in ("t", "timeSec", "startSec", "at", "sec"):
                        if k in it:
                            pts.append(float(it[k]))
                            break
    for e in d.get("effects", []):
        if isinstance(e, dict) and e.get("duck") is True and "timeSec" in e:
            pts.append(float(e["timeSec"]))
    return sorted({round(p, 3) for p in pts if p >= 0}), path


# --------------------------------------------------------------------------
# 循环体 / BGM 时间轴 / 淡入淡出 / 洼谷包络
# --------------------------------------------------------------------------
def make_loop(x: np.ndarray, bar_sec: float, fade_sec: float = LOOP_FADE_SEC):
    """按整小节边界做 1.5s 等功率 cos/sin 交叉淡化循环体（严禁生硬截断重头播）。"""
    fade = int(round(fade_sec * SR))
    bar = int(round(bar_sec * SR))
    if bar <= fade:
        bar = 2 * fade
    n = len(x)
    bars = max(1, (n - fade) // bar)
    body = bars * bar                      # 循环长度 = 整数个小节
    if n < body + fade:
        reps = int(math.ceil((body + fade) / max(1, n)))
        x = np.tile(x, (reps, 1))[:body + fade]
    loop = x[:body].copy()
    tail = x[body - fade:body]
    head = x[0:fade]
    u = np.linspace(0.0, 1.0, fade, endpoint=False, dtype=np.float64)
    ca = np.cos(0.5 * np.pi * u)[:, None].astype(np.float32)
    cb = np.sin(0.5 * np.pi * u)[:, None].astype(np.float32)
    loop[body - fade:body] = (tail * ca + head * cb).astype(np.float32)
    return loop, bars


def build_bgm_track(loop: np.ndarray, v_samples: int, off_samples: int):
    """video_t = bgm_t + offset；负偏移 = 预卷跳过前奏，正偏移 = 前奏静音后切入。"""
    L = len(loop)
    out = np.zeros((v_samples, 2), dtype=np.float32)
    if off_samples >= 0:
        start = min(off_samples, v_samples)
        n = v_samples - start
        if n > 0:
            idx = np.arange(n, dtype=np.int64) % L
            out[start:] = loop[idx]
    else:
        skip = -off_samples
        idx = (np.arange(v_samples, dtype=np.int64) + skip) % L
        out[:] = loop[idx]
    return out


def rms_dbfs(x: np.ndarray) -> float:
    if len(x) == 0:
        return -120.0
    r = float(np.sqrt(np.mean(np.square(x.astype(np.float64)))))
    return 20.0 * math.log10(max(r, 1e-9))


def soft_lowpass_fft(x: np.ndarray, sr: int, cutoff: float, order: int = 2) -> np.ndarray:
    """零相位 Butterworth 幅频响应低通（FFT 实现，避免引入 scipy 依赖）。

    作用对象是「已截好的整数小节乐段」，之后会被循环平铺，因此 FFT 的循环卷积
    边界与它的实际使用方式一致，不会产生额外爆音。
    """
    if cutoff <= 0 or cutoff >= sr * 0.45:
        return x
    n = len(x)
    spec = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    h = 1.0 / np.sqrt(1.0 + (f / float(cutoff)) ** (2 * order))
    return np.fft.irfft(spec * h[:, None], n=n, axis=0).astype(np.float32)


def pick_fill_segment(loop: np.ndarray, bar_samples: int, target_samples: int,
                      prefer_bars: int = 0, drops=()) -> dict:
    """从同曲里挑一段整数小节的「最低能量」乐段，用于前段铺底。

    约束（按优先级从严到宽逐级放宽，任何放宽都会在 stderr 打印 warning）：
      - 长度必须是整数小节；默认按前段长度自适应：≥34s 用 16 小节、≥17s 用 8 小节、
        否则 4 小节（越长循环次数越少，长片前段不会听出机械重复）；
      - 候选小节数按 [16, 8, 4, 2] 依次降档，并夹紧到「连续可用小节最长段」
        `max_usable_run`，避免短曲（如 35s 测试曲）在 offset 很大时直接退出；
      - 必须完整位于 loop 内；
      - 严格档排除：曲尾 8 小节（淡出/尾奏，循环起来像在渐弱）、Drop 前后各 2 小节
        （上升段/落点，铺底会抢高潮）、能量低于中位数 10dB 的近静音小节；
      - 以「每小节 RMS」做滑窗，取能量最低的合规窗口。
    """
    total_bars = len(loop) // bar_samples
    if total_bars < 2:
        raise SystemExit(
            f"[fill] 曲目可用小节数不足（{total_bars} < 2），无法铺底；"
            "请改用更长的配乐，或调小 --align-climax。")

    bar_sec = bar_samples / SR
    need_sec = target_samples / SR
    if prefer_bars:
        ladder = [max(1, int(prefer_bars))]
    elif need_sec >= 34.0:
        ladder = [16, 8, 4, 2]
    elif need_sec >= 17.0:
        ladder = [8, 4, 2]
    else:
        ladder = [4, 2]

    # 每小节 RMS
    bar_db = np.asarray(
        [rms_dbfs(loop[i * bar_samples:(i + 1) * bar_samples]) for i in range(total_bars)],
        dtype=np.float64)
    med = float(np.median(bar_db))

    def build_mask(tail_bars: int, drop_pad: int, silent_filter: bool) -> np.ndarray:
        bad = np.zeros(total_bars, dtype=bool)
        if tail_bars > 0:
            bad[max(0, total_bars - tail_bars):] = True
        for d in drops or ():
            bi = int(round(float(d) / bar_sec))
            bad[max(0, bi - drop_pad):min(total_bars, bi + drop_pad + 1)] = True
        if silent_filter:
            bad |= (bar_db < med - 10.0)
        return bad

    def longest_run(mask: np.ndarray) -> int:
        best = run = 0
        for flag in mask:
            run = 0 if flag else run + 1
            if run > best:
                best = run
        return best

    def search(mask: np.ndarray, bars: int):
        best = None
        for i in range(total_bars - bars + 1):
            if mask[i:i + bars].any():
                continue
            score = float(bar_db[i:i + bars].mean())
            if best is None or score < best["score"]:
                best = {"bars": bars, "start_bar": i, "score": score}
        return best

    # 从严到宽：严格 → 取消近静音过滤 → 收窄曲尾/Drop 保护 → 任意窗口
    strategies = (
        ("strict", build_mask(8, 2, True)),
        ("no_silent_filter", build_mask(8, 2, False)),
        ("relaxed_tail_drop", build_mask(min(8, max(1, total_bars // 4)), 1, False)),
        ("any_window", np.zeros(total_bars, dtype=bool)),
    )

    best = None
    used_strategy = ""
    usable = 0
    for name, mask in strategies:
        usable = longest_run(mask)
        for bars in ladder:
            if bars > usable:
                continue
            found = search(mask, bars)
            if found is not None:
                best = found
                used_strategy = name
                break
        if best is not None:
            break

    if best is None:
        raise SystemExit(
            f"[fill] 未找到可用铺底乐段（共 {total_bars} 小节，最长连续可用 {usable}）。")

    degraded = used_strategy != "strict" or best["bars"] != ladder[0]
    if degraded:
        print(
            f"[fill][warn] 铺底降档：策略 {used_strategy} / {best['bars']} 小节"
            f"（曲目共 {total_bars} 小节，最长连续可用 {usable}；"
            f"目标 {need_sec:.1f}s 前段）。保护边距已按可用长度放宽。",
            file=sys.stderr,
        )

    start = best["start_bar"] * bar_samples
    seg = loop[start:start + best["bars"] * bar_samples].copy()
    return {
        "segment": seg,
        "bars": best["bars"],
        "start_sec": start / SR,
        "bar_rms_dbfs": round(best["score"], 2),
        "target_samples": target_samples,
        "max_usable_run": usable,
        "strategy": used_strategy,
        "degraded": degraded,
    }


def make_segment_loop(seg: np.ndarray, xfade_sec: float = FILL_SEAM_XFADE_SEC) -> np.ndarray:
    """把整数小节乐段的尾与头做等功率交叉淡化，得到可无缝循环的铺底块。"""
    fade = min(int(round(xfade_sec * SR)), len(seg) // 4)
    if fade <= 0:
        return seg
    out = seg.copy()
    tail = seg[-fade:]
    head = seg[:fade]
    u = np.linspace(0.0, 1.0, fade, endpoint=False, dtype=np.float64)
    ca = np.cos(0.5 * np.pi * u)[:, None].astype(np.float32)
    cb = np.sin(0.5 * np.pi * u)[:, None].astype(np.float32)
    out[-fade:] = (tail * ca + head * cb).astype(np.float32)
    return out


def fill_preroll(track: np.ndarray, loop: np.ndarray, offset_samples: int,
                 bar_samples: int, climax_rms_db: float | None,
                 fill_bars: int = 0, lowpass_hz: float = FILL_LOWPASS_HZ,
                 below_db: float = FILL_BELOW_CLIMAX_DB, drops=()) -> dict | None:
    """把 [0, offset) 用同曲低能量乐段铺满，并交叉淡化进主轨第 0 采样。

    返回铺底参数摘要（写进 bgm_mix_report.json）；offset <= 0 时返回 None。
    """
    if offset_samples <= 0:
        return None

    pick = pick_fill_segment(loop, bar_samples, offset_samples,
                             prefer_bars=fill_bars, drops=drops)
    seg = make_segment_loop(pick["segment"])
    if lowpass_hz and lowpass_hz > 0:
        seg = soft_lowpass_fft(seg, SR, lowpass_hz)

    # 平铺铺满前段（快审片只混前 N 秒时，前段可能整段都是铺底）
    need = min(offset_samples, len(track))
    reps = int(math.ceil((need + int(FILL_JOIN_XFADE_SEC * SR)) / len(seg)))
    tiled = np.tile(seg, (reps, 1)).astype(np.float32)
    block = tiled[:need]

    # 增益：按主高潮段实测 RMS 压低 5 dB（规范区间 4–6 dB）。
    # 高潮段电平由调用方在**原曲 loop** 的 Drop 附近测得，与预览时长无关，
    # 因此 --preview-duration 截短时电平基准依然正确。
    climax_rms = float(climax_rms_db) if climax_rms_db is not None else -12.0
    fill_rms = rms_dbfs(block)
    gain_db = float(np.clip(climax_rms - fill_rms - below_db, -24.0, 6.0))
    block *= float(10.0 ** (gain_db / 20.0))

    # 0.0s 起 0.4s 柔和淡入
    fi = min(int(round(FILL_FADE_IN_SEC * SR)), len(block))
    if fi > 0:
        u = np.linspace(0.0, 1.0, fi, endpoint=False, dtype=np.float64)
        block[:fi] *= (0.5 - 0.5 * np.cos(np.pi * u))[:, None].astype(np.float32)

    track[:need] = block

    # 铺底尾 → 主轨首采样：用「铺底的下一个循环续段」与主轨首段做等功率交叉淡化。
    # 主轨内容不位移（Drop 仍精准落在 align_climax），只是在其最前面 0.30s 内
    # 把铺底的能量平滑让渡出去，避免硬切爆音。
    xf = min(int(round(FILL_JOIN_XFADE_SEC * SR)), len(track) - need)
    if xf > 0:
        cont = tiled[need:need + xf] * float(10.0 ** (gain_db / 20.0))
        u = np.linspace(0.0, 1.0, xf, endpoint=False, dtype=np.float64)
        cf = np.cos(0.5 * np.pi * u)[:, None].astype(np.float32)   # 1 -> 0
        cm = np.sin(0.5 * np.pi * u)[:, None].astype(np.float32)   # 0 -> 1
        head = track[need:need + xf].copy()
        track[need:need + xf] = head * cm + cont * cf

    return {
        "enabled": True,
        "reason": "align_climax 晚于曲目 Drop，正偏移前段禁止留白",
        "fill_bars": pick["bars"],
        "degraded": pick.get("degraded", False),
        "strategy": pick.get("strategy"),
        "max_usable_run": pick.get("max_usable_run"),
        "segment_start_sec": round(pick["start_sec"], 3),
        "segment_rms_dbfs": pick["bar_rms_dbfs"],
        "climax_rms_dbfs": round(climax_rms, 2),
        "gain_db": round(gain_db, 2),
        "below_climax_db": below_db,
        "lowpass_hz": lowpass_hz if lowpass_hz and lowpass_hz > 0 else None,
        "fade_in_sec": FILL_FADE_IN_SEC,
        "seam_xfade_sec": FILL_SEAM_XFADE_SEC,
        "join_xfade_sec": FILL_JOIN_XFADE_SEC,
        "filled_sec": round(need / SR, 3),
        "loop_length_sec": round(len(seg) / SR, 3),
        "repeats": reps,
    }


def apply_edge_fades(track: np.ndarray, v_samples: int, fade_out_sec: float = FADE_OUT_SEC,
                     fade_in_sec: float = FADE_IN_SEC):
    fi = min(int(round(fade_in_sec * SR)), v_samples)
    fo = min(int(round(fade_out_sec * SR)), v_samples)
    if fi > 0:
        u = np.linspace(0.0, 1.0, fi, endpoint=False, dtype=np.float64)
        track[:fi] *= (0.5 - 0.5 * np.cos(np.pi * u))[:, None].astype(np.float32)
    if fo > 0 and v_samples > fo:
        u = np.linspace(0.0, 1.0, fo, dtype=np.float64)
        # 对数（dB 线性）淡出 + 余弦收尾，末端严格归零
        g = (10.0 ** (-48.0 * u / 20.0)) * (0.5 + 0.5 * np.cos(np.pi * u))
        g[-1] = 0.0
        track[v_samples - fo:v_samples] *= g[:, None].astype(np.float32)


def duck_envelope(v_samples: int, points, duck_db: float):
    """采样级余弦洼谷：反转点前 0.45s 压低，落点顺滑回弹。"""
    g = np.ones(v_samples, dtype=np.float32)
    if not points:
        return g
    dg = float(10.0 ** (duck_db / 20.0))
    pre = int(round(DUCK_PRE_SEC * SR))
    ramp = int(round(DUCK_RAMP_SEC * SR))
    rel = int(round(DUCK_RELEASE_SEC * SR))
    for t in points:
        c = int(round(float(t) * SR))
        s = c - pre
        if c < 0 or s >= v_samples:
            continue
        a, b = max(0, s), min(v_samples, s + ramp)
        if b > a:
            u = np.clip((np.arange(a, b) - s) / ramp, 0.0, 1.0)
            w = 0.5 + 0.5 * np.cos(np.pi * u)          # 1 -> 0
            g[a:b] = np.minimum(g[a:b], (1.0 - (1.0 - dg) * (1.0 - w)).astype(np.float32))
        a, b = max(0, s + ramp), min(v_samples, c)
        if b > a:
            g[a:b] = np.minimum(g[a:b], np.float32(dg))
        a, b = max(0, c), min(v_samples, c + rel)
        if b > a:
            u = np.clip((np.arange(a, b) - c) / rel, 0.0, 1.0)
            w = 0.5 - 0.5 * np.cos(np.pi * u)          # 0 -> 1
            g[a:b] = np.minimum(g[a:b], (dg + (1.0 - dg) * w).astype(np.float32))
    return g


def fit_len(x: np.ndarray, v_samples: int):
    if len(x) >= v_samples:
        return x[:v_samples].copy()
    return np.vstack([x, np.zeros((v_samples - len(x), 2), dtype=np.float32)])


# --------------------------------------------------------------------------
# BGM 断层自检
# --------------------------------------------------------------------------
def detect_bgm_gaps(track: np.ndarray, gain_db: float, total_sec: float,
                    start_sec: float = GAP_WINDOW_START_SEC,
                    end_margin: float = GAP_WINDOW_END_MARGIN_SEC,
                    max_gap: float = GAP_MAX_SEC) -> dict:
    """在 [start, total-end_margin] 内找 > max_gap 的异常空白（低于铺底阈值）。

    阈值取「该区间 BGM 短时 RMS 中位数 − 25 dB」，并夹在 [-60, -32] dBFS；
    衡量的是「相对铺底的异常掉底」，不会把整体偏轻的段落误判成断层。
    高潮前刻意做的 0.4–0.6s 动态洼谷远短于 1.5s，不会触发。
    """
    mono = track.mean(axis=1) * float(10.0 ** (gain_db / 20.0))
    hop = max(1, int(round(GAP_HOP_SEC * SR)))
    win = max(hop, int(round(GAP_WIN_SEC * SR)))
    n = len(mono)
    lo = int(round(start_sec * SR))
    hi = int(round((total_sec - end_margin) * SR))
    lo, hi = max(0, lo), min(n, hi)
    if hi - lo < win * 2:
        return {"pass": False, "reason": "可检测区间过短",
                "window": [start_sec, round(total_sec - end_margin, 2)],
                "gaps": [], "longestGapSec": None, "thresholdDbfs": None,
                "bedMedianDbfs": None}

    idx = np.arange(lo, hi - win + 1, hop)
    csum = np.concatenate([[0.0], np.cumsum(np.square(mono.astype(np.float64)))])
    energy = (csum[idx + win] - csum[idx]) / win
    db = 10.0 * np.log10(np.maximum(energy, 1e-12))
    median = float(np.median(db))
    threshold = float(np.clip(median - 25.0, -60.0, -32.0))

    below = db < threshold
    gaps = []
    run_start = None
    for i, flag in enumerate(below):
        t = (idx[i] + win * 0.5) / SR
        if flag and run_start is None:
            run_start = t
        elif not flag and run_start is not None:
            dur = t - run_start
            if dur > max_gap:
                gaps.append({"startSec": round(run_start, 3), "endSec": round(t, 3),
                             "durationSec": round(dur, 3)})
            run_start = None
    if run_start is not None:
        t_end = (idx[-1] + win) / SR
        dur = t_end - run_start
        if dur > max_gap:
            gaps.append({"startSec": round(run_start, 3), "endSec": round(t_end, 3),
                         "durationSec": round(dur, 3)})

    longest = max((g["durationSec"] for g in gaps), default=0.0)
    bed_ok = median > -55.0
    return {
        "pass": bool(len(gaps) == 0 and bed_ok),
        "window": [round(start_sec, 3), round(total_sec - end_margin, 3)],
        "thresholdDbfs": round(threshold, 2),
        "bedMedianDbfs": round(median, 2),
        "bedPresent": bed_ok,
        "maxAllowedGapSec": max_gap,
        "longestGapSec": round(longest, 3),
        "gapCount": len(gaps),
        "gaps": gaps[:20],
        "method": "50ms hop / 100ms RMS；阈值 = 区间中位数 − 25dB（夹 -60~-32 dBFS）",
    }


# --------------------------------------------------------------------------
# 轻量纯音效母带导出
# --------------------------------------------------------------------------
def resample_linear(x: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if dst_sr == src_sr or len(x) == 0:
        return x
    n_out = int(round(len(x) * dst_sr / src_sr))
    t = np.arange(n_out, dtype=np.float64) * (src_sr / dst_sr)
    i0 = np.floor(t).astype(np.int64)
    i1 = np.minimum(i0 + 1, len(x) - 1)
    w = (t - i0).astype(np.float32)
    if x.ndim == 2:
        w = w[:, None]
    return (x[i0] * (1.0 - w) + x[i1] * w).astype(np.float32)


def write_wav_16(path: Path, x: np.ndarray, sr: int, channels: int):
    """16-bit PCM WAV（默认 32kHz 单声道 ≈ 6–8 MB/120s，轻量母带留底用）。"""
    y = resample_linear(x, SR, sr)
    if channels == 1 and y.ndim == 2:
        y = y.mean(axis=1)
    y = np.clip(y, -1.0, 1.0)
    pcm = (y * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# --------------------------------------------------------------------------
# FFmpeg 封装 + ebur128 实测
# --------------------------------------------------------------------------
def mux(ffmpeg: str, video: Path, raw_pcm: Path, out: Path, limit_dbfs: float,
        preview_duration: float | None = None):
    limit = 10.0 ** (limit_dbfs / 20.0)
    cmd = [ffmpeg, "-y", "-v", "error",
           "-i", str(video),
           "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(raw_pcm),
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy",
           "-af", f"alimiter=limit={limit:.9f}:level=false:attack=5:release=50",
           "-c:a", "aac", "-b:a", "256k", "-ar", str(SR), "-ac", "2"]
    if preview_duration is not None and preview_duration > 0:
        cmd += ["-t", f"{preview_duration:.3f}"]
    cmd += ["-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise SystemExit(f"[FFmpeg] 封装失败（退出码 {r.returncode}）：\n"
                         f"{(r.stderr or '')[-1200:]}")


def measure_loudness(ffmpeg: str, out: Path):
    """ebur128 实测集成响度 LUFS 与 True Peak dBTP；解析失败回退 loudnorm JSON。"""
    r = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(out),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, timeout=600)
    txt = (r.stderr or "") + (r.stdout or "")
    idx = txt.rfind("Summary:")
    tail = txt[idx:] if idx >= 0 else txt
    i_vals = re.findall(r"I:\s+(-?[\d.]+)\s+LUFS", tail)
    p_vals = re.findall(r"Peak:\s+(-?[\d.]+)\s+dBFS", tail)
    if i_vals and p_vals:
        return float(i_vals[-1]), float(p_vals[-1]), "ebur128"

    r2 = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(out),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=600)
    m = re.search(r"\{\s*\"input_i\".*?\}", (r2.stderr or ""), re.S)
    if m:
        d = json.loads(m.group(0))
        return float(d["input_i"]), float(d["input_tp"]), "loudnorm(fallback)"
    raise SystemExit("[ebur128] 无法解析响度/真峰值测量输出。")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(
        description="交付自动混音（单成片 + 前段铺底 + 断层自检）")
    p.add_argument("--video", required=True, help="已验收的渲染中间片 / 阶段 1 快审片")
    p.add_argument("--bgm", default=None, help="配乐路径；不传则自动锁定 assets/bgm/bgm.*")
    p.add_argument("--beats", default=None, help="视频分幕 beats.json（读 hardCut/duck 反转点）")
    p.add_argument("--align-climax", type=float, default=None, help="画面高潮秒数，如 122.0")
    p.add_argument("--bgm-drop-index", type=int, default=0,
                   help="取第几个 Drop（默认 0；若 0 太早可试 1）")
    p.add_argument("--bgm-offset", type=float, default=None,
                   help="手动指定 BGM 起始偏移秒数（显式指定优先）")
    p.add_argument("--fill-bars", type=int, default=0,
                   help="前段铺底乐段小节数（4/8/16，默认 0=自动挑 8→4→16）")
    p.add_argument("--preroll-bars", type=int, default=None,
                   help="[兼容旧参] 等同 --fill-bars")
    p.add_argument("--fill-lowpass", type=float, default=FILL_LOWPASS_HZ,
                   help=f"前段铺底温和低通 Hz（默认 {FILL_LOWPASS_HZ:.0f}；0=关闭）")
    p.add_argument("--fill-below-db", type=float, default=FILL_BELOW_CLIMAX_DB,
                   help="铺底相对主高潮段压低 dB（默认 5，规范区间 4–6）")
    p.add_argument("--bgm-gain", type=float, default=-13.5, help="BGM 相对增益 dB（默认 -13.5）")
    p.add_argument("--duck-db", type=float, default=-4.0, help="洼谷压低 dB（默认 -4.0）")
    p.add_argument("--duck-at", default=None, help="手动反转点秒数，逗号分隔，优先于 --beats")
    p.add_argument("--fade-out", type=float, default=2.5, help="片尾对数淡出秒数（默认 2.5）")
    p.add_argument("--output", "--out", dest="out", default=None,
                   help="输出 mp4（交付阶段直接写 <主题>.mp4）")
    p.add_argument("--preview-duration", type=float, default=None,
                   help="只混前 N 秒（阶段 1 快审片带 BGM）")
    p.add_argument("--sfx", default=None,
                   help="微音效母带 WAV（如 examples/nim_game/src/sfx_mix.wav）；"
                        "传入则按视频时长裁剪对齐后混入，不再依赖输入视频自带音轨")
    p.add_argument("--sfx-out", default=None,
                   help="导出轻量纯微音效母带（如 src/sfx_only.wav）")
    p.add_argument("--sfx-sr", type=int, default=32000, help="sfx_only.wav 采样率（默认 32000）")
    p.add_argument("--sfx-channels", type=int, choices=(1, 2), default=1,
                   help="sfx_only.wav 声道数（默认 1）")
    p.add_argument("--ffmpeg", default=None, help="显式指定 9.0.2 的 ffmpeg.exe")
    a = p.parse_args(argv)

    if a.preroll_bars is not None and a.fill_bars == 0:
        a.fill_bars = int(a.preroll_bars)

    ff, probe, ver = locate_tools(a.ffmpeg)
    video = Path(a.video).resolve()
    if not video.exists():
        raise SystemExit(f"[video] 渲染中间片不存在：{video}")

    bgm = resolve_default_bgm(a.bgm)
    beats_data, beats_path = ensure_beats(bgm, ff)
    bpm = float(beats_data["bpm"])
    bar_sec = float(beats_data.get("bar_sec") or 4 * 60.0 / bpm)
    drops = beats_data.get("drops", [])

    # --- 输出路径 ---
    if a.out:
        out = Path(a.out).resolve()
        if out.suffix.lower() != ".mp4":
            out = out.with_suffix(".mp4")
    else:
        stem = video.stem
        for suffix in ("_cinema_clean", "_with_bgm", "_silent_sfx"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        if a.preview_duration:
            stem += "_preview"
        out = video.with_name(stem + "_with_bgm.mp4")
    if out == video:
        raise SystemExit("[out] 输出路径与输入相同，已拒绝（保留源片）。")
    out.parent.mkdir(parents=True, exist_ok=True)

    # --- 1. 高潮卡点偏移 ---
    drop_t, aligned, offset, climax_err = None, None, 0.0, None
    if a.bgm_offset is not None:
        offset = float(a.bgm_offset)
        aligned = a.align_climax
    elif a.align_climax is not None:
        if not drops:
            raise SystemExit("[align-climax] 节拍档案里没有 drops，无法自动卡点。")
        i = a.bgm_drop_index
        if i < 0 or i >= len(drops):
            raise SystemExit(f"[align-climax] --bgm-drop-index {i} 越界（共 {len(drops)} 个 Drop）。")
        drop_t = float(drops[i]["t"])
        aligned = float(a.align_climax)
        offset = aligned - drop_t
        climax_err = abs((drop_t + offset) - aligned)
        if climax_err > 0.03:
            raise SystemExit(f"[align-climax] 卡点误差 {climax_err:.4f}s 超过 0.03s。")

    v_dur = probe_duration(probe, str(video)) or probe_duration(probe, str(video), "v:0")
    if v_dur <= 0:
        raise SystemExit(f"[ffprobe] 无法读取视频时长：{video}")
    if a.preview_duration and a.preview_duration > 0:
        v_dur = min(v_dur, float(a.preview_duration))
    v_samples = int(round(v_dur * SR))

    # --- 2. 解码双轨 ---
    bgm_pcm = decode_f32(ff, bgm, sr=SR, channels=2)
    sfx_source = None
    if a.sfx:
        sfx_input = Path(a.sfx).resolve()
        if not sfx_input.exists():
            raise SystemExit(f"[sfx] 指定的微音效母带不存在：{sfx_input}")
        # 按输入视频实际时长裁剪/补零对齐，兼容 10s 冒烟片与 Stage 1 快审片
        effects = fit_len(decode_f32(ff, sfx_input, sr=SR, channels=2), v_samples)
        sfx_source = str(sfx_input)
        audio_note = (f"已使用 --sfx 指定的微音效母带，按视频时长 {v_dur:.2f}s 裁剪对齐："
                      f"{sfx_input.name}")
    elif has_audio_stream(probe, str(video)):
        effects = fit_len(decode_f32(ff, video, sr=SR, channels=2), v_samples)
        audio_note = "已从渲染中间片无损提取 48kHz 立体声微音效轨"
    else:
        effects = np.zeros((v_samples, 2), dtype=np.float32)
        audio_note = "渲染中间片无音轨，按静音基线处理"
    sfx_peak = float(np.abs(effects).max()) if len(effects) else 0.0
    sfx_peak_dbfs = round(20.0 * math.log10(sfx_peak + 1e-12), 2)

    loop, loop_bars = make_loop(bgm_pcm, bar_sec)
    bgm_track = build_bgm_track(loop, v_samples, int(round(offset * SR)))

    # --- 3. 正偏移前段铺底（不再留白） ---
    fill_info = None
    if offset > 0.05:
        # 高潮段电平基准：优先在原曲 Drop 前后各 6s 测（song 时间轴，与预览时长无关）；
        # 无 Drop（手动 --bgm-offset）时退回按画面高潮点在视频轴测。
        if drop_t is not None:
            a2 = max(0, int(round((drop_t - 6.0) * SR)))
            b2 = min(len(loop), int(round((drop_t + 6.0) * SR)))
            climax_rms_db = rms_dbfs(loop[a2:b2]) if b2 > a2 else None
        else:
            T = float(aligned) if aligned else 0.0
            a2 = max(0, int(round((T - 6.0) * SR)))
            b2 = min(len(bgm_track), int(round((T + 6.0) * SR)))
            climax_rms_db = rms_dbfs(bgm_track[a2:b2]) if b2 > a2 else None
        fill_info = fill_preroll(
            bgm_track, loop, int(round(offset * SR)), int(round(bar_sec * SR)),
            climax_rms_db, fill_bars=a.fill_bars, lowpass_hz=a.fill_lowpass,
            below_db=a.fill_below_db, drops=[d.get("t") for d in drops if "t" in d])
    elif a.preroll_bars:
        print("[fill] offset <= 0，无需铺底（--preroll-bars 已忽略）。", file=sys.stderr)

    apply_edge_fades(bgm_track, v_samples, a.fade_out,
                     FILL_FADE_IN_SEC if (fill_info and fill_info.get("enabled")) else FADE_IN_SEC)

    # --- 4. 洼谷点 ---
    if a.duck_at is not None:
        duck_points = sorted({round(float(v), 3) for v in a.duck_at.split(",") if v.strip()})
        duck_src = "--duck-at 手动指定"
    else:
        duck_points, bp = extract_duck_points(
            Path(a.beats) if a.beats else None, video)
        duck_src = f"视频分幕 {bp.name}" if bp else "无（未给 --beats / 无同目录 beats.json）"
    duck_points = [t for t in duck_points if 0 <= t <= v_dur]
    bgm_track *= duck_envelope(v_samples, duck_points, a.duck_db)[:, None]

    # --- 5. 断层自检（混入 SFX 之前测 BGM 本身，避免被音效盖住） ---
    gap_check = detect_bgm_gaps(bgm_track, a.bgm_gain, v_dur)

    # --- 6. 混合 + 限幅 + 实测（自适应收紧以保证 TP ≤ -1.0 dBTP） ---
    mix = effects + bgm_track * float(10.0 ** (a.bgm_gain / 20.0))
    raw_peak_dbfs = 20.0 * math.log10(float(np.abs(mix).max()) + 1e-12)

    # 严禁用 np.clip 硬削波：饱和方波化会让 AAC 重建振铃，实测真峰值反而冲到
    # +2.7 dBFS。改为按当前限幅门限做线性预缩放（波形不变、洼谷比例保留），
    # 并预留 1.0 dB 给 AAC overshoot；末级仍由 alimiter 做真峰值限幅。
    ceiling, lufs, tp, method, attempts = LIMIT_START_DBFS, None, None, "", 0
    used_ceiling = LIMIT_START_DBFS
    with tempfile.TemporaryDirectory(prefix="bgm_mix_") as td:
        raw = Path(td) / "mix.f32"
        for attempts in range(1, 6):
            used_ceiling = ceiling
            pre = 10.0 ** ((ceiling - 1.0) / 20.0)
            peak = float(np.abs(mix).max())
            scaled = mix * (pre / peak) if peak > pre else mix
            scaled.astype("<f4").tofile(raw)
            mux(ff, video, raw, out, ceiling, a.preview_duration)
            lufs, tp, method = measure_loudness(ff, out)
            if tp <= TARGET_TP_DBTP + 1e-6:
                break
            ceiling -= 0.4                 # 逐次收紧，直到 ebur128 实测达标
    if tp > TARGET_TP_DBTP + 1e-6:
        raise SystemExit(
            f"[limiter] 自适应限幅 {attempts} 次后真峰值仍为 {tp:.2f} dBTP，"
            "未达 ≤ -1.0 dBTP，已停止交付（请降低 --bgm-gain 后重试）。")

    # --- 7. 轻量纯音效母带 ---
    sfx_path = None
    if a.sfx_out:
        sfx_path = Path(a.sfx_out).resolve()
        write_wav_16(sfx_path, effects, a.sfx_sr, a.sfx_channels)
        print(f"[sfx] 已导出纯微音效母带：{sfx_path} "
              f"({a.sfx_sr}Hz / {a.sfx_channels}ch / 16bit / 峰值 {sfx_peak_dbfs} dBFS)",
              file=sys.stderr)
        if sfx_peak_dbfs < -90.0:
            print("[sfx][warn] 导出的微音效母带近似静音：输入视频无音轨且未指定 --sfx；"
                  "如需成片带微音效，请加 --sfx <sfx_mix.wav>。", file=sys.stderr)

    a_dur = probe_duration(probe, str(out), "a:0")
    report = {
        "schema": "bgm_mix/1.1",
        "bgm_file": str(bgm),
        "bgm_name": bgm.name,
        "beats_file": str(beats_path),
        "license_status": "user_supplied",
        "license_note": "配乐由使用者自备，本工具不授予任何音乐版权；商用请确认授权，并用 sfx_only.wav 换乐重混",
        "bpm": bpm,
        "bar_sec": bar_sec,
        "loop_bars": loop_bars,
        "bgm_offset_sec": round(offset, 4),
        "aligned_climax_sec": aligned,
        "bgm_drop_index": a.bgm_drop_index if drop_t is not None else None,
        "bgm_drop_t": drop_t,
        "climax_error_sec": round(climax_err, 4) if climax_err is not None else None,
        "preroll_fill": fill_info,
        "duck_points": duck_points,
        "duck_points_source": duck_src,
        "duck_db": a.duck_db,
        "duck_pre_sec": DUCK_PRE_SEC,
        "fade_out_sec": a.fade_out,
        "bgm_gain_db": a.bgm_gain,
        "integrated_lufs": round(lufs, 2),
        "true_peak_dbtp": round(tp, 2),
        "loudness_method": method,
        "limiter_ceiling_dbfs": round(used_ceiling, 2),
        "limiter_attempts": attempts,
        "raw_peak_dbfs_before_scale": round(raw_peak_dbfs, 2),
        "bgm_gap_check": gap_check,
        "preview_duration_sec": a.preview_duration,
        "sfx_source": sfx_source,
        "sfx_peak_dbfs": sfx_peak_dbfs,
        "sfx_only_wav": str(sfx_path) if sfx_path else None,
        "output_path": str(out),
        "video_duration_sec": round(v_dur, 3),
        "audio_duration_sec": round(a_dur, 3) if a_dur else None,
        "video_codec": "copy (-c:v copy，画面零损直通，绝不重编码)",
        "audio_codec": "aac 256k / 48000Hz stereo / +faststart",
        "audio_source_note": audio_note,
        "delivery_mode": "single_film_with_bgm",
        "ffmpeg": ver,
    }
    rp = out.with_name("bgm_mix_report.json")
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    line = "=" * 78
    print(line)
    print(" BGM 混音报告")
    print("-" * 78)
    print(f" 输入片    : {video.name}")
    print(f" 默认单曲  : {bgm.name}  |  BPM {bpm:.2f}  |  小节 {bar_sec:.3f}s  |  循环 {loop_bars} 小节")
    print(f" 节拍档案  : {beats_path.name}")
    print(f" 微音效轨  : {Path(sfx_source).name if sfx_source else '（无 --sfx，取自视频音轨或静音）'}"
          f"  峰值 {sfx_peak_dbfs} dBFS")
    if drop_t is not None:
        print(f" 高潮卡点  : Drop#{a.bgm_drop_index} t={drop_t:.3f}s → 画面 {aligned:.3f}s")
        print(f" 起始偏移  : {offset:+.3f}s   |   卡点误差 {climax_err:.3f}s  "
              f"(≤ 0.03s [{'OK' if climax_err <= 0.03 else 'FAIL'}])")
    else:
        print(f" 起始偏移  : {offset:+.3f}s   （未指定 --align-climax）")
    if fill_info and fill_info.get("enabled"):
        note = f"  [降档: {fill_info.get('strategy')}]" if fill_info.get("degraded") else ""
        print(f" 前段铺底  : {fill_info['fill_bars']} 小节 @ {fill_info['segment_start_sec']:.2f}s 起  "
              f"{fill_info['gain_db']:+.2f} dB（低 {fill_info['below_climax_db']:.0f} dB / "
              f"低通 {fill_info['lowpass_hz'] or 'off'}Hz）  铺满 {fill_info['filled_sec']:.1f}s{note}")
    elif offset > 0.05:
        print(" 前段铺底  : 未启用（异常）")
    else:
        print(" 前段铺底  : 无需（offset ≤ 0）")
    print(f" 洼谷点    : {len(duck_points)} 个 {duck_points[:8]}  ({a.duck_db} dB / 前置 {DUCK_PRE_SEC}s) · {duck_src}")
    print(f" 集成响度  : {lufs:.2f} LUFS  |  真峰值 {tp:.2f} dBTP  "
          f"(≤ -1.0 [{'OK' if tp <= TARGET_TP_DBTP + 1e-6 else 'FAIL'}])  [{method}]")
    print(f" 断层自检  : {'PASS' if gap_check['pass'] else 'FAIL'}  "
          f"最长空白 {gap_check.get('longestGapSec')}s / 允许 {GAP_MAX_SEC}s  "
          f"[{gap_check['window'][0]}s–{gap_check['window'][1]}s]")
    print(f" 封装      : -c:v copy / AAC 256k / +faststart / 限幅 {used_ceiling:.2f} dBFS ×{attempts}")
    print(f" 输出      : {out}")
    print(f" 报告      : {rp.name}")
    if sfx_path:
        print(f" 音效母带  : {sfx_path.name}")
    print("-" * 78)
    if not gap_check["pass"]:
        print(" [WARN] BGM 断层自检未通过，禁止交付；请检查铺底/交叉淡化参数。")
    print(" [LICENSE] 配乐由使用者自备，本工具不授予音乐版权；商用请确认授权并保留 sfx_only.wav。")
    print(line)
    return 0 if gap_check["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
