import json

import pytest
from conftest import W

import core


def test_timecodes():
    assert core.parse_time("01:02:03.5") == 3723.5
    assert core.parse_time("02:03,250") == 123.25
    assert core.parse_time("7.5") == 7.5
    assert core.parse_time(4) == 4.0
    assert core.fmt_time(3723.5) == "01:02:03.500"
    assert core.fmt_time(59.9996) == "00:01:00.000"
    assert core.fmt_time(1.25, ",") == "00:00:01,250"
    assert core.fmt_dur(725) == "12:05"
    assert core.fmt_dur(3725) == "1:02:05"
    with pytest.raises(ValueError):
        core.parse_time("abc")


def test_merge_and_subtract():
    assert core.merge([(5, 6), (1, 2), (1.5, 3), (3.05, 4)]) == [(1, 3), (3.05, 4), (5, 6)]
    assert core.merge([(1, 2), (2.05, 3)], gap=0.1) == [(1, 3)]
    assert core.merge([(2, 1)]) == []
    assert core.subtract((0, 10), [(2, 3), (2.5, 4), (9, 12)]) == [(0, 2), (4, 9)]
    assert core.subtract((0, 10), [(-1, 11)]) == []
    assert core.subtract((0, 10), []) == [(0, 10)]


def test_snap():
    assert core.snap(1.016, 30) == 1.0
    assert core.snap(1.02, 30) == pytest.approx(1.0333333, abs=1e-6)
    assert core.snap(1.016, 0) == 1.016


def test_segment_words_splits_on_sentence_and_gap():
    words = [W("Hello", 0, 0.4), W("there.", 0.4, 0.8), W("Next", 0.9, 1.2), W("one", 1.2, 1.5), W("after", 2.5, 2.8), W("gap", 2.8, 3.0)]
    segs = core.segment_words(words)
    assert [s["text"] for s in segs] == ["Hello there.", "Next one", "after gap"]
    assert [s["id"] for s in segs] == ["s0001", "s0002", "s0003"]
    assert segs[1]["start"] == 0.9 and segs[1]["end"] == 1.5


def test_segment_words_no_space_language():
    words = [{"w": "你好", "s": 0, "e": 0.5}, {"w": "世界。", "s": 0.5, "e": 1.0}]
    assert core.segment_words(words, "zh")[0]["text"] == "你好世界。"


def _transcript(tmp_path, words, dur=20.0):
    tr = {"source": "x.mp4", "duration": dur, "language": "en", "segments": core.segment_words(words)}
    p = tmp_path / "t.words.json"
    p.write_text(json.dumps(tr))
    return tr, p


PROBE = {"main": {"duration": 20.0, "fps": 25.0, "has_audio": True, "has_video": True}}


def test_resolve_edl_drop_and_snap(tmp_path):
    edl = {"_dir": str(tmp_path), "sources": {"main": "x.mp4"},
           "drop": [{"start": 2.01, "end": 3.0}, {"start": 10, "end": 10.05}, {"start": 19.5, "end": 25}]}
    pieces = core.resolve_edl(edl, PROBE)
    assert [p[0] for p in pieces] == ["main"] * 3
    assert [p[1:] for p in pieces] == [pytest.approx(x) for x in [(0.0, 2.0), (3.0, 10.0), (10.04, 19.52)]]
    for _, s, e in pieces:
        assert s * 25 == pytest.approx(round(s * 25)) and e * 25 == pytest.approx(round(e * 25))


def test_resolve_edl_merges_tiny_gaps_after_snap(tmp_path):
    edl = {"_dir": str(tmp_path), "sources": {"main": "x.mp4"}, "drop": [{"start": 5.001, "end": 5.01}]}
    assert core.resolve_edl(edl, PROBE) == [("main", 0.0, 20.0)]


def test_resolve_edl_segments_and_order(tmp_path):
    words = [W("One.", 1, 2), W("Two.", 3, 4), W("Three.", 5, 6)]
    _, p = _transcript(tmp_path, words)
    edl = {"_dir": str(tmp_path), "sources": {"main": "x.mp4"}, "transcripts": {"main": p.name}, "pad": 0.0,
           "clips": [{"segs": "s0003"}, {"segs": "s0001-s0002"}]}
    assert core.resolve_edl(edl, PROBE) == [("main", 5.0, 6.0), ("main", 1.0, 4.0)]


def test_resolve_edl_min_keep_and_empty(tmp_path):
    edl = {"_dir": str(tmp_path), "sources": {"main": "x.mp4"}, "clips": [{"start": 1, "end": 1.05}]}
    with pytest.raises(SystemExit):
        core.resolve_edl(edl, PROBE)


def test_remap_words(tmp_path):
    words = [W("a", 1.0, 1.4), W("b", 2.0, 2.4), W("c", 5.0, 5.4), W("d", 8.0, 8.4)]
    tr, _ = _transcript(tmp_path, words)
    out = core.remap_words([("main", 0.0, 3.0), ("main", 7.9, 9.0)], {"main": tr})
    got = [(w["w"].strip(), w["s"], w["e"]) for s in out["segments"] for w in s["words"]]
    assert got == [("a", 1.0, 1.4), ("b", 2.0, 2.4), ("d", 3.1, 3.5)]
    assert out["duration"] == pytest.approx(4.1)


def test_remap_keeps_word_whose_start_was_trimmed(tmp_path):
    tr, _ = _transcript(tmp_path, [W("You", 7.9, 8.3)])
    out = core.remap_words([("main", 8.18, 10.0)], {"main": tr})
    assert out["segments"][0]["words"][0]["s"] == 0.0


def test_guard_output_refuses_source(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"")
    with pytest.raises(SystemExit):
        core.guard_output(src, [src])
