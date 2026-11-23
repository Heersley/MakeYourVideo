"""Preflight and finish the native Stage 2 PNG sequence. Delivery is staged in the run directory."""

import argparse
import json
import math
import re
import struct
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

from bounds import PROJECT, inspect_full_layout, inspect_key_details, launch_chromium, reading_bounds, reading_frames, serve_layout
from preview_qc import EPISODE, SOURCE, contact_sheet_font, pinned_tools, probe_media, verify_locked_sources, write_json

FPS, COUNT, SIZE = 60, 11040, (1080, 1920)
CLIP = "异或博弈_cinema_clean.mp4"
MOTION_THRESHOLD = .15
EXPECTED_CUTS = [34.8, 83.8, 142.0, 148.8]
DARK_RANGE = (84, 95)
CLOSING_START = 182.5


def read_score():
    score = json.loads((EPISODE / "beats.json").read_text(encoding="utf-8-sig"))
    beats = score["beats"]
    assert score["duration_tier"] == "long" and len(beats) == 31 and len(score["effects"]) == 25
    assert [beat["startSec"] for beat in beats if beat["hardCut"]] == EXPECTED_CUTS
    assert beats[0]["startSec"] == 0 and round(beats[-1]["endSec"] * FPS) == COUNT
    assert sum(round(beat["durationSec"] * FPS) for beat in beats) == COUNT
    assert all(first["endSec"] == second["startSec"] for first, second in zip(beats, beats[1:]))
    assert all(len("".join(beat["lines"]).replace("【", "").replace("】", "").replace(" ", "")) <= 22 for beat in beats)
    return score


def sequence_files(directory):
    matched = []
    for path in directory.glob("element-*.png"):
        matched.append((int(path.stem.removeprefix("element-")), path))
    return sorted(matched)


def index_sequence(work, args):
    folder = args.frames_dir.resolve() if args.frames_dir else work / "frames"
    if not folder.is_relative_to(EPISODE / ".work"):
        raise ValueError("The PNG input must remain inside the episode's .work directory.")
    images = sequence_files(folder)
    if not images:
        raise ValueError(f"No native Remotion PNGs were found in {folder}.")
    if args.frame_map:
        frame_ids = json.loads(args.frame_map.read_text(encoding="utf-8-sig"))
        if len(frame_ids) != len(images) or sorted(set(frame_ids)) != frame_ids:
            raise ValueError("--frame-map must contain one increasing native frame number for each emitted PNG.")
    elif args.first_frame is not None:
        frame_ids = [args.first_frame + position * args.stride for position in range(len(images))]
    else:
        frame_ids = [frame for frame, _ in images]
    if not all(0 <= frame < COUNT for frame in frame_ids):
        raise ValueError("The PNG sequence contains frame numbers beyond the 184.0-second timeline.")
    if not args.preflight:
        digit_widths = {len(path.stem.removeprefix("element-")) for _, path in images}
        if frame_ids != list(range(COUNT)) or len(digit_widths) != 1:
            raise ValueError(f"Expected {COUNT} contiguous, consistently padded native Remotion PNGs.")
    return dict(zip(frame_ids, (path for _, path in images), strict=True))


def read_png(path):
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape != (SIZE[1], SIZE[0], 3):
        raise ValueError(f"Expected a native {SIZE[0]}×{SIZE[1]} Remotion PNG: {path}")
    return image


def gray(image):
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def crop_box(bounds):
    x, y, right, bottom = bounds
    return (max(0, math.floor(x) - 1), max(0, math.floor(y) - 1),
            min(SIZE[0], math.ceil(right) + 1), min(SIZE[1], math.ceil(bottom) + 1))


def reading_checks(beats, files, labels):
    scenes = []
    for beat in beats:
        lo, hi = reading_frames(beat, FPS)
        window_start, window_end, inclusive = reading_bounds(beat)
        selected = [frame for frame in range(lo, hi) if frame in files]
        report = {
            "beat": f"B{beat['id']:02d}", "sourceWindowSec": [round(window_start, 3), round(window_end, 3)],
            "inclusiveEnd": inclusive, "expectedFrames": hi - lo, "testedFrames": len(selected),
            "firstFrame": lo, "endExclusive": hi, "complete": len(selected) == hi - lo,
            "text_box_diff": None, "geometryChanged": [], "boxes": [],
        }
        if not selected:
            scenes.append(report)
            continue
        baseline = selected[0]
        reference = read_png(files[baseline])
        stable = [label for label in labels[baseline] if not label["trail"]]
        if not stable:
            report["missingText"] = True
        boxes = [{"text": label["text"], "bounds": crop_box(label["bounds"]), "maxRGBDelta": 0}
                 for label in stable]
        for frame in selected[1:]:
            compare = [label for label in labels[frame] if not label["trail"]]
            if compare != stable:
                report["geometryChanged"].append(frame)
            image = read_png(files[frame])
            for box in boxes:
                x, y, right, bottom = box["bounds"]
                delta = int(cv2.absdiff(image[y:bottom, x:right], reference[y:bottom, x:right]).max())
                if delta > box["maxRGBDelta"]:
                    box["maxRGBDelta"] = delta
                    box["maxAtFrame"] = frame
        report["boxes"] = boxes
        report["text_box_diff"] = max((box["maxRGBDelta"] for box in boxes), default=0)
        scenes.append(report)
    return scenes


def seam_frames(beats):
    return {round(beat["startSec"] * FPS): f"B{beat['id']:02d}" for beat in beats[1:] if not beat["hardCut"]}


def raw_seams(beats, files):
    results = {}
    for frame, to in seam_frames(beats).items():
        if frame not in files or frame - 1 not in files:
            continue
        before, after = read_png(files[frame - 1]), read_png(files[frame])
        results[frame] = {
            "to": to, "frame": frame, "sec": frame / FPS,
            "nativeMaxRGBDelta": int(cv2.absdiff(before, after).max()),
            "nativeSeamDelta": float(cv2.absdiff(gray(before), gray(after)).mean()),
        }
    return results


def inspect_title_hold(files):
    start = round(CLOSING_START * FPS)
    reference = read_png(files[start])
    changed = []
    maximum = 0
    for frame in range(start + 1, COUNT):
        difference = int(cv2.absdiff(reference, read_png(files[frame])).max())
        if difference:
            changed.append(frame)
            maximum = max(maximum, difference)
    return {
        "startSec": CLOSING_START, "endSecExclusive": COUNT / FPS,
        "framesChecked": COUNT - start, "maxRGBDelta": maximum,
        "changedFrames": changed, "passed": not changed,
    }


def inspect_pickup_sync(work, score):
    observations = []
    with serve_layout(work) as address, sync_playwright() as playwright:
        browser = launch_chromium(playwright)
        page = browser.new_page(viewport={"width": SIZE[0], "height": SIZE[1]})
        page.goto(address, wait_until="load")
        page.evaluate("async () => { await window.loadNimSceneFonts(); await document.fonts.ready; }")
        for move in score["moves"]:
            cue_frame = round(move["timeSec"] * FPS)
            heap = move["heap"] - 1
            selector = f'[data-game-label="count-{("I", "II", "III")[heap]}"]'
            frames = page.evaluate(
                """({first, frames, fps, selector}) => Array.from({length: frames}, (_, i) => {
                  const frame = first + i;
                  window.inspectNimFrames(frame, frame + 1, fps);
                  const count = document.querySelector(selector);
                  return {
                    frame,
                    digits: [...(count?.querySelectorAll('text') ?? [])].map(node => node.textContent),
                    rolling: Boolean(count?.querySelector('[data-qc-digit-roll]')),
                    stones: [...document.querySelectorAll('[data-pick-frame]')].map(node => ({
                      cue: Number(node.dataset.pickFrame),
                      player: node.dataset.pickPlayer,
                      heap: Number(node.dataset.pickHeap),
                      y: Number(node.dataset.pickY),
                      rail: Number(node.dataset.pickTargetY),
                    })),
                  };
                })""",
                {"first": cue_frame - 1, "frames": FPS + 1, "fps": FPS, "selector": selector},
            )
            before, after = str(move["before"][heap]), str(move["after"][heap])
            flight = [row for row in frames if row["stones"]]
            rolling = [row for row in frames if row["rolling"]]
            overlap = bool(flight and rolling and
                           flight[0]["frame"] == cue_frame < rolling[0]["frame"] and
                           rolling[-1]["frame"] < flight[-1]["frame"])
            counts_ok = (
                frames[0]["digits"] == [before] and frames[-1]["digits"] == [after]
                and bool(rolling) and all(row["digits"] == [before, after] for row in rolling)
            )
            route_ok = (
                bool(flight) and all(
                    len(row["stones"]) == move["removed"] and all(
                        stone["cue"] == move["timeSec"]
                        and stone["player"] == move["player"] and stone["heap"] == move["heap"]
                        and (stone["rail"] < 710 if move["player"] == "first" else stone["rail"] > 1250)
                        for stone in row["stones"]
                    )
                    for row in flight
                )
                and all(abs(stone["y"] - stone["rail"]) <= 1.5 for stone in flight[-1]["stones"])
            )
            observations.append({
                "cueSec": move["timeSec"], "player": move["player"], "heap": move["heap"],
                "removed": move["removed"], "before": int(before), "after": int(after),
                "flightFrames": [flight[0]["frame"], flight[-1]["frame"]] if flight else [],
                "rollingFrames": [rolling[0]["frame"], rolling[-1]["frame"]] if rolling else [],
                "countValuesCorrect": counts_ok, "routeCorrect": route_ok, "rollDuringFlight": overlap,
                "passed": counts_ok and route_ok and overlap,
            })
        special_scenes = inspect_key_details(page, score)
        browser.close()
    return (
        {"moves": observations, "passed": bool(observations) and all(row["passed"] for row in observations)},
        special_scenes,
    )


def motion_summary(samples):
    previous_frame, previous_gray = None, None
    run_start, windows = None, []
    measured = 0
    for frame, current in samples:
        if previous_frame is not None:
            adjacent = frame - previous_frame == FPS // 10
            if adjacent:
                measured += 1
            low = adjacent and float(cv2.absdiff(current, previous_gray).mean()) < MOTION_THRESHOLD
            if low and run_start is None:
                run_start = previous_frame
            if not low and run_start is not None:
                windows.append((run_start, previous_frame))
                run_start = None
        previous_frame, previous_gray = frame, current
    if run_start is not None:
        windows.append((run_start, previous_frame))
    return {
        "fps": 10, "deltaThreshold": MOTION_THRESHOLD, "measuredFramePairs": measured,
        "longestStaticSec": max(((stop - start) / FPS for start, stop in windows), default=0),
        "overLimit": [
            {"startSec": start / FPS, "endSec": stop / FPS, "durationSec": (stop - start) / FPS}
            for start, stop in windows if stop - start > round(1.20 * FPS)
        ],
    }


def build_preflight(work, beats, files, layout, reading, seams):
    dark = []

    def samples():
        for frame, path in files.items():
            if frame % (FPS // 10):
                continue
            luma = gray(read_png(path))
            dark.append(float(np.mean(luma < 40) * 100))
            if frame < COUNT - round(1.5 * FPS):
                yield frame, luma

    motion = motion_summary(samples())
    reading_issues = [row["beat"] for row in reading if row["text_box_diff"] not in (None, 0)
                      or row["geometryChanged"] or row.get("missingText")]
    checks = {
        "sampledReading": not reading_issues,
        "sampledSeams": all(row["nativeMaxRGBDelta"] == 0 for row in seams.values()),
        "sampledMotion": not motion["overLimit"],
        "layout": layout["passed"],
    }
    report = {
        "checks": checks, "passed": all(checks.values()), "fullSequenceCount": COUNT,
        "testedPngs": len(files), "readingIssues": reading_issues, "reading": reading,
        "seams": list(seams.values()), "expectedSeams": len(seam_frames(beats)),
        "motion": motion, "sampledDarkPct": float(np.mean(dark)) if dark else None,
        "layout": "bounds.json",
    }
    write_json(work / "preflight_qc.json", report)
    return report


def encode_clean(work, files, ffmpeg):
    first = files[0]
    digits = len(first.stem.removeprefix("element-"))
    pending = work / "cinema_clean_encoding.mp4"
    clean = work / CLIP
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "warning", "-stats_period", "15", "-stats", "-y",
        "-framerate", "60", "-start_number", "0",
        "-i", first.parent / f"element-%0{digits}d.png",
        "-i", SOURCE / "sfx_mix.wav", "-map", "0:v:0", "-map", "1:a:0", "-t", "184",
        "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.2", "-pix_fmt", "yuv420p",
        "-crf", "16", "-preset", "slow", "-g", "120", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "256k",
        "-metadata", "comment=AI-assisted mathematical animation",
        pending,
    ]
    subprocess.run(command, check=True)
    pending.replace(clean)
    return clean, [str(value) for value in command]


def has_faststart(path):
    with path.open("rb") as stream:
        while head := stream.read(8):
            size, name = struct.unpack(">I4s", head)
            if name in (b"moov", b"mdat"):
                return name == b"moov"
            header_size = 8
            if size == 1:
                size = struct.unpack(">Q", stream.read(8))[0]
                header_size = 16
            if size < header_size:
                return False
            stream.seek(size - header_size, 1)
    return False


def encoding_audit(path, ffmpeg, ffprobe):
    stream = subprocess.check_output([
        ffmpeg, "-v", "error", "-i", path, "-map", "0:v:0", "-c:v", "copy", "-f", "h264", "-",
    ])
    nals = re.split(rb"\x00\x00(?:\x00)?\x01", stream)
    types = [nal[0] & 31 for nal in nals if nal]
    settings = next((nal for nal in nals if b"x264 - core" in nal), b"")
    packets = json.loads(subprocess.check_output([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "packet=flags", "-of", "json", path,
    ]))["packets"]
    keys = [index for index, packet in enumerate(packets) if "K" in packet["flags"]]
    audit = {
        "slices": types.count(1) + types.count(5), "idrSlices": types.count(5),
        "keyframes": len(keys), "packetCount": len(packets), "faststart": has_faststart(path),
        "maximumGop": max((second - first for first, second in zip(keys, [*keys[1:], COUNT])), default=None),
        "x264CRF16": b"crf=16.0" in settings, "x264Keyint120": b"keyint=120" in settings,
        "x264SlowSettings": all(term in settings for term in
                                (b"subme=8", b"trellis=2", b"rc_lookahead=50", b"direct=3")),
        "structuralOverrides": [text.decode("ascii") for text in (b"slice_max_mbs", b"slice-max-mbs", b"slices=")
                                if text in settings],
    }
    audit["passed"] = (
        audit["slices"] == COUNT and audit["packetCount"] == COUNT and audit["idrSlices"] == len(keys)
        and 1 < len(keys) < COUNT and keys[0] == 0 and audit["maximumGop"] <= 120
        and all(audit[name] for name in ("faststart", "x264CRF16", "x264Keyint120", "x264SlowSettings"))
        and not audit["structuralOverrides"]
    )
    return audit


def inspect_clean(path, beats, seams):
    markers = {}
    for beat in beats:
        start, stop = reading_frames(beat, FPS)
        markers[(start + stop) // 2] = beat["id"]
    thumbnails = {}
    visible_bounds = []
    darkness = np.empty(COUNT, dtype=np.float64)
    previous = None
    capture = cv2.VideoCapture(str(path))

    def samples():
        nonlocal previous
        for frame in range(COUNT):
            ok, image = capture.read()
            if not ok or image.shape != (SIZE[1], SIZE[0], 3):
                raise ValueError(f"Decode failed at frame {frame}: {path}")
            luma = gray(image)
            darkness[frame] = np.mean(luma < 40) * 100
            if frame in markers:
                thumbnails[frame] = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                x, y, width, height = cv2.boundingRect((luma > 102).astype(np.uint8))
                beat = markers[frame]
                # The approved Stage 1 revisions extend the physical board to x=984.
                board_on_screen = beat <= 11 or beat in (28, 29, 30)
                safe_right = 984 if board_on_screen else 910
                inside = bool(width and x >= 89 and y >= 179
                              and x + width <= safe_right + 1 and y + height <= 1501)
                visible_bounds.append({"beat": f"B{beat:02d}", "frame": frame,
                                       "bounds": [x, y, x + width, y + height],
                                       "safe": [90, 180, safe_right, 1500], "passed": inside})
            if frame in seams:
                seams[frame]["seam_delta"] = float(cv2.absdiff(luma, previous).mean())
            previous = luma
            if frame % 6 == 0 and frame < COUNT - round(1.5 * FPS):
                yield frame, luma
        if capture.read()[0]:
            raise ValueError(f"Decoded more than {COUNT} frames.")

    try:
        motion = motion_summary(samples())
    finally:
        capture.release()
    statistics = {
        "darkPctMean": float(darkness.mean()), "darkPctMin": float(darkness.min()),
        "darkPctMax": float(darkness.max()), "frames": COUNT,
        "keyframes": [{"beat": f"B{beat:02d}", "frame": frame, "sec": frame / FPS,
                       "darkPct": float(darkness[frame])} for frame, beat in markers.items()],
    }
    return motion, statistics, thumbnails, visible_bounds


def make_images(work, thumbnails, statistics, cover_beat):
    metadata = statistics["keyframes"]
    cols, width, height, pad, caption = 6, 200, 356, 14, 27
    nrows = math.ceil(len(metadata) / cols)
    page = Image.new("RGB", (pad + cols * (width + pad), pad + nrows * (height + caption + pad)), "#101114")
    font = contact_sheet_font(15)
    draw = ImageDraw.Draw(page)
    cover = f"B{cover_beat:02d}"
    for index, marker in enumerate(metadata):
        x = pad + index % cols * (width + pad)
        y = pad + index // cols * (height + caption + pad)
        image = thumbnails[marker["frame"]]
        page.paste(image.resize((width, height), Image.Resampling.LANCZOS), (x, y))
        draw.text((x, y + height + 5), f'{marker["beat"]}  {marker["sec"]:06.2f}s', fill="#C9A96A", font=font)
        if marker["beat"] == cover:
            image.save(work / "cover.png")
    page.save(work / "contact_sheet.png")
    return {"panels": len(metadata), "coverBeat": cover, "source": "decoded clean video"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--layout-only", action="store_true")
    modes.add_argument("--preflight", action="store_true")
    modes.add_argument("--verify-existing", action="store_true")
    modes.add_argument("--encode-only", action="store_true")
    parser.add_argument("--first-frame", type=int)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--frame-map", type=Path)
    parser.add_argument("--frames-dir", type=Path, help="Read an existing PNG directory inside this episode.")
    parser.add_argument("--cover-beat", type=int, choices=range(1, 32), default=13)
    args = parser.parse_args()
    work = args.work.resolve()
    if not work.is_relative_to(EPISODE / ".work"):
        parser.error("Work must stay inside this episode's .work directory.")
    if (args.first_frame is not None or args.stride != 1 or args.frame_map) and not args.preflight:
        parser.error("Frame remapping may be used only for sparse PNG preflight.")
    locked = verify_locked_sources()
    score = read_score()
    beats = score["beats"]
    files = {} if args.layout_only else index_sequence(work, args)
    ffmpeg, ffprobe = pinned_tools()

    if args.encode_only:
        clean, command = encode_clean(work, files, ffmpeg)
        write_json(work / "encode_command.json", command)
        print(clean)
        return 0

    labels, layout = inspect_full_layout(work / "layout_full", beats)
    write_json(work / "bounds.json", layout)
    print(json.dumps({"layoutPassed": layout["passed"], "layoutIssues": len(layout["issues"]),
                      "fontIssues": len(layout["fontIssues"])}, ensure_ascii=False), flush=True)
    if args.layout_only:
        return not layout["passed"]

    reading = reading_checks(beats, files, labels)
    seams = raw_seams(beats, files)
    if args.preflight:
        report = build_preflight(work, beats, files, layout, reading, seams)
        print(json.dumps({"checks": report["checks"], "readingIssues": report["readingIssues"],
                          "motion": report["motion"], "sampledDarkPct": report["sampledDarkPct"]}))
        return not report["passed"]

    reading_ok = len(reading) == 31 and all(
        row["complete"] and row["text_box_diff"] == 0 and not row["geometryChanged"] and not row.get("missingText")
        for row in reading
    )
    write_json(work / "reading_qc.json", {
        "source": "original Remotion PNGs", "method": "maximum absolute RGB difference in 1080p Chromium text boxes",
        "scenes": reading, "passed": reading_ok,
    })
    title_hold = inspect_title_hold(files)
    pickup_sync, special_scenes = inspect_pickup_sync(work / "layout_full", score)
    if args.verify_existing:
        clean = work / CLIP
    else:
        clean, command = encode_clean(work, files, ffmpeg)
        write_json(work / "encode_command.json", command)
    media = probe_media(clean, ffmpeg, ffprobe)
    audit = encoding_audit(clean, ffmpeg, ffprobe)
    motion, darkness, thumbnails, visible_bounds = inspect_clean(clean, beats, seams)
    layout["decodedRestingVisibleBounds"] = {
        "displayGrayThreshold": 102, "samples": visible_bounds,
        "passed": len(visible_bounds) == 31 and all(row["passed"] for row in visible_bounds),
    }
    write_json(work / "bounds.json", layout)
    images = make_images(work, thumbnails, darkness, args.cover_beat)
    # The motion threshold belongs to 10 fps still-window detection (§5.3②).
    # A soft seam holds the authored state exactly; compare its native frames
    # and retain the decoded delta separately (including across H.264 GOPs).
    seam_ok = len(seams) == 26 and all(row["nativeMaxRGBDelta"] == 0 for row in seams.values())
    spec_ok = (
        (media["width"], media["height"], media["fps"], media["frameCount"], media["durationSec"])
        == (*SIZE, FPS, COUNT, 184)
        and (media["codec"], media["profile"], media["level"], media["pixelFormat"]) == ("h264", "High", 42, "yuv420p")
        and (media["audioCodec"], media["audioChannels"], media["audioSampleRate"]) == ("aac", 2, 48000)
        and media["audioPeakDbfs"] is not None and -16 <= media["audioPeakDbfs"] <= -12
    )
    layout_ok = layout["passed"] and layout["decodedRestingVisibleBounds"]["passed"] and special_scenes["passed"]
    pickup = {
        "seams": list(seams.values()), "maxSeamDelta": max(row["seam_delta"] for row in seams.values()),
        "maxNativeSeamDelta": max(row["nativeSeamDelta"] for row in seams.values()),
        "seamGate": "Exact equality of adjacent original PNG frames at every non-cut boundary.",
        "motion": motion, "readingWindows": 31, "text_box_diff": max(row["text_box_diff"] or 0 for row in reading),
        "pickupSync": pickup_sync, "closingHold": title_hold,
        "layout": {"report": "bounds.json", "frames": layout["layoutFramesChecked"],
                   "issues": layout["issues"], "specialScenes": special_scenes, "passed": layout_ok},
        "passed": all((seam_ok, reading_ok, not motion["overLimit"], layout_ok,
                       pickup_sync["passed"], title_hold["passed"])),
    }
    write_json(work / "pickup_qc.json", pickup)
    checks = {
        "specAndStereo": spec_ok, "standardEncoding": audit["passed"],
        "studioDark": DARK_RANGE[0] <= darkness["darkPctMean"] <= DARK_RANGE[1],
        "motion": not motion["overLimit"], "pickupSync": pickup_sync["passed"],
        "closingHold": title_hold["passed"],
        "softSeams": seam_ok, "reading": reading_ok,
        "layout": layout_ok,
        "factsAndLockedInputs": verify_locked_sources() == locked, "contactAndCover": images["panels"] == 31,
    }
    report = {
        "revision": "Stage 2", "checks": checks, "passed": all(checks.values()),
        "deliveryReady": False, "decoderReports": "pending", "media": media, "encodingAudit": audit,
        "darkness": darkness, "images": images, "text_box_diff": pickup["text_box_diff"], "motion": motion,
        "maxSeamDelta": pickup["maxSeamDelta"], "maxNativeSeamDelta": pickup["maxNativeSeamDelta"],
        "score": {"durationTier": score["duration_tier"], "beats": len(beats), "soundEffects": len(score["effects"])},
        "closingHold": title_hold,
        "fontFaces": layout["fontFaces"],
        "lockedSha256": locked, "ffmpeg": str(ffmpeg),
        "files": {"reading": "reading_qc.json", "pickup": "pickup_qc.json", "bounds": "bounds.json"},
    }
    write_json(work / "full_qc.json", report)
    print(json.dumps({"checks": checks, "darkPctMean": darkness["darkPctMean"],
                      "maxSeamDelta": pickup["maxSeamDelta"], "text_box_diff": pickup["text_box_diff"],
                      "motion": motion}, ensure_ascii=False))
    return not report["passed"]


if __name__ == "__main__":
    raise SystemExit(main())
