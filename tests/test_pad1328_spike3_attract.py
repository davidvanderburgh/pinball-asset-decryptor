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


def test_spike3_items_go_on_where_the_bank_scene_can_be_shown():
    # PAD-1371: Star Wars ELG 1.10's items are on the glass (its page shows the bank's scene, as the game's own clip
    # pages do); the titles whose ports carry no clip route yet are refused for that, not for the glass
    prof = MP.profiles()["star_wars_elg_1_10_spike3"]
    assert prof.arch == "a64"
    assert AI.title_refusal(prof) == ""
    for key in ("walking_dead_remastered_le_0_92_spike3", "star_wars_2025_le_0_96_spike3",
                "star_wars_2025_pro_0_84_spike3", "pokemon_le_0_82_spike3"):
        other = MP.profiles()[key]
        assert AI.title_refusal(other) == AI.NO_CLIPS % other.label, key


def test_spike3_modes_carries_them_on_elg(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import spike3_modes as S3M, clip_variants as CV
    from pinball_decryptor.plugins.stern import mode_write as MW
    png = tmp_path / "p.png"
    png.write_bytes(b"x")
    AI.save(str(tmp_path), AI.clean({"items": [{"kind": "photo", "file": str(png), "seconds": 5, "entry": 10}]}))
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    elg = MP.profiles()["star_wars_elg_1_10_spike3"]
    monkeypatch.setattr(CV, "project_title", lambda p, probe=False: elg)
    assert S3M.attract_wanted(str(tmp_path), real_card=False) is elg
    wdr = MP.profiles()["walking_dead_remastered_le_0_92_spike3"]
    monkeypatch.setattr(CV, "project_title", lambda p, probe=False: wdr)
    assert S3M.attract_wanted(str(tmp_path), real_card=False) is None
    assert "attract items" not in S3M.FAMILY_LEFT_OUT          # the engine's own sentence says why


def test_runtime_reads_the_table_pointer_sized():
    src = open(RUNTIME, encoding="utf-8").read()
    body = src[src.index("static void attract_arm(void)"):src.index("/* ---- round 2: the game's own start menu")]
    assert "pm_addr *slot, page;" in body and "*(volatile pm_addr *)slot" in body
    assert "size != 24" in body and "at + sizeof(pm_addr) > size" in body
    # PAD-1371: off on Spike 3 only without a way to show the bank's scene from a page
    assert re.search(r"#if PM_A64\s+/\* PAD-1328 / PAD-1371", body)
    assert "if (!ait_video && !ait_show) {" in body
    assert "cannot show an item yet" not in src


def test_runtime_keeps_game_addresses_whole():
    # PAD-1371: the scene show's address in a 32-bit `unsigned` sent a Spike 3 item's page to 0x00000000eac5baa0
    # (Star Wars ELG's 0x7bb2eac5baa0 cut short); no site or global a Spike 3 port carries is held in an `unsigned`
    import glob
    src = open(RUNTIME, encoding="utf-8").read()
    assert "static pm_addr ait_show_fn;" in src
    names = set()
    for path in glob.glob(os.path.join(os.path.dirname(RUNTIME), "ports", "spike3", "*.port")):
        for line in open(path, encoding="utf-8"):
            f = line.split()
            if len(f) >= 2 and f[0] in ("site", "data"):
                names.add(f[1])
    held = re.findall(r"\bunsigned\s+(?:\w+\s*=\s*[^;]*?,\s*)?\w+\s*=\s*(?:fn|data)\(\"(\w+)\"\)\s*[,;]", src)
    assert held and not sorted(set(held) & names)


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


# ---- expression light shows: the Spike 3 cabinet's lights -------------------------------------------------------
CAB_COUNTS = {"fallout_le_0_82_spike3": 184, "pokemon_le_0_82_spike3": 184,
              "walking_dead_remastered_le_0_92_spike3": 184, "transformers_mtmte_le_0_96_spike3": 184,
              "star_wars_2025_le_0_96_spike3": 136, "star_wars_2025_pro_0_84_spike3": 136,
              "star_wars_elg_1_10_spike3": 0}


def test_spike3_cabinet_names():
    from pinball_decryptor.plugins.stern import lampmap as LM
    assert LM.cabinet_role("EXPRESSION LIGHTING L 3") == ("blade", "L", 3)
    assert LM.cabinet_role("CABINET R-IN LOWER 60") == ("blade", "R", 60)
    assert LM.cabinet_role("CABINET L-OUT 97") == ("blade", "L", 97)
    assert LM.cabinet_role("SPEAKER R 20") == ("speaker", "R", 20)
    assert LM.cabinet_strip("CABINET L-IN UPPER 1") == "IN" and LM.cabinet_strip("CABINET R-OUT 121") == "OUT"
    assert LM.cabinet_strip("EXPRESSIVE LIGHTING L 3") == ""
    for name in ("CABINET L-IN", "SPEAKER L", "ETOPPER L DOME LED", "BACKBOX GI", "SPEAKER L 1-R"):
        assert LM.cabinet_role(name) is None, name


def _cablamps(key):
    import re as _re
    out = []
    with open(MP.port_path(MP.profiles()[key]), encoding="utf-8") as f:
        for line in f:
            m = _re.match(r"cablamp (\S+)\s+(\d+)\s+(.*?)\s+# .*at (\d+),(\d+)", line)
            if m:
                out.append(([int(x) for x in m.group(1).split(",")], int(m.group(2)), m.group(3),
                            int(m.group(4)), int(m.group(5))))
    return out


@pytest.mark.parametrize("key", sorted(CAB_COUNTS))
def test_ports_carry_the_cabinet(key):
    cab = _cablamps(key)
    assert len(cab) == CAB_COUNTS[key]
    if not cab:
        return
    assert all(len(ids) == 3 and len(set(ids)) == 3 for ids, _u, _n, _x, _y in cab)
    by = {n: (u, x, y) for _ids, u, n, x, y in cab}
    assert sum(1 for n in by if n.startswith("SPEAKER L ")) == 20 and sum(1 for n in by if n.startswith("SPEAKER R ")) == 20
    assert all(y < 140 for n, (u, x, y) in by.items() if n.startswith("SPEAKER"))          # the runtime's speaker lane
    assert all(y >= 140 for n, (u, x, y) in by.items() if not n.startswith("SPEAKER"))
    from pinball_decryptor.plugins.stern import lampmap as LM
    assert all((x < 150) == (LM.cabinet_role(n)[1] == "L") for n, (u, x, y) in by.items())   # the runtime's side
    if "CABINET L-IN UPPER 1" in by:
        # a Spike 3 strip is numbered from the top: its first pixel is the strip's top end
        assert by["CABINET L-IN UPPER 1"][0] > 950 and by["CABINET L-IN LOWER 48"][0] < 50
        assert by["CABINET L-OUT 97"][1] < by["CABINET L-IN UPPER 1"][1] < 150
    else:
        assert by["EXPRESSION LIGHTING L 1"][0] < 50 and by["EXPRESSION LIGHTING R 96"][0] > 950


def test_runtime_has_room_for_a_spike3_cabinet():
    src = open(RUNTIME, encoding="utf-8").read()
    m = re.search(r"#define N_CAB\s+(\d+)", src)
    assert m and int(m.group(1)) >= max(CAB_COUNTS.values())


@pytest.mark.parametrize("game", ["fallout_le", "star_wars_2025_le", "star_wars_elg"])
def test_cabinet_lines_off_the_real_programs(game):
    import s3port as S
    t = S.Elf(_prog(game))
    S.scan(t)
    key = (TABLES.get(game) or (NO_TABLE.get(game),))[0]
    port = MP.read_port(MP.port_path(MP.profiles()[key]))
    lg = port["site"]["lamp_group"]
    lines = S.cabinet_lines_a64(t, {"lamp_group": lg[0] if isinstance(lg, (tuple, list)) else lg})
    drafted = [l for l in lines if l.startswith("cablamp ")]
    shipped = [l.rstrip("\n") for l in open(MP.port_path(MP.profiles()[key]), encoding="utf-8")
               if l.startswith("cablamp ")]
    assert drafted == shipped
    devs = [d for d in S.device_records(t) if d[3] == 3]
    for line in drafted[:10]:
        ids, name = line.split()[1], line.split("  #")[0].split(None, 3)[3]
        # a light id is its lamp's rank in the device table + 1: the three channels of the named pixel
        assert [devs[int(i) - 1][0] for i in ids.split(",")] == [name + "-R", name + "-G", name + "-B"]


def test_spike3_cabinet_shows_are_gated_until_seen_lit():
    from pinball_decryptor.plugins.stern import cab_shows as CS, spike3_modes as S3M
    for key, n in CAB_COUNTS.items():
        prof = MP.profiles()[key]
        assert CS.title_refusal(prof) == (CS.NO_SPIKE3 if n else CS.NO_CAB) % prof.label
    assert "expression light shows" in S3M.FAMILY_LEFT_OUT


def test_lights_tab_says_why_on_a_spike3_card(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import lights as L
    from pinball_decryptor.plugins.stern import cab_shows as CS, clip_variants as CV, title_reader as TR
    card = tmp_path / "fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 1024)
    prof = MP.profiles()["fallout_le_0_82_spike3"]
    monkeypatch.setattr(MP, "project_card", lambda p: type("C", (), {"image": str(card)})())
    monkeypatch.setattr(MP, "card_arch", lambda image: "a64")
    monkeypatch.setattr(CV, "project_title", lambda p, probe=False: prof)
    monkeypatch.setattr(TR, "game_program", lambda c: pytest.fail("a Spike 3 program is not read by the Spike 2 reader"))
    assert L.project_layout(str(tmp_path)) == (CS.NO_SPIKE3 % prof.label, [])
