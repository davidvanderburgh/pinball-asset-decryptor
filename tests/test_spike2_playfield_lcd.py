"""LcdPanel: the VILLAIN VISION window draws what the padlcd block names.

Queue item 83. batman's lcdnode drives three playfield TVs by DISPLAY ID;
the shim publishes the ids into dump/padlcd and the panel maps id ->
<tables>/<game>/lcd/<id>.png, extracting art lazily. Since David's
2026-08-24 consistency ask the panel is its OWN Toplevel window - the same
shape as item 44's second-display windows - not a strip inside a view. The
faults these guard against: a window that builds on titles with no lcdnode
(every title would grow a stray black window), a placeholder that never
upgrades when the art lands (the lazy extraction would be invisible), an id
change that keeps showing the previous villain (stale cache reference), and
a close box that kills the window instead of hiding it (item 44's contract).

REAL Tk, like the hit-test and action-row tests: what is under test is
Toplevel construction, the WM_DELETE protocol, and PhotoImage lifetime -
the keep-a-reference rule is exactly the thing a stub Tk cannot see. The
padlcd block is a real temp file written with struct.pack, because the
offsets (magic 0, id[4] at 16) are hard-coded on both sides and a drifting
reader should fail HERE, not on a live run.
"""
import os
import struct
import sys
import types

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


def _write_block(path, ids, magic=MAGIC):
    d = struct.pack("<4I", magic, 1, 1, 1)
    d += struct.pack("<4I", *(list(ids) + [0] * (4 - len(ids))))
    d += b"\x00" * (48 - len(d))
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
    p = playfield.LcdPanel(root, "batman")
    p._art = os.path.join(tmp, "lcd")
    p.drv = FakeDrv()
    return playfield, p, block


def _poll(p, times=1):
    for _ in range(times):
        p._next = 0.0
        p.poll()


def test_no_lcdnode_title_never_builds(tmp_path, monkeypatch):
    """An unstamped (or absent) block must build NOTHING - this is what keeps
    every non-batman title free of a stray black window."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _poll(p)                                    # file absent
        assert p.win is None
        _write_block(block, [54], magic=0)          # present but unstamped
        _poll(p)
        assert p.win is None
    finally:
        root.destroy()


def test_stamped_block_builds_window_and_requests_art(tmp_path, monkeypatch):
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, [54, 919, 928])
        _poll(p)
        assert p.win is not None, "magic stamped but no window"
        assert "villain vision" in p.win.title()
        # The title must land in padwinpos's "game2" family so the window's
        # position persists like any item 44 second display.
        assert "] - Stern Spike 2 emulator" in p.win.title()
        assert p.ids[:3] == [54, 919, 928]
        assert not any(p.have)
        asked = {c[2] for c in p.drv.calls if c[0] == "lcdart.py"}
        assert asked == {"54", "919", "928"}, p.drv.calls
        # a second poll must NOT re-request the same ids
        _poll(p)
        assert len(p.drv.calls) == 3
    finally:
        root.destroy()


def test_art_landing_upgrades_the_placeholder(tmp_path, monkeypatch):
    """The lazy extraction's whole contract: the cell retries and swaps to
    the image once <art>/<id>.png exists, keeping a PhotoImage reference."""
    root = _root()
    try:
        import tkinter as tk
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, [54])
        _poll(p)
        assert p.have[0] is False
        os.makedirs(p._art)
        img = tk.PhotoImage(width=240, height=180)   # a real 240x180 PNG
        img.write(os.path.join(p._art, "54.png"), format="png")
        _poll(p, times=10)                           # the ~1 Hz retry branch
        assert p.have[0] is True, "art landed but the cell never upgraded"
        assert p.imgs[0] is not None, "PhotoImage reference not kept"
    finally:
        root.destroy()


def test_id_change_redraws_and_id_zero_is_idle(tmp_path, monkeypatch):
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, [54])
        _poll(p)
        _write_block(block, [3047])                  # villain captured
        _poll(p)
        assert p.ids[0] == 3047
        assert ("lcdart.py", "batman", "3047") in p.drv.calls
        _write_block(block, [0])                     # idle: nothing to fetch
        _poll(p)
        assert p.ids[0] == 0
        assert not any(c[2] == "0" for c in p.drv.calls)
    finally:
        root.destroy()


def _write_png(art_dir, name):
    import tkinter as tk
    os.makedirs(art_dir, exist_ok=True)
    img = tk.PhotoImage(width=240, height=180)
    img.write(os.path.join(art_dir, name), format="png")


def _write_gif(art_dir, name, colors):
    """A real multi-frame GIF - PIL authors it, Tk plays it, exactly the
    hand-off lcdart.py's ffmpeg stage performs."""
    Image = pytest.importorskip("PIL.Image")
    os.makedirs(art_dir, exist_ok=True)
    frames = [Image.new("RGB", (240, 180), c) for c in colors]
    frames[0].save(os.path.join(art_dir, name), save_all=True,
                   append_images=frames[1:], loop=0, duration=100)


def test_cached_still_still_asks_for_motion(tmp_path, monkeypatch):
    """The stale-cache upgrade path: an id whose PNG predates the GIF stage
    must STILL ask lcdart.py once - the old png-only test here left every
    pre-motion cache frozen for ever."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_png(p._art, "54.png")                 # cached still, no gif
        _write_block(block, [54])
        _poll(p)
        assert p.have[0] is True, "cached still did not paint"
        assert ("lcdart.py", "batman", "54") in p.drv.calls, \
            "png-cached id never asked for its motion"
    finally:
        root.destroy()


def test_gif_landing_animates_and_wraps(tmp_path, monkeypatch):
    """The motion contract: once <id>.gif lands, each poll advances one
    frame, frames cache as they decode, and the clip loops at its end."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_png(p._art, "54.png")
        _write_block(block, [54])
        _poll(p)
        assert p.anim[0] is None, "animation started with no gif on disk"
        _write_gif(p._art, "54.gif", ["red", "green", "blue"])
        seen = []
        for _ in range(7):                          # 3 frames + wrap + reuse
            _poll(p)
            seen.append(p.imgs[0])
        a = p.anim[0]
        assert a is not None, "gif landed but the cell never animated"
        assert len(a["frames"]) == 3, "lazy decode cached %d frames" % \
            len(a["frames"])
        assert a["done"] is True, "clip end never detected"
        assert len({id(s) for s in seen}) == 3, \
            "7 polls drew %d distinct frames, not the 3-frame loop" % \
            len({id(s) for s in seen})
        assert seen[0] is not seen[1], "the drawn frame never advanced"
    finally:
        root.destroy()


def test_id_change_resets_animation(tmp_path, monkeypatch):
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_png(p._art, "54.png")
        _write_gif(p._art, "54.gif", ["red", "green"])
        _write_block(block, [54])
        _poll(p, times=3)
        assert p.anim[0] is not None
        _write_png(p._art, "919.png")               # still-only successor
        _write_block(block, [919])
        _poll(p)
        assert p.anim[0] is None, "old clip's frames survived the id change"
        assert p.ids[0] == 919 and p.have[0] is True
    finally:
        root.destroy()


def test_close_hides_and_polling_survives(tmp_path, monkeypatch):
    """Item 44's close contract carried over: the close box WITHDRAWS the
    window, the panel keeps polling behind it, and nothing resurrects it."""
    root = _root()
    try:
        playfield, p, block = _panel(root, str(tmp_path), monkeypatch)
        _write_block(block, [54])
        _poll(p)
        assert p.win.state() != "withdrawn"
        p._hide()                                    # the WM_DELETE handler
        assert p.win.state() == "withdrawn"
        _write_block(block, [3047])                  # ids move while hidden
        _poll(p)
        assert p.ids[0] == 3047, "hidden window stopped tracking ids"
        assert p.win.state() == "withdrawn", "an id change re-showed the window"
    finally:
        root.destroy()
