#!/usr/bin/env python3
"""QEMU=qemu-arm-static settings_test.py ROOT BIN T [FONT]

PAD-307: the SETTINGS tile and its Color correction screen, driven through the
rig's keyboard file the way padglhost presses buttons - by name (the cab[]
bytes at 1068), so no switch table is needed.

  1. walk  - the tile is the last card; START on it opens Settings, START again
             opens Color correction on the first adjustable image; a middle-
             shades value is changed (+2 steps), saved for THIS game, and the
             values file holds exactly that line; BACK, BACK TO THE GAMES, and
             the countdown - which never runs inside Settings - boots the card
             the menu opened on, never the tile.
  1b. plain - PAD-537: BRIGHTNESS, CONTRAST and SATURATION (the rows after START
             FROM) are stepped and saved; the line carries the brightness and
             contrast as a fifth field.
  2. all   - "Save for every game" puts one set on both adjustable images.
  3. hold  - a flipper HELD while a value is being changed repeats the step.
  4. idle  - nothing pressed inside Settings: it closes by itself
             (PAD_SETTINGS_IDLE_MS) and the countdown boots a game.
  5. apply - --apply-color writes a copy of a program whose pad_cp numbers are
             the saved ones (the same template shader_profile.py writes), refuses
             one whose pad_cp is in the old shape, and says "nothing to do" for
             an image with no line; a line with a brightness and contrast is
             written folded into gain and gamma, the numbers the PC's own
             Profile.curve() makes of it.

The emulator comes from the environment ($QEMU), never argv: the rig's teardown
does pkill -f 'arm-binfmt|qemu-arm' and this script's command line must not
match it."""
import os
import re
import struct
import importlib.util
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkmedia  # noqa: E402

MAGIC = 0x53444150
OFF_CAB = 1068
CAB_IDX = {"left": 0, "right": 1, "start": 2, "action": 3, "select": 4,
           "plus": 5, "minus": 6, "back": 7}

CONF = """image=p3|STERN STOCK|original Stern code|art0.png||
image=p7:img1|TMNT 1987|upscaled cartoon retheme|art1.png|anim1.gif|
image=p7:img2|TMNT 1987 BW|black and white edition|art0.png||
color_profile=1|1.10 1.20 1.35|1.00 1.00 1.00|0.00 0.00 0.00|0.90|Recommended
color_profile=2|1.00 1.00 1.00|1.00 1.00 1.00|0.00 0.00 0.00|0.00|Black and white
test=art0.png|Red square
test=anim1.gif|Moving
test=confirm.wav|Tone
default=1
timeout=4
"""

# the template every pad_cp is written in (shader_profile.py TUNABLE_TEMPLATE)
TEMPLATE = ("c=mix(vec3(dot(c,vec3(0.299,0.587,0.114))),c,########);"
            "c=pow(clamp(c*vec3(########,########,########),0.0,1.0),"
            "vec3(########,########,########));"
            "c=vec3(########,########,########)+(vec3(1.0)-vec3(########,########,########))*c;")


def fail(msg, *more):
    print("settings_test: FAIL %s" % msg)
    for m in more:
        print(m)
    raise SystemExit(1)


def pad_cp(sat, gain, gamma, lift):
    out = TEMPLATE
    for v in (sat,) + gain + gamma + lift + lift:
        out = out.replace("#" * 8, "%.6f" % v, 1)
    return ("highp vec4 pad_cp(highp vec4 f){highp float a=f.a;highp vec3 c=clamp(f.rgb,0.0,1.0);"
            + out + "return vec4(c,a);}")


def _colour_profile():
    """core/colour_profile.py of the repo this test sits in (it imports nothing of the app)"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..",
                        "pinball_decryptor", "core", "colour_profile.py")
    spec = importlib.util.spec_from_file_location("pad_colour_profile", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    root, binp, t = sys.argv[1:4]
    qemu = os.environ.get("QEMU", "qemu-arm-static")
    font = sys.argv[4] if len(sys.argv) > 4 and os.path.isfile(sys.argv[4]) else \
        os.path.join(root, "usr/local/spike/VeraMono.ttf")
    t = os.path.join(t, "settings")
    os.makedirs(t, exist_ok=True)
    media = os.path.join(t, "media")
    mkmedia.make(media)
    conf = os.path.join(t, "settings.conf")
    with open(conf, "w") as f:
        f.write(CONF)
    no_list = os.path.join(t, "no_such_table_dir", "switch_list.txt")

    def run(name, presses, env=None, hold=None, timeout=4, wait=0.0):
        """presses: button names (or (name, hold seconds)); returns (rc, out, err, values)"""
        values = os.path.join(t, name + ".color")
        choice = os.path.join(t, name + ".choice")
        last = os.path.join(t, name + ".last")
        for p in (values, choice, last):
            if os.path.exists(p):
                os.unlink(p)
        sw = os.path.join(t, name + ".padsw")
        with open(sw, "wb") as f:
            f.write(struct.pack("<II", MAGIC, 1) + bytes(4096 - 8))
        e = dict(os.environ)
        e.update(env or {})
        p = subprocess.Popen([qemu, "-L", root, binp, "--headless", os.path.join(t, name + ".ppm"),
                              "--conf", conf, "--input", "padsw", "--padsw", sw, "--tables", no_list,
                              "--timeout", str(timeout), "--out", choice, "--last", last,
                              "--log", os.path.join(t, name + ".log"), "--font", font, "--no-invert",
                              "--media", media, "--audio", "none", "--color-file", values],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e)
        time.sleep(1.2)
        for press in presses:
            button, held = (press, 0.15) if isinstance(press, str) else press
            with open(sw, "r+b") as f:
                f.seek(OFF_CAB + CAB_IDX[button])
                f.write(b"\x01")
            time.sleep(held)
            with open(sw, "r+b") as f:
                f.seek(OFF_CAB + CAB_IDX[button])
                f.write(b"\x00")
            time.sleep(0.45)
        time.sleep(wait)
        try:
            o, err = p.communicate(timeout=40)
        except subprocess.TimeoutExpired:
            p.kill()
            o, err = p.communicate()
            fail("(%s) codeselect did not exit" % name, o, err)
        vals = open(values).read() if os.path.exists(values) else None
        ch = open(choice).read().strip() if os.path.exists(choice) else None
        return p.returncode, o, err, vals, ch

    def lines_of(vals):
        return [ln for ln in (vals or "").splitlines() if ln and not ln.startswith("#")]

    # the colour screen's rows (two adjustable images): GAME 0, START FROM 1, BRIGHTNESS 2,
    # CONTRAST 3, SATURATION 4, MIDDLE SHADES 5-7, COLOR LEVEL 8-10, DARKEST SHADES 11,
    # SEE IT ON THE TEST PICTURES 12 (PAD-1279), SAVE 13, SAVE FOR EVERY GAME 14, BACK 15;
    # the Settings list: COLOR CORRECTION 0, TEST PICTURES 1, BACK TO THE GAMES 2
    # 1. walk: card 1 (the default) -> RIGHT RIGHT = the tile (card 4 of 4)
    walk = ["right", "right", "start",          # the tile opens Settings
            "start",                            # Color correction, on image 1
            "right", "right", "right", "right", "right",   # -> 5 = MIDDLE SHADES red
            "start", "right", "right", "start",  # +2 steps: 1.10 -> 1.20
            "right", "right", "right", "right", "right", "right", "right", "right",   # 5 -> 13 = SAVE
            "start",
            "right", "right", "start",          # 13 -> 15 = BACK (nothing unsaved)
            "right", "right", "start"]          # BACK TO THE GAMES
    rc, o, e, vals, ch = run("walk", walk)
    for want in ("[select] settings: open",
                 "[select] settings: color correction, 2 adjustable images, on image 1 (TMNT 1987)",
                 "[select] color: image 1 (TMNT 1987) saved: 1.2000 1.2000 1.3500|1.0000 1.0000 1.0000|"
                 "0.0000 0.0000 0.0000|0.9000",
                 "[select] settings: left color correction",
                 "[select] settings: back to the games",
                 "[select] settings: closed"):
        if want not in o:
            fail("(walk) no %r" % want, o, e)
    if "countdown expired: booting card 2 (the settings tile is highlighted" not in e:
        fail("(walk) the countdown did not boot the card the menu opened on", o, e)
    if rc != 0 or ch != "1" or "[select] chose 1 TMNT 1987" not in o:
        fail("(walk) rc %s choice %r" % (rc, ch), o, e)
    if lines_of(vals) != ["p7:img1|1.2000 1.2000 1.3500|1.0000 1.0000 1.0000|0.0000 0.0000 0.0000|0.9000"]:
        fail("(walk) the values file holds %r" % vals)

    # 1b. plain: BRIGHTNESS +2 (110%), CONTRAST +3 (115%), SATURATION -2 (90% -> 80%), SAVE
    plain = ["right", "right", "start", "start",
             "right", "right", "start", "right", "right", "start",            # 2 BRIGHTNESS
             "right", "start", "right", "right", "right", "start",            # 3 CONTRAST
             "right", "start", "left", "left", "start",                       # 4 SATURATION
             "right", "right", "right", "right", "right", "right", "right", "right", "right",   # 4 -> 13 SAVE
             "start",
             "right", "right", "start", "right", "right", "start"]
    rc, o, e, vals, ch = run("plain", plain)
    want_line = ("p7:img1|1.1000 1.2000 1.3500|1.0000 1.0000 1.0000|0.0000 0.0000 0.0000|0.8000"
                 "|1.1000 1.1500")
    if lines_of(vals) != [want_line]:
        fail("(plain) the values file holds %r, expected %r" % (vals, want_line), o, e)
    if "[select] color: image 1 (TMNT 1987) saved: " + want_line.split("|", 1)[1] not in o:
        fail("(plain) not saved as %r" % want_line, o, e)

    # 2. all: START FROM -> Black and white (3 steps: As built, Recommended, No change, B&W),
    # then SAVE FOR EVERY GAME
    allg = ["right", "right", "start", "start",
            "right", "start", "right", "right", "right", "start",   # START FROM -> Black and white
            "left", "left", "left",            # 1 -> 0 -> 15 -> 14 = SAVE FOR EVERY GAME
            "start",
            "right", "start",                  # 15 = BACK
            "right", "right", "start"]
    rc, o, e, vals, ch = run("all", allg)
    got = sorted(lines_of(vals))
    want = ["p7:img1|1.0000 1.0000 1.0000|1.0000 1.0000 1.0000|0.0000 0.0000 0.0000|0.0000"]
    # image 2 was BUILT black and white: its line is dropped, it boots as built
    if got != want:
        fail("(all) the values file holds %r, expected %r" % (got, want), o, e)
    if "image 2 (TMNT 1987 BW) saved: 1.0000 1.0000 1.0000|1.0000 1.0000 1.0000|0.0000 0.0000 0.0000|0.0000 " \
       "(as built: no line in the values file)" not in o:
        fail("(all) image 2 not saved as built", o)

    # 3. hold: change the red middle shades and HOLD the right flipper 1.5 s
    hold = ["right", "right", "start", "start", "right", "right", "right", "right", "right", "start",
            ("right", 1.5), "start",
            "right", "right", "right", "right", "right", "right", "right", "right", "start",   # 5 -> 13 SAVE
            "right", "right", "start", "right", "right", "start"]
    rc, o, e, vals, ch = run("hold", hold)
    m = re.search(r"saved: (\d\.\d+) ", o)
    if not m:
        fail("(hold) nothing saved", o, e)
    if float(m.group(1)) < 1.10 + 5 * 0.05 - 1e-6:
        fail("(hold) a 1.5 s hold moved red only to %s (expected at least 5 steps)" % m.group(1), o)

    # 4. idle: into Color correction, change something, then press nothing
    rc, o, e, vals, ch = run("idle", ["right", "right", "start", "start", "right", "right", "start", "right"],
                             env={"PAD_SETTINGS_IDLE_MS": "3000"}, wait=6)
    if "[select] settings: nothing pressed for 3 s: back to the games, unsaved changes dropped" not in o:
        fail("(idle) Settings did not close by itself", o, e)
    if rc != 0 or ch != "1" or vals is not None:
        fail("(idle) rc %s choice %r values %r" % (rc, ch, vals), o, e)

    # 4b. test pictures (PAD-1279): from the list - the built-in patterns, then the card's own
    # (a picture, an animation, a sound) and BACK; START on a picture steps the correction
    # through each adjustable game and none; BACK returns to the list
    n_items = 6 + 3 + 1
    tp = ["right", "right", "start",            # the tile
          "right", "start",                     # TEST PICTURES
          "start", "start", "start",            # image 1 -> image 2 -> none -> (wraps) image 1
          "left",                               # 0 -> BACK (the last)
          "left", "left", "left",               # the sound, the animation, the picture
          "right", "right", "right",            # back to BACK
          "start",                              # back to the list
          "right", "start"]                     # BACK TO THE GAMES
    rc, o, e, vals, ch = run("testpics", tp)
    for want in ("[select] test: open (6 built-in, 3 of the card's own)",
                 "[select] test: 1/%d Test card" % n_items,
                 "[select] test: color TMNT 1987 BW",
                 "[select] test: color not corrected",
                 "[select] test: %d/%d Back to settings" % (n_items, n_items),
                 "[select] test: 9/%d Tone (confirm.wav)" % n_items,
                 "[select] test: 8/%d Moving (anim1.gif)" % n_items,
                 "[select] test: 7/%d Red square (art0.png)" % n_items,
                 "[select] test: closed",
                 "[select] settings: back to the games",
                 "[select] settings: closed"):
        if want not in o:
            fail("(testpics) no %r" % want, o, e)
    if rc != 0 or ch != "1" or vals is not None:
        fail("(testpics) rc %s choice %r values %r" % (rc, ch, vals), o, e)

    if not re.search(r"\[select\] test: color TMNT 1987$", o, re.M):
        fail("(testpics) the correction did not come back round to image 1", o, e)

    # 4c. from Color correction: SEE IT ON THE TEST PICTURES shows the numbers being changed,
    # unsaved, and BACK lands on Color correction again, where they are saved
    tc = ["right", "right", "start", "start",   # Color correction on image 1
          "right", "right", "right", "right", "right",   # -> 5 MIDDLE SHADES red
          "start", "right", "start",            # 1.10 -> 1.15, unsaved
          "right", "right", "right", "right", "right", "right", "right",   # 5 -> 12 TEST
          "start",                              # the test pictures
          "left", "start",                      # BACK -> Color correction
          "right", "start",                     # 13 SAVE
          "right", "right", "start", "right", "right", "start"]
    rc, o, e, vals, ch = run("testcolor", tc)
    if "[select] test: 10/10 Back to color correction" not in o or "[select] test: closed" not in o:
        fail("(testcolor) the test pictures did not open from Color correction", o, e)
    if lines_of(vals) != ["p7:img1|1.1500 1.2000 1.3500|1.0000 1.0000 1.0000|0.0000 0.0000 0.0000|0.9000"]:
        fail("(testcolor) after the test pictures the change was not still there to save: %r" % vals, o, e)

    # 4d. the pictures themselves, by snapshot, caption hidden: a built-in pattern is exact,
    # the card's own picture is its own pixels uncorrected and the game's numbers corrected
    def snap_test(name, conf_path, row):
        out = os.path.join(t, "test_%s.ppm" % name)
        r = subprocess.run([qemu, "-L", root, binp, "--snapshot", out, "--conf", conf_path, "--font", font,
                            "--media", media, "--no-invert", "--screen", "test", "--screen-row", str(row),
                            "--screen-edit"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if r.returncode != 0:
            fail("(test snapshot %s) rc %d" % (name, r.returncode), r.stdout, r.stderr)
        w, h, data = mkmedia.read_ppm(out)
        return w, h, (lambda x, y: tuple(data[(y * w + x) * 3:(y * w + x) * 3 + 3]))
    plain_conf = os.path.join(t, "testonly.conf")
    with open(plain_conf, "w") as f:
        f.write("image=p3|STERN STOCK|original Stern code||\n"
                "test=art0.png|Red square\ntest=nosuch.png|Missing\ntest=notes.txt|Not a picture\n")
    w, h, px = snap_test("grey", plain_conf, 1)
    if (w, h) != (1360, 768):
        fail("(test snapshot) %dx%d" % (w, h))
    # the grey ramp: the darkest band holds 0..15 in 16 steps, the lightest 240..255
    band = h // 4
    for k in (0, 1, 7, 15):
        x = k * w // 16 + w // 32
        got = px(x, 2 * band + band // 2)
        if got != (k, k, k):
            fail("(test grey) dark step %d at x %d is %r" % (k, x, got))
        got = px(x, 3 * band + band // 2)
        if got != (240 + k,) * 3:
            fail("(test grey) light step %d at x %d is %r" % (k, x, got))
    w, h, px = snap_test("own", plain_conf, 6)
    own = px(w // 2, h // 2)
    w, h, px2 = snap_test("own_corrected", conf, 6)
    if px2(w // 2, h // 2) == own:
        fail("(test own) the corrected picture is the same as the plain one: %r" % (own,))
    w, h, px = snap_test("missing", plain_conf, 7)
    w, h, px = snap_test("notpic", plain_conf, 8)
    r = subprocess.run([qemu, "-L", root, binp, "--snapshot", os.path.join(t, "tile_tests.ppm"),
                        "--conf", plain_conf, "--font", font, "--media", media, "--no-invert",
                        "--highlight-card", "1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0 or "card 2/2 (settings)" not in r.stdout:
        fail("(test tile) a card with test= lines and no color_profile= has no SETTINGS tile", r.stdout)

    # 4e. a TEST CARD (testcard=on, PAD-1279): nothing boots - the TEST CARD menu from power-up
    # (DEFAULT PAD TEST CARD, IMAGES, VIDEOS, SCENES, SOUNDS, COLOR CORRECTION), each a list;
    # START selects, ACTION backs out, an empty list does nothing; Color correction on its one
    # pseudo-image; no idle exit; it runs until it is stopped (SIGTERM here, the power switch on
    # a machine).  A video is a .padv (video.h): JPEG frames, played at its own rate.
    def write_padv(path, frames, fps):
        import io
        from PIL import Image
        blobs = []
        for rgb in frames:
            b = io.BytesIO()
            Image.new("RGB", (64, 48), rgb).save(b, "JPEG", quality=95, subsampling=0)
            blobs.append(b.getvalue())
        n = len(blobs)
        off = 32 + 4 * (n + 1)
        offs = []
        for b in blobs:
            offs.append(off)
            off += len(b)
        offs.append(off)
        with open(path, "wb") as f:
            f.write(b"PADVJPG1" + struct.pack("<IIIIII", 64, 48, int(fps * 1000), n, 0, 0))
            f.write(struct.pack("<%dI" % (n + 1), *offs))
            for b in blobs:
                f.write(b)
    # a test card's own files are on its p3, not with the media: test_dir= says where
    tdir = os.path.join(t, "testdir")
    os.makedirs(tdir, exist_ok=True)
    import shutil
    shutil.copyfile(os.path.join(media, "art0.png"), os.path.join(tdir, "art0.png"))
    write_padv(os.path.join(tdir, "clip.padv"), [(200, 40, 40)] * 6 + [(40, 40, 200)] * 6, 10)
    with open(os.path.join(tdir, "bad.padv"), "wb") as f:
        f.write(b"PADVJPG1" + struct.pack("<IIIIII", 4000, 48, 10000, 1, 0, 0) + bytes(16))
    tconf = os.path.join(t, "testcard.conf")
    with open(tconf, "w") as f:
        f.write("image=testcard|TEST CARD|color profile test card||\n"
                "color_profile=0|1.10 1.20 1.35|1.00 1.00 1.00|0.00 0.00 0.00|0.90|Recommended\n"
                "testcard=on\ntest_dir=%s\ntest_image=art0.png|Red square\ntest_video=clip.padv|Clip\n"
                "test_video=bad.padv|Too big\ntest_scene=art0.png|Scene one\n"
                "test_sound=art0.png|Not a sound\n" % tdir)
    tvals = os.path.join(t, "testcard.color")
    tout = os.path.join(t, "testcard.choice")
    for q in (tvals, tout):
        if os.path.exists(q):
            os.unlink(q)
    tsw = os.path.join(t, "testcard.padsw")
    with open(tsw, "wb") as f:
        f.write(struct.pack("<II", MAGIC, 1) + bytes(4096 - 8))
    env = dict(os.environ, PAD_SETTINGS_IDLE_MS="2000", PAD_VID_THREADS="2")
    tp = subprocess.Popen([qemu, "-L", root, binp, "--headless", os.path.join(t, "testcard.ppm"),
                           "--conf", tconf, "--input", "padsw", "--padsw", tsw, "--tables", no_list,
                           "--timeout", "3", "--out", tout, "--last", os.path.join(t, "testcard.last"),
                           "--font", font, "--no-invert", "--media", media, "--audio", "none",
                           "--color-file", tvals],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    time.sleep(1.2)
    walk = (["start", "start", "right", "action", "action"]       # the patterns: 1, 2, back, back
            + ["right", "start", "start", "action", "action"]     # IMAGES: Red square
            + ["right", "start", "start", "wait", "right", "action", "action"]   # VIDEOS: Clip, Too big
            + ["right", "start", "start", "action", "action"]     # SCENES: Scene one
            + ["right", "start", "action"]                        # SOUNDS: none - nothing happens
            + ["right", "start",                                  # COLOR CORRECTION
               "right", "start", "right", "start",                # BRIGHTNESS +1
               ] + ["right"] * 11 + ["start"]                     # 1 -> 12 = SAVE
            + ["action"]                                          # ACTION: leave, back to the menu
            + ["right"])                                          # six entries: round to the first
    for button in walk:
        if button == "wait":
            time.sleep(2.5)
            continue
        with open(tsw, "r+b") as f:
            f.seek(OFF_CAB + CAB_IDX[button])
            f.write(b"\x01")
        time.sleep(0.15)
        with open(tsw, "r+b") as f:
            f.seek(OFF_CAB + CAB_IDX[button])
            f.write(b"\x00")
        time.sleep(0.45)
    time.sleep(5)
    alive = tp.poll() is None
    tp.terminate()
    try:
        o, e = tp.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        tp.kill()
        o, e = tp.communicate()
    if not alive:
        fail("(testcard) the test card exited by itself (idle or countdown)", o, e)
    for want in ("[select] testcard: nothing boots: the test card menu until power-off",
                 "[select] settings: the test card menu",
                 "[select] menu: DEFAULT PAD TEST CARD (6)",
                 "[select] test: open DEFAULT PAD TEST CARD (6)",
                 "[select] test: 2/6 ",
                 "[select] menu: IMAGES (1)",
                 "[select] test: 1/1 Red square (art0.png)",
                 "[select] menu: VIDEOS (2)",
                 "[select] test: video 12 frames at 10.000 fps, 2 decoders",
                 "[select] test: 2/2 Too big (bad.padv)",
                 "[select] test: the video is 4000x48, the screen 1360x768",
                 "[select] menu: SCENES (1)",
                 "[select] test: 1/1 Scene one (art0.png)",
                 "[select] menu: SOUNDS: none on this card",
                 "[select] settings: color correction, 1 adjustable image, on image 0 (TEST CARD)",
                 "[select] color: image 0 (TEST CARD) saved: ",
                 "[select] settings: left color correction"):
        if want not in o:
            fail("(testcard) no %r" % want, o, e)
    if o.count("[select] menu: back") != 4:
        fail("(testcard) ACTION backed out to the menu %d times, expected 4" % o.count("[select] menu: back"),
             o, e)
    if "not a file that list shows" not in o + e:
        fail("(testcard) test_sound=art0.png was not refused", o, e)
    if "back to the games" in o or os.path.exists(tout) and open(tout).read().strip():
        fail("(testcard) a test card left for the games or chose one", o, e)
    tl = lines_of(open(tvals).read() if os.path.exists(tvals) else "")
    if len(tl) != 1 or not tl[0].startswith("testcard|"):
        fail("(testcard) the values file holds %r, expected one testcard| line" % tl, o, e)
    # the pictures: the menu (the default), one list, and the video's first frame decoded,
    # in its own colour and uncorrected (the app built its profile in)
    for name, screen, want in (("menu", None, "screen settings"), ("pick", "pick:videos", "screen pick:videos")):
        args = [qemu, "-L", root, binp, "--snapshot", os.path.join(t, "testcard_%s.ppm" % name),
                "--conf", tconf, "--font", font, "--media", media, "--no-invert"]
        if screen:
            args += ["--screen", screen]
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if r.returncode != 0 or want not in r.stdout:
            fail("(testcard) the %s snapshot" % name, r.stdout, r.stderr)
    out = os.path.join(t, "testcard_video.ppm")
    r = subprocess.run([qemu, "-L", root, binp, "--snapshot", out, "--conf", tconf, "--font", font,
                        "--media", media, "--no-invert", "--screen", "test:videos", "--screen-row", "0",
                        "--screen-edit"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        fail("(testcard) the video snapshot: rc %d" % r.returncode, r.stdout, r.stderr)
    w, h, data = mkmedia.read_ppm(out)
    cx, cy = w // 2, h // 2
    got = tuple(data[(cy * w + cx) * 3:(cy * w + cx) * 3 + 3])
    if any(abs(a - b) > 6 for a, b in zip(got, (200, 40, 40))):
        fail("(testcard) the video's first frame is %r at the centre, expected about (200, 40, 40)" % (got,),
             r.stdout)
    if tuple(data[0:3]) != (0, 0, 0):
        fail("(testcard) round the video is %r, expected black" % (tuple(data[0:3]),))

    # 5. apply: a synthetic program with three pad_cp in the template, one stock string
    prog = os.path.join(t, "game")
    blob = (b"\x7fELF" + b"\x00" * 60 + b"stock text void main(){}\x00" * 50
            + b"".join(pad_cp(0.9, (1.0, 1.0, 1.0), (1.1, 1.2, 1.35), (0.0, 0.0, 0.0)).encode()
                       + b"\x00" * 7 for _k in range(3)) + b"tail" * 64)
    with open(prog, "wb") as f:
        f.write(blob)
    os.chmod(prog, 0o755)
    values = os.path.join(t, "apply.color")
    with open(values, "w") as f:
        f.write("p7:img1|1.30 1.20 1.35|0.95 1 1|0.02 0.02 0.02|1.10\n")
    out = os.path.join(t, "game.out")

    def apply(image, program=prog):
        if os.path.exists(out):
            os.unlink(out)
        r = subprocess.run([qemu, "-L", root, binp, "--apply-color", "--conf", conf, "--image", str(image),
                            "--program", program, "--to", out, "--color-file", values],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return r.returncode, r.stdout

    rc, o = apply(1)
    if rc != 0 or "3 color function(s) rewritten" not in o:
        fail("(apply) rc %d" % rc, o)
    new = open(out, "rb").read()
    if len(new) != len(blob) or (os.stat(out).st_mode & 0o777) != 0o755:
        fail("(apply) the copy is %d bytes mode %o" % (len(new), os.stat(out).st_mode & 0o777))
    expect = blob.replace(pad_cp(0.9, (1.0, 1.0, 1.0), (1.1, 1.2, 1.35), (0, 0, 0)).encode(),
                          pad_cp(1.1, (0.95, 1.0, 1.0), (1.3, 1.2, 1.35), (0.02, 0.02, 0.02)).encode())
    if new != expect:
        fail("(apply) the copy differs from the expected bytes")
    rc, o = apply(2)
    if rc != 1 or "nothing set on this machine" not in o or os.path.exists(out):
        fail("(apply) image 2 with no line: rc %d" % rc, o)
    rc, o = apply(0)
    if rc != 1 or "no adjustable color profile" not in o:
        fail("(apply) image 0: rc %d" % rc, o)
    # the v1.60 shape (no lift statement): refused, nothing left behind
    old = os.path.join(t, "game.old")
    with open(old, "wb") as f:
        f.write(blob.replace(b"c=vec3(0.000000,0.000000,0.000000)+(vec3(1.0)-vec3(0.000000,0.000000,0.000000))*c;",
                             b"", 1))
    rc, o = apply(1, old)
    if rc != 2 or "in the adjustable shape" not in o or os.path.exists(out):
        fail("(apply) the old shape: rc %d" % rc, o)
    # PAD-537: brightness and contrast have no slot of their own: the copy carries them folded
    # into gain and gamma exactly as the PC's Profile.curve() folds them
    with open(values, "w") as f:
        f.write("p7:img1|1.10 1.20 1.35|1 1 1|0 0 0|0.80|1.10 1.15\n")
    rc, o = apply(1)
    if rc != 0 or "3 color function(s) rewritten" not in o:
        fail("(apply) brightness/contrast: rc %d" % rc, o)
    got = re.search(rb"c=mix\(vec3\(dot\(c,vec3\(0\.299,0\.587,0\.114\)\)\),c,([0-9.]{8})\);"
                    rb"c=pow\(clamp\(c\*vec3\(([0-9.]{8}),([0-9.]{8}),([0-9.]{8})\),0\.0,1\.0\),"
                    rb"vec3\(([0-9.]{8}),([0-9.]{8}),([0-9.]{8})\)\);", open(out, "rb").read())
    if not got:
        fail("(apply) brightness/contrast: no pad_cp in the copy")
    got = [float(v) for v in got.groups()]
    cp = _colour_profile()
    gamma, gain, _lift = cp.Profile(gamma=(1.10, 1.20, 1.35), saturation=0.80, brightness=1.10,
                                    contrast=1.15).curve()
    expect = [0.80] + list(gain) + list(gamma)
    if any(abs(a - b) > 2e-6 for a, b in zip(got, expect)):
        fail("(apply) brightness/contrast folded to %r, the PC folds them to %r" % (got, expect))
    # 6. settings=off: the owner left the card out - the menu has the images' cards alone
    off = os.path.join(t, "off.conf")
    with open(off, "w") as f:
        f.write(CONF + "settings=off\n")
    snaps = []
    for name, c in (("on", conf), ("off", off)):
        r = subprocess.run([qemu, "-L", root, binp, "--snapshot", os.path.join(t, "tile_%s.ppm" % name),
                            "--conf", c, "--font", font, "--media", media, "--no-invert",
                            "--highlight-card", "3"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        snaps.append((r.returncode, r.stdout))
    if snaps[0][0] != 0 or "card 4/4 (settings)" not in snaps[0][1]:
        fail("(off) with the card on, card 4 is not the settings card", snaps[0][1])
    if snaps[1][0] == 0 or "out of range (3 cards)" not in snaps[1][1]:
        fail("(off) settings=off still has a fourth card", snaps[1][1])
    print("settings_test: OK (walk, brightness/contrast/saturation, save for every game, a held flipper, "
          "the idle exit, test pictures, a test card, --apply-color, settings=off)")


if __name__ == "__main__":
    main()
