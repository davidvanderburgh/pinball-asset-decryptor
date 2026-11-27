"""PAD-1637 round 2: a game mode's own sounds by MUSIC MODE - DoomWalrus666: "Or any specially assigned audio track in
Custom Modes of any kind". A mode's start sound, shot sound, music (and end call where it rides a carrier) can each have
a file of its own for music modes 2.. (Sounds page, By music mode); each goes on a carrier of its own from the same
allocator, the mode file names it `<key>@<m> <request> ...`, and mode_file.c plays the MUSIC MODE's carriers at each
start (pm_music_mode), the plain lines' where that mode has none."""
import inspect
import os
import pathlib
from types import SimpleNamespace

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import service_menu as SvM
from pinball_decryptor.plugins.stern import sound_modes as SM
from tests import test_spike2_mode_roster as R
from tests.mode_examples import form as MX

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"


def _project(tmp_path, tick=True):
    project = str(tmp_path / "project")
    out = []
    for _name, spec in MX.example_specs()[:2]:
        slug, _s = MP.new_mode(project, spec=spec)
        out.append(slug)
    slug = out[0]
    folder = MP.mode_folder(project, slug)
    spec = MP.load(os.path.join(folder, MP.MODE_FILE))
    for name in ("theme.wav", "theme2.wav", "go3.wav"):
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"RIFF")
    spec.music = "theme.wav"
    MP.set_own_mode_file(spec, "music", 2, "theme2.wav")
    MP.set_own_mode_file(spec, "sound_start", 3, "go3.wav")
    MP.save(project, slug, spec)
    if tick:
        sv = SvM.load(project)
        sv["on"] = sorted(set(sv["on"]) | {"music_mode"})
        SvM.save(project, sv)
    return project, slug, spec


# ---- the mode's files --------------------------------------------------------------------------------------------------
def test_keys_and_files():
    assert MP.alt_key("music", 2) == "music@2" and MP.split_key("music@2") == ("music", 2)
    assert MP.split_key("music") == ("music", 1) and MP.split_key("music@2_sid") == ("music@2_sid", 1)
    assert MP.split_key("call:roar") == ("call:roar", 1)
    spec = MP.ModeSpec()
    MP.set_own_mode_file(spec, "music", 3, "a.wav")
    MP.set_own_mode_file(spec, "sound_start", 2, "b.wav")
    assert MP.own_mode_files(spec) == [("sound_start", 2, "b.wav"), ("music", 3, "a.wav")]
    again = MP.ModeSpec.from_json(spec.to_json())
    assert again.sound_modes == {"music": {"3": "a.wav"}, "sound_start": {"2": "b.wav"}}
    MP.set_own_mode_file(spec, "music", 3, "")
    assert spec.sound_modes == {"sound_start": {"2": "b.wav"}}
    for bad in (("music", 1), ("music", 9), ("bogus", 2)):
        try:
            MP.set_own_mode_file(spec, bad[0], bad[1], "x.wav")
        except MP.ModeProjectError:
            continue
        raise AssertionError(bad)
    spec.sound_modes = {"music": {"1": "x", "q": "y", "2": ""}, "junk": {"2": "z"}}
    assert MP.own_mode_files(spec) == []
    assert MP.own_mode_file_name("music", 2) == "music_music_mode_2.wav"
    assert MW.sound_words("music@2") == "music in music mode 2" and MW.sound_words("music") == "music"


def test_the_mode_file_names_each_music_modes_carrier():
    spec = MP.ModeSpec()
    spec.music, spec.sound_start = "m.wav", "s.wav"
    own = {"music": 125, "music_sid": 618, "sound_start": 900, "music@2": 125, "music@2_sid": 105,
           "sound_start@3": 901, "swaps": [(901, "a" * 16, "b" * 16), (777, "c" * 16, "d" * 16)]}
    lines = MP.own_sound_lines(spec, own, {"sound_start": 1200, "sound_start@3": 800})
    assert "music@2 125 105" in lines and "sound_start@3 901 800" in lines
    assert lines.index("music          125 618") < lines.index("music@2 125 105")
    assert "swap           901 %s %s" % ("a" * 16, "b" * 16) in lines          # the alt's carrier is carried
    assert not [ln for ln in lines if " 777 " in ln]


# ---- the build: carriers of their own ---------------------------------------------------------------------------------
def test_each_music_modes_file_gets_a_carrier_of_its_own(tmp_path):
    project, slug, _spec = _project(tmp_path)
    said = []
    own = MW.choose_own_sounds(project, MW.project_modes(project), (True, ""), log=lambda m, l="info": said.append(m))
    mine = {o["key"]: o for o in own if o["slug"] == slug}
    assert set(mine) == {"music", "music@2", "sound_start@3"}
    assert mine["music@2"]["music"] and not mine["sound_start@3"]["music"]
    assert mine["music@2"]["wav"].endswith("theme2.wav") and mine["sound_start@3"]["wav"].endswith("go3.wav")
    if mine["music"].get("sid"):                        # a title with beds: each its own bed on the one carrier
        assert mine["music@2"]["request"] == mine["music"]["request"]
        assert mine["music@2"]["sid"] != mine["music"]["sid"]
    requests, ms = MW.own_cfg_args(project, slug, None, [dict(o, ms=700 if not o["music"] else None) for o in own])
    assert requests["music@2"] == mine["music@2"]["request"] and requests["sound_start@3"]
    if mine["music"].get("sid"):
        assert requests["music@2_sid"] == mine["music@2"]["sid"] and requests["music_sid"] == mine["music"]["sid"]
    assert ms == {"sound_start@3": 700}


def test_music_mode_unticked_leaves_them_out(tmp_path):
    project, slug, _spec = _project(tmp_path, tick=False)
    said = []
    own = MW.choose_own_sounds(project, MW.project_modes(project), (True, ""), log=lambda m, l="info": said.append(m))
    assert {o["key"] for o in own if o["slug"] == slug} == {"music"}
    assert any("MUSIC MODE is not ticked" in m for m in said)


def test_the_card_gets_its_music_mode_setting(tmp_path):
    project, _slug, _spec = _project(tmp_path)
    modes = SM.load(project)
    assert modes.own_top == 3 and modes.count == 3
    assert "own_top" not in str(SM.to_json(modes))
    from pinball_decryptor.plugins.stern import engine as E
    src = inspect.getsource(E)
    assert 'sound_modes.own_mm = any(_MW_split_key(u.get("key"))[1] > 1 for u in mode_own_used or ())' in src
    assert "if sound_mode_used or (sound_modes is not None and sound_modes.own_mm):" in src
    cfg = inspect.getsource(E._sound_modes_cfg)
    assert 'bool(getattr(modes, "own_mm", False))' in cfg and "and not intro and not speak and not coop_mm:" in cfg


# ---- the runtime ------------------------------------------------------------------------------------------------------
MAIN = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdarg.h>
static unsigned mode_now = 1;
unsigned pm_music_mode(void) { return mode_now; }
static void pm_log(const char *f, ...) { (void)f; }
static int is_space(char c) { return c == ' ' || c == '\t'; }
@NUM@
@STRUCT@
@FNS@
static void show(struct own_sounds *S)
{
    own_sounds_music_mode(S);
    printf("m%u start %u/%u shot %u/%u/%u music %u/%u\n", mode_now, S->start, S->start_ms, S->shot, S->shot_every,
           S->shot_ms, S->music, S->music_sid);
}
int main(void)
{
    static struct own_sounds S;
    S.start = 900; S.start_ms = 1200; S.shot = 901; S.shot_every = 2; S.shot_ms = 300; S.music = 125; S.music_sid = 618;
    printf("alt %d %d %d %d\n", own_sounds_alt(&S, "music@2 125 105"), own_sounds_alt(&S, "sound_start@3 950 800"),
           own_sounds_alt(&S, "sound_shot@2 960 0 400"), own_sounds_alt(&S, "music 125 618"));
    own_sounds_alt(&S, "music@1 5 5");                  /* not a music mode of its own: ignored */
    printf("n %u\n", S.n_alt);
    for (mode_now = 1; mode_now <= 3; mode_now++) show(&S);
    mode_now = 1;
    show(&S);
    return 0;
}
"""


def test_the_runtime_takes_the_music_modes_carriers(tmp_path):
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    start = src.index("struct own_sounds {")
    struct = src[start:src.index("};", start) + 2]
    fns = R._lift(src, "static int own_sounds_alt(struct own_sounds *S, const char *line)") + "\n" + R._lift(
        src, "static void own_sounds_music_mode(struct own_sounds *S)")
    num = R._lift(src, "static int hexval(int c)") + "\n" + R._lift(src, "static uint64_t num(const char **p)")
    out = R._host_run(tmp_path, MAIN.replace("@NUM@", num).replace("@STRUCT@", struct).replace("@FNS@", fns))
    out = out.splitlines()
    assert "alt 1 1 1 0" in out and "n 3" in out
    assert out.count("m1 start 900/1200 shot 901/2/300 music 125/618") == 2       # mode 1: the plain lines, again
    assert "m2 start 900/1200 shot 960/2/400 music 125/105" in out                 # its own music bed and shot call
    assert "m3 start 950/800 shot 901/2/300 music 125/618" in out


def test_the_runtime_wiring():
    mf = (SDK / "mode_file.c").read_text(encoding="utf-8")
    key = R._lift(mf, "static int own_sounds_key(struct slot *M, const char *line)")
    assert key.index("own_sounds_alt(S, line)") < key.index('key_is(line, "music")')
    start = R._lift(mf, "static void own_sounds_start(struct slot *M)")
    assert start.index("own_sounds_music_mode(S);") < start.index("own_sounds_priorities(S);")
    clear = R._lift(mf, "static void own_sounds_clear(struct slot *M)")
    assert "S->n_alt = 0;" in clear and "S->based = 0;" in clear
    assert "unsigned pm_music_mode(void);" in (SDK / "pad_mode.h").read_text(encoding="utf-8")
    rt = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    assert "unsigned pm_music_mode(void)\n{\n    return sndm_mode();\n}" in rt.replace("\r\n", "\n")


# ---- the Sounds page ---------------------------------------------------------------------------------------------------
def test_the_sounds_pages_grid(tmp_path):
    from pinball_decryptor.webui.tabs.modes import ModesTab
    project, slug, spec = _project(tmp_path)
    prof = MP.profile(spec.title)
    me = SimpleNamespace(_open_project=project, _shown=None, _profile=prof,
                         _OWN_MODE_WORDS=ModesTab._OWN_MODE_WORDS)
    got = ModesTab._own_modes_state(me, spec, MP.mode_folder(project, slug))
    assert [c["m"] for c in got["modes"]] == [2, 3, 4] and got["off"] == ""
    rows = {r["key"]: r for r in got["rows"]}
    assert rows["music"]["files"] == {"2": "theme2.wav"} and rows["music"]["plain"] == "theme.wav"
    assert rows["sound_start"]["files"] == {"3": "go3.wav"} and rows["sound_shot"]["files"] == {}
    assert ("sound_end" in rows) == MW.end_on_carrier(prof)
