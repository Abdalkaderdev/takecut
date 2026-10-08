import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
for d in ("video-edit", "video-cleanup", "video-captions", "video-shorts"):
    sys.path.insert(0, str(SKILLS / d / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))


def W(w, s, e):
    return {"w": " " + w, "s": s, "e": e}


def uv(script: str, *args, cwd=None, check=True) -> subprocess.CompletedProcess:
    if not shutil.which("uv"):
        pytest.skip("uv not installed")
    p = subprocess.run(["uv", "run", "--quiet", str(SKILLS / script), *map(str, args)], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode:
        raise AssertionError(f"{script} failed ({p.returncode}):\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    return p


@pytest.fixture
def need_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg not installed")
