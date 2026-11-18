"""PAD-1405: a mode's bar meters (value/max, colour, label, up to four) and its screen fade (the whole glass to a colour,
flat or as an edge glow), in blocks, the build and the SDK kit - on every title that takes a mode's screens.

Emulator-proven on Uncanny X-Men LE and Pro 0.98 (C:/tmp/PAD-1405: build_set.py, job.sh): three meters found with 20
levels each and three fades with 16 steps, the meters following their values, the black fade with a red edge glow
and back, a red tint at once, everything gone at its end.
"""
import json
import os
import shutil
import struct
import subprocess

import numpy as np
import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import mode_assets as MA
from pinball_decryptor.plugins.stern import mode_meters as MM
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import scene_write as SW
from tests.test_stern_scene_write import _art, _fake_scene

SDK = os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu", "modes", "sdk")
PORTS = os.path.join(SDK, "ports")
num = lambda v: {"k": "num", "v": v}          # noqa: E731
var = lambda n: {"k": "var", "name": n}       # noqa: E731


def _prog(meters=True, fades=True):
    blast = [{"op": "fade", "color": "#000000", "style": "flat", "to": num(80), "ms": num(1500)},
             {"op": "fade", "color": "#FF0000", "style": "glow", "to": num(100), "ms": num(1500)}] if fades else []
    back = [{"op": "fade", "color": "#000000", "style": "flat", "to": num(0), "ms": num(600)},
            {"op": "fade", "color": "#ff0000", "style": "glow", "to": num(0), "ms": num(600)}] if fades else []
    p = {"name": "OPTIC", "seconds": 40, "screen": False,
         "vars": [{"name": "hp", "reset": "mode"}, {"name": "energy", "reset": "mode"}],
         "scripts": [
             {"hat": {"kind": "mode_start"}, "do": [{"op": "set", "var": "hp", "value": num(5)}]},
             {"hat": {"kind": "every", "seconds": 2}, "do": [
                 {"op": "change", "var": "energy", "by": num(25)},
                 {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": var("energy"), "b": num(100)},
                  "then": blast, "else": back}]}]}
    if meters:
        p["meters"] = [{"label": "CYCLOPS", "color": "#e02020", "value": var("hp"), "max": num(5), "numbers": True},
                       {"label": "ENERGY", "color": "#20b0ff", "value": var("energy")},
                       {"label": "TIME", "color": "#ffcc00", "value": {"k": "secs_left"}, "max": num(40)}]
    return p


# ---- the program ----------------------------------------------------------------------------------------------------
def test_meters_are_normalized_with_a_most_of_100_and_a_colour_and_at_most_four():
    p = BM.normalize({"meters": [{"label": " energy ", "color": "red", "value": var("x")}] * 6})
    assert len(p["meters"]) == BM.METERS_MAX == MM.METERS_MAX == 4
    m = p["meters"][0]
    assert m == {"label": "energy", "color": BM.METER_COLOR, "value": var("x"), "max": num(100), "numbers": False,
                 "at": None}
    assert BM.normalize({})["meters"] == []
    # an emptied slot stays empty and is named
    p = BM.normalize({"meters": [{"label": "A", "value": None, "max": None}]})
    out = BM.problems(p)
    assert any("Meter 1 (A)" in s for s in out) and any("Meter 1's most" in s for s in out)


def test_fade_layers_are_one_per_colour_and_look_in_first_use_order_and_three_at_most():
    p = BM.normalize(_prog())
    assert BM.fade_layers(p) == [{"color": "#000000", "style": "flat"}, {"color": "#ff0000", "style": "glow"}]
    assert BM.problems(p) == []
    many = BM.normalize(_prog())
    many["scripts"].append({"hat": {"kind": "mode_end"}, "do": [
        {"op": "fade", "color": c, "style": "flat", "to": num(10), "ms": num(0)} for c in ("#111111", "#222222")]})
    assert len(BM.fade_layers(many)) == 4
    assert any("more than 3 colours" in s for s in BM.problems(many))
    bad = BM.normalize(_prog())
    bad["scripts"][1]["do"][1]["then"][0]["to"] = None
    assert BM.problems(bad)


def test_the_c_drives_the_kits_meters_and_fades():
    c = BM.to_c(_prog(), "optic")
    assert '#include "intricate_kit.h"' in c
    assert ('static struct kit_meter meter[3] = {{ .scene = "hud", .node = "PadMode_optic_Meter1" }, '
            '{ .scene = "hud", .node = "PadMode_optic_Meter2" }, { .scene = "hud", .node = "PadMode_optic_Meter3" }};') in c
    assert 'static struct kit_fade fade[2] = {{ .scene = "hud", .node = "PadMode_optic_Fade1" }' in c
    assert "kit_fade_to(&fade[0], (int)((80LL)), (int)((1500LL)));" in c
    assert "kit_fade_to(&fade[1], (int)((100LL)), (int)((1500LL)));" in c        # #FF0000 is #ff0000's layer
    assert 'pm_snprintf(w, sizeof w, "CYCLOPS %s/%s", a, b);' in c and "kit_meter_set(&meter[1], v, most, 0);" in c
    for k in range(3):
        assert "kit_meter_tick(&meter[%d]);" % k in c
    assert "kit_fade_tick(&fade[1]);" in c
    assert "meters_show(0);" in c and "fades_off();" in c
    assert "if (run.on) meters_show(!under_layer && !pm_display_covered() && !pm_aside());" in c


def test_a_mode_without_them_has_none_of_it_and_no_kit():
    c = BM.to_c(_prog(meters=False, fades=False), "plain")
    assert "kit_meter" not in c and "kit_fade" not in c and "intricate_kit.h" not in c
    only = BM.normalize(_prog(meters=False))
    assert BM.uses_kit(only) and "intricate_kit.h" in BM.to_c(only, "only")


def test_the_assets_carry_what_the_build_needs(tmp_path):
    project = str(tmp_path / "X-Men LE 0.98 Extract")
    os.makedirs(project)
    card = "uncanny_xmen_le-0_98_0.Release.16G.sdcard.raw"
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    slug, _path = BM.new_blocks_mode(project, "OPTIC", example="ramps")
    p = BM.load(project, slug)
    p.update({k: v for k, v in _prog().items() if k in ("meters", "scripts", "vars")})
    BM.save(project, slug, p)
    spec = CM.load(project, slug)
    assert spec.meters == [{"label": "CYCLOPS", "color": "#e02020", "at": None},
                           {"label": "ENERGY", "color": "#20b0ff", "at": None},
                           {"label": "TIME", "color": "#ffcc00", "at": None}]
    assert spec.fades == [{"color": "#000000", "style": "flat"}, {"color": "#ff0000", "style": "glow"}]
    assert os.path.isfile(os.path.join(MP.mode_folder(project, slug), BM.KIT_FILE))
    # the build puts the fades first (under every screen of the modes') and then the meters
    prof = MP.profile_from_port(os.path.join(PORTS, "uncanny_xmen_le-0.98.port"))
    assert prof.can("screen")
    names = [s["name"] for s in MA._code_screens(project, [(slug, spec)], prof)]
    st = MM.stem(slug)
    assert names[:5] == [st + "_Fade1", st + "_Fade2", st + "_Meter1", st + "_Meter2", st + "_Meter3"]


# ---- the pictures ---------------------------------------------------------------------------------------------------
def test_a_meters_screen_has_its_label_and_a_picture_a_level_premultiplied():
    (s,) = MM.meter_screens("optic", [{"label": "ENERGY", "color": "#20b0ff"}])
    assert s["name"] == "PadMode_optic_Meter1" and s["words"] == "ENERGY"
    assert s["words_name"] == "PadMode_optic_Meter1_Words"
    assert [lay["name"] for lay in s["layers"]] == ["PadMode_optic_Meter1_L%d" % j for j in range(1, 21)]
    assert (s["x"], s["y"]) == MM.METER_AT_DEFAULT
    for lay in [s["art_rgba"]] + [lay["rgba"] for lay in s["layers"]]:
        assert lay.shape[0] % 4 == 0 and lay.shape[1] % 4 == 0
        assert (lay[..., :3].max(axis=2) <= lay[..., 3]).all()                 # premultiplied: nothing under clear
    filled = [(lay["rgba"][..., 3] > 128).sum() for lay in s["layers"]]
    assert filled == sorted(filled) and filled[0] > 0
    # placed down the right edge, one under another; a place of its own kept on the glass
    two = MM.meter_screens("optic", [{}, {"at": [5000, -3]}, {}])
    assert two[2]["y"] - two[0]["y"] == 2 * MM.METER_GAP
    assert (two[1]["x"], two[1]["y"]) == (MM.GLASS_W - MM.METER_W, 0.0)
    assert MM.meter_names("optic", 2)["level"](7) == "PadMode_optic_Meter2.PadMode_optic_Meter2_L7"


def test_a_fade_covers_the_glass_flat_or_strongest_at_its_edges():
    flat, glow = MM.fade_screens("optic", [{"color": "#000000"}, {"color": "#ff0000", "style": "glow"}])
    assert len(flat["layers"]) == len(glow["layers"]) == MM.FADE_LEVELS == 16
    f = flat["layers"][-1]
    assert f["x"] <= 0 and f["y"] <= 0
    assert f["x"] + f["rgba"].shape[1] * f["sx"] >= MM.GLASS_W and f["y"] + f["rgba"].shape[0] * f["sy"] >= MM.GLASS_H
    assert (f["rgba"][..., 3] == 255).all() and (f["rgba"][..., :3] == 0).all()
    assert (flat["layers"][7]["rgba"][..., 3] == 128).all()                   # step 8 of 16: half
    g = glow["layers"][-1]["rgba"]
    h, w = g.shape[:2]
    assert g[h // 2, w // 2, 3] == 0 and g[0, 0, 3] > 200                     # clear in the middle, red at the edges
    assert (g[..., 0] <= g[..., 3]).all() and (g[..., 1:3] == 0).all()        # premultiplied red
    assert MM.fade_screens("optic", [{}] * 5)[-1]["name"] == "PadMode_optic_Fade3"


# ---- the scene ------------------------------------------------------------------------------------------------------
def test_each_layer_is_a_sprite_holding_its_picture():
    p = SW.PROFILES["f9daed5a19aafc807bf9eb3c2def6c27"]
    layers = [{"name": "M_L%d" % j, "rgba": _art(8, 4)} for j in (1, 2)]
    group, ids = SW.screen(p, "M", _art(), "W", 0, 0, layers=layers)
    assert len(ids) == SW.screen_ids(layers) == 17
    for j in (1, 2):
        at = group.index(SW.string("M_L%d" % j))
        # the layer node: its ptr id, its name, then (past its frame and track) a Sprite component
        assert struct.unpack_from("<I", group, at - 4)[0] == SW.FLAG | ids[7 + 5 * (j - 1)]
        assert SW.string("M_L%d_Pic" % j) in group
    assert group.count(struct.pack("<I", p.poly["sprite"])) >= 2


def test_many_meters_move_the_carried_fonts_ids_past_them(monkeypatch):
    """A card of several modes with meters takes more ids than the 0x800 the screens had: the font starts past them."""
    data, p = _fake_scene(monkeypatch)
    screens = []
    for k in range(25):
        screens += MM.meter_screens("m%d" % k, [{"label": "X"}])
    need = sum(SW.screen_ids(s["layers"]) for s in screens)
    assert need > SW.FONT_ID_GAP
    new, infos = SW.add_screens(data, screens)
    assert len(infos) == 25
    assert struct.unpack_from("<Q", new, p.root_count_at)[0] == p.root_count + 25
    with pytest.raises(SW.SceneWriteError, match="beside a HUD"):
        SW.add_screens(data, screens, huds=[("x", {})])


# ---- the ARM build --------------------------------------------------------------------------------------------------
def test_it_builds_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    src = tmp_path / "optic.c"
    src.write_text(BM.to_c(_prog(), "optic"), encoding="utf-8")
    shutil.copy(os.path.join(SDK, "examples", BM.KIT_FILE), tmp_path / BM.KIT_FILE)
    r = subprocess.run(["bash", os.path.join(SDK, "build_mode.sh"), "-o", str(tmp_path / "mode.so"), str(src),
                        os.path.join(SDK, "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()
