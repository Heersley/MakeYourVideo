"""Create a runnable copy of the production example in output/evergreen_vibe."""
import argparse
import json
import re
import shutil
import sys
import tempfile
import wave
from datetime import date
from pathlib import Path

import numpy as np

EXAMPLE = Path(__file__).resolve().parent
ROOT = EXAMPLE.parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "core/vibe")]

from episode import TRACK, core_snapshot, load_profile, read, sample_plan, sha256_file
from evidence_kit import FACES
from sfx_engine import render_sfx


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")


def tick(_event, rate, _rng):
    t = np.arange(round(rate * 0.12)) / rate
    return np.sin(2 * np.pi * 630 * t) * np.sin(np.pi * t / 0.12) ** 2 * np.exp(-18 * t)


def make_music(path, rate):
    # Original four-bar pad with a brighter section at the authored downbeat.
    t = np.arange(rate * 96) / rate
    chord = np.array([110, 130.8128, 146.8324, 98])[(t // 2).astype(int) % 4]
    phase = 2 * np.pi * np.cumsum(chord) / rate
    pad = 0.34 * np.sin(phase) + 0.17 * np.sin(2 * phase) + 0.11 * np.sin(3 * phase)
    swell = 0.66 + 0.34 * np.minimum(1, np.maximum(0, (t - 24) * 4))
    stereo = np.column_stack((pad, 0.9 * pad + 0.06 * np.sin(4 * phase))) * swell[:, None]
    with wave.open(str(path), "wb") as file:
        file.setparams((2, 2, rate, 0, "NONE", ""))
        file.writeframes(np.rint(stereo * 32767).astype("<i2").tobytes())
    write_json(path.with_suffix(".beats.json"), {
        "source_sha256": sha256_file(path), "bpm": 120, "bar_sec": 2,
        "bar_times": list(range(0, 96, 2)), "drops": [{"t": 24}],
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", nargs="?", type=Path,
                        default=TRACK / date.today().isoformat() / "01_diameter")
    parser.add_argument("--fonts", type=Path, default=ROOT / "assets/fonts")
    args = parser.parse_args()
    ep = args.episode.resolve()
    if not ep.is_relative_to(TRACK.resolve()):
        parser.error("目录须位于 output/evergreen_vibe/ 下")
    parts = ep.relative_to(TRACK.resolve()).parts
    if len(parts) != 2 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]) or not re.fullmatch(r"\d{2}_.+", ep.name):
        parser.error("目录格式须为 output/evergreen_vibe/YYYY-MM-DD/NN_主题")
    if ep.exists():
        parser.error(f"目录已存在：{ep}")
    missing = [file for _, _, file in FACES if not (args.fonts / file).is_file()]
    if missing:
        parser.error("缺少字体：" + "、".join(missing) + "。见 assets/fonts/FONT-NOTICE.md")

    ep.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ep.parent, prefix=".prepare-") as temp:
        stage = Path(temp) / ep.name
        src = stage / "src"
        shutil.copytree(EXAMPLE / "src", src, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("beats.json", "facts_and_sources.md"):
            shutil.copyfile(EXAMPLE / name, stage / name)
        fonts = src / "assets/fonts"
        fonts.mkdir(parents=True)
        for _, _, name in FACES:
            shutil.copyfile(args.fonts / name, fonts / name)
        for notice in args.fonts.glob("*.txt"):
            if "OFL" in notice.name.upper() or "LICENSE" in notice.name.upper():
                shutil.copyfile(notice, fonts / notice.name)
        manifest = read(src / "manifest.json")
        manifest.update(bgm=(ep / "src/bed.wav").relative_to(ROOT).as_posix(),
                        licenseNote="程序合成配乐，随示例按 MIT 许可提供")
        write_json(src / "manifest.json", manifest)
        core_snapshot.install(stage)
        score = read(stage / "beats.json")
        profile = load_profile(manifest["profile"])
        timeline = sample_plan(score, profile)
        fps = score["fps"]
        events = [{"frame": round(c["timeSec"] * fps), "voice": c["type"]} for c in score["effects"]]
        render_sfx(events, {"tick": tick}, timeline["count"], fps, profile.data, src / "sfx.wav")
        make_music(src / "bed.wav", profile.hard["audio"]["sampleRate"])
        stage.rename(ep)
    print(ep)


if __name__ == "__main__":
    main()
