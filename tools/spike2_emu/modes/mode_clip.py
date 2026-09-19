#!/usr/bin/env python3
"""mode_clip.py - item 132: add a mode's OWN CLIP to a stock in-game video bank scene.

    mode_clip.py <stock bank scene.radium> <out dir> --name KaijuRush_Clip
                 (--clip our.mp4 | --make "KAIJU RUSH") [--seconds 4]

Writes ``<out dir>/scene.radium`` with one more clip in both of the bank's maps
(video_bank.add_clip) and ``<out dir>/scene.assets/<path>``, the clip file itself - the
same layout as the scene's directory on a card. ``--make`` renders a title card clip
with ffmpeg; ``--clip`` takes one you made. Either way it must be H.264, 8-bit 4:2:0,
silent and the bank's own size (1360x768 on Godzilla), which is checked with ffprobe.
Prints where the directory goes and the mode-file line that plays it.

EMULATOR-PROVEN, not hardware-proven (TODO item 132). Unlike an own screen, a clip
added here is harmless without the mode: nothing names it until mode.so plays it.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from pinball_decryptor.plugins.stern import video_bank as VB  # noqa: E402

FONTS = (r"C:\Windows\Fonts\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _font_arg(path):
    return path.replace("\\", "/").replace(":", "\\:")


def make_clip(out, title, w, h, seconds, fps=30):
    """A title card over a moving bar, with the frame number in the corner so a
    screenshot says which frame it caught. Constrained Baseline 3.0, like most stock clips."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("mode_clip: --make needs ffmpeg on PATH")
    font = next((f for f in FONTS if os.path.exists(f)), None)
    if not font:
        sys.exit("mode_clip: no bold font found for the title (%s)" % ", ".join(FONTS))
    f = _font_arg(font)
    graph = (
        "color=c=0x0a3a14:s={w}x{h}:r={fps}:d={s}[bg];"
        "color=c=0xffe600:s=60x{h}:r={fps}:d={s}[bar];"
        "[bg][bar]overlay=x='-60+t*{speed}':y=0[v1];"
        "[v1]drawtext=fontfile='{f}':text='{t}':fontsize={big}:fontcolor=0xffe600:"
        "borderw=8:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2-40,"
        "drawtext=fontfile='{f}':text='frame %{{frame_num}}':fontsize=40:fontcolor=white:"
        "x=w-text_w-40:y=h-80[v]"
    ).format(w=w, h=h, fps=fps, s=seconds, speed=(w + 60) / seconds, f=f,
             t=title.replace("'", "").replace(":", "\\:"), big=max(40, int(h * 0.22)))
    cmd = [ffmpeg, "-v", "error", "-y", "-filter_complex", graph, "-map", "[v]",
           "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0", "-pix_fmt", "yuv420p",
           "-b:v", "2500k", "-g", str(fps), "-an", "-movflags", "+faststart", "-f", "mp4", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("mode_clip: ffmpeg failed: %s" % r.stderr.strip()[-400:])


def probe(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    r = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-of", "json", path],
                       capture_output=True, text=True)
    return json.loads(r.stdout or "{}").get("streams", [])


def check_clip(path, w, h):
    streams = probe(path)
    if streams is None:
        print("WARNING: no ffprobe on PATH - the clip was not checked")
        return
    video = [s for s in streams if s.get("codec_type") == "video"]
    problems = []
    if len(video) != 1:
        problems.append("%d video streams" % len(video))
    else:
        v = video[0]
        if v.get("codec_name") != "h264":
            problems.append("codec %s, the machine decodes only h264" % v.get("codec_name"))
        if v.get("pix_fmt") not in ("yuv420p", "yuvj420p"):
            problems.append("pixel format %s, not 8-bit 4:2:0" % v.get("pix_fmt"))
        if (v.get("width"), v.get("height")) != (w, h):
            problems.append("%sx%s, the bank is %dx%d" % (v.get("width"), v.get("height"), w, h))
    if any(s.get("codec_type") == "audio" for s in streams):
        problems.append("it has audio; in-game clips are silent")
    if problems:
        sys.exit("mode_clip: %s: %s" % (path, "; ".join(problems)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bank", help="the stock video bank scene.radium")
    ap.add_argument("out", help="a directory: gets scene.radium and scene.assets/")
    ap.add_argument("--name", required=True, help="the clip's name, what mode.so plays")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--clip", help="an H.264 clip of the bank's size")
    src.add_argument("--make", metavar="TITLE", help="render a title card clip with ffmpeg")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--scene-id", default=VB.GODZILLA_PRO_BANK)
    args = ap.parse_args(argv)
    data = open(args.bank, "rb").read()
    try:
        bank = VB.parse(data)
    except VB.VideoBankError as e:
        sys.exit("mode_clip: %s is not a video bank this can walk: %s" % (args.bank, e))
    out_scene = os.path.join(args.out, "scene.radium")
    if os.path.abspath(out_scene) == os.path.abspath(args.bank):
        sys.exit("refusing to overwrite the stock scene in place: give another output directory")
    os.makedirs(args.out, exist_ok=True)
    path = VB.next_path(bank)
    clip_out = os.path.join(args.out, "scene.assets", *path.split("/"))
    os.makedirs(os.path.dirname(clip_out), exist_ok=True)
    if args.make:
        make_clip(clip_out, args.make, bank.width, bank.height, args.seconds)
    else:
        shutil.copyfile(args.clip, clip_out)
    check_clip(clip_out, bank.width, bank.height)
    try:
        new, info = VB.add_clip(data, args.name, os.path.getsize(clip_out), path)
    except VB.VideoBankError as e:
        sys.exit("mode_clip: %s" % e)
    with open(out_scene, "wb") as f:
        f.write(new)
    print("wrote %s (%d -> %d bytes, %d clips), md5 %s" % (out_scene, len(data), len(new), info["clips"], info["md5"]))
    print("wrote %s (%d bytes), clip id %d" % (clip_out, info["size"], info["clip_id"]))
    print("goes to  assets/lcd/auto_loaded/%s/  (scene.radium, and scene.assets/%s)" % (args.scene_id, path))
    print("mode file line:")
    print("  clip_start     %s" % info["name"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
