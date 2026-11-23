"""Collect native visual evidence from the episode's registered full Composition."""
import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from delivery_check import original_frames, require
from episode import ROOT, bindings, film_name, plan, read, sha256_file, within
from profile_loader import load_profile


FACES = (
    ("Source Serif 4", "400", "SourceSerif4-Regular.ttf.woff2"),
    ("Source Serif 4", "600", "SourceSerif4-Semibold.ttf.woff2"),
    ("ChillJinshuSong", "400", "ChillJinshuSongRegular.woff"),
    ("ChillJinshuSong", "700", "ChillJinshuSongBold.woff"),
    ("Noto Sans SC", "400", "NotoSansSC-Regular.otf"),
    ("Noto Sans SC", "500", "NotoSansSC-Medium.otf"),
    ("JetBrains Mono", "400", "JetBrainsMono-Regular.woff2"),
    ("JetBrains Mono", "500", "JetBrainsMono-Medium.woff2"),
)


def montage(frames, frame_file, output, tile_width, columns):
    with Image.open(frame_file(frames[0])) as source:
        height = round(tile_width * source.height / source.width)
    columns = min(columns, len(frames))
    rows = (len(frames) + columns - 1) // columns
    gap = 12
    sheet = Image.new("RGB", (columns * (tile_width + gap) - gap, rows * (height + gap) - gap), "#131B23")
    for index, frame in enumerate(frames):
        with Image.open(frame_file(frame)) as source:
            tile = source.convert("RGB").resize((tile_width, height), Image.Resampling.LANCZOS)
        sheet.paste(tile, (index % columns * (tile_width + gap), index // columns * (height + gap)))
    sheet.save(output)


def preview_metrics(movie, profile, count, lighting):
    video, visual = profile.hard["video"], profile.hard["visual"]
    scale, fps = video["previewScale"], video["previewFps"]
    width, height = (round(video[k] * scale) for k in ("width", "height"))
    stride = fps // visual["motionHz"]
    roi = slice(*(round(y * scale) for y in visual["roiY"]))
    cap = cv2.VideoCapture(str(movie))
    previous = None
    share = longest = run = 0
    try:
        require(abs(cap.get(cv2.CAP_PROP_FPS) - fps) < 1e-6, "快审帧率")
        for frame in range(count):
            ok, image = cap.read()
            require(ok and image.shape == (height, width, 3), f"快审画幅或帧数 {frame}")
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            share += np.mean(gray < visual["darkBelow"] if lighting == "studio_dark"
                             else gray > visual["lightAbove"])
            if frame % stride == 0:
                current = gray[roi]
                if previous is not None:
                    run = run + 1 if cv2.absdiff(current, previous).mean() < visual["roiDelta"] else 0
                    longest = max(run, longest)
                previous = current
        require(not cap.read()[0], "快审多余帧")
    finally:
        cap.release()
    return {"width": width, "height": height, "fps": fps, "frames": count,
            "lightPct": float(share * 100 / count), "roiLongestSec": longest / visual["motionHz"]}


def layout_measurements(dom, spec, profile):
    expected = {(name, weight, "loaded") for name, weight, _ in FACES}
    readings = {str(n) for frames in spec["timeline"]["reading"].values() for n in frames}
    left, top, right, bottom = profile.hard["visual"]["safeZone"]
    boxes = {}
    for frame, row in dom["frames"].items():
        loaded = {(face["family"], face["weight"], face["status"]) for face in row["faces"]}
        require(expected <= loaded, f"本地字体未完整实装 {frame}: 缺 {sorted(expected - loaded)}，实测 {sorted(loaded)}")
        require(frame not in readings or row["boxes"], f"缺少阅读窗静态文字框 {frame}")
        if frame in readings:
            for item in row["boxes"]:
                x, y, r, b = item["box"]
                require(item["opacity"] == 1 and item["stationary"] and
                        left <= x < r <= right and top <= y < b <= bottom, f"静态文字或安全区 {frame}")
        boxes[frame] = [item["box"] for item in row["boxes"]]
    public = Path(spec["publicDir"])
    fonts = [{"family": name, "weight": weight, "file": file, "status": "loaded",
              "sha256": sha256_file(within(public, Path("fonts") / file))}
             for name, weight, file in FACES]
    return boxes, fonts


def collect_evidence(mode, ep, work, *, cover_frame, still_frames, phone_frames=None, check=None):
    """Run the standard pipeline. check(dom_frames, full_plan) may raise or return details."""
    ep, work = Path(ep).resolve(), Path(work).resolve()
    require(mode in ("preview", "full") and work.parent == within(ep, ".work"), "取证模式或 run 路径")
    preview = mode == "preview"
    picture = within(work, "picture.mp4")
    movie = within(ep, "src/review/preview.mp4") if preview else within(work, Path("delivery") / ep.name / film_name(ep))
    receipt = read(within(work, "receipt.json"))
    spec = plan(ep, "full")
    profile = load_profile(spec["profile_id"], expected=spec["profile_sha256"])
    media = sha256_file(movie)
    picture_digest = sha256_file(picture)
    require(receipt["run"] == work.name and receipt["approved"] == bindings(ep, "review")
            and media == receipt["media"] and picture_digest == receipt["picture"], "本次取证来源")
    require(all(receipt.get(key) == value for key, value in profile.stamp.items()), "取证档案")
    timeline = spec["timeline"]
    contact_frames = [frames[1] for frames in timeline["reading"].values()]
    require(set(still_frames) == {"prop", "trail", "climax"}, "快审静帧名")
    if phone_frames is None:
        phone_frames = list(dict.fromkeys([*still_frames.values(), *contact_frames[:2], cover_frame]))
    frames = sorted({*timeline["frames"], *still_frames.values(), *phone_frames, cover_frame})
    require(phone_frames and all(type(n) is int and 0 <= n < spec["frames"] for n in frames), "取证帧越界")
    native = set(timeline["frames"])
    if not preview:
        for frame in native:
            require(receipt["frames"].get(str(frame)) == sha256_file(within(work, f"frame-{frame}.png")),
                    f"原始 PNG 摘要 {frame}")
    with tempfile.TemporaryDirectory(prefix="evidence-", dir=work, ignore_cleanup_errors=True) as folder:
        scratch = Path(folder)
        config = scratch / "capture.json"
        config.write_text(json.dumps({"plan": spec, "frames": frames,
                                      "pngFrames": frames if preview else sorted(set(frames) - native)}), "utf-8")
        try:
            subprocess.run(["node", str(Path(__file__).with_name("collect_evidence.cjs")), str(config)],
                           cwd=ROOT, check=True, timeout=120 + 3 * len(frames))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            for name in ("chrome-launch.json", "chrome-stderr.log"):
                if (scratch / name).is_file():
                    shutil.copyfile(scratch / name, work / ("evidence-" + name))
            raise
        dom = read(scratch / "dom.json")
        require(set(dom["frames"]) == set(map(str, frames)), "DOM 取证帧覆盖")
        boxes, fonts = layout_measurements(dom, spec, profile)
        score = spec["inputProps"]["score"]
        original = original_frames(scratch if preview else work, score, boxes, profile, spec["applied_overrides"])
        details = check(dom["frames"], spec) if check else None

        def frame_file(n):
            return (work if not preview and n in native else scratch) / f"frame-{n}.png"

        if preview:
            report = read(movie.with_name("preview_mix_report.json"))
            audio, visual = profile.hard["audio"], profile.hard["visual"]
            metrics = preview_metrics(movie, profile, plan(ep, "preview")["frames"], score["lighting"])
            low, high = visual["lighting"][score["lighting"]]
            checks = {
                "lighting": low <= metrics["lightPct"] <= high,
                "motion": metrics["roiLongestSec"] <= visual["maxStaticSec"],
                "mix": media == report["media_sha256"]
                and report["true_peak_dbtp"] <= audio["truePeakMax"]
                and report["bgm_gap_check"]["pass"] is True,
            }
            require(all(checks.values()), f"快审证据 {checks}")
            for name, frame in still_frames.items():
                shutil.copyfile(frame_file(frame), scratch / f"{name}.png")
            montage(phone_frames, frame_file, scratch / "phone.png", 360, 3)
            copies = ["prop.png", "trail.png", "climax.png", "phone.png"]
            report_name, dest = "preview_qc.json", movie.parent
            stop = math.ceil(metrics["frames"] * spec["fps"] / metrics["fps"])
            result = {"media_sha256": media, "passed": True, "checks": checks,
                      "media": metrics, "fonts": {"families": 4, "files": 8, "faces": fonts},
                      "reading": {"beats": original["reading"]},
                      "seams": {"preview": [row for row in original["seams"] if row["frames"][1] < stop],
                                "native_full_timeline": original["seams"]},
                      "lighting": {"mode": score["lighting"], "decodedPreviewPct": metrics["lightPct"]},
                      "motion": {"roiLongestSec": metrics["roiLongestSec"]},
                      "sound": {"lufs": report["integrated_lufs"], "truePeakDbtp": report["true_peak_dbtp"]},
                      "stillFrames": still_frames, "phoneFrames": phone_frames}
        else:
            shutil.copyfile(frame_file(cover_frame), scratch / "cover.png")
            montage(contact_frames, frame_file, scratch / "contact_sheet.png", 240, 6)
            copies = ["cover.png", "contact_sheet.png"]
            report_name, dest = "layout.json", work
            result = {"picture_sha256": picture_digest, "media_sha256": media, "passed": True,
                      "issues": [], "boxes": boxes, "dom": {"browser": dom["browser"], "fonts": fonts},
                      "safeZone": {"rectPx": profile.hard["visual"]["safeZone"], "passed": True},
                      "coverFrame": cover_frame, "contactFrames": contact_frames, "nativeAudit": original}
        result["stills"] = {name: sha256_file(scratch / name) for name in copies}
        if details is not None:
            result["details"] = details
        (scratch / report_name).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), "utf-8")
        for name in [*copies, report_name]:
            os.replace(scratch / name, dest / name)
    return result


def main(*, cover_frame=None, still_frames=None, phone_frames=None, check=None, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("preview", "full"))
    parser.add_argument("--episode", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    if cover_frame is None:
        parser.add_argument("--cover", required=True, type=int)
    if still_frames is None:
        for name in ("prop", "trail", "climax"):
            parser.add_argument("--" + name, required=True, type=int)
    args = parser.parse_args(argv)
    if still_frames is None:
        still_frames = {name: getattr(args, name) for name in ("prop", "trail", "climax")}
    collect_evidence(args.mode, args.episode, args.work, cover_frame=args.cover if cover_frame is None else cover_frame,
                     still_frames=still_frames, phone_frames=phone_frames, check=check)


if __name__ == "__main__":
    main()
