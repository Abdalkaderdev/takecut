---
name: video-ffmpeg
description: Tested ffmpeg recipes for everyday video and audio jobs - trim, concatenate mixed formats, speed up or slow down with pitch-correct audio, crop/scale/pad, compress to a target file size, convert and remux, high-quality GIFs, extract audio or frames, background music that ducks under speech, picture-in-picture, watermarks, loudness normalization, phone footage (VFR) fixes. Use for any one-off ffmpeg task, or when the user asks to compress, convert, resize, speed up, make a GIF, add music, overlay a logo or webcam.
license: MIT
compatibility: Requires ffmpeg and ffprobe on PATH; uv for the two helper scripts.
metadata:
  author: Abdalkader Alhamoud
  homepage: https://github.com/Abdalkaderdev/takecut
---

# video-ffmpeg

Find the recipe in [references/recipes.md](references/recipes.md), copy the command, change only
the file names and the documented knobs. Every command there runs in CI against generated clips.

## Rules

- Never write over an input file; new name in the same folder (or `edits/`).
- Probe first when the input is unknown: `uv run ../video-edit/scripts/probe.py INPUT`.
- Re-encode when cutting precisely; `-c copy` only for remuxing or rough keyframe cuts.
- `-pix_fmt yuv420p` and `-movflags +faststart` for anything that must play everywhere.
- On Windows, filter arguments with paths (subtitles, fonts) need the drive colon escaped
  (`C\:/path`); simpler to run ffmpeg from the file's folder and use a bare name.

## Helper scripts (the error-prone ones)

- Fit a size limit: `uv run scripts/compress.py INPUT --mb 25 [--max-height 720]`
  (two-pass, computes bitrate from duration, downscales when the bitrate is too low).
- Music under speech: `uv run scripts/duck.py VIDEO MUSIC [--music-db -14] [--duck 8]`
  (loops/fades music to the video length, sidechain-compresses it under the voice).

## Index

| task | section |
|---|---|
| frame-accurate or instant trim | Trim |
| join clips, same or mixed formats | Concatenate (many clips: video-edit EDL) |
| 1.5x / 0.5x with normal-pitch audio | Speed change |
| 720p, square, letterbox, vertical with blur | Crop, scale, pad |
| CRF quality, HEVC, target size | Compress |
| remux, MOV/ProRes to MP4, WebM | Convert and remux |
| GIF with palette | GIF |
| m4a/mp3/wav, frame grab, contact sheet | Extract audio, frames |
| sidechain ducking | Music under speech |
| webcam overlay | Picture-in-picture |
| logo overlay | Watermark |
| EBU R128 | Loudness |
| VFR to CFR, rotation | Phone footage |

Tasks that cut by content (remove pauses, fillers, sections by transcript) belong to
`video-edit` / `video-cleanup`; captions to `video-captions`; vertical face-tracked clips to
`video-shorts`.
