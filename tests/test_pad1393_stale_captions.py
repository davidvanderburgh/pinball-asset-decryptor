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
                                    "slots": {"audio/idx2095 - music - x.wav": {"2": "a.wav"}}},
                   "service_menu": {"on": ["music_mode"]}}, f)        # round 3: ticked by the owner
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
        assert rows["music_mode"]["on"] and rows["music_mode"]["can"]      # round 2: switchable here too
        assert not rows["edition"]["on"] and not rows["handicap"]["on"]
        assert rows["handicap"]["note"].startswith("Not on the card")


def test_the_panel_unticks_music_mode_and_image_set(tmp_path):
    """Round 2 (DragonRR): "Music mode is checked and cannot be unchecked", "Image set ... I cannot uncheck it". Their
    rows can be left off the card on the panel; the project keeps the settings, the Write leaves them out."""
    from pinball_decryptor.plugins.stern import service_menu as SM, sound_modes as SMo, scene_variants as SV
    from tests.webui_harness import web_app
    p = str(tmp_path / "proj")
    os.makedirs(p)
    scene = "auto_loaded/" + "c" * 40 + "/scene.radium"
    with open(os.path.join(p, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({SMo.STAGED_KEY: {"names": ["Standard", "Orchestral"],
                                    "slots": {"audio/idx2095 - music - x.wav": {"2": "a.wav"}}},
                   SV.STAGED_KEY: {"names": ["Standard", "Dark"], "scenes": {scene: {"2": {"card": True}}}}}, f)
    assert SM.wanted(p) == []                               # round 3: both start unticked
    assert {w[0] for w in SM.wanted(p, honour_off=False)} == {MS.MUSIC_MODE, MS.IMAGE_SET}
    SM.save(p, {"order": [], "on": ["music_mode", "image_set"]})
    assert {w[0] for w in SM.wanted(p)} == {MS.MUSIC_MODE, MS.IMAGE_SET}
    with web_app(tmp_path / "app") as w:
        modes = w.window.service("modes")
        var = modes._project_var() if modes is not None else None
        if var is None:
            pytest.skip("no project folder variable in this window")
        w.run(lambda: var.set(p))
        w.drain()
        w.call("ui.select_tab", "svcmenu")
        w.drain()

        def rows():
            return {r["key"]: r for r in w.state("svcmenu")["settings"]}
        r = rows()
        assert r["music_mode"]["on"] and r["music_mode"]["can"]
        assert r["image_set"]["on"] and r["image_set"]["can"]
        assert r["edition"]["can"] and not r["edition"]["on"]   # no editions yet: tickable all the same (a placeholder)
        assert w.call("svcmenu.set_row", "image_set", False)
        assert w.call("svcmenu.set_row", "music_mode", False)
        w.drain()
        r = rows()
        assert not r["image_set"]["on"] and r["image_set"]["can"]
        assert r["image_set"]["note"].startswith("Off the card")
        assert not r["music_mode"]["on"] and r["music_mode"]["note"].startswith("Off the card")
        assert SM.wanted(p) == []                           # the Write (and the menu page) leave both out
        assert {x[0] for x in SM.wanted(p, honour_off=False)} == {MS.MUSIC_MODE, MS.IMAGE_SET}
        assert SMo.load(p).count == 2 and SV.load(p)        # the settings themselves are kept
        assert w.call("svcmenu.set_row", "music_mode", True)
        w.drain()
        assert rows()["music_mode"]["on"] and [x[0] for x in SM.wanted(p)] == [MS.MUSIC_MODE]
        assert SM.load(p)["on"] == ["music_mode"]


def test_the_on_list_keeps_the_order_and_only_known_keys(tmp_path):
    from pinball_decryptor.plugins.stern import service_menu as SM
    p = str(tmp_path)
    assert SM.off_keys(p) == set(SM.OFF_KEYS)               # round 3: everything off until ticked
    SM.save(p, {"order": ["handicap"], "on": ["image_set", "handicap", "bogus"]})
    assert SM.load(p) == {"order": ["handicap"], "on": ["image_set"], "coop": False}
    assert SM.off_keys(p) == {"music_mode", "edition"}
    SM.save(p, {"order": [], "on": []})
    assert SM.load(p) == {"order": [], "on": [], "coop": False}


def test_round3_every_row_starts_unticked(tmp_path):
    """Round 3 (DragonRR): "Everything should be unchecked by default". A project with music modes and image sets
    shows both rows unticked (but tickable), Handicap and Co-op unticked, and the round-2 "off" list is read no
    more."""
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import service_menu as SM, sound_modes as SMo, scene_variants as SV
    from tests.webui_harness import web_app
    p = str(tmp_path / "proj")
    os.makedirs(p)
    scene = "auto_loaded/" + "c" * 40 + "/scene.radium"
    SC.save(p, {SMo.STAGED_KEY: {"names": ["Standard", "Orchestral"],
                                 "slots": {"audio/idx2095 - music - x.wav": {"2": "a.wav"}}},
                SV.STAGED_KEY: {"names": ["Standard", "Dark"], "scenes": {scene: {"2": {"card": True}}}},
                SM.STAGED_KEY: {"off": ["edition"]}})
    assert SM.wanted(p) == [] and SM.off_keys(p) == set(SM.OFF_KEYS)
    with web_app(tmp_path / "app") as w:
        modes = w.window.service("modes")
        var = modes._project_var() if modes is not None else None
        if var is None:
            pytest.skip("no project folder variable in this window")
        w.run(lambda: var.set(p))
        w.drain()
        w.call("ui.select_tab", "svcmenu")
        w.drain()
        r = {x["key"]: x for x in w.state("svcmenu")["settings"]}
        assert not any(x["on"] for x in r.values()), r
        assert r["music_mode"]["can"] and r["image_set"]["can"] and r["edition"]["can"]   # every row tickable
        assert r["music_mode"]["note"].startswith("Off the card")


def test_round3_coop_row_is_gone_from_the_service_menu_tab():
    """PAD-1443 (daveyvandy: "too confusing to have it buried in the service menu"): co-op play has no service menu
    row; its games are always on the game's start menu, so the Service menu tab lists none to tick."""
    from pinball_decryptor.webui.tabs import svcmenu
    assert "coop_play" not in [k for k, _n, _w in svcmenu.SETTINGS]
    assert not hasattr(svcmenu.ServiceMenuTab, "_set_coop")


def test_an_unticked_music_mode_leaves_the_music_modes_and_keeps_the_other_sounds(tmp_path, monkeypatch):
    """The Write's side: MUSIC MODE unticked drops the other music modes only; sounds in turn and in attract stay."""
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import engine as E, service_menu as SM, sound_modes as SMo
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: MP.profile("james_bond_pro_1_06"))
    p = str(tmp_path)
    SC.save(p, {"sound_modes": {"names": ["Standard", "Orchestral"],
                                "slots": {"audio/idx2095 - music - x.wav": {"2": "a.wav"}},
                                "attract": ["b.wav"], "turns": {"audio/idx0002.wav": ["t.wav"]}}})
    logs = []

    def build():
        logs.clear()
        return E._sound_modes_for_build(p, False, lambda t, lvl="info": logs.append((t, lvl)),
                                        ext4_available=lambda: (True, ""))
    modes, _prof = build()                                 # round 3: unticked until ticked
    assert modes is not None and modes.count == 0 and modes.attract == ["b.wav"] and modes.turns
    assert any("MUSIC MODE is not ticked" in t for t, _l in logs)
    SM.save(p, {"order": [], "on": ["music_mode"]})
    modes, _prof = build()
    assert modes.count == 2
    assert SMo.load(p).count == 2                          # the project keeps them


def test_spike3_honours_the_unticked_rows(tmp_path, monkeypatch):
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import editions as Ed, service_menu as SM, spike3_menu as S3, \
        spike3_music as S3M, sound_modes as SMo
    p = str(tmp_path)
    monkeypatch.setattr(Ed, "load", lambda project: ["Kaiju", "Heisei"])
    monkeypatch.setattr(Ed, "project_refusal", lambda project: "")
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: None)
    SC.save(p, {"sound_modes": {"names": ["Standard", "Orchestral"],
                                "slots": {"audio/idx2095 - music - x.wav": {"2": "a.wav"}}}})
    assert S3.rows_wanted(p) == [] and S3M.wanted(p) == (None, None)   # round 3: unticked until ticked
    SM.save(p, {"order": [], "on": ["edition", "music_mode"]})
    assert [r[0] for r in S3.rows_wanted(p)] == [MS.EDITION]
    assert S3M.wanted(p)[0] is not None
