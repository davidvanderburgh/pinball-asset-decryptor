"""What the app left in the PC's previous Linux, found once and given back
(PAD-1599).

WHY.  Before the app brought its own Linux (PAD-Runtime, core/runtime.py) it
ran everything in the machine's default WSL distro: the Spike 2 card cache
(``~/cardcache``, up to 64 GB, PAD-739), every emulator's unpacked games, runs
and Python (``/var/tmp/pad_*``) and the Jersey Jack images and staging
(``/var/tmp/jjp_*``).  Once the app moved into its own distro none of that is
reached again: the space keeper (core/space_keeper.py), Reclaim and the
give-back at close (core/disk_giveback.py) all act on the app's distro only,
and a distro's disk file never shrinks by itself.  On David's PC the old
Ubuntu's disk file is 206 GB.

WHAT.  Manage disk space shows a section of its own while there is something
of the app's in that distro: the same names the space keeper knows
(:data:`space_keeper.SCAN_LIVE`, ``wsl_disk``'s staging and rig paths) plus
each user's ``~/cardcache``.  One press removes them, trims the filesystem,
stops that distro alone (``wsl --terminate``: the app's own Linux and every
other distro keep running) and compacts its disk file through Windows'
virtual-disk API - no Administrator (:func:`wsl_disk.virtdisk_compact`).

THE DISTRO IS THE USER'S, so:

* nothing is removed without the press, and only names the app makes;
  save states (``~/padslots``), settings and high scores (a rig's ``nv*``)
  are never offered;
* nothing at all is offered while the app still works in it: when the app
  has no Linux of its own (no runtime, a stale one, ``PAD_RUNTIME=0``), when
  a PAD checkout sits in it (run from source there), when an emulator game
  runs in it, or when anything of the app's there was used in the last
  :data:`IN_USE_SECS` - a person who still runs the tools there;
* it is ONE-TIME: once a look finds nothing, or the space has been given
  back, that distro is never looked at again.  A distro still in use is
  looked at again after :data:`RECHECK_SECS`, so the window does not start
  the user's Linux every time it opens.

``PAD_OLD_DISTRO`` names the distro to treat as the previous one (support,
and the proof: a throwaway distro, never the user's own).
"""

from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
import time

from . import runtime, space_keeper, wsl_disk

log = logging.getLogger(__name__)

_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

#: Distros that are never the user's previous Linux.
SKIP = ("docker-desktop", "docker-desktop-data")
#: Anything of the app's used this recently means the distro is still in use.
IN_USE_SECS = 14 * 86400
#: How long a distro found in use is left before it is looked at again.
RECHECK_SECS = 7 * 86400
#: Smaller entries are not worth a line.
MIN_BYTES = 1 << 20
#: How long the distro gets to let go of its disk file after a terminate,
#: and how often it is asked again meanwhile.
RELEASE_WAIT_S = 60
RETERMINATE_EVERY_S = 15

_CARD_RE = re.compile(r"^/(root|home/[A-Za-z0-9_][A-Za-z0-9._-]*)/cardcache$")


# ---------------------------------------------------------------------------
# Which distro
# ---------------------------------------------------------------------------

def previous():
    """``{name, vhdx, size}`` of the Linux the app used before its own, or
    None: off Windows, while the app has no Linux of its own (it still works
    in the default one), when the default IS the app's, or no disk file."""
    if not wsl_disk.is_supported():
        return None
    want = os.environ.get("PAD_OLD_DISTRO") or wsl_disk.default_distro_name()
    if not want or want.casefold() == runtime.DISTRO.casefold() \
            or want.casefold() in SKIP:
        return None
    found = [(n, p) for n, p in (wsl_disk.registered_distros() or [])
             if n.casefold() == want.casefold() and p]
    if not found:
        return None
    if runtime.wsl_distro() != runtime.DISTRO:
        return None                 # the app's commands still go there
    name, base = found[0]
    vhdx = os.path.join(base, "ext4.vhdx")
    try:
        size = os.path.getsize(vhdx)
    except OSError:
        return None
    return {"name": name, "vhdx": vhdx, "size": size}


def _run(name, script, timeout=600):
    """Run *script* as root in distro *name*; stdout.  Base64 across, as
    ``wsl_disk._wsl_script`` does (wsl.exe's own shell eats ``$``)."""
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    proc = subprocess.run(
        ["wsl.exe", "-d", name, "-u", "root", "--", "bash", "-c",
         "echo %s | base64 -d | bash" % b64],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=_FLAGS)
    if proc.returncode != 0:
        raise wsl_disk.WslDiskError(
            ((proc.stderr or "") + (proc.stdout or "")).strip()
            or "wsl exited %d" % proc.returncode)
    return proc.stdout


# ---------------------------------------------------------------------------
# The scan: one pass as root in that distro
# ---------------------------------------------------------------------------
# Lines, tab-separated:
#   L <root> / H <path>          as the space keeper's (SCAN_LIVE)
#   X <dir>                      a PAD checkout (run from source here)
#   E <kind> <bytes> <last> <path>   an entry: card | rig | staging
#   U <last> <path>              never offered, but its use counts
# <last> is the newest modification OR read of any file in it (relatime
# updates a read file's atime at least daily; find and du read no file).
_SCAN = space_keeper.SCAN_LIVE + r"""
newest() { find "$1" -xdev -type f -printf '%T@\n%A@\n' 2>/dev/null | sort -rn | head -1 | cut -d. -f1; }
for h in /root /home/* /opt /srv; do
  [ -d "$h" ] || continue
  f=$(find "$h" -xdev -maxdepth 5 -path '*/pinball_decryptor/__main__.py' -print -quit 2>/dev/null)
  [ -n "$f" ] && printf 'X\t%s\n' "${f%/pinball_decryptor/__main__.py}"
done
rootdev=$(stat -c %d /)
for h in /root /home/*; do
  [ -d "$h" ] || continue
  c=$h/cardcache
  if [ -d "$c" ] && [ ! -L "$c" ] && ! mountpoint -q "$c" && [ "$(stat -c %d "$c")" = "$rootdev" ]; then
    s=$(du -sxb "$c" 2>/dev/null | cut -f1)
    printf 'E\tcard\t%s\t%s\t%s\n' "${s:-0}" "$(newest "$c")" "$c"
  fi
  for u in "$h/padslots" "$h/.pad-rig" "$h/s1emu"; do
    [ -e "$u" ] && printf 'U\t%s\t%s\n' "$(newest "$u")" "$u"
  done
done
for r in /var/tmp/pad_*/; do
  r=${r%/}
  [ -L "$r" ] && continue
  case ${r##*/} in pad_aaiw_*) continue ;; esac
  list=()
  for c in "$r"/cache/*/ "$r"/*/; do
    [ -d "$c" ] || continue
    c=${c%/}
    [ -L "$c" ] && continue
    [ "${c##*/}" = cache ] && continue
    list+=("$c")
  done
  [ ${#list[@]} -gt 0 ] || continue
  du -sxb "${list[@]}" 2>/dev/null | while IFS=$'\t' read -r s p; do
    printf 'E\trig\t%s\t%s\t%s\n' "$s" "$(newest "$p")" "$p"
  done
done
find /tmp /var/tmp -maxdepth 1 \( -name 'cgc_stage_*' -o -name 'bof_*' \
    -o -name 'jjp_*' -o -name 'pad_aaiw_*' \) ! -type l 2>/dev/null |
while IFS= read -r p; do
  s=$(du -sxb "$p" 2>/dev/null | cut -f1)
  printf 'E\tstaging\t%s\t%s\t%s\n' "${s:-0}" "$(newest "$p")" "$p"
done
true
"""


def parse(text):
    """The scan's lines -> ``{live, held, checkouts, entries, uses}``."""
    out = {"live": set(), "held": set(), "checkouts": [], "entries": [],
           "uses": []}
    for line in (text or "").splitlines():
        b = line.rstrip("\r").split("\t")
        try:
            if b[0] == "L" and len(b) == 2:
                out["live"].add(b[1])
            elif b[0] == "H" and len(b) == 2:
                out["held"].add(b[1].rstrip("/"))
            elif b[0] == "X" and len(b) == 2:
                out["checkouts"].append(b[1])
            elif b[0] == "E" and len(b) == 5:
                out["entries"].append({"kind": b[1], "size": int(b[2]),
                                       "last": int(b[3] or 0),
                                       "path": b[4]})
            elif b[0] == "U" and len(b) == 3:
                out["uses"].append((int(b[1] or 0), b[2]))
        except ValueError:
            continue
    return out


def _held(path, held):
    pre = path.rstrip("/") + "/"
    return any(h == path or h.startswith(pre) for h in held)


def offerable(kind, path):
    """Only ever a name the app makes, checked again before every removal."""
    if kind == "card":
        return bool(_CARD_RE.match(path))
    if kind == "rig":
        return wsl_disk._is_rig_path(path)
    if kind == "staging":
        return wsl_disk._is_safe_staging_path(path) \
            and not wsl_disk._is_rig_path(path)
    return False


def _what(kind, path):
    if kind == "card":
        return "Spike 2 emulator: card cache (%s)" % path
    if kind == "rig":
        m = wsl_disk._RIG_PATH_RE.match(path)
        root, sub, name = m.groups()
        detail, _k = wsl_disk._rig_detail(root, sub, name)
        return "%s: %s" % (wsl_disk.RIG_MAKERS.get(root, "Emulator"), detail)
    mfr, detail = wsl_disk._classify(path)
    return "%s: %s" % (mfr, detail)


def plan(scan, now):
    """``{in_use, items, total}``: *in_use* a sentence saying why nothing is
    offered (empty when the distro is the app's leftovers only); *items*
    ``[{kind, path, size, what}]``, largest first.  Pure."""
    why = ""
    if scan["checkouts"]:
        why = "PAD is run from source in it (%s)" % scan["checkouts"][0]
    elif scan["live"]:
        why = "an emulator game is running in it"
    items = []
    newest = max([u[0] for u in scan["uses"]] + [0])
    for e in scan["entries"]:
        newest = max(newest, e["last"])
        if not offerable(e["kind"], e["path"]):
            continue
        if _held(e["path"], scan["held"]):
            why = why or "something is using %s" % e["path"]
            continue
        if e["size"] < MIN_BYTES:
            continue
        items.append(dict(e, what=_what(e["kind"], e["path"])))
    if not why and newest and now - newest < IN_USE_SECS:
        why = "something of the app's in it was used %s" % (
            "today" if now - newest < 86400
            else "%d days ago" % ((now - newest) // 86400))
    if why:
        items = []
    items.sort(key=lambda e: e["size"], reverse=True)
    return {"in_use": why, "items": items,
            "total": sum(e["size"] for e in items)}


def scan(name, now=None):
    return plan(parse(_run(name, _SCAN)), time.time() if now is None else now)


# ---------------------------------------------------------------------------
# The record: one-time, per distro
# ---------------------------------------------------------------------------

def _record(name):
    recs = space_keeper.load_state().get("old_distro") or {}
    return dict(recs.get(name.casefold()) or {})


def _remember(name, **kw):
    st = space_keeper.load_state()
    recs = st.get("old_distro") or {}
    rec = dict(recs.get(name.casefold()) or {}, name=name, **kw)
    recs[name.casefold()] = rec
    st["old_distro"] = recs
    space_keeper._save_state(st)
    return rec


def check(now=None):
    """What the section shows, or None (and then it does not appear):
    ``{name, vhdx, size, items, total, compact_only}``.  Starts that distro
    for its scan, so the caller runs it off the UI thread."""
    now = time.time() if now is None else now
    prev = previous()
    if not prev:
        return None
    rec = _record(prev["name"])
    verdict = rec.get("verdict")
    if verdict in ("none", "done"):
        return None
    if verdict == "in_use" and \
            now - float(rec.get("checked") or 0) < RECHECK_SECS:
        return None
    if verdict == "compact":            # removed; the disk file still owed
        return dict(prev, items=[], total=0, compact_only=True)
    try:
        p = scan(prev["name"], now)
    except Exception as exc:                            # noqa: BLE001
        log.info("previous Linux %s: not scanned (%s)", prev["name"], exc)
        return None                     # asked again next time
    if p["in_use"]:
        log.info("previous Linux %s: in use - %s", prev["name"], p["in_use"])
        _remember(prev["name"], verdict="in_use", checked=now,
                  why=p["in_use"])
        return None
    if not p["items"]:
        _remember(prev["name"], verdict="none", checked=now)
        return None
    return dict(prev, items=p["items"], total=p["total"],
                compact_only=False)


# ---------------------------------------------------------------------------
# Removing, and giving the disk file back
# ---------------------------------------------------------------------------
# Every path is a quoted literal checked by offerable(); the card caches are
# checked again in Linux (not a link, not a mount, on the root filesystem),
# and every path is refused when an emulator of it has a game running.
_REMOVE = r"""
paths=()
for p in %s; do
  case $p in
    */cardcache)
      if [ -L "$p" ] || mountpoint -q "$p" || [ "$(stat -c %%d "$p" 2>/dev/null)" != "$(stat -c %%d /)" ]; then
        printf 'K\t%%s\n' "$p"; continue
      fi ;;
  esac
  [ -e "$p" ] && paths+=("$p")
done
[ ${#paths[@]} -gt 0 ] || exit 0
printf 'F\t%%s\n' "$(du -scxb "${paths[@]}" 2>/dev/null | tail -1 | cut -f1)"
""" + wsl_disk._UNMOUNT_AND_REMOVE.replace("paths=(%s)\n", "", 1) \
    .replace("%", "%%").replace('[ -e "$p" ] && echo "$p"',
                                '[ -e "$p" ] && printf "K\\t%%s\\n" "$p"') + r"""
fstrim -v / 2>&1 | sed 's/^/T\t/' || true
"""

# Is a person using that Linux: a process on a terminal, or VS Code's server
# (this script itself runs with no terminal).
_IN_USE = r"""
anc=" "; p=$$
while [ "${p:-0}" -gt 1 ]; do anc="$anc$p "; p=$(awk '{print $4}' /proc/$p/stat 2>/dev/null); done
for d in /proc/[0-9]*; do
  case "$anc" in *" ${d#/proc/} "*) continue ;; esac
  c=$(cat "$d/comm" 2>/dev/null) || continue
  case $c in agetty|getty|login) continue ;; esac
  case $(readlink "$d/fd/0" 2>/dev/null) in /dev/pts/*) echo "a terminal: $c"; continue ;; esac
  grep -aq 'vscode-server' "$d/cmdline" 2>/dev/null && echo "VS Code"
done | sort -u | head -5
true
"""


class Busy(Exception):
    """WSL is in use, so it is not shut down: the compact is owed (the
    give-back at close does it).  ``args[0]`` is the list of reasons."""


def remove(name, items, now=None):
    """Remove *items* (the section's, re-planned against a fresh scan: only
    what is still offered) and trim.  Returns ``(freed, removed, kept)``."""
    now = time.time() if now is None else now
    fresh = scan(name, now)
    if fresh["in_use"]:
        raise wsl_disk.WslDiskError(
            "Nothing was removed: %s." % fresh["in_use"])
    ok = {e["path"] for e in fresh["items"]}
    paths = sorted({it["path"] for it in items
                    if it["path"] in ok and offerable(it["kind"],
                                                      it["path"])})
    if not paths:
        return 0, [], []
    for p in paths:                         # quoted literals: no quote in one
        if "'" in p or not wsl_disk._SAFE_PATH_RE.match(p):
            raise wsl_disk.WslDiskError("Refusing to remove %r" % p)
    roots = sorted({wsl_disk._RIG_PATH_RE.match(p).group(1) for p in paths
                    if wsl_disk._is_rig_path(p)})
    if roots:
        busy = _run(name, wsl_disk._RIG_BUSY % " ".join(roots),
                    timeout=60).split()
        if busy:
            raise wsl_disk.WslDiskError(
                "A game is running in %s there; nothing was removed."
                % name)
    out = _run(name, _REMOVE % " ".join("'%s'" % p for p in paths),
               timeout=1800)
    freed, kept = 0, []
    for line in out.splitlines():
        b = line.split("\t", 1)
        if b[0] == "F" and len(b) == 2:
            try:
                freed = int(b[1].strip() or 0)
            except ValueError:
                pass
        elif b[0] == "K" and len(b) == 2:
            kept.append(b[1].strip())
    removed = [p for p in paths if p not in kept]
    _remember(name, verdict="compact", checked=now, freed=freed)
    return freed, removed, kept


def busy_reasons(name, busy_host=None, distros=None, app_scan=None):
    """Why WSL must not be shut down now ([] = it may): the give-back's own
    fail-closed checks (core/disk_giveback.py) - a Linux program open on
    Windows, a fresh rig lease, a distro running besides the app's and this
    one, anything running in the app's Linux - and a person in this one."""
    from . import disk_giveback
    why = list((busy_host or disk_giveback.windows_busy)())
    try:
        running = (distros or disk_giveback.running_distros)()
    except Exception as e:                              # noqa: BLE001
        return why + ["WSL did not say what is running (%s)" % e]
    mine = (runtime.DISTRO.casefold(), name.casefold())
    others = [n for n in running if n.casefold() not in mine]
    if others:
        why.append("%s %s running" % (", ".join(others),
                                      "is" if len(others) == 1 else "are"))
    if any(n.casefold() == name.casefold() for n in running):
        try:
            users = [u.strip() for u in _run(name, _IN_USE, 60).splitlines()]
        except Exception as e:                          # noqa: BLE001
            users = ["it could not be checked (%s)" % e]
        users = [u for u in users if u]
        if users:
            why.append("%s is in use (%s)" % (name, ", ".join(users)))
    if not why:
        try:
            scan = app_scan or (lambda: wsl_disk._wsl_script(
                disk_giveback.scan_script([]), timeout=600))
            why += disk_giveback.parse_scan(scan())[1]
        except Exception as e:                          # noqa: BLE001
            why.append("the app's Linux could not be checked (%s)" % e)
    return why


def compact(prev, progress=None, busy=None, release=None, compact_fn=None):
    """Give *prev*'s disk file back: WSL keeps a distro's disk attached
    until the whole of WSL shuts down (measured on WSL 2.6.1: a terminated
    distro's file stays locked, and even ``wsl --export --vhd`` is refused),
    so WSL is shut down - only when nothing runs - and the file compacted
    through Windows' virtual-disk API, as the give-back at close does.
    Returns ``(before, after)``; raises :class:`Busy` (nothing stopped, the
    compact stays owed) or WslDiskError."""
    name, vhdx = prev["name"], prev["vhdx"]
    why = (busy or (lambda: busy_reasons(name)))()
    if why:
        raise Busy(why)
    release = release or (lambda v: wsl_disk._shutdown_until_free(v, progress))
    compact_fn = compact_fn or wsl_disk.virtdisk_compact
    before = os.path.getsize(vhdx)
    err = None
    with wsl_disk.wsl_paused():
        for _attempt in (1, 2, 3, 4):
            try:
                release(vhdx)
                if progress:
                    progress("Compacting %s's disk file (this can take a "
                             "few minutes)…" % name)
                compact_fn(vhdx)
                err = None
                break
            except Exception as e:                      # noqa: BLE001
                err = e
                if getattr(e, "errno", None) != 32:
                    break
    if err is not None:
        raise wsl_disk.WslDiskError(str(err))
    after = os.path.getsize(vhdx)
    done(name, before, after)
    return before, after


def done(name, before, after):
    """The space is back: that distro is never looked at again."""
    _remember(name, verdict="done", done=time.time(), before=before,
              after=after)


def owed():
    """``[{name, vhdx, size}]``: distros whose leftovers were removed but
    whose disk file was not compacted yet - the give-back at close takes
    them (core/disk_giveback.py).  Registry and files only, no wsl.exe."""
    recs = space_keeper.load_state().get("old_distro") or {}
    where = {n.casefold(): (n, p)
             for n, p in (wsl_disk.registered_distros() or []) if p}
    out = []
    for key, rec in recs.items():
        if rec.get("verdict") != "compact" or key not in where:
            continue
        name, base = where[key]
        vhdx = os.path.join(base, "ext4.vhdx")
        try:
            out.append({"name": name, "vhdx": vhdx,
                        "size": os.path.getsize(vhdx)})
        except OSError:
            continue
    return out
