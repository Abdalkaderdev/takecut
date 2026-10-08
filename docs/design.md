# Design

## Goal

Let a coding agent (Claude Code, Codex, Gemini CLI, Cursor) edit real footage the way a person
edits a text document: read the transcript, decide what to keep, get a correct render. The agent
makes editorial decisions; tested scripts do everything that has to be exact.

## Principles

1. **The agent never improvises raw ffmpeg for core operations.** Cutting, joining, reframing and
   captioning go through scripts in `skills/*/scripts/`. One-off tasks use the tested recipes in
   `video-ffmpeg`, which CI executes.
2. **Single-file scripts with PEP 723 metadata**, run with `uv run script.py`. Dependencies install
   on first run into uv's cache; nothing is installed globally. Python >= 3.10. The shared engine
   (`video-edit/scripts/core.py`, `render.py`, `captions.py`) is standard library only.
3. **Local first.** faster-whisper on CUDA (float16) when an NVIDIA GPU is present, otherwise CPU
   int8. With a GPU but no CUDA libraries, `transcribe.py` re-runs itself under uv with the
   `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` wheels. Hosted Whisper (Groq, OpenAI) is opt-in via
   `--api` and an env key.
4. **Edits are data.** An EDL (JSON) says which source ranges to keep or drop, by segment id or
   time. It is reviewable, diffable and re-renderable.
5. **Never touch sources.** All output goes to `edits/<name>/` next to the source; `render.py`
   refuses an output path equal to any input. Preview first, then final; print every output path.

## Pipeline

```
probe -> transcribe -> (agent reads transcript.txt) -> EDL -> render --preview -> render
            |                                          ^
            +-> cleanup.py (silence/filler/retake) ----+
render -> <out>.mp4 + <out>.words.json (remapped) -> captions.py / shorts.py
```

## Transcription

- Audio is decoded by ffmpeg to 16 kHz mono float32 and passed as an array (avoids PyAV version
  drift).
- `word_timestamps=True`, `vad_filter=True` (Silero VAD), beam size 5.
- Whisper tends to omit disfluencies. A short disfluent `initial_prompt` per language (en, de, fr,
  es, it, pt, nl) makes it write "um"/"uh" so cleanup can see them. Language is detected first so
  the prompt matches.
- Words split by the tokenizer ("real" + "-life") are glued back.
- Segments: break at sentence punctuation, pauses >= 0.5 s, or 30 words. Ids `s0001..` are stable
  for a given transcript and are what the agent references.

## Rendering

- Each kept piece is its own input with `-ss`/`-t` before `-i` (accurate seek when transcoding),
  so pieces can come from any source in any order without decoding the whole file.
- Per piece: `fps`, scale + pad to the target, `tpad` + `trim` to exactly the piece length;
  audio resampled to 48 kHz stereo, `afade` in/out (15 ms default), `apad` + `atrim` to exactly
  the same length. Piece boundaries are snapped to the source frame grid, so video frame count
  and audio sample count agree and A/V sync cannot drift across hundreds of cuts.
- Pieces render in batches of 12 (bounded decoder memory) to intermediate MKV (x264 + PCM),
  joined with the concat demuxer (stream copy), then muxed once to MP4/AAC.
- Loudness: optional two-pass `loudnorm` (measure, then `linear=true` with measured values) on
  the joined audio. Final audio is trimmed to the exact video length (loudnorm can add samples).
- Sources without audio get `anullsrc` silence for their pieces.
- Output: `<name>.mp4` plus `<name>.words.json` / `.txt`, the transcript remapped to the new
  timeline (words kept if at least 80 ms or half of them survives), so captions and shorts of an
  edit need no second transcription.

## Cleanup detection

| reason | method |
|---|---|
| silence | `silencedetect` (default -35 dB, 0.6 s); leave 0.15 s each side |
| pause | word gaps where silencedetect saw nothing (noise floor too high) |
| filler | per-language token list; English "like" only when comma-delimited |
| retake | consecutive sentences >= 80% similar (difflib on tokens), or the earlier is a prefix of the later; drop the earlier |
| stutter | immediately repeated 1-4 token runs inside a sentence, with an allow-list ("very very") |

Output is an EDL with a `drop` list (each entry has `reason` and `text`) and a Markdown report.

## Shorts

- The agent picks moments from the transcript (criteria in `video-shorts/references/picking.md`);
  `shorts.py` takes ranges, segment ids or multi-part clips, widens ranges to whole words, renders
  the cut through `render.py`, builds word-highlight ASS captions from the remapped words, and
  reframes.
- Reframe: sample 6 frames/s, detect faces with OpenCV YuNet (Haar cascade fallback), follow the
  largest face with a continuity bias, interpolate gaps, median filter, dead zone (6% of width),
  speed limit and easing, 0.5 s moving average, then one `crop x` command per frame via
  `sendcmd`. No faces: centre crop or `--x`. Captions burn in the same ffmpeg pass.

## Captions

- Cue building from words: max 42 chars/line, 2 lines, 17 chars/s, 0.83-7 s, 2-frame gap, break
  on pauses > 0.6 s and on sentence ends; balanced two-line split.
- ASS with PlayRes equal to the video size; presets clean, boxed, minimal, highlight, pop.
- Translation: `translate-prep` exports `{id: text}`, the agent translates values, `translate-apply`
  validates keys and re-wraps into the original timings.

## Packaging

- Five Agent Skills (`skills/<name>/SKILL.md`, spec at agentskills.io) with `scripts/` and
  `references/`. `video-edit` holds the shared engine; the others import it from
  `../video-edit/scripts`, so skills are installed side by side.
- The repo root is also a Claude Code plugin (`.claude-plugin/plugin.json`) and its own marketplace
  (`.claude-plugin/marketplace.json`, source `./`).

## Testing

- Unit: timecodes, range merge/subtract, frame snapping, EDL resolution, word remapping, caption
  rules and ASS output, filler/retake/stutter detection, API response parsing (no ffmpeg needed).
- Render: synthetic testsrc + sine clips, 12-piece cut with loudnorm, mixed sizes/fps with a
  silent input, preview size, overwrite refusal; decoded audio vs video length within one frame.
- Recipes: every command in `video-ffmpeg/references/recipes.md` runs against generated fixtures.
- End-to-end (CI on Ubuntu): espeak-ng speech with fillers, retakes and pauses over testsrc ->
  transcribe (Whisper base) -> cleanup -> preview -> render -> SRT/ASS/burn -> 9:16 short.
