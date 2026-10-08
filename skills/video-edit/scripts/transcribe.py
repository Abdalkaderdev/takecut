# /// script
# requires-python = ">=3.10"
# dependencies = ["faster-whisper>=1.1", "numpy"]
# ///
"""Transcribe a video/audio file with word timestamps.

Local by default (faster-whisper, CUDA if available, else CPU int8). Optional API backends:
--api groq (GROQ_API_KEY) or --api openai (OPENAI_API_KEY).

Writes edits/<name>/transcript.words.json and transcript.txt next to the source.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import NO_SPACE_LANGS, die, edits_dir, ffmpeg, fmt_dur, probe, segment_words, write_transcript  # noqa: E402

FILLER_PROMPTS = {
    "en": "Umm, let me think like, hmm... Okay, here's what I'm, like, thinking. Uh, so, you know, I mean, uh.",
    "de": "Ähm, also, äh, ich meine, ähm... na ja, also.",
    "fr": "Euh, alors, bah, euh... en fait, hein, euh.",
    "es": "Eh, este, o sea, eh... pues, bueno, eh.",
    "it": "Ehm, cioè, eh... allora, tipo, ehm.",
    "pt": "É, tipo, ahn... então, né, hum.",
    "nl": "Eh, uhm, nou, ehm... dus, eh.",
}
LANG_NAMES = {
    "english": "en", "german": "de", "french": "fr", "spanish": "es", "italian": "it", "portuguese": "pt",
    "dutch": "nl", "japanese": "ja", "chinese": "zh", "arabic": "ar", "russian": "ru", "turkish": "tr",
    "korean": "ko", "hindi": "hi", "polish": "pl", "ukrainian": "uk", "swedish": "sv",
}
API = {
    "groq": ("https://api.groq.com/openai/v1/audio/transcriptions", "GROQ_API_KEY", "whisper-large-v3-turbo"),
    "openai": ("https://api.openai.com/v1/audio/transcriptions", "OPENAI_API_KEY", "whisper-1"),
}
GPU_HINT = (
    "GPU libraries (cuBLAS/cuDNN for CUDA 12) were not found. Either install the CUDA 12 toolkit + cuDNN 9, or run:\n"
    '  uv run --with nvidia-cublas-cu12 --with "nvidia-cudnn-cu12>=9,<10" transcribe.py ...'
)


os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def preload_cuda_libs():
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            spec = importlib.util.find_spec(pkg)
        except ModuleNotFoundError:
            continue
        for loc in (spec.submodule_search_locations or []) if spec else []:
            for sub in ("bin", "lib"):
                d = Path(loc) / sub
                if not d.is_dir():
                    continue
                if os.name == "nt":
                    os.add_dll_directory(str(d))
                    os.environ["PATH"] = str(d) + os.pathsep + os.environ["PATH"]
                else:
                    import ctypes

                    for so in sorted(d.glob("lib*.so*")):
                        try:
                            ctypes.CDLL(str(so), mode=ctypes.RTLD_GLOBAL)
                        except OSError:
                            pass


def maybe_fetch_gpu_libs(args):
    """With an NVIDIA GPU but no cuBLAS/cuDNN, re-run once under uv with the pip CUDA wheels (cached after first use)."""
    if args.api or args.device == "cpu" or os.environ.get("TAKECUT_GPU_REEXEC") or not shutil.which("uv"):
        return
    import ctypes.util

    import ctranslate2

    if ctranslate2.get_cuda_device_count() == 0:
        return
    try:
        if importlib.util.find_spec("nvidia.cublas"):
            return
    except ModuleNotFoundError:
        pass
    if ctypes.util.find_library("cublas64_12" if os.name == "nt" else "cublas"):
        return
    print("NVIDIA GPU found; fetching CUDA 12 libraries through uv (about 1 GB once, cached afterwards). Use --device cpu to skip.",
          file=sys.stderr)
    env = {**os.environ, "TAKECUT_GPU_REEXEC": "1"}
    cmd = ["uv", "run", "--quiet", "--with", "nvidia-cublas-cu12", "--with", "nvidia-cudnn-cu12>=9,<10", __file__, *sys.argv[1:]]
    code = subprocess.call(cmd, env=env)
    if code == 0:
        raise SystemExit(0)
    print("GPU run failed (see above); continuing on CPU.", file=sys.stderr)
    args.device = "cpu"


def decode_pcm(src: Path):
    import numpy as np

    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True,
    )
    if p.returncode != 0:
        die(f"ffmpeg could not decode audio:\n{p.stderr.decode(errors='replace')[-2000:]}")
    return np.frombuffer(p.stdout, np.float32)


def local(src: Path, args) -> tuple[list, str, str]:
    preload_cuda_libs()
    import ctranslate2
    from faster_whisper import WhisperModel

    audio = decode_pcm(src)
    devices = [args.device] if args.device != "auto" else (["cuda", "cpu"] if ctranslate2.get_cuda_device_count() > 0 else ["cpu"])
    last = None
    for dev in devices:
        model_name = args.model if args.model != "auto" else ("large-v3-turbo" if dev == "cuda" else "small")
        compute = args.compute_type if args.compute_type != "auto" else ("float16" if dev == "cuda" else "int8")
        try:
            t0 = time.time()
            print(f"loading {model_name} on {dev} ({compute})", file=sys.stderr)
            model = WhisperModel(model_name, device=dev, compute_type=compute)
            lang = args.language
            if not lang:
                lang = model.detect_language(audio)[0]
            prompt = args.prompt if args.prompt is not None else (None if args.no_filler_prompt else FILLER_PROMPTS.get(lang))
            segments, _ = model.transcribe(
                audio,
                language=lang,
                word_timestamps=True,
                vad_filter=not args.no_vad,
                initial_prompt=prompt,
                beam_size=args.beam_size,
            )
            words = []
            for seg in segments:
                for w in seg.words or []:
                    words.append({"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 3)})
                print(f"\r  {fmt_dur(seg.end)} / {fmt_dur(len(audio) / 16000)}", end="", file=sys.stderr)
            print(f"\n  done in {time.time() - t0:.1f}s", file=sys.stderr)
            return words, lang, f"faster-whisper:{model_name}@{dev}"
        except Exception as exc:
            last = exc
            msg = str(exc).lower()
            if dev == "cuda" and len(devices) > 1:
                hint = GPU_HINT if any(k in msg for k in ("cublas", "cudnn", "dll", ".so")) else ""
                print(f"\nCUDA failed ({exc}); falling back to CPU.\n{hint}", file=sys.stderr)
                continue
            raise
    raise last


def multipart(fields: dict, file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for k, vals in fields.items():
        for v in vals if isinstance(vals, list) else [vals]:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
        f"Content-Type: audio/ogg\r\n\r\n".encode()
    )
    parts.append(file_path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def parse_api_words(data: dict, offset: float) -> list:
    raw = data.get("words") or [w for s in data.get("segments", []) for w in s.get("words", [])]
    return [{"w": " " + w["word"].strip(), "s": round(w["start"] + offset, 3), "e": round(w["end"] + offset, 3)} for w in raw]


def api(src: Path, args, duration: float) -> tuple[list, str, str]:
    url, env, default_model = API[args.api]
    key = os.environ.get(env)
    if not key:
        die(f"--api {args.api} needs {env} in the environment")
    model = args.model if args.model != "auto" else default_model
    chunk = 1200.0
    words, lang = [], args.language
    with tempfile.TemporaryDirectory() as tmp:
        for i, off in enumerate(range(0, int(duration) + 1, int(chunk))):
            if off >= duration:
                break
            part = Path(tmp) / f"chunk{i}.ogg"
            ffmpeg(["-ss", off, "-t", chunk, "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k", part])
            fields = {
                "model": model,
                "response_format": "verbose_json",
                "timestamp_granularities[]": ["word", "segment"],
                "temperature": "0",
            }
            if lang:
                fields["language"] = lang
            prompt = args.prompt if args.prompt is not None else (None if args.no_filler_prompt else FILLER_PROMPTS.get(lang or "en"))
            if prompt:
                fields["prompt"] = prompt
            body, ctype = multipart(fields, "file", part)
            req = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": ctype})
            print(f"  uploading chunk {i + 1} ({part.stat().st_size / 1e6:.1f} MB) to {args.api}", file=sys.stderr)
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    data = json.load(r)
            except urllib.error.HTTPError as e:
                die(f"{args.api} API error {e.code}: {e.read().decode(errors='replace')[:500]}")
            words += parse_api_words(data, off)
            lang = lang or LANG_NAMES.get(str(data.get("language", "")).lower(), data.get("language"))
    return words, lang, f"{args.api}:{model}"


def glue_pieces(words: list, lang) -> list:
    """Whisper sometimes splits a word ("real" + "-life"); merge pieces without a leading space."""
    if lang in NO_SPACE_LANGS:
        return words
    out = []
    for w in words:
        if out and not w["w"].startswith(" "):
            prev = out[-1]
            out[-1] = {**prev, "w": prev["w"] + w["w"], "e": w["e"], **({"p": min(prev["p"], w["p"])} if "p" in prev and "p" in w else {})}
        else:
            out.append(dict(w))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--model", default="auto", help="tiny|base|small|medium|large-v3|large-v3-turbo (default: turbo on GPU, small on CPU)")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--compute-type", default="auto")
    ap.add_argument("--language", help="ISO code, e.g. en, de. Auto-detected if omitted")
    ap.add_argument("--api", choices=sorted(API), help="use a hosted Whisper API instead of the local model")
    ap.add_argument("--prompt", help="custom initial prompt (names, jargon)")
    ap.add_argument("--no-filler-prompt", action="store_true", help="don't bias Whisper toward writing um/uh")
    ap.add_argument("--no-vad", action="store_true")
    ap.add_argument("--beam-size", type=int, default=5)
    ap.add_argument("--out", help="output directory (default: edits/<name>/ next to the source)")
    args = ap.parse_args()

    src = Path(args.input).resolve()
    info = probe(src)
    if not info["has_audio"]:
        die("input has no audio stream")
    out = Path(args.out) if args.out else edits_dir(src)
    out.mkdir(parents=True, exist_ok=True)
    maybe_fetch_gpu_libs(args)
    words, lang, engine = api(src, args, info["duration"]) if args.api else local(src, args)
    words = glue_pieces([w for w in words if w["w"].strip()], lang)
    tr = {
        "source": info["path"],
        "duration": info["duration"],
        "language": lang,
        "engine": engine,
        "segments": segment_words(words, lang),
    }
    jp = out / "transcript.words.json"
    txt = write_transcript(tr, jp)
    print(json.dumps({"words": len(words), "segments": len(tr["segments"]), "language": lang, "engine": engine,
                      "words_json": str(jp), "transcript": str(txt)}, indent=1))


if __name__ == "__main__":
    main()
