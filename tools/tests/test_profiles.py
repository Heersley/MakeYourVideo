"""Profile, approval, and archive regressions. Media I/O in the finish fixture is simulated."""
import argparse
import copy
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from test_production import TOOLS, av_reports, episode, mix_bgm, qc, score
from test_gates import sample_fixture, sidecar
import backup_infra
import profile_loader as profiles


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def timed_score(first):
    data = score()
    template = data["beats"][0]
    beats = []
    start = 0
    for index, duration in enumerate([first] + [5] * 15, 1):
        beats.append(dict(template, id=index, startSec=start, endSec=start + duration,
                          durationSec=duration, readingStartSec=start + 0.5, readingEndSec=start + 1.5))
        start += duration
    return dict(data, beats=beats, totalSec=start)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.ep = self.root / "04_fixture"
        (self.ep / "src/assets").mkdir(parents=True)
        (self.ep / "src/entry.tsx").write_text("// fixture")
        (self.ep / "src/sfx.wav").write_bytes(b"RIFF-fx")
        (self.root / "bed.wav").write_bytes(b"RIFF-bed")
        sidecar(self.root / "bed.wav")
        (self.ep / "facts_and_sources.md").write_text("fixture facts")
        topic = self.root / "inbox/evergreen_vibe/card.md"
        topic.parent.mkdir(parents=True)
        topic.write_text("---\ntrack: evergreen_vibe\ncut_mode: cinema\nlighting: studio_dark\n"
                         "asset_layers: [vector]\nduration_tier: standard\nstatus: approved\ndate: 2026-11-22\n---")
        self.manifest = dict(version=1, topic="card.md", entry="entry.tsx", previewComposition="Review",
                             fullComposition="Full", previewFrames=900, sfx="src/sfx.wav",
                             profile="vibe-3.4", bgm="bed.wav", licenseNote="fixture")
        self.request = dict(rule="beat_duration", scope="B01", value=3.5, reason="导演要求短钩子")
        self.save(self.manifest, timed_score(3.5))
        stack.enter_context(patch.object(episode, "ROOT", self.root))

    def save(self, manifest, data):
        write_json(self.ep / "src/manifest.json", manifest)
        write_json(self.ep / "beats.json", data)

    def approve(self, gate="review", accept=False, note="确认样片与 B01 节奏"):
        if gate == "review":
            sample_fixture(self.ep)
        args = SimpleNamespace(action="approve", gate=gate, accept_overrides=accept, note=note)
        return episode.execute(args, self.ep, argparse.ArgumentParser())

    def submit(self):
        self.manifest["overrides"] = [self.request]
        self.save(self.manifest, timed_score(3.5))

    def test_beat_override_needs_manifest_entry_not_a_gate(self):
        for entry in (episode.plan, episode.preflight):
            with self.subTest(entry=entry), self.assertRaisesRegex(ValueError, "B01"):
                entry(self.ep, "full")
        self.submit()
        self.assertEqual(episode.plan(self.ep, "preview")["applied_overrides"], [self.request])
        self.assertEqual(episode.state(self.ep)["nextGate"], "review")

    def test_override_exact_value_and_content_drift(self):
        self.submit()
        for mode in ("preview", "full"):
            self.assertEqual(episode.plan(self.ep, mode)["applied_overrides"], [self.request])
        # Engineering fields are not content: they never invalidate a sample.
        self.manifest["concurrency"] = 4
        self.save(self.manifest, timed_score(3.5))
        self.assertEqual(episode.state(self.ep)["nextGate"], "review")
        self.save(self.manifest, timed_score(2))
        with self.assertRaisesRegex(ValueError, "B01"):
            episode.plan(self.ep, "full")

    def test_rule_scope_and_hard_limits(self):
        for rule in ("level", "maxMae", "safeZone", "lufsMin"):
            manifest = dict(self.manifest, overrides=[dict(self.request, rule=rule)])
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                episode.validate_contract("manifest", manifest)
        with self.assertRaises(ValueError):
            episode.validate_contract("manifest", dict(self.manifest, overrides=[dict(self.request, reason=" ")]))
        for changes in ({"profile":"vibe-3.3"}, {"overrides":[dict(self.request, scope="B02")]},
                        {"overrides":[self.request, self.request]}):
            manifest = dict(self.manifest, overrides=[self.request])
            self.save(manifest | changes, timed_score(3.5))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                episode.plan(self.ep, "full")
        profile = profiles.load_profile("vibe-3.4")
        data = timed_score(3.5)
        data["beats"][0]["readingEndSec"] = 0.9
        with self.assertRaisesRegex(ValueError, "阅读窗"):
            episode.sample_plan(data, profile, [self.request])
        with self.assertRaisesRegex(ValueError, "总时长"):
            episode.sample_plan(dict(data, totalSec=70), profile, [self.request])

    def test_workstation_precedence_and_decoder(self):
        shutil.copyfile(TOOLS / "env.example.json", self.root / "env.example.json")
        with patch.object(profiles, "TOOLS", self.root):
            self.assertEqual(profiles.environment()["concurrency"], 2)
            self.assertEqual(profiles.environment(legacy=3)["concurrency"], 3)
            for n in (1, 4):
                write_json(self.root / "env.local.json", {"concurrency":n})
                self.assertEqual(profiles.environment(legacy=3)["concurrency"], n)
                self.assertEqual(profiles.environment(concurrency=2)["concurrency"], 2)
            with redirect_stderr(io.StringIO()) as out:
                self.assertEqual(profiles.environment(concurrency=5)["concurrency"], 5)
            self.assertIn("concurrency=5", out.getvalue())
            for val in (0, -1, True):
                with self.assertRaises(ValueError):
                    profiles.environment(concurrency=val)
            write_json(self.root / "env.local.json", {"hwaccel":"software"})
            with self.assertRaisesRegex(ValueError, "D3D11VA"):
                profiles.environment()

    def test_registered_profile_propagates_through_four_consumers(self):
        tools = self.root / "tools"
        shutil.copytree(TOOLS / "contracts", tools / "contracts")
        (tools / "profiles").mkdir()
        shutil.copyfile(TOOLS / "env.example.json", tools / "env.example.json")
        changed = copy.deepcopy(profiles.load_profile().data)
        changed["id"] = "vibe-9.9"
        changed["hard"]["video"]["crf"] = 17
        changed["hard"]["audio"]["lufs"] = [-18, -17]
        file = tools / "profiles/vibe-9.9.json"
        write_json(file, changed)
        write_json(tools / "profiles/registry.json", {changed["id"]:episode.sha256_file(file)})
        self.save(dict(self.manifest, profile=changed["id"]), score())
        with patch.object(profiles, "TOOLS", tools):
            profile = profiles.load_profile(changed["id"])
            plan = episode.plan(self.ep, "full")
            node = "const {encoderArgs}=require(process.argv[1]);console.log(JSON.stringify(encoderArgs(JSON.parse(require('fs').readFileSync(0,'utf8')))))"
            result = subprocess.run(["node", "-e", node, str(TOOLS/"render_episode.cjs")], check=True,
                                    input=json.dumps(plan | {"work":str(self.root)}), capture_output=True, text=True)
            args = json.loads(result.stdout)
            self.assertEqual(args[args.index("-crf") + 1], "17")
            self.assertEqual(plan["profile_sha256"], profile.stamp["profile_sha256"])
            dec, mix = av_reports()
            self.assertEqual(mix_bgm.final_audio_failures(profile.hard["audio"], -16, -2, -13, 75, 75, 0),
                             ["integrated_lufs"])
            with self.assertRaisesRegex(ValueError, "integrated_lufs"):
                qc.av_checks(dec, mix, 120, profile)
            qc.av_checks(dec, mix | {"integrated_lufs":-17}, 120, profile)
            file.write_bytes(file.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                profiles.load_profile(changed["id"])

    def test_finish_and_offline_verify_archive(self):
        self.exercise_archive(False)

    def test_finish_with_pinned_core(self):
        self.exercise_archive(True)

    def exercise_archive(self, with_core):
        self.submit()
        if with_core:
            episode.core_snapshot.install(self.ep)
        approval = self.approve()
        ep = self.ep
        profile = profiles.load_profile("vibe-3.4")
        run = "a" * 32
        work = ep / ".work" / run
        candidate = work / "delivery" / ep.name
        (candidate / "src").mkdir(parents=True)
        for path in (candidate / episode.film_name(ep), candidate / "src/sfx_only.wav", work / "picture.mp4"):
            path.write_bytes(b"simulated media")
        digest = episode.sha256_file(work / "picture.mp4")
        timeline = episode.sha256_file(ep / "beats.json")
        plan = episode.sample_plan(timed_score(3.5), profile, [self.request])
        for frame in plan["frames"]:
            (work / f"frame-{frame}.png").write_bytes(b"source frame")
        frames = {str(n):episode.sha256_file(work / f"frame-{n}.png") for n in plan["frames"]}
        write_json(work / "receipt.json", dict(profile.stamp, media=digest, picture=digest,
                                               approved=approval["bindings"], frames=frames))
        write_json(work / "layout.json", dict(passed=True, issues=[], boxes={}, picture_sha256=digest))
        for filename in ("encoder.json", "render-plan.json"):
            write_json(work / filename, {})
        import cv2
        import numpy as np
        image = cv2.imencode(".png", np.zeros((2, 2, 3), np.uint8))[1].tobytes()
        for name in ("contact_sheet.png", "cover.png"):
            (work / name).write_bytes(image)
        write_json(ep / "src/review/receipt.json", {"run":"b"*32})
        dec, mix = av_reports(plan["count"])
        dec.update(profile.stamp, input={"sha256":digest})
        mix.update(profile.stamp, media_sha256=digest, timeline_sha256=timeline, aligned_climax_sec=55, sfx_sha256=digest)
        duration = plan["count"] / 60
        mix.update(video_duration_sec=duration, audio_duration_sec=duration, bgm_gap_check={
            "pass": True, "bedPresent": True, "maxAllowedGapSec": 1.5, "gapCount": 0, "gaps": [],
            "longestGapSec": 0, "window": [0.5, duration - 2]})
        bad_gap = dict(mix["bgm_gap_check"], gapCount=1)
        with self.assertRaisesRegex(ValueError, "断层明细"):
            qc.av_checks(dec, mix | {"bgm_gap_check":bad_gap}, plan["count"], profile)
        write_json(candidate / "bgm_mix_report.json", mix)
        reading = dict(frames=plan["frames"], reading={key:dict(frames=val, maxSampleDelta=0)
                       for key,val in plan["reading"].items()}, seams=[dict(frames=p, seam_delta=0) for p in plan["seams"]])
        with ExitStack() as stack:
            for func, value in (("original_frames", reading),
                                ("decoded_metrics", dict(lightPct=90, roiLongestSec=0)),
                                ("audit_video_stream", dict(faststart=True, videoStreamHash="SHA256=fixture"))):
                stack.enter_context(patch.object(qc, func, return_value=value))
            stack.enter_context(patch.object(qc.subprocess, "run", side_effect=lambda cmd, **kw: write_json(Path(cmd[-1]), dec)))
            self.assertTrue(qc.finish(ep, work, "fixture review")["passed"])
        final = episode.read(ep / "src/final_qc.json")
        if with_core:
            pin = episode.read(ep / "src/manifest.json")["coreSnapshot"]
            self.assertEqual(pin, final["coreSnapshot"])
            clock = ep / "src/vendor/vibe/clock.ts"
            original = clock.read_bytes()
            clock.write_bytes(original + b" ")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                qc.verify(ep)
            clock.write_bytes(original)
        self.assertEqual(final["approvalId"], approval["id"])
        self.assertEqual(final["approvalGate"], "review")
        self.assertEqual(final["approvalFile"], "content-approval.json")
        self.assertEqual(final["applied_overrides"], [self.request])
        self.assertFalse(work.exists())
        # 交付归档只认 review 签字；采纳后流程结束。
        self.assertEqual(episode.state(ep)["nextGate"], "delivery")
        delivery = episode.execute(SimpleNamespace(action="approve", gate="delivery",
            note="采纳本部成片", accept_overrides=False), ep, argparse.ArgumentParser())
        self.assertEqual(delivery["gate"], "delivery")
        self.assertEqual(episode.state(ep)["nextGate"], "done")
        # Archive verification needs the schema but never consults an installed profile registry.
        shutil.copytree(TOOLS / "contracts", self.root / "contracts")
        with patch.object(profiles, "TOOLS", self.root):
            self.assertTrue(qc.verify(ep)["passed"])
            folder = ep / "src/production" / run
            snap = folder / "profile.json"
            snap.write_bytes(profile.raw + b" ")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                qc.verify(ep)
            snap.write_bytes(profile.raw)
            write_json(folder / final["approvalFile"], approval | {"note":"changed"})
            with self.assertRaisesRegex(ValueError, "批准记录摘要"):
                qc.verify(ep)

    def test_strict_diagnostic_flags_cannot_relax_gate(self):
        import decoder_check
        for flag, value in (("--every", "60"), ("--gray-min-area-pct", "101"), ("--iframe-warn", "1")):
            with self.subTest(flag=flag), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                decoder_check.main(["--strict", flag, value])
            self.assertEqual(caught.exception.code, 2)

    def test_recovery_excludes_local_settings(self):
        for name in backup_infra.ROOT_FILES:
            (self.root / name).write_text(name)
        tools = self.root / "tools"
        tools.mkdir()
        write_json(tools / "ENV.LOCAL.JSON", {"pythonPath":"machine-only"})
        write_json(tools / "env.example.json", {})
        fonts = self.root / "assets/fonts"
        fonts.mkdir(parents=True)
        (fonts / "test.otf").write_bytes(b"OTTO")
        dest = self.root / "test.zip"
        with patch.object(backup_infra, "ROOT", self.root):
            backup_infra.create(dest)
        with ZipFile(dest) as archive:
            self.assertEqual(archive.read("assets/fonts/test.otf"), b"OTTO")
            self.assertIn("tools/env.example.json", archive.namelist())
            self.assertNotIn("tool/env.local.json", [name.lower() for name in archive.namelist()])
