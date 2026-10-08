from conftest import W

import cleanup
import core

EN = cleanup.FILLERS["en"] | cleanup.COMMON


def test_fillers_detected_and_span_to_next_word():
    ws = [W("So,", 0.0, 0.3), W("um,", 0.5, 0.8), W("the", 1.0, 1.2), W("uh", 1.3, 1.5), W("plan.", 1.6, 2.0)]
    cuts = cleanup.filler_cuts(ws, EN, None)
    assert [c[3] for c in cuts] == ["um,", "uh"]
    s, e, kind, _ = cuts[0]
    assert kind == "filler" and s >= 0.3 and abs(e - 0.97) < 1e-9


def test_like_only_when_comma_delimited():
    ws = [W("I", 0, 0.1), W("like", 0.1, 0.3), W("it.", 0.3, 0.5), W("It's,", 0.6, 0.8), W("like,", 0.9, 1.1), W("big.", 1.2, 1.4)]
    cuts = cleanup.filler_cuts(ws, EN, "like")
    assert [c[3] for c in cuts] == ["like,"]


def test_multilingual_filler_tokens():
    ws = [{"w": " Ähm,", "s": 0, "e": 0.4}, {"w": " also", "s": 0.5, "e": 0.8}]
    assert cleanup.filler_cuts(ws, cleanup.FILLERS["de"], None)[0][3] == "Ähm,"


def segs(*sentences, gap=0.4):
    words, t = [], 0.0
    for s in sentences:
        for tok in s.split():
            words.append(W(tok, t, t + 0.25))
            t += 0.3
        t += gap
    return core.segment_words(words)


def test_retake_keeps_last_take():
    sg = segs("Then it cuts them out.", "Then it cuts them out, frame accurate, with fades.")
    cuts = cleanup.repeat_cuts(sg, EN)
    assert len(cuts) == 1 and cuts[0][2] == "retake"
    assert cuts[0][1] < sg[1]["start"] and cuts[0][0] < sg[0]["start"]


def test_near_duplicate_sentence():
    sg = segs("We ship on Friday this week.", "We ship on Friday this week!")
    assert [c[2] for c in cleanup.repeat_cuts(sg, EN)] == ["retake"]


def test_different_sentences_untouched():
    sg = segs("The first point is speed.", "The second point is cost.")
    assert cleanup.repeat_cuts(sg, EN) == []


def test_stutter_inside_sentence():
    sg = segs("I I think we should we should go now.")
    kinds = [(c[2], c[3]) for c in cleanup.repeat_cuts(sg, EN)]
    assert ("stutter", "I") in kinds and ("stutter", "we should") in kinds


def test_legit_repetition_kept():
    assert cleanup.repeat_cuts(segs("It was very very good."), EN) == []


def test_silence_cuts_keep_breathing_room_and_word_gaps():
    words = [W("a", 0.0, 0.5), W("b", 3.0, 3.5), W("c", 10.0, 10.5)]
    cuts = cleanup.silence_cuts([(0.5, 3.0)], words, keep=0.15, min_dur=0.6, duration=11.0)
    sil = [c for c in cuts if c[2] == "silence"]
    assert sil == [(0.65, 2.85, "silence", "")]
    pauses = [c for c in cuts if c[2] == "pause"]
    assert len(pauses) == 1 and pauses[0][0] > 3.5 and pauses[0][1] < 10.0


def test_leading_silence_cut_fully():
    cuts = cleanup.silence_cuts([(0.0, 2.0)], [W("a", 2.0, 2.5)], keep=0.15, min_dur=0.6, duration=3.0)
    assert cuts[0][0] == 0.0
