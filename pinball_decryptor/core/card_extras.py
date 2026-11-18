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
    """The effective record a build uses: the saved keys plus this computer's own (:func:`with_pad_key`)."""
    rec = load(project)
    if rec is not None and rec['enabled']:
        rec['public_keys'] = validate_keys(with_pad_key(rec['public_keys']))
    return rec


def digest(project):
    rec = configuration(project)
    if rec is None:
        return None
    record = dict(rec)
    if not record['enabled']:
        record['public_keys'] = ''
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


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
        raise ExtrasError('SSH options could not be saved to this project. Check folder permissions and free space before building.') from None
