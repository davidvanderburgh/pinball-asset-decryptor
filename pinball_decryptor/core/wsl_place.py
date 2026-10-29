"""Which Windows drive the app's WSL disks live on, and moving them (PAD-819).

Everything Linux the app keeps is a virtual-disk file on a Windows drive, and
by default every one of them is on C: under ``%LOCALAPPDATA%``:

  * the app's Linux itself - our PAD-Runtime distro (``runtime\\ext4.vhdx``,
    core/runtime.py), or the user's own default distro on a machine without
    it - which grows with every extract and every emulator's unpacked game;
  * the emulators' work disk (``data\\pad-data.vhdx``, core/rigdata.py);
  * the Spike 2 card store (``data\\pad-cards.vhdx``, PAD-651), when made.

Users with a small C: ran out of room ("Can WSL use another drive other than
C?").  WSL can keep a distro anywhere: ``wsl --manage <distro> --move <dir>``
moves its disk and repoints its registry entry, and the two data disks are
plain files the app attaches by path.  So Settings > Manage disk space offers
"Move to another drive": it shuts WSL down (held down meanwhile, as Reclaim
does - :func:`wsl_disk.wsl_paused`), copies the data disks over, moves the
distro, and remembers the new place in ``wsl_place.json`` beside the app's
other machine-local state, so :func:`rigdata.disk_path`,
:func:`rigdata.cards_disk_path` and :func:`runtime.install_dir` (a reinstall of
the runtime) all follow it.  Moving back to C: forgets it again.

The moved tree is ``X:\\pinball_decryptor\\`` with the same layout as the one
under ``%LOCALAPPDATA%`` (``runtime\\``, ``data\\``), and a distro that is not
ours under ``wsl\\<name>\\``.  An environment override (``PAD_RUNTIME_DIR``,
``PAD_DATA_DISK``, ``PAD_CARDS_DISK``) still wins, and a disk it names is
left where it is.
"""

import json
import ntpath
import os
import shutil
import subprocess
import sys
import threading
import time

_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

APP_DIR = "pinball_decryptor"

#: Room the destination must have beyond the disks themselves: a drive filled
#: to the last byte by the move would freeze WSL there instead (PAD-490).
SPARE_BYTES = 5 * 1024 ** 3

#: File systems a WSL disk can live on (WSL refuses FAT/exFAT, and so do the
#: VHDX attaches the data disks use).
DISK_FS = ("NTFS", "REFS")

COPY_CHUNK = 16 * 1024 * 1024


class MoveError(Exception):
    """A user-facing reason the move could not be made (or finished)."""


# ---------------------------------------------------------------------------
# where it is
# ---------------------------------------------------------------------------

def _local_base() -> str:
    return os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")


def default_root() -> str:
    return os.path.join(_local_base(), APP_DIR)


def place_file() -> str:
    """The note of where the disks were moved to.  Always under
    LOCALAPPDATA: it is how the app finds the moved tree, so it cannot be
    in it."""
    override = os.environ.get("PAD_WSL_PLACE")
    if override:
        return override
    return os.path.join(default_root(), "wsl_place.json")


def root() -> str:
    """The folder the app's disks are in: the moved place, or the default."""
    try:
        with open(place_file(), encoding="utf-8") as f:
            saved = (json.load(f) or {}).get("root")
        if isinstance(saved, str) and saved:
            return saved
    except (OSError, ValueError, AttributeError):
        pass
    return default_root()


def data_dir() -> str:
    return os.path.join(root(), "data")


def runtime_dir() -> str:
    return os.path.join(root(), "runtime")


def root_on(drive: str) -> str:
    """Where the tree goes on *drive* (``"D:"``): back under LOCALAPPDATA when
    that is the drive it lives on, else ``D:\\pinball_decryptor``."""
    drive = drive.rstrip("\\/").upper()
    if ntpath.splitdrive(default_root())[0].upper() == drive:
        return default_root()
    return drive + "\\" + APP_DIR


def save_root(path: str) -> None:
    p = place_file()
    if ntpath.normcase(path) == ntpath.normcase(default_root()):
        try:
            os.remove(p)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"root": path}, f, indent=1)
    os.replace(tmp, p)


def drive_of(path) -> str:
    return ntpath.splitdrive(path or "")[0].upper()


# ---------------------------------------------------------------------------
# the drives it can go to
# ---------------------------------------------------------------------------

def _volume(letter):
    """``(label, fs)`` of ``X:``, or None when it cannot be read."""
    import ctypes
    name = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        letter + "\\", name, 261, None, None, None, fs, 261)
    if not ok:
        return None
    return name.value, fs.value


def _fixed_letters():
    import ctypes
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    out = []
    for i in range(26):
        if mask & (1 << i):
            letter = "%s:" % chr(65 + i)
            # 3 = DRIVE_FIXED: internal disks, and USB SSDs/HDDs too (only
            # sticks and card readers say removable - no home for a disk WSL
            # needs at every start).
            if k32.GetDriveTypeW(letter + "\\") == 3:
                out.append(letter)
    return out


def drives(letters=None, volume=None, usage=None):
    """Every fixed drive: ``[{letter, label, fs, free, total, ok, why}]``.
    ``ok`` is False with ``why`` for one a WSL disk cannot live on."""
    if letters is None:
        if sys.platform != "win32":
            return []
        letters = _fixed_letters()
    volume = volume or _volume
    usage = usage or shutil.disk_usage
    out = []
    for letter in letters:
        try:
            vol = volume(letter)
            du = usage(letter + "\\")
        except OSError:
            continue
        if vol is None:
            continue
        label, fs = vol
        d = {"letter": letter, "label": label, "fs": fs,
             "free": du.free, "total": du.total, "ok": True, "why": ""}
        if fs.upper() not in DISK_FS:
            d["ok"], d["why"] = False, "%s: WSL needs NTFS" % fs
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# what there is to move
# ---------------------------------------------------------------------------

def items():
    """What the app keeps on a Windows drive for WSL, each
    ``{key, label, path, size, pinned}``: ``path`` is the disk file;
    ``pinned`` names the environment variable that fixes it in place."""
    from . import rigdata, runtime, wsl_disk
    out = []
    name, vhdx = wsl_disk._default_distro_vhdx()
    if name and vhdx and os.path.isfile(vhdx):
        ours = name == runtime.DISTRO
        out.append({"key": "distro", "distro": name,
                    "label": ("the app's Linux (%s)" % name if ours
                              else "your Linux, %s, that the app uses" % name),
                    "path": vhdx, "size": _size(vhdx),
                    "pinned": ("PAD_RUNTIME_DIR" if ours and os.environ.get(
                        "PAD_RUNTIME_DIR") else "")})
    for key, label, path, env in (
            ("data", "the emulators' data disk", rigdata.disk_path(),
             "PAD_DATA_DISK"),
            ("cards", "the Spike 2 card store", rigdata.cards_disk_path(),
             "PAD_CARDS_DISK")):
        if os.path.isfile(path):
            out.append({"key": key, "label": label, "path": path,
                        "size": _size(path),
                        "pinned": env if os.environ.get(env) else ""})
    return out


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def target_of(item, dest_root):
    """Where *item* goes under *dest_root*: a distro's FOLDER (``--move``
    takes a folder), a data disk's FILE."""
    from . import runtime
    if item["key"] == "distro":
        if item["distro"] == runtime.DISTRO:
            return os.path.join(dest_root, "runtime")
        return os.path.join(dest_root, "wsl", item["distro"])
    return os.path.join(dest_root, "data", ntpath.basename(item["path"]))


def plan(drive, all_items=None, all_drives=None):
    """``(to_move, dest_root, problem)`` for moving everything onto *drive*:
    *problem* is "" when it can go ahead, else what stops it."""
    all_items = items() if all_items is None else all_items
    all_drives = drives() if all_drives is None else all_drives
    drive = drive.rstrip("\\/").upper()
    dest_root = root_on(drive)
    to_move = [i for i in all_items
               if not i["pinned"] and drive_of(i["path"]) != drive]
    d = next((x for x in all_drives if x["letter"].upper() == drive), None)
    if d is None:
        return to_move, dest_root, "%s is not a drive this PC has." % drive
    if not d["ok"]:
        return to_move, dest_root, ("%s can't hold WSL's disks (%s)."
                                    % (drive, d["why"]))
    if not to_move:
        return to_move, dest_root, "Everything is on %s already." % drive
    need = sum(i["size"] for i in to_move) + SPARE_BYTES
    if d["free"] < need:
        return to_move, dest_root, (
            "%s has %s free; the move needs %s (the disks, and 5 GB to "
            "spare)." % (drive, _gb(d["free"]), _gb(need)))
    return to_move, dest_root, ""


def _gb(n):
    return "%.1f GB" % (n / 1024 ** 3)


def move_supported():
    """``(ok, message)``: whether this WSL has ``--manage --move`` (WSL 2.3
    and later; probed from the help text, as resize is)."""
    from . import wsl_disk
    if sys.platform != "win32":
        return False, "Moving WSL is only available on Windows."
    try:
        proc = subprocess.run(["wsl", "--help"], capture_output=True,
                              timeout=20, creationflags=_CREATE_FLAGS)
    except FileNotFoundError:
        return False, "WSL is not installed."
    except Exception as e:                              # noqa: BLE001
        return False, "WSL is not responding: %s" % e
    text = wsl_disk._decode_wsl(proc.stdout) + wsl_disk._decode_wsl(
        proc.stderr)
    if "--move" in text:
        return True, ""
    return False, ("This WSL is too old to move its disk (it needs "
                   "`wsl --manage --move`). Update WSL with `wsl --update`, "
                   "then reopen this window.")


# ---------------------------------------------------------------------------
# moving
# ---------------------------------------------------------------------------

def _copy(src, dst, on_bytes):
    """Copy *src* to *dst* through ``dst.part``, flushed to the drive, then
    renamed: a copy cut short never looks like a disk."""
    part = dst + ".part"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    done = 0
    try:
        with open(src, "rb") as fi, open(part, "wb") as fo:
            while True:
                buf = fi.read(COPY_CHUNK)
                if not buf:
                    break
                fo.write(buf)
                done += len(buf)
                on_bytes(len(buf))
            fo.flush()
            os.fsync(fo.fileno())
        if os.path.getsize(part) != os.path.getsize(src):
            raise MoveError("the copy of %s came out a different size"
                            % ntpath.basename(src))
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return part


def _move_distro(name, dest, size, on_progress, run=None):
    """``wsl --manage <name> --move <dest>``, reporting the copy as the
    new disk file grows."""
    if os.path.exists(dest) and os.listdir(dest):
        raise MoveError("%s is not empty: WSL moves a Linux only into an "
                        "empty folder. Move or delete what is there, then "
                        "try again." % dest)
    os.makedirs(dest, exist_ok=True)
    stop = threading.Event()

    def watch():
        new = os.path.join(dest, "ext4.vhdx")
        while not stop.wait(1.0):
            on_progress(_size(new))

    t = threading.Thread(target=watch, name="pad-wsl-move-watch", daemon=True)
    t.start()
    try:
        proc = (run or subprocess.run)(
            ["wsl", "--manage", name, "--move", dest], capture_output=True,
            timeout=12 * 3600, creationflags=_CREATE_FLAGS)
    finally:
        stop.set()
        t.join(5)
    if proc.returncode != 0:
        from . import wsl_disk
        said = (wsl_disk._decode_wsl(proc.stdout)
                + wsl_disk._decode_wsl(proc.stderr)).strip()
        raise MoveError("WSL could not move %s:\n%s"
                        % (name, said or "exit %d" % proc.returncode))
    on_progress(size)


def move(drive, progress=None, *, all_items=None, all_drives=None,
         hold=None, free_disk=None, run=None):
    """Move every disk of the app's onto *drive*.  Returns ``[(label,
    new_path)]``.  Raises :class:`MoveError` with what was done and what was
    not.

    WSL is shut down and held down for the whole move (*hold*, *free_disk*:
    :func:`wsl_disk.wsl_paused` and its wait for a disk file to be let go).
    The data disks go first, all copied before any is switched to, then the
    place is saved and the old files deleted; the distro last, by WSL itself,
    which repoints its own registry entry.  So whatever fails, every disk is
    whole in exactly one place the app looks."""
    from . import wsl_disk
    say = progress or (lambda _m: None)
    to_move, dest_root, problem = plan(drive, all_items, all_drives)
    if problem:
        raise MoveError(problem)
    hold = hold or wsl_disk.wsl_paused
    free_disk = free_disk or wsl_disk._shutdown_until_free
    total = sum(i["size"] for i in to_move) or 1
    moved_bytes = [0]
    last = [0.0]

    def report(what, extra=0, force=False):
        now = time.monotonic()
        if force or now - last[0] >= 1.0:
            last[0] = now
            pct = min(100, int(100 * (moved_bytes[0] + extra) / total))
            say("Moving %s to %s… %d%%" % (what, drive.upper(), pct))

    done = []
    files = [i for i in to_move if i["key"] != "distro"]
    distro = next((i for i in to_move if i["key"] == "distro"), None)
    with hold():
        for i in to_move:
            free_disk(i["path"], say)
        if files:
            parts = []
            try:
                for i in files:
                    dst = target_of(i, dest_root)
                    if os.path.exists(dst):
                        raise MoveError(
                            "%s is there already. Move or delete it, then "
                            "try again." % dst)

                    def on_bytes(n, _i=i):
                        moved_bytes[0] += n
                        report(_i["label"])
                    parts.append((i, _copy(i["path"], dst, on_bytes), dst))
            except BaseException:
                for _i, part, _dst in parts:
                    try:
                        os.remove(part)
                    except OSError:
                        pass
                raise
            for i, part, dst in parts:
                os.replace(part, dst)
            save_root(dest_root)
            for i, _part, dst in parts:
                try:
                    os.remove(i["path"])
                except OSError:
                    pass
                done.append((i["label"], dst))
        if distro:
            dest = target_of(distro, dest_root)
            base = moved_bytes[0]
            report(distro["label"], force=True)
            try:
                # WSL keeps a registered distro's disk open until it shuts
                # down, even a stopped one (measured, WSL 2.6), and something
                # outside the app may start it again meanwhile: shut it down
                # and try again, as Reclaim does (PAD-739)
                for attempt in (1, 2, 3):
                    try:
                        _move_distro(distro["distro"], dest, distro["size"],
                                     lambda n: report(distro["label"],
                                                      min(n, distro["size"])),
                                     run=run)
                        break
                    except MoveError as e:
                        if "SHARING_VIOLATION" not in str(e):
                            raise
                        if attempt == 3:
                            raise MoveError(wsl_disk._IN_USE_HELP.replace(
                                "try Reclaim again", "try the move again")
                                + "\n\n" + str(e))
                        free_disk(distro["path"], say)
            except MoveError as e:
                if done:
                    raise MoveError(
                        "%s\n\nMoved: %s. They work from there; %s stayed "
                        "where it was." % (e, ", ".join(l for l, _ in done),
                                            distro["label"]))
                raise
            moved_bytes[0] = base + distro["size"]
            report(distro["label"], force=True)
            done.append((distro["label"], dest))
        # what the app makes later (a data disk on a rig's first run, the
        # runtime on a reinstall) goes where the user asked too
        save_root(dest_root)
    from . import runtime
    runtime.invalidate()
    return done
