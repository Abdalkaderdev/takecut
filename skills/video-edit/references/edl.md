# EDL and transcript formats

## Contents

- [Transcript (`*.words.json`)](#transcript-wordsjson)
- [EDL schema](#edl-schema)
- [How an EDL resolves](#how-an-edl-resolves)
- [Recipes](#recipes)
- [Variable frame rate](#variable-frame-rate)

## Transcript (`*.words.json`)

```json
{
 "source": "/abs/path/talk.mp4", "duration": 723.4, "language": "en", "engine": "faster-whisper:small@cpu",
 "segments": [
  {"id": "s0001", "start": 0.0, "end": 3.86, "text": "Hi, I'm going to show you...",
   "words": [{"w": " Hi,", "s": 0.0, "e": 0.34, "p": 0.78}]}
 ]
}
```

- Times are seconds in the source. `p` is Whisper's word probability (absent for API backends).
- Segments break at sentence ends, pauses >= 0.5 s, or 30 words. Ids are `s0001`...
- `transcript.txt` shows the same as `[s0001 00:00:00.000-00:00:03.860] text`.
- `render.py` writes `<output>.words.json` in the same shape with times on the edited timeline.

## EDL schema

```json
{
  "name": "cleanup",
  "sources": {"main": "../../talk.mp4", "broll": "C:/footage/broll.mov"},
  "transcripts": {"main": "transcript.words.json"},
  "clips": [
    {"src": "main", "segs": "s0003-s0010"},
    {"src": "broll", "start": "00:00:04.000", "end": "00:00:07.500"},
    {"src": "main", "start": 95.2}
  ],
  "drop": [
    {"src": "main", "start": 12.40, "end": 13.10, "reason": "filler", "text": "um,"},
    {"segs": "s0007"}
  ],
  "pad": 0.08,
  "fade": 0.015,
  "min_keep": 0.1,
  "loudnorm": false,
  "lufs": -16,
  "output": {"width": 1920, "height": 1080, "fps": 30, "crf": 18, "preset": "medium"}
}
```

| key | meaning |
|---|---|
| `name` | output basename; default: EDL filename up to the first dot |
| `sources` | key -> path, relative to the EDL file or absolute. Order matters when `clips` is absent |
| `transcripts` | key -> words JSON, required for `segs` references to that source |
| `clips` | ordered keep list. Absent = every source in full, in `sources` order |
| `clips[].segs` | `"s0004"` or `"s0004-s0009"` (inclusive). Expanded by `pad` on both sides |
| `clips[].start/end` | seconds or `HH:MM:SS.mmm` / `MM:SS.mmm`. Missing `end` = end of source |
| `drop` | ranges removed from the clips of the same source. `segs` drops are not padded |
| `src` | source key; defaults to the first source |
| `reason`, `text` | free text for reports, ignored by the renderer |
| `pad` | seconds added around `segs` clips (Whisper word ends are often early). Default 0.08 |
| `fade` | audio fade in/out at every piece edge. Default 0.015 (15 ms) |
| `min_keep` | pieces shorter than this after drops are discarded. Default 0.1 |
| `loudnorm` | two-pass EBU R128 to `lufs` (default -16; -14 for social). Ignored in preview |
| `output` | override size/fps (default: first source), x264 `crf`/`preset` |

## How an EDL resolves

1. Each clip becomes a source range (segments expanded by `pad`, clamped to the file).
2. Drops for that source are subtracted.
3. Every boundary snaps to the source's frame grid; pieces under `min_keep` are discarded.
4. Consecutive pieces of the same source that touch are merged (no needless cut).
5. Each piece is decoded from an accurate seek, normalized (fps, size, 48 kHz stereo), faded,
   padded/trimmed to identical A/V length, and concatenated.

## Recipes

Keep only a few segments, in a new order:

```json
{"sources": {"main": "../../talk.mp4"}, "transcripts": {"main": "transcript.words.json"},
 "clips": [{"segs": "s0042-s0047"}, {"segs": "s0001-s0003"}]}
```

Join several files (intro + talk + outro), normalizing formats:

```json
{"name": "joined", "sources": {"intro": "intro.mp4", "talk": "../../talk.mp4", "outro": "outro.mov"},
 "output": {"width": 1920, "height": 1080, "fps": 30}}
```

Cut a time range out of the middle:

```json
{"sources": {"main": "../../talk.mp4"}, "drop": [{"start": "00:04:10", "end": "00:05:02.5"}]}
```

## Variable frame rate

Phone recordings are usually VFR; `probe.py` warns about it. Convert once, then edit the copy:

```
ffmpeg -i IN.mp4 -fps_mode cfr -r 30 -c:v libx264 -crf 18 -preset medium -c:a aac -b:a 192k edits/IN.cfr.mp4
```

Use the source's nominal rate (`fps` from probe, rounded: 24, 25, 30, 50, 60).
