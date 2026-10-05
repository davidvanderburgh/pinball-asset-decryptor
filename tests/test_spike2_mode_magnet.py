"""A mode's own magnet grab, and the limits it cannot raise (PAD-381).

pad_mode_runtime.c's magnet section: pm_magnet_grab(ms) sends ONE bounded coil command (the
operator's draw power for the draw time, then the hold power for the rest, the whole at most 5 s)
and never re-sends, so the board lets go by itself even if everything above it stops. What is
worth failing on:

  * THE CLAMP: no grab is longer than MAGNET_MAX_MS, the draw included, and a hold power is never
    sent with no hold time.
  * THE REFUSALS, in their order: only the running mode, only in a game, never with the magnet
    disabled, never while the game's own magnet works, never twice at once, 3 s between grabs, six
    a minute.
  * ONE COMMAND PER GRAB: the only callers of the coil call are the grab and the let-go.
  * THE PORTS: Pro and LE 1.16 name the call, the device the game's magnet object holds, and the
    game's own magnet processes; the site words match the game programs when they are here.

The decisions are lifted verbatim from the runtime and compiled for the host (the roster test's
way); emulator-proven separately (docs/plans/mode_coils.md).
"""
import os
import pathlib
import re
import shutil
import struct
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = {"godzilla_pro-1.16": (SDK / "ports" / "godzilla_pro-1.16.port", 11,
                               [os.environ.get("PAD_GODZILLA_PRO_116_GAME", ""), r"C:\tmp\gzpro116_stock.elf",
                                "/mnt/c/tmp/gzpro116_stock.elf"]),
         "godzilla_le-1.16": (SDK / "ports" / "godzilla_le-1.16.port", 13,
                              [os.environ.get("PAD_GODZILLA_LE_116_GAME", ""), r"C:\tmp\gzle116_stock.elf",
                               "/mnt/c/tmp/gzle116_stock.elf"])}


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _lift(src, signature):
    """A function's text, verbatim from the runtime (brace-matched from its signature; a prototype,
    where a ';' comes before the '{', is skipped)."""
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


def _defines(src):
    return "\n".join(re.findall(r"^#define MAGNET_\w+ .*$", src, re.M))


def _host_run(tmp_path, code):
    cc = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")
    if not cc:
        pytest.skip("no C compiler on this host")
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-o", str(tmp_path / "t"),
                        str(tmp_path / "t.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout


def test_a_grab_is_one_clamped_command(tmp_path):
    src = _src()
    out = _host_run(tmp_path, "#include <stdio.h>\n" + _defines(src) + "\n" +
                    re.search(r"^struct magnet_cmd \{.*?\};", src, re.M | re.S).group(0) + "\n" +
                    _lift(src, "static int magnet_plan(") + r"""
static void t(const char *label, unsigned ms, unsigned dp, unsigned dt, unsigned hp)
{
    struct magnet_cmd c = {0, 0, 0, 0};
    const char *why = 0;
    int ok = magnet_plan(ms, dp, dt, hp, &c, &why);
    printf("%s %d %u %u %u %u %s\n", label, ok, c.draw_pwr, c.draw_ms, c.hold_pwr, c.hold_ms, why ? "refused" : "-");
}
int main(void)
{
    t("stock", 2000, 255, 350, 50);
    t("huge", 60000, 255, 350, 50);
    t("tiny", 10, 255, 350, 50);
    t("draw_longer", 300, 255, 350, 50);
    t("no_hold_power", 2000, 255, 350, 0);
    t("zero_draw", 2000, 0, 350, 50);
    t("bad_draw", 2000, 999, 350, 50);
    t("bad_hold", 2000, 255, 350, 300);
    t("long_draw_adj", 5000, 255, 60000, 50);
    return 0;
}
""")
    rows = {l.split()[0]: l.split()[1:] for l in out.strip().splitlines()}
    assert rows["stock"] == ["1", "255", "350", "50", "1650", "-"]
    assert rows["huge"] == ["1", "255", "350", "50", "4650", "-"]           # 5000 ms in all, never more
    assert rows["tiny"] == ["1", "255", "100", "0", "0", "-"]               # 100 ms floor, all draw
    assert rows["draw_longer"] == ["1", "255", "300", "0", "0", "-"]        # the draw is inside the grab
    assert rows["no_hold_power"] == ["1", "255", "350", "0", "0", "-"]      # no hold time for a 0 power
    assert rows["long_draw_adj"] == ["1", "255", "5000", "0", "0", "-"]     # an odd adjustment still ends at 5 s
    for k in ("zero_draw", "bad_draw", "bad_hold"):
        assert rows[k][0] == "0" and rows[k][-1] == "refused", k


def test_the_refusals_and_their_order(tmp_path):
    src = _src()
    out = _host_run(tmp_path, "#include <stdio.h>\n" + _defines(src) + "\n" +
                    _lift(src, "static const char *magnet_refusal(") + r"""
static unsigned long st[MAGNET_PER_MIN];
static void t(const char *label, int run, int game, int dis, int busy, unsigned long until,
              unsigned long ended, unsigned long now)
{
    const char *w = magnet_refusal(run, game, dis, busy, until, ended, now, st);
    printf("%s|%s\n", label, w ? w : "-");
}
int main(void)
{
    unsigned i;
    t("ok", 1, 1, 0, 0, 0, 0, 100000);
    t("not_running", 0, 0, 1, 1, 5, 99999, 100000);
    t("no_game", 1, 0, 1, 1, 5, 99999, 100000);
    t("disabled", 1, 1, 1, 1, 5, 99999, 100000);
    t("game_busy", 1, 1, 0, 1, 5, 99999, 100000);
    t("holding", 1, 1, 0, 0, 5, 99999, 100000);
    t("cool_2999", 1, 1, 0, 0, 0, 97001, 100000);
    t("cool_3000", 1, 1, 0, 0, 0, 97000, 100000);
    for (i = 0; i < MAGNET_PER_MIN; i++) st[i] = 50000 + i * 4000;
    t("six_in_a_minute", 1, 1, 0, 0, 0, 0, 100000);
    t("first_now_old", 1, 1, 0, 0, 0, 0, 110001);
    return 0;
}
""")
    rows = dict(l.split("|", 1) for l in out.strip().splitlines())
    assert rows["ok"] == "-"
    assert rows["not_running"].startswith("only the running mode")
    assert rows["no_game"].startswith("no game is being played")
    assert rows["disabled"].startswith("the operator has the magnet disabled")
    assert rows["game_busy"].startswith("the game's own magnet")
    assert rows["holding"].startswith("a grab is already holding")
    assert rows["cool_2999"].startswith("the last grab ended less than 3 s ago")
    assert rows["cool_3000"] == "-"
    assert rows["six_in_a_minute"].startswith("six grabs in the last minute")
    assert rows["first_now_old"] == "-"


def test_one_command_per_grab_and_it_is_never_resent():
    src = _src()
    calls = [m.start() for m in re.finditer(r"\bmagnet_send\(", src)]
    assert len(calls) == 3, "magnet_send: its definition, the grab and the let-go - nothing else may send"
    grab = _lift(src, "int pm_magnet_grab(")
    let_go = _lift(src, "static void magnet_let_go(")
    tick = _lift(src, "static void magnet_tick(")
    assert grab.count("magnet_send(") == 1
    assert "magnet_send(0, 0, 0, 0)" in let_go
    assert "magnet_send" not in tick                       # the tick only ever lets go
    assert re.search(r"#define MAGNET_MAX_MS\s+5000u", src)


def test_the_runtime_lets_go_on_every_end():
    src = _src()
    assert 'magnet_let_go("the mode ended")' in _lift(src, "void pm_end(void)")
    assert 'magnet_let_go("the ball ended")' in _lift(src, "static void on_ball_end(")
    assert "magnet_tick();" in _lift(src, "static void on_tick(")
    tick = _lift(src, "static void magnet_tick(")
    for why in ("a magnet process of the game's started", "its time ran out", "the game ended or tilted",
                "no mode is running"):
        assert why in tick


@pytest.mark.parametrize("key", sorted(PORTS))
def test_the_port_names_the_magnet(key):
    port, dev, _ = PORTS[key]
    text = port.read_text(encoding="utf-8")
    for site in ("coil_fire", "adjustment", "proc_exists", "magnet_get"):
        assert re.search(r"^site %s\s+0x[0-9a-f]{8} 0x[0-9a-f]{8} 0x[0-9a-f]{8}\s*$" % site, text, re.M), site
    assert re.search(r"^value magnet_dev\s+%d\s*$" % dev, text, re.M)
    procs = re.search(r"^text magnet_procs\s+(.*)$", text, re.M).group(1).split()
    assert {"360", "362", "363"} <= set(procs)


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
def test_the_sites_match_the_game_program(key):
    port, dev, cands = PORTS[key]
    b = _elf(cands)
    if b is None:
        pytest.skip("no %s game program here" % key)
    text = port.read_text(encoding="utf-8")
    for site in ("coil_fire", "adjustment", "proc_exists", "magnet_get"):
        a, w0, w1 = (int(x, 16) for x in
                     re.search(r"^site %s\s+(\S+) (\S+) (\S+)" % site, text, re.M).groups())
        assert (_word(b, a), _word(b, a + 4)) == (w0, w1), site
