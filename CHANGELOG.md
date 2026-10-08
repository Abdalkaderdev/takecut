# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-08

### Added

- `video-edit`: probe, local transcription with word timestamps (faster-whisper, CUDA or CPU,
  optional Groq/OpenAI API), JSON edit decision lists by segment id or time, frame-accurate
  renderer with click-free cuts, multi-source joins, preview mode, two-pass loudness
  normalization, transcript remapped onto the edited timeline.
- `video-cleanup`: silence, filler-word (12 languages), retake and stutter detection with a cut
  report and an EDL.
- `video-shorts`: moment picking guide, 9:16 reframing with smoothed face tracking, word-highlight
  captions, batch rendering from a JSON spec.
- `video-captions`: SRT/VTT with broadcast line and timing rules, five ASS presets, burn-in,
  timing-safe translation flow.
- `video-ffmpeg`: CI-tested recipe reference plus target-size compression and music ducking scripts.
- Claude Code plugin manifest and marketplace; CI on Linux, Windows and macOS; end-to-end test on
  synthetic speech.
