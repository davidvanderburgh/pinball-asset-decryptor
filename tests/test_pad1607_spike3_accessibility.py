"""PAD-1607: the accessibility options (PAD-1589: color-blind insert colors, spoken scores) on Spike 3 cards.

The 64-bit runtime carries PAD-1589's code. A Spike 3 title takes the color-blind colors when its port names its
inserts (``lamp`` lines, read off the 64-bit program's own light, lamp and device tables by s3port.py
``inserts_a64``) and the spoken scores when a carrier is measured for it (a request the game never plays). The
Spike 3 Write carries ``access.cfg`` and the words (records appended to image.bin, ``sword`` lines in sounds.cfg),
and spike3_menu puts COLOR BLIND and SPOKEN SCORES in the game's own operator menu. The library tests skip when the
Spike 3 cards are not on this machine.
"""
import os
import re
import struct
import sys

import pytest

from pinball_decryptor.plugins.stern import accessibility as AC
from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = os.path.join(os.path.dirname(__file__), "..")
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
PORTS3 = os.path.join(SDK, "ports", "spike3")
LIBRARY = r"D:\Pinball\images\Stern\spike3"
ELG_CARD = "star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw"
TF_CARD = "transformers_mtmte_le-0_96_0_spike3.Release.64G.sdcard-secure.raw"
_PROGRAMS = {}


def _spike3_profiles():
    return {k: p for k, p in MP.profiles().items() if getattr(p, "arch", "arm") == "a64"}


def _program(card):
    path = os.path.join(LIBRARY, card)
    if not os.path.isfile(path):
        pytest.skip("no Spike 3 library card %s" % card)
    if card not in _PROGRAMS:
        from pinball_decryptor.plugins.stern import title_reader as TR
        _g, _v, elf = TR.game_program(path)
        _PROGRAMS[card] = elf if isinstance(elf, (bytes, bytearray)) else open(elf, "rb").read()
    return _PROGRAMS[card]


# ---- which Spike 3 titles take them --------------------------------------------------------------------------------
def test_every_spike3_title_with_rgb_inserts_takes_the_colour_blind_colours():
    profs = _spike3_profiles()
    assert len(profs) >= 9
    for key, prof in profs.items():
        if key.startswith("star_wars_elg"):         # one-color inserts only: nothing to change
            assert AC.title_refusal(prof, "cvd") == AC.NO_RGB % prof.label
        else:
            assert AC.title_refusal(prof, "cvd") == "", key


def test_a_title_of_one_color_inserts_refuses_them_on_spike2_too():
    profs = MP.profiles()
    for key in ("star_wars_elg_1_10", "james_bond_60th_le_1_11", "jurassic_park_the_pin_1_05"):
        assert AC.title_refusal(profs[key], "cvd") == AC.NO_RGB % profs[key].label, key
    assert AC.title_refusal(profs["godzilla_le_1_16"], "cvd") == ""
    assert AC.title_refusal(profs["jurassic_park_le_1_16"], "cvd") == ""


def test_spoken_scores_go_on_the_spike3_titles_with_a_carrier():
    for key, prof in _spike3_profiles().items():
        why = AC.title_refusal(prof, "spoken")
        if AC.carrier_calls(prof):
            assert why == "", key
        else:
            assert why == AC.NO_CARRIER_A64 % prof.label, key
    elg = _spike3_profiles()["star_wars_elg_1_10_spike3"]
    assert AC.carrier_calls(elg) == (135, 202, 201, 74, 238)
    assert not hasattr(AC, "NO_SPIKE3")


def test_the_spoken_carriers_of_the_census():
    """Every Spike 3 build with a card on the census PC has its carriers: ELG's are the modes' own (TITLES_A64), the
    rest SPEAK_CARRIERS_A64's, kept apart so the modes' own sounds stay off those builds; never the framework's 24."""
    from pinball_decryptor.plugins.stern import mode_sounds as MSo
    profs = _spike3_profiles()
    assert set(AC.SPEAK_CARRIERS_A64) <= set(profs)
    for key, calls in AC.SPEAK_CARRIERS_A64.items():
        assert len(calls) == 5 and len(set(calls)) == 5 and 24 not in calls, key
        assert MSo.profile_carriers(key) is None, key
        assert AC.carrier_calls(profs[key]) == calls
    missing = sorted(k for k, p in profs.items() if not AC.carrier_calls(p))
    assert missing == ["pokemon_le_0_87_spike3"]        # its card is not on the census PC
    assert AC.carrier_calls(MP.profiles()["godzilla_le_1_16"]) == ()


@pytest.mark.parametrize("name", sorted(os.listdir(PORTS3)))
def test_every_spike3_port_names_its_inserts(name):
    port = MP.read_port(os.path.join(PORTS3, name))
    lamps = port.get("lamp") or []                      # [(name, light ids, shot mask)]
    assert len(lamps) >= 60, name
    assert all(d in port["data"] for d in AC.LAMP_DATA)
    if not name.startswith("star_wars_elg"):          # ELG's inserts are one-color; every other title has RGB ones
        assert any(len(ids) == 3 and all(ids) for _n, ids, _m in lamps), name


def test_the_derived_ports_lamp_blocks_say_how_they_were_read():
    for name in sorted(os.listdir(PORTS3)):
        if name.startswith("star_wars_elg"):
            continue                                    # carried by name from its Spike 2 port (PAD-1283)
        txt = open(os.path.join(PORTS3, name), encoding="utf-8").read()
        assert "# ---- lamps (PAD-1607): read off the 64-bit light table" in txt, name


# ---- the 64-bit insert reader -------------------------------------------------------------------------------------
def _s3port():
    sys.path.insert(0, os.path.join(ROOT, "tools", "spike3_emu"))
    import s3port
    return s3port


def _elf(raw, tmp_path):
    S = _s3port()
    p = tmp_path / "game"
    p.write_bytes(raw)
    t = S.Elf(str(p))
    S.scan(t)
    return S, t


def test_the_reader_gives_elgs_proven_lamp_lines(tmp_path):
    """Star Wars ELG 1.10's Spike 3 lamp lines were carried by name from its Spike 2 port and lit on the rig
    (PAD-1283): the reader, from the 64-bit program alone, gives the same light ids for all 66."""
    S, t = _elf(_program(ELG_CARD), tmp_path)
    txt = open(os.path.join(PORTS3, "star_wars_elg-1.10.port"), encoding="utf-8").read()
    g = int(re.search(r"^site\s+lamp_group\s+(0x[0-9a-f]+)", txt, re.M).group(1), 16)
    have = {m.group(2).strip(): m.group(1) for m in re.finditer(r"^lamp\s+(\S+)\s+\S+\s+(.*?)\s+#", txt, re.M)}
    lines = S.lamp_lines_a64(t, {"lamp_group": g})
    got = {m.group(2).strip(): m.group(1) for l in lines for m in [re.match(r"^lamp\s+(\S+)\s+\S+\s+(.*?)\s+#", l)]
           if m}
    assert len(have) == 66 and got == have
    ins, image = S.inserts_a64(t, g)
    ds = next(i for i in ins if i["name"] == "DEATH STAR (X2)")
    assert (ds["x"], ds["y"]) == (49, 60) and image.endswith("Playfield_AK_SW_PIN_DIAG_GRAPHIC_cropped")


def test_the_light_table_is_found_by_its_pointer():
    """light_devices: the table a pointer names, light k's device at +26 of record k, counted from 1"""
    S = _s3port()

    class T:
        pass
    t = T()
    base, n = 0x10000, 5
    b = bytearray(0x20000)
    recs = [("GI", 1, 0, 3), ("SW", 1, 0, 1)] + [("L%d" % k, 6, k, 3) for k in range(n)]
    for k in range(1, n + 1):
        struct.pack_into("<H", b, base + 40 * k + 26, 2 + k)          # light k -> recs[1 + k] (from 1)
    t.b, t.ptr = bytes(b), {0x900: base}
    t.off = lambda va: va if 0 <= va < len(b) - 2 else None
    assert S.light_devices(t, n, recs) == {k: 1 + k for k in range(1, n + 1)}
    struct.pack_into("<H", b, base + 40 * 3 + 26, 2)                  # a switch: no run
    t.b = bytes(b)
    assert S.light_devices(t, n, recs) == {}


# ---- the operator menu ----------------------------------------------------------------------------------------------
def test_colour_blind_and_spoken_scores_rows_grow_into_elgs_program(monkeypatch):
    from pinball_decryptor.plugins.stern import menu_settings as MS, spike3_menu, spike3_modes
    b = _program(ELG_CARD)
    monkeypatch.setattr(spike3_modes, "access_wanted", lambda p, real_card=True: (
        {"cvd": "blue_yellow", "spoken": True}, None))
    rows = spike3_menu.access_rows("x")
    assert [r[0] for r in rows] == [MS.COLOUR_BLIND, MS.SPOKEN_SCORES]
    assert rows[0][1] == AC.CVD_MENU_VALUES and rows[0][3]["default"] == AC.preset_value("blue_yellow") + 1
    assert rows[1][3]["onoff"] and rows[1][3]["help_text"] == AC.SPOKEN_MENU_HELP
    out, settings, refused = spike3_menu.grow(b, rows)
    assert not refused and {s.key for s in settings} == {MS.COLOUR_BLIND, MS.SPOKEN_SCORES}
    assert len({s.live for s in settings}) == 2 and all(MS.check(out, s) == [] for s in settings)


def test_the_rows_ride_rows_wanted_and_the_menu_plan(monkeypatch):
    from pinball_decryptor.plugins.stern import menu_settings as MS, spike3_menu, spike3_modes
    monkeypatch.setattr(spike3_modes, "access_wanted", lambda p, real_card=True: ({"cvd": "", "spoken": True}, None))
    assert [r[0] for r in spike3_menu.access_rows("x")] == [MS.SPOKEN_SCORES]
    assert MS.SPOKEN_SCORES in [r[0] for r in spike3_menu.rows_wanted("x")]
    assert MS.COLOUR_BLIND in spike3_menu._QUIET and MS.SPOKEN_SCORES not in spike3_menu._QUIET
    monkeypatch.setattr(spike3_modes, "access_wanted", lambda p, real_card=True: None)
    assert spike3_menu.access_rows("x") == []


# ---- the words on a carrier ------------------------------------------------------------------------------------------
class _Rec:
    def __init__(self, flags_lo, param, param2=0, channels=1):
        self.flags_lo, self.param, self.param2, self.channels = flags_lo, param, param2, channels


class _Img:
    def __init__(self, records):
        self.records, self.count = records, len(records)


def _words(tmp_path, n=3):
    import wave
    out = []
    for k in range(n):
        p = tmp_path / ("w%d.wav" % k)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(b"\0\0" * 4410 * (k + 1))
        out.append((k, str(p)))
    return out


def test_the_words_ride_a_carrier_the_modes_did_not_take(monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import engine, spike3_modes as S3M, spike3_write as W
    prof = _spike3_profiles()["star_wars_elg_1_10_spike3"]
    img = _Img([_Rec(0x2, 0x100000 * k + 0x10) for k in range(8)] + [_Rec(0x2, 0x8000010)])
    monkeypatch.setattr(engine, "_spoken_wavs", lambda project, log: _words(tmp_path))
    monkeypatch.setattr(S3M, "carrier_view", lambda reader, raw: (
        "/games/star_wars_elg/audio/image.bin", img, lambda r: img.records[5] if r == 202 else None))
    taken = W.NewRecord(_words(tmp_path, 1)[0][1], 1, 0x2, 0x8100010, 77)
    speak, adds = S3M.spoken_words("p", None, b"", prof, taken_requests=[135],
                                   adds={"/games/star_wars_elg/audio/image.bin": [taken]})
    assert speak["request"] == 202 and speak["key"] == struct.pack("<II", 0x2, 0x100000 * 5 + 0x10)
    news = adds["/games/star_wars_elg/audio/image.bin"]
    keys = [nr.key for nr in news]
    assert len(news) == 3 and len(set(keys)) == 3 and taken.key not in keys
    assert all(nr.flags_lo == 0x2 for nr in news) and {(r.flags_lo, r.param) for r in img.records}.isdisjoint(
        (nr.flags_lo, nr.param) for nr in news)
    assert [w[0] for w in speak["words"]] == [0, 1, 2] and [w[1] for w in speak["words"]] == keys
    assert [w[2] for w in speak["words"]] == [100, 200, 300]
    from pinball_decryptor.plugins.stern import sound_modes as SMo
    text = SMo.cfg_text(0, 0, [], True, speak=speak)
    assert text.splitlines()[1] == "only" and text.count("\nsword\t") == 3
    assert "sword\t1\t202\t%s\t%s\t200" % (speak["key"].hex(), keys[1].hex()) in text


def test_no_carrier_left_says_why(monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import engine, spike3_modes as S3M
    prof = _spike3_profiles()["star_wars_elg_1_10_spike3"]
    img = _Img([_Rec(0x2, 0x10)])
    monkeypatch.setattr(engine, "_spoken_wavs", lambda project, log: _words(tmp_path, 1))
    monkeypatch.setattr(S3M, "carrier_view", lambda reader, raw: ("/x/image.bin", img, lambda r: None))
    said = []
    assert S3M.spoken_words("p", None, b"", prof, log=lambda m, k="info": said.append(m)) == (None, {})
    assert said and said[0].startswith("Spoken scores: left out of this build:")


# ---- the plan --------------------------------------------------------------------------------------------------------
def test_access_wanted_follows_the_project_and_the_title(monkeypatch):
    from pinball_decryptor.plugins.stern import handicap as HC, mode_write as MW, spike3_modes as S3M
    profs = _spike3_profiles()
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    monkeypatch.setattr(AC, "load_cvd", lambda p: "red_green")
    monkeypatch.setattr(AC, "load_spoken", lambda p: True)
    monkeypatch.setattr(HC, "project_title", lambda p, probe=False: profs["star_wars_elg_1_10_spike3"])
    assert S3M.access_wanted("p", real_card=False) == ({"cvd": "", "spoken": True},
                                                       profs["star_wars_elg_1_10_spike3"])
    monkeypatch.setattr(HC, "project_title", lambda p, probe=False: profs["pokemon_le_0_87_spike3"])
    assert S3M.access_wanted("p", real_card=False)[0] == {"cvd": "red_green", "spoken": False}
    monkeypatch.setattr(AC, "load_cvd", lambda p: "")
    assert S3M.access_wanted("p", real_card=False) is None


def test_the_spike3_write_passes_the_rows_live_values():
    import inspect
    from pinball_decryptor.plugins.stern import spike3_modes as S3M, spike3_write as W
    assert {"cvd_setting", "spk_setting"} <= set(inspect.signature(S3M.plan).parameters)
    assert {"cvd_setting", "spk_setting"} <= set(inspect.signature(W._plan_modes).parameters)
    src = inspect.getsource(W.write_card)
    assert "menu.live(MS.COLOUR_BLIND)" in src and "menu.live(MS.SPOKEN_SCORES)" in src


def test_a_spike3_plan_carries_access_cfg(monkeypatch, tmp_path):
    """A card of the color-blind colors alone: the plan's payload carries access.cfg (``only``), no sounds.cfg."""
    from pinball_decryptor.plugins.stern import mode_write as MW, spike3_modes as S3M
    prof = _spike3_profiles()["transformers_mtmte_le_0_96_spike3"]
    raw = _program(TF_CARD)

    class Reader:
        pass
    monkeypatch.setattr(S3M, "access_wanted", lambda p, real_card=True: ({"cvd": "red_green", "spoken": False}, prof))
    for name in ("feed_wanted", "variants_wanted", "records_wanted", "cabs_wanted"):
        monkeypatch.setattr(S3M, name, lambda p, real_card=True: ([], None) if name != "feed_wanted" else (0, None))
    for name in ("coop_wanted", "hand_wanted", "comp_wanted", "attract_wanted"):
        monkeypatch.setattr(S3M, name, lambda p, real_card=True: None)
    from pinball_decryptor.plugins.stern import spike3_music as S3MU
    monkeypatch.setattr(S3MU, "wanted", lambda p, real_card=True: (None, None))
    monkeypatch.setattr(S3MU, "left_out_lines", lambda p: [])
    monkeypatch.setattr(MW, "preview_on", lambda: False)
    monkeypatch.setattr(MW, "preview_left_out", lambda p: "")
    monkeypatch.setattr(S3M, "card_state", lambda r: ("stock", "/games/transformers_mtmte_le/game"))
    monkeypatch.setattr(S3M, "game_program", lambda r, t: object())
    Reader.read_file_bytes = lambda self, node: raw
    mplan = S3M.plan(str(tmp_path), Reader(), str(tmp_path / "s"), real_card=False, cvd_setting=0x70b000)
    assert mplan is not None
    files = {name: path for name, path, _mode in mplan.files()}
    assert AC.CFG_NAME in files and "sounds.cfg" not in files
    text = open(files[AC.CFG_NAME], encoding="utf-8").read()
    assert "cvd\t1\t0x70b000" in text and "\nonly\n" in text
    assert any(l.startswith("Color-blind inserts: ") for l in mplan.lines)


# ---- the runtime ----------------------------------------------------------------------------------------------------
def test_the_runtime_ends_an_accessibility_only_ball_on_the_bus():
    """A Spike 3 port ends a ball on a bus event (value ball_end_event + site hook_dispatch, no ball_end site): a card
    of these options only takes that event to their own ball's end."""
    src = open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8").read()
    disp = src[src.index("static void on_event_dispatch(pm_reg *r)"):]
    disp = disp[:disp.index("\n}\n")]
    assert "if (acc_bus_end) on_acc_ball_end(r);" in disp and "else on_ball_end(r);" in disp
    arm = src[src.index("if (acc.on && spk_live) {                 /* PAD-1589"):]
    arm = arm[:arm.index("return;")]
    assert 'pm_port_value("ball_end_event", -1)' in arm and "acc_bus_end = 1;" in arm and "events_arm();" in arm


def test_the_flipper_hold_only_where_the_runtime_sees_the_edges(tmp_path):
    """Pokemon and both Star Wars 2025 ports have no switch_edge: the card says the scores at each ball's end only,
    access.cfg naming no flipper buttons and the Write's line not promising the hold."""
    from pinball_decryptor.plugins.stern import mode_write as MW
    profs = _spike3_profiles()
    no_hold = sorted(k for k, p in profs.items() if not AC.flipper_hold_ok(p))
    assert no_hold == ["pokemon_le_0_82_spike3", "pokemon_le_0_87_spike3", "pokemon_pro_0_87_spike3",
                       "star_wars_2025_le_0_96_spike3", "star_wars_2025_pro_0_84_spike3"]
    assert AC.flipper_hold_ok(MP.profiles()["godzilla_le_1_16"])

    class Plan:
        lines = []
        access_file = ""
    res = Plan()
    res.profile, res.lines = profs["pokemon_pro_0_87_spike3"], []
    MW.access_into(res, b"", str(tmp_path), {"spoken": True, "spoken_setting": 0x10}, only=True)
    text = open(res.access_file, encoding="utf-8").read()
    assert "spoken\t0x10\t0,0" in text
    assert "flipper" not in res.lines[0]
