"""Tests for item 148: the Modes tab's title profiles come from the SDK's PORT files.

One case per port in ``tools/spike2_emu/modes/sdk/ports``: its shots, what the runtime
would arm with, which parts of a mode the title cannot do (each with a reason), and
whether the port was ever run. For each, a blank mode and a ready-made one generate a
runtime file that ``mode_file.c`` accepts ON THAT TITLE: only keys its parser knows (read
from the C source, not copied here), masks inside the port's own shots and as wide as
the game sends, a clock and a trigger count, under its 4096-byte buffer, and no line for
a part the title cannot do. A build ships the title's port as ``padmode/game.port``.
Desk only: no card, no emulator.
"""

import json
import os
import pathlib
import re

import pytest

from pinball_decryptor.plugins.stern import mode_assets as MA
from pinball_decryptor.plugins.stern import mode_project as MP

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"
ALL = set(MP.PARTS)
EVERY_CAPABILITY = ("callout", "lights", "screens", "clips", "own-sound", "messages", "award-screen")
NO_FRAMEWORK_DISPLAY = ("callout", "own-sound", "messages")
CALLOUT_SOUND = ("callout", "own-sound")

#: port -> (shots, shot_mask_bits, proven, parts it cannot do, what the runtime arms with)
PORTS = {
    "godzilla_pro-1.15": (15, 64, True, set(), EVERY_CAPABILITY),   # item 160: + the three spinners
    "godzilla_le-1.16": (21, 64, True, set(), EVERY_CAPABILITY),
    "turtles_pro-1.58": (17, 32, True, ALL, NO_FRAMEWORK_DISPLAY),
    "turtles_pro-1.59": (17, 32, True, {"own_sound", "screen"}, ("callout", "clips", "own-sound", "messages")),
    "deadpool_pro-1.16": (25, 64, True, {"countdown", "own_sound", "screen"}, ("callout", "clips", "own-sound", "messages")),
    "deadpool_le-1.14": (28, 64, True, {"countdown", "own_sound", "screen"}, ("callout", "clips", "own-sound", "messages")),
    # item 162 (2026-09-24): every latest build, proven by a full build check in the emulator
    "godzilla_pro-1.16": (21, 64, True, {"screen"}, EVERY_CAPABILITY),
    "aerosmith_le-1.15": (43, 64, True, {"countdown", "screen"}, ("callout", "clips", "own-sound")),
    "avengers_infinity_le-1.09": (36, 64, True, {"lights", "own_sound", "screen"}, ("callout", "clips", "own-sound")),
    "batman-1.13": (43, 64, True, ALL - {"events", "lights", "stack"}, CALLOUT_SOUND),
    "elvira3-1.13": (45, 64, True, ALL - {"events", "lights", "stack"}, CALLOUT_SOUND),
    "foo_fighters_le-1.04": (41, 64, True, {"own_sound", "screen"}, ("callout", "clips", "own-sound")),
    "james_bond_60th_le-1.11": (37, 64, True, {"clip", "countdown", "screen"}, CALLOUT_SOUND),
    "led_zeppelin_le-1.22": (31, 32, True, {"clip", "own_sound", "screen"}, ("callout", "screens", "own-sound")),
    "led_zeppelin_pro-1.22": (30, 32, True, {"clip", "own_sound", "screen"}, ("callout", "screens", "own-sound")),
    "metallica_spike-1.03": (40, 64, True, {"clip", "screen"}, ("callout", "screens", "own-sound")),
    "munsters_le-1.28": (27, 32, True, {"clip", "screen"}, CALLOUT_SOUND),
    "rush_le-1.18": (38, 64, True, {"clip", "screen"}, CALLOUT_SOUND),
    "star_wars_elg-1.10": (30, 64, True, {"clip", "own_sound", "screen"}, CALLOUT_SOUND),
    "star_wars_le-1.30": (42, 64, True, {"clip", "own_sound", "screen"}, CALLOUT_SOUND),
    "uncanny_xmen_le-0.98": (33, 64, True, {"own_sound", "screen"}, ("callout", "screens", "clips", "own-sound")),
    "jaws_le-1.02": (27, 64, True, {"screen"}, ("callout", "screens", "clips", "own-sound", "messages")),
    "stranger_things_le-1.12": (39, 64, True, {"lights", "screen"}, ("callout", "clips", "own-sound")),
    "king_kong_le-0.97": (55, 64, True, {"screen"}, ("callout", "screens", "clips", "own-sound")),
    "james_bond_le-1.06": (44, 64, True, {"clip", "screen"}, CALLOUT_SOUND),
    "jurassic_park_le-1.16": (38, 64, True, {"own_sound", "screen"}, ("callout", "screens", "clips", "own-sound")),
    "guardians_le-1.14": (34, 64, True, {"screen"}, ("callout", "clips", "own-sound")),
    "iron_maiden_le-1.16": (32, 64, True, ALL - {"countdown", "events", "stack"}, CALLOUT_SOUND),
    "sword_of_rage_le-1.18": (35, 64, True, {"lights", "own_sound", "screen"}, ("callout", "clips", "own-sound")),
    "mando_le-1.44": (40, 64, True, {"own_sound", "screen"}, ("callout", "clips", "own-sound")),
    "turtles_le-1.59": (17, 32, True, ALL - {"countdown", "events"}, NO_FRAMEWORK_DISPLAY),
    "dungeons_and_dragons_le-1.00": (33, 64, True, {"screen"}, ("callout", "clips", "own-sound")),
    "john_wick_le-1.01": (43, 64, True, ALL - {"events", "lights", "stack"}, CALLOUT_SOUND),
    "venom_le-1.07": (40, 64, True, {"screen"}, ("callout", "clips", "own-sound")),
}

#: the lines a part of a mode puts in the runtime file
PART_KEYS = {
    "screen": ("screen_scene", "screen_node", "screen_text"),
    "clip": ("clip_start", "clip_end"),
    "lights": ("light_owner", "light_on", "light_off"),
    "countdown": ("callout_at", "callout_count"),
    "own_sound": ("sound_key", "sound_callout"),
}


def _mode_file_keys():
    """Every key mode_file.c's cfg_line() accepts, read from the C source."""
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    body = src[src.index("static void cfg_line"):src.index("static void cfg_parse")]
    keys = set(re.findall(r'\b(?:TEXT|NUM|NUM64)\("([a-z_]+)"', body))
    keys |= set(re.findall(r'key_is\(line, "([a-z_]+)"\)', body))
    # and the keys of the helpers cfg_line hands a line to (starts_line, stack_line, ...)
    for helper in re.findall(r'if \(([a-z_]+_(?:line|key))\(M, line\)\) return;', body):
        start = src.index("static int %s(" % helper)
        keys |= set(re.findall(r'key_is\(line, "([a-z_]+)"\)', src[start:src.index("\n}\n", start)]))
    assert {"name", "trigger", "seconds", "shots", "award", "callout_at"} <= keys
    return keys


def _cfg(text):
    out = {}
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            k, _, v = s.partition(" ")
            out.setdefault(k, []).append(v.strip())
    return out


def _port(name):
    return str(SDK / "ports" / (name + ".port"))


def _check_runtime_file(p, spec, slug):
    return _check_text(p, MP.runtime_cfg(spec, slug), spec.start_shot)


def _check_text(p, text, start_shot):
    cfg = _cfg(text)
    unknown = set(cfg) - _mode_file_keys()
    assert not unknown, "keys mode_file.c would skip: %s" % unknown
    assert len(text.encode()) < 4096                              # mode_file.c CFG_MAX
    trigger, count = cfg["trigger"][0].split()
    assert int(cfg["seconds"][0]) > 0 and int(count) > 0          # else NOT VALID
    every = 0
    for _n, m in p.shots:
        every |= m
    for mask in (int(trigger, 0), int(cfg["shots"][0], 0)):
        assert mask and mask & ~every == 0, "a mask outside %s's shots" % p.label
        assert mask < (1 << p.shot_mask_bits), "wider than %s sends" % p.label
    assert int(trigger, 0) == p.mask([start_shot])
    for part, keys in PART_KEYS.items():
        if not p.can(part):
            assert not set(keys) & set(cfg), "%s: a %s line for a title that cannot" % (p.label, part)
    return cfg


@pytest.mark.parametrize("name", sorted(PORTS))
def test_a_profile_per_port(name):
    shots, bits, proven, cannot, runtime = PORTS[name]
    p = MP.profile_from_port(_port(name))
    game, version = name.split("-")
    assert (p.game_dir, p.version, p.port) == (game, version, name + ".port")
    assert p.key == "%s_%s" % (game, version.replace(".", "_"))
    assert len(p.shots) == shots and len({n for n, _m in p.shots}) == shots
    assert p.shot_mask_bits == bits and p.proven is proven
    assert {part for part in MP.PARTS if not p.can(part)} == cannot
    for part in MP.PARTS:
        assert bool(p.why_not(part)) == (part in cannot)
        if part in cannot:
            assert p.label in p.why_not(part) and "\u2014" not in p.why_not(part)
    assert p.runtime_can == runtime
    # item 163: every countdown's callouts are heard now (Jaws's were the last)
    assert p.sound_note == ""
    assert bool(p.proven_note) == (not proven)
    assert p.example_start_shot in {n for n, _m in p.shots}
    # it is the profile the tab finds for that card
    found = MP.profile_for_card(game, version + ".0")
    assert found is not None and found.key == p.key

    # a blank mode and every ready-made one generate a file the runtime accepts here
    blank = MP.blank_spec(p)
    assert blank.title == p.key and MP.validate(blank) == []
    _check_runtime_file(p, blank, "blank")
    examples = MP.examples_for(p)
    assert examples
    for ex_name, spec in examples:
        assert spec.title == p.key and MP.validate(spec) == [], ex_name
        _check_runtime_file(p, spec, MP.slugify(ex_name))


def test_stack_needs_the_ports_own_mode_queries_as_the_runtime_asks_for_them(tmp_path):
    """``stack no`` (item 140) works only where the port names the game's own mode queries:
    the names STACK_NEEDS lists are the ones pad_mode_runtime.c asks for (read from its
    source). A Godzilla port without them cannot stack, and says why."""
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    body = src[src.index("int pm_stock_mode_running"):src.index("const char *pm_stock_mode_what")]
    asked = set(re.findall(r'"(stock_[a-z_]+)"', body)) | set(
        re.findall(r'data\("(stock_[a-z_]+)"\)', src[src.index("static int stock_query"):]))
    sites, data = MP.STACK_NEEDS
    assert set(sites) <= asked and set(data) <= asked
    for key in ("godzilla_pro_1_15", "godzilla_le_1_16"):
        assert MP.profile(key).can("stack")
    text = open(_port("godzilla_le-1.16"), encoding="utf-8").read()
    bare = "\n".join(line for line in text.splitlines() if "stock_" not in line)
    (tmp_path / "godzilla_le-1.16.port").write_text(bare, encoding="utf-8")
    p = MP.profile_from_port(str(tmp_path / "godzilla_le-1.16.port"))
    assert not p.can("stack") and "tells that one of its own modes is running" in p.why_not("stack")
    assert [part for part in MP.PARTS if not p.can(part)] == ["stack"]
    # a stack no mode still makes a file every title's runtime reads (one that cannot tell
    # logs so and starts it anyway), and so do the other items' keys
    assert {"stack", "starts", "cooldown"} <= _mode_file_keys()
    for key in ("turtles_pro_1_58", "turtles_le_1_59"):
        q = MP.profile(key)
        spec = MP.blank_spec(q)
        spec.stack, spec.starts, spec.cooldown = False, "once_per_ball", 5
        cfg = _check_text(q, MP.runtime_cfg(spec, "x"), spec.start_shot)
        assert cfg["stack"] == ["no"] and not q.can("stack")


def test_stack_on_the_other_cmode_titles_is_the_mode_table_route(tmp_path):
    """item 164: every cmode title but Godzilla stacks through the game's mode TABLE, walked by the
    runtime (STACK_TABLE_NEEDS are the names its generic route reads); a build is offered only once a
    stack no mode was seen held back in the emulator (STACK_PROVEN)."""
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    body = src[src.index("static int stock_class"):src.index("int pm_stock_mode_running")]
    asked = set(re.findall(r'(?:data|pm_port_value)\("([a-z_]+)"', body))
    data, values = MP.STACK_TABLE_NEEDS
    assert set(data) | set(values) <= asked
    for key in MP.STACK_PROVEN:
        q = MP.profile(key.replace("-", "_").replace(".", "_"))
        assert q.can("stack"), key
        spec = MP.blank_spec(q)
        spec.stack = False
        assert _check_text(q, MP.runtime_cfg(spec, "x"), spec.start_shot)["stack"] == ["no"]
    text = open(_port("jaws_le-1.02"), encoding="utf-8").read()
    text = re.sub(r"^version(\s+)1\.02", r"version\g<1>9.99", text, flags=re.M)
    (tmp_path / "jaws_le-9.99.port").write_text(text, encoding="utf-8")
    p = MP.profile_from_port(str(tmp_path / "jaws_le-9.99.port"))     # the same title, a build not yet seen
    assert p.version == "9.99"
    assert not p.can("stack") and "not yet seen a mode of yours wait" in p.why_not("stack")


def test_stack_on_the_titles_with_no_cmode_rules_is_multiballs_only(tmp_path):
    """item 164: a title with no cmode rules stacks through the framework's count of the balls in play
    (STACK_BALLS_NEEDS are the sites the runtime's route calls); it waits for multiballs only, and the
    profile says so in its stack note; a build is offered once seen in the emulator (STACK_BALLS_PROVEN)."""
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    body = src[src.index("static int stock_balls_route"):src.index("int pm_stock_mode_running")]
    assert set(MP.STACK_BALLS_NEEDS) <= set(re.findall(r'fn\("([a-z_]+)"\)', body))
    for key in MP.STACK_BALLS_PROVEN:
        q = MP.profile(key.replace("-", "_").replace(".", "_"))
        assert q.can("stack"), key
        assert "waits only for the game's multiballs" in q.stack_note, key
    for key in MP.STACK_PROVEN:                 # the mode table sees every mode: no note
        assert MP.profile(key.replace("-", "_").replace(".", "_")).stack_note == "", key
    text = open(_port("beatles-1.29"), encoding="utf-8").read()
    text = re.sub(r"^version(\s+)1\.29", r"version\g<1>9.99", text, flags=re.M)
    (tmp_path / "beatles-9.99.port").write_text(text, encoding="utf-8")
    p = MP.profile_from_port(str(tmp_path / "beatles-9.99.port"))
    assert p.version == "9.99" and not p.can("stack")
    assert "tells a multiball is running but has not yet seen" in p.why_not("stack")


def test_every_shipped_port_is_proven():
    assert all(MP.profile(k).proven for k in MP.profiles())


def test_a_port_marked_not_run_is_unproven_and_says_why(tmp_path):
    src = (SDK / "ports" / "deadpool_le-1.14.port").read_text(encoding="utf-8")
    port = tmp_path / "deadpool_le-1.14.port"
    port.write_text("# drafted. NOT RUN: never run in the emulator.\n" + src, encoding="utf-8")
    p = MP.profile_from_port(str(port))
    assert p.proven is False and "never run" in p.proven_note


def test_clip_v2_needs_are_what_the_runtime_checks():
    """item 164: CLIP_V2_NEEDS is copied from pad_mode_runtime.c's clip2_s / clip2_d / clip2_v."""
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")

    def names(var):
        body = re.search(r"%s\[\] = \{(.*?)\};" % var, src, re.S).group(1)
        return tuple(re.findall(r'"([a-z_0-9]+)"', body))
    assert MP.CLIP_V2_NEEDS == (names("clip2_s"), names("clip2_d"), names("clip2_v"))
    assert MP.CLIP_LAYER_NEEDS == (names("clip3_s"), names("clip3_d"), names("clip3_v"))
    assert 'pm_scene_id("video_bank") || site("video_surface")' in src


def test_deadpool_plays_its_clips_on_the_video_layer(tmp_path):
    """item 164: the Deadpools' clips go through the game's full-screen video layer, and only with
    every layer line."""
    for key in ("deadpool_le-1.14", "deadpool_pro-1.16"):
        src = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
        assert "site surface_find" not in src               # the bank's surface alone is not on the glass
        assert "clips" in MP.profile_from_port(_port(key)).runtime_can
        port = tmp_path / (key + ".port")
        port.write_text(_without(src, "video_layer"), encoding="utf-8")
        assert "clips" not in MP.profile_from_port(str(port)).runtime_can


def _without(port_text, *names):
    return "\n".join(l for l in port_text.split("\n")
                     if not any(re.match(r"(site|data|value|scene)\s+%s\s" % n, l) for n in names))


def test_clip_v2_arms_clips_from_the_surface_lines(tmp_path):
    """Venom 1.07 has no clip_play: its clips come from the surface lines alone, and go with them."""
    src = (SDK / "ports" / "venom_le-1.07.port").read_text(encoding="utf-8")
    assert "clips" in MP.profile_from_port(_port("venom_le-1.07")).runtime_can
    port = tmp_path / "venom_le-1.07.port"
    port.write_text(_without(src, "surface_find"), encoding="utf-8")
    assert "clips" not in MP.profile_from_port(str(port)).runtime_can
    port.write_text(_without(src, "video_bank"), encoding="utf-8")
    assert "clips" not in MP.profile_from_port(str(port)).runtime_can
    # a port with the game's own video_surface getter needs no bank scene id (JP LE's bank is demand_loaded)
    port.write_text(_without(src, "video_bank") + "\nsite video_surface      0x00100000 0xe92d4070 0xe3065c18\n",
                    encoding="utf-8")
    assert "clips" in MP.profile_from_port(str(port)).runtime_can


def test_the_bank_and_hud_live_in_their_measured_lcd_tree():
    gz = MP.GODZILLA_PRO_1_15
    assert gz.lcd("bank") == "assets/lcd/auto_loaded/" + gz.bank_scene
    assert gz.lcd("hud") == "assets/lcd/auto_loaded/" + gz.hud_scene
    trees = {k: v.get("bank_tree", "auto_loaded") for k, v in MP.TITLE_SCENES.items()}
    assert set(trees.values()) <= {"auto_loaded", "demand_loaded"}
    for key, tree in trees.items():
        p = MP.profile(key.replace("-", "_").replace(".", "_"))
        if p is not None:
            assert p.bank_tree == tree and p.lcd("bank").startswith("assets/lcd/%s/" % tree)


def test_godzilla_pro_1_15_is_unchanged_and_is_what_its_port_says():
    g = MP.GODZILLA_PRO_1_15
    assert MP.profile("godzilla_pro_1_15") is g and MP.profiles()["godzilla_pro_1_15"] is g
    assert (g.key, g.label, g.game_dir) == ("godzilla_pro_1_15", "Godzilla Pro 1.15", "godzilla_pro")
    assert (g.callout_countdown, g.callout_ten_seconds, g.callout_time_up) == (1287, 1291, 1295)
    assert (g.light_owner, g.light_lts) == (538, 224)
    assert g.hud_scene == "32e6ae280ddaec08e203a02289bb39a04968e7b0"
    assert g.bank_scene == "60ed7e5036b8ce09d35a3e101ea6fc1380b37d97"
    assert (g.version, g.port) == ("1.15", "godzilla_pro-1.15.port")
    assert all(g.can(part) for part in MP.PARTS)
    derived = MP.profile_from_port(MP.port_path(g))
    for f in ("key", "label", "game_dir", "shots", "callout_countdown", "callout_ten_seconds",
              "callout_time_up", "light_owner", "light_lts", "hud_scene", "bank_scene",
              "runtime_can", "example_start_shot", "sound_note"):
        assert getattr(derived, f) == getattr(g, f), f
    # a blank mode on it is exactly the mode the tab made before item 148
    assert MP.blank_spec(g).to_json() == MP.ModeSpec().to_json()
    assert [n for n, _ in MP.examples_for(g)] == [n for n, _ in MP.example_specs()]


def test_premium_1_16_offers_godzillas_names_with_three_shield_targets():
    p = MP.profile_for_card("godzilla_le", "1.16.0")
    names = [n for n, _m in p.shots]
    assert p.label == "Godzilla Premium/LE 1.16"
    assert {"Maser target", "Left ramp", "Shield target left", "Shield target center",
            "Shield target right"} <= set(names)
    assert [n for n, _ in MP.examples_for(p)][0] == "KAIJU RUSH"
    # the same shot NAME is another bit on LE: the masks are the LE port's own
    assert p.mask(["Shield target right"]) == 0x200000000 != MP.GODZILLA_PRO_1_15.mask(["Shield target right"])


def test_a_card_with_no_port_gets_none_and_the_help_names_making_a_port():
    assert MP.profile_for_card("godzilla_pro", "1.14.0") is None
    assert MP.profile_for_card("turtles_pro", "1.58.1") is None      # a patch level is another build
    assert MP.profile_for_card("", "1.15") is None
    # the words say what is missing; the SDK pointer is the details a tooltip shows
    assert "port" not in MP.NO_PORT_HELP
    assert "Making a port for another game or version" in MP.NO_PORT_DETAILS
    assert "MODE_SDK.md" in MP.NO_PORT_DETAILS
    heading = "### Making a port for another game or version"
    assert heading in (SDK / "MODE_SDK.md").read_text(encoding="utf-8")


def test_retarget_matches_shots_by_name():
    tmnt = MP.profile("turtles_pro_1_59")
    kaiju = MP.example("KAIJU RUSH")
    spec, dropped = MP.retarget(kaiju, tmnt)
    assert spec is not kaiju and kaiju.title == "godzilla_pro_1_15"
    assert spec.title == "turtles_pro_1_59"
    assert spec.start_shot == "Center loop"                          # the port's example
    assert spec.scoring_shots == ["Left ramp", "Right ramp"]         # names TMNT has too
    assert dropped == ["Maser target", "Powerline left", "Powerline center", "Powerline right"]
    same, none = MP.retarget(kaiju, MP.GODZILLA_PRO_1_15)
    assert none == [] and same.to_json() == kaiju.to_json()


def test_a_new_port_file_shows_up_and_a_broken_one_is_left_out(tmp_path):
    src = open(_port("turtles_pro-1.59"), encoding="utf-8").read()
    (tmp_path / "turtles_pro-9.99.port").write_text(src.replace("version        1.59", "version        9.99"),
                                                    encoding="utf-8")
    (tmp_path / "broken.port").write_text("game x\nversion 1\n", encoding="utf-8")
    (tmp_path / "not_a_port.txt").write_text("game y\n", encoding="utf-8")
    found = MP.profiles(str(tmp_path))
    assert list(found) == ["turtles_pro_9_99"]
    p = MP.profile_for_card("turtles_pro", "9.99.0", ports_dir=str(tmp_path))
    assert p.label == "TMNT Pro 9.99" and os.path.isabs(p.port) and MP.port_path(p) == p.port
    with pytest.raises(MP.ModeProjectError, match="lacks"):
        MP.profile_from_port(str(tmp_path / "broken.port"))


# ---- which card a project is for ---------------------------------------------------------
def _extract_record(project, name, card_version=None):
    rec = {"input_path": "D:\\cards\\" + name, "input_name": name, "size": 1, "mtime": 1}
    if card_version:
        rec["card_version"] = card_version
    (project / ".extract_source.json").write_text(json.dumps(rec), encoding="utf-8")


@pytest.mark.parametrize("name, card_version, game, key", [
    ("godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0", "godzilla_le", "godzilla_le_1_16"),
    ("turtles_pro-1_59_0.Release.8G.sdcard.raw", None, "turtles_pro", "turtles_pro_1_59"),
    ("jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0", "jaws_le", "jaws_le_1_02"),
    ("godzilla_pro-1_14_0_spike2.Release.8G.sdcard.raw", "1.14.0", "godzilla_pro", None),
])
def test_project_card_from_the_extract_record(tmp_path, name, card_version, game, key):
    _extract_record(tmp_path, name, card_version)
    card = MP.project_card(str(tmp_path))
    assert card.game_dir == game and card.image.endswith(name)
    p = MP.profile_for_card(card.game_dir, card.version)
    assert (p.key if p else None) == key


def test_project_card_from_the_project_anchor_and_a_bare_folder(tmp_path):
    from pinball_decryptor.core import project_file
    assert MP.project_card(str(tmp_path)) is None                    # bare: the tab keeps Pro 1.15
    assert MP.project_card(str(tmp_path / "missing")) is None
    image = "D:\\Pinball\\turtles_pro-1_58_0.Release.8G.sdcard.raw"
    project_file.save(str(tmp_path / ".pinproj"), manufacturer_key="stern",
                      paths={"write_original": image, "write_assets": str(tmp_path)},
                      extract_options={})
    card = MP.project_card(str(tmp_path))
    assert (card.game_dir, card.version, card.image) == ("turtles_pro", "1.58.0", image)
    assert MP.profile_for_card(card.game_dir, card.version).key == "turtles_pro_1_58"


def test_a_renamed_card_waits_for_the_probe(tmp_path, monkeypatch):
    image = tmp_path / "my card.raw"
    image.write_bytes(b"\0" * 1024)
    _extract_record(tmp_path, "my card.raw", "1.59.0")
    rec = json.loads((tmp_path / ".extract_source.json").read_text(encoding="utf-8"))
    rec["input_path"] = str(image)
    (tmp_path / ".extract_source.json").write_text(json.dumps(rec), encoding="utf-8")
    card = MP.project_card(str(tmp_path))
    assert (card.game_dir, card.version, card.image) == ("", "1.59.0", str(image))
    # not a card: the probe answers nothing, and the answer is cached
    assert MP.probe_card_title(str(image)) == (None, None)
    assert MP.probed_card_title(str(image)) == (None, None)
    monkeypatch.setitem(MP._PROBED, MP._probe_key(str(image)), ("turtles_pro", "1.59.0"))
    card = MP.project_card(str(tmp_path))
    assert (card.game_dir, card.version) == ("turtles_pro", "1.59.0")
    assert MP.probe_card_title(str(tmp_path / "nothing.raw")) == (None, None)


# ---- the build ships the port ---------------------------------------------------------
@pytest.mark.parametrize("key", ["turtles_pro_1_59", "jaws_le_1_02", "deadpool_pro_1_16"])
def test_the_build_ships_the_titles_port_and_leaves_out_what_it_cannot_do(tmp_path, key):
    p = MP.profile(key)
    project = tmp_path / "proj"
    for name, spec in MP.examples_for(p)[:1] + [("SECOND", MP.blank_spec(p, "SECOND"))]:
        spec.screen = True                              # asked for; the title cannot
        spec.clip = "none" if p.can("clip") else "title"
        if not p.can("clip"):                           # item 148 (j): nor Advanced's second clip
            spec.clip_both = {"clip": "title", "title": "AGAIN", "seconds": 2.0}
        MP.new_mode(str(project), name, spec)
    out = tmp_path / "out"
    res = MA.build(str(project), None, None, str(out))   # no stock scene is read
    assert res.port == "game.port" and res.files == [] and res.mode_files == ["mode.cfg", "mode1.cfg"]
    assert (out / "padmode" / "game.port").read_bytes() == open(MP.port_path(p), "rb").read()
    for (slot, _slug, _name), (_s, spec) in zip(res.slots, MP.list_modes(str(project))[0]):
        text = (out / "padmode" / MA.mode_file_name(slot)).read_text(encoding="utf-8")
        _check_text(p, text, spec.start_shot)


def test_a_jaws_mode_builds_its_clip_into_jaws_bank(tmp_path):
    """Jaws LE 1.02's Clip is live since item 148's run2 put an added clip on its glass: the
    build renders the clip, adds it to the bank the Jaws port names, and the mode file plays
    it by name - the same functions that run used (render_title_clip + add_clip)."""
    from pinball_decryptor.core import audio
    from pinball_decryptor.plugins.stern import video_bank as VB
    from tests.test_stern_video_bank import synthetic

    ff = audio.find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    p = MP.profile("jaws_le_1_02")
    assert p.can("clip") and len(p.bank_scene) == 40
    project, out = tmp_path / "proj", tmp_path / "out"
    spec = MP.blank_spec(p, "SHARK CLIP")
    spec.clip, spec.clip_seconds = "title", 1.0
    slug, _spec = MP.new_mode(str(project), spec=spec)
    res = MA.build(str(project), None, synthetic(("A", "B")), str(out), ffmpeg=ff)
    bank_rel = "assets/lcd/auto_loaded/%s" % p.bank_scene
    assert res.new_files == [bank_rel + "/scene.assets/2.asset/2.asset"]
    bank = VB.parse((out / bank_rel / "scene.radium").read_bytes())
    assert MP.asset_names(slug)["clip"] in [c.name for c in bank.library.entries]
    cfg = _check_text(p, (out / "padmode" / "mode.cfg").read_text(encoding="utf-8"), spec.start_shot)
    assert cfg["clip_start"] == [MP.asset_names(slug)["clip"]]
    assert (out / "padmode" / "game.port").read_bytes() == open(MP.port_path(p), "rb").read()


# ---- the CARD decides the port, not the title a mode was saved with ----------------------
def _card_project(tmp_path, name, card_version=None):
    project = tmp_path / "proj"
    project.mkdir()
    _extract_record(project, name, card_version)
    return project


def test_project_profile_is_the_cards_port_or_none():
    assert MP.project_profile(None) == (None, None)


def test_project_profile_for_each_kind_of_project(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    assert MP.project_profile(str(bare)) == (None, None)
    le = _card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    card, p = MP.project_profile(str(le))
    assert card.game_dir == "godzilla_le" and p.key == "godzilla_le_1_16"
    nop = tmp_path / "nop"
    nop.mkdir()
    _extract_record(nop, "godzilla_pro-1_14_0_spike2.Release.8G.sdcard.raw", "1.14.0")
    card, p = MP.project_profile(str(nop))
    assert card.game_dir == "godzilla_pro" and p is None


def test_a_premium_card_builds_its_own_port_for_modes_saved_as_godzilla_pro_1_15(tmp_path):
    """David's own project: a Godzilla Premium 1.16 card (a godzilla_le card) whose modes
    were made before item 148, so every mode.json says godzilla_pro_1_15. The build ships
    the CARD's port and the card's masks: Shield target right is 0x200000000 on Premium
    1.16, 0x100000000 on Pro 1.15. A mode saved on the card's own title builds beside it."""
    le = MP.profile("godzilla_le_1_16")
    project = _card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    old = MP.ModeSpec(name="OLD MODE", screen=False, scoring_shots=["Shield target right"])
    assert old.title == MP.GODZILLA_PRO_1_15.key
    MP.new_mode(str(project), spec=old)
    new = MP.blank_spec(le, "NEW MODE")
    new.screen = new.lights = False
    MP.new_mode(str(project), spec=new)
    out = tmp_path / "out"
    res = MA.build(str(project), None, None, str(out))
    port = (out / "padmode" / "game.port").read_bytes()
    assert port == open(MP.port_path(le), "rb").read()
    assert port != open(MP.port_path(MP.GODZILLA_PRO_1_15), "rb").read()
    texts = {name: (out / "padmode" / MA.mode_file_name(slot)).read_text(encoding="utf-8")
             for slot, _slug, name in res.slots}
    cfg = _check_text(le, texts["OLD MODE"], "Maser target")
    assert int(cfg["shots"][0], 0) == 0x200000000 == le.mask(["Shield target right"])
    _check_text(le, texts["NEW MODE"], new.start_shot)
    # the project itself is left as it was: the build reads, it does not rewrite
    assert {s.title for _slug, s in MP.list_modes(str(project))[0]} == {
        MP.GODZILLA_PRO_1_15.key, le.key}


def test_a_build_refuses_a_mode_naming_shots_the_cards_game_lacks(tmp_path):
    project = _card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0")
    MP.new_mode(str(project), spec=MP.example("KAIJU RUSH"))
    with pytest.raises(MA.ModeAssetError) as e:
        MA.build(str(project), None, None, str(tmp_path / "out"))
    text = str(e.value)
    assert "KAIJU RUSH" in text and "Powerline left" in text and "Jaws LE 1.02" in text
    assert not (tmp_path / "out" / "padmode").exists()


def test_a_build_refuses_a_card_with_no_port(tmp_path):
    project = _card_project(tmp_path, "godzilla_pro-1_14_0_spike2.Release.8G.sdcard.raw", "1.14.0")
    MP.new_mode(str(project), spec=MP.ModeSpec(name="OLD MODE", screen=False))
    with pytest.raises(MA.ModeAssetError, match="can't be made for Godzilla Pro 1.14 yet"):
        MA.build(str(project), None, None, str(tmp_path / "out"))


def test_a_build_probes_a_renamed_card_and_uses_its_port(tmp_path, monkeypatch):
    image = tmp_path / "my card.raw"
    image.write_bytes(b"\0" * 1024)
    project = _card_project(tmp_path, "my card.raw", "1.59.0")
    rec = json.loads((project / ".extract_source.json").read_text(encoding="utf-8"))
    rec["input_path"] = str(image)
    (project / ".extract_source.json").write_text(json.dumps(rec), encoding="utf-8")
    calls = []

    def probe(path):
        calls.append(path)
        MP._PROBED[MP._probe_key(path)] = ("turtles_pro", "1.59.0")
        return "turtles_pro", "1.59.0"

    monkeypatch.setattr(MP, "probe_card_title", probe)
    monkeypatch.setattr(MP, "_PROBED", {})
    tmnt = MP.profile("turtles_pro_1_59")
    spec = MP.blank_spec(tmnt, "RUSH")
    MP.new_mode(str(project), spec=spec)
    MA.build(str(project), None, None, str(tmp_path / "out"))
    assert calls == [str(image)]
    assert (tmp_path / "out" / "padmode" / "game.port").read_bytes() == open(MP.port_path(tmnt), "rb").read()


# ---- item 147's events, per title -------------------------------------------------------
def test_events_come_from_the_port_as_the_runtime_arms_them(tmp_path):
    """A profile's events are the port's ``event`` lines that pad_mode_runtime.c's events_arm
    would arm: a bus event needs ``site hook_dispatch``, a site event its own site. Only the
    ports proven by item 162's build check carry the events that fired; a port without them greys
    them, with the reason."""
    le = MP.profile("godzilla_le_1_16")
    text = open(_port("godzilla_le-1.16"), encoding="utf-8").read()
    assert list(le.events) == [line.split()[1] for line in text.splitlines() if line.startswith("event ")]
    assert le.can("events") and MP.GODZILLA_PRO_1_15.can("events")
    assert set(MP.profile_from_port(_port("godzilla_pro-1.15")).events) == set(MP.GODZILLA_PRO_1_15.events)
    for key in ("turtles_pro_1_58",):
        p = MP.profile(key)
        assert p.events == () and "events yet" in p.why_not("events")
    no_bus = "\n".join(line for line in text.splitlines() if not line.startswith("site hook_dispatch"))
    (tmp_path / "godzilla_le-1.16.port").write_text(no_bus, encoding="utf-8")
    assert MP.profile_from_port(str(tmp_path / "godzilla_le-1.16.port")).events == (
        "skill_shot", "multiball_start", "multiball_end")


def test_a_premium_build_of_a_pro_titled_mode_that_starts_on_an_event(tmp_path):
    """Item 147 + fix-1: a mode saved as Godzilla Pro 1.15 that starts on a ball start and ends
    on a multiball, built for a Premium 1.16 card, keeps both events (Premium's port carries
    them) and ships Premium's port; on a Jaws card, whose port has the bus events but no
    multiball start (a site event only the Godzilla ports place), the build refuses."""
    le = MP.profile("godzilla_le_1_16")
    project = _card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    spec = MP.ModeSpec(name="EVENTFUL", screen=False, starts_on="event ball_start",
                       ends_on="event multiball_start")
    MP.new_mode(str(project), spec=spec)
    out = tmp_path / "out"
    MA.build(str(project), None, None, str(out))
    assert (out / "padmode" / "game.port").read_bytes() == open(MP.port_path(le), "rb").read()
    cfg = _cfg((out / "padmode" / "mode.cfg").read_text(encoding="utf-8"))
    assert cfg["starts_on"] == ["event ball_start"] and cfg["ends_on"] == ["event multiball_start"]
    assert "trigger" not in cfg

    jaws = tmp_path / "jaws"
    jaws.mkdir()
    _extract_record(jaws, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0")
    j = MP.profile("jaws_le_1_02")
    spec = MP.blank_spec(j, "EVENTFUL")
    spec.starts_on = "event multiball_start"
    MP.new_mode(str(jaws), spec=spec)
    with pytest.raises(MA.ModeAssetError, match="no event 'multiball_start'"):
        MA.build(str(jaws), None, None, str(tmp_path / "out2"))


# ---- item 141's Advanced fields on another title (family sweep, 2026-09-17) ---------------
def _advanced_kaiju():
    """KAIJU RUSH made on Godzilla Pro 1.15 with Advanced set: points on a Powerline and a
    ramp, a Powerline that ends it early, the two measured callouts and one typed by hand."""
    spec = MP.example("KAIJU RUSH")
    spec.shot_award = [["Powerline left", 750000], ["Left ramp", 500000]]
    spec.end_shot = "Powerline right"
    spec.callout_at = [[10, 1291], [5, 1295], [3, 1111]]
    return spec


def test_retarget_drops_advanced_shots_and_another_titles_callouts():
    """Item 148's retarget with item 141's fields: a per-shot award or early-ending shot on a
    shot the title lacks is dropped (the form cannot show it, so kept it blocked every build
    for good), and a callout id made on another game is kept only where both ports measured
    that callout under the same name, as that title's own id."""
    kaiju = _advanced_kaiju()
    jaws, tmnt, le = (MP.profile(k) for k in ("jaws_le_1_02", "turtles_pro_1_59", "godzilla_le_1_16"))

    spec, dropped = MP.retarget(kaiju, jaws)
    assert spec.shot_award == [["Left ramp", 500000]] and spec.end_shot == ""
    assert spec.callout_at == [[10, jaws.callout_ten_seconds], [5, jaws.callout_time_up]] == [[10, 1387], [5, 1388]]
    assert {"Powerline left", "Powerline right", "callout 1111"} <= set(dropped)
    assert len(dropped) == len(set(dropped))                     # a name once, however many fields name it
    assert MP.dropped_callouts(dropped) == ["callout 1111"]
    assert kaiju.shot_award[0] == ["Powerline left", 750000] and kaiju.callout_at[0] == [10, 1291]

    spec, dropped = MP.retarget(kaiju, tmnt)                     # TMNT's port names no callouts
    assert spec.callout_at == [] and MP.dropped_callouts(dropped) == ["callout 1291", "callout 1295",
                                                                      "callout 1111"]
    assert "callout_at" not in MP.runtime_cfg(spec, "k")          # no Godzilla id rides along on TMNT

    spec, dropped = MP.retarget(kaiju, le)                       # the same calls on Premium 1.16
    assert spec.callout_at == [[10, 1291], [5, 1295]] and dropped == ["callout 1111"]
    assert spec.shot_award == kaiju.shot_award and spec.end_shot == "Powerline right"

    same, none = MP.retarget(kaiju, MP.GODZILLA_PRO_1_15)        # its own title: nothing changes
    assert none == [] and same.to_json() == kaiju.to_json()
    text = MP.retarget_refusal(kaiju, MP.retarget(kaiju, jaws)[1], jaws)
    assert "Powerline left" in text and "callout 1111" in text and "Jaws LE 1.02" in text


def test_a_build_refuses_advanced_fields_the_card_lacks_until_the_mode_is_saved_for_it(tmp_path):
    """The open gap item 148's verifier found: a Godzilla mode with points on a Powerline
    and a hand-typed callout, on a Jaws card, was refused by every build and no edit in the
    tab could clear it. The build refuses and names both; the mode as the tab saves it after
    an edit (the retargeted copy) builds, with Jaws's own masks and callout ids."""
    jaws = MP.profile("jaws_le_1_02")
    project = _card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0")
    kaiju = _advanced_kaiju()
    kaiju.clip = "none"                                          # no stock bank is read here
    slug, _spec = MP.new_mode(str(project), spec=kaiju)
    with pytest.raises(MA.ModeAssetError) as e:
        MA.build(str(project), None, None, str(tmp_path / "out"))
    text = str(e.value)
    for words in ("KAIJU RUSH", "Maser target", "Powerline left", "Powerline right", "callout 1111",
                  "Jaws LE 1.02"):
        assert words in text, words
    assert "callout 1291" not in text                            # moved to Jaws's ten-seconds call
    saved, _dropped = MP.retarget(MP.load(str(project / "modes" / slug / "mode.json")), jaws)
    MP.save(str(project), slug, saved)
    out = tmp_path / "out2"
    MA.build(str(project), None, None, str(out))
    cfg = _cfg((out / "padmode" / "mode.cfg").read_text(encoding="utf-8"))
    assert cfg["shot_award"] == ["0x%08x 500000" % jaws.mask(["Left ramp"])]
    assert "end_shot" not in cfg
    assert saved.countdown and jaws.can("countdown")             # the countdown's own line, then Advanced's
    assert cfg["callout_at"] == ["10 1387", "10 1387", "5 1388"]
