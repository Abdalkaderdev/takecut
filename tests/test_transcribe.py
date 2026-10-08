import transcribe


def test_glue_word_pieces():
    ws = [{"w": " real", "s": 1.0, "e": 1.2, "p": 0.9}, {"w": "-life", "s": 1.2, "e": 1.5, "p": 0.7}, {"w": " romance", "s": 1.5, "e": 2.0, "p": 1.0}]
    out = transcribe.glue_pieces(ws, "en")
    assert [(w["w"], w["s"], w["e"], w["p"]) for w in out] == [(" real-life", 1.0, 1.5, 0.7), (" romance", 1.5, 2.0, 1.0)]
    assert transcribe.glue_pieces([{"w": "你", "s": 0, "e": 1}, {"w": "好", "s": 1, "e": 2}], "zh")[1]["w"] == "好"


def test_parse_api_words_top_level_and_nested():
    data = {"words": [{"word": "Hello", "start": 0.1, "end": 0.5}]}
    assert transcribe.parse_api_words(data, 10.0) == [{"w": " Hello", "s": 10.1, "e": 10.5}]
    nested = {"segments": [{"words": [{"word": " hi", "start": 1, "end": 2}]}]}
    assert transcribe.parse_api_words(nested, 0)[0]["w"] == " hi"


def test_multipart_contains_fields(tmp_path):
    f = tmp_path / "a.ogg"
    f.write_bytes(b"OggS")
    body, ctype = transcribe.multipart({"model": "m", "timestamp_granularities[]": ["word", "segment"]}, "file", f)
    assert ctype.startswith("multipart/form-data; boundary=")
    assert body.count(b'name="timestamp_granularities[]"') == 2
    assert b'filename="a.ogg"' in body and b"OggS" in body
