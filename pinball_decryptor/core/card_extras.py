"""Local project SSH intent; never included in portable mod/preset records."""

import base64
import binascii
import os
import struct
import hashlib
import json

from . import staged_changes


class ExtrasError(ValueError):
    """An invalid or unsafe card Extras request."""


MAX_TEXT = 256 * 1024
CURVES = {'nistp256': 65, 'nistp384': 97, 'nistp521': 133}


def _text(text):
    if not isinstance(text, str) or len(text) > MAX_TEXT or '\x00' in text:
        raise ExtrasError('SSH public keys must be text, at most 256 KiB.')
    if 'PRIVATE KEY' in text.upper():
        raise ExtrasError('Paste public keys only; private keys are not accepted.')
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _fields(blob):
    fields, at = [], 0
    while at < len(blob):
        if at + 4 > len(blob):
            raise ValueError()
        n = struct.unpack_from('>I', blob, at)[0]
        at += 4
        if n > 8192 or at + n > len(blob):
            raise ValueError()
        fields.append(blob[at:at + n])
        at += n
    return fields


def validate_keys(text):
    """Canonical plain authorized_keys, with verified SSH wire types and lengths.

    Options/certificates/security-key types are deliberately not accepted: only
    the key types exercised against the shipped server belong in this form.
    """
    lines, seen = [], set()
    for line_no, line in enumerate(_text(text).splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        try:
            parts = line.split(None, 2)
            kind, encoded = parts[:2]
            blob = base64.b64decode(encoded, validate=True)
            f = _fields(blob)
            if not f or f[0].decode('ascii') != kind:
                raise ValueError()
            if kind == 'ssh-ed25519':
                valid = len(f) == 2 and len(f[1]) == 32
            elif kind == 'ssh-rsa':
                valid = (len(f) == 3 and 3 <= int.from_bytes(f[1], 'big') <= 2**32
                         and int.from_bytes(f[1], 'big') % 2 == 1
                         and 1024 <= int.from_bytes(f[2], 'big').bit_length() <= 16384
                         and int.from_bytes(f[2], 'big') % 2 == 1)
                if valid:
                    for value in f[1:]:
                        if not value or value[0] & 0x80 or (len(value) > 1 and value[0] == 0 and value[1] < 0x80):
                            valid = False
            elif kind.startswith('ecdsa-sha2-'):
                curve = kind.removeprefix('ecdsa-sha2-')
                valid = (len(f) == 3 and curve in CURVES and f[1] == curve.encode()
                         and len(f[2]) == CURVES[curve] and f[2][:1] == b'\x04')
            else:
                valid = False
            if not valid:
                raise ValueError()
            # Length-correct ECDSA/Ed25519 blobs can still encode unusable
            # points. PyCryptodome is already a required runtime dependency.
            from Crypto.PublicKey import ECC, RSA
            if kind == 'ssh-rsa':
                RSA.import_key((kind + ' ' + encoded).encode())
            else:
                ECC.import_key(kind + ' ' + encoded)
        except (ValueError, IndexError, UnicodeError, binascii.Error):
            raise ExtrasError(f'Invalid or unsupported SSH public key on line {line_no}.') from None
        identity = (kind, encoded)
        if identity not in seen:
            lines.append(line)
            seen.add(identity)
    if not lines:
        raise ExtrasError('Enabling SSH requires at least one valid public key.')
    return '\n'.join(lines) + '\n'


def load(project):
    """Return saved intent, or None when this project has never configured SSH."""
    if not project or not os.path.isdir(project):
        return None
    extras = staged_changes.load(project).get('extras')
    if extras is None:
        return None
    if not isinstance(extras, dict):
        raise ExtrasError('The project Extras configuration is invalid.')
    rec = extras.get('ssh')
    if rec is None:
        return None
    if (not isinstance(rec, dict) or type(rec.get('enabled')) is not bool
            or not isinstance(rec.get('public_keys'), str)):
        raise ExtrasError('The project SSH configuration is invalid.')
    return {'enabled': rec['enabled'], 'public_keys': _text(rec['public_keys'])}


def with_pad_key(text):
    """*text* with this computer's own public key added (PAD-1397): every card built with remote access on lets
    PAD in, so Send to machine works without the user handing PAD a private key.  Unchanged when the key can't
    be made."""
    from . import pad_ssh_key
    line = pad_ssh_key.public_line()
    if not line:
        return text
    return (text.rstrip('\n') + '\n' + line) if text.strip() else line


def configuration(project):
    """The effective record a build uses: the saved keys plus this computer's own (:func:`with_pad_key`).

    PAD-1531: a project built for sharing (:func:`load_share`) builds with remote access off whatever else is
    saved, and ``share`` asks the build to empty the machine's own partitions too (core/share_build.py)."""
    if load_share(project):
        return {'enabled': False, 'public_keys': '', 'share': True}
    rec = load(project)
    if rec is not None and rec['enabled']:
        rec['public_keys'] = validate_keys(with_pad_key(rec['public_keys']))
    return rec


def key_id(line):
    """``(kind, base64)`` of an authorized_keys line, the part that is the key (its comment is not), or None."""
    parts = (line or '').split()
    if len(parts) < 2 or line.lstrip().startswith('#'):
        return None
    return parts[0], parts[1]


def key_name(line):
    """A short name for a key line a person can recognise: its comment (often user@computer), else the start of
    its SHA256 fingerprint."""
    from . import pad_ssh_key
    parts = (line or '').split(None, 2)
    try:
        digest = hashlib.sha256(base64.b64decode(parts[1])).digest()
        fp = 'key SHA256:' + base64.b64encode(digest).decode().rstrip('=')[:12]
    except (IndexError, ValueError, binascii.Error):
        fp = 'a key'
    comment = parts[2].strip() if len(parts) == 3 else ''
    if comment == pad_ssh_key.COMMENT:
        # every PAD computer's key carries the same comment: the fingerprint tells them apart
        return 'PAD on another computer (%s)' % fp
    return comment[:60] or fp


def others(text, own=''):
    """PAD-1531: the key lines in *text* (a card's authorized_keys) that are neither this computer's own key nor
    one of the lines in *own* (the project's saved keys of the user's own SSH programs): the computers a card lets
    in that are not this one's owner's."""
    from . import pad_ssh_key
    mine = {key_id(line) for line in ((own or '') + '\n' + pad_ssh_key.public_line()).splitlines()}
    out, seen = [], set()
    for line in (text or '').splitlines():
        ident = key_id(line.strip())
        if ident is None or ident in mine or ident in seen:
            continue
        seen.add(ident)
        out.append(line.strip())
    return out


def load_share(project):
    """PAD-1531: True when cards and images built from this project are for sharing (``extras.share``): no remote
    access, none of the machine's own data.  False when never set."""
    if not project or not os.path.isdir(project):
        return False
    extras = staged_changes.load(project).get('extras')
    if not isinstance(extras, dict):
        return False
    rec = extras.get('share')
    if rec is None:
        return False
    if not isinstance(rec, dict) or type(rec.get('enabled')) is not bool:
        raise ExtrasError('The project build-for-sharing setting is invalid.')
    return rec['enabled']


def save_share(project, enabled):
    if not project or not os.path.isdir(project):
        raise ExtrasError('Select a project folder before changing Build for sharing.')
    if type(enabled) is not bool:
        raise ExtrasError('Build for sharing must be a checkbox value.')
    data = staged_changes.load(project)
    extras = data.setdefault('extras', {})
    if not isinstance(extras, dict):
        raise ExtrasError('The project Extras configuration is invalid.')
    extras['share'] = {'enabled': enabled}
    _persist(project, data)
    return enabled


def digest(project):
    rec = configuration(project)
    wifi = load_wifi(project)
    buttons = load_buttons(project)
    if rec is None and wifi is None and buttons is None:
        return None
    record = None
    if rec is not None:
        record = dict(rec)
        if not record['enabled']:
            record['public_keys'] = ''
    if wifi is not None:
        # PAD-1467: a project that also sets the Wi-Fi start-up; one that never has keeps the digest it had
        record = {'ssh': record, 'wifi': wifi}
    if buttons is not None:
        # PAD-1467: and one that sets remote buttons; again, a project that never has keeps its digest
        record = {'base': record, 'buttons': buttons}
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def load_wifi(project):
    """PAD-1467: the saved Wi-Fi choices ``{'enabled': bool, 'band5': bool}``, or None when this project never
    set them (``extras.wifi`` in the project's ``.staged_changes.json``; core/wifi_card.py puts them on the card).
    ``enabled`` is the Wi-Fi start-up, ``band5`` the newer adapter driver and 5 GHz, which needs the first."""
    if not project or not os.path.isdir(project):
        return None
    extras = staged_changes.load(project).get('extras')
    if extras is None:
        return None
    if not isinstance(extras, dict):
        raise ExtrasError('The project Extras configuration is invalid.')
    rec = extras.get('wifi')
    if rec is None:
        return None
    if (not isinstance(rec, dict) or type(rec.get('enabled')) is not bool
            or type(rec.get('band5', False)) is not bool):
        raise ExtrasError('The project Wi-Fi configuration is invalid.')
    return {'enabled': rec['enabled'], 'band5': bool(rec['enabled'] and rec.get('band5', False))}


def load_buttons(project):
    """PAD-1467: the saved remote-buttons choice ``{'enabled': bool}``, or None when this project never set it
    (``extras.buttons`` in the project's ``.staged_changes.json``; core/remote_buttons.py puts it on the card)."""
    if not project or not os.path.isdir(project):
        return None
    extras = staged_changes.load(project).get('extras')
    if extras is None:
        return None
    if not isinstance(extras, dict):
        raise ExtrasError('The project Extras configuration is invalid.')
    rec = extras.get('buttons')
    if rec is None:
        return None
    if not isinstance(rec, dict) or type(rec.get('enabled')) is not bool:
        raise ExtrasError('The project remote-buttons configuration is invalid.')
    return {'enabled': rec['enabled']}


def save_buttons(project, enabled):
    if not project or not os.path.isdir(project):
        raise ExtrasError('Select a project folder before changing the remote-buttons option.')
    if type(enabled) is not bool:
        raise ExtrasError('The remote-buttons option must be a checkbox value.')
    data = staged_changes.load(project)
    extras = data.setdefault('extras', {})
    if not isinstance(extras, dict):
        raise ExtrasError('The project Extras configuration is invalid.')
    extras['buttons'] = {'enabled': enabled}
    _persist(project, data)
    return dict(extras['buttons'])


def save_wifi(project, enabled, band5=False):
    if not project or not os.path.isdir(project):
        raise ExtrasError('Select a project folder before changing the Wi-Fi option.')
    if type(enabled) is not bool or type(band5) is not bool:
        raise ExtrasError('The Wi-Fi option must be a checkbox value.')
    data = staged_changes.load(project)
    extras = data.setdefault('extras', {})
    if not isinstance(extras, dict):
        raise ExtrasError('The project Extras configuration is invalid.')
    extras['wifi'] = {'enabled': enabled, 'band5': bool(enabled and band5)}
    _persist(project, data)
    return dict(extras['wifi'])


def save(project, enabled, public_keys):
    if not project or not os.path.isdir(project):
        raise ExtrasError('Select a project folder before configuring SSH.')
    if type(enabled) is not bool:
        raise ExtrasError('SSH enablement must be a checkbox value.')
    text = _text(public_keys)
    if enabled:
        # PAD-1397: no key of the user's own is fine, this computer's is added to the card (configuration)
        text = validate_keys(text) if text.strip() else ''
    elif text.strip():
        # Retain an unfinished public-key draft when disabled, but normalize
        # complete lists so toggling produces stable build records.
        try:
            text = validate_keys(text)
        except ExtrasError:
            pass
    data = staged_changes.load(project)
    extras = data.setdefault('extras', {})
    if not isinstance(extras, dict):
        raise ExtrasError('The project Extras configuration is invalid.')
    extras['ssh'] = {'enabled': enabled, 'public_keys': text}
    _persist(project, data)
    return dict(extras['ssh'])


def stage_draft(project, enabled, public_keys):
    """Keep an incomplete form edit, with effective builds still validated.

    A malformed enabled draft must block a build, rather than silently build
    the last valid key list while the screen displays something different.
    """
    if not project or not os.path.isdir(project) or type(enabled) is not bool:
        raise ExtrasError('Select a project folder before configuring SSH.')
    text = _text(public_keys)
    data = staged_changes.load(project)
    extras = data.setdefault('extras', {})
    if not isinstance(extras, dict):
        raise ExtrasError('The project Extras configuration is invalid.')
    extras['ssh'] = {'enabled': enabled, 'public_keys': text}
    _persist(project, data)


def _persist(project, data):
    try:
        staged_changes.save(project, data, strict=True)
    except OSError:
        raise ExtrasError('Network options could not be saved to this project. Check folder permissions and free space before building.') from None
