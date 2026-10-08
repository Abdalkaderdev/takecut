# /// script
# requires-python = ">=3.10"
# ///
"""Captions from word timestamps: SRT, VTT, styled ASS, burn-in, and a timing-safe translation flow.

  captions.py srt   WORDS.json [-o out.srt]
  captions.py vtt   WORDS.json [-o out.vtt]
  captions.py ass   WORDS.json|SUBS.srt --preset clean|boxed|highlight|pop|minimal [--video V | --size 1080x1920]
  captions.py burn  VIDEO SUBS.ass|SUBS.srt [-o out.mp4]
  captions.py translate-prep  SUBS.srt            -> SUBS.lines.json  (id -> text, translate the values)
  captions.py translate-apply SUBS.srt LINES.json [-o SUBS.<lang>.srt]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "video-edit" / "scripts"))
try:
    from core import NO_SPACE_LANGS, SENTENCE_END, all_words, die, ffmpeg, fmt_time, guard_output, load_words, parse_time, probe
except ImportError:
    raise SystemExit("error: video-captions needs the video-edit skill installed next to it (skills/video-edit/scripts/core.py)")

RULES = {"max_chars": 42, "max_lines": 2, "max_cps": 17.0, "min_dur": 0.83, "max_dur": 7.0, "gap": 0.083, "pause": 0.6}


def _join(parts, lang):
    return ("" if lang in NO_SPACE_LANGS else " ").join(p for p in parts if p)


def wrap(tokens: list, max_chars: int, max_lines: int, lang=None) -> list:
    text = _join(tokens, lang)
    n = len(tokens)
    if len(text) <= max_chars or n < 2 or max_lines < 2:
        return [list(range(n))]
    best, best_score = None, None
    for k in range(1, n):
        a, b = _join(tokens[:k], lang), _join(tokens[k:], lang)
        over = max(0, len(a) - max_chars) + max(0, len(b) - max_chars)
        score = (over, abs(len(a) - len(b)) - (6 if tokens[k - 1].endswith((",", ";", ":", ".", "?", "!")) else 0))
        if best_score is None or score < best_score:
            best, best_score = k, score
    if max_lines > 2 and len(_join(tokens[best:], lang)) > max_chars:
        rest = wrap(tokens[best:], max_chars, max_lines - 1, lang)
        return [list(range(best))] + [[i + best for i in line] for line in rest]
    return [list(range(best)), list(range(best, n))]


def build_cues(words: list, lang=None, **rules) -> list:
    r = {**RULES, **rules}
    limit = r["max_chars"] * r["max_lines"]
    groups, cur = [], []
    for w in words:
        if not w["w"].strip():
            continue
        if cur:
            text = _join([x["w"].strip() for x in cur + [w]], lang)
            prev = cur[-1]["w"].strip()
            if (len(text) > limit or w["e"] - cur[0]["s"] > r["max_dur"] or w["s"] - cur[-1]["e"] > r["pause"]
                    or (prev.endswith(SENTENCE_END) and len(_join([x["w"].strip() for x in cur], lang)) >= r["max_chars"] / 3)):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    cues = []
    for i, g in enumerate(groups):
        toks = [w["w"].strip() for w in g]
        if toks[0][:1].islower() and (i == 0 or groups[i - 1][-1]["w"].strip().endswith(SENTENCE_END)):
            toks[0] = toks[0][0].upper() + toks[0][1:]
        lines = wrap(toks, r["max_chars"], r["max_lines"], lang)
        text = _join(toks, lang)
        start, end = g[0]["s"], g[-1]["e"]
        end = max(end, start + r["min_dur"], start + len(text) / r["max_cps"])
        if i + 1 < len(groups):
            end = min(end, groups[i + 1][0]["s"] - r["gap"])
        end = max(end, g[-1]["e"], start + 0.2)
        cues.append({"start": round(start, 3), "end": round(end, 3), "words": g, "lines": [[toks[j] for j in ln] for ln in lines], "lang": lang})
    return cues


def cue_text(c) -> str:
    return "\n".join(_join(ln, c.get("lang")) for ln in c["lines"])


def to_srt(cues) -> str:
    return "".join(f"{i}\n{fmt_time(c['start'], ',')} --> {fmt_time(c['end'], ',')}\n{cue_text(c)}\n\n" for i, c in enumerate(cues, 1))


def to_vtt(cues) -> str:
    return "WEBVTT\n\n" + "".join(f"{fmt_time(c['start'])} --> {fmt_time(c['end'])}\n{cue_text(c)}\n\n" for c in cues)


def parse_srt(text: str, lang=None) -> list:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.strip().split("\n")
        tl = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if tl is None:
            continue
        a, b = [x.strip().split(" ")[0] for x in lines[tl].split("-->")]
        body = lines[tl + 1:]
        cues.append({"id": lines[0].strip() if tl else str(len(cues) + 1), "start": parse_time(a), "end": parse_time(b),
                     "lines": [ln.split() if lang not in NO_SPACE_LANGS else [ln] for ln in body], "lang": lang})
    return cues


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


PRESETS = {
    "clean": dict(size=0.055, bold=1, color="FFFFFF", outline_color="000000", outline=0.0035, shadow=0.0012, border=1, align=2, margin=0.07, upper=False, max_chars=42),
    "boxed": dict(size=0.05, bold=0, color="FFFFFF", outline_color="000000", outline=0.006, shadow=0, border=3, align=2, margin=0.07, upper=False, box_alpha=0x60, max_chars=42),
    "minimal": dict(size=0.045, bold=0, color="F2F2F2", outline_color="202020", outline=0.002, shadow=0, border=1, align=2, margin=0.05, upper=False, max_chars=48),
    "highlight": dict(size=0.06, bold=1, color="FFFFFF", outline_color="000000", outline=0.004, shadow=0.0015, border=1, align=2, margin=0.12, upper=False, highlight="FFD400", max_chars=28),
    "pop": dict(size=0.085, bold=1, color="FFFFFF", outline_color="000000", outline=0.006, shadow=0.002, border=1, align=2, margin=0.30, upper=True, highlight="2BE36B", max_chars=16, max_lines=1),
}


def ass_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def to_ass(cues, w: int, h: int, preset: str = "clean", font: str = "Arial") -> str:
    p = PRESETS[preset]
    base = h if w >= h else w * 1.25
    size = round(p["size"] * base)
    outline = round(p["outline"] * base, 1)
    shadow = round(p["shadow"] * base, 1)
    back = ass_color("000000", p.get("box_alpha", 0x80))
    oc = back if p["border"] == 3 else ass_color(p["outline_color"])
    style = (f"Style: Default,{font},{size},{ass_color(p['color'])},{ass_color(p.get('highlight', p['color']))},{oc},{back},"
             f"{-1 if p['bold'] else 0},0,0,0,100,100,0,0,{p['border']},{outline},{shadow},{p['align']},"
             f"{round(w * 0.06)},{round(w * 0.06)},{round(h * p['margin'])},1")
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\nPlayResY: {h}\nYCbCr Matrix: TV.709\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style}\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def t(x):
        cs = int(round(max(x, 0) * 100))
        hh, cs = divmod(cs, 360000)
        mm, cs = divmod(cs, 6000)
        ss, cs = divmod(cs, 100)
        return f"{hh}:{mm:02d}:{ss:02d}.{cs:02d}"

    def fmt(tok):
        tok = ass_escape(tok)
        return tok.upper() if p["upper"] else tok

    events = []
    for c in cues:
        lang = c.get("lang")
        sep = "" if lang in NO_SPACE_LANGS else " "
        hl = p.get("highlight")
        words = c.get("words")
        if not hl or not words:
            text = "\\N".join(sep.join(fmt(x) for x in ln) for ln in c["lines"])
            events.append(f"Dialogue: 0,{t(c['start'])},{t(c['end'])},Default,,0,0,0,,{text}")
            continue
        flat = [x for ln in c["lines"] for x in ln]
        breaks = set()
        n = 0
        for ln in c["lines"][:-1]:
            n += len(ln)
            breaks.add(n)
        for i in range(len(flat)):
            s = c["start"] if i == 0 else words[i]["s"]
            e = words[i + 1]["s"] if i + 1 < len(flat) else c["end"]
            if e <= s:
                continue
            parts = []
            for j, tok in enumerate(flat):
                if j in breaks:
                    parts.append("\\N")
                elif j:
                    parts.append(sep)
                if j == i:
                    pop = "\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)" if preset == "pop" else ""
                    parts.append(f"{{\\c&H{ass_color(hl)[4:]}&{pop}}}{fmt(tok)}{{\\r}}")
                else:
                    parts.append(fmt(tok))
            events.append(f"Dialogue: 0,{t(s)},{t(e)},Default,,0,0,0,,{''.join(parts)}")
    return head + "\n".join(events) + "\n"


def cues_for(path: Path, preset: str | None = None, **rules) -> list:
    p = PRESETS.get(preset or "clean", PRESETS["clean"])
    rules.setdefault("max_chars", p.get("max_chars", 42))
    rules.setdefault("max_lines", p.get("max_lines", 2))
    if path.suffix.lower() == ".srt":
        return parse_srt(path.read_text(encoding="utf-8-sig"))
    tr = load_words(path)
    return build_cues(all_words(tr), tr.get("language"), **rules)


def burn(video: Path, subs: Path, out: Path, crf: int = 18, fonts_dir: str | None = None) -> Path:
    out = guard_output(out, [video])
    with tempfile.TemporaryDirectory() as tmp:
        if subs.suffix.lower() == ".srt":
            info = probe(video)
            local = Path(tmp) / "subs.ass"
            local.write_text(to_ass(parse_srt(subs.read_text(encoding="utf-8-sig")), info["width"], info["height"]), encoding="utf-8")
        else:
            local = Path(tmp) / "subs.ass"
            shutil.copy(subs, local)
        vf = "ass=subs.ass" + (f":fontsdir={Path(fonts_dir).resolve().as_posix().replace(':', chr(92) + ':')}" if fonts_dir else "")
        ffmpeg(["-i", video.resolve(), "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out], cwd=tmp)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("srt", "vtt", "ass"):
        s = sub.add_parser(name)
        s.add_argument("input")
        s.add_argument("-o", "--out")
        s.add_argument("--max-chars", type=int)
        s.add_argument("--max-lines", type=int)
        s.add_argument("--max-cps", type=float, default=RULES["max_cps"])
        s.add_argument("--min-dur", type=float, default=RULES["min_dur"])
        s.add_argument("--max-dur", type=float, default=RULES["max_dur"])
        if name == "ass":
            s.add_argument("--preset", default="clean", choices=sorted(PRESETS))
            s.add_argument("--video", help="read output size from this video")
            s.add_argument("--size", help="WxH, e.g. 1080x1920")
            s.add_argument("--font", default="Arial")
    b = sub.add_parser("burn")
    b.add_argument("video")
    b.add_argument("subs")
    b.add_argument("-o", "--out")
    b.add_argument("--crf", type=int, default=18)
    b.add_argument("--fonts-dir")
    tp = sub.add_parser("translate-prep")
    tp.add_argument("srt")
    ta = sub.add_parser("translate-apply")
    ta.add_argument("srt")
    ta.add_argument("lines")
    ta.add_argument("-o", "--out")
    ta.add_argument("--max-chars", type=int, default=42)
    ta.add_argument("--lang", help="target language code (enables no-space wrapping for zh/ja/th)")
    args = ap.parse_args()

    if args.cmd in ("srt", "vtt", "ass"):
        src = Path(args.input)
        rules = {k: v for k, v in dict(max_chars=args.max_chars, max_lines=args.max_lines, max_cps=args.max_cps,
                                        min_dur=args.min_dur, max_dur=args.max_dur).items() if v is not None}
        cues = cues_for(src, getattr(args, "preset", None), **rules)
        stem = src.name.replace(".words.json", "").replace(".srt", "")
        if args.cmd == "ass":
            if args.size:
                w, h = map(int, args.size.lower().split("x"))
            elif args.video:
                info = probe(args.video)
                w, h = info["width"], info["height"]
            else:
                die("ass needs --video or --size")
            text = to_ass(cues, w, h, args.preset, args.font)
            out = Path(args.out or src.with_name(f"{stem}.{args.preset}.ass"))
        else:
            text = to_srt(cues) if args.cmd == "srt" else to_vtt(cues)
            out = Path(args.out or src.with_name(f"{stem}.{args.cmd}"))
        out.write_text(text, encoding="utf-8")
        print(json.dumps({"output": str(out.resolve()), "cues": len(cues)}))
    elif args.cmd == "burn":
        v = Path(args.video)
        out = Path(args.out) if args.out else v.with_name(f"{v.stem}.captioned.mp4")
        print(json.dumps({"output": str(burn(v, Path(args.subs), out, args.crf, args.fonts_dir))}))
    elif args.cmd == "translate-prep":
        srt = Path(args.srt)
        cues = parse_srt(srt.read_text(encoding="utf-8-sig"))
        out = srt.with_suffix(".lines.json")
        out.write_text(json.dumps({c["id"]: " ".join(" ".join(ln) for ln in c["lines"]) for c in cues}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"output": str(out.resolve()), "cues": len(cues),
                          "next": "copy it, translate every value (keep the keys), then run translate-apply"}))
    else:
        srt = Path(args.srt)
        cues = parse_srt(srt.read_text(encoding="utf-8-sig"))
        lines = json.loads(Path(args.lines).read_text(encoding="utf-8"))
        missing = [c["id"] for c in cues if c["id"] not in lines]
        extra = set(lines) - {c["id"] for c in cues}
        if missing or extra:
            die(f"translation keys don't match the SRT. missing: {missing[:10]} extra: {sorted(extra)[:10]}")
        for c in cues:
            toks = list(lines[c["id"]]) if args.lang in NO_SPACE_LANGS else lines[c["id"]].split()
            c["lang"] = args.lang
            c["lines"] = [[toks[j] for j in ln] for ln in wrap(toks, args.max_chars, 2, args.lang)]
        out = Path(args.out or srt.with_name(srt.stem + f".{args.lang or 'translated'}.srt"))
        out.write_text(to_srt(cues), encoding="utf-8")
        print(json.dumps({"output": str(out.resolve()), "cues": len(cues)}))


if __name__ == "__main__":
    main()
