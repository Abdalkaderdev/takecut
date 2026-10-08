---
name: video-cleanup
description: Automatically tighten talking-head footage, podcasts, tutorials and screen recordings. Removes silences and dead air, filler words (um, uh, comma-delimited "like", plus German, French, Spanish, Italian, Portuguese, Dutch, Russian, Turkish, Arabic, Japanese and Chinese fillers), stutters and repeated or false-start takes (keeps the last good take), then normalizes loudness to EBU R128. Reports every cut with timestamps and total time saved. Use when the user asks to clean up, tighten, remove ums or pauses, cut dead air, or make a recording sound professional.
license: MIT
compatibility: Requires ffmpeg, ffprobe and uv, and the video-edit skill installed alongside (shared scripts).
metadata:
  author: Abdalkader Alhamoud
  homepage: https://github.com/Abdalkaderdev/takecut
---

# video-cleanup

Detection is a script; the decision stays reviewable: it writes an EDL plus a report, you (and
the user) check them, then the video-edit renderer produces the result. Script paths below are
relative to this skill's folder (the shared engine is in `../video-edit/scripts/`); run them by
full path from the user's working directory (don't `cd` into the skill).

## Steps

1. Transcribe if `edits/<name>/transcript.words.json` doesn't exist yet:
   `uv run ../video-edit/scripts/transcribe.py INPUT`
2. Detect:
   `uv run scripts/cleanup.py edits/<name>/transcript.words.json`
   -> `edits/<name>/cleanup.edl.json` and `cleanup.report.md`, prints counts and before/after.
3. Read `cleanup.report.md`. Sanity-check `retake` and `stutter` rows against `transcript.txt`;
   remove any drop entry from the EDL that cuts real content (each has `reason` and `text`).
4. Preview: `uv run ../video-edit/scripts/render.py edits/<name>/cleanup.edl.json --preview`
5. Final: `uv run ../video-edit/scripts/render.py edits/<name>/cleanup.edl.json`
   -> `cleanup.mp4` and `cleanup.words.json` (for captions without re-transcribing).
6. Tell the user: before -> after duration, counts per reason, output path.

## What gets cut

| reason | detection | what is removed |
|---|---|---|
| `silence` | ffmpeg `silencedetect` (`--noise -35dB`, `--min-silence 0.6`) | the silence minus `--keep-pause 0.15` s on each side, so speech keeps a natural breath |
| `pause` | word gap > ~1.3 s where silencedetect saw no silence (noisy rooms) | the gap minus padding |
| `filler` | token in the language's filler list; "like" only when comma-delimited | the filler and the pause after it |
| `retake` | consecutive sentences that are near-duplicates (>= 80% similar) or where one is a prefix of the next | the earlier take; the last one is kept |
| `stutter` | immediately repeated 1-4 word runs inside a sentence ("I I think", "we should we should") | the first occurrence; "very very", "no no" etc. are kept |

## Options

- Noisy room / music bed: `--noise -30dB` (higher = more aggressive) or `--no-silences`.
- Keep more air: `--keep-pause 0.25`; cut only long silences: `--min-silence 1.0`.
- Fillers: `--add-fillers "basically,actually"` (single words) or replace with `--fillers "um,uh"`; `--no-like`.
- `--no-fillers`, `--no-repeats`, `--no-loudnorm`, `--lufs -14` (social) / `-16` (default).
- `--name tight` writes `tight.edl.json` so several variants can coexist.

Language comes from the transcript. Whisper normally drops "um"/"uh"; `transcribe.py` prompts it
to keep them for en/de/fr/es/it/pt/nl. For other languages fillers may be missing from the
transcript; silence and retake removal still work. Per-language lists:
[references/fillers.md](references/fillers.md).
