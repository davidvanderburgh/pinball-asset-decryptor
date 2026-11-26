"""PAD-1585: Stern's own updater, made safe on a card PAD built.

A Spike 2 card runs ``/etc/init.d/update /games`` in the background at every power-up (the last section of
``/etc/init.d/game``). It looks for a ``*.spk`` downloaded over Insider Connected (``/connectivity/update`` with
the ``UPDATE_REQUESTED`` flag) and then, five times three seconds apart, on a USB stick; one found, it ends the
game, remounts /games read-write and runs Stern's installer (``spike_menu``), which unpacks the new code over the
card. On a card of ours that puts Stern's files over the owner's work, and on a multi-boot card it writes into
whichever game booted (through the shared files of a compact card, into every game at once).

So every Spike 2 card PAD writes carries a GUARD: a marked block at the top of Stern's own script (the script
itself stays, so a Stern change to it later is still Stern's). The block does the same looking Stern's code does
and then:

* a ``.spk`` on a USB stick: the game is held the way Send to machine holds it (its restart loop frozen, the game
  ended), the card's own message screen (``boot_display`` + ``dprint``, the pair Stern's updater uses for
  "APPLYING UPDATE PLEASE WAIT") says the update was not installed and that this card is updated with PAD, until
  the stick is taken out; then the game comes back. Nothing on the card is written.
* an Insider Connected download: the flag goes (as Stern's own script drops a flag with no ``.spk``), the screen
  says so for half a minute and the game comes back. The downloaded file is left where Stern put it.
* nothing waiting: the script ends, as Stern's does when it finds nothing.
* the way back to Stern's updater: a USB stick holding a file whose name starts ``stern-update-ok`` (any case,
  any extension, beside the ``.spk`` or alone) hands that power-up's update to Stern's code below the block.

A stock card never gets the block. :data:`GUARD_LINES` has a twin in ``tools/spike2_emu/updateguard.py`` for the
multi-boot builder (``mkmulticard.inject_into_p2``); a test holds them equal.
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from .card_extras import ExtrasError

#: Stern's updater on the card's system partition
UPDATE_SCRIPT = '/etc/init.d/update'
#: a file on a USB stick whose name starts so hands that power-up's update to Stern's updater
PASS_MARKER = 'stern-update-ok'
#: where the guard notes what it did, on the card's dump partition (writable, where the game's logs go)
GUARD_LOG = '/dump/pad-update-guard.log'
#: how long the screen says a refused download (seconds) before the game comes back
NET_SECONDS = 30
#: the longest the screen waits for the stick to come out (checks three seconds apart: half an hour)
USB_CHECKS = 600


def screen_text(*lines):
    """Four lines of sixteen characters, each centred: what the card's ``dprint`` shows (remote_send's twin)."""
    return "".join(str(l)[:16].center(16) for l in lines[:4]).rstrip()


#: what the game's screen says when an update on a USB stick is refused
USB_WORDS = ("STERN UPDATE", "NOT INSTALLED", "UPDATE WITH PAD", "REMOVE USB DRIVE")
#: and an Insider Connected download
NET_WORDS = ("STERN UPDATE", "NOT INSTALLED", "THIS CARD IS", "UPDATED WITH PAD")
USB_MESSAGE = screen_text(*USB_WORDS)
NET_MESSAGE = screen_text(*NET_WORDS)

GUARD_BEGIN = '# >>> PAD update guard (PAD-1585) >>>'
GUARD_END = '# <<< PAD update guard <<<'

GUARD_LINES = [
    GUARD_BEGIN,
    "# This card was built with PAD: a Stern update would put Stern's files over the owner's. An update waiting",
    "# on a USB stick or downloaded over Insider Connected is not installed and the screen says so; a USB stick",
    "# holding a file named %s* hands this power-up's update to Stern's updater below." % PASS_MARKER,
    'pad_spk() {',
    '  for f in "$1"/*.[sS][pP][kK] "$1"/*.[sS][pP][kK].[0-9][0-9][0-9].000; do',
    '    [ -f "$f" ] && return 0',
    '  done',
    '  return 1',
    '}',
    'pad_ok() {',
    "  ls \"$1\" 2>/dev/null | grep -qi '^%s'" % PASS_MARKER,
    '}',
    'pad_pids() {',
    '  for d in /proc/[0-9]*; do',
    '    read -r s < "$d/stat" 2>/dev/null || continue',
    '    case "$s" in *" ($1) "*) printf \'%s \' "${d#/proc/}" ;; esac',
    '  done',
    '}',
    'pad_log() {',
    '  echo "UPDATE: PAD: $1"',
    '  (echo "$(date) $1" >> %s) 2>/dev/null' % GUARD_LOG,
    '}',
    'pad_stick_in() {',
    '  for d in /dev/sda1 /dev/sda /dev/sdb1 /dev/sdb; do',
    '    if mount -r $d /media >/dev/null 2>&1; then',
    '      umount /media >/dev/null 2>&1',
    '      return 0',
    '    fi',
    '  done',
    '  return 1',
    '}',
    'pad_tell() {',
    '  pad_mon=""',
    '  i=0',
    '  while [ $i -lt 15 ] && [ -z "$pad_mon" ]; do',
    '    pad_mon=$(pad_pids game_monitor)',
    '    [ -z "$pad_mon" ] && sleep 1',
    '    i=$((i+1))',
    '  done',
    "  pad_marks=\" $(ls /tmp/game_restarts 2>/dev/null | tr '\\n' ' ') \"",
    '  [ -n "$pad_mon" ] && kill -STOP $pad_mon 2>/dev/null',
    '  pad_game=" $(pad_pids game)"',
    '  [ -n "${pad_game# }" ] && kill -9 $pad_game 2>/dev/null',
    '  pad_bd=""',
    '  pad_dp=""',
    '  for d in /games/spike3/bin /usr/local/spike /usr/local/bin; do',
    '    if [ -z "$pad_bd" ] && [ -x "$d/boot_display" ]; then pad_bd="$d/boot_display"; fi',
    '    if [ -z "$pad_dp" ] && [ -x "$d/dprint" ]; then pad_dp="$d/dprint"; fi',
    '  done',
    '  if [ -n "$pad_bd" ] && [ -n "$pad_dp" ]; then',
    "    (trap '' HUP; exec \"$pad_bd\") </dev/null >/dev/null 2>&1 &",
    '    sleep 1',
    '    "$pad_dp" "$1" >/dev/null 2>&1',
    '  fi',
    '}',
    'pad_back() {',
    '  for p in $(pad_pids boot_display); do kill $p 2>/dev/null; done',
    '  [ -n "$pad_mon" ] || return 0',
    '  kill -CONT $pad_mon 2>/dev/null',
    '  i=0',
    '  pad_new=""',
    '  while [ $i -lt 40 ] && [ -z "$pad_new" ]; do',
    '    for p in $(pad_pids game); do',
    '      case "$pad_game " in *" $p "*) ;; *) pad_new=$p ;; esac',
    '    done',
    '    [ -z "$pad_new" ] && sleep 1',
    '    i=$((i+1))',
    '  done',
    '  for f in $(ls /tmp/game_restarts 2>/dev/null); do',
    '    case "$pad_marks" in *" $f "*) ;; *) rm -f "/tmp/game_restarts/$f" ;; esac',
    '  done',
    '}',
    'pad_guard() {',
    '  umount /media >/dev/null 2>&1',
    '  pad_net=""',
    '  pad_usb=""',
    '  pad_pass=""',
    '  if [ -e /connectivity/update/UPDATE_REQUESTED ] && pad_spk /connectivity/update; then pad_net=1; fi',
    '  for a in 1 2 3 4 5; do',
    '    for d in /dev/sda1 /dev/sda /dev/sdb1 /dev/sdb; do',
    '      if mount -r $d /media >/dev/null 2>&1; then',
    '        pad_ok /media && pad_pass=1',
    '        pad_spk /media && pad_usb=1',
    '        umount /media >/dev/null 2>&1',
    '        if [ -n "$pad_pass$pad_usb" ]; then break 2; fi',
    '      fi',
    '    done',
    '    if [ -n "$pad_net" ]; then break; fi',
    '    sleep 3',
    '  done',
    '  if [ -n "$pad_pass" ]; then',
    '    pad_log "%s on the USB drive: Stern\'s updater runs"' % PASS_MARKER,
    '    return 0',
    '  fi',
    '  if [ -n "$pad_net" ]; then',
    '    rm -f /connectivity/update/UPDATE_REQUESTED',
    '    pad_log "refused the update downloaded over Insider Connected"',
    '  fi',
    '  if [ -n "$pad_usb" ]; then',
    '    pad_log "refused the update on the USB drive"',
    '    pad_tell "%s"' % USB_MESSAGE,
    '    i=0',
    '    while [ $i -lt %d ] && pad_stick_in; do sleep 3; i=$((i+1)); done' % USB_CHECKS,
    '    pad_log "USB drive out: the game is back"',
    '    pad_back',
    '  elif [ -n "$pad_net" ]; then',
    '    pad_tell "%s"' % NET_MESSAGE,
    '    sleep %d' % NET_SECONDS,
    '    pad_back',
    '  fi',
    '  return 1',
    '}',
    'if ! pad_guard; then exit 0; fi',
    GUARD_END,
]


class NotStern(ExtrasError):
    """The card's updater is not the script the guard knows: it is left alone."""


def stern_shaped(text):
    """True when *text* is Stern's Spike updater as the guard knows it (the USB and Insider Connected routes)."""
    if isinstance(text, bytes):
        text = text.decode('utf-8', 'replace')
    text = strip_guard(text)
    return (text.startswith('#!') and 'DOWNLOADED_SPK_AVAILABLE' in text and '[sS][pP][kK]' in text
            and 'update_monitor' in text and 'kill_game' in text)


def strip_guard(text):
    """*text* without the guard block (the inverse of :func:`guard_script`)."""
    if isinstance(text, bytes):
        text = text.decode('utf-8', 'replace')
    lines = text.split('\n')
    if GUARD_BEGIN not in lines:
        return text
    i = lines.index(GUARD_BEGIN)
    j = lines.index(GUARD_END, i) if GUARD_END in lines[i:] else None
    if j is None:
        raise NotStern('The update guard on this card has no end line.')
    del lines[i:j + 1]
    return '\n'.join(lines)


def has_guard(text):
    """True when *text* carries the guard as this app writes it (an older block reads False: it is renewed)."""
    if isinstance(text, bytes):
        text = text.decode('utf-8', 'replace')
    lines = text.split('\n')
    n = len(GUARD_LINES)
    return any(lines[k:k + n] == GUARD_LINES for k in range(len(lines) - n + 1))


def guard_script(text):
    """Stern's updater *text* with the guard as its first lines after ``#!``. Idempotent; an older guard is
    replaced. Raises :class:`NotStern` for a script that is not Stern's."""
    if isinstance(text, bytes):
        text = text.decode('utf-8')
    if not stern_shaped(text):
        raise NotStern("The card's updater is not the one Stern ships, so it was left as it is.")
    lines = strip_guard(text).split('\n')
    lines[1:1] = GUARD_LINES
    return '\n'.join(lines)


# ---------------------------------------------------------------------------------------------- the card
#: what a build says it did
GUARD_TEXT = ("Stern's updater guarded: a Stern update on a USB stick or from Insider Connected is not "
              "installed over this card (the game's screen says so).")


def _cancel(cancel):
    if cancel is not None and cancel():
        raise ExtrasError('Update guard canceled.')


def _command(ex, program, *args):
    from . import ssh_card
    return ssh_card._command(ex, program, *args)


def _script_of(r):
    from . import ssh_card
    node = ssh_card._node(r, UPDATE_SCRIPT)
    if node is None or stat.S_IFMT(node['mode']) != stat.S_IFREG or node['size'] > 256 * 1024:
        return None
    return r.read_file_bytes(node).decode('utf-8', 'replace')


def read_update_script(path, keys=None):
    """``(text or None, partition, encrypted)`` of the card image *path*: Stern's updater as it is on the card's
    system partition, None when it has none. A Spike 3 card's (encrypted) is read only with its *keys*."""
    from . import ssh_card
    from ..plugins.stern.ext4 import Ext4Reader
    with open(path, 'rb') as f:
        size = os.fstat(f.fileno()).st_size
        part, encrypted = ssh_card.system_partition(f, size)
        if not encrypted:
            return _script_of(Ext4Reader(f, part[2], part[3])), part, False
    if keys is None:
        return None, part, True
    from . import ssh_spike3
    with ssh_spike3.open_rootfs(path, key_source=keys) as vol:
        return _script_of(Ext4Reader(vol, 0, vol.size)), part, True


def state(path, keys=None):
    """'guarded', 'open' (Stern's updater, unguarded), 'other' (an updater the guard does not know), 'none' (no
    updater) or 'spike3' (an encrypted system partition and no *keys*) for the card image *path*."""
    text, _part, encrypted = read_update_script(path, keys)
    if encrypted and keys is None:
        return 'spike3'
    if text is None:
        return 'none'
    if has_guard(text):
        return 'guarded'
    return 'open' if stern_shaped(text) else 'other'


def prepare_rootfs(part, work, cancel=None):
    """Guard Stern's updater on the scratch copy *part* of a Spike 2 system partition (never a card)."""
    from . import ssh_card
    from .executor import create_executor
    from ..plugins.stern.ext4 import Ext4Reader
    part, work = Path(part), Path(work)
    ex = create_executor()
    exec_part = ex.to_exec_path(str(part))
    _command(ex, 'e2fsck', '-fn', exec_part)
    with part.open('rb') as f:
        r = Ext4Reader(f, 0, part.stat().st_size)
        node = ssh_card._node(r, UPDATE_SCRIPT)
        if node is None or stat.S_IFMT(node['mode']) != stat.S_IFREG or node['links'] != 1:
            raise NotStern("The card's updater is missing or not a plain file, so it was left as it is.")
        old = r.read_file_bytes(node)
    guarded = guard_script(old).encode('utf-8')
    _cancel(cancel)
    staged = work / 'update.guarded'
    staged.write_bytes(guarded)
    src = ex.to_exec_path(str(staged))
    if any(c in src for c in ('"', '\n', '\r', '\\')):
        raise ExtrasError('The update guard staging path contains unsupported filesystem-tool characters.')
    mode = stat.S_IFREG | (stat.S_IMODE(node['mode']) or 0o755)
    cmds = ['rm %s' % UPDATE_SCRIPT, 'write "%s" %s' % (src, UPDATE_SCRIPT),
            'set_inode_field %s mode 0%o' % (UPDATE_SCRIPT, mode),
            'set_inode_field %s uid %d' % (UPDATE_SCRIPT, node.get('uid', 0)),
            'set_inode_field %s gid %d' % (UPDATE_SCRIPT, node.get('gid', 0))]
    # Stern's times kept, as the multi-boot builder keeps them: its p2 fingerprint reads a guarded card as its source
    cmds += ['set_inode_field %s %s @%d' % (UPDATE_SCRIPT, k, node[k]) for k in ('atime', 'ctime', 'mtime') if node.get(k)]
    script = work / 'debugfs.update-guard'
    script.write_text('\n'.join(cmds) + '\n')
    _command(ex, 'debugfs', '-w', '-f', ex.to_exec_path(str(script)), exec_part)
    _command(ex, 'e2fsck', '-fn', exec_part)
    with part.open('rb') as f:
        r = Ext4Reader(f, 0, part.stat().st_size)
        node = ssh_card._node(r, UPDATE_SCRIPT)
        if node is None or r.read_file_bytes(node) != guarded or stat.S_IMODE(node['mode']) != stat.S_IMODE(mode):
            raise ExtrasError("Stern's updater did not read back as guarded.")


def apply_to_build(original, output, log=None, cancel=None):
    """Guard Stern's updater on the built Spike 2 image *output* (a copy, never *original*). Returns the line
    for the build's summary, '' when the card has nothing to guard (a Spike 3 card: its own step; an updater
    the guard does not know: said in the log, the card left as it is). A failure part way raises: the pipeline
    quarantines the image as it does for the other system-partition steps."""
    from . import ssh_card
    if os.path.samefile(original, output):
        raise ExtrasError('The update guard must not write the original image.')
    text, part, encrypted = read_update_script(output)
    if encrypted:
        return ''
    if text is None:
        if log:
            log("This card has no Stern updater (%s), so there is nothing to guard." % UPDATE_SCRIPT, 'info')
        return ''
    if has_guard(text):
        if log:
            log(GUARD_TEXT, 'info')
        return GUARD_TEXT
    if not stern_shaped(text):
        if log:
            log("The card's updater is not the one Stern ships, so it was left as it is: a Stern update on it "
                "would install over this card.", 'warning')
        return ''
    _cancel(cancel)
    _, _, start, size = part
    if shutil.disk_usage(Path(output).parent).free < size + (32 << 20):
        raise ExtrasError("Not enough free space to guard Stern's updater on the system partition.")
    ssh_card.rewrite_partition(output, start, size, lambda p, work: prepare_rootfs(p, work, cancel),
                               cancel, what='Update guard', stop=_cancel)
    if state(output) != 'guarded':
        raise ExtrasError("Stern's updater on the built image did not read back as guarded.")
    if log:
        log(GUARD_TEXT, 'info')
    return GUARD_TEXT


def apply_to_spike3_build(original, output, keys, log=None, cancel=None):
    """:func:`apply_to_build` for a Spike 3 image *output*: its system partition is opened with the card's *keys*
    and rewritten through ``ssh_spike3.rewrite_rootfs`` (the checked way remote access changes it)."""
    from . import ssh_spike3
    if os.path.samefile(original, output):
        raise ExtrasError('The update guard must not write the original image.')
    now = state(output, keys)
    if now == 'guarded':
        if log:
            log(GUARD_TEXT, 'info')
        return GUARD_TEXT
    if now != 'open':
        if log:
            log("This card's updater is not the one Stern ships (or it has none), so it was left as it is.",
                'warning' if now == 'other' else 'info')
        return ''
    ssh_spike3.rewrite_rootfs(output, lambda p, work: prepare_rootfs(p, work, cancel), keys, cancel=cancel,
                              what='Update guard', stop=_cancel)
    if state(output, keys) != 'guarded':
        raise ExtrasError("Stern's updater on the built image did not read back as guarded.")
    if log:
        log(GUARD_TEXT, 'info')
    return GUARD_TEXT
