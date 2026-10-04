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
    return _build(tmp_path_factory, SCREEN_STUBS, "aside")


def _build(tmp_path_factory, stubs, tag):
    cc = _cc()
    d = tmp_path_factory.mktemp(tag)
    src = HARNESS
    # pm_show prints the clock: the harness's own definition of now_ms comes after the screen stubs
    src = src.replace("static unsigned long now_ms;\n", "")
    src = src.replace("#include <fcntl.h>\n", "#include <fcntl.h>\nstatic unsigned long now_ms;\n", 1)
    for old, new in stubs:
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
def _block_section(name):
    port = _port(name)
    named = {int(k[1].rsplit("_", 1)[1]): v for k, v in port.items() if k[0] == "site" and k[1].startswith("block_start_")}
    objs = {int(k[1].rsplit("_", 1)[1]): v[0] for k, v in port.items() if k[0] == "data" and k[1].startswith("block_obj_")}
    return port, named, objs


def _default(name):
    """The port's `text block_default <ids>`: the ids a mode that lists none holds off."""
    for line in (SDK / "ports" / name).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts[:2] == ["text", "block_default"]:
            return [int(w) for w in parts[2:]]
    return []


def test_the_premium_port_names_every_non_multiball_mode_and_checks_two():
    name = "godzilla_le-1.16.port"
    port, named, objs = _block_section(name)
    assert set(named) == set(range(12, 27))                  # every mode but the multiballs 1-11
    assert named[21] == [0x000b98fc, 0xe92d4ff0, 0xe1a05000] and named[23] == [0x0010e91c, 0xe92d4ff0, 0xe24dd014]
    assert objs[21] == 0x007b5b20 and objs[23] == 0x007b5c88 and set(objs) == set(named)
    assert _default(name) == [21, 23]                        # the two checked on a machine card
    assert ("data", "block_mode_table") not in port and ("site", "stock_mode_start") not in port


@pytest.mark.parametrize("name", ["deadpool_le-1.14.port", "deadpool_pro-1.16.port"])
def test_the_deadpool_ports_name_their_modes_and_check_none(name):
    port, named, objs = _block_section(name)
    assert len(named) == 19 and set(objs) == set(named)
    assert 127 in named                                        # Battle Juggernaut: the scanner's 1000, a free id
    assert _default(name) == []                              # nothing checked on a machine yet
    assert not set(named) & {8, 9, 11, 12, 16, 17, 18}         # Deadpool's multiballs


def test_the_premium_starts_match_the_game():
    """Each named start is that mode's own start (vptr + 0x20 on Godzilla, the vptr being the vtable + 8) and
    starts as the port says."""
    name = "godzilla_le-1.16.port"
    path = next((p for p in ELVES[name] if p and os.path.isfile(p)), None)
    if not path:
        pytest.skip("game program not present for %s" % name)
    e, (port, named, objs) = _Elf(path), _block_section(name)
    vtables = {21: 0x63af40, 23: 0x640ed8}                    # cmode_jet_fighter_attack, cmode_tesla_strike
    for mid, vt in vtables.items():
        assert e.u32(vt + 8 + 0x20) == named[mid][0], mid
    for mid, site in named.items():
        assert (e.u32(site[0]), e.u32(site[0] + 4)) == (site[1], site[2]), mid
    # RuleJetFighters::v[25] starts 21 so: mov r1,#21, bl get, ldr [r0], ldr [r3,#0x20]
    assert e.u32(0x1592b8) == 0xe3a01015 and e.u32(0x1592c4) == 0xe5903000 and e.u32(0x1592c8) == 0xe5933020


def test_the_premium_port_hides_only_the_battle_shots_from_the_battle_rule():
    port = _port("godzilla_le-1.16.port")
    assert port[("site", "block_battle_shots")] == [0x00124b3c, 0xe92d40f8, 0xe1a06002]
    assert port[("value", "block_battle_lo")] == [0x00300000]          # the Left and Right ramp
    assert port[("value", "block_battle_hi")] == [0x00000020]          # the scoop


def test_the_battle_rules_shot_handler_matches_the_game():
    """RuleBattle::v[25] (vtable 0x642690 + 8 + 25 * 4): it tests r2 for the two ramps and r3 for the scoop,
    and the scoop's path creates the process that waits for effect 132, the BATTLE SELECTION screen."""
    name = "godzilla_le-1.16.port"
    path = next((p for p in ELVES[name] if p and os.path.isfile(p)), None)
    if not path:
        pytest.skip("game program not present for %s" % name)
    e, port = _Elf(path), _port(name)
    site = port[("site", "block_battle_shots")]
    assert e.u32(0x642690) == 0 and e.u32(0x642690 + 8 + 25 * 4) == site[0]
    assert (e.u32(site[0]), e.u32(site[0] + 4)) == (site[1], site[2])
    assert e.u32(0x124b58) == 0xe2062601 and e.u32(0x124b68) == 0xe2062602   # and r2, r6, #0x100000 / #0x200000
    assert e.u32(0x124b78) == 0xe2073020                                      # and r3, r7, #0x20
    assert e.u32(0x124d40) == 0xe3a02084 and e.u32(0x124d48) == 0xe58020a0   # mov r2,#132; str r2,[r0,#0xa0]



# ---- PAD-363: a mode file's game_modes / block_modes ------------------------------------------------------------
BLOCK_STUBS = [(old, new) for old, new in SCREEN_STUBS] + [
    ("int pm_aside(void) { return in_game ? stock : 0; }",
     "int pm_aside(void) { return in_game ? stock : 0; }\n"
     "int pm_block_list(const unsigned char *ids, int n) { int i; printf(\"BLOCKLIST\"); "
     "for (i = 0; i < n; i++) printf(\" %u\", ids[i]); printf(\"%s\\n\", n ? \"\" : \" defaults\"); return 1; }\n"
     "int pm_block_game_modes(int on) { printf(\"BLOCK %d\\n\", on); return 1; }"),
]


@pytest.fixture(scope="module")
def harness_block(tmp_path_factory):
    return _build(tmp_path_factory, BLOCK_STUBS, "block")


def test_game_modes_block_lists_the_modes_and_holds_them_from_start_to_end(harness_block, tmp_path):
    out = _run(harness_block, tmp_path, RUSH + "game_modes block\nblock_modes 21, 23\n", "shot", "0x08000000",
               "tick", "30", "ball_end")
    assert "unknown key" not in out
    lines = out.splitlines()
    i_list, i_on = lines.index("BLOCKLIST 21 23"), lines.index("BLOCK 1")
    i_start = next(i for i, ln in enumerate(lines) if "RUSH START" in ln)
    i_end = next(i for i, ln in enumerate(lines) if "RUSH END" in ln)
    assert i_list < i_on < i_start and "BLOCK 0" in lines[i_start:i_end + 2]


def test_game_modes_give_way_waits_for_the_games_mode_and_ends_when_one_begins(harness_block, tmp_path):
    out = _run(harness_block, tmp_path, RUSH + "game_modes give_way\n", "stock", "1", "shot", "0x08000000",
               "tick", "10", "stock", "0", "shot", "0x08000000", "tick", "10", "stock", "1", "tick", "10")
    assert "one of the game's modes is running - its trigger count is kept" in out
    assert out.index("STOCK 0") < out.index("RUSH START") < out.index("RUSH END (the game's own mode began)")
    assert "BLOCK 1" not in out


def test_game_modes_stack_is_what_a_mode_file_without_the_key_does(harness_block, tmp_path):
    out = _run(harness_block, tmp_path, RUSH, "stock", "1", "shot", "0x08000000", "tick", "10")
    assert "RUSH START" in out and "BLOCK" not in out and "game's own mode began" not in out


@pytest.mark.parametrize("value", ["sideways", ""])
def test_a_game_modes_that_is_not_known_is_stack(harness_block, tmp_path, value):
    out = _run(harness_block, tmp_path, RUSH + "game_modes %s\n" % value, "shot", "0x08000000", "tick", "5")
    assert "game_modes needs stack, give_way or block" in out and "RUSH START" in out


def test_the_generator_reads_godzillas_modes_as_the_port_has_them():
    name = "godzilla_le-1.16.port"
    path = next((p for p in ELVES[name] if p and os.path.isfile(p)), None)
    if not path:
        pytest.skip("game program not present for %s" % name)
    from pinball_decryptor.plugins.stern import game_mode_blocks as G
    modes = {m.id: m for m in G.read_modes(open(path, "rb").read())}
    assert modes[21].name == "Jet Fighter Attack" and modes[21].start == 0x000b98fc and modes[21].blockable
    assert modes[1].multiball and not modes[1].blockable                # Godzilla Multiball: never offered
    _port_now, named, _objs = _block_section(name)
    assert {i for i, m in modes.items() if m.blockable} == set(named)


# ---- PAD-363: the Modes tab's lever - ModeSpec.game_modes / block_modes ------------------------------------------
def _title(name):
    from pinball_decryptor.plugins.stern import mode_project as MP
    return MP.profile_from_port(os.path.join(SDK, "ports", name))


def MP_game_modes_of_a_port_without_block_lines():
    from pinball_decryptor.plugins.stern import mode_project as MP
    return MP._game_modes(dict(site={"score_add": (1, 2, 3)}, data={}, value={}, text={}))


def test_a_title_lists_the_modes_its_port_can_hold_off_and_which_are_checked():
    dp, gz = _title("deadpool_le-1.14.port"), _title("godzilla_le-1.16.port")
    rows = {i: (name, on) for i, name, on in dp.game_modes}
    assert len(rows) == 19 and rows[21] == ("Chimichanga", False) and rows[24] == ("Berserker Rage", False)
    assert rows[6] == rows[7] == ("Quest", False)                       # two of its modes share a name
    assert not set(rows) & {8, 9, 11, 12, 16, 17, 18}                    # never a multiball
    assert [i for i, _n, on in gz.game_modes if on] == [21, 23]          # the port's checked defaults
    assert MP_game_modes_of_a_port_without_block_lines() == ()      # no block lines: nothing to offer


def test_game_modes_validates_and_writes_only_what_differs_from_stack():
    from pinball_decryptor.plugins.stern import mode_project as MP
    dp, gz = _title("deadpool_le-1.14.port"), _title("godzilla_le-1.16.port")
    spec = MP.ModeSpec()
    assert MP.validate_game_modes(spec, dp) == [] and MP.game_modes_lines(spec) == []
    spec.game_modes = "sideways"
    assert MP.validate_game_modes(spec, dp) == ["What it does about the game's own modes is stack, give_way or block."]
    spec.game_modes = "give_way"
    assert MP.game_modes_lines(spec) == ["game_modes     give_way"]
    spec.game_modes = "block"
    assert MP.validate_game_modes(spec, dp) == ["Tick at least one of Deadpool LE 1.14's modes to hold off."]
    assert MP.validate_game_modes(spec, gz) == [] and MP.held_off(spec, gz) == (21, 23)   # the defaults
    assert MP.game_modes_lines(spec) == ["game_modes     block"]
    spec.block_modes = [24, 21, 8]
    assert MP.validate_game_modes(spec, dp) == ["Deadpool LE 1.14 has no mode the app can hold off numbered 8."]
    spec.block_modes = [24, 21]
    assert MP.validate_game_modes(spec, dp) == [] and MP.held_off(spec, dp) == (21, 24)
    assert MP.game_modes_lines(spec) == ["game_modes     block", "block_modes    21 24"]
    assert MP.validate_game_modes(spec, _title("godzilla_pro-1.15.port")) == []   # the runtime gives way there
    text = MP.runtime_cfg(spec, "rush")
    assert "\ngame_modes     block\n" in text and "\nblock_modes    21 24\n" in text


def test_a_mode_moved_to_another_title_keeps_the_modes_it_holds_off_by_name():
    import dataclasses
    from pinball_decryptor.plugins.stern import mode_project as MP
    dp = _title("deadpool_le-1.14.port")
    pro = dataclasses.replace(_title("deadpool_pro-1.16.port"),
                              game_modes=((3, "Chimichanga", False), (9, "Quest", False), (11, "Quest", False)))
    spec = MP.ModeSpec(title=dp.key, start_shot=dp.shots[0][0], scoring_shots=[dp.shots[0][0]],
                       game_modes="block", block_modes=[21, 6, 24])
    out, _dropped = MP.retarget(spec, pro)
    assert out.block_modes == [3, 9, 11] and out.game_modes == "block"   # Berserker Rage is not on it


# ---- PAD-363: every title - ids up to 127, plain-C starts, the words a veto can move ----------------------------
def test_block_modes_takes_ids_up_to_127_and_refuses_past_it(harness_block, tmp_path):
    out = _run(harness_block, tmp_path, RUSH + "game_modes block\nblock_modes 21 70 127 128\n", "shot", "0x08000000",
               "tick", "5")
    assert "BLOCKLIST 21 70 127" in out.splitlines()
    assert "block_modes: 128 is not a mode id the runtime can hold off (0-127)" in out


def test_a_block_with_no_list_asks_for_the_ports_defaults(harness_block, tmp_path):
    out = _run(harness_block, tmp_path, RUSH + "game_modes block\n", "shot", "0x08000000", "tick", "5")
    assert "BLOCKLIST defaults" in out.splitlines()


def test_a_veto_moves_only_words_that_do_not_touch_the_pc():
    from pinball_decryptor.plugins.stern.game_mode_blocks import movable
    ok = [(0xe92d40f8, 0xe1a06002), (0xe3a01000, 0xe30c36e8), (0xe5902000, 0xe92d40f8), (0xe3a00000, 0xe12fff1e),
          (0xe320f000, 0xe92d4010), (0xe30f3fff, 0xe92d4010)]
    refused = [(0xea03df43, 0xe3a00000),      # D&D's Finish State: a branch
               (0xe3a01000, 0xeaffffc8),      # D&D's Map Orange 2a: a tail call
               (0xe59f3010, 0xe92d4010),      # a literal load
               (0xe12fff1e, 0xe92d4010),      # returns at once: the second word is the next function's
               (0xe28f0008, 0xe92d4010),      # an add from the pc
               (0xe8bd8010, 0xe92d4010),      # a pop into the pc
               (0xe12fff33, 0xe92d4010)]      # blx r3
    assert all(movable(w) for w in ok) and not any(movable(w) for w in refused)


def test_the_runtime_tells_a_plain_c_start_by_its_own_hook():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    assert "t[2] = 0xe3a01000u | n;   /* mov r1, #n */" in src               # the hook's index reaches the logger
    assert "(!block_obj[id] || block_obj[id] == r[0])" in src             # no object: the start is the mode's own
    assert "#define BLOCK_IDS 128" in src


def test_venom_names_its_modes_past_31_and_never_a_multiball():
    rows = {i: n for i, n, _on in _title("venom_le-1.07.port").game_modes}
    assert len(rows) == 55 and rows[90] == "Symbiote Mania" and rows[31] == "Mini Mode 13"
    assert not {59, 60, 64, 69, 72, 87} & set(rows)                         # its multiballs
    dd = {i: n for i, n, _on in _title("dungeons_and_dragons_le-1.00.port").game_modes}
    assert dd[43] == "Map Arabel" and 41 not in dd and 65 not in dd        # Finish State, Orange 2a: not movable


# ---- PAD-363: Godzilla's Saucer Attack rule, and a start refused with 0 ------------------------------------------
@pytest.mark.parametrize("name,handler", [("godzilla_le-1.16.port", 0x00174f9c), ("godzilla_pro-1.15.port", 0x001715c4),
                                          ("godzilla_pro-1.16.port", 0x001715c4)])
def test_every_godzilla_hides_the_pops_from_the_saucer_rule_while_a_mode_blocks(name, handler):
    """David's Premium (2026-10-04): "overlapping text for saucer mode feedback under Ghidorah" - the pop bumper
    lights Saucer Attack (a rule, no mode to refuse) and its words land on ours. RuleSaucerAttack::v[25] tests lo
    0x40 (the pop bumper) and hi 0x400 / 0x100; the battle rule's lines are on every Godzilla now too."""
    port = _port(name)
    assert port[("site", "block_rule_0")] == [handler, 0xe92d47f0, 0xe1a04002]
    assert port[("value", "block_rule_lo_0")] == [0x40] and port[("value", "block_rule_hi_0")] == [0x500]
    assert ("site", "block_battle_shots") in port and port[("value", "block_battle_hi")] == [0x20]


def test_the_runtime_hooks_other_rules_and_can_refuse_a_start_with_0():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    assert "#define BLOCK_RULES 8" in src and "hook_n(fn(name), on_rule_shots, (unsigned)i)" in src
    assert "t[7] = 0x13a00000u | refused;" in src                         # movne r0, #0 or #1
    assert 'pm_snprintf(ret, sizeof ret, "block_ret_%u", id);' in src
