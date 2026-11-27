"""PAD-1637: the co-op sounds by MUSIC MODE - DoomWalrus666: "a different audio track assigned for co-op teams: intro
video music, awards ceremony music, character select music ... the flexibility to alter those music selections with
their music mode choices". The intro's sound, the select music, the awards music and each character's sound once
picked can each have a file of their own for music modes 2.. (Characters dialog, By music mode...); the build makes
each a record on the co-op intro's carrier, sounds.cfg names it with its mode, and the runtime plays the file of the
mode the operator's MUSIC MODE says at each play (mode 1's when that mode has none)."""
import os
import wave
from types import SimpleNamespace

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import sound_modes as SM
from tests import test_pad1017_coop_turns as T
from tests import test_spike2_mode_roster as R


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "project"
    p.mkdir()
    return str(p)


def _file(tmp_path, name, data=b"not really a sound"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _chars(project, n=2):
    CP.save(project, True)
    chars = CP.load_characters(project)
    chars["list"] = [{"name": "HERO %d" % (i + 1)} for i in range(n)]
    chars["pick"] = True
    return CP.save_characters(project, chars)


# ---- the project's files -----------------------------------------------------------------------------------------------
def test_each_sound_keeps_a_file_per_music_mode(project, tmp_path):
    _chars(project)
    CP.save_select_sound(project, _file(tmp_path, "theme.wav"))
    CP.save_mode_sound(project, "select", 2, _file(tmp_path, "orchestral.mp3"))
    CP.save_mode_sound(project, "ceremony", 3, _file(tmp_path, "metal.wav"))
    CP.save_mode_sound(project, "intro", 2, _file(tmp_path, "intro2.ogg"))
    chars = CP.save_picked_mode_sound(project, 1, 2, _file(tmp_path, "roar.wav"))
    assert chars["mode_sounds"] == {"select": {"2": "coop/select_sound_mode_2.mp3"},
                                    "ceremony": {"3": "coop/ceremony_sound_mode_3.wav"},
                                    "intro": {"2": "coop/intro_sound_mode_2.ogg"}}
    assert chars["list"][1]["picked_modes"] == {"2": "coop/character_2_picked_sound_mode_2.wav"}
    assert "picked_modes" not in chars["list"][0]
    got = [(k, m, os.path.basename(p)) for k, m, p in CP.mode_sounds(project)]
    assert got == [("intro", 2, "intro_sound_mode_2.ogg"), ("select", 2, "select_sound_mode_2.mp3"),
                   ("ceremony", 3, "ceremony_sound_mode_3.wav"), ("picked2", 2, "character_2_picked_sound_mode_2.wav")]
    assert CP.select_sound_path(project).endswith("select_music.wav")          # mode 1's untouched
    # another file for the same mode replaces it (another extension's goes); None forgets it
    CP.save_mode_sound(project, "select", 2, _file(tmp_path, "orch2.wav"))
    assert sorted(f for f in os.listdir(os.path.join(project, "coop")) if f.startswith("select_sound_mode_2")) == [
        "select_sound_mode_2.wav"]
    chars = CP.save_mode_sound(project, "select", 2, None)
    assert "select" not in chars["mode_sounds"]
    chars = CP.save_picked_mode_sound(project, 1, 2, None)
    assert "picked_modes" not in chars["list"][1]
    assert not os.path.exists(os.path.join(project, "coop", "character_2_picked_sound_mode_2.wav"))


def test_junk_is_refused_and_dropped(project, tmp_path):
    _chars(project)
    with pytest.raises(CP.CoopError):
        CP.save_mode_sound(project, "select", 1, _file(tmp_path, "a.wav"))     # mode 1 is the plain file
    with pytest.raises(CP.CoopError):
        CP.save_mode_sound(project, "select", 9, _file(tmp_path, "a.wav"))
    with pytest.raises(CP.CoopError):
        CP.save_mode_sound(project, "bogus", 2, _file(tmp_path, "a.wav"))
    with pytest.raises(CP.CoopError):
        CP.save_mode_sound(project, "select", 2, _file(tmp_path, "a.txt"))
    with pytest.raises(CP.CoopError):
        CP.save_picked_mode_sound(project, 5, 2, _file(tmp_path, "a.wav"))
    assert CP.clean_mode_files({"1": "x", "2": "y", "9": "z", "q": "w", "3": ""}) == {"2": "y"}
    assert CP._characters({"list": [], "mode_sounds": {"bogus": {"2": "x"}, "select": {"5": "s"}}})["mode_sounds"] == {
        "select": {"5": "s"}}


def test_the_mode_files_alone_keep_the_characters_record(project, tmp_path):
    chars = CP.save_mode_sound(project, "ceremony", 2, _file(tmp_path, "a.wav"))
    assert CP.load_characters(project)["mode_sounds"] == chars["mode_sounds"]


def test_settings_file_carries_the_mode_files(project, tmp_path):
    _chars(project)
    CP.save_mode_sound(project, "select", 2, _file(tmp_path, "o.mp3", b"select 2"))
    CP.save_mode_sound(project, "intro", 4, _file(tmp_path, "i.wav", b"intro 4"))
    CP.save_picked_mode_sound(project, 0, 3, _file(tmp_path, "r.wav", b"roar 3"))
    zpath = str(tmp_path / "coop.zip")
    CP.export_settings(project, zpath)
    other = tmp_path / "other"
    other.mkdir()
    got = CP.import_settings(str(other), zpath)
    assert got["pictures"] == 3
    files = {(k, m): open(p, "rb").read() for k, m, p in CP.mode_sounds(str(other))}
    assert files == {("select", 2): b"select 2", ("intro", 4): b"intro 4", ("picked1", 3): b"roar 3"}


# ---- the music modes' count and the build's records -----------------------------------------------------------------
def test_the_pseudo_modes_round_trip_and_stay_clear_of_the_others():
    seen = set()
    for role in [SM.INTRO_MODE] + [SM.INTRO_MODE + n for n in range(1, SM.PICKED_MAX + 1)] + [SM.CEREMONY_MODE,
                                                                                             SM.SELECT_MODE]:
        assert SM.coop_mode(role, 1) == role
        for m in range(2, SM.MAX_MODES + 1):
            x = SM.coop_mode(role, m)
            assert SM.coop_role(x) == role and SM.coop_music_mode(x) == m and SM.is_intro(x)
            assert not (SM.is_speak(x) or SM.is_juke(x) or SM.is_shot(x) or SM.is_attract(x))
            assert SM.picked_of(x) == SM.picked_of(role) and SM.is_ceremony(x) == SM.is_ceremony(role)
            assert SM.is_select(x) == SM.is_select(role) and SM.Modes().level("r", x) == 0
            seen.add(x)
    assert len(seen) == (SM.MAX_MODES - 1) * (SM.PICKED_MAX + 3)
    assert not SM.is_intro(SM.SPEAK_BASE) and not SM.is_intro(SM.COOP_MM_BASE + SM.PICKED_MAX + 3)
    assert SM._coop_what(SM.coop_mode(SM.SELECT_MODE, 3)) == "the co-op character select's music in music mode 3"
    assert SM.when(SM.coop_mode(SM.CEREMONY_MODE, 2)).endswith(", while MUSIC MODE is 2")


def test_a_co_op_mode_file_gives_the_card_its_music_mode(project, tmp_path):
    assert SM.load(project).count == 0
    CP.save_mode_sound(project, "select", 3, _file(tmp_path, "a.wav"))
    assert SM.load(project).count == 0                  # co-op off: nothing
    CP.save(project, True)
    modes = SM.load(project)
    assert modes.coop_top == 3 and modes.count == 3 and modes.menu_names()[2] == modes.name(3)
    assert "coop_top" not in str(SM.to_json(modes))     # never saved


def test_files_carry_the_mode_files_on_the_intros_carrier():
    modes = SM.Modes()
    modes.intro_rel = "audio/idx1725.wav"
    modes.select = "sel.wav"
    modes.coop_modes = [(SM.SELECT_MODE, 2, "sel2.wav"), (SM.INTRO_MODE + 3, 4, "pick3.wav")]
    files = modes.files()
    assert ("audio/idx1725.wav", SM.SELECT_MODE, "sel.wav") in files
    assert ("audio/idx1725.wav", SM.coop_mode(SM.SELECT_MODE, 2), "sel2.wav") in files
    assert ("audio/idx1725.wav", SM.coop_mode(SM.INTRO_MODE + 3, 4), "pick3.wav") in files
    assert modes.coop and modes.count == 4


def test_sounds_cfg_names_each_mode_file_with_its_mode():
    k, h, g = bytes(8), b"H" * 8, b"G" * 8
    intro = {"request": 979, "key": k, "host": h, "ms": 5000, "picks": [], "ceremony": None, "select": (h, 8000),
             "by_mode": [(SM.SELECT_MODE, 2, g, 6000), (SM.INTRO_MODE, 3, g, 4000), (SM.CEREMONY_MODE, 2, g, 7000),
                         (SM.INTRO_MODE + 2, 4, g, 900)]}
    text = SM.cfg_text(0x1000, 4, [], False, intro=intro).splitlines()
    gx, kx, hx = g.hex(), k.hex(), h.hex()
    assert "cselm\t979\t%s\t%s\t8000" % (kx, hx) in text
    assert "cselm\t979\t%s\t%s\t6000\t2" % (kx, gx) in text
    assert "cintro\t979\t%s\t%s\t4000\t3" % (kx, gx) in text
    assert "ccer\t979\t%s\t%s\t7000\t2" % (kx, gx) in text
    assert "cpick\t2\t979\t%s\t%s\t900\t4" % (kx, gx) in text


def test_the_build_puts_the_mode_files_on_lines_of_their_own():
    from pinball_decryptor.plugins.stern import engine as E
    params = [{"idx": 1725, "findkey": b"K" * 8}, {"idx": 9001, "findkey": b"S" * 8, "grown": True},
              {"idx": 9002, "findkey": b"T" * 8, "grown": True}, {"idx": 9003, "findkey": b"U" * 8, "grown": True}]
    modes = SimpleNamespace(intro_plan={"request": 979, "slot": 1725})
    used = [{"slot": 1725, "host": 9001, "mode": SM.SELECT_MODE, "frames": 44100 * 8},
            {"slot": 1725, "host": 9002, "mode": SM.coop_mode(SM.SELECT_MODE, 2), "frames": 44100 * 6},
            {"slot": 1725, "host": 9003, "mode": SM.coop_mode(SM.INTRO_MODE + 1, 3), "frames": 44100}]
    got = E._intro_lines(params, used, modes, lambda *a, **k: None)
    assert got["select"] == (b"S" * 8, 8000) and got["picks"] == []
    assert got["by_mode"] == [(SM.SELECT_MODE, 2, b"T" * 8, 6000), (SM.INTRO_MODE + 1, 3, b"U" * 8, 1000)]
    only = E._intro_lines(params, used[1:2], modes, lambda *a, **k: None)   # a mode's file with no mode 1 file
    assert only["key"] == b"K" * 8 and only["select"] is None and len(only["by_mode"]) == 1


def _ffmpeg():
    from pinball_decryptor.core.audio import find_ffmpeg
    ff = find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    return ff


def _tone(path, seconds=1):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x10\x00" * int(22050 * seconds))
    return path


def test_the_build_makes_each_mode_file_a_wav_of_its_own(project, tmp_path):
    _ffmpeg()
    from pinball_decryptor.plugins.stern import engine as E
    _chars(project)
    CP.save_select_sound(project, _tone(str(tmp_path / "s.wav")))
    CP.save_mode_sound(project, "select", 2, _tone(str(tmp_path / "s2.wav")))
    CP.save_mode_sound(project, "ceremony", 3, _tone(str(tmp_path / "c3.wav")))
    CP.save_picked_mode_sound(project, 1, 2, _tone(str(tmp_path / "p.wav")))
    logs = []
    plain = E._coop_select_wav(project, lambda *a, **k: logs.append(a))
    got = E._coop_mode_wavs(project, lambda *a, **k: logs.append(a))
    assert [(r, m) for r, m, _p in got] == [(SM.SELECT_MODE, 2), (SM.CEREMONY_MODE, 3), (SM.INTRO_MODE + 2, 2)]
    for _r, _m, p in got:
        assert os.path.basename(p).startswith("coopmm_") and os.path.getsize(p) > 44
    # making the plain one again never removes a mode's, nor a mode's the plain one
    assert E._coop_select_wav(project, lambda *a, **k: None) == plain and os.path.isfile(plain)
    assert all(os.path.isfile(p) for _r, _m, p in E._coop_mode_wavs(project, lambda *a, **k: None))
    assert os.path.isfile(plain)
    # the pick off: the characters' own are left out
    chars = CP.load_characters(project)
    chars["pick"] = False
    CP.save_characters(project, chars)
    assert [(r, m) for r, m, _p in E._coop_mode_wavs(project, lambda *a, **k: None)] == [
        (SM.SELECT_MODE, 2), (SM.CEREMONY_MODE, 3)]


# ---- the runtime ------------------------------------------------------------------------------------------------------
MAIN = r"""
#include <stdio.h>
#include <stdlib.h>
#define SNDM_MODES 8
#define CPK_CHARS 16
enum { CMM_INTRO = 1, CMM_PICK, CMM_CER, CMM_SELM };
static unsigned mode_now = 1;
static unsigned sndm_mode(void) { return mode_now; }
static void say(const char *f, ...) { (void)f; }
static unsigned long number(const char **p, int *ok)
{
    char *e;
    unsigned long v = strtoul(*p, &e, 10);
    *ok = e != *p;
    *p = e;
    return v;
}
@FNS@
static void line(int kind, int n, const char *mds, unsigned char b, unsigned ms)
{
    unsigned char h[8];
    int k, m = cmm_mode_of(mds);
    for (k = 0; k < 8; k++) h[k] = b;
    if (m < 0) { printf("bad %s\n", mds); return; }
    cmm_add(kind, n, m, h, ms);
}
static void use(int kind, int n)
{
    unsigned char h[8] = {0};
    unsigned ms = 0;
    int got = cmm_use(kind, n, h, &ms);
    printf("m%u k%d n%d -> %d %c %u\n", mode_now, kind, n, got, got ? h[0] : '-', ms);
}
int main(void)
{
    line(CMM_SELM, 0, 0, 'A', 8000);          /* mode 1's */
    line(CMM_SELM, 0, "2", 'B', 6000);
    line(CMM_CER, 0, "3", 'C', 7000);         /* only in mode 3 */
    line(CMM_PICK, 2, 0, 'P', 900);
    line(CMM_PICK, 5, "2", 'Q', 800);
    line(CMM_SELM, 0, "9", 'X', 1);           /* not a mode */
    line(CMM_SELM, 0, "x", 'X', 1);
    for (mode_now = 1; mode_now <= 3; mode_now++) {
        use(CMM_SELM, 0);
        use(CMM_CER, 0);
        use(CMM_PICK, 2);
        use(CMM_PICK, 5);
        printf("have m%u %x\n", mode_now, cpk_have_now());
    }
    line(CMM_SELM, 0, "2", 'D', 5000);        /* a line again: replaced, not added */
    mode_now = 2;
    use(CMM_SELM, 0);
    printf("n %d\n", n_cmm);
    return 0;
}
"""


def test_the_runtime_plays_the_file_of_the_mode_now(tmp_path):
    src = T.RUNTIME.read_text(encoding="utf-8")
    start = src.index("#define CMM_MAX")
    end = src.index("static void ci_sound_line(", start)
    out = R._host_run(tmp_path, MAIN.replace("@FNS@", src[start:end])).splitlines()
    assert "bad 9" in out and "bad x" in out
    assert "m1 k4 n0 -> 1 A 8000" in out and "m2 k4 n0 -> 1 B 6000" in out and "m3 k4 n0 -> 1 A 8000" in out
    assert "m1 k3 n0 -> 0 - 0" in out and "m2 k3 n0 -> 0 - 0" in out and "m3 k3 n0 -> 1 C 7000" in out
    assert "m1 k2 n2 -> 1 P 900" in out and "m2 k2 n2 -> 1 P 900" in out
    assert "m1 k2 n5 -> 0 - 0" in out and "m2 k2 n5 -> 1 Q 800" in out
    assert "have m1 2" in out and "have m2 12" in out and "have m3 2" in out
    assert "m2 k4 n0 -> 1 D 5000" in out and "n 5" in out


def test_the_runtime_wiring():
    src = T.RUNTIME.read_text(encoding="utf-8")
    for begin, use, play in (
            ("static void ccer_begin(void)\n{", "cmm_use(CMM_CER, 0, ccer.host, &ccer.sound_ms)", "pm_sound("),
            ("static void cselm_begin(void)\n{", "cmm_use(CMM_SELM, 0, cselm.host, &cselm.sound_ms)", "cselm_play("),
            ("static void ci_sound_start(unsigned long now)\n{", "cmm_use(CMM_INTRO, 0, ci.host, &ci.sound_ms)",
             "pm_sound(")):
        body = R._lift(src, begin)
        assert use in body and body.index(use) < body.index(play)      # the mode's record before the play
    picked = R._lift(src, "static void coop_picked_begin(int c)\n{")
    assert "cmm_use(CMM_PICK, c + 1, cpk.host[c], &cpk.sound_ms[c])" in picked and "cpk_have_now()" in picked
    assert "cpk_have_now()" in R._lift(src, "static int cselm_picked_follows(int c)\n{")
    for name, kind in (("ci", "CMM_INTRO"), ("ccer", "CMM_CER"), ("cselm", "CMM_SELM")):
        body = R._lift(src, "static void %s_sound_line(" % name)
        assert "cmm_mode_of(mds)" in body and "cmm_add(%s, 0, m" % kind in body
    assert "cmm_add(CMM_PICK, (int)n, m" in R._lift(src, "static void cpk_sound_line(")
    for disp in ("ci_sound_line(f[1], f[2], f[3], f[4], n >= 6 ? f[5] : 0)",
                 "ccer_sound_line(f[1], f[2], f[3], f[4], n >= 6 ? f[5] : 0)",
                 "cselm_sound_line(f[1], f[2], f[3], f[4], n >= 6 ? f[5] : 0)",
                 "cpk_sound_line(f[1], f[2], f[3], f[4], f[5], n >= 7 ? f[6] : 0)"):
        assert disp in src


# ---- the dialog -------------------------------------------------------------------------------------------------------
def test_the_dialogs_grid(project, tmp_path):
    from pinball_decryptor.webui.tabs.modes import ModesTab
    _chars(project)
    CP.save_mode_sound(project, "select", 2, _file(tmp_path, "o.mp3"))
    CP.save_picked_mode_sound(project, 0, 3, _file(tmp_path, "r.wav"))
    got = ModesTab._coop_by_mode(None, project, CP.load_characters(project))
    assert [c["m"] for c in got["modes"]] == [2, 3, 4]
    rows = {r["kind"]: r for r in got["rows"]}
    assert "intro" not in rows                           # no intro video: no intro to play a sound over
    assert rows["select"]["files"] == {"2": "select_sound_mode_2.mp3"}
    assert rows["picked1"]["files"] == {"3": "character_1_picked_sound_mode_3.wav"}
    assert rows["picked1"]["label"] == "HERO 1 once picked" and rows["ceremony"]["files"] == {}
    CP.save_intro(project, _file(tmp_path, "intro.mp4"))
    rows = {r["kind"]: r for r in ModesTab._coop_by_mode(None, project, CP.load_characters(project))["rows"]}
    assert rows["intro"]["plain"] == "intro_video.mp4"
