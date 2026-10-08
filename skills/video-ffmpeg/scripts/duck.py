# /// script
# requires-python = ">=3.10"
# ///
"""Add background music that ducks under speech (sidechain compression), looped and faded to the video length."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("music")
    ap.add_argument("--music-db", type=float, default=-18.0, help="music level before ducking (dB)")
    ap.add_argument("--duck", type=float, default=8.0, help="compression ratio while speech is present")
    ap.add_argument("--fade", type=float, default=2.0, help="music fade in/out seconds")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()

    src = Path(args.video).resolve()
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                               capture_output=True, text=True, check=True).stdout)
    out = Path(args.out).resolve() if args.out else src.with_name(f"{src.stem}.music.mp4")
    if out == src:
        sys.exit("error: refusing to overwrite the source")
    graph = (
        f"[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume={args.music_db}dB,"
        f"afade=t=in:d={args.fade},afade=t=out:st={max(0, dur - args.fade):.3f}:d={args.fade}[m];"
        "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,asplit=2[voice][sc];"
        f"[m][sc]sidechaincompress=threshold=0.02:ratio={args.duck}:attack=15:release=350:makeup=1[ducked];"
        "[voice][ducked]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]"
    )
    cmd = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-i", str(src), "-stream_loop", "-1", "-i", str(Path(args.music).resolve()),
           "-filter_complex", graph, "-map", "0:v:0?", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-t", f"{dur:.3f}", "-movflags", "+faststart", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if p.returncode:
        sys.exit(f"error: ffmpeg failed:\n{p.stderr[-2000:]}")
    print(json.dumps({"output": str(out), "duration": round(dur, 3)}))


if __name__ == "__main__":
    main()
