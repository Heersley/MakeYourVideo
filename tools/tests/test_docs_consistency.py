import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DocsTests(unittest.TestCase):
    def test_public_links_and_episode_commands(self):
        help_text = subprocess.check_output(
            [sys.executable, "-X", "utf8", "-B", "tools/episode.py", "--help"], cwd=ROOT, encoding="utf-8"
        )
        actions = set(re.search(r"\{(status,[^{}]+)\}", help_text)[1].split(","))
        docs = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
        for doc in docs:
            with self.subTest(doc=doc.name):
                text = doc.read_text("utf-8")
                for link in re.findall(r"\[[^\]]+\]\(([^)#]+)\)", text):
                    if "://" not in link:
                        self.assertTrue((doc.parent / link).exists(), (doc.name, link))
                self.assertLessEqual(set(re.findall(r"tools/episode\.py ([a-z][a-z-]*)", text)), actions)

    def test_readme_environment_and_example(self):
        readme = (ROOT / "README.md").read_text("utf-8")
        package = json.loads((ROOT / "package.json").read_bytes())
        lock = json.loads((ROOT / "package-lock.json").read_bytes())
        self.assertIn(package["engines"]["node"], readme)
        self.assertEqual(package["devDependencies"], lock["packages"][""]["devDependencies"])
        self.assertIn("3.12.4", readme)
        self.assertIn("9.0.2", readme)
        self.assertIn("D3D11VA", readme)
        self.assertIn("jsonschema", (ROOT / "requirements.txt").read_text("utf-8"))
        self.assertTrue((ROOT / package["scripts"]["dev"].split()[-1]).is_file())
