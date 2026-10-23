"""PAD-686: Godzilla's start menu gets ONE "MODE CHALLENGE" entry whose flippers step through every challenge of the
modes' own (David: "One MODE CHALLENGE entry whose flippers step through all 13 modes, then the menu moves on"). The
entry's rules are lifted from the runtime verbatim and run on the desk; the port lines and the app's offer are read."""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")
LE_PORT = os.path.join(SDK, "ports", "godzilla_le-1.16.port")
CC = shutil.which("gcc") or shutil.which("cc")
needs_cc = pytest.mark.skipif(not CC or os.name == "nt", reason="needs a C compiler (WSL or Linux)")


def _rt():
    with open(RUNTIME, encoding="utf-8") as f:
        return f.read()


def _lift(src, signature):
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


@needs_cc
def test_the_flippers_step_through_the_modes_then_move_on(tmp_path):
    src = _rt()
    code = "#include <stdio.h>\n" + _lift(src, "static int challenge_frame_step(") + "\n" + \
        _lift(src, "static int challenge_frame_arrive(") + r"""
int main(void)
{
    unsigned eat;
    int sub, k;
    /* thirteen modes: from the first, twelve right presses step, the thirteenth moves the cursor on */
    sub = challenge_frame_arrive(13, 1);
    printf("arrive_left %d\n", sub);
    for (k = 0; k < 13; k++) {
        sub = challenge_frame_step(13, sub, 0, 1, &eat);
        printf("right %d %u\n", sub, eat);
    }
    /* from the right (a left press onto the entry): the last, then back down to the first, then on */
    sub = challenge_frame_arrive(13, 0);
    printf("arrive_right %d\n", sub);
    for (k = 0; k < 13; k++) {
        sub = challenge_frame_step(13, sub, 1, 0, &eat);
        printf("left %d %u\n", sub, eat);
    }
    sub = challenge_frame_step(1, 0, 0, 1, &eat);
    printf("one %d %u\n", sub, eat);
    sub = challenge_frame_step(0, 5, 1, 1, &eat);
    printf("none %d %u\n", sub, eat);
    sub = challenge_frame_step(13, 40, 0, 0, &eat);
    printf("stale %d %u\n", sub, eat);
    return 0;
}
"""
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([CC, "-std=gnu17", "-Wall", "-o", str(tmp_path / "t"), str(tmp_path / "t.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout.splitlines()
    assert out[0] == "arrive_left 0"
    rights = [tuple(map(int, l.split()[1:])) for l in out[1:14]]
    assert rights[:12] == [(k, 2) for k in range(1, 13)]          # each press steps, the press eaten
    assert rights[12] == (12, 0)                                    # past the last: the cursor moves on
    assert out[14] == "arrive_right 12"
    lefts = [tuple(map(int, l.split()[1:])) for l in out[15:28]]
    assert lefts[:12] == [(k, 1) for k in range(11, -1, -1)] and lefts[12] == (0, 0)
    assert out[28:] == ["one 0 0", "none 0 0", "stale 0 0"]


def test_the_frame_hook_appends_the_entry_and_names_the_mode():
    frame = _lift(_rt(), "static void challenge_menu_frame(")
    assert "list[ours_at] = entry" in frame and "*count = ours_at + 1" in frame
    assert "*count >= cap" in frame                                 # never past the game's room
    assert "pm_message_set((unsigned)msg, own_challenge[own[frame_sub]].name)" in frame
    assert "pm_message_restore((unsigned)msg)" in frame             # off the entry: the game's own name again
    assert "own_pending = own[frame_sub]" in frame and "own_pending = -1" in frame
    # on the entry the King of the Monsters challenge's own flag is cleared (set, the game starts its battle with the
    # game and the picked mode is refused); back onto the game's own entry it is set again
    assert "game_flag_clear((unsigned)flag)" in frame and "game_flag_set((unsigned)flag)" in frame
    # and the game-play pick is Standard's on the entry (the game re-applies the picked index's flags as it starts),
    # the game's own again off it
    assert '*gpm = (unsigned)pm_port_value("challenge_mode_plain", 1)' in frame and "*gpm = entry" in frame
    assert re.search(r"#define N_OWN_CHALLENGE (\d+)", _rt()).group(1) == "16"


def test_the_port_names_the_menu_frame():
    with open(LE_PORT, encoding="utf-8") as f:
        port = f.read()
    assert re.search(r"^site\s+challenge_menu_frame\s+0x000603d8 0xe0833106 0xe51330d4", port, re.M)
    want = {"challenge_menu_frame_list_at": "300", "challenge_menu_frame_count_at": "64",
            "challenge_menu_frame_cap": "9", "challenge_menu_frame_entry": "4", "challenge_menu_frame_cursor_reg": "6",
            "challenge_menu_frame_left": "4", "challenge_menu_frame_buttons_reg": "5", "challenge_menu_frame_right": "2", "challenge_menu_slot": "0",
            "game_play_mode_at": "8", "challenge_mode_plain": "1", "challenge_menu_sets_on": "1"}
    assert re.search(r"^data\s+game_play_modes\s+0x007b2814\b", port, re.M)
    for k, v in want.items():
        assert re.search(r"^value\s+%s\s+%s\b" % (k, v), port, re.M), k


def test_the_app_offers_a_challenge_of_its_own_on_godzilla_le():
    from pinball_decryptor.plugins.stern import mode_project as MP
    p = MP.profile("godzilla_le_1_16")
    assert getattr(p, "challenge_menu", 0) == MP.CHALLENGE_FRAME_ROOM
    from pinball_decryptor.plugins.stern import block_modes as BM
    assert BM.CHALLENGE_NEW in BM.card_checks(p)["challenges"]
