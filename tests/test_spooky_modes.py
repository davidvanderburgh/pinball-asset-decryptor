"""Custom modes on Spooky's Unity titles (PAD-1417): tools/spooky_emu/modes/mkspkmodes.py (the
checker, the pad/ folder, the update build) and plugins/spooky/custom_modes.py (the app's half).
The runtime itself (PadModes.cs) is proven on the Spooky rig (docs/plans/spooky_modes.md); these
hold the files around it to what that proof ran.
"""
import io
import json
import os
import re
import tarfile

import pytest

from pinball_decryptor.plugins.spooky import custom_modes as SM

LABEL = "scooby_doo-2025.12.01.09"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CS = os.path.join(ROOT, "tools", "spooky_emu", "modes", "unity", "PadModes.cs")
SWAY = ("set $mod Mod4\n"
        "assign [class=\"main.x86_64\"] 1\n"
        "exec --no-startup-id /game/code/uptest/main.x86_64\n"
        "#exec --no-startup-id /game/code/uptest/topper/topper.x86_64\n")
I3 = "exec feh --bg-fill /game/code/uptest/splash.png\nexec --no-startup-id /game/code/uptest/main.x86_64\n"


@pytest.fixture
def mk():
    return SM.mk()


@pytest.fixture
def port():
    return SM.load_port(LABEL)


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_SPOOKY_MODES_DIR", str(tmp_path / "modes"))
    return SM.title_dir(LABEL)


def _mode(folder, fn, text):
    with open(os.path.join(folder, fn), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ------------------------------------------------------------------ the port report
def test_the_port_report_is_the_running_games(port, mk):
    assert port["title"] == "Scooby-Doo" and port["engine"] == "unity"
    # read by the runtime in the game: its switch symbols (get_switch_name), callouts, fonts
    assert len(port["switches"]) == 80 and "right_inlane" in port["switches"]
    assert port["switch_labels"]["right_inlane"] == "RIGHT INLANE"
    assert len(port["sounds"]) == 1437 and port["sound_paths"]["daphne_jackpot"].endswith("/daphne_jackpot")
    assert "GhoulFriAOE SDF" in port["fonts"]
    # measured in the game: score_points(1000) scored 10,000; Game.score_points rounds to 100
    assert port["points_scale"] == 10 and port["points_round"] == 100
    # the starter picks are the game's own names
    d = port["defaults"]
    assert set(d["start"].split() + d["shots"].split()) <= set(port["switches"])
    assert {d[k] for k in ("sound_start", "sound_shot", "sound_complete")} <= set(port["sounds"])
    so, dll = mk.runtime_files(port)
    assert os.path.isfile(so) and os.path.isfile(dll)


def test_every_key_the_checker_takes_is_one_the_runtime_reads(mk):
    """A key the check accepts but PadModes.cs never reads would be silently ignored."""
    with open(CS, encoding="utf-8") as f:
        src = f.read()
    read = set(re.findall(r'(?:Get\(|SwitchList\(m, |Sound\(m, |Coil\(m, |Lines\(m, )"([a-z_]+)"', src))
    # PAD-1508: penalty runs only where the game's score call takes points away (the check refuses it here)
    refused = {"penalty"} if "unity" not in mk.PENALTY_ENGINES else set()
    assert set(mk.KEYS) - {"name", "title"} - refused <= read, set(mk.KEYS) - read - refused
    # and every other JJP key is refused by name
    assert "code" in mk.NOT_YET and "game_modes" in mk.NOT_YET and "points" not in mk.NOT_YET
    assert "lamps" not in mk.NOT_YET and "multiball" not in mk.NOT_YET and "start_on" not in mk.NOT_YET


# ------------------------------------------------------------------ the check
def test_the_starter_modes_pass_the_check(folder, port, mk):
    modes, problems = mk.check_modes(folder, port)
    assert problems == []
    assert [m["name"] for m in modes] == ["Snack Attack", "Target Rush"]


def test_the_check_names_what_the_game_would_not_take(folder, port, mk):
    _mode(folder, "9_bad.mode", "name = Bad\nstart = right_inlane nosuch_switch\nshots = left_sling\n"
                                "points = 250030\ncode = rules\nsound_shot = no_such_callout\n"
                                "wibble = 1\n")
    _mode(folder, "9_nostart.mode", "name = Never\ncomplete = 3\n")
    _modes, problems = mk.check_modes(folder, port)
    text = "\n".join(problems)
    assert "nosuch_switch" in text
    assert "rounds every award to 100, so it would score 250,000" in text
    assert "code is not on Spooky games yet" in text
    assert "no_such_callout" in text
    assert "unknown key wibble" in text
    assert "9_nostart.mode: no start rule" in text
    assert "complete = 3 but no shots" in text


# ------------------------------------------------------------------ the launch line
def test_the_launch_line_preloads_the_runtime(mk):
    text, n = mk.patch_launch(SWAY)
    assert n == 1
    assert "exec --no-startup-id env LD_PRELOAD=/game/code/uptest/pad/padunity.so /game/code/uptest/main.x86_64\n" in text
    assert "#exec --no-startup-id /game/code/uptest/topper/topper.x86_64" in text     # left alone
    assert 'assign [class="main.x86_64"] 1' in text                                     # not a launch line
    again, n2 = mk.patch_launch(text)
    assert again == text and n2 == 1                                                    # built twice: once
    # a launch line with an env of its own keeps it; another preload stays after ours
    other, _ = mk.patch_launch("exec env FOO=1 LD_PRELOAD=/x.so /game/code/uptest/main.x86_64 -a\n")
    assert other == "exec env FOO=1 LD_PRELOAD=/game/code/uptest/pad/padunity.so:/x.so /game/code/uptest/main.x86_64 -a\n"
    crlf, _ = mk.patch_launch(I3.replace("\n", "\r\n"))
    assert crlf.count("\r\n") == 2 and "LD_PRELOAD" in crlf


# ------------------------------------------------------------------ build and stage
def _tar(path, members):
    with tarfile.open(path, "w:gz") as t:
        for name, data in members:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o755
            t.addfile(ti, io.BytesIO(data))


def _read(path):
    out = {}
    with tarfile.open(path, "r:gz") as t:
        for ti in t:
            out[ti.name] = t.extractfile(ti).read() if ti.isfile() else None
    return out


def test_build_puts_the_runtime_and_modes_in_the_stock_update(tmp_path, folder, port, mk):
    stock = tmp_path / "stock" / "v2025.12.01.09.scooby"
    stock.parent.mkdir()
    _tar(str(stock), [("./main.x86_64", b"ELF"), ("./sway_config", SWAY.encode()), ("./i3_config", I3.encode()),
                      ("./version.txt", b"v2025.12.01.09\n"), ("./pad/old.mode", b"from an older build")])
    out = tmp_path / "new" / "v2025.12.01.09.scooby"
    out.parent.mkdir()
    mk.build(str(stock), folder, str(out), port, log=lambda s: None)
    got = _read(str(out))
    assert got["./main.x86_64"] == b"ELF"
    for f in ("./sway_config", "./i3_config"):
        assert b"env LD_PRELOAD=/game/code/uptest/pad/padunity.so /game/code/uptest/main.x86_64" in got[f]
    assert "./pad/old.mode" not in got                       # an older build's pad/ is replaced
    so, dll = mk.runtime_files(port)
    assert got["pad/padunity.so"] == open(so, "rb").read()
    assert got["pad/PadModes.dll"] == open(dll, "rb").read()
    assert b"points_scale = 10" in got["pad/modes/title.cfg"]
    assert b"name = Snack Attack" in got["pad/modes/1_snack_attack.mode"]
    assert not os.path.exists(str(out) + ".partial")
    # never over the stock one; never an update without a launch line; never with problems
    with pytest.raises(mk.Refused):
        mk.build(str(stock), folder, str(stock), port, log=lambda s: None)
    bare = tmp_path / "bare.scooby"
    _tar(str(bare), [("main.x86_64", b"ELF")])
    with pytest.raises(mk.Refused, match="no launch line"):
        mk.build(str(bare), folder, str(tmp_path / "x.scooby"), port, log=lambda s: None)
    assert not os.path.exists(str(tmp_path / "x.scooby.partial"))
    _mode(folder, "9_bad.mode", "name = Bad\nstart = nosuch\n")
    with pytest.raises(mk.Refused, match="problems"):
        mk.build(str(stock), folder, str(tmp_path / "y.scooby"), port, log=lambda s: None)


def test_stage_is_the_try_it_folder(tmp_path, folder, port, mk):
    pad = mk.stage(folder, str(tmp_path / "try" / "pad"), port)
    names = sorted(os.path.relpath(os.path.join(d, f), pad).replace("\\", "/")
                   for d, _s, fs in os.walk(pad) for f in fs)
    assert names == ["PadModes.dll", "README.txt", "modes/1_snack_attack.mode", "modes/2_target_rush.mode",
                     "modes/title.cfg", "padunity.so"]
    cfg = open(os.path.join(pad, "modes", "title.cfg"), encoding="utf-8").read()
    assert cfg.count("points_scale = 10") == 1
    # the scale is the game's: a person's points_scale line is refused, never staged
    with open(os.path.join(folder, "title.cfg"), "a", encoding="utf-8") as f:
        f.write("points_scale = 3\n")
    assert any("points_scale is the game's own" in p for p in mk.check_modes(folder, port)[1])
    assert "points_scale = 3" not in mk.title_cfg_text(folder, port)


# ------------------------------------------------------------------ the app's half
def test_the_card_is_the_title(tmp_path):
    f = tmp_path / "v2025.12.01.09.scooby"
    f.write_bytes(b"\x1f\x8b")
    assert SM.label_for_card(str(f)) == LABEL
    other = tmp_path / "v2024.01.01.01.scooby"
    other.write_bytes(b"\x1f\x8b")
    assert SM.label_for_card(str(other)) == ""          # a version no port report knows
    assert SM.label_for_card("") == ""
    t = {x["label"]: x for x in SM.titles()}[LABEL]
    assert t["can_run"] and t["name"] == "Scooby-Doo 2025.12.01.09" and t["counts"]["sounds"] == 1437


def test_a_title_folder_is_seeded_and_edited(folder):
    assert sorted(SM.mode_files(LABEL)) == ["1_snack_attack.mode", "2_target_rush.mode"]
    assert SM.read_title(LABEL)["font_title"] == "GhoulFriAOE SDF"
    fn = SM.new_mode(LABEL, "Ghost Chase")
    assert fn == "3_ghost_chase.mode"
    v = SM.read_mode(LABEL, fn)
    assert v["start"] == "right_inlane left_inlane" and v["sound_start"] == "daphne_scooby_doo_where_are_you"
    with open(os.path.join(folder, fn), "rb") as f:
        assert b"\r\n" not in f.read()                  # the machine is Linux
    dup = SM.duplicate_mode(LABEL, fn)
    assert SM.read_mode(LABEL, dup)["name"] == "Ghost Chase copy"
    SM.delete_mode(LABEL, dup)
    assert dup not in SM.mode_files(LABEL)
    with pytest.raises(ValueError):
        SM.new_mode(LABEL, "x", how="blocks")
    assert SM.check(LABEL)[1] == []


def test_a_callout_is_heard_from_the_extract(tmp_path, port):
    d = tmp_path / "ex" / "AudioClip"
    d.mkdir(parents=True)
    (d / "daphne_jackpot.wav").write_bytes(b"RIFF")
    idx = SM.sound_index(str(tmp_path / "ex"))
    assert SM.sound_file(idx, "daphne_jackpot", port).endswith("daphne_jackpot.wav")
    assert SM.sound_file(idx, "fred_jackpot", port) == ""


def test_the_write_tab_carries_the_modes(tmp_path, folder):
    """Write packs an extract folder: the person's modes for its title go in with the runtime,
    the launch lines preload it, and an extract's own pad/ is replaced."""
    from pinball_decryptor.plugins.spooky import formats
    ex = tmp_path / "extract"
    ex.mkdir()
    (ex / ".spooky_meta").write_text(json.dumps({"game": "Scooby-Doo", "format": "tar_gz", "ext": ".scooby"}))
    (ex / "version.txt").write_text("v2025.12.01.09\n")
    (ex / "main.x86_64").write_bytes(b"ELF")
    (ex / "sway_config").write_text(SWAY)
    (ex / "i3_config").write_text(I3)
    (ex / "pad").mkdir()
    (ex / "pad" / "stale.txt").write_text("old")
    assert SM.label_for_extract(str(ex)) == LABEL
    pm = SM.write_pad_modes(LABEL)
    out = tmp_path / "v2025.12.01.09.scooby"
    formats.create_tar_gz(str(ex), str(out), pad_modes=pm)
    got = _read(str(out))
    assert b"LD_PRELOAD=/game/code/uptest/pad/padunity.so" in got["sway_config"]
    assert b"LD_PRELOAD=/game/code/uptest/pad/padunity.so" in got["i3_config"]
    assert "pad/modes/1_snack_attack.mode" in got and "pad/padunity.so" in got
    assert not any(n.startswith("pad/stale") or n == os.path.join("pad", "stale.txt") for n in got)
    assert got["main.x86_64"] == b"ELF" and ".spooky_meta" not in got
    # no modes: nothing changes; modes with problems: refused with the check's words
    _mode(folder, "9_bad.mode", "name = Bad\nstart = nosuch\n")
    with pytest.raises(ValueError, match="nosuch"):
        SM.write_pad_modes(LABEL)
    for fn in SM.mode_files(LABEL):
        os.unlink(os.path.join(folder, fn))
    assert SM.write_pad_modes(LABEL) is None
