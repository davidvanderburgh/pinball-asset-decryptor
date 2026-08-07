"""The spike2_emu rig's path resolution and per-title table derivation.

These cover the two things that made the rig unrunnable anywhere but the machine
it was written on: paths written down instead of derived, and per-title tables
committed instead of built from the card.

FAST AND SYNTHETIC ON PURPOSE - no WSL, no card image, no game binary, no
emulator. Every path here is a tmp_path, and `PAD_ROOT` / `PAD_TABLES` are set
so nothing reaches for `wsl.exe` to find out where it is. The real end-to-end
proof is a run; this is the part that can be checked in half a second after any
edit.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


@pytest.fixture()
def rig(monkeypatch, tmp_path):
    """The rig modules, pointed at a synthetic rootfs under tmp_path."""
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    root = tmp_path / "spike2root"
    (root / "dump").mkdir(parents=True)
    (root / "games").mkdir()
    monkeypatch.setenv("PAD_ROOT", str(root))
    monkeypatch.setenv("PAD_TABLES", str(root / "dump" / "tables"))
    monkeypatch.delenv("PAD_GAME", raising=False)
    import gameinfo
    import padpath
    # to_win()/to_wsl() memoise, and a previous test's answers must not leak.
    padpath._WIN_CACHE.clear()
    return type("Rig", (), {"padpath": padpath, "gameinfo": gameinfo,
                            "root": root})


def test_paths_come_from_the_environment_not_a_machine(rig):
    """PAD_ROOT decides, and everything else hangs off it."""
    assert rig.padpath.root() == str(rig.root)
    assert rig.padpath.dump() == os.path.join(str(rig.root), "dump")
    assert rig.padpath.tables() == os.path.join(str(rig.root), "dump", "tables")


def test_rig_directory_is_derived_from_this_file(rig):
    """Not written down. This is what lets a checkout live anywhere."""
    assert os.path.isfile(os.path.join(rig.padpath.RIG, "padpath.py"))


def test_empty_env_var_reads_as_unset(rig, monkeypatch):
    """`env A="$B" cmd` passes an EMPTY A when B is unset, and the rig does
    exactly that in several places - so "" must not be taken for an answer."""
    monkeypatch.setenv("PAD_WSL_DISTRO", "   ")
    assert rig.padpath._env("PAD_WSL_DISTRO") is None


@pytest.mark.parametrize("path,is_win", [
    (r"\\wsl.localhost\Ubuntu\home\x", True),
    (r"C:\Users\x", True),
    ("/home/x/spike2root", False),
    ("", False),
    (None, False),
])
def test_windows_path_detection(rig, path, is_win):
    """One variable carries either form: a POSIX path inside WSL, and the
    translated Windows path in the process WSL launches (WSLENV's /p)."""
    assert bool(rig.padpath.is_windows_path(path)) is is_win


def test_to_win_leaves_a_windows_path_alone(rig):
    """So a value already translated by WSLENV is never round-tripped."""
    p = r"\\wsl.localhost\Ubuntu\home\x"
    assert rig.padpath.to_win(p) == p


def test_published_title_is_read_from_the_dump_directory(rig):
    """run_game.sh publishes it; it is the only source that can name a title
    running straight off a card."""
    (rig.root / "dump" / "title").write_text(
        "name=jaws_le\ndir=/home/x/card/jaws_le-1_02_0\n")
    assert rig.gameinfo.published()["name"] == "jaws_le"
    assert rig.gameinfo.active() == "jaws_le"


def test_pad_game_beats_the_published_title(rig, monkeypatch):
    (rig.root / "dump" / "title").write_text("name=jaws_le\n")
    monkeypatch.setenv("PAD_GAME", "godzilla_pro")
    assert rig.gameinfo.active() == "godzilla_pro"


def test_no_title_returns_none_rather_than_guessing_godzilla(rig):
    """It used to fall back to the title this rig was built against, which is
    a lie on any other machine and the whole class of thing this fixes."""
    assert rig.gameinfo.active() is None


def test_a_single_extracted_title_is_enough_to_choose(rig):
    d = rig.root / "games" / "elvira3"
    d.mkdir()
    (d / "game").write_bytes(b"\x7fELF")
    assert rig.gameinfo.active() == "elvira3"


def test_table_dir_is_outside_the_checkout(rig, monkeypatch):
    """The tables are derived data and must not be written into git again."""
    monkeypatch.setenv("PAD_GAME", "godzilla_pro")
    tdir = rig.gameinfo.table_dir()
    assert tdir.startswith(str(rig.root))
    assert "tools" not in tdir.replace(str(rig.root), "")


def test_switch_dump_needs_its_footer_before_it_is_read(rig, tmp_path):
    """A dump read while it is still being written is a switch table with holes
    in it, and a short switch table does not look wrong."""
    import mktables
    log = tmp_path / "run.log"
    log.write_text("[sw] --- switches: count=88 entry[]=0x1 raw[]=0x2 ---\n"
                   "[sw] id=1   num=0    node=4  bit=0  raw=? logical=0 flags=0x0024 A\n")
    assert mktables.switch_dump_complete(str(log)) is False
    with log.open("a") as f:
        f.write("[dev] --- ball devices: count=7 ---\n")
    assert mktables.switch_dump_complete(str(log)) is True


def test_switch_dump_absent_is_not_a_crash(rig, tmp_path):
    import mktables
    assert mktables.switch_dump_complete(str(tmp_path / "nope.log")) is False
    assert mktables.wait_for_switches(None, 5) is False


def test_swtable_by_name_feeds_the_position_join(rig):
    """`[sw]` is printed by every run; `[swmap]` needs PAD_SW_MAP set. Both
    carry an id and a name, so the join takes either."""
    import swtable
    rows = [(1, 0, 4, 0, "Left Spinner"), (2, 0, 8, 9, "?")]
    m = swtable.by_name(rows)
    assert m["LEFT SPINNER"] == (1, 4, 0)
    assert "?" not in m                       # unnamed switches cannot be joined


def test_switchxy_joins_on_name_and_ignores_off_playfield_devices(rig):
    import switchxy
    recs = [
        dict(kind="switch", image="playfield", name="LEFT SPINNER", x=10, y=20),
        dict(kind="switch", image="cabinet", name="SLAM TILT", x=1, y=2),
        dict(kind="coil", image="playfield", name="LEFT SPINNER", x=99, y=99),
    ]
    rows = switchxy.join({"LEFT SPINNER": (47, 8, 9), "SLAM TILT": (5, 0, 1)}, recs)
    assert [(r[0], r[3]["x"], r[3]["y"]) for r in rows] == [(47, 10, 20)]


def test_devicexy_build_honours_the_title_it_was_asked_for(rig, monkeypatch):
    """THE REGRESSION THIS EXISTS FOR. build() called gameinfo.elf() with no
    argument, so asking for one title's records returned whichever title was
    ACTIVE - building `turtles_pro` handed back Godzilla's 575 records, its
    313x710 artwork size and its 31/31 left-right check, all of which look like
    a healthy result.
    """
    import devicexy
    for name in ("godzilla_pro", "turtles_pro"):
        d = rig.root / "games" / name
        d.mkdir()
        (d / "game").write_bytes(b"\x7fELF" + name.encode() + b"\x00" * 64)
    monkeypatch.setenv("PAD_GAME", "godzilla_pro")

    asked = []
    real_load = devicexy.load

    def spy(path=None):
        asked.append(path)
        return real_load(path)

    monkeypatch.setattr(devicexy, "load", spy)
    devicexy.build("turtles_pro")
    assert asked and "turtles_pro" in asked[0]


def test_ledio_builds_with_no_wire_log(rig):
    """The map is static - every column comes from the device table - so
    requiring a PAD_NB_LOG capture made the inserts wait on an instrumented
    run for data that never depended on one."""
    import ledio
    recs = [dict(kind="led", group=6, index=4, name="SHIELD-R", x=1, y=2,
                 conn="8b", image="playfield")]
    rows, problems, _report = ledio.build(recs, None)
    assert [(n, r["index"]) for n, r in rows] == [(8, 4)]
    assert problems == []
    assert "NOT verified" in ledio.text("t", rows, False)
    assert "NOT verified" not in ledio.text("t", rows, True)


def test_wsl_detection_is_defined_in_exactly_one_place(rig):
    """padpath owns it. playaudio.sh used to carry its own copy.

    This rig's own rules forbid two scripts defining one fact - alive.sh and
    killgame.sh disagreeing about what a running rig is has already cost a
    session - and "are we on WSL" now decides real behaviour in several places.
    """
    import glob
    import re
    own = []
    for path in sorted(glob.glob(os.path.join(RIG, "*.sh"))):
        if os.path.basename(path) == "padpath.sh":
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                # A definition, not a call: `is_wsl() { pad_is_wsl; }` delegates
                # and is fine; a second copy of the /proc/version test is not.
                if re.search(r"microsoft\s+/proc/version", line):
                    own.append("%s:%d" % (os.path.basename(path), n))
    assert not own, "a second definition of 'are we on WSL': %s" % own


def test_native_and_wsl_playfield_shapes_are_both_counted(rig):
    """alive.sh is the rig's only definition of "clean".

    Under WSL the playfield is a Windows process seen as an interop stub
    (`/init ... playfield.py`); on a Linux desktop it is an ordinary
    `python3 .../playfield.py`. Counting only the first printed a confident 0
    over a live window on every Linux machine - the precise failure this script
    exists to prevent.
    """
    with open(os.path.join(RIG, "alive.sh"), encoding="utf-8") as f:
        text = f.read()
    assert "playfield" in text
    assert "^/init .*playfield" in text, "the WSL interop stub is no longer counted"
    assert "python3? .*playfield" in text, "the native Linux process is not counted"


def test_the_windows_installer_ships_the_rig():
    """The Emulate tab is unreachable for an installed user without this.

    The rig was left out of the installers on the grounds that it needs WSL, a
    C toolchain and a card image before it does anything - and the result was a
    tab that could only ever tell an installed user the rig "was not found".
    3.3 MB of scripts is a poor reason to make a feature unreachable, so it
    ships, and this is here because a dropped [Files] line would be invisible
    until someone installed the app and tried it.
    """
    iss = os.path.join(os.path.dirname(RIG), "..", "installer",
                       "pinball_decryptor.iss")
    iss = os.path.normpath(iss)
    if not os.path.exists(iss):
        pytest.skip("installer manifest not present")
    with open(iss, encoding="utf-8", errors="replace") as f:
        text = f.read()
    assert "tools\\spike2_emu" in text, \
        "pinball_decryptor.iss no longer ships tools/spike2_emu"
    line = next(l for l in text.splitlines()
                if "tools\\spike2_emu" in l and l.strip().startswith("Source:"))
    assert "recursesubdirs" in text.split(line, 1)[1][:200], \
        "the rig is shipped without recursesubdirs, so subdirectories are lost"


def test_the_rig_never_writes_into_its_own_directory():
    """Because {app} is Program Files, which is read-only for the user.

    build.sh compiles in ~/emusrc, rootfs.sh refuses a /mnt destination, and
    the derived tables live under the rootfs - so nothing on the runtime path
    writes here. Three forensic scripts did (`$RIG/now.png`, `$RIG/dev.dis`),
    which would have been a permission error the moment the rig shipped.
    """
    import glob
    import re
    bad = []
    pat = re.compile(r"\$\{?(?:RIG|S)\}?/[A-Za-z0-9_]+\.(png|log|dis|txt|json)\b")
    for path in sorted(glob.glob(os.path.join(RIG, "*.sh"))
                       + glob.glob(os.path.join(RIG, "*.py"))):
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            for n, line in enumerate(f, 1):
                if line.lstrip().startswith("#"):
                    continue
                if pat.search(line):
                    bad.append("%s:%d: %s"
                               % (os.path.basename(path), n, line.strip()[:90]))
    assert not bad, ("writes into the rig's own directory, which is read-only "
                     "once installed:\n  " + "\n  ".join(bad))


def test_no_unquoted_path_expansion_in_the_shell_scripts():
    """A path with a SPACE in it must not word-split into two arguments.

    THIS COULD NOT HAPPEN BEFORE AND NOW IT CAN. Every script used to carry one
    hard-coded path, and that path had no spaces, so nothing was ever quoted.
    De-welding made the rig runnable from anywhere - which includes
    `C:\\Program Files\\Pinball Asset Decryptor\\tools\\spike2_emu`, where
    `cp $RIG/hwshim.c $HOME/emusrc/hwshim.c` becomes five arguments and cp
    reports "target ... Not a directory".

    A lint rather than a run: the failure needs WSL, a card and several minutes
    to see, and this sees it in milliseconds after any edit. It only checks the
    argument-leading case, which is the one that splits - an assignment's
    right-hand side does not word-split and is left alone.
    """
    import glob
    import re
    bad = []
    pat = re.compile(r"(?<=[ \t])\$\{?(?:RIG|S|ROOT|R|HOME|TABLES)\}?/")
    for path in sorted(glob.glob(os.path.join(RIG, "*.sh"))):
        with open(path, encoding="utf-8", newline="") as f:
            for n, line in enumerate(f, 1):
                if line.lstrip().startswith("#"):
                    continue
                if pat.search(line):
                    bad.append("%s:%d: %s"
                               % (os.path.basename(path), n, line.strip()[:90]))
    assert not bad, ("unquoted path expansion (breaks under a path with a "
                     "space):\n  " + "\n  ".join(bad))


def _art_dir(rig, title, names):
    """A fake title whose assets hold `names`, so artwork discovery can be
    checked without a card."""
    d = rig.root / "games" / title / "assets" / "nuk" / "images" / "Test"
    d.mkdir(parents=True)
    for n in names:
        (d / n).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 25)
    return d


@pytest.mark.parametrize("title,files,want", [
    # Jaws puts the qualifier LAST. A `*_playfield.png` suffix test found
    # nothing and the rig reported "this title ships no playfield drawing"
    # about a title shipping two of them.
    ("jaws_le", ["jaws_le_playfield_scaled.png", "jaws_pro_playfield_scaled.png",
                 "jaws_pro_backpanel_scaled.png", "jaws_topper_scaled.png"],
     "jaws_le_playfield_scaled.png"),
    # The same directory must give the Pro machine the Pro drawing. A substring
    # test picks this pair correctly BY ACCIDENT, because "scaLEd" contains
    # "le" - so it would hand an LE machine the Pro artwork the moment the
    # alphabetical order changed.
    ("jaws_pro", ["jaws_le_playfield_scaled.png", "jaws_pro_playfield_scaled.png"],
     "jaws_pro_playfield_scaled.png"),
    ("godzilla_pro", ["scaled_godzilla_le_playfield.png",
                      "scaled_godzilla_pro_playfield.png"],
     "scaled_godzilla_pro_playfield.png"),
    ("godzilla_le", ["scaled_godzilla_le_playfield.png",
                     "scaled_godzilla_pro_playfield.png"],
     "scaled_godzilla_le_playfield.png"),
    ("john_wick_le", ["john_wick_le_playfield.png"], "john_wick_le_playfield.png"),
])
def test_playfield_artwork_is_found_and_the_right_model_chosen(
        rig, monkeypatch, title, files, want):
    _art_dir(rig, title, files)
    monkeypatch.setenv("PAD_GAME", title)
    got = rig.gameinfo.find_playfield_art()
    assert got is not None, "no artwork found for %s" % title
    assert os.path.basename(got) == want


def test_a_title_with_no_drawing_is_not_a_failure(rig, monkeypatch):
    """Elvira and Led Zeppelin ship no images/Test at all, and the schematic
    playfield is the right answer for them."""
    _art_dir(rig, "elvira3", ["elvira3_topper_scaled.png"])
    monkeypatch.setenv("PAD_GAME", "elvira3")
    assert rig.gameinfo.find_playfield_art() is None


def test_ledio_reports_a_wire_disagreement(rig):
    import ledio
    recs = [dict(kind="led", group=6, index=4, name="A", x=1, y=2, conn="8b",
                 image="playfield")]
    _rows, problems, _r = ledio.build(recs, {8: {9}})
    assert problems == [(8, [4])]
