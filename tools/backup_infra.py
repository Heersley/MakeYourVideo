"""Create and verify a local infrastructure recovery archive. Existing archives are immutable."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ("README.md", "LICENSE", "package.json", "package-lock.json",
              "requirements.txt", "tsconfig.json", ".gitattributes", ".gitignore")
ASSET_TYPES = {
    "docs": {".md"},
    "tools": {".py", ".md", ".json", ".cjs", ".mjs", ".ts"},
    "core/vibe": {".py", ".json", ".tsx", ".ts"},
    "examples/diameter": {".md", ".py", ".json", ".tsx"},
    "assets/fonts": {".txt", ".md", ".woff", ".woff2", ".otf"},
    "assets/bgm": {".txt", ".md"},
}


def create(dest):
    paths = [ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()]
    excluded = {"__pycache__", ".work", "legacy_archive", "env.local.json"}
    for directory, suffixes in ASSET_TYPES.items():
        for path in (ROOT / directory).rglob("*"):
            parts = {part.casefold() for part in path.relative_to(ROOT).parts}
            if not parts.intersection(excluded) and path.is_file() and (
                    path.suffix.lower() in suffixes or path.name == "LICENSE"):
                paths.append(path)
    dest.parent.mkdir(parents=True,exist_ok=True)
    # Publish the verified file without replacing any previous backup.
    with tempfile.NamedTemporaryFile(dir=dest.parent,delete=False) as temp:
        candidate = Path(temp.name)
    try:
        digests = {}
        with ZipFile(candidate,"w",ZIP_DEFLATED) as archive:
            for path in sorted(paths):
                name = path.relative_to(ROOT).as_posix()
                data = path.read_bytes()
                archive.writestr(name,data)
                digests[name] = hashlib.sha256(data).hexdigest()
            archive.writestr("SHA256.json",json.dumps(digests,indent=2))
        count = verify(candidate)
        if os.name == "nt":
            # Windows rename rejects an existing target and also works without hard-link permission.
            candidate.rename(dest)
        else:
            os.link(candidate,dest)
        return count
    finally:
        candidate.unlink(missing_ok=True)


def verify(path):
    with ZipFile(path) as archive:
        digests = json.loads(archive.read("SHA256.json"))
        if sorted(archive.namelist()) != sorted([*digests,"SHA256.json"]):
            raise ValueError("归档文件清单不一致")
        for name,expected in digests.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError(f"归档摘要错误: {name}")
    return len(digests)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("create","verify"))
    parser.add_argument("archive",type=Path)
    args = parser.parse_args()
    count = (create if args.action == "create" else verify)(args.archive.resolve())
    print(f"{args.action}: {count} verified files")
