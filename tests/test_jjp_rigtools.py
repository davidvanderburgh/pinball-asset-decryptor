"""The JJP rig installs what it needs from the Linux it runs in (PAD-1590).

A new PC's default distro - where the JJP emulator runs - stopped getting the
JJP packages once the installer put them into the app's own Linux, so Start
died on "mount.sh: missing partclone.restore".  tools/jjp_emu/rigtools.sh is
the rig's one list of what it needs; watch.sh runs it before anything else.
These hold the list to the scripts that actually call the tools.
"""
import pathlib
import re

from pinball_decryptor.webui import emulate_jjp_core

RIG = pathlib.Path(__file__).resolve().parent.parent / "tools" / "jjp_emu"
RIGTOOLS = RIG / "rigtools.sh"


def _table():
    """[(probe, [package, ...])] - the TOOLS block, read as rigtools.sh reads it."""
    text = RIGTOOLS.read_text(encoding="utf-8")
    block = re.search(r"^TOOLS='\n(.*?)^'", text, re.S | re.M).group(1)
    rows = []
    for line in block.splitlines():
        words = line.split()
        if words:
            rows.append((words[0], words[1:]))
    return rows


def test_every_row_has_a_probe_and_a_package():
    rows = _table()
    assert len(rows) >= 10
    for probe, pkgs in rows:
        assert pkgs, probe
        assert re.fullmatch(r"(py:|pc:)?[\w.+-]+", probe), probe


def test_the_tools_the_report_was_missing_are_in_the_table():
    """partclone is the report itself; Xephyr, the FUSE headers and Tk are what
    the next steps would have stopped on in the same bare distro."""
    probes = {p for p, _ in _table()}
    assert {"partclone.restore", "Xephyr", "pc:fuse3", "py:tkinter",
            "py:PIL.ImageTk", "gcc", "xdotool"} <= probes


def test_every_install_hint_in_the_rig_is_in_the_table():
    """Each script names its own fix ("apt-get install -y xserver-xephyr").  A
    package a script asks for that the table does not install is a Start that
    still fails on a bare distro."""
    packages = {p for _, pkgs in _table() for p in pkgs}
    # build-essential is build.sh's generic hint; the table installs what it
    # actually uses from it (gcc, libc6-dev).
    aliases = {"build-essential": {"gcc", "libc6-dev"}}
    missing = []
    for script in sorted(RIG.glob("*.sh")):
        if script.name == "rigtools.sh":
            continue
        for hint in re.findall(r"apt-get install -y ([\w.+ -]+)",
                               script.read_text(encoding="utf-8")):
            for pkg in hint.split():
                if not (aliases.get(pkg, {pkg}) <= packages):
                    missing.append("%s: %s" % (script.name, pkg))
    assert not missing, missing


def test_watch_runs_the_tools_step_before_the_mount():
    text = (RIG / "watch.sh").read_text(encoding="utf-8")
    tools = text.index('bash "$HERE/rigtools.sh"')
    assert text.index('step "tools"') < tools < text.index('bash "$HERE/mount.sh"')
    # ...and it is not fatal: each later step names what it still lacks.
    line = text[tools:text.index("\n", tools)]
    assert "||" in line and "exit" not in line


def test_rigtools_is_root_and_apt_only_when_something_is_missing():
    text = RIGTOOLS.read_text(encoding="utf-8")
    nothing = text.index('[ -n "$MISSING" ] ||')
    assert nothing < text.index("apt-get -o")
    assert nothing < text.index('[ "$(id -u)" = "0" ]')
    assert "DEBIAN_FRONTEND=noninteractive" in text


def test_the_footer_names_the_tools_step():
    assert emulate_jjp_core.FOOTER_STEPS[0][0] == "== tools =="
    assert emulate_jjp_core.FOOTER_STEPS[0][1] == "copy"
