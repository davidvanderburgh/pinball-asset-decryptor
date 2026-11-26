"""The LAYERED TEST: a clip with the game's scenes over it, for a test card (Simon, 2026-11-22/23).

Simon: "a layered test on the TEST CARD - a clip with scenes over it (e.g. Match clip + 0335207f
MATCH/digits + 9d578751 score panel), looped; quick press freeze, long press back out", then "do
the overlay with the match video and you may as well do the correct overlay too".

The clip plays through the machine's own decoder on the test card (codeselect/gstclip.c); the
scenes are drawn HERE, by PAD's scene renderer (:func:`scene_render.render_tree`), one RGBA frame
per clip frame, and written as a ``.pado`` beside the clip (codeselect/overlay.h, which documents
the format).  A scene holds still for most of its length, so equal frames share one picture, and
each picture is cropped to what it draws.

A scene is named by the start of its folder's hash, as the Scenes tab shows it (``0335207f``), and
may be pinned to a frame or a label of its own (``9d578751@MatchFrame``): the game puts the score
panel at its Match frame and leaves it there while the Match scene plays through.  Otherwise a
scene plays from its first frame, one frame per clip frame, and holds its last.

What the game fills in at run time (the scores, the digit Match lands on) is drawn as the scene
itself has it, as the Scenes tab previews it.
"""
import hashlib
import io
import json
import os
import struct

MAGIC = b"PADOVL01"
NONE = 0xFFFFFFFF
#: the screen the test card draws on (Spike 2): an overlay bigger than it is refused there
MAX_CANVAS = (1360, 768)


class Refused(Exception):
    pass


def scene_tree(project):
    path = os.path.join(project, "images", "scene_textures", "scene_tree.json")
    if not os.path.isfile(path):
        raise Refused("%s has no scene tree (images/scene_textures/scene_tree.json)" % project)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_scene(spec):
    """'0335207f' / '9d578751@MatchFrame' / '9d578751@5' -> (hash prefix, pin or None)."""
    key, _sep, pin = str(spec).strip().partition("@")
    key = key.strip().lower()
    if len(key) < 6 or any(c not in "0123456789abcdef" for c in key):
        raise Refused("scene %r: name it by its hash, at least 6 hex digits (as the Scenes tab shows it)" % spec)
    return key, (pin.strip() or None)


def find_scene(tree, key):
    """The one manifest whose scene folder's hash starts with *key*."""
    hits = [(k, v) for k, v in tree.items()
            if any(part.lower().startswith(key) for part in k.split("/")[-3:-1])]
    if not hits:
        raise Refused("no scene %s in the project" % key)
    if len(hits) > 1:
        raise Refused("%s names %d scenes: give more of its hash" % (key, len(hits)))
    return hits[0]


def pin_frame(man, pin):
    """A frame number, or a label of the scene's own root timeline -> its frame."""
    if pin is None:
        return None
    if pin.isdigit():
        return int(pin)
    for label, f in man["root"].get("labels") or ():
        if label == pin:
            return int(f)
    raise Refused("the scene has no label %r (it has %s)"
                  % (pin, ", ".join(l for l, _f in man["root"].get("labels") or ()) or "none"))


def render_frames(project, scenes, frames):
    """RGBA PIL image per clip frame, yielded one at a time (a long clip's frames are ~4 MB each
    at full stage size, so they are never all held): the scenes (``(manifest, pin)``, drawn in
    order, the first lowest) composited over transparency, straight alpha."""
    from PIL import Image
    from . import fontrender as fr
    from . import scene_eval as ev
    from . import scene_render as sr
    fonts = fr.load_fonts(project)
    cache, inks = {}, {}
    w, h = int(scenes[0][0]["stage"][0]), int(scenes[0][0]["stage"][1])
    still = {}
    for k in range(frames):
        frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for i, (man, pin) in enumerate(scenes):
            f = pin if pin is not None else min(k, max(0, int(man["root"].get("frames") or 1) - 1))
            if pin is not None and i in still:
                layer = still[i]
            else:
                d = ev.draw_list(man, f)
                layer = None
                if d:
                    got = sr.render_tree(project, man, frame=f, draws=d, split=set(range(len(d))),
                                         fonts=fonts, cache=cache, inks=inks)
                    layer = got["sel"] if isinstance(got, dict) else None
                if pin is not None:
                    still[i] = layer
            if layer is not None:
                if layer.size != (w, h):
                    raise Refused("the scenes are not one size (%dx%d and %dx%d)" % ((w, h) + layer.size))
                frame = Image.alpha_composite(frame, layer)
        yield frame


def write_pado(images, fps, out):
    """*images* (an iterable of RGBA, one canvas size; read once, a frame at a time) -> the
    ``.pado`` at *out*.  -> (frames, pictures, bytes)."""
    pics, seen, table = [], {}, []
    w = h = None
    for im in images:
        if w is None:
            w, h = im.size
            if w > MAX_CANVAS[0] or h > MAX_CANVAS[1]:
                raise Refused("the scene is %dx%d; the test card's screen is %dx%d"
                              % ((w, h) + MAX_CANVAS))
        box = im.getbbox()
        if box is None or im.getchannel("A").getbbox() is None:
            table.append(NONE)
            continue
        crop = im.crop(box)
        key = (box, hashlib.sha1(crop.tobytes()).hexdigest())
        if key not in seen:
            buf = io.BytesIO()
            crop.save(buf, "PNG", optimize=True)
            seen[key] = len(pics)
            pics.append((box[0], box[1], buf.getvalue()))
        table.append(seen[key])
    if w is None:
        raise Refused("no frames")
    head = MAGIC + struct.pack("<IIIIII", w, h, int(round(fps * 1000)), len(table), len(pics), 0)
    index = struct.pack("<%dI" % len(table), *table)
    off = len(head) + len(index) + 16 * len(pics)
    entries, blobs = [], []
    for x, y, png in pics:
        entries.append(struct.pack("<iiII", x, y, off, len(png)))
        blobs.append(png)
        off += len(png)
    data = head + index + b"".join(entries) + b"".join(blobs)
    tmp = out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out)
    return len(table), len(pics), len(data)


def read_pado(path):
    """-> {'canvas', 'fps', 'frames', 'pictures': [(x, y, png bytes)], 'table'}: for tests and checks."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != MAGIC:
        raise Refused("%s is not an overlay" % path)
    w, h, fps, n, npics, _z = struct.unpack_from("<IIIIII", data, 8)
    table = list(struct.unpack_from("<%dI" % n, data, 32))
    pics = []
    for i in range(npics):
        x, y, off, size = struct.unpack_from("<iiII", data, 32 + 4 * n + 16 * i)
        pics.append((x, y, data[off:off + size]))
    return {"canvas": (w, h), "fps": fps / 1000.0, "frames": n, "pictures": pics, "table": table}


def make_overlay(project, scene_specs, out, frames, fps=30.0, log=print):
    """The overlay for a clip of *frames* frames at *fps*, from the project's scenes
    (:func:`parse_scene` specs, drawn in order)."""
    tree = scene_tree(project)
    scenes = []
    for spec in scene_specs:
        key, pin = parse_scene(spec)
        name, man = find_scene(tree, key)
        f = pin_frame(man, pin)
        scenes.append((man, f))
        log("  scene %s%s: %s" % (key, " at frame %d" % f if f is not None else " from frame 0",
                                  name.split("/")[-2]))
    images = render_frames(project, scenes, int(frames))
    n, npics, size = write_pado(images, fps, out)
    log("  overlay: %d frames, %d picture%s, %d KB -> %s" % (n, npics, "" if npics == 1 else "s",
                                                           size >> 10, out))
    return n, npics, size


def clip_frames(path):
    """(frames, fps) of a video, from ffprobe."""
    import subprocess
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # no console flashing up under the app
    try:                                    # PAD's own ffprobe (a Windows install has none on the PATH)
        from pinball_decryptor.core.audio import find_ffprobe
        probe = find_ffprobe() or "ffprobe"
    except Exception:                       # noqa: BLE001 - the command line, outside the app
        probe = "ffprobe"
    try:
        r = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-count_packets",
                            "-show_entries", "stream=nb_read_packets,r_frame_rate", "-of", "json",
                            path], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=120, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refused("ffprobe cannot read %s (%s)" % (path, e))
    try:
        s = json.loads(r.stdout.decode("utf-8", "replace"))["streams"][0]
        num, den = s["r_frame_rate"].split("/")
        return int(s["nb_read_packets"]), float(num) / float(den)
    except (KeyError, IndexError, ValueError, ZeroDivisionError):
        raise Refused("ffprobe cannot read %s" % path)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Render a project's scenes as an overlay (.pado) for a "
                                             "test clip: the layered test.")
    ap.add_argument("project", help="the PAD project folder the scenes are read from")
    ap.add_argument("out", help="the .pado to write (put it beside the clip, with the clip's name)")
    ap.add_argument("--scene", action="append", required=True, metavar="HASH[@FRAME|@LABEL]",
                    help="a scene to draw, the lowest first; pinned to a frame or label, or "
                         "playing from frame 0")
    ap.add_argument("--clip", help="the clip: its frame count and rate")
    ap.add_argument("--frames", type=int, help="the clip's frame count (without --clip)")
    ap.add_argument("--fps", type=float, default=30.0)
    a = ap.parse_args(argv)
    try:
        frames, fps = clip_frames(a.clip) if a.clip else (a.frames, a.fps)
        if not frames:
            raise Refused("give --clip or --frames")
        make_overlay(a.project, a.scene, a.out, frames, fps)
    except Refused as exc:
        print("error: %s" % exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
