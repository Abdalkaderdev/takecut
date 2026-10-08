# /// script
# requires-python = ">=3.10"
# ///
"""Print a compact JSON summary of a media file and flag problems (VFR, rotation, no audio)."""
import argparse
import json

from core import fmt_time, probe


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    for f in args.files:
        info = probe(f)
        info["duration_tc"] = fmt_time(info["duration"])
        warn = []
        if info.get("vfr"):
            warn.append("variable frame rate: convert to CFR before editing (see video-edit SKILL.md)")
        if info.get("rotation"):
            warn.append(f"rotation metadata {info['rotation']}: width/height reported as displayed")
        if not info["has_audio"]:
            warn.append("no audio stream: transcription and cleanup are not possible")
        if not info["has_video"]:
            warn.append("no video stream")
        info["warnings"] = warn
        print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
