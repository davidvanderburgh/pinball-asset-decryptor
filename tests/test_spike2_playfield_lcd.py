"""LcdPanel: the VILLAIN VISION window draws what the padlcd block names.

Queue item 83. batman's lcdnode drives the "3 LCD INSERT" fixture; the shim
decodes the game's play commands into dump/padlcd and the panel maps the
named asset -> <tables>/<game>/lcd/<id>.{png,webp}, extracting art lazily.

★ THE BLOCK IS v4 AND SO ARE THESE TESTS, after two wrong readings and one
overcorrection. v1 believed the wire addressed three displays and drew a
single command as three ids. v2 named the payload's second u32 "last" off
one capture. v3 swung to "unnamed companion" - too hard: the game's own
duration helper (0x37e2fc, padlcd.h) computes last-first+1 x a period, so
asset..aux IS consumed as an inclusive clip block somewhere real, and the
panel now cycles it clip by clip (verb 1 wraps, verb 2 holds on the last).

So two faults come first here: any return of per-cell state, and the block
degenerating - snapping back to its first clip mid-cycle, or fetching its
end/rate fields as if they were assets. The rest guarded:
a window that builds on titles with no lcdnode (every title would grow a
stray black window), a placeholder that never upgrades when the art lands
(the lazy extraction would be invisible), an asset change that keeps
showing the previous clip (stale cache reference), a close box that kills
the window instead of hiding it (item 44's contract), and a bare verb byte
reaching the caption as silence (a "stop" that looked like "carry on").

THE WINDOW IS A WEB PAGE (2026-09-23): LcdPanel is now a MODEL the page
(pfpage/pf.js) draws. A picture is PNG bytes in the module's BLOBS store,
referenced by key, so these tests assert WHICH key the screen shows and
decode those bytes with PIL to check the pixels - what used to be canvas
item ids and PhotoImage lifetime is now `item` / `item_img` / `item_state`
/ `placeholder`. The window's close box and its remembered position moved
to the controller (Playfield._lcd_closed / api_lcd_close / save_state);
those are driven through a minimal real Playfield with a fake host.

The padlcd block is still a real temp file written with struct.pack,
because the offsets are hard-coded on both sides and a drifting reader
should fail HERE, not on a live run. The art is real PIL-authored files.
"""
import io
import json
import os
import struct
import sys
import threading

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

MAGIC = 0x44434c50

#: The colour _write_png paints its stills - anything but black, so a dark
#: dissolve frame can be told apart from the picture by one pixel.
STILL_RGB = (200, 180, 40)
TV_RGB = (90, 60, 40)


def _pil():
    return pytest.importorskip("PIL.Image")


def _write_block(path, asset=0, aux=0, rate=0, verb=0, bright=255, magic=MAGIC,
                 dec=1):
    """The v4 page: magic, version, gen, decoded, then the one display's
    state (asset, aux, rate, verb, x1, x2, x3, bright, fade, ms). bright
    defaults to 255 exactly as the shim stamps it at map time - 0 means
    "the game commanded dark" and blanks the panel, so a helper defaulting
    to 0 would run every test in the dark. `dec` is the decoded counter -
    bumping it with the SAME command models the game's ~5.2 s re-command
    (the panel no longer keys anything off it; kept for block realism)."""
    d = struct.pack("<14I", magic, 4, 1, dec,
                    asset, aux, rate, verb, 0, 0, 0, bright, 15, 0)
    with open(path, "wb") as f:
        f.write(d + b"\x00" * (4096 - len(d)))


class FakeDrv:
    def __init__(self):
        self.calls = []

    def run_script(self, *a):
        self.calls.append(a)


class FakeHost:
    """The web host as the controller sees it: windows opened (with the
    close handler the controller registers), shown/hidden, and where each
    window currently sits."""

    def __init__(self, geom=None):
        self.opened = []            # [(name, spec, on_close)]
        self.shown = []             # [(name, bool)]
        self.published = []
        self.geom = dict(geom or {})

    def open_window(self, name, spec, on_close=None):
        self.opened.append((name, spec, on_close))

    def show_window(self, name, show):
        self.shown.append((name, show))

    def geometry(self, name):
        return self.geom.get(name)

    def publish(self, etype, data=None):
        self.published.append((etype, data))


def _panel(tmp, monkeypatch, on_build=None):
    import playfield
    block = os.path.join(tmp, "padlcd")
    monkeypatch.setattr(playfield, "LCD_PATH", block)
    # The state file too: the controller restores villain_pos from it and
    # the close box writes it - the tests must never touch the user's real
    # one.
    monkeypatch.setattr(playfield, "STATE", os.path.join(tmp, "state.json"))
    p = playfield.LcdPanel("batman", on_build=on_build)
    p._art = os.path.join(tmp, "lcd")
    p.drv = FakeDrv()
    return playfield, p, block


def _controller(playfield, monkeypatch, host):
    """A real Playfield with ONLY the state its window / state methods read
    - the full constructor starts a SwitchDriver and loads the title's
    tables, none of which the villain vision's window plumbing touches."""
    monkeypatch.setattr(playfield.pfweb, "screen_size", lambda: (1920, 1080))
    ctl = playfield.Playfield.__new__(playfield.Playfield)
    ctl.lock = threading.RLock()
    ctl.host = host
    ctl.pos = {}
    ctl.lcd = None
    # the status bar's Pause / volume poll rides every tick (PAD-204); no
    # control file, and a block path that can never be a live rig's
    monkeypatch.setattr(playfield, "SW_PATH", os.devnull)
    ctl.run = playfield.RunCtl(None)
    return ctl


def _poll(p, times=1):
    for _ in range(times):
        p._next = 0.0
        p.poll()


def _blob_img(key):
    """The PIL image a BLOBS key holds - what the page would fetch."""
    import playfield
    Image = _pil()
    got = playfield.BLOBS.get(key)
    assert got is not None, "BLOBS has no entry for key %r" % (key,)
    data, mime = got
    assert mime == "image/png", mime
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def _rgb(key, xy):
    return _blob_img(key).convert("RGB").getpixel(xy)


def _size(key):
    return _blob_img(key).size


def _write_png(art_dir, name, color=STILL_RGB, w=240, h=180):
    Image = _pil()
    os.makedirs(art_dir, exist_ok=True)
    Image.new("RGB", (w, h), color).save(os.path.join(art_dir, name))


def _write_clip(art_dir, name, colors):
    """A real multi-frame lossless WebP - PIL authors it, PIL plays it,
    exactly the hand-off lcdart.py's ffmpeg stage performs. Lossless so a
    frame's colour comes back EXACTLY, which is the point of the format
    (the GIF it replaced dithered a 256-colour palette and David caught it
    on the glass within a minute)."""
    Image = _pil()
    os.makedirs(art_dir, exist_ok=True)
    frames = [Image.new("RGB", (240, 180), c) for c in colors]
    frames[0].save(os.path.join(art_dir, name), save_all=True,
                   append_images=frames[1:], loop=0, duration=100,
                   lossless=True)


def test_no_lcdnode_title_never_builds(tmp_path, monkeypatch):
    """An unstamped (or absent) block must build NOTHING - this is what keeps
    every non-batman title free of a stray black window."""
    builds = []
    playfield, p, block = _panel(str(tmp_path), monkeypatch,
                                 on_build=lambda: builds.append(1))
    _poll(p)                                    # file absent
    assert p.built is False and not builds
    _write_block(block, asset=54, magic=0)      # present but unstamped
    _poll(p)
    assert p.built is False and not builds
    assert p.spec()["built"] is False


def test_stamped_block_builds_window_and_requests_art(tmp_path, monkeypatch):
    builds = []
    playfield, p, block = _panel(str(tmp_path), monkeypatch,
                                 on_build=lambda: builds.append(1))
    _write_block(block, asset=1736, verb=2)
    _poll(p)
    assert p.built is True, "magic stamped but no window"
    assert builds == [1], "the window was not requested exactly once"
    title = p.spec()["title"]
    assert "villain vision" in title
    # The title must land in the item 44 second-display family so
    # screenrec skips it and the window diagnostics name it correctly.
    assert "] - Stern Spike 2 emulator" in title
    assert p.id == 1736
    assert p.have is False
    assert p.placeholder == "asset 1736" and not p.item
    assert [c[2] for c in p.drv.calls] == ["1736"], p.drv.calls
    # ONE screen: nothing may reintroduce per-cell state.
    assert not isinstance(p.id, (list, tuple))
    # Later polls must NOT re-request. times=10 on purpose: it drives
    # _polls across the %10 retry branch, so _show actually re-runs with
    # the art still missing and only the backoff holds the count at 1.
    _poll(p, times=10)
    assert len(p.drv.calls) == 1
    assert builds == [1], "a later poll requested the window again"


def test_block_command_starts_at_its_first_clip(tmp_path, monkeypatch):
    """v1 drew this frame as three display ids (54, 928 and 106 - a rate
    code - side by side); v2 captioned it "range" off one capture. The
    reading that SURVIVED the disassembly: asset..aux is an inclusive clip
    block (the game's duration helper 0x37e2fc computes last-first+1 x a
    period), the panel starts at its first clip and fetches ONLY that one -
    928 and 106 must still never be fetched as if they were assets.
    """
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_block(block, asset=54, aux=928, rate=12, verb=1)
    _poll(p)
    assert p.id == 54, "the block's first clip was not drawn"
    assert p.cycle == (54, 928)
    assert [c[2] for c in p.drv.calls] == ["54"], \
        "block end / rate fetched as if they were assets: %r" \
        % p.drv.calls
    cap = p.cap_text
    assert "assets 54-928" in cap and "12 fps" in cap, cap
    assert "loop" in cap, cap
    # ... and a plain single-asset command must clear the block.
    _write_block(block, asset=3004, verb=2)
    _poll(p)
    assert p.id == 3004 and p.cycle is None
    cap = p.cap_text
    assert "3004" in cap and "928" not in cap and "once" in cap, cap


def test_block_cycles_clip_by_clip_and_wraps_on_loop(tmp_path, monkeypatch):
    """The block's whole point: when a clip ends the NEXT id in the block
    takes the screen, and verb 1 wraps the block's end back to its first
    clip. The command stays on the wire unchanged throughout - the panel
    must advance itself, and a poll must not snap the drawn id back to the
    block's start mid-cycle."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    for i in (54, 55, 56):
        _write_png(p._art, "%d.png" % i)
        _write_clip(p._art, "%d.webp" % i, ["red", "green"])
    _write_block(block, asset=54, aux=56, rate=12, verb=1)
    seen = []
    for _ in range(24):             # 3 clips x 2 frames, several laps
        _poll(p)
        seen.append(p.id)
    assert set(seen) == {54, 55, 56}, seen
    # order: each id holds for its clip, then hands over - never jumps
    changes = [i for k, i in enumerate(seen) if k and i != seen[k - 1]]
    assert changes[:4] == [55, 56, 54, 55], (seen, changes)
    cap = p.cap_text
    assert "assets 54-56" in cap and "showing" in cap, cap


def test_single_clip_verb_once_holds_not_loops(tmp_path, monkeypatch):
    """verb 2 = play ONCE. The panel looped every single clip regardless,
    which showed motion during the long tail the real TV spends holding a
    one-shot's last frame - the game re-commands the display each attract
    beat precisely because one-shots END. verb 1 must still loop."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_png(p._art, "54.png")
    _write_clip(p._art, "54.webp", ["red", "green"])
    _write_block(block, asset=54, verb=2)
    for _ in range(3):
        _poll(p)                        # plays through the 2 frames
    frozen = p.anim["i"]
    held = p.item_img
    for _ in range(5):
        _poll(p)
    assert p.anim["i"] == frozen, "a one-shot clip wrapped"
    assert p.item_img == held, "a one-shot clip left its last frame"
    assert _rgb(held, (120, 90)) == (0, 128, 0), \
        "a one-shot did not hold on its LAST frame"
    # ... and the same clip under verb 1 loops again.
    _write_block(block, asset=54, verb=1)
    for _ in range(4):
        _poll(p)
    assert p.anim["i"] != frozen or p.anim["i"] <= 2, \
        "verb 1 did not resume looping"


def _write_tv(art_dir, w=120, h=100, hole=(20, 15, 60, 45)):
    """A stand-in for the card's TV sprite: opaque, with a transparent
    rectangular screen hole - the shape lcdframe.py pulls off the card."""
    Image = _pil()
    os.makedirs(art_dir, exist_ok=True)
    tv = Image.new("RGBA", (w, h), TV_RGB + (255,))
    x, y, hw, hh = hole
    tv.paste((0, 0, 0, 0), (x, y, x + hw, y + hh))
    tv.save(os.path.join(art_dir, "tvframe.png"))
    with open(os.path.join(art_dir, "tvframe.txt"), "w", encoding="utf8") as f:
        f.write("%d %d %d %d\n" % hole)


def test_card_tv_art_is_used_and_the_clip_keeps_its_aspect(tmp_path, monkeypatch):
    """When lcdframe.py has pulled the game's own TV off the card, the
    panel composites the picture INTO its screen hole rather than drawing
    a cabinet. The clip must keep its aspect - the hole is squarer than
    4:3 and stretching to fill would distort every face on the TV."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_tv(p._art)
    _write_png(p._art, "54.png")
    _write_block(block, asset=54, verb=2)
    _poll(p)
    assert p.tv is not None and p.tv_hole == (20, 15, 60, 45)
    # The window is the SET's size, and the composed image fills it.
    spec = p.spec()
    assert spec["size"] == [120, 100]
    assert _size(p.img) == (120, 100)
    # The picture sits in the hole and the set's own pixels surround it.
    assert _rgb(p.img, (50, 37)) == STILL_RGB
    assert _rgb(p.img, (5, 5)) == TV_RGB
    # No hand-drawn cabinet when real art exists: the page draws its
    # cabinet only when the spec says there is no card TV.
    assert spec["tv"] is True, "the page would draw a cabinet over card art"
    assert list(spec["screen"]) == [20, 15, 60, 45]
    # Aspect kept: a 240x180 clip into a 60x45 hole fits exactly; make
    # the hole square and the clip must letterbox, not stretch.
    p2 = playfield.LcdPanel("batman")
    p2._art = p._art
    p2._load_tv()
    p2.tv_hole = (20, 15, 60, 60)
    composed = p2._compose(_PILImage_new(240, 180))
    assert _size(composed) == (120, 100)
    # 240x180 into 60x60 -> 60x45 at y 22..67: the band above the picture
    # (still inside the sprite's transparent hole) is black letterbox; a
    # stretch would have painted it red.
    assert _rgb(composed, (50, 17)) == (0, 0, 0), \
        "the clip was stretched to the hole instead of letterboxed"
    assert _rgb(composed, (50, 40)) == (255, 0, 0)


def _PILImage_new(w, h):
    Image = _pil()
    return Image.new("RGB", (w, h), "red")


def test_no_card_art_falls_back_to_the_drawn_cabinet(tmp_path, monkeypatch):
    """Every title without the texture - and any run with no card mounted -
    must still get a TV, not a bare rectangle. The page draws that cabinet
    when the spec says there is no card TV, around a screen of the model's
    own geometry."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_block(block, asset=54, verb=2)
    _poll(p)
    assert p.tv is None
    spec = p.spec()
    assert spec["tv"] is False, "no card art and no drawn cabinet"
    L = playfield.LcdPanel
    assert spec["size"] == [L.CW + L.PAD_L + L.PAD_R, L.CH + L.PAD_T + L.PAD_B]
    assert spec["pad"] == [L.PAD_L, L.PAD_T, L.PAD_R, L.PAD_B]


def test_filmstrip_records_the_sequence_without_duplicates(tmp_path, monkeypatch):
    """The strip answers the question one frame never can: WHAT PLAYED, in
    order. Two rules it must hold - the game re-issues every attract
    command ~250 ms later, so a re-send must NOT add a second entry; and a
    clip with no art must not enter the history as a placeholder."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    for i in (54, 55, 56):
        _write_png(p._art, "%d.png" % i)
    _write_block(block, asset=54, verb=2)
    _poll(p)
    _write_block(block, asset=54, verb=2)   # the 250 ms re-send
    _poll(p, times=3)
    assert [i for i, _ in p._recent] == [54], p._recent
    _write_block(block, asset=55, verb=2)
    _poll(p)
    _write_block(block, asset=56, verb=2)
    _poll(p)
    assert [i for i, _ in p._recent] == [54, 55, 56], p._recent
    # Every entry's thumbnail is a real picture the page can fetch.
    for _i, key in p._recent:
        assert _size(key) == (240, 180)
    # An id with NO art must not land in the history.
    _write_block(block, asset=999, verb=2)
    _poll(p)
    assert [i for i, _ in p._recent] == [54, 55, 56], p._recent
    # ... and the strip is bounded, oldest dropping off the left.
    for i in (57, 58):
        _write_png(p._art, "%d.png" % i)
        _write_block(block, asset=i, verb=2)
        _poll(p)
    assert len(p._recent) == playfield.LcdPanel.STRIP_N
    assert [i for i, _ in p._recent][-1] == 58
    assert p.dyn()["current"] == 58


def test_clip_name_is_shown_and_formatted(tmp_path, monkeypatch):
    """The card's own scene file names every villain clip by episode and
    timecode (lcdnames.py). Showing it is the only independent check on the
    id->clip mapping there has ever been - and the only form a person can
    hold up against a real Villain Vision. The raw name is a mouthful, so
    it is trimmed to "S1E001 00:18:32"; anything not of that shape must
    still be shown rather than mangled or dropped."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    os.makedirs(p._art, exist_ok=True)
    with open(os.path.join(p._art, "names.txt"), "w", encoding="utf8") as f:
        f.write("54\tS1E001_Clips.S1E001_00-18-32-21\n")
        f.write("2\tPhoneScenes.S1E005_00-03-30-09_LVL_7\n")
    _write_block(block, asset=54, verb=2)
    _poll(p)
    assert p.nm_text == "S1E001 00:18:32", p.nm_text
    # An off-shape name survives as itself.
    _write_block(block, asset=2, verb=2)
    _poll(p)
    assert "LVL_7" in p.nm_text, p.nm_text
    # An id with no name is blank, not "None".
    _write_block(block, asset=999, verb=2)
    _poll(p)
    assert p.nm_text == "", p.nm_text


def test_a_title_with_no_name_table_stays_silent(tmp_path, monkeypatch):
    """Every non-lcdnode title has no names.txt. That must be silent and
    must not cost a read per poll - the load is tried exactly once."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_block(block, asset=54, verb=2)
    _poll(p, times=8)
    assert p.nm_text == ""
    assert p._named is True and not p.names


def test_brightness_zero_blanks_the_screen(tmp_path, monkeypatch):
    """The 0x80 family (132 call sites): the game drops the TVs to 0 for
    ~250 ms around every clip swap. A panel that keeps showing footage
    while the wire says dark is unfaithful in the exact way this window
    exists to not be. 255 must bring the picture back. This still (a bare
    file still shown as-is, with no decoded picture behind it) has nothing
    to dissolve from, so the blank is INSTANT - the dissolve path has its
    own test below."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_png(p._art, "54.png")
    _write_block(block, asset=54, verb=2)
    _poll(p)
    assert p.item and p.item_state == "normal"
    assert p.dyn()["shown"] is True
    _write_block(block, asset=54, verb=2, bright=0)
    _poll(p)
    assert p.item_state == "hidden", \
        "wire says dark, panel still shows footage"
    assert p.dyn()["shown"] is False
    assert not p._fadeq, "a still with nothing to fade from queued a dissolve"
    _write_block(block, asset=54, verb=2, bright=255)
    _poll(p)
    assert p.item_state == "normal", \
        "brightness 255 did not restore the picture"
    assert p.item_img == p.img and p.dyn()["shown"] is True


def test_block_verb_once_holds_on_the_last_clip(tmp_path, monkeypatch):
    """verb 2 played the block through once: the screen must HOLD on the
    final clip's last frame, not wrap - a wrap here would loop footage the
    game asked to see exactly once."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    for i in (54, 55):
        _write_png(p._art, "%d.png" % i)
        _write_clip(p._art, "%d.webp" % i, ["red", "green"])
    _write_block(block, asset=54, aux=55, rate=12, verb=2)
    for _ in range(12):
        _poll(p)
    assert p.id == 55, "the block did not reach (or hold) its last clip"
    before = p.cap_text
    held = p.item_img
    for _ in range(6):
        _poll(p)
    assert p.id == 55 and p.cap_text == before, \
        "verb 2 wrapped instead of holding"
    assert p.item_img == held, "verb 2 kept playing past the block's end"


def test_bare_verb_is_shown_not_swallowed(tmp_path, monkeypatch):
    """Verbs 3, 4 and 5 arrive with no content and are almost certainly
    stop / pause / clear. v2 stored the byte in a field whose reader only
    had words for 1 and 2, so those three reached the caption as an empty
    string - a stop looked exactly like "carry on playing". The number must
    survive to the caption even though the word is unknown."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_block(block, asset=1736, verb=4)
    _poll(p)
    cap = p.cap_text
    assert "4" in cap.replace("1736", ""), \
        "a bare verb vanished from the caption: %r" % cap
    assert "loop" not in cap and "once" not in cap, \
        "an unknown verb was given a known word: %r" % cap
    assert p.dyn()["cap"] == cap


def test_art_landing_upgrades_the_placeholder(tmp_path, monkeypatch):
    """The lazy extraction's whole contract: the cell retries and swaps to
    the image once <art>/<id>.png exists, and the picture it shows is one
    the page can actually fetch (a BLOBS key with real PNG bytes)."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_block(block, asset=54)
    _poll(p)
    assert p.have is False
    assert p.placeholder == "asset 54" and not p.item
    _write_png(p._art, "54.png")
    _poll(p, times=10)                           # the ~1 Hz retry branch
    assert p.have is True, "art landed but the cell never upgraded"
    assert p.img is not None, "no picture recorded for the landed art"
    assert p.item and p.item_img == p.img and p.placeholder is None, \
        "the placeholder was not replaced by the picture"
    assert p.dyn()["pic"] == p.img and p.dyn()["placeholder"] is None
    # NATIVE SIZE was the headline of the own-window change and was
    # unasserted - re-adding subsample(2,2) or shrinking the screen kept
    # the suite green (review mutation test).
    assert _size(p.img) == (240, 180), "art no longer drawn at native size"
    assert _rgb(p.img, (120, 90)) == STILL_RGB
    # The window carries the TV cabinet as well as the screen, so it is
    # screen + padding - but the SCREEN must stay native, and the picture
    # must sit in it rather than in the middle of the case (the knob panel
    # is on one side only, so those differ). The page centres the picture
    # in spec()["screen"], so that rect is what is pinned here.
    L = playfield.LcdPanel
    spec = p.spec()
    assert spec["size"] == [L.CW + L.PAD_L + L.PAD_R,
                            L.CH + L.PAD_T + L.PAD_B]
    assert spec["screen"] == [L.PAD_L, L.PAD_T, L.CW, L.CH], \
        "the picture's screen is not the screen inside the case"
    assert (spec["cw"], spec["ch"]) == (L.CW, L.CH)


def test_asset_change_redraws_and_zero_is_idle(tmp_path, monkeypatch):
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_block(block, asset=54)
    _poll(p)
    _write_block(block, asset=3047)              # villain captured
    _poll(p)
    assert p.id == 3047
    assert p.placeholder == "asset 3047", p.placeholder
    assert ("lcdart.py", "batman", "3047") in p.drv.calls
    _write_block(block)                          # idle: nothing named
    _poll(p)
    assert p.id == 0
    assert p.cap_text == "idle"
    assert p.placeholder == "—", p.placeholder
    assert not any(c[2] == "0" for c in p.drv.calls)


def test_asset_change_replaces_the_previous_picture(tmp_path, monkeypatch):
    """The stale-cache fault in the header: an asset change must put the
    NEW asset's picture on the screen, never keep the previous one."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_png(p._art, "54.png", color=(255, 0, 0))
    _write_png(p._art, "3047.png", color=(0, 0, 255))
    _write_block(block, asset=54)
    _poll(p)
    assert _rgb(p.item_img, (120, 90)) == (255, 0, 0)
    _write_block(block, asset=3047)
    _poll(p)
    assert p.id == 3047
    assert _rgb(p.item_img, (120, 90)) == (0, 0, 255), \
        "an asset change kept showing the previous clip"


def test_cached_still_still_asks_for_motion(tmp_path, monkeypatch):
    """The stale-cache upgrade path: an asset whose PNG predates the clip
    stage must STILL ask lcdart.py - and ONE ask inside the backoff window,
    across a revisit too (review: membership alone could not tell one ask
    from an ask per _show entry)."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_png(p._art, "54.png")                 # cached still, no clip
    _write_block(block, asset=54)
    _poll(p)
    assert p.have is True, "cached still did not paint"
    assert ("lcdart.py", "batman", "54") in p.drv.calls, \
        "png-cached asset never asked for its motion"
    _write_png(p._art, "919.png")
    _write_block(block, asset=919)               # away...
    _poll(p, times=10)
    _write_block(block, asset=54)                # ...and back
    _poll(p, times=10)
    asks = [c for c in p.drv.calls if c[2] == "54"]
    assert len(asks) == 1, \
        "revisited asset re-asked inside the backoff: %r" % p.drv.calls


def test_clip_landing_animates_and_wraps(tmp_path, monkeypatch):
    """The motion contract: once <id>.webp lands, each poll advances one
    frame, frames cache as they decode, and the clip loops WITH THE REPLAY
    IN ORDER - the review proved the old distinct-count assertion stayed
    green with looping fully broken (freeze on the last frame draws three
    distinct frames too)."""
    import playfield as _pf
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_png(p._art, "54.png")
    _write_block(block, asset=54)
    _poll(p)
    assert p.anim is None, "animation started with no clip on disk"
    _write_clip(p._art, "54.webp", ["red", "green", "blue"])
    seen = []
    for _ in range(7):                           # two full loops + one
        _poll(p)
        seen.append(p.img)
    a = p.anim
    assert a is not None, "clip landed but the cell never animated"
    assert a["n"] == 3, "frame count not learned: %r" % a.get("n")
    assert len(a["frames"]) == 3, "lazy decode cached %d frames" % \
        len(a["frames"])
    assert seen[3] == seen[0] and seen[4] == seen[1], \
        "the clip did not loop in order: %r" % seen
    assert seen[0] != seen[1], "the drawn frame never advanced"
    assert [_rgb(k, (120, 90)) for k in seen[:3]] == \
        [(255, 0, 0), (0, 128, 0), (0, 0, 255)], \
        "the frames are not the clip's, in order"
    # One PERSISTENT picture, re-pointed per frame at the CACHED frame -
    # re-encoding (or re-storing) a picture per tick leaks one BLOBS entry
    # per frame at 10 Hz, the web window's version of a leaked canvas item.
    assert p.item is True and p.item_img == p.img
    n = _pf.BLOBS._n
    _poll(p, times=4)
    assert _pf.BLOBS._n == n, \
        "a looping clip stored %d new pictures" % (_pf.BLOBS._n - n)


def test_asset_change_resets_animation(tmp_path, monkeypatch):
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_png(p._art, "54.png")
    _write_clip(p._art, "54.webp", ["red", "green"])
    _write_block(block, asset=54)
    _poll(p, times=3)
    assert p.anim is not None
    # 54 is FULLY cached (png + webp): the ask guard must not have
    # spawned a subprocess for it - the review proved this negative
    # was unasserted, so an always-ask regression stayed green.
    assert not any(c[2] == "54" for c in p.drv.calls), \
        "fully-cached asset still asked lcdart: %r" % p.drv.calls
    _write_png(p._art, "919.png")                # still-only successor
    _write_block(block, asset=919)
    _poll(p)
    assert p.anim is None, "old clip's frames survived the change"
    assert p.id == 919 and p.have is True


def test_cached_still_with_late_driver_still_upgrades(tmp_path, monkeypatch):
    """THE motion review's headline: asset first seen while drv is None,
    with a cached still. The still paints, `have` latches True - and a
    `not have` retry gate then never re-entered _show, so the clip was
    never requested for the whole session (a mid-run window relaunch on an
    older cache hit this deterministically on the steady attract asset)."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_png(p._art, "54.png")                 # older cache
    p.drv = None                                 # window up before view
    _write_block(block, asset=54)
    _poll(p, times=10)
    assert p.have is True, "cached still did not paint"
    assert 54 not in p._asked, "driverless ask was swallowed for good"
    p.drv = FakeDrv()                            # the view arrives
    _poll(p, times=10)                           # a retry tick passes
    assert ("lcdart.py", "batman", "54") in p.drv.calls, \
        "still-cached cell never asked for its motion after drv landed"


def test_corrupt_still_does_not_block_motion(tmp_path, monkeypatch):
    """A torn/corrupt png must degrade to a placeholder, not veto the clip:
    the review caught _animate gated on `have`, which let one bad still
    permanently block a perfectly good clip."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    os.makedirs(p._art, exist_ok=True)
    with open(os.path.join(p._art, "54.png"), "wb") as f:
        f.write(b"not a png")                    # the torn write
    _write_clip(p._art, "54.webp", ["red", "green", "blue"])
    _write_block(block, asset=54)
    _poll(p, times=3)
    assert p.have is False, "corrupt still somehow decoded"
    a = p.anim
    assert a is not None and len(a["frames"]) >= 2, \
        "good clip blocked by a corrupt still"


def test_hidden_window_stops_the_decode_work(tmp_path, monkeypatch):
    """After the close box, the asset keeps tracking (cheap) but frames must
    stop advancing - the review measured the decode pass as the panel's one
    real cost, and it ran at full price for a window nobody could see."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    ctl = _controller(playfield, monkeypatch, FakeHost())
    ctl.lcd = p
    _write_png(p._art, "54.png")
    _write_clip(p._art, "54.webp", ["red", "green", "blue"])
    _write_block(block, asset=54)
    _poll(p, times=2)
    before = len(p.anim["frames"])
    shown = p.item_img
    ctl._lcd_closed()                            # the close box
    assert p._hidden is True
    _poll(p, times=4)
    assert len(p.anim["frames"]) == before, \
        "hidden window kept decoding frames"
    assert p.item_img == shown, "hidden window kept drawing frames"


def test_close_hides_and_polling_survives(tmp_path, monkeypatch):
    """Item 44's close contract carried over: the close box HIDES the
    window, the panel keeps polling behind it, and nothing resurrects it.
    Driven through the handler the controller REGISTERS when it opens the
    window, not LcdPanel.hide() directly - the review's mutation test
    deleted the registration and the old direct call kept the suite green
    while a live close box would have destroyed the window."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    host = FakeHost(geom={"lcd": (612, 208), "main": (40, 30)})
    ctl = _controller(playfield, monkeypatch, host)
    p.on_build = ctl._open_lcd
    ctl.lcd = p
    _write_block(block, asset=54)
    _poll(p)
    assert len(host.opened) == 1, "a stamped block did not open the window"
    name, spec, on_close = host.opened[0]
    assert name == "lcd" and spec["page"] == "lcd"
    assert "villain vision" in spec["title"]
    assert on_close, "the window has no registered close handler - the " \
                     "default would DESTROY it and the panel with it"
    assert p._hidden is False
    on_close()                                   # a real close-box click
    assert p._hidden is True
    with open(playfield.STATE) as f:
        assert json.load(f).get("villain_pos") == [612, 208], \
            "close did not record the window's position"
    _write_block(block, asset=3047)              # the wire moves on
    _poll(p)
    assert p.id == 3047, "hidden window stopped tracking the wire"
    assert p._hidden is True, "a change re-showed the window"
    assert len(host.opened) == 1 and not any(s for _n, s in host.shown), \
        "a change re-opened or re-showed the window"
    # The page's own close control lands in the same place - and it is the
    # one that also asks the host to hide the window.
    p.show_again()
    assert ctl.api_lcd_close() is True
    assert p._hidden is True
    assert host.shown == [("lcd", False)], host.shown


def test_position_persists_roundtrip(tmp_path, monkeypatch):
    """The own-window promise the review caught as FALSE, now real: opening
    the window restores villain_pos from the state file, save_state records
    it (beside the playfield's own)."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    with open(playfield.STATE, "w") as f:
        json.dump({"villain_pos": [473, 291]}, f)
    host = FakeHost()
    ctl = _controller(playfield, monkeypatch, host)
    p.on_build = ctl._open_lcd
    ctl.lcd = p
    _write_block(block, asset=54)
    _poll(p)
    assert len(host.opened) == 1
    spec = host.opened[0][1]
    assert (spec.get("x"), spec.get("y")) == (473, 291), \
        "saved position not restored (window spec %r)" % spec
    # The window moved; the page reports where both windows now sit.
    host.geom = {"lcd": (500, 320), "main": (12, 34)}
    ctl.save_state()
    with open(playfield.STATE) as f:
        st = json.load(f)
    assert st.get("villain_pos") == [500, 320], st
    assert st.get("playfield_pos") == [12, 34], st
    # ... and with no host geometry the page's last reported position
    # (api_geom) is what is saved.
    host.geom = {}
    ctl.api_geom("lcd", 77, 88)
    ctl.api_geom("main", 5, 6)
    ctl.save_state()
    with open(playfield.STATE) as f:
        st = json.load(f)
    assert st["villain_pos"] == [77, 88] and st["playfield_pos"] == [5, 6]


@pytest.mark.skipif(sys.platform != "win32",
                    reason="zorder/padwinpos bind Win32 at import (ctypes.WinDLL)")
def test_window_roles_disambiguate_villain_from_game2():
    """The villain window's title contains game2's needle in both window
    diagnostics; each must classify it under its OWN key or a stranded
    villain window steals the [display N] slot (review findings 2 and 3).

    WINDOWS ONLY, and importorskip was the wrong tool for saying so.
    zorder.py and padwinpos.py call ctypes.WinDLL at module scope and import
    ctypes.wintypes, so on Linux and macOS they raise AttributeError rather
    than ImportError - which importorskip does not catch. It read as a guard
    and was not one: this test passed locally and on windows-latest and took
    down ubuntu-latest and macos-latest on the v0.170.0 release push."""
    zorder = pytest.importorskip("zorder")
    assert zorder.role_of(
        "batman [villain vision] - Stern Spike 2 emulator") == "VILLAIN"
    assert zorder.role_of(
        "star_wars [display 2] - Stern Spike 2 emulator") == "GAME2"
    padwinpos = pytest.importorskip("padwinpos")
    keys = [k for k, _ in padwinpos.TRACK]
    assert keys.index("villain") < keys.index("game2")


def test_poll_chain_survives_an_exception(tmp_path, monkeypatch, capsys):
    """One bad poll (torn read, broken pipe under run_script) costs one
    tick, not the panel for the run. The review traced the pre-fix ordering
    - poll before reschedule, no guard - to a permanently dead VILLAIN
    VISION on any single uncaught error. The web window's loop is one
    thread driving every model (the LCD poll included) through _tick, and
    it must carry on past an exception."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    ctl = _controller(playfield, monkeypatch, FakeHost())
    ctl.lcd = p
    ctl.kind = "schematic"
    ctl._stop = threading.Event()
    calls = []

    def tick():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("torn read")
        ctl._stop.set()

    ctl._tick = tick
    done = threading.Thread(target=ctl._loop, daemon=True)
    done.start()
    done.join(5.0)
    assert not done.is_alive(), "the loop never finished"
    assert len(calls) == 2, "the loop did not re-arm past the exception"
    assert "torn read" in capsys.readouterr().err, \
        "the exception was swallowed without a trace"


def test_tick_drives_the_panel_and_publishes_its_changes(tmp_path, monkeypatch):
    """The loop's tick is what polls the panel now (the Tk after() chain is
    gone): a stamped block must reach the page as an "lcd" event, and a
    quiet panel must publish nothing."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    host = FakeHost()
    ctl = _controller(playfield, monkeypatch, host)
    ctl.lcd = p
    ctl.kind = None
    ctl.view = None
    _write_block(block, asset=1736, verb=2)
    ctl._tick()
    lcd = [d for e, d in host.published if e == "lcd"]
    assert lcd and lcd[-1]["placeholder"] == "asset 1736", host.published
    assert p.dirty is False
    host.published.clear()
    p._next = 0.0
    ctl._tick()
    assert not [e for e, _d in host.published if e == "lcd"], \
        "an unchanged panel republished"


# --- THE STILLS BOARD (measured from machine footage, 2026-08-26) -------
#
# The Villain Vision holds ONE stored still per command id and fades
# between them - the attract cycle is 11 stills matching the wire's
# 11-command rotation one-for-one, and gameplay rests on the logo card
# while the wire hammers asset 54. lcdstills.py derives the set + map;
# the MAP'S EXISTENCE is what switches the panel to stills mode. A title
# without a map keeps the clip player (every earlier test in this file).


def _write_map(art, rows):
    d = os.path.join(art, "stills")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "map.txt"), "w", encoding="utf8") as f:
        f.write("# test map\n")
        for i, fn, label in rows:
            f.write("%d\t%s\t%s\n" % (i, fn, label))
    return d


def _write_still(d, name, color="green", w=240, h=180):
    Image = _pil()
    Image.new("RGB", (w, h), color).save(os.path.join(d, name))


def _centre(key):
    w, h = _size(key)
    return _rgb(key, (w // 2, h // 2))


def test_mapped_id_shows_its_still_never_the_clip(tmp_path, monkeypatch):
    """The map is the measurement: command 54 must show the board's
    stored still (labelled), not clip 54 - even with the clip's own art
    sitting in the cache - and nothing may animate."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_png(p._art, "54.png")
    _write_clip(p._art, "54.webp", ["red", "blue"])
    d = _write_map(p._art, [(54, "logo.png", "BATMAN logo card")])
    _write_still(d, "logo.png")
    _write_block(block, asset=54, verb=2)
    _poll(p, times=6)
    assert p.id == 54 and p.have
    assert p.nm_text == "BATMAN logo card", p.nm_text
    assert p.anim is None, "a stills board opened a clip decoder"
    assert _centre(p.item_img) == (0, 128, 0), \
        "the screen shows something other than the board's still"


def test_unmapped_id_on_a_stills_board_stays_still(tmp_path, monkeypatch):
    """An id the map does not carry falls back to the clip's still frame,
    named from names.txt as before - but must NOT play the motion webp:
    the measurement is that this display never animates."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_png(p._art, "601.png")
    _write_clip(p._art, "601.webp", ["red", "blue"])
    d = _write_map(p._art, [(54, "logo.png", "BATMAN logo card")])
    _write_still(d, "logo.png")
    _write_block(block, asset=601, verb=2)
    _poll(p, times=6)
    assert p.id == 601 and p.have
    assert p.anim is None, "unmapped id animated on a stills board"
    assert _centre(p.item_img) == STILL_RGB, \
        "the clip's still frame is not what is shown"


def test_block_command_selects_by_its_first_id(tmp_path, monkeypatch):
    """The game-start block 919..928 shows the IN COLOR title card on the
    machine: on a stills board a block selects the FIRST id's still and
    nothing cycles."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    d = _write_map(p._art, [(919, "incolor.png", "BATMAN IN COLOR card")])
    _write_still(d, "incolor.png", "purple")
    _write_block(block, asset=919, aux=928, rate=12, verb=2)
    _poll(p, times=4)
    assert p.id == 919
    assert p.cycle is None, "a stills board cycled a block command"
    assert p.nm_text == "BATMAN IN COLOR card"
    assert _centre(p.item_img) == (128, 0, 128)


def test_still_swap_records_the_filmstrip_once(tmp_path, monkeypatch):
    """Attract steps the map one still per beat; each swap enters the
    filmstrip once (the 250 ms double-issue must not duplicate it)."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    d = _write_map(p._art, [(2, "go.png", "Game Over card"),
                            (54, "logo.png", "BATMAN logo card")])
    _write_still(d, "go.png", "blue")
    _write_still(d, "logo.png")
    _write_block(block, asset=2, verb=2)
    _poll(p, times=3)
    _write_block(block, asset=2, verb=2, dec=2)     # the re-issue
    _poll(p, times=2)
    _write_block(block, asset=54, verb=2, dec=3)
    _poll(p, times=3)
    assert [i for i, _ in p._recent] == [2, 54], p._recent
    assert [_centre(k) for _i, k in p._recent] == [(0, 0, 255), (0, 128, 0)]


def test_a_missing_still_file_falls_back_to_clip_art(tmp_path, monkeypatch):
    """A mapped id whose png is unreadable must not strand the screen on
    a placeholder while the clip art exists - card artwork heals lazily
    like everything else here."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_png(p._art, "54.png")
    _write_map(p._art, [(54, "gone.png", "BATMAN logo card")])
    _write_block(block, asset=54, verb=2)
    _poll(p, times=3)
    assert p.id == 54 and p.have, "missing still stranded the panel"
    assert p.placeholder is None and _centre(p.item_img) == STILL_RGB


def test_brightness_drop_dissolves_only_the_screen(tmp_path, monkeypatch):
    """The real set FADES through clip swaps (the wire's fade code 15) -
    but the SET ITSELF is a physical cabinet and must never dim or
    vanish: only the screen goes dark (tester report: "the TV outline
    should not be fading in and out"). With the card's TV composed into
    the image, every dissolve step keeps the picture VISIBLE - end state
    is a black screen in a lit set - and 255 restores the picture."""
    playfield, p, block = _panel(str(tmp_path), monkeypatch)
    _write_tv(p._art)                   # PIL path: _compose stashes
    _write_png(p._art, "54.png")        # the picture to fade from
    _write_block(block, asset=54, verb=2)
    _poll(p)
    assert p._pic_pil is not None
    held = p.img
    lit = [_rgb(held, (50, 37))[c] for c in range(3)]
    _write_block(block, asset=54, verb=2, bright=0)
    screens = []
    for k in range(4):                  # steps + dark end state
        _poll(p)
        assert p.item_state == "normal", \
            "the set vanished at dissolve step %d" % k
        assert _rgb(p.item_img, (5, 5)) == TV_RGB, \
            "the set dimmed at dissolve step %d" % k
        screens.append(_rgb(p.item_img, (50, 37)))
    assert not p._fadeq
    # the screen darkened step by step to black
    assert screens[-1] == (0, 0, 0), screens
    assert all(sum(a) <= sum(b) for a, b in zip(screens[1:], screens)), screens
    assert sum(screens[0]) < sum(lit), "the first step did not dim the screen"
    # the dark frame is the dissolve's own; the record of the picture stays
    assert p.item_img != held and p.img == held
    _write_block(block, asset=54, verb=2, bright=255)
    _poll(p)                            # instant reveal, real picture
    assert p.item_state == "normal"
    assert p.item_img == held
    assert not p._fadeq
