"""Keeping the app's disk use in check on its own (PAD-613).

David, 2026-10-18: "Users shouldn't have to prune and maintain the cache in
WSL.  We need to be smarter about managing it automatically."

Settings ▸ Manage disk space (webui/shellx_disk.py over core/wsl_disk.py and
core/host_temp.py) already knew how to find and delete everything the app
leaves behind - but only when a person opened it and pressed Clean.  Nothing
else ever did, so on David's own PC the app's Linux sat at 83% with 17 GB
free, and the Windows temp folder held 39 GiB in 653 leftover folders from
cancelled Stern builds.  This module is the same clean-up, run by the app.

WHAT GOES, AND WHEN.  Only things the app can make again, and only once they
have clearly stopped being used:

  * LEFTOVERS from crashed or cancelled runs - WSL staging (``/tmp`` +
    ``/var/tmp``: ``jjp_*``, ``cgc_stage_*``, ``bof_*``, ``pad_aaiw_*``) and
    the Windows temp folder's PAD folders - once nothing inside has changed
    for :data:`STALE_SECS` (a day).  A run that is still going writes all
    the time; a day of silence is a run that ended without cleaning up.
  * HALF-UNPACKED GAMES (``*.partial`` / ``*.part`` in an emulator's cache)
    on the same rule.
  * AN EMULATOR'S UNPACKED GAME not started for :data:`UNUSED_SECS` (30
    days).  Its next Start unpacks it again; nothing is lost - settings and
    high scores are not in the cache.
  * A SPIKE 2 CACHED CARD not booted for 30 days, through the rig's own
    ``cardmount.sh --cache-drop`` (which refuses a mounted or copying one).
  * And when the room left for the app's Linux falls under
    :data:`FLOOR_BYTES`, emulator games are removed least recently played
    first until it is back over - before an extract runs out halfway.

NEVER: anything of an emulator whose game is running, anything a process has
open or is working in, anything started in the last hour, settings and high
scores (``nv*``), save states, the emulators' own Python, a folder the rig
did not make (``Leftover:`` rows are offered in the window, never removed
here), and Stern's deliberate build caches in the temp folder.

ROOM LEFT IS NOT ``df``.  WSL's disk is a file that grows on the Windows
drive; its own ``df`` reports the virtual size (often 1 TB) and says nothing
about the drive behind it.  :func:`room_left` takes the smaller of what the
Linux sees and what the Windows drive can still give it - the room the next
extract will really have.

NEVER STARTS WSL.  The WSL half runs only when WSL is already up (the app
uses it for something, so it is about to be busy anyway); booting the VM to
tidy it would cost more than it saves.  The Windows temp half runs anyway.
"""

import json
import logging
import os
import shutil
import threading
import time

from . import host_temp, wsl_disk

log = logging.getLogger(__name__)

STALE_SECS = 24 * 3600
UNUSED_SECS = 30 * 24 * 3600
RECENT_SECS = 3600
#: The room an extract needs: the biggest titles want 20+ GB while they
#: stage, and a game unpacked for an emulator 4-8 GB.  15 GB keeps a normal
#: extract safe without clearing every game off a small disk.
FLOOR_BYTES = 15 * 1024 ** 3
#: The automatic run comes round this often while the app is open; a run
#: that is not due (see :func:`due`) returns at once.
CHECK_EVERY_SECS = 30 * 60
#: A full run at most this often - unless the room left is under the floor.
MIN_INTERVAL_SECS = 6 * 3600
#: Under this a leftover is noise, and the small ones in /var/tmp are often
#: a rig's live logs or settings (jjp_devices.json, jjp_ui.log).
_MIN_LEFTOVER = 1 << 20

#: Never removed from the temp folder: Stern keeps these on purpose.
_HOST_KEEP = frozenset(getattr(host_temp, "_SPIKE2_KEPT", {}))

_lock = threading.Lock()


def disabled():
    """Captures and tests never delete anything (``PAD_UI_CAPTURE`` /
    ``PAD_UI_NO_RIG``), nor does a machine that says so (``PAD_SPACE_KEEPER=0``)."""
    return bool(os.environ.get("PAD_SPACE_KEEPER") == "0"
                or os.environ.get("PAD_UI_CAPTURE")
                or os.environ.get("PAD_UI_NO_RIG"))


# ---------------------------------------------------------------------------
# What the last run did (shown in the window, and the rate limit)
# ---------------------------------------------------------------------------

def state_path():
    override = os.environ.get("PAD_SPACE_STATE")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "pinball_decryptor", "space_keeper.json")


def load_state():
    try:
        with open(state_path(), encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(st):
    p = state_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=1)
        os.replace(tmp, p)
    except OSError:
        log.exception("saving %s", p)


def due(now=None, st=None):
    """A full run is due: never run, or the last one is old enough."""
    now = time.time() if now is None else now
    st = load_state() if st is None else st
    return now - float(st.get("checked") or 0) >= MIN_INTERVAL_SECS


def auto_enabled(st=None):
    """The window's "Clean up automatically" box: ON unless turned off.
    Off stops the scheduled runs only; "Clean up now" still works."""
    st = load_state() if st is None else st
    return st.get("auto", True) is not False


def set_auto(on):
    st = load_state()
    st["auto"] = bool(on)
    _save_state(st)


# ---------------------------------------------------------------------------
# The WSL side: one pass as root lists every candidate
# ---------------------------------------------------------------------------
# Lines, tab-separated (a name holding a tab or newline is skipped - nothing
# the app makes is named like that):
#   D <free> <used>                  df of /var/tmp
#   L <root>                         an emulator with a game running
#   H <path>                         something a process has open / works in,
#                                    or a loop device's backing file
#   S <bytes> <newest> <path>        a leftover (wsl_disk's staging names)
#   C <root> <bytes> <last> <path>   an emulator cache entry; <last> is the
#                                    newest of its own date and its markers
#   B <build> <entry>                a PB I/O-board build stacked on <entry>
_SCAN = r"""
df -B1 --output=avail,used /var/tmp | tail -1 | awk '{print "D\t" $1 "\t" $2}'
for r in /var/tmp/pad_*/; do
  r=${r%/}; n=${r##*/}
  case $n in pad_aaiw_*) continue ;; esac
  live=0
  for f in "$r"/*.pid "$r"/rig*/*.pid; do
    [ -f "$f" ] || continue
    p=$(head -c 20 "$f" | tr -dc 0-9)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null && live=1
  done
  [ $live = 0 ] && grep -aqlE "[/]var/tmp/$n/" /proc/[0-9]*/cmdline 2>/dev/null && live=1
  [ $live = 1 ] && printf 'L\t%s\n' "$n"
done
for p in /proc/[0-9]*; do
  readlink "$p/cwd" "$p"/fd/* 2>/dev/null
done | grep -aE '^/(var/)?tmp/' | sort -u | sed 's/^/H\t/'
cat /sys/block/loop*/loop/backing_file 2>/dev/null | sed 's/^/H\t/'
awk '{print $5}' /proc/self/mountinfo | grep -aE '^/(var/)?tmp/' |
  sed 's/\\040/ /g; s/^/H\t/'
newest() { find "$1" -xdev -printf '%T@\n' 2>/dev/null | sort -rn | head -1 | cut -d. -f1; }
find /tmp /var/tmp -maxdepth 1 \( -name 'cgc_stage_*' -o -name 'bof_*' \
    -o -name 'jjp_*' -o -name 'pad_aaiw_*' \) 2>/dev/null |
while IFS= read -r p; do
  s=$(du -sxb "$p" 2>/dev/null | cut -f1)
  [ "${s:-0}" -ge @MIN@ ] || continue
  printf 'S\t%s\t%s\t%s\n' "$s" "$(newest "$p")" "$p"
done
for c in /var/tmp/pad_*/cache/*/ /var/tmp/@BOFMULTI@/*/; do
  [ -d "$c" ] || continue
  c=${c%/}; nm=${c##*/}
  n=${c#/var/tmp/}; n=${n%%/*}
  case $nm in *.media) continue ;; esac
  [ $n = pad_pbio ] && case $nm in build-*) continue ;; esac
  case $nm in
    *.partial|*.part) last=$(newest "$c") ;;
    *) last=$(stat -c %Y "$c" "$c/used" "$c/.used" "$c/.complete" "$c/.boot" \
              "$c/source" "$c/.pad_source" "$c/launcher" 2>/dev/null | sort -rn | head -1) ;;
  esac
  s=$(du -scxb "$c" "$c.media" 2>/dev/null | tail -1 | cut -f1)
  printf 'C\t%s\t%s\t%s\t%s\n' "$n" "${s:-0}" "${last:-0}" "$c"
done
for c in /var/tmp/jjp_*/; do
  [ -d "${c}iso" ] || [ -e "${c}sda3.raw" ] || continue
  c=${c%/}
  last=$(stat -c %Y "$c" "$c/.used" 2>/dev/null | sort -rn | head -1)
  s=$(du -sxb "$c" 2>/dev/null | cut -f1)
  printf 'C\tjjp\t%s\t%s\t%s\n' "${s:-0}" "${last:-0}" "$c"
done
for b in /var/tmp/pad_pbio/cache/build-*/; do
  [ -f "$b/layers" ] || continue
  b=${b%/}
  sed -n 's|^\(/var/tmp/pad_pbio/cache/[^/]*\)/.*|\1|p' "$b/layers" | sort -u |
    while IFS= read -r e; do printf 'B\t%s\t%s\n' "$b" "$e"; done
done
true
""".replace("@MIN@", str(_MIN_LEFTOVER)).replace("@BOFMULTI@",
                                                  wsl_disk.BOFMULTI_ROOT)


def parse_scan(text):
    """The scan's lines -> ``{free, used, live, held, staging, cache, deps}``."""
    out = {"free": None, "used": None, "live": set(), "held": set(),
           "staging": [], "cache": [], "deps": {}}
    for line in (text or "").splitlines():
        bits = line.rstrip("\r").split("\t")
        tag = bits[0]
        try:
            if tag == "D" and len(bits) == 3:
                out["free"], out["used"] = int(bits[1]), int(bits[2])
            elif tag == "L" and len(bits) == 2:
                out["live"].add(bits[1])
            elif tag == "H" and len(bits) == 2:
                out["held"].add(bits[1].rstrip("/"))
            elif tag == "S" and len(bits) == 4:
                out["staging"].append({"path": bits[3], "size": int(bits[1]),
                                       "last": int(bits[2] or 0)})
            elif tag == "C" and len(bits) == 5:
                out["cache"].append({"root": bits[1], "size": int(bits[2]),
                                     "last": int(bits[3] or 0),
                                     "path": bits[4]})
            elif tag == "B" and len(bits) == 3:
                out["deps"].setdefault(bits[2], []).append(bits[1])
        except ValueError:
            continue
    return out


def is_leftover_name(path):
    """A staging path the app may remove as a leftover once it is stale."""
    base = path.rstrip("/").rsplit("/", 1)[-1]
    if base.startswith("jjp_"):
        return base.startswith(wsl_disk.JJP_SCRATCH)
    return True


is_jjp_image = wsl_disk.is_jjp_image


def _held(path, held):
    pre = path.rstrip("/") + "/"
    return any(h == path or h.startswith(pre) for h in held)


def _partial(path):
    return path.endswith((".partial", ".part"))


def plan_wsl(scan, now, room=None, floor=FLOOR_BYTES):
    """What to remove from WSL, in order: ``[{path, size, why, what,
    extra}]``.  Pure: the whole decision, testable without a WSL.

    *room* is the room the app's Linux really has (:func:`room_left`), None
    when unknown - then nothing is removed for room, only for age."""
    held, live = scan["held"], scan["live"]
    out = []

    def take(e, why, what):
        out.append({"path": e["path"], "size": e["size"], "why": why,
                    "what": what, "extra": scan["deps"].get(e["path"], [])})

    for e in scan["staging"]:
        if not (wsl_disk._is_safe_staging_path(e["path"])
                and is_leftover_name(e["path"])):
            continue
        if _held(e["path"], held) or now - e["last"] < STALE_SECS:
            continue
        mfr, detail = wsl_disk._classify(e["path"])
        take(e, "leftover", "%s: %s" % (mfr, detail))

    games = []
    for e in scan["cache"]:
        jjp = e["root"] == "jjp"
        if (e["root"] in live or _held(e["path"], held)
                or not (is_jjp_image(e["path"]) if jjp
                        else wsl_disk._is_rig_path(e["path"]))):
            continue
        idle = now - e["last"]
        name = e["path"].rsplit("/", 1)[-1]
        what = ("Jersey Jack Pinball: emulator image %s" % name[4:] if jjp
                else "%s: %s" % (wsl_disk.RIG_MAKERS.get(e["root"],
                                                         "Emulator"), name))
        if _partial(e["path"]):
            if idle >= STALE_SECS:
                take(e, "leftover", what + " (half unpacked)")
        elif idle >= UNUSED_SECS:
            take(e, "unused", what)
        elif idle >= RECENT_SECS:
            games.append((e, what))

    if room is not None:
        room += sum(x["size"] for x in out)
        for e, what in sorted(games, key=lambda g: g[0]["last"]):
            if room >= floor:
                break
            take(e, "room", what)
            room += e["size"]
    return out


def room_left(free_inside, used_inside, vhdx_size=None, host_free=None):
    """The room the app's Linux really has: what its own filesystem has
    free, but never more than the Windows drive can still give the growing
    disk file plus the slack already inside that file."""
    if free_inside is None:
        return None
    if vhdx_size is None or host_free is None or used_inside is None:
        return free_inside
    return min(free_inside, host_free + max(0, vhdx_size - used_inside))


def _wsl_room(scan):
    try:
        _name, vhdx = wsl_disk._default_distro_vhdx()
        size = os.path.getsize(vhdx) if vhdx else None
        host = shutil.disk_usage(os.path.dirname(vhdx)).free if vhdx else None
    except OSError:
        size = host = None
    return room_left(scan["free"], scan["used"], size, host)


def _remove_wsl(plan):
    """Delete the plan, one emulator at a time, so one that has just started
    a game (wsl_disk.delete checks again and refuses) keeps only its own
    entries.  Returns the plan items actually removed."""
    groups = {}
    for item in plan:
        m = wsl_disk._RIG_PATH_RE.match(item["path"])
        groups.setdefault(m.group(1) if m else "", []).append(item)
    def paths_of(root, items):
        paths = []
        for it in items:
            paths.append(it["path"])
            if root == wsl_disk.BOFMULTI_ROOT:      # its own pictures
                paths.append(it["path"] + ".media")
            paths += [x for x in it["extra"] if wsl_disk._is_rig_path(x)]
        return sorted(set(paths))

    done = []
    for root, items in groups.items():
        try:
            wsl_disk.delete(paths_of(root, items))
            done += items
            continue
        except Exception as exc:                            # noqa: BLE001
            if len(items) == 1:
                log.info("space keeper: kept %s (%s)", items[0]["path"], exc)
                continue
        # one stuck entry must not keep the rest for ever: one at a time
        for it in items:
            try:
                wsl_disk.delete(paths_of(root, [it]))
                done.append(it)
            except Exception as exc:                        # noqa: BLE001
                log.info("space keeper: kept %s (%s)", it["path"], exc)
    return done


# ---------------------------------------------------------------------------
# The Windows temp folder
# ---------------------------------------------------------------------------

def _newest_mtime(path):
    try:
        newest = os.lstat(path).st_mtime
    except OSError:
        return None
    if os.path.isdir(path) and not os.path.islink(path):
        for root, dirs, files in os.walk(path):
            for n in dirs + files:
                try:
                    newest = max(newest, os.lstat(os.path.join(root, n)).st_mtime)
                except OSError:
                    pass
    return newest


def plan_host(entries, now):
    out = []
    for e in entries:
        name = os.path.basename(e["path"])
        if name in _HOST_KEEP or e["size"] < _MIN_LEFTOVER:
            continue
        last = _newest_mtime(e["path"])
        if last is None or now - last < STALE_SECS:
            continue
        out.append({"path": e["path"], "size": e["size"], "why": "leftover",
                    "what": "%s: %s" % (e["manufacturer"], e["detail"]),
                    "extra": []})
    return out


# ---------------------------------------------------------------------------
# Spike 2's cached cards (on the emulator's own disk)
# ---------------------------------------------------------------------------

def plan_cards(rows, now):
    """Cards not booted for 30 days.  A card never booted (no ``.boot``) has
    no date here and stays: the rig's own eviction takes those first.  The
    library's newest builds (``pinned``, PAD-727) stay however long they go
    unbooted: they are the cache's reason for being."""
    out = []
    for r in rows:
        if r.get("pinned"):
            continue
        boot = int(r.get("boot") or 0)
        if boot and now - boot >= UNUSED_SECS:
            out.append({"path": r["label"], "size": int(r["real_kb"]) * 1024,
                        "why": "unused", "what": "Stern Spike 2: cached card "
                        + r["label"], "extra": []})
    return out


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

_WHY = {"leftover": "left behind by a run that ended without cleaning up",
        "unused": "not used for 30 days",
        "room": "the oldest-played, to keep room free"}


def tidy(force=False, cards=None, now=None, dry_run=False, wsl=None):
    """Run the automatic clean-up if it is due (or *force*).

    *cards* is ``(list_rows, drop_labels)`` for Spike 2's card cache (the
    web UI's emu_cache helpers), None to leave cards alone.  *wsl*: run the
    WSL half - None means "only if WSL is already running".  Returns the
    run's record (also saved, see :func:`load_state`), or None when nothing
    ran.  *dry_run* decides without deleting or saving."""
    if not dry_run and disabled():
        return None
    if not (force or dry_run or auto_enabled()):
        return None
    if not _lock.acquire(blocking=False):
        return None
    try:
        return _tidy(force, cards, time.time() if now is None else now,
                     dry_run, wsl)
    finally:
        _lock.release()


def _tidy(force, cards, now, dry_run, wsl):
    st = load_state()
    if wsl is None:
        wsl = wsl_disk.is_supported() and wsl_disk.is_running()
    if not (force or dry_run or due(now, st)):
        # Between full runs only the room is checked: one df, no du/find.
        if not wsl:
            return None
        try:
            u = wsl_disk.usage()
            room = _wsl_room({"free": u["free"], "used": u["used"]})
        except Exception:                                   # noqa: BLE001
            return None
        if room is None or room >= FLOOR_BYTES:
            return None
    scan, room = None, None
    if wsl:
        try:
            scan = parse_scan(wsl_disk._wsl_script(_SCAN, timeout=600))
            room = _wsl_room(scan)
        except Exception as exc:                            # noqa: BLE001
            log.info("space keeper: WSL scan failed (%s)", exc)

    plan = []
    if scan is not None:
        plan += [dict(p, where="wsl") for p in plan_wsl(scan, now, room)]
    try:
        plan += [dict(p, where="host")
                 for p in plan_host(host_temp.scan(), now)]
    except Exception as exc:                                # noqa: BLE001
        log.info("space keeper: temp folder scan failed (%s)", exc)
    if cards and scan is not None:      # listing cards runs wsl.exe
        try:
            plan += [dict(p, where="card")
                     for p in plan_cards(cards[0](), now)]
        except Exception as exc:                            # noqa: BLE001
            log.info("space keeper: card cache list failed (%s)", exc)

    if dry_run:
        return {"at": now, "room": room, "removed": plan,
                "freed": sum(p["size"] for p in plan), "dry_run": True}

    done = []
    wsl_items = [p for p in plan if p["where"] == "wsl"]
    if wsl_items:
        done += _remove_wsl(wsl_items)
    host_items = [p for p in plan if p["where"] == "host"]
    if host_items:
        try:
            host_temp.delete([p["path"] for p in host_items])
            done += [p for p in host_items if not os.path.exists(p["path"])]
        except Exception as exc:                            # noqa: BLE001
            log.info("space keeper: temp folder clean failed (%s)", exc)
    card_items = [p for p in plan if p["where"] == "card"]
    if card_items:
        try:
            cards[1]([p["path"] for p in card_items])
            left = {r["label"] for r in cards[0]()}
            done += [p for p in card_items if p["path"] not in left]
        except Exception as exc:                            # noqa: BLE001
            log.info("space keeper: card cache drop failed (%s)", exc)

    freed = sum(p["size"] for p in done)
    for p in done:
        log.info("space keeper: removed %s (%s, %s)", p["path"], p["what"],
                 _WHY.get(p["why"], p["why"]))
    rec = {"at": now, "freed": freed, "count": len(done),
           "room": room, "wsl": scan is not None,
           "removed": [{k: p[k] for k in ("where", "what", "size", "why")}
                       for p in done][:200]}
    st["checked"] = now
    st["auto"] = auto_enabled()     # the box may have changed meanwhile
    if done:
        st["last"] = rec
        st["freed_total"] = int(st.get("freed_total") or 0) + freed
    _save_state(st)
    return rec


def summary(st=None, now=None):
    """One sentence for the window: what the automatic clean-up last did."""
    st = load_state() if st is None else st
    now = time.time() if now is None else now
    last = st.get("last")
    off = "" if auto_enabled(st) else " It is turned off on this PC."
    if not st.get("checked"):
        return off.strip() or "It has not run on this PC yet."
    if not last:
        return ("Last checked %s: nothing needed removing."
                % _when(st["checked"], now)) + off
    s = ("Last clean-up %s removed %d item%s and freed %s"
         % (_when(last["at"], now), last["count"],
            "" if last["count"] == 1 else "s", _fmt(last["freed"])))
    total = int(st.get("freed_total") or 0)
    if total > last["freed"]:
        s += " (%s in all)" % _fmt(total)
    s += "."
    if st["checked"] > last["at"] + 60:
        s += " Last checked %s." % _when(st["checked"], now)
    return s + off


def _fmt(n):
    n = float(n or 0)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return ("%d %s" % (n, unit)) if unit == "B" else (
                "%.1f %s" % (n, unit))
        n /= 1024.0


def _when(t, now):
    ago = max(0, now - float(t))
    if ago < 90:
        return "just now"
    if ago < 3600:
        return "%d minutes ago" % round(ago / 60)
    if ago < 36 * 3600:
        h = round(ago / 3600)
        return "%d hour%s ago" % (h, "" if h == 1 else "s")
    return time.strftime("on %d %b %Y", time.localtime(t))


__all__ = ["tidy", "plan_wsl", "plan_host", "plan_cards", "parse_scan",
           "room_left", "summary", "load_state", "due", "disabled",
           "auto_enabled", "set_auto",
           "FLOOR_BYTES", "STALE_SECS", "UNUSED_SECS"]
