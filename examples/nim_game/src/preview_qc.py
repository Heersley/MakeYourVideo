"""Encode and measure the B01–B07 preview and inspect B25 and B28–B29 in Chromium."""

import argparse
import hashlib
import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from bounds import PROJECT, inspect_layout, locate_ffmpeg, reading_bounds, reading_frames

SOURCE = Path(__file__).resolve().parent
EPISODE = SOURCE.parent
REVIEW = EPISODE / "review"
FPS, COUNT = 30, 1044
WIDTH, HEIGHT = 540, 960
MOTION_THRESHOLD = 0.15
LOCKED = {
    "beats.json": "c4aba7c3ee99062e0758c18e4b502bcd70a46383e53bc892633a2b3a0ae708f2",
    "facts_and_sources.md": "8592776daa9498b907972de8a16db2bae350210e3b9935faf6f8a6d2d205c690",
    "src/sfx_mix.wav": "4bb71161b4f754a739913a00024e2532a8f44b6efc67029dc2390430f06bc628",
}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_locked_sources():
    hashes = {}
    for name, expected in LOCKED.items():
        with (EPISODE / name).open("rb") as file:
            observed = hashlib.file_digest(file, "sha256").hexdigest()
        if observed != expected:
            raise ValueError(f"Locked input changed: {name}; SHA-256 {observed}")
        hashes[name] = observed
    return hashes


def pinned_tools():
    """跨平台定位 ffmpeg/ffprobe（FFMPEG_BIN → WinGet → PATH），不再硬编码 WinGet 路径。"""
    return locate_ffmpeg()


def contact_sheet_font(size=15):
    """等宽字体：逐个候选尝试，全部失败时安全回落到 Pillow 内置位图字体。"""
    candidates = (
        "C:/Windows/Fonts/consola.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, ValueError):
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def frame_number(seconds, fps=FPS):
    return round(seconds * fps)


def read_sequence(work):
    files = sorted((work / "frames").glob("element-*.png"))
    if [int(path.stem.removeprefix("element-")) for path in files] != list(range(COUNT)):
        raise ValueError(f"Expected a contiguous sequence of {COUNT} original PNGs: {work}")
    return files


def encode_preview(files, ffmpeg, work):
    digits = len(files[0].stem.removeprefix("element-"))
    target = work / "stage1_preview.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", str(FPS), "-start_number", "0",
            "-i", files[0].parent / f"element-%0{digits}d.png",
            "-i", SOURCE / "sfx_mix.wav", "-map", "0:v:0", "-map", "1:a:0",
            "-t", str(COUNT / FPS), "-c:v", "libx264", "-profile:v", "high",
            "-level:v", "4.2", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "slow",
            "-g", str(FPS * 2), "-c:a", "aac", "-b:a", "256k",
            "-movflags", "+faststart", "-metadata", "comment=AI-assisted mathematical animation",
            target,
        ],
        check=True,
    )
    return target


def read_png(path):
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape != (HEIGHT, WIDTH, 3):
        raise ValueError(f"Not an unmodified {WIDTH}×{HEIGHT} PNG from the review render: {path}")
    return image


def measure_reading(files, beats, labels):
    rows = []
    scale = WIDTH / 1080
    for beat in beats:
        first, stop = reading_frames(beat, FPS)
        start_sec, end_sec, inclusive_end = reading_bounds(beat)
        if first >= stop or not labels[first]:
            raise ValueError(f"No text boxes in reading window B{beat['id']:02d}")
        reference = read_png(files[first])
        boxes = []
        geometry_changes = []
        for label in labels[first]:
            x, y, right, bottom = label["bounds"]
            left, top = max(0, math.floor(x * scale) - 1), max(0, math.floor(y * scale) - 1)
            end_x, end_y = min(WIDTH, math.ceil(right * scale) + 1), min(HEIGHT, math.ceil(bottom * scale) + 1)
            boxes.append({"text": label["text"], "bounds": [left, top, end_x, end_y], "maxRGBDelta": 0})
        for frame in range(first + 1, stop):
            if labels[frame] != labels[first]:
                geometry_changes.append(frame)
            image = read_png(files[frame])
            for box in boxes:
                x, y, end_x, end_y = box["bounds"]
                delta = int(cv2.absdiff(image[y:end_y, x:end_x], reference[y:end_y, x:end_x]).max())
                box["maxRGBDelta"] = max(box["maxRGBDelta"], delta)
        rows.append({
            "beat": f"B{beat['id']:02d}", "firstFrame": first, "endFrameExclusive": stop,
            "sourceWindowSec": [round(start_sec, 3), round(end_sec, 3)],
            "sourceWindowDurationSec": round(end_sec - start_sec, 3),
            "inclusiveEnd": inclusive_end,
            "actualSampleTimesSec": [round(first / FPS, 6), round((stop - 1) / FPS, 6)],
            "frameCount": stop - first, "boxes": boxes,
            "geometryChanges": geometry_changes,
            "text_box_diff": max(box["maxRGBDelta"] for box in boxes),
        })
    return rows


def analyze_video(path, files, beats):
    soft_seams = {
        frame_number(beat["startSec"]): beat for beat in beats[1:] if not beat["hardCut"]
    }
    representative = {0: {"beat": "B01", "sample": "opening"}}
    for beat in beats:
        first, stop = reading_frames(beat, FPS)
        representative[(first + stop) // 2] = {
            "beat": f"B{beat['id']:02d}", "sample": "reading",
        }
    representative[frame_number(9.0)] = {"beat": "B03", "sample": "rule detail"}
    representative[frame_number(33.26)] = {"beat": "B07", "sample": "upward retrieval"}
    capture = cv2.VideoCapture(str(path))
    dark, seams, samples, motion_deltas = [], [], [], []
    previous = previous_10fps = None
    try:
        for frame in range(COUNT):
            ok, image = capture.read()
            if not ok or image.shape != (HEIGHT, WIDTH, 3):
                raise ValueError(f"Could not decode video frame {frame}: {path}")
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            dark.append(float(np.mean(gray < 40) * 100))
            if frame in representative:
                samples.append({
                    **representative[frame], "frame": frame, "sec": frame / FPS,
                    "darkPct": dark[-1],
                })
            if frame in soft_seams:
                left, right = (read_png(files[index]) for index in (frame - 1, frame))
                raw_gray = cv2.absdiff(
                    cv2.cvtColor(left, cv2.COLOR_BGR2GRAY),
                    cv2.cvtColor(right, cv2.COLOR_BGR2GRAY),
                )
                seams.append({
                    "to": f"B{soft_seams[frame]['id']:02d}", "frame": frame, "sec": frame / FPS,
                    "seam_delta": float(cv2.absdiff(gray, previous).mean()),
                    "nativeSeamDelta": float(raw_gray.mean()),
                    "nativeMaxRGBDelta": int(cv2.absdiff(left, right).max()),
                })
            if frame % (FPS // 10) == 0:
                if previous_10fps is not None:
                    motion_deltas.append(float(cv2.absdiff(gray, previous_10fps).mean()))
                previous_10fps = gray
            previous = gray
        if capture.read()[0]:
            raise ValueError(f"More than {COUNT} preview frames: {path}")
    finally:
        capture.release()

    static_windows = []
    first = None
    for index, delta in enumerate([*motion_deltas, MOTION_THRESHOLD]):
        if delta < MOTION_THRESHOLD and first is None:
            first = index
        if delta >= MOTION_THRESHOLD and first is not None:
            static_windows.append({
                "startSec": first / 10, "endSec": index / 10, "durationSec": (index - first) / 10,
            })
            first = None
    longest = max((window["durationSec"] for window in static_windows), default=0)
    return {
        "dark": {
            "grayBelow": 40, "framesMeasured": len(dark), "meanPct": float(np.mean(dark)),
            "minPct": min(dark), "maxPct": max(dark), "keyFrames": samples,
        },
        "seams": seams,
        "motion": {
            "sampleFps": 10, "deltaThreshold": MOTION_THRESHOLD, "longestStaticSec": longest,
            "windowsOverLimit": [row for row in static_windows if row["durationSec"] > 1.2],
        },
    }


def probe_media(path, ffmpeg, ffprobe):
    result = json.loads(subprocess.check_output([
        ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path,
    ]))
    video, audio = [next(stream for stream in result["streams"] if stream["codec_type"] == kind)
                    for kind in ("video", "audio")]
    pcm = np.frombuffer(subprocess.check_output([
        ffmpeg, "-v", "error", "-i", path, "-map", "0:a:0", "-f", "f32le", "-",
    ]), dtype="<f4")
    peak = float(np.max(np.abs(pcm)))
    return {
        "width": video["width"], "height": video["height"], "frameCount": int(video["nb_frames"]),
        "fps": float(Fraction(video["r_frame_rate"])), "durationSec": float(video["duration"]),
        "profile": video["profile"], "level": video["level"], "pixelFormat": video["pix_fmt"],
        "codec": video["codec_name"], "audioCodec": audio["codec_name"],
        "audioChannels": audio["channels"], "audioSampleRate": int(audio["sample_rate"]),
        "audioPeakDbfs": 20 * math.log10(peak) if peak > 0 else None,
    }


def make_contact_sheet(path, files, samples):
    columns = 5
    width, height, margin, caption = 222, 394, 14, 26
    rows = math.ceil(len(samples) / columns)
    sheet = Image.new(
        "RGB", (margin + columns * (width + margin), margin + rows * (height + caption + margin)),
        "#101114",
    )
    draw = ImageDraw.Draw(sheet)
    font = contact_sheet_font(15)
    for index, sample in enumerate(samples):
        x = margin + index % columns * (width + margin)
        y = margin + index // columns * (height + caption + margin)
        with Image.open(files[sample["frame"]]) as image:
            sheet.paste(image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS), (x, y))
        text = f'{sample["beat"]}   {sample["sec"]:05.2f}s'
        draw.text((x, y + height + 5), text, font=font, fill="#C9A96A")
    sheet.save(path)


def make_trail_comparison(work):
    panels = [("B01", 213, "text_exit_03_55.png"), ("B02", 441, "text_exit_07_35.png")]
    composite = Image.new("RGB", (2160, 1920))
    for index, (_, _, file) in enumerate(panels):
        with Image.open(work / file) as image:
            if image.size != (1080, 1920) or image.format != "PNG":
                raise ValueError(f"Expected a native 1080×1920 Remotion PNG: {work / file}")
            composite.paste(image.convert("RGB"), (index * 1080, 0))
    path = work / "text_exit_trail_check.png"
    composite.save(path)
    sources = [{"beat": beat, "frame": frame, "sec": frame / 60, "panel": side}
               for (beat, frame, _), side in zip(panels, ("left", "right"))]
    return path, {"width": 2160, "height": 1920, "composition": "NimCinema", "panels": sources}


def retained_stone_closeup():
    path = REVIEW / "stone_closeup_check.png"
    with Image.open(path) as image:
        width, height = image.size
        image.verify()
    with path.open("rb") as file:
        sha256 = hashlib.file_digest(file, "sha256").hexdigest()
    return {"origin": "Stage 1 v2", "file": path.name, "width": width, "height": height, "sha256": sha256}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path, nargs="?")
    parser.add_argument("--layout-only", action="store_true")
    parser.add_argument("--verify-locks", action="store_true")
    args = parser.parse_args()
    hashes = verify_locked_sources()
    if args.verify_locks:
        print(json.dumps(hashes, ensure_ascii=False))
        return 0
    if args.work is None:
        parser.error("work is required for layout or video QA")
    work = args.work.resolve()
    if not work.is_relative_to(EPISODE / ".work"):
        raise ValueError("All task intermediates must stay inside this episode's .work directory.")
    score = json.loads((EPISODE / "beats.json").read_text(encoding="utf-8-sig"))
    beats = [beat for beat in score["beats"] if frame_number(beat["startSec"]) < COUNT]
    if len(beats) != 7 or frame_number(beats[-1]["endSec"]) != COUNT:
        raise ValueError("The review must end at the B07/B08 junction at 34.8 seconds.")

    if not args.layout_only:
        files = read_sequence(work)
        retained_closeup = retained_stone_closeup()
        trail, trail_metadata = make_trail_comparison(work)
        ffmpeg, ffprobe = pinned_tools()
        video = encode_preview(files, ffmpeg, work)
        stats = analyze_video(video, files, beats)
        media = probe_media(video, ffmpeg, ffprobe)
        sheet = work / "stage1_contact_sheet.png"
        make_contact_sheet(sheet, files, stats["dark"]["keyFrames"])

    labels, layout = inspect_layout(work / "layout", score["beats"])
    recap = layout["b25"]["samples"]
    recap_issues = layout["b25"]["issues"]
    expected_states = []
    for moves in (score["moves"][:5], score["moves"][5:]):
        expected_states.extend(",".join(map(str, state)) for state in [moves[0]["before"], *(
            move["after"] for move in moves
        )])
    for row in recap:
        if row["boardStates"] != expected_states:
            recap_issues.append({"type": "recap-state-sequence", "firstFrame": row["frame"]})
    expected_roles = {28: {"我 · 先手", "你 · 后手"}, 29: {"对手 · 先手", "我 · 后手"}}
    closing = layout["b28and29"]["samples"]
    closing_issues = layout["b28and29"]["issues"]
    for row in closing:
        visible_roles = {item["text"] for item in row["texts"] if item["text"].endswith((" · 先手", " · 后手"))}
        if visible_roles != expected_roles[row["beat"]]:
            closing_issues.append({"type": "closing-role-pair", "frame": row["frame"]})
    write_json(work / "stage1_layout.json", layout)
    layout_checks = {
        "layout": (
            not layout["previewIssues"] and not layout["nativeIssues"]
            and not recap_issues and not closing_issues
            and all(row["texts"] for row in recap) and len(closing) == 6
        ),
        "fontLoading": not layout["fontIssues"],
        "b03Clearance": layout["B03Clearance"]["passed"] and layout["B03Geometry"]["passed"],
        "b07Route": all(row["passed"] for row in layout["B07Route"]),
        "rollingClip": layout["rollingClip"]["passed"],
        "trailPanelLayout": all(row["passed"] for row in layout["trailPanelLayout"]),
    }
    if args.layout_only:
        print(json.dumps(layout_checks, ensure_ascii=False))
        return not all(layout_checks.values())

    reading = measure_reading(files, beats, labels)
    text_diff = max(row["text_box_diff"] for row in reading)
    seam_max = max(row["seam_delta"] for row in stats["seams"])
    if len(stats["seams"]) != 6:
        raise ValueError(f"Expected 6 non-cut seams, observed {len(stats['seams'])}.")
    checks = {
        "media": (
            (media["width"], media["height"], media["fps"], media["frameCount"]) == (WIDTH, HEIGHT, FPS, COUNT)
            and abs(media["durationSec"] - COUNT / FPS) < 0.001
            and (media["codec"], media["pixelFormat"], media["profile"], media["level"]) == ("h264", "yuv420p", "High", 42)
            and (media["audioCodec"], media["audioChannels"], media["audioSampleRate"]) == ("aac", 2, 48000)
            and media["audioPeakDbfs"] is not None
            and -16 <= media["audioPeakDbfs"] <= -12
        ),
        "seams": seam_max < MOTION_THRESHOLD and all(row["nativeMaxRGBDelta"] == 0 for row in stats["seams"]),
        "reading": text_diff == 0 and not any(row["geometryChanges"] for row in reading)
        and all(row["sourceWindowDurationSec"] >= .85 for row in reading),
        "studioDark": 86 <= stats["dark"]["meanPct"] <= 93,
        "motion": stats["motion"]["longestStaticSec"] <= 1.2,
        "lockedInputs": verify_locked_sources() == hashes,
        "retainedStoneCloseup": retained_stone_closeup() == retained_closeup,
        **layout_checks,
    }
    report = {
        "revision": "Stage 1 v3", "media": media, **stats, "maxSeamDelta": seam_max,
        "text_box_diff": float(text_diff), "reading": reading,
        "readingMethod": "Every original Remotion PNG in each settled window. Default [beatEnd − 1.40s, beatEnd − 0.50s]; B06 [27.865s, 28.72s), B07 [33.46s, 34.32s). Compare absolute RGB inside measured Chromium text boxes against the window's first sampled frame.",
        "layout": layout, "lockedHashesSha256": hashes,
        "retainedStoneCloseup": retained_closeup,
        "textExitTrailComparison": trail_metadata,
        "remotionPngSequence": str(files[0].parent.relative_to(EPISODE)),
        "ffmpeg": str(ffmpeg), "checks": checks, "passed": all(checks.values()),
    }
    report_path = work / "stage1_qc.json"
    write_json(report_path, report)
    if report["passed"]:
        REVIEW.mkdir(parents=True, exist_ok=True)
        video.replace(REVIEW / video.name)
        sheet.replace(REVIEW / sheet.name)
        trail.replace(REVIEW / trail.name)
        report_path = report_path.replace(REVIEW / report_path.name)
    print(json.dumps({
        "checks": checks, "maxSeamDelta": seam_max, "text_box_diff": text_diff,
        "meanDarkPct": stats["dark"]["meanPct"], "longestStaticSec": stats["motion"]["longestStaticSec"],
        "report": str(report_path),
    }, ensure_ascii=False))
    return not report["passed"]


if __name__ == "__main__":
    raise SystemExit(main())
