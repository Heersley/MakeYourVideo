"""BGM 工具链公共模块。

职责：
  1. 定位可用的 **FFmpeg 7+**（开发验证版本 9.0.2），优先显式参数与 FFMPEG_BIN，
     其次 PATH；避免误用缺 libx264 / d3d11 的旧构建；
  2. 用 FFmpeg 把任意 .mp3/.m4a/.wav/.flac 解码为交错 f32le PCM；
  3. ffprobe 时长探测、仓库根目录与默认单曲槽位定位。

被 bgm_analyze.py / mix_bgm.py 共同 import，无第三方依赖（仅 numpy）。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

MIN_MAJOR = 7
SUPPORTED_EXT = (".mp3", ".m4a", ".wav", ".flac")
DEFAULT_STEM = "bgm"
DEFAULT_EXT_ORDER = (".m4a", ".mp3", ".wav", ".flac")


def version_line(exe: str) -> str:
    try:
        r = subprocess.run([exe, "-version"], capture_output=True,
                           text=True, timeout=20)
        txt = (r.stdout or "") + (r.stderr or "")
        return txt.splitlines()[0].strip() if txt.strip() else ""
    except Exception:
        return ""


def major_of(line: str) -> int:
    m = re.search(r"ffmpeg version (\d+)", line)
    return int(m.group(1)) if m else 0


def locate_tools(explicit: str | None = None):
    """返回 (ffmpeg, ffprobe, version_line)。只接受 major>=9 的 9.0.2 家族。"""
    cands: list[Path] = []
    if explicit:
        p = Path(explicit)
        cands.append(p if p.suffix.lower() == ".exe" else p / "ffmpeg.exe")
    env = os.environ.get("FFMPEG_BIN")
    if env:
        p = Path(env)
        cands.append(p if p.suffix.lower() == ".exe" else p / "ffmpeg.exe")
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        root = Path(local) / "Microsoft" / "WinGet" / "Packages"
        for pat in ("Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe",
                    "*FFmpeg*/**/bin/ffmpeg.exe"):
            try:
                cands += sorted(root.glob(pat))
            except Exception:
                pass
    which = shutil.which("ffmpeg")
    if which:
        cands.append(Path(which))

    seen, scored = set(), []
    for c in cands:
        cs = str(c)
        if cs in seen or not c.exists():
            continue
        seen.add(cs)
        line = version_line(cs)
        mj = major_of(line)
        if mj >= MIN_MAJOR:
            scored.append((mj, cs, line))
    if not scored:
        raise SystemExit(
            "[FFmpeg] 未找到 FFmpeg 7+（含 libx264）。\n"
            "        请用 --ffmpeg 指定 ffmpeg 可执行文件，"
            "或设置环境变量 FFMPEG_BIN；确认 `ffmpeg -version` 可用。"
        )
    scored.sort(key=lambda t: -t[0])
    _, ff, line = scored[0]
    probe_path = str(Path(ff).with_name("ffprobe.exe"))
    if not Path(probe_path).exists():
        probe_path = shutil.which("ffprobe") or probe_path
    return ff, probe_path, line


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
        "[BGM] 未找到默认槽位 bgm.*。请把音频放到：\n"
        f"        {d}/bgm.m4a"
        "   （自动探测顺序 .m4a -> .mp3 -> .wav -> .flac）\n"
        "        放好后先跑一次：python tools/bgm_analyze.py\n"
        "        或本次用 --bgm <音频路径> 显式指定。"
    )
