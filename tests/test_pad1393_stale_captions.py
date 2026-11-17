"""PAD-1393: a card an earlier Write gave rows of ours (MUSIC MODE, EDITION, HANDICAP) had "no spare setting left" for
IMAGE SET once only MUSIC MODE was still wanted: a spare carrying another setting's caption was held back even when that
setting was no longer on the card. Such a row is free unless its setting is wanted by the same Write. And the Service
menu tab's panel shows a box on every row (MUSIC MODE and EDITION ticked when the card gets them, greyed: their own
tabs switch them)."""
import json
import os

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable

from tests.test_pad1382_more_settings import LE116, PRO116, _program

MUSIC = (MS.MUSIC_MODE, 3, ["Standard", "Orchestral", "Stoner"])
IMAGE = (MS.IMAGE_SET, 2, ["Standard", "Kaiju"])
HANDI = (MS.HANDICAP, 2, ["Off", "On"], {"onoff": True})
COOP = (MS.COOP_PLAY, 2, ["Off", "On"], {"onoff": True})


def _written(card, rows):
    """The program as an earlier Write of *rows* left it: its captions on the spare rows."""
    elf = _program(card)
    _s, writes, _c, refused = MS.plan_many(AdjustmentTable(elf), rows)
    assert refused == {}
    b = bytearray(elf)
    for off, data in writes.items():
        b[off:off + len(data)] = data
    return bytes(b)


def _captions(t):
    return {MS.menu_label(t, t.by_name[n]) for n in MS.spare(t)}


@pytest.mark.parametrize("earlier", [HANDI, COOP], ids=["handicap", "coop"])
@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_a_row_of_a_setting_no_longer_wanted_is_free(card, earlier):
    t = AdjustmentTable(_written(card, [MUSIC, (MS.EDITION, 2, ["One", "Two"]), earlier]))
    assert _captions(t) == {"MUSIC MODE", "EDITION", MS.SETTINGS[earlier[0]][1]}  # every spare one carries ours
    settings, _w, _c, refused = MS.plan_many(t, [MUSIC, IMAGE])
    assert refused == {}
    by = {s.key: s for s in settings}
    assert set(by) == {MS.MUSIC_MODE, MS.IMAGE_SET} and not MS.is_shared(by[MS.IMAGE_SET])
    assert by[MS.MUSIC_MODE].id == t.by_name["AD_GI_MAX_BRIGHTNESS"]


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_a_row_of_a_setting_still_wanted_stays_its_own(card):
    t = AdjustmentTable(_written(card, [MUSIC, (MS.EDITION, 2, ["One", "Two"]), HANDI]))
    settings, _w, _c, refused = MS.plan_many(t, [MUSIC, HANDI, IMAGE])
    assert refused == {}
    by = {s.key: s for s in settings}
    handi = next(n for n in MS.spare(t) if MS.menu_label(t, t.by_name[n]) == "HANDICAP")
    assert by[MS.HANDICAP].id == t.by_name[handi]                  # HANDICAP keeps the row it had
    assert by[MS.IMAGE_SET].id == t.by_name["AD_LED_MAX_BRIGHTNESS"]   # EDITION's old row, EDITION not wanted


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_a_deprecated_spare_is_taken_before_another_settings_old_row(card):
    # one DEPRECATED spare left beside a stale HANDICAP row: IMAGE SET takes the DEPRECATED one
    t = AdjustmentTable(_written(card, [MUSIC, HANDI]))
    settings, _w, _c, refused = MS.plan_many(t, [MUSIC, IMAGE])
    assert refused == {}
    img = next(s for s in settings if s.key == MS.IMAGE_SET)
    assert MS.menu_label(t, img.id).upper().startswith(MS.DEPRECATED)


def test_the_panel_ticks_music_mode_when_the_card_gets_it(tmp_path):
    from pinball_decryptor.plugins.stern import sound_modes as SMo
    from tests.webui_harness import web_app
    p = str(tmp_path / "proj")
    os.makedirs(p)
    with open(os.path.join(p, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({SMo.STAGED_KEY: {"names": ["Standard", "Orchestral"],
                                    "slots": {"audio/idx2095 - music - x.wav": {"2": "a.wav"}}}}, f)
    assert SMo.load(p).count == 2
    with web_app(tmp_path / "app") as w:
        modes = w.window.service("modes")
        var = modes._project_var() if modes is not None else None
        if var is None:
            pytest.skip("no project folder variable in this window")
        w.run(lambda: var.set(p))
        w.drain()
        w.call("ui.select_tab", "svcmenu")
        w.drain()
        rows = {r["key"]: r for r in w.state("svcmenu")["settings"]}
        assert rows["music_mode"]["on"] and not rows["music_mode"]["can"]
        assert not rows["edition"]["on"] and not rows["handicap"]["on"]
        assert rows["handicap"]["note"].startswith("Not on the card")
