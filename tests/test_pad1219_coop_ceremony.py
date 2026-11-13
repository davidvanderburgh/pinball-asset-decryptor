"""PAD-1219: the co-op awards ceremony - the award cards over a clip that fills the glass (the game's End of Ball Bonus
loop, or the owner's own video) with the game's HUD off it and the final score along the bottom.

DoomWalrus666: "Co-op awards are playing over a gameplay clip (Mechagodzilla) instead of the End of Ball Bonus videos
... please remove the scoreboard, power up bar, and credits/player/ball count thing. Just display the awards box, and
the final score along the bottom in large font ... add an option in the Modes tab Character settings to add a custom
awards ceremony background video"."""
import os
import re
import types

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import mode_write as MW
from tests import test_pad1028_coop_awards as A
from tests import test_spike2_mode_roster as R


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "project"
    p.mkdir()
    return str(p)


def _video(tmp_path, name="awards.mp4", data=b"not really a video"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


# ---- the owner's video, kept in the project -------------------------------------------------------------------------
def test_ceremony_video_kept_beside_the_intro(project, tmp_path):
    CP.save_intro(project, _video(tmp_path, "intro.mp4"))
    chars = CP.save_ceremony(project, _video(tmp_path))
    assert chars["ceremony"] == "coop/ceremony_video.mp4" and chars["intro"] == "coop/intro_video.mp4"
    assert CP.ceremony_path(project) == os.path.join(project, "coop", "ceremony_video.mp4")
    CP.save_ceremony(project, _video(tmp_path, "awards.mov"))
    assert sorted(os.listdir(os.path.join(project, "coop"))) == ["ceremony_video.mov", "intro_video.mp4"]
    CP.save_ceremony(project, None)
    assert "ceremony" not in CP.load_characters(project) and CP.ceremony_path(project) == ""
    assert CP.intro_path(project).endswith("intro_video.mp4")
    with pytest.raises(CP.CoopError):
        CP.save_ceremony(project, _video(tmp_path, "awards.txt"))


def test_settings_file_carries_the_ceremony_video(project, tmp_path):
    CP.save(project, True)
    CP.save_intro(project, _video(tmp_path, "intro.mp4", b"intro bytes"))
    CP.save_ceremony(project, _video(tmp_path, data=b"awards bytes"))
    zpath = str(tmp_path / "coop.zip")
    CP.export_settings(project, zpath)
    other = tmp_path / "other"
    other.mkdir()
    got = CP.import_settings(str(other), zpath)
    assert got["pictures"] == 2
    with open(CP.ceremony_path(str(other)), "rb") as f:
        assert f.read() == b"awards bytes"
    with open(CP.intro_path(str(other)), "rb") as f:
        assert f.read() == b"intro bytes"


# ---- the build: what plays behind the cards, the final score's band -------------------------------------------------
def _result(project):
    return types.SimpleNamespace(project=project, lines=[], new=[], replaced=[],
                                 profile=types.SimpleNamespace(label="Godzilla LE 1.16"))


def test_without_a_video_the_games_bonus_loop_goes_behind_the_cards(project, tmp_path, monkeypatch):
    monkeypatch.setattr(CP, "bonus_loop", lambda bank, parsed=None: ("EndOfBallBonus_BackgroundLoop", "SquareCrop"))
    res = _result(project)
    assert MW.coop_ceremony_into(res, b"bank", str(tmp_path)) == ("EndOfBallBonus_BackgroundLoop", "SquareCrop")
    assert res.new == [] and "End of Ball Bonus loop" in res.lines[0]
    monkeypatch.setattr(CP, "bonus_loop", lambda bank, parsed=None: None)
    res = _result(project)
    assert MW.coop_ceremony_into(res, b"bank", str(tmp_path)) is None
    assert "the HUD off it" in res.lines[0]


def test_the_owners_video_goes_in_the_bank_full_screen(project, tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import video_bank as VB
    CP.save_ceremony(project, _video(tmp_path))
    made = {}

    def clip(src, out, w, h, ffmpeg, max_seconds=None):
        made.update(src=src, size=(w, h))
        with open(out, "wb") as f:
            f.write(b"x" * 100)
    monkeypatch.setattr(CP, "intro_clip", clip)
    monkeypatch.setattr(VB, "clip_frame", lambda bank: (1360, 768))
    monkeypatch.setattr(VB, "add_clip", lambda bank, name, size: (bank + name.encode(), {"path": "2.asset/9.asset"}))
    monkeypatch.setattr(MW, "_coop_bank", lambda result, stock, what: ("a/b/scene.radium", stock, ""))
    res = _result(project)
    got = MW.coop_ceremony_into(res, b"bank", str(tmp_path / "scratch"), ffmpeg="ffmpeg")
    assert got == ("PadCoopCeremony", "Normal")
    assert made == {"src": CP.ceremony_path(project), "size": (1360, 768)}
    assert res.new[0][0] == "a/b/scene.assets/2.asset/9.asset"
    assert res.replaced and res.replaced[0][0] == "a/b/scene.radium"


def test_the_final_scores_band_rides_with_the_cards(project):
    CP.save_characters(project, {"pick": True, "list": [{"name": "GODZILLA 1954", "ability": ""}]})
    screens = CP.award_screens(project)
    band = screens[-1]
    assert [s["name"] for s in screens] == ["PadCoopAward_1", "PadCoopFinal"]
    assert band["art_rgba"].shape == (CP.FINAL_SIZE[1], CP.FINAL_SIZE[0], 4)
    assert band["words_name"] == "PadCoopFinal_Words" and band["words_scale"] >= 1.4
    assert CP.FINAL_AT[1] >= CP.AWARD_AT[1] + CP.AWARD_SIZE[1]           # under the cards
    assert CP.FINAL_AT[1] + CP.FINAL_SIZE[1] <= 768                       # on the glass
    a = band["art_rgba"].astype(int)
    assert (a[..., :3] <= a[..., 3:4]).all()                              # premultiplied
    assert a[0, 680, 3] == 0 and a[120, 680, 3] > 150                     # see-through at its top, dark at its foot


@pytest.mark.skipif(not os.path.isfile(A.GZ_ELF), reason="needs the Godzilla LE 1.16 program")
def test_write_names_the_ceremony_in_coop_cfg(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import sound_modes as SMo
    with open(A.GZ_ELF, "rb") as f:
        elf = f.read()
    prof = next(p for p in MP.profiles().values() if SMo.title_key(p) == "godzilla_le-1.16")
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: MP.port_path(prof))
    monkeypatch.setattr(MW, "coop_ceremony_into", lambda *a, **k: ("EndOfBallBonus_BackgroundLoop", "SquareCrop"))
    monkeypatch.setattr(MW, "coop_clips_into", lambda *a, **k: [])
    monkeypatch.setattr(MW, "coop_intro_into", lambda *a, **k: None)
    monkeypatch.setattr(MW, "coop_picked_into", lambda *a, **k: [])
    monkeypatch.setattr(MW, "coop_bonus_into", lambda *a, **k: None)
    from pinball_decryptor.plugins.stern import scene_write as SW
    monkeypatch.setattr(SW, "add_screens", lambda hud, screens, **k: (b"hud with the cards", []))
    project = str(tmp_path / "project")
    os.makedirs(project)
    CP.save(project, True)
    CP.save_characters(project, {"pick": True, "list": [{"name": "GODZILLA 1954", "ability": ""}]})
    try:
        result = MW.plan(project, b"stock hud", b"", elf, str(tmp_path / "scratch"), modes_on=False, coop=True,
                         coop_prof=prof)
    except MW.ModeWriteError as e:
        pytest.skip("the HUD scene is not on hand here: %s" % e)
    with open(result.coop_file, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[lines.index("award_cards on") + 1] == "ceremony EndOfBallBonus_BackgroundLoop SquareCrop"


# ---- the runtime -------------------------------------------------------------------------------------------------
def test_the_final_scores_words(tmp_path):
    src = A.RUNTIME.read_text(encoding="utf-8")
    words = R._lift(src, "static void coop_final_words_of(char *out, unsigned cap, int teams, unsigned long long s1, "
                         "unsigned long long s2)")
    main = r"""
#include <stdio.h>
#include <stdint.h>
#define pm_snprintf snprintf
@DEF@
static void pm_commas(char *out, unsigned cap, uint64_t v)
{
    char t[32];
    int n = snprintf(t, sizeof t, "%llu", (unsigned long long)v), i, o = 0;
    for (i = 0; i < n && o + 2 < (int)cap; i++) { if (i && (n - i) % 3 == 0) out[o++] = ','; out[o++] = t[i]; }
    out[o] = 0;
}
@FN@
int main(void)
{
    char w[80];
    coop_final_words_of(w, sizeof w, 0, 155084330ull, 0ull);
    printf("[%s]", w);
    coop_final_words_of(w, sizeof w, 1, 900ull, 34500ull);
    printf("[%s]", w);
    coop_final_words_of(w, sizeof w, 1, 155084330ull, 98000000ull);
    printf("[%s]", w);
    return 0;
}
""".replace("@FN@", words).replace("@DEF@", re.search(r"#define COOP_FINAL_FITS \d+", src).group(0))
    assert R._host_run(tmp_path, main) == ("[FINAL SCORE  155,084,330][TEAM 1  900   TEAM 2  34,500]"
                                           "[T1 155,084,330  T2 98,000,000]")


def test_the_ceremony_keeps_the_hud_off_and_its_clip_behind_the_cards():
    src = A.RUNTIME.read_text(encoding="utf-8")
    show = R._lift(src, "static void coop_cards_show(unsigned n)")
    # the build's clip first (a bonus end the game never shows at a game's end is not waited for), then the HUD off,
    # the clip up, the cards, the clip given back, the HUD back
    assert show.index("if (coop_cer_clip[0])") < show.index("coop_cer_begin();") \
        < show.index("coop_cards_backdrop(coop_bonus_clip)") < show.index("pm_show(coop_card[c], 1);") \
        < show.index("coop_cards_backdrop(0);") < show.index("coop_cer_end();")
    begin = R._lift(src, "static void coop_cer_begin(void)\n{")
    assert "coop_cer_keep = scene(coop_scr_scene);" in begin and '"PadCoopFinal"' in begin
    assert "pm_score(1), pm_score(2)" in begin and "pm_show(coop_final, 1);" in begin
    assert "pm_show(coop_final, 0);" in R._lift(src, "static void coop_cer_end(void)\n{")
    assert "pm_show(coop_final, 0);" in R._lift(src, "static void coop_cards_find(void)")   # hidden all game
    veto = R._lift(src, "static void coop_cer_scene_show(unsigned *r)")
    assert "== coop_cer_keep" in veto and 'fn("video_player")' in veto and "r[0] = 0;" in veto
    on = R._lift(src, "static void on_scene_show(unsigned *r)")
    assert on.index("scene_show_backdrop(r);") < on.index("if (coop_cer_on) coop_cer_scene_show(r);")
    assert "|| coop_cer_on) return 1;" in R._lift(src, "static int bd_place_ok(unsigned e)")   # any background's place
    line = R._lift(src, "static void coop_line(const char *s)")
    assert 'str_starts(s, "ceremony ")' in line and "coop_cer_crop[k] = p[k];" in line
