from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = [
    "Hi, I'm going to show you how to edit video by editing text.",
    1.6,
    "Um, the idea is simple.",
    0.4,
    "You record yourself talking, and then, uh, the agent reads the transcript.",
    2.2,
    "It finds the boring parts.",
    0.3,
    "It finds the silences, the fillers, and the takes you messed up.",
    1.8,
    "Then it cuts them out.",
    0.3,
    "Then it cuts them out, frame accurate, with tiny fades so nothing pops.",
    1.5,
    "Um, after that you can make short clips for your phone.",
    2.5,
    "Uh, and every clip gets captions.",
    1.2,
]

LONG_SCRIPT = SCRIPT + [
    "Let me explain why this matters.",
    1.4,
    "Most people spend hours, um, scrubbing through a timeline.",
    0.5,
    "They look for the pauses by eye.",
    2.0,
    "That is slow, and it is boring work.",
    0.4,
    "A transcript turns the whole video into text.",
    0.3,
    "A transcript turns the whole video into text that an agent can read in seconds.",
    1.7,
    "Uh, so the agent decides what to keep.",
    0.6,
    "And a tested script does the cutting, so the result is, um, always in sync.",
    2.4,
    "You check a quick preview, and if it looks right, you render the final file.",
    1.1,
    "Uh, that's it. Thanks for watching.",
    1.0,
]


def espeak() -> str:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    win = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "eSpeak NG" / "espeak-ng.exe"
    if not exe and win.exists():
        exe = str(win)
    if not exe:
        raise RuntimeError("espeak-ng not found")
    return exe


PRETTY = ("gradients=s={size}:rate={fps}:c0=0x0b1020:c1=0x23305e:c2=0x3b1e54:nb_colors=3:speed=0.004:type=linear,"
          "drawtext=font=Consolas:text='SOURCE %{{pts\\:hms}}':x=40:y=40:fontsize=28:fontcolor=white@0.7")


def make_clip(out: Path, script=SCRIPT, size="1280x720", fps=30, pretty=False) -> Path:
    out = Path(out)
    work = out.parent / (out.stem + "_parts")
    work.mkdir(parents=True, exist_ok=True)
    inputs, labels = [], []
    for i, item in enumerate(script):
        if isinstance(item, str):
            wav = work / f"{i:03d}.wav"
            subprocess.run([espeak(), "-v", "en-us", "-s", "155", "-w", str(wav), item], check=True)
            inputs += ["-i", str(wav)]
        else:
            inputs += ["-f", "lavfi", "-t", str(item), "-i", "anullsrc=r=22050:cl=mono"]
        labels.append(f"[{i}:a]")
    n = len(script)
    graph = f"{''.join(labels)}concat=n={n}:v=0:a=1,aresample=48000,pan=stereo|c0=c0|c1=c0[a]"
    audio = work / "audio.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[a]", str(audio)], check=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         PRETTY.format(size=size, fps=fps) if pretty else f"testsrc2=size={size}:rate={fps}",
         "-i", str(audio), "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", str(out)],
        check=True,
    )
    shutil.rmtree(work, ignore_errors=True)
    return out


if __name__ == "__main__":
    make_clip(Path(sys.argv[1]), LONG_SCRIPT if "--long" in sys.argv else SCRIPT, pretty="--pretty" in sys.argv)
