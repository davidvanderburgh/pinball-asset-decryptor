"""PAD-624: the Video tab's Played in and clip sounds on every Spike 2 title, not Godzilla's kind
alone (a Pinside report on an Uncanny X-Men project saw neither).

Three ways a title's rules are classes, each read for its modes (:func:`.clip_modes._mode_classes`):
``cmode_*`` leaves (Godzilla, unchanged), classes deriving from ``cmode`` named freely (Venom's
``ccarnage_mball``, Deadpool's ``cbattle_juggernaut``), and singleton rule classes (X-Men's
``Mode_Stopping_A_Juggernaut``). When the card gives the tab nothing, the toolbar says why in one
line. Checked on synthetic class models, in the web harness, and on the real X-Men and Venom
programs where the cards are on this machine (skipped elsewhere, as on CI)."""

import json
import os

import pytest

from pinball_decryptor.plugins.stern import clip_modes as CM
from pinball_decryptor.plugins.stern import stock_scan as S
from pinball_decryptor.webui import video_modes as VM
from tests.test_webui_video import _project, _scan, _wait
from tests.webui_harness import web_app

CARDS = os.environ.get("PAD444_CARDS", r"D:\Pinball\images\Stern\spike2")
XMEN = os.path.join(CARDS, "uncanny_xmen_pro-0_98_0.Release.16G.sdcard.raw")
VENOM = os.path.join(CARDS, "venom_pro-1_07_0.Release.8G.sdcard.raw")


def _model(**bases):
    return {c: ({"base": b} if b else {}) for c, b in bases.items()}


# ---- which classes are modes ---------------------------------------------------------------------
def test_a_godzilla_style_title_keeps_its_cmode_leaves():
    model = _model(cmode=None, cmode_timed="cmode", cmode_manager=None, cmode_null="cmode",
                   cmode_battle_vs_gigan="cmode_timed", cmode_monster_zero="cmode")
    assert CM._mode_classes(S, model) == ["cmode_battle_vs_gigan", "cmode_monster_zero"]


def test_freely_named_mode_classes_are_modes_and_their_framework_is_not(monkeypatch):
    model = _model(cmode=None, cmode_timed="cmode", cmode_battle="cmode_timed",
                   cmode_manager=None, cmode_null="cmode", cmode_song_player=None,
                   cbattle_juggernaut="cmode_battle",
                   cbattle_juggernaut_sauron="cbattle_juggernaut",
                   cberserker_rage="cmode_timed", ccarnage_mball="cmode")
    assert CM._mode_classes(S, model) == [
        "cbattle_juggernaut_sauron", "cberserker_rage", "ccarnage_mball"]
    # a base the game builds an object of is a mode too (Deadpool's battle and its Sauron one)
    from pinball_decryptor.plugins.stern import stock_scan_cpp as SC
    monkeypatch.setattr(SC, "init_objects", lambda prog, model, root: [
        {"class": "cbattle_juggernaut"}, {"class": "cmode_timed"}])
    assert CM._mode_classes(S, model, prog=object()) == [
        "cbattle_juggernaut", "cbattle_juggernaut_sauron", "cberserker_rage", "ccarnage_mball"]


def test_a_singleton_rule_title_reads_its_rule_classes_less_the_shared_parts():
    names = ["Mode_Stopping_A_Juggernaut", "Multiball_Berserker", "Rule_Danger_Room", "Skillshot",
             "Mode_Select", "Mode_Info", "Mode_Shared", "Sentinels_Controller", "ShakerManager",
             "Sentinels_Display", "ScoreFrame"]
    model = _model(MenuPage=None, **{n: "Singleton<%s>" % n for n in names})
    model.update(_model(**{"Singleton<%s>" % n: None for n in names}))
    assert CM._mode_classes(S, model) == [
        "Mode_Stopping_A_Juggernaut", "Multiball_Berserker", "Rule_Danger_Room", "Skillshot"]


@pytest.mark.parametrize("cls, label, slug", [
    ("cmode_battle_vs_megalon_and_gigan_mb", "Battle vs Megalon and Gigan Multiball",
     "battle_vs_megalon_and_gigan_mb"),
    ("cberserker_rage", "Berserker Rage", "berserker_rage"),
    ("ccarnage_mball", "Carnage Multiball", "carnage_mball"),
    ("choth_i", "Hoth I", "hoth_i"),
    ("Mode_Stopping_A_Juggernaut", "Stopping a Juggernaut", "stopping_a_juggernaut"),
    ("Multiball_To_Me_My_Xmen", "To Me My Xmen Multiball", "to_me_my_xmen"),
    ("Rule_Danger_Room", "Danger Room", "danger_room"),
])
def test_each_kind_of_mode_class_is_named_in_words(cls, label, slug):
    assert CM.mode_label(cls) == label
    assert CM.mode_slug(cls) == slug


def test_a_copy_of_a_freely_named_modes_clip_is_known_again():
    name = CM.own_name("Bloodlust_Start", "cblood_lust")
    assert name == "Bloodlust_Start_blood_lust"
    assert CM.copy_of(name, {"Bloodlust_Start"}, {"cblood_lust": "Blood Lust"}) == (
        "Bloodlust_Start", "cblood_lust")


# ---- the toolbar says why there is nothing ---------------------------------------------------------
def _ready(w):
    return _wait(w, lambda st: st["rows"] and st["modes"]["ready"] and not st.get("scanning"))


def test_a_project_whose_card_is_gone_says_so_in_one_line(tmp_path):
    proj = _project(tmp_path, names=("video/a.mp4",))
    (proj / ".extract_source.json").write_text(json.dumps(
        {"input_path": str(tmp_path / "gone" / "uncanny_xmen_pro-0_98_0.Release.16G.sdcard.raw"),
         "input_name": "uncanny_xmen_pro-0_98_0.Release.16G.sdcard.raw"}), encoding="utf-8")
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        st = _ready(w)
        assert st["modes"]["list"] == []
        assert st["modes"]["why"] == {"line": VM.WHY_GONE,
                                      "tip": {"head": VM.WHY_GONE, "lines": [VM.WHY_GONE_TIP]}}


def test_a_title_whose_modes_cant_be_told_apart_says_so_and_where_its_sounds_are(
        tmp_path, monkeypatch):
    proj = _project(tmp_path, names=("video/a.mp4",))
    card = tmp_path / "elvira3-1_13_0.Release.16G.sdcard.raw"
    card.write_bytes(b"\0" * 16)
    (proj / ".extract_source.json").write_text(json.dumps(
        {"input_path": str(card), "input_name": card.name}), encoding="utf-8")
    sounds = {"pairs": {"a": [[5, "next", 3, 4096]]}, "count": 10}

    def fake(card_path, rows, cancel=None):
        return CM.CardClips(card=card_path, game="elvira3", version="1.13.0",
                            name_of={"video/a.mp4": "a"}, sounds=dict(sounds),
                            note="the app can't tell this game's modes apart in its program")
    monkeypatch.setattr(CM, "read_card", fake)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        st = _ready(w)
        assert st["modes"]["why"]["line"] == VM.WHY_NO_MODES
        assert st["modes"]["why"]["tip"]["lines"] == [VM.WHY_NO_MODES_TIP, VM.WHY_SOUNDS_OK]
        # ... and with no sounds either, the tip says that instead
        sounds.clear()
        sounds.update({"note": "no clip's code asks for a sound by a fixed number"})
        card.write_bytes(b"\0" * 32)                    # another size: the card is read again
        _scan(w, proj)
        st = _wait(w, lambda st: st["modes"]["ready"] and (st["modes"].get("why") or {}).get(
            "tip", {}).get("lines", [""])[-1] == VM.WHY_SOUNDS_NONE)
        assert st["modes"]["why"]["line"] == VM.WHY_NO_MODES


def test_the_page_draws_the_why_line():
    path = os.path.join(os.path.dirname(VM.__file__), "static", "js", "tabs", "video.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "md.why ? html`<span class=\"small muted nw vid-modes-why\" ...${tip(md.why.tip)}>" \
           "${md.why.line}</span>`" in js


@pytest.mark.parametrize("code", ["de", "es", "fr"])
def test_the_why_lines_are_in_every_language(code):
    path = os.path.join(os.path.dirname(VM.__file__), "static", "i18n", code + ".json")
    with open(path, encoding="utf-8") as f:
        cat = json.load(f)
    for k in (VM.WHY_GONE, VM.WHY_GONE_TIP, VM.WHY_UNREAD, VM.WHY_NO_MODES, VM.WHY_NO_MODES_TIP,
              VM.WHY_SOUNDS_OK, VM.WHY_SOUNDS_NONE):
        assert cat.get(k), (code, k)


# ---- the real programs ---------------------------------------------------------------------------
def _program(card):
    from pinball_decryptor.plugins.stern.clip_sounds import card_fragments
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, version, part = card_title(card)
    with CardImage(card) as img:
        return (img.preview(part, "/%s/game" % game, cap=256 << 20),
                card_fragments(img, part, game), game, version)


@pytest.mark.skipif(not os.path.isfile(XMEN), reason="the X-Men Pro 0.98 card is not here")
def test_xmen_names_the_modes_that_play_its_clips_and_their_sounds():
    from pinball_decryptor.plugins.stern import clip_sounds as CS
    elf, fragments, game, version = _program(XMEN)
    names = {"Stopping_A_Juggernaut_Award2", "Fiery_Assault_Award1", "Mode_Fail",
             "EscapeNimrod_Start", "TMMXM_Rogue_Award", "OrbitSkillShot_1", "Lock1"}
    ctx = {}
    r = CM.analyse(elf, names, ctx=ctx)
    assert r.modes_of("Stopping_A_Juggernaut_Award2") == ["Mode_Stopping_A_Juggernaut"]
    assert r.label("Mode_Stopping_A_Juggernaut") == "Stopping a Juggernaut"
    assert r.modes_of("Fiery_Assault_Award1") == ["Mode_A_Fiery_Assault"]
    assert r.modes_of("EscapeNimrod_Start") == ["Mode_Escape_Nimrod"]
    # the clip every mode plays when it fails is each of theirs
    assert len(r.modes_of("Mode_Fail")) >= 6
    sr = CS.analyse(elf, names, fragments, game, version, refs=r.refs or None, ctx=ctx)
    assert sr.sounds_of("Stopping_A_Juggernaut_Award2")
    assert any(s["how"] in CS.SURE for s in sr.sounds_of("TMMXM_Rogue_Award"))


@pytest.mark.skipif(not os.path.isfile(VENOM), reason="the Venom Pro 1.07 card is not here")
def test_venom_names_its_freely_named_modes():
    elf, _f, _g, _v = _program(VENOM)
    r = CM.analyse(elf, {"CarnageMultiball_CarnageJackpot", "LasherBattle_Advance_1",
                         "ToxinTeamUp_Award_Captain"})
    assert [r.label(m) for m in r.modes_of("CarnageMultiball_CarnageJackpot")] == [
        "Carnage Multiball"]
    assert [r.label(m) for m in r.modes_of("LasherBattle_Advance_1")] == ["Lasher Mode"]
    assert [r.label(m) for m in r.modes_of("ToxinTeamUp_Award_Captain")] == ["Toxin Teamup"]
