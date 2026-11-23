"""Two human gates only: review (sample) and delivery (adoption).

topic/facts stay as history but never block anything, and the review approval
binds content bytes only, so tool upgrades and scheduling fields cannot void a
sample the director already signed.
"""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"tools")]

import episode
from test_production import score

SALT = ROOT/"output/evergreen_vibe/2026-11-22/04_fixture"


def render_args():
    return SimpleNamespace(concurrency=None, transport=None, bgm_gain=None)


def ship_args():
    return SimpleNamespace(work=None, note=None, clean_abandoned=False,
                           bgm_gain=None, concurrency=None, transport=None)


def sidecar(bgm):
    bgm.with_suffix(".beats.json").write_text(json.dumps({"source_sha256": episode.sha256_file(bgm)}), "utf-8")


def sample_fixture(ep):
    """Minimum artifacts for state-machine unit tests. test_seal runs real media."""
    folder = ep / "src/review"
    folder.mkdir(exist_ok=True)
    movie = folder / "preview.mp4"
    movie.write_bytes(b"state-machine sample fixture")
    digest = episode.sha256_file(movie)
    for name, data in (
        ("receipt.json", {"media": digest, "approved": episode.bindings(ep, "review")}),
        ("preview_qc.json", {"media_sha256": digest, "passed": True}),
    ):
        (folder / name).write_text(json.dumps(data), "utf-8")


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.enterContext(patch.object(episode, "ROOT", self.root))
        (self.root/"bed.wav").write_bytes(b"RIFF-bed")
        sidecar(self.root / "bed.wav")
        self.ep = self.root/"05_gate"
        (self.ep/"src/assets").mkdir(parents=True)
        (self.ep/"src/entry.tsx").write_text("// fixture")
        (self.ep/"src/sfx.wav").write_bytes(b"RIFF-fx")
        (self.ep/"facts_and_sources.md").write_text("fixture facts")
        self.manifest = dict(version=1, topic="card.md", entry="entry.tsx",
                             previewComposition="Review", fullComposition="Full",
                             previewFrames=900, sfx="src/sfx.wav", bgm="bed.wav",
                             licenseNote="fixture")
        self.save(self.manifest, score())

    def save(self, manifest, data):
        (self.ep/"src/manifest.json").write_text(json.dumps(manifest), "utf-8")
        (self.ep/"beats.json").write_text(json.dumps(data), "utf-8")

    def approve(self, gate="review"):
        if gate == "review":
            sample_fixture(self.ep)
        args = SimpleNamespace(action="approve", gate=gate, note="导演确认样片", accept_overrides=False)
        return episode.execute(args, self.ep, argparse.ArgumentParser())

    def test_only_two_gates_and_preview_needs_none(self):
        self.assertEqual(episode.GATES, ("review", "delivery"))
        state = episode.state(self.ep)
        self.assertEqual(state["nextGate"], "review")
        self.assertEqual(state["approved"], {})
        self.assertEqual(episode.plan(self.ep, "preview")["frames"], 900)
        # preview 不要求任何签字：把渲染入口换成哨兵，证明它已走到渲染而不是被门禁拦住。
        with patch.object(episode, "preflight", side_effect=RuntimeError("render-stub")):
            with self.assertRaisesRegex(RuntimeError, "render-stub"):
                episode.produce(self.ep, "preview", render_args())
        with self.assertRaisesRegex(ValueError, "review"):
            episode.produce(self.ep, "full", render_args())
        with self.assertRaisesRegex(ValueError, "review"):
            episode.ship(self.ep, ship_args(), argparse.ArgumentParser())

    def test_review_unlocks_full_and_stops_at_delivery(self):
        approval = self.approve()
        state = episode.state(self.ep)
        self.assertEqual(state["approved"]["review"], approval["id"])
        self.assertEqual(state["nextGate"], "delivery")
        with patch.object(episode, "preflight", side_effect=RuntimeError("render-stub")):
            with self.assertRaisesRegex(RuntimeError, "render-stub"):
                episode.produce(self.ep, "full", render_args())

    def test_review_binds_content_only(self):
        before = episode.bindings(self.ep, "review")
        for key in ("beats.json", "src/entry.tsx", "src/sfx.wav", "bgm"):
            self.assertIn(key, before)
        self.assertEqual([key for key in before if key.startswith("tools/")], [])
        for tooling in ("manifest_content_sha256", "preview", "preview_qc.json",
                        "package-lock.json", "src/manifest.json"):
            self.assertNotIn(tooling, before)

        approval = self.approve()
        # 纯工程调度字段与工具升级不影响已签样片。
        self.manifest.update(evidenceScript="src/evidence.py", concurrency=6,
                             previewFrames=600, publicDir="src/assets")
        self.save(self.manifest, score())
        self.assertEqual(episode.state(self.ep)["nextGate"], "delivery")
        self.assertEqual(episode.state(self.ep)["approved"]["review"], approval["id"])

        # 改动画源码或时间轴，立刻回到 review。
        (self.ep/"src/entry.tsx").write_text("// fixture v2")
        self.assertEqual(episode.state(self.ep)["nextGate"], "review")
        (self.ep/"src/entry.tsx").write_text("// fixture")
        self.assertEqual(episode.state(self.ep)["nextGate"], "delivery")
        data = score()
        data["beats"][0]["lines"] = ["改过的句子"]
        self.save(self.manifest, data)
        self.assertEqual(episode.state(self.ep)["nextGate"], "review")

    def test_legacy_gate_approval_is_recorded_not_enforced(self):
        legacy = self.approve("facts")
        self.assertEqual(legacy["gate"], "facts")
        state = episode.state(self.ep)
        self.assertEqual(state["nextGate"], "review")
        self.assertNotIn("facts", state["approved"])
        self.assertEqual(len(state["history"]), 1)

    @unittest.skipUnless(SALT.is_dir(), "锁定的首部 2K 成片不在本检出中")
    def test_locked_episode_verify_still_passes(self):
        before = sorted((p.name, p.stat().st_size) for p in SALT.iterdir())
        result = episode.execute(SimpleNamespace(action="verify"), SALT, argparse.ArgumentParser())
        self.assertTrue(result["passed"])
        with patch.object(episode, "ROOT", ROOT):
            self.assertEqual(episode.state(SALT)["nextGate"], "done")
        self.assertEqual(before, sorted((p.name, p.stat().st_size) for p in SALT.iterdir()))


if __name__ == "__main__":
    unittest.main()
