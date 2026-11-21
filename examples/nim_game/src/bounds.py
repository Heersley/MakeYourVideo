"""Read native design bounds and actual glyph fonts without taking screenshots."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from bisect import bisect_right
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from fontTools.ttLib import TTFont
from playwright.sync_api import sync_playwright

SOURCE = Path(__file__).resolve().parent
EPISODE = SOURCE.parent


def _find_repo_root(start: Path) -> Path:
    """向上定位仓库根（含 package.json 的那一级），不依赖固定的目录层级深度。"""
    for parent in start.parents:
        if (parent / "package.json").exists():
            return parent
    return start.parents[-1] if start.parents else start


PROJECT = _find_repo_root(EPISODE)
EXE = ".exe" if platform.system() == "Windows" else ""

# 字体目录候选：渲染侧标准路径（public/fonts）优先，其次仓库归档与 QC 历史路径。
FONT_DIRS = (
    PROJECT / "public" / "fonts",
    PROJECT / "assets" / "fonts",
    SOURCE / "assets" / "fonts",
)


def font_file(name: str) -> Path | None:
    """按候选顺序定位字体文件；找不到返回 None。"""
    for directory in FONT_DIRS:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def locate_ffmpeg(explicit: str | None = None):
    """跨平台定位 ffmpeg / ffprobe：显式参数 → FFMPEG_BIN → WinGet → PATH。"""
    tools = PROJECT / "tools"
    if tools.is_dir() and str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        import bgm_common  # noqa: WPS433 — 延迟导入，避免与 tools/ 缺失时硬崩
        ffmpeg, ffprobe, _ = bgm_common.locate_tools(explicit)
        return ffmpeg, ffprobe
    except (Exception, SystemExit):
        pass

    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("FFMPEG_BIN"):
        candidates.append(Path(os.environ["FFMPEG_BIN"]))
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(Path(which))
    for candidate in candidates:
        exe = candidate if candidate.suffix.lower() == ".exe" else candidate / f"ffmpeg{EXE}"
        if not exe.exists():
            continue
        probe = exe.with_name(f"ffprobe{EXE}")
        return str(exe), str(probe if probe.exists() else shutil.which("ffprobe") or probe)
    raise SystemExit(
        "[layout] 未找到 FFmpeg。请用 --ffmpeg 指定可执行文件，"
        "或设置环境变量 FFMPEG_BIN，或确认 `ffmpeg -version` 可用。"
    )


def find_esbuild() -> Path | None:
    """跨平台定位 esbuild：优先平台包 @esbuild/<platform>，其次 node_modules/.bin。"""
    platform_dir = PROJECT / "node_modules" / "@esbuild"
    if platform_dir.is_dir():
        for candidate in sorted(platform_dir.glob(f"*/esbuild{EXE}")):
            if candidate.is_file():
                return candidate
    for name in (f"esbuild{EXE}", "esbuild"):
        candidate = PROJECT / "node_modules" / ".bin" / name
        if candidate.is_file():
            return candidate
    return None


def find_headless_shell() -> Path | None:
    """定位 Remotion 自带的 chrome-headless-shell（跨平台，不写死 .exe）。"""
    root = PROJECT / "node_modules" / ".remotion" / "chrome-headless-shell"
    if not root.is_dir():
        return None
    for candidate in root.rglob(f"chrome-headless-shell{EXE}"):
        return candidate
    for candidate in root.rglob("chrome-headless-shell*"):
        if candidate.is_file():
            return candidate
    return None


def launch_chromium(playwright):
    """优先用 Remotion 的 headless shell；缺失时回落到 Playwright 自带 Chromium。"""
    shell = find_headless_shell()
    if shell is not None:
        return playwright.chromium.launch(executable_path=str(shell))
    return playwright.chromium.launch()
TEXT_SAFE_AREA = (90, 180, 910, 1500)
PREVIEW_END = 1044
CHINESE = "ChillJinshuSong"
SERIF = "Source Serif 4"
MONO = "JetBrains Mono"
FACES = (
    (CHINESE, "400", "尼姆博弈"),
    (CHINESE, "700", "尼姆博弈"),
    (SERIF, "400", "NIM 1901"),
    (SERIF, "600", "NIM 1901"),
    (MONO, "400", "XOR 0123456789"),
    (MONO, "500", "XOR 0123456789"),
)
REQUIRED_WEIGHTS = {(family, weight) for family, weight, _ in FACES}


def reading_bounds(beat):
    # The two late game moves need their entire roll and win animation before the reading freeze.
    if beat["id"] == 6:
        return 27.865, 28.72, False
    if beat["id"] == 7:
        return 33.46, 34.32, False
    if beat["id"] == 31:
        return 182.5, 184.0, False
    end = beat["endSec"]
    return end - 1.40, end - .50, True


def reading_frames(beat, fps):
    start, end, inclusive_end = reading_bounds(beat)
    first = math.ceil(start * fps - 1e-8)
    stop = math.floor(end * fps + 1e-8) + 1 if inclusive_end else math.ceil(end * fps - 1e-8)
    return first, stop


class LayoutHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def translate_path(self, path):
        # 直接返回绝对路径，避免在 ThreadingHTTPServer 下改写共享的 self.directory。
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/assets/fonts/"):
            # 字体按 FONT_DIRS 顺序解析：开源用户只放到 public/fonts 也能被 QC 读到。
            target = font_file(Path(clean).name)
            if target is not None:
                return str(target)
        if clean.startswith("/assets/"):
            return str(SOURCE / "assets" / clean[len("/assets/"):])
        return str(Path(self.server.work) / clean.lstrip("/"))


@contextmanager
def serve_layout(work):
    work.mkdir(parents=True, exist_ok=True)
    bundle = work / "preview_layout.js"
    esbuild = find_esbuild()
    if esbuild is None:
        raise SystemExit(
            "[layout] 未找到 esbuild。请先在仓库根目录执行 npm install。"
        )
    subprocess.run(
        [
            str(esbuild),
            str(SOURCE / "preview_layout.tsx"),
            "--bundle",
            # 自动 JSX 运行时：与 Remotion 自带打包器一致，无需每个 .tsx 都 import React
            "--jsx=automatic",
            "--log-level=error", '--define:process.env.NODE_ENV="production"',
            f"--outfile={bundle}",
        ],
        check=True,
        cwd=PROJECT,
    )
    (work / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><style>body{margin:0}'
        '#root{position:relative;width:1080px;height:1920px}</style><div id="root"></div>'
        '<script>window.remotion_staticBase="/assets";</script><script src="/preview_layout.js"></script>',
        encoding="utf-8",
    )
    with ThreadingHTTPServer(("127.0.0.1", 0), LayoutHandler) as server:
        server.work = work
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/"
        finally:
            server.shutdown()
            worker.join()


def sample_layout(page, first, stop, fps):
    return page.evaluate("args => window.inspectNimFrames(...args)", [first, stop, fps])


def font_session(page):
    session = page.context.new_cdp_session(page)
    session.send("DOM.enable")
    session.send("CSS.enable")
    return session


def platform_fonts(session, root, selector):
    node = session.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
    return session.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"] if node else []


def read_faces(page, session):
    faces = page.evaluate(
        """async probes => {
          await window.loadNimSceneFonts();
          await document.fonts.ready;
          const cleanFamily = family => family.replaceAll('"', '').replaceAll("'", '');
          const rules = Array.from(document.styleSheets).flatMap(sheet => Array.from(sheet.cssRules))
            .filter(rule => rule instanceof CSSFontFaceRule);
          for (const [family, weight, text] of probes) {
            const sample = document.createElement('span');
            sample.dataset.fontProbe = family + '-' + weight;
            Object.assign(sample.style, {position: 'absolute', left: '-2000px',
              fontFamily: '"' + family + '"', fontWeight: weight, fontSynthesis: 'none'});
            sample.textContent = text;
            document.body.append(sample);
          }
          return Array.from(document.fonts, face => {
            const family = cleanFamily(face.family);
            const rule = rules.find(({style}) => cleanFamily(style.fontFamily) === family
              && style.fontWeight === face.weight);
            const src = rule?.style.getPropertyValue('src') || '';
            const path = src.split(')')[0].slice(4).replaceAll('"', '').replaceAll("'", '');
            return {family, status: face.status, weight: face.weight,
              source: path.startsWith('/assets/fonts/') ? decodeURIComponent(path.split('/').at(-1)) : null,
            };
          });
        }""", FACES,
    )
    root = session.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
    for face in faces:
        src = face["source"]
        if src and Path(src).name == src:
            target = font_file(src)
            if target is None:
                face["postScriptName"] = None
                face["fileWeight"] = None
            else:
                with TTFont(target, lazy=True) as font:
                    face["postScriptName"] = font["name"].getDebugName(6)
                    face["fileWeight"] = font["OS/2"].usWeightClass
        face["platformFonts"] = platform_fonts(
            session, root, f'[data-font-probe="{face["family"]}-{face["weight"]}"]',
        )
    page.evaluate("""() => document.querySelectorAll('[data-font-probe]').forEach(node => node.remove())""")
    return faces


def actual_fonts(page, session, beat, frame):
    candidates = page.evaluate("frame => window.inspectNimFontCandidates(frame)", frame)
    root = session.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
    rows = []
    for candidate in candidates:
        selector = f'[data-qa-font-id="{candidate["id"]}"]'
        fonts = platform_fonts(session, root, selector)
        rows.append({"beat": beat, "frame": frame, **candidate, "fonts": fonts})
    return rows


def issues_in_layout(rows, title_band=True):
    problems = {}
    left, top, right, bottom = TEXT_SAFE_AREA
    for index, beat_id, labels in rows:
        for position, label in enumerate(labels):
            text = label["text"]
            x, y, x_end, y_end = label["bounds"]
            upper = title_band and label["role"] == "headline" and beat_id != 31
            departing = label["trail"] or label["flight"]
            if departing:
                x_min, x_max = 0, 1080
                y_min, y_max = (0, 540) if upper else (1300, 1500) if label["role"] == "readout" else (0, 1920)
            else:
                x_min, x_max = left, right
                y_min, y_max = (210, 500) if upper else (top, bottom)
            if x < x_min - .5 or y < y_min - .5 or x_end > x_max + .5 or y_end > y_max + .5:
                problems.setdefault(("outside", beat_id, text, label["trail"]), []).append(index)
            for other in labels[:position]:
                if label["trail"] or other["trail"] or min(label["opacity"], other["opacity"]) < .1:
                    continue
                if label["flight"] and other["flight"] and label["role"] == other["role"]:
                    continue
                if label["slot"] is not None and label["slot"] == other["slot"]:
                    continue
                ox, oy, ox_end, oy_end = other["bounds"]
                overlap_x = min(x_end, ox_end) - max(x, ox)
                overlap_y = min(y_end, oy_end) - max(y, oy)
                if overlap_x > 1.5 and overlap_y > .22 * min(y_end - y, oy_end - oy):
                    problems.setdefault(("overlap", beat_id, text, other["text"]), []).append(index)
    return [
        {"type": key[0], "beat": key[1], "detail": list(key[2:]),
         "firstFrame": min(frames), "lastFrame": max(frames), "frames": len(set(frames))}
        for key, frames in problems.items()
    ]


def b03_clearance(preview, beat):
    first, stop = round(beat["startSec"] * 30), round(beat["endSec"] * 30)
    return clearance_pairs((frame, preview[frame]) for frame in range(first, stop))


def clearance_pairs(samples):
    rows = []
    rule_labels = {"取1颗", "也可取整堆"}
    for frame, labels in samples:
        titles = {re.sub(r"\s+", "", row["text"]): row["bounds"] for row in labels
                  if not row["trail"] and row["opacity"] >= .1}
        for action in rule_labels.intersection(titles):
            for target in {"4", "III"}.intersection(titles):
                x, y, x_end, y_end = titles[action]
                a, b, a_end, b_end = titles[target]
                distance = math.hypot(max(0, a - x_end, x - a_end), max(0, b - y_end, y - b_end))
                rows.append({"frame": frame, "label": action, "neighbor": target, "gapPx": distance})
    minimum = [
        min((row for row in rows if (row["label"], row["neighbor"]) == (action, target)),
            key=lambda row: row["gapPx"], default=None)
        for action in sorted(rule_labels) for target in ("4", "III")
    ]
    return {
        "pairs": minimum, "frames": len({row["frame"] for row in rows}),
        "passed": all(row is not None and row["gapPx"] >= 26 for row in minimum),
    }


def route_waypoints(page):
    reports = []
    for start, actor in [(30.8, "second"), (32.8, "first")]:
        first, stop = round(start * 60), round((start + 1.05) * 60)
        points = page.evaluate("r => window.inspectNimRoutes(r[0], r[1], 60)", [first, stop])
        trace = [point for point in points if point["actor"] == actor]
        last = trace[-1] if trace else None
        target = last["targetY"] if last else None
        reaches_rail = target is not None and abs(last["y"] - target) <= 1
        correct_role = target is not None and (target < 710 if actor == "first" else target > 1250)
        reports.append({
            "actor": actor, "cueSec": start, "first": trace[0] if trace else None,
            "last": last, "samples": len(trace),
            "passed": reaches_rail and correct_role and len(trace) > 8,
        })
    return reports


def font_issues(faces, rendered):
    errors = []
    by_key = {(face["family"], face["weight"]): face for face in faces}
    family_by_postscript = {
        face["postScriptName"]: (face["family"], face["weight"])
        for face in faces if face.get("postScriptName")
    }
    for key in sorted(REQUIRED_WEIGHTS | by_key.keys()):
        family, weight = key
        face = by_key.get(key, {})
        actual = face.get("platformFonts", [])
        same_file = len(actual) == 1 and actual[0]["isCustomFont"] \
            and actual[0]["postScriptName"] == face.get("postScriptName")
        if key not in REQUIRED_WEIGHTS or face.get("status") != "loaded" \
                or face.get("fileWeight") != int(weight) or not same_file:
            errors.append({"family": family, "weight": weight, "reason": "Unexpected or unverified FontFace",
                           "details": face})
    for row in rendered:
        declarations = [row["family"], *row["childFamilies"]]
        stack = {part.strip().strip("\"'") for declaration in declarations for part in declaration.split(",")}
        used = {
            family_by_postscript.get(font["postScriptName"]) if font["isCustomFont"] else None
            for font in row["fonts"]
        }
        expected = None
        has_han = bool(re.search(r"[\u3400-\u9fff]", row["text"]))
        if row["role"] == "headline":
            if has_han:
                expected = (CHINESE, "700" if row["weight"] != "400" else "400")
            elif re.search(r"[A-Za-z0-9]", row["text"]):
                expected = (SERIF, "600" if row["weight"] != "400" else "400")
        elif row["role"] == "archives":
            expected = (SERIF, "400")
        elif has_han:
            expected = (CHINESE, "400")
        elif MONO in stack and re.search(r"[A-Za-z0-9]", row["text"]):
            expected = (MONO, row["weight"])
        if not used or None in used or any(font[0] not in stack for font in used if font) \
                or (expected is not None and expected not in used):
            errors.append({"beat": row["beat"], "text": row["text"], "reason": "Unexpected glyph font",
                           "expected": expected, "fonts": row["fonts"], "declared": row["family"]})
    checked_headlines = {row["beat"] for row in rendered if row["role"] == "headline"}
    if len(checked_headlines) != 31:
        errors.append({"reason": "Missing headline platform-font samples", "checked": sorted(checked_headlines)})
    return errors


def pickup_geometry(samples):
    callouts = [{"frame": sample["frame"], **sample["callout"]}
                for sample in samples if sample["callout"] is not None]
    clipped_slots = [{"frame": sample["frame"], **slot} for sample in samples for slot in sample["slots"]]
    for callout in callouts:
        callout["gapPx"] = callout["jawLeft"] - callout["labelRight"]
    closest = min(callouts, key=lambda row: row["gapPx"], default=None)
    guide_lengths = sorted(set(row["guideLength"] for row in callouts))
    bad_slots = [slot for slot in clipped_slots if slot["em"] <= 0 or not slot["isSvgViewport"]
                 or "hidden" not in slot["cssOverflow"] or abs(slot["height"] / slot["em"] - 1.15) > .005]
    return {
        "B03Geometry": {
            "frames": len(callouts), "minClearance": closest, "guideLengthsPx": guide_lengths,
            "passed": closest is not None and closest["gapPx"] >= 12
            and all(abs(length - 12) < .1 for length in guide_lengths),
        },
        "rollingClip": {
            "checkedSlotFrames": len(clipped_slots), "issues": bad_slots,
            "expectedHeightEm": 1.15, "passed": bool(clipped_slots) and not bad_slots,
        },
    }


def inspect_trail_panels(page):
    panels = []
    for frame, beat in [(213, 1), (441, 2)]:
        sample = page.evaluate("f => window.inspectNimSpecialFrames(f, f + 1, 60)[0]", frame)
        flight = [label for label in sample["labels"] if label["flight"] and not label["trail"]]
        ghosts = [label for label in sample["labels"] if label["trail"]]
        threads = sample["threads"]
        violations = issues_in_layout([(frame, beat, [*flight, *ghosts])])
        thread_violations = [
            thread for thread in threads
            if thread["bounds"][0] < -.5 or thread["bounds"][1] < -.5
            or thread["bounds"][2] > 1080.5 or thread["bounds"][3] > 1920.5
        ]
        panels.append({
            "frame": frame, "sec": frame / 60, "beat": beat,
            "flyingGlyphs": len(flight), "visibleGhosts": len(ghosts), "threads": len(threads),
            "issues": violations, "threadBoundsIssues": thread_violations,
            "passed": bool(flight and ghosts and threads) and not violations and not thread_violations,
        })
    return panels


def settled_frame(beat):
    first, stop = reading_frames(beat, 60)
    return (first + stop) // 2


def inspect_key_details(page, score):
    beats = score["beats"]
    b03_frames = [round(sec * 60) for sec in (9.1, 10.1, 11.2)]
    callout_samples = [
        page.evaluate("f => window.inspectNimSpecialFrames(f, f + 1, 60)[0]", frame)
        for frame in b03_frames
    ]
    b03 = pickup_geometry(callout_samples)["B03Geometry"]
    b03["clearancePairs"] = clearance_pairs((row["frame"], row["labels"]) for row in callout_samples)
    b03["passed"] = b03["passed"] and b03["clearancePairs"]["passed"] and b03["frames"] == 3

    frame = settled_frame(beats[24])
    recap = page.evaluate("frame => window.inspectNimRecap(frame)", frame)
    expected = []
    for moves in (score["moves"][:5], score["moves"][5:]):
        expected.extend(",".join(map(str, state)) for state in (moves[0]["before"], *(move["after"] for move in moves)))
    tuples = [row for row in recap["texts"] if re.fullmatch(r"\(\d+,\d+,\d+\)", row["text"])]
    gaps = [right["bounds"][0] - left["bounds"][2]
            for track in (tuples[:6], tuples[6:]) for left, right in zip(track, track[1:])]
    b25 = {"frame": frame, "nodes": recap["boardStates"], "minLabelGapPx": min(gaps, default=0),
           "passed": recap["boardStates"] == expected and len(tuples) == 12 and min(gaps, default=0) > 0}

    frame = settled_frame(beats[25])
    archive = [row for row in sample_layout(page, frame, frame + 1, 60)[0] if row["role"] == "archives"]
    # The text area excludes the plate border, ornaments and edge ticks.
    b26 = {"frame": frame, "rows": archive, "passed": len(archive) == 6 and all(
        230 <= bounds[0] and 675 <= bounds[1] and bounds[2] <= 770 and bounds[3] <= 1175
        for row in archive for bounds in [row["bounds"]]
    )}

    expected_roles = {28: {"我 · 先手", "你 · 后手"}, 29: {"对手 · 先手", "我 · 后手"}}
    closing = []
    for beat_id, expected_pair in expected_roles.items():
        frame = settled_frame(beats[beat_id - 1])
        labels = sample_layout(page, frame, frame + 1, 60)[0]
        pair = {row["text"] for row in labels if row["text"].endswith((" · 先手", " · 后手"))}
        closing.append({"frame": frame, "beat": beat_id, "labels": sorted(pair), "passed": pair == expected_pair})
    return {"B03": b03, "B25": b25, "B26": b26, "B28–B29": closing,
            "passed": all(row["passed"] for row in [b03, b25, b26, *closing])}


def inspect_keyframe_layout(work, score):
    with serve_layout(work) as address, sync_playwright() as playwright:
        browser = launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(address, wait_until="load")
        sample_layout(page, 0, 1, 60)
        session = font_session(page)
        faces = read_faces(page, session)
        rows, fonts = [], []
        for beat in score["beats"]:
            frame, beat_id = settled_frame(beat), beat["id"]
            rows.append((frame, beat_id, sample_layout(page, frame, frame + 1, 60)[0]))
            fonts.extend(actual_fonts(page, session, beat_id, frame))
        details = inspect_key_details(page, score)
        trail = inspect_trail_panels(page)
        browser.close()
    issues = issues_in_layout(rows)
    font_problems = font_issues(faces, fonts)
    return {"canvas": [1080, 1920], "safeArea": TEXT_SAFE_AREA, "scenesChecked": len(rows),
            "keyframes": [frame for frame, _, _ in rows], "issues": issues, "fontIssues": font_problems,
            "fontFaces": faces, "specialScenes": details, "trailPanelLayout": trail,
            "passed": len(rows) == 31 and not issues and not font_problems
            and details["passed"] and all(row["passed"] for row in trail)}


def inspect_layout(work, beats):
    b25 = next(beat for beat in beats if beat["id"] == 25)
    with serve_layout(work) as address, sync_playwright() as playwright:
        browser = launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(address, wait_until="load")
        sample_layout(page, 0, 1, 60)
        session = font_session(page)
        faces = read_faces(page, session)

        preview_samples = []
        for start in range(0, PREVIEW_END, 60):
            preview_samples.extend(page.evaluate(
                "args => window.inspectNimSpecialFrames(...args)", [start, min(start + 60, PREVIEW_END), 30]
            ))
        preview = [sample["labels"] for sample in preview_samples]

        native_sets, fonts = [], []
        for beat in beats:
            id_ = beat["id"]
            first = round(beat["startSec"] * 60)
            end = round(beat["endSec"] * 60)
            hold_first, hold_stop = reading_frames(beat, 60)
            settled = (hold_first + hold_stop) // 2 if id_ != 31 else round(181.3 * 60)
            native_frames = sorted({first, first + 25, hold_first, settled, hold_stop - 1,
                                    *(end - n for n in (21, 17, 12, 8, 4, 1))})
            for frame in native_frames:
                native_sets.append((frame, id_, sample_layout(page, frame, frame + 1, 60)[0]))
            fonts.extend(actual_fonts(page, session, id_, settled))

        first, stop = reading_frames(b25, 60)
        recap = [
            {"frame": frame, "sec": frame / 60,
             **page.evaluate("frame => window.inspectNimRecap(frame)", frame)}
            for frame in (first, (first + stop) // 2, stop - 1)
        ]
        closing = []
        for id_ in (28, 29):
            first, stop = reading_frames(beats[id_ - 1], 60)
            for frame in (first, (first + stop) // 2, stop - 1):
                closing.append({"frame": frame, "beat": id_,
                                "texts": sample_layout(page, frame, frame + 1, 60)[0]})
        routes = route_waypoints(page)
        trail_panels = inspect_trail_panels(page)
        browser.close()

    preview_with_beats = []
    for frame, labels in enumerate(preview):
        scene = next(beat for beat in beats if frame < round(beat["endSec"] * 30))
        preview_with_beats.append((frame, scene["id"], labels))
    preview_issues = issues_in_layout(preview_with_beats)
    native_issues = issues_in_layout(native_sets)
    recap_issues = issues_in_layout((row["frame"], 25, row["texts"]) for row in recap)
    metadata = {
        "method": "Chromium DOM layout and CDP CSS.getPlatformFontsForNode; no screenshots outside B01–B07",
        "previewFramesInspected": len(preview),
        "fullTimelineSampleCount": len(native_sets),
        "sampleFramesByBeat": {
            f"B{beat['id']:02d}": [frame for frame, id_, _ in native_sets if id_ == beat["id"]]
            for beat in beats
        },
        "previewIssues": preview_issues, "nativeIssues": native_issues,
        "B03Clearance": b03_clearance(preview, beats[2]),
        **pickup_geometry(preview_samples),
        "B07Route": routes,
        "b25": {"samples": recap, "issues": recap_issues},
        "b28and29": {"samples": closing, "issues": []},
        "fontFaces": faces, "platformFontSamples": fonts,
        "fontIssues": font_issues(faces, fonts),
        "trailPanelLayout": trail_panels,
    }
    return preview, metadata


def inspect_full_layout(work, beats):
    """Collect exact text boxes for every native reading frame and 10 fps layout checks."""
    starts = [round(beat["startSec"] * 60) for beat in beats]
    total = round(beats[-1]["endSec"] * 60)
    inspect = set(range(0, total, 6))
    reading = set()
    for beat, begin in zip(beats, starts):
        first, stop = reading_frames(beat, 60)
        reading.update(range(first, stop))
        inspect.update((max(0, begin - 1), begin))
    inspect.update(reading)
    requested = sorted(inspect)
    stable_labels, rows, fonts = {}, [], []
    with serve_layout(work) as address, sync_playwright() as playwright:
        browser = launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(address, wait_until="load")
        sample_layout(page, 0, 1, 60)
        session = font_session(page)
        faces = read_faces(page, session)
        for first in range(0, len(requested), 64):
            batch = requested[first:first + 64]
            results = page.evaluate("frames => window.inspectNimSelectedFrames(frames, 60)", batch)
            for frame, labels in zip(batch, results, strict=True):
                beat_id = beats[bisect_right(starts, frame) - 1]["id"]
                rows.append((frame, beat_id, labels))
                if frame in reading:
                    stable_labels[frame] = labels
        for beat in beats:
            fonts.extend(actual_fonts(page, session, beat["id"], settled_frame(beat)))
        browser.close()
    issues = issues_in_layout(rows)
    font_problems = font_issues(faces, fonts)
    report = {
        "canvas": [1080, 1920],
        "frameRate": 60,
        "layoutFramesChecked": len(rows),
        "readingLayoutFrames": len(stable_labels),
        "issues": issues,
        "fontFaces": faces,
        "fontIssues": font_problems,
        "platformFontSamples": fonts,
        "passed": not issues and not font_problems,
    }
    return stable_labels, report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check settled layout and packaged font usage in all 31 beats.")
    parser.add_argument("--work", type=Path, required=True)
    work = parser.parse_args().work.resolve()
    if not work.is_relative_to((EPISODE / ".work").resolve()):
        parser.error("The work directory must be within the episode's .work.")
    score = json.loads((EPISODE / "beats.json").read_text(encoding="utf-8-sig"))
    report = inspect_keyframe_layout(work, score)
    path = work / "preflight_bounds.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scenes": report["scenesChecked"], "layoutIssues": len(report["issues"]),
                      "fontIssues": len(report["fontIssues"]), "specialScenesPassed": report["specialScenes"]["passed"],
                      "passed": report["passed"], "report": str(path)}, ensure_ascii=False))
    raise SystemExit(not report["passed"])
