---
name: video-edit
description: Edit real video footage through its transcript. Probes a file, transcribes it locally with word timestamps (faster-whisper, GPU or CPU, no API key), lets you cut by editing a JSON edit decision list (EDL), and renders frame-accurate output with click-free cuts. Use when the user wants to cut, trim, rearrange or join video/audio clips by what is said, remove sections, or needs a transcript with timecodes. Also the shared engine for the video-cleanup, video-shorts and video-captions skills.
license: MIT
compatibility: Requires ffmpeg and ffprobe on PATH and uv (https://docs.astral.sh/uv/). Python 3.10+ is fetched by uv. Optional NVIDIA GPU (CUDA 12).
metadata:
  author: Abdalkader Alhamoud
  homepage: https://github.com/Abdalkaderdev/takecut
---

# video-edit

Read a video as text, decide the cut as data, render it with a tested script. Never improvise raw
ffmpeg for cutting; use the scripts below. `scripts/...` means this skill's folder + `scripts/...`:
run them by full path from the user's working directory (don't `cd` into the skill folder), e.g.
`uv run /path/to/skills/video-edit/scripts/probe.py talk.mp4`.

## Rules

- Never modify, move or overwrite a source file. Everything goes to `edits/<name>/` next to it.
- Always render `--preview` first and tell the user the path; render the final only after they
  agree (or they said to go straight to final).
- Print the exact output paths you produced.
- Long jobs: transcription runs at a few times realtime on CPU (`small`) and 15x+ on a laptop
  GPU (`large-v3-turbo`). For a 1 h file on CPU, warn the user, suggest `--model base`, or run
  it in the background.

## Workflow

1. **Probe** - duration, fps, resolution, VFR/rotation warnings:
   `uv run scripts/probe.py INPUT`
   If it warns about variable frame rate (phone footage), convert to CFR first (see
   [references/edl.md](references/edl.md#variable-frame-rate)) and edit the converted file.
2. **Transcribe** - writes `edits/<name>/transcript.words.json` and `transcript.txt`:
   `uv run scripts/transcribe.py INPUT [--language en] [--model small|large-v3-turbo] [--device cpu]`
   With an NVIDIA GPU it fetches CUDA libraries through uv once and uses `large-v3-turbo`.
   `--api groq` / `--api openai` use GROQ_API_KEY / OPENAI_API_KEY instead (audio is uploaded).
   Use `--prompt "Names, Jargon"` for unusual spellings.
3. **Read** `transcript.txt`. One line per segment: `[s0012 00:01:03.420-00:01:07.900] text`.
   Segment ids are stable; refer to them in the EDL.
4. **Write an EDL** (`edits/<name>/<edit-name>.edl.json`). Minimal forms:
   ```json
   {"sources": {"main": "../../talk.mp4"}, "transcripts": {"main": "transcript.words.json"},
    "drop": [{"segs": "s0004-s0006"}, {"start": "00:02:10.5", "end": 135.2, "reason": "off topic"}]}
   ```
   ```json
   {"sources": {"main": "../../talk.mp4"}, "transcripts": {"main": "transcript.words.json"},
    "clips": [{"segs": "s0030-s0034"}, {"segs": "s0002"}, {"start": 61.0, "end": 64.5}]}
   ```
   `clips` = what to keep, in output order (may reorder, may use several sources). `drop` = what to
   remove from the clips (or from whole sources when there are no clips). Full schema, options
   (`pad`, `fade`, `loudnorm`, output size) and multi-source joins: [references/edl.md](references/edl.md).
5. **Preview**: `uv run scripts/render.py EDL --preview` -> `<edit-name>.preview.mp4` (480p, fast).
6. **Final**: `uv run scripts/render.py EDL` -> `<edit-name>.mp4` plus `<edit-name>.words.json`
   and `<edit-name>.txt` (the transcript remapped to the new timeline; use them for captions or
   shorts of the edit without re-transcribing).

## What render guarantees

Frame-accurate cuts (piece boundaries snap to the source frame grid), a 15 ms audio fade at every
cut, audio and video of identical length per piece (A/V sync never drifts), mixed resolutions/frame
rates normalized to the first source (or `output.width/height/fps`), sources without audio get
silence, optional two-pass EBU R128 loudness normalization.

## Related skills

- `video-cleanup`: automatic silence / filler / retake removal -> an EDL for this renderer.
- `video-shorts`: vertical 9:16 clips with face tracking and captions.
- `video-captions`: SRT/VTT/styled burned-in captions and translation.
- `video-ffmpeg`: tested one-off ffmpeg recipes (compress, GIF, speed, music ducking...).

## Troubleshooting

- `ffmpeg not found`: install it (winget install Gyan.FFmpeg / brew install ffmpeg / apt install ffmpeg).
- CUDA errors fall back to CPU automatically; `--device cpu` skips the GPU entirely.
- Bad word timings on music-heavy audio: try `--no-vad` or a larger `--model`.
