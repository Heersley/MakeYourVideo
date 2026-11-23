import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"tools"), str(ROOT/"core/vibe")]
import core_snapshot
import episode
import sfx_engine
from test_production import score


class VibeTests(unittest.TestCase):
    def test_sfx_sample_offset_peak_and_repeatability(self):
        profile = episode.load_profile().data
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fx.wav"
            events = [{"voice":"tick", "frame":7}]
            def voice(event, rate, rng):
                return rng.uniform(.2, .5, 100)
            first = sfx_engine.render_sfx(events, {"tick":voice}, 113, 59, profile, out, seed=3)
            second = sfx_engine.render_sfx(events, {"tick":voice}, 113, 59, profile, out, seed=3)
            self.assertEqual(first, second)
            self.assertEqual(first["sha256"], hashlib.sha256(out.read_bytes()).hexdigest())
            with wave.open(str(out)) as wav:
                self.assertEqual(wav.getnchannels(), 2)
                frames = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
            pcm = frames.reshape(-1, 2)
            np.testing.assert_array_equal(pcm[:, 0], pcm[:, 1])
            self.assertEqual(first["events"][0]["sample"], round(7*48000/59))
            self.assertEqual(np.flatnonzero(pcm.any(axis=1))[0], first["events"][0]["sample"])
            actual = 20*np.log10(max(abs(int(frames.max())), abs(int(frames.min()))) / 32768)
            self.assertAlmostEqual(first["peakDbfs"], actual)
            self.assertTrue(-16 <= actual <= -12)

    def test_sfx_rejects_bad_events_without_replacing_master(self):
        profile = episode.load_profile().data
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/"fx.wav"
            out.write_bytes(b"previous")
            for events in ([], [{"frame":1,"voice":"mute"}], [{"frame":.2,"voice":"mute"}]):
                with self.assertRaises(ValueError):
                    sfx_engine.render_sfx(events, {"mute":lambda *args: np.zeros(40)}, 60, 60, profile, out)
                self.assertEqual(out.read_bytes(), b"previous")

    def test_snapshot_is_bound_to_plan_and_portable(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ep = base/"04_test"
            (ep/"src/assets").mkdir(parents=True)
            (ep/"src/entry.tsx").write_text("// fixture")
            manifest = dict(version=1, topic="card.md", entry="entry.tsx", fullComposition="Full",
                            previewComposition="Review", previewFrames=900, sfx="src/sfx.wav")
            (ep/"src/manifest.json").write_text(json.dumps(manifest))
            (ep/"beats.json").write_text(json.dumps(score()))
            original = core_snapshot.install(ep)
            with patch.object(core_snapshot, "CORE", base/"absent"):
                self.assertEqual(core_snapshot.install(ep), original)
                moved = base/"a/b/c/04_test"
                shutil.copytree(ep, moved)
                self.assertEqual(episode.plan(moved,"full")["inputProps"]["profile"]["id"], "vibe-3.3")
                target = moved/"src/vendor/vibe/clock.ts"
                target.write_text("broken")
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    episode.plan(moved,"full")
                receipt = moved/"src/vendor/vibe/core_snapshot.json"
                receipt.write_text("{}")
                with self.assertRaisesRegex(ValueError, "receipt"):
                    episode.plan(moved,"full")

    def test_production_entry_uses_local_snapshot(self):
        # Run the production compiler and normal module resolution against a disposable episode.
        workspace = ROOT / "temp/_work"
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workspace) as tmp:
            ep = Path(tmp)
            (ep/"src").mkdir()
            (ep/"src/manifest.json").write_text("{}")
            core_snapshot.install(ep)
            entry = ep/"src/entry.tsx"
            cmd = ["node", str(ROOT/"tools/check_entry.cjs"), str(entry)]
            entry.write_text("export {Fonts} from './vendor/vibe/Fonts';")
            subprocess.run(cmd, cwd=ROOT, check=True)
            live = Path(os.path.relpath(ROOT/"core/vibe/Fonts", entry.parent)).as_posix()
            entry.write_text(f"export {{Fonts}} from '{live}';")
            bad = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("Import the episode snapshot", bad.stderr)

    def test_frontend_contract(self):
        subprocess.run(["node", "--test", str(ROOT/"tools/tests/vibe_core.cjs")], cwd=ROOT, check=True)
