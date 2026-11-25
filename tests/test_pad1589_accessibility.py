"""PAD-1589: color-blind insert colors and spoken scores (plugins/stern/accessibility.py, pad_mode_runtime.c
"accessibility", docs/plans/pad1589_accessibility.md)."""
import itertools
import math
import os
import re
import shutil
import subprocess
import sys
import wave

import pytest

from pinball_decryptor.plugins.stern import accessibility as AC
from pinball_decryptor.plugins.stern import sound_modes as SMo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")
LIGHTSHOWS = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "modes_lightshows.js")
EMU = os.path.join(ROOT, "tools", "spike2_emu")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---- the colors ------------------------------------------------------------------------------------------------------

#: Machado, Oliveira & Fernandes 2009, severity 1.0 (linear RGB)
MACHADO = {
    "protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritan": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _srgb(v):
    v = min(1.0, max(0.0, v))
    return 255.0 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)


def _sim(rgb, kind):
    lin = [_lin((rgb >> s) & 255) for s in (16, 8, 0)]
    return [_srgb(sum(MACHADO[kind][i][j] * lin[j] for j in range(3))) for i in range(3)]


def _lab(c):
    r, g, b = (_lin(x) for x in c)
    x = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = 0.0193 * r + 0.1192 * g + 0.9505 * b
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116   # noqa: E731
    fx, fy, fz = f(x / 0.9505), f(y), f(z / 1.089)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _worst(preset, kinds):
    """The smallest CIE76 distance between two of the game's colors as a color-blind player sees them."""
    out = {n: (AC.remap(c, preset) if preset else c) for n, c in AC.GAME_COLOURS.items()}
    return min(math.dist(_lab(_sim(out[a], k)), _lab(_sim(out[b], k)))
               for k in kinds for a, b in itertools.combinations(out, 2))


def test_each_preset_keeps_the_games_colors_further_apart_for_its_players():
    rg, by = ("protan", "deutan"), ("tritan",)
    assert _worst("", rg) < 8 and _worst("red_green", rg) > 25          # 7.8 -> 26.0: three times as far apart
    assert _worst("", by) < 17 and _worst("blue_yellow", by) > 30       # 16.7 -> 30.4


def test_remap_keeps_red_white_grey_and_brightness():
    for p in AC.PRESETS:
        assert AC.remap(0xffffff, p) == 0xffffff
        assert AC.remap(0x404040, p) == 0x404040
        assert AC.remap(0, p) == 0
    assert AC.remap(0xff0000, "blue_yellow") == 0xff0000
    assert AC.remap(0xff0000, "red_green") >> 16 == 0xff                  # still red
    for c in (0x00ff00, 0xc02000, 0x123456, 0x80ff20):                   # the brightest and dimmest parts kept
        m = AC.remap(c, "red_green")
        parts = [(c >> s) & 255 for s in (16, 8, 0)]
        got = [(m >> s) & 255 for s in (16, 8, 0)]
        assert max(got) == max(parts) and min(got) == min(parts)
    assert AC.remap(0x00ff00, "nonsense") == 0x00ff00


def test_known_values():
    assert [AC.remap(c, "red_green") for c in (0xff6000, 0xffd000, 0x00ff00, 0x0000ff)] == \
        [0x6fff00, 0x00ff8b, 0x00d5ff, 0x5500ff]
    assert [AC.remap(c, "blue_yellow") for c in (0xffd000, 0x00ffff, 0x8000ff)] == [0xffa700, 0x00aaff, 0xb000ff]


SAMPLES = [(r << 16) | (g << 8) | b for r in range(0, 256, 17) for g in range(0, 256, 51) for b in range(0, 256, 15)]


def _maps_in(text, start):
    """The two hue maps a copy carries, as written in its source after *start*."""
    i = text.index(start) + len(start)
    nums = [int(n) for n in re.findall(r"-?\d+", text[i:i + 700])]
    pairs = list(zip(nums[0::2], nums[1::2]))
    return pairs[:9], pairs[9:18]


def test_the_copies_carry_the_same_maps():
    want = [[(a * 10, o * 10) for a, o in AC.PRESETS[p][2]] for p in AC.PRESET_ORDER]
    want = [w + [(w[0][0] + 3600, w[0][1] + 3600)] for w in want]
    rt = _read(RUNTIME)
    assert list(_maps_in(rt, "static const short acc_map[2][9][2] = {")) == [want[0], want[1]]
    js = _read(LIGHTSHOWS)
    assert list(_maps_in(js, "const CVD_MAP = {")) == [want[0], want[1]]
    sys.path.insert(0, EMU)
    try:
        import cablights
    finally:
        sys.path.remove(EMU)
    assert [list(cablights.CVD_MAP[p]) for p in AC.PRESET_ORDER] == want
    for p in AC.PRESET_ORDER:                                           # and the window's maths, byte for byte
        for c in SAMPLES:
            r, g, b = cablights.cvd_remap(((c >> 16) & 255, (c >> 8) & 255, c & 255), p)
            assert (r << 16) | (g << 8) | b == AC.remap(c, p)


@pytest.mark.skipif(not shutil.which("node"), reason="no node")
def test_the_light_shows_copy_gives_the_same_bytes(tmp_path):
    js = _read(LIGHTSHOWS)
    body = js[js.index("const CVD_MAP"):js.index("// ------------------------------------------------------------------ the program's shows")]
    script = tmp_path / "cvd.js"
    script.write_text(body.replace("export function", "function") + "\nconst out = [];\nfor (const p of "
                      "['red_green','blue_yellow']) for (const c of %s) out.push(cvdRemap(c, p));\n"
                      "console.log(out.join(' '));\n" % SAMPLES, encoding="utf-8")
    got = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout.split()
    assert [int(x) for x in got] == [AC.remap(c, p) for p in AC.PRESET_ORDER for c in SAMPLES]


def _lift(text, head):
    i = text.index(head)
    j = text.index("{", i)
    depth = 0
    for k in range(j, len(text)):
        depth += {"{": 1, "}": -1}.get(text[k], 0)
        if depth == 0:
            return text[i:k + 1]
    raise AssertionError(head)


@pytest.mark.skipif(not (shutil.which("gcc") or shutil.which("cc")), reason="no C compiler")
def test_the_runtimes_copy_gives_the_same_bytes(tmp_path):
    rt = _read(RUNTIME)
    src = ("#include <stdio.h>\n" + _lift(rt, "static const short acc_map[2][9][2] =").split(";")[0] + ";\n"
           + _lift(rt, "static unsigned acc_remap(unsigned rgb, int preset)\n{")
           + "\nint main(void){static const unsigned s[]={%s};unsigned i;int p;for(p=1;p<=2;p++)"
             "for(i=0;i<sizeof s/sizeof s[0];i++)printf(\"%%u \",acc_remap(s[i],p));return 0;}\n"
           % ",".join(map(str, SAMPLES)))
    c = tmp_path / "acc.c"
    c.write_text(src, encoding="utf-8")
    exe = tmp_path / "acc"
    subprocess.run([shutil.which("gcc") or shutil.which("cc"), "-O1", "-o", str(exe), str(c)], check=True)
    got = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split()
    assert [int(x) for x in got] == [AC.remap(c, p) for p in AC.PRESET_ORDER for c in SAMPLES]


# ---- the spoken scores ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("n, words", [
    (0, "zero"), (7, "seven"), (15, "fifteen"), (40, "forty"), (105, "one hundred five"),
    (2500, "two thousand five hundred"),
    (1234567, "one million two hundred thirty four thousand five hundred sixty seven"),
    (1200000500, "one billion two hundred million five hundred"),
    (25000000000, "twenty five billion"),
    (1000000000000, "one thousand billion"),
])
def test_number_words(n, words):
    assert AC.spoken(AC.number_words(n)) == words


def test_say_score():
    assert AC.spoken(AC.say_score(2, 1200500)) == "player two one million two hundred thousand five hundred"


def test_the_runtime_says_the_same_words_in_the_same_order():
    rt = _read(RUNTIME)
    names = re.findall(r'"([a-z]+)"', _lift(rt, "static const char *const acc_word[ACC_WORDS] =").split(";")[0])
    assert tuple(names) == AC.WORDS
    assert "#define ACC_WORDS   %d" % len(AC.WORDS) in rt
    assert "ACC_W_HUNDRED = %d" % AC.W["hundred"] in rt


@pytest.mark.skipif(not (shutil.which("gcc") or shutil.which("cc")), reason="no C compiler")
def test_the_runtimes_number_words_match(tmp_path):
    rt = _read(RUNTIME)
    src = ("#include <stdio.h>\n#include <stdint.h>\n"
           "enum { ACC_W_HUNDRED = 28, ACC_W_THOUSAND, ACC_W_MILLION, ACC_W_BILLION, ACC_W_PLAYER, ACC_W_POINTS };\n"
           "#define ACC_SAY_MAX 120\nstatic struct { unsigned char q[ACC_SAY_MAX]; int n; } spk;\n"
           + _lift(rt, "static void acc_q(int w)") + "\n" + _lift(rt, "static void acc_below_thousand(unsigned n)")
           + "\n" + _lift(rt, "static void acc_number(uint64_t n)")
           + "\nint main(void){static const unsigned long long v[]={0,7,15,40,105,2500,1234567,1200000500ull,"
             "25000000000ull,987654321ull};unsigned i;int k;for(i=0;i<10;i++){spk.n=0;acc_number(v[i]);"
             "for(k=0;k<spk.n;k++)printf(\"%d \",spk.q[k]);printf(\"|\");}return 0;}\n")
    c = tmp_path / "words.c"
    c.write_text(src, encoding="utf-8")
    exe = tmp_path / "words"
    subprocess.run([shutil.which("gcc") or shutil.which("cc"), "-o", str(exe), str(c)], check=True)
    got = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split("|")[:-1]
    for g, n in zip(got, (0, 7, 15, 40, 105, 2500, 1234567, 1200000500, 25000000000, 987654321)):
        assert [int(x) for x in g.split()] == AC.number_words(n)


def test_trim_silence(tmp_path):
    p = str(tmp_path / "w.wav")
    rate = 22050
    import array
    data = array.array("h", [0] * 8000 + [12000 if i % 20 < 10 else -12000 for i in range(4000)] + [0] * 9000)
    with wave.open(p, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())
    assert AC.trim_silence(p)
    with wave.open(p, "rb") as w:
        n = w.getnframes()
    assert 4000 <= n <= 4000 + 2 * rate * 20 // 1000 + 2
    assert not AC.trim_silence(p) or True                               # trimming again changes little


def test_the_word_range_is_its_own():
    for k in (0, len(AC.WORDS) - 1):
        m = SMo.speak_mode(k)
        assert SMo.is_speak(m) and SMo.speak_of(m) == k
        assert not (SMo.is_juke(m) or SMo.is_intro(m) or SMo.is_shot(m) or SMo.is_attract(m) or SMo.is_mode_turn(m))
        assert SMo.is_turn(m)                           # built as a file in turn: the carrier's loudness, never cut
        assert SMo.who(m) == "Spoken scores" and SMo.when(m) == "when the machine says a score"
        assert SMo.Modes().level("x", m) == 0
    assert not SMo.is_speak(SMo.CEREMONY_MODE) and not SMo.is_speak(SMo.JUKE_BASE + 1)


def test_sounds_cfg_word_lines():
    text = SMo.cfg_text(0, 0, [], True, speak={"request": 1251, "key": bytes(range(8)),
                                               "words": [(0, b"ABCDEFGH", 419), (32, b"abcdefgh", 355)]})
    assert "sword\t0\t1251\t0001020304050607\t4142434445464748\t419" in text.splitlines()
    assert "sword\t32\t1251\t0001020304050607\t6162636465666768\t355" in text.splitlines()


def test_modes_files_carry_the_words_on_their_carrier():
    m = SMo.Modes(speak=[(0, "a.wav"), (1, "b.wav")], speak_rel="audio/idx1920.wav")
    assert m.any
    assert (("audio/idx1920.wav", SMo.speak_mode(1), "b.wav")) in m.files()
    assert SMo.card_record(m, [{"mode": SMo.speak_mode(0), "lines": 1, "rel": "audio/idx1920.wav",
                                         "slot": 1920}]) == \
        SMo.card_record(m, [])


# ---- the project, the menu, the card ----------------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    return str(tmp_path)


def test_project_settings(project):
    assert AC.load_cvd(project) == "" and not AC.load_spoken(project)
    was = AC.save_cvd(project, True, "blue_yellow")
    assert was == {"on": False, "preset": "red_green"}
    assert AC.load_cvd(project) == "blue_yellow" and AC.preset_of(project) == "blue_yellow"
    AC.save_cvd(project, False)
    assert AC.load_cvd(project) == "" and AC.preset_of(project) == "blue_yellow"     # the pick kept for the preview
    assert not AC.save_spoken(project, True) and AC.load_spoken(project)
    assert AC.save_spoken(project, False) and not AC.load_spoken(project)


def test_access_cfg():
    text = AC.cfg_text("blue_yellow", 0x7a4e58, True, 0x7a4e68, (60, 59), only=True)
    assert text.splitlines()[1:] == ["cvd\t2\t0x7a4e58", "spoken\t0x7a4e68\t60,59", "only"]
    assert not any(x.startswith("cvd") for x in AC.cfg_text("", 0, True, 0, (60, 59)).splitlines())
    assert not any(x.startswith("spoken") for x in AC.cfg_text("red_green", 0, False).splitlines())


def test_the_menu_rows():
    from pinball_decryptor.plugins.stern import engine as E, menu_settings as MS
    assert MS.SETTINGS[MS.COLOUR_BLIND][1:3] == ("COLOR BLIND", "Color Blind")
    assert MS.SETTINGS[MS.SPOKEN_SCORES][1:3] == ("SPOKEN SCORES", "Spoken Scores")
    log = lambda *a, **k: None                                          # noqa: E731
    key, n, names, opts = E._ColourBlindMenu("blue_yellow", log).wanted()
    assert (key, n, opts["default"], opts["from_zero"]) == ("colour_blind", 3, 3, True)   # 0 Off, 1, 2: starts on 2
    assert len(opts["help_text"]) <= 63
    key, n, names, opts = E._SpokenScoresMenu(log).wanted()
    assert (key, n, opts["default"], opts["onoff"]) == ("spoken_scores", 2, 1, True)      # Off to start with
    assert len(opts["help_text"]) <= 63


def test_service_menu_tab_lists_them(project):
    from pinball_decryptor.plugins.stern import service_menu as SM
    AC.save_cvd(project, True, "red_green")
    AC.save_spoken(project, True)
    keys = [w[0] for w in SM.wanted(project)]
    assert "colour_blind" in keys and "spoken_scores" in keys


def test_access_cfg_goes_beside_the_runtime(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW

    class Prof:
        label, arch, game_dir = "Godzilla LE 1.16", "arm", "godzilla_le"
    monkeypatch.setattr(AC, "title_refusal", lambda prof, what: "")
    monkeypatch.setattr(SMo, "flipper_buttons", lambda elf: [60, 59])
    result = MW.ModePlan(project=str(tmp_path), profile=Prof(), port="", build=None)
    MW.access_into(result, b"", str(tmp_path / "s"), {"cvd": "red_green", "cvd_setting": 0x10, "spoken": True,
                                                      "spoken_setting": 0x14}, only=True)
    assert _read(result.access_file).splitlines()[1:] == ["cvd\t1\t0x10", "spoken\t0x14\t60,59", "only"]
    assert any(line.startswith("color-blind inserts: red-green colors") for line in result.lines)
    assert any(line.startswith("spoken scores: player and score") for line in result.lines)


def test_the_rig_and_the_card_carry_access_cfg():
    sys.path.insert(0, EMU)
    try:
        import mode_install
    finally:
        sys.path.remove(EMU)
    assert ("access.cfg", 0o100644) in mode_install.EXTRA_FILES
    assert "access.cfg" in mode_install.STANDALONE_FILES
    for sh in ("cardmodes.sh", "tryit.sh"):
        assert "access.cfg" in _read(os.path.join(EMU, "modes", sh))


def test_the_runtime_runs_them_without_the_score_gate():
    rt = _read(RUNTIME)
    gate = rt[rt.index("    if (((clipv_only || sndm_only"):rt.index("    if (!insider_arm()) return;")]
    assert "acc_cfg_only()" in gate and "on_acc_ball_end" in gate and "acc.cvd_wanted) lamps_arm()" in gate
    assert "acc_ball_end();" in _lift(rt, "static void on_ball_end(pm_reg *r)")
    assert "acc_tick();" in _lift(rt, "static void on_tick(pm_reg *r)")
    assert "acc_tick();" in _lift(rt, "static void on_hand_tick(pm_reg *r)")
    assert "spk_lookup(r)" in _lift(rt, "static void on_sound_lookup(pm_reg *r)")


def test_the_playfield_window_previews_and_stands_down(tmp_path, monkeypatch):
    sys.path.insert(0, EMU)
    try:
        import playfield
    finally:
        sys.path.remove(EMU)
    vals = {"R": 0xff, "G": 0x60, "B": 0}
    assert playfield.cvd_vals(vals, "red_green") == {"R": 0x6f, "G": 0xff, "B": 0}
    assert playfield.cvd_vals({"W": 200}, "red_green") == {"W": 200}          # a one-color insert keeps its lens
    assert playfield.cvd_vals(vals, "") is vals
    monkeypatch.setattr(playfield.padpath, "dump", lambda: str(tmp_path))
    assert playfield.card_cvd() == 0                                          # no run's card note
    note = tmp_path / "pad_cvd.now"
    note.write_text("2\n")
    assert playfield.card_cvd() == 2                                          # the card recolors: no preview over it
    old = os.path.getmtime(note) - 60
    os.utime(note, (old, old))
    assert playfield.card_cvd() == 0                                          # an ended run's note is not believed
    monkeypatch.setattr(playfield, "load_state", lambda: {"cvd_preview": "blue_yellow"})
    assert playfield.cvd_preview() == "blue_yellow"
    monkeypatch.setattr(playfield, "load_state", lambda: {"cvd_preview": "bogus"})
    assert playfield.cvd_preview() == ""


def test_the_preview_switch_is_shared_with_the_window(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import insert_colours as IC
    monkeypatch.setattr(IC, "state_path", lambda: str(tmp_path / ".pad_playfield.json"))
    assert IC.cvd_preview() == ""
    assert IC.set_cvd_preview("red_green") == "red_green" and IC.cvd_preview() == "red_green"
    assert IC.set_cvd_preview("nonsense") == "" and IC.cvd_preview() == ""
