"""Run every bash block in skills/video-ffmpeg/references/recipes.md against generated fixtures."""
import re
import shlex
import subprocess

import pytest
from conftest import SKILLS, uv

RECIPES = SKILLS / "video-ffmpeg" / "references" / "recipes.md"


def commands():
    text = RECIPES.read_text(encoding="utf-8")
    out = []
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        for line in block.strip().splitlines():
            if line.strip() and not line.startswith("#"):
                out.append(line.strip())
    return out


def ff(*args, cwd):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, cwd=cwd)


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("recipes")
    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=f=300", "-t", "6", *enc, "in.mp4", cwd=d)
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=f=500", "-t", "2", *enc, "a.mp4", cwd=d)
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-f", "lavfi", "-i", "sine=f=700:sample_rate=44100", "-t", "2",
       "-c:v", "mpeg4", "-c:a", "pcm_s16le", "b.mov", cwd=d)
    ff("-f", "lavfi", "-i", "smptebars=size=320x240:rate=30", "-t", "6", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "cam.mp4", cwd=d)
    ff("-f", "lavfi", "-i", "color=c=white:size=200x80,format=rgba", "-frames:v", "1", "logo.png", cwd=d)
    ff("-f", "lavfi", "-i", "sine=f=220", "-t", "4", "music.mp3", cwd=d)
    (d / "list.txt").write_text("file 'in.mp4'\nfile 'in.mp4'\n")
    return d


@pytest.mark.parametrize("cmd", commands(), ids=lambda c: c[:60])
def test_recipe(cmd, fixtures):
    argv = shlex.split(cmd)
    if argv[:2] == ["uv", "run"]:
        script = argv[2].replace("scripts/", "video-ffmpeg/scripts/", 1)
        uv(script, *argv[3:], cwd=fixtures)
        return
    p = subprocess.run(argv, cwd=fixtures, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-2000:]
    if argv[0] == "ffprobe":
        assert '"duration"' in p.stdout
        return
    outs = [a for a in argv if a.startswith("out")]
    assert outs and (fixtures / outs[-1]).stat().st_size > 0
