"""BGM 工具链公共模块。

职责：
  1. 只定位本机 Gyan/WinGet **FFmpeg 9.0.2**，绝不误用 PATH 里的
     2013 版 N-55702；
  2. 用 FFmpeg 把任意 .mp3/.m4a/.wav/.flac 解码为交错 f32le PCM；
  3. ffprobe 时长探测、仓库根目录与默认单曲槽位定位。

被 bgm_analyze.py / mix_bgm.py 共同 import，无第三方依赖（仅 numpy）。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

SUPPORTED_EXT = (".mp3", ".m4a", ".wav", ".flac")
DEFAULT_STEM = "bgm"
DEFAULT_BGM_GAIN = -13.5
DEFAULT_EXT_ORDER = (".m4a", ".mp3", ".wav", ".flac")


def version_line(exe: str) -> str:
    try:
        r = subprocess.run([exe, "-version"], capture_output=True,
                           text=True, timeout=20)
        txt = (r.stdout or "") + (r.stderr or "")
        return txt.splitlines()[0].strip() if txt.strip() else ""
    except Exception:
        return ""


def sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def locate_tools(explicit: str | None = None):
    """Select matching ffmpeg/ffprobe binaries from one pinned installation."""
    from profile_loader import environment
    setting = explicit or environment()["ffmpegDir"] or os.environ.get("FFMPEG_BIN")
    if setting:
        path = Path(setting)
        candidates = [path if path.suffix.lower() == ".exe" else path / "ffmpeg.exe"]
    else:
        packages = Path(os.environ.get("LOCALAPPDATA", ".")) / "Microsoft/WinGet/Packages"
        candidates = sorted(packages.glob("Gyan.FFmpeg*/ffmpeg-9.0.2-full_build/bin/ffmpeg.exe"))
        fallback = shutil.which("ffmpeg")
        if fallback:
            candidates.append(Path(fallback))
    for path in candidates:
        probe = path.with_name("ffprobe.exe")
        if path.is_file() and probe.is_file():
            ff, fp = version_line(str(path)), version_line(str(probe))
            if all(re.match(r"^ff(?:mpeg|probe) version 9[.]0[.]2(?:[-+_ ]|$)", v)
                   for v in (ff, fp)):
                return str(path.resolve()), str(probe.resolve()), ff
    raise SystemExit(f"FFmpeg/ffprobe 9.0.2 pair required, searched: {candidates}")


def decode_f32(ffmpeg: str, media, sr: int = 22050, channels: int = 1,
               timeout: int = 900):
    """解码为 float32 PCM，返回 (n, channels)；channels=1 时返回一维数组。"""
    import numpy as np

    cmd = [ffmpeg, "-v", "error", "-i", str(media),
           "-map", "0:a:0", "-ac", str(channels), "-ar", str(sr),
           "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0 or not r.stdout:
        err = r.stderr.decode("utf-8", "replace")[-900:]
        raise SystemExit(f"[FFmpeg] 解码失败：{media}\n{err}")
    x = np.frombuffer(r.stdout, dtype="<f4").astype(np.float32)
    if channels > 1:
        n = len(x) // channels
        return x[:n * channels].reshape(n, channels)
    return x


def probe_duration(ffprobe: str, media: str, stream: str | None = None) -> float:
    cmd = [ffprobe, "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream, "-show_entries", "stream=duration"]
    else:
        cmd += ["-show_entries", "format=duration"]
    cmd += ["-of", "default=noprint_wrappers=1:nokey=1", str(media)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except Exception:
        return 0.0
    for tok in r.stdout.split():
        try:
            v = float(tok)
            if v > 0:
                return v
        except ValueError:
            pass
    return 0.0


def has_audio_stream(ffprobe: str, media: str) -> bool:
    cmd = [ffprobe, "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=index", "-of", "csv=p=0", str(media)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return bool(r.stdout.strip())
    except Exception:
        return False


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_bgm_dir() -> Path:
    return repo_root() / "assets" / "bgm"


def resolve_default_bgm(explicit: str | None = None) -> Path:
    """定位默认单曲；未放入时给出清晰路径提示并报错退出。"""
    if explicit:
        p = Path(explicit).resolve()
        if not p.exists():
            raise SystemExit(f"[BGM] 指定的音频不存在：{p}")
        return p
    d = default_bgm_dir()
    for ext in DEFAULT_EXT_ORDER:
        p = d / (DEFAULT_STEM + ext)
        if p.exists():
            return p
    raise SystemExit(
        "[BGM] 未找到默认单曲 bgm。请把音频放到：\n"
        f"        {d}\\bgm.m4a"
        "   （自动探测顺序 .m4a -> .mp3 -> .wav -> .flac）\n"
        "        放好后先跑一次：python tools\\bgm_analyze.py\n"
        "        或本次用 --bgm <音频路径> 显式指定。"
    )
