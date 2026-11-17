"""PAD-1382: more settings of ours than a game has spare rows share two - MORE SETTINGS (which one) and the row under it
(its value) - and the mode runtime keeps every value in a file on the card (pad_mode_runtime.c "more settings").

Godzilla 1.16 has three spare rows; CO-OP PLAY, HANDICAP and the three picture settings are five. Before this, two of
them were refused (co-op left off the card, handicaps forced on). Emulator proof: artifacts/PAD-1382/emulator."""
import os
import re

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable, menu_label

CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")
PRO116 = os.path.join(CARDS, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")


def _wanted(music=False, edition=False):
    from pinball_decryptor.plugins.stern import coop_play as CP, handicap as HC, picture_settings as PS
    rows = [("music_mode", 3, ["Standard", "Orchestral", "Heisei"])] if music else []
    rows += [("edition", 2, ["One", "Two"])] if edition else []
    rows += [(k, PS.VALUES, (), {"default": PS.NORMAL, "help_text": PS.HELP[k]}) for k in PS.KEYS]
    rows += [("coop_play", CP.MENU_VALUES, (), {"default": 1, "help_text": CP.MENU_HELP, "from_zero": True}),
             ("handicap", HC.MENU_VALUES, (), {"default": 1, "help_text": HC.MENU_HELP, "onoff": True})]
    return rows


def _program(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        return img.preview(part, "/%s/game" % game, cap=256 << 20)


# ---- on the real programs -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_settings_that_fit_keep_rows_of_their_own(card):
    t = AdjustmentTable(_program(card))
    rows = [r for r in _wanted(music=True) if r[0] in ("music_mode", "coop_play", "handicap")]
    settings, _w, _c, refused = MS.plan_many(t, rows)
    assert refused == {}
    assert [s.key for s in settings] == ["music_mode", "coop_play", "handicap"]
    assert not any(s.shared for s in settings)
    assert MS.shared_cfg_text(settings) == ""


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_five_settings_on_three_spare_rows_share_two(card):
    t = AdjustmentTable(_program(card))
    settings, writes, cat, refused = MS.plan_many(t, _wanted())
    assert refused == {}
    by = {s.key: s for s in settings}
    pick, value = by[MS.MORE_SELECT], by[MS.MORE_VALUE]
    assert pick.id != value.id and {pick.id, value.id} <= {31, 33, 35}
    assert pick.values == 5 and pick.category == value.category == MS.OWN_CATEGORY    # round 5: Custom Code
    keys = ["brightness", "contrast", "saturation", "coop_play", "handicap"]
    for k, key in enumerate(keys, 1):
        s = by[key]
        assert s.live == MS.SHARED_BASE + 4 * k and s.shared == (k,) and MS.is_shared(s)
        assert s.id == value.id and s.where.endswith("MORE SETTINGS %d" % k)
    assert (by["coop_play"].low, by["coop_play"].values) == (0, 3)
    assert by["handicap"].kind == MS.onoff_kind(t) and by["brightness"].kind == MS.number_kind(t)
    # the runtime may write each one's words in the room the program has
    desc, help_va, help_room, row_va, row_room = value.shared[:5]
    assert all(len(by[k].help) <= help_room and len(by[k].caption) <= row_room for k in keys)
    assert desc == t.table_va + value.id * t.elem
    assert "1 Brightne" in pick.help or "1 = Brightness" in pick.help
    assert cat is not None and writes
    assert MS.plan_many(t, _wanted(), share=False)[3]          # without sharing, two are refused as before


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_edition_keeps_a_row_of_its_own(card):
    """EDITION is read off the board's store before the game runs (codeselect), so it never shares."""
    t = AdjustmentTable(_program(card))
    settings, _w, _c, refused = MS.plan_many(t, _wanted(music=True, edition=True))
    assert refused == {}
    by = {s.key: s for s in settings}
    assert not by["edition"].shared and by["edition"].id == t.by_name["AD_LED_MAX_BRIGHTNESS"]
    assert {by[MS.MORE_SELECT].id, by[MS.MORE_VALUE].id} == {31, 35}
    assert [s.key for s in settings if MS.is_shared(s)] == ["music_mode", "brightness", "contrast", "saturation",
                                                            "coop_play", "handicap"]


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_the_shared_rows_read_back_from_the_built_program(card, tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    raw = _program(card)
    t = AdjustmentTable(raw)
    settings, writes, cat, _r = MS.plan_many(t, _wanted())
    reloc, why = E._text_reloc_plan(raw)
    assert reloc, why
    va = reloc["base_va"] + reloc["used"]
    fw = list(writes.items()) + list(MS.table_writes(t, cat, va, *settings).items())
    grown = E._grow_program_text(raw, fw, MS.table_blob(cat, *settings), reloc, None, str(tmp_path), None,
                                 lambda *a, **k: None)
    with open(grown["path"], "rb") as f:
        new = f.read()
    by = {s.key: s for s in settings}
    for key in (MS.MORE_SELECT, MS.MORE_VALUE):
        assert MS.check(new, by[key]) == [], key
    nt = AdjustmentTable(new)
    assert menu_label(nt, by[MS.MORE_SELECT].id) == "MORE SETTINGS"
    assert menu_label(nt, by[MS.MORE_VALUE].id) == "SETTING VALUE"
    # a second Write of the same card takes the same rows again (its captions are ours)
    again, _w, _c, refused = MS.plan_many(nt, _wanted())
    assert refused == {} and {s.key: s.id for s in again} == {s.key: s.id for s in settings}


# ---- the runtime's table --------------------------------------------------------------------------------------------
def _setting(key, live, values=3, low=1, default=1, kind=2, shared=(), help="h", caption="C", ident=33):
    return MS.MenuSetting(key, ident, caption, help, values, live, 16, default, "Adjustments > Attract Mode", low, kind,
                          shared)


def test_settings_cfg_names_both_rows_and_every_shared_setting():
    pick = _setting(MS.MORE_SELECT, 0x7a4e58, values=2, ident=35)
    value = _setting(MS.MORE_VALUE, 0x7a4e68, shared=(0x71c8a0, 0x5e6924, 67, 0x5ede58, 27, 4, 8, 12, 36))
    a = _setting("coop_play", MS.SHARED_BASE + 4, values=3, low=0, default=0, shared=(1,), caption="Co-op Play",
                 help="0 Off.\t1 Classic.")
    b = _setting("handicap", MS.SHARED_BASE + 8, values=2, low=0, default=0, kind=1, shared=(2,), caption="Handicap",
                 help="On: picks")
    text = MS.shared_cfg_text([pick, value, b, a])
    assert text.splitlines()[1:] == [
        "select\t0x007a4e58\t2",
        "value\t0x007a4e68\t0x0071c8a0\t0x005e6924\t67\t0x005ede58\t27",
        "fields\t4\t8\t12\t36",
        "option\t1\tcoop_play\t0\t2\t0\t2\tCo-op Play\t0 Off. 1 Classic.",
        "option\t2\thandicap\t0\t1\t0\t1\tHandicap\tOn: picks",
    ]
    assert MS.shared_cfg_text([a, b]) == ""


def test_the_runtime_reads_shared_values_where_the_app_puts_them():
    src = open(RUNTIME, encoding="utf-8").read()
    assert int(re.search(r"#define MSET_BASE\s+(0x[0-9a-f]+)u", src).group(1), 16) == MS.SHARED_BASE
    assert re.search(r"#define MSET_N\s+(\d+)", src).group(1) == str(MS.MAX_VALUES)
    assert '"/usr/local/padmode/%s", "/dump/%s"' % (MS.SHARED_CFG, MS.SHARED_CFG) in src
    # every setting's reader takes its address through setting_addr (a row's, or a shared word)
    for reader in ("coop.setting = setting_addr(", "hand.setting = setting_addr(", "sndm_live = setting_addr(",
                   "pic_set[w].live = (unsigned)setting_addr(", "return only && v ? setting_addr(v)"):
        assert reader in src, reader
    # the rows are watched before the card's "only" gate, so a card of settings alone has them too
    assert src.index("mset_arm();") < src.index("clipv_arm();")


def test_the_shared_rows_table_rides_with_the_runtime():
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tools", "spike2_emu"))
    import mode_install
    assert ("settings.cfg", 0o100644) in mode_install.EXTRA_FILES
    assert "settings.cfg" not in mode_install.STANDALONE_FILES     # always with a setting's own cfg
    tryit = open(os.path.join(ROOT, "tools", "spike2_emu", "modes", "tryit.sh"), encoding="utf-8").read()
    assert 'put "$S/settings.cfg" "$DUMP/settings.cfg"' in tryit
    assert tryit.count('"$DUMP"/settings.cfg') == 2                # cleared before an install and by a removal


def test_p2_payload_carries_settings_cfg(tmp_path):
    from pinball_decryptor.plugins.stern import mode_write as MW
    cfg = tmp_path / "settings.cfg"
    cfg.write_text("select\t0x1\t2\n")
    assert "settings_file" in MW.ModePlan.__dataclass_fields__
    src = open(MW.__file__, encoding="utf-8").read()
    assert 'getattr(result, "settings_file", "")' in src and "MSet.SHARED_CFG" in src


def test_music_modes_cfg_is_pointed_at_the_value_the_menu_gave(tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    p = tmp_path / "sounds.cfg"
    p.write_text("# x\nonly\nsetting\t0x007a4e60\t3\nsound\t2\t5\tab\n", encoding="utf-8")
    E._point_sounds_cfg(str(p), MS.SHARED_BASE + 4)
    assert p.read_text(encoding="utf-8").splitlines() == ["# x", "only", "setting\t0xfade0004\t3", "sound\t2\t5\tab"]
