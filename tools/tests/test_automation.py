import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"tools")]

import episode
from _oss_env import media_tests_enabled, skip_reason


class AutomationTests(unittest.TestCase):
    def test_cleanup_does_not_claim_failed_deletion(self):
        with tempfile.TemporaryDirectory() as root:
            ep = Path(root)
            abandoned = ep / ".work" / ("a" * 32)
            abandoned.mkdir(parents=True)
            with patch.object(shutil, "rmtree", side_effect=PermissionError("file in use")):
                self.assertEqual(episode.clean_abandoned(ep, None), [])
            self.assertTrue(abandoned.is_dir())
            self.assertEqual(episode.clean_abandoned(ep, None), [abandoned.name])

    def test_detach_records_job_and_short_poll_returns_exit_code(self):
        folder = ROOT/"output/evergreen_vibe/2026-11-22/98_detach_probe"
        shutil.rmtree(folder, ignore_errors=True)
        (folder/"src").mkdir(parents=True)
        manifest = {"version": 1, "topic": "98_探针.md", "entry": "entry.tsx",
                    "previewComposition": "Review", "fullComposition": "Cinema",
                    "previewFrames": 900, "sfx": "src/sfx.wav"}
        (folder/"src/manifest.json").write_text(json.dumps(manifest), "utf-8")
        command = [sys.executable, "-B", str(ROOT/"tools/episode.py")]
        try:
            started = subprocess.run(command + ["snapshot", str(folder), "--detach"],
                                     cwd=ROOT, capture_output=True, text=True, check=True)
            job = json.loads(started.stdout)
            self.assertEqual(job["status"], "running")
            self.assertTrue((folder/".work/active_job.json").is_file())
            polled = subprocess.run(command + ["job", str(folder), "--wait", "20"],
                                    cwd=ROOT, capture_output=True, text=True, check=True)
            state = json.loads(polled.stdout)
            self.assertEqual(state["jobId"], job["jobId"])
            self.assertEqual(state["status"], "succeeded")
            self.assertEqual(state["exitCode"], 0)
            self.assertIsNone(state["error"])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    @unittest.skipUnless(media_tests_enabled(), skip_reason())
    def test_cdp_pipe_renders_without_loopback_port(self):
        root = ROOT/"temp/_work/cdp_test"
        shutil.rmtree(root, ignore_errors=True)
        (root/"run").mkdir(parents=True)
        (root/"public").mkdir()
        (root/"entry.tsx").write_text(
            'import {Composition, registerRoot, useCurrentFrame} from "remotion";\n'
            'const Comp = () => {const f = useCurrentFrame();\n'
            '  return <div style={{width:160,height:120,background:"#123456",color:"#fff"}}>{f}</div>;};\n'
            'const Root = () => <Composition id="T" component={Comp} durationInFrames={2}'
            ' fps={30} width={160} height={120} />;\n'
            'registerRoot(Root);\n', "utf-8")
        ffmpeg = episode.locate_tools()[0]
        plan = {"entry": str((root/"entry.tsx").resolve()), "publicDir": str((root/"public").resolve()),
                "composition": "T", "width": 160, "height": 120, "fps": 30, "frames": 2,
                "scale": 1, "concurrency": 1, "inputProps": {}, "timeline": {"frames": [0, 1]},
                "work": str((root/"run").resolve()), "ffmpeg": ffmpeg,
                "renderConfig": {"encoder": "libx264", "profile": "high", "level": "5.1",
                                 "pixFmt": "yuv420p", "colorSpace": "bt709", "crf": 16,
                                 "preset": "ultrafast", "gop": 120, "movflags": "+faststart"}}
        (root/"plan.json").write_text(json.dumps(plan), "utf-8")
        try:
            run = subprocess.run(["node", str(ROOT/"tools/render_episode.cjs"),
                                  str(root/"plan.json"), "--transport=cdp-pipe"],
                                 cwd=ROOT, capture_output=True, text=True, timeout=180)
            self.assertEqual(run.returncode, 0, run.stderr[-800:])
            movie = (root/"run/picture.mp4").read_bytes()
            self.assertGreater(len(movie), 500)
            self.assertEqual(movie[4:8], b"ftyp")
            frames = sorted((root/"run").glob("frame-*.png"))
            self.assertEqual(len(frames), 2)
            png = frames[0].read_bytes()
            self.assertNotEqual(png, frames[1].read_bytes(), "The registered composition must actually change frames")
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(int.from_bytes(png[16:20], "big"), 160)
            self.assertEqual(int.from_bytes(png[20:24], "big"), 120)
            self.assertNotIn("--remote-debugging-port", run.args)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
