"""Shared environment guard for media-heavy integration tests in the OSS repo.

The OSS repository ships no font binaries and no rendered media. Tests that spin a
real Chromium/Remotion render (and create thousands of intermediate files) are
opt-in so a fresh checkout runs the full suite cleanly. Contributors with the
complete local toolchain can enable them with:

    MKYV_MEDIA_TESTS=1 python -m unittest discover -s tools/tests -v

Font binaries: 4 families / 8 files in public/fonts/ (see assets/fonts/FONT-NOTICE.md).
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FONT_FILES = (
    "SourceSerif4-Regular.ttf.woff2", "SourceSerif4-Semibold.ttf.woff2",
    "ChillJinshuSongRegular.woff", "ChillJinshuSongBold.woff",
    "NotoSansSC-Regular.otf", "NotoSansSC-Medium.otf",
    "JetBrainsMono-Regular.woff2", "JetBrainsMono-Medium.woff2",
)


def fonts_available():
    for folder in (ROOT / "public/fonts", ROOT / "assets/fonts"):
        if folder.is_dir() and all((folder / name).is_file() for name in FONT_FILES):
            return True
    return False


def media_tests_enabled():
    return os.environ.get("MKYV_MEDIA_TESTS") == "1" and fonts_available()


def skip_reason():
    if os.environ.get("MKYV_MEDIA_TESTS") != "1":
        return "真实渲染测试需 MKYV_MEDIA_TESTS=1 显式开启"
    return "缺少 4 族 8 个字体二进制（放入 public/fonts/ 后重试）"
