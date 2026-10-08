# /// script
# requires-python = ">=3.10"
# ///
"""Detect silences, filler words and repeated/false-start takes; write an EDL plus a cut report.

Needs the transcript from video-edit/scripts/transcribe.py. Writes, next to the transcript:
  cleanup.edl.json   drop list for video-edit/scripts/render.py
  cleanup.report.md  every cut with timecodes, reason and text, plus totals
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "video-edit" / "scripts"))
try:
    from core import all_words, fmt_dur, fmt_time, load_words, merge, norm_token, probe, run, similar
except ImportError:
    raise SystemExit("error: video-cleanup needs the video-edit skill installed next to it (skills/video-edit/scripts/core.py)")

FILLERS = {
    "en": {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "mm", "mhm"},
    "de": {"äh", "ähm", "öh", "öhm", "hm", "ähh"},
    "fr": {"euh", "heu", "bah", "ben", "hum"},
    "es": {"eh", "em", "este", "mmm"},
    "it": {"ehm", "eh", "uhm", "mmm"},
    "pt": {"é", "hum", "ahn", "éé"},
    "nl": {"eh", "ehm", "uhm", "uh"},
    "ru": {"э", "ээ", "эм", "ну"},
    "tr": {"ııı", "şey", "eee"},
    "ar": {"اه", "ام", "اممم", "يعني"},
    "ja": {"えーと", "えっと", "あの", "えー", "あのー", "うーん"},
    "zh": {"嗯", "呃", "那个", "额"},
}
COMMON = {"um", "uh", "uhm", "umm", "hmm", "mm", "erm"}
LIKE_FILLER = {"en": "like"}
REPEAT_OK = {"very", "really", "no", "yeah", "yes", "bye", "ha", "hey", "so", "that", "had", "is", "go", "knock", "well"}


def silences(src: Path, noise: str, min_dur: float) -> list:
    p = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", src, "-vn", "-af", f"silencedetect=noise={noise}:d={min_dur}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    dur = probe(src)["duration"]
    return [(max(0.0, s), ends[i] if i < len(ends) else dur) for i, s in enumerate(starts)]


def silence_cuts(sil, words, keep: float, min_dur: float, duration: float) -> list:
    cuts = []
    for s, e in sil:
        lead = 0.0 if s <= 0.01 else keep
        tail = 0.0 if e >= duration - 0.01 else keep
        if e - s >= min_dur and (e - tail) - (s + lead) > 0.05:
            cuts.append((s + lead, e - tail, "silence", ""))
    gaps_from_words = []
    for a, b in zip(words, words[1:]):
        if b["s"] - a["e"] >= min_dur + 2 * keep + 0.4:
            gaps_from_words.append((a["e"] + keep + 0.1, b["s"] - keep - 0.1, "pause", ""))
    for g in gaps_from_words:
        if not any(s < g[1] and g[0] < e for s, e in sil):
            cuts.append(g)
    return cuts


def filler_cuts(words, fillers: set, like: str | None) -> list:
    cuts = []
    for i, w in enumerate(words):
        tok = norm_token(w["w"])
        raw = w["w"].strip()
        is_filler = tok in fillers
        if like and tok == like:
            prev_raw = words[i - 1]["w"].strip() if i else ""
            is_filler = raw.endswith(",") and (i == 0 or prev_raw.endswith((",", ".", "?", "!")))
        if not is_filler:
            continue
        prev_e = words[i - 1]["e"] if i else 0.0
        nxt = words[i + 1] if i + 1 < len(words) else None
        start = max(prev_e, w["s"] - 0.02)
        end = (nxt["s"] - 0.03) if nxt and nxt["s"] - w["e"] < 1.0 else w["e"] + 0.05
        if end - start > 0.05:
            cuts.append((start, end, "filler", raw))
    return cuts


def toks(seg) -> list:
    return [t for t in (norm_token(w["w"]) for w in seg["words"]) if t]


def repeat_cuts(segments, fillers: set) -> list:
    cuts = []
    for a, b in zip(segments, segments[1:]):
        ta = [t for t in toks(a) if t not in fillers]
        tb = [t for t in toks(b) if t not in fillers]
        if len(ta) < 2 or not tb or b["start"] - a["end"] > 6:
            continue
        dup = len(ta) >= 3 and similar(ta, tb) >= 0.8
        false_start = len(ta) < len(tb) and similar(ta, tb[: len(ta)]) >= 0.8
        if dup or false_start:
            cuts.append((a["start"] - 0.02, b["start"] - 0.03, "retake", a["text"]))
    for seg in segments:
        ws = [w for w in seg["words"] if norm_token(w["w"])]
        t = [norm_token(w["w"]) for w in ws]
        i = 0
        while i < len(t):
            for n in (4, 3, 2, 1):
                if i + 2 * n <= len(t) and t[i:i + n] == t[i + n:i + 2 * n] and not (n == 1 and t[i] in REPEAT_OK):
                    cuts.append((ws[i]["s"] - 0.02, ws[i + n]["s"] - 0.03, "stutter", " ".join(w["w"].strip() for w in ws[i:i + n])))
                    i += n - 1
                    break
            i += 1
    return cuts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", help="transcript.words.json from transcribe.py")
    ap.add_argument("--source", help="video file (default: the transcript's source)")
    ap.add_argument("--min-silence", type=float, default=0.6, help="cut silences longer than this (s)")
    ap.add_argument("--keep-pause", type=float, default=0.15, help="silence to leave on each side of a cut (s)")
    ap.add_argument("--noise", default="-35dB", help="silencedetect threshold, e.g. -30dB for noisy rooms")
    ap.add_argument("--fillers", help="comma list replacing the language's filler words")
    ap.add_argument("--add-fillers", help="comma list added to the language's filler words")
    ap.add_argument("--no-silences", action="store_true")
    ap.add_argument("--no-fillers", action="store_true")
    ap.add_argument("--no-repeats", action="store_true")
    ap.add_argument("--no-like", action="store_true", help="don't treat comma-delimited 'like' as a filler")
    ap.add_argument("--no-loudnorm", action="store_true")
    ap.add_argument("--lufs", type=float, default=-16.0, help="loudness target (-16 podcasts/YouTube, -14 social)")
    ap.add_argument("--name", default="cleanup")
    args = ap.parse_args()

    tp = Path(args.transcript).resolve()
    tr = load_words(tp)
    src = Path(args.source or tr["source"]).resolve()
    info = probe(src)
    lang = (tr.get("language") or "en").split("-")[0]
    words = all_words(tr)
    if args.fillers:
        fillers = {norm_token(f) for f in args.fillers.split(",")}
    else:
        fillers = FILLERS.get(lang, set()) | COMMON
    if args.add_fillers:
        fillers |= {norm_token(f) for f in args.add_fillers.split(",")}

    cuts = []
    if not args.no_silences:
        sil = silences(src, args.noise, args.min_silence)
        cuts += silence_cuts(sil, words, args.keep_pause, args.min_silence, info["duration"])
    if not args.no_fillers:
        cuts += filler_cuts(words, fillers, None if args.no_like else LIKE_FILLER.get(lang))
    if not args.no_repeats:
        cuts += repeat_cuts(tr["segments"], fillers)
    cuts = sorted((max(0.0, s), min(info["duration"], e), k, t) for s, e, k, t in cuts if e > s)

    merged = merge([(s, e) for s, e, *_ in cuts])
    removed = sum(e - s for s, e in merged)
    counts = {}
    for _, _, k, _ in cuts:
        counts[k] = counts.get(k, 0) + 1

    out_dir = tp.parent
    try:
        rel_src = Path(os.path.relpath(src, out_dir)).as_posix()
    except ValueError:
        rel_src = src.as_posix()
    edl = {
        "name": args.name,
        "sources": {"main": rel_src},
        "transcripts": {"main": tp.name},
        "drop": [{"start": round(s, 3), "end": round(e, 3), "reason": k, "text": t} for s, e, k, t in cuts],
        "fade": 0.015,
        "loudnorm": not args.no_loudnorm,
        "lufs": args.lufs,
    }
    edl_path = out_dir / f"{args.name}.edl.json"
    edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=1), encoding="utf-8")

    after = info["duration"] - removed
    lines = [
        f"# Cleanup report: {src.name}",
        "",
        f"{fmt_dur(info['duration'])} -> {fmt_dur(after)} ({removed:.1f}s removed, {100 * removed / max(info['duration'], 1e-9):.0f}%)",
        "",
        "| reason | count |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(counts.items())],
        "",
        "| # | reason | start | end | dur | text |",
        "|---|---|---|---|---|---|",
    ]
    lines += [f"| {i} | {k} | {fmt_time(s)} | {fmt_time(e)} | {e - s:.2f}s | {t.replace('|', '/')} |" for i, (s, e, k, t) in enumerate(cuts, 1)]
    report = out_dir / f"{args.name}.report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "edl": str(edl_path),
        "report": str(report),
        "counts": counts,
        "before": fmt_dur(info["duration"]),
        "after": fmt_dur(after),
        "removed_s": round(removed, 1),
    }, indent=1))


if __name__ == "__main__":
    main()
