"""Run the actual CLI, Chromium, FFmpeg, and the delivery checker on a short fixture."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image

from test_production import episode, score


ROOT = Path(__file__).resolve().parents[2]


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def pcm(path, samples):
    with wave.open(str(path), "wb") as wav:
        wav.setparams((2, 2, 48000, 0, "NONE", ""))
        wav.writeframes(np.rint(32767 * samples).astype("<i2").tobytes())


@contextmanager
def edited(path, data=None):
    original = path.read_bytes()
    try:
        if data is None:
            path.unlink()
        elif isinstance(data, bytes):
            path.write_bytes(data)
        else:
            write_json(path, data)
        yield
    finally:
        path.write_bytes(original)


class SealTests(unittest.TestCase):
    @classmethod
    def invoke(cls, *args, check=True):
        result = subprocess.run([sys.executable, "-B", "tools/episode.py", args[0],
                                 str(cls.ep), *map(str, args[1:])],
                                cwd=cls.root, capture_output=True, encoding="utf-8",
                                errors="replace", timeout=180)
        if check and result.returncode:
            raise AssertionError(f"{args}: {result.stderr}\n{result.stdout}")
        return result

    @classmethod
    def setUpClass(cls):
        parent = ROOT / "temp/_work"
        parent.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(prefix="seal-", dir=parent, ignore_cleanup_errors=True)
        cls.addClassCleanup(temp.cleanup)
        cls.root = root = Path(temp.name)
        shutil.copytree(ROOT / "tools", root / "tools",
                        ignore=shutil.ignore_patterns("tests", "__pycache__", "legacy_archive",
                                                      "env.local.json"))
        for name in ("package.json", "package-lock.json", "tsconfig.json"):
            if (ROOT / name).is_file():
                shutil.copyfile(ROOT / name, root / name)
        (root / "docs").mkdir()
        for name in ("AGENTS.md", "STYLE_B_SILENT_VIBE.md"):
            shutil.copyfile(ROOT / "docs" / name, root / "docs" / name)
        cls.ep = ep = root / "output/evergreen_vibe/2026-11-23/01_fixture"
        src = ep / "src"
        (src / "vendor").mkdir(parents=True)
        shutil.copytree(ROOT / "core/vibe", root / "core/vibe")
        src_fonts = ROOT / "assets/fonts"
        font_binaries = [p for p in src_fonts.iterdir() if p.suffix.lower() in {".woff", ".woff2", ".otf"}] if src_fonts.is_dir() else []
        if not font_binaries:
            raise unittest.SkipTest("字体二进制未随开源仓分发；准备 4 族 8 个字体后再跑真实渲染")
        shutil.copytree(src_fonts, src / "assets/fonts")
        shutil.copytree(src / "assets", src / "alt-public")
        profile = episode.read(ROOT / "tools/profiles/vibe-3.3.json")
        profile["id"] = "vibe-9.9"
        hard = profile["hard"]
        hard["video"].update(width=320, height=240, fps=10, previewFps=10, previewSec=[5, 6])
        hard["visual"].update(safeZone=[10, 10, 310, 230], roiY=[90, 200])
        hard["timeline"]["duration"]["standard"][0] = 5
        profile_path = root / "tools/profiles/vibe-9.9.json"
        write_json(profile_path, profile)
        write_json(root / "tools/profiles/registry.json", {"vibe-9.9": episode.sha256_file(profile_path)})
        data = score()
        data.update(fps=10, totalSec=5, alignClimaxSec=2, beats=data["beats"][:1],
                    effects=[{"timeSec": i / 10, "type": "tick"} for i in range(10)])
        write_json(ep / "beats.json", data)
        (ep / "facts_and_sources.md").write_text("Short production fixture.", "utf-8")
        cls.manifest_path = src / "manifest.json"
        cls.bgm_beats = src / "bed.beats.json"
        bgm = src / "bed.wav"
        pcm(bgm, np.tile((0.5 * np.sin(2 * np.pi * 440 * np.arange(48000 * 8) / 48000))[:, None], (1, 2)))
        write_json(cls.bgm_beats, {"source_sha256": episode.sha256_file(bgm), "bpm": 120, "bar_sec": 2,
                                  "bar_times": [0, 2, 4, 6], "drops": [{"t": 2}]})
        effects = np.zeros((48000 * 5, 2))
        cue = 0.2 * np.sin(2 * np.pi * 440 * np.arange(1440) / 48000)
        effects[96000:97440, 0] = cue
        effects[96000:97440, 1] = -cue
        pcm(src / "sfx.wav", effects)
        write_json(cls.manifest_path, {"version": 1, "topic": "fixture.md", "entry": "entry.tsx",
                                       "previewComposition": "Review", "fullComposition": "Cinema",
                                       "previewFrames": 50, "profile": "vibe-9.9", "sfx": "src/sfx.wav",
                                       "bgm": bgm.relative_to(root).as_posix(), "licenseNote": "synthetic tone",
                                       "bgmGainDb": -16, "evidenceScript": "src/evidence/frames.py"})
        (src / "evidence").mkdir()
        (src / "evidence/frames.py").write_text(
            'import sys\nfrom pathlib import Path\n'
            'sys.path.insert(0, str(Path.cwd() / "tools"))\n'
            'from evidence_kit import main\n'
            'def check(frames, plan):\n'
            '    assert frames["20"]["details"][0]["data"]["vibeEvidence"] == "test"\n'
            '    return {"custom": True}\n'
            'main(cover_frame=49, still_frames={"prop": 0, "trail": 39, "climax": 20}, check=check)\n',
            "utf-8")
        (src / "entry.tsx").write_text(
            'import {Composition, registerRoot, useCurrentFrame} from "remotion";\n'
            'import {Fonts} from "./vendor/vibe/Fonts";\n'
            'const Scene = () => {const f = useCurrentFrame(); return <Fonts folder="fonts">\n'
            '  <div style={{background:"#090a0b", width:320,height:240}}>\n'
            '    <div data-vibe-static-text data-holding={f >= 20 && f < 30}\n'
            '      style={{position:"absolute",left:20,top:20,font:"20px Source Serif 4",color:"#ffdf8a"}}>Evidence</div>\n'
            '    <div data-vibe-evidence="test" style={{position:"absolute",left:20+5*f,top:110,\n'
            '      width:100,height:70,backgroundColor:"#79b0ce"}}/>\n'
            '  </div></Fonts>;};\n'
            'const Root = () => <>{["Review","Cinema","Other"].map(id => <Composition key={id} id={id}\n'
            '  component={Scene} width={320} height={240} fps={10} durationInFrames={50}/>)}</>;\n'
            'registerRoot(Root);\n', "utf-8")
        (src / "alternate.tsx").write_text('import "./entry";\n', "utf-8")
        (src / "unused.css").write_text("/* Bound scene stylesheet */\n", "utf-8")
        cls.ffmpeg = episode.locate_tools()[0]
        cls.invoke("snapshot")
        cls.invoke("preview", "--transport", "cdp-pipe")
        cls.review = src / "review"
        cls.approval_args = ("approve", "--gate", "review", "--note", "Sample inspected")
        cls.invoke(*cls.approval_args)
        cls.review_event = next((src / "reviews").glob("*.json"))

    def gate(self):
        return json.loads(self.invoke("status").stdout)["nextGate"]

    def test_approval_requires_current_sample(self):
        with edited(self.review_event):
            for name in ("preview.mp4", "preview_qc.json", "receipt.json"):
                with self.subTest(missing=name), edited(self.review / name):
                    bad = self.invoke(*self.approval_args, check=False)
                    self.assertNotEqual(bad.returncode, 0)
                    self.assertIn("review", bad.stderr)
            with edited(self.manifest_path, episode.read(self.manifest_path) | {"bgmGainDb": -15}):
                bad = self.invoke(*self.approval_args, check=False)
                self.assertNotEqual(bad.returncode, 0)
                self.assertIn("过期", bad.stderr)

    def test_exact_content_selection(self):
        base = episode.read(self.manifest_path)
        for key, value in (("entry", "alternate.tsx"), ("fullComposition", "Other"),
                           ("publicDir", "src/alt-public"), ("bgmGainDb", -15)):
            with self.subTest(key=key), edited(self.manifest_path, base | {key: value}):
                self.assertEqual(self.gate(), "review")
        with edited(self.bgm_beats, episode.read(self.bgm_beats) | {"bpm": 121}):
            self.assertEqual(self.gate(), "review")
        with edited(self.ep / "src/unused.css"):
            self.assertEqual(self.gate(), "review")
        script = self.root / "tools/episode.py"
        with edited(script, script.read_bytes() + b"\n# Local infrastructure update\n"), edited(
                self.manifest_path, base | {"evidenceScript": "src/evidence/new.py", "concurrency": 3, "previewFrames": 51}):
            self.assertEqual(self.gate(), "delivery")

    def test_evidence_preview(self):
        qc = episode.read(self.review / "preview_qc.json")
        self.assertTrue(qc["passed"])
        self.assertEqual(qc["media_sha256"], episode.sha256_file(self.review / "preview.mp4"))
        self.assertEqual(len(qc["fonts"]["faces"]), 8)
        self.assertEqual(qc["reading"]["beats"]["1"]["maxSampleDelta"], 0)
        self.assertEqual(qc["details"], {"custom": True})
        for name, digest in qc["stills"].items():
            self.assertEqual(episode.sha256_file(self.review / name), digest)
        with Image.open(self.review / "phone.png") as phone:
            self.assertEqual(phone.width, 3 * 360 + 2 * 12)

    def test_resume_rejects_missing_or_changed_receipt(self):
        folder = self.ep / ".work" / uuid4().hex
        folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, folder)
        shutil.copyfile(self.review / "preview.mp4", folder / "picture.mp4")
        failed = self.invoke("ship", "--work", folder, check=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("picture-receipt.json", failed.stderr)
        self.assertFalse((folder / "picture-receipt.json").exists())
        write_json(folder / "picture-receipt.json", {"approved": {}, "mode": "full",
                                                    "picture": episode.sha256_file(folder / "picture.mp4")})
        for action in ("ship", "full"):
            failed = self.invoke(action, "--work", folder, check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("内容版本不匹配", failed.stderr)

    def video_stream(self, path):
        return subprocess.check_output([self.ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v:0",
                                        "-c:v", "copy", "-f", "hash", "-hash", "sha256", "-"],
                                       text=True, timeout=30).strip()

    def test_ship_retries_real_mix_and_finishes(self):
        initial = self.invoke("full", "--transport", "cdp-pipe", check=False)
        self.assertNotEqual(initial.returncode, 0, initial.stdout)
        match = re.search(r"\[episode\] work=(.+)", initial.stderr)
        self.assertIsNotNone(match, initial.stderr)
        work = Path(match[1].strip())
        movie = self.ep / "fixture.mp4"
        candidate = work / "delivery" / self.ep.name
        diagnostic = episode.read(candidate / "mix_diagnostic.json")
        self.assertEqual(diagnostic["reasons"], ["integrated_lufs"])
        self.assertTrue(-25 <= diagnostic["integrated_lufs"] < -18, diagnostic)
        self.assertFalse((candidate / movie.name).exists())
        self.assertFalse((candidate / "bgm_mix_report.json").exists())
        self.assertFalse(movie.exists())
        picture = self.video_stream(work / "picture.mp4")
        production = self.invoke("ship", "--work", work)
        retries = json.loads(production.stdout[production.stdout.rfind('\n{') + 1:])["mixRetries"]
        self.assertEqual(retries, [diagnostic])
        mix = episode.read(self.ep / "bgm_mix_report.json")
        self.assertTrue(-18 <= mix["integrated_lufs"] <= -14, mix)
        self.assertAlmostEqual(mix["bgm_gain_db"], -16 + (-16 - diagnostic["integrated_lufs"]))
        self.assertEqual(self.video_stream(movie), picture)
        self.assertEqual(self.gate(), "delivery")
        layout = episode.read(self.ep / "src/production" / work.name / "layout.json")
        self.assertTrue(layout["passed"])
        self.assertEqual(layout["details"], {"custom": True})
        self.assertEqual(layout["stills"]["contact_sheet.png"], episode.sha256_file(self.ep / "contact_sheet.png"))
        self.assertTrue(layout["boxes"]["20"])
        with wave.open(str(self.ep / "src/sfx_only.wav"), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 2)
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, 2)
            self.assertGreater(int(np.max(samples[:, 0])), 5000)
            np.testing.assert_allclose(samples[:, 0], -samples[:, 1], atol=1, rtol=0)
        print(f"\n[seal] real ship {diagnostic['integrated_lufs']} -> {mix['integrated_lufs']} LUFS; "
              f"peak {mix['true_peak_dbtp']} dBTP; same {picture}; retry count {len(retries)}")
