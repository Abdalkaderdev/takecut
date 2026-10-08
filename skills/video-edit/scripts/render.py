# /// script
# requires-python = ">=3.10"
# ///
"""Render an edit decision list (EDL JSON) to video, frame-accurately.

Every kept piece is re-encoded from an accurate input seek, gets a short audio fade in/out so cuts
don't click, and is padded/trimmed so audio and video have identical length. Pieces are joined in
batches, then muxed once (optionally with two-pass EBU R128 loudness normalization).

Writes <edl dir>/<name>.mp4 (or <name>.preview.mp4 with --preview) plus <output>.words.json with
the transcript remapped onto the new timeline.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import (  # noqa: E402
    EDL_DEFAULTS, _abs, ffmpeg, fmt_dur, fmt_time, guard_output, load_edl, load_words, probe, remap_words,
    resolve_edl, run, write_transcript,
)

BATCH = 12


def even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def target_format(edl: dict, probes: dict, preview: bool) -> tuple[int, int, float]:
    first = next(iter(probes.values()))
    o = edl.get("output", {})
    w, h = o.get("width") or first.get("width", 1280), o.get("height") or first.get("height", 720)
    fps = o.get("fps") or first.get("fps") or 30
    if preview and h > 480:
        w, h = w * 480 / h, 480
    return even(w), even(h), fps


def render_batch(pieces, sources, probes, out: Path, w, h, fps, fade, enc):
    inputs, graph, labels = [], [], []
    idx = 0
    for k, (src, s, e) in enumerate(pieces):
        d = e - s
        inputs += ["-ss", f"{s:.6f}", "-t", f"{d:.6f}", "-i", sources[src]]
        vi = idx
        idx += 1
        if probes[src]["has_audio"]:
            ai = vi
        else:
            inputs += ["-f", "lavfi", "-t", f"{d:.6f}", "-i", "anullsrc=r=48000:cl=stereo"]
            ai = idx
            idx += 1
        f = min(fade, d / 4)
        graph.append(
            f"[{vi}:v:0]fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration=1,trim=duration={d:.6f},setpts=PTS-STARTPTS[v{k}]"
        )
        graph.append(
            f"[{ai}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"afade=t=in:d={f:.4f},afade=t=out:st={d - f:.6f}:d={f:.4f},apad,atrim=duration={d:.6f},asetpts=PTS-STARTPTS[a{k}]"
        )
        labels.append(f"[v{k}][a{k}]")
    graph.append(f"{''.join(labels)}concat=n={len(pieces)}:v=1:a=1[v][a]")
    ffmpeg([*inputs, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]", *enc, "-c:a", "pcm_s16le", out])


def loudnorm_params(path: Path, lufs: float) -> str:
    p = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vn", "-af",
             f"loudnorm=I={lufs}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr)
    if not m:
        return f"loudnorm=I={lufs}:TP=-1.5:LRA=11"
    j = json.loads(m.group(0))
    if j["input_i"] in ("-inf", "inf"):
        return "anull"
    return (
        f"loudnorm=I={lufs}:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
        f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true"
    )


def render(edl: dict, preview: bool = False, out: Path | None = None, quiet: bool = False) -> dict:
    base = edl.get("_dir", ".")
    sources = {k: _abs(base, v) for k, v in edl["sources"].items()}
    probes = {k: probe(v) for k, v in sources.items()}
    for k, p in probes.items():
        if not p["has_video"]:
            raise SystemExit(f"error: source {k} has no video stream")
    pieces = resolve_edl(edl, probes)
    opt = {**EDL_DEFAULTS, **edl}
    w, h, fps = target_format(edl, probes, preview)
    name = edl.get("name", "edit")
    out = Path(out) if out else Path(base) / (f"{name}.preview.mp4" if preview else f"{name}.mp4")
    out = guard_output(out, sources.values())
    crf = edl.get("output", {}).get("crf", 18)
    enc = (["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30"] if preview
           else ["-c:v", "libx264", "-preset", edl.get("output", {}).get("preset", "medium"), "-crf", str(crf)])
    enc += ["-pix_fmt", "yuv420p", "-g", str(int(round(fps * 2)))]

    tmp = Path(tempfile.mkdtemp(prefix="takecut-", dir=out.parent))
    try:
        parts = []
        batches = [pieces[i:i + BATCH] for i in range(0, len(pieces), BATCH)]
        for i, b in enumerate(batches):
            if not quiet:
                print(f"  rendering part {i + 1}/{len(batches)} ({len(b)} pieces)", file=sys.stderr)
            part = tmp / f"part{i:04d}.mkv"
            render_batch(b, sources, probes, part, w, h, fps, opt["fade"], enc)
            parts.append(part)
        if len(parts) == 1:
            joined = parts[0]
        else:
            lst = tmp / "parts.txt"
            lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
            joined = tmp / "joined.mkv"
            ffmpeg(["-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", joined.name], cwd=tmp)
        af = loudnorm_params(joined, opt["lufs"]) if opt["loudnorm"] and not preview else "anull"
        total = sum(e - s for _, s, e in pieces)
        ffmpeg(["-i", joined, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                "-af", f"{af},aresample=48000,atrim=duration={total:.6f}",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    trs = {k: load_words(_abs(base, v)) for k, v in edl.get("transcripts", {}).items()}
    words_path = txt_path = None
    if trs:
        lang = next(iter(trs.values())).get("language")
        remapped = remap_words(pieces, trs, lang)
        remapped["source"] = str(out)
        words_path = out.with_name(out.stem + ".words.json")
        txt_path = write_transcript(remapped, words_path)
    src_total = sum(p["duration"] for p in probes.values()) if not edl.get("clips") else None
    res = probe(out)
    summary = {
        "output": str(out),
        "words_json": str(words_path) if words_path else None,
        "transcript": str(txt_path) if txt_path else None,
        "pieces": len(pieces),
        "cuts": max(0, len(pieces) - 1),
        "duration": round(res["duration"], 3),
        "duration_tc": fmt_time(res["duration"]),
        "size": f"{w}x{h}@{fps:g}",
    }
    if src_total:
        summary["source_duration"] = round(src_total, 3)
        summary["saved"] = f"{fmt_dur(src_total)} -> {fmt_dur(res['duration'])} ({src_total - res['duration']:.1f}s removed)"
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("edl")
    ap.add_argument("--preview", action="store_true", help="fast low-res render (<=480p, ultrafast) for checking cuts")
    ap.add_argument("-o", "--out", help="output path (default: next to the EDL)")
    args = ap.parse_args()
    print(json.dumps(render(load_edl(args.edl), args.preview, args.out), indent=1))


if __name__ == "__main__":
    main()
