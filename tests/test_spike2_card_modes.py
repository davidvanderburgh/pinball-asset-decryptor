"""The item 149 family follow-up: EMULATING A CARD RUNS ITS OWN MODES.

On a machine a card that carries modes of our own loads them itself (the game_monitor hook
preloads /usr/local/padmode/mode.so). The rig execs ./game directly, so run_game.sh asks the
card (modes/cardmodes.sh) and puts the card's own object, port and mode files in the guest
through modes/tryit.sh install, then preloads the object.

Two kinds of test, because two kinds of machine run this file:

* TEXT tests read the rig scripts. They run everywhere, Windows and CI included, and pin the
  wiring a functional test cannot reach without a whole emulator: run_game.sh calls the
  script before the namespace and exports its answer, watch.sh hands the two variables on
  and repeats the [modes] lines where the Emulate tab reads them, the macOS box lets the
  opt-out cross, tryit.sh takes the marker out with the files it replaces.
* FUNCTIONAL tests build a real ext4 "card" with the real installer (mode_install.py) and
  run modes/cardmodes.sh against a stand-in guest (PAD_ROOT). They need Linux bash and
  e2fsprogs and SKIP without them: Windows has neither, and CI has no e2fsprogs.
"""
import os
import re
import shutil
import struct
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(REPO, "tools", "spike2_emu")
SCRIPT = os.path.join(RIG, "modes", "cardmodes.sh")
sys.path.insert(0, RIG)


def _text(*parts):
    with open(os.path.join(RIG, *parts), encoding="utf-8") as f:
        return f.read()


# ---- the wiring, read off the scripts (every platform) -------------------------------------

def test_run_game_asks_the_card_before_the_namespace_and_exports_the_answer():
    src = _text("run_game.sh")
    call = src.index('bash "$S/modes/cardmodes.sh" "${PAD_CARD:-}" | tail -1')
    # the answer becomes PAD_MODE_SO only when there is one: an empty answer must leave a
    # PAD_MODE_SO the launch brought exactly as it was
    assert re.search(r'\[ -n "\$_cardmode_so" \] && export PAD_MODE_SO="\$_cardmode_so"', src)
    # out in the open, before the namespace the game runs in: the install is a plain copy
    # that wants $PAD_HOME, and both LD_PRELOAD lines are inside the namespace's script
    assert call < src.index("unshare $USERNS")
    # ...and after the card is mounted and the title decided, so a refusal up there costs nothing
    assert call > src.index('OVERRIDE_SRC=$(bash "$S/overrides.sh"')
    assert src.count("${PAD_MODE_SO:+$PAD_MODE_SO:}/lib/hwshim.so") == 2


def test_watch_hands_both_variables_to_run_game_and_repeats_what_it_found():
    src = _text("watch.sh")
    launch = src[src.index("setsid env PAD_THREAD_ENTRY=1"):]
    launch = launch[:launch.index('bash "$RIG/run_game.sh"')]
    assert 'PAD_MODE_SO="${PAD_MODE_SO:-}"' in launch
    assert 'PAD_CARD_MODES="${PAD_CARD_MODES:-}"' in launch
    # the [modes] lines are written before the event feed listens (it tails from the END of
    # the log), so they are repeated on this script's stdout - what the Emulate tab drains -
    # once the guest is up
    repeat = src.index("grep -a '^\\[modes\\] ' \"$LOG\"")
    assert src.index('echo "[watch] the game never started.') < repeat
    assert repeat < src.index('tail -q -n 0 -F "$PAD_HOME/padvid.log"')


def test_the_macos_box_lets_the_opt_out_cross():
    src = _text("docker", "padbox.sh")
    loop = src[src.index("for v in PAD_GAME"):]
    assert "PAD_CARD_MODES" in loop[:loop.index("; do")]


def test_tryit_install_takes_the_marker_out_with_the_files_it_replaces():
    """The marker says "cardmodes.sh put these files here". Once Try it (or the override
    set) has replaced them they are somebody else's, and a marker left behind would have
    a later stock run take THOSE out."""
    src = _text("modes", "tryit.sh")
    clearing = src[src.index('rm -f "$DUMP"/mode.cfg'):]
    assert '"$DUMP"/cardmodes.from' in clearing[:clearing.index("put ")]


def test_the_emulate_tab_shows_the_rigs_lines_unfiltered():
    """Start drains watch.sh's stdout line by line into the log pane with no filter of its
    own, so a line watch.sh prints is a line the user reads."""
    with open(os.path.join(REPO, "pinball_decryptor", "gui", "emulate_tab.py"),
              encoding="utf-8") as f:
        src = f.read()
    drain = src[src.index("for raw in self._proc.stdout:"):]
    assert 'self._log("[emulate] " + line)' in drain[:400]


# ---- the script itself, against a real ext4 card (Linux bash + e2fsprogs) ------------------

def _bash():
    return shutil.which("bash") if sys.platform != "win32" else None


needs_rig_tools = pytest.mark.skipif(
    not (_bash() and shutil.which("mke2fs") and shutil.which("debugfs")
         and shutil.which("e2fsck") and shutil.which("python3")),
    reason="needs Linux bash, python3 and e2fsprogs (mke2fs, debugfs, e2fsck)")

STOCK_MONITOR = (
    "#!/bin/sh\n"
    "\n"
    "while [ true ] ;\n"
    "do\n"
    "\t$1\n"
    "\t/usr/local/bin/boot_display&\n"
    "\tsleep 1\n"
    "\tpkill boot_display\n"
    "done\n"
)


def _mbr(start_lba, count_lba):
    """Sector 0 with ONE Linux (0x83) partition in the second primary slot, which is where
    a Spike 2 card keeps its rootfs (see test_spike2_mode_install._mbr)."""
    mbr = bytearray(512)
    e = 0x1BE + 16
    mbr[e + 4] = 0x83
    struct.pack_into("<II", mbr, e + 8, start_lba, count_lba)
    mbr[510:512] = b"\x55\xaa"
    return bytes(mbr)


def _mkcard(tmp_path, name="card.raw"):
    """A card image whose p2 is a 64 MiB ext4 that LOOKS LIKE A ROOTFS to parts.identify()
    (it has /lib and /usr and no /spk) and carries a stock /etc/init.d/game_monitor."""
    import mkmulticard as mk

    off = 24576 * 512
    blocks = 65536
    card = tmp_path / name
    part = tmp_path / (name + ".p2")
    subprocess.run(["mke2fs", "-q", "-t", "ext4", "-b", "1024", str(part), str(blocks)],
                   check=True)
    mon = tmp_path / (name + ".monitor")
    mon.write_text(STOCK_MONITOR)
    mk.debugfs_write_script(str(part), [
        "mkdir /lib", "mkdir /etc", "mkdir /etc/init.d", "mkdir /usr", "mkdir /usr/local",
        "mkdir /usr/local/bin",
        "write %s /etc/init.d/game_monitor" % mon,
        "set_inode_field /etc/init.d/game_monitor mode 0100755",
    ])
    with open(card, "wb") as out:
        out.write(_mbr(24576, blocks * 2))
        out.truncate(off)
        out.seek(off)
        out.write(part.read_bytes())
    part.unlink()
    return str(card)


OBJECT = b"\x7fELF" + b"\x01" * 4096
PORT = "game godzilla_le\nversion 1.16\n"
CFGS = ("# GENERATED\nname           ATOMIC BREATH\nseconds 25\n",
        "name DESTOROYAH\r\nseconds 15\r\n",          # a CR must not reach the log line
        "name\tMOTHRA'S SONG\nseconds 40\n")


def _install_modes(tmp_path, card, port=True, cfgs=CFGS):
    """The REAL installer, so the layout under test is the one a Written card has."""
    import mode_install as mi

    src = tmp_path / "payload"
    src.mkdir(exist_ok=True)
    (src / "mode.so").write_bytes(OBJECT)
    (src / "game.port").write_text(PORT)
    paths = []
    for i, body in enumerate(cfgs):
        p = src / ("m%d.mode" % i)
        p.write_bytes(body.encode("utf-8"))
        paths.append(str(p))
    mi.install(card, str(src / "mode.so"), paths[0],
               str(src / "game.port") if port else None, extra_cfgs=paths[1:])


def _guest(tmp_path):
    root = tmp_path / "home" / "spike2root"
    (root / "lib").mkdir(parents=True)
    (root / "dump").mkdir()
    return root


def _run(tmp_path, root, card, **env):
    full = {k: v for k, v in os.environ.items()
            if k not in ("PAD_MODE_SO", "PAD_CARD_MODES", "PAD_ROOT", "PAD_HOME", "PAD_TABLES")}
    full.update(PAD_HOME=str(tmp_path / "home"), PAD_ROOT=str(root),
                TMPDIR=str(tmp_path), **env)
    return subprocess.run(["bash", SCRIPT, card], env=full, capture_output=True, text=True,
                          timeout=120)


def _dump(root):
    return sorted(os.listdir(root / "dump"))


@needs_rig_tools
def test_a_card_with_modes_yields_the_object_and_the_install(tmp_path):
    card = _mkcard(tmp_path)
    _install_modes(tmp_path, card)
    root = _guest(tmp_path)
    for stale in ("mode5.cfg", "mode.start", "mode.log"):
        (root / "dump" / stale).write_text("an earlier run's")

    r = _run(tmp_path, root, card)
    assert r.returncode == 0, r.stderr
    # THE ANSWER: the last line of stdout is what run_game.sh exports as PAD_MODE_SO
    assert r.stdout.splitlines()[-1] == "/lib/pad_mode.so"
    # the card's own bytes, under the names the runtime reads in the rig
    assert (root / "lib" / "pad_mode.so").read_bytes() == OBJECT
    assert (root / "dump" / "game.port").read_text() == PORT
    assert _dump(root) == ["cardmodes.from", "game.port", "mode.cfg", "mode1.cfg", "mode2.cfg"]
    assert (root / "dump" / "mode2.cfg").read_bytes() == CFGS[2].encode("utf-8")
    # said plainly, once, with the names read from the mode files in slot order
    said = [ln for ln in r.stderr.splitlines() if ln.startswith("[modes] ")]
    assert said == ["[modes] this card carries 3 mode(s) of its own (ATOMIC BREATH, DESTOROYAH, "
                    "MOTHRA'S SONG): their runtime runs in this game, as on the machine"]
    # nothing half-copied, and the throwaway stage is gone
    assert not [n for n in os.listdir(root / "lib") if n.endswith(".tmp")]
    assert not [n for n in os.listdir(tmp_path) if n.startswith("padcardmodes.")]


@needs_rig_tools
def test_a_runtime_the_launch_brought_wins_and_nothing_is_touched(tmp_path):
    card = _mkcard(tmp_path)
    _install_modes(tmp_path, card)
    root = _guest(tmp_path)
    (root / "lib" / "pad_mode.so").write_bytes(b"the project's")
    (root / "dump" / "mode.cfg").write_text("name THE PROJECT'S\n")

    r = _run(tmp_path, root, card, PAD_MODE_SO="/lib/pad_mode.so")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""                      # run_game.sh keeps the launch's value
    assert (root / "lib" / "pad_mode.so").read_bytes() == b"the project's"
    assert _dump(root) == ["mode.cfg"]
    assert (root / "dump" / "mode.cfg").read_text() == "name THE PROJECT'S\n"
    said = [ln for ln in r.stderr.splitlines() if ln.startswith("[modes] ")]
    assert len(said) == 1 and "left out" in said[0] and "PAD_MODE_SO=/lib/pad_mode.so" in said[0]
    assert "3 mode(s)" in said[0]


@needs_rig_tools
def test_the_opt_out_does_not_even_ask_the_card(tmp_path):
    card = _mkcard(tmp_path)
    _install_modes(tmp_path, card)
    root = _guest(tmp_path)
    r = _run(tmp_path, root, card, PAD_CARD_MODES="0")
    assert r.returncode == 0 and r.stdout.strip() == ""
    assert os.listdir(root / "lib") == [] and _dump(root) == []
    assert [ln for ln in r.stderr.splitlines() if ln.startswith("[modes] ")] == [
        "[modes] PAD_CARD_MODES=0: the card is not asked for modes of its own"]


@needs_rig_tools
def test_a_stock_card_changes_nothing_and_says_nothing(tmp_path):
    card = _mkcard(tmp_path)
    root = _guest(tmp_path)
    # files somebody ELSE left (a hand run, a Try it): no marker, so they are not ours to take
    (root / "dump" / "mode.cfg").write_text("name SOMEBODY ELSE'S\n")
    (root / "lib" / "pad_mode.so").write_bytes(b"theirs")
    r = _run(tmp_path, root, card)
    assert r.returncode == 0
    assert r.stdout == "" and r.stderr == ""
    assert _dump(root) == ["mode.cfg"]
    assert (root / "lib" / "pad_mode.so").read_bytes() == b"theirs"
    assert not [n for n in os.listdir(tmp_path) if n.startswith("padcardmodes.")]


@needs_rig_tools
def test_a_stock_card_after_a_card_with_modes_finds_none_of_them(tmp_path):
    """Nothing leaks: what an install of OURS left is taken out by the next run that
    installs nothing - a stock card, no card at all, the opt-out."""
    modded = _mkcard(tmp_path, "modded.raw")
    _install_modes(tmp_path, modded)
    stock = _mkcard(tmp_path, "stock.raw")
    root = _guest(tmp_path)

    assert _run(tmp_path, root, modded).stdout.strip() == "/lib/pad_mode.so"
    (root / "dump" / "mode.log").write_text("armed, 3 mode file(s)\n")
    (root / "dump" / "game.out").write_text("not a mode file")

    r = _run(tmp_path, root, stock)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert _dump(root) == ["game.out"]

    assert _run(tmp_path, root, modded).stdout.strip() == "/lib/pad_mode.so"
    r = _run(tmp_path, root, "")                       # an extracted title: no card to ask
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert _dump(root) == ["game.out"]


@needs_rig_tools
def test_a_card_whose_monitor_does_not_load_the_object_is_left_as_the_machine_leaves_it(tmp_path):
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    _install_modes(tmp_path, card)
    # take the hook out and leave the files: a machine would boot this card without its modes
    ref, _off = mi._ref(card)
    mon = tmp_path / "stock_monitor"
    mon.write_text(STOCK_MONITOR)
    mk.debugfs_write_script(ref, ["rm /etc/init.d/game_monitor",
                                  "write %s /etc/init.d/game_monitor" % mon])
    root = _guest(tmp_path)
    r = _run(tmp_path, root, card)
    assert r.returncode == 0 and r.stdout.strip() == ""
    assert os.listdir(root / "lib") == [] and _dump(root) == []
    assert "does not load them" in r.stderr


@needs_rig_tools
def test_a_card_without_a_port_never_stops_the_run(tmp_path):
    """Item 128's first cards carried their addresses in the object and no port. The SDK
    runtime will not arm without one, tryit.sh will not install without one - and a card
    must never be able to make the emulator refuse to start."""
    card = _mkcard(tmp_path)
    _install_modes(tmp_path, card, port=False)
    root = _guest(tmp_path)
    r = _run(tmp_path, root, card)
    assert r.returncode == 0 and r.stdout.strip() == ""
    assert os.listdir(root / "lib") == [] and _dump(root) == []
    assert "no port file" in r.stderr


@pytest.mark.skipif(not _bash() or not shutil.which("mke2fs") or not shutil.which("debugfs")
                    or not shutil.which("e2fsck")
                    or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs Linux bash and e2fsprogs, as a user root does not stop")
def test_a_guest_this_account_cannot_write_is_a_line_not_a_refusal(tmp_path):
    """The app's Start unpacks the guest as root, so its lib is root's; a desktop-user run
    then cannot install. tryit.sh names the owner and the remedy; the run goes on."""
    card = _mkcard(tmp_path)
    _install_modes(tmp_path, card)
    root = _guest(tmp_path)
    os.chmod(root / "lib", 0o555)
    try:
        r = _run(tmp_path, root, card)
    finally:
        os.chmod(root / "lib", 0o755)
    assert r.returncode == 0 and r.stdout.strip() == ""
    assert "could NOT be put in the emulator" in r.stderr
    assert "chown" in r.stderr                         # tryit.sh's remedy, passed on
    assert "boots WITHOUT them" in r.stderr
    assert _dump(root) == []


@pytest.mark.skipif(not _bash(), reason="bash -n needs Linux bash")
@pytest.mark.parametrize("script", ["modes/cardmodes.sh", "modes/tryit.sh", "run_game.sh",
                                    "watch.sh", "docker/padbox.sh"])
def test_the_scripts_still_parse(script):
    r = subprocess.run(["bash", "-n", os.path.join(RIG, script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@needs_rig_tools
def test_a_card_of_code_modes_puts_their_assets_in_the_guest_and_names_them(tmp_path):
    """The intricate modes' own audio and video: a card whose modes are CODE modes carries no mode
    file, only the object and one <slug>.assets per mode (Write's code_plan). The emulator installs
    them beside the port, names each mode from its file, and a later stock run takes them out."""
    import mode_install as mi

    card = _mkcard(tmp_path)
    src = tmp_path / "payload"
    src.mkdir()
    (src / "mode.so").write_bytes(OBJECT)
    (src / "game.port").write_text(PORT)
    assets = []
    for slug, name in (("ghidorah_heads", "KING GHIDORAH"), ("oxygen_destroyer", "OXYGEN DESTROYER")):
        p = src / (slug + ".assets")
        p.write_text("# GENERATED\nname   %s\nmusic  125 618\ncall   won 1251 1500 4\n" % name)
        assets.append(str(p))
    mi.install(card, str(src / "mode.so"), None, str(src / "game.port"), assets=assets)
    root = _guest(tmp_path)
    (root / "dump" / "stale.assets").write_text("an earlier run's")
    r = _run(tmp_path, root, card)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines()[-1] == "/lib/pad_mode.so"
    assert _dump(root) == ["cardmodes.from", "game.port", "ghidorah_heads.assets", "oxygen_destroyer.assets"]
    assert (root / "dump" / "ghidorah_heads.assets").read_bytes() == open(assets[0], "rb").read()
    said = [ln for ln in r.stderr.splitlines() if ln.startswith("[modes] ")]
    assert said == ["[modes] this card carries 2 mode(s) of its own (KING GHIDORAH, OXYGEN DESTROYER): "
                    "their runtime runs in this game, as on the machine"]
    # a stock card afterwards: the marker's files go, the .assets with them
    stock = _mkcard(tmp_path, "stock")
    r = _run(tmp_path, root, stock)
    assert r.returncode == 0 and _dump(root) == []
