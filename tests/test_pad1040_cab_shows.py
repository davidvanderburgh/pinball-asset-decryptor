"""PAD-1040: the cabinet's expression light shows - the blades and speaker lights, a show of the card's own tied to a
song (BEN: "if songs are swapped out, the expression lighting is no longer in sync with the replaced audio track").

Here: the port's `cablamp` lines (lampmap.cabinet: which lamps, their places on the cabinet drawing and along their
strips), the sidecar's shows and ``cabshow.cfg`` (cab_shows), the patterns' names agreeing in the runtime, the app and
the preview, and the preview's arithmetic (webui/static/js/tabs/cabfx.js) agreeing with the runtime's "CAB FX" slice
colour for colour (node + a host C compiler)."""

import json
import os
import re
import subprocess

from pinball_decryptor.plugins.stern import cab_shows as CS, lampmap as LM
from tests import test_stern_block_modes as T
from tests.test_pad646_light_shows import _node_run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
JS = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "cabfx.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _table(blade_names, speaker_names, extra=()):
    """A light/lamp table as lampmap.find_tables gives it: each name an RGB lamp of three lights."""
    lights, lamps = [None], []
    for n, name in enumerate(list(blade_names) + list(speaker_names) + list(extra)):
        ids = []
        for c in "RGB":
            lights.append({"name": "%s-%s" % (name, c), "group": 1, "index": len(lights), "cls": 3, "image": "",
                           "x": 0, "y": 0})
            ids.append(len(lights) - 1)
        lamps.append({"lamp": n + 1, "kind": 2, "lights": ids})
    return {"lights": lights, "lamps": lamps}


def test_the_blades_and_speakers_are_cabinet_lights_and_nothing_else_is():
    assert LM.cabinet_role("EXPRESSIVE LIGHTING L 3") == ("blade", "L", 3)
    assert LM.cabinet_role("EXPRESSIVE LIGHTING 50") == ("blade", "", 50)          # King Kong names no side
    assert LM.cabinet_role("SPEAKER 23") == ("speaker", "", 23)
    assert LM.cabinet_role("LEFT SPEAKER 2") == ("speaker", "L", 2)                # Batman 66
    for name in ("LEFT RAMP", "SPEAKER LOGO", "TOPPER GI 1", "LEFT SPEAKER LOGO", "BACKBOX GI"):
        assert LM.cabinet_role(name) is None, name


def test_each_cabinet_light_has_its_place_on_the_drawing_and_along_its_strip():
    blades = ["EXPRESSIVE LIGHTING L %d" % n for n in range(1, 49)] + \
             ["EXPRESSIVE LIGHTING R %d" % n for n in range(49, 97)]
    t = _table(blades, ["SPEAKER %d" % n for n in range(1, 24)], extra=["LEFT RAMP"])
    cab = LM.cabinet(None, t)
    assert len(cab) == 96 + 23 and all(c["name"] != "LEFT RAMP" for c in cab)
    by = {c["name"]: c for c in cab}
    l1, l48, r49 = by["EXPRESSIVE LIGHTING L 1"], by["EXPRESSIVE LIGHTING L 48"], by["EXPRESSIVE LIGHTING R 49"]
    assert (l1["x"], r49["x"]) == (LM.CAB_BLADE_X["L"], LM.CAB_BLADE_X["R"])
    assert l1["y"] > l48["y"] >= LM.CAB_BLADE_TOP and l1["u"] < 30 and l48["u"] > 970      # pixel 1 at the bottom
    assert l1["lights"] == sorted(l1["lights"])                                        # R, G, B in that order
    s1, s12 = by["SPEAKER 1"], by["SPEAKER 12"]
    assert s1["y"] < LM.CAB_BLADE_TOP and s1["y"] < s12["y"] and s1["u"] < s12["u"]   # the ring, from the top round
    line = LM.cabinet_line(l1)
    assert line.split()[:3] == ["cablamp", ",".join(map(str, l1["lights"])), str(l1["u"])]
    assert "at %d,%d" % (l1["x"], l1["y"]) in line and line.endswith("blade L")


def test_a_title_that_names_no_side_splits_its_blades_at_the_middle():
    t = _table(["EXPRESSIVE LIGHTING %d" % n for n in range(1, 97)], [])
    cab = LM.cabinet(None, t)
    assert {c["side"] for c in cab if c["n"] <= 48} == {"L"} and {c["side"] for c in cab if c["n"] > 48} == {"R"}


def test_the_patterns_are_named_alike_in_the_runtime_the_app_and_the_preview():
    rt = _read(os.path.join(SDK, "pad_mode_runtime.c"))
    names = re.search(r"CX_NAMES\[CX_N\] = \{(.*?)\};", rt, re.S).group(1)
    c_names = re.findall(r'"([a-z_]+)"', names)
    js_names = re.findall(r'"([a-z_]+)"', re.search(r"CX_NAMES = \[(.*?)\];", _read(JS), re.S).group(1))
    assert c_names == list(CS.FX) == js_names


def test_shows_normalize_and_write_the_runtimes_file():
    raw = {"shows": [{"name": "  Kashmir  ", "slot": 384, "loop": 1,
                      "blades": [{"fx": "sweep_up", "ms": 3000, "a": "#FF0000", "b": "#000010", "rate": 5,
                                  "blend": 9999}, {"fx": "nope", "ms": 1}],
                      "speakers": "not a list"},
                     {"name": "No song", "slot": None, "blades": [{"fx": "solid"}]},
                     "junk"]}
    shows = CS.norm(raw)["shows"]
    assert [s["name"] for s in shows] == ["Kashmir", "No song"]
    k = shows[0]
    assert k["loop"] is True and k["speakers"] == []
    assert k["blades"][0] == {"fx": "sweep_up", "ms": 3000, "a": "#FF0000", "b": "#000010", "rate": 5, "blend": 3000}
    assert k["blades"][1]["fx"] == "solid" and k["blades"][1]["ms"] == CS.STEP_MS_MIN
    assert CS.problems(shows[1]) == ["It plays with no song: pick the song it goes with."]
    plays = {77: [384, 385], 78: [384], 79: [385, 384], 80: [None]}
    assert CS.sids_for_slot(plays, 384) == [77, 78]
    text, skipped = CS.cfg_text(shows, {384: CS.sids_for_slot(plays, 384)}, only=True)
    lines = text.splitlines()
    assert lines[1] == "only" and skipped == ["No song"]
    assert lines[2] == "show 77,78 1 Kashmir"
    assert lines[3] == "blades sweep_up 3000 0xff0000 0x000010 5 3000"
    assert CS.length_ms(k) == 3000 + CS.STEP_MS_MIN


def test_every_preset_is_a_show_the_runtime_takes():
    for key, _label, _loop, _b, _s in CS.PRESETS:
        s = CS.norm_show(CS.preset(key))
        assert all(st["fx"] in CS.FX for lane in CS.LANES for st in s[lane])
        assert len(s["blades"]) <= CS.STEPS_MAX


# ---- the preview against the runtime, colour for colour -------------------------------------------------------
_LIGHTS = [(-1, 0, 0), (-1, 10, 1), (-1, 499, 2), (-1, 989, 3), (1, 10, 48), (1, 500, 60), (1, 999, 95),
           (0, 21, 96), (0, 500, 107), (0, 978, 118)]
_TIMES = [0, 1, 37, 150, 299, 300, 500, 777, 999, 1000, 2500]


def _slice(rt):
    return rt[rt.index("/* ---- CAB FX BEGIN"):rt.index("/* ---- CAB FX END */")]


def _c_driver():
    steps = ",\n".join("    { %d, 1000, 0xff8040u, 0x102030u, 130, 300 }" % i for i in range(len(CS.FX)))
    return "\n".join([
        "#include <stdio.h>",
        _slice(_read(os.path.join(SDK, "pad_mode_runtime.c"))),
        "static const struct cx_step STEPS[] = {\n%s\n};" % steps,
        "static const struct cx_step PREV = { CX_RAINBOW, 700, 0x20ff80u, 0x000000u, 90, 0 };",
        "int main(void) {",
        "    static const int L[][3] = { %s };" % ", ".join("{ %d, %d, %d }" % x for x in _LIGHTS),
        "    static const unsigned times[] = { %s };" % ", ".join(str(t) for t in _TIMES),
        "    unsigned s, t, k;",
        "    for (s = 0; s < sizeof(STEPS) / sizeof(STEPS[0]); s++)",
        "        for (t = 0; t < sizeof(times) / sizeof(times[0]); t++)",
        "            for (k = 0; k < sizeof(L) / sizeof(L[0]); k++) {",
        "                printf(\"%06x\\n\", cx_blend(&STEPS[s], &PREV, L[k][0], (unsigned)L[k][1], (unsigned)L[k][2], times[t]));",
        "                printf(\"%06x\\n\", cx_colour(&STEPS[s], L[k][0], (unsigned)L[k][1], (unsigned)L[k][2], times[t] * 7u));",
        "            }",
        "    return 0;",
        "}", ""])


def _js_driver():
    src = _read(JS).replace("export ", "")
    return "\n".join([
        src,
        "const L = %s, TIMES = %s, N = %d;" % (json.dumps(_LIGHTS), json.dumps(_TIMES), len(CS.FX)),
        "const prev = { fx: 16, ms: 700, a: 0x20ff80, b: 0, rate: 90, blend: 0 };",
        "const out = [];",
        "for (let s = 0; s < N; s++) { const st = { fx: s, ms: 1000, a: 0xff8040, b: 0x102030, rate: 130, blend: 300 };",
        "  for (const t of TIMES) for (const [side, u, k] of L) {",
        "    out.push(cxBlend(st, prev, side, u, k, t).toString(16).padStart(6, '0'));",
        "    out.push(cxColour(st, side, u, k, t * 7).toString(16).padStart(6, '0')); } }",
        "console.log(out.join('\\n'));", ""])


def test_the_preview_paints_every_cabinet_light_the_colour_the_runtime_paints(tmp_path):
    cc = T._cc()
    (tmp_path / "cx.c").write_text(_c_driver(), encoding="utf-8")
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-function", "-Wno-unused-const-variable",
                        "-o", str(tmp_path / "cx"), str(tmp_path / "cx.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    want = subprocess.run([str(tmp_path / "cx")], capture_output=True, text=True, check=True).stdout.split()
    got = _node_run(tmp_path, _js_driver())
    n = 2 * len(CS.FX) * len(_TIMES) * len(_LIGHTS)
    assert len(want) == n and len(got) == n
    bad = [(i // (2 * len(_TIMES) * len(_LIGHTS)), w, g) for i, (w, g) in enumerate(zip(want, got)) if w != g]
    assert not bad, bad[:10]
    assert len(set(want)) > 150                            # the patterns paint, not one colour over and over


def test_the_runtime_reads_cablamp_lines_and_cabshow_cfg():
    rt = _read(os.path.join(SDK, "pad_mode_runtime.c"))
    assert 'if (str_eq(key, "cablamp")) { cab_line(s); return; }' in rt
    assert '"/usr/local/padmode/cabshow.cfg", "/dump/cabshow.cfg"' in rt
    assert "if (cabs_live) cabs_worker(r[0]);" in rt                 # the sound worker says which request started
    assert "cabs_tick();" in rt.split("static void on_tick(unsigned *r)")[1].split("\n}\n")[0]
    hdr = _read(os.path.join(SDK, "pad_mode.h"))
    for fn in ("pm_cab_count", "pm_cab_at", "pm_cab_xy", "pm_cab_paint", "pm_cab_release_all", "pm_cab_show",
               "pm_cab_show_stop", "pm_lamp_release_inserts"):
        assert fn + "(" in hdr and fn + "(" in rt, fn


# ---- the card build ------------------------------------------------------------------------------------------
def test_a_title_with_cabinet_lights_can_have_shows_and_one_without_cannot():
    from pinball_decryptor.plugins.stern import mode_project as MP
    lz = MP.read_port(os.path.join(SDK, "ports", "led_zeppelin_le-1.22.port"))
    assert len(lz["cablamp"]) == 96 + 23 and not [n for n, _ids, _m in lz["lamp"] if LM.cabinet_role(n)]
    assert CS.port_refusal(lz, "Led Zeppelin LE 1.22") == "" and CS.plays_with_songs(lz)
    beatles = MP.read_port(os.path.join(SDK, "ports", "beatles-1.29.port"))
    assert "no blades or speaker lights" in CS.port_refusal(beatles, "The Beatles 1.29")


def test_the_build_puts_cabshow_cfg_beside_the_runtime(tmp_path):
    from types import SimpleNamespace
    from pinball_decryptor.plugins.stern import mode_write as MW
    shows = CS.norm({"shows": [{"name": "Kashmir", "slot": 384, "blades": [{"fx": "pulse", "ms": 500}]},
                               {"name": "Nothing", "slot": 9, "blades": [{"fx": "solid"}]}]})["shows"]
    said = []
    result = SimpleNamespace(profile=object(), cabshow_file="", lines=[])
    orig = CS.title_refusal
    CS.title_refusal = lambda prof: ""
    try:
        MW.cabs_into(result, str(tmp_path), shows, {384: [77]}, only=True, log=lambda *a: said.append(a[0]))
    finally:
        CS.title_refusal = orig
    text = open(result.cabshow_file, encoding="utf-8").read().splitlines()
    assert text[1:4] == ["only", "show 77 0 Kashmir", "blades pulse 500 0xffffff 0x000000 0 0"]
    assert any("Nothing" in w for w in said) and result.lines == ["expression lights: 1 show(s), each played with its song"]


def test_cabshow_cfg_is_a_file_the_install_carries():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mode_install", os.path.join(ROOT, "tools", "spike2_emu", "mode_install.py"))
    mi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mi)
    assert CS.CFG_NAME in dict(mi.EXTRA_FILES) and CS.CFG_NAME in mi.STANDALONE_FILES
    for sh in ("tryit.sh", "cardmodes.sh"):
        assert "cabshow.cfg" in _read(os.path.join(ROOT, "tools", "spike2_emu", "modes", sh)), sh


# ---- a show made from the song ---------------------------------------------------------------------------------
def _click_track(path, bpm, bars=(16, 16), sr=44100, intro=1.3):
    import wave
    import numpy as np
    beat = 60.0 / bpm
    x = np.zeros(int((intro + sum(bars) * 4 * beat + 2) * sr), np.float32)
    t, k = intro, 0
    for sec, nb in enumerate(bars):
        amp = 0.15 if sec == 0 else 0.8
        for _ in range(nb * 4):
            i, n = int(t * sr), int(0.08 * sr)
            env = np.exp(-np.arange(n) / (0.015 * sr)) * (1.0 if k % 4 == 0 else 0.6)
            x[i:i + n] += amp * env * (np.sin(2 * np.pi * 60 * np.arange(n) / sr)
                                      + 0.3 * np.random.RandomState(k).randn(n))
            t += beat
            k += 1
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32000).astype("<i2").tobytes())


def test_a_show_made_from_a_song_follows_its_beat_bars_and_loud_part(tmp_path):
    from pinball_decryptor.plugins.stern import cab_auto as CA
    for bpm in (96, 128, 150):
        path = str(tmp_path / ("click%d.wav" % bpm))
        _click_track(path, bpm)
        info = CA.analyse(path)
        assert abs(info["bpm"] - bpm) < 0.5, info["bpm"]
        period = 60000.0 / bpm
        clicks = [1300 + j * period for j in range(32 * 4)]
        inside = [b for b in info["beats"] if 1200 < b < clicks[-1] + 100]
        assert len(inside) == len(clicks)
        assert max(abs(b - min(clicks, key=lambda c: abs(c - b))) for b in inside) < 15      # ms
        assert all(round(((b - 1300) / period) % 4) % 4 == 0 for b in info["bars"] if b > 1200)  # the downbeats
        loud = [s for s in info["sections"] if s["kind"] == "loud"]
        assert loud and abs(loud[0]["start"] - clicks[64]) < 100          # the loud half, from its first bar
        show, _ = CA.make(path, "punchy", name="Click", slot=7, info=info)
        for lane in CS.LANES:
            assert sum(st["ms"] for st in show[lane]) == info["length_ms"]
            assert len(show[lane]) <= CS.STEPS_MAX
        bars = set(info["bars"])
        at, starts = 0, []
        for st in show["blades"]:
            starts.append(at)
            at += st["ms"]
        on_bar = [a for a in starts[1:] if a in bars or any(abs(a - b) <= 1 for b in bars)]
        assert len(on_bar) >= len(starts) - 3                               # every step but the ends on a bar line
        assert show["blades"][0]["fx"] == "fade_in" and show["blades"][-1]["fx"] == "fade_out"
        assert CS.norm_show(show) == show


def test_every_style_makes_a_show_the_runtime_takes(tmp_path):
    from pinball_decryptor.plugins.stern import cab_auto as CA
    path = str(tmp_path / "click.wav")
    _click_track(path, 120, bars=(4, 8, 4))
    info = CA.analyse(path)
    for style in CA.STYLES:
        show, _ = CA.make(path, style, info=info)
        text, skipped = CS.cfg_text([dict(show, slot=1)], {1: [5]}, only=False)
        assert not skipped and text.count("\nblades ") == len(show["blades"])


def test_the_tab_is_in_the_rail_for_spike_2_and_not_behind_the_mode_makers_preview():
    from pinball_decryptor.webui.tabs import TABS
    assert ("lights", "lights", "Expression Lights", "Expression lights", "Make", "lights") in TABS
    win = _read(os.path.join(ROOT, "pinball_decryptor", "webui", "window.py"))
    assert '"Expression Lights": g("modes"),' in win
    eng = _read(os.path.join(ROOT, "pinball_decryptor", "plugins", "stern", "engine.py"))
    gate = eng[eng.index("def _cabs_for_build"):eng.index("def _cab_sids_for_build")]
    assert "preview_on" not in gate
