"""Stereo SFX master must reach mix_bgm and sfx_only.wav without the -3.01 dB upmix.

FFmpeg spreads a mono master over two channels at 1/sqrt(2) each. A -14.0 dB
master therefore arrived at -17.0 dB and tripped the -16 dB floor. The engine now
writes real two-channel PCM, so the read-back attenuation must be exactly 0.0 dB.
"""
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"tools"), str(ROOT/"core/vibe")]

import episode
import sfx_engine
from bgm_common import decode_f32, locate_tools, sha256_file

TARGET_DB = -14.0
FPS, FRAMES = 30, 150


def write_pcm(path, samples, rate=48000):
    pcm = np.rint(np.asarray(samples, np.float64) * 32767).astype("<i2")
    if pcm.ndim == 1:
        pcm = pcm[:, None]
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(pcm.shape[1])
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return path


def peak_dbfs(samples):
    return 20 * math.log10(max(float(np.abs(samples).max()), 1e-12))


class StereoMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg, _, _ = locate_tools()
        workspace = ROOT/"temp/_work"
        workspace.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(dir=workspace))
        cls.profile = episode.load_profile().data

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def render_master(self, folder):
        rate = self.profile["hard"]["audio"]["sampleRate"]
        t = np.arange(int(FRAMES / FPS * rate)) / rate
        tone = 0.7 * np.sin(2 * np.pi * 440 * t) * np.exp(-t * 3.0)
        return sfx_engine.render_sfx([{"frame": 0, "voice": "tone"}],
                                     {"tone": lambda event, hz, rng: tone},
                                     FRAMES, FPS, self.profile, folder/"master.wav")

    def test_mono_source_really_loses_three_db_on_read(self):
        # The defect this change removes is a property of the reader, so it is
        # pinned here: a mono master still arrives 3.01 dB quieter as stereo.
        folder = self.tmp/"mono"
        folder.mkdir(exist_ok=True)
        mono = write_pcm(folder/"mono.wav", np.full(4800, 0.2))
        direct = peak_dbfs(decode_f32(self.ffmpeg, mono, sr=48000, channels=1))
        upmixed = peak_dbfs(decode_f32(self.ffmpeg, mono, sr=48000, channels=2))
        self.assertAlmostEqual(direct - upmixed, 3.01, places=2)

    def test_master_is_equal_channel_stereo_at_profile_midpoint(self):
        folder = self.tmp/"stereo"
        folder.mkdir(exist_ok=True)
        report = self.render_master(folder)
        self.assertEqual(report["channels"], 2)
        with wave.open(str(folder/"master.wav")) as handle:
            self.assertEqual(handle.getnchannels(), 2)
            frames = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
        channels = frames.reshape(-1, 2)
        np.testing.assert_array_equal(channels[:, 0], channels[:, 1])
        self.assertAlmostEqual(report["peakDbfs"], TARGET_DB, delta=0.05)
        read_back = peak_dbfs(decode_f32(self.ffmpeg, folder/"master.wav", sr=48000, channels=2))
        self.assertAlmostEqual(read_back, TARGET_DB, delta=0.05)

        folder2 = self.tmp/"authored"
        folder2.mkdir(exist_ok=True)
        left = np.linspace(-0.6, 0.6, 2400)
        authored = np.stack([left, -left], axis=1)
        stereo = sfx_engine.render_sfx([{"frame": 0, "voice": "pair"}],
                                       {"pair": lambda event, hz, rng: authored},
                                       FRAMES, FPS, self.profile, folder2/"pair.wav")
        with wave.open(str(folder2/"pair.wav")) as handle:
            decoded = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
        decoded = decoded.reshape(-1, 2)
        self.assertEqual(stereo["channels"], 2)
        # An authored pair keeps its two channels instead of being folded to L = R.
        np.testing.assert_array_equal(decoded[:, 0], -decoded[:, 1])
        self.assertGreater(int(decoded[:, 0].max()), 0)
        self.assertLess(int(decoded[:, 1].min()), 0)

    def test_end_to_end_level_survives_mix_bgm(self):
        folder = self.tmp/"mix"
        folder.mkdir(exist_ok=True)
        self.render_master(folder)
        video = folder/"picture.mp4"
        subprocess.run([self.ffmpeg, "-y", "-v", "error", "-f", "lavfi",
                        "-i", f"color=c=black:s=160x120:r={FPS}:d={FRAMES/FPS}",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(video)],
                       check=True, timeout=120)
        rate, seconds = 48000, FRAMES / FPS
        t = np.arange(int(seconds * rate)) / rate
        bed = np.tile(0.02 * np.sin(2 * np.pi * 220 * t), (2, 1)).T
        bgm = write_pcm(folder/"bed.wav", bed)
        bgm.with_suffix(".beats.json").write_text(json.dumps(
            {"source_sha256": sha256_file(bgm), "bpm": 120, "bar_sec": 2.0,
             "bar_times": [0, 2, 4, 6], "drops": [{"t": 2.0}]}), "utf-8")
        (folder/"beats.json").write_text(json.dumps({"beats": []}), "utf-8")
        stem = folder/"sfx_only.wav"
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT/"tools/mix_bgm.py"), "--video", str(video),
             "--bgm", str(bgm), "--beats", str(folder/"beats.json"), "--license-note", "fixture",
             "--sfx", str(folder/"master.wav"), "--sfx-out", str(stem),
             "--out", str(folder/"out.mp4"), "--preview-duration", str(seconds)],
            capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-1200:])
        report = json.loads((folder/"preview_mix_report.json").read_text("utf-8"))
        self.assertAlmostEqual(report["sfx_peak_dbfs"], TARGET_DB, delta=0.3)
        self.assertAlmostEqual(report["exported_sfx_peak_dbfs"], TARGET_DB, delta=0.3)
        with wave.open(str(stem)) as handle:
            self.assertEqual(handle.getnchannels(), 2)
            exported = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
        self.assertAlmostEqual(peak_dbfs(exported.astype(np.float64) / 32768), TARGET_DB, delta=0.3)


if __name__ == "__main__":
    unittest.main()
