"""Item 128: mode_install against a REAL ext4 image, not a mock.

The acceptance clause is "removing the mode leaves the card stock", and the
text-level round-trip is already covered by test_spike2_modehook. What that
cannot show is whether the bytes survive a debugfs write/read cycle on an actual
filesystem - which is where item 129's lesson applies: a copy reallocates blocks,
so a reader opened earlier reads stale extents, and only a FRESH read proves
anything. So these tests build a small ext4 image with the stock directory
layout, install into it, and read back through new debugfs calls.

Skipped, not failed, where mke2fs/debugfs are missing: CI has no e2fsprogs and a
red suite there would say nothing about this code.
"""
import os
import shutil
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
sys.path.insert(0, RIG)

pytestmark = pytest.mark.skipif(
    not (shutil.which("mke2fs") and shutil.which("debugfs") and shutil.which("e2fsck")),
    reason="needs e2fsprogs (mke2fs, debugfs, e2fsck)")

STOCK_MONITOR = (
    "#!/bin/sh\n"
    "\n"
    "# set up core dump\n"
    "ulimit -c unlimited\n"
    "echo /dump/core > /proc/sys/kernel/core_pattern\n"
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
    """A 512-byte MBR whose SECOND primary entry is a Linux (0x83) partition.

    mode_install finds p2 through mkmulticard.p2_range -> Geometry.from_reader,
    which reads sector 0, demands the 0x55AA signature and parses four 16-byte
    entries at 0x1BE + 16*i, taking the type from byte 4 and (start, count) as
    '<II' at byte 8; part_range then insists the type is 0x83. The first version
    of this fixture dropped a bare ext4 image at the right offset with no
    partition table at all, and every test that opened a card died in _ref with
    "no MBR signature" before reaching any of the code under test.

    Written here rather than through write_tables(): that takes a Plan, and
    dragging the card BUILDER into a test of the installer would couple the two.
    This asserts the layout Geometry parses; it does not define it.
    """
    import struct

    mbr = bytearray(512)
    e = 0x1BE + 16          # entry index 1 = partition 2
    mbr[e + 4] = 0x83
    struct.pack_into("<II", mbr, e + 8, start_lba, count_lba)
    mbr[510:512] = b"\x55\xaa"
    return bytes(mbr)


def _mkcard(tmp_path, monitor=STOCK_MONITOR):
    """A card image with a real MBR and a 64 MiB ext4 p2 carrying
    /etc/init.d/game_monitor and /usr/local, at the offset the stock layout uses
    (STOCK_P2 starts at sector 24576).

    64 MiB, not 32: install() refuses unless the free space clears
    P2_FREE_MARGIN (8 MiB), and the margin is the point of the check - a fixture
    sized just over it would pass by luck and hide a real refusal.
    """
    import mkmulticard as mk

    off = 24576 * 512
    blocks = 65536                      # x 1 KiB = 64 MiB
    card = tmp_path / "card.raw"
    part = tmp_path / "p2.img"
    subprocess.run(["mke2fs", "-q", "-t", "ext4", "-b", "1024", str(part), str(blocks)],
                   check=True)
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "game_monitor").write_text(monitor)
    ref = str(part)
    mk.debugfs_write_script(ref, [
        "mkdir /etc", "mkdir /etc/init.d", "mkdir /usr", "mkdir /usr/local",
        "mkdir /usr/local/bin", "mkdir /usr/local/spike",
        "write %s /etc/init.d/game_monitor" % str(stage / "game_monitor"),
        "set_inode_field /etc/init.d/game_monitor mode 0100755",
        "set_inode_field /etc/init.d/game_monitor uid 0",
        "set_inode_field /etc/init.d/game_monitor gid 0",
        "set_inode_field /etc/init.d/game_monitor mtime @1600000000",
        "set_inode_field /etc/init.d/game_monitor ctime @1600000000",
        "set_inode_field /etc/init.d/game_monitor atime @1600000000",
    ])
    with open(card, "wb") as out:
        out.write(_mbr(24576, blocks * 2))      # count is in 512-byte SECTORS
        out.truncate(off)
        out.seek(off)
        out.write(part.read_bytes())
    return str(card)


def _payload(tmp_path):
    so = tmp_path / "mode.so"
    cfg = tmp_path / "kaiju.mode"
    so.write_bytes(b"\x7fELF" + b"\x00" * 4096)      # stands in for the real object
    cfg.write_text("name KAIJU RUSH\nseconds 30\n")
    return str(so), str(cfg)


def test_install_then_remove_restores_the_monitor_byte_for_byte(tmp_path):
    """THE ACCEPTANCE CLAUSE, on a real filesystem."""
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    ref, _off = mi._ref(card)
    before = mk.debugfs_cat(ref, mi.GAME_MONITOR)

    mi.install(card, so, cfg)
    assert mk.debugfs_cat(ref, mi.GAME_MONITOR) != before

    mi.remove(card)
    assert mk.debugfs_cat(ref, mi.GAME_MONITOR) == before
    assert not mk.debugfs_exists(ref, mi.MODE_DIR)


def test_install_puts_both_files_on_p2_with_the_right_modes(tmp_path):
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    mi.install(card, so, cfg)
    ref, _off = mi._ref(card)

    assert mk.debugfs_cat(ref, mi.MODE_DIR + "/mode.so") == open(so, "rb").read()
    assert mk.debugfs_cat(ref, mi.MODE_DIR + "/mode.cfg") == open(cfg, "rb").read()
    # PERMISSION BITS, not the full mode. debugfs prints `Mode:  0755` with no
    # S_IFREG and debugfs_stat parses exactly that, which is the same fact that
    # made _restore_monitor_attrs necessary: writing a parsed mode straight back
    # strips the type nibble and e2fsck calls the inode invalid. The installer
    # writes 0100755/0100644; what comes back out is 0755/0644.
    assert mk.debugfs_stat(ref, mi.MODE_DIR + "/mode.so")["mode"] == 0o755
    assert mk.debugfs_stat(ref, mi.MODE_DIR + "/mode.cfg")["mode"] == 0o644


def test_removal_restores_the_monitors_clocks(tmp_path):
    """Item 129 measured that two otherwise identical builds differ in exactly 130
    bytes and every one is an ext4 timestamp. A removal that leaves new clocks is
    not "the card stock" in the only sense that can be checked."""
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    ref, _off = mi._ref(card)
    st_before = mk.debugfs_stat(ref, mi.GAME_MONITOR)

    mi.install(card, so, cfg)
    mi.remove(card)

    st_after = mk.debugfs_stat(ref, mi.GAME_MONITOR)
    for k in ("mtime", "ctime", "atime"):
        assert st_after[k] == st_before[k], k
    assert st_after["mode"] == st_before["mode"]
    assert (st_after["uid"], st_after["gid"]) == (st_before["uid"], st_before["gid"])


def test_install_places_the_port_when_given_and_takes_it_off_again(tmp_path):
    """The SDK runtime (item 134) reads game.port beside its mode files and will not
    arm without it. The first hardware card had the port placed by a scratch copy of
    the install sequence; this pins the installer doing it, and remove taking all three."""
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    port = tmp_path / "game.port"
    port.write_text("title godzilla_le\nversion 1.16\n")
    mi.install(card, so, cfg, str(port))
    ref, _off = mi._ref(card)
    assert mk.debugfs_cat(ref, mi.MODE_DIR + "/game.port") == port.read_bytes()
    assert mk.debugfs_stat(ref, mi.MODE_DIR + "/game.port")["mode"] == 0o644
    assert set(mi.inspect(card)["files"]) == {"mode.so", "mode.cfg", "game.port"}

    # an install that brings no port leaves none behind: a port is measured for one
    # object, and a stale one under a new object would be worse than none
    mi.install(card, so, cfg)
    assert not mk.debugfs_exists(ref, mi.MODE_DIR + "/game.port")

    mi.install(card, so, cfg, str(port))
    assert mi.remove(card) == ["game.port", "mode.cfg", "mode.so"]
    assert not mk.debugfs_exists(ref, mi.MODE_DIR)


def test_install_is_idempotent(tmp_path):
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    mi.install(card, so, cfg)
    ref, _off = mi._ref(card)
    once = mk.debugfs_cat(ref, mi.GAME_MONITOR)
    mi.install(card, so, cfg)
    assert mk.debugfs_cat(ref, mi.GAME_MONITOR) == once


def test_inspect_reports_stock_then_installed(tmp_path):
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    info = mi.inspect(card)
    assert info["installed"] is False and info["hooked"] is False

    mi.install(card, so, cfg)
    info = mi.inspect(card)
    assert info["installed"] is True and info["hooked"] is True
    assert set(info["files"]) == {"mode.so", "mode.cfg"}


def test_refuses_a_monitor_it_does_not_recognise(tmp_path):
    """Never guess. A card whose game_monitor is not stock is not edited at all -
    and the refusal must happen BEFORE anything is written."""
    import mkmulticard as mk
    import mode_install as mi
    import modehook

    odd = STOCK_MONITOR.replace("\t$1\n", "\t/games/game\n")
    card = _mkcard(tmp_path, monitor=odd)
    so, cfg = _payload(tmp_path)
    ref, _off = mi._ref(card)

    with pytest.raises(modehook.Refused):
        mi.install(card, so, cfg)
    assert mk.debugfs_cat(ref, mi.GAME_MONITOR).decode() == odd
    assert not mk.debugfs_exists(ref, mi.MODE_DIR)


def test_refuses_a_missing_object_before_touching_the_card(tmp_path):
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    _so, cfg = _payload(tmp_path)
    with pytest.raises(mk.Refused):
        mi.install(card, str(tmp_path / "nope.so"), cfg)
    ref, _off = mi._ref(card)
    assert not mk.debugfs_exists(ref, mi.MODE_DIR)


def test_remove_on_a_stock_card_is_a_no_op(tmp_path):
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    ref, _off = mi._ref(card)
    before = mk.debugfs_cat(ref, mi.GAME_MONITOR)
    assert mi.remove(card) == []
    assert mk.debugfs_cat(ref, mi.GAME_MONITOR) == before


def test_cli_refusal_exits_2(tmp_path):
    """A build script that checks the exit code must see a refusal as a failure."""
    import mode_install as mi

    rc = mi.main(["install", str(tmp_path / "no.raw"),
                  "--so", str(tmp_path / "no.so"), "--cfg", str(tmp_path / "no.mode")])
    assert rc == 2


# ---- item 149: several modes on one card (mode.cfg, mode1.cfg, mode2.cfg ...) ---------
def _p2_image(card):
    """p2's bytes, for a byte-for-byte comparison of the whole partition."""
    import mkmulticard as mk

    off, length = mk.p2_range(card)
    with open(card, "rb") as f:
        f.seek(off)
        return f.read(length)


def test_install_places_several_mode_files_in_slot_order(tmp_path):
    """Write ships a project's modes: the first file is mode.cfg, the next mode1.cfg,
    each read back through a FRESH debugfs call."""
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    second = tmp_path / "atomic.mode"
    second.write_text("name ATOMIC BREATH\nseconds 25\n")
    port = tmp_path / "game.port"
    port.write_text("title godzilla_pro\nversion 1.15\n")
    names = mi.install(card, so, cfg, str(port), extra_cfgs=[str(second)])
    assert names == ["game.port", "mode.cfg", "mode.so", "mode1.cfg"]
    ref, _off = mi._ref(card)
    assert mk.debugfs_cat(ref, mi.MODE_DIR + "/mode.cfg") == open(cfg, "rb").read()
    assert mk.debugfs_cat(ref, mi.MODE_DIR + "/mode1.cfg") == second.read_bytes()
    assert mk.debugfs_stat(ref, mi.MODE_DIR + "/mode1.cfg")["mode"] == 0o644
    assert set(mi.inspect(card)["files"]) == {"mode.so", "mode.cfg", "mode1.cfg", "game.port"}
    assert mk.e2fsck(ref)[0] == 0


def test_reinstall_with_one_mode_drops_the_stale_second_file(tmp_path):
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    second = tmp_path / "atomic.mode"
    second.write_text("name ATOMIC BREATH\n")
    mi.install(card, so, cfg, extra_cfgs=[str(second)])
    mi.install(card, so, cfg)
    ref, _off = mi._ref(card)
    assert not mk.debugfs_exists(ref, mi.MODE_DIR + "/mode1.cfg")
    assert set(mi.inspect(card)["files"]) == {"mode.so", "mode.cfg"}


def test_removing_several_modes_leaves_p2_stock(tmp_path):
    """Removing every mode leaves the card stock: the game_monitor script byte for byte,
    its clocks, no padmode directory, e2fsck clean - with a mode1.cfg on the card, which
    the rmdir would trip over if remove() did not know the slot."""
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    ref, _off = mi._ref(card)
    mon_before = mk.debugfs_cat(ref, mi.GAME_MONITOR)
    st_before = mk.debugfs_stat(ref, mi.GAME_MONITOR)
    extras = []
    for i in range(1, 3):
        p = tmp_path / ("m%d.mode" % i)
        p.write_text("name MODE %d\n" % i)
        extras.append(str(p))
    mi.install(card, so, cfg, extra_cfgs=extras)
    assert mi.remove(card) == ["mode.cfg", "mode.so", "mode1.cfg", "mode2.cfg"]
    assert mk.debugfs_cat(ref, mi.GAME_MONITOR) == mon_before
    st_after = mk.debugfs_stat(ref, mi.GAME_MONITOR)
    for k in ("mode", "uid", "gid", "atime", "ctime", "mtime"):
        assert st_after[k] == st_before[k], k
    assert not mk.debugfs_exists(ref, mi.MODE_DIR)
    assert mk.e2fsck(ref)[0] == 0


def test_more_mode_files_than_slots_is_refused_before_writing(tmp_path):
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    before = _p2_image(card)
    with pytest.raises(mk.Refused):
        mi.install(card, so, cfg, extra_cfgs=[cfg] * (len(mi.EXTRA_CFGS) + 1))
    assert _p2_image(card) == before


def test_cli_takes_the_cfg_option_more_than_once(tmp_path):
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, cfg = _payload(tmp_path)
    second = tmp_path / "atomic.mode"
    second.write_text("name ATOMIC BREATH\n")
    assert mi.main(["install", card, "--so", so, "--cfg", cfg, "--cfg", str(second)]) == 0
    ref, _off = mi._ref(card)
    assert mk.debugfs_cat(ref, mi.MODE_DIR + "/mode1.cfg") == second.read_bytes()


# ---- a CODE mode's own assets (<slug>.assets, sdk/pad_mode_assets.h) --------------------------------------
def _assets(tmp_path, *slugs):
    out = []
    for slug in slugs:
        p = tmp_path / (slug + ".assets")
        p.write_text("name %s\nmusic 125 618\ncall won 1251 1500 4\n" % slug.upper())
        out.append(str(p))
    return out


def test_a_card_of_code_modes_only_needs_no_mode_file(tmp_path):
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, _cfg = _payload(tmp_path)
    port = tmp_path / "game.port"
    port.write_text("game godzilla_le\nversion 1.16\n")
    assets = _assets(tmp_path, "ghidorah_heads", "final_wars")
    names = mi.install(card, so, None, str(port), assets=assets)
    assert names == ["final_wars.assets", "game.port", "ghidorah_heads.assets", "mode.so"]
    ref, _off = mi._ref(card)
    assert mk.debugfs_cat(ref, mi.MODE_DIR + "/ghidorah_heads.assets") == open(assets[0], "rb").read()
    assert mk.debugfs_stat(ref, mi.MODE_DIR + "/final_wars.assets")["mode"] == 0o644
    assert not mk.debugfs_exists(ref, mi.MODE_DIR + "/mode.cfg")
    assert mk.e2fsck(ref)[0] == 0
    # a reinstall with one code mode drops the other's file; a form mode beside it keeps its mode.cfg
    _so, cfg = _payload(tmp_path)
    mi.install(card, so, cfg, str(port), assets=assets[:1])
    assert set(mi.inspect(card)["files"]) == {"mode.so", "mode.cfg", "game.port", "ghidorah_heads.assets"}
    assert sorted(mi.remove(card)) == ["game.port", "ghidorah_heads.assets", "mode.cfg", "mode.so"]
    assert not mk.debugfs_exists(ref, mi.MODE_DIR)


def test_an_install_with_neither_a_mode_file_nor_assets_or_a_bad_name_is_refused(tmp_path):
    import mkmulticard as mk
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, _cfg = _payload(tmp_path)
    with pytest.raises(mk.Refused, match="no mode file and no code mode's assets"):
        mi.install(card, so, None)
    bad = tmp_path / "Bad Name.assets"
    bad.write_text("name X\n")
    with pytest.raises(mk.Refused, match="is not a code mode's <slug>.assets"):
        mi.install(card, so, None, assets=[str(bad)])
    assert not mi.inspect(card)["installed"]


def test_cli_takes_asset_files_and_no_cfg(tmp_path):
    import mode_install as mi

    card = _mkcard(tmp_path)
    so, _cfg = _payload(tmp_path)
    (a,) = _assets(tmp_path, "anguirus_assist")
    assert mi.main(["install", card, "--so", so, "--asset", a]) == 0
    assert set(mi.inspect(card)["files"]) == {"mode.so", "anguirus_assist.assets"}
