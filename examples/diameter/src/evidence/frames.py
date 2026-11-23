import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "tools"))

from evidence_kit import main

main(cover_frame=3450, still_frames={"prop": 120, "trail": 274, "climax": 3450})
