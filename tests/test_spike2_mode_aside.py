"""PAD-347: a mode file's own screen steps aside while one of the game's own modes runs.

David's Premium, 2026-10-03: during the game's JET FIGHTER ATTACK one of our modes wrote its words where the
game's mode writes its own. Stern never shows two modes' words at once, so while the game's mode runs
(``pm_aside``) a mode file's screen is hidden and comes back when the game's mode ends; ``aside keep`` leaves it
up (a screen laid out clear of the game's words). mode_file.c is compiled for the HOST against stubs of the SDK
calls (skips without an ELF C compiler).
"""
import os
import subprocess
import struct

import pytest

from tests.test_spike2_mode_roster import HARNESS, _cc, weak_stubs
from tests.test_spike2_mode_display import ELVES, SDK, _Elf, _port

# the roster harness, with a screen the mode finds, its shows printed, and the game's mode switched by `stock <k>`
SCREEN_STUBS = [
    ("void *pm_node(const char *s, const char *p) { return 0; }",
     "static char fake_node[4];\nvoid *pm_node(const char *s, const char *p) { return fake_node; }"),
    ("void *pm_text(const char *s, const char *p) { return 0; }",
     "static char fake_text[4];\nvoid *pm_text(const char *s, const char *p) { return fake_text; }"),
    ("void pm_show(void *n, int on) {}",
     "void pm_show(void *n, int on) { printf(\"SHOW %d at %lu\\n\", on, now_ms); }"),
    ("int pm_stock_mode_running(unsigned kinds) { return 0; }",
     "static int stock;\nint pm_stock_mode_running(unsigned kinds) { return stock; }\n"
     "int pm_aside(void) { return in_game ? stock : 0; }"),
    ("        } else if (!strcmp(argv[k], \"ball_end\")) {",
     "        } else if (!strcmp(argv[k], \"stock\")) {   /* stock <k>: one of the game's modes runs (0 = none) */\n"
     "            stock = atoi(argv[++k]);\n"
     "            printf(\"STOCK %d at %lu\\n\", stock, now_ms);\n"
     "        } else if (!strcmp(argv[k], \"ball_end\")) {"),
]


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = _cc()
    d = tmp_path_factory.mktemp("aside")
    src = HARNESS
    # pm_show prints the clock: the harness's own definition of now_ms comes after the screen stubs
    src = src.replace("static unsigned long now_ms;\n", "")
    src = src.replace("#include <fcntl.h>\n", "#include <fcntl.h>\nstatic unsigned long now_ms;\n", 1)
    for old, new in SCREEN_STUBS:
        assert src.count(old) == 1, old
        src = src.replace(old, new)
    (d / "harness.c").write_text(src)
    stubs, _names = weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    (d / "weak_stubs.c").write_text(stubs)
    for std in ("-std=gnu2x", "-std=gnu17"):
        r = subprocess.run([cc, std, "-w", "-I", str(SDK), "-c", "-o", str(d / "weak_stubs.o"), str(d / "weak_stubs.c")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    exe = d / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "harness.c"), str(SDK / "mode_file.c"), str(d / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def _run(harness, tmp_path, cfg, *args):
    (tmp_path / "mode.cfg").write_text(cfg)
    env = dict(os.environ, MODE_DIR=str(tmp_path))
    r = subprocess.run([str(harness), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


RUSH = ("name RUSH\ntrigger 0x08000000 1\nseconds 20\nshots 0x00300000\naward 1000000\n"
        "screen_node PadMode_rush_Screen\nscreen_text PadMode_rush_Screen.PadMode_rush_Screen_Words\n")


def _shows(out):
    return [ln.split()[1] for ln in out.splitlines() if ln.startswith("SHOW ")]


def test_the_screen_steps_aside_while_the_games_mode_runs_and_comes_back(harness, tmp_path):
    out = _run(harness, tmp_path, RUSH, "shot", "0x08000000", "tick", "30", "stock", "1", "tick", "30",
               "stock", "0", "tick", "30")
    assert "unknown key" not in out
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if "RUSH START" in ln)
    on = next(i for i, ln in enumerate(lines) if ln.startswith("STOCK 1"))
    off = next(i for i, ln in enumerate(lines) if ln.startswith("STOCK 0"))
    shows = [(i, ln.split()[1]) for i, ln in enumerate(lines) if ln.startswith("SHOW ")]
    assert [v for i, v in shows if i < on][-1] == "1"                        # up while the mode runs alone
    assert [v for i, v in shows if on < i < off] == ["0"]                    # hidden once, while the game's runs
    assert [v for i, v in shows if i > off] == ["1"]                         # back once it is over
    assert "RUSH: its screen steps aside - a stock mode has the middle of the screen" in out
    assert "RUSH: its screen is back - the game's mode is over" in out
    assert start < on


def test_a_mode_that_starts_beside_the_games_mode_steps_aside_at_once(harness, tmp_path):
    out = _run(harness, tmp_path, RUSH, "stock", "1", "shot", "0x08000000", "tick", "30")
    assert "RUSH START" in out
    assert _shows(out)[-1] == "0" and "its screen steps aside" in out


def test_aside_keep_leaves_the_screen_up(harness, tmp_path):
    out = _run(harness, tmp_path, RUSH + "aside keep\n", "shot", "0x08000000", "tick", "30", "stock", "1", "tick", "30",
               "stock", "0", "tick", "30")
    assert "unknown key" not in out and "RUSH START" in out
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if "RUSH START" in ln)
    assert [ln for ln in lines[start:] if ln.startswith("SHOW 0")] == []    # up the whole time
    assert "steps aside" not in out


@pytest.mark.parametrize("value", ["sideways", ""])
def test_an_aside_that_is_not_keep_or_hide_is_hide(harness, tmp_path, value):
    out = _run(harness, tmp_path, RUSH + "aside %s\n" % value, "shot", "0x08000000", "tick", "30", "stock", "1",
               "tick", "30")
    assert "aside needs keep or hide" in out
    assert "its screen steps aside" in out


def test_the_screen_is_not_shown_again_after_its_total_is_gone(harness, tmp_path):
    # the mode ends while the game's mode runs; its total's time runs out while hidden; the game's mode ending
    # later must not bring the screen back
    out = _run(harness, tmp_path, RUSH, "shot", "0x08000000", "tick", "30", "stock", "1", "tick", "1600",
               "stock", "0", "tick", "60")
    lines = out.splitlines()
    end = next(i for i, ln in enumerate(lines) if "RUSH END" in ln)
    off = next(i for i, ln in enumerate(lines) if ln.startswith("STOCK 0"))
    assert end < off
    assert [ln for ln in lines[off:] if ln.startswith("SHOW 1")] == []


# ---- PAD-347: blocking the game's modes on Godzilla Premium 1.16 ----------------------------------------------
def test_the_premium_port_names_the_game_mode_start_and_only_safe_modes_to_refuse():
    port = _port("godzilla_le-1.16.port")
    assert port[("site", "stock_mode_start")] == [0x0007eac0, 0xe92d4010, 0xe1a04000]
    assert port[("data", "block_mode_table")] == [0x007b4aa8]
    assert port[("value", "block_mode_count")] == [27]
    ids = port[("value", "block_mode_ids")][0]
    assert not ids & 0xffe                                  # never a multiball (1-11): locks, the magnets
    assert not ids & (0x3f << 12)                           # never a battle (12-17): the scoop, its select screen
    assert ids == sum(1 << i for i in (18, 19, 21, 22, 23, 24, 25))


def test_the_premium_start_and_table_match_the_game():
    name = "godzilla_le-1.16.port"
    path = next((p for p in ELVES[name] if p and os.path.isfile(p)), None)
    if not path:
        pytest.skip("game program not present for %s" % name)
    e, port = _Elf(path), _port(name)
    site = port[("site", "stock_mode_start")]
    assert (e.u32(site[0]), e.u32(site[0] + 4)) == (site[1], site[2])
    # the manager's get (0xd3fa0): cmp r1,#26 ... movw/movt r3 = the table ... ldr r0,[r3,r1,lsl#2]
    assert e.u32(0xd3fa0) == 0xe351001a and e.u32(0xd3fb4) == 0xe7930101
    lo, hi = e.u32(0xd3fac), e.u32(0xd3fb0)
    imm = lambda w: ((w >> 4) & 0xf000) | (w & 0xfff)        # noqa: E731
    assert (imm(hi) << 16) | imm(lo) == port[("data", "block_mode_table")][0]
    # the hurry-ups' start is a branch to it
    w = e.u32(0xb8dac)
    off = w & 0xffffff
    off = off - (1 << 24) if off & 0x800000 else off
    assert (w >> 24) == 0xea and 0xb8dac + 8 + 4 * off == site[0]
