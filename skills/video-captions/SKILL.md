---
name: video-captions
description: Make accurate subtitles and styled burned-in captions from word-level timestamps. Generates SRT and WebVTT that follow broadcast rules (42 characters per line, 2 lines, reading speed, minimum duration, gaps), ASS captions with presets (clean, boxed, minimal, word-highlight karaoke, TikTok-style pop), burns them into video, and translates captions while keeping the original timings. Use when the user asks for subtitles, captions, SRT/VTT files, burned-in or animated captions, or subtitles in another language.
license: MIT
compatibility: Requires ffmpeg (with libass) and uv, and the video-edit skill installed alongside for transcription.
metadata:
  author: Abdalkader Alhamoud
  homepage: https://github.com/Abdalkaderdev/takecut
---

# video-captions

Script paths are relative to this skill's folder; run them by full path from the user's working
directory (don't `cd` into the skill). Input is a words JSON: either
`edits/<name>/transcript.words.json` (captions for the original) or the `<edit>.words.json` that
video-edit's `render.py` writes next to an edited output (captions for the edit; no re-transcribing).

## Files

- SRT: `uv run scripts/captions.py srt WORDS.json` -> `<stem>.srt`
- VTT: `uv run scripts/captions.py vtt WORDS.json`
- Styled ASS: `uv run scripts/captions.py ass WORDS.json --preset highlight --video VIDEO.mp4`
  (or `--size 1080x1920`; PlayRes matches the video so sizes are proportional)
- Burn in: `uv run scripts/captions.py burn VIDEO.mp4 SUBS.ass` -> `VIDEO.captioned.mp4`
  (an `.srt` is converted with the `clean` style). Audio is copied untouched.

Missing transcript: `uv run ../video-edit/scripts/transcribe.py VIDEO` first.

## Presets

| preset | look | use |
|---|---|---|
| `clean` | white bold, black outline, bottom | default landscape subtitles |
| `boxed` | white on a translucent black box | busy backgrounds, accessibility |
| `minimal` | smaller, thin outline | documentary, interviews |
| `highlight` | full line, active word yellow | tutorials, talking heads |
| `pop` | 1-3 uppercase words, active word green, slight scale pop, lower-middle | vertical shorts |

Options: `--font "Inter"` (must be installed, or pass `--fonts-dir` to `burn`), `--max-chars`,
`--max-lines`, `--max-cps` (default 17), `--min-dur` (0.83 s), `--max-dur` (7 s).
Line-break and timing rules: [references/rules.md](references/rules.md).

## Translation (timings preserved)

1. Make the source-language SRT (above).
2. `uv run scripts/captions.py translate-prep SUBS.srt` -> `SUBS.lines.json` (`{"1": "text", ...}`).
3. Translate every value yourself into a new file, e.g. `SUBS.de.lines.json`. Keep every key,
   one entry per cue, no merging or splitting. Translate meaning, keep it about as short as the
   original (subtitles are read fast); keep names and numbers.
4. `uv run scripts/captions.py translate-apply SUBS.srt SUBS.de.lines.json --lang de`
   -> `SUBS.de.srt` with the original timings, re-wrapped to the line rules. It refuses if keys
   don't match. Use `--lang zh|ja|th` for languages written without spaces.
5. Optional: `uv run scripts/captions.py ass SUBS.de.srt --preset boxed --video VIDEO.mp4`, then `burn`.

Always report output paths and the cue count.
