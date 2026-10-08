# /// script
# requires-python = ">=3.10"
# ///
"""Compress a video to fit a target file size with two-pass x264 (e.g. 25 MB for Discord, 100 MB for email gateways).

Computes the video bitrate from duration, reserves audio bitrate and ~3% container overhead, and
downscales when the bitrate would be too low for the resolution.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def sh(cmd, cwd=None):
    p = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, errors="replace")
    if p.returncode:
        sys.exit(f"error: {cmd[0]} failed:\n{p.stderr[-2000:]}")
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input")
    ap.add_argument("--mb", type=float, required=True, help="target size in megabytes (10^6 bytes)")
    ap.add_argument("--audio-kbps", type=int, default=128)
    ap.add_argument("--max-height", type=int, help="cap output height, e.g. 720")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()

    src = Path(args.input).resolve()
    info = json.loads(sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height:format=duration", "-of", "json", src]))
    dur = float(info["format"]["duration"])
    height = int(info["streams"][0]["height"])
    total_kbps = args.mb * 8e6 * 0.97 / dur / 1000
    v_kbps = int(total_kbps - args.audio_kbps)
    if v_kbps < 100:
        sys.exit(f"error: {args.mb} MB is too small for {dur:.0f}s (would need {v_kbps} kbps video). Trim it or lower --audio-kbps.")
    target_h = args.max_height or height
    for limit, h in ((400, 480), (900, 720), (2000, 1080)):
        if v_kbps < limit:
            target_h = min(target_h, h)
            break
    vf = ["-vf", f"scale=-2:{target_h}"] if target_h < height else []
    out = Path(args.out).resolve() if args.out else src.with_name(f"{src.stem}.{args.mb:g}MB.mp4")
    if out == src:
        sys.exit("error: refusing to overwrite the source")
    common = ["-c:v", "libx264", "-preset", "slow", "-b:v", f"{v_kbps}k", *vf]
    with tempfile.TemporaryDirectory() as tmp:
        sh(["ffmpeg", "-y", "-nostdin", "-i", src, *common, "-pass", "1", "-passlogfile", "pass", "-an", "-f", "null", "-"], cwd=tmp)
        sh(["ffmpeg", "-y", "-nostdin", "-i", src, *common, "-pass", "2", "-passlogfile", "pass",
            "-c:a", "aac", "-b:a", f"{args.audio_kbps}k", "-movflags", "+faststart", out], cwd=tmp)
    size = out.stat().st_size
    print(json.dumps({"output": str(out), "size_mb": round(size / 1e6, 2), "target_mb": args.mb, "video_kbps": v_kbps, "height": target_h}))


if __name__ == "__main__":
    main()
