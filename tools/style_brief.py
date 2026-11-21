#!/usr/bin/env python3
"""从成片反推视觉规范：抽关键帧 → 测背景色 / 色板 / 三段式占比 / 字号阶梯 → style_brief.md。

分工原则（重要）：
  本脚本只做「可确定性测量」的部分 —— 颜色、几何、占比、字高、行带位置。
  「哪行是标题、哪个是强调数字」这类语义判断不在脚本内做，输出里留
  「待视觉模型判定」清单，由下游模型（或 Agent）补完后再定稿。

用法:
  python TOOL/style_brief.py --video output/evergreen/2026-11-19/01_帕累托前沿/15秒样片_净画面.mp4
  python TOOL/style_brief.py --video a.mp4 --out ./style --max-frames 12
  python TOOL/style_brief.py --frames ./frames --out ./style     # 已有帧目录时跳过抽帧

输出:
  <out>/style_brief.md      人读报告
  <out>/style_brief.json    机读结果（给后续 prompt / 模板复用）
  <out>/frames/*.png        抽出的关键帧
  <out>/contact_sheet.png   联系表，人工复核用

依赖: ffmpeg + ffprobe（建议 ≥5.0）+ Pillow。
ffmpeg 解析顺序: --ffmpeg → FFMPEG_BIN 环境变量 → ffmpeg -version ≥5 的 PATH 项
                → winget 安装的 Gyan 完整版 → PATH 任意项（会告警）。
  本机 PATH 里可能还留着 2013 年的老版本，它解不了 HEVC 且 ffprobe 字段名不同，
  所以这里不盲信 which("ffmpeg")。
"""

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# 项目基准色（AGENTS.md §4.2 暖黑金线）
BASE_BG = "#0D0B09"
BASE_GOLD = "#C9A96A"
# 竖屏三段式默认切分（顶部悬念标题区 / 中部画布 / 底部字幕安全带）
DEFAULT_TOP_PCT = 12.0
DEFAULT_BOTTOM_PCT = 28.0
ANALYSIS_WIDTH = 720          # 分析用降采样宽度，全高按比例；字高最终换算成百分比
MIN_FFMPEG_MAJOR = 5

# 视觉判定判据来自 AGENTS.md §4。脚本将判据和结构化提问交给视觉模型。
ACCENT_MAX_COUNT = 4          # 强调色全片最多出现处数
AVOID_LIST = [
    "霓虹", "蓝紫渐变", "赛博城市", "粒子雨", "光效字", "每字弹跳", "AI 人脸",
    "炫技转场", "水印角标", "每元素不同动画", "高频闪烁", "黑屏开场",
    "字幕压住画布主体", "防御性标注", "常驻角标或文献小卡", "类比当定论",
]


def out(msg=""):
    print(msg, flush=True)


def hexc(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def lum(rgb):
    return rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- ffmpeg 定位

def ffmpeg_major(exe):
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=20)
        m = re.search(r"ffmpeg version (\d+)", (r.stdout or "") + (r.stderr or ""))
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def locate_tools(explicit=None):
    """返回 (ffmpeg, ffprobe, major, note)。优先选用能解 HEVC 的新版。"""
    if explicit:
        p = Path(explicit)
        ff = p if p.suffix.lower() == ".exe" else p / "ffmpeg.exe"
        if not ff.exists():
            raise SystemExit(f"--ffmpeg 指向的路径不存在: {ff}")
        return str(ff), str(ff.with_name("ffprobe.exe")), ffmpeg_major(str(ff)), "参数指定"

    env = os.environ.get("FFMPEG_BIN")
    if env:
        p = Path(env)
        ff = p if p.suffix.lower() == ".exe" else p / "ffmpeg.exe"
        if ff.exists():
            return str(ff), str(ff.with_name("ffprobe.exe")), ffmpeg_major(str(ff)), "FFMPEG_BIN"

    cands = []
    local = os.environ.get("LOCALAPPDATA", "")
    for pat in ("Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe",
                "Microsoft/WinGet/Packages/*FFmpeg*/**/bin/ffmpeg.exe"):
        cands += sorted(Path(local).glob(pat)) if local else []
    which = shutil.which("ffmpeg")
    if which:
        cands.append(Path(which))

    scored = [(ffmpeg_major(str(c)), c) for c in cands if Path(c).exists()]
    scored.sort(key=lambda t: -t[0])
    if not scored:
        raise SystemExit("找不到 ffmpeg。请安装（winget install Gyan.FFmpeg）或用 --ffmpeg 指定。")

    major, ff = scored[0]
    note = "PATH/系统" if which and str(ff) == which else "自动发现"
    return str(ff), str(ff.with_name("ffprobe.exe")), major, note


def run(cmd, timeout=180):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or ""), (r.stderr or "")


# ---------------------------------------------------------------- 取帧

def probe_video(ffprobe, video):
    code, so, _ = run([ffprobe, "-v", "error", "-select_streams", "v:0",
                       "-show_entries", "stream=width,height,codec_name,r_frame_rate,duration",
                       "-of", "default=nw=1", video])
    info = {}
    for line in so.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    w, h = int(info.get("width", 0)), int(info.get("height", 0))
    dur = float(info.get("duration") or 0)
    if not dur:
        _, so2, _ = run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=nw=1:nk=1", video])
        try:
            dur = float((so2 or "0").strip().splitlines()[0])
        except Exception:
            dur = 0.0
    return {"width": w, "height": h, "codec": info.get("codec_name", ""),
            "fps_expr": info.get("r_frame_rate", ""), "duration": round(dur, 3),
            "aspect": round(w / h, 4) if h else 0}


def keyframe_times(ffprobe, video):
    """关键帧时间点。新旧 ffprobe 字段名不同：新版 pts_time，2013 老版 pkt_pts_time。
    用 -show_entries frame=pts_time 在老版上会静默返回空行，所以两个都取并兜底。"""
    for fields in ("frame=pts_time", "frame=pkt_pts_time"):
        code, so, _ = run([ffprobe, "-v", "error", "-select_streams", "v:0",
                           "-skip_frame", "nokey", "-show_frames",
                           "-show_entries", fields, "-of", "csv=p=0", video])
        times = []
        for line in so.splitlines():
            for tok in line.split(","):
                tok = tok.strip()
                if tok and re.fullmatch(r"-?\d+(\.\d+)?", tok):
                    try:
                        t = float(tok)
                    except ValueError:
                        continue
                    if t >= 0:
                        times.append(t)
                    break
        if times:
            return sorted(set(round(t, 3) for t in times))
    return []


def uniform_times(duration, n):
    if duration <= 0:
        return [0.0]
    return [round(duration * (i + 0.5) / n, 3) for i in range(n)]


def pick_times(times, max_frames):
    if len(times) <= max_frames:
        return times
    step = len(times) / max_frames
    return [times[min(len(times) - 1, int(i * step))] for i in range(max_frames)]


def extract_frames(ffmpeg, video, times, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, t in enumerate(times, 1):
        p = outdir / f"frame_{i:02d}_t{t:07.2f}.png"
        code, _, err = run([ffmpeg, "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", video,
                            "-frames:v", "1", "-vf", f"scale={ANALYSIS_WIDTH}:-1",
                            str(p)], timeout=120)
        if code == 0 and p.exists() and p.stat().st_size > 0:
            paths.append((t, p))
        else:
            out(f"  ! 取帧失败 t={t}s {err.strip()[:80]}")
    return paths


# ---------------------------------------------------------------- 图像分析

def border_bg(im):
    """四条边带取中位数当作底色。不用全图众数：中部主体色会污染结果。"""
    w, h = im.size
    px = im.load()
    samples = []
    for x in range(0, w, 3):
        for y in (1, 2, h - 3, h - 2):
            samples.append(px[x, y])
    for y in range(0, h, 3):
        for x in (1, 2, w - 3, w - 2):
            samples.append(px[x, y])
    if not samples:
        return (0, 0, 0)
    samples.sort(key=lum)
    return samples[len(samples) // 2]


def palette(im, k=6):
    """4bit 量化直方图取主色，返回 [(hex, pct)]。"""
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    q = small.quantize(colors=32, method=Image.MEDIANCUT).convert("RGB")
    px = q.load()
    counts = {}
    for y in range(0, q.height, 2):
        for x in range(0, q.width, 2):
            c = px[x, y]
            key = (c[0] // 8 * 8, c[1] // 8 * 8, c[2] // 8 * 8)
            counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values()) or 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:k]
    return [(hexc(c), round(n / total * 100, 2)) for c, n in top]


def band_metrics(im, top_pct, bottom_pct):
    w, h = im.size
    g = im.convert("L")
    px = g.load()
    edges = g.filter(ImageFilter.FIND_EDGES).load()
    zones = {
        "top": (0, int(h * top_pct / 100)),
        "mid": (int(h * top_pct / 100), int(h * (100 - bottom_pct) / 100)),
        "bottom": (int(h * (100 - bottom_pct) / 100), h),
    }
    res = {}
    for name, (y0, y1) in zones.items():
        tot = n = dark = bright = edge = 0
        for y in range(y0, y1, 3):
            for x in range(0, w, 5):
                v = px[x, y]
                tot += v
                n += 1
                if v < 40:
                    dark += 1
                elif v > 180:
                    bright += 1
                edge += edges[x, y]
        n = max(n, 1)
        res[name] = {
            "height_pct": round((y1 - y0) / h * 100, 2),
            "mean_lum": round(tot / n, 1),
            "dark_ratio": round(dark / n * 100, 2),
            "bright_ratio": round(bright / n * 100, 2),
            "edge_density": round(edge / n, 2),
        }
    return res


def text_rows(im, top_pct, bottom_pct):
    """行带检测：边缘能量剖面 → 垂直滑动平均压制细线 → 分带鲁棒阈值 → 字缝容差合并。

    两个坑都是实测踩出来的：
    1. 单像素水平分割线（每屏都有的细金线）会让整带 max 暴涨，
       以 max 为基准的阈值会把真实文字整片淹掉。所以先做垂直滑动平均：
       1px 线的响应被摊薄到窗口内，40px 的文字带几乎不受影响。
    2. 各带内容密度差异大，阈值必须分带计算，不能全图共用。

    返回字高的「帽高近似」，用于比较层级，不等于字号。
    """
    w, h = im.size
    g = im.convert("L")
    e = g.filter(ImageFilter.FIND_EDGES)
    ep = e.load()
    prof = [(y, sum(ep[x, y] for x in range(0, w, 3)) / (w // 3)) for y in range(0, h, 2)]
    if not prof:
        return []

    win = max(3, int(h * 0.015) // 2)            # 半窗宽，整窗约 1.5% 画面高
    vals = [v for _, v in prof]
    smooth = []
    for i in range(len(vals)):
        a, b = max(0, i - win), min(len(vals), i + win + 1)
        smooth.append(sum(vals[a:b]) / (b - a))

    zones = {"top": (0, int(h * top_pct / 100)),
             "mid": (int(h * top_pct / 100), int(h * (100 - bottom_pct) / 100)),
             "bottom": (int(h * (100 - bottom_pct) / 100), h)}
    gap_tol = max(6, int(h * 0.012))
    min_h = max(10, int(h * 0.016))
    rows = []

    for zname, (z0, z1) in zones.items():
        idx = [i for i, (y, _) in enumerate(prof) if z0 <= y < z1]
        if not idx:
            continue
        seg = [smooth[i] for i in idx]
        peak = max(seg)
        base = statistics.median(seg)
        if peak < 1.0 or peak < base * 1.35:        # 区内对比不足 → 没有实际内容
            continue
        # 阈值必须高于底噪。只用 peak*0.3 时，峰值弱的区（例如只剩细字刊头，
        # peak≈6）阈值会掉到 1.8，而底噪本身就有 2.4，整段全被判命中，
        # 于是产出 0%–12% 这种占满整个顶部区的假行带。
        thr = max(peak * 0.30, base * 1.18, 3.0)
        hits = [(prof[i][0], smooth[i]) for i in idx if smooth[i] > thr]
        if not hits:
            continue
        runs, cur = [], [hits[0][0], hits[0][0]]
        for y, _ in hits[1:]:
            if y - cur[1] <= gap_tol:
                cur[1] = y
            else:
                runs.append(cur)
                cur = [y, y]
        runs.append(cur)
        for a, b in runs:
            if b - a < min_h:
                continue
            rows.append({
                "zone": zname,
                "y0_pct": round(a / h * 100, 2),
                "y1_pct": round(b / h * 100, 2),
                "cap_pct": round((b - a) / h * 100, 2),
                "energy_pct": round(max(s for y, s in hits if a <= y <= b) / peak * 100, 1),
            })
    return rows


def cluster_tiers(per_frame_rows, frame_count):
    """按「区 + 字高」聚类成层级。

    不能只按字高跨区合并：顶部标题与底部字幕常同字号，合并后会得到
    y0=8% / y1=79% 这种不可能的行带，进而报出假的安全区冲突。位置信息
    是规范的一部分，所以区必须参与聚类键。
    """
    allrows = [dict(r, _fi=fi) for fi, rows in enumerate(per_frame_rows) for r in rows]
    if not allrows:
        return []
    clusters = []
    for r in sorted(allrows, key=lambda r: -r["cap_pct"]):
        for c in clusters:
            if c["zone"] == r["zone"] and abs(c["cap_med"] - r["cap_pct"]) <= max(0.3, c["cap_med"] * 0.2):
                c["rows"].append(r)
                c["cap_med"] = statistics.median([x["cap_pct"] for x in c["rows"]])
                break
        else:
            clusters.append({"zone": r["zone"], "cap_med": r["cap_pct"], "rows": [r]})

    tiers = []
    for c in sorted(clusters, key=lambda c: -c["cap_med"]):
        rows = c["rows"]
        # 按「帧」计出现率：同一帧内同层的多条行带只算 1 次。
        # 早前按 (y0_pct, y1_pct) 元组去重，位置稳定的层级会被压成 1 帧，
        # 导致 L1 出现率虚低到 30%、甚至整层被 share<0.30 误过滤。
        share = min(1.0, len({r["_fi"] for r in rows}) / max(frame_count, 1))
        if share < 0.30:
            continue
        caps = [r["cap_pct"] for r in rows]
        mean = statistics.mean(caps) if len(caps) > 1 else caps[0]
        spread = (statistics.pstdev(caps) / mean * 100) if len(caps) > 1 and mean else 0.0
        tiers.append({
            "cap_pct": round(c["cap_med"], 2),
            "zone": c["zone"],
            "y0_pct": round(statistics.median([r["y0_pct"] for r in rows]), 2),
            "y1_pct": round(statistics.median([r["y1_pct"] for r in rows]), 2),
            "presence_pct": round(share * 100, 1),
            "spread_pct": round(spread, 1),
            "stability": "稳定" if spread <= 6 else ("波动" if spread <= 15 else "不稳定"),
        })
    tiers.sort(key=lambda t: -t["cap_pct"])
    for i, t in enumerate(tiers, 1):
        t["tier"] = f"L{i}"
    return tiers


def contact_sheet(paths, dest, cols=4, thumb_w=260):
    if not paths:
        return None
    ims = []
    for _, p in paths:
        try:
            im = Image.open(p).convert("RGB")
            im.thumbnail((thumb_w, thumb_w * 4))
            ims.append((p.name, im))
        except Exception:
            continue
    if not ims:
        return None
    rows = (len(ims) + cols - 1) // cols
    cw = max(i.width for _, i in ims) + 8
    ch = max(i.height for _, i in ims) + 22
    sheet = Image.new("RGB", (cols * cw, rows * ch), (24, 22, 20))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
    except Exception:
        font = ImageFont.load_default()
    for idx, (name, im) in enumerate(ims):
        x = (idx % cols) * cw + 4
        y = (idx // cols) * ch + 4
        sheet.paste(im, (x, y))
        d.text((x, y + im.height + 3), name, fill=(200, 190, 175), font=font)
    sheet.save(dest)
    return dest


# ---------------------------------------------------------------- 汇总

def analyze(video, outdir, args, ffmpeg, ffprobe):
    meta = probe_video(ffprobe, video)
    out(f"视频 {meta['width']}x{meta['height']} {meta['codec']} {meta['duration']}s")

    if args.frames:
        paths = []
        for i, p in enumerate(sorted(Path(args.frames).glob("*.png")), 1):
            paths.append((float(i - 1), p))
        if not paths:
            raise SystemExit(f"{args.frames} 里没有 png")
        out(f"复用现有帧 {len(paths)} 张")
    else:
        times = keyframe_times(ffprobe, video)
        src = f"关键帧 {len(times)}"
        # 关键帧常受长 GOP 影响严重不足（15 秒片可能只有 2 个 I 帧），
        # 这时补均匀抽样，保证层级统计有足够样本。
        if len(times) < args.max_frames:
            merged = sorted(set(times) | set(uniform_times(meta["duration"], args.max_frames)))
            dedup = [merged[0]]
            for t in merged[1:]:
                if t - dedup[-1] > 0.25:
                    dedup.append(t)
            times = dedup
            src += f" + 均匀补样 → {len(times)}"
        times = pick_times(times, args.max_frames)
        out(f"抽帧 {len(times)} 张（{src}）")
        paths = extract_frames(ffmpeg, video, times, outdir / "frames")
    if not paths:
        raise SystemExit("没有可用帧，检查视频是否可解码（HEVC 需 ffmpeg ≥5）")

    # --frames 模式没有容器可探测，规格从首帧图像反推，否则画幅会误报
    if not meta["width"]:
        with Image.open(paths[0][1]) as _im:
            w0, h0 = _im.size
        meta.update({"width": w0, "height": h0, "codec": "（帧目录）",
                     "aspect": round(w0 / h0, 4) if h0 else 0, "fps_expr": "—"})
        out(f"规格取自首帧 {w0}x{h0}")

    per_frame, bgs, pals = [], [], []
    for t, p in paths:
        im = Image.open(p).convert("RGB")
        bgs.append(border_bg(im))
        pals.append(palette(im))
        per_frame.append(text_rows(im, args.safe_top, args.safe_bottom))

    med = tuple(int(statistics.median([c[i] for c in bgs])) for i in range(3))
    palette_sum = {}
    for pal in pals:
        for hx, pct in pal:
            palette_sum[hx] = palette_sum.get(hx, 0) + pct
    top_pal = sorted(palette_sum.items(), key=lambda kv: -kv[1])[:8]
    n_frames = len(pals)
    top_pal = [(hx, round(v / n_frames, 2)) for hx, v in top_pal]

    im0 = Image.open(paths[0][1]).convert("RGB")
    bands = band_metrics(im0, args.safe_top, args.safe_bottom)
    tiers = cluster_tiers(per_frame, n_frames)

    # 规范符合性检查：只判「能测的」，测不了的（AIGC 标识位语义）留给视觉模型
    checks = []
    sz_top, sz_bot = args.safe_top, args.safe_bottom
    top_rows = [t for t in tiers if t["zone"] == "top"]
    mid_cap = max((t["cap_pct"] for t in tiers if t["zone"] == "mid"), default=0)
    bot = [t for t in tiers if t["zone"] == "bottom"]
    aspect = meta["aspect"]

    if abs(aspect - 0.5625) < 0.02:
        checks.append({"level": "ok", "item": "画幅", "detail": f"{meta['width']}×{meta['height']}，标准 9:16"})
    else:
        checks.append({"level": "warn", "item": "画幅",
                       "detail": f"宽高比 {aspect}，非 9:16（0.5625）"})

    bg_l = lum(med)
    bgd = dist(med, to_rgb(BASE_BG))
    if bg_l >= 60:
        checks.append({"level": "warn", "item": "底色", "detail": f"亮度 {round(bg_l, 1)}，非深色底，与暖黑金线不符"})
    elif bgd < 30:
        checks.append({"level": "ok", "item": "底色", "detail": f"{hexc(med)}，与基准 {BASE_BG} 距离 {round(bgd, 1)}"})
    else:
        checks.append({"level": "info", "item": "底色",
                       "detail": f"{hexc(med)} 为深色，但与基准 {BASE_BG} 距离 {round(bgd, 1)}，确认是否有意换底"})

    if top_rows:
        t = top_rows[0]
        checks.append({"level": "ok", "item": "顶部进度条区",
                       "detail": f"检出文字块 {t['y0_pct']}%–{t['y1_pct']}%（块高 {t['cap_pct']}%，"
                                 f"≈{round(t['cap_pct'] * 19.2)}px；块高含行距，非单行字高）"})
    else:
        checks.append({"level": "info", "item": "顶部进度条区",
                       "detail": f"顶部 {sz_top}% 内无 ≥1.6% 帽高的文字行带。"
                                 "字幕以外的文字角色由视觉模型核验（见 §6）。"})

    if not bot:
        checks.append({"level": "warn", "item": "底部字幕", "detail": f"底部 {sz_bot}% 安全带内未检测到字幕行带"})
    elif bot[0]["y1_pct"] > 97:
        checks.append({"level": "warn", "item": "底部字幕",
                       "detail": f"字幕下沿 {bot[0]['y1_pct']}% 贴底，可能撞抖音底栏标题区"})
    elif bot[0]["cap_pct"] * 19.2 < 36:
        checks.append({"level": "info", "item": "底部字幕",
                       "detail": f"字幕帽高 ≈{round(bot[0]['cap_pct'] * 19.2)}px 偏小，小屏可读性需复核"})
    else:
        checks.append({"level": "ok", "item": "底部字幕",
                       "detail": f"行带 {bot[0]['y0_pct']}%–{bot[0]['y1_pct']}%（帽高 ≈{round(bot[0]['cap_pct'] * 19.2)}px），留在安全带内"})

    if mid_cap > 8:
        checks.append({"level": "info", "item": "中部主体",
                       "detail": f"帽高 {mid_cap}%（≈{round(mid_cap * 19.2)}px），确认是否遮挡画布主体"})
    else:
        checks.append({"level": "ok", "item": "中部主体",
                       "detail": f"最大帽高 {mid_cap}%，未压满画面"})

    if len(tiers) >= 3:
        ratio = tiers[0]["cap_pct"] / (tiers[-1]["cap_pct"] or 1)
        checks.append({"level": "ok", "item": "字号层级",
                       "detail": f"{len(tiers)} 级，L1/L{len(tiers)} = {ratio:.2f}×，层级分明"})
    elif len(tiers) == 2:
        checks.append({"level": "info", "item": "字号层级",
                       "detail": "仅 2 级，标题与字幕接近同级，检查是否有意扁平化"})
    elif len(tiers) == 1:
        checks.append({"level": "info", "item": "字号层级", "detail": "只检出 1 级，样本可能以图形为主"})
    else:
        checks.append({"level": "warn", "item": "字号层级",
                       "detail": "未检出稳定文字行带；若画面确有文字，多为字号过小或与底色对比不足"})

    # 三段式切分校准：顶部 12% 通常只放刊头细字，真正决定 safe_top 的是最大字号层（标题）的上沿。
    # 用所有层级里的最上沿会误取到刊头，把 safe_top 越调越小，切分就失去意义了。
    if tiers:
        main_tier = tiers[0]                      # tiers 按帽高降序，L1 即最大字号层
        top_y = main_tier["y0_pct"]
        if abs(top_y - sz_top) > 2:
            checks.append({"level": "info", "item": "三段式切分",
                           "detail": f"最大字号层 {main_tier['tier']}（帽高 {main_tier['cap_pct']}%）上沿在 "
                                     f"{top_y}%，与配置的顶部线 {sz_top}% 差 {round(abs(top_y - sz_top), 1)} 个点；"
                                     f"若要按标题切分，建议 --safe-top {top_y:.0f}"})
        else:
            checks.append({"level": "ok", "item": "三段式切分",
                           "detail": f"标题上沿 {top_y}%，与顶部线 {sz_top}% 吻合"})

    sheet = contact_sheet(paths, outdir / "contact_sheet.png")

    return {
        "source": str(video),
        "meta": meta,
        "frames_analyzed": n_frames,
        "bg_hex": hexc(med),
        "bg_rgb": list(med),
        "bg_lum": round(lum(med), 1),
        "is_dark": lum(med) < 60,
        "bg_vs_base": {"base": BASE_BG, "distance": round(dist(med, to_rgb(BASE_BG)), 1)},
        "palette": [{"hex": h, "pct": p, "vs_gold": round(dist(to_rgb(h), to_rgb(BASE_GOLD)), 1)}
                    for h, p in top_pal],
        "safe_zone": {"top_pct": args.safe_top, "bottom_pct": args.safe_bottom,
                      "bands": bands},
        "text_tiers": tiers,
        "checks": checks,
        "contact_sheet": str(sheet) if sheet else None,
    }


# ---------------------------------------------------------------- 语义回填

def semantics_request(r, outdir):
    """生成给视觉模型的结构化提问包：各层 bbox + 判据常量 + 回复 schema。

    脚本测不出「哪层是标题、有没有 AIGC 标识、中文是衬线还是黑体」，
    但这些判断都有客观判据。把判据和 bbox 一起写进请求包，让视觉模型照着答，
    再用 --semantics 回填，就不用每次靠人回忆 AGENTS.md 的条款。
    """
    tiers = []
    for t in r["text_tiers"]:
        tiers.append({
            "tier": t["tier"],
            "zone": t["zone"],
            "cap_pct": t["cap_pct"],
            "cap_px_at_1920": round(t["cap_pct"] / 100 * 1920),
            "y_range_pct": [t["y0_pct"], t["y1_pct"]],
            "role": "",          # 留给视觉模型填
        })
    sheet = r.get("contact_sheet")
    req = {
        "produced_by": "TOOL/style_brief.py",
        "source": r["source"],
        "contact_sheet": sheet,
        "frames_dir": str(Path(sheet).parent / "frames") if sheet else None,
        "measured": {
            "bg_hex": r["bg_hex"],
            "resolution": f"{r['meta']['width']}x{r['meta']['height']}",
            "text_tiers": tiers,
            "safe_zone": r["safe_zone"],
        },
        "judgement_rules": {
            "accent_max_count": ACCENT_MAX_COUNT,
            "avoid_list": AVOID_LIST,
            "aigc_style": "画面只检查是否有烧录标识。AI 内容声明由发布平台提供",
            "allowed_layers": ["顶部极简章节进度条", "中部核心画布", "低透明环境微动装饰",
                               "底部字幕", "片尾短暂显示的矢量徽标"],
            "zh_typeface": "中文系统衬线；等宽只给数字与代码；拉丁 Times New Roman Italic",
        },
        "reply_schema": {
            "by": "谁判定的",
            "date": "YYYY-MM-DD",
            "font": {"family": "无衬线（黑体）/ 衬线 / 等宽 / 混排",
                     "weight": "", "letter_spacing": "", "align": {}, "notes": ""},
            "tier_roles": {"L1": "悬念标题 / 底部字幕 / 章节进度条 / 强调数字 / 其他"},
            "aigc_label": {"present": False, "text": "", "issues": []},
            "accent": {"count": 0, "where": []},
            "avoid_hits": [],
            "deviations": [{"clause": "§4.2", "item": "", "observed": ""}],
            "verdict": "一句话结论",
        },
        "how_to_reply": ("只回一个符合 reply_schema 的 JSON。看完 contact_sheet.png"
                         "（必要时看 frames/ 单帧）后执行 "
                         "python TOOL/style_brief.py --out <本目录> --semantics <该 JSON> 回填。"),
    }
    p = Path(outdir) / "semantics_request.json"
    p.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def render_semantics(sem, r):
    """§6：有视觉判定就出结论表，没有就出结构化提问包指引。"""
    L = []
    if not sem:
        sheet = r.get("contact_sheet")
        outdir = str(Path(sheet).parent) if sheet else "."
        L.append("## 6. 待视觉模型判定（脚本不猜）")
        L.append("")
        L.append("脚本已生成 `semantics_request.json`：内含各层 bbox、判据常量"
                 f"（画面白名单、强调色 ≤{ACCENT_MAX_COUNT} 处、Avoid 清单）与回复 schema。")
        L.append("把它和 `contact_sheet.png` 一起交给视觉模型，按 schema 回答后回填：")
        L.append("")
        L.append("```powershell")
        L.append(f'python TOOL/style_brief.py --out "{outdir}" --semantics semantics.json')
        L.append("```")
        L.append("")
        L.append("需要模型回答的 5 件事：")
        L.append("")
        L.append("1. 各层级里哪一层是**悬念标题**、哪一层是**字幕**、哪一层是**强调数字**；")
        L.append("2. 是否存在烧录的 **AIGC 标识**。AI 内容声明由发布平台提供。")
        L.append("3. 中文字体是**衬线**还是**无衬线**（§4.2 要求中文系统衬线，等宽只给数字）；")
        L.append("4. 强调色出现次数（§4.2 要求全片 ≤4 处）；")
        L.append("5. 是否超出画面白名单或命中 `Avoid` 清单，检查防御性标注、角标和文献年份小卡。")
        L.append("")
        return L

    L.append("## 6. 视觉判定结论")
    L.append("")
    L.append(f"> 判定方：{sem.get('by') or '视觉模型'} · {sem.get('date') or '—'} · "
             f"依据 `contact_sheet.png` 与 `frames/`")
    L.append("")

    roles = sem.get("tier_roles") or {}
    if r["text_tiers"]:
        L.append("### 6.1 层级角色映射")
        L.append("")
        L.append("| 层级 | 区 | 帽高 | 纵向位置 | 语义角色 |")
        L.append("|---|---|---:|---|---|")
        for t in r["text_tiers"]:
            px = round(t["cap_pct"] / 100 * 1920)
            L.append(f"| {t['tier']} | {t['zone']} | {t['cap_pct']}%（≈{px}px） | "
                     f"{t['y0_pct']}%–{t['y1_pct']}% | {roles.get(t['tier']) or '—'} |")
        L.append("")

    f = sem.get("font") or {}
    if f:
        L.append("### 6.2 字体")
        L.append("")
        L.append("| 项 | 判定 |")
        L.append("|---|---|")
        for k, label in (("family", "字体族"), ("weight", "字重"), ("letter_spacing", "字距")):
            if f.get(k):
                L.append(f"| {label} | {f[k]} |")
        al = f.get("align") or {}
        if al:
            L.append(f"| 对齐 | {'；'.join(f'{k}={v}' for k, v in al.items())} |")
        if f.get("notes"):
            L.append(f"| 备注 | {f['notes']} |")
        L.append("")

    a = sem.get("aigc_label") or {}
    if a:
        L.append("### 6.3 画面内的 AIGC 标识")
        L.append("")
        L.append("| 项 | 实测 | 要求（§4.3） | 判定 |")
        L.append("|---|---|---|---|")
        present = bool(a.get("present"))
        L.append(f"| 是否烧录 | {'是' if present else '否'} | 由发布平台声明 | "
                 f"{'⚠' if present else '✓'} |")
        if present and a.get("text"):
            L.append(f"| 文字 | {a['text']} | — | — |")
        if a.get("issues"):
            L.append("")
        for it in (a.get("issues") or []):
            L.append(f"- ⚠ {it}")
        L.append("")

    ac = sem.get("accent") or {}
    av = sem.get("avoid_hits")
    if ac or av is not None:
        L.append("### 6.4 强调色与 Avoid 清单")
        L.append("")
        if ac:
            cnt = ac.get("count")
            tail = ""
            if isinstance(cnt, int):
                tail = " ✓" if cnt <= ACCENT_MAX_COUNT else " ⚠ 超限"
            L.append(f"- **强调色出现**：{cnt if cnt is not None else '—'} 处"
                     f"（§4.2 上限 {ACCENT_MAX_COUNT} 处）{tail}")
            for w in (ac.get("where") or []):
                L.append(f"  - {w}")
        if av:
            L.append(f"- **Avoid 命中**：{len(av)} 项")
            for x in av:
                L.append(f"  - ⚠ {x}")
        elif av is not None:
            L.append("- **Avoid 清单**：未命中 ✓")
        L.append("")

    L.append("### 6.5 与 AGENTS.md 的偏差")
    L.append("")
    dev = sem.get("deviations") or []
    if dev:
        L.append("| 条款 | 项 | 实测 |")
        L.append("|---|---|---|")
        for d in dev:
            L.append(f"| {d.get('clause', '—')} | {d.get('item', '—')} | {d.get('observed', '—')} |")
    else:
        L.append("未发现偏差。")
    L.append("")
    if sem.get("verdict"):
        L.append(f"**结论**：{sem['verdict']}")
        L.append("")
    return L


def render_md(r, ffmpeg_ver, note, sem=None):
    L = []
    m = r["meta"]
    L.append("# style_brief")
    L.append("")
    L.append(f"> 由 `TOOL/style_brief.py` 自动生成 · 样本 `{Path(r['source']).name}` · "
             f"{r['frames_analyzed']} 帧 · ffmpeg {ffmpeg_ver}")
    if sem:
        L.append("> 几何与颜色为脚本实测；语义判定（层级角色、字体、AIGC 标识）"
                 "由视觉模型回填，见 §6。")
    else:
        L.append("> 本文件只报告**可测量**的视觉参数；语义判断（谁是大标题、谁是强调数字）"
                 "见文末「待视觉模型判定」。")
    L.append("")
    L.append("## 1. 素材规格")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append(f"| 分辨率 | {m['width']}×{m['height']}（{m['aspect']}） |")
    L.append(f"| 编码 / 时长 | {m['codec']} / {m['duration']}s |")
    L.append(f"| 帧率 | {m['fps_expr']} |")
    L.append(f"| 画幅判定 | {'竖屏 9:16 ✓' if abs(m['aspect'] - 0.5625) < 0.02 else '非标准 9:16'} |")
    L.append("")

    L.append("## 2. 色彩")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    d = r["bg_vs_base"]["distance"]
    judge = "与基准一致" if d < 12 else ("接近" if d < 30 else "偏离，需复核")
    L.append(f"| 背景色 HEX | **{r['bg_hex']}** `rgb{tuple(r['bg_rgb'])}` |")
    L.append(f"| 背景亮度 | {r['bg_lum']} / 255 → {'深色底 ✓' if r['is_dark'] else '亮底（与暖黑金线不符）'} |")
    L.append(f"| 对基准 {BASE_BG} | RGB 距离 {d} · {judge} |")
    L.append("")
    L.append("| 色板（按面积） | 占比 | 对基准金 {0} 距离 |".format(BASE_GOLD))
    L.append("|---|---:|---:|")
    for p in r["palette"]:
        L.append(f"| `{p['hex']}` | {p['pct']}% | {p['vs_gold']} |")
    L.append("")

    sz = r["safe_zone"]
    L.append(f"## 3. 三段式安全区（顶 {sz['top_pct']}% / 中 {round(100 - sz['top_pct'] - sz['bottom_pct'], 1)}% / 底 {sz['bottom_pct']}%）")
    L.append("")
    L.append("| 区 | 高度占比 | 平均亮度 | 暗部占比 | 亮部占比 | 边缘密度 | 判读 |")
    L.append("|---|---:|---:|---:|---:|---:|---|")
    names = {"top": "顶部（章节进度条）", "mid": "中部（核心画布）", "bottom": "底部（字幕安全带）"}
    for k in ("top", "mid", "bottom"):
        b = sz["bands"][k]
        ed = b["edge_density"]
        note_k = "空白" if ed < 2 else ("稀疏（小号标签/细线）" if ed < 6 else "信息密集")
        L.append(f"| {names[k]} | {b['height_pct']}% | {b['mean_lum']} | {b['dark_ratio']}% | "
                 f"{b['bright_ratio']}% | {ed} | {note_k} |")
    L.append("")

    L.append("## 4. 文字层级阶梯（帽高 / 块高近似）")
    L.append("")
    if r["text_tiers"]:
        base = r["text_tiers"][0]["cap_pct"] or 1
        L.append("| 层级 | 区 | 帽高占比 | 折合 1080×1920 像素 | 纵向位置 | 出现帧占比 | 稳定性 |")
        L.append("|---|---|---:|---:|---|---:|---|")
        for t in r["text_tiers"]:
            px = round(t["cap_pct"] / 100 * 1920)
            ratio = t["cap_pct"] / base
            L.append(f"| {t['tier']} | {t['zone']} | {t['cap_pct']}%"
                     f"（对 L1 为 {ratio:.2f}×） | ≈{px}px | "
                     f"{t['y0_pct']}%–{t['y1_pct']}% | {t['presence_pct']}% | {t['stability']} |")
    else:
        L.append("未检测到稳定文字行带（纯图形画面或文字过小）。")
    L.append("")
    L.append("> 帽高 ≠ 字号。中文字号约为帽高的 1.35–1.45 倍；"
             "同一层级跨帧波动 >15% 通常是入场动画未收敛，建议改用中段帧复核。")
    L.append("> 同区内的**多行文字块**会被合成一条带，"
             "此时数值是块高而非单行字高；语义角色见 §6。")
    L.append("")

    L.append("## 5. 规范符合性检查")
    L.append("")
    mark = {"ok": "✓", "warn": "⚠", "info": "·"}
    for c in r["checks"]:
        L.append(f"- {mark.get(c['level'], '·')} **{c['item']}**：{c['detail']}")
    L.append("")

    L.extend(render_semantics(sem, r))
    L.append("## 7. 复现")
    L.append("")
    L.append("```powershell")
    L.append(f"python TOOL/style_brief.py --video \"{r['source']}\"")
    L.append("```")
    L.append("")
    L.append(f"ffmpeg 来源：{note}")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="从成片反推视觉规范，产出 style_brief.md")
    ap.add_argument("--video", help="输入视频")
    ap.add_argument("--frames", help="已有帧目录（跳过抽帧）")
    ap.add_argument("--out", help="输出目录，默认 <视频名>_style/")
    ap.add_argument("--max-frames", type=int, default=10, help="最多分析帧数，默认 10")
    ap.add_argument("--safe-top", type=float, default=DEFAULT_TOP_PCT, help="顶部保留区百分比")
    ap.add_argument("--safe-bottom", type=float, default=DEFAULT_BOTTOM_PCT, help="底部安全区百分比")
    ap.add_argument("--ffmpeg", help="ffmpeg 所在目录或可执行文件")
    ap.add_argument("--semantics", help="视觉判定 JSON；回填 §6 并重写报告")
    args = ap.parse_args()

    # 仅回填模式：给了 --semantics 但没给视频/帧目录，直接吃目录里已有的 style_brief.json，
    # 不重新抽帧。视觉模型判完只需回填，不必把视频再算一遍。
    if args.semantics and not args.video and not args.frames:
        if not args.out:
            ap.error("仅回填时必须用 --out 指向已有分析目录")
        od = Path(args.out)
        js = od / "style_brief.json"
        if not js.exists():
            raise SystemExit(f"{js} 不存在，先完整跑一次分析")
        res = json.loads(js.read_text(encoding="utf-8"))
        sem_in = json.loads(Path(args.semantics).read_text(encoding="utf-8"))
        res["semantics"] = sem_in
        js.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        (od / "style_brief.md").write_text(
            render_md(res, res.get("ffmpeg_ver") or "—", "（回填模式，未重新抽帧）", sem_in),
            encoding="utf-8")
        out(f"已回填 §6 -> {od / 'style_brief.md'}")
        return

    if not args.video and not args.frames:
        ap.error("--video 或 --frames 至少要给一个")

    ffmpeg, ffprobe, major, note = locate_tools(args.ffmpeg)
    if major and major < MIN_FFMPEG_MAJOR:
        out(f"⚠ ffmpeg 主版本 {major} < {MIN_FFMPEG_MAJOR}：不支持 HEVC 解码，"
            f"ffprobe 字段也可能是 pkt_pts_time。建议 winget install Gyan.FFmpeg")
    out(f"ffmpeg {major}（{note}）")

    video = Path(args.video).resolve() if args.video else None
    if video and not video.exists():
        raise SystemExit(f"视频不存在: {video}")
    outdir = Path(args.out) if args.out else (
        video.parent / f"{video.stem}_style" if video else Path("style_out"))
    outdir.mkdir(parents=True, exist_ok=True)

    result = analyze(video or Path(args.frames), outdir, args, ffmpeg, ffprobe)
    sem = None
    if args.semantics:
        sem = json.loads(Path(args.semantics).read_text(encoding="utf-8"))
        result["semantics"] = sem
    (outdir / "style_brief.json").write_text(
        json.dumps(dict(result, ffmpeg_ver=major), ensure_ascii=False, indent=2), encoding="utf-8")
    req = semantics_request(result, outdir)
    (outdir / "style_brief.md").write_text(
        render_md(result, major, note, sem), encoding="utf-8")

    out("")
    warns = sum(1 for c in result["checks"] if c["level"] == "warn")
    out(f"背景色 {result['bg_hex']} | 层级 {len(result['text_tiers'])} 级 | 告警 {warns} 项")
    out(f"-> {outdir / 'style_brief.md'}")
    out(f"-> {outdir / 'style_brief.json'}")
    out(f"-> {req}（交给视觉模型，回答后用 --semantics 回填）")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
