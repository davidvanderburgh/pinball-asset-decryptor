"""PAD-1271: the mode runtime on a Spike 3 (64-bit ARM) game, and its first port (Star Wars ELG 1.10).

What the emulator found, held here at the desk (no card, no emulator):
- hook_a64.h's template labels were reached through the GOT; the labels being local to the asm block, every
  GOT load named `.text + offset`, the linker gave them ONE entry, every label read as the same address, and no
  slot got its template (the first hooked call: SIGILL for ever). They are declared hidden now.
- a veto's logger answers an int: the slot tests w0, not x0 (whose top half is the caller's).
- a hooked function may open with a b / b.cond / cbz / cbnz / tbz / tbnz (Spike 3 ELG's agent_header opens
  with `cbz x0`): it is re-aimed at a far jump in the slot to where it went.
- the Insider gate's achievement-query scan has a 64-bit form (adrp + add of the words; `mov w2, #type`;
  `bl agent_begin`), proven on ELG's own code words below.
- a switch id is a u16 argument; 64-bit ARM leaves the register's upper bits to the caller: masked.
- the port: core entries only (the rest of the runtime still reads 32-bit structs), 64-bit scores, the
  bus's end of ball, switch ids one lower than Spike 2's (the program's own device table).
"""
import pathlib
import re
import shutil

import pytest

from tests.test_spike2_mode_roster import _host_run, _lift

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
HOOK = SDK / "hook_a64.h"
RUNTIME = SDK / "pad_mode_runtime.c"
PORT = SDK / "ports" / "spike3" / "star_wars_elg-1.10.port"


def _cc_or_skip():
    from tests.test_spike2_mode_roster import _cc
    try:
        cc = _cc()
    except Exception:
        cc = None
    if not cc:
        pytest.skip("no host C compiler")
    return cc


# ---- the hook layer -------------------------------------------------------------------------------------
def test_template_labels_are_hidden_so_they_are_reached_pc_relative():
    h = HOOK.read_text(encoding="utf-8")
    push = h.index("#pragma GCC visibility push(hidden)")
    decl = h.index("extern const unsigned pm_a64_tpl[]")
    pop = h.index("#pragma GCC visibility pop")
    assert push < decl < pop


def test_a_veto_answer_is_read_as_an_int():
    h = HOOK.read_text(encoding="utf-8")
    assert '"    mov  w17, w0\\n"' in h
    assert '"    mov  x17, x0\\n"' not in h


def test_moved_word_re_aims_a_conditional_branch(tmp_path):
    _cc_or_skip()
    h = HOOK.read_text(encoding="utf-8")
    code = "#include <stdio.h>\n" + "\n".join(_lift(h, s) for s in (
        "static unsigned long a64_cond_target(", "static unsigned a64_cond_retarget(")) + r"""
int main(void)
{
    /* ELG Spike 3's agent_header: cbz x0, +0x54 at 0x5488f0 */
    printf("%lx\n", a64_cond_target(0x5488f0ul, 0xb40002a0u));
    /* the same cbz, from the slot's word 40 to its stub at word 44 (16 bytes on) */
    printf("%08x\n", a64_cond_retarget(0x1000ul + 40 * 4, 0x1000ul + 44 * 4, 0xb40002a0u));
    /* tbz w3, #5, -8 ; b.ne +12 ; b -0x100 */
    printf("%lx\n", a64_cond_target(0x2000ul, 0x36280003u | ((0x3ffeu) << 5)));
    printf("%lx\n", a64_cond_target(0x2000ul, 0x54000061u));
    printf("%lx\n", a64_cond_target(0x2000ul, 0x17ffffc0u));
    /* not a branch: 0 */
    printf("%lx\n", a64_cond_target(0x2000ul, 0xd2800001u));
    return 0;
}
"""
    out = _host_run(tmp_path, code, flags=("-Wno-unused-function",)).split()
    assert out == ["548944", "b4000080", "1ff8", "200c", "1f00", "0"]


def test_the_hook_layer_no_longer_refuses_a_branch_first():
    h = HOOK.read_text(encoding="utf-8")
    mw = _lift(h, "static unsigned moved_word(")
    assert "a64_cond_target(addr, w)" in mw and "!a64_is_bl(w)" in mw
    assert "0xd61f0200u" in mw                      # br x16: the far jump to where the branch went


# ---- the Insider gate's achievement query, on 64-bit ARM ---------------------------------------------------
# Star Wars ELG 1.10 (Spike 3, games/game sha1 ceb8d70b...), 0x295260..0x2952c8: the GAME_ACHIEVEMENT_QUERY sender.
ELG_SENDER = [0xd10183ff, 0xaa0103e5, 0x90002024, 0xf9468484, 0xd2800023, 0x52800382, 0xa90453f3, 0xaa0003f3,
              0x910043f4, 0xaa1403e1, 0xf9400400, 0xb94010a5, 0xf9400000, 0xf9002bfe, 0xf9400086, 0xf9001fe6,
              0xd2800006, 0x390023e5, 0x940af2f6, 0x340002c0, 0xf9400a60, 0x900017c4, 0xf00017a2, 0x9102c084,
              0x912a8042, 0xd2800025, 0x5280e6c3]


def test_the_achievement_query_is_found_in_elg_spike3_code(tmp_path):
    _cc_or_skip()
    src = RUNTIME.read_text(encoding="utf-8")
    words = ", ".join("0x%08xu" % w for w in ELG_SENDER)
    code = r"""
#include <stdio.h>
#define pm_addr unsigned long   /* the a64 build's (_host_run puts the 32-bit typedef first) */
static const unsigned W[] = { %s };
#define BASE 0x295260ul
static unsigned code_word64(pm_addr at)
{
    return at >= BASE && at < BASE + sizeof W ? W[(at - BASE) / 4] : 0;
}
%s
%s
int main(void)
{
    pm_addr at;
    for (at = BASE; at < BASE + sizeof W; at += 4)
        if (achq_loads_a64(at, 0x58d0b0ul))
            printf("%%lx %%d\n", at, achq_type_before_a64(at, 0x551e80ul));
    printf("wrong-begin %%d\n", achq_type_before_a64(0x2952bcul, 0x551e84ul));
    return 0;
}
""" % (words, _lift(src, "static int achq_loads_a64("), _lift(src, "static int achq_type_before_a64("))
    out = _host_run(tmp_path, code, flags=("-Wno-unused-function",)).split("\n")
    assert out[0] == "2952bc 28"                     # type 28, as on every Spike 2 build measured
    assert out[1] == "wrong-begin -1"


def test_achq_find_takes_the_64_bit_look_on_spike3():
    src = RUNTIME.read_text(encoding="utf-8")
    f = _lift(src, "static int achq_find(pm_addr begin)")
    assert "PM_A64 ? MAP_R | MAP_GAME : how" in f             # the words are in read-only data there
    assert "!achq_loads_a64(at, str) || (t = achq_type_before_a64(at, begin)) < 0" in f
    assert "!achq_loads(at, str) || (t = achq_type_before(at, begin)) < 0" in f


def test_a_switch_id_is_masked_to_its_16_bits_on_64_bit_arm():
    src = RUNTIME.read_text(encoding="utf-8")
    f = _lift(src, "static void on_switch_hit(pm_reg *r)")
    assert re.search(r"#if PM_A64\s+id &= 0xffffu;", f)
    assert 'hit_log_left = pm_port_value("switch_hit_log", 0);' in src


def test_the_core_score_path_holds_addresses_in_pm_addr():
    src = RUNTIME.read_text(encoding="utf-8")
    assert 'pm_addr f32 = fn("score_add32"), f = fn("score_add");' in _lift(src, "uint64_t pm_score_add(")
    assert 'pm_addr s32 = data("scores32"), s64 = data("scores");' in _lift(src, "uint64_t pm_score(")
    assert not re.search(r'^\s*unsigned \w+ = (fn|data)\("[a-z_0-9]+"\);', src, re.M)


# ---- the first Spike 3 port ---------------------------------------------------------------------------------
def _lines(kind):
    out = []
    for raw in PORT.read_text(encoding="utf-8").splitlines():
        t = raw.split()
        if t and t[0] == kind:
            out.append(t)
    return out


SOUND_SITES = {"callout", "callout_nth", "sound_play", "sound_nth", "sound_active", "sound_stop",     # PAD-1282
               "sound_worker", "sound_resolve", "sound_lookup"}
# PAD-1283: the lamp layer and the game's own light shows (tests/test_pad1283_spike3_lights.py)
LIGHT_SITES = {"lamp_group", "lamp_free_owner", "show_priority", "show_start", "event_post_replacing", "event_cancel",
               "proc_exists", "proc_create", "show_1", "show_2", "show_3", "show_4", "show_5"}
LIGHT_VALUES = {"lamp_slot_size", "lamp_slot_level", "lamp_slot_alpha", "lamp_slot_fade", "lamp_slot_used",
                "lamp_group_prio", "lamp_group_next", "event_next", "event_flags", "event_show_flag", "event_show_id",
                "proc_exit_hooks", "proc_exit_slots", "show_proc"}


# PAD-1284: a mode's screen, its words and its clip
SCENE_SITES = {"dynamic_cast", "resource_get", "find_node", "find_text", "set_text", "surface_find",
               "surface_set_video", "surface_play", "surface_stop", "surface_state", "surface_position",
               "surface_duration"}
SCENE_VALUES = {"scene_player_scene", "node_visible_vfn", "surface_playing"}
# PAD-1285: a mode's multiball, its held coil (the right control gate) and its blocks of the game's three modes
PLAY_SITES = {"balls_in_play", "multiball_serve", "proc_sleep", "adjustment", "coil_fire", "coil_take", "coil_give",
              "block_start_0", "block_start_1", "block_start_2"}
PLAY_DATA = {"game_flags": "0x00749630", "game_flag_count": "0x005a37c8", "coil_count": "0x0073e1d8",
             "coil_table": "0x00749300", "right_gate_obj": "0x00711730"}
PLAY_VALUES = {"magnet_proc", "right_gate_ctl", "right_gate_devoff", "right_gate_off_slot", "right_gate_dev",
               "game_flags_at", "mode_flag_1", "mode_flag_2", "mode_flag_3"}


def test_elg_spike3_port_carries_the_core_and_only_proven_entries():
    sites = {t[1]: t for t in _lines("site")}
    assert set(sites) == {"tick", "hook_dispatch", "score_add", "switch_hit", "switch_hit2", "switch_edge",  # PAD-1322
                          "agent_header", "agent_begin",
                          "coop_player_change", "coop_add_player",                  # PAD-1326: co-op play
                          "challenge_menu", "challenge_menu_pick",                  # PAD-1327
                          "challenge_scores", "game_scores", "challenge_score_entry", "challenge_scores_gate",
                          "challenge_pages_0", "challenge_pages_1", "audit_add",  # PAD-1327: records
                          "coil_frame", "coil_off",                                 # PAD-1329: spare outputs
                          "challenge_balls", "challenge_balls_2", "challenge_balls_at_0", "challenge_balls_at_1",
                          "challenge_balls_at_2", "challenge_balls_at_3", "challenge_end_ball",
                          "challenge_extra_ball", "ball_launch",                    # PAD-1330: its own challenges
                          "attract_sleep", "attract_show", "player_advance",       # PAD-1328: the attract table
                          } | SOUND_SITES | LIGHT_SITES | SCENE_SITES | PLAY_SITES
    for t in sites.values():
        t = t[:t.index("#")] if "#" in t else t                 # a show's line ends in a note (PAD-1283)
        assert len(t) == 5 and all(re.fullmatch(r"0x[0-9a-f]{8}", x) for x in t[2:])
    assert sites["tick"][2:] == ["0x00247940", "0xd2800001", "0x528006e0"]
    assert sites["hook_dispatch"][2] == "0x002274e0" and sites["hook_dispatch"][4] == "0x71033c1f"   # cmp w0, #0xcf
    assert sites["agent_header"][3] == "0xb40002a0"                                                 # cbz x0
    data = {t[1]: t[2] for t in _lines("data")}
    assert data == {"cur_player": "0x006b1a1a", "scores": "0x007122c0", "score_mult": "0x006a7f30",
                    "mode_mask": "0x0079206c", "sound_channels": "0x00733340", "sound_requests": "0x006fd360",
                    "sound_request_count": "0x005a38c8",                         # the sound ones: PAD-1282
                    "challenge_scores_table": "0x006c4b40", "challenge_scores_count": "0x006a3398",   # PAD-1327
                    "event_head": "0x007493d8", "event_current": "0x007493e0",   # the lamp layer's: PAD-1283
                    "lamp_layers": "0x00735e68", "light_count": "0x0073ec88",
                    "resource_manager": "0x00712bf8", "typeinfo_resource": "0x0068b850",  # the scene lookup's: PAD-1284
                    "typeinfo_scene_player": "0x0068fb48", **PLAY_DATA,
                    "coop_player": "0x006b1a1a", "coop_players": "0x00792200",      # PAD-1326: co-op play
                    "message_table": "0x006c96e8",
                    "sw_struct": "0x007477e0", "sw_blocks": "0x00747a78",              # PAD-1329: spare inputs
                    "attract_table": "0x006a45c0"}                                  # PAD-1328
    values = {t[1]: t[2] for t in _lines("value") if not t[1].startswith(("sound_", "countdown_"))
              and t[1] not in LIGHT_VALUES and not t[1].startswith("show_secs_") and t[1] not in SCENE_VALUES
              and t[1] not in PLAY_VALUES and not t[1].startswith(("switch_", "challenge_", "attract_"))}   # PAD-1322 / 1327 / 1328
    assert values == {"mode_mask_busy": "0x210", "ball_end_event": "0x34",
                      "ball_launch_flag": "12", "ball_launch_wait_flag": "13",   # PAD-1330: its own challenges
                      # PAD-1286: the game's mode books, each flag by its name (the same ids on both builds)
                      "place_flag_completed_0": "69", "place_flag_completed_1": "67", "place_flag_completed_2": "68",
                      "done_flag_0": "66",
                      "coop_ball_msg": "1255"}                  # PAD-1326: its Spike 2 build's number


def test_elg_spike3_switch_ids_are_the_ones_the_rig_measured():
    by_name = {" ".join(t[3:]).lower(): int(t[1]) for t in _lines("switch")}
    # each pressed on the Spike 3 rig, the id its switch_hit call carried (value switch_hit_log)
    assert by_name["death star target"] == 26
    assert by_name["left luke orbit"] == 28
    assert by_name["hidden target"] == 29
    assert by_name["top lane left"] == 30
    assert by_name["center target"] == 33
    assert by_name["leia orbit"] == 36
    assert by_name["yoda mystery target"] == 59
    assert len(by_name) == 30


def test_the_spike3_port_is_not_among_the_spike2_ports():
    """The Spike 2 lookups list ports/*.port; a Spike 3 port of the same game and version stays out of them."""
    assert not (SDK / "ports" / "star_wars_elg-1.10_spike3.port").exists()
    assert PORT.parent.name == "spike3"
    assert "star_wars_elg-1.10.port" in [p.name for p in (SDK / "ports").glob("*.port")]   # Spike 2's, as it was


# ---- the drafter ----------------------------------------------------------------------------------------------
def test_s3port_values_carried_are_only_the_proven_ones():
    import importlib.util
    spec = importlib.util.spec_from_file_location("s3port", ROOT / "tools" / "spike3_emu" / "s3port.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    assert S.VALUES_PROVEN == ("mode_mask_busy",)
    assert set(S.SITES_PROVEN) == {"tick", "hook_dispatch", "score_add", "agent_header", "agent_begin"} | SOUND_SITES | (
        LIGHT_SITES - {"lamp_free_owner"} - {"show_%d" % n for n in range(1, 6)})
    assert S.sext(0x3FFFFFF, 26) == -1 and S.sext(0x10, 26) == 16

    class T:                                         # site_ok on three first instructions
        def __init__(self, w):
            self.w = w

        def u32(self, va):
            return self.w
    assert S.site_ok(T(0xb40002a0), 0) == ""                     # cbz: the hook layer moves it now
    assert "bl" in S.site_ok(T(0x94000010), 0)
    assert "literal" in S.site_ok(T(0x58000050), 0)
