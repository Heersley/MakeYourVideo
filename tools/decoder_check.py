#!/usr/bin/env python.exe
"""tools/decoder_check.py — D3D11VA 与软件解码的原生 NV12 对拍工具（v1.2.0）。

硬件解码故障可能在软件解码正常时出现异常灰块。工具比较两路原生 NV12 帧，
检测异常灰区并审计编码，供单期正式验收与兼容性诊断使用。

严格模式要求软硬解 NV12 零差、全片单切片、两个解码进程正常退出、完整抽样与零异常灰块。
默认诊断保留像素容差。2K 固定 High@5.1，1080p 历史验证采用 High@4.2。
输出包含被测文件 SHA-256；单片流程另验音频、版面、事实及定点原始 PNG。

退出码
------
  0 = 本项 PASS
  1 = FAIL（硬验收不通过，禁止交付）
  2 = 环境 / 输入错误（参数、文件、FFmpeg、依赖），同样禁止交付

用法
----
  python tools\\decoder_check.py --video <主题>.mp4 --output src\\decoder_check.json
  python tools\\decoder_check.py --video xxx.mp4 --every 3 --output temp\\_work\\dc.json
  python tools\\decoder_check.py --video xxx.mp4 --strict          # 编码告警也算失败

stdout 只输出一份机器可读 JSON（可管道消费）；进度与诊断走 stderr。
"""
from __future__ import annotations

from bgm_common import locate_tools as locate_ffmpeg
import hashlib
from profile_loader import DEFAULT_PROFILE, load_profile
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

TOOL_NAME = "decoder_check.py"
TOOL_VERSION = "1.2.0"
SCHEMA = "decoder_check/1.1"

PINNED_FFMPEG = "9.0.2"     # 生产锁定版本
MIN_FFMPEG_MAJOR = 9        # 低于 9 的构建缺 d3d11 输出格式 / 新 -fps_mode 语法，禁止使用

# H.264 Level 上限（ITU-T H.264 Table A-1，列出支持诊断的档位）
#   maxMBsPerSec = MaxFS × MaxMBPS 的上限；maxFrameMBs = MaxFS
LEVEL_LIMITS = {
    42: {"label": "4.2", "maxFrameMBs": 8704, "maxMBsPerSec": 522240},
    50: {"label": "5.0", "maxFrameMBs": 22080, "maxMBsPerSec": 589824},
    51: {"label": "5.1", "maxFrameMBs": 36864, "maxMBsPerSec": 983040},
}
# 历史兼容组合：分辨率@帧率 → 期望 Level（v3.3 起 2K 为标准档，1080p 仅历史兼容）
EXPECTED_LEVELS = {
    (1080, 1920, 60): frozenset({42}),
}

# 异常灰块的亮度范围与中性色判定
# 下限 60 而非 24：D3D11VA 故障填充的是**中灰常量**（例如 RGB 129 → Y≈129），
# 而 studio_dark 的正常暗场规定灰度 < 40（暗铜台座 RGB(30,26,21) → Y≈26）。
# 取 60 = 暗场上限 40 + 20 余量：既不误伤正常暗场渐变，也不削弱中灰故障的检测力。
GRAY_Y_MIN, GRAY_Y_MAX, GRAY_CHROMA_MAX = 60, 150, 20
GRAY_OPEN_BASE_PX = 15      # 1080 宽下的开运算核，按分辨率等比缩放（2K → 20）

EXIT_PASS, EXIT_FAIL, EXIT_ENV = 0, 1, 2


# --------------------------------------------------------------------------- #
# 环境：FFmpeg 定位与版本锁
# --------------------------------------------------------------------------- #
def probe_media(ffprobe: str, movie: Path) -> dict:
    cmd = [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(movie)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"[decoder_check] ffprobe 失败：{r.stderr.decode('utf-8', 'replace')[-600:]}")
    return json.loads(r.stdout.decode("utf-8", "replace"))


def _fraction(text: str | None) -> float:
    if not text:
        return 0.0
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(text)
    except Exception:
        return 0.0


# --------------------------------------------------------------------------- #
# 非常规编码审计：码率 bpp / 每帧切片数 / 全 I 帧
# --------------------------------------------------------------------------- #
def packet_flags(ffprobe: str, movie: Path, limit: int) -> list[str]:
    """按封装顺序读前 limit 个视频包，只取关键帧标记（不解码，极快）。"""
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "packet=flags", "-of", "csv=p=0",
           "-read_intervals", f"%+#{max(1, limit)}", str(movie)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    out = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if line:
            out.append(line.split(",")[-1])
    return out


def slice_audit(ffmpeg: str, movie: Path, packets: int) -> dict:
    """用 trace_headers 位流滤镜数每帧切片数：micro-slicing 是本机硬解灰块的头号触发器。"""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "info", "-nostdin", "-i", str(movie),
           "-map", "0:v:0", "-c", "copy", "-bsf:v", "trace_headers",
           "-frames:v", str(max(1, packets)), "-f", "null", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")
    re_first = re.compile(r"first_mb_in_slice\s+[01]+\s*=\s*(-?\d+)")
    re_type = re.compile(r"\bslice_type\s+[01]+\s*=\s*(-?\d+)")
    per_frame: list[int] = []
    types: list[int] = []
    pending = False            # 刚读到 "Slice Header"，等它的 first_mb_in_slice
    cur_slices, cur_type = 0, None
    lines = 0
    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            lines += 1
            if lines > 4_000_000:            # 安全阀：异常流不无限读
                break
            if "Slice Header" in line:
                pending = True
                continue
            m = re_first.search(line)
            if m and pending:
                pending = False
                if int(m.group(1)) == 0:     # 新一帧的第一片：结算上一帧
                    if cur_slices:
                        per_frame.append(cur_slices)
                        types.append(cur_type if cur_type is not None else -1)
                    cur_slices, cur_type = 1, None
                else:
                    cur_slices += 1
                continue
            if cur_type is None:
                m = re_type.search(line)
                if m:
                    cur_type = int(m.group(1))
        if cur_slices:
            per_frame.append(cur_slices)
            types.append(cur_type if cur_type is not None else -1)
    finally:
        try:
            proc.stderr.close()
        except Exception:
            pass
        if proc.poll() is None:
            proc.kill()
        proc.wait()

    if not per_frame:
        return {"available": False, "reason": "trace_headers 未解析到 Slice Header"}
    intra = sum(1 for t in types if t % 5 == 2)
    return {
        "available": True,
        "framesAudited": len(per_frame),
        "slicesPerFrameAvg": round(sum(per_frame) / len(per_frame), 3),
        "slicesPerFrameMax": max(per_frame),
        "slicesPerFrameMin": min(per_frame),
        "intraFrameRatioInAudit": round(intra / len(types), 4) if types else None,
    }


def codec_conformance(stream: dict, width: int, height: int, fps: float, policy=None) -> dict:
    """分辨率 × Level × Profile 合法性审计（v1.1 新增，硬判定）。

    `1440×2560@60` 在 16×16 宏块网格下是 90×160 = 14,400 宏块/帧、864,000 宏块/秒；
    `Level 4.2`（522,240）与 `Level 5.0`（589,824）都装不下，必须 `Level 5.1`（983,040）。
    写错 Level 的片子在本机能软解、到严格播放器上却拒解或花屏——所以这一项不降级为告警。
    """
    profile = (stream.get("profile") or "").strip()
    level = int(stream.get("level") or 0)
    fps_r = int(round(fps)) if fps else 0
    mb_w, mb_h = (width + 15) // 16, (height + 15) // 16
    mb_frame = mb_w * mb_h
    mb_sec = mb_frame * (fps_r or 0)

    video = (policy or load_profile()).hard["video"]
    if (width,height,fps) == (video["width"],video["height"],video["fps"]):
        expected = {int(round(float(video["level"])*10))}
    else:
        expected = EXPECTED_LEVELS.get((width, height, fps))
    lim = LEVEL_LIMITS.get(level)
    notes: list[str] = []

    profile_ok = profile.lower() == video["profile"].lower()
    if not profile_ok:
        notes.append(f"profile 为 {profile or '空'}，本厂只认证 High")
    if expected is None:
        notes.append(f"不在本厂认证规格内（{width}×{height}@{fps_r}）："
                     "标准档应为 1440×2560@60")
    elif level not in expected:
        allowed = " / ".join(
            f"High@{LEVEL_LIMITS[code]['label']}" for code in sorted(expected))
        notes.append(f"Level 写错：{width}×{height}@{fps_r} 只认证 {allowed}，"
                     f"实际 {level_label(level)}")
    if lim is None:
        notes.append(f"未知 Level 编码 {level}（本厂认证 4.2 / 5.0 / 5.1）")
    else:
        if mb_frame > lim["maxFrameMBs"]:
            notes.append(f"帧宏块数 {mb_frame} 超过 Level {lim['label']} 上限 "
                         f"{lim['maxFrameMBs']}")
        if mb_sec > lim["maxMBsPerSec"]:
            notes.append(f"宏块率 {mb_sec}/s 超过 Level {lim['label']} 上限 "
                         f"{lim['maxMBsPerSec']}/s")

    return {
        "expectedLevel": LEVEL_LIMITS[min(expected)]["label"] if expected else None,
        "expectedLevels": [LEVEL_LIMITS[code]["label"] for code in sorted(expected)] if expected else None,
        "actualLevel": level_label(level),
        "actualLevelCode": level or None,
        "profile": profile or None,
        "macroBlocksPerFrame": mb_frame,
        "macroBlocksPerSec": mb_sec,
        "levelLimitMBsPerSec": lim["maxMBsPerSec"] if lim else None,
        "levelHeadroomPct": (round((lim["maxMBsPerSec"] - mb_sec) * 100.0 / lim["maxMBsPerSec"], 1)
                             if lim else None),
        "compliant": len(notes) == 0,
        "notes": notes,
    }


def level_label(code: int) -> str:
    if code in LEVEL_LIMITS:
        return LEVEL_LIMITS[code]["label"]
    return f"{code / 10:.1f}" if code else "unknown"


def encoding_audit(ffmpeg: str, ffprobe: str, movie: Path, stream: dict, audit_frames: int,
                   bpp_warn: float, slices_warn: int, iframe_warn: float, policy=None) -> dict:
    w = int(stream.get("width") or 0)
    h = int(stream.get("height") or 0)
    fps = _fraction(stream.get("r_frame_rate")) or _fraction(stream.get("avg_frame_rate")) or 0.0
    vbr = int(stream.get("bit_rate") or 0)
    bpp = (vbr / (w * h * fps)) if (w and h and fps and vbr) else None

    flags = packet_flags(ffprobe, movie, audit_frames)
    kf = sum(1 for f in flags if "K" in f)
    kf_ratio = (kf / len(flags)) if flags else None

    slices = slice_audit(ffmpeg, movie, audit_frames)

    warnings: list[str] = []
    if bpp is not None and bpp > bpp_warn:
        warnings.append(
            f"码率异常偏高：{vpp_str(vbr)}（{bpp:.3f} bits/px/frame > 阈值 {bpp_warn}），"
            "疑似非标编码或冗余数据（历史事故：35.2 Mbps ≈ 0.283 bpp）")
    if kf_ratio is not None and kf_ratio > iframe_warn:
        warnings.append(
            f"关键帧占比异常：{kf_ratio:.1%} of {len(flags)} packets > {iframe_warn:.0%}，疑似全 I 帧编码")
    if slices.get("available") and slices["slicesPerFrameAvg"] > slices_warn:
        warnings.append(
            f"每帧切片数异常：avg {slices['slicesPerFrameAvg']} / max {slices['slicesPerFrameMax']} "
            f"> 阈值 {slices_warn}，疑似 slice-max-mbs 微分片（本机 D3D11VA 灰块头号触发器）")

    codec = (stream.get("codec_name") or "").lower()
    pix = (stream.get("pix_fmt") or "")
    video = (policy or load_profile()).hard["video"]
    if codec and codec != video["codec"]:
        warnings.append(f"编码并非 H.264（{codec}）：全平台硬解兼容红线只认证 "
                        "H.264 High@5.1（2K）/ High@4.2（1080p）+ yuv420p")
    if pix and pix != video["pixFmt"]:
        warnings.append(f"像素格式并非 yuv420p（{pix}）：全平台兼容基线为 yuv420p")

    conf = codec_conformance(stream, w, h, fps,policy)
    warnings.extend(conf["notes"])

    return {
        "videoBitrateBps": vbr or None,
        "bitsPerPixelPerFrame": round(bpp, 4) if bpp is not None else None,
        "auditedPackets": len(flags),
        "keyFrameCount": kf,
        "keyFrameRatio": round(kf_ratio, 4) if kf_ratio is not None else None,
        "sliceAudit": slices,
        "conformance": conf,
        "thresholds": {"bppWarn": bpp_warn, "slicesPerFrameWarn": slices_warn,
                       "keyFrameRatioWarn": iframe_warn},
        "warnings": warnings,
        "status": "warn" if warnings else "ok",
    }


def vpp_str(bps: int) -> str:
    return f"{bps / 1e6:.2f} Mbps" if bps else "unknown"


# --------------------------------------------------------------------------- #
# 异常纯灰连通域（事故画像：大面积中性灰、Y 落在 60–150、RGB 极差 <= 20）
# --------------------------------------------------------------------------- #
def gray_mask(bgr, kernel: int):
    y = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    b, g, r = cv2.split(bgr)
    chroma = cv2.subtract(cv2.max(cv2.max(b, g), r), cv2.min(cv2.min(b, g), r))
    mask = ((y >= GRAY_Y_MIN) & (y <= GRAY_Y_MAX) & (chroma <= GRAY_CHROMA_MAX)).astype("uint8")
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((kernel, kernel), "uint8"))


def gray_block_pct(bgr, mask, area_total: int, min_ratio: float, flat_std: float = 2.0):
    """返回 (纯灰占比%, 有纹理中性灰占比%, 最大纯灰块信息)。

    「异常纯灰」= 中性（RGB 极差 ≤20）+ 中灰带（60≤Y≤150）+ 面积 ≥1% + **平坦**（通道标准差 ≤2）。
    最后一条是关键：解码故障只会填充**常量色**（均匀填充时 std = 0.0），
    而设计稿里的大块中性灰必然带渐变 / 抗锯齿 / 纹理（实测 std ≈ 19），据此区分「内容」与「故障」。
    面积 < 1% 的碎块一律不算（细线 / 文字抗锯齿）。
    """
    if int(mask.sum()) < max(1, int(area_total * min_ratio)):
        return 0.0, 0.0, None                      # 快路径：总量都不够，必无合格连通块
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return 0.0, 0.0, None
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = areas >= area_total * min_ratio
    if not keep.any():
        return 0.0, 0.0, None

    kept_idx = [i + 1 for i in np.nonzero(keep)[0]]
    kept_idx.sort(key=lambda i: -int(stats[i, cv2.CC_STAT_AREA]))
    flat_area, textured_area, worst = 0, 0, None
    for rank, idx in enumerate(kept_idx):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if rank >= 8:                              # 只对最大的 8 块判平坦度，其余按有纹理计
            textured_area += area
            continue
        px = bgr[labels == idx]
        std = [float(px[:, 2].std()), float(px[:, 1].std()), float(px[:, 0].std())]
        if max(std) <= flat_std:
            flat_area += area
            if worst is None or area > worst["areaPx"]:
                x, y_, bw, bh = (int(stats[idx, cv2.CC_STAT_LEFT]), int(stats[idx, cv2.CC_STAT_TOP]),
                                 int(stats[idx, cv2.CC_STAT_WIDTH]), int(stats[idx, cv2.CC_STAT_HEIGHT]))
                worst = {
                    "areaPx": area,
                    "areaPctOfRegion": round(area * 100.0 / area_total, 3),
                    "bbox": [x, y_, bw, bh],
                    "meanRGB": [int(round(float(px[:, 2].mean()))), int(round(float(px[:, 1].mean()))),
                                int(round(float(px[:, 0].mean())))],
                    "stdRGB": [round(v, 2) for v in std],
                }
        else:
            textured_area += area
    return (float(flat_area) * 100.0 / area_total,
            float(textured_area) * 100.0 / area_total,
            worst)


# --------------------------------------------------------------------------- #
# 双链解码对拍主体
# --------------------------------------------------------------------------- #
def build_cmd(ffmpeg: str, movie: Path, hardware: bool, every: int, threads: int) -> list[str]:
    args = [ffmpeg, "-v", "error", "-nostdin"]
    if hardware:
        args += ["-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11"]
    filters = ["hwdownload", "format=nv12"] if hardware else ["format=nv12"]
    if every > 1:
        filters.append(f"select=not(mod(n\\,{every}))")
    args += ["-i", str(movie), "-map", "0:v:0", "-vf", ",".join(filters),
             "-fps_mode", "passthrough", "-pix_fmt", "nv12"]
    if threads > 0:
        args += ["-threads", str(threads)]
    return args + ["-f", "rawvideo", "-"]


def compare(ffmpeg: str, movie: Path, width: int, height: int, every: int, threads: int,
            max_mae: float, max_peak: int, max_outlier_share: float,
            gray_min_ratio: float, progress_every: int = 300) -> dict:
    frame_size = width * height * 3 // 2
    kernel = max(3, int(round(GRAY_OPEN_BASE_PX * width / 1080)))

    procs: list[subprocess.Popen] = []
    try:
        for hw in (False, True):
            procs.append(subprocess.Popen(build_cmd(ffmpeg, movie, hw, every, threads),
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        soft, hard = procs

        worst_mae, worst_peak, worst_rgb = 0.0, 0, 0
        worst_mae_frame = -1
        left_max, full_max = 0.0, 0.0
        left_tex_max, full_tex_max = 0.0, 0.0
        worst_gray = None
        bad: list[dict] = []
        bad_count = 0
        count = 0
        t0 = time.time()

        while True:
            a = soft.stdout.read(frame_size)     # 软解
            b = hard.stdout.read(frame_size)     # 硬解
            if not a and not b:
                break
            if len(a) != frame_size or len(b) != frame_size:
                tail = {n: (p.stderr.read() or b"").decode("utf-8", "replace").strip()[-600:]
                        for n, p in zip(("software", "hardware"), procs) if p.poll() is not None}
                raise RuntimeError(
                    f"解码器输出不完整帧（软解 {len(a)} / 硬解 {len(b)} 字节，期望 {frame_size}）；"
                    f"硬解 stderr: {tail.get('hardware') or '（进程仍存活，无输出）'}")
            fa = np.frombuffer(a, np.uint8)
            fb = np.frombuffer(b, np.uint8)
            diff = np.abs(fa.astype("i2") - fb.astype("i2"))
            mae = float(diff.mean())
            peak = int(diff.max())
            outlier = float((diff > 16).mean())

            frame_no = count * every
            if mae > worst_mae:
                worst_mae, worst_mae_frame = mae, frame_no
            worst_peak = max(worst_peak, peak)

            hw_bgr = None
            if peak:
                # 只有真的有差异才做 RGB 抽样比对，避免每帧双份 cvtColor 拖慢整片
                hw_bgr = cv2.cvtColor(fb.reshape(height * 3 // 2, width), cv2.COLOR_YUV2BGR_NV12)
                sw_bgr = cv2.cvtColor(fa.reshape(height * 3 // 2, width), cv2.COLOR_YUV2BGR_NV12)
                worst_rgb = max(worst_rgb, int(cv2.absdiff(hw_bgr, sw_bgr).max()))

            if hw_bgr is None:
                hw_bgr = cv2.cvtColor(fb.reshape(height * 3 // 2, width), cv2.COLOR_YUV2BGR_NV12)
            mask = gray_mask(hw_bgr, kernel)
            left_pct, left_tex, left_info = gray_block_pct(
                hw_bgr[:, : width // 2], mask[:, : width // 2], (width // 2) * height, gray_min_ratio)
            full_pct, full_tex, full_info = gray_block_pct(hw_bgr, mask, width * height, gray_min_ratio)
            left_max = max(left_max, left_pct)
            full_max = max(full_max, full_pct)
            left_tex_max = max(left_tex_max, left_tex)
            full_tex_max = max(full_tex_max, full_tex)
            if (left_pct > 0 or full_pct > 0) and worst_gray is None:
                sw_bgr = cv2.cvtColor(fa.reshape(height * 3 // 2, width), cv2.COLOR_YUV2BGR_NV12)
                sw_left, _, _ = gray_block_pct(sw_bgr[:, : width // 2], gray_mask(sw_bgr, kernel)[:, : width // 2],
                                               (width // 2) * height, gray_min_ratio)
                worst_gray = {
                    "frame": frame_no,
                    "sec": round(frame_no / max(1, _fps_hint), 3) if _fps_hint else None,
                    "hardwareLeftPct": round(left_pct, 3),
                    "hardwareFullPct": round(full_pct, 3),
                    "softwareLeftPct": round(sw_left, 3),
                    "region": left_info or full_info,
                }

            if mae > max_mae or peak > max_peak or outlier > max_outlier_share:
                bad_count += 1
                if len(bad) < 50:
                    bad.append({"frame": frame_no, "mae": round(mae, 4), "peak": peak,
                                "outlierShare": round(outlier, 6)})
                elif len(bad) == 50:
                    bad.append({"truncated": True, "note": "badFrames 仅保留前 50 条"})

            count += 1
            if progress_every and count % progress_every == 0:
                print(f"[decoder_check] {count} 帧已对拍（{time.time() - t0:.1f}s）…",
                      file=sys.stderr, flush=True)

        rc = [p.wait() for p in procs]
        err_soft = (soft.stderr.read() or b"").decode("utf-8", "replace").strip()
        err_hard = (hard.stderr.read() or b"").decode("utf-8", "replace").strip()
        return {
            "framesCompared": count,
            "maxFrameMAE": round(worst_mae, 4),
            "maxFrameMAEFrame": worst_mae_frame if worst_mae > 0 else None,
            "maxSampleDelta": worst_peak,
            "maxRGBDelta": worst_rgb,
            "badFrameCount": bad_count,
            "badFrames": bad,
            "grayLeftHalfMaxPct": round(left_max, 3),
            "grayFullFrameMaxPct": round(full_max, 3),
            "grayTexturedLeftHalfMaxPct": round(left_tex_max, 3),
            "grayTexturedFullFrameMaxPct": round(full_tex_max, 3),
            "grayWorstSample": worst_gray,
            "decoderExitCodes": {"software": rc[0], "hardware": rc[1]},
            "decoderStderr": {"software": err_soft[-800:] or None, "hardware": err_hard[-800:] or None},
            "elapsedSec": round(time.time() - t0, 2),
        }
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
            for stream in (p.stdout, p.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            p.wait()


_fps_hint = 0.0


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="D3D11VA 硬解 vs 软件解码 原生 NV12 对拍验收（全厂通用，无单期依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video_pos", nargs="?", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--video", type=Path, help="待验收的 mp4（必填）")
    ap.add_argument("--every", type=int, default=None, help="抽样间隔（帧）；60fps 下 6 ≈ 10 帧/秒，默认 6")
    ap.add_argument("--output", type=Path, help="把 JSON 报告另存到该路径")
    ap.add_argument("--ffmpeg", help="显式指定 FFmpeg 9.x 的 ffmpeg.exe（默认自动定位 WinGet 9.0.2）")
    ap.add_argument("--threads", type=int, default=0, help="解码线程数，0=FFmpeg 自动（默认）")
    ap.add_argument("--max-mae", type=float, default=0.5, help="单帧平均绝对差上限，默认 0.5")
    ap.add_argument("--max-peak", type=int, default=8, help="单样本最大差上限，默认 8")
    ap.add_argument("--max-outlier-share", type=float, default=0.002,
                    help="单帧内差值>16 的样本占比上限，默认 0.002")
    ap.add_argument("--gray-min-area-pct", type=float, default=1.0,
                    help="连通过滤：只统计占区域 >= 该百分比的灰块，默认 1.0")
    ap.add_argument("--audit-frames", type=int, default=90, help="编码审计抽样包数，默认 90")
    ap.add_argument("--bpp-warn", type=float, default=0.35, help="码率 bpp 告警阈值，默认 0.35")
    ap.add_argument("--slices-warn", type=int, default=8, help="每帧切片数告警阈值，默认 8")
    ap.add_argument("--iframe-warn", type=float, default=0.25, help="关键帧占比告警阈值，默认 0.25")
    ap.add_argument("--strict", action="store_true", help="把编码告警升级为硬失败")
    ap.add_argument("--quiet", action="store_true", help="不打印进度到 stderr")
    ap.add_argument("--profile",default=DEFAULT_PROFILE)
    args = ap.parse_args(argv)
    policy = load_profile(args.profile)
    limits = policy.hard["decoder"]
    if args.strict:
        if args.every not in (None, limits["sampleEvery"]):
            ap.error("--strict 的采样间隔必须与所选制作档案一致")
        for name in ("gray_min_area_pct", "bpp_warn", "iframe_warn", "max_outlier_share"):
            if getattr(args, name) != ap.get_default(name):
                ap.error("--strict 要求使用标准诊断阈值: " + name)
    if args.every is None:
        args.every = limits["sampleEvery"]

    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    global cv2, np
    try:
        import numpy as np                                  # noqa: F811
        import cv2                                          # noqa: F811
    except Exception as exc:                                # pragma: no cover
        print(f"[decoder_check] 缺少依赖 numpy / opencv-python：{exc}\n"
              "        请用 python 运行（系统 3.13 无这些包）。", file=sys.stderr)
        return EXIT_ENV

    movie = args.video or args.video_pos
    if not movie:
        ap.error("必须用 --video 指定 mp4")
    movie = movie.resolve()
    if not movie.is_file():
        print(f"[decoder_check] 视频不存在：{movie}", file=sys.stderr)
        return EXIT_ENV
    if args.every < 1:
        print("[decoder_check] --every 必须 >= 1", file=sys.stderr)
        return EXIT_ENV

    try:
        ffmpeg, ffprobe, ff_line = locate_ffmpeg(args.ffmpeg)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ENV

    global _fps_hint
    meta = probe_media(ffprobe, movie)
    vstreams = [s for s in meta.get("streams", []) if s.get("codec_type") == "video"]
    if not vstreams:
        print(f"[decoder_check] 没有视频流：{movie}", file=sys.stderr)
        return EXIT_ENV
    v = vstreams[0]
    width, height = int(v["width"]), int(v["height"])
    fps = _fraction(v.get("r_frame_rate")) or _fraction(v.get("avg_frame_rate"))
    _fps_hint = fps
    nb = int(v["nb_frames"]) if str(v.get("nb_frames") or "").isdigit() else 0
    if not nb:
        nb = int(round(_fraction(v.get("duration")) * fps)) if fps else 0
    expected = (nb + args.every - 1) // args.every if nb else 0

    if not args.quiet:
        print(f"[decoder_check] {movie.name}  {width}x{height}@{fps:g}fps  {nb} 帧  "
              f"抽样 every={args.every} → 预期 {expected} 帧", file=sys.stderr, flush=True)

    if args.strict:
        args.max_mae, args.max_peak = limits["maxMae"], limits["maxPeak"]
        args.audit_frames = nb
        args.slices_warn = limits["slicesPerFrame"]

    encoding = encoding_audit(ffmpeg, ffprobe, movie, v, args.audit_frames,
                              args.bpp_warn, args.slices_warn, args.iframe_warn, policy)

    hard_failed_reason = None
    cmp: dict = {}
    for attempt in (1, 2):
        try:
            cmp = compare(ffmpeg, movie, width, height, args.every, args.threads,
                          args.max_mae, args.max_peak, args.max_outlier_share,
                          args.gray_min_area_pct / 100.0,
                          progress_every=0 if args.quiet else 300)
            cmp["attempts"] = attempt
            break
        except Exception as exc:
            # 只在「一帧都没读到」时重试一次：这是 D3D11 设备被占用/初始化抢跑的典型瞬态，
            # 与内容/编码无关；只要已读到帧就视为真失败，绝不掩盖问题。
            if attempt == 1:
                print(f"[decoder_check] 硬解链首帧未就绪，2s 后重试一次：{exc}", file=sys.stderr, flush=True)
                time.sleep(2.0)
                continue
            cmp = {"error": f"{type(exc).__name__}: {exc}", "attempts": attempt}
            hard_failed_reason = "解码链异常中断（详见 comparison.error）"

    hw_ok = "error" not in cmp and cmp.get("decoderExitCodes", {}).get("hardware") == 0
    frames_ok = bool(expected) and cmp.get("framesCompared") == expected
    pixel_ok = bool(cmp.get("badFrameCount") == 0)
    gray_ok = all(0 <= cmp.get(key, float("inf")) <= limits["maxGrayPct"]
                  for key in ("grayLeftHalfMaxPct", "grayFullFrameMaxPct"))
    encoding_ok = encoding["status"] == "ok"
    codec_ok = bool(encoding.get("conformance", {}).get("compliant"))

    checks = {
        "hardwareDecode": bool(hw_ok),
        "frameCountComplete": bool(frames_ok),
        "pixelMatch": bool(pixel_ok),
        "noGrayBlock": bool(gray_ok),
        "codecConformance": codec_ok,
    }
    if args.strict:
        slices = encoding["sliceAudit"]
        checks["fullSingleSliceAudit"] = bool(nb and slices.get("framesAudited") == nb
                                              and slices.get("slicesPerFrameMax") == limits["slicesPerFrame"]
                                              and encoding["auditedPackets"] == nb)
        checks["softwareDecode"] = cmp.get("decoderExitCodes", {}).get("software") == 0
        for key in ("fullSingleSliceAudit", "softwareDecode"):
            if not checks[key]:
                encoding["warnings"].append(key)
        encoding_ok = encoding_ok and checks["fullSingleSliceAudit"] and checks["softwareDecode"]
        encoding["status"] = "ok" if encoding_ok else "warn"
        checks["encodingStandard"] = bool(encoding_ok)

    reasons = []
    if hard_failed_reason:
        reasons.append(hard_failed_reason)
    if not hw_ok and not hard_failed_reason:
        reasons.append("D3D11VA 硬解链未正常结束（可能静默回退软解或驱动拒绝）")
    if not frames_ok and expected:
        reasons.append(f"抽样帧数不符：实得 {cmp.get('framesCompared')} / 预期 {expected}")
    if not pixel_ok:
        reasons.append(f"软硬解像素不匹配：{cmp.get('badFrameCount')} 帧越界（阈值 MAE<={args.max_mae} / peak<={args.max_peak}）")
    if not gray_ok:
        reasons.append(f"异常纯灰连通域：左半屏 {cmp.get('grayLeftHalfMaxPct')}% / "
                       f"全屏 {cmp.get('grayFullFrameMaxPct')}%（上限 {limits['maxGrayPct']}%）")
    if not codec_ok:
        reasons.append("编码档位不合规：" + "；".join(encoding.get("conformance", {}).get("notes") or []))
    if args.strict and not encoding_ok:
        reasons.append("非常规编码告警（--strict）：" + "；".join(encoding["warnings"]))

    passed = all(checks.values())
    passed = passed and not reasons

    with movie.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    audio_stream = next((s for s in meta["streams"] if s.get("codec_type") == "audio"), {})
    report = {
        **policy.stamp,
        "strict": args.strict,
        "schema": SCHEMA,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION,
                 "python": sys.version.split()[0], "numpy": np.__version__, "opencv": cv2.__version__},
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ffmpeg": {"path": ffmpeg, "ffprobe": ffprobe, "version": ff_line,
                   "pinned": PINNED_FFMPEG,
                   "pinnedMatched": PINNED_FFMPEG in ff_line},
        "input": {"sha256": digest, "path": str(movie), "sizeBytes": movie.stat().st_size},
        "stream": {"codec": v.get("codec_name"), "profile": v.get("profile"),
                   "level": v.get("level"),
                   "levelLabel": level_label(int(v.get("level") or 0)),
                   "pixFmt": v.get("pix_fmt"), "colorSpace": v.get("color_space"),
                   "audioChannels": audio_stream.get("channels"),
                   "audioSampleRate": int(audio_stream.get("sample_rate") or 0),
                   "width": width, "height": height, "fps": round(fps, 4),
                   "nbFrames": nb, "durationSec": round(nb / fps, 3) if (nb and fps) else None,
                   "videoBitrateBps": int(v["bit_rate"]) if str(v.get("bit_rate") or "").isdigit() else None,
                   "audioCodec": next((s.get("codec_name") for s in meta.get("streams", [])
                                       if s.get("codec_type") == "audio"), None)},
        "sampling": {"every": args.every, "expectedFrames": expected,
                     "framesCompared": cmp.get("framesCompared"),
                     "mode": "native NV12 (Y+UV) 双链直读，全程不经 RGB"},
        "hardware": {"accel": "d3d11va", "outputFormat": "d3d11",
                     "download": "hwdownload,format=nv12", "available": bool(hw_ok)},
        "tolerances": {"maxFrameMAE": args.max_mae, "maxSampleDelta": args.max_peak,
                       "maxOutlierShare": args.max_outlier_share, "grayLimitPct": limits["maxGrayPct"],
                       "grayMinAreaPct": args.gray_min_area_pct, "grayFlatStdMax": 2.0,
                       "grayLumaBand": [GRAY_Y_MIN, GRAY_Y_MAX]},
        "comparison": cmp,
        "encodingAudit": encoding,
        "checks": checks,
        "passed": bool(passed),
        "verdict": "PASS" if passed else "FAIL",
        "reasons": reasons,
    }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", "utf-8")
    print(text)

    if not args.quiet:
        print(f"[decoder_check] {'PASS' if passed else 'FAIL'}  "
              f"{width}x{height}@{fps:g} High@{level_label(int(v.get('level') or 0))}  "
              f"MAE={cmp.get('maxFrameMAE')} peak={cmp.get('maxSampleDelta')} "
              f"gray(left/full)={cmp.get('grayLeftHalfMaxPct')}/{cmp.get('grayFullFrameMaxPct')} "
              f"frames={cmp.get('framesCompared')}/{expected}"
              + ("  " + " | ".join(reasons) if reasons else ""), file=sys.stderr)
    return EXIT_PASS if passed else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
