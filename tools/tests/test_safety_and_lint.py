import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS_JSON = ROOT / ".agents/hooks.json"
GATE_SCRIPT = ROOT / ".agents/hooks/safety_gate.cjs"
CHECK_ENTRY = ROOT / "tools/check_entry.cjs"


def run_hook(command_line, tool_name="run_command"):
    payload = {
        "hookEventName": "PreToolUse",
        "toolCall": {"id": "test_1", "name": tool_name, "args": {"CommandLine": command_line}},
    }
    proc = subprocess.run(
        ["node", "./hooks/safety_gate.cjs"],
        cwd=ROOT / ".agents",
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def run_check_entry(code):
    with tempfile.TemporaryDirectory(dir=ROOT / "temp/_work") as tmp:
        entry = Path(tmp) / "entry.tsx"
        entry.write_text(code, encoding="utf-8")
        return subprocess.run(
            ["node", str(CHECK_ENTRY), str(entry)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )


class SafetyHookTests(unittest.TestCase):
    def test_hooks_json_points_to_existing_script(self):
        cfg = json.loads(HOOKS_JSON.read_text("utf-8"))
        self.assertIn("makeyourvideo-safety-gate", cfg)
        self.assertTrue(GATE_SCRIPT.is_file())
        pre = cfg["makeyourvideo-safety-gate"]["PreToolUse"][0]
        self.assertEqual(pre["matcher"], "run_command")
        self.assertIn("safety_gate.cjs", pre["hooks"][0]["command"])

    def test_denies_git_gc_and_prune(self):
        for cmd in (
            "git gc",
            "git -C . prune --expire=now",
            "& $git gc --aggressive",
            "echo ok; git --no-pager prune",
        ):
            with self.subTest(cmd=cmd):
                res = run_hook(cmd)
                self.assertEqual(res["decision"], "deny")

    def test_allows_safe_git_and_grep_mentions(self):
        for cmd in (
            'git commit -m "ban git gc and git prune"',
            "git -c gc.auto=0 fetch origin main",
            'Select-String -Path AGENTS.md -Pattern "git gc|git prune"',
            "git status --short",
        ):
            with self.subTest(cmd=cmd):
                res = run_hook(cmd)
                self.assertEqual(res["decision"], "allow")

    def test_forces_ask_on_episode_approve(self):
        for cmd in (
            "python -B tools/episode.py approve $ep --gate review --note '确认通过'",
            "& $python -B tools/episode.py approve output/evergreen_vibe/2026-11-24/01_demo --gate delivery --note 'ok'",
            'python -B -c "import subprocess; subprocess.run([\'python\',\'tools/episode.py\',\'approve\'])"',
        ):
            with self.subTest(cmd=cmd):
                res = run_hook(cmd)
                self.assertEqual(res["decision"], "force_ask")

    def test_allows_other_episode_actions(self):
        for cmd in (
            "python -B tools/episode.py status $ep",
            "python -B tools/episode.py preview $ep",
            "python -B tools/episode.py verify $ep",
        ):
            with self.subTest(cmd=cmd):
                res = run_hook(cmd)
                self.assertEqual(res["decision"], "allow")


class StaticLintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "temp/_work").mkdir(parents=True, exist_ok=True)

    def test_blocks_banned_system_fonts(self):
        for font in ("Microsoft YaHei", "SimSun", "SimHei", "STZhongsong", "微软雅黑", "华文中宋"):
            with self.subTest(font=font):
                proc = run_check_entry(f'export const s = {{fontFamily: "{font}, serif"}};\n')
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("[vibe-lint][ERROR]", proc.stderr)
        proc = run_check_entry('export const s = {fontFamily: "黑体, sans-serif"};\n')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("[vibe-lint][ERROR]", proc.stderr)

    def test_no_false_positive_on_comments_or_blackbody_physics(self):
        code = (
            "// 严禁使用 Microsoft YaHei / SimSun / SimHei / STZhongsong\n"
            'export const title = "黑体辐射与紫外灾难";\n'
            'export const style = {fontFamily: \'"Source Serif 4", "ChillJinshuSong", serif\'};\n'
        )
        proc = run_check_entry(code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr.strip(), "")

    def test_spring_overshoot_clamping_errors_and_passes(self):
        bad_cases = [
            "import {spring} from 'remotion'; export const v = spring({frame: 10, fps: 60});",
            "import {spring} from 'remotion'; export const v = spring({frame: 10, fps: 60, config: {damping: 18}});",
            "import {spring} from 'remotion'; export const v = spring({frame: 10, fps: 60, config: {damping: 18, overshootClamping: false}});",
            "import {spring as sp} from 'remotion'; const C = {damping: 18}; export const v = sp({frame: 10, fps: 60, config: C});",
            "import * as R from 'remotion'; export const v = R.spring({frame: 10, fps: 60, config: {stiffness: 100}});",
        ]
        for code in bad_cases:
            with self.subTest(code=code):
                proc = run_check_entry(code + "\n")
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("[vibe-lint][ERROR]", proc.stderr)

        good_cases = [
            "import {spring} from 'remotion'; export const v = spring({frame: 10, fps: 60, config: {damping: 18, overshootClamping: true}});",
            "import {spring} from 'remotion'; const CFG = {damping: 20, overshootClamping: true} as const; export const v = spring({frame: 10, fps: 60, config: CFG});",
            "import * as R from 'remotion'; const BASE = {overshootClamping: true}; export const v = R.spring({frame: 10, fps: 60, config: {...BASE, damping: 16}});",
        ]
        for code in good_cases:
            with self.subTest(code=code):
                proc = run_check_entry(code + "\n")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertNotIn("[vibe-lint][ERROR]", proc.stderr)

    def test_spring_dynamic_config_warns_without_failing(self):
        code = (
            "import {spring, type SpringConfig} from 'remotion';\n"
            "export function anim(cfg: Partial<SpringConfig>) {\n"
            "  return spring({frame: 10, fps: 60, config: cfg});\n"
            "}\n"
        )
        proc = run_check_entry(code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[vibe-lint][WARN]", proc.stderr)
        self.assertNotIn("[vibe-lint][ERROR]", proc.stderr)


if __name__ == "__main__":
    unittest.main()
