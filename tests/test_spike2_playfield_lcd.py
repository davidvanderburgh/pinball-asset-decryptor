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

REAL Tk, like the hit-test and action-row tests: what is under test is
Toplevel construction, the WM_DELETE protocol, and PhotoImage lifetime -
the keep-a-reference rule is exactly the thing a stub Tk cannot see. The
padlcd block is a real temp file written with struct.pack, because the
offsets are hard-coded on both sides and a drifting reader should fail
HERE, not on a live run.
"""
import os
import struct
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

MAGIC = 0x44434c50


def _root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:                          # no display / no Tcl
        pytest.skip("Tk unavailable: %s" % exc)
    root.attributes("-alpha", 0)
    return root


def _write_block(path, asset=0, aux=0, rate=0, verb=0, bright=255, magic=MAGIC):
    """The v4 page: magic, version, gen, decoded, then the one display's
    state (asset, aux, rate, verb, x1, x2, x3, bright, fade, ms). bright
    defaults to 255 exactly as the shim stamps it at map time - 0 means
    "the game commanded dark" and blanks the panel, so a helper defaulting
    to 0 would run every test in the dark."""
    d = struct.pack("<14I", magic, 4, 1, 1,
                    asset, aux, rate, verb, 0, 0, 0, bright, 15, 0)
    with open(path, "wb") as f:
        f.write(d + b"\x00" * (4096 - len(d)))


class FakeDrv:
    def __init__(self):
        self.calls = []

    def run_script(self, *a):
        self.calls.append(a)


def _panel(root, tmp, monkeypatch):
    import playfield
    block = os.path.join(tmp, "padlcd")
    monkeypatch.setattr(playfield, "LCD_PATH", block)
    # The state file too: _build restores villain_pos from it and _hide
    # writes it - the tests must never touch the user's real one.
    monkeypatch.setattr(playfield, "STATE", os.path.join(tmp, "state.json"))
    p = playfield.LcdPanel(root, "batman")
    p._art = os.path.join(tmp, "lcd")
    p.drv = FakeDrv()
    return playfield, p, block


def _poll(p, times=1):
    for _ in range(times):
        p._next = 0.0
        p.poll()


def _write_png(art_dir, name):
    import tkinter as tk
    os.makedirs(art_dir, exist_ok=True)
    img = tk.PhotoImage(width=240, height=180)
    img.write(os.path.join(art_dir, name), format="png")


def _write_clip(art_dir, name, colors):
    """A real multi-frame lossless WebP - PIL authors it, PIL plays it,
    exactly the hand-off lcdart.py's ffmpeg stage performs. Lossless so a
    frame's colour comes back EXACTLY, which is the point of the format
    (the GIF it replaced dithered a 256-colour palette and David caught it
    on the glass within a minute)."""
    Image = pytest.importorskip("PIL.Image")
    os.makedirs(art_dir, exist_ok=True)
    frames = [Image.new("RGB", (240, 180), c) for c in colors]
    frames[0].save(os.path.join(art_dir, name), save_all=True,
                   append_images=frames[1:], loop=0, duration=100,
                   lossless=True)


def test_no_lcdnode_title_never_builds(tmp_path, monkeypatch):
    """An unstamped (or absent) block must build NOTHING - this is what keeps
    every non-batman title free of a stray black window."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _poll(p)                                    # file absent
        assert p.win is None
        _write_block(block, asset=54, magic=0)      # present but unstamped
        _poll(p)
        assert p.win is None
    finally:
        root.destroy()


def test_stamped_block_builds_window_and_requests_art(tmp_path, monkeypatch):
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, asset=1736, verb=2)
        _poll(p)
        assert p.win is not None, "magic stamped but no window"
        assert "villain vision" in p.win.title()
        # The title must land in the item 44 second-display family so
        # screenrec skips it and the window diagnostics name it correctly.
        assert "] - Stern Spike 2 emulator" in p.win.title()
        assert p.id == 1736
        assert p.have is False
        assert [c[2] for c in p.drv.calls] == ["1736"], p.drv.calls
        # ONE screen: nothing may reintroduce per-cell state.
        assert not isinstance(p.id, (list, tuple))
        # Later polls must NOT re-request. times=10 on purpose: it drives
        # _polls across the %10 retry branch, so _show actually re-runs with
        # the art still missing and only the backoff holds the count at 1.
        _poll(p, times=10)
        assert len(p.drv.calls) == 1
    finally:
        root.destroy()


def test_block_command_starts_at_its_first_clip(tmp_path, monkeypatch):
    """v1 drew this frame as three display ids (54, 928 and 106 - a rate
    code - side by side); v2 captioned it "range" off one capture. The
    reading that SURVIVED the disassembly: asset..aux is an inclusive clip
    block (the game's duration helper 0x37e2fc computes last-first+1 x a
    period), the panel starts at its first clip and fetches ONLY that one -
    928 and 106 must still never be fetched as if they were assets.
    """
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, asset=54, aux=928, rate=12, verb=1)
        _poll(p)
        assert p.id == 54, "the block's first clip was not drawn"
        assert p.cycle == (54, 928)
        assert [c[2] for c in p.drv.calls] == ["54"], \
            "block end / rate fetched as if they were assets: %r" \
            % p.drv.calls
        cap = p.cap["text"]
        assert "assets 54-928" in cap and "12 fps" in cap, cap
        assert "loop" in cap, cap
        # ... and a plain single-asset command must clear the block.
        _write_block(block, asset=3004, verb=2)
        _poll(p)
        assert p.id == 3004 and p.cycle is None
        cap = p.cap["text"]
        assert "3004" in cap and "928" not in cap and "once" in cap, cap
    finally:
        root.destroy()


def test_block_cycles_clip_by_clip_and_wraps_on_loop(tmp_path, monkeypatch):
    """The block's whole point: when a clip ends the NEXT id in the block
    takes the screen, and verb 1 wraps the block's end back to its first
    clip. The command stays on the wire unchanged throughout - the panel
    must advance itself, and a poll must not snap the drawn id back to the
    block's start mid-cycle."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
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
        cap = p.cap["text"]
        assert "assets 54-56" in cap and "showing" in cap, cap
    finally:
        root.destroy()


def test_single_clip_verb_once_holds_not_loops(tmp_path, monkeypatch):
    """verb 2 = play ONCE. The panel looped every single clip regardless,
    which showed motion during the long tail the real TV spends holding a
    one-shot's last frame - the game re-commands the display each attract
    beat precisely because one-shots END. verb 1 must still loop."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_png(p._art, "54.png")
        _write_clip(p._art, "54.webp", ["red", "green"])
        _write_block(block, asset=54, verb=2)
        for _ in range(3):
            _poll(p)                        # plays through the 2 frames
        frozen = p.anim["i"]
        for _ in range(5):
            _poll(p)
        assert p.anim["i"] == frozen, "a one-shot clip wrapped"
        # ... and the same clip under verb 1 loops again.
        _write_block(block, asset=54, verb=1)
        for _ in range(4):
            _poll(p)
        assert p.anim["i"] != frozen or p.anim["i"] <= 2, \
            "verb 1 did not resume looping"
    finally:
        root.destroy()


def _write_tv(art_dir, w=120, h=100, hole=(20, 15, 60, 45)):
    """A stand-in for the card's TV sprite: opaque, with a transparent
    rectangular screen hole - the shape lcdframe.py pulls off the card."""
    Image = pytest.importorskip("PIL.Image")
    os.makedirs(art_dir, exist_ok=True)
    tv = Image.new("RGBA", (w, h), (90, 60, 40, 255))
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
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_tv(p._art)
        _write_png(p._art, "54.png")
        _write_block(block, asset=54, verb=2)
        _poll(p)
        assert p.tv is not None and p.tv_hole == (20, 15, 60, 45)
        # The canvas is the SET's size, and the composed image fills it.
        assert int(p.cv["width"]) == 120 and int(p.cv["height"]) == 100
        assert (p.img.width(), p.img.height()) == (120, 100)
        # No hand-drawn cabinet when real art exists.
        assert not p.cv.find_withtag("case"), "drew a cabinet over card art"
        # Aspect kept: a 240x180 clip into a 60x45 hole fits exactly; make
        # the hole square and the clip must letterbox, not stretch.
        p2 = playfield.LcdPanel(root, "batman")
        p2._art = p._art
        p2._load_tv()
        p2.tv_hole = (20, 15, 60, 60)
        composed = p2._compose(_PILImage_new(240, 180))
        assert (composed.width(), composed.height()) == (120, 100)
    finally:
        root.destroy()


def _PILImage_new(w, h):
    Image = pytest.importorskip("PIL.Image")
    return Image.new("RGB", (w, h), "red")


def test_no_card_art_falls_back_to_the_drawn_cabinet(tmp_path, monkeypatch):
    """Every title without the texture - and any run with no card mounted -
    must still get a TV, not a bare rectangle."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, asset=54, verb=2)
        _poll(p)
        assert p.tv is None
        assert p.cv.find_withtag("case"), "no card art and no drawn cabinet"
    finally:
        root.destroy()


def test_filmstrip_records_the_sequence_without_duplicates(tmp_path, monkeypatch):
    """The strip answers the question one frame never can: WHAT PLAYED, in
    order. Two rules it must hold - the game re-issues every attract
    command ~250 ms later, so a re-send must NOT add a second entry; and a
    clip with no art must not enter the history as a placeholder."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
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
    finally:
        root.destroy()


def test_clip_name_is_shown_and_formatted(tmp_path, monkeypatch):
    """The card's own scene file names every villain clip by episode and
    timecode (lcdnames.py). Showing it is the only independent check on the
    id->clip mapping there has ever been - and the only form a person can
    hold up against a real Villain Vision. The raw name is a mouthful, so
    it is trimmed to "S1E001 00:18:32"; anything not of that shape must
    still be shown rather than mangled or dropped."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        os.makedirs(p._art, exist_ok=True)
        with open(os.path.join(p._art, "names.txt"), "w", encoding="utf8") as f:
            f.write("54\tS1E001_Clips.S1E001_00-18-32-21\n")
            f.write("2\tPhoneScenes.S1E005_00-03-30-09_LVL_7\n")
        _write_block(block, asset=54, verb=2)
        _poll(p)
        assert p.nm["text"] == "S1E001 00:18:32", p.nm["text"]
        # An off-shape name survives as itself.
        _write_block(block, asset=2, verb=2)
        _poll(p)
        assert "LVL_7" in p.nm["text"], p.nm["text"]
        # An id with no name is blank, not "None".
        _write_block(block, asset=999, verb=2)
        _poll(p)
        assert p.nm["text"] == "", p.nm["text"]
    finally:
        root.destroy()


def test_a_title_with_no_name_table_stays_silent(tmp_path, monkeypatch):
    """Every non-lcdnode title has no names.txt. That must be silent and
    must not cost a read per poll - the load is tried exactly once."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, asset=54, verb=2)
        _poll(p, times=8)
        assert p.nm["text"] == ""
        assert p._named is True and not p.names
    finally:
        root.destroy()


def test_brightness_zero_blanks_the_screen(tmp_path, monkeypatch):
    """The 0x80 family (132 call sites): the game drops the TVs to 0 for
    ~250 ms around every clip swap. A panel that keeps showing footage
    while the wire says dark is unfaithful in the exact way this window
    exists to not be. 255 must bring the picture back."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_png(p._art, "54.png")
        _write_block(block, asset=54, verb=2)
        _poll(p)
        assert p.cv.itemcget(p.item, "state") in ("", "normal")
        _write_block(block, asset=54, verb=2, bright=0)
        _poll(p)
        assert p.cv.itemcget(p.item, "state") == "hidden", \
            "wire says dark, panel still shows footage"
        _write_block(block, asset=54, verb=2, bright=255)
        _poll(p)
        assert p.cv.itemcget(p.item, "state") == "normal", \
            "brightness 255 did not restore the picture"
    finally:
        root.destroy()


def test_block_verb_once_holds_on_the_last_clip(tmp_path, monkeypatch):
    """verb 2 played the block through once: the screen must HOLD on the
    final clip's last frame, not wrap - a wrap here would loop footage the
    game asked to see exactly once."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        for i in (54, 55):
            _write_png(p._art, "%d.png" % i)
            _write_clip(p._art, "%d.webp" % i, ["red", "green"])
        _write_block(block, asset=54, aux=55, rate=12, verb=2)
        for _ in range(12):
            _poll(p)
        assert p.id == 55, "the block did not reach (or hold) its last clip"
        before = p.cap["text"]
        for _ in range(6):
            _poll(p)
        assert p.id == 55 and p.cap["text"] == before, \
            "verb 2 wrapped instead of holding"
    finally:
        root.destroy()


def test_bare_verb_is_shown_not_swallowed(tmp_path, monkeypatch):
    """Verbs 3, 4 and 5 arrive with no content and are almost certainly
    stop / pause / clear. v2 stored the byte in a field whose reader only
    had words for 1 and 2, so those three reached the caption as an empty
    string - a stop looked exactly like "carry on playing". The number must
    survive to the caption even though the word is unknown."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, asset=1736, verb=4)
        _poll(p)
        cap = p.cap["text"]
        assert "4" in cap.replace("1736", ""), \
            "a bare verb vanished from the caption: %r" % cap
        assert "loop" not in cap and "once" not in cap, \
            "an unknown verb was given a known word: %r" % cap
    finally:
        root.destroy()


def test_art_landing_upgrades_the_placeholder(tmp_path, monkeypatch):
    """The lazy extraction's whole contract: the cell retries and swaps to
    the image once <art>/<id>.png exists, keeping a PhotoImage reference."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, asset=54)
        _poll(p)
        assert p.have is False
        _write_png(p._art, "54.png")
        _poll(p, times=10)                           # the ~1 Hz retry branch
        assert p.have is True, "art landed but the cell never upgraded"
        assert p.img is not None, "PhotoImage reference not kept"
        # NATIVE SIZE was the headline of the own-window change and was
        # unasserted - re-adding subsample(2,2) or shrinking the canvas kept
        # the suite green (review mutation test).
        assert (p.img.width(), p.img.height()) == (240, 180), \
            "art no longer drawn at native size"
        # The canvas now carries the TV cabinet as well as the screen, so it
        # is screen + padding - but the SCREEN must stay native, and the
        # picture must sit in it rather than in the middle of the case (the
        # knob panel is on one side only, so those differ).
        L = playfield.LcdPanel
        assert int(p.cv["width"]) == L.CW + L.PAD_L + L.PAD_R
        assert int(p.cv["height"]) == L.CH + L.PAD_T + L.PAD_B
        assert p.cv.coords(p.item) == list(p._screen_mid()), \
            "the picture is not centred in the screen"
    finally:
        root.destroy()


def test_asset_change_redraws_and_zero_is_idle(tmp_path, monkeypatch):
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, asset=54)
        _poll(p)
        _write_block(block, asset=3047)              # villain captured
        _poll(p)
        assert p.id == 3047
        assert ("lcdart.py", "batman", "3047") in p.drv.calls
        _write_block(block)                          # idle: nothing named
        _poll(p)
        assert p.id == 0
        assert p.cap["text"] == "idle"
        assert not any(c[2] == "0" for c in p.drv.calls)
    finally:
        root.destroy()


def test_cached_still_still_asks_for_motion(tmp_path, monkeypatch):
    """The stale-cache upgrade path: an asset whose PNG predates the clip
    stage must STILL ask lcdart.py - and ONE ask inside the backoff window,
    across a revisit too (review: membership alone could not tell one ask
    from an ask per _show entry)."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
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
    finally:
        root.destroy()


def test_clip_landing_animates_and_wraps(tmp_path, monkeypatch):
    """The motion contract: once <id>.webp lands, each poll advances one
    frame, frames cache as they decode, and the clip loops WITH THE REPLAY
    IN ORDER - the review proved the old distinct-count assertion stayed
    green with looping fully broken (freeze on the last frame draws three
    distinct frames too)."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
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
        assert seen[3] is seen[0] and seen[4] is seen[1], \
            "the clip did not loop in order: %r" % [id(s) for s in seen]
        assert seen[0] is not seen[1], "the drawn frame never advanced"
        # One PERSISTENT picture item, reconfigured per frame - a
        # delete/create pair per tick leaks an item per frame at 10 Hz.
        # Tag-scoped since the canvas also carries the TV cabinet: the
        # cabinet must be drawn ONCE and the picture must not multiply.
        pics = p.cv.find_withtag("pic")
        assert len(pics) == 1, "%d picture items after 7 draws" % len(pics)
        case = len(p.cv.find_withtag("case"))
        _poll(p, times=4)
        assert len(p.cv.find_withtag("case")) == case, \
            "the cabinet was redrawn while the clip played"
    finally:
        root.destroy()


def test_asset_change_resets_animation(tmp_path, monkeypatch):
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
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
    finally:
        root.destroy()


def test_cached_still_with_late_driver_still_upgrades(tmp_path, monkeypatch):
    """THE motion review's headline: asset first seen while drv is None,
    with a cached still. The still paints, `have` latches True - and a
    `not have` retry gate then never re-entered _show, so the clip was
    never requested for the whole session (a mid-run window relaunch on an
    older cache hit this deterministically on the steady attract asset)."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
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
    finally:
        root.destroy()


def test_corrupt_still_does_not_block_motion(tmp_path, monkeypatch):
    """A torn/corrupt png must degrade to a placeholder, not veto the clip:
    the review caught _animate gated on `have`, which let one bad still
    permanently block a perfectly good clip."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
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
    finally:
        root.destroy()


def test_hidden_window_stops_the_decode_work(tmp_path, monkeypatch):
    """After the close box, the asset keeps tracking (cheap) but frames must
    stop advancing - the review measured the decode pass as the panel's one
    real cost, and it ran at full price for a window nobody could see."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_png(p._art, "54.png")
        _write_clip(p._art, "54.webp", ["red", "green", "blue"])
        _write_block(block, asset=54)
        _poll(p, times=2)
        before = len(p.anim["frames"])
        p.win.tk.eval(p.win.protocol("WM_DELETE_WINDOW"))
        assert p._hidden is True
        _poll(p, times=4)
        assert len(p.anim["frames"]) == before, \
            "hidden window kept decoding frames"
    finally:
        root.destroy()


def test_close_hides_and_polling_survives(tmp_path, monkeypatch):
    """Item 44's close contract carried over: the close box WITHDRAWS the
    window, the panel keeps polling behind it, and nothing resurrects it.
    Driven through the REGISTERED WM_DELETE handler, not _hide() directly -
    the review's mutation test deleted the protocol() registration and the
    old direct call kept the suite green while a live close box would have
    destroyed the Toplevel."""
    root = _root()
    try:
        import json
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, asset=54)
        _poll(p)
        assert p.win.state() != "withdrawn"
        cmd = p.win.protocol("WM_DELETE_WINDOW")
        assert cmd, "close box has no registered handler - Tk's default " \
                    "would DESTROY the window and kill the poll loop"
        p.win.tk.eval(cmd)                           # a real close-box click
        assert p.win.state() == "withdrawn"
        with open(playfield.STATE) as f:
            assert "villain_pos" in json.load(f), \
                "close did not record the window's position"
        _write_block(block, asset=3047)              # the wire moves on
        _poll(p)
        assert p.id == 3047, "hidden window stopped tracking the wire"
        assert p.win.state() == "withdrawn", "a change re-showed the window"
    finally:
        root.destroy()


def test_position_persists_roundtrip(tmp_path, monkeypatch):
    """The own-window promise the review caught as FALSE, now real: _build
    restores villain_pos from the state file, save_state records it."""
    root = _root()
    try:
        import json
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        with open(playfield.STATE, "w") as f:
            json.dump({"villain_pos": [473, 291]}, f)
        _write_block(block, asset=54)
        _poll(p)
        root.update()
        assert abs(p.win.winfo_x() - 473) < 45 and \
               abs(p.win.winfo_y() - 291) < 60, \
            "saved position not restored (window at +%d+%d)" % (
                p.win.winfo_x(), p.win.winfo_y())
        playfield.save_state(root, p)
        st = json.load(open(playfield.STATE))
        assert "villain_pos" in st and "playfield_pos" in st
    finally:
        root.destroy()


def test_window_roles_disambiguate_villain_from_game2():
    """The villain window's title contains game2's needle in both window
    diagnostics; each must classify it under its OWN key or a stranded
    villain window steals the [display N] slot (review findings 2 and 3)."""
    zorder = pytest.importorskip("zorder")
    assert zorder.role_of(
        "batman [villain vision] - Stern Spike 2 emulator") == "VILLAIN"
    assert zorder.role_of(
        "star_wars [display 2] - Stern Spike 2 emulator") == "GAME2"
    padwinpos = pytest.importorskip("padwinpos")
    keys = [k for k, _ in padwinpos.TRACK]
    assert keys.index("villain") < keys.index("game2")


def test_poll_chain_survives_an_exception(tmp_path, monkeypatch):
    """start() reschedules in a finally: one bad poll (torn read, broken
    pipe under run_script) costs one tick, not the panel for the run. The
    review traced the pre-fix ordering - poll before reschedule, no guard -
    to a permanently dead VILLAIN VISION on any single uncaught error."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)

        def boom():
            raise RuntimeError("torn read")

        p.poll = boom
        with pytest.raises(RuntimeError):
            p.start()
        pending = root.tk.eval("after info")
        assert pending, "the poll chain did not re-arm past the exception"
        for aid in pending.split():
            root.after_cancel(aid)
    finally:
        root.destroy()
