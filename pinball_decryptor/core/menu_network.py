"""The boot menu and the test card on the network, with no game running (Simon, 2026-11-25/26).

Simon: "I thought we were putting the update network stuff into the test card side?"  A card with remote access
(core/ssh_card.py) starts its SSH server at power-up, but on a Spike 2 card only the loopback interface comes up on
its own (``/etc/network/interfaces``: ``auto lo``).  Stern's GAME brings the network up, through ifup, and the Wi-Fi
network's name and password are the game's own settings: it hands them to wpa_supplicant (``ADD_NETWORK`` /
``SET_NETWORK``) each time and never writes them to a file.  So a test card, or a multi-boot card sitting in its
boot menu, was off the network: nothing could be sent to it until a game had started.

This puts ``/etc/init.d/padnet`` on the card's system partition.  The menu's hook (codeselect/select.sh) starts it
just before the menu shows and stops it the moment a game is chosen, so the game sets up its own network exactly as
Stern ships it.  It brings up the wired port (DHCP, as the card's own ``iface eth0 inet dhcp``) and, when the owner
gave PAD a Wi-Fi network (Simon chose "Type it into PAD"), joins that with ``/etc/padnet/wpa.conf`` (root only,
0600).  The password itself never goes on the card or into PAD's settings: PAD keeps the network's WPA key, derived
from the name and password the standard way (PBKDF2-SHA1, 4096 rounds), which is what wpa_supplicant would make of
them anyway.

Written the checked way the other extras are (core/ssh_card.py): a scratch copy changed with debugfs, read back,
then written in."""

import binascii
import hashlib
import json
import os
import stat
import struct
import threading
from pathlib import Path

from . import ssh_card
from .card_extras import ExtrasError
from .executor import create_executor
from ..plugins.stern.ext4 import Ext4Reader, Ext4Error

INIT = '/etc/init.d/padnet'
DIR = '/etc/padnet'
WPA = DIR + '/wpa.conf'
#: what the menu's hook (select.sh) runs, by this name
SCRIPT = b'''#!/bin/sh
# PAD (Simon, 2026-11-26): the boot menu and the test card on the network with no game running.
# select.sh starts this before the menu and stops it when a game is chosen; the game then brings up
# its own network as Stern ships it.  Wired port by DHCP; Wi-Fi only with /etc/padnet/wpa.conf.
RUN=/var/run/padnet
CONF=/etc/padnet/wpa.conf
start() {
    mkdir -p $RUN
    if [ -d /sys/class/net/eth0 ]; then
        ip link set eth0 up 2>/dev/null
        udhcpc -b -R -p $RUN/eth0.pid -i eth0 -H stern-spike2 >/dev/null 2>&1
    fi
    [ -s $CONF ] || return 0
    # the adapter's driver was loaded by /etc/init.d/game a moment ago
    i=0
    while [ ! -d /sys/class/net/wlan0 ] && [ $i -lt 20 ]; do sleep 1; i=$((i + 1)); done
    [ -d /sys/class/net/wlan0 ] || return 0
    ip link set wlan0 up 2>/dev/null
    wpa_supplicant -B -P $RUN/wpa.pid -i wlan0 -c $CONF -D nl80211,wext >/dev/null 2>&1
    udhcpc -b -R -p $RUN/wlan0.pid -i wlan0 -H stern-spike2 >/dev/null 2>&1
}
stop() {
    for f in $RUN/eth0.pid $RUN/wlan0.pid $RUN/wpa.pid; do
        [ -s $f ] && kill $(cat $f) 2>/dev/null
        rm -f $f
    done
    sleep 1
    for i in eth0 wlan0; do
        [ -d /sys/class/net/$i ] || continue
        ip addr flush dev $i 2>/dev/null
        ip link set $i down 2>/dev/null
    done
    rm -rf /var/run/padnet_wpa
}
case "$1" in
    start) start ;;
    stop) stop ;;
    *) echo "usage: $0 start|stop" >&2; exit 1 ;;
esac
exit 0
'''
NOT_SPIKE2 = 'The menu network needs a Stern Spike 2 card.'
NO_TOOLS = "This card has no wpa_supplicant or udhcpc where the menu network expects them."


# ---- the owner's Wi-Fi, saved once for the Test card and Multi-boot tabs --------------------------------------------
_LOCK = threading.Lock()
SAVED_DEFAULTS = {"wifi_name": "", "wifi_key": "", "multiboot": False}


def store_path():
    """Beside the app's settings (PAD_MENU_WIFI_STORE for the tests)."""
    forced = os.environ.get("PAD_MENU_WIFI_STORE")
    if forced:
        return forced
    from . import config
    return os.path.join(os.path.dirname(config.SETTINGS_FILE), "menu_wifi.json")


def _clean(d):
    out = dict(SAVED_DEFAULTS)
    if isinstance(d, dict):
        name, key = d.get("wifi_name"), d.get("wifi_key")
        if isinstance(name, str) and 1 <= len(name.encode("utf-8")) <= 32 and isinstance(key, str) and (
                key == "" or (len(key) == 64 and all(c in "0123456789abcdef" for c in key))):
            out["wifi_name"], out["wifi_key"] = name, key
        if isinstance(d.get("multiboot"), bool):
            out["multiboot"] = d["multiboot"]
    return out


def saved():
    """``{"wifi_name", "wifi_key", "multiboot"}``: the Wi-Fi the menu and the test card join (the name and its WPA
    key, never the password), and whether a multi-boot card gets the menu network."""
    with _LOCK:
        try:
            with open(store_path(), encoding="utf-8") as f:
                return _clean(json.load(f))
        except (OSError, ValueError):
            return dict(SAVED_DEFAULTS)


def save(**changes):
    """Change the saved settings (keys of :data:`SAVED_DEFAULTS`); returns them."""
    now = saved()
    now.update({k: v for k, v in changes.items() if k in SAVED_DEFAULTS})
    now = _clean(now)
    with _LOCK:
        path = store_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(now, f)
        os.replace(tmp, path)
    return now


def set_wifi(name, password):
    """Save the Wi-Fi *name* with the key of *password* (``''`` *name* forgets it): ``''`` or why not."""
    name = (name or "").strip()
    if not name:
        save(wifi_name="", wifi_key="")
        return ""
    why = check_wifi(name, password or "")
    if why:
        return why
    save(wifi_name=name, wifi_key=wifi_key(name, password or ""))
    return ""


def shown():
    """What a page may show of the saved Wi-Fi: its name and whether it is open - never the key."""
    s = saved()
    return {"name": s["wifi_name"], "open": bool(s["wifi_name"]) and not s["wifi_key"], "multiboot": s["multiboot"]}


def has_remote_access(image):
    """Whether the card image *image* starts an SSH server (core/ssh_card.py): the menu network is for reaching it."""
    try:
        with open(image, 'rb') as f:
            p2 = next((p for p in ssh_card._partitions(f) if p[0] == 2 and p[1] == 0x83), None)
            if p2 is None:
                return False
            return ssh_card._node(Ext4Reader(f, p2[2], p2[3]), ssh_card.HOOK) is not None
    except (OSError, ValueError, Ext4Error, struct.error, ExtrasError):
        return False


def check_wifi(name, password):
    """``''`` when *name* and *password* make a Wi-Fi network wpa_supplicant can join, else why not, in the user's
    words.  *password* ``''`` is an open network."""
    raw = (name or '').encode('utf-8')
    if not 1 <= len(raw) <= 32:
        return 'A Wi-Fi network name is 1 to 32 characters.'
    if password and not (8 <= len(password) <= 63 and all(32 <= ord(c) < 127 for c in password)):
        return 'A Wi-Fi password is 8 to 63 ordinary characters (or none, for an open network).'
    return ''


def wifi_key(name, password):
    """The network's WPA key (64 hex digits) from its *name* and *password*, as wpa_supplicant derives it; ``''`` for
    an open network.  This, not the password, is what PAD keeps and the card gets."""
    if not password:
        return ''
    return hashlib.pbkdf2_hmac('sha1', password.encode('ascii'), name.encode('utf-8'), 4096, 32).hex()


def wpa_conf(name, key):
    """``/etc/padnet/wpa.conf`` for the network *name* with WPA *key* (``''``: an open one)."""
    lines = ['ctrl_interface=/var/run/padnet_wpa', 'network={',
             '    ssid=%s' % binascii.hexlify(name.encode('utf-8')).decode('ascii'), '    scan_ssid=1']
    if key:
        if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            raise ExtrasError('The saved Wi-Fi key is not one PAD made; enter the Wi-Fi password again.')
        lines.append('    psk=%s' % key)
    else:
        lines.append('    key_mgmt=NONE')
    lines.append('}')
    return ('\n'.join(lines) + '\n').encode('ascii')


def _read(reader, path, limit):
    node = ssh_card._node(reader, path)
    if node is None or stat.S_IFMT(node['mode']) != stat.S_IFREG or node['size'] > limit:
        return None
    return bytes(reader.read_file_bytes(node))


def _wanted(config):
    """``{path: (bytes, mode)}`` the card should end with, from *config* ``{'wifi_name', 'wifi_key'}``."""
    want = {INIT: (SCRIPT, 0o755)}
    name = (config or {}).get('wifi_name') or ''
    if name:
        want[WPA] = (wpa_conf(name, (config or {}).get('wifi_key') or ''), 0o600)
    return want


def inspect_root(reader):
    """Raises ExtrasError when the system filesystem behind *reader* cannot take the menu network."""
    game = _read(reader, '/etc/init.d/game', 1 << 20)
    if game is None or b'/usr/local/spike' not in game:
        raise ExtrasError(NOT_SPIKE2)
    for tool in ('/usr/sbin/wpa_supplicant', '/sbin/udhcpc'):
        if ssh_card._node(reader, tool) is None:
            raise ExtrasError(NO_TOOLS)


def _verify(reader, want):
    for path, (data, mode) in want.items():
        node = ssh_card._node(reader, path)
        if (node is None or node['mode'] != stat.S_IFREG | mode or node['uid'] or node['gid']
                or _read(reader, path, 1 << 20) != data):
            raise ExtrasError('The menu network files on the card did not read back as written.')
    if WPA not in want and ssh_card._node(reader, WPA) is not None:
        raise ExtrasError('An earlier Wi-Fi network could not be taken off the card.')


def prepare_rootfs(part, work, config, cancel=None):
    """Bring a scratch copy *part* of the system filesystem to *config*, checked before and after; never a card."""
    part, work = Path(part), Path(work)
    size = part.stat().st_size
    want = _wanted(config)
    ex = create_executor()
    exec_part = ex.to_exec_path(str(part))
    ssh_card._command(ex, 'e2fsck', '-fn', exec_part)
    commands = []
    with part.open('rb') as f:
        r = Ext4Reader(f, 0, size)
        inspect_root(r)
        if ssh_card._node(r, DIR) is None and WPA in want:
            commands.append('mkdir %s' % DIR)
        for i, (path, (data, mode)) in enumerate(want.items()):
            node = ssh_card._node(r, path)
            if node is not None:
                if stat.S_IFMT(node['mode']) != stat.S_IFREG:
                    raise ExtrasError('The card has something unexpected where %s goes.' % path)
                commands.append('rm %s' % path)
            staged = work / ('padnet%d' % i)
            staged.write_bytes(data)
            src = ex.to_exec_path(str(staged))
            if any(c in src for c in ('"', '\n', '\r', '\\')):
                raise ExtrasError('The staging path contains unsupported filesystem-tool characters.')
            commands.append('write "%s" %s' % (src, path))
            for field, val in (('mode', '0100%o' % mode), ('uid', '0'), ('gid', '0')):
                commands.append('set_inode_field %s %s %s' % (path, field, val))
        if WPA not in want and ssh_card._node(r, WPA) is not None:
            commands.append('rm %s' % WPA)
        if ssh_card._node(r, DIR) is not None or WPA in want:
            for field, val in (('mode', '040700'), ('uid', '0'), ('gid', '0')):
                commands.append('set_inode_field %s %s %s' % (DIR, field, val))
    if cancel is not None and cancel():
        raise ExtrasError('Menu network preparation canceled.')
    script = work / 'padnet.commands'
    script.write_text('\n'.join(commands) + '\n')
    ssh_card._command(ex, 'debugfs', '-w', '-f', ex.to_exec_path(str(script)), exec_part)
    ssh_card._command(ex, 'e2fsck', '-fn', exec_part)
    with part.open('rb') as f:
        _verify(Ext4Reader(f, 0, size), want)


def note(config):
    name = (config or {}).get('wifi_name') or ''
    return ('Menu network: the menu and test card start the wired port%s.'
            % (' and join the Wi-Fi network "%s"' % name if name else ''))


def apply_to_build(original, output, config, log=None, cancel=None):
    """Put the menu network on the built image *output* (a copy, never *original*), or raise before success.
    *config* ``{'wifi_name': str, 'wifi_key': str}`` (both may be empty: the wired port only).  Returns the build
    summary's line."""
    ssh_card._regular(original)
    ssh_card._regular(output, allow_pending=True, writable=True)
    with open(output, 'rb') as f:
        try:
            p2 = next((p for p in ssh_card._partitions(f) if p[0] == 2 and p[1] == 0x83), None)
            if p2 is None:
                raise ExtrasError(NOT_SPIKE2)
            inspect_root(Ext4Reader(f, p2[2], p2[3]))
        except (OSError, ValueError, Ext4Error, struct.error) as e:
            raise ExtrasError(str(e)) from None
    _, _, start, size = p2
    ssh_card.rewrite_partition(output, start, size,
                               lambda part, work: prepare_rootfs(part, work, config, cancel=cancel),
                               cancel, what='Menu network')
    text = note(config)
    if log:
        log(text, 'info')
    return text
