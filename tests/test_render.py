import json
import re
import subprocess

import pytest
from conftest import uv

import core


def ff(*args, cwd=None):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True, cwd=cwd)


def decoded_duration(path, stream):
    if stream == "v":
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                            "stream=nb_read_frames,r_frame_rate", "-of", "json", str(path)], capture_output=True, text=True)
        st = json.loads(p.stdout)["streams"][0]
        num, den = st["r_frame_rate"].split("/")
        return int(st["nb_read_frames"]) * int(den) / int(num)
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-map", f"0:{stream}", "-f", "null", "-"], capture_output=True, text=True)
    h, m, s = re.findall(r"time=(\d+):(\d+):([\d.]+)", p.stderr)[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


@pytest.fixture
def clips(tmp_path, need_ffmpeg):
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=f=440:sample_rate=44100", "-t", "12",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", tmp_path / "a.mp4")
    ff("-f", "lavfi", "-i", "testsrc=size=480x480:rate=25", "-t", "4", "-c:v", "libx264", "-preset", "ultrafast",
       "-pix_fmt", "yuv420p", tmp_path / "silent.mp4")
    return tmp_path


def run_edl(tmp_path, edl, *extra):
    p = tmp_path / "e.edl.json"
    p.write_text(json.dumps(edl))
    return json.loads(uv("video-edit/scripts/render.py", p, *extra).stdout)


def test_render_drops_and_stays_in_sync(clips):
    drops = [{"start": i + 0.3, "end": i + 0.6} for i in range(0, 11)]
    res = run_edl(clips, {"name": "e", "sources": {"a": "a.mp4"}, "drop": drops, "loudnorm": True})
    assert res["pieces"] == 12
    expected = sum(e - s for _, s, e in core.resolve_edl(core.load_edl(clips / "e.edl.json")))
    v, a = decoded_duration(res["output"], "v"), decoded_duration(res["output"], "a")
    assert abs(v - expected) < 1 / 30 + 1e-3
    assert abs(a - v) <= 1 / 30 + 1e-3
    info = core.probe(res["output"])
    assert (info["width"], info["height"], info["fps"]) == (640, 360, 30)


def test_render_mixed_sources_and_silent_input(clips):
    edl = {"name": "mix", "sources": {"a": "a.mp4", "s": "silent.mp4"},
           "clips": [{"src": "a", "start": 1, "end": 3}, {"src": "s", "start": 0, "end": 2}, {"src": "a", "start": "00:00:08", "end": 9}]}
    res = run_edl(clips, edl)
    v, a = decoded_duration(res["output"], "v"), decoded_duration(res["output"], "a")
    assert abs(v - 5.0) < 0.05 and abs(a - v) <= 1 / 30 + 1e-3


def test_preview_is_small(clips):
    res = run_edl(clips, {"name": "e", "sources": {"a": "a.mp4"}, "output": {"width": 1280, "height": 720}}, "--preview")
    assert res["output"].endswith("e.preview.mp4")
    assert core.probe(res["output"])["height"] == 480


def test_render_refuses_to_overwrite_source(clips):
    p = clips / "e.edl.json"
    p.write_text(json.dumps({"sources": {"a": "a.mp4"}}))
    r = uv("video-edit/scripts/render.py", p, "-o", clips / "a.mp4", check=False)
    assert r.returncode != 0 and "refusing" in r.stderr
