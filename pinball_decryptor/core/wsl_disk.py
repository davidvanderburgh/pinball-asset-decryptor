"""WSL disk-space management for the WSL-backed pipelines (Windows only).

On Windows every native-tool pipeline (CGC, Dutch Pinball, Barrels of Fun,
Jersey Jack) runs its ext4 / ``dd`` / ``debugfs`` work inside the **default**
WSL2 distro via ``wsl -u root -- bash`` (see :class:`core.executor.WslExecutor`
and the per-plugin clones).  All staging therefore lands in that one distro's
filesystem (``/tmp`` + ``/var/tmp``), and that filesystem is a single virtual
disk (``ext4.vhdx``) on the Windows host that grows on demand and **never
shrinks on its own**.

A completed pipeline cleans up its own staging, but a crashed/cancelled run
leaves it behind, and even after deletion the freed bytes stay trapped inside
the ``.vhdx`` (Windows sees no space back) until the disk is compacted.  This
module gives the GUI a "disk management" view of that distro so users never
have to touch ``df`` / ``diskpart`` by hand:

  * :func:`available`     -- is WSL usable at all (Windows + a default distro)?
  * :func:`usage`         -- total / used / free of the WSL filesystem.
  * :func:`scan_staging`  -- every leftover PAD staging artifact under
                             ``/tmp`` + ``/var/tmp``, attributed to a
                             manufacturer/game, with its on-disk size.
  * :func:`scan_rigs`     -- what the emulators keep under ``/var/tmp/pad_<rig>``:
                             unpacked games, run folders, their Python setup,
                             leftovers (PAD-318) - with whether a game of that
                             emulator is running.
  * :func:`delete`        -- ``rm -rf`` selected staging paths (prefix-guarded).
  * :func:`vhdx_info`     -- the backing ``.vhdx`` path + its size on the
                             Windows drive, and an estimate of how much a
                             compact would hand back.
  * :func:`reclaim`       -- shut WSL down and compact the ``.vhdx`` so the
                             freed space returns to Windows (needs admin).

Everything is a no-op / "unsupported" off Windows -- the GUI only surfaces the
button there.
"""

import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile

from . import runtime

_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _gib(n):
    """Short binary-GiB string for user-facing messages (``12.0 GiB``)."""
    return "%.1f GiB" % (n / 1024 ** 3) if n is not None else "unknown"


def _decode_wsl(b):
    """Decode wsl.exe output, which is UTF-16-LE (utf-8 on odd configs)."""
    if not b:
        return ""
    if b"\x00" in b:
        return b.decode("utf-16-le", errors="replace")
    return b.decode("utf-8", errors="replace")

# Top-level staging path prefixes our WSL pipelines create.  A scanned entry
# must start with one of these (and contain no shell metacharacters) before we
# will ``rm -rf`` it -- so a bug or a tampered path can never delete outside
# our own staging.  Keep in sync with the plugins:
#   CGC  -> /tmp/cgc_stage_<game>_<pid>   (pipeline._stage_dir_for)
#   BoF  -> /tmp/bof_<game>_*             (bof/pipeline.py)
#   JJP  -> /tmp/jjp_* , /var/tmp/jjp_*   (jjp/pipeline.py)
#   DP   -> /tmp/pad_aaiw_*               (dp/aaiw.py)
_ALLOWED_PREFIXES = (
    "/tmp/cgc_stage_",
    "/tmp/bof_",
    "/tmp/jjp_",
    "/tmp/pad_aaiw_",
    "/var/tmp/cgc_stage_",
    "/var/tmp/bof_",
    "/var/tmp/jjp_",
    "/var/tmp/pad_aaiw_",
)

# The scan looks for these top-level name patterns under both staging roots
# (``/tmp`` + ``/var/tmp``).  Searching both roots for every name is harmless --
# a name simply won't match where that plugin doesn't stage -- and ``delete``
# re-validates each hit against _ALLOWED_PREFIXES, so the scan can be broad.
_SCAN_ROOTS = ("/tmp", "/var/tmp")
_SCAN_NAMES = ("cgc_stage_*", "bof_*", "jjp_*", "pad_aaiw_*")

# Friendly manufacturer label per prefix (matches plugin `display` strings).
_CGC = "Chicago Gaming Company"
_BOF = "Barrels of Fun"
_JJP = "Jersey Jack Pinball"
_DP = "Dutch Pinball"

_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./ \-]+$")


class WslDiskError(Exception):
    """A WSL disk-management operation failed (with a user-facing message)."""


# ---------------------------------------------------------------------------
# Low-level WSL invocation
# ---------------------------------------------------------------------------

def is_supported():
    """True on the only platform this module targets (Windows/WSL)."""
    return sys.platform == "win32"


def _wsl_bash(bash_cmd, timeout=120):
    """Run *bash_cmd* in the WSL distro the app uses, as root; return stdout.

    Mirrors :class:`core.executor.WslExecutor` - the same head, from the same
    function - so this module reports on exactly the Linux the pipelines stage
    into, which since the app brought its own is not necessarily the machine's
    default one.
    """
    proc = subprocess.run(
        runtime.wsl_head(root=True) + ["--", "bash", "-c", bash_cmd],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_CREATE_FLAGS,
    )
    if proc.returncode != 0:
        out = (proc.stderr or "") + (proc.stdout or "")
        raise WslDiskError(out.strip() or f"wsl exited {proc.returncode}")
    return proc.stdout


def _wsl_script(script, timeout=120):
    """Run a multi-line bash *script* as :func:`_wsl_bash` does.  wsl.exe
    hands its command line to a shell of its own first, which expands every
    ``$var`` and eats the quotes before bash sees them, so the script goes
    across base64-encoded and is decoded on the Linux side."""
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return _wsl_bash("echo %s | base64 -d | bash" % b64, timeout=timeout)


def available():
    """``(ok, message)`` -- whether WSL is installed and a distro responds."""
    if not is_supported():
        return False, "WSL disk management is only available on Windows."
    try:
        _wsl_bash("echo ok", timeout=20)
        return True, "WSL available"
    except FileNotFoundError:
        return False, ("WSL is not installed. The WSL-backed pipelines "
                       "(Chicago Gaming, Dutch Pinball, Barrels of Fun, "
                       "Jersey Jack) won't run without it.")
    except Exception as e:
        return False, f"WSL is not responding: {e}"


def is_running():
    """True if a WSL distro is already running.

    Uses ``wsl -l --running -q`` which only *lists* running distros -- it never
    starts one.  Lets the passive startup badge check WSL staging only when WSL
    is already up, so we never spin the distro up just to draw a badge.
    """
    if not is_supported():
        return False
    try:
        proc = subprocess.run(
            ["wsl", "-l", "--running", "-q"],
            capture_output=True, timeout=15, creationflags=_CREATE_FLAGS)
    except Exception:
        return False
    out = proc.stdout or b""
    # wsl.exe emits UTF-16-LE; fall back to utf-8 for odd configs.
    text = out.decode("utf-16-le", errors="replace") if b"\x00" in out \
        else out.decode("utf-8", errors="replace")
    return any(line.strip().lstrip("﻿") for line in text.splitlines())


def _lxss_names():
    """Every registered distro's name, casefolded, from ``HKCU\\...\\Lxss``;
    None when the registry cannot be read.  Never runs wsl.exe."""
    try:
        import winreg
    except ImportError:
        return None
    base = r"Software\Microsoft\Windows\CurrentVersion\Lxss"
    names = set()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as dk:
                        names.add(
                            winreg.QueryValueEx(dk, "DistributionName")[0]
                            .casefold())
                except OSError:
                    continue
    except OSError:
        return None
    return names


def running_distros():
    """Names of the WSL distros running right now; ``[]`` when none, off
    Windows, or when wsl.exe cannot answer.

    Same ``wsl -l --running -q`` as :func:`is_running`, so it never starts a
    distro - which matters most to the in-app update's WSL restart, which must
    not boot the VM it is about to shut down.

    NOTHING RUNNING IS ANSWERED WITH A SENTENCE, and a localised one ("There
    are no running distributions."), so the lines are kept only when they name
    a distro the registry knows.  Without the registry, a failed exit is the
    empty answer.
    """
    if not is_supported():
        return []
    try:
        proc = subprocess.run(
            ["wsl", "-l", "--running", "-q"],
            capture_output=True, timeout=15, creationflags=_CREATE_FLAGS)
    except Exception:
        return []
    names = [line.strip().lstrip("﻿")
             for line in _decode_wsl(proc.stdout or b"").splitlines()]
    names = [n for n in names if n]
    known = _lxss_names()
    if known is None:
        return names if proc.returncode == 0 else []
    return [n for n in names if n.casefold() in known]


def default_distro_name():
    """The machine's DEFAULT distro's name, or None.  Registry only.

    Not :func:`_default_distro_vhdx`, which answers "the distro the app uses"
    and has to ask the runtime whether ours is usable to do it - a wsl.exe
    call, and one that starts PAD-Runtime.
    """
    if not is_supported():
        return None
    try:
        import winreg
    except ImportError:
        return None
    base = r"Software\Microsoft\Windows\CurrentVersion\Lxss"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
            guid = winreg.QueryValueEx(k, "DefaultDistribution")[0]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            base + "\\" + guid) as k:
            return winreg.QueryValueEx(k, "DistributionName")[0]
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Usage + scan (read-only)
# ---------------------------------------------------------------------------

def usage():
    """Return the WSL filesystem usage as ``{total, used, free, pct}`` (bytes).

    ``pct`` is used/total as an int 0-100.  ``df`` the ``/var/tmp`` path -- that
    is the filesystem the WSL pipelines stage into, and it is always on the
    persistent (resizable) ext4 disk.  We deliberately do NOT df ``/tmp``: on
    WSL configs where systemd mounts ``/tmp`` as a RAM-backed ``tmpfs`` that
    would report ~half of RAM instead of the disk, so the usage bar and the
    resize UI would track a filesystem the disk resize can't grow (RTS).
    """
    out = _wsl_bash("df -B1 --output=size,used,avail /var/tmp | tail -1",
                    timeout=30)
    parts = out.split()
    if len(parts) < 3:
        raise WslDiskError(f"Could not parse df output: {out!r}")
    total, used, free = (int(parts[0]), int(parts[1]), int(parts[2]))
    pct = int(round(used * 100 / total)) if total else 0
    return {"total": total, "used": used, "free": free, "pct": pct}


def _classify(path):
    """Map a staging path to ``(manufacturer, detail)`` for the UI grouping."""
    base = path.rstrip("/").rsplit("/", 1)[-1]
    if base.startswith("cgc_stage_"):
        rest = base[len("cgc_stage_"):]
        # New form is "<game>_<pid>"; legacy form is just "<pid>".
        head, _, tail = rest.rpartition("_")
        if head and tail.isdigit():
            return _CGC, _prettify(head)
        return _CGC, "extract / write staging"
    if base.startswith("bof_"):
        return _BOF, _bof_detail(base)
    if base.startswith("jjp_"):
        return _JJP, _jjp_detail(base)
    if base.startswith("pad_aaiw_"):
        return _DP, "Alice in Wonderland staging"
    return "Other", base


def _prettify(game_key):
    """`pulp_fiction` -> `Pulp Fiction` for display (game-key form)."""
    return game_key.replace("_", " ").replace("-", " ").strip().title()


def _title_from_filename(s):
    """Readable title from a sanitized ISO basename, preserving its casing
    (``Wonka-v03.03`` stays ``Wonka-v03.03``, not ``Wonka V03.03``)."""
    return s.replace("_", " ").strip() or "staging"


_UUID8_RE = re.compile(r"^[0-9a-f]{8}$")


def _jjp_detail(base):
    """Pull the game title out of a `jjp_*` staging name.

    JJP names its staging after the ISO file (``jjp_raw_<iso-basename>.img``)
    and its scratch dirs ``jjp_iso_<iso-basename>_<uuid8>`` /
    ``jjp_chunks_<iso-basename>_<uuid8>`` (the basename was added so leftovers
    are attributable; older runs used a bare ``<uuid8>`` with no title).  The
    raw image is the space-heavy one, so it shows just the title.
    """
    if base.startswith("jjp_raw_"):
        stem = base[len("jjp_raw_"):]
        if stem.endswith(".img"):
            stem = stem[:-4]
        return _title_from_filename(stem)
    for prefix, role in (("jjp_iso_", "ISO mount"),
                         ("jjp_chunks_", "conversion chunks"),
                         ("jjp_debugfs_", "debugfs scratch"),
                         ("jjp_ssd_", "Direct-SSD staging"),
                         ("jjp_sys_", "system-file staging")):
        if base.startswith(prefix):
            rest = base[len(prefix):]
            head, _, tail = rest.rpartition("_")
            if head and _UUID8_RE.match(tail):
                return f"{_title_from_filename(head)} ({role})"
            return role  # bare-uuid form -- no title in the path
    return "extract / write staging"


def _bof_detail(base):
    """Pull a readable label out of a `bof_*` staging name.

    Names look like ``bof_<game>_extracted`` / ``bof_<game>_repack`` /
    ``bof_<game>.tar.gz`` / ``bof_convert.gd`` / ``bof_tex.webp`` /
    ``bof_gdc_compile``.  We strip the known role suffixes to recover the
    game token where there is one, else fall back to the bare name.
    """
    stem = base[len("bof_"):]
    for suffix in ("_extracted", "_repack.tar.gz", "_repack",
                   "_mod.tar.gz", "_patched.x86_64", "_patch.sh",
                   ".tar.gz"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if stem in ("convert.gd", "tex.webp", "gdc_compile"):
        return "build scratch"
    return _prettify(stem) if stem else "build scratch"


def scan_staging():
    """Return a list of leftover staging entries, largest first.

    Each entry is ``{path, size, manufacturer, detail}`` (size in bytes).
    ``du -sxb`` stays on one filesystem (``-x``) so a still-mounted loop image
    under a crashed run's mountpoint is reported as its staging footprint, not
    the mounted device's size.
    """
    # One `find` over both roots: -maxdepth 1 keeps it to the top-level staging
    # entries, the -name group matches our prefixes, and `du -sxb` sizes each
    # without crossing into a still-mounted loop image (-x).  `find` returns 0
    # on no-match (unlike a `nullglob` for-loop, whose trailing `[ -e ]` test
    # fails and exits 1), but a missing /var/tmp would still make it non-zero,
    # so swallow with `; true`.
    roots = " ".join(_SCAN_ROOTS)
    name_expr = " -o ".join(f"-name '{n}'" for n in _SCAN_NAMES)
    cmd = (f"find {roots} -maxdepth 1 \\( {name_expr} \\) "
           f"-exec du -sxb {{}} + 2>/dev/null; true")
    out = _wsl_bash(cmd, timeout=300)
    entries = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        size_str, _, path = line.partition("\t")
        if not path:
            # du separates with a tab, but be tolerant of whitespace.
            bits = line.split(None, 1)
            if len(bits) != 2:
                continue
            size_str, path = bits
        try:
            size = int(size_str)
        except ValueError:
            continue
        if size == 0:
            continue  # empty leftover -- nothing to free, just noise
        path = path.strip()
        mfr, detail = _classify(path)
        entries.append({"path": path, "size": size,
                        "manufacturer": mfr, "detail": detail})
    entries.sort(key=lambda e: e["size"], reverse=True)
    return entries


# ---------------------------------------------------------------------------
# The emulators' own folders (PAD-318)
# ---------------------------------------------------------------------------
# Every emulator rig keeps everything it writes under one root,
# /var/tmp/pad_<rig> (tools/*_emu/*path.sh): cache/<build> (a game unpacked
# from its update - the big ones), rig<N> (a slot's last run), its own Python
# (py27, py3, mamba, env, site...), nv<N> (settings and high scores - never
# offered) and whatever else a session left there.  None of it shrinks on its
# own, and the staging scan above never saw it: a full WSL disk showed
# "Nothing to clean up".

#: /var/tmp/pad_<rig> -> the maker it emulates, as the dialog groups rows.
RIG_MAKERS = {
    "pad_ap": "American Pinball", "pad_apav": "American Pinball",
    "pad_bof": "Barrels of Fun", "pad_cgc": "Chicago Gaming Company",
    "pad_cgcpf": "Chicago Gaming Company", "pad_dp": "Dutch Pinball",
    "pad_pb": "Pinball Brothers", "pad_pbio": "Pinball Brothers",
    "pad_proc": "P-ROC board", "pad_spooky": "Spooky Pinball",
    "pad_spkproc": "Spooky Pinball", "pad_spkproc_decomp": "Spooky Pinball",
}
#: Roots that are a second rig of the same maker: said beside each entry.
RIG_VARIANTS = {"pad_apav": "A/V rig", "pad_spkproc": "P-ROC rig",
                "pad_pbio": "I/O-board rig", "pad_cgcpf": "playfield rig"}
#: A rig's own Python, re-installed when next needed.
_RIG_ENVS = ("py27", "py3", "mamba", "env", "bin", "site")
#: Never offered: settings and high scores (nv<N>), a run's home, mount
#: points and scratch too small to matter.
_RIG_KEEP_RE = re.compile(r"^(nv\d*|home|lower|loctmp)$")
_RIG_MIN_BYTES = 1 << 20
_RIG_PATH_RE = re.compile(
    r"^/var/tmp/(pad_[a-z0-9_]+)/(cache/)?([A-Za-z0-9_.\- ]+)$")

# One pass as root: for each rig root, whether a game of it is running (a
# live pid in any of its *.pid files, or a process whose command line names
# the root - "[/]" keeps grep from matching its own), then the size of each
# entry: cache/<build>, and every other top-level folder.  ONE du per root,
# games first: a run folder hard-links the game it ran, and du counts a file
# once, for the first entry that has it - so a run folder's size is what it
# holds of its own, and the rows add up to what deleting them frees.
_RIG_SCAN = r"""
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
  list=()
  for c in "$r"/cache/*/ "$r"/*/; do
    [ -d "$c" ] || continue
    c=${c%/}
    [ "${c##*/}" = cache ] && continue
    list+=("$c")
  done
  [ ${#list[@]} -gt 0 ] || continue
  du -sxb "${list[@]}" 2>/dev/null | sed "s/\$/\t$live/"
done
true
"""


# Which of these rig roots (%s) has a game running: the scan's test.
_RIG_BUSY = r"""
for n in %s; do
  b=0
  grep -aqlE "[/]var/tmp/$n/" /proc/[0-9]*/cmdline 2>/dev/null && b=1
  for f in /var/tmp/$n/*.pid /var/tmp/$n/rig*/*.pid; do
    [ -f "$f" ] || continue
    p=$(head -c 20 "$f" | tr -dc 0-9)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null && b=1
  done
  [ $b = 1 ] && echo "$n"
done
true
"""


def _rig_detail(root, sub, name):
    """(what it is, kind) for one entry of a rig's root."""
    if root == "pad_spkproc_decomp":
        return "Leftover: decompiled %s" % name, "leftover"
    if sub:
        return "Unpacked game: %s" % name, "game"
    m = re.match(r"^rig(\d+)$", name)
    if m:
        return "Last run's folder (rig %s)" % m.group(1), "run"
    if name.startswith(_RIG_ENVS):
        return "The emulator's Python (%s)" % name, "env"
    return "Leftover: %s" % name, "leftover"


def scan_rigs():
    """The emulators' folders, largest first: ``{path, size, manufacturer,
    detail, kind, live}`` - kind ``game`` (re-unpacked on its next Start),
    ``run`` (made again on the next Start), ``env`` (re-installed when next
    needed), ``leftover``; ``live`` = a game of that emulator is running."""
    out = _wsl_script(_RIG_SCAN, timeout=600)
    entries = []
    for line in out.splitlines():
        bits = line.rstrip("\r").split("\t")
        if len(bits) != 3:
            continue
        size_str, path, live = bits
        m = _RIG_PATH_RE.match(path)
        try:
            size = int(size_str)
        except ValueError:
            continue
        if not m or size < _RIG_MIN_BYTES or _RIG_KEEP_RE.match(m.group(3)):
            continue
        root, sub, name = m.groups()
        detail, kind = _rig_detail(root, sub, name)
        if root in RIG_VARIANTS:
            detail += " (%s)" % RIG_VARIANTS[root]
        entries.append({"path": path, "size": size,
                        "manufacturer": RIG_MAKERS.get(root, "Emulator"),
                        "detail": detail, "kind": kind,
                        "live": live.strip() == "1"})
    entries.sort(key=lambda e: e["size"], reverse=True)
    return entries


def _is_rig_path(path):
    m = _RIG_PATH_RE.match(path)
    return bool(m) and not m.group(1).startswith("pad_aaiw_") \
        and not _RIG_KEEP_RE.match(m.group(3)) \
        and m.group(3) not in (".", "..") \
        and not (not m.group(2) and m.group(3) == "cache")


# ---------------------------------------------------------------------------
# Delete staging (fast, non-disruptive, no admin needed)
# ---------------------------------------------------------------------------

def _is_safe_staging_path(path):
    if _is_rig_path(path):
        return True
    return (any(path.startswith(p) for p in _ALLOWED_PREFIXES)
            and bool(_SAFE_PATH_RE.match(path))
            and path not in ("/tmp", "/var/tmp", "/"))


def delete(paths):
    """``rm -rf`` each staging path in *paths* (prefix-guarded).

    Returns the number of bytes freed inside WSL (sum of the deleted sizes as
    measured just before removal).  Any path failing the safety check raises
    :class:`WslDiskError` *before* anything is deleted.
    """
    paths = [p.strip() for p in paths if p and p.strip()]
    if not paths:
        return 0
    for p in paths:
        if not _is_safe_staging_path(p):
            raise WslDiskError(
                f"Refusing to delete a path outside PAD staging: {p!r}")
    # Measure first (so we can report freed bytes), then unmount whatever is
    # mounted inside and remove (_UNMOUNT_AND_REMOVE).  An emulator's folder
    # is never deleted while a game of it runs - checked again here, not just
    # at scan time (the game may have started since).
    roots = sorted({_RIG_PATH_RE.match(p).group(1) for p in paths
                    if _is_rig_path(p)})
    if roots:
        busy = _wsl_script(_RIG_BUSY % " ".join(roots), timeout=60).split()
        if busy:
            raise WslDiskError(
                "A game is running in %s - stop it on its Emulate tab "
                "first; nothing was deleted." % ", ".join(
                    sorted({RIG_MAKERS.get(b, b) for b in busy})))
    quoted = " ".join("'%s'" % p for p in paths)
    freed_out = _wsl_bash(
        f"du -scxb {quoted} 2>/dev/null | tail -1 | cut -f1", timeout=120)
    try:
        freed = int(freed_out.strip())
    except ValueError:
        freed = 0
    left = _wsl_script(_UNMOUNT_AND_REMOVE % quoted, timeout=300).split("\n")
    left = [p for p in (s.strip() for s in left) if p]
    if left:
        raise WslDiskError(
            "Could not delete %s - something in it is still in use. Stop "
            "every game on the Emulate tabs (or restart WSL) and try again."
            % ", ".join(left))
    return freed


# Unmount every mount at or under each path, deepest first, then remove.  A
# mount can sit below the folder being deleted, not on it: the PB I/O-board
# rig keeps a machine's OS image loop-mounted read-only at
# cache/os-<iso>/mnt between runs, and a crashed DP/JJP run can leave an ISO
# mount behind - `umount -R <folder>` missed those, and `rm -rf` walked into
# the read-only image and failed on every file in it (PAD-422).  A mount that
# will not come off is detached lazily (whatever holds it lets go later), and
# `rm --one-file-system` never descends into one still there.  Prints each
# path that is left.  The paths are quoted literals (%s), never a variable
# wsl.exe's own shell could expand.
_UNMOUNT_AND_REMOVE = r"""
paths=(%s)
for p in "${paths[@]}"; do
  while read -r _ _ _ _ mp _; do
    mp=${mp//\\040/ }
    case "$mp" in "$p"|"$p"/*) echo "${#mp} $mp" ;; esac
  done < /proc/self/mountinfo | sort -rn | cut -d' ' -f2- |
  while IFS= read -r mp; do
    umount "$mp" 2>/dev/null || umount -l "$mp" 2>/dev/null
  done
done
rm -rf --one-file-system "${paths[@]}" 2>/dev/null
for p in "${paths[@]}"; do [ -e "$p" ] && echo "$p"; done
true
"""


def delete_all():
    """Delete every leftover staging entry; return ``(count, bytes_freed)``."""
    entries = scan_staging()
    if not entries:
        return 0, 0
    freed = delete([e["path"] for e in entries])
    return len(entries), freed


# ---------------------------------------------------------------------------
# Reclaim to Windows (compact the .vhdx -- disruptive, needs admin)
# ---------------------------------------------------------------------------

def _guid_named(lxss_key, want):
    """The Lxss subkey GUID whose ``DistributionName`` is *want*, or None.

    WSL keys its distros by GUID and keeps the name inside, so finding one by
    name means walking the subkeys.  None rather than an exception when it is
    not there: the caller then falls back to the default distro, which is what
    a machine without our runtime uses anyway."""
    import winreg
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(lxss_key, i)
        except OSError:
            return None
        i += 1
        try:
            with winreg.OpenKey(lxss_key, sub) as k:
                if winreg.QueryValueEx(k, "DistributionName")[0] == want:
                    return sub
        except OSError:
            continue


def _default_distro_vhdx():
    """Return ``(distro_name, vhdx_path)`` for the distro THE APP USES.

    Read from ``HKCU\\...\\Lxss``: the ``DefaultDistribution`` GUID points at
    the per-distro subkey holding ``BasePath`` (and ``DistributionName``); the
    disk is ``ext4.vhdx`` under it.  Returns ``(None, None)`` if not found.

    NOT NECESSARILY THE DEFAULT ONE, despite the name this has always carried.
    Everything else in this module measures the Linux the app actually runs in
    - :func:`usage` df's the filesystem the pipelines stage into - and this is
    what the RESIZE acts on.  Left pointing at the default, the dialog would
    report one distro filling up and its Resize button would grow another.
    """
    if not is_supported():
        return None, None
    try:
        import winreg
    except ImportError:
        return None, None
    base = r"Software\Microsoft\Windows\CurrentVersion\Lxss"
    want = runtime.wsl_distro()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
            guid = winreg.QueryValueEx(k, "DefaultDistribution")[0]
            if want:
                guid = _guid_named(k, want) or guid
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            base + "\\" + guid) as k:
            base_path = winreg.QueryValueEx(k, "BasePath")[0]
            name = winreg.QueryValueEx(k, "DistributionName")[0]
    except OSError:
        return None, None
    # BasePath often carries the \\?\ extended-length prefix.
    if base_path.startswith("\\\\?\\"):
        base_path = base_path[4:]
    vhdx = os.path.join(base_path, "ext4.vhdx")
    return name, vhdx


def vhdx_info():
    """Return ``{distro, path, size, reclaimable}`` for the backing disk.

    ``size`` is the ``.vhdx`` file size on the Windows drive; ``reclaimable``
    is an estimate of what a compact would hand back -- the gap between the
    file's on-disk size and the bytes actually used inside the filesystem.
    Any field is ``None`` when it can't be determined (no Hyper-V/registry).
    """
    name, vhdx = _default_distro_vhdx()
    info = {"distro": name, "path": vhdx, "size": None, "reclaimable": None}
    if not vhdx or not os.path.isfile(vhdx):
        return info
    try:
        info["size"] = os.path.getsize(vhdx)
    except OSError:
        return info
    try:
        used = usage()["used"]
        info["reclaimable"] = max(0, info["size"] - used)
    except Exception:
        pass
    return info


def reclaim(progress=None):
    """Shut WSL down and compact the default distro's ``.vhdx``.

    Returns ``bytes_reclaimed`` (the drop in the ``.vhdx`` file size).  Raises
    :class:`WslDiskError` with a user-facing message on any failure -- the most
    common being "not running as Administrator" (``diskpart``'s ``compact
    vdisk`` needs elevation).  This terminates *all* WSL activity, so the GUI
    must confirm before calling and must not have a pipeline running.

    *progress* is an optional ``callable(message)`` for step narration.
    """
    if not is_supported():
        raise WslDiskError("Reclaim is only available on Windows.")

    from .admin import is_admin
    if not is_admin():
        raise WslDiskError(
            "Reclaiming space compacts the WSL virtual disk, which needs "
            "Administrator rights.\n\nClose the app, right-click it and choose "
            "\"Run as administrator\", then try again. (Cleaning up staging "
            "above does NOT need admin.)")

    name, vhdx = _default_distro_vhdx()
    if not vhdx or not os.path.isfile(vhdx):
        raise WslDiskError(
            "Could not locate the WSL virtual disk (ext4.vhdx). Your distro "
            "may be stored somewhere non-standard; reclaiming isn't available.")

    try:
        before = os.path.getsize(vhdx)
    except OSError as e:
        raise WslDiskError(f"Cannot read the virtual disk: {e}")

    if progress:
        progress("Shutting down WSL…")
    try:
        subprocess.run(["wsl", "--shutdown"], capture_output=True,
                       timeout=120, creationflags=_CREATE_FLAGS)
    except Exception as e:
        raise WslDiskError(f"Could not shut down WSL: {e}")

    # diskpart compacts an attached-read-only vdisk in place.  It's present on
    # every Windows install (unlike the Hyper-V Optimize-VHD cmdlet), and
    # compacting read-only avoids any chance of corrupting the filesystem.
    script = (
        f'select vdisk file="{vhdx}"\n'
        f"attach vdisk readonly\n"
        f"compact vdisk\n"
        f"detach vdisk\n"
    )
    sf = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="ascii") as f:
            f.write(script)
            sf = f.name
        if progress:
            progress("Compacting the virtual disk (this can take a few "
                     "minutes)…")
        proc = subprocess.run(
            ["diskpart", "/s", sf], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800,
            creationflags=_CREATE_FLAGS)
        if proc.returncode != 0:
            out = (proc.stdout or "") + (proc.stderr or "")
            raise WslDiskError(
                "diskpart could not compact the disk:\n" + out.strip())
    finally:
        if sf:
            try:
                os.remove(sf)
            except OSError:
                pass

    try:
        after = os.path.getsize(vhdx)
    except OSError:
        after = before
    return max(0, before - after)


# ---------------------------------------------------------------------------
# Resize the virtual disk (grow OR shrink -- the small-WSL extract wall)
# ---------------------------------------------------------------------------

def host_free_bytes():
    """Free bytes on the Windows drive that backs the WSL ``.vhdx`` (or None).

    Growing the disk can only ever be backed by this drive's free space, so the
    resize UI uses it to cap how large a target it offers.
    """
    _, vhdx = _default_distro_vhdx()
    if not vhdx:
        return None
    try:
        return shutil.disk_usage(os.path.dirname(vhdx)).free
    except OSError:
        return None


def resize_supported():
    """``(ok, message)`` -- whether ``wsl --manage --resize`` is available.

    Added in WSL 2.x; older ``wsl.exe`` builds (or the in-box Windows 10 store
    stub) don't have it, in which case resizing isn't offered.  We probe the
    help text rather than parse a version so it works across builds.
    """
    if not is_supported():
        return False, "Resizing the WSL disk is only available on Windows."
    try:
        proc = subprocess.run(["wsl", "--help"], capture_output=True,
                              timeout=20, creationflags=_CREATE_FLAGS)
    except FileNotFoundError:
        return False, "WSL is not installed."
    except Exception as e:  # noqa: BLE001
        return False, f"WSL is not responding: {e}"
    help_text = _decode_wsl(proc.stdout) + _decode_wsl(proc.stderr)
    if "--resize" in help_text:
        return True, "resize available"
    return False, ("This WSL version can't resize its disk from the app "
                   "(needs WSL 2's `--manage --resize`). Update WSL with "
                   "`wsl --update`, then reopen this window.")


def resize_disk(new_size_bytes, progress=None):
    """Grow or shrink the default distro's virtual disk to *new_size_bytes*.

    Drives ``wsl --manage <distro> --resize``, which resizes the ``.vhdx`` *and*
    its ext4 filesystem in one supported step -- safer than hand-driving
    ``diskpart`` + ``resize2fs``, and (unlike compacting) it does **not** need
    Administrator.  Growing is bounded by the host drive's free space; shrinking
    can only go down to just above the bytes WSL already uses, so we validate
    that up front and raise a clear error rather than let the resize fail
    mid-flight.  Returns the new :func:`usage` dict.
    """
    ok, msg = resize_supported()
    if not ok:
        raise WslDiskError(msg)
    name, _vhdx = _default_distro_vhdx()
    if not name:
        raise WslDiskError("Could not identify the default WSL distro, so "
                           "resizing isn't available.")

    used = usage()["used"]
    new_size_bytes = int(new_size_bytes)
    # Never below what's in use (+1 GiB slack for filesystem metadata).  WSL's
    # own offline resize2fs would refuse anyway, but a pre-check gives a far
    # clearer message than its raw error.
    floor = used + 1024 ** 3
    if new_size_bytes < floor:
        raise WslDiskError(
            "Can't resize to %s -- WSL is already using %s. Choose at least "
            "%s." % (_gib(new_size_bytes), _gib(used), _gib(floor)))

    mb = max(1, new_size_bytes // (1024 ** 2))

    # `wsl --manage --resize` runs an offline `e2fsck` before resizing.  If the
    # ext4 journal wasn't cleanly flushed (a not-uncommon state even right after
    # a `wsl --shutdown`), e2fsck *recovers the journal* and exits non-zero,
    # which `--manage` reports as a generic "Failed to resize disk" / E_FAIL.
    # The recovery is persisted, so a second attempt sees a clean filesystem and
    # succeeds -- the documented "run it twice" behaviour.  So shut WSL down and
    # try up to twice, surfacing the error only if the retry also fails.
    last_out = ""
    for attempt in (1, 2):
        if progress:
            progress("Shutting down WSL…")
        try:
            subprocess.run(["wsl", "--shutdown"], capture_output=True,
                           timeout=120, creationflags=_CREATE_FLAGS)
        except Exception as e:  # noqa: BLE001
            raise WslDiskError(f"Could not shut down WSL: {e}")

        if progress:
            progress("Resizing the virtual disk (this can take a few "
                     "minutes)…" if attempt == 1
                     else "Filesystem journal recovered — retrying the "
                          "resize…")
        try:
            proc = subprocess.run(
                ["wsl", "--manage", name, "--resize", f"{mb}MB"],
                capture_output=True, timeout=1800, creationflags=_CREATE_FLAGS)
        except subprocess.TimeoutExpired as e:
            raise WslDiskError("The resize timed out after 30 minutes.") from e
        if proc.returncode == 0:
            break
        last_out = (_decode_wsl(proc.stdout) + _decode_wsl(proc.stderr)).strip()
    else:
        raise WslDiskError(
            "WSL could not resize the disk:\n"
            + (last_out or "wsl --manage failed twice.")
            + "\n\nClose anything using WSL (terminals, Docker Desktop, "
              "VS Code), then try again.")

    # `--manage --resize` grows the .vhdx, but on some WSL builds it does NOT
    # grow the ext4 filesystem inside to fill the enlarged disk (RTS: resized to
    # 200 GB, `df` still showed 7.58 GiB — the container grew, the filesystem
    # didn't).  Explicitly grow the fs to the device size ourselves: resize2fs
    # online-grows a mounted ext4, needs no Administrator, and is a harmless
    # no-op when the fs already fills the disk (so it's safe after a shrink or
    # on WSL builds that already resized the fs).  `findmnt -n -o SOURCE /` names
    # the root block device unambiguously (unlike lsblk's wslg-trapped
    # MOUNTPOINT); the first _wsl_bash call also restarts the distro we just
    # shut down.
    if progress:
        progress("Growing the Linux filesystem to fill the disk…")
    try:
        dev = _wsl_bash("findmnt -n -o SOURCE /", timeout=60).strip()
        if dev:
            _wsl_bash("resize2fs %s" % dev, timeout=600)
    except WslDiskError as e:
        raise WslDiskError(
            "The virtual disk was resized, but growing the Linux filesystem to "
            "fill it failed:\n" + str(e)) from e

    if progress:
        progress("Verifying new size…")
    return usage()
