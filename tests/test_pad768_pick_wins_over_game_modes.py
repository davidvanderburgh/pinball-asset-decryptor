"""PAD-768: a battle picked on the game's selection screen wins over the game's own mini modes running then.

David (Godzilla Premium, Heisei 1.99D): "I went to start King Caesar but jet fighters was going and then as soon as the
King Caesar started it canceled out and just did jet fighters instead. Anything from the Kaiju Battle select screen
should override the mini modes." The game opens its selection screen while its Jet Fighter Attack (a timed mode, id 21)
runs; the picked mode started past it (PAD-733's pick_go) and its next tick saw "one of the game's modes running" and
ended it, the battle lost. Now the pick's start ends the game's mini modes (pm_game_modes_end: each one's own STOP,
lost) and a pick in one of the game's multiballs runs through it.

- Blocks (plugins/stern/block_modes.py) on the desk harness (sdk/examples/desk_harness.c: `timed 1` is Jet Fighter
  Attack, `multiball 1` the game's multiball).
- Mode files (sdk/mode_file.c, `roster_slot`) on test_spike2_mode_roster's host harness, with the game's modes
  controllable.
- The runtime's side (pad_mode_runtime.c pm_game_modes_end): what it skips and what it reads its slots from.
Both harnesses need an ELF host C compiler (they skip on Windows and macOS; run under WSL / the Linux CI leg).
"""
import pathlib
import re
import subprocess

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from tests import test_spike2_mode_roster as R
from tests import test_stern_block_battle as B

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"


def caesar(game_modes="block"):
    """KING CAESAR in Gigan's slot (2), as David's: it keeps the game's modes off; two Buildings win it."""
    p = B.gigan()
    p["name"] = "KING CAESAR"
    p["game_modes"] = game_modes
    p["wait_multiball"] = True
    return p


# ---- blocks ----------------------------------------------------------------------------------------
def test_the_pick_ends_the_game_mini_mode_and_the_battle_runs_to_its_win(tmp_path):
    out = B.play(tmp_path, caesar(), "timed", 1, "pick", 2, "secs", 3, "shot", "Building", "shot", "Building", "secs", 2,
                 slug="king_caesar")
    assert "[KING CAESAR] START (a block): player 1" in out
    assert "GAME MODES END 1 (a battle picked on the selection screen)" in out
    assert out.index("GAME MODES END 1") < out.index("[KING CAESAR] START")          # ended as it starts
    assert "the game's own mode began" not in out                        # before: ended on its first tick, lost
    assert "[KING CAESAR] the battle it took the place of: WON" in out
    assert out.count("ROSTER OVER") == 1 and "ROSTER OVER WON" in out


def test_a_pick_in_the_game_multiball_runs_through_it(tmp_path):
    out = B.play(tmp_path, caesar(), "multiball", 1, "balls", 2, "pick", 2, "secs", 3, "shot", "Building", "shot", "Building",
                 "secs", 2, slug="king_caesar")
    assert "[KING CAESAR] START (a block): player 1" in out
    assert "picked in the game's multiball: it runs through it" in out
    assert "the game's own mode began" not in out
    assert "ROSTER OVER WON" in out


def test_a_game_mode_beginning_while_a_picked_battle_runs_still_ends_it(tmp_path):
    """Ours still run alone: only what was running at the pick gives way to it."""
    out = B.play(tmp_path, caesar(), "pick", 2, "secs", 2, "battle", 1, "secs", 2, slug="king_caesar")
    assert "GAME MODES END" not in out                                    # nothing of the game's ran at the pick
    assert "END (the game's own mode began)" in out
    assert "ROSTER OVER lost" in out


def test_a_mode_that_stacks_leaves_the_game_mini_mode_be(tmp_path):
    out = B.play(tmp_path, caesar(game_modes="stack"), "timed", 1, "pick", 2, "secs", 3, slug="king_caesar")
    assert "[KING CAESAR] START (a block): player 1" in out
    assert "GAME MODES END" not in out
    assert "the game's own mode began" not in out


def test_a_start_that_is_not_a_pick_still_waits_for_the_game_mode(tmp_path):
    p = caesar()
    p["scripts"].append({"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]})
    out = B.play(tmp_path, p, "timed", 1, "shot", "Left ramp", "secs", 2, slug="king_caesar")
    assert "START (a block)" not in out
    assert "GAME MODES END" not in out
    assert "not started (a block)" in out


def test_the_c_ends_the_game_modes_only_for_a_battle_pick():
    c = BM.to_c(caesar(), "king_caesar")
    assert c.count("pm_game_modes_end(") == 2         # at the pick (under the screen's close), and as it starts
    assert "if (battle_picked && !battle_cleared && GAME_MODES" in c
    assert "pick_go = 2;" in c                                            # the battle pick
    assert "if (pick_go == 2 && GAME_MODES)" in c
    assert "(run.own_mball || run.pick_mball) && pm_aside() == (int)PM_STOCK_MULTIBALL" in c
    plain = B.gigan()
    plain["scripts"][0]["hat"] = {"kind": "shot", "shot": "Building", "when": "idle"}
    assert "pick_go = 2;" not in BM.to_c(plain, "gigan_stages")


# ---- mode files ------------------------------------------------------------------------------------
GAME_STUBS = r"""
static int g_timed, g_mball;
int pm_stock_mode_running(unsigned kinds)
{
    if ((kinds & PM_STOCK_MULTIBALL) && g_mball) return PM_STOCK_MULTIBALL;
    if ((kinds & PM_STOCK_ANY) && (g_timed || g_mball)) return PM_STOCK_ANY;
    return 0;
}
int pm_aside(void) { return in_game ? pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL | PM_STOCK_ANY) : 0; }
int pm_balls_in_play(void) { return g_mball ? 2 : 1; }
int pm_game_modes_end(const char *why) { if (!g_timed) return 0; g_timed = 0; printf("GAME MODES END (%s)\n", why); return 1; }
"""


@pytest.fixture(scope="module")
def mf_harness(tmp_path_factory):
    cc = R._cc()
    d = tmp_path_factory.mktemp("pad768")
    src = R.HARNESS.replace("int pm_stock_mode_running(unsigned kinds) { return 0; }\n", "")
    src = src.replace("int main(int argc, char **argv)\n", GAME_STUBS + "\nint main(int argc, char **argv)\n")
    src = src.replace('        } else if (!strcmp(argv[k], "ball_end")) {',
                      '        } else if (!strcmp(argv[k], "timed")) { g_timed = atoi(argv[++k]); printf("TIMED %d\\n", g_timed);\n'
                      '        } else if (!strcmp(argv[k], "mball")) { g_mball = atoi(argv[++k]); printf("MBALL %d\\n", g_mball);\n'
                      '        } else if (!strcmp(argv[k], "ball_end")) {')
    assert "g_timed = atoi" in src and "GAME MODES END" in src and "pm_stock_mode_running(unsigned kinds) { return 0; }" not in src
    (d / "harness.c").write_text(src)
    stubs, _names = R.weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    (d / "weak_stubs.c").write_text(stubs)
    exe = d / "harness"
    for std in ("-std=gnu2x", "-std=gnu17"):
        r = subprocess.run([cc, std, "-w", "-I", str(SDK), "-c", "-o", str(d / "weak_stubs.o"), str(d / "weak_stubs.c")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "harness.c"), str(SDK / "mode_file.c"), str(d / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


CAESAR_MF = "name KING CAESAR\nroster_slot 1\nseconds 30\nshots 0x70300000\naward 1000000\ngame_modes block\n"


def test_a_mode_file_pick_ends_the_game_mini_mode_and_runs(mf_harness, tmp_path):
    out = R._run(mf_harness, tmp_path, CAESAR_MF, "timed", "1", "pick", "1", "tick", "200", "ball_end")
    assert "PICK 1 -> 1" in out
    assert "KING CAESAR START (roster pick)" in out                       # before: refused, the pick given back
    assert "GAME MODES END (a battle picked on the selection screen)" in out
    assert "picked but not started" not in out
    assert "the game's own mode began" not in out
    assert "KING CAESAR END (ball ended)" in out
    assert out.count("ROSTER_DONE") == 1


def test_a_mode_file_pick_in_the_game_multiball_runs_through_it(mf_harness, tmp_path):
    out = R._run(mf_harness, tmp_path, CAESAR_MF, "mball", "1", "pick", "1", "tick", "100", "mball", "0", "tick", "100",
                 "ball_end")
    assert "KING CAESAR START (roster pick)" in out
    assert "picked in the game's multiball - it runs through it" in out
    assert "the game's own mode began" not in out
    assert "KING CAESAR END (ball ended)" in out


def test_a_mode_file_trigger_still_waits_for_the_game_mode(mf_harness, tmp_path):
    cfg = CAESAR_MF + "trigger 0x00100000 1\n"
    out = R._run(mf_harness, tmp_path, cfg, "timed", "1", "shot", "0x00100000", "tick", "10")
    assert "START (trigger shot)" not in out
    assert "GAME MODES END" not in out


# ---- the runtime -----------------------------------------------------------------------------------
def _runtime():
    return (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")


def test_the_runtime_ends_only_mini_modes_through_their_own_stop():
    src = _runtime()
    body = src[src.index("int pm_game_modes_end(const char *why)"):]
    body = body[:body.index("\n}\n")]
    assert "(kind & 0x20u) || (kind & 0x8u) || (kind & 0x21u) == 1u" in body   # beside all / battle / multiball
    assert "stock_beside(beside, place_name(id))" in body                      # Tesla Strike runs beside ours
    assert "place_held[up].on && place_held[up].id == id" in body              # ours in its place: not running
    assert "(obj, 0u, 1u)" in body                                             # its STOP, lost
    assert "aside.at = 0" in body                                              # the next pm_aside asks afresh
    # its TOTAL screen is not shown over ours (run a1: JET FIGHTER ATTACK TOTAL covered the start clip for 4.5 s)
    assert body.index("= 0;     /* no TOTAL screen over ours */") < body.index("(obj, 0u, 1u)")
    assert 'pm_port_value("stock_award_at", -1)' in body and 'pm_port_value("battle_total_at", -1)' in body


def test_the_runtime_reads_the_slots_off_the_game_query():
    """The ACTIVE ask is `ldr r3,[r3,#A]; blx r3`, the KIND getter `ldr r3,[r3,#K]; cmp r3,r6` (Godzilla 0xd41b0: v[14] and
    v[17], the words as the game program has them)"""
    words = [0xe92d4070, 0xe30f66a0, 0xe59f4060, 0xe34064f7, 0xe284506c, 0xea000001, 0xe1540005, 0x0a000011,
             0xe5b40004, 0xe5903000, 0xe5933038, 0xe12fff33, 0xe3500000, 0x0afffff7, 0xe5940000, 0xe5903000,
             0xe5933044, 0xe1530006]
    src = _runtime()
    fn = src[src.index("static long mode_query_slot(int kind_slot)"):]
    fn = fn[:fn.index("\n}\n")]
    pairs = re.findall(r"w\[i \+ 1\] == (0x[0-9a-f]+)u\) return", fn)
    assert pairs == ["0xe12fff33", "0xe1530006"]

    def slot(kind):
        want = int(pairs[1 if kind else 0], 16)
        for i in range(len(words) - 1):
            if (words[i] & 0xfffff000) == 0xe5933000 and not words[i] & 3 and words[i + 1] == want:
                return (words[i] & 0xfff) // 4
        return -1
    assert (slot(0), slot(1)) == (14, 17)


@pytest.mark.parametrize("port", ["godzilla_le-1.16", "godzilla_pro-1.16", "godzilla_pro-1.15"])
def test_the_godzilla_ports_have_what_the_pick_needs(port):
    text = (SDK / "ports" / (port + ".port")).read_text(encoding="utf-8")
    assert re.search(r"^site stock_any_running\s+0x", text, re.M)
    assert re.search(r"^value mode_slot_stop\s+11", text, re.M)
    assert re.search(r"^data block_obj_21\s+0x", text, re.M)
    assert re.search(r"^text block_name_21\s+Jet Fighter Attack", text, re.M)
    assert re.search(r"^value stock_award_at\s+0x50", text, re.M)          # the points this time: no TOTAL screen
    assert re.search(r"^value battle_total_at\s+0xf0", text, re.M)
