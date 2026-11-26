"""Settings and score backups a machine gets by itself (PAD-1588).

PAD-1467 made a backup of a machine's ``/data/nv`` (its adjustments, audits and high scores) over remote access
(:func:`.machine_care.backup_settings`), but only when the owner pressed the button, and a card written whole loses
them: nobody remembers to back up first.  So:

- **by itself**: a machine of My machines that this computer can log in to (remote access) and that answers on the
  network is backed up when its last backup is more than a day old *and* its settings changed since (a second pass
  over a machine with nothing changed keeps no duplicate: it only notes when it looked).  Default on; the owner can
  turn it off and picks how many backups each machine keeps (:data:`KEEP_DEFAULT`); older ones are pruned.
- **before a Send** (the Send pipeline, after it logs in) and **before a whole-card write** (the flash, to any
  reachable machine that runs the image's game), one is taken whatever its age, again none when nothing changed.

A backup only reads: it never holds or restarts the game.  The backups are the PAD-1467 zips, kept per machine
under ``machine_backups/<machine>/`` beside the app's settings, where the machine is its identity (its host key),
so one the router gives a new address keeps its backups.  My machines shows the last one's date and restores any.
"""
import hashlib
import json
import os
import re
import threading
import time
import zipfile

from . import config, machine_care
from .atomic_file import write_json_atomic

#: settings keys: backups by itself (default on) and how many each machine keeps
AUTO_KEY = "machine_backup_auto"
KEEP_KEY = "machine_backup_keep"
KEEP_DEFAULT = 5
KEEP_MAX = 50
#: a machine is backed up by itself at most this often (s)
DUE_AFTER = 24 * 3600
STATE = "state.json"

#: every file of ``/data/nv`` and its sha1, named as in the backup's tar (``nv/<game>/...``): what changed, read
#: without copying anything
SUMS = ('cd /data 2>/dev/null && [ -d nv ] && find nv -type f | sort | while read f; do '
        'echo "$(sha1sum "$f" | cut -d" " -f1) $f"; done')

_locks, _locks_lock = {}, threading.Lock()


def root():
    return os.path.join(os.path.dirname(config.SETTINGS_FILE), "machine_backups")


def auto_on(settings):
    return bool((settings or {}).get(AUTO_KEY, True))


def keep_of(settings):
    try:
        n = int((settings or {}).get(KEEP_KEY, KEEP_DEFAULT))
    except (TypeError, ValueError):
        n = KEEP_DEFAULT
    return max(1, min(KEEP_MAX, n))


def machine_id(host_key=None, address=""):
    """The folder name of a machine's backups: its identity, else its address."""
    if host_key and len(host_key) == 2 and host_key[1]:
        return "id-" + hashlib.sha1(str(host_key[1]).encode("ascii", "replace")).hexdigest()[:16]
    return "at-" + (re.sub(r"[^A-Za-z0-9_.-]+", "_", address or "") or "machine")


def folder(mid):
    return os.path.join(root(), mid)


def _lock_of(mid):
    with _locks_lock:
        return _locks.setdefault(mid, threading.Lock())


def _state(mid):
    try:
        with open(os.path.join(folder(mid), STATE), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _note(mid, **fields):
    os.makedirs(folder(mid), exist_ok=True)
    st = _state(mid)
    st.update(fields)
    write_json_atomic(os.path.join(folder(mid), STATE), st)


def _manifest(path):
    try:
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read(machine_care.MANIFEST).decode("utf-8"))
        return m if isinstance(m, dict) and m.get("kind") == "pad-machine-settings" else None
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def _stamp(m, path):
    if isinstance(m.get("stamp"), (int, float)):
        return float(m["stamp"])
    try:
        return time.mktime(time.strptime(m.get("taken") or "", "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError, OverflowError):
        return os.path.getmtime(path)


def kept(mid, sums=False):
    """The machine's backups, the one last seen on the machine first: ``[{'path', 'name', 'taken', 'stamp', 'game',
    'files', 'bytes', 'why', 'seen'}]`` (and ``'sums'``, each file's sha1, with *sums*).  *seen* is when the machine
    last had exactly these settings: a restored backup is the machine's settings again, and is pruned last."""
    d = folder(mid)
    seen = _state(mid).get("seen") or {}
    try:
        names = [n for n in os.listdir(d) if n.endswith(".zip")]
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(d, n)
        m = _manifest(p)
        if m is None:
            continue
        rec = {"path": p, "name": n, "taken": m.get("taken") or "", "stamp": _stamp(m, p),
               "game": m.get("game") or "", "files": len(m.get("files") or {}), "bytes": m.get("bytes") or 0,
               "why": m.get("why") or ""}
        try:
            rec["seen"] = max(rec["stamp"], float(seen.get(n) or 0))
        except (TypeError, ValueError):
            rec["seen"] = rec["stamp"]
        if sums:
            rec["sums"] = m.get("files") or {}
        out.append(rec)
    out.sort(key=lambda r: (r["seen"], r["stamp"], r["name"]), reverse=True)
    return out


def last_looked(mid):
    """When the machine's settings were last read for a backup (taken or found unchanged), or 0."""
    newest = kept(mid)
    try:
        checked = float(_state(mid).get("checked") or 0)
    except (TypeError, ValueError):
        checked = 0.0
    return max(checked, newest[0]["seen"] if newest else 0.0)


def due(mid, now=None):
    return (now if now is not None else time.time()) - last_looked(mid) >= DUE_AFTER


def prune(mid, keep):
    """Delete all but the newest *keep* backups; the names deleted."""
    gone = []
    for rec in kept(mid)[max(1, int(keep)):]:
        try:
            os.remove(rec["path"])
            gone.append(rec["name"])
        except OSError:
            pass
    return gone


def remote_sums(machine):
    """``{'nv/<game>/...': sha1}`` of the machine's ``/data/nv`` (read only)."""
    out = {}
    for line in machine_care._sh(machine, SUMS, 120).splitlines():
        a = line.split(None, 1)
        if len(a) == 2 and len(a[0]) == 40:
            out[a[1].strip()] = a[0]
    return out


def take(machine, mid, keep, force=False, why="auto", address="", now=None):
    """Back *machine* up into its folder unless it is not due (``force`` skips that) or a kept backup already holds
    exactly its settings (nothing changed since, or a backup was put back).  ``{'status': 'taken'|'unchanged'|'recent',
    'path', 'files', 'pruned', 'last'}``: *last* is the kept backup it matched, else the newest there was."""
    with _lock_of(mid):
        if not force and not due(mid, now):
            return {"status": "recent", "path": "", "files": 0, "pruned": [], "last": (kept(mid) or [{}])[0]}
        older = kept(mid, sums=True)
        newest = older[0] if older else None
        stamp = time.time() if now is None else now
        sums = remote_sums(machine)
        same = next((k for k in older if sums and k["sums"] == sums), None)
        if same is not None:
            _seen(mid, same["name"], stamp, address)
            return {"status": "unchanged", "path": same["path"], "files": len(sums), "pruned": [], "last": same}
        d = folder(mid)
        os.makedirs(d, exist_ok=True)
        part = os.path.join(d, ".taking.part")
        res = machine_care.backup_settings(machine, part)
        got = (_manifest(part) or {}).get("files")
        same = next((k for k in older if k["sums"] == got), None)
        if same is not None:
            os.remove(part)                         # changed back between the two reads
            _seen(mid, same["name"], stamp, address)
            return {"status": "unchanged", "path": same["path"], "files": res["files"], "pruned": [], "last": same}
        _mark(part, why, stamp)
        base = "%s-settings-%s" % (re.sub(r"[^A-Za-z0-9_.-]+", "_", res["game"] or "machine").strip("_") or "machine",
                                   time.strftime("%Y%m%d-%H%M%S", time.localtime(stamp)))
        path, n = os.path.join(d, base + ".zip"), 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(d, "%s-%d.zip" % (base, n))
        os.replace(part, path)
        _note(mid, checked=stamp, address=address, game=res["game"])
        return {"status": "taken", "path": path, "files": res["files"], "pruned": prune(mid, keep),
                "last": newest}


def _seen(mid, name, stamp, address):
    seen = {k: v for k, v in (_state(mid).get("seen") or {}).items() if os.path.exists(os.path.join(folder(mid), k))}
    seen[name] = stamp
    _note(mid, checked=stamp, address=address, seen=seen)


def _mark(path, why, stamp):
    """Say in the backup's own record what took it (``auto``, ``send``, ``write``, ``by hand``) and when."""
    with zipfile.ZipFile(path) as z:
        m = json.loads(z.read(machine_care.MANIFEST).decode("utf-8"))
        raw = z.read(machine_care.TAR_NAME)
    m["why"], m["taken"], m["stamp"] = why, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stamp)), stamp
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(machine_care.MANIFEST, json.dumps(m, indent=1, sort_keys=True))
        z.writestr(machine_care.TAR_NAME, raw)


# ------------------------------------------------------------------ which machines
def known():
    """The machines this computer can log in to: ``[{'address', 'host_key', 'game', 'id'}]``."""
    from . import pad_ssh_key
    return [dict(m, id=machine_id(m["host_key"], m["address"])) for m in pad_ssh_key.machines() if m["host_key"]]


def for_game(game):
    return [m for m in known() if game and m["game"] == game]


def _connect(address, timeout=10):
    from . import remote_send
    host, port = remote_send.parse_address(address)
    return remote_send.SshMachine(host, port, timeout=timeout)


def auto_pass(games, keep, connect=None, now=None, log=None):
    """One look at every machine of *games* (My machines' game keys) this computer can log in to: each one due and
    answering is backed up when it changed.  ``[(machine record, result or None, error text)]``."""
    connect = connect or _connect
    out = []
    for m in known():
        if m["game"] not in games or not due(m["id"], now):
            continue
        try:
            machine = connect(m["address"])
        except Exception as e:                      # noqa: BLE001 - not on the network now: looked at again later
            out.append((m, None, str(e) or e.__class__.__name__))
            continue
        try:
            res = take(machine, m["id"], keep, why="auto", address=m["address"], now=now)
            out.append((m, res, ""))
            if log and res["status"] == "taken":
                log("Backed up the settings, audits and high scores of %s at %s by itself (%d files)."
                    % (m["game"] or "the machine", m["address"], res["files"]), "info")
        except Exception as e:                      # noqa: BLE001 - said; the next pass tries again
            out.append((m, None, str(e) or e.__class__.__name__))
        finally:
            try:
                machine.close()
            except Exception:                       # noqa: BLE001
                pass
    return out


def said(res):
    """A Send's or a write's log line for a backup taken first."""
    if res["status"] == "unchanged":
        return ("The machine's settings, audits and high scores are the same as its backup of %s, so no new one is "
                "kept." % res["last"]["taken"][:16])
    return "Backed up the machine's settings, audits and high scores first (%d files)." % res["files"]


def before_send(machine, keep, log=None):
    """The backup a Send takes once it is logged in, whatever the last one's age.  Never raises: a Send is not
    stopped by a backup that could not be taken, it is said."""
    say = log or (lambda *a, **k: None)
    try:
        from . import pad_ssh_key
        hk = getattr(machine, "identity", None) or pad_ssh_key.host_key(machine.host, machine.port)
        address = machine.host if int(getattr(machine, "port", 22)) == 22 else "%s:%d" % (machine.host, machine.port)
        res = take(machine, machine_id(hk, address), keep, force=True, why="send", address=address)
        say(said(res), "info")
        return res
    except Exception as e:                          # noqa: BLE001
        say("Couldn't back up the machine's settings first (%s); the Send goes on." % e, "warning")
        return None


def before_write(game, keep, log=None, connect=None):
    """Before a whole card is written for *game*: every machine running it that answers is backed up first."""
    say = log or (lambda *a, **k: None)
    out = []
    for m in for_game(game):
        try:
            machine = (connect or _connect)(m["address"])
        except Exception:                           # noqa: BLE001 - not on the network: nothing to back up
            continue
        try:
            res = take(machine, m["id"], keep, force=True, why="write", address=m["address"])
            say("%s (the machine at %s, before this card is written)" % (said(res).rstrip("."), m["address"]),
                "info")
            out.append(res)
        except Exception as e:                      # noqa: BLE001
            say("Couldn't back up the machine at %s first: %s" % (m["address"], e), "warning")
        finally:
            try:
                machine.close()
            except Exception:                       # noqa: BLE001
                pass
    return out


# ------------------------------------------------------------------ My machines
def game_key(entry):
    """The game folder a My machines entry's card runs (``godzilla_le``), as a machine on the network names it."""
    from . import machines
    try:
        info = machines.release_info(entry)
    except Exception:                               # noqa: BLE001
        info = None
    return (info or {}).get("key") or ""


def my_games(settings):
    """The game keys of My machines (the machines backed up by themselves)."""
    from . import machines
    return {k for k in (game_key(e) for e in machines.entries(settings)) if k}


def game_of_card(path, mfr_key):
    """The game an image file is a card of, from its fingerprint (off the UI thread: it may open the file)."""
    from . import lineage
    info = lineage.card_print(path, measure=True) or {}
    return game_key({"manufacturer": mfr_key, "sidx": info.get("sidx") or ""}) if info.get("sidx") else ""
