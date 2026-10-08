# ffmpeg recipes

Every `bash` block in this file is executed by `tests/test_recipes.py` against generated fixtures
(`in.mp4`, `a.mp4`, `b.mov`, `cam.mp4`, `logo.png`, `music.mp3`, `list.txt`), so the commands are
known to work with ffmpeg 6+. Script paths (`scripts/...`, `../video-edit/...`) are relative to
the skill folder. Commands use plain argv quoting (double quotes only, no pipes, no
shell variables) so they paste into bash, zsh, PowerShell and cmd alike.

Always: write to a new file, never over the input. Add `-movflags +faststart` for anything played
on the web.

## Contents

1. [Inspect](#inspect)
2. [Trim](#trim)
3. [Concatenate](#concatenate)
4. [Speed change](#speed-change)
5. [Crop, scale, pad](#crop-scale-pad)
6. [Compress](#compress)
7. [Convert and remux](#convert-and-remux)
8. [GIF](#gif)
9. [Extract audio, frames](#extract-audio-frames)
10. [Music under speech](#music-under-speech)
11. [Picture-in-picture](#picture-in-picture)
12. [Watermark](#watermark)
13. [Loudness](#loudness)
14. [Phone footage](#phone-footage)

## Inspect

```bash
ffprobe -v error -show_entries format=duration,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels -of json in.mp4
```

`r_frame_rate` != `avg_frame_rate` usually means variable frame rate. `../video-edit/scripts/probe.py` prints the same with warnings.

## Trim

Frame-accurate (re-encodes). `-ss` before `-i` seeks fast and, when transcoding, still lands on the exact frame:

```bash
ffmpeg -y -ss 00:00:02.500 -i in.mp4 -t 3 -c:v libx264 -crf 18 -preset medium -c:a aac -b:a 192k -movflags +faststart out_trim.mp4
```

Instant but keyframe-bound (`-c copy` can only start on a keyframe, so the start snaps backwards
and players may show a frozen first second). Use for rough chops only:

```bash
ffmpeg -y -ss 2 -i in.mp4 -t 3 -c copy -avoid_negative_ts make_zero out_trim_copy.mp4
```

Gotchas: `-t` is a duration, `-to` an end time. `-to` after `-ss` placed before `-i` is relative to
the seek point in older builds; prefer `-t`. For many cuts with fades, use an EDL and
`../video-edit/scripts/render.py` instead of chaining trims.

## Concatenate

Same codec, resolution and frame rate (e.g. clips from one camera): concat demuxer, no re-encode.
`list.txt` contains lines like `file 'a.mp4'`:

```bash
ffmpeg -y -f concat -safe 0 -i list.txt -c copy out_concat_copy.mp4
```

Mixed formats, sizes or frame rates: concat filter with every input normalized first. Inputs with
no audio need a silent track (`-f lavfi -t <dur> -i anullsrc=r=48000:cl=stereo`).

```bash
ffmpeg -y -i a.mp4 -i b.mov -filter_complex "[0:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v0];[1:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v1];[0:a]aresample=48000,aformat=channel_layouts=stereo[a0];[1:a]aresample=48000,aformat=channel_layouts=stereo[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" -map "[v]" -map "[a]" -c:v libx264 -crf 18 -c:a aac -movflags +faststart out_concat.mp4
```

For more than a few files, write an EDL with one clip per source and run `render.py`; it does the
same normalization, adds fades and handles silent inputs.

## Speed change

`setpts` changes video speed, `atempo` changes audio speed without changing pitch (ffmpeg 5+
accepts 0.5 to 100 in a single atempo):

```bash
ffmpeg -y -i in.mp4 -filter_complex "[0:v]setpts=PTS/1.5[v];[0:a]atempo=1.5[a]" -map "[v]" -map "[a]" -c:v libx264 -crf 18 -c:a aac out_fast.mp4
```

Slow motion to 0.5x:

```bash
ffmpeg -y -i in.mp4 -filter_complex "[0:v]setpts=PTS*2[v];[0:a]atempo=0.5[a]" -map "[v]" -map "[a]" -c:v libx264 -crf 18 -c:a aac out_slow.mp4
```

Gotchas: `setpts=PTS/1.5` keeps the frame rate metadata, so frames are dropped on output (fine).
For smoother slow motion add `minterpolate=fps=60` (slow). If ffmpeg was built with librubberband,
`rubberband=tempo=1.5` sounds better than atempo on music.

## Crop, scale, pad

Scale to 720p keeping aspect (`-2` keeps the width even, required by yuv420p):

```bash
ffmpeg -y -i in.mp4 -vf "scale=-2:720:flags=lanczos" -c:v libx264 -crf 20 -c:a copy out_720.mp4
```

Center square crop:

```bash
ffmpeg -y -i in.mp4 -vf "crop=ih:ih" -c:v libx264 -crf 20 -c:a copy out_square.mp4
```

Letterbox any input into 1920x1080:

```bash
ffmpeg -y -i in.mp4 -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1" -c:v libx264 -crf 20 -c:a copy out_pad.mp4
```

Vertical 9:16 with a blurred copy behind (no face tracking; for that use `video-shorts`):

```bash
ffmpeg -y -i in.mp4 -filter_complex "[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:2[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1" -c:v libx264 -crf 20 -c:a copy out_vertical_blur.mp4
```

## Compress

Quality-targeted (CRF; 18 visually lossless, 23 default, 28 small). `-preset slow` buys 5-10% size:

```bash
ffmpeg -y -i in.mp4 -c:v libx264 -crf 26 -preset slow -c:a aac -b:a 128k -movflags +faststart out_crf.mp4
```

Size-targeted (two-pass, picks the bitrate and resolution for you):

```bash
uv run scripts/compress.py in.mp4 --mb 2
```

H.265 is ~40% smaller at equal quality but some browsers and older phones won't play it; add
`-tag:v hvc1` so Apple devices recognize it:

```bash
ffmpeg -y -i in.mp4 -c:v libx265 -crf 28 -preset medium -tag:v hvc1 -c:a aac -b:a 128k out_hevc.mp4
```

## Convert and remux

Remux (container change only, instant, no quality loss) when the codecs are already compatible:

```bash
ffmpeg -y -i in.mp4 -c copy out_remux.mkv
```

Anything to a universally playable MP4:

```bash
ffmpeg -y -i b.mov -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart out_convert.mp4
```

WebM (VP9 + Opus) for the web:

```bash
ffmpeg -y -i in.mp4 -c:v libvpx-vp9 -crf 34 -b:v 0 -row-mt 1 -deadline good -cpu-used 4 -c:a libopus -b:a 96k out.webm
```

Gotchas: ProRes/DNxHD/10-bit sources need `-pix_fmt yuv420p` or many players show black or green.

## GIF

Palette in one pass (`palettegen` + `paletteuse`), otherwise ffmpeg's default 256-color palette bands badly:

```bash
ffmpeg -y -ss 1 -t 3 -i in.mp4 -filter_complex "fps=12,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" -loop 0 out.gif
```

Size knobs, in order of impact: duration, width, fps, `bayer_scale` (higher = less noise, more banding).

## Extract audio, frames

```bash
ffmpeg -y -i in.mp4 -vn -c:a copy out_audio.m4a
ffmpeg -y -i in.mp4 -vn -c:a libmp3lame -q:a 2 out_audio.mp3
ffmpeg -y -i in.mp4 -vn -ac 1 -ar 16000 out_speech.wav
ffmpeg -y -ss 2 -i in.mp4 -frames:v 1 -q:v 2 out_frame.jpg
ffmpeg -y -i in.mp4 -vf "fps=1/2,scale=320:-2,tile=3x2" -frames:v 1 out_contact.png
```

`-c:a copy` only works when the target container accepts the codec (AAC -> .m4a, Opus -> .ogg/.webm).

## Music under speech

Sidechain compression: the voice drives a compressor on the music, so music dips while someone
talks and comes back in pauses. The script loops/fades the music to the video length:

```bash
uv run scripts/duck.py in.mp4 music.mp3 --music-db -14
```

Inline version (music must be at least as long as the video, or add `-stream_loop -1` before its `-i`):

```bash
ffmpeg -y -i in.mp4 -stream_loop -1 -i music.mp3 -filter_complex "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=-14dB[m];[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[v][sc];[m][sc]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=350[d];[v][d]amix=inputs=2:duration=first:normalize=0[a]" -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest out_music.mp4
```

Gotchas: `amix` divides levels by the input count unless `normalize=0`. The sidechain input must
be the second pad of `sidechaincompress`.

## Picture-in-picture

Webcam in the bottom-right corner at a quarter width, 24 px margin:

```bash
ffmpeg -y -i in.mp4 -i cam.mp4 -filter_complex "[1:v]scale=iw/4:-2[pip];[0:v][pip]overlay=W-w-24:H-h-24:shortest=1" -map 0:a -c:v libx264 -crf 20 -c:a copy out_pip.mp4
```

Rounded/bordered PiP: pad the small stream first, e.g. `[1:v]scale=iw/4:-2,pad=iw+8:ih+8:4:4:white[pip]`.

## Watermark

Logo top-right at 60% opacity:

```bash
ffmpeg -y -i in.mp4 -i logo.png -filter_complex "[1:v]format=rgba,colorchannelmixer=aa=0.6,scale=160:-1[wm];[0:v][wm]overlay=W-w-20:20" -c:v libx264 -crf 20 -c:a copy out_watermark.mp4
```

Text watermark needs a font file path (`drawtext=fontfile=...`); on Windows escape the drive colon
(`C\:/Windows/Fonts/arial.ttf`). Prefer a PNG.

## Loudness

One-pass EBU R128 to -16 LUFS (fine for previews; may pump on dynamic material):

```bash
ffmpeg -y -i in.mp4 -c:v copy -af "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000" -c:a aac -b:a 192k out_loud.mp4
```

Two-pass is accurate: run once with `print_format=json` to measure, then pass `measured_I`,
`measured_TP`, `measured_LRA`, `measured_thresh`, `offset` and `linear=true`. `render.py` does this
when the EDL has `"loudnorm": true`. Targets: -16 LUFS podcasts/YouTube, -14 social, -23 broadcast.

## Phone footage

Phones record variable frame rate (VFR). Cutting VFR by time gives A/V drift; convert to constant
frame rate first, keeping the original:

```bash
ffmpeg -y -i in.mp4 -fps_mode cfr -r 30 -c:v libx264 -crf 18 -preset medium -c:a aac -b:a 192k out_cfr.mp4
```

Rotation is stored as metadata; ffmpeg applies it automatically when re-encoding. With `-c copy`
the metadata is kept as-is.
