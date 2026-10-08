# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python-headless>=4.8", "numpy"]
# ///
"""Cut vertical shorts from a long video: render each picked moment, reframe to 9:16 with face tracking,
burn word-highlight captions.

Spec JSON (list), each item one short:
  {"title": "hook-about-x", "start": "00:03:12.4", "end": "00:03:51.0"}
  {"title": "two-parts", "clips": [{"segs": "s0040-s0044"}, {"start": 610.2, "end": 622.9}]}
  {"title": "by-ids", "segs": "s0102-s0110"}

Writes edits/<name>/shorts/NN-title.mp4 next to the source.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for d in (ROOT / "video-edit" / "scripts", ROOT / "video-captions" / "scripts", Path(__file__).resolve().parent):
    sys.path.insert(0, str(d))
try:
    from captions import PRESETS, build_cues, to_ass
    from core import all_words, die, edits_dir, fmt_time, load_words, parse_time
    from reframe import reframe
    from render import render
except ImportError as exc:
    raise SystemExit(f"error: video-shorts needs video-edit and video-captions installed next to it ({exc})")


def word_safe(start: float, end: float, words: list) -> tuple:
    for w in words:
        if w["s"] < start < w["e"]:
            start = w["s"]
        if w["s"] < end < w["e"]:
            end = w["e"]
    return start, end


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "short"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("spec", help="JSON file with the picked moments")
    ap.add_argument("--transcript", help="default: edits/<name>/transcript.words.json")
    ap.add_argument("--preset", default="pop", choices=sorted(PRESETS))
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--x", type=float, help="fixed crop centre 0..1 instead of face tracking")
    ap.add_argument("--loudnorm", action="store_true", help="normalize each short to -14 LUFS")
    ap.add_argument("--only", type=int, nargs="*", help="render only these 1-based spec indices")
    args = ap.parse_args()

    src = Path(args.source).resolve()
    tp = Path(args.transcript).resolve() if args.transcript else edits_dir(src) / "transcript.words.json"
    work = tp.parent
    if not tp.exists():
        die(f"no transcript at {tp}; run video-edit/scripts/transcribe.py first")
    tr = load_words(tp)
    words = all_words(tr)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if isinstance(spec, dict):
        spec = spec.get("shorts", [])
    out_dir = work / "shorts"
    out_dir.mkdir(exist_ok=True)
    w, h = map(int, args.size.lower().split("x"))
    results = []
    for i, item in enumerate(spec, 1):
        if args.only and i not in args.only:
            continue
        clips = item.get("clips") or ([{"segs": item["segs"]}] if "segs" in item else [{"start": item["start"], "end": item["end"]}])
        fixed = []
        for c in clips:
            if "segs" in c:
                fixed.append(c)
            else:
                s, e = word_safe(parse_time(c["start"]), parse_time(c["end"]), words)
                fixed.append({"start": round(s - 0.05, 3), "end": round(e + 0.12, 3)})
        name = f"{i:02d}-{slug(item.get('title', f'short-{i}'))}"
        edl = {
            "_dir": str(out_dir),
            "name": name + ".cut",
            "sources": {"main": str(src)},
            "transcripts": {"main": str(tp)},
            "clips": fixed,
            "loudnorm": args.loudnorm,
            "lufs": -14.0,
            "output": {"crf": 16, "preset": "fast"},
        }
        (out_dir / f"{name}.edl.json").write_text(json.dumps({k: v for k, v in edl.items() if k != "_dir"}, indent=1), encoding="utf-8")
        print(f"[{i}/{len(spec)}] {name}: cutting", file=sys.stderr)
        cut = render(edl, quiet=True)
        ass = None
        if not args.no_captions and cut["words_json"]:
            cw = load_words(cut["words_json"])
            p = PRESETS[args.preset]
            cues = build_cues(all_words(cw), cw.get("language"), max_chars=p.get("max_chars", 42), max_lines=p.get("max_lines", 2))
            ass = out_dir / f"{name}.ass"
            ass.write_text(to_ass(cues, w, h, args.preset), encoding="utf-8")
        print(f"[{i}/{len(spec)}] {name}: reframing", file=sys.stderr)
        res = reframe(Path(cut["output"]), out_dir / f"{name}.mp4", (w, h), ass, args.x)
        os.remove(cut["output"])
        if cut["words_json"]:
            os.replace(cut["words_json"], out_dir / f"{name}.words.json")
            os.replace(cut["transcript"], out_dir / f"{name}.txt")
        res.update(title=item.get("title"), duration=cut["duration"], duration_tc=fmt_time(cut["duration"]))
        results.append(res)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
