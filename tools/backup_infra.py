"""Create and verify a local infrastructure recovery archive. Existing archives are immutable."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ("README.md","package.json","package-lock.json","tsconfig.json",
              ".gitattributes",".gitignore")
DOC_FILES = ("AGENTS.md","STYLE_B_SILENT_VIBE.md","PROCESS.md","prompt.md","PRODUCTION.md")


def create(dest):
    paths = [ROOT/name for name in ROOT_FILES if (ROOT/name).is_file()]
    paths += [ROOT/"docs"/name for name in DOC_FILES if (ROOT/"docs"/name).is_file()]
    for name in ("tools","core/vibe","assets/fonts","assets/bgm"):
        for p in (ROOT/name).rglob("*"):
            if p.name.casefold() == "env.local.json":
                continue
            if p.is_file() and not set(p.parts).intersection({"__pycache__","legacy_archive"}):
                allowed = {"tools":{".py",".md",".json",".cjs",".mjs",".ts"},
                           "core/vibe":{".py",".json",".tsx",".ts"},
                           "assets/fonts":{".txt",".md",".woff",".woff2",".otf"},
                           "assets/bgm":{".txt",".json"}}
                if p.suffix.lower() in allowed[name] or p.name == "LICENSE":
                    paths.append(p)
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
