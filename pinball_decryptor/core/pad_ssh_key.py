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


def _entry(rec):
    hk = rec.get("host_key")
    return {"address": str(rec.get("address") or "").strip(),
            "host_key": tuple(hk) if isinstance(hk, (list, tuple)) and len(hk) == 2 else None,
            "game": str(rec.get("game") or ""),
            # PAD-1627: the owner's own name for it (My machines), kept when the router moves it
            "name": str(rec.get("name") or "").strip()}


def _load_machines():
    """``(current address, [machine, ...])`` as kept in machines.json.  PAD-1427: every machine this computer
    has found (David: "I can have MANY machines on my network"), each ``{'address', 'host_key', 'game'}``, and
    which one Send to machine uses.  The PAD-1397 file held one ``{"address"}``: it reads as a list of one."""
    try:
        with open(_machines_file(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if isinstance(data.get("machines"), list):
        machines = [_entry(m) for m in data["machines"] if isinstance(m, dict)]
        current = str(data.get("current") or "")
    else:
        old = _entry(data)
        machines = [old] if old["address"] else []
        current = old["address"]
    return current, [m for m in machines if m["address"]]


def _save_machines(current, machines):
    os.makedirs(KEY_DIR, exist_ok=True)
    write_json_atomic(_machines_file(), {"current": current, "machines": [
        dict(m, host_key=list(m["host_key"]) if m["host_key"] else None) for m in machines]})


def machines():
    """Every machine this computer knows, in the order they were found: ``[{'address', 'host_key', 'game'}]``."""
    return _load_machines()[1]


def machine():
    """The machine Send to machine uses: ``{'address', 'host_key', 'game'}`` (all empty when there is none)."""
    current, ms = _load_machines()
    return next((m for m in ms if m["address"] == current), _entry({"address": current}))


def last_address():
    """The address of the machine Send to machine uses on this computer, or ``""``."""
    return _load_machines()[0]


def machine_for_game(game):
    """The address of the one known machine that runs *game* (``deadpool_le``), or ``""`` (none, or several)."""
    hits = [m["address"] for m in machines() if game and m["game"] == game]
    return hits[0] if len(hits) == 1 else ""


def remember_address(address):
    """An address typed in by hand: it becomes the machine used, a known machine's identity kept with it."""
    address = (address or "").strip()
    with _lock:
        _current, ms = _load_machines()
        if address and not any(m["address"] == address for m in ms):
            ms.append(_entry({"address": address}))
        _save_machines(address, ms)


def remember_machine(address, host_key=None, game="", make_current=True, replaces=""):
    """A machine found (a scan, or a connection that let this computer in), with its identity and game.  The same
    identity at a new address is the same machine, moved.  PAD-1627: *replaces* is the address of the remembered
    machine this one IS although its identity is new (a card written again has a new one): its place, and the
    owner's name for it, are kept."""
    address = (address or "").strip()
    with _lock:
        current, ms = _load_machines()
        old = (next((m for m in ms if host_key and m["host_key"] == tuple(host_key)), None)
               or next((m for m in ms if m["address"] == address), None)
               or next((m for m in ms if replaces and m["address"] == replaces), None))
        rec = _entry({"address": address, "host_key": host_key or (old or {}).get("host_key"),
                      "game": game or (old or {}).get("game") or "",
                      "name": (old or {}).get("name") or ""})
        if old is not None:
            if current == old["address"]:
                current = address
            ms[ms.index(old)] = rec
            ms = [m for m in ms if m is rec or m["address"] != address]
        else:
            ms = [m for m in ms if m["address"] != address] + [rec]
        _save_machines(address if make_current or not current else current, ms)


def name_machine(address, name):
    """PAD-1627: the owner's name for the known machine at *address* ("" takes it off). True when stored."""
    with _lock:
        current, ms = _load_machines()
        hit = next((m for m in ms if m["address"] == address), None)
        if hit is None:
            return False
        hit["name"] = (name or "").strip()
        _save_machines(current, ms)
        return True


def select_machine(address):
    """Make the known machine at *address* the one Send to machine uses."""
    with _lock:
        _current, ms = _load_machines()
        if not any(m["address"] == address for m in ms):
            return False
        _save_machines(address, ms)
        return True


def forget_machine(address):
    """Forget the machine at *address*: its identity and its place in the list (the next one is used)."""
    with _lock:
        current, ms = _load_machines()
        ms = [m for m in ms if m["address"] != address]
        if current == address:
            current = ms[0]["address"] if ms else ""
        _save_machines(current, ms)
