"""Custom modes on Looney Tunes, Spooky's Godot title (PAD-1419): the Godot half of
tools/spooky_emu/modes/mkspkmodes.py (the runtime's files, override.cfg, the plain-tar build, the
port report) and of plugins/spooky/custom_modes.py and formats.py (the app, Write).  The runtime
itself (godot/pad_modes.gd) is proven on the Spooky rig (docs/plans/spooky_modes.md); these hold
the files around it to what that proof ran.
"""
import io
import json
import os
import re
import tarfile

import pytest

from pinball_decryptor.plugins.spooky import custom_modes as SM

LABEL = "legends_of_tera-2025.10.08"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = os.path.join(ROOT, "tools", "spooky_emu", "modes")
GD = os.path.join(MODES, "godot", "pad_modes.gd")
OVERRIDE = '[autoload]\n\nPadModes="*/game/code/uptest/pad/pad_modes.gd"\n'


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


def _tar(path, members, gz=False):
    with tarfile.open(path, "w:gz" if gz else "w") as t:
        for name, data in members:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o755
            t.addfile(ti, io.BytesIO(data))


def _read(path):
    out = {}
    with tarfile.open(path, "r:*") as t:
        for ti in t:
            out[ti.name] = t.extractfile(ti).read() if ti.isfile() else None
    return out


# ------------------------------------------------------------------ the port report
def test_the_port_report_is_the_running_games(port, mk):
    assert port["engine"] == "godot" and port["title"] == "Looney Tunes" and port["update_ext"] == ".looney"
    assert port["game_title"] == "LOONEY TUNES" and port["game_version"] == "2025.10.08"
    # measured in the game: Game.score(1000) scored 1000; the game rounds to 10
    assert port["points_scale"] == 1 and port["points_round"] == 10
    assert len(port["switches"]) == 96 and port["switch_ids"]["inlane_left"] == 22
    assert port["switch_ids"]["spinner"] == 18 and port["switch_labels"]["spinner"] == "SPINNER"
    assert len(port["sounds"]) == 1101 and port["voice_lines"] == 918
    assert port["sound_paths"]["bugs_hurry1"].endswith(".wav")
    assert "CCHeroSandwichMeat" in port["fonts"] and "Truculenta-Bold" in port["fonts"]
    assert len(port["game_modes"]) == 68
    for k, v in port["defaults"].items():
        table = "switches" if k in ("start", "shots") else "sounds"
        assert set(v.split()) <= set(port[table]), k
    assert mk.runtime_files(port) == (GD,)


def test_every_key_the_checker_takes_is_one_the_runtime_reads(mk):
    """A key the check accepts but pad_modes.gd never reads would be silently ignored."""
    with open(GD, encoding="utf-8") as f:
        src = f.read()
    read = set(re.findall(r'(?:cfg\.get\(|_sound\(m, )"([a-z_]+)"', src))
    # keys read in a loop: for k in ["coil_start", ...]: ... cfg.get(k
    for group in re.findall(r'for k in \[([^\]]+)\]:\s+var w := _words\(cfg\.get\(k', src):
        read |= set(re.findall(r'"([a-z_]+)"', group))
    assert set(mk.KEYS) - read == set(), set(mk.KEYS) - read


def test_make_port_takes_the_runtimes_report(mk):
    raw = {"engine": "godot", "game_title": "LOONEY TUNES", "game_version": "2025.03.01",
           "switches": ["spinner"], "sounds": ["a"], "points_scale_measured": {"asked": 1000, "scored": 1000, "multiplier": 1}}
    p = mk.make_port(raw, "legends_of_tera-2025.03.01", "Looney Tunes", ".looney")
    assert p["points_scale"] == 1 and p["points_round"] == 10 and p["runtime_script"] == "pad_modes.gd"
    assert p["version"] == "2025.03.01" and "points_scale_measured" not in p
    with pytest.raises(mk.Refused, match="not 2025.10.08"):
        mk.make_port(raw, LABEL, "Looney Tunes", ".looney")
    raw["points_scale_measured"]["multiplier"] = 2
    with pytest.raises(mk.Refused, match="multiplier"):
        mk.make_port(raw, "legends_of_tera-2025.03.01", "Looney Tunes", ".looney")
    del raw["points_scale_measured"]
    with pytest.raises(mk.Refused, match="no points"):
        mk.make_port(raw, "legends_of_tera-2025.03.01", "Looney Tunes", ".looney")


# ------------------------------------------------------------------ the check
def test_the_starter_modes_pass_the_check(folder, port, mk):
    modes, problems = mk.check_modes(folder, port)
    assert problems == [] and [m["name"] for m in modes] == ["Carrot Chase", "Spinner Frenzy"]


def test_the_check_names_what_the_game_would_not_take(folder, port, mk):
    _mode(folder, "9_bad.mode", "name = Bad\nstart = spinner\nshots = nosuch\npoints = 1005\n"
                                "sound_start = daphne_jackpot\nfont_title = Comic Sans\nlamps = X\n")
    _modes, problems = mk.check_modes(folder, port)
    text = "\n".join(problems)
    assert "nosuch" in text                                     # not a Looney Tunes switch
    assert "rounds every award to 10, so it would score 1,000" in text
    assert "daphne_jackpot" in text                             # a Scooby-Doo callout
    assert "Comic Sans" in text
    assert "not one of Looney Tunes's lamps: X" in text


# ------------------------------------------------------------------ the update
def test_the_runtime_is_pad_modes_gd_and_override_cfg(folder, port, mk):
    files = {rel: src for rel, src, _m in mk.pad_files(folder, port)}
    assert files["pad_modes.gd"] == GD and "padunity.so" not in files and "PadModes.dll" not in files
    assert mk.top_files(port) == [("override.cfg", OVERRIDE.encode(), 0o644)]
    assert mk.launch_files(port) == ()
    # the Unity titles carry none, and keep their launch lines
    scooby = SM.load_port("scooby_doo-2025.12.01.09")
    assert mk.top_files(scooby) == [] and mk.launch_files(scooby) == mk.LAUNCH_FILES


def test_build_writes_the_plain_tar_again_with_the_runtime(tmp_path, folder, port, mk):
    stock = tmp_path / "stock" / "2025.10.08.looney"
    stock.parent.mkdir()
    _tar(str(stock), [("main.x86_64", b"ELF"), ("speaker_kit.hex", b":00"), ("version.txt", b"2025_10_08\n")])
    out = tmp_path / "new" / "2025.10.08.looney"
    out.parent.mkdir()
    log = []
    mk.build(str(stock), folder, str(out), port, log=log.append)
    with open(str(out), "rb") as f:
        assert f.read(2) != b"\x1f\x8b"                         # plain, as the machine's update is
    got = _read(str(out))
    assert got["main.x86_64"] == b"ELF" and got["speaker_kit.hex"] == b":00"
    assert got["override.cfg"] == OVERRIDE.encode()
    assert got["pad/pad_modes.gd"] == open(GD, "rb").read()
    assert b"name = Carrot Chase" in got["pad/modes/1_carrot_chase.mode"]
    assert "pad/modes/title.cfg" in got and "pad/README.txt" in got
    assert any("override.cfg" in l for l in log) and any("2 mode file(s)" in l for l in log)
    # a modes update built again: one override.cfg, one pad/
    again = tmp_path / "again.looney"
    mk.build(str(out), folder, str(again), port, log=lambda s: None)
    with tarfile.open(str(again)) as t:
        names = t.getnames()
    assert names.count("override.cfg") == 1 and names.count("pad/pad_modes.gd") == 1
    # never an update without the game in it
    bare = tmp_path / "bare.looney"
    _tar(str(bare), [("version.txt", b"x")])
    with pytest.raises(mk.Refused, match="no main.x86_64"):
        mk.build(str(bare), folder, str(tmp_path / "x.looney"), port, log=lambda s: None)
    assert not os.path.exists(str(tmp_path / "x.looney.partial"))


def test_stage_is_the_try_it_folder(tmp_path, folder, port, mk):
    pad = mk.stage(folder, str(tmp_path / "try" / "pad"), port)
    names = sorted(os.path.relpath(os.path.join(d, f), pad).replace("\\", "/")
                   for d, _s, fs in os.walk(pad) for f in fs)
    assert names == ["README.txt", "modes/1_carrot_chase.mode", "modes/2_spinner_frenzy.mode",
                     "modes/title.cfg", "pad_modes.gd"]


def test_the_rig_loads_a_try_it_folder_as_the_update_would(mk):
    """run_game.sh writes the same override.cfg for a Try it folder as the build puts in the update,
    and prepare.sh keeps a Godot modes update beside the stock one."""
    with open(os.path.join(ROOT, "tools", "spooky_emu", "run_game.sh"), encoding="utf-8") as f:
        rg = f.read()
    m = re.search(r"printf '(\[autoload\][^']*)' > \"\$UPTEST/override.cfg\"", rg)
    assert m and m.group(1).replace("\\n", "\n") == mk.OVERRIDE_TEXT
    with open(os.path.join(ROOT, "tools", "spooky_emu", "prepare.sh"), encoding="utf-8") as f:
        assert 'pad/pad_modes.gd" ]' in f.read()


# ------------------------------------------------------------------ the app's half
def test_the_card_is_the_title(tmp_path):
    f = tmp_path / "2025.10.08.looney"
    f.write_bytes(b"main.x86_64")
    assert SM.label_for_card(str(f)) == LABEL
    t = {x["label"]: x for x in SM.titles()}[LABEL]
    assert t["can_run"] and t["name"] == "Looney Tunes 2025.10.08" and t["counts"]["switches"] == 96


def test_a_sound_is_heard_from_the_extract(tmp_path, port):
    d = tmp_path / "ex" / "assets" / "sounds" / "voice" / "hurry"
    d.mkdir(parents=True)
    path = port["sound_paths"]["bugs_hurry1"].rsplit("/", 1)[-1]
    (d / path).write_bytes(b"RIFF")
    idx = SM.sound_index(str(tmp_path / "ex"))
    assert SM.sound_file(idx, "bugs_hurry1", port).endswith(path)
    assert SM.sound_file(idx, "jab_jackpot", port) == ""


def test_the_write_tab_carries_the_modes(tmp_path, folder):
    """Write packs a Looney Tunes extract as the plain tar it is: the modes and the runtime go in,
    override.cfg loads it, and an extract's own pad/ and override.cfg are replaced."""
    from pinball_decryptor.plugins.spooky import formats
    ex = tmp_path / "extract"
    ex.mkdir()
    (ex / ".spooky_meta").write_text(json.dumps({"game": "Looney Tunes", "format": "plain_tar", "ext": ".looney"}))
    (ex / "version.txt").write_text("2025_10_08\n")
    (ex / "main.x86_64").write_bytes(b"ELF")
    (ex / "override.cfg").write_text("[autoload]\n\nOld=\"*/x.gd\"\n")
    (ex / "pad").mkdir()
    (ex / "pad" / "stale.txt").write_text("old")
    assert SM.label_for_extract(str(ex)) == LABEL
    pm = SM.write_pad_modes(LABEL)
    assert SM.loads_how(LABEL).startswith("an override.cfg")
    out = tmp_path / "2025.10.08.looney"
    formats.create_tar(str(ex), str(out), pad_modes=pm)
    with tarfile.open(str(out)) as t:
        names = t.getnames()
    got = _read(str(out))
    assert names.count("override.cfg") == 1 and got["override.cfg"] == OVERRIDE.encode()
    assert "pad/pad_modes.gd" in got and "pad/modes/1_carrot_chase.mode" in got
    assert not any("stale" in n for n in got)
    assert got["main.x86_64"] == b"ELF" and ".spooky_meta" not in got
    # no modes, no change: Write of a plain tar without them carries the extract as it is
    plain = tmp_path / "plain.looney"
    formats.create_tar(str(ex), str(plain))
    assert "override.cfg" in _read(str(plain)) and "pad/pad_modes.gd" not in _read(str(plain))


def test_both_looney_tunes_builds_have_a_port_and_starters(mk):
    """The library holds 2025.03.01 and 2025.10.08: each has its own port report (the older one
    lacks a font and some callouts) and a starter folder its check passes."""
    old = SM.load_port("legends_of_tera-2025.03.01")
    new = SM.load_port(LABEL)
    assert old["engine"] == "godot" and old["game_version"] == "2025.03.01" and old["points_scale"] == 1
    assert old["switches"] == new["switches"] and len(old["sounds"]) == 1019
    assert "bugs_count_one" not in old["sounds"] and "digital-7 (mono)" not in old["fonts"]
    for label in ("legends_of_tera-2025.03.01", LABEL):
        _modes, problems = mk.check_modes(os.path.join(MODES, "examples", label), SM.load_port(label))
        assert problems == [], (label, problems)
    assert {t["label"] for t in SM.titles() if t["can_run"]} >= {"legends_of_tera-2025.03.01", LABEL}
