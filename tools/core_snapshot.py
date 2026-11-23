"""Pin an episode-local, offline-verifiable copy of the Vibe source release."""
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core/vibe"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    version_path = root / "version.json"
    if version_path.resolve().parent != root.resolve():
        raise ValueError("External core release manifest")
    release = json.loads(version_path.read_bytes())
    names = release["files"]
    if (not re.fullmatch(r"\d+\.\d+\.\d+", release["coreVersion"]) or not names
            or not isinstance(names, dict)
            or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\.(?:py|tsx?|json)", n)
                   or n in ("version.json", "core_snapshot.json") for n in names)):
        raise ValueError("Invalid core release manifest")
    files = {}
    for name in sorted([*names, "version.json"]):
        path = root / name
        if path.resolve().parent != root.resolve() or not path.is_file():
            raise ValueError("Missing or external core file: " + name)
        files[name] = sha(path)
        if name != "version.json" and files[name] != names[name]:
            raise ValueError("Core release file mismatch: " + name)
    return {"coreVersion": release["coreVersion"], "files": files}


def folder(ep):
    target = ep / "src/vendor/vibe"
    if target.resolve() != ep.resolve() / "src/vendor/vibe":
        raise ValueError("Unsafe snapshot destination")
    return target


def verify(ep, expected):
    target = folder(ep)
    if expected is None and not target.exists():
        return None
    record = target / "core_snapshot.json"
    if not expected or not record.is_file() or record.resolve() != record.absolute() or sha(record) != expected:
        raise ValueError("Missing or changed core snapshot receipt")
    data = inventory(target)
    if (data != json.loads(record.read_bytes()) or
            {p.name for p in target.iterdir()} != {*data["files"], record.name}):
        raise ValueError("Core snapshot content mismatch")
    return data


def install(ep):
    ep = ep.resolve()
    manifest_path = ep / "src/manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8-sig"))
    if manifest.get("coreSnapshot"):
        return verify(ep, manifest["coreSnapshot"])
    if (ep / "src/final_qc.json").exists():
        raise ValueError("Completed episode cannot adopt a new core")
    target = folder(ep)
    data = inventory(CORE)
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            stage = Path(tmp) / "vibe"
            stage.mkdir()
            for name in data["files"]:
                shutil.copyfile(CORE / name, stage / name)
            if inventory(stage) != data:
                raise ValueError("Core changed during copy")
            (stage / "core_snapshot.json").write_text(json.dumps(data, indent=2), "utf-8")
            stage.rename(target)
    # Retry after interruption between directory installation and manifest binding.
    digest = sha(target / "core_snapshot.json")
    if verify(ep, digest) != data:
        raise ValueError("Existing snapshot differs from selected release")
    manifest["coreSnapshot"] = digest
    with tempfile.NamedTemporaryFile(dir=manifest_path.parent, delete=False, mode="w", encoding="utf-8") as temp:
        json.dump(manifest, temp, ensure_ascii=False, indent=2)
    os.replace(temp.name, manifest_path)
    return data
