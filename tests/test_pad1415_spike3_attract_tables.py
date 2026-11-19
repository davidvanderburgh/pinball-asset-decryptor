"""PAD-1415: attract items on the last four Spike 3 titles.

Pokemon LE 0.82, Fallout LE 0.82 and Transformers LE 0.96 walk a 24-byte {test, page, float seconds} table like the
others' 16-byte ones (gdb on the child create, rig, hidden, muted: every attract page started from the table walk);
s3port's reader missed them because the page is loaded into x1 and moved to x0 after a `cbz x1`, and on Pokemon it
took a 10-entry slideshow for the table. Walking Dead Remastered LE 0.92's items go in and play on its attract bank
(`scene attract_bank` 60ed7e50), not its play bank 71e39c43.

The tests that read the real programs run when PAD_S3_PROGRAMS names a folder of `<game>.game` files."""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "spike3_emu"))

from pinball_decryptor.plugins.stern import attract_items as AI          # noqa: E402
from pinball_decryptor.plugins.stern import clip_variants as CV          # noqa: E402
from pinball_decryptor.plugins.stern import mode_project as MP           # noqa: E402

PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")
WDR = "walking_dead_remastered_le_0_92_spike3"
ATTRACT_BANK = "60ed7e5036b8ce09d35a3e101ea6fc1380b37d97"


def _prog(game):
    path = os.path.join(PROGS, game + ".game")
    if not PROGS or not os.path.isfile(path):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    return path


def test_all_seven_spike3_titles_take_attract_items():
    for key, prof in MP.profiles().items():
        if key.endswith("_spike3") and AI.port_table(prof) is not None:
            assert AI.title_refusal(prof) == "", key
    for key in ("pokemon_le_0_82_spike3", "fallout_le_0_82_spike3", "transformers_mtmte_le_0_96_spike3", WDR):
        t = AI.port_table(MP.profiles()[key])
        assert t is not None and t["show"], key


def test_wdr_items_go_in_its_attract_bank():
    wdr = MP.profiles()[WDR]
    port = MP.read_port(MP.port_path(wdr))
    assert port["scene"]["attract_bank"] == ATTRACT_BANK
    assert port["scene"]["video_bank"].startswith("71e39c43")             # its modes' clips stay on the play bank
    assert CV.attract_scene(wdr) == "walking_dead_remastered_le/assets/lcd/auto_loaded/%s/scene.radium" % ATTRACT_BANK
    assert CV.attract_scene(wdr) != CV.bank_scene(wdr)
    for key in ("star_wars_2025_le_0_96_spike3", "pokemon_le_0_82_spike3", "star_wars_elg_1_10_spike3"):
        prof = MP.profiles()[key]
        assert CV.attract_scene(prof) == CV.bank_scene(prof), key


def test_wdr_build_reads_the_attract_bank_not_the_play_bank(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"x")
    AI.save(str(tmp_path), AI.clean({"items": [{"kind": "photo", "file": str(png), "seconds": 5, "entry": 4}]}))
    asked = []

    def read_card(scene):
        asked.append(scene)
        return None
    with pytest.raises(AI.AttractError) as e:
        AI.build(str(tmp_path), MP.profiles()[WDR], b"play bank", str(tmp_path / "out"), read_card=read_card)
    assert asked == [CV.attract_scene(MP.profiles()[WDR])]
    assert ATTRACT_BANK in str(e.value)


def test_runtime_plays_an_item_on_the_attract_bank():
    src = open(RUNTIME, encoding="utf-8").read()
    surf = src[src.index("static void *clip2_surface(void)"):]
    surf = surf[:surf.index("\n}\n")]
    assert surf.index("if (clip2_attract)") < surf.index('site("video_surface")')
    assert 'clipv_scene_surface("attract_bank")' in surf
    arm = src[src.index("static void attract_arm(void)"):src.index("/* ---- round 2: the game's own start menu")]
    assert 'if (pm_scene_id("attract_bank") && !ait_video) ait_bank = "attract_bank";' in arm
    assert "pm_scene_id(ait_bank)" in arm
    tick = src[src.index("static void ait_tick(void)"):src.index("static int attract_wanted(void)")]
    assert "clip2_attract = !ait_video && ait_bank[0] == 'a';" in tick
    assert re.search(r"pm_clip_stop\(\);[^\n]*\n\s+clip2_attract = 0;", tick)
    play = src[src.index("static void ait_play(unsigned i)"):src.index("/* ---- PAD-1407")]
    assert "scene_player_of(ait_bank)" in play


@pytest.mark.parametrize("game,table,count,stamp", [
    ("pokemon_le", 0x3197b38, 51, 0x108),
    ("fallout_le", 0x19288b0, 65, 0x108),
    ("transformers_mtmte_le", 0x9a7dd8, 59, 0x110),
])
def test_reader_finds_the_x1_loaded_tables(game, table, count, stamp):
    import s3port as S
    t = S.Elf(_prog(game))
    S.scan(t)
    port = MP.read_port(MP.port_path(next(p for k, p in MP.profiles().items() if k.startswith(game) and
                                          k.endswith("_spike3"))))
    sleep = port["site"]["proc_sleep"]
    sleep = sleep[0] if isinstance(sleep, (tuple, list)) else sleep
    s = S.attract_sequencer(t, sleep)
    assert (s["entry"], s["size"], s["count"], s["seconds_at"], s["stamp"]) == (table, 24, count, 16, stamp)
    lines = "\n".join(S.attract_lines(t, {"proc_sleep": sleep}))
    assert "data  attract_table       0x%08x" % table in lines and "site  attract_show" in lines


@pytest.mark.parametrize("game,key,names", [
    ("pokemon_le", "pokemon_le_0_82_spike3", {3: "Game Title 1", 6: "Credits Press Start", 8: "High Score1"}),
    ("fallout_le", "fallout_le_0_82_spike3", {6: "Credits Press Start", 35: "Team Scores 1"}),
    ("transformers_mtmte_le", "transformers_mtmte_le_0_96_spike3", {3: "Game Title Autobot 1", 7: "Grand Champ"}),
])
def test_attract_tab_names_their_screens(game, key, names):
    with open(_prog(game), "rb") as f:
        pages = AI.read_pages(f.read(), MP.profiles()[key])
    assert len(pages) == AI.port_table(MP.profiles()[key])["count"]
    for k, n in names.items():
        assert pages[k].name == n, (k, pages[k].name)
    assert not pages[3].sometimes and pages[8].sometimes         # the title shows every time, a high score at times


def test_wdr_items_are_sized_like_its_attract_clips(tmp_path, monkeypatch):
    # an item made in the play bank's mid-screen shape was squeezed into a pillar on the full-screen attract bank (rig)
    from types import SimpleNamespace
    from pinball_decryptor.core import video as V
    wdr = MP.profiles()[WDR]
    play = CV.bank_assets(wdr)
    att = CV.attract_scene(wdr)[:-len("scene.radium")] + "scene.assets/"
    (tmp_path / "video").mkdir()
    rows = {"bank/a.mp4": play + "1.asset", "bank/b.mp4": att + "0.asset"}
    (tmp_path / "video" / "manifest.txt").write_text("".join("%s\t/%s\n" % kv for kv in rows.items()))
    for rel in rows:
        (tmp_path / "video" / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "video" / rel).write_bytes(b"x")
    sizes = {"a.mp4": (2560, 1440), "b.mp4": (1920, 1080)}         # the play bank's is even bigger: still not taken
    monkeypatch.setattr(V, "detect_video_info", lambda p: SimpleNamespace(
        width=sizes[os.path.basename(p)][0], height=sizes[os.path.basename(p)][1]))
    assert AI.reference_slot(str(tmp_path), wdr)[0] == "video/bank/b.mp4"
    (tmp_path / "video" / "manifest.txt").write_text("bank/a.mp4\t/%s1.asset\n" % play)
    assert AI.reference_slot(str(tmp_path), wdr)[0] == "video/bank/a.mp4"   # none of its attract clips: the bank's
