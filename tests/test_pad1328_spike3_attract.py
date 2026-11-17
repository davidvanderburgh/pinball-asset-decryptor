"""PAD-1328: the attract mode's page table on Spike 3 (64-bit) programs.

s3port.attract_sequencer reads the sequencer the 64-bit way (the page loaded from a table entry, made a child process,
stamped at +0x108 and a frame slept): Star Wars ELG 1.10 28 entries of 16 bytes {test, page} at 0x6a45c0, Walking Dead
Remastered LE 0.92 48, Star Wars 2025 LE 0.96 183 and Pro 0.84 126, Pokemon LE 0.82 10 of 24 bytes {test, page, float
seconds}; Fallout LE and Transformers LE run theirs from a director with no table. The ports carry the lines, the
runtime reads the table's words pointer-sized, and the Attract tab reads a 64-bit program's pages. Showing an item is
gated off on Spike 3 (the scene show from an item's page stalls ELG in the emulator: docs/plans/spike3_modes.md).

The tests that read the real programs run when PAD_S3_PROGRAMS names a folder of `<game>.game` files (a card's
games/<game>/game, as tests/test_pad1287_spike3_port_from_spike3.py)."""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "spike3_emu"))

from pinball_decryptor.plugins.stern import attract_items as AI          # noqa: E402
from pinball_decryptor.plugins.stern import mode_project as MP           # noqa: E402

PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")

#: game -> (profile key, table, entry size, count)
TABLES = {
    "star_wars_elg": ("star_wars_elg_1_10_spike3", 0x6a45c0, 16, 28),
    "walking_dead_remastered_le": ("walking_dead_remastered_le_0_92_spike3", 0x7b5c38, 16, 48),
    "star_wars_2025_le": ("star_wars_2025_le_0_96_spike3", 0x8b7a98, 16, 183),
    "star_wars_2025_pro": ("star_wars_2025_pro_0_84_spike3", 0x754a50, 16, 126),
    "pokemon_le": ("pokemon_le_0_82_spike3", 0x3198290, 24, 10),
}
NO_TABLE = {"fallout_le": "fallout_le_0_82_spike3", "transformers_mtmte_le": "transformers_mtmte_le_0_96_spike3"}


def _prog(game):
    path = os.path.join(PROGS, game + ".game")
    if not PROGS or not os.path.isfile(path):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    return path


@pytest.mark.parametrize("game", sorted(TABLES))
def test_port_carries_the_table(game):
    key, table, size, count = TABLES[game]
    t = AI.port_table(MP.profiles()[key])
    assert t is not None
    assert (t["table"], t["size"], t["page_at"], t["count"]) == (table, size, 8, count)


@pytest.mark.parametrize("game", sorted(NO_TABLE))
def test_director_titles_have_no_table(game):
    prof = MP.profiles()[NO_TABLE[game]]
    assert AI.port_table(prof) is None
    assert "starts its attract screens in a way" in AI.title_refusal(prof)


def test_show_pair_on_the_titles_whose_pages_have_it():
    for game in ("star_wars_elg", "walking_dead_remastered_le", "star_wars_2025_le", "star_wars_2025_pro"):
        port = MP.read_port(MP.port_path(MP.profiles()[TABLES[game][0]]))
        assert "attract_show" in port["site"] and "player_advance" in port["site"], game
        assert AI.port_table(MP.profiles()[TABLES[game][0]])["show"]


def test_spike3_items_are_gated_until_a_route_is_proven():
    prof = MP.profiles()["star_wars_elg_1_10_spike3"]
    assert prof.arch == "a64"
    assert AI.title_refusal(prof) == AI.NO_GLASS % prof.label
    # the 24-byte table is not what refuses Pokemon: it has no clip route
    pk = MP.profiles()["pokemon_le_0_82_spike3"]
    assert AI.title_refusal(pk) == AI.NO_CLIPS % pk.label


def test_spike3_modes_leaves_them_out_quietly(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import spike3_modes as S3M, clip_variants as CV
    from pinball_decryptor.plugins.stern import mode_write as MW
    png = tmp_path / "p.png"
    png.write_bytes(b"x")
    AI.save(str(tmp_path), AI.clean({"items": [{"kind": "photo", "file": str(png), "seconds": 5, "entry": 10}]}))
    monkeypatch.setattr(CV, "project_title", lambda p, probe=False: MP.profiles()["star_wars_elg_1_10_spike3"])
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    assert S3M.attract_wanted(str(tmp_path), real_card=False) is None
    assert "attract items" not in S3M.FAMILY_LEFT_OUT          # the engine's own sentence says why


def test_runtime_reads_the_table_pointer_sized():
    src = open(RUNTIME, encoding="utf-8").read()
    body = src[src.index("static void attract_arm(void)"):src.index("/* ---- round 2: the game's own start menu")]
    assert "pm_addr *slot, page;" in body and "*(volatile pm_addr *)slot" in body
    assert "size != 24" in body and "at + sizeof(pm_addr) > size" in body
    assert re.search(r"#if PM_A64\s+/\* PAD-1328", body)
    assert "typedef pm_reg (*ait_page_fn)(pm_reg, pm_reg, pm_reg, pm_reg);" in src


@pytest.mark.parametrize("game", sorted(TABLES) + sorted(NO_TABLE))
def test_finder_on_the_real_programs(game):
    import s3port as S
    t = S.Elf(_prog(game))
    S.scan(t)
    port = MP.read_port(MP.port_path(MP.profiles()[(TABLES.get(game) or (NO_TABLE[game],))[0]]))
    sleep = port["site"]["proc_sleep"]
    sleep = sleep[0] if isinstance(sleep, (tuple, list)) else sleep
    s = S.attract_sequencer(t, sleep)
    if game in NO_TABLE:
        assert s is None
        return
    _key, table, size, count = TABLES[game]
    assert (s["entry"], s["size"], s["page_at"], s["count"]) == (table, size, 8, count)
    assert s["stamp"] in (0x108, 0x110)
    lines = S.attract_lines(t, {"proc_sleep": sleep})
    assert "data  attract_table       0x%08x" % table in "\n".join(lines)


def test_pages_of_the_real_elg_program():
    prof = MP.profiles()["star_wars_elg_1_10_spike3"]
    with open(_prog("star_wars_elg"), "rb") as f:
        pages = AI.read_pages(f.read(), prof)
    assert len(pages) == 28
    names = [p.name for p in pages]
    assert names[1] == "Credits" and names[10] == "Star Wars Logo"
    assert names[2] == "Net How To Connect Overlay"
    assert sum(n == "High score / champion page" for n in names) == 12
    assert pages[0].page == 0x139a50 and pages[0].sometimes and not pages[1].sometimes


# ---- inactivity pausing the timers: no Spike 3 game needs it ---------------------------------------------------
IDLE_READS = {"fallout_le": (176, 0x4873e4), "star_wars_2025_le": (182, 0x280a18), "transformers_mtmte_le": (174, 0x28323c)}


def test_idle_pause_is_offered_on_no_spike3_title():
    from pinball_decryptor.plugins.stern import idle_pause as IP
    for key, prof in MP.profiles().items():
        if key.endswith("_spike3"):
            why = IP.title_refusal(prof)
            if prof.game_dir in IP.NO_SETTING_TITLES:
                assert why == IP.NO_SETTING % prof.label
            else:
                assert why == IP.NO_NEED % prof.label


@pytest.mark.parametrize("game", sorted(set(TABLES) | set(NO_TABLE)))
def test_each_spike3_title_honours_or_lacks_the_setting(game):
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    from pinball_decryptor.plugins.stern import idle_pause as IP
    with open(_prog(game), "rb") as f:
        raw = f.read()
    t = AdjustmentTable(raw, wide_ok=True)
    ids = [i for i, n in enumerate(t.names) if n == "AD_INACTIVE_TIMER"]
    if game in IP.NO_SETTING_TITLES:
        assert ids == []
        return
    aid, at = IDLE_READS[game]
    assert ids == [aid]
    import s3port as S
    e = S.Elf(_prog(game))
    port = MP.read_port(MP.port_path(MP.profiles()[(TABLES.get(game) or (NO_TABLE[game],))[0]]))
    adj = port["site"]["adjustment"]
    adj = adj[0] if isinstance(adj, (tuple, list)) else adj
    reads = [e.tva + 4 * i for i, w in enumerate(e.words) if w == 0x52800000 | aid << 5
             and S._bl(e.tva + 4 * i + 4, e.words[i + 1]) == adj]
    assert reads == [at]
    assert e.u32(at + 8) == 0x7100041F                         # cmp w0, #1: the game's own should-pause test
