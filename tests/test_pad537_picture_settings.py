"""PAD-537 (an owner's request): BRIGHTNESS, CONTRAST and SATURATION in the game's own service menu,
applied live, with a test card on the game's screen.

menu_settings gives the three rows spare (DEPRECATED) settings the card's MUSIC MODE and EDITION
leave; picture_settings writes ``picture.cfg`` for the mode runtime, which re-points four GL
imports of the game program and passes every fragment shader's colour through the settings. The
emulator showed it on a Write-built Godzilla Premium/LE 1.16 card (the rows on LCD/Lamp, a value
accepted changing the whole screen at once, the test card for 15 s, the values kept over a
reboot); these tests pin the parts on the real Godzilla 1.16 programs where the cards are on this
machine (skipped elsewhere, as on CI) and everything that needs no card everywhere."""

import os
import re

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern import picture_settings as PS
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable, menu_label

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RUNTIME = os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")
COLOUR_C = os.path.join(REPO, "tools", "spike2_emu", "codeselect", "colour.c")
CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")
PRO116 = os.path.join(CARDS, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---- what the values mean -----------------------------------------------------------------------
def test_five_changes_nothing_and_the_ends_are_what_the_help_says():
    for key in PS.KEYS:
        assert len(PS.FACTORS[key]) == PS.VALUES == 9
        assert PS.FACTORS[key][PS.NORMAL - 1] == 1000
        assert list(PS.FACTORS[key]) == sorted(PS.FACTORS[key])
        assert "5 is normal" in PS.HELP[key]
        # the game's spare help strings hold 63 characters (Godzilla 1.16's shortest)
        assert len(PS.HELP[key]) <= 63
    assert PS.FACTORS[MS.SATURATION][0] == 0                    # 1 = black and white
    assert "black and white" in PS.HELP[MS.SATURATION]


def test_the_rows_sit_beside_the_game_s_lcd_brightness():
    for key in PS.KEYS:
        fixed, caption, row, category = MS.SETTINGS[key]
        assert fixed is None and category == 11 and caption == key.upper() and row == key.title()


def test_picture_cfg_names_the_slots_the_settings_and_the_card():
    slots = {s: 0x709000 + 4 * k for k, s in enumerate(PS.SYMBOLS)}
    rows = [MS.MenuSetting(MS.BRIGHTNESS, 35, "Brightness", "h", 9, 0x7a4e58, 11, 5),
            MS.MenuSetting(MS.MUSIC_MODE, 31, "Music Mode", "h", 2, 0x7a4e78, 13, 1)]
    text = PS.cfg_text(slots, rows, only=True)
    lines = text.splitlines()
    assert lines[1] == "only"
    assert "got\tglShaderSource\t0x00709000" in lines
    assert "got\teglSwapBuffers\t0x0070900c" in lines
    assert "setting\tbrightness\t0x007a4e58\t600\t700\t800\t900\t1000\t1100\t1200\t1300\t1400" in lines
    assert not any("music_mode" in ln for ln in lines)          # not a picture row
    assert lines[-1] == "card\t860\t6\t480\t300\t15000"
    assert "only" not in PS.cfg_text(slots, rows, only=False).splitlines()


def test_a_program_the_runtime_cannot_re_point_is_refused():
    with pytest.raises(PS.PictureError):
        PS.import_slots(b"not a program")
    with pytest.raises(PS.PictureError):
        PS.import_slots(b"\x7fELF\x02\x01" + bytes(64))          # 64-bit


# ---- the runtime agrees with the app --------------------------------------------------------------
def test_the_runtime_reads_the_file_and_re_points_the_four_imports():
    src = _read(RUNTIME)
    m = re.search(r'PIC_SYMS\[PIC_GOTS\]\s*=\s*\{([^}]*)\}', src)
    assert m and re.findall(r'"(\w+)"', m.group(1)) == list(PS.SYMBOLS)
    m = re.search(r'PIC_FILES\[\]\s*=\s*\{([^}]*)\}', src)
    assert m and "/usr/local/padmode/%s" % PS.CFG_NAME in m.group(1)
    m = re.search(r'PIC_NAMES\[PIC_N\]\s*=\s*\{([^}]*)\}', src)
    assert m and re.findall(r'"(\w+)"', m.group(1)) == list(PS.KEYS)
    assert "pic_arm();" in src


def _triples(text):
    return [tuple(int(float(v)) for v in t) for t in re.findall(r"vec3\(([\d.]+),([\d.]+),([\d.]+)\)", text)]


def test_the_game_s_test_card_is_the_boot_menu_s():
    """The test card the shaders draw is the multi-boot menu's (codeselect colour.c), which is
    the Color profile tab's: the same dark sea tones and skin tones."""
    src = _read(RUNTIME)
    glsl = src[src.index("static const char PIC_GLSL[]"):src.index("static void pic_line")]
    colour = _read(COLOUR_C)
    for name in ("sea", "skin"):
        m = re.search(r"%s\[6\]\[3\]\s*=\s*\{(.*?)\};" % name, colour, re.S)
        want = [tuple(int(v) for v in t) for t in re.findall(r"\{(\d+),\s*(\d+),\s*(\d+)\}", m.group(1))]
        assert len(want) == 6
        got = _triples(glsl)
        assert all(t in got for t in want), name
    m = re.search(r"greys\[16\]\s*=\s*\{([^}]*)\}", colour)
    assert [int(v) for v in m.group(1).split(",")] == [
        0, 8, 16, 24, 32, 48, 64, 80, 96, 112, 128, 160, 192, 224, 240, 255]
    assert "g=8.0*i" in glsl and "g=32.0+16.0*(i-4.0)" in glsl


def test_the_card_install_and_the_emulator_carry_picture_cfg():
    install = _read(os.path.join(REPO, "tools", "spike2_emu", "mode_install.py"))
    assert '("picture.cfg", 0o100644)' in install
    assert re.search(r'STANDALONE_FILES = \([^)]*"picture\.cfg"', install)
    for rel in ("cardmodes.sh", "tryit.sh"):
        assert '"$DUMP/picture.cfg"' in _read(os.path.join(REPO, "tools", "spike2_emu", "modes", rel)) \
            or '"$DUMP"/picture.cfg' in _read(os.path.join(REPO, "tools", "spike2_emu", "modes", rel))


# ---- the real game programs (David's machine) ---------------------------------------------------
def _program(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        return img.preview(part, "/%s/game" % game, cap=256 << 20)


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_godzilla_116_imports_the_four_through_its_own_table(card):
    slots = PS.import_slots(_program(card))
    assert set(slots) == set(PS.SYMBOLS)
    if card == LE116:      # the slots the emulator runs re-pointed
        assert slots == {"glUseProgram": 0x709230, "eglSwapBuffers": 0x709564,
                         "glShaderSource": 0x70972c, "glLinkProgram": 0x709900}
    else:
        assert slots == {"glUseProgram": 0x6fe218, "eglSwapBuffers": 0x6fe548,
                         "glShaderSource": 0x6fe710, "glLinkProgram": 0x6fe8e4}


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_the_three_take_the_spare_settings_the_others_leave(card):
    t = AdjustmentTable(_program(card))
    alone, _w, cat, refused = MS.plan_many(t, PS.wanted())
    assert not refused and cat is not None
    assert [(s.key, s.id, s.default, s.values) for s in alone] == [
        (MS.BRIGHTNESS, 35, 5, 9), (MS.CONTRAST, 33, 5, 9), (MS.SATURATION, 31, 5, 9)]
    assert [s.help for s in alone] == [PS.HELP[k] for k in PS.KEYS]
    music = (MS.MUSIC_MODE, 2, ["Standard", "Orchestral"])
    edition = (MS.EDITION, 2, ["Standard", "70th"])
    one, _w, _c, refused = MS.plan_many(t, [music] + PS.wanted())
    assert [(s.key, s.id) for s in one] == [(MS.MUSIC_MODE, 31), (MS.BRIGHTNESS, 35), (MS.CONTRAST, 33)]
    assert list(refused) == [MS.SATURATION] and "no spare setting" in refused[MS.SATURATION]
    both, _w, _c, refused = MS.plan_many(t, [music, edition] + PS.wanted())
    assert [(s.key, s.id) for s in both] == [(MS.MUSIC_MODE, 31), (MS.EDITION, 33), (MS.BRIGHTNESS, 35)]
    assert set(refused) == {MS.CONTRAST, MS.SATURATION}


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_the_rows_read_back_from_the_built_program_and_build_again(card, tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    raw = _program(card)
    t = AdjustmentTable(raw)
    settings, writes, cat, refused = MS.plan_many(t, PS.wanted())
    reloc, why = E._text_reloc_plan(raw)
    assert reloc, why
    va = reloc["base_va"] + reloc["used"]
    fw = list(writes.items()) + list(MS.table_writes(t, cat, va, *settings).items())
    grown = E._grow_program_text(raw, fw, MS.table_blob(cat, *settings), reloc, None, str(tmp_path), None,
                                 lambda *a, **k: None)
    with open(grown["path"], "rb") as f:
        built = f.read()
    for s in settings:
        assert MS.check(built, s) == []
        assert menu_label(AdjustmentTable(built), s.id) == s.key.upper()
    # the program's import table did not move with the growth
    assert PS.import_slots(built) == PS.import_slots(raw)
    # built again on top (Emulate's edits on a PAD card): the same rows, nothing new to list
    again, _w, cat2, refused = MS.plan_many(AdjustmentTable(built), PS.wanted())
    assert not refused and cat2 is None
    assert [(s.key, s.id) for s in again] == [(s.key, s.id) for s in settings]


# ---- the Write tab and the build's gate -----------------------------------------------------------
def test_the_write_tab_tick_asks_for_the_rows_and_says_how_many_fit(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import write as W
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.plugins.stern import editions as Ed

    class Mfr:
        key = "stern"
        current_era = "spike2"

    class Win:
        _running = False
        cb = {}

    monkeypatch.setattr(W.WriteTab, "mfr", property(lambda self: Mfr()))
    svc = W.WriteTab.__new__(W.WriteTab)
    svc.window = Win()
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "cap", lambda n: True, raising=False)
    monkeypatch.setattr(svc, "_is_direct", lambda: False, raising=False)
    monkeypatch.setattr(svc, "_info_assets_dir", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "log", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(PS, "OFFERED", True)          # PAD-575: switched off for now; as it was
    monkeypatch.setattr(PS, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(PS, "title_refusal", lambda prof: "")
    staged_changes.save(str(tmp_path), {"audio": {"x": "y"}})
    assert svc.set_picture(True) is True
    data = staged_changes.load(str(tmp_path))
    assert data[PS.STAGED_KEY] == {"on": True} and data["audio"] == {"x": "y"}
    assert state["picture_cap"] is True and state["picture_on"] is True
    assert state["picture_note"] == ("The card gets Brightness, Contrast and Saturation in "
                                     "Adjustments > Machine Settings > LCD/Lamp.")
    # an edition takes a spare setting: Saturation no longer fits
    data[Ed.STAGED_KEY] = {"names": ["Standard", "70th"]}
    staged_changes.save(str(tmp_path), data)
    svc._publish_picture()
    assert state["picture_note"].startswith("The card gets Brightness and Contrast in ")
    assert "Saturation is left out" in state["picture_note"]
    assert svc.set_picture(False) is True
    assert PS.STAGED_KEY not in staged_changes.load(str(tmp_path))
    assert state["picture_on"] is False and state["picture_note"] == ""


def test_a_title_never_tried_is_refused_and_says_so(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine as E
    monkeypatch.setattr(PS, "OFFERED", True)          # PAD-575: switched off for now; as it was
    PS.save(str(tmp_path), True)
    said = []
    assert E._picture_for_build(str(tmp_path), True, lambda m, *a: said.append(m)) is None
    assert "direct-SD write" in said[-1]

    class Prof:
        label = "Jaws Pro 1.01"
        game_dir = "jaws_pro"
        version = "1.01"
    assert "have not been tried on Jaws Pro" in PS.title_refusal(Prof())
    assert PS.title_refusal(None) == PS.NO_TITLE
