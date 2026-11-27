"""What the Select card tab shows once a card is picked: the picture the
machine puts on the glass while it starts up, as a "yes, that one" for the
pick.

* An ordinary Spike 2 card: the game's own loading splash (the backglass
  art the LCD shows while the game starts), read straight off the games
  partition: ``<game>/assets/lcd/GameLogo.png`` on 34 of the 36 shipped
  builds, ``GameLogos/backglass_<le|pro|prem>.png`` (one per edition) on
  Godzilla and King Kong.  A card with neither shows the Stern logo the OS
  partition draws before it (``/usr/local/spike/SternLogo.png``, see
  ``plugins/stern/engine.py``, "The boot screen").  A few directory reads
  and one file, well under 0.1 s even on a 16 GB image.
* A multi-boot card: the boot MENU, drawn by the Multi-boot tab's own
  pipeline - ``mkmulticard.py inspect`` pulls the card's menu media out, the
  selector is built (or found) and one ``--snapshot`` frame is drawn with the
  card's default game highlighted.  That is WSL and qemu and takes seconds,
  so it runs on the tab's worker, and a card it cannot draw (a card in the
  reader, a machine with no rig) falls back to the primary game's splash, saying why.

Nothing here writes to the card.  Results are cached per card file (path,
size, mtime) under the temp folder, so picking the same card again is
instant.
"""

import hashlib
import os
import subprocess
import tempfile

#: The file the machine draws while it boots, preferred over any other
#: picture in the same folder.
BOOT_NAME = "SternLogo.png"

#: How long one tool step of the menu render may take.  The selector build
#: is the slow one on a first run (make, incremental after that).
STEP_TIMEOUT_S = 300


def rig_off():
    """``PAD_UI_NO_RIG`` (the tests, the screen captures): no tool runs, the
    Multi-boot tab's own rule."""
    return os.environ.get("PAD_UI_NO_RIG", "") not in ("", "0")


def cache_root():
    return os.path.join(tempfile.gettempdir(), "pad_card_preview")


#: PAD-1596: a card's folder of previews nobody has looked at for this long
#: goes (a folder was added per card file and change, and none ever went);
#: the space keeper ages them out by the same rule (core/pad_temp.py).
KEEP_DAYS = 7


def prune_cache(keep=(), max_age_days=KEEP_DAYS, now=None):
    """Drop the card folders not used for *max_age_days*, except *keep*
    (the one being shown); :func:`touch` marks a use.  Returns how many
    went.  Never raises."""
    import shutil
    import time
    root = cache_root()
    cutoff = (time.time() if now is None else now) - max_age_days * 86400
    gone = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for name in names:
        if name in keep:
            continue
        p = os.path.join(root, name)
        try:
            newest = os.path.getmtime(p)
            if os.path.isdir(p):
                for f in os.listdir(p):
                    newest = max(newest, os.path.getmtime(os.path.join(p, f)))
        except OSError:
            continue
        if newest < cutoff:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass
            gone += not os.path.lexists(p)
    return gone


def touch(folder):
    """Mark *folder* (a card's previews) as used now."""
    try:
        os.utime(folder, None)
    except OSError:
        pass


def card_key(path):
    """A stable name for *path*'s cache folder, or ``None`` for a raw
    device (the same ``\\\\.\\PHYSICALDRIVE2`` is another card a minute
    later) or a file that is not there."""
    from ..core.rawdevice import is_device_path
    if is_device_path(path):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    # v2: the game's splash joined the Stern logo (a v1 folder holds only
    # the logo, which would hide a splash the card has)
    ident = "v2|%s|%d|%d" % (os.path.normcase(os.path.abspath(path)),
                          st.st_size, st.st_mtime_ns)
    return hashlib.sha256(ident.encode("utf-8")).hexdigest()[:24]


def games_on(path):
    """``[pretty name, ...]`` for every game image on the card, boot-menu
    order; one entry for an ordinary card, ``[]`` for one that is not a
    Spike 2 games card."""
    from ..plugins.stern.multiimage import card_images, pretty
    try:
        return [pretty(img) for img in card_images(path)]
    except Exception:                                   # noqa: BLE001
        return []


#: The splash, in the order it is looked for under ``<game>/assets/lcd``.
SPLASH_FILE = "GameLogo.png"
SPLASH_DIR = "GameLogos"
_EDITION = {"le": "le", "pro": "pro", "prem": "prem", "premium": "prem"}


def _pick_backglass(names, folder):
    """The ``backglass_*.png`` for the edition the game folder names
    (``godzilla_pro`` -> ``backglass_pro.png``), else Premium's, else the
    first; ``None`` when there are none."""
    glass = sorted(n for n in names if n.lower().startswith("backglass_")
                   and n.lower().endswith(".png"))
    if not glass:
        return None
    ed = _EDITION.get(folder.rsplit("_", 1)[-1].lower()) if "_" in folder else None
    for want in (ed, "prem"):
        if want and "backglass_%s.png" % want in [n.lower() for n in glass]:
            return next(n for n in glass if n.lower() == "backglass_%s.png" % want)
    return glass[0]


def _splash_of(reader, img):
    """``(png bytes, card path)`` of the loading splash of the game image *img* in *reader*'s tree, or ``None``."""
    from ..plugins.stern.multiimage import _children
    ino, where = 2, []
    for name in ([img.subdir] if img.subdir else []) + [img.folder, "assets", "lcd"]:
        ino = _children(reader, ino).get(name)
        if ino is None:
            return None
        where.append(name)
    lcd = _children(reader, ino)
    pick = None
    if SPLASH_FILE in lcd:
        pick = (lcd[SPLASH_FILE], where + [SPLASH_FILE])
    elif SPLASH_DIR in lcd:
        sub = _children(reader, lcd[SPLASH_DIR])
        name = _pick_backglass(sub, img.folder)
        if name:
            pick = (sub[name], where + [SPLASH_DIR, name])
    if pick is None:
        return None
    node = reader.read_inode(pick[0])
    return reader.read_file_bytes(node), "/" + "/".join(pick[1])


def all_splash_bytes(path, limit=None):
    """PAD-1632: ``[(png bytes, card path) or None, ...]``, one per game image on the card in boot-menu order (an
    ordinary card has one), at most *limit*; ``[]`` for a card with no game image."""
    from ..plugins.stern import formats
    from ..plugins.stern.ext4 import Ext4Reader
    from ..plugins.stern.multiimage import _images_in
    out = []
    f = formats.open_card(path)
    try:
        for idx, ptype, lba, n in formats.parse_all_partitions_file(f):
            if ptype != 0x83:
                continue
            try:
                reader = Ext4Reader(f, lba * 512, n * 512)
            except Exception:                           # noqa: BLE001
                continue
            for img in _images_in(reader, idx + 1):
                if limit is not None and len(out) >= limit:
                    return out
                try:
                    out.append(_splash_of(reader, img))
                except Exception:                       # noqa: BLE001 - that image just has no picture
                    out.append(None)
        return out
    finally:
        f.close()


def splash_bytes(path):
    """``(png bytes, card path)`` of the primary game's loading splash, or
    ``None`` when its tree has none (see the module docstring)."""
    got = all_splash_bytes(path, limit=1)
    return got[0] if got else None


#: The boot menu's own list on a multi-boot card's system partition
MENU_CONF = ("usr", "local", "codeselect", "images.conf")


def menu_titles(path):
    """PAD-1632: the name the card's boot menu gives each game image, in menu order (``["Godzilla", "Heisei",
    ...]``, from its ``images.conf``); ``[]`` for a card with no boot menu or one that cannot be read.  A few
    directory reads; never raises."""
    try:
        from ..plugins.stern import formats
        from ..plugins.stern.ext4 import Ext4Reader
        from ..plugins.stern.multiimage import _children
        f = formats.open_card(path)
        try:
            for _idx, ptype, lba, n in formats.parse_all_partitions_file(f):
                if ptype != 0x83:
                    continue
                try:
                    reader = Ext4Reader(f, lba * 512, n * 512)
                    ino = 2
                    for name in MENU_CONF:
                        ino = _children(reader, ino).get(name)
                        if ino is None:
                            break
                    if ino is None:
                        continue
                    text = reader.read_file_bytes(reader.read_inode(ino)).decode("utf-8", "replace")
                except Exception:                       # noqa: BLE001 - not this partition
                    continue
                out = []
                for line in text.splitlines():
                    if line.startswith("image="):
                        fields = line[len("image="):].split("|")
                        out.append(fields[1].strip() if len(fields) > 1 else "")
                return out
            return []
        finally:
            f.close()
    except Exception:                                   # noqa: BLE001
        return []


#: PAD-1632: a row of My machines shows its card's games as small pictures: this many at most, this wide
THUMBS_MAX = 3
THUMB_W = 256


def thumbs(path, out_dir=None):
    """PAD-1632: small pictures of the splash of each game image on the card *path* (at most
    :data:`THUMBS_MAX`), for the card's row on My machines: ``[file, ...]``, ``""`` for an image with no splash.
    Kept in the card's preview folder, so a card asked again costs a few ``stat`` calls; ``[]`` for a card that
    cannot be read (a device, a missing file, not a Spike 2 games card).  Never raises."""
    try:
        key = card_key(path)
        if key is None:
            return []
        out_dir = out_dir or os.path.join(cache_root(), key)
        mark = os.path.join(out_dir, "thumbs.txt")
        if os.path.isfile(mark):
            with open(mark, encoding="utf-8") as f:
                names = f.read().split("\n")
            got = [os.path.join(out_dir, n) if n else "" for n in names if n != "."]
            if all(not g or os.path.isfile(g) for g in got):
                touch(out_dir)
                return got
        import io
        from PIL import Image
        os.makedirs(out_dir, exist_ok=True)
        names = []
        for i, one in enumerate(all_splash_bytes(path, limit=THUMBS_MAX)):
            name = ""
            if one is not None:
                try:
                    with Image.open(io.BytesIO(one[0])) as im:
                        im = im.convert("RGB")
                        im.thumbnail((THUMB_W, THUMB_W))
                        name = "thumb%d.jpg" % i
                        im.save(os.path.join(out_dir, name), "JPEG", quality=82)
                except Exception:                       # noqa: BLE001 - a picture PIL cannot read
                    name = ""
            names.append(name)
        with open(mark, "w", encoding="utf-8") as f:
            f.write("\n".join(names) if names else ".")
        return [os.path.join(out_dir, n) if n else "" for n in names]
    except Exception:                                   # noqa: BLE001
        return []


def boot_screen_bytes(path):
    """``(png bytes, card path)`` of the card's boot screen, or ``None``."""
    from ..plugins.stern import engine, formats
    f = formats.open_card(path)
    try:
        parts = [(lba * 512, n * 512) for _i, ptype, lba, n
                 in formats.parse_all_partitions_file(f) if ptype == 0x83]
        reader, node = engine._boot_screen_dir(f, parts)
        if reader is None:
            return None
        imgs = engine._boot_images(reader, node)
        if not imgs:
            return None
        pick = next((e for e in imgs if e[0].endswith("/" + BOOT_NAME)),
                    imgs[0])
        return reader.read_file_bytes(pick[1]), pick[0]
    finally:
        f.close()


def _png_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def splash_png(path, out_dir):
    """``{src, w, h, kind, card_path}`` for the picture the machine shows
    while this card starts, written as a file into *out_dir*: the game's
    splash (``kind`` 'splash'), else the Stern logo (``kind`` 'boot');
    ``None`` when the card has neither."""
    got, kind = None, "splash"
    try:
        got = splash_bytes(path)
    except Exception:                                   # noqa: BLE001
        got = None
    if got is None:
        got, kind = boot_screen_bytes(path), "boot"
    if got is None:
        return None
    data, card_path = got
    os.makedirs(out_dir, exist_ok=True)
    ext = os.path.splitext(card_path)[1].lower() or ".png"
    dst = os.path.join(out_dir, kind + ext)
    with open(dst, "wb") as f:
        f.write(data)
    w, h = _png_size(dst)
    return {"src": dst, "w": w, "h": h, "kind": kind, "card_path": card_path}


class Cancelled(Exception):
    pass


class Runner:
    """Runs tool steps one at a time, and can be told to stop: a newer pick
    kills the step in flight rather than waiting for it."""

    def __init__(self):
        self._proc = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:                           # noqa: BLE001
                pass

    def run(self, label, argv):
        """``stdout+stderr`` text of *argv*; raises ``RuntimeError`` naming
        the step (and its last lines) on a non-zero exit."""
        from . import rig as _rig
        if self.cancelled:
            raise Cancelled()
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                creationflags=_rig.CREATE_FLAGS)
        self._proc = proc
        try:
            out, _ = proc.communicate(timeout=STEP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise RuntimeError("%s took longer than %d s" % (label,
                                                             STEP_TIMEOUT_S))
        finally:
            self._proc = None
        if self.cancelled:
            raise Cancelled()
        text = out.decode("utf-8", "replace")
        if proc.returncode != 0:
            tail = [ln.strip() for ln in text.splitlines() if ln.strip()][-2:]
            raise RuntimeError("%s failed (exit %d)%s" % (
                label, proc.returncode, ": " + " / ".join(tail) if tail else ""))
        return text


def menu_png(path, out_dir, runner):
    """``{src, w, h}`` for the multi-boot card's menu as the machine first
    draws it (the default game highlighted), rendered into *out_dir*.

    The Multi-boot tab's own steps, in its own order (see
    ``MultibootPanel.load_card`` and ``_render_frames``); the card's media
    is drawn as it is, so there is no prepare step."""
    from PIL import Image
    from . import multiboot_core as mt
    media = os.path.join(out_dir, "media")
    conf = os.path.join(out_dir, "images.conf")
    ppm = os.path.join(out_dir, "menu.ppm")
    os.makedirs(media, exist_ok=True)
    text = runner.run("Reading the menu", mt.wsl_command(
        mt.inspect_args(path, media, as_json=True)))
    info = mt.parse_inspect(text)
    if not isinstance(info, dict):
        raise RuntimeError("the card's menu could not be read")
    form, _warnings = mt.form_from_inspect(info, path, media,
                                           mt.DEFAULT_SELECTOR_DIR)
    if len(form.images) < 2:
        raise RuntimeError("the card has no boot menu")
    with open(conf, "w", encoding="utf-8", newline="\n") as f:
        f.write(mt.write_preview_conf(form))
    text = runner.run("Finding the menu program", mt.ensure_selector_args(
        form, card=mt.selector_card(form, path)))
    binary = mt.parse_selector_path(text)
    if not binary:
        raise RuntimeError("the menu program could not be found or built")
    row = min(max(int(form.default), 0), len(form.images) - 1)
    runner.run("Drawing the menu", mt.wsl_command(mt.preview_snapshot_args(
        binary, conf, media, ppm, mt.preview_highlight(form, row), 0,
        mt.rootfs_for(form.selector_dir)), exe=None))
    dst = os.path.join(out_dir, "menu.png")
    with Image.open(ppm) as im:
        im.save(dst)
        w, h = im.size
    try:
        os.remove(ppm)
    except OSError:
        pass
    return {"src": dst, "w": w, "h": h}


def cached(out_dir, name):
    """``{src, w, h}`` for a picture a previous look at this card left in
    *out_dir*, or ``None``."""
    p = os.path.join(out_dir, name)
    if not os.path.isfile(p):
        return None
    try:
        w, h = _png_size(p)
    except Exception:                                   # noqa: BLE001
        return None
    return {"src": p, "w": w, "h": h}

