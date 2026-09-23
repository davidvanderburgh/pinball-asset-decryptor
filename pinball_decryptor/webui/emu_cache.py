"""The Spike 2 emulator's card cache, as the disk-space window lists it.

``scan_emu_cache`` / ``drop_emu_cache`` and their rig lookup, moved unchanged
out of the Tk disk dialog (``gui/disk_dialog.py``) at the web UI cut-over;
the web disk-space window (``webui/shellx_disk.py``) calls them.  Tk-free.
"""

import subprocess
import sys
import time

_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# ----------------------------------------------------------------------
# Spike 2 emulator card cache (David, 2026-09-11: "the manage disk space
# window should also have the emulator cache items shown")
#
# The cache is the biggest thing this app puts on disk by a distance -- one
# card is 7 GB and the rig keeps several -- and until now it was reachable
# ONLY from the emulator tab's own Card cache window, so the dialog whose
# whole job is "where did my disk go" answered without it.
#
# It is a THIRD location, not a third flavour of the two that already exist:
# it lives on the emulator's own work disk, which is neither the default
# distro's .vhdx that the WSL bar reports nor the Windows temp drive.  So it
# gets its own usage bar, its own group, and its own delete path, and the
# freed bytes are folded back into its own bar rather than either other one.
#
# It is also NOT leftover staging.  Nothing crashed to put it there; it is a
# deliberate cache, and deleting it costs a 7 GB re-copy on the next boot
# rather than nothing.  Every label in this file says so, and the confirm
# says it again with the size, because "Clean all" reaches it too.
# ----------------------------------------------------------------------
def _emu_rig():
    """Import the emulator's rig helpers, or ``None`` if unavailable.

    Deferred and inside a try: the disk-space window is opened by users who
    may have no emulator, no WSL and no rig, and a missing card cache must
    cost them a greyed-out row rather than a traceback.
    """
    try:
        from .emulate_core import parse_cache_list, rig_cmd
        return rig_cmd, parse_cache_list
    except Exception:                                        # noqa: BLE001
        return None


def scan_emu_cache():
    """``(entries, usage)`` for the emulator card cache; ``([], None)`` if none.

    Entries are shaped like the other two scanners' (``path`` / ``size`` /
    ``manufacturer`` / ``detail``) so the tree does not need to know which
    scanner produced a row.  ``path`` carries the cache LABEL, which is what
    ``cardmount.sh --cache-drop`` takes -- the rig addresses a cached card by
    label, not by filesystem path, and that is the identity the delete needs.
    """
    rig = _emu_rig()
    if not rig:
        return [], None
    rig_cmd, parse_cache_list = rig
    try:
        out = subprocess.run(rig_cmd("cardmount.sh", "--cache-list"),
                             stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL,
                             timeout=30, creationflags=_CREATE_FLAGS)
        text = out.stdout.decode("utf-8", "replace")
    except Exception:                                        # noqa: BLE001
        return [], None

    rows, disk = parse_cache_list(text)
    entries = []
    for r in rows:
        detail = r["label"]
        if r.get("boot"):
            detail += "   last booted %s" % time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(r["boot"]))
        else:
            detail += "   never booted"
        entries.append({"path": r["label"],
                        "size": r["real_kb"] * 1024,
                        "manufacturer": "Stern Spike 2",
                        "detail": detail})

    usage = None
    if disk:
        avail_kb, size_kb = disk
        total = size_kb * 1024
        free = avail_kb * 1024
        used = max(0, total - free)
        usage = {"total": total, "free": free, "used": used,
                 "pct": int(round(used * 100.0 / total)) if total else 0}
    return entries, usage


def drop_emu_cache(labels, sizes):
    """Drop cached cards by label; return the bytes actually freed.

    *sizes* is ``{label: bytes}`` from the scan the caller is already
    holding, so this costs ONE extra rig round trip rather than three --
    each is a ``wsl.exe`` hop that can take seconds.

    Each drop is independent, so one failure must not strand the rest: the
    loop keeps going, and the total counts only the labels a re-read
    confirms are gone.  A drop that silently did nothing therefore reports
    zero freed instead of a number the disk will contradict.
    """
    rig = _emu_rig()
    if not rig or not labels:
        return 0
    rig_cmd, _ = rig
    for label in labels:
        try:
            subprocess.run(rig_cmd("cardmount.sh", "--cache-drop", label),
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           timeout=60, creationflags=_CREATE_FLAGS)
        except Exception:                                    # noqa: BLE001
            continue
    still = {e["path"] for e in scan_emu_cache()[0]}
    return sum(sz for lbl, sz in (sizes or {}).items()
               if lbl in labels and lbl not in still)
