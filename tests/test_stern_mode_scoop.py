"""PAD-381: a mode holds a ball in the scoop, then the game kicks it out - the runtime's wrap, the ports,
the model, the generated mode file and the tab's seconds, at the desk. Emulator-proven on the stock Pro
1.16 and Premium/LE 1.16 cards (MODE_SDK.md "The scoop"; ``mode_project.SCOOP_PROVEN``).

What is worth failing on:
  * THE KICK-OUT IS NEVER THE MODE'S. The scoop section fires no coil: it only delays the game's own
    eject, by holding inside the game's handler for the scoop's ball device.
  * THE GAME'S OWN HOLD COMES FIRST: the wrapper runs the game's handler, THEN holds, and only on the
    port's settled-ball event.
  * THE HOLD ENDS on its time, a release, the mode ending, and the game ending or tilting; it is a
    sleep a tick at a time in the device's own process, never a busy wait.
  * THE SWAP IS CHECKED: the record's pointer is replaced only while it points at the handler, and the
    port's slot holds the handler's address in the game program itself.
"""
import os
import pathlib
import re
import struct
from dataclasses import replace

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = {"godzilla_pro-1.16": [os.environ.get("PAD_GODZILLA_PRO_116_GAME", ""), r"C:\tmp\gzpro116_stock.elf",
                               "/mnt/c/tmp/gzpro116_stock.elf"],
         "godzilla_le-1.16": [os.environ.get("PAD_GODZILLA_LE_116_GAME", ""), r"C:\tmp\gzle116_stock.elf",
                              "/mnt/c/tmp/gzle116_stock.elf"]}


def _lift(src, signature):
    """A function's text, brace-matched from its signature (a prototype is skipped)."""
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


def _section(src):
    a = src.index("/* ---- the scoop: a ball held there for the mode")
    return src[a:src.index("/* ---- the game's own rules: a shot that COUNTS AS", a)]


# ---- the runtime ---------------------------------------------------------------------------
def test_the_scoop_never_fires_a_coil():
    sec = re.sub(r"/\*.*?\*/", "", _section(RUNTIME.read_text(encoding="utf-8")), flags=re.S)   # the code alone
    for call in ("coil_fire", "magnet_send", "coil_take", "coil_give", "proc_create"):
        assert call not in sec, call


def test_the_game_holds_first_and_the_mode_after():
    src = RUNTIME.read_text(encoding="utf-8")
    wrap = _lift(src, "static unsigned scoop_wrap(")
    body = wrap[wrap.index("{"):]
    assert body.index("scoop.orig(ev, a1, a2, a3)") < body.index("ev != scoop.event")
    assert "return r;" in body                              # the game's own answer, unchanged
    loop = body[body.index("while ("):body.index('fn("proc_sleep"))(1);')]
    for cond in ("!scoop.release", "scoop.hold_ms", "running", "pm_in_game()", "pm_ms() < scoop.until"):
        assert cond in loop, cond


def test_every_end_lets_go_and_the_swap_is_checked():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "scoop_let_go();" in _lift(src, "void pm_end(void)")
    assert "scoop.hold_ms = 0;" in _lift(src, "static void scoop_let_go(void)")
    tick = _lift(src, "static void scoop_tick(void)")
    assert '*slot != fn("scoop_handler")' in tick and "can &= ~PM_CAN_SCOOP;" in tick
    assert tick.index('*slot != fn("scoop_handler")') < tick.index("*slot = (unsigned)(unsigned long)scoop_wrap;")
    assert "scoop_tick();" in _lift(src, "static void on_tick(")
    assert "scoop_arm();" in _lift(src, "static void pad_mode_start(void)")


def test_the_apps_limits_are_the_runtimes():
    src = RUNTIME.read_text(encoding="utf-8")
    assert int(re.search(r"#define SCOOP_MAX_MS\s+(\d+)u", src).group(1)) == MP.SCOOP_MAX_MS
    assert int(re.search(r"#define SCOOP_MIN_MS\s+(\d+)u", src).group(1)) == MP.SCOOP_MIN_MS
    hdr = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    for decl in ("int pm_scoop_hold(unsigned ms);", "void pm_scoop_release(void);", "int pm_scoop_holding(void);"):
        assert decl in hdr
    assert re.search(r"#define PM_CAN_SCOOP\s+0x100000u", hdr)


# ---- the ports and the game programs ---------------------------------------------------------
def _elf(cands):
    for c in cands:
        if c and os.path.isfile(c):
            return open(c, "rb").read()
    return None


def _word(b, va):
    e = struct.unpack_from("<I", b, 0x1c)[0]
    for i in range(struct.unpack_from("<H", b, 0x2c)[0]):
        t, off, v, _pa, fs = struct.unpack_from("<5I", b, e + 32 * i)
        if t == 1 and v <= va < v + fs:
            return struct.unpack_from("<I", b, va - v + off)[0]
    return None


@pytest.mark.parametrize("key", sorted(PORTS))
def test_the_port_names_the_scoop(key):
    port = MP.read_port(str(SDK / "ports" / (key + ".port")))
    assert "scoop_handler" in port["site"] and port["data"].get("scoop_slot")
    assert port["value"]["scoop_event"] == 2


@pytest.mark.parametrize("key", sorted(PORTS))
def test_the_slot_points_at_the_handler_in_the_game_program(key):
    b = _elf(PORTS[key])
    if b is None:
        pytest.skip("no %s game program here" % key)
    port = MP.read_port(str(SDK / "ports" / (key + ".port")))
    addr, w0, w1 = port["site"]["scoop_handler"]
    assert (_word(b, addr), _word(b, addr + 4)) == (w0, w1)
    assert _word(b, port["data"]["scoop_slot"]) == addr


# ---- the model, the mode file, the tab -------------------------------------------------------
PRO_116 = MP.profile_from_port(str(SDK / "ports" / "godzilla_pro-1.16.port"))
CANNOT = replace(PRO_116, key="godzilla_pro_1_16_scoopnot",
                 cannot=(("scoop", "Not on Godzilla Pro 1.16 yet (a test)."),))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    monkeypatch.setitem(MP.PROFILES, PRO_116.key, PRO_116)
    monkeypatch.setitem(MP.PROFILES, CANNOT.key, CANNOT)


def _spec(p, **kw):
    spec = MP.blank_spec(p)
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _key(spec, key):
    return [line.split(None, 1)[1] for line in MP.runtime_cfg(spec, "sc").splitlines()
            if line and not line.startswith("#") and line.split(None, 1)[0] == key]


def test_the_line_carries_a_time_and_nothing_else():
    assert MP.ModeSpec().scoop_hold_ms == 0 and not _key(_spec(PRO_116), "scoop_hold")
    assert _key(_spec(PRO_116, scoop_hold_ms=4000), "scoop_hold") == ["4000"]
    spec = _spec(CANNOT, scoop_hold_ms=4000)
    assert MP.validate_scoop(spec, CANNOT) == [
        "Holding a ball in the scoop is not on Godzilla Pro 1.16 yet (Mode says why)."]
    assert MP.scoop_lines(spec, CANNOT) == []


@pytest.mark.parametrize("value", [99, 10001, "lots"])
def test_validate_names_a_bad_time(value):
    problems = MP.validate(_spec(PRO_116, scoop_hold_ms=value))
    assert "The scoop holds a ball 0.1 to 10 seconds." in problems
    from pinball_decryptor.webui.tabs.modes import problem_pages
    assert problem_pages(problems) == ["mode"] * len(problems)


def test_the_field_round_trips(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=MP.ModeSpec(name="HELD", scoop_hold_ms=3500))
    assert MP.load(str(project / "modes" / slug / "mode.json")).scoop_hold_ms == 3500


def test_the_tab_reads_seconds():
    from pinball_decryptor.webui.tabs.modes import ModesTab
    assert ModesTab._magnet_ms("3") == 3000 and ModesTab._magnet_ms("0.5") == 500
    assert ModesTab.SPINBOXES["scoop_s"][:2] == [MP.SCOOP_MIN_MS / 1000, MP.SCOOP_MAX_MS / 1000]


def test_every_shipped_build_gets_a_verdict_with_the_game_named():
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        build = "%s-%s" % (p.game_dir, p.version)
        if build in MP.SCOOP_PROVEN:
            assert p.can("scoop"), key
        else:
            assert not p.can("scoop") and p.label in p.why_not("scoop"), key


def test_the_interpreter_sets_the_hold_when_the_mode_starts():
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    assert "if (scoop_line(M, line)) return;" in src
    start = _lift(src, "static void mode_start(")
    assert "if (cfg.scoop_ms) pm_scoop_hold(cfg.scoop_ms);" in start


def test_the_docs_name_the_key_and_the_calls():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("scoop_hold", "scoop_hold_ms", "pm_scoop_hold"):
        assert re.search(r"`%s(?:[ (][^`]*)?`" % re.escape(name), doc), name
    assert "## The scoop (PAD-381)" in (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
