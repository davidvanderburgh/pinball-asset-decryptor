"""PAD-1041: Prolonged Competition on every Spike 2 game's start menu (pad_mode_runtime.c "Prolonged Competition on
the start menu", plugins/stern/prolonged_comp.py).

Venom and Dungeons & Dragons offer COMPETITION GAME PLAY UNTIL POWERED OFF on their start menu; the other games have
only the one-game COMPETITION entry, which sets FG_PLAYER_COMPETITION_MODE_ACTIVE and nothing else. The runtime adds a
PROLONGED entry to that menu and keeps the flag set at every game's start until the machine is switched off. The toggle
rule is lifted verbatim and run on the host; the shipped programs' flag and captions are read when they are here."""
import glob
import os
import pathlib

import pytest

from tests import test_spike2_mode_roster as R

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"

MAIN = r"""
#include <stdio.h>
@FNS@
int main(void)
{
    int on = 0, g;
    /* picked on game 1, plain Starts for games 2 and 3, picked again for game 4, a plain Start for game 5 */
    static const int picked[] = { 1, 0, 0, 1, 0 };
    for (g = 0; g < 5; g++) {
        on = comp_next(on, picked[g]);
        printf("game %d %d\n", g + 1, on);
    }
    return 0;
}
"""


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def test_picked_once_every_game_is_competition_until_picked_again(tmp_path):
    fns = R._lift(_src(), "static int comp_next(int on, int picked)")
    out = R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()
    assert out == ["game 1 1", "game 2 1", "game 3 1", "game 4 0", "game 5 0"]


def test_it_arms_before_the_score_gate_and_alone_keeps_insider_connected():
    src = _src()
    assert src.index("comp_arm();") < src.index("if (!insider_arm()) return;")
    assert ("(clipv_only || sndm_only || pic_only || idle_only || hand_cfg_only() || comp_cfg_only()) "
            "&& !attract_wanted() && !coop_wanted()") in src
    arm = R._lift(src, "static void comp_arm(void)")
    # the start menu's two sites (the challenges' menu lines) and the event bus, each a hook of its own
    assert 'hook(fn("challenge_menu_pick"), comp_menu_picked)' in arm and "hook(bus->addr, on_comp_dispatch)" in arm
    assert 'hook_full(fn("challenge_menu"), comp_menu_built)' in arm      # Elvira keeps the count in a register
    start = R._lift(src, "static void comp_game_start(void)")
    assert "if (comp.on) game_flag_set(comp.flag);" in start and "else if (was) game_flag_clear(comp.flag);" in start
    # the pick plays as Standard: kind 0 on the kind-jump menus (r3) and written into the entry on the others
    picked = R._lift(src, "static void comp_menu_picked(unsigned *r)")
    assert "else r[3] = 0;" in picked and "*(unsigned *)(e8 + MENU_KIND_AT) = 0;" in picked


def _port(name):
    from pinball_decryptor.plugins.stern import mode_project as MP
    return MP.read_port(str(PORTS / name))


def test_every_build_whose_start_menu_the_app_knows_is_offered_it():
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import prolonged_comp as PCo
    offered = {k for k, p in MP.profiles().items() if not PCo.title_refusal(p)}
    menus = {k for k, p in MP.profiles().items()
             if "challenge_menu" in MP.read_port(MP.port_path(p))["site"]}
    assert offered == menus and len(offered) == 49
    for key in ("deadpool_pro_1_16", "james_bond_le_1_06", "star_wars_pro_1_31", "turtles_pro_1_59",
                "elvira3_1_13", "mando_pro_1_45", "foo_fighters_le_1_04"):
        assert key in offered, key


def test_venom_and_dnd_keep_their_own():
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import prolonged_comp as PCo
    for key in ("venom_pro_1_07", "venom_le_1_07", "dungeons_and_dragons_pro_1_10"):
        assert "already" in PCo.title_refusal(MP.profile(key)), key
    assert "start menu yet" in PCo.title_refusal(MP.profile("godzilla_le_1_16"))
    assert PCo.title_refusal(None) == PCo.NO_TITLE


def test_the_tick_is_kept_in_the_project(tmp_path):
    from pinball_decryptor.plugins.stern import prolonged_comp as PCo
    assert not PCo.load(str(tmp_path))
    assert PCo.save(str(tmp_path), True) is False
    assert PCo.load(str(tmp_path))
    assert PCo.save(str(tmp_path), False) is True
    assert not PCo.load(str(tmp_path))


def test_comp_cfg_rides_with_the_runtime():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mode_install", ROOT / "tools" / "spike2_emu" / "mode_install.py")
    mi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mi)
    assert ("comp.cfg", 0o100644) in mi.EXTRA_FILES and "comp.cfg" in mi.STANDALONE_FILES
    for sh in ("cardmodes.sh", "tryit.sh"):
        assert "comp.cfg" in (ROOT / "tools" / "spike2_emu" / "modes" / sh).read_text(encoding="utf-8"), sh
    assert 'grep -c "^comp on"' in (ROOT / "tools" / "spike2_emu" / "modes" / "cardmodes.sh").read_text(encoding="utf-8")


ELFS = sorted(p for d in os.environ.get("PAD_GAME_ELFS", "C:/tmp/PAD-1041/elfs;C:/tmp/PAD-1010/elfs").split(";")
              for p in glob.glob(os.path.join(d, "*.elf")))


@pytest.mark.skipif(not ELFS, reason="no shipped game programs here (PAD_GAME_ELFS)")
def test_every_shipped_program_names_the_flag_and_the_captions():
    from pinball_decryptor.plugins.stern import prolonged_comp as PCo
    seen = {}
    for p in ELFS:
        name = os.path.basename(p)
        if name in seen:
            continue
        seen[name] = PCo.cfg_values(PCo.cfg_text(open(p, "rb").read(), only=True))
    # FG_PLAYER_COMPETITION_MODE_ACTIVE is 17 on every latest build; the captions are the start menu's own
    assert {v["flag"] for v in seen.values()} == {17}
    assert all((v["caption"], v["caption_end"]) in ((1919, 1914), (1920, 1915)) for v in seen.values())
    fo = [v for k, v in seen.items() if k.startswith("foo_fighters_le")]
    if fo:
        assert fo[0]["caption"] == 1920 and fo[0]["caption_end"] == 1915


def test_cfg_text_says_only_when_the_card_has_no_modes(monkeypatch):
    from pinball_decryptor.plugins.stern import prolonged_comp as PCo
    monkeypatch.setattr(PCo, "card_lines", lambda elf: (17, 1919, 1914))
    on, off = PCo.cfg_text(b"", True), PCo.cfg_text(b"", False)
    assert "only" in on.split() and "only" not in off.split() and "comp on" in off
    assert PCo.cfg_values(on) == {"flag": 17, "caption": 1919, "caption_end": 1914}


def test_a_program_with_no_competition_flag_is_refused():
    from pinball_decryptor.plugins.stern import prolonged_comp as PCo
    with pytest.raises(PCo.CompError):
        PCo.card_lines(b"not an elf")


def test_mode_write_puts_comp_cfg_beside_the_runtime(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import prolonged_comp as PCo
    monkeypatch.setattr(PCo, "card_lines", lambda elf: (17, 1919, 1914))
    prof = MP.profile("deadpool_pro_1_16")
    plan = MW.ModePlan(project=str(tmp_path), profile=prof, port=MP.port_path(prof), build=None)
    MW.comp_into(plan, b"", str(tmp_path / "scratch"), only=True)
    assert pathlib.Path(plan.comp_file).read_text(encoding="utf-8").splitlines()[1:] == [
        "comp on", "flag 17", "caption 1919", "caption_end 1914", "only"]
    assert any(l.startswith("prolonged competition: ") for l in plan.lines)
    venom = MP.profile("venom_pro_1_07")
    plan2 = MW.ModePlan(project=str(tmp_path), profile=venom, port=MP.port_path(venom), build=None)
    with pytest.raises(MW.ModeWriteError, match="already"):
        MW.comp_into(plan2, b"", str(tmp_path / "scratch2"), only=True)


def test_the_card_staging_carries_comp_cfg(tmp_path):
    from pinball_decryptor.plugins.stern import mode_write as MW
    src = (ROOT / "pinball_decryptor" / "plugins" / "stern" / "mode_write.py").read_text(encoding="utf-8")
    assert 'if getattr(result, "comp_file", ""):' in src and "comp_into(result, game_elf, scratch, only=True)" in src
    assert MW.ModePlan.__dataclass_fields__["comp_file"].default == ""
