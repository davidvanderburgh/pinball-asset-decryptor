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

Simon (2026-11-26), after the first table run: "the number overlay ... is in the wrong place", "the overlay colour is
wrong ... possibly a filter being applied twice?" and "it shows 'inactive player' it should show 'player 4'":
- the clip is placed as the game's video player shows it (:func:`clip_placement`, :func:`place_clip`): Godzilla's
  player draws a 1360x768 clip zoomed 1.32x about the centre, so the clip's own "0" sat elsewhere under the scene's;
- the scenes are drawn as a ticked scene's picture is (text_scenes.render_resting_frame): the Scenes tab's edits,
  each picture's own colour profile, the text colours, the whole-screen profile the game's shaders apply, not the
  PC's screen simulation (:func:`scene_setup`) - they were drawn from the bare pictures before;
- a player's name box reads "Player N", as the game writes it ("Player %d"), not the scene's stand-in.
"""
import hashlib
import io
import json
import os
import re
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


#: a player's name box (the score panel's P1..P4 ...Username): the game writes "Player %d" there
_NAME_BOX = re.compile(r"(?:^|/)P(\d)_[^/]*/[^/]*Username[^/]*$")


def player_names(draws):
    """*draws* with each player's name box reading "Player N" (Simon: "it should show 'player 4'")."""
    out = []
    for d in draws:
        if isinstance(d, dict) and d.get("kind") == "text":
            m = _NAME_BOX.search("/".join(str(p) for p in d.get("path") or ()))
            if m:
                d = dict(d, text="Player %s" % m.group(1))
        out.append(d)
    return out


#: draws scene_render shows as a stand-in outline (it has no picture of them)
STAND_IN_KINDS = ("video", "spine")


def without_stand_ins(draws):
    """*draws* without the video and spine nodes.

    Simon (2026-11-27): the overlay "Too dark / saturated" on the table, the video right - the game's own Match frame
    (the emulator's framebuffer) against the overlay: MATCH [191, 92, 29] in the game, [156, 83, 42] in ours.  The
    player scene's Video node has no picture in the project, so scene_render draws its stand-in there (a see-through
    blue-grey box, 40, 40, 60 at 90/255, for the Scenes preview) - and in a layered test that box lay over every
    scene under it and over the clip.  A layered test's clip IS the video: the box goes."""
    return [d for d in draws if not (isinstance(d, dict) and d.get("kind") in STAND_IN_KINDS)]


def scene_setup(project, card, man, profiles=True):
    """``(manifest, render_tree keywords)`` for scene *card* drawn as the machine shows it, as a ticked scene's
    picture is (webui/text_scenes.render_resting_frame): the project's Scenes edits (PAD-403: less what the scene
    already shows), its text colours (PAD-438) and score panel colours (PAD-507), each picture's own colour profile
    baked, the whole-screen profile (PAD-312) and not the PC screen's simulation.  Each step that cannot be worked
    out is left off, as the Scenes tab leaves it.

    *profiles* False (Simon, 2026-11-26: the overlay "too dark / saturated" on the table, "It is possible you are
    carrying through the emulation style profiling of the graphics to the actual machine" - an A/B test): the
    pictures and lines as extracted, without each file's own colour profile."""
    from . import scene_edit, scene_render
    kw = {}
    try:
        ops = scene_edit.ops_for(project, card)
        man, _notes = scene_edit.apply_manifest(man, scene_edit.to_apply(project, card, man, ops))
    except Exception:                                           # noqa: BLE001 - the stock layout
        ops = []
    try:
        from . import text_colour
        lines, _w = text_colour.line_ops(project, card, man, ops, bake=profiles)
        if lines:
            man, _n = scene_edit.apply_manifest(man, lines)
    except Exception:                                           # noqa: BLE001
        pass
    try:
        from . import score_colours
        game = score_colours.preview_ops(project, man, bake=profiles)
        if game:
            man, _n = scene_edit.apply_manifest(man, game)
    except Exception:                                           # noqa: BLE001
        pass
    try:
        scene_edit.mark_own_of(man, project, card)
    except Exception:                                           # noqa: BLE001
        pass
    for key, make in (("pictures", lambda: scene_render.pending_pictures(project, bake=profiles)),
                      ("sizes", lambda: scene_render.picture_sizes(project)),
                      ("view", lambda: _machine_view(project)),
                      ("colors", lambda: _text_colors(project, card)),
                      ("text_edits", lambda: _text_edits(project, card, man))):
        try:
            got = make()
        except Exception:                                       # noqa: BLE001
            got = None
        if got:
            kw[key] = got
    return man, kw


def _machine_view(project):
    from pinball_decryptor.core import colour_profile as cp
    return cp.machine_view(project, True, False)


def _text_colors(project, card):
    from . import text_colors
    return text_colors.colors_for(project, card)


def _text_edits(project, card, man):
    """``{drawn line: replacement}``: the scene's own Replace Text rows, and the game program's rows whose original
    the scene draws (the game writes over its stand-in), as the Scenes tab's preview has them."""
    from pinball_decryptor.core import text_manifest
    from . import progtext, scene_eval as ev
    changed = text_manifest.changed(project) or {}
    out = dict(changed.get(card) or ())
    drawn = set()
    frames = max(1, int(man["root"].get("frames") or 1))
    for f in sorted(set(range(0, frames, max(1, frames // 12))) | {frames - 1}):
        drawn.update(d["text"] for d in ev.draw_list(man, f) if d.get("kind") == "text" and d.get("text"))
    for path, pairs in changed.items():
        if (path or "").lower().endswith(".radium"):
            continue
        for orig, rep in pairs:
            o = progtext.decode_text(orig)
            if o in drawn:
                out[o] = progtext.decode_text(rep)
    return out


#: the state a layered test's clip is shown in when none was chosen: Godzilla's player shows a clip with the score
#: panel on screen (Match) in its ScoreFrame state - measured 2026-11-26, the clip's 0 then sits beside the Match
#: scene's digit at its height (in Normal it sat 77 px lower, the misplacement Simon saw)
DEFAULT_STATES = ("ScoreFrame", "Normal")


def clip_states(project, clip):
    """The ways the game's video player can show the clip named *clip* (``match``): ``[(label, (a, d, tx, ty))]`` in
    the player's own order - each label of the player scene's timeline (Godzilla's: Normal, ScoreFrame, SquareCrop,
    LetterboxCrop), its scale across and down and where the clip's corner lands on the stage, with the project's
    Scenes edits on.  The game's code picks the label for each moment; ``[]`` when no scene plays the clip."""
    from . import scene_edit, scene_eval as ev
    name = str(clip or "").strip()
    if not name:
        return []
    trees = scene_edit.trees_of(project) or {}
    for card in sorted(trees):
        man = trees[card]
        if not isinstance(man, dict) or not man.get("root"):
            continue
        boxes = {str(o.get("name")) for o in (man.get("objects") or {}).values()
                 if o.get("kind") == "Video" and name in (o.get("clips") or ())}
        if not boxes:
            continue
        try:
            ops = scene_edit.ops_for(project, card)
            man = scene_edit.apply_manifest(man, scene_edit.to_apply(project, card, man, ops))[0]
        except Exception:                                       # noqa: BLE001 - the stock layout
            pass
        labels = sorted(((int(f), str(lab)) for lab, f in man["root"].get("labels") or ()), key=lambda x: x[0])
        if not labels:
            labels = [(0, "Normal")]
        out = []
        for f, lab in labels:
            for d in ev.draw_list(man, f):
                if d.get("kind") == "video" and str(d.get("name")) in boxes:
                    a, _b, _c, dd, tx, ty = (float(x) for x in d["m"])
                    out.append((lab, (a, dd, tx, ty)))
                    break
        if out:
            return out
    return []


def default_state(states):
    """The label :data:`DEFAULT_STATES` picks among *states* (the first it has), else the first."""
    have = [lab for lab, _m in states]
    for lab in DEFAULT_STATES:
        if lab in have:
            return lab
    return have[0] if have else ""


def clip_placement(project, clip, state=""):
    """How the game's video player shows the clip named *clip* in *state* (a label of :func:`clip_states`; the
    :func:`default_state` when empty or not there): ``(a, d, tx, ty)``, or ``None`` when no scene plays the clip or
    that state shows it 1:1 at the corner (the clip goes as it is)."""
    states = clip_states(project, clip)
    if not states:
        return None
    got = dict(states)
    m = got.get(state) or got.get(default_state(states))
    a, dd, tx, ty = m
    if abs(a - 1) < 1e-3 and abs(dd - 1) < 1e-3 and abs(tx) < 0.5 and abs(ty) < 0.5:
        return None
    return m


def place_clip(src, dst, placement, stage, fps=None, cancel=None):
    """*src* as the game's player shows it (:func:`clip_placement`) on a *stage*-sized black canvas: an H.264 .mp4
    the machine's decoder plays, drawn 1:1 by the test card under the scenes' canvas."""
    import subprocess
    from pinball_decryptor.core.audio import find_ffmpeg
    a, d, tx, ty = placement
    sw, sh = int(stage[0]) // 2 * 2, int(stage[1]) // 2 * 2
    vf = ("color=c=black:s=%dx%d%s[bg];[0:v]scale=trunc(iw*%.6f/2)*2:trunc(ih*%.6f/2)*2[v];"
          "[bg][v]overlay=x=%d:y=%d:shortest=1,format=yuv420p"
          % (sw, sh, (":r=%g" % fps) if fps else "", a, d, int(round(tx)), int(round(ty))))
    cmd = [find_ffmpeg() or "ffmpeg", "-y", "-v", "error", "-i", src, "-filter_complex", vf, "-an",
           "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-profile:v", "high", "-level", "4.1",
           "-movflags", "+faststart", dst]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    while proc.poll() is None:
        if cancel and cancel():
            proc.kill()
            raise Refused("canceled")
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
    err = proc.stderr.read().decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not os.path.isfile(dst):
        raise Refused("the clip could not be placed as the game shows it: %s" % (err[-300:] or proc.returncode))
    return dst


def render_frames(project, scenes, frames, progress=None):
    """RGBA PIL image per clip frame, yielded one at a time (a long clip's frames are ~4 MB each
    at full stage size, so they are never all held): the scenes (``(manifest, pin)`` or
    ``(manifest, pin, render_tree keywords)``, drawn in order, the first lowest) composited over
    transparency, straight alpha.

    Simon (2026-11-26): "It takes a really long time to make the test card with no feedback that anything is going
    on. It should be a fast process?" - a scene draws the same picture on most frames (Godzilla's Match: 17 pictures
    in 221 frames, 86 s drawing every one), so a scene's layer is drawn again only when its draw list changes, and
    a frame the same as the one before is the same picture.  *progress(done, frames)*: called now and then."""
    from PIL import Image
    from . import fontrender as fr
    from . import scene_eval as ev
    from . import scene_render as sr
    fonts = fr.load_fonts(project)
    cache, inks = {}, {}
    w, h = int(scenes[0][0]["stage"][0]), int(scenes[0][0]["stage"][1])
    still = {}
    drawn = {}                                  # scene -> (its draw list's key, its layer) last frame
    last = None                                 # (the frame's layers' keys, the frame) last frame
    step = max(1, frames // 10)
    for k in range(frames):
        if progress is not None and k and k % step == 0:
            progress(k, frames)
        keys, layers = [], []
        for i, scene in enumerate(scenes):
            man, pin = scene[0], scene[1]
            kw = scene[2] if len(scene) > 2 else {}
            f = pin if pin is not None else min(k, max(0, int(man["root"].get("frames") or 1) - 1))
            if pin is not None and i in still:
                key, layer = still[i]
            else:
                d = without_stand_ins(player_names(ev.draw_list(man, f)))
                key = repr(d)
                if i in drawn and drawn[i][0] == key:
                    layer = drawn[i][1]
                else:
                    layer = None
                    if d:
                        got = sr.render_tree(project, man, frame=f, draws=d, split=set(range(len(d))),
                                             fonts=fonts, cache=cache, inks=inks, **kw)
                        layer = got["sel"] if isinstance(got, dict) else None
                    drawn[i] = (key, layer)
                if pin is not None:
                    still[i] = (key, layer)
            keys.append(key)
            layers.append(layer)
        if last is not None and last[0] == keys:
            yield last[1]
            continue
        frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for layer in layers:
            if layer is not None:
                if layer.size != (w, h):
                    raise Refused("the scenes are not one size (%dx%d and %dx%d)" % ((w, h) + layer.size))
                frame = Image.alpha_composite(frame, layer)
        last = (keys, frame)
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
        if seen.get("last") is not None and seen["last"][0] is im:
            table.append(seen["last"][1])               # the same picture as the frame before (render_frames)
            continue
        box = im.getbbox()
        if box is None or im.getchannel("A").getbbox() is None:
            table.append(NONE)
            seen["last"] = (im, NONE)
            continue
        crop = im.crop(box)
        key = (box, hashlib.sha1(crop.tobytes()).hexdigest())
        if key not in seen:
            buf = io.BytesIO()
            crop.save(buf, "PNG", optimize=True)
            seen[key] = len(pics)
            pics.append((box[0], box[1], buf.getvalue()))
        table.append(seen[key])
        seen["last"] = (im, seen[key])
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


def make_overlay(project, scene_specs, out, frames, fps=30.0, log=print, profiles=True, progress=None):
    """The overlay for a clip of *frames* frames at *fps*, from the project's scenes
    (:func:`parse_scene` specs, drawn in order); *profiles*: :func:`scene_setup`'s."""
    tree = scene_tree(project)
    scenes = []
    for spec in scene_specs:
        key, pin = parse_scene(spec)
        name, man = find_scene(tree, key)
        man, kw = scene_setup(project, name, man, profiles=profiles)
        f = pin_frame(man, pin)
        scenes.append((man, f, kw))
        log("  scene %s%s: %s" % (key, " at frame %d" % f if f is not None else " from frame 0",
                                  name.split("/")[-2]))
    images = render_frames(project, scenes, int(frames), progress=progress)
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
