import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["docs/AGENTS.md","docs/STYLE_B_SILENT_VIBE.md","docs/PROCESS.md","docs/prompt.md","README.md","docs/PRODUCTION.md"]


class DocsTests(unittest.TestCase):
    def test_actions_and_dependencies(self):
        docs = {name:(ROOT/name).read_text("utf-8") for name in DOCS}
        for name, text in docs.items():
            with self.subTest(name=name):
                self.assertNotRegex(text, r"阶段\s*[123一二三]|第[一二三123]阶段")
                for link in re.findall(r"\[[^\]]+\]\(([^)#]+)\)", text):
                    if "://" not in link:
                        self.assertTrue(((ROOT/name).parent/link).exists(), (name,link))
        engines = json.loads((ROOT/"package.json").read_bytes())["engines"]["node"]
        self.assertIn(f"Node engines 为 `{engines}`", docs["README.md"])
        for gate in ("review","delivery"):
            self.assertIn(gate, docs["docs/PROCESS.md"])
        self.assertIn("两处", docs["docs/PROCESS.md"])
        for name, text in docs.items():
            with self.subTest(gates=name):
                self.assertNotRegex(text, r"四个卡点|四处人工卡点|四次批准")
        for name in ("tools/episode.py","docs/PRODUCTION.md","tools/profiles/vibe-3.3.json",
                     "tools/profiles/vibe-3.4.json","core/vibe"):
            self.assertTrue((ROOT/name).exists(), name)

    def test_prompt_matches_profiles(self):
        prompt = (ROOT/"docs/prompt.md").read_text("utf-8")
        flat = re.sub(r"[`\s]", "", prompt)
        profile = json.loads((ROOT/"tools/profiles/vibe-3.3.json").read_bytes())
        extended = json.loads((ROOT/"tools/profiles/vibe-3.4.json").read_bytes())
        version = json.loads((ROOT/"core/vibe/version.json").read_bytes())["coreVersion"]
        bgm = json.loads((ROOT/"assets/bgm/bgm.beats.json").read_bytes())
        hard = profile["hard"]
        video, visual, audio, timeline = (hard[k] for k in ("video","visual","audio","timeline"))
        beats = profile["defaults"]["beatDurationSec"]
        expected = {
            "canvas": f"{video['width']}×{video['height']}@{video['fps']}fps",
            "preview": (f"{int(video['width']*video['previewScale'])}×"
                        f"{int(video['height']*video['previewScale'])}@{video['previewFps']}fps"),
            "previewSec": f"只渲前{video['previewSec'][0]:.0f}–{video['previewSec'][1]:.0f}s",
            "level": f"High@{video['level']}",
            "pixFmt": video["pixFmt"],
            "crf": f"crf{video['crf']}",
            "preset": f"preset{video['preset']}",
            "gop": f"-g{video['gop']}",
            "safeZone": (f"x:{visual['safeZone'][0]}–{visual['safeZone'][2]},"
                         f"y:{visual['safeZone'][1]}–{visual['safeZone'][3]}"),
            "roi": f"y:{visual['roiY'][0]}–{visual['roiY'][1]}",
            "roiDelta": f"roi_delta<{visual['roiDelta']}",
            "static": f"≤{visual['maxStaticSec']:.2f}s",
            "dark": (f"studio_dark底色灰度<{visual['darkBelow']}占"
                     f"[{visual['lighting']['studio_dark'][0]}%,{visual['lighting']['studio_dark'][1]}%]"),
            "light": (f"keynote_light底色灰度>{visual['lightAbove']}占"
                      f"[{visual['lighting']['keynote_light'][0]}%,{visual['lighting']['keynote_light'][1]}%]"),
            "lufs": f"{audio['lufs'][0]}～{audio['lufs'][1]}LUFS",
            "truePeak": f"≤{audio['truePeakMax']:.1f}dBTP",
            "gap": f">{audio['gapMaxSec']:.1f}s",
            "gapWindow": f"[{audio['gapStartSec']:.1f}s,total-{audio['gapEndMarginSec']:.1f}s]",
            "climax": f"≤{audio['climaxErrorSec']:.2f}s",
            "sfxPeak": f"峰值[{audio['sfxPeak'][0]},{audio['sfxPeak'][1]}]dB",
            "standard": f"{timeline['duration']['standard'][0]}–{timeline['duration']['standard'][1]}s",
            "long": f"{timeline['duration']['long'][0]}–{timeline['duration']['long'][1]}s",
            "cuts": (f"cinema≤{timeline['maxCuts']['cinema']}"
                     f"/rhythmic≤{timeline['maxCuts']['rhythmic']}"),
            "cues": f"微音效{timeline['cinemaCues'][0]}–{timeline['cinemaCues'][1]}个",
            "maxChars": f"上限{timeline['maxTextChars']}字",
            "reading": f"{timeline['readingSec'][0]:.2f}–{timeline['readingSec'][1]:.2f}s",
            "beatTiers": "/".join(f"{low:.1f}–{high:.1f}s" for low, high in beats),
            "coreVersion": f"core/vibe{version}",
            "bpm": f"BPM{bgm['bpm']}",
            "bar": f"小节{bgm['bar_sec']:.4f}s",
            "drop1": f"主Drop{bgm['drops'][0]['t']:.3f}s",
            "drop2": f"与{bgm['drops'][1]['t']:.3f}s",
            "decoderMae": f"maxFrameMAE={hard['decoder']['maxMae']}",
            "decoderPeak": f"maxSampleDelta={hard['decoder']['maxPeak']}",
            "profile33": "vibe-3.3.json",
            "profile34": "vibe-3.4.json",
            "fontCount": "4族8文件",
        }
        for label, value in expected.items():
            with self.subTest(field=label):
                self.assertIn(value, flat)

        self.assertEqual(extended["allowedOverrides"], ["beat_duration"])
        self.assertEqual(profile["allowedOverrides"], [])
        fonts = [p for p in (ROOT/"assets/fonts").iterdir()
                 if p.suffix.lower() in {".woff",".woff2",".otf"}]
        notice = (ROOT/"assets/fonts/FONT-NOTICE.md").read_text("utf-8")
        if fonts:
            self.assertEqual(len(fonts), 8)
        else:
            # No font binaries in the OSS repo; assert the documented 4-family/8-file contract.
            self.assertIn("4", notice)
            self.assertIn("8", notice)

        for pattern in (r"Stage\s*[12]", r"阶段\s*[12]", r"两阶段"):
            with self.subTest(pattern=pattern):
                self.assertNotRegex(prompt, pattern)
        self.assertNotRegex(prompt, r"第一件事[:：][^\n]*episode\.py")
