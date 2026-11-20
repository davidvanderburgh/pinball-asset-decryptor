"""PAD-1410: porting a game written in MPF to the mode SDK.

- MPF_PORTING.md sits beside MODE_SDK.md (the app opens it from the same folder) and every SDK call it names is one
  the SDK has (pad_mode.h, pad_mode_assets.h, the kit), so the guide cannot drift from the API it maps onto.
- The worked example (docs/plans/pad1410_mpf_port: the MPF game and its C port, UNCANNY STORY) is the one the
  emulator played: its assets.json is a valid code mode's, the screens its C finds are the ones its assets.json makes
  the build add, every shot it asks for is on both Uncanny X-Men 0.98 ports or is a button shot, and it uses the
  calls the guide maps MPF's parts onto.
- The new-mode wizard's C step offers the guide, and the brief copied for an agent names it only when the maker says
  the game was written in MPF.
"""

import json
import os
import re

from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import mode_meters, mode_runtime as MR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
EX = os.path.join(ROOT, "docs", "plans", "pad1410_mpf_port")
GUIDE = os.path.join(SDK, "MPF_PORTING.md")


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def _api():
    text = _read(SDK, "pad_mode.h") + _read(SDK, "pad_mode_assets.h") + _read(SDK, "examples", "intricate_kit.h")
    return set(re.findall(r"\b((?:pm|kit|pa)_[a-z0-9_]+)\b", text)) | set(re.findall(r"struct ((?:kit|pa)_[a-z_]+)", text))


def test_the_guide_sits_beside_the_sdk_guide():
    assert os.path.isfile(GUIDE)
    assert os.path.normcase(os.path.dirname(GUIDE)) == os.path.normcase(MR.sdk_dir())
    text = _read(GUIDE)
    for want in ("MODE_SDK.md", "pm_own_game", "pm_begin_layer", "pm_saved_put", "kit_menu_open", "kit_meter_set",
                 "kit_fade_to", "pm_shot_claim", "pm_ball_save", "pm_multiball_start", '"Action button"'):
        assert want in text, want


def test_every_sdk_call_the_guide_names_exists():
    api = _api()
    named = set(re.findall(r"`[^`]*?\b((?:pm|kit|pa)_[a-z0-9_]+)\b", _read(GUIDE)))
    named |= set(re.findall(r"\b((?:pm|kit|pa)_[a-z0-9_]+)\(", _read(GUIDE)))
    ours = {n for n in named if not n.startswith(("pm_mode", "kit_game"))} - {"pm_modes"}
    missing = sorted(n for n in ours if n not in api)
    # the example's own functions (fut_tick...) never match pm_/kit_/pa_; PadMode_ node names are not calls
    assert not missing, missing


def test_the_worked_example_is_a_valid_code_mode():
    spec = CM.CodeAssets.from_json(json.loads(_read(EX, "xstory", "assets.json")))
    CM.validate(spec, os.path.join(EX, "xstory"))
    assert [m["label"] for m in spec.meters] == ["SENTINEL", "PHOENIX", "MUTANT METER"]
    assert len(spec.meters) <= mode_meters.METERS_MAX
    assert [f["style"] for f in spec.fades] == ["flat", "glow"]
    assert [m["title"] for m in spec.menus] == ["CHOOSE YOUR MUTANT"]


def test_the_example_finds_the_screens_its_assets_make():
    c = _read(EX, "xstory", "xstory.c")
    spec = json.loads(_read(EX, "xstory", "assets.json"))
    nodes = set(re.findall(r'"(PadMode_xstory_[A-Za-z]+\d)"', c))
    want = {"PadMode_xstory_Meter%d" % (k + 1) for k in range(len(spec["meters"]))}
    want |= {"PadMode_xstory_Fade%d" % (k + 1) for k in range(len(spec["fades"]))}
    want |= {"PadMode_xstory_Menu%d" % (k + 1) for k in range(len(spec["menus"]))}
    assert nodes == want, (nodes, want)


def test_the_example_asks_for_shots_both_xmen_ports_have():
    c = _read(EX, "xstory", "xstory.c")
    asked = set(re.findall(r'pm_shot\("([^"]+)"\)', c))
    assert asked == {"Left ramp exit opto", "Right ramp exit opto", "Xjet tgt", "Dr ramp exit", "Action button"}
    for key in ("uncanny_xmen_le-0.98", "uncanny_xmen_pro-0.98"):
        port = _read(SDK, "ports", key + ".port")
        names = {ln.split(None, 2)[2].strip() for ln in port.splitlines() if ln.startswith("shot ")}
        for s in asked - {"Action button"}:          # the buttons are the card's buttons.cfg shots (PAD-1403)
            assert s in names, (key, s)


def test_the_example_is_the_whole_game_with_layers_and_saved_progress():
    c = _read(EX, "xstory", "xstory.c")
    assert c.count("PM_REGISTER(") == 3
    for call in ("pm_own_game(1)", "pm_begin_layer(50, 0)", "pm_begin_layer(80, 0)", "pm_shot_claim()",
                 "pm_saved_put(\"xstory:chapter\"", "pm_saved_get(\"xstory:chapter\"", "pm_saved_stamp(",
                 "pm_ball_save(10)", "pm_multiball_start(2, 10)", "kit_menu_open(", "kit_menu_shot(",
                 "kit_new_game(", "#include \"intricate_kit.h\""):
        assert call in c, call
    assert "INTRO_S" not in c and "intro_over" not in c          # PAD-1464: the kit's menu waits for the film itself
    api = _api()
    used = set(re.findall(r"\b((?:pm|kit|pa)_[a-z0-9_]+)\(", c))
    assert used and used <= api, sorted(used - api)
    # the MPF game it was ported from, one config per mode
    for mode in ("future", "roster", "sentinel", "phoenix"):
        assert os.path.isfile(os.path.join(EX, "mpf", "modes", mode, "config", mode + ".yaml")), mode


def test_the_wizard_offers_the_guide_and_names_it_only_for_mpf():
    js = _read(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "modes_new.js")
    assert 'call("modes.open_mpf_doc")' in js and "Open MPF_PORTING.md, the porting guide" in js
    assert "It ports a game I wrote in MPF (YAML and Python)" in js
    assert "mpfDoc: mpf ? s.mpf_doc : \"\"" in js
    brief = js[js.index("export function agentBrief"):js.index("export function NameField")]
    assert "...(mpfDoc ? [`It ports a game written in the Mission Pinball Framework" in brief
    assert "Read ${mpfDoc} next" in brief
    for code in ("de", "es", "fr"):
        cat = json.loads(_read(ROOT, "pinball_decryptor", "webui", "static", "i18n", code + ".json"))
        assert "Open MPF_PORTING.md, the porting guide" in cat, code
