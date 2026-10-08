import subprocess
import sys

from conftest import SKILLS, W

import captions


def words_from(text, start=0.0, step=0.3, gap_after=None):
    out, t = [], start
    for i, tok in enumerate(text.split()):
        out.append(W(tok, round(t, 3), round(t + step - 0.05, 3)))
        t += step + (gap_after.get(i, 0) if gap_after else 0)
    return out


def test_wrap_balances_lines():
    toks = "the quick brown fox jumps over the lazy dog again and again today".split()
    lines = captions.wrap(toks, 42, 2)
    texts = [" ".join(toks[i] for i in ln) for ln in lines]
    assert len(texts) == 2 and all(len(t) <= 42 for t in texts)
    assert abs(len(texts[0]) - len(texts[1])) < 12
    assert captions.wrap(["short", "line"], 42, 2) == [[0, 1]]


def test_cues_respect_char_limit_and_lines():
    ws = words_from("word " * 80)
    cues = captions.build_cues(ws, max_chars=20, max_lines=2)
    for c in cues:
        assert len(c["lines"]) <= 2
        assert all(len(" ".join(ln)) <= 20 for ln in c["lines"])


def test_cues_break_on_pause_and_sentence():
    ws = words_from("This is the first sentence. And this is two after a pause", gap_after={8: 1.2})
    cues = captions.build_cues(ws)
    assert captions.cue_text(cues[0]).startswith("This is the first sentence.")
    assert any(captions.cue_text(c).startswith("And this") for c in cues)
    assert captions.cue_text(cues[-1]).endswith("pause")


def test_min_duration_reading_speed_and_gap():
    ws = [W("Hi.", 0.0, 0.2), W("Supercalifragilistic", 3.0, 3.3), W("next", 3.4, 3.6)]
    cues = captions.build_cues(ws, pause=0.5)
    assert cues[0]["end"] - cues[0]["start"] >= 0.83
    for a, b in zip(cues, cues[1:]):
        assert a["end"] <= b["start"] - 0.08 + 1e-9
    long = captions.build_cues(words_from("a b c d e f g h i j k l m n o p q r s t", step=0.05), max_chars=60)
    text = captions.cue_text(long[0]).replace("\n", " ")
    assert long[0]["end"] - long[0]["start"] >= len(text) / 17 - 1e-3


def test_capitalizes_after_dropped_filler():
    cues = captions.build_cues([W("the", 0, 0.2), W("idea.", 0.2, 0.5)])
    assert captions.cue_text(cues[0]) == "The idea."


def test_srt_vtt_roundtrip():
    cues = captions.build_cues(words_from("Hello world. Second sentence here", gap_after={1: 1.0}))
    srt = captions.to_srt(cues)
    assert srt.startswith("1\n00:00:00,000 --> ")
    back = captions.parse_srt(srt)
    assert len(back) == len(cues)
    assert abs(back[0]["end"] - cues[0]["end"]) < 0.002
    assert captions.to_vtt(cues).startswith("WEBVTT\n\n00:00:00.000 --> ")


def test_ass_presets_and_highlight_events():
    cues = captions.build_cues(words_from("one two three four"))
    for name in captions.PRESETS:
        ass = captions.to_ass(cues, 1080, 1920, name)
        assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
        assert "[Events]" in ass and "Dialogue:" in ass
    hl = captions.to_ass(cues, 1920, 1080, "highlight")
    assert hl.count("Dialogue:") == 4
    assert "{\\c&H00D4FF&}" in hl
    assert captions.to_ass(cues, 1920, 1080, "clean").count("Dialogue:") == 1


def test_ass_escapes_override_braces():
    assert captions.ass_escape("a{b}c") == "a(b)c"


def test_ass_color():
    assert captions.ass_color("FFD400") == "&H0000D4FF"
    assert captions.ass_color("000000", 0x80) == "&H80000000"


def test_translate_flow_keeps_timings(tmp_path):
    srt = tmp_path / "a.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,500\nHello there\n\n2\n00:00:03,000 --> 00:00:04,000\nBye\n\n", encoding="utf-8")
    script = SKILLS / "video-captions" / "scripts" / "captions.py"
    subprocess.run([sys.executable, script, "translate-prep", srt], check=True, capture_output=True)
    lines = tmp_path / "a.lines.json"
    assert lines.exists()
    tr = tmp_path / "a.de.lines.json"
    tr.write_text('{"1": "Hallo zusammen, das ist eine deutlich längere Übersetzung als vorher", "2": "Tschüss"}', encoding="utf-8")
    subprocess.run([sys.executable, script, "translate-apply", srt, tr, "--lang", "de"], check=True, capture_output=True)
    out = (tmp_path / "a.de.srt").read_text(encoding="utf-8")
    assert "00:00:01,000 --> 00:00:02,500" in out and "00:00:03,000 --> 00:00:04,000" in out
    first = out.split("\n\n")[0].split("\n")[2:]
    assert len(first) == 2 and all(len(x) <= 42 for x in first)
    bad = tmp_path / "bad.json"
    bad.write_text('{"1": "x"}', encoding="utf-8")
    p = subprocess.run([sys.executable, script, "translate-apply", srt, bad], capture_output=True, text=True)
    assert p.returncode != 0 and "missing" in p.stderr
