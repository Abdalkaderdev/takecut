# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python-headless>=4.8", "numpy"]
# ///
"""Reframe a landscape video to vertical (default 1080x1920) with a smoothed face-tracking crop.

Faces: OpenCV YuNet (downloaded once, ~230 KB, cached) -> Haar cascade -> fixed position (--x).
The crop path is median-filtered, held inside a dead zone, speed-limited and eased, then applied
per frame through ffmpeg sendcmd. Optional ASS subtitles are burned in the same pass.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "video-edit" / "scripts"))
try:
    from core import die, ffmpeg, guard_output, probe
except ImportError:
    raise SystemExit("error: video-shorts needs the video-edit skill installed next to it (skills/video-edit/scripts/core.py)")

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
CACHE = Path(os.environ.get("TAKECUT_CACHE", Path.home() / ".cache" / "takecut"))


class Detector:
    def __init__(self, width: int, height: int):
        import cv2

        self.cv2 = cv2
        self.kind = "haar"
        model = CACHE / "face_detection_yunet_2023mar.onnx"
        try:
            if not model.exists():
                CACHE.mkdir(parents=True, exist_ok=True)
                urllib.request.urlretrieve(YUNET_URL, model)
            self.net = cv2.FaceDetectorYN.create(str(model), "", (width, height), 0.7)
            self.kind = "yunet"
        except Exception as exc:
            print(f"YuNet unavailable ({exc}); using Haar cascade", file=sys.stderr)
            self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def __call__(self, frame) -> list:
        if self.kind == "yunet":
            _, faces = self.net.detect(frame)
            return [(f[0] + f[2] / 2, f[1] + f[3] / 2, f[2], f[3], float(f[-1])) for f in (faces if faces is not None else [])]
        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
        found = self.haar.detectMultiScale(gray, 1.1, 6, minSize=(frame.shape[0] // 12,) * 2)
        return [(x + w / 2, y + h / 2, w, h, 1.0) for x, y, w, h in found]


def track(path: Path, sample_fps: float = 6.0, det_width: int = 640):
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    W = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    step = max(1, int(round(fps / sample_fps)))
    scale = det_width / W
    det = None
    times, xs = [], []
    prev = None
    i = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            small = cv2.resize(frame, (det_width, int(round(frame.shape[0] * scale))))
            if det is None:
                det = Detector(small.shape[1], small.shape[0])
            faces = det(small)
            x = np.nan
            if faces:
                def rank(f, prev=prev):
                    area = f[2] * f[3] * f[4]
                    return area / (1 + (abs(f[0] - prev) / det_width * 4 if prev is not None else 0))
                best = max(faces, key=rank)
                x = best[0] / det_width
                prev = best[0]
            times.append(i / fps)
            xs.append(x)
        i += 1
    cap.release()
    return np.array(times), np.array(xs, dtype=float), (det.kind if det else "none"), fps, max(n, i)


def smooth_path(times, xs, crop_frac: float, deadzone: float = 0.06, max_speed: float = 0.35, fallback: float = 0.5):
    import numpy as np

    if len(xs) == 0 or np.all(np.isnan(xs)):
        return np.full(len(times), fallback), 0.0
    found = ~np.isnan(xs)
    coverage = float(found.mean())
    xs = np.interp(times, times[found], xs[found])
    k = 5
    pad = np.pad(xs, k // 2, mode="edge")
    med = np.array([np.median(pad[j:j + k]) for j in range(len(xs))])
    cam = np.empty_like(med)
    cam[0] = med[0]
    for j in range(1, len(med)):
        dt = times[j] - times[j - 1]
        err = med[j] - cam[j - 1]
        if abs(err) <= deadzone:
            cam[j] = cam[j - 1]
        else:
            move = (abs(err) - deadzone) * 0.5
            cam[j] = cam[j - 1] + np.sign(err) * min(move, max_speed * dt)
    w = max(1, int(round(0.5 / max(times[1] - times[0], 1e-6)))) if len(times) > 1 else 1
    kernel = np.ones(w) / w
    cam = np.convolve(np.pad(cam, w // 2, mode="edge"), kernel, mode="valid")[: len(med)]
    half = crop_frac / 2
    return np.clip(cam, half, 1 - half), coverage


def reframe(src: Path, out: Path, size=(1080, 1920), ass: Path | None = None, x: float | None = None,
            crf: int = 18, preset: str = "medium") -> dict:
    import numpy as np

    info = probe(src)
    W, H = info["width"], info["height"]
    ow, oh = size
    out = guard_output(out, [src])
    target_ratio = ow / oh
    crop_w = min(W, int(round(H * target_ratio / 2)) * 2)
    crop_h = H if crop_w < W else min(H, int(round(W / target_ratio / 2)) * 2)
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        filters = []
        method, coverage = "static", None
        if crop_w < W:
            if x is None:
                times, xs, method, fps, nframes = track(src)
                path, coverage = smooth_path(times, xs, crop_w / W)
                if coverage == 0:
                    method = "center (no faces found)"
            else:
                fps, nframes = info.get("fps") or 30, int(info["duration"] * (info.get("fps") or 30))
                times, path = np.array([0.0]), np.array([x])
                path = np.clip(path, crop_w / W / 2, 1 - crop_w / W / 2)
            frame_t = np.arange(nframes) / fps
            px = np.interp(frame_t, times, path) * W - crop_w / 2
            px = np.clip(np.round(px), 0, W - crop_w).astype(int)
            lines, last = [], None
            for t, v in zip(frame_t, px):
                if v != last:
                    lines.append(f"{t:.4f} crop x {v};")
                    last = v
            (tmpd / "crop.cmd").write_text("\n".join(lines) + "\n", encoding="utf-8")
            filters.append(f"sendcmd=f=crop.cmd,crop={crop_w}:{crop_h}:{px[0]}:0")
        elif crop_h < H:
            filters.append(f"crop={crop_w}:{crop_h}:0:(ih-{crop_h})/2")
        filters.append(f"scale={ow}:{oh}:flags=lanczos,setsar=1,format=yuv420p")
        if ass:
            shutil.copy(ass, tmpd / "subs.ass")
            filters.append("ass=subs.ass")
        audio = ["-c:a", "aac", "-b:a", "192k"] if info["has_audio"] else ["-an"]
        ffmpeg(["-i", Path(src).resolve(), "-vf", ",".join(filters), "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                *audio, "-movflags", "+faststart", out], cwd=tmpd)
    return {"output": str(out), "tracking": method, "face_coverage": None if coverage is None else round(coverage, 2),
            "crop": f"{crop_w}x{crop_h} of {W}x{H}", "size": f"{ow}x{oh}"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--out")
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--ass", help="ASS subtitles to burn (make them with captions.py ass --size 1080x1920)")
    ap.add_argument("--x", type=float, help="fixed horizontal centre 0..1 instead of face tracking (e.g. 0.3 = speaker on the left)")
    ap.add_argument("--crf", type=int, default=18)
    args = ap.parse_args()
    src = Path(args.input)
    w, h = map(int, args.size.lower().split("x"))
    out = Path(args.out) if args.out else src.with_name(f"{src.stem}.vertical.mp4")
    if args.x is not None and not 0 <= args.x <= 1:
        die("--x must be between 0 and 1")
    print(json.dumps(reframe(src, out, (w, h), Path(args.ass) if args.ass else None, args.x, args.crf), indent=1))


if __name__ == "__main__":
    main()
