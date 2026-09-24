#!/usr/bin/env python3
"""mode_install.py - item 128: put a mode of our own on a card's p2, and take it
off again leaving the card stock.

    mode_install.py install <card.raw> --so <mode.so> --cfg <x.mode> [--cfg <y.mode> ...] [--port <game.port>]
                                       [--asset <slug>.assets ...]
    mode_install.py remove  <card.raw>
    mode_install.py inspect <card.raw>

Several --cfg (item 149): the first is mode.cfg, the rest mode1.cfg .. mode7.cfg.
--asset (a CODE mode's own assets, sdk/pad_mode_assets.h): <slug>.assets beside mode.so, one per
code mode, naming the carriers the build gave its music and calls. A card of code modes only needs no
--cfg: the object carries the modes and each .assets file names one.

WHAT GOES WHERE, and why it is split across two partitions (measured on a stock
Godzilla Pro 1.15 p2 with debugfs, no mount, no guest):

  p2  /usr/local/padmode/mode.so    0100755 root:root   the object
      /usr/local/padmode/mode.cfg   0100644 root:root   the mode, as data
      /usr/local/padmode/game.port  0100644 root:root   the SDK runtime's port for this
                                                        game (item 134) - the object
                                                        reads it beside its mode files
      /etc/init.d/game_monitor      hooked, see modehook.py

The port is optional here because item 128's own mode.c carried its addresses inside
the object; the SDK runtime (item 134) does not, and refuses to arm without a port.
The first hardware card (Godzilla Premium 1.16, 2026-09-16) had the port placed by a
copy of this sequence in a scratch script; this is that third file, done properly.

  p6  /dump/mode.log, /dump/mode.start, /dump/mode.stop   left to the object

p2 is mounted READ-ONLY on a machine (`/dev/root / auto ro,ro` in fstab; the init
script remounts rw only when it must write), which is fine for an object and a
config the game only reads, and impossible for a log. /dump is a partition of its
own (`/dev/mmcblk0p6`), so the log stays there - mode.c looks for its mode file at
the p2 path first and the /dump path second, so the rig's hot reload is unchanged.

THIS IS write_select_files WITH THREE DELIBERATE DIFFERENCES. That function is the
hardware-proven way to put small files on p2 - a debugfs -w script straight into
the card (rm, write, mode/uid/gid), e2fsck before AND after, a free-space refusal,
a full read-back compare, the p2 md5 sidecar rewritten - and its docstring says
why it beats extract/write-back: "a kill mid-script leaves at worst one small file
half written... the rootfs stays bootable". The differences:

  1. It REFUSES a card with no /usr/local/codeselect ("not a multi-boot card").
     A STOCK card is exactly what this targets, so an absent /usr/local/padmode
     means mkdir, never a refusal. (/usr/local itself already exists on a stock
     p2 - inode 1987, 040755 root:root, holding bin/ and spike/ - so there is no
     new parent to make.)
  2. It forces 0100644. mode.so needs 0100755.
  3. Removal restores /etc/init.d/game_monitor's atime/ctime/mtime. Item 129
     measured that two otherwise identical card builds differ in exactly 130
     bytes and every one of them is an ext4 clock, so a removal that leaves new
     timestamps is not "the card stock" in the only sense that can be checked.
"""
import argparse
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mkmulticard as mk            # noqa: E402  (imports clean, no side effects)
import modehook                     # noqa: E402

MODE_DIR = modehook.MODE_DIR
GAME_MONITOR = "/etc/init.d/game_monitor"

#: name on the card -> mode. The .so is executable; the mode file is data.
CARD_FILES = (("mode.so", 0o100755), ("mode.cfg", 0o100644))
#: the SDK runtime's port, placed when the install is given one
PORT_FILE = ("game.port", 0o100644)
#: item 149: a card holds up to eight modes, the slots mode.so reads (item 133) -
#: mode.cfg, then mode1.cfg .. mode7.cfg. These are the seven after the first.
EXTRA_CFGS = tuple(("mode%d.cfg" % i, 0o100644) for i in range(1, 8))
#: item 160: the "counts as" table of the game's own rules (sdk/MODE_SDK.md "Counts as"), the
#: only other data file the runtime reads beside its mode files; placed when the install is
#: given one (--file), taken off when it is not
EXTRA_FILES = (("stock.cfg", 0o100644),)
#: everything an install can leave behind, for remove() and inspect(). Every slot is
#: listed, so a removal takes a leftover mode1.cfg too and the rmdir cannot fail on it.
ALL_FILES = CARD_FILES + (PORT_FILE,) + EXTRA_CFGS + EXTRA_FILES
#: a code mode's own assets file: <slug>.assets, the slug a card project folder name
ASSET_SUFFIX = ".assets"
ASSET_MODE = 0o100644


def asset_name_ok(name):
    stem = name[:-len(ASSET_SUFFIX)] if name.endswith(ASSET_SUFFIX) else ""
    return bool(stem) and all(c.isalnum() or c == "_" for c in stem) and stem == stem.lower()


def _ref(card):
    off, _len = mk.p2_range(card)
    return mk.fs_ref(card, off), off


def _restore_monitor_attrs(st):
    """The debugfs commands that put game_monitor's owner, mode and clocks back.

    THE FILE-TYPE BITS ARE THE TRAP. debugfs prints `Mode:  0755` - permission
    bits ONLY, no S_IFREG - and debugfs_stat parses exactly that, so writing the
    value straight back with `set_inode_field ... mode 0755` strips the type
    nibble. e2fsck then says

        Inode 21 (/etc/init.d/game_monitor) has invalid mode (0755).
        Entry 'game_monitor' in /etc/init.d has an incorrect filetype (was 1, should be 0).

    which is a corrupt rootfs, not a cosmetic difference. mkmulticard writes
    `statmod.S_IFREG | mode` for the same reason; this is that, in one place, so
    install and remove cannot drift apart.

    The clocks are restored for item 129's reason: two otherwise identical card
    builds differ in exactly 130 bytes and every one of them is an ext4
    timestamp, so a card whose game_monitor carries new clocks is not "stock" in
    the only sense that can actually be checked.
    """
    c = mk.dq(GAME_MONITOR)
    mode = st.get("mode", 0o755) & 0o7777          # keep permission bits only...
    cmds = ["set_inode_field %s mode 0%o" % (c, stat.S_IFREG | mode),   # ...then say it is a FILE
            "set_inode_field %s uid %d" % (c, st.get("uid", 0)),
            "set_inode_field %s gid %d" % (c, st.get("gid", 0))]
    for k in ("atime", "ctime", "mtime"):
        if k in st:
            cmds.append("set_inode_field %s %s @%d" % (c, k, st[k]))
    return cmds


def _clean(ref, card, when):
    rc, txt = mk.e2fsck(ref)
    if rc != 0:
        raise mk.Refused("p2 of %s is not clean %s (e2fsck rc=%d):\n%s"
                         % (card, when, rc, txt.strip()[-600:]))
    return txt


def _free_bytes(card, off, fsck_txt):
    used, total = mk.e2fsck_blocks(fsck_txt)
    bs = mk.ext_block_size(card, off)
    return (total - used) * bs, total * bs


def inspect(card):
    """-> {'installed': bool, 'hooked': bool, 'files': {name: size}}"""
    ref, _off = _ref(card)
    out = {"installed": False, "hooked": False, "files": {}}
    if mk.debugfs_exists(ref, MODE_DIR):
        out["installed"] = True
        for e in mk.debugfs_ls(ref, MODE_DIR):
            if e[4] not in (".", ".."):
                out["files"][e[4]] = e[5]
    mon = mk.debugfs_cat(ref, GAME_MONITOR)
    out["hooked"] = modehook.has_hook(mon)
    return out


def install(card, so_path, cfg_path, port_path=None, workdir=None, extra_cfgs=(), assets=(),
            extras=()):
    """Put mode.so + mode.cfg (+ game.port) on p2 and hook game_monitor. Idempotent.
    A port left on p2 by an earlier install is removed when this one brings none.

    ``extra_cfgs`` (item 149): the mode files for slots 1.. in order, placed as
    mode1.cfg, mode2.cfg ... A slot file an earlier install left and this one does not
    bring is removed, so the card holds exactly the modes asked for.

    ``assets``: the code modes' ``<slug>.assets`` files, placed under their own names; a card
    of code modes only has no ``cfg_path`` (None). An .assets file an earlier install left and
    this one does not bring is removed too.

    ``extras`` (item 160): the runtime's other data files by their own names, today only
    ``stock.cfg`` (:data:`EXTRA_FILES`); one an earlier install left and this one does not
    bring is removed too."""
    mk.need_tools("debugfs", "e2fsck")
    extra_cfgs = list(extra_cfgs or ())
    assets = list(assets or ())
    extras = list(extras or ())
    for x in extras:
        if os.path.basename(x) not in dict(EXTRA_FILES):
            raise mk.Refused("%s is not a file the mode runtime reads (%s) - nothing has been written"
                             % (os.path.basename(x), ", ".join(n for n, _m in EXTRA_FILES)))
    if len(extra_cfgs) > len(EXTRA_CFGS):
        raise mk.Refused("a card holds at most %d mode files - nothing has been written"
                         % (1 + len(EXTRA_CFGS)))
    if not cfg_path and not assets:
        raise mk.Refused("no mode file and no code mode's assets - nothing has been written")
    if extra_cfgs and not cfg_path:
        raise mk.Refused("slot files without a mode.cfg - nothing has been written")
    for a in assets:
        if not asset_name_ok(os.path.basename(a)):
            raise mk.Refused("%s is not a code mode's <slug>.assets - nothing has been written"
                             % os.path.basename(a))
    given = [so_path] + ([cfg_path] if cfg_path else []) + ([port_path] if port_path else [])
    for p in given + extra_cfgs + assets + extras:
        if not os.path.isfile(p):
            raise mk.Refused("%s is not a file - nothing has been written" % p)
    files = ((CARD_FILES if cfg_path else CARD_FILES[:1]) + ((PORT_FILE,) if port_path else ())
             + EXTRA_CFGS[:len(extra_cfgs)] + tuple((os.path.basename(a), ASSET_MODE) for a in assets)
             + tuple((os.path.basename(x), dict(EXTRA_FILES)[os.path.basename(x)]) for x in extras))
    ref, off = _ref(card)

    # The script we are about to edit, and the hook, BEFORE anything is written:
    # a refusal here must cost nothing.
    mon_before = mk.debugfs_cat(ref, GAME_MONITOR)
    st = mk.debugfs_stat(ref, GAME_MONITOR)
    mon_after = modehook.hook_game_monitor(mon_before).encode("utf-8")

    txt = _clean(ref, card, "before the write")
    free, _total = _free_bytes(card, off, txt)
    payload = {"mode.so": open(so_path, "rb").read()}
    if cfg_path:
        payload["mode.cfg"] = open(cfg_path, "rb").read()
    for a in assets + extras:
        with open(a, "rb") as f:
            payload[os.path.basename(a)] = f.read()
    if port_path:
        payload[PORT_FILE[0]] = open(port_path, "rb").read()
    for (name, _mode), p in zip(EXTRA_CFGS, extra_cfgs):
        with open(p, "rb") as f:
            payload[name] = f.read()
    need = sum(len(b) for b in payload.values()) + len(mon_after)
    if need > free - mk.P2_FREE_MARGIN:
        raise mk.Refused("p2 has %d KB free and the mode needs %d KB (margin %d KB)"
                         % (free >> 10, need >> 10, mk.P2_FREE_MARGIN >> 10))

    stage = tempfile.mkdtemp(prefix="mode_install.", dir=workdir)
    try:
        cmds = []
        if not mk.debugfs_exists(ref, MODE_DIR):
            cmds.append("mkdir " + mk.dq(MODE_DIR))
        present = {e[4] for e in mk.debugfs_ls(ref, MODE_DIR)} \
            if mk.debugfs_exists(ref, MODE_DIR) else set()
        staged = []
        for name, mode in files:
            p = os.path.join(stage, name)
            with open(p, "wb") as f:
                f.write(payload[name])
            staged.append((p, name, mode))
        p_mon = os.path.join(stage, "game_monitor")
        with open(p_mon, "wb") as f:
            f.write(mon_after)
        # rm only what is there (debugfs reports a missing rm as an error line),
        # then every write, then every attribute - the order write_select_files uses.
        # A file this install does not bring (a port from an earlier one) goes too:
        # the directory holds exactly what was asked for, so a stale port cannot
        # outlive the object it was measured for.
        cmds += ["rm " + mk.dq(MODE_DIR + "/" + n) for (n, _m) in ALL_FILES if n in present]
        cmds += ["rm " + mk.dq(MODE_DIR + "/" + n) for n in sorted(present) if n.endswith(ASSET_SUFFIX)]
        cmds.append("rm " + mk.dq(GAME_MONITOR))
        cmds += ["write %s %s" % (mk.dq(p), mk.dq(MODE_DIR + "/" + n)) for (p, n, _m) in staged]
        cmds.append("write %s %s" % (mk.dq(p_mon), mk.dq(GAME_MONITOR)))
        cmds += ["set_inode_field %s mode 040755" % mk.dq(MODE_DIR),
                 "set_inode_field %s uid 0" % mk.dq(MODE_DIR),
                 "set_inode_field %s gid 0" % mk.dq(MODE_DIR)]
        for _p, n, mode in staged:
            c = mk.dq(MODE_DIR + "/" + n)
            cmds += ["set_inode_field %s mode 0%o" % (c, mode),
                     "set_inode_field %s uid 0" % c, "set_inode_field %s gid 0" % c]
        cmds += _restore_monitor_attrs(st)
        mk.debugfs_write_script(ref, cmds)
    finally:
        import shutil
        shutil.rmtree(stage, ignore_errors=True)

    _clean(ref, card, "after the write")
    # Read back through a FRESH debugfs call, never a held handle: item 129 found a
    # copy reallocates blocks and a reader opened earlier reads stale extents.
    for name, _mode in files:
        if mk.debugfs_cat(ref, MODE_DIR + "/" + name) != payload[name]:
            raise mk.Refused("%s read back from p2 differs from what was written" % name)
    if mk.debugfs_cat(ref, GAME_MONITOR) != mon_after:
        raise mk.Refused("%s read back from p2 differs from what was written" % GAME_MONITOR)
    mk.write_p2_sidecar(card)
    return sorted(payload)


def remove(card, workdir=None):
    """Take the mode off and restore game_monitor - the exact inverse of install."""
    mk.need_tools("debugfs", "e2fsck")
    ref, _off = _ref(card)
    mon_before = mk.debugfs_cat(ref, GAME_MONITOR)
    st = mk.debugfs_stat(ref, GAME_MONITOR)
    mon_after = modehook.strip_hook(mon_before).encode("utf-8")
    _clean(ref, card, "before the removal")

    present = {e[4] for e in mk.debugfs_ls(ref, MODE_DIR)} \
        if mk.debugfs_exists(ref, MODE_DIR) else set()
    stage = tempfile.mkdtemp(prefix="mode_remove.", dir=workdir)
    try:
        cmds = ["rm " + mk.dq(MODE_DIR + "/" + n) for (n, _m) in ALL_FILES if n in present]
        cmds += ["rm " + mk.dq(MODE_DIR + "/" + n) for n in sorted(present) if n.endswith(ASSET_SUFFIX)]
        if present or mk.debugfs_exists(ref, MODE_DIR):
            cmds.append("rmdir " + mk.dq(MODE_DIR))
        if mon_after != mon_before:
            p_mon = os.path.join(stage, "game_monitor")
            with open(p_mon, "wb") as f:
                f.write(mon_after)
            cmds.append("rm " + mk.dq(GAME_MONITOR))
            cmds.append("write %s %s" % (mk.dq(p_mon), mk.dq(GAME_MONITOR)))
            # The SAME helper install uses - owner, mode with the S_IFREG bits put
            # back, and the clocks. Two copies of this drifted apart once already:
            # install was fixed and remove was not, which would have corrupted the
            # inode on the way out while the install half looked healthy.
            cmds += _restore_monitor_attrs(st)
        if not cmds:
            return []
        mk.debugfs_write_script(ref, cmds)
    finally:
        import shutil
        shutil.rmtree(stage, ignore_errors=True)

    _clean(ref, card, "after the removal")
    if mk.debugfs_exists(ref, MODE_DIR):
        raise mk.Refused("%s is still on p2 after the removal" % MODE_DIR)
    back = mk.debugfs_cat(ref, GAME_MONITOR)
    if modehook.has_hook(back):
        raise mk.Refused("%s still carries the mode hook after the removal" % GAME_MONITOR)
    mk.write_p2_sidecar(card)
    return sorted(n for n in present if n in dict(ALL_FILES) or n.endswith(ASSET_SUFFIX))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("install")
    p.add_argument("card")
    p.add_argument("--so", required=True)
    p.add_argument("--cfg", action="append", default=[],
                   help="a mode file; repeat it for several modes (item 149): the first "
                        "goes on the card as mode.cfg, the next as mode1.cfg, and so on")
    p.add_argument("--asset", action="append", default=[],
                   help="a code mode's <slug>.assets (sdk/pad_mode_assets.h); repeat it for "
                        "several code modes. A card of code modes only needs no --cfg")
    p.add_argument("--file", action="append", default=[],
                   help="another data file the runtime reads beside its mode files, by its own "
                        "name: stock.cfg, the counts-as table of the game's own rules (item 160)")
    p.add_argument("--port", help="the SDK runtime's port file for this game (item 134)")
    p.add_argument("--workdir")
    p = sub.add_parser("remove")
    p.add_argument("card")
    p.add_argument("--workdir")
    p = sub.add_parser("inspect")
    p.add_argument("card")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "install":
            names = install(a.card, a.so, a.cfg[0] if a.cfg else None, a.port, a.workdir,
                            extra_cfgs=a.cfg[1:], assets=a.asset, extras=a.file)
            print("[mode] installed %s into %s and hooked %s"
                  % (", ".join(names), MODE_DIR, GAME_MONITOR))
        elif a.cmd == "remove":
            names = remove(a.card, a.workdir)
            print("[mode] removed %s; %s restored"
                  % (", ".join(names) or "nothing", GAME_MONITOR))
        else:
            info = inspect(a.card)
            print("[mode] %s: %s, game_monitor %s"
                  % (MODE_DIR,
                     ("%d file(s): %s" % (len(info["files"]),
                                          ", ".join("%s %d B" % (k, v)
                                                    for k, v in sorted(info["files"].items()))))
                     if info["installed"] else "absent",
                     "hooked" if info["hooked"] else "stock"))
    except mk.Refused as e:
        print("[mode] refused: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
