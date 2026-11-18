"""This computer's own remote-access key, and the machines it has met (PAD-1397).

Send to machine logs in to a machine over remote access (SSH, PR #38) without the user handing PAD a private key:
PAD makes an Ed25519 key of its own the first time it is wanted, keeps it beside settings.json, and every card built
with remote access on trusts it (card_extras.configuration adds the public half to the card's authorized keys).
The private key never leaves this folder and never goes into a project, a mod or a build record.

The machines' own host keys are remembered here too, on first contact (``known_hosts.json``): a machine that later
answers with a different key is refused, as ssh does, until the user forgets it (a reflashed machine whose /data
was wiped makes a new one)."""

import json
import os
import threading

from . import config
from .atomic_file import write_json_atomic

#: the folder, beside settings.json; tests point it at a temp folder (conftest)
KEY_DIR = os.path.join(os.path.dirname(config.SETTINGS_FILE), "remote_access")
KEY_NAME = "pad_ed25519"
#: the comment on the public key line, which is what the user sees in a card's authorized keys
COMMENT = "pinball-asset-decryptor"

_lock = threading.Lock()


def _paths():
    return os.path.join(KEY_DIR, KEY_NAME), os.path.join(KEY_DIR, KEY_NAME + ".pub")


def _make():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    return private, public.decode("ascii") + " " + COMMENT + "\n"


def ensure():
    """``(private key path, public key line)``, the key made on first call.  Raises OSError when it can't be kept."""
    priv, pub = _paths()
    with _lock:
        if not (os.path.isfile(priv) and os.path.isfile(pub)):
            os.makedirs(KEY_DIR, exist_ok=True)
            private, public = _make()
            tmp = priv + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(private)
            os.replace(tmp, priv)
            with open(pub + ".tmp", "w", encoding="ascii", newline="\n") as fh:
                fh.write(public)
            os.replace(pub + ".tmp", pub)
        with open(pub, encoding="ascii") as fh:
            line = fh.read().strip()
    return priv, line + "\n"


def public_line():
    """This computer's public key line, or ``""`` when it can't be made (no crypto library, a read-only folder):
    a build then simply carries the user's own keys, and Send says why it can't log in."""
    try:
        return ensure()[1]
    except Exception:                                   # noqa: BLE001 - never stops a build
        return ""


def load_private():
    """The paramiko key object for logging in."""
    import paramiko
    priv, _pub = ensure()
    return paramiko.Ed25519Key.from_private_key_file(priv)


# ---------------------------------------------------------------- host keys
def _hosts_file():
    return os.path.join(KEY_DIR, "known_hosts.json")


def _hosts():
    try:
        with open(_hosts_file(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def host_key(host, port=22):
    """``(type, base64)`` this computer has on record for *host*, or None."""
    rec = _hosts().get("%s:%d" % (host, int(port)))
    return tuple(rec) if isinstance(rec, list) and len(rec) == 2 else None


def remember_host(host, port, kind, b64):
    with _lock:
        data = _hosts()
        data["%s:%d" % (host, int(port))] = [kind, b64]
        os.makedirs(KEY_DIR, exist_ok=True)
        write_json_atomic(_hosts_file(), data)


def forget_host(host, port=22):
    with _lock:
        data = _hosts()
        if data.pop("%s:%d" % (host, int(port)), None) is not None:
            write_json_atomic(_hosts_file(), data)


# ---------------------------------------------------------------- the machine's address
def _machines_file():
    return os.path.join(KEY_DIR, "machines.json")


def last_address():
    """The machine address Send to machine last used on this computer, or ``""``."""
    try:
        with open(_machines_file(), encoding="utf-8") as fh:
            data = json.load(fh)
        return str(data.get("address") or "") if isinstance(data, dict) else ""
    except (OSError, ValueError):
        return ""


def remember_address(address):
    with _lock:
        os.makedirs(KEY_DIR, exist_ok=True)
        write_json_atomic(_machines_file(), {"address": (address or "").strip()})
