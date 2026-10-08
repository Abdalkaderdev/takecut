import json
import os
import shutil

import pytest
from conftest import uv
from test_render import decoded_duration

import core

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    import synth

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    try:
        synth.espeak()
    except RuntimeError:
        pytest.skip("espeak-ng not installed")
    return synth.make_clip(tmp_path_factory.mktemp("e2e") / "talk.mp4")


def test_pipeline(clip):
    model = os.environ.get("TAKECUT_TEST_MODEL", "base")
    device = os.environ.get("TAKECUT_TEST_DEVICE", "auto")
    src_info = core.probe(clip)

    tr = json.loads(uv("video-edit/scripts/transcribe.py", clip, "--model", model, "--device", device, "--language", "en").stdout)
    assert tr["words"] > 40
    transcript = (clip.parent / "edits" / "talk" / "transcript.txt").read_text(encoding="utf-8")
    assert "[s0001 00:00:00" in transcript

    cl = json.loads(uv("video-cleanup/scripts/cleanup.py", tr["words_json"]).stdout)
    assert cl["counts"].get("silence", 0) >= 4
    assert cl["counts"].get("filler", 0) >= 2
    assert cl["counts"].get("retake", 0) >= 1

    prev = json.loads(uv("video-edit/scripts/render.py", cl["edl"], "--preview").stdout)
    assert prev["output"].endswith("cleanup.preview.mp4")

    res = json.loads(uv("video-edit/scripts/render.py", cl["edl"]).stdout)
    assert res["duration"] < src_info["duration"] - 8
    v, a = decoded_duration(res["output"], "v"), decoded_duration(res["output"], "a")
    assert abs(a - v) <= 1 / 30 + 1e-3, (a, v)
    assert os.path.exists(clip), "source must be untouched"
    assert core.probe(clip)["duration"] == src_info["duration"]

    srt = json.loads(uv("video-captions/scripts/captions.py", "srt", res["words_json"]).stdout)
    assert srt["cues"] >= 5
    text = open(srt["output"], encoding="utf-8").read()
    assert "-->" in text and " um" not in text.lower()

    ass = json.loads(uv("video-captions/scripts/captions.py", "ass", res["words_json"], "--preset", "highlight", "--video", res["output"]).stdout)
    burned = json.loads(uv("video-captions/scripts/captions.py", "burn", res["output"], ass["output"]).stdout)
    assert core.probe(burned["output"])["duration"] == pytest.approx(res["duration"], abs=0.1)

    spec = clip.parent / "shorts.json"
    spec.write_text(json.dumps([{"title": "Demo short", "segs": "s0003-s0005"}]))
    shorts = json.loads(uv("video-shorts/scripts/shorts.py", clip, spec).stdout)
    info = core.probe(shorts[0]["output"])
    assert (info["width"], info["height"]) == (1080, 1920) and info["has_audio"]
    assert shorts[0]["tracking"].startswith("center")
