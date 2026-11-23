"""Immutable production profiles and per-workstation settings."""
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

TOOLS = Path(__file__).resolve().parent
DEFAULT_PROFILE = "vibe-3.3"


@dataclass(frozen=True)
class Profile:
    data: dict
    raw: bytes

    @property
    def stamp(self):
        return {"profile_id": self.data["id"], "profile_sha256": hashlib.sha256(self.raw).hexdigest()}

    @property
    def hard(self):
        return self.data["hard"]


@lru_cache(maxsize=8)
def profile_validator(tools):
    schema = json.loads((tools/"contracts/profile.schema.json").read_bytes())
    return Draft202012Validator(schema)


def parse_profile(raw):
    data = json.loads(raw)
    issue = next(profile_validator(TOOLS).iter_errors(data), None)
    if issue:
        raise ValueError(f"profile {list(issue.path)}: {issue.message}")
    hard = data["hard"]
    video,visual,audio = (hard[k] for k in ("video","visual","audio"))
    left,top,right,bottom = visual["safeZone"]
    lo,hi = visual["roiY"]
    if not (0 <= left < right <= video["width"] and 0 <= top < bottom <= video["height"]
            and 0 <= lo < hi <= video["height"] and visual["motionHz"] > 0
            and video["fps"] > 0 and video["fps"] % visual["motionHz"] == 0
            and hard["decoder"]["sampleEvery"] > 0):
        raise ValueError("制作档案画幅、ROI 或采样频率无效")
    for low,high in (audio["lufs"],audio["sfxPeak"],video["previewSec"],
                     hard["timeline"]["readingSec"],*visual["lighting"].values(),
                     *hard["timeline"]["duration"].values(),*data["defaults"]["beatDurationSec"]):
        if low > high:
            raise ValueError("制作档案范围倒置")
    return Profile(data, raw)


def load_profile(name=DEFAULT_PROFILE, *, archive=None, expected=None):
    if not re.fullmatch(r"vibe-[0-9]+\.[0-9]+", name):
        raise ValueError(f"非法 profile ID: {name}")
    if archive is None:
        folder = TOOLS/"profiles"
        registry = json.loads((folder/"registry.json").read_bytes())
        if name not in registry:
            raise ValueError(f"未注册 profile: {name}")
        expected = registry[name]
        archive = folder/(name+".json")
    profile = parse_profile(archive.read_bytes())
    if profile.data["id"] != name or profile.stamp["profile_sha256"] != expected:
        raise ValueError(f"制作档案 ID 或 SHA-256 不匹配: {name}")
    return profile


def environment(*, concurrency=None, legacy=None):
    defaults = json.loads((TOOLS/"env.example.json").read_bytes())
    local = TOOLS/"env.local.json"
    overrides = json.loads(local.read_bytes()) if local.exists() else {}
    if not isinstance(overrides, dict) or overrides.keys() - defaults.keys():
        raise ValueError("本机配置包含未知字段")
    if legacy is not None:
        defaults["concurrency"] = legacy
    cfg = defaults | overrides
    if concurrency is not None:
        cfg["concurrency"] = concurrency
    workers = cfg["concurrency"]
    if type(workers) is not int or workers < 1:
        raise ValueError("并发必须是正整数")
    if workers > 4:
        print(f"[env] concurrency={workers}，请留意 2K 渲染内存", file=sys.stderr)
    if cfg["hwaccel"] != "d3d11va":
        raise ValueError("当前硬解验收仅支持 D3D11VA")
    for key in ("ffmpegDir","pythonPath"):
        if cfg[key] is not None and not (isinstance(cfg[key],str) and Path(cfg[key]).is_absolute()):
            raise ValueError(f"{key} 需要绝对路径")
    return cfg
