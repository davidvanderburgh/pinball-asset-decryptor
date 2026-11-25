"""PAD-1585: the update guard for Stern's /etc/init.d/update, for the multi-boot builder (mkmulticard).

The twin of pinball_decryptor/core/update_guard.py's block and its guard/strip functions (a test holds them
equal): every card PAD writes - one game or multi-boot - carries it, so a Stern update on a USB stick or from
Insider Connected is never installed over the card. See that module for what the block does.
"""
from __future__ import annotations


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


class NotStern(Exception):
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
