---
name: video-shorts
description: Turn long landscape videos (podcasts, talks, interviews, streams) into vertical 9:16 shorts for TikTok, YouTube Shorts and Instagram Reels. Picks self-contained 20-60 second moments with a hook from the transcript, reframes 16:9 to 9:16 with a smoothed face-tracking crop (OpenCV YuNet, fallback to a fixed speaker position), and burns word-by-word captions. Use when the user asks for shorts, reels, clips, highlights, vertical versions or "the best moments" of a video.
license: MIT
compatibility: Requires ffmpeg, ffprobe and uv, plus the video-edit and video-captions skills installed alongside. Downloads a 230 KB face model on first use (falls back to an offline Haar cascade).
metadata:
  author: Abdalkader Alhamoud
  homepage: https://github.com/Abdalkaderdev/takecut
---

# video-shorts

You pick the moments (reading the transcript is the part a script can't do well); the script cuts,
reframes and captions them. Script paths are relative to this skill's folder; run them by full
path from the user's working directory (don't `cd` into the skill).

## Steps

1. Transcript: `uv run ../video-edit/scripts/transcribe.py INPUT` (skip if
   `edits/<name>/transcript.words.json` exists). For a cleaned-up source, run video-cleanup first
   and use `cleanup.mp4` as INPUT, with `--transcript edits/<name>/cleanup.words.json`.
2. Read `edits/<name>/transcript.txt` and choose moments. Criteria in
   [references/picking.md](references/picking.md). Short version: 20-60 s, the first sentence
   hooks on its own, one complete idea, ends on a payoff, no dangling "so..." or references to
   earlier context.
3. Write `edits/<name>/shorts.json`:
   ```json
   [
    {"title": "Why most edits fail", "segs": "s0041-s0049"},
    {"title": "The one rule", "start": "00:12:03.2", "end": "00:12:41.0"},
    {"title": "Setup in two parts", "clips": [{"segs": "s0102-s0104"}, {"segs": "s0110-s0113"}]}
   ]
   ```
   Time ranges are widened to whole words automatically. `clips` joins non-adjacent parts.
4. Present the picks to the user (title, timecodes, the hook line, duration) before rendering many.
5. Render: `uv run scripts/shorts.py INPUT edits/<name>/shorts.json [--preset pop|highlight|clean|boxed|minimal]`
   -> `edits/<name>/shorts/01-why-most-edits-fail.mp4` ... plus `.ass`, `.edl.json`, `.words.json`, `.txt`.
   With `--transcript`, outputs go to `shorts/` next to that transcript.
   `--only 2 3` re-renders selected items. `--loudnorm` sets -14 LUFS.
6. Report each output path, duration and the `tracking` field. If tracking says `center (no faces
   found)` or the speaker sits off-centre, rerun that item with `--x 0.3` (0 = left edge, 1 = right).

## Reframing details

- Faces are sampled 6x per second; the crop follows the largest face, preferring the one near the
  previous position (stable on two-person shots until the other face dominates).
- The path is median-filtered, held still inside a dead zone (6% of frame width), speed-limited and
  eased, so the camera doesn't jitter or chase every head movement.
- Already-vertical or square input is center-cropped/scaled without tracking.
- Standalone: `uv run scripts/reframe.py INPUT [--ass subs.ass] [--x 0.4] [--size 1080x1920]`.
- Other aspect ratios: `--size 1080x1350` (4:5 feed), `--size 1080x1080`.

## Captions

Default preset `pop`: 1-3 words at a time, uppercase, active word highlighted, lower-middle of
the frame clear of platform UI. `highlight` shows a full line with the active word coloured.
`--no-captions` for a clean export. Edit an `.ass` and rerun `reframe.py` with `--ass` to tweak.
