"""Tests for :mod:`pinball_decryptor.plugins.stern.mode_project` (item 127).

A mode is authored as ``<project>/modes/<slug>/mode.json`` and the file ``mode.so``
reads is GENERATED from it. The bar for the generator is the mode that is already
proven in the emulator: KAIJU RUSH authored by NAME here must produce the same runtime
values as ``tools/spike2_emu/modes/kaiju_rush_own_clip.mode`` (item 132's final run).
Desk only: no card, no emulator, no rig.
"""

import json
import os
import pathlib

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

REPO = pathlib.Path(__file__).resolve().parents[1]
PROVEN = REPO / "tools" / "spike2_emu" / "modes" / "kaiju_rush_own_clip.mode"


def _keys(text):
    """What mode.c's parser keeps: key -> value (last wins), comments and blanks skipped.
    callout_at is a repeatable key, so it is collected as a list."""
    out = {"callout_at": []}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        k, _, v = s.partition(" ")
        v = v.strip()
        if k == "callout_at":
            out[k].append(v.split())
        else:
            out[k] = v
    return out


def _kaiju():
    return MP.ModeSpec(
        name="KAIJU RUSH", start_shot="Maser target", start_count=3, seconds=30,
        scoring_shots=["Powerline left", "Powerline center", "Powerline right", "Left ramp", "Right ramp"],
        award=1000000, screen=True, clip="title", clip_when="start",
        countdown=True, lights=True, light_color="#00ff00")


def test_kaiju_rush_by_name_generates_the_proven_mode_file():
    cfg = _keys(MP.runtime_cfg(_kaiju(), "kaiju_rush"))
    proven = _keys(PROVEN.read_text(encoding="utf-8"))
    for key in ("name", "seconds", "award", "screen_scene", "restore_after", "light_owner",
                "light_on", "light_off", "callout_count", "callout_end", "callout_at"):
        assert cfg[key] == proven[key], key
    # masks: compare as numbers, the runtime reads 0x hex either way
    assert [int(x, 0) for x in cfg["trigger"].split()] == [int(x, 0) for x in proven["trigger"].split()]
    assert int(cfg["shots"], 0) == int(proven["shots"], 0) == 0x70300000
    # the asset names are the build's own, not item 131/132's hand-picked ones
    assert cfg["screen_node"] == "PadMode_kaiju_rush_Screen"
    assert cfg["screen_text"] == "PadMode_kaiju_rush_Screen.PadMode_kaiju_rush_Screen_Words"
    assert cfg["clip_start"] == "PadMode_kaiju_rush_Clip"


def test_the_examples_build_as_they_are_and_the_first_is_the_proven_mode(tmp_path):
    """Every example validates with no file of its own and generates a file mode.c
    accepts; KAIJU RUSH, the first, is the mode that ran on a real machine, so it must
    generate exactly what the proven mode file carries. new_mode copies an example
    rather than handing out the shared instance."""
    names = [n for n, _ in MP.example_specs()]
    assert names[0] == "KAIJU RUSH" and len(names) == len(set(names))
    for name, spec in MP.example_specs():
        assert spec.name == name
        assert MP.validate(spec, None) == [], name
        text = MP.runtime_cfg(spec, MP.slugify(name))
        assert len(text.encode()) < 4096
    kaiju, proven = _keys(MP.runtime_cfg(MP.example("KAIJU RUSH"), "kaiju_rush")), _keys(PROVEN.read_text(encoding="utf-8"))
    for key in ("name", "seconds", "award", "light_on", "light_off", "callout_at"):
        assert kaiju[key] == proven[key], key
    assert int(kaiju["shots"], 0) == int(proven["shots"], 0)
    assert MP.example("no such mode") is None

    slug, spec = MP.new_mode(str(tmp_path), spec=MP.example("KAIJU RUSH"))
    assert slug == "kaiju_rush" and spec is not MP.example("KAIJU RUSH")
    spec.award = 5
    assert MP.example("KAIJU RUSH").award == 1000000            # the example is untouched
    assert MP.load(os.path.join(MP.mode_folder(str(tmp_path), slug), MP.MODE_FILE)).name == "KAIJU RUSH"


def test_runtime_cfg_is_one_mode_c_accepts():
    """mode.c refuses a mode without seconds and a trigger count, and CFG_MAX is 4096."""
    text = MP.runtime_cfg(_kaiju(), "kaiju_rush")
    k = _keys(text)
    assert int(k["seconds"]) > 0 and int(k["trigger"].split()[1]) > 0
    assert len(text.encode()) < 4096


def test_optional_parts_come_and_go():
    spec = _kaiju()
    spec.screen, spec.clip, spec.lights, spec.countdown = False, "none", False, False
    k = _keys(MP.runtime_cfg(spec, "x"))
    for gone in ("screen_scene", "screen_node", "clip_start", "clip_end", "light_owner",
                 "callout_count"):
        assert gone not in k
    assert k["callout_at"] == []
    assert k["callout_end"] == "1295"
    spec.clip, spec.clip_when = "title", "end"
    assert _keys(MP.runtime_cfg(spec, "x"))["clip_end"] == "PadMode_x_Clip"


def test_own_end_sound_needs_the_built_key():
    spec = _kaiju()
    spec.end_sound = "end.wav"
    assert "sound_key" not in _keys(MP.runtime_cfg(spec, "k"))          # not built yet
    k = _keys(MP.runtime_cfg(spec, "k", sound_key="45df2b8b01000084"))
    assert k["sound_key"] == "45df2b8b01000084" and k["sound_callout"] == "1295"
    assert "callout_end" not in k


def test_light_colour_and_advanced_commands():
    spec = _kaiju()
    spec.light_color = "#ff8000"
    on, off = MP.light_commands(spec, MP.GODZILLA_PRO_1_15)
    assert "--red 255 --green 128 --blue 0" in on and "--fade 20" in off
    spec.light_on_raw, spec.light_off_raw = "blele --sweep 0 --lts 7", ""
    assert MP.light_commands(spec, MP.GODZILLA_PRO_1_15) == ("blele --sweep 0 --lts 7", "")


def test_validate_names_every_problem(tmp_path):
    spec = MP.ModeSpec(name=" ", start_shot="Nope", start_count=0, seconds=0,
                       scoring_shots=["Left ramp", "Flipper"], award=0, panel_color="green",
                       clip="file", clip_file="", screen_art="missing.png")
    problems = " ".join(MP.validate(spec, str(tmp_path)))
    for words in ("needs a name", "starts the mode", "at least one shot", "at least a second",
                  "'Flipper'", "worth something", "panel colour", "video file", "missing.png"):
        assert words in problems, words
    assert MP.validate(_kaiju(), str(tmp_path)) == []
    with pytest.raises(MP.ModeProjectError):
        MP.runtime_cfg(spec, "bad")


def test_project_round_trip_keeps_unknown_keys(tmp_path):
    project = str(tmp_path)
    slug, spec = MP.new_mode(project, "Kaiju Rush")
    assert slug == "kaiju_rush"
    path = os.path.join(project, "modes", slug, "mode.json")
    data = json.load(open(path, encoding="utf-8"))
    data["future_key"] = {"from": "a newer editor"}
    data["award"] = 7000000
    json.dump(data, open(path, "w", encoding="utf-8"))
    found, broken = MP.list_modes(project)
    assert broken == [] and [s for s, _ in found] == ["kaiju_rush"]
    spec = found[0][1]
    assert spec.award == 7000000 and spec.extra == {"future_key": {"from": "a newer editor"}}
    MP.save(project, slug, spec)
    assert json.load(open(path, encoding="utf-8"))["future_key"] == {"from": "a newer editor"}


def test_new_duplicate_delete_and_the_limit(tmp_path):
    project = str(tmp_path)
    a, _ = MP.new_mode(project, "Rush")
    b, _ = MP.new_mode(project, "Rush")
    assert (a, b) == ("rush", "rush_2")
    open(os.path.join(project, "modes", a, "art.png"), "wb").write(b"png")
    c, spec = MP.duplicate_mode(project, a)
    assert (c, spec.name) == ("rush_copy", "Rush COPY")
    assert os.path.isfile(os.path.join(project, "modes", c, "art.png"))
    MP.delete_mode(project, b)
    assert [s for s, _ in MP.list_modes(project)[0]] == ["rush", "rush_copy"]
    for i in range(MP.MAX_MODES - 2):
        MP.new_mode(project, "M%d" % i)
    with pytest.raises(MP.ModeProjectError, match="at most"):
        MP.new_mode(project, "one too many")


def test_a_broken_mode_file_is_named_not_hidden(tmp_path):
    project = str(tmp_path)
    MP.new_mode(project, "Good")
    os.makedirs(os.path.join(project, "modes", "bad"))
    open(os.path.join(project, "modes", "bad", "mode.json"), "w").write("{not json")
    found, broken = MP.list_modes(project)
    assert [s for s, _ in found] == ["good"] and [s for s, _ in broken] == ["bad"]


def test_a_newer_format_is_refused():
    with pytest.raises(MP.ModeProjectError, match="newer"):
        MP.ModeSpec.from_json({"format": MP.FORMAT + 1, "name": "X"})


# ---- item 139: how often a mode can start ---------------------------------------------
def test_starts_default_adds_nothing_to_the_generated_file():
    """Any number of times and no wait are today's behaviour: the file carries neither
    key, so KAIJU RUSH's generated file is byte-for-byte what it was before item 139."""
    spec = _kaiju()
    assert (spec.starts, spec.cooldown) == ("unlimited", 0)
    text = MP.runtime_cfg(spec, "kaiju_rush")
    assert "starts" not in _keys(text) and "cooldown" not in _keys(text)
    assert MP.starts_cfg_lines(spec) == []
    spec.starts, spec.cooldown = "once_per_game", 20
    assert MP.runtime_cfg(spec, "kaiju_rush").startswith(text)          # only appended to


@pytest.mark.parametrize("starts, line", [
    ("once_per_game", "once_per_game"), ("once_per_ball", "once_per_ball"),
    (3, "3"), ("3", "3"), (1, "1"), (99, "99"),
])
def test_each_starts_policy_writes_its_line(starts, line):
    spec = _kaiju()
    spec.starts = starts
    k = _keys(MP.runtime_cfg(spec, "k"))
    assert k["starts"] == line and "cooldown" not in k


def test_cooldown_writes_its_line_only_when_set():
    spec = _kaiju()
    spec.cooldown = 20
    text = MP.runtime_cfg(spec, "k")
    assert _keys(text)["cooldown"] == "20" and "starts" not in _keys(text)
    assert "cooldown       20\n" in text                    # the file's key column
    spec.cooldown = 0
    assert "cooldown" not in _keys(MP.runtime_cfg(spec, "k"))


def test_starts_and_cooldown_round_trip_through_mode_json(tmp_path):
    project = str(tmp_path)
    for starts, cooldown in (("once_per_ball", 0), (4, 30), ("unlimited", 3600)):
        slug, spec = MP.new_mode(project, "Often %s" % starts)
        spec.starts, spec.cooldown = starts, cooldown
        path = MP.save(project, slug, spec)
        data = json.load(open(path, encoding="utf-8"))
        assert (data["starts"], data["cooldown"]) == (starts, cooldown)
        back = MP.load(path)
        assert (back.starts, back.cooldown) == (starts, cooldown) and back.extra == {}
    # a count or a wait written as text reads back as a number
    spec = MP.ModeSpec.from_json({"name": "X", "starts": "3", "cooldown": "15"})
    assert (spec.starts, spec.cooldown) == (3, 15)
    # a mode.json from before item 139 has neither key: today's behaviour
    spec = MP.ModeSpec.from_json({"name": "OLD"})
    assert (spec.starts, spec.cooldown) == ("unlimited", 0)


@pytest.mark.parametrize("starts, cooldown, words", [
    ("twice", 0, "How often it can start"), (0, 0, "How often it can start"),
    (100, 0, "How often it can start"), (True, 0, "How often it can start"),
    ("unlimited", -1, "wait after it ends"), ("unlimited", 3601, "wait after it ends"),
    ("unlimited", "soon", "wait after it ends"),
])
def test_validate_refuses_bad_starts_and_cooldown(starts, cooldown, words):
    spec = _kaiju()
    spec.starts, spec.cooldown = starts, cooldown
    problems = " ".join(MP.validate(spec))
    assert words in problems
    with pytest.raises(MP.ModeProjectError):
        MP.runtime_cfg(spec, "bad")


@pytest.mark.parametrize("starts, cooldown, words", [
    ("unlimited", 0, "Can start: any number of times"),
    ("once_per_game", 0, "Can start: once a game, for each player"),
    ("once_per_ball", 0, "Can start: once a ball, for each player"),
    (1, 0, "Can start: once a game, for each player"),
    (3, 0, "Can start: up to 3 times a game, for each player"),
    ("unlimited", 20, "Can start: any number of times; not again until 20 s after it ends"),
    ("once_per_ball", 5, "Can start: once a ball, for each player; not again until 5 s after it ends"),
    ("nope", 0, "Can start: (choose how often)"),
])
def test_starts_words(starts, cooldown, words):
    spec = _kaiju()
    spec.starts, spec.cooldown = starts, cooldown
    assert MP.starts_words(spec) == words


# ---- item 142: a cut from a film keeps where it came from, never the film -------------
_FILM = "D:/Films/Godzilla.2014.mp4"


def _film_cut(spec):
    spec.clip, spec.clip_file = "file", "clip.mp4"
    spec.clip_source, spec.clip_from, spec.clip_length = _FILM, 5700.0, 6.0
    spec.end_sound = "end.wav"
    spec.sound_source, spec.sound_from, spec.sound_length = _FILM, 5702.5, 4.0
    spec.screen_art, spec.art_source, spec.art_from = "art.png", _FILM, 5703.0
    spec.clip_crop, spec.art_crop = "fill", "letterbox"
    return spec


def test_film_cut_provenance_round_trips_and_old_files_load(tmp_path):
    spec = _film_cut(_kaiju())
    back = MP.ModeSpec.from_json(json.loads(json.dumps(spec.to_json())))
    assert back == spec and back.extra == {}
    assert (back.clip_source, back.clip_from, back.clip_length) == (_FILM, 5700.0, 6.0)
    assert (back.sound_from, back.sound_length, back.art_source, back.art_from) == (5702.5, 4.0, _FILM, 5703.0)
    assert (back.clip_crop, back.art_crop) == ("fill", "letterbox")
    old = {k: v for k, v in _kaiju().to_json().items()
           if k not in ("clip_source", "clip_from", "clip_length", "sound_source", "sound_from",
                        "sound_length", "art_source", "art_from", "clip_crop", "art_crop")}
    loaded = MP.ModeSpec.from_json(old)
    assert (loaded.clip_source, loaded.clip_from, loaded.sound_length, loaded.art_source) == ("", 0.0, 0.0, "")
    assert (loaded.clip_crop, loaded.art_crop) == ("", "")
    assert loaded.extra == {}


def test_film_cut_provenance_never_reaches_the_runtime_file():
    plain = _kaiju()
    plain.clip, plain.clip_file, plain.end_sound, plain.screen_art = "file", "clip.mp4", "end.wav", "art.png"
    cut = _film_cut(_kaiju())
    assert MP.runtime_cfg(cut, "k") == MP.runtime_cfg(plain, "k")
    assert MP.runtime_cfg(cut, "k", sound_key="45df2b8b01000084") == MP.runtime_cfg(
        plain, "k", sound_key="45df2b8b01000084")
    assert "Godzilla" not in MP.runtime_cfg(cut, "k")


def test_film_cut_validation(tmp_path):
    folder = str(tmp_path)
    for name in ("clip.mp4", "end.wav", "art.png"):
        (tmp_path / name).write_bytes(b"x")
    spec = _film_cut(_kaiju())
    assert MP.validate(spec, folder) == []
    spec.clip_length, spec.sound_from, spec.art_from = 31, -1, "later"
    problems = " ".join(MP.validate(spec, folder))
    assert "clip cut from a film runs up to 30 seconds" in problems
    assert "sound's time in the film is 0:00 or later" in problems
    assert "picture's time in the film is 0:00 or later" in problems
    spec = _film_cut(_kaiju())
    spec.clip_crop = "stretch"
    assert MP.validate(spec, folder) == ["The clip's crop is letterbox or fill."]
    spec = _film_cut(_kaiju())
    (tmp_path / "Godzilla.2014.mp4").write_bytes(b"a whole film")
    problems = MP.validate(spec, folder)
    assert problems == ["The film Godzilla.2014.mp4 is in the mode's folder; a mode keeps only the cut."]
    spec.clip_source = r"D:\Films\Godzilla.2014.mp4"             # a Windows path, read anywhere
    assert MP.validate(spec, folder) == problems
    assert MP.validate(spec, None) == []


# ---- item 140: stacking with the game's own modes -----------------------------------
def test_stack_no_is_written_only_when_asked_and_round_trips(tmp_path):
    """Item 140: a mode that must not run beside the game's own battle or multiball carries
    `stack no`; the default (stack yes, how every mode ran before) adds nothing, so a file
    generated today is byte-for-byte the file generated before the key existed."""
    spec = _kaiju()
    assert spec.stack is True
    before = MP.runtime_cfg(spec, "kaiju_rush")
    assert "stack" not in _keys(before)
    assert not any(line.startswith("stack") for line in before.splitlines())
    spec.stack = False
    after = MP.runtime_cfg(spec, "kaiju_rush")
    assert _keys(after)["stack"] == "no"
    assert after == before + "stack          no\n"
    assert "stack" not in _keys(MP.runtime_cfg(MP.example("KAIJU RUSH"), "kaiju_rush"))

    project = str(tmp_path)
    slug, s = MP.new_mode(project, "Waits Its Turn")
    s.stack = False
    MP.save(project, slug, s)
    path = os.path.join(MP.mode_folder(project, slug), MP.MODE_FILE)
    assert json.load(open(path, encoding="utf-8"))["stack"] is False
    assert MP.load(path).stack is False
    # a mode.json written before the key existed opens as stack yes
    assert MP.ModeSpec.from_json({"format": 1, "name": "OLD"}).stack is True


# ---- item 141: the Advanced section's parameters ------------------------------------------
def test_advanced_parameters_at_their_defaults_change_no_byte():
    """A mode that never opens Advanced generates exactly what it did before item 141, so
    KAIJU RUSH (the mode that ran on a machine) is byte-identical."""
    spec = _kaiju()
    assert (spec.award_ladder, spec.shot_award, spec.end_shot, spec.clip_both, spec.callout_at,
            spec.restore_after) == ("rising", [], "", {}, [], 6)
    assert MP.parameter_lines(spec, "kaiju_rush", MP.GODZILLA_PRO_1_15) == []
    text = MP.runtime_cfg(spec, "kaiju_rush")
    for key in ("award_ladder", "shot_award", "end_shot", "clip_end"):
        assert key not in _keys(text)
    assert _keys(text)["restore_after"] == "6"
    assert MP.runtime_cfg(MP.example("KAIJU RUSH"), "kaiju_rush") == text


def test_advanced_parameters_generate_the_runtime_lines():
    spec = _kaiju()
    spec.award_ladder = "fixed"
    spec.shot_award = [["Building", 5000000], ["Shield target right", "3,000,000"]]
    spec.end_shot = "Shield target left"
    spec.clip_both = {"clip": "title", "title": "OVER", "seconds": 3}
    spec.callout_at = [[20, 1295], [25, 1291]]
    spec.restore_after = 9
    text = MP.runtime_cfg(spec, "param_test")
    k = _keys(text)
    assert k["award_ladder"] == "fixed" and k["end_shot"] == "0x80000000"
    assert [ln.split()[1:] for ln in text.splitlines() if ln.startswith("shot_award")] == [
        ["0x00400000", "5000000"], ["0x100000000", "3000000"]]
    assert k["clip_start"] == "PadMode_param_test_Clip" and k["clip_end"] == "PadMode_param_test_Clip2"
    assert k["callout_at"] == [["10", "1291"], ["20", "1295"], ["25", "1291"]]
    assert k["restore_after"] == "9"
    assert MP.second_clip_name("param_test") == "PadMode_param_test_Clip2"
    # the same clip at both ends plays the first clip's name again; a clip at the end
    # puts the second at the start
    spec.clip_both, spec.clip_when = {"clip": "same"}, "end"
    k = _keys(MP.runtime_cfg(spec, "param_test"))
    assert k["clip_end"] == k["clip_start"] == "PadMode_param_test_Clip"
    assert len(text.encode()) < 4096


def test_advanced_parameters_survive_a_save_and_load(tmp_path):
    project = str(tmp_path)
    slug, spec = MP.new_mode(project, "Param Test")
    spec.shot_award, spec.end_shot = [["Building", 5000000]], "Big loop"
    spec.clip_both, spec.callout_at, spec.restore_after = {"clip": "same"}, [[8, 1291]], 8
    MP.save(project, slug, spec)
    back = MP.load(os.path.join(MP.mode_folder(project, slug), MP.MODE_FILE))
    assert (back.shot_award, back.end_shot, back.clip_both, back.callout_at, back.restore_after) == (
        [["Building", 5000000]], "Big loop", {"clip": "same"}, [[8, 1291]], 8)
    assert back.extra == {}


def test_advanced_parameters_validate_naming_every_problem(tmp_path):
    spec = _kaiju()
    spec.award_ladder = "steep"
    spec.shot_award = [["Flipper", 5], ["Building", 0], ["Building", 7], ["x"]]
    spec.end_shot = "Drain"
    spec.clip_both = {"clip": "file", "file": "gone.mp4"}
    spec.callout_at = [[30, 1291], [5, 0], [1, 2], [3, 2030]] + [[2, 1291]] * 5
    spec.restore_after = 0
    problems = " ".join(MP.validate(spec, str(tmp_path)))
    for words in ("rising or fixed", "'Flipper' to pay", "Building's own points", "Building has its own points twice",
                  "[shot, points]", "'Drain' to end", "gone.mp4", "30 seconds left", "id 0",
                  "at most 7 callouts", "1 to 60 seconds", "id 2030 is not a callout number (Godzilla Pro 1.15 has 1 to 2029)"):
        assert words in problems, words
    spec = _kaiju()
    spec.clip, spec.clip_both = "none", {"clip": "same"}
    assert "choose the first clip" in " ".join(MP.validate(spec))
    spec.clip, spec.clip_both = "title", {"clip": "title", "seconds": 99}
    assert "1 to 30 seconds" in " ".join(MP.validate(spec))
    assert MP.callout_choices(MP.GODZILLA_PRO_1_15) == [("Ten seconds left", 1291), ("Time is up", 1295)]


def test_advanced_parameters_validate_hand_edited_shapes_without_raising():
    """A shot name that is not text (hand-edited JSON) is named, not a TypeError; restore_after
    is checked only with the mode's own screen, the only time runtime_cfg writes it."""
    spec = _kaiju()
    spec.shot_award = [[["Building"], 5], [{"a": 1}, 2]]
    spec.end_shot = ["Shield target left"]
    problems = " ".join(MP.validate(spec))
    assert problems.count("A per-shot award is [shot, points].") == 2
    assert "no shot called ['Shield target left'] to end the mode" in problems
    spec = _kaiju()
    spec.restore_after = 0
    assert "1 to 60 seconds" in " ".join(MP.validate(spec))
    spec.screen = False
    assert MP.validate(spec) == []
    assert "restore_after" not in MP.runtime_cfg(spec, "kaiju_rush")


# ---- item 147: a mode that starts or ends on one of the game's events ---------------------
def test_an_event_start_replaces_the_trigger_line():
    """An event start writes `starts_on event <name>` and NO trigger line, so a mode.so
    older than events logs the file NOT VALID instead of starting it on a shot."""
    spec = _kaiju()
    spec.starts_on, spec.ends_on = "event ball_start", "clock"
    assert MP.validate(spec) == []
    text = MP.runtime_cfg(spec, "kaiju_rush")
    cfg = _keys(text)
    assert "trigger" not in cfg
    assert cfg["starts_on"] == "event ball_start" and cfg["ends_on"] == "clock"
    assert text.splitlines()[2] == "starts_on      event ball_start"   # right under the name


def test_a_shot_start_and_a_drain_end_write_what_they_wrote_before():
    spec = _kaiju()
    before = MP.runtime_cfg(spec, "kaiju_rush")
    spec.starts_on, spec.ends_on = "shot", "drain"
    assert MP.runtime_cfg(spec, "kaiju_rush") == before
    assert "starts_on" not in before and "ends_on" not in before and "trigger " in before


def test_an_event_end_is_written_and_events_are_checked_against_the_title():
    spec = _kaiju()
    spec.starts_on, spec.ends_on = "event multiball_start", "event multiball_end"
    assert MP.validate(spec) == []
    assert _keys(MP.runtime_cfg(spec, "x"))["ends_on"] == "event multiball_end"
    spec.starts_on = "event made_up"
    assert any("no event 'made_up' to start on" in p for p in MP.validate(spec))
    spec.starts_on, spec.ends_on = "event", "sometimes"
    problems = " ".join(MP.validate(spec))
    assert "Pick the event that starts" in problems and "ends on the drain" in problems
    assert set(MP.GODZILLA_PRO_1_15.events) >= {"ball_start", "multiball_start", "skill_shot"}
    assert all(e in MP.EVENT_LABELS for e in MP.GODZILLA_PRO_1_15.events)


def test_starts_on_and_ends_on_round_trip_and_default_for_an_older_file():
    spec = MP.ModeSpec(name="X", starts_on="event skill_shot", ends_on="event ball_end")
    back = MP.ModeSpec.from_json(json.loads(json.dumps(spec.to_json())))
    assert (back.starts_on, back.ends_on) == ("event skill_shot", "event ball_end")
    old = MP.ModeSpec.from_json({"format": 1, "name": "OLD"})
    assert (old.starts_on, old.ends_on) == ("shot", "drain")


# ---- item 157: the display priority and the lit shots ------------------------------------------
def test_a_display_priority_and_lit_shots_write_their_lines_and_nothing_at_the_defaults():
    spec = MP.ModeSpec(name="PLAIN")
    base = MP.runtime_cfg(spec, "plain")
    assert "priority" not in base and "light_shots" not in base          # every older file, byte for byte
    spec = MP.ModeSpec(name="LIT", priority=180, light_shots="#00E6FF", light_shots_pattern="chase")
    cfg = MP.runtime_cfg(spec, "lit")
    assert "\npriority       180\n" in cfg and "\nlight_shots    00e6ff chase\n" in cfg
    back = MP.ModeSpec.from_json(json.loads(json.dumps(spec.to_json())))
    assert (back.priority, back.light_shots, back.light_shots_pattern) == (180, "#00E6FF", "chase")
    assert MP.ModeSpec.from_json({"format": 1, "name": "OLD"}).priority == 0


@pytest.mark.parametrize("field,value,words", [
    ("priority", 256, "display priority is 0 (none) to 255"),
    ("priority", -1, "display priority is 0 (none) to 255"),
    ("priority", "high", "display priority is 0 (none) to 255"),
    ("light_shots", "orange", "not a colour like #ff6000"),
    ("light_shots_pattern", "strobe", "solid, blink, pulse or chase"),
])
def test_a_bad_display_priority_or_lit_shots_value_is_named(field, value, words):
    spec = MP.ModeSpec(name="BAD")
    setattr(spec, field, value)
    assert any(words in p for p in MP.validate(spec)), MP.validate(spec)

# ---- the family's one version comparison, and which card a project is for ----------------
def test_version_key_is_one_tuple_of_ints_for_every_spelling():
    """The three private copies (mode_project, mode_tryit, mode_runtime) are one function: a
    card's index name, a profile's port version and a port file's name compare by VALUE, so
    jaws_le's ``1_02_0`` on the card is the ``1.02`` in the port's name."""
    for spelling in ("1.16.0", "1.16", "1_16_0", "1_16", "v1.16.0", "1.16.0.0"):
        assert MP.version_key(spelling) == (1, 16), spelling
    assert MP.version_key("1_02_0") == MP.version_key("1.02") == (1, 2)
    assert MP.version_key("1.15.1") == (1, 15, 1) != MP.version_key("1.15")
    assert MP.version_key("") == MP.version_key(None) == ()
    assert MP._version_key is MP.version_key                       # the old name still works
    from pinball_decryptor.plugins.stern import mode_runtime as MR
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    assert not hasattr(MR, "_version_key") and not hasattr(MT, "_version_key")
    assert MR.port_file("jaws_le", "1.02.0") and MR.port_file("jaws_le", "1_02_0")
    assert MR.port_file("jaws_le", "1.02.0") == MR.port_file("jaws_le", "1.02")
    assert MR.port_file("jaws_le", "1.2.1") is None


@pytest.mark.usefixtures("preview_modes_on")
def test_the_no_project_sentence_is_one_for_the_family():
    assert MP.NO_PROJECT_HELP.startswith("Open or extract a card project first (Extract tab).")
    from pinball_decryptor.plugins.stern import code_modes as CM
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from pinball_decryptor.plugins.stern import mode_write as MW
    with pytest.raises(MT.TryItError, match="Extract tab"):
        MT.new_code_mode("", "Blitz")
    with pytest.raises(CM.CodeModeError, match="Extract tab"):
        CM.add_example("", CM.EXAMPLES[0]["name"])
    with pytest.raises(MW.ModeWriteError, match="Extract tab"):
        MW.build_tryit_set("", "card.raw", "base")


def _record(project, name, card_version=None, input_path=None):
    rec = {"input_path": input_path or ("D:\\cards\\" + name), "input_name": name,
           "size": 1, "mtime": 1}
    if card_version:
        rec["card_version"] = card_version
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f)


def _anchor(project, image):
    from pinball_decryptor.core import project_file
    project_file.save(os.path.join(project, ".pinproj"), manufacturer_key="stern",
                      paths={"write_original": image, "write_assets": project},
                      extract_options={})


def test_the_extract_record_wins_over_the_anchor_even_when_its_name_does_not_parse(
        tmp_path, monkeypatch):
    """The card the project was MEASURED on is the extract record's, whatever it is called.
    A renamed record used to lose to the anchor's stock image when that parsed, so a set
    could be prepared for a card the project was never measured on. Now the record's image
    is the answer with ``game_dir`` "" until probed - project_card never opens it - and the
    anchor's paths count only when there is no record at all."""
    project = str(tmp_path)
    renamed = str(tmp_path / "my card.raw")
    with open(renamed, "wb") as f:
        f.write(bytes(1024))
    _record(project, "my card.raw", "1.16.0", input_path=renamed)
    _anchor(project, r"D:\Pinball\turtles_pro-1_58_0.Release.8G.sdcard.raw")
    card = MP.project_card(project)
    assert (card.image, card.game_dir, card.version) == (renamed, "", "1.16.0")
    # the probe fills it in (off the UI thread), and the record's exact version is kept
    monkeypatch.setitem(MP._PROBED, MP._probe_key(renamed), ("godzilla_le", "1.16.0"))
    card = MP.project_card(project)
    assert (card.game_dir, card.version, card.source) == ("godzilla_le", "1.16.0",
                                                          "the card's own index")
    # a record whose name parses is still the record, with its exact version
    _record(project, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    card = MP.project_card(project)
    assert (card.game_dir, card.version) == ("godzilla_le", "1.16.0")
    assert card.source == "the extract's record of the card"
    # no record: the anchor's paths, as before
    os.remove(os.path.join(project, ".extract_source.json"))
    card = MP.project_card(project)
    assert (card.game_dir, card.version) == ("turtles_pro", "1.58.0")
    assert card.source == "the card's file name"


def test_project_cards_names_the_two_roles_without_opening_an_image(tmp_path, monkeypatch):
    """made_for is the project's card; try_on is the image handed in - the live Emulate
    card, never the anchor's copy - known by its Stern name or an earlier probe, else ""."""
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _record(project, "godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw", "1.15.0")

    def never(path):
        raise AssertionError("project_cards must not open an image")
    monkeypatch.setattr(MP, "probe_card_title", never)
    made_for, try_on = MP.project_cards(project)
    assert made_for.game_dir == "godzilla_pro" and try_on is None
    made_for, try_on = MP.project_cards(project, r"E:\built\godzilla_le-1_16_0_built.raw")
    assert (made_for.game_dir, made_for.version) == ("godzilla_pro", "1.15.0")
    assert (try_on.game_dir, try_on.version) == ("godzilla_le", "1.16.0")
    assert try_on.image == r"E:\built\godzilla_le-1_16_0_built.raw"
    renamed = str(tmp_path / "picked.raw")
    with open(renamed, "wb") as f:
        f.write(bytes(64))
    _made, try_on = MP.project_cards(project, renamed)
    assert (try_on.game_dir, try_on.version, try_on.image) == ("", "", renamed)
    monkeypatch.setitem(MP._PROBED, MP._probe_key(renamed), ("turtles_pro", "1.59.0"))
    _made, try_on = MP.project_cards(project, renamed)
    assert (try_on.game_dir, try_on.version) == ("turtles_pro", "1.59.0")
    assert MP.project_cards(str(tmp_path / "bare"), renamed)[0] is None



def test_a_save_survives_a_reader_holding_the_file(tmp_path, monkeypatch):
    """On Windows a reader holding mode.json (OneDrive, antivirus, the
    indexer) makes the swap-in fail for a moment; the save retries instead of
    losing the edit."""
    spec = _kaiju()
    MP.save(str(tmp_path), "kaiju_rush", spec)
    real = os.replace
    fails = {"n": 2}

    def flaky(src, dst):
        if fails["n"]:
            fails["n"] -= 1
            raise PermissionError(5, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    spec2 = MP.ModeSpec.from_json(dict(spec.to_json(), name="SAVED ANYWAY"))
    path = MP.save(str(tmp_path), "kaiju_rush", spec2)
    assert fails["n"] == 0
    assert MP.load(path).name == "SAVED ANYWAY"
    assert not os.path.exists(path + ".tmp")
