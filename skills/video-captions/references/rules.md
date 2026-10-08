# Caption rules

Defaults follow common broadcast/streaming guidelines (Netflix, BBC style).

| rule | default | flag |
|---|---|---|
| characters per line | 42 (presets: highlight 28, pop 16, minimal 48) | `--max-chars` |
| lines per cue | 2 (pop: 1) | `--max-lines` |
| reading speed | 17 characters/second; cues are extended to meet it when there is room | `--max-cps` |
| minimum duration | 0.83 s (5/6 s) | `--min-dur` |
| maximum duration | 7 s | `--max-dur` |
| gap between cues | 0.083 s (2 frames at 24 fps) | - |
| break on pause | a silence > 0.6 s always starts a new cue | - |

How cues are built from words:

1. Words accumulate until the next word would exceed `max_chars * max_lines`, the cue would run
   longer than `max_dur`, there is a pause, or a sentence ended and the cue already holds a third
   of a line.
2. Two-line cues split at the word boundary that best balances line lengths, preferring a break
   after punctuation and never exceeding `max_chars` when avoidable.
3. End time = last word end, extended for minimum duration and reading speed, but never past the
   next cue start minus the gap.
4. A cue that starts a sentence is capitalized (fixes "um, the idea" -> "The idea" after cleanup).

Word-highlight presets (`highlight`, `pop`) emit one ASS event per word with the active word
coloured; timing comes straight from the word timestamps.

For CJK/Thai use `--max-chars 16` (or 20) since every character counts and there are no spaces.
