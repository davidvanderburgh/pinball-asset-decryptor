"""Image-slot scanning + replacement staging for the 'Replace Image' GUI tab.

A *slot* is an image file (.png / .jpg / .bmp / …) that already exists in an
extracted assets folder.  The GUI lists every slot with its original name,
dimensions + format and a thumbnail, lets the user assign a replacement image
of *any* format, then this module *stages* those assignments: each replacement
is scaled to the slot's pixel dimensions and saved in the slot's format, written
over the original file in the assets folder.

Because the staged file lands at the original's exact path + name, the existing
per-manufacturer Write pipeline picks it up as a changed asset and repacks it.
This mirrors :mod:`core.audio_slots` / :mod:`core.video_slots`; the image
equivalent always needs Pillow (matching dimensions / format is a re-encode).
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from .audio_slots import replace_with_retry
from .checksums import NON_ASSET_DIRS, is_other_extract
from .image import (IMAGE_EXTS, ImageInfo, detect_image_info, pil_available,
                    transcode_image_to)
from .video_slots import StagedCache as _StagedCache


@dataclass
class ImageSlot:
    """One replaceable image file found in an extracted assets folder."""
    rel_path: str                  # forward-slash path relative to assets_dir
    abs_path: str
    ext: str                       # ".png" / ".jpg" / …
    info: Optional[ImageInfo]      # None if not yet probed / Pillow failed
    size: int
    probed: bool = False           # True once Pillow has been attempted

    @property
    def folder(self) -> str:
        """Parent folder of the slot (\"\" for files at the assets root)."""
        return os.path.dirname(self.rel_path)

    def resolution_str(self) -> str:
        if self.info and self.info.width and self.info.height:
            return f"{self.info.width}×{self.info.height}"
        return "—"

    def format_summary(self) -> str:
        """One-line, human-readable format string for the slot list."""
        base = self.ext.lstrip(".").upper()
        if self.info is None:
            return base
        parts = [self.info.fmt or base]
        if self.info.has_alpha:
            parts.append("alpha")
        return " ".join(parts)


def scan_image_slots(assets_dir: str, roots=None, exts=None,
                     probe: bool = True) -> List[ImageSlot]:
    """Walk *assets_dir* and return an ImageSlot for every image file, sorted
    by relative path.  Hidden dot-folders and our own ``*.stage.*`` temp files
    are skipped.

    *roots* optionally restricts the walk to specific subdirectories (still
    reporting paths relative to *assets_dir*).  ``None`` scans the whole tree.
    *exts* optionally narrows which extensions count as slots (default
    :data:`core.image.IMAGE_EXTS`).  *probe* controls whether Pillow metadata
    (dimensions / format) is read during the walk; the GUI passes ``False`` to
    list slots instantly and fills metadata in afterwards on a background pass.
    """
    slots: List[ImageSlot] = []
    if not assets_dir or not os.path.isdir(assets_dir):
        return slots

    allowed = tuple(e.lower() for e in exts) if exts else IMAGE_EXTS
    walk_roots = [r for r in (roots or [assets_dir]) if os.path.isdir(r)]
    seen = set()
    for walk_root in walk_roots:
        for root, dirs, files in os.walk(walk_root):
            # Same prune as audio_slots: dot-dirs + the project's top-level
            # generated / staged folders (checksums.NON_ASSET_DIRS).
            dirs[:] = [d for d in dirs
                       if not d.startswith(".")
                       and not is_other_extract(os.path.join(root, d))
                       and not (d in NON_ASSET_DIRS
                                and os.path.normcase(os.path.normpath(root))
                                == os.path.normcase(
                                    os.path.normpath(assets_dir)))]
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                # Dot-files are our sidecars (.blank.png, the transparent
                # group-blank source), never slots.
                if ext not in allowed or ".stage." in fn or fn.startswith("."):
                    continue
                abs_path = os.path.join(root, fn)
                if abs_path in seen:
                    continue
                seen.add(abs_path)
                info = detect_image_info(abs_path) if probe else None
                rel = os.path.relpath(abs_path, assets_dir).replace(os.sep, "/")
                try:
                    size = os.path.getsize(abs_path)
                except OSError:
                    size = 0
                slots.append(ImageSlot(
                    rel_path=rel, abs_path=abs_path, ext=ext,
                    info=info, size=size, probed=probe))

    slots.sort(key=lambda s: s.rel_path.lower())
    return slots


def stage_replacement(slot: ImageSlot, replacement_path: str,
                      keep_size: bool = False,
                      original_info: Optional[ImageInfo] = None,
                      colour=None):
    """Stage a single replacement over *slot*.

    The replacement is scaled to the slot's pixel dimensions (unless
    *keep_size*), saved in the slot's format, and written atomically over
    ``slot.abs_path``.  *original_info* describes the slot's PRISTINE file
    when the caller has it (the slot's own file may already hold an earlier
    replacement).  Returns ``(ok, detail)`` — on success *detail*
    summarises the conversions (may be empty); on failure it's an error
    message.

    A conversion that comes out byte for byte the file already in the slot
    leaves that file as it is, its modification time included (PAD-509: a
    picture staged again the same way on every Emulate Start moved the
    project's "have the edits changed?" fingerprint, and the emulator's
    whole override set was rebuilt for nothing).
    """
    if not os.path.isfile(replacement_path):
        return False, "replacement file not found"
    if not pil_available():
        return False, "need Pillow to convert images"

    tmp = slot.abs_path + ".stage" + slot.ext
    try:
        info = (original_info or slot.info
                or detect_image_info(slot.abs_path))
        ok, detail = transcode_image_to(replacement_path, tmp, info,
                                        keep_size=keep_size, colour=colour)
        if ok and keep_size:
            detail = ", ".join(d for d in (detail, "own size kept") if d)
        if not ok:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return False, detail
        import filecmp
        if os.path.isfile(slot.abs_path) and filecmp.cmp(
                tmp, slot.abs_path, shallow=False):
            os.remove(tmp)
        else:
            replace_with_retry(tmp, slot.abs_path)
        return True, detail
    except (OSError, ValueError) as e:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False, str(e)


#: Where :func:`stage_replacements` remembers what it last staged into each
#: picture slot (see :class:`PictureCache`).
PICTURE_CACHE = os.path.join(".write_cache", "image_staged.json")

#: Part of every picture recipe: bump it whenever what a conversion produces
#: changes in a way the converter's own source does not show.
CONVERSION_REV = 1

_CONVERTER_KEYS = {}


def _converter_key(coloured):
    """What converts a picture, for :class:`PictureCache`: :data:`CONVERSION_REV`
    and the source of the converter (``core/image.py``, and ``core/
    colour_profile.py`` for a picture under a color profile).

    PAD-863 (DragonRR): the recipe held the app's version, so every update
    converted every staged picture again on the next Start - his one large
    picture 20 s after each of the near-daily releases, all 5,811 of
    Godzilla's when they are under a profile - although nearly no release
    changes how a picture converts.  Like the card's picture cache
    (``engine._picture_cache_recipe``), the app's version stands in only
    when the source cannot be read."""
    key = _CONVERTER_KEYS.get(coloured)
    if key is None:
        import hashlib
        from . import colour_profile, image
        h = hashlib.sha1(str(CONVERSION_REV).encode())
        try:
            for mod in (image, colour_profile) if coloured else (image,):
                with open(mod.__file__, "rb") as f:
                    h.update(f.read())
            key = h.hexdigest()[:16]
        except (OSError, TypeError):
            from .. import __version__
            key = "app-" + __version__
        _CONVERTER_KEYS[coloured] = key
    return key


class PictureCache(_StagedCache):
    """What each picture slot was last staged from, so a Start (or a Write)
    that changes nothing about a picture does not convert it again - the
    pictures' half of :class:`core.video_slots.StagedCache`.

    PAD-505 (DragonRR, after the conversion stopped locking the app up:
    "when I run emulate it is still hanging staging files"): every Emulate
    Start converted all of Godzilla's 5,811 pictures again, the same way, for
    minutes on a busy PC.  A recipe is the source (its path, size and
    modification time; for the game's own picture that is its ``.orig/``
    snapshot), the pristine snapshot the size is fitted to, Keep size, the
    color profile and the converter (:func:`_converter_key`: a new one
    converts once more, in case it converts differently); the slot's file
    afterwards has to be the one that staging left."""

    FILE = PICTURE_CACHE

    @staticmethod
    def recipe(rep, orig=None, keep_size=False, colour=None):
        import hashlib
        import json
        try:
            st = os.stat(rep)
        except (OSError, TypeError):
            return None
        shape = None
        if orig:
            try:
                ost = os.stat(orig)
                shape = [ost.st_size, ost.st_mtime_ns]
            except OSError:
                shape = None
        blob = json.dumps([_converter_key(colour is not None),
                           os.path.normcase(os.path.abspath(rep)),
                           st.st_size, st.st_mtime_ns, shape, bool(keep_size),
                           colour.key() if colour is not None else None])
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    def kept(self, assets_dir, slot, rep, keep_size, colour):
        """Is *slot* already what staging *rep* into it would make?  Only a
        slot with its ``.orig/`` snapshot (staged before) can be."""
        from . import staged_originals
        snap = staged_originals.snapshot_path(assets_dir, slot.rel_path)
        if not snap:
            return False
        return self.fresh(slot, self.recipe(rep or snap, snap, keep_size,
                                            colour))


def pictures_due(slots_by_rel: Dict[str, ImageSlot],
                 assignments: Dict[str, str], assets_dir=None,
                 keep_size=frozenset()):
    """How many pictures :func:`stage_replacements` would stage if it ran
    now with the same arguments (PAD-489): the picks, the game's own
    pictures switched on behind the unlock, and the built pictures switched
    on, less the ones an earlier staging left as this one would make them
    (:class:`PictureCache`).  Counted without touching a file (the staging
    itself sets aside a built picture's uncorrected copy)."""
    from . import colour_profile
    colour = colour_profile.active(assets_dir) if assets_dir else None
    picked = {rel for rel, rep in assignments.items()
              if rep and rel in slots_by_rel}
    cache = PictureCache(assets_dir) if assets_dir else None
    chosen = ({} if colour is not None or not assets_dir
              else colour_profile.asset_map(assets_dir, "images",
                                            sorted(picked)))

    def kept(rel, rep):
        return cache is not None and cache.kept(
            assets_dir, slots_by_rel[rel], rep, rel in keep_size,
            colour or chosen.get(rel))

    n = sum(1 for rel in picked if not kept(rel, assignments[rel]))
    if colour is None and assets_dir:
        stock, profs = _stock_to_stage(assets_dir, slots_by_rel, picked)
        chosen.update(profs)
        n += sum(1 for rel in stock if not kept(rel, None))
        resolve = colour_profile.asset_resolver(assets_dir)
        for rel in colour_profile.built_image_on(assets_dir):
            if rel not in slots_by_rel or rel in picked or rel in stock:
                continue
            if resolve("images", rel) is None:
                # No change: back to its kept uncorrected copy (PAD-528)
                n += bool(colour_profile.uncorrected_path(assets_dir, rel))
            elif (colour_profile.uncorrected_path(assets_dir, rel)
                  or os.path.isfile(slots_by_rel[rel].abs_path)):
                n += 1
    return n


def _stock_to_stage(assets_dir, slots_by_rel, picked):
    """The game's own pictures switched on behind the unlock that a staging
    stages, and the profile each gets baked in: ``(rels, {rel: Profile})``.

    One whose profile changes nothing (No change) is staged too where an
    earlier build changed it (it has its ``.orig/`` snapshot): from those
    pristine bytes, so it goes back to the game's own colors.  DragonRR,
    PAD-528: after every picture had been built Black and white, No change
    on all of them left them Black and white, because a staging with no
    profile that changes something skipped the game's pictures altogether."""
    from . import colour_profile, staged_originals
    stock = {rel for rel in colour_profile.stock_image_rels(assets_dir, picked)
             if rel in slots_by_rel}
    profs = colour_profile.asset_map(assets_dir, "images", sorted(stock))
    return ({rel for rel in stock if rel in profs
             or staged_originals.has_snapshot(assets_dir, rel)}, profs)


def picture_workers(pictures: int) -> int:
    """How many pictures :func:`stage_replacements` converts at once: half
    the computer's cores, at most eight.  ``PAD_STAGE_WORKERS`` overrides
    it (1 = one at a time, as before PAD-599)."""
    try:
        n = int(os.environ.get("PAD_STAGE_WORKERS", "") or 0)
    except ValueError:
        n = 0
    if n <= 0:
        n = min(8, max(1, (os.cpu_count() or 1) // 2))
    return max(1, min(n, pictures))


def stage_replacements(slots_by_rel: Dict[str, ImageSlot],
                       assignments: Dict[str, str],
                       log_cb=None, progress_cb=None, assets_dir=None,
                       keep_size=frozenset(), cancel_cb=None):
    """Stage every assignment in *assignments* (rel_path -> replacement path).

    *slots_by_rel* maps the same rel_path keys to their ImageSlot.  Returns
    ``(staged, failures)`` where *failures* is a list of ``(rel_path, error)``.
    Rel paths in *keep_size* are staged at the replacement's own dimensions.

    *assets_dir*, when given, snapshots each slot's pristine bytes under
    ``.orig/`` before the first overwrite so the edit can be reverted without a
    full re-extract (see :mod:`core.staged_originals`).

    *cancel_cb* (returns truthy to stop) is asked before each picture: a
    whole game's pictures under a colour profile are thousands (PAD-489).
    """
    from .checksums import read_baseline_any

    from . import colour_profile
    # the project's colour profile (PAD-305), read once for the whole pass
    colour = colour_profile.active(assets_dir) if assets_dir else None
    items = [(rel, rep) for rel, rep in assignments.items()
             if rep and rel in slots_by_rel]
    # The chosen-files profile (PAD-312), baked into the pictures switched
    # on; where the display-wide profile corrects the files itself (not
    # Spike 2, *colour* set) it wins, so a picture is never corrected twice.
    chosen = ({} if colour is not None
              else colour_profile.asset_map(assets_dir, "images",
                                            [rel for rel, _r in items]))
    # The game's own pictures switched on behind the Images tab's advanced
    # unlock (PAD-335): staged from their pristine bytes (the .orig/
    # snapshot, so a second build never corrects twice), profile baked in.
    # a picture picked again: a copy kept from its earlier build is stale
    for rel, _r in items:
        colour_profile.discard_uncorrected(assets_dir, rel)
    if colour is None and assets_dir:
        # (PAD-528: No change too, where an earlier build changed them)
        stock, profs = _stock_to_stage(assets_dir, slots_by_rel,
                                       {rel for rel, _r in items})
        chosen.update(profs)
        items += [(rel, None) for rel in sorted(stock)]
        # The user's own pictures an earlier build put here, pick gone
        # (PAD-345): corrected from their kept uncorrected copy, never from
        # .orig/ (Stern's picture), so a second build never corrects twice.
        resolve = colour_profile.asset_resolver(assets_dir)
        for rel in colour_profile.built_image_on(assets_dir):
            if rel not in slots_by_rel or rel in dict(items):
                continue
            # its own profile (PAD-368), else the project's
            prof = resolve("images", rel)
            if prof is None:
                # No change: its kept uncorrected copy goes back (PAD-528)
                kept = colour_profile.uncorrected_path(assets_dir, rel)
            else:
                kept = colour_profile.keep_uncorrected(assets_dir, rel)
            if kept:
                if prof is not None:
                    chosen[rel] = prof
                items.append((rel, kept))
                # already the size the build made it: never fitted again
                keep_size = frozenset(keep_size) | {rel}
    # PAD-505: what an earlier staging left just as this one would make it
    cache = PictureCache(assets_dir) if assets_dir else None
    n_kept = 0
    if cache is not None:
        todo = []
        for rel, rep in items:
            if cache.kept(assets_dir, slots_by_rel[rel], rep, rel in keep_size,
                          colour or chosen.get(rel)):
                n_kept += 1
            else:
                todo.append((rel, rep))
        items = todo
        if n_kept and log_cb:
            log_cb("{:,} picture(s) left as they are: an earlier build "
                   "converted them just as this one would.".format(n_kept),
                   "info")
    total = len(items)
    staged = n_kept
    failures: List = []
    baseline = read_baseline_any(assets_dir) if assets_dir else {}
    try:
        staged += _stage_items(items, slots_by_rel, baseline, failures, cache,
                               colour, chosen, log_cb, progress_cb,
                               assets_dir, keep_size, cancel_cb)
    finally:
        if cache is not None:
            cache.save()
    if progress_cb:
        progress_cb(total, total, "")
    return staged, failures


def _stage_items(items, slots_by_rel, baseline, failures, cache, colour,
                 chosen, log_cb, progress_cb, assets_dir, keep_size,
                 cancel_cb):
    """:func:`stage_replacements`' loop over the pictures it converts;
    returns how many it staged, *failures* gets the rest."""
    from . import staged_originals
    total = len(items)
    staged = 0

    def _one(rel, rep):
        """Stage one picture: ``(ok, detail, lines)``."""
        slot = slots_by_rel[rel]
        lines = [(f"Staging {rel}  ←  "
                  + (os.path.basename(rep) if rep else
                     "its own picture, colors corrected for the machine"
                     if colour or chosen.get(rel) else
                     "its own picture, its own colors (No change)"),
                  "info")]
        original = snap = None
        if assets_dir:
            staged_originals.snapshot(assets_dir, rel, baseline.get(rel))
            # Fitted to the PRISTINE picture's size, which slot.info is only
            # while the slot is untouched.  Once an earlier replacement was
            # kept at its own size (PAD-154), the slot's file is that size,
            # and every later pick - Keep size off included - was fitted to
            # it, so unticking the box never took (PAD-179).  Video staging
            # budgets against the snapshot for the same reason.
            snap = staged_originals.snapshot_path(assets_dir, rel)
            if snap:
                original = detect_image_info(snap)
            if rep is None:
                rep = snap or slot.abs_path
        ok, detail = stage_replacement(slot, rep, keep_size=rel in keep_size,
                                       original_info=original,
                                       colour=colour or chosen.get(rel))
        if ok:
            if cache is not None:
                cache.record(slot, cache.recipe(rep, snap, rel in keep_size,
                                                colour or chosen.get(rel)))
            lines.append((f"  ✓ {rel}" + (f"  ({detail})" if detail else ""),
                          "success"))
        else:
            if cache is not None:
                cache.forget(rel)
            lines.append((f"  ✗ {rel}: {detail}", "error"))
        return ok, detail, lines

    # Pillow does its decoding, scaling and PNG packing outside Python's
    # lock, so several pictures convert at once (PAD-599: a retheme's 2,331
    # took 101 s one at a time).  At most a few run ahead of the one being
    # reported, so a Cancel still stops within a picture or two.
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor
    workers = picture_workers(total)
    pool = (ThreadPoolExecutor(max_workers=workers,
                               thread_name_prefix="pad-stage-image")
            if workers > 1 else None)
    queued = deque()
    todo = iter(enumerate(items))
    try:
        while True:
            while len(queued) < (workers * 2 if pool is not None else 1):
                nxt = next(todo, None)
                if nxt is None:
                    break
                if cancel_cb is not None and cancel_cb():
                    todo = iter(())
                    if log_cb:
                        log_cb("Canceled — skipping the remaining image "
                               "replacement(s).", "error")
                    break
                i, (rel, rep) = nxt
                queued.append((i, rel, pool.submit(_one, rel, rep)
                               if pool is not None else None, rep))
            if not queued:
                break
            i, rel, fut, rep = queued.popleft()
            if progress_cb:
                progress_cb(i, total, rel)
            try:
                ok, detail, lines = (fut.result() if fut is not None
                                     else _one(rel, rep))
            except Exception as e:                      # noqa: BLE001
                ok, detail, lines = False, str(e), [(f"  ✗ {rel}: {e}",
                                                     "error")]
            if log_cb:
                for text, level in lines:
                    log_cb(text, level)
            if ok:
                staged += 1
            else:
                failures.append((rel, detail))
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
    return staged
