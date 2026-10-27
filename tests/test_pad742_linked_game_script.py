"""PAD-742: a card whose /etc/init.d/game (or game_monitor) is a LINK.

Stern's downloads carry both scripts as plain files, but a card that has been on
a machine can carry either as a link to the real script. debugfs's cat and stat
do not follow the last link of a path: cat read the link's target text as block
numbers and every multi-boot build from that card's backup stopped at

    debugfs 'cat /etc/init.d/game' ... failed: cat: Attempt to read block from
    filesystem resulted in short read while reading ext2 file

Now the scripts are read and rewritten where the link leads, and the link stays.

The pure resolver runs everywhere; the rest builds a real ext4 rootfs and needs
e2fsprogs (WSL/Linux), like test_spike2_mode_install.
"""
import os
import shutil
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
sys.path.insert(0, RIG)

pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(RIG, "mkmulticard.py")),
                                reason="the spike2 rig is not in this checkout")

needs_e2fs = pytest.mark.skipif(
    not (shutil.which("mke2fs") and shutil.which("debugfs") and shutil.which("e2fsck")),
    reason="needs e2fsprogs (mke2fs, debugfs, e2fsck)")


@pytest.fixture
def mk():
    import mkmulticard
    return mkmulticard


# ---- the resolver (pure) ----------------------------------------------------------------------
def _links(table):
    return lambda p: table.get(p)


@pytest.mark.parametrize("table, want", [
    ({}, "/etc/init.d/game"),                                                  # stock: no link
    ({"/etc/init.d/game": "game.real"}, "/etc/init.d/game.real"),             # relative
    ({"/etc/init.d/game": "/usr/local/spike/game"}, "/usr/local/spike/game"),  # absolute
    ({"/etc/init.d/game": "../../opt/./game"}, "/opt/game"),                  # .. and .
    ({"/etc/init.d/game": "a", "/etc/init.d/a": "b"}, "/etc/init.d/b"),        # a chain
    ({"/etc/init.d": "rc.d", "/etc/rc.d/game": "/x/g"}, "/x/g"),               # a linked directory
])
def test_resolve_link_path_follows_every_link_on_the_way(mk, table, want):
    assert mk.resolve_link_path("/etc/init.d/game", _links(table)) == want


def test_resolve_link_path_refuses_a_loop(mk):
    with pytest.raises(mk.Refused, match="loop"):
        mk.resolve_link_path("/etc/init.d/game", _links({"/etc/init.d/game": "game"}))


def test_inject_commands_rewrite_the_file_the_link_leads_to(mk):
    items = [("/stage/game", "/etc/init.d/game.real", 0o755)]
    cmds = mk.inject_commands(items, [], {"mtime": 5}, game_path="/etc/init.d/game.real")
    assert 'rm "/etc/init.d/game.real"' in cmds
    assert not any('"/etc/init.d/game"' in c for c in cmds)
    assert 'set_inode_field "/etc/init.d/game.real" mtime @5' in cmds


def test_the_monitor_hook_goes_to_the_file_the_link_leads_to(mk):
    cmds = mk.mode_set_commands([], None, False, ("/stage/game_monitor", {}, "/opt/mon"))
    assert 'write "/stage/game_monitor" "/opt/mon"' in cmds
    assert not any(mk.GAME_MONITOR + '"' in c for c in cmds)
    # the two-field form callers already pass still means GAME_MONITOR itself
    cmds = mk.mode_set_commands([], None, False, ("/stage/game_monitor", {}))
    assert 'rm "%s"' % mk.GAME_MONITOR in cmds


# ---- on a real rootfs -------------------------------------------------------------------------
def _rootfs(tmp_path, mk, game_link=None, game_at="/etc/init.d/game", monitor_link=None,
            blocks=16384):
    """A 1 KiB-block ext4 like Stern's p2: /etc/init.d/game (SYNTH_GAME) + game_monitor, root
    owned, at the paths given; `game_link` / `monitor_link` put a symlink at the stock path."""
    from tests.test_spike2_mode_install import STOCK_MONITOR
    img = str(tmp_path / "p2.img")
    root = tmp_path / "root"
    files = {game_at: mk.SYNTH_GAME, "/usr/local/spike/game_monitor" if monitor_link
             else mk.GAME_MONITOR: STOCK_MONITOR}
    for path, text in files.items():
        p = root / path.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        p.chmod(0o755)
    for path, target in ((mk.GAME_SCRIPT, game_link), (mk.GAME_MONITOR, monitor_link)):
        if target:
            p = root / path.lstrip("/")
            p.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, p)
    os.makedirs(root / "games", exist_ok=True)
    os.makedirs(root / "usr" / "local", exist_ok=True)
    subprocess.run(["mke2fs", "-q", "-F", "-t", "ext3", "-b", "1024", "-d", str(root), "-E",
                    "root_owner=0:0", img, str(blocks)], check=True)
    return img


def _selector(tmp_path):
    sel = tmp_path / "sel"
    sel.mkdir()
    (sel / "codeselect").write_bytes(b"\x7fELF codeselect stand-in\n")
    (sel / "select.sh").write_text("#!/bin/sh\n")
    return str(sel)


def _inject(mk, img, tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir(exist_ok=True)
    conf = mk.render_images_conf(["/dev/mmcblk0p3", "/dev/mmcblk0p7"], ["A", "B"])
    return mk.inject_into_p2(img, _selector(tmp_path), conf, str(stage))


def _link(mk, img, path):
    return mk.debugfs_readlink(img, path)


@needs_e2fs
def test_the_users_error_is_debugfs_reading_a_link(mk, tmp_path):
    """The reported failure, reproduced: cat of a linked game script is a 'short read'."""
    img = _rootfs(tmp_path, mk, game_link="game.real", game_at="/etc/init.d/game.real")
    with pytest.raises(mk.Refused, match="short read"):
        mk.debugfs_cat(img, mk.GAME_SCRIPT)


@needs_e2fs
@pytest.mark.parametrize("link, real", [
    ("game.real", "/etc/init.d/game.real"),                         # a fast (short) link
    ("/usr/local/spike/" + "x" * 64 + "/game", "/usr/local/spike/" + "x" * 64 + "/game"),  # slow
])
def test_inject_hooks_the_linked_script_and_keeps_the_link(mk, tmp_path, link, real):
    img = _rootfs(tmp_path, mk, game_link=link, game_at=real)
    _inject(mk, img, tmp_path)
    assert _link(mk, img, mk.GAME_SCRIPT) == link                   # the card's link, untouched
    hooked = mk.debugfs_cat(img, real).decode()
    assert mk.has_hook(hooked) and mk.strip_hook(hooked) == mk.SYNTH_GAME
    assert mk.e2fsck(img)[0] == 0
    # and back out again: the script is the card's own, still behind its link
    assert mk.clean_p2(img)[0] is True
    assert mk.debugfs_cat(img, real).decode() == mk.SYNTH_GAME
    assert _link(mk, img, mk.GAME_SCRIPT) == link


@needs_e2fs
def test_a_stock_card_is_hooked_exactly_as_before(mk, tmp_path):
    img = _rootfs(tmp_path, mk)
    assert mk.p2_file(img, mk.GAME_SCRIPT) == mk.GAME_SCRIPT
    _inject(mk, img, tmp_path)
    assert mk.has_hook(mk.debugfs_cat(img, mk.GAME_SCRIPT).decode())
    assert mk.debugfs_stat(img, mk.GAME_SCRIPT)["type"] == "regular"


@needs_e2fs
def test_a_link_off_the_rootfs_is_refused_by_name(mk, tmp_path):
    """/games is another partition's mount point: the script is not on p2 to hook."""
    img = _rootfs(tmp_path, mk, game_link="/games/game_script", game_at="/etc/init.d/game.unused")
    with pytest.raises(mk.Refused, match=r"/etc/init.d/game on this card is a link to "
                                         r"/games/game_script, which is not a file on the rootfs"):
        _inject(mk, img, tmp_path)


@needs_e2fs
def test_a_filesystem_bigger_than_its_partition_is_not_clean(mk, tmp_path):
    """e2fsck -n answers 'Abort? no' and exits 0; every block past the end then reads short."""
    img = _rootfs(tmp_path, mk)
    os.truncate(img, 15 << 20)          # the last MiB of the filesystem is past the end
    rc, txt = mk.e2fsck(img)
    assert rc != 0 and "bigger than its partition" in txt


@needs_e2fs
def test_mode_install_hooks_a_linked_monitor_and_removes_it_again(tmp_path):
    """The Modes tab's write (mode_install) on the same kind of card: game_monitor a link."""
    import mkmulticard as mk
    import mode_install as mi
    from tests.test_spike2_mode_install import _mbr, _payload

    img = _rootfs(tmp_path, mk, monitor_link="../../usr/local/spike/game_monitor", blocks=65536)
    card = tmp_path / "card.raw"
    with open(card, "wb") as out:
        out.write(_mbr(24576, 65536 * 2))
        out.truncate(24576 * 512)
        out.seek(24576 * 512)
        out.write(open(img, "rb").read())
    card = str(card)
    ref, _off = mi._ref(card)
    real = "/usr/local/spike/game_monitor"
    before = mk.debugfs_cat(ref, real)
    so, cfg = _payload(tmp_path)
    mi.install(card, so, cfg)
    assert mk.debugfs_readlink(ref, mi.GAME_MONITOR) == "../../usr/local/spike/game_monitor"
    assert mi.inspect(card)["hooked"]
    # the emulator's own read of it (cardmodes.sh: parts.py --rootfs-file) sees the hook too
    import parts
    assert parts._cat(card, 24576 * 512, mi.GAME_MONITOR) == mk.debugfs_cat(ref, real).decode()
    mi.remove(card)
    assert mk.debugfs_cat(ref, real) == before
    assert mk.debugfs_readlink(ref, mi.GAME_MONITOR) == "../../usr/local/spike/game_monitor"
    assert mk.debugfs_stat(ref, real)["type"] == "regular"
