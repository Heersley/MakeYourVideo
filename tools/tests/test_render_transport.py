"""cdp-pipe must start Chrome with only the run directory writable, and must
never exit silently: the real code and stderr belong in the run directory, and a
detached job that dies must end as `failed` in active_job.json.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"tools")]

import episode
from test_production import score
from _oss_env import media_tests_enabled, skip_reason

RENDER = ROOT/"tools/render_episode.cjs"
SANDBOX_KEYS = ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")


def workspace():
    """A disposable run root that also works from a freshly restored package."""
    folder = ROOT/"temp/_work"
    folder.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=folder)


def build_plan(root, frames=3, width=160, height=120):
    (root/"run").mkdir(parents=True, exist_ok=True)
    (root/"public").mkdir(exist_ok=True)
    (root/"entry.tsx").write_text(
        'import {Composition, registerRoot, useCurrentFrame} from "remotion";\n'
        'const Comp = () => {const f = useCurrentFrame();\n'
        '  return <div style={{width:%d,height:%d,background:"#123456",color:"#fff"}}>{f}</div>;};\n'
        'const Root = () => <Composition id="T" component={Comp} durationInFrames={%d}'
        ' fps={30} width={%d} height={%d} />;\n'
        'registerRoot(Root);\n' % (width, height, frames, width, height), "utf-8")
    plan = {"entry": str((root/"entry.tsx").resolve()), "publicDir": str((root/"public").resolve()),
            "composition": "T", "width": width, "height": height, "fps": 30, "frames": frames,
            "scale": 1, "concurrency": 1, "inputProps": {}, "timeline": {"frames": list(range(frames))},
            "work": str((root/"run").resolve()), "ffmpeg": episode.locate_tools()[0],
            "renderConfig": {"encoder": "libx264", "profile": "high", "level": "5.1",
                             "pixFmt": "yuv420p", "colorSpace": "bt709", "crf": 16,
                             "preset": "ultrafast", "gop": 120, "movflags": "+faststart"}}
    (root/"plan.json").write_text(json.dumps(plan), "utf-8")
    return plan


class RenderTransportTests(unittest.TestCase):
    def render(self, root, env=None):
        return subprocess.run(["node", str(RENDER), str(root/"plan.json"), "--transport=cdp-pipe"],
                              cwd=ROOT, capture_output=True, text=True, timeout=300, env=env)

    @unittest.skipUnless(media_tests_enabled(), skip_reason())
    def test_cdp_pipe_renders_with_only_the_run_directory_writable(self):
        with workspace() as tmp:
            root = Path(tmp)
            build_plan(root)
            # A regular file where the host expects a profile root: nothing can be
            # created beneath it, which is exactly how the sandboxed desktop fails.
            blocked = root/"blocked"
            blocked.write_text("not a directory", "utf-8")
            env = {**os.environ, **{key: str(blocked/"appdata") for key in SANDBOX_KEYS}}
            run = self.render(root, env)
            self.assertEqual(run.returncode, 0, run.stderr[-1500:])
            movie = (root/"run/picture.mp4").read_bytes()
            self.assertGreater(len(movie), 500)
            self.assertEqual(movie[4:8], b"ftyp")
            self.assertEqual(len(sorted((root/"run").glob("frame-*.png"))), 3)
            launch = json.loads((root/"run/chrome-launch.json").read_text("utf-8"))
            self.assertEqual(launch["exitCode"], 0)
            self.assertIsNone(launch["spawnError"])
            for flag in ("--no-sandbox", "--disable-crash-reporter-for-testing", "--disable-breakpad",
                         "--no-crash-upload", "--remote-debugging-pipe"):
                self.assertIn(flag, launch["args"])
            work = str((root/"run").resolve())
            self.assertEqual(set(launch["sandboxEnv"]), set(SANDBOX_KEYS))
            for key, value in launch["sandboxEnv"].items():
                self.assertTrue(value.startswith(work), (key, value))
                self.assertTrue(Path(value).is_dir(), key)
            stderr = (root/"run/chrome-stderr.log").read_text("utf-8", "replace")
            # Chromium may log a disconnected Crashpad registration pipe even with
            # crash reporting disabled. The real zero exit and the PNGs above check startup.
            self.assertNotIn("crashpad_database_win", stderr.lower())

    @unittest.skipUnless(media_tests_enabled(), skip_reason())
    def test_chrome_startup_failure_keeps_code_and_stderr(self):
        with workspace() as tmp:
            root = Path(tmp)
            build_plan(root)
            node = shutil.which("node")
            self.assertTrue(node)
            run = self.render(root, {**os.environ, "VIBE_CHROME": node})
            self.assertEqual(run.returncode, 1)
            self.assertIn("Chrome exited", run.stderr)
            launch = json.loads((root/"run/chrome-launch.json").read_text("utf-8"))
            self.assertNotEqual(launch["exitCode"], 0)
            self.assertIn("bad option", launch["stderrTail"])
            self.assertIn("bad option", (root/"run/chrome-stderr.log").read_text("utf-8", "replace"))
            self.assertFalse((root/"run/picture.mp4").exists())

    def test_job_supervisor_records_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp)
            args = SimpleNamespace(job_id="a"*32, job_command=json.dumps(
                [sys.executable, "-B", "-c", "raise SystemExit(3)"]))
            result = episode.supervise(ep, args)
            record = json.loads((ep/".work/active_job.json").read_text("utf-8"))
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["exitCode"], 3)
            self.assertEqual(record["jobId"], "a"*32)
            self.assertIn("3", record["error"])
            self.assertIsNotNone(record["pid"])
            self.assertEqual(result["exitCode"], 3)

            args = SimpleNamespace(job_id="b"*32, job_command=json.dumps(
                [str(ep/"missing-python.exe"), "-V"]))
            episode.supervise(ep, args)
            record = json.loads((ep/".work/active_job.json").read_text("utf-8"))
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["exitCode"], 1)
            self.assertIn("FileNotFoundError", record["error"])
            self.assertIsNotNone(record["finishedAt"])

    def test_detached_failure_is_reported_in_active_job(self):
        folder = ROOT/"output/evergreen_vibe/2026-11-22/97_detach_fail"
        shutil.rmtree(folder, ignore_errors=True)
        (folder/"src").mkdir(parents=True)
        (folder/"src/sfx.wav").write_bytes(b"RIFF-fx")
        (folder/"src/bgm.wav").write_bytes(b"RIFF-bed")
        (folder/"beats.json").write_text(json.dumps(score()), "utf-8")
        (folder/"beats.json").write_text(json.dumps(score()), "utf-8")
        (folder/"src/manifest.json").write_text(json.dumps({
            "version": 1, "topic": "97_探针.md", "entry": "entry.tsx",
            "previewComposition": "Review", "fullComposition": "Cinema",
            "previewFrames": 900, "sfx": "src/sfx.wav",
            "bgm": "output/evergreen_vibe/2026-11-22/97_detach_fail/src/bgm.wav",
            "licenseNote": "fixture"}), "utf-8")
        command = [sys.executable, "-B", str(ROOT/"tools/episode.py")]
        try:
            started = subprocess.run(command + ["preview", str(folder), "--detach"],
                                     cwd=ROOT, capture_output=True, text=True, check=True, timeout=120)
            job = json.loads(started.stdout)
            self.assertEqual(job["status"], "running")
            polled = subprocess.run(command + ["job", str(folder), "--wait", "40"],
                                    cwd=ROOT, capture_output=True, text=True, check=True, timeout=180)
            state = json.loads(polled.stdout)
            self.assertEqual(state["jobId"], job["jobId"])
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["exitCode"], 1)
            self.assertIn("入口", state["error"])
            record = json.loads((folder/".work/active_job.json").read_text("utf-8"))
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["exitCode"], 1)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
