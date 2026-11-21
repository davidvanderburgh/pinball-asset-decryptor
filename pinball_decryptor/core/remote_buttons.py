"""Remote buttons: press a Spike 2 machine's coin-door service buttons from the PC (PAD-1467).

David, with the live view of the machine's screen on the Network tab: "and remote control pressing buttons from the
computer to navigate the machine remotely would be killer too."

**How the game hears a button.**  The game's cabinet-switch thread loops on an 8-byte SPI transfer on
``/dev/spidev1.0``; the 8 bytes it reads are one bit a cabinet switch, a 0 meaning made.  The machine has no input
device and its kernel no uinput, so nothing can be "typed" at it.  PAD's emulator presses buttons by standing
between the game and that device; ``resources/remote/pad-buttons.so`` is the same idea for a real machine: a 6 KB
object with no library dependency, preloaded into the game, that lets the real transfer happen and then clears the
bits the PC asked for.

**The bits** were read off a Godzilla LE by having the watching build of the shim write down which bit moved as each
real button was pressed: Enter 8, Plus 9, Minus 10, Back 11, and the coin door 23 (1 with the door open).  They are
the CPU board's own wiring, not a playfield board's.

**The coin door is respected.**  A press is applied only while the REAL word says the door is open, which is also
when the machine has cut its coil power: a press from the PC does nothing a hand at the open door could not.
With the door closed the buttons do nothing, as the real ones do.

**On the card** (the project's ``extras.buttons``, set on the Network tab, applied by a build like remote access):
``/usr/local/bin/pad-buttons.so``, and ``/etc/init.d/game_monitor``'s one line that starts the game given the block
that preloads it (:data:`ALL_HOOK_LINES`, beside PAD's own mode runtime and a multi-boot card's menu when the card
has them; ``tools/spike2_emu/modehook.py`` knows the block, so a mode install keeps it).  Off puts the script's
earlier form back and takes the file off.

**A press** is one line in ``/run/pad-buttons`` (a RAM file), written over remote access: the bits, when to let go
(uptime, never more than 3 s ahead), and the door condition.  The shim says it is alive, and what the real word
is, in ``/run/pad-buttons.state`` twice a second.
"""
import hashlib
import os
import shutil
import stat
import struct
from pathlib import Path

from . import card_extras, ssh_card
from .card_extras import ExtrasError
from .executor import create_executor
from ..plugins.stern.ext4 import Ext4Reader, Ext4Error

RESOURCES = Path(__file__).resolve().parents[1] / 'resources' / 'remote'
SHIM = RESOURCES / 'pad-buttons.so'
SHIM_SHA256 = '4a8862ffe22cc4f419f522413dd67a62e8ec90f84a6925b5e3eda464d98a1a46'
SO = '/usr/local/bin/pad-buttons.so'
MONITOR = '/etc/init.d/game_monitor'
DIRS = ('/usr', '/usr/local', '/usr/local/bin', '/etc', '/etc/init.d')
CTL = '/run/pad-buttons'
STATE = '/run/pad-buttons.state'

#: the cabinet word's bits (see the module text for how they were found)
BITS = {'enter': 8, 'plus': 9, 'minus': 10, 'back': 11}
LABELS = (('back', 'Back'), ('minus', '−'), ('plus', '+'), ('enter', 'Enter'))
DOOR_BIT, DOOR_OPEN = 23, 1
HOLD_CS = 15                                   # a press: 0.15 s, what a finger's was on the machine (15 to 19)

# ---- /etc/init.d/game_monitor: the same blocks as tools/spike2_emu/modehook.py (a test holds them equal) ----
RUN_LINE = '\t$1'
MODE_SO = '/usr/local/padmode/mode.so'
MENU_SO = '/usr/local/codeselect/padmenu.so'
HOOK_LINES = [
    '\t# padmode (item 128): preload a mode of our own into THE GAME only.',
    '\t# Command-scoped, so the restart lines below and conagent never see it.',
    '\tif [ -f ' + MODE_SO + ' ]; then',
    '\t\tLD_PRELOAD=' + MODE_SO + ' $1',
    '\telse',
    '\t\t$1',
    '\tfi',
]
MENU_HOOK_LINES = [
    '\t# padmode (item 128) + padmenu (PAD-1309): preload into THE GAME only.',
    '\t# Command-scoped, so the restart lines below and conagent never see it.',
    '\tPADPRE=',
    '\t[ -f ' + MENU_SO + ' ] && PADPRE=' + MENU_SO,
    '\t[ -f ' + MODE_SO + ' ] && PADPRE=${PADPRE:+$PADPRE:}' + MODE_SO,
    '\tif [ -n "$PADPRE" ]; then',
    '\t\tLD_PRELOAD=$PADPRE $1',
    '\telse',
    '\t\t$1',
    '\tfi',
]
#: the block with the buttons shim: every object preloaded when it is there (the menu first, then the buttons,
#: then the mode runtime: each hands every ioctl on), the stock line when none is
ALL_HOOK_LINES = [
    '\t# padmode (item 128) + padmenu (PAD-1309) + pad-buttons (PAD-1467): preload into THE GAME only.',
    '\t# Command-scoped, so the restart lines below and conagent never see it.',
    '\tPADPRE=',
    '\t[ -f ' + MENU_SO + ' ] && PADPRE=' + MENU_SO,
    '\t[ -f ' + SO + ' ] && PADPRE=${PADPRE:+$PADPRE:}' + SO,
    '\t[ -f ' + MODE_SO + ' ] && PADPRE=${PADPRE:+$PADPRE:}' + MODE_SO,
    '\tif [ -n "$PADPRE" ]; then',
    '\t\tLD_PRELOAD=$PADPRE $1',
    '\telse',
    '\t\t$1',
    '\tfi',
]
BLOCKS = (ALL_HOOK_LINES, MENU_HOOK_LINES, HOOK_LINES)

NOT_SPIKE2 = 'Remote buttons work on Stern Spike 2 cards only.'
NOT_STOCK = ("This card's game start-up script (/etc/init.d/game_monitor) is not one this app knows, so it is left "
             'as it is and remote buttons cannot be put on it.')
#: what the Network tab shows under "Exactly what it changes on the card": (what, value, in code type)
DETAILS = (
    ('File added to the card', SO + ' (system partition, owner root, permissions 755; 6 KB, no library needed)', True),
    ('File changed', MONITOR + ": the one line that starts the game also loads that file into it", True),
    ('What the file does', 'The game reads its cabinet buttons as 8 bytes from /dev/spidev1.0, one bit a switch. '
     'The file lets that read happen and then, for 0.15 s after you click a button here, shows the game the '
     "button's bit as pressed. It reads nothing else and writes only two small RAM files in /run.", False),
    ('Buttons', 'Back, Minus, Plus and Enter on the coin door. Not Start, the flippers or anything on the '
     'playfield.', False),
    ('Coin door', 'A press is applied only while the coin door is open, exactly as the real buttons work, and '
     'that is when the machine has its coil power off. With the door closed the buttons here do nothing.', False),
    ('Who can press', 'Only a computer the card lets in over remote access (its key).', False),
    ('To undo', 'Untick it and write the card (or Send to machine): the file is taken off and the script put '
     'back.', False),
)


def offered(mfr):
    """Whether *mfr*'s current platform could ever take the option (Stern Spike 2)."""
    return bool(mfr is not None and getattr(mfr, 'key', '') == 'stern' and getattr(mfr, '_era', '') == 'spike2')


def shim_bytes():
    data = SHIM.read_bytes()
    if hashlib.sha256(data).hexdigest() != SHIM_SHA256:
        raise ExtrasError('The remote-buttons file that ships with the app is not the one it was built with.')
    return data


def _lines(text):
    return (text.decode('utf-8', 'replace') if isinstance(text, bytes) else text).split('\n')


def _find(lines, block):
    n = len(block)
    return next((k for k in range(len(lines) - n + 1) if lines[k:k + n] == block), None)


def strip_blocks(text):
    """*text* with any of PAD's preload blocks put back to the stock line (modehook.strip_hook's twin)."""
    lines = _lines(text)
    for block in BLOCKS:
        k = _find(lines, block)
        if k is not None:
            lines[k:k + len(block)] = [RUN_LINE]
            break
    return '\n'.join(lines)


def monitor_text(text, on, mode=False, menu=False):
    """The game start-up script for the buttons choice *on*.  Off puts back the form the card would have without
    it: the multi-boot block when the card has a boot menu (*menu*), the mode block when it has modes (*mode*),
    else Stern's own line.  ExtrasError when the script is not one of the known forms."""
    lines = _lines(strip_blocks(text))
    hits = [k for k, l in enumerate(lines) if l == RUN_LINE]
    if len(hits) != 1:
        raise ExtrasError(NOT_STOCK)
    block = ALL_HOOK_LINES if on else MENU_HOOK_LINES if menu else HOOK_LINES if mode else [RUN_LINE]
    lines[hits[0]:hits[0] + 1] = block
    return '\n'.join(lines)


def _read(reader, path, limit=1 << 20):
    try:
        return ssh_card._read(reader, path, limit)
    except ExtrasError:
        raise ExtrasError('A remote-buttons system file on the card has an unsafe type or size.') from None


def inspect_root(reader):
    """``{'enabled'}`` for a Spike 2 system partition, or ExtrasError when its start-up script is not known."""
    script = _read(reader, MONITOR, 64 << 10)
    if script is None:
        raise ExtrasError(NOT_STOCK)
    monitor_text(script, True)                              # refuses a script that is not a known form
    there = ssh_card._node(reader, SO) is not None
    so = _read(reader, SO) if there else None
    hooked = _find(_lines(script), ALL_HOOK_LINES) is not None
    return {'enabled': bool(hooked and so is not None and hashlib.sha256(so).hexdigest() == SHIM_SHA256),
            'hooked': hooked, 'file': there}


def inspect_image(path, *, allow_pending=False):
    """Never raises: ``{'supported', 'reason', 'enabled'}`` (and ``'partition'``) for the card image at *path*."""
    try:
        ssh_card._regular(path, allow_pending=allow_pending)
        with open(path, 'rb') as f:
            parts = ssh_card._partitions(f)
            p2 = next((p for p in parts if p[0] == 2 and p[1] == 0x83), None)
            if p2 is None:
                raise ExtrasError(NOT_SPIKE2)
            f.seek(p2[2])
            if f.read(6) == b'LUKS\xba\xbe':
                raise ExtrasError(NOT_SPIKE2)
            info = inspect_root(Ext4Reader(f, p2[2], p2[3]))
        info.update(supported=True, reason='', partition=p2)
        return info
    except (OSError, ValueError, Ext4Error, struct.error) as e:
        return {'supported': False, 'reason': str(e).replace('Remote access (SSH) needs', 'This option needs'),
                'enabled': False}


def describe(info):
    if not info.get('supported'):
        return ''
    return 'pad-buttons.so loaded with the game' if info.get('enabled') else 'no remote buttons (as shipped)'


def validate_request(original, project):
    """The project's saved choice (``{'enabled'}``) when a build must apply it, None when it never set one."""
    config = card_extras.load_buttons(project)
    if config is None:
        return None
    info = inspect_image(original)
    if not info['supported']:
        if not config['enabled']:
            return None
        raise ExtrasError(info['reason'])
    return config


def guard_flash(project, image):
    config = validate_request(image, project)
    if config is not None and inspect_image(image)['enabled'] != config['enabled']:
        raise ExtrasError('Build the complete image first to apply the pending remote-buttons change, then flash '
                          'that build.')


def _stop(cancel):
    if cancel is not None and cancel():
        raise ExtrasError('The remote-buttons preparation was canceled.')


def _command(ex, program, *args):
    try:
        return ssh_card._command(ex, program, *args)
    except ExtrasError:
        raise ExtrasError('Remote-buttons preparation failed running %s; no completed build was produced.'
                          % program) from None


def prepare_rootfs(part, work, on, cancel=None):
    """Bring the scratch plaintext ext filesystem *part* to the buttons choice *on*, checked before and after."""
    part, work = Path(part), Path(work)
    size = part.stat().st_size
    ex = create_executor()
    _stop(cancel)
    exec_part = ex.to_exec_path(str(part))
    _command(ex, 'e2fsck', '-fn', exec_part)
    commands, want_script = [], None

    def stage(name, data):
        staged = work / name
        staged.write_bytes(data)
        src = ex.to_exec_path(str(staged))
        if any(c in src for c in ('"', '\n', '\r', '\\')):
            raise ExtrasError('The staging path contains unsupported filesystem-tool characters.')
        return src

    def put(reader, dest, src, mode):
        node = ssh_card._node(reader, dest)
        if node is not None:
            if stat.S_IFMT(node['mode']) != stat.S_IFREG or node['links'] != 1:
                raise ExtrasError('A remote-buttons destination on the card is a link or hard-linked file.')
            commands.append('rm %s' % dest)
        commands.append('write "%s" %s' % (src, dest))
        for field, val in (('mode', '0100%o' % mode), ('uid', '0'), ('gid', '0')):
            commands.append('set_inode_field %s %s %s' % (dest, field, val))

    with part.open('rb') as f:
        r = Ext4Reader(f, 0, size)
        state = inspect_root(r)
        script = _read(r, MONITOR, 64 << 10)
        want_script = monitor_text(script, on, mode=ssh_card._node(r, MODE_SO) is not None,
                                   menu=ssh_card._node(r, MENU_SO) is not None).encode('utf-8')
        if on:
            for path in DIRS:
                node = ssh_card._node(r, path)
                if node is None:
                    commands.append('mkdir %s' % path)
                elif stat.S_IFMT(node['mode']) != stat.S_IFDIR:
                    raise ExtrasError('A remote-buttons destination folder on the card is a link or special file.')
            if not state['enabled']:
                put(r, SO, stage('pad-buttons.so', shim_bytes()), 0o755)
        elif state['file']:
            commands.append('rm %s' % SO)
        if want_script != script:
            put(r, MONITOR, stage('game_monitor', want_script), 0o755)
    script_file = work / 'debugfs.commands'
    script_file.write_text('\n'.join(commands) + '\n')
    if commands:
        _command(ex, 'debugfs', '-w', '-f', ex.to_exec_path(str(script_file)), exec_part)
    _command(ex, 'e2fsck', '-fn', exec_part)
    with part.open('rb') as f:
        r = Ext4Reader(f, 0, size)
        after = inspect_root(r)
        node = ssh_card._node(r, MONITOR)
        if (after['enabled'] != on or _read(r, MONITOR, 64 << 10) != want_script or (not on and after['file'])
                or stat.S_IMODE(node['mode']) != 0o755):
            raise ExtrasError('The remote-buttons files did not read back from the card as written.')


def note(on):
    return ('Remote buttons: Back, Minus, Plus and Enter can be pressed from this computer while the coin door is '
            'open.' if on else 'Remote buttons: off, as Stern ships it.')


def apply_to_build(original, output, config, log=None, cancel=None):
    """Put the project's buttons choice *config* on the built image *output* (never *original*), or raise before
    success.  Returns the line for the build's summary ('' when nothing is asked or nothing is on the card)."""
    if config is None:
        return ''
    if type(config.get('enabled')) is not bool:
        raise ExtrasError('Invalid remote-buttons option.')
    on = config['enabled']
    ssh_card._regular(original)
    ssh_card._regular(output, allow_pending=True, writable=True)
    if os.path.samefile(original, output):
        raise ExtrasError('Remote-buttons preparation must not write the original image.')
    dest = inspect_image(output, allow_pending=True)
    if not dest['supported']:
        if not on:
            return ''
        raise ExtrasError(dest['reason'])
    if dest['enabled'] == on and (on or not (dest['hooked'] or dest['file'])):
        if log and on:
            log(note(on), 'info')
        return note(on) if on else ''
    _stop(cancel)
    _, _, start, size = dest['partition']
    if shutil.disk_usage(Path(output).parent).free < size + (48 << 20):
        raise ExtrasError('Not enough free space to prepare remote buttons on the system partition.')
    ssh_card.rewrite_partition(output, start, size, lambda part, work: prepare_rootfs(part, work, on, cancel=cancel),
                               cancel, what='Remote buttons', stop=_stop)
    if inspect_image(output, allow_pending=True).get('enabled') != on:
        raise ExtrasError('The remote-buttons choice on the built image did not read back as written.')
    if log:
        log(note(on), 'info')
    return note(on)


# ------------------------------------------------------------------ on the machine, over remote access
#: what the app asks before it offers a press: is the shim in the running game, and is the door open
STATUS = ('read u _ < /proc/uptime; echo "up ${u%%.*}${u#*.}"; cat %s 2>/dev/null || echo none' % STATE)


def parse_status(text):
    """``dict(ready, door_open, reason)`` from :data:`STATUS`'s answer."""
    up, state = None, None
    for line in (text or '').splitlines():
        a = line.split()
        if len(a) == 2 and a[0] == 'up' and a[1].isdigit():
            up = int(a[1])
        elif len(a) == 2 and a[0].isdigit() and len(a[1]) == 16:
            state = a
    if state is None or up is None or up - int(state[0]) > 300:
        return dict(ready=False, door_open=False,
                    reason="This machine's card has no remote buttons (or its game is not running). Tick Remote "
                           'buttons below and write the card, or Send to machine.')
    try:
        word = bytes.fromhex(state[1])
    except ValueError:
        return dict(ready=False, door_open=False, reason='The machine answered in a form this app does not read.')
    door = ((word[DOOR_BIT >> 3] >> (DOOR_BIT & 7)) & 1) == DOOR_OPEN
    return dict(ready=True, door_open=door,
                reason='' if door else 'The coin door is closed: open it and the buttons work, as the real ones do.')


def press_script(names, hold_cs=HOLD_CS):
    """The shell words that ask the shim to hold *names* (one name or several) for *hold_cs* hundredths of a
    second, coin door permitting.  A hold is capped where the shim caps it."""
    if isinstance(names, str):
        names = [names]
    mask = 0
    for name in names:
        if name not in BITS:
            raise ExtrasError('There is no remote button called %r.' % (name,))
        mask |= 1 << BITS[name]
    hold = max(5, min(int(hold_cs), 250))
    return ('read u _ < /proc/uptime; u=${u%%.*}${u#*.}; echo "%x $((u + %d)) %d %d" > %s'
            % (mask, hold, DOOR_BIT, DOOR_OPEN, CTL))


def status(machine):
    answer = machine.sh(STATUS, timeout=20, check=False)
    return parse_status(answer[1] if isinstance(answer, tuple) else answer)


def press(machine, name, hold_cs=HOLD_CS):
    """Press *name* on *machine* (a connected ``remote_send`` machine); ``dict(ok, ready, door_open, reason)``."""
    st = status(machine)
    if st['ready'] and st['door_open']:
        machine.sh(press_script(name, hold_cs), timeout=20, check=False)
    return dict(st, ok=bool(st['ready'] and st['door_open']))
