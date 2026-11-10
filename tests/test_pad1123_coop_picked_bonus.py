"""PAD-1123: a co-op character's clip and sound once picked, and the character on its teammate's End of Ball Bonus -
the project's files, the clips the build makes (a still as long as its sound; the bonus loop with a framed window right
of the bonus's words, through the bank's crop), the sound's pseudo modes and sounds.cfg line, coop.cfg's lines, and
the runtime's choices (lifted verbatim from pad_mode_runtime.c)."""
import os
import shutil
import subprocess
import zipfile
from types import SimpleNamespace

import pytest

from tests import test_spike2_mode_roster as R
from tests import test_pad1017_coop_turns as T

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import sound_modes as SM

#: Godzilla LE 1.16's video bank, SquareCrop (read off the card: x1.29, moved -197,-126)
SQUARE = (1.28997802734375, 0, 0, 0, 0, 1.2899322509765625, 0, 0, 0, 0, 1, 0, -197.0, -126.0, 0, 1)


def _ffmpeg():
    from pinball_decryptor.core.audio import find_ffmpeg
    ff = find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg here")
    return ff


def _project(tmp_path, n=2):
    project = str(tmp_path / "project")
    os.makedirs(project)
    CP.save(project, True)
    CP.save_characters(project, {"pick": True, "list": [{"name": "godzilla %d" % (k + 1)} for k in range(n)]})
    return project


def _png(path, colour=(200, 30, 30), size=(64, 48)):
    from PIL import Image
    Image.new("RGB", size, colour).save(path)
    return str(path)


# ---- the project's files ---------------------------------------------------------------------------------------------
def test_a_character_keeps_a_clip_and_a_sound_once_picked(tmp_path):
    project = _project(tmp_path)
    pic = _png(tmp_path / "poster.png")
    wav = tmp_path / "roar.wav"
    wav.write_bytes(b"RIFF0000WAVE")
    CP.save_picked_clip(project, 0, pic)
    CP.save_picked_sound(project, 0, str(wav))
    c = CP.load_characters(project)["list"][0]
    assert c["picked_clip"] == "coop/character_1_picked.png" and c["picked_sound"] == "coop/character_1_picked_sound.wav"
    assert CP.picked_clip_path(project, c) and CP.is_still(CP.picked_clip_path(project, c))
    assert CP.picked_sound_source(project, c).endswith("character_1_picked_sound.wav")
    assert CP.picked_entries(project) == [(0, "PadCoopPicked1", CP.picked_clip_path(project, c))]
    CP.save_picked_sound(project, 0, None)                  # a still without a sound: silent
    c = CP.load_characters(project)["list"][0]
    assert c["picked_sound"] == "" and CP.picked_sound_source(project, c) == ""
    assert not os.path.exists(os.path.join(project, "coop", "character_1_picked_sound.wav"))
    CP.save_picked_clip(project, 0, None)
    assert CP.load_characters(project)["list"][0]["picked_clip"] == "" and CP.picked_entries(project) == []


def test_a_picked_video_plays_its_own_sound_without_one_of_its_own(tmp_path):
    project = _project(tmp_path)
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\0" * 32)
    CP.save_picked_clip(project, 1, str(vid))
    c = CP.load_characters(project)["list"][1]
    assert CP.picked_sound_source(project, c) == CP.picked_clip_path(project, c)


def test_files_it_cannot_take_are_refused(tmp_path):
    project = _project(tmp_path)
    bad = tmp_path / "notes.txt"
    bad.write_text("x")
    with pytest.raises(CP.CoopError):
        CP.save_picked_clip(project, 0, str(bad))
    with pytest.raises(CP.CoopError):
        CP.save_picked_sound(project, 0, str(bad))
    fake = tmp_path / "fake.png"
    fake.write_text("not a picture")
    with pytest.raises(CP.CoopError):
        CP.save_picked_clip(project, 0, str(fake))
    with pytest.raises(CP.CoopError):
        CP.save_picked_clip(project, 5, _png(tmp_path / "p.png"))


def test_the_bonus_tick_shows_characters_with_a_picture_or_video(tmp_path):
    project = _project(tmp_path, 3)
    CP.save_picture(project, 0, _png(tmp_path / "a.png"))
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"\0" * 32)
    CP.save_video(project, 2, str(vid))
    assert CP.bonus_entries(project) == []                  # off until ticked
    CP.save_bonus(project, True)
    got = CP.bonus_entries(project)
    assert [(i, n) for i, n, _p, _v in got] == [(0, "PadCoopBonus1"), (2, "PadCoopBonus3")]
    assert got[0][2] and not got[0][3] and got[1][3]        # the second has a video (it wins)
    CP.save_bonus(project, False)
    assert "bonus" not in CP.load_characters(project)


def test_the_settings_file_carries_them(tmp_path):
    project = _project(tmp_path)
    CP.save_picked_clip(project, 0, _png(tmp_path / "poster.png"))
    wav = tmp_path / "roar.wav"
    wav.write_bytes(b"RIFF0000WAVE")
    CP.save_picked_sound(project, 1, str(wav))
    CP.save_bonus(project, True)
    out = str(tmp_path / "coop.zip")
    CP.export_settings(project, out)
    names = zipfile.ZipFile(out).namelist()
    assert any(n.endswith("1_godzilla_1_picked.png") for n in names)
    assert any(n.endswith("2_godzilla_2_picked_sound.wav") for n in names)
    other = str(tmp_path / "other")
    os.makedirs(other)
    CP.import_settings(other, out)
    got = CP.load_characters(other)
    assert got["bonus"] is True
    assert got["list"][0]["picked_clip"] == "coop/character_1_picked.png"
    assert got["list"][1]["picked_sound"] == "coop/character_2_picked_sound.wav"
    assert os.path.isfile(os.path.join(other, "coop", "character_2_picked_sound.wav"))


# ---- the clips the build makes ---------------------------------------------------------------------------------------
def test_the_window_lands_right_of_the_bonus_words_on_the_glass():
    x, y, w, h = CP.bonus_box(SQUARE, 1360, 768)
    gx, gy = x * SQUARE[0] + SQUARE[12], y * SQUARE[5] + SQUARE[13]           # back on the glass
    assert abs(gx - CP.BONUS_WINDOW[0]) < 3 and abs(gy - CP.BONUS_WINDOW[1]) < 3
    assert abs(w * SQUARE[0] - CP.BONUS_WINDOW[2]) < 3 and abs(h * SQUARE[5] - CP.BONUS_WINDOW[3]) < 3
    assert CP.BONUS_WINDOW[0] > 925                         # the bonus's words end at x 925 (emulator)
    assert CP.BONUS_WINDOW[0] + CP.BONUS_WINDOW[2] + CP.BONUS_BORDER <= 1360
    assert CP.bonus_box(None, 1360, 768)[:2] == CP.BONUS_WINDOW[:2]          # Normal: 1:1


def test_the_bonus_loop_is_found_by_name_at_its_crop():
    bank = SimpleNamespace(library=SimpleNamespace(entries=[SimpleNamespace(name=n) for n in (
        "bonus_collect_powerup", "EndOfBallBonus_BackgroundLoop", "intro1")]),
        labels=[("Normal", 1), ("SquareCrop", 3)])
    assert CP.bonus_loop(b"", bank) == ("EndOfBallBonus_BackgroundLoop", "SquareCrop")
    bank.labels = [("Normal", 1)]
    assert CP.bonus_loop(b"", bank) == ("EndOfBallBonus_BackgroundLoop", "Normal")
    bank.library.entries = [SimpleNamespace(name="bonus_collect_powerup")]
    assert CP.bonus_loop(b"", bank) is None


def test_a_still_is_a_clip_as_long_as_asked(tmp_path):
    ff = _ffmpeg()
    out = str(tmp_path / "picked.mp4")
    CP.picked_clip(_png(tmp_path / "poster.png", size=(300, 400)), out, 320, 180, ff, seconds=4.5)
    assert abs(CP.media_seconds(out, ff) - 4.5) < 0.2


def test_the_bonus_copy_frames_the_picture_in_its_window(tmp_path):
    ff = _ffmpeg()
    from PIL import Image
    loop = str(tmp_path / "loop.mp4")
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=1360x768:r=30", "-t", "2",
                    "-pix_fmt", "yuv420p", loop], check=True)
    out = str(tmp_path / "bonus.mp4")
    box = CP.bonus_box(SQUARE, 1360, 768)
    CP.bonus_clip(loop, out, box, ff, picture=_png(tmp_path / "p.png", (20, 200, 40)), colour="#ffb400")
    assert abs(CP.media_seconds(out, ff) - 2.0) < 0.2       # as long as the loop
    png = str(tmp_path / "f.png")
    subprocess.run([ff, "-v", "error", "-y", "-ss", "1", "-i", out, "-frames:v", "1", png], check=True)
    im = Image.open(png).convert("RGB")
    x, y, w, h = box
    r, g, b = im.getpixel((x + w // 2, y + h // 2))         # the picture in the window
    assert g > 150 and r < 80 and b < 90
    r, g, b = im.getpixel((x - 2, y + h // 2))              # its frame, in the character's colour
    assert r > 200 and 140 < g < 220 and b < 60
    r, g, b = im.getpixel((100, 100))                       # the loop round it
    assert max(r, g, b) < 60


# ---- the sound ------------------------------------------------------------------------------------------------------
def test_a_characters_sound_rides_the_intros_carrier():
    assert SM.is_intro(SM.INTRO_MODE) and SM.is_intro(SM.INTRO_MODE + 16) and not SM.is_intro(SM.INTRO_MODE + 17)
    assert SM.picked_of(SM.INTRO_MODE) == 0 and SM.picked_of(SM.INTRO_MODE + 3) == 3
    assert not SM.is_juke(SM.INTRO_MODE + 16) and not SM.is_shot(SM.INTRO_MODE + 1)
    assert SM.who(SM.INTRO_MODE + 2) == "Co-op characters" and SM.who(SM.INTRO_MODE) == "Co-op intro"
    m = SM.Modes()
    m.picks = [(2, "roar.wav")]
    assert m.coop and m.any
    assert m.files() == []                                  # no carrier yet
    m.intro_rel, m.intro = "audio/idx1725.wav", "intro.wav"
    assert m.files() == [("audio/idx1725.wav", SM.INTRO_MODE, "intro.wav"),
                         ("audio/idx1725.wav", SM.INTRO_MODE + 2, "roar.wav")]


def test_sounds_cfg_names_each_characters_sound():
    key, host, pick = bytes(range(8)), bytes(range(8, 16)), bytes(range(16, 24))
    text = SM.cfg_text(0, 0, [], True, intro={"request": 979, "key": key, "host": host, "ms": 12000,
                                        "picks": [(3, pick, 2500)]})
    assert "cintro\t979\t%s\t%s\t12000" % (key.hex(), host.hex()) in text
    assert "cpick\t3\t979\t%s\t%s\t2500" % (key.hex(), pick.hex()) in text
    text = SM.cfg_text(0, 0, [], True, intro={"request": 979, "key": key, "host": None, "ms": 0,
                                        "picks": [(1, pick, 900)]})
    assert "cintro" not in text and "cpick\t1\t979\t" in text      # picks without an intro


def test_the_build_splits_the_intros_record_from_the_characters(tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    params = [{"idx": 1725, "findkey": b"K" * 8}, {"idx": 9001, "findkey": b"I" * 8, "grown": True},
              {"idx": 9002, "findkey": b"P" * 8, "grown": True}]
    modes = SimpleNamespace(intro_plan={"request": 979, "slot": 1725})
    used = [{"slot": 1725, "host": 9001, "mode": SM.INTRO_MODE, "frames": 44100},
            {"slot": 1725, "host": 9002, "mode": SM.INTRO_MODE + 4, "frames": 22050}]
    got = E._intro_lines(params, used, modes, lambda *a, **k: None)
    assert got["request"] == 979 and got["key"] == b"K" * 8 and got["host"] == b"I" * 8 and got["ms"] == 1000
    assert got["picks"] == [(4, b"P" * 8, 500)]
    assert all(u["lines"] == 1 for u in used)


# ---- coop.cfg and the runtime ----------------------------------------------------------------------------------------
MAIN = r"""
#include <stdio.h>
#define CPK_CHARS 16
@FNS@
int main(void)
{
    static char clips[16][32] = { "PadCoopBonus1", "", "PadCoopBonus3" };
    const char *loop = "EndOfBallBonus_BackgroundLoop";
    const char *a = cb_pick(loop, loop, 0, (const char (*)[32])clips, 16);
    const char *b = cb_pick(loop, loop, 1, (const char (*)[32])clips, 16);
    const char *c = cb_pick("intro1", loop, 0, (const char (*)[32])clips, 16);
    const char *d = cb_pick(loop, loop, -1, (const char (*)[32])clips, 16);
    const char *e = cb_pick(loop, "", 0, (const char (*)[32])clips, 16);
    printf("bonus %s %s %s %s %s\n", a ? a : "-", b ? b : "-", c ? c : "-", d ? d : "-", e ? e : "-");
    printf("has %d %d %d %d %d\n", cpk_has(0, "PadCoopPicked1", 0u, 979), cpk_has(0, "", 1u, 979),
           cpk_has(0, "PadCoopPicked1", 1u, 979), cpk_has(1, "", 1u, 979), cpk_has(0, "PadCoopPicked1", 1u, 0));
    return 0;
}
"""

SIGS = ("static int str_eq(const char *a, const char *b)",
        "static int cpk_has(int c, const char *clip, unsigned have_sound, unsigned request)",
        "static const char *cb_pick(const char *name, const char *loop, int c, const char (*clips)[32], int n)")


def test_the_runtime_answers_the_bonus_loop_with_the_teammates_copy(tmp_path):
    src = T.RUNTIME.read_text(encoding="utf-8")
    out = R._host_run(tmp_path, MAIN.replace("@FNS@", "\n".join(R._lift(src, s) for s in SIGS))).splitlines()
    assert "bonus PadCoopBonus1 - - - -" in out             # theirs; none for a character without one, another clip,
    assert "has 1 2 3 0 1" in out                           # no character, no loop; clip 1 | sound 2


def test_the_runtime_wiring():
    src = T.RUNTIME.read_text(encoding="utf-8")
    close = R._lift(src, "static void coop_pick_close(const char *how)")
    assert "if (coop_done.on) coop_picked_begin(c);" in close     # only for the teammate up, with its card shown
    tick = R._lift(src, "static void coop_picked_tick(void)")
    assert "coop_done.on || coop_clip_on >= 0" in tick            # the clip waits for the card and its video to go
    assert "ci_skip(switch_held(coop_left), switch_held(coop.button), &cpk.freed)" in tick
    assert "pm_clip(cpk.clip[c])" in tick
    play = R._lift(src, "static void on_coop_bonus_play(unsigned *r)")
    assert "coop_pick_of[coop.turn]" in play and "r[0] = (unsigned)(unsigned long)ours;" in play
    look = R._lift(src, "static void on_sound_lookup(unsigned *r)")
    assert "if (cpk_live && r[1] && cpk_lookup(r)) return;" in look
    line = R._lift(src, "static void coop_line(const char *s)")
    assert 'str_starts(s, "char_picked ")' in line and 'str_starts(s, "bonus_loop ")' in line


def test_coop_cfg_lines_from_the_build(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW
    project = _project(tmp_path)
    result = SimpleNamespace(project=project, lines=[], new=[], replaced=[], profile=None)
    assert MW.coop_picked_into(result, b"", str(tmp_path / "s")) == []         # no picked clip: nothing asked
    assert MW.coop_bonus_into(result, b"", str(tmp_path / "s")) is None        # bonus off: nothing asked
    CP.save_picked_clip(project, 0, _png(tmp_path / "poster.png"))
    CP.save_characters(project, dict(CP.load_characters(project), pick=False))
    assert MW.coop_picked_into(result, b"", str(tmp_path / "s")) == []         # no pick: no clip once picked


@pytest.mark.skipif(not os.path.isfile(r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"),
                    reason="no Godzilla LE 1.16 card here")
def test_godzillas_bank_has_its_bonus_loop_at_squarecrop():
    from pinball_decryptor.plugins.stern import clip_variants as CV
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern import video_bank as VB
    card = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
    with open(card, "rb") as f:
        r = E._open_readers(f, E._linux_partitions(card))[0][1]
        prof = SimpleNamespace(game_dir="godzilla_le",
                               lcd=lambda k: "assets/lcd/auto_loaded/60ed7e5036b8ce09d35a3e101ea6fc1380b37d97")
        data = bytes(r.read_file_bytes(MW.lookup(r, CV.bank_scene(prof))))
    assert CP.bonus_loop(data) == ("EndOfBallBonus_BackgroundLoop", "SquareCrop")
    t = VB.crop_transform(data, "SquareCrop")
    assert abs(t[0] - 1.29) < 0.01 and t[12] == -197.0 and t[13] == -126.0
    assert shutil.which  # (the card's own loop: 8 s, 1360x768 - read in the build by coop_bonus_into)
