"""The boot menu's buttons, BY NAME - so a title's first run has a keyboard.

David, 2026-09-19, on a multi-image card's first start on a fresh runtime:
"the first time loading a multi image won't let me use arrow keys (or select)
since the virtual playfield isn't initialized yet."

WHAT WAS WRONG, in three places at once. The keyboard reaches the game through
the TITLE'S OWN switch ids, and a title's ids come from a list built out of the
game's run - about a minute into its first start. The boot menu runs BEFORE that
game. So on a first run (1) the menu had no id for the flippers or Action,
(2) padglhost refuses to publish a playfield key on another title's ids (item
49) and so had nothing for the arrows, and (3) the virtual playfield, showing
"WAITING for tables", had no key handler at all because every one hangs off a
view. The menu's own log said it plainly: no `key:` line in 30 s, then
`countdown expired`.

THE FIX is a fixed-order region at the end of the switch block, padsw.h's
`cab[]` / `scr_cab[]`: the menu's eight buttons held BY NAME, written by
padglhost (keyboard) and by the playfield's helper (scripts), read by the menu,
never read by the game path. That is four copies of one layout and two copies
of one key table in three languages, and this file is what keeps them the same
fact: a drift fails here in a second instead of as one dead key on a machine.

The routing logic (KeyInput, swkeys) is tested with fakes - what is under test
is which edge goes where, not Tk's delivery. The menu's own behaviour is
codeselect/test/padsw_test.py (`make check`, under qemu).
"""
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)


def _text(*parts):
    with open(os.path.join(RIG, *parts), encoding="utf8", newline="") as f:
        return f.read()


@pytest.fixture
def padsw():
    import padsw as mod
    return mod


@pytest.fixture
def keybinds():
    import keybinds as mod
    return mod


# --- one layout, four copies -------------------------------------------------

def test_the_python_offsets_follow_the_end_of_the_block(padsw):
    assert padsw.CAB_N == 8
    assert padsw.OFF_CAB == padsw.OFF_SPIN + padsw.MAX_ID
    assert padsw.OFF_SCR_CAB == padsw.OFF_CAB + padsw.CAB_N
    assert padsw.OFF_PAUSED == padsw.OFF_SCR_CAB + padsw.CAB_N    # PAD-204
    assert padsw.OFF_PAUSE_REQ == padsw.OFF_PAUSED_MS + 4
    assert padsw.SIZE == padsw.OFF_PAUSE_REQ + 4
    assert padsw.SIZE <= 4096


@pytest.mark.skipif(not shutil.which("gcc"), reason="no C compiler")
def test_padsw_h_agrees_with_the_python_offsets(padsw, tmp_path):
    """The header is the definition; ask the COMPILER where the fields sit."""
    src = tmp_path / "layout.c"
    src.write_text('#include <stdio.h>\n#include <stddef.h>\n#include "padsw.h"\n'
                   'int main(void){printf("%zu %zu %zu %zu\\n", '
                   'offsetof(struct padsw_shm, spin), offsetof(struct padsw_shm, cab), '
                   'offsetof(struct padsw_shm, scr_cab), sizeof(struct padsw_shm));'
                   'return 0;}\n')
    exe = tmp_path / "layout"
    subprocess.run(["gcc", "-std=gnu17", "-I", RIG, "-o", str(exe), str(src)], check=True)
    spin, cab, scr_cab, size = (int(x) for x in
                                subprocess.run([str(exe)], check=True, capture_output=True,
                                               text=True).stdout.split())
    assert spin == padsw.OFF_SPIN
    assert cab == padsw.OFF_CAB
    assert scr_cab == padsw.OFF_SCR_CAB
    assert size == padsw.SIZE


def test_the_menu_reads_the_same_offsets(padsw):
    """codeselect is a separate program (ARM, built on the rig) that does not
    include padsw.h, so its offsets are a third copy."""
    c = _text("codeselect", "input_padsw.c")
    assert int(re.search(r"#define OFF_CAB\s+(\d+)", c).group(1)) == padsw.OFF_CAB
    assert int(re.search(r"#define OFF_SCR_CAB\s+(\d+)", c).group(1)) == padsw.OFF_SCR_CAB


def test_the_shim_mirror_carries_the_fields(padsw):
    """hwshim.c is built -nostdlib with its own hand-kept copy of the struct."""
    c = _text("hwshim.c")
    body = re.search(r"struct padsw_shm \{(.*?)\n\};", c, re.S).group(1)
    assert "unsigned char cab[8]; unsigned char scr_cab[8];" in body
    tail = body.rstrip().splitlines()[-1]           # PAD-204's pause is last now
    assert "unsigned paused; unsigned paused_ms; unsigned pause_req;" in tail
    assert "spin[256]" in body                      # ...and after the last old field
    assert body.index("spin[256]") < body.index("cab[8]")


def test_the_button_order_is_one_fact(padsw):
    """padsw.h's PADSW_CAB_*, padsw.py's CAB_NAMES and the menu's key order
    (KEY_OF(EV_*)) - the by-name byte k IS menu key k."""
    hdr = _text("padsw.h")
    named = {int(v): n.lower() for n, v in
             re.findall(r"#define PADSW_CAB_(\w+)\s+(\d+)", hdr) if n != "N"}
    assert [named[i] for i in sorted(named)] == list(padsw.CAB_NAMES)
    assert int(re.search(r"#define PADSW_CAB_N\s+(\d+)", hdr).group(1)) == len(padsw.CAB_NAMES)
    enum = re.search(r"enum sel_event \{(.*?)\};", _text("codeselect", "input.h"), re.S).group(1)
    events = [e.split("=")[0].strip() for e in enum.replace("\n", " ").split(",") if e.strip()]
    assert events[0] == "EV_NONE" and events[-1] == "EV_COUNT"
    assert [e[3:].lower() for e in events[1:-1]] == list(padsw.CAB_NAMES)


# --- one key table, two copies ------------------------------------------------

#: the X11 keysym values, written out here as the independent oracle
_XKEYSYM = {"Left": 0xff51, "Right": 0xff53, "1": 0x31, "Space": 0x20,
            "Enter": 0xff0d, "KP Ent": 0xff8d, "=": 0x3d, "-": 0x2d,
            "Bksp": 0xff08, "Esc": 0xff1b}


def _c_cab_keys():
    c = _text("padglhost.c")
    body = re.search(r"cab_keys\[\] = \{(.*?)\n\};", c, re.S).group(1)
    return {int(sym, 16): name.lower() for sym, name in
            re.findall(r"\{\s*(0x[0-9a-fA-F]+),\s*PADSW_CAB_(\w+)\s*\}", body)}


def test_the_game_window_and_the_playfield_map_the_same_keys(keybinds):
    """padglhost.c's cab_keys[] is the game window's table, keybinds.py's
    CABINET_KEYS the playfield window's; two windows, one keyboard."""
    want = {_XKEYSYM[key]: button for key, button in keybinds.CABINET_KEYS}
    assert _c_cab_keys() == want


def test_each_button_key_is_the_key_that_already_does_that_in_the_game():
    """Left is the left flipper in the game and the left button in the menu -
    the table's other half. Read off the compiled binds[] head."""
    c = _text("padglhost.c")
    rows = {int(sym, 16): what for sym, _key, what in re.findall(
        r'\{\s*(0x[0-9a-fA-F]+),\s*"([^"]*)",\s*"([^"]*)"', c.split("binds[MAXBINDS] = {")[1]
        .split("};")[0])}
    label = {"left": "Left Flipper", "right": "Right Flipper", "start": "Start Button",
             "action": "Action Button", "select": "Service Select",
             "plus": "Service Plus", "minus": "Service Minus", "back": "Service Back"}
    for sym, button in _c_cab_keys().items():
        assert rows[sym] == label[button], (hex(sym), button)


# --- padglhost's own code, compiled and driven -------------------------------

_HARNESS = r'''
#define main padglhost_main
#include "padglhost.c"
#undef main
#include <assert.h>
#include <stdio.h>

static struct padsw_shm blk;

static int cab_bytes(void) { int n = 0, i; for (i = 0; i < PADSW_CAB_N; i++) n = n * 2 + (swshm->cab[i] ? 1 : 0); return n; }

int main(int argc, char **argv)
{
    int i;
    (void)argc;
    /* the key state machine, against a plain block */
    swshm = &blk;
    cab_key(0xff51, 1);                                  /* Left down       */
    assert(swshm->cab[PADSW_CAB_LEFT] == 1);
    for (i = 0; i < PADSW_CAB_N; i++) if (i != PADSW_CAB_LEFT) assert(swshm->cab[i] == 0);
    assert(swshm->gen == 0);                             /* never the id path */
    cab_key(0xff51, 1);                                  /* a repeat: same   */
    assert(swshm->cab[PADSW_CAB_LEFT] == 1);
    cab_key(0xff51, 0);
    assert(cab_bytes() == 0);
    /* two keys, one button: held until BOTH are up */
    cab_key(0xff0d, 1); cab_key(0xff8d, 1);
    assert(swshm->cab[PADSW_CAB_SELECT] == 1);
    cab_key(0xff0d, 0);
    assert(swshm->cab[PADSW_CAB_SELECT] == 1);
    cab_key(0xff8d, 0);
    assert(swshm->cab[PADSW_CAB_SELECT] == 0);
    /* a key that is not a menu button moves nothing */
    cab_key('q', 1);
    assert(cab_bytes() == 0);
    /* every key in the table lands on its own button, and only that one */
    for (i = 0; i < NCAB_KEYS; i++) {
        int j;
        cab_key(cab_keys[i].sym, 1);
        for (j = 0; j < PADSW_CAB_N; j++)
            assert((swshm->cab[j] != 0) == (j == cab_keys[i].cab));
        cab_key(cab_keys[i].sym, 0);
        assert(cab_bytes() == 0);
    }
    /* the scripts' half is never ours */
    blk.scr_cab[PADSW_CAB_START] = 1;
    cab_key(0xff51, 1); cab_key(0xff51, 0);
    assert(blk.scr_cab[PADSW_CAB_START] == 1);

    /* opening a LIVE block clears what is ours (held[], cab[]) and only that */
    swshm = 0;
    setenv("PAD_SW_SHM", argv[1], 1);
    sw_shm_open();
    assert(swshm != 0 && swshm != &blk);
    assert(swshm->magic == PADSW_MAGIC);
    assert(cab_bytes() == 0);                            /* stale keyboard byte gone   */
    assert(swshm->held[66] == 0);
    assert(swshm->scr_cab[PADSW_CAB_ACTION] == 1);       /* the scripts' byte survives */
    assert(swshm->scr_held[7] == 1);
    puts("harness ok");
    return 0;
}
'''


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    """padglhost.c itself, with main() renamed, linked into a test program.
    Skips when there is no compiler or no X11/EGL runtime to link against - a
    compile that FAILS with those present is a real failure."""
    gcc = shutil.which("gcc")
    if not gcc or not sys.platform.startswith("linux"):
        pytest.skip("needs gcc on Linux")
    d = tmp_path_factory.mktemp("cabharness")
    (d / "h.c").write_text(_HARNESS)
    common = ["-std=gnu17", "-O0", "-Wall", "-Werror=implicit-function-declaration", "-I", RIG]
    obj = subprocess.run([gcc, *common, "-c", str(d / "h.c"), "-o", str(d / "h.o")],
                         capture_output=True, text=True)
    assert obj.returncode == 0, obj.stderr
    exe = d / "h"
    link = subprocess.run([gcc, str(d / "h.o"), "-o", str(exe), "-l:libEGL.so.1", "-l:libX11.so.6"],
                          capture_output=True, text=True)
    if link.returncode != 0:
        pytest.skip("no libEGL/libX11 to link padglhost against: %s" % link.stderr.strip()[-200:])
    return exe, d


def test_padglhost_publishes_the_buttons_by_name(harness):
    """The real cab_key()/cab_publish()/sw_shm_open() - the X11 event handler
    only calls the first (padglhost.c: cab_key(sym, press) before bind_for)."""
    exe, d = harness
    block = d / "padsw"
    raw = bytearray(4096)
    struct.pack_into("<I", raw, 0, 0x53444150)                    # a live block
    raw[8 + 66] = 1                                                # stale keyboard id
    raw[1068 + 3] = 1                                              # stale keyboard button
    raw[1076 + 3] = 1                                              # a script's button: survives
    raw[280 + 7] = 1                                               # a script's switch: survives
    block.write_bytes(bytes(raw))
    r = subprocess.run([str(exe), str(block)], capture_output=True, text=True)
    assert r.returncode == 0 and "harness ok" in r.stdout, (r.stdout, r.stderr[-400:])


def test_the_key_handler_calls_the_buttons_before_the_lookup():
    """The one line the harness cannot reach: the event handler. A key with no
    binds[] row must still reach the button, which means cab_key() runs BEFORE
    the `if (b < 0) break;`."""
    c = _text("padglhost.c")
    handler = c[c.index("case 3: {                      /* KeyRelease */"):]
    assert handler.index("cab_key(sym, press)") < handler.index("if (b < 0) break;")
    assert "XLookupKeysym(&ev, 0)" in handler[:handler.index("if (b < 0) break;")]


def test_tk_keysym_names_for_the_playfield(keybinds):
    assert keybinds.cabinet_keysyms() == {
        "Left": "left", "Right": "right", "1": "start", "space": "action",
        "Return": "select", "KP_Enter": "select", "equal": "plus", "minus": "minus",
        "BackSpace": "back", "Escape": "back"}


def test_the_button_names_are_the_blocks(keybinds, padsw):
    assert {b for _k, b in keybinds.CABINET_KEYS} == set(padsw.CAB_NAMES)


# --- swkeys: the helper's `cab` line ------------------------------------------

class _Block(bytearray):
    """The switch block, as mutable as the mmap the helpers are written for."""

    def flush(self):
        pass

    def close(self):
        pass


def _run_swkeys(monkeypatch, padsw, lines):
    """Run swkeys.main() over `lines`, snapshotting the cab region after each
    one. Returns (snapshots, block): snapshots[i] is scr_cab AFTER line i, and
    the last is the state once stdin has ended."""
    import swkeys
    block = _Block(4096)
    monkeypatch.setattr(padsw, "open_block", lambda *a, **k: block)
    snaps = []

    class Stdin:
        def __iter__(self):
            for ln in lines:
                yield ln
                snaps.append(bytes(block[padsw.OFF_SCR_CAB:padsw.OFF_SCR_CAB + padsw.CAB_N]))

    monkeypatch.setattr(sys, "stdin", Stdin())
    assert swkeys.main() == 0
    snaps.append(bytes(block[padsw.OFF_SCR_CAB:padsw.OFF_SCR_CAB + padsw.CAB_N]))
    return snaps, block


def test_a_cab_line_holds_the_named_button(monkeypatch, padsw):
    snaps, block = _run_swkeys(monkeypatch, padsw,
                               ["cab left 1\n", "cab start 1\n", "cab left 0\n"])
    left, start = padsw.CAB_NAMES.index("left"), padsw.CAB_NAMES.index("start")
    assert snaps[0][left] == 1 and snaps[0][start] == 0
    assert snaps[1][left] == 1 and snaps[1][start] == 1
    assert snaps[2][left] == 0 and snaps[2][start] == 1
    # EOF releases what is still held, the way it does for a switch
    assert snaps[-1] == bytes(padsw.CAB_N)
    assert not any(block[padsw.OFF_CAB:padsw.OFF_CAB + padsw.CAB_N])   # never the keyboard's


def test_a_cab_edge_touches_no_switch_state(monkeypatch, padsw):
    _snaps, block = _run_swkeys(monkeypatch, padsw, ["cab action 1\n"])
    assert not any(block[padsw.OFF_HELD:padsw.OFF_HELD + padsw.MAX_ID])
    assert not any(block[padsw.OFF_SCR_HELD:padsw.OFF_SCR_HELD + padsw.MAX_ID])


def test_a_malformed_line_is_dropped_not_fatal(monkeypatch, padsw):
    snaps, _b = _run_swkeys(monkeypatch, padsw,
                            ["cab bogus 1\n", "cab left\n", "cab left x\n", "cab\n",
                             "abc\n", "0 1\n", "300 1\n", "cab right 1\n"])
    assert all(s == bytes(padsw.CAB_N) for s in snaps[:-2])
    assert snaps[-2][padsw.CAB_NAMES.index("right")] == 1       # and it kept going


def test_the_id_lines_still_work(monkeypatch, padsw):
    """The verb is an addition: `<id> <level>` behaves as it always did."""
    import swkeys
    _snaps, block = _run_swkeys(monkeypatch, padsw, ["66 1\n"])
    assert block[padsw.OFF_SCR_HELD + 66] == 0                  # released at EOF
    assert swkeys.parse("66 1\n") == ("sw", 66, 1)
    assert swkeys.parse("cab left 1\n") == ("cab", "left", 1)
    assert swkeys.parse("cab nope 1\n") is None


# --- the playfield window ------------------------------------------------------

class _Pipe:
    """SwitchPipe, recording."""

    def __init__(self):
        self.calls = []

    def _ensure(self):
        return True

    def set(self, sw, val):
        self.calls.append(("sw", sw, val))
        return True

    def set_cab(self, name, val):
        self.calls.append(("cab", name, val))
        return True

    def close(self):
        self.calls.append(("close",))


# THE WINDOW IS A WEB PAGE NOW (2026-09-23). The page sends each key's edge
# once (it drops KeyboardEvent.repeat and keys typed into a text box) as
# api_key(code, key, down); KeyInput.key(keysym, down) is what those land on.
# The Tk tests drove bindings on a fake root; these drive the model directly,
# and pin the page's two filters at the source.

def _ctl(made=False):
    return types.SimpleNamespace(
        view=types.SimpleNamespace(sw=types.SimpleNamespace(
            is_made=lambda s: made)),
        drv=None)


@pytest.fixture
def pf(monkeypatch):
    mod = pytest.importorskip("playfield")
    monkeypatch.setattr(mod, "SwitchPipe", _Pipe)
    return mod


def _keys(pf, rows):
    return pf.KeyInput(_ctl(), rows)


def _tap(ki, keysym):
    assert ki.key(keysym, True) is not None
    ki.key(keysym, False)


def _page_js():
    return open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools", "spike2_emu", "pfpage", "pf.js"),
        encoding="utf8").read()


def test_the_waiting_state_takes_the_buttons_and_nothing_else(pf):
    """No rows at all - the 'WAITING for tables' window: the buttons still go."""
    ki = _keys(pf, [])
    for keysym, button in [("Left", "left"), ("Right", "right"), ("1", "start"),
                           ("space", "action"), ("Return", "select"),
                           ("KP_Enter", "select"), ("equal", "plus"),
                           ("minus", "minus"), ("BackSpace", "back"),
                           ("Escape", "back")]:
        ki.pipe.calls.clear()
        _tap(ki, keysym)
        assert ki.pipe.calls == [("cab", button, 1), ("cab", button, 0)], keysym
    ki.pipe.calls.clear()
    assert ki.key("q", True) is False                     # a playfield key, no title yet
    assert ki.pipe.calls == []


def test_a_key_with_a_title_row_presses_both(pf, keybinds):
    """The Left arrow is also the title's left flipper once its list exists: the
    switch AND the button, and the button follows the same release."""
    rows = keybinds.parse(["Left\t-\t56\tLEFT FLIPPER BUTTON\n", "Q\t-\t46\tSkill Shot\n"])
    ki = _keys(pf, rows)
    _tap(ki, "Left")
    assert ki.pipe.calls == [("sw", 56, 1), ("cab", "left", 1),
                             ("sw", 56, 0), ("cab", "left", 0)]
    ki.pipe.calls.clear()
    _tap(ki, "q")                                         # a non-button key: switch only
    assert ki.pipe.calls == [("sw", 46, 1), ("sw", 46, 0)]


def test_a_row_the_title_does_not_have_still_reaches_the_button(pf, keybinds):
    """An n/a row (ids 0) presses no switch - but the menu's button is not the
    title's to withhold."""
    rows = keybinds.parse(["Left\t-\t0\tLeft Flipper\n"])
    ki = _keys(pf, rows)
    _tap(ki, "Left")
    assert ki.pipe.calls == [("cab", "left", 1), ("cab", "left", 0)]


def test_an_auto_repeat_pair_keeps_the_button_held(pf):
    """A held key must not flutter the button. The page drops the browser's
    repeat events; a second down that does arrive (two tabs, a stale page) is
    still one press, and one up lets go."""
    assert "if (e.repeat) return;" in _page_js()
    ki = _keys(pf, [])
    ki.key("Right", True)
    ki.key("Right", True)                                 # ...a repeat...
    assert ki.pipe.calls == [("cab", "right", 1)]
    ki.key("Right", False)
    assert ki.pipe.calls == [("cab", "right", 1), ("cab", "right", 0)]
    ki.key("Right", False)                                # a stray up: nothing
    assert ki.pipe.calls == [("cab", "right", 1), ("cab", "right", 0)]


def test_a_text_field_keeps_its_keys():
    """Typing a slot name must not move the menu: the page never sends a key
    whose target is a text box."""
    js = _page_js()
    assert 't.tagName === "INPUT"' in js and 't.tagName === "TEXTAREA"' in js
    assert "typing(e)" in js


def test_a_toggle_row_is_unchanged(pf, keybinds):
    """The door key is not a menu button and behaves as it always did."""
    rows = keybinds.parse(["C\tct\t33\tCoin Door Closed\n"])
    ki = pf.KeyInput(_ctl(made=False), rows)
    ki.key("c", True)
    assert ki.pipe.calls == [("sw", 33, 1)]
    ki.key("c", False)                                    # a toggle's up is nothing
    assert ki.pipe.calls == [("sw", 33, 1)]


def test_detach_lets_go_of_the_window(pf):
    """The WAITING window's keyboard is replaced when the real view arrives:
    it forgets what is down and the pipe closes (that EOF is what releases
    whatever is still held), so no late release is written."""
    ki = _keys(pf, [])
    ki.key("Left", True)
    ki.detach()
    assert ki.pipe.calls[-1] == ("close",)
    assert ("cab", "left", 0) not in ki.pipe.calls        # the EOF does it, not a late write
    assert ki.down == set()


def test_a_lost_focus_lets_go_of_every_key(pf):
    """The page sends a blur when the window loses focus; a flipper held while
    alt-tabbing away must not stay up for good."""
    assert 'addEventListener("blur", () => api("blur"));' in _page_js()
    ki = _keys(pf, [])
    ki.key("Left", True)
    ki.key("Right", True)
    ki.release_all()
    assert ("cab", "left", 0) in ki.pipe.calls
    assert ("cab", "right", 0) in ki.pipe.calls
    assert ki.down == set()


def test_the_pipe_writes_the_lines_swkeys_reads(monkeypatch):
    """Both verbs, byte for byte - the format swkeys.parse() reads. The REAL
    SwitchPipe (no fixture: that one is the recording fake)."""
    import swkeys
    playfield = pytest.importorskip("playfield")
    sent = io.BytesIO()
    pipe = playfield.SwitchPipe()
    monkeypatch.setattr(pipe, "_ensure", lambda: True)
    pipe._p = types.SimpleNamespace(stdin=types.SimpleNamespace(
        write=sent.write, flush=lambda: None))
    assert pipe.set_cab("left", 1) is True
    assert pipe.set(56, 0) is True
    lines = sent.getvalue().decode().splitlines(True)
    assert lines == ["cab left 1\n", "56 0\n"]
    assert [swkeys.parse(ln) for ln in lines] == [("cab", "left", 1), ("sw", 56, 0)]


def test_a_dead_pipe_reports_the_edge_undelivered(monkeypatch):
    """set() answers False when nothing could carry the edge, which is what
    lets a row's press fall back to the spawn path; set_cab() has no such path
    and must not raise."""
    playfield = pytest.importorskip("playfield")
    pipe = playfield.SwitchPipe()
    monkeypatch.setattr(pipe, "_ensure", lambda: False)
    assert pipe.set(5, 1) is False
    assert pipe.set_cab("left", 1) is False


def test_the_waiting_window_wires_its_keyboard_in_main(pf, monkeypatch, tmp_path):
    """The WAITING page (no tables yet) gets a rows-less KeyInput, so the boot
    menu's buttons work by name; the real view's arrival detaches it BEFORE
    anything else is built; and closing the window closes it. The window is a
    web page now (2026-09-23), so this drives the real controller - the page's
    key events arrive as api_key(code, key, down) - with everything that could
    reach WSL or a run's files faked first."""
    monkeypatch.setattr(pf, "wsl_run", lambda *a, **k: None)
    monkeypatch.setattr(pf, "state_run", lambda *a, **k: None)
    monkeypatch.setattr(pf, "state_slots", lambda *a, **k: {})
    monkeypatch.setattr(pf, "SAVESTATES", False)
    monkeypatch.setattr(pf, "layout_is_usable", lambda: False)
    for name in ("LED_PATH", "LCD_PATH", "SW_PATH", "BINDS_PATH", "BALL_PATH"):
        monkeypatch.setattr(pf, name, str(tmp_path / ("absent_" + name)))
    monkeypatch.setattr(pf, "STATE", str(tmp_path / "state.json"))
    tables = {"rows": []}
    monkeypatch.setattr(pf, "load_switch_list",
                        lambda *a, **k: list(tables["rows"]))

    # ---- the placeholder has a keyboard, and it is ONLY the buttons ----------
    ctl = pf.Playfield()
    assert ctl.kind == "waiting" and ctl.view is None
    keys = ctl.keys
    assert isinstance(keys, pf.KeyInput)
    assert keys.map and all(r["ids"] == [] and r.get("cab")
                            for r in keys.map.values())
    assert ctl.api_key("ArrowLeft", "ArrowLeft", True) is True
    assert ctl.api_key("ArrowLeft", "ArrowLeft", False) is True
    assert ctl.api_key("KeyQ", "q", True) is False      # no title rows yet
    assert keys.pipe.calls == [("cab", "left", 1), ("cab", "left", 0)]

    # ---- the tables land: detach FIRST, then build ---------------------------
    order = []
    real_detach, real_build = keys.detach, ctl._build_view
    keys.detach = lambda: (order.append("detach"), real_detach())
    ctl._build_view = lambda rows=None: (order.append("build"),
                                         real_build(rows))
    tables["rows"] = [dict(id=77, num=15, node=8, bit=37, name="Trough 1")]
    ctl.swap_in(tables["rows"])
    assert order == ["detach", "build"]
    assert keys.pipe.calls[-1] == ("close",)           # EOF releases the rest
    assert ctl.kind == "schematic" and ctl.keys is not keys

    # ---- closing the window closes the placeholder's keyboard ----------------
    tables["rows"] = []
    ctl2 = pf.Playfield()
    assert ctl2.kind == "waiting"
    k2 = ctl2.keys
    ctl2.api_key("ArrowRight", "ArrowRight", True)     # still held at close
    ctl2.bye()
    assert k2.pipe.calls[-2:] == [("cab", "right", 0), ("close",)]
