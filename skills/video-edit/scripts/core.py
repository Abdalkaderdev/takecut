"""Shared helpers for takecut scripts: ffmpeg/ffprobe, timecodes, ranges, EDL resolution, transcripts.

Standard library only so every skill can import it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

SENTENCE_END = tuple(".?!…。？！")
NO_SPACE_LANGS = {"zh", "ja", "th", "lo", "km", "my", "yue"}


def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        die(f"{tool} not found on PATH. Install ffmpeg (https://ffmpeg.org/download.html) and retry.")
    return path


def run(cmd: list, cwd=None, capture: bool = False) -> subprocess.CompletedProcess:
    need(cmd[0])
    p = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-25:])
        die(f"{Path(cmd[0]).name} failed ({p.returncode}):\n{tail}")
    return p


def ffmpeg(args: list, cwd=None) -> subprocess.CompletedProcess:
    return run(["ffmpeg", "-hide_banner", "-nostdin", "-y", *args], cwd=cwd)


def _rate(s: str | None) -> float:
    if not s or s in ("0/0", "0"):
        return 0.0
    if "/" in s:
        n, d = s.split("/")
        return float(n) / float(d) if float(d) else 0.0
    return float(s)


def probe(path) -> dict:
    path = Path(path)
    if not path.is_file():
        die(f"no such file: {path}")
    p = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path])
    data = json.loads(p.stdout)
    fmt = data.get("format", {})
    v = next((s for s in data["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    info = {
        "path": str(path.resolve()),
        "duration": float(fmt.get("duration") or 0),
        "size_bytes": int(fmt.get("size") or 0),
        "bitrate": int(fmt.get("bit_rate") or 0),
        "format": fmt.get("format_name"),
        "has_video": v is not None,
        "has_audio": a is not None,
    }
    if v:
        w, h = int(v["width"]), int(v["height"])
        rot = 0
        for sd in v.get("side_data_list", []):
            if "rotation" in sd:
                rot = int(float(sd["rotation"]))
        rot = rot or int(v.get("tags", {}).get("rotate", 0))
        if abs(rot) % 180 == 90:
            w, h = h, w
        r, avg = _rate(v.get("r_frame_rate")), _rate(v.get("avg_frame_rate"))
        info.update(
            width=w,
            height=h,
            rotation=rot,
            fps=round(avg or r, 3),
            vfr=bool(r and avg and abs(r - avg) / r > 0.01),
            vcodec=v.get("codec_name"),
            pix_fmt=v.get("pix_fmt"),
        )
    if a:
        info.update(acodec=a.get("codec_name"), sample_rate=int(a.get("sample_rate") or 0), channels=a.get("channels"))
    return info


def edits_dir(source) -> Path:
    source = Path(source).resolve()
    d = source.parent / "edits" / source.stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def guard_output(out: Path, sources) -> Path:
    out = Path(out).resolve()
    for s in sources:
        if out == Path(s).resolve():
            die(f"refusing to overwrite source file {s}")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


TC = re.compile(r"^(?:(\d+):)?(?:(\d+):)?(\d+(?:[.,]\d+)?)$")


def parse_time(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    m = TC.match(str(v).strip())
    if not m:
        raise ValueError(f"bad time: {v!r}")
    a, b, c = m.groups()
    sec = float(c.replace(",", "."))
    if b is not None:
        return int(a) * 3600 + int(b) * 60 + sec
    if a is not None:
        return int(a) * 60 + sec
    return sec


def fmt_time(t: float, sep: str = ".") -> str:
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def fmt_dur(t: float) -> str:
    t = int(round(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def merge(ranges, gap: float = 0.0) -> list:
    out = []
    for s, e in sorted((float(s), float(e)) for s, e in ranges if e > s):
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [tuple(r) for r in out]


def subtract(base: tuple, cuts) -> list:
    pieces = [base]
    for cs, ce in merge(cuts):
        nxt = []
        for s, e in pieces:
            if ce <= s or cs >= e:
                nxt.append((s, e))
                continue
            if cs > s:
                nxt.append((s, cs))
            if ce < e:
                nxt.append((ce, e))
        pieces = nxt
    return pieces


def snap(t: float, fps: float) -> float:
    return round(t * fps) / fps if fps else t


def load_words(path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "segments" not in data:
        die(f"{path} is not a takecut words JSON")
    return data


def all_words(tr: dict) -> list:
    return [w for seg in tr["segments"] for w in seg["words"]]


def join_words(words, lang: str | None = None) -> str:
    if lang in NO_SPACE_LANGS:
        return "".join(w["w"].strip() for w in words)
    return " ".join(w["w"].strip() for w in words if w["w"].strip())


def norm_token(s: str) -> str:
    return re.sub(r"[^\w']+", "", s.lower()).strip("'")


def segment_words(words, lang=None, max_gap: float = 0.5, max_words: int = 30) -> list:
    segs, cur = [], []
    for w in words:
        if cur:
            gap = w["s"] - cur[-1]["e"]
            if cur[-1]["w"].strip().endswith(SENTENCE_END) or gap >= max_gap or len(cur) >= max_words:
                segs.append(cur)
                cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    return [
        {"id": f"s{i:04d}", "start": ws[0]["s"], "end": ws[-1]["e"], "text": join_words(ws, lang), "words": ws}
        for i, ws in enumerate(segs, 1)
    ]


def transcript_text(tr: dict) -> str:
    head = f"# source: {Path(tr.get('source', '?')).name}  duration {fmt_time(tr.get('duration', 0))}  language {tr.get('language', '?')}  segments {len(tr['segments'])}\n"
    head += "# [id start-end] text   (times are source seconds as HH:MM:SS.mmm)\n"
    return head + "".join(f"[{s['id']} {fmt_time(s['start'])}-{fmt_time(s['end'])}] {s['text']}\n" for s in tr["segments"])


def write_transcript(tr: dict, json_path: Path) -> Path:
    json_path = Path(json_path)
    json_path.write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = json_path.with_name(json_path.name.replace(".words.json", ".txt"))
    txt.write_text(transcript_text(tr), encoding="utf-8")
    return txt


def seg_span(tr: dict, ref: str) -> tuple:
    ids = [s["id"] for s in tr["segments"]]
    a, _, b = ref.partition("-")
    b = b or a
    if a not in ids or b not in ids:
        die(f"unknown segment reference {ref!r}")
    i, j = ids.index(a), ids.index(b)
    if j < i:
        die(f"segment range {ref!r} is reversed")
    return tr["segments"][i]["start"], tr["segments"][j]["end"]


def similar(a, b) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


EDL_DEFAULTS = {"pad": 0.08, "fade": 0.015, "min_keep": 0.1, "loudnorm": False, "lufs": -16.0}


def load_edl(path) -> dict:
    path = Path(path).resolve()
    edl = json.loads(path.read_text(encoding="utf-8"))
    edl["_dir"] = str(path.parent)
    edl.setdefault("name", path.name.split(".")[0])
    return edl


def _abs(base: str, p: str) -> str:
    q = Path(p)
    return str(q if q.is_absolute() else (Path(base) / q).resolve())


def resolve_edl(edl: dict, probes: dict | None = None) -> list:
    """Return ordered pieces [(src_key, start, end)] in source seconds, frame-snapped."""
    base = edl.get("_dir", ".")
    sources = {k: _abs(base, v) for k, v in edl["sources"].items()}
    if not sources:
        die("EDL has no sources")
    first = next(iter(sources))
    trs = {k: load_words(_abs(base, v)) for k, v in edl.get("transcripts", {}).items()}
    probes = probes or {k: probe(v) for k, v in sources.items()}
    opt = {**EDL_DEFAULTS, **edl}

    def span(item, pad):
        src = item.get("src", first)
        if src not in sources:
            die(f"unknown source key {src!r}")
        if "segs" in item:
            if src not in trs:
                die(f"segment refs need transcripts.{src} in the EDL")
            s, e = seg_span(trs[src], item["segs"])
            s, e = s - pad, e + pad
        else:
            s, e = parse_time(item.get("start", 0)), parse_time(item["end"]) if "end" in item else probes[src]["duration"]
        dur = probes[src]["duration"]
        return src, max(0.0, s), min(dur, e)

    clips = [span(c, opt["pad"]) for c in edl.get("clips", [])] or [(k, 0.0, probes[k]["duration"]) for k in sources]
    drops: dict = {}
    for d in edl.get("drop", []):
        src, s, e = span(d, 0.0) if "segs" in d else (d.get("src", first), parse_time(d["start"]), parse_time(d["end"]))
        drops.setdefault(src, []).append((s, e))

    pieces = []
    for src, s, e in clips:
        fps = probes[src].get("fps") or 0
        for ps, pe in subtract((s, e), drops.get(src, [])):
            ps, pe = snap(ps, fps), snap(pe, fps)
            pe = min(pe, probes[src]["duration"])
            if pe - ps < opt["min_keep"]:
                continue
            if pieces and pieces[-1][0] == src and abs(pieces[-1][2] - ps) < 1e-6:
                pieces[-1] = (src, pieces[-1][1], pe)
            else:
                pieces.append((src, ps, pe))
    if not pieces:
        die("EDL resolves to nothing: every clip was dropped")
    return pieces


def remap_words(pieces, trs: dict, lang=None) -> dict:
    out, t, seen = [], 0.0, set()
    for src, s, e in pieces:
        for i, w in enumerate(all_words(trs[src]) if src in trs else []):
            overlap = min(e, w["e"]) - max(s, w["s"])
            if (src, i) not in seen and overlap > 0 and overlap >= min(0.08, (w["e"] - w["s"]) / 2):
                seen.add((src, i))
                out.append({**w, "s": round(t + max(w["s"], s) - s, 3), "e": round(t + min(w["e"], e) - s, 3)})
        t += e - s
    return {"duration": round(t, 3), "language": lang, "segments": segment_words(out, lang)}
