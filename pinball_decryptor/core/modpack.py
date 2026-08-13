"""Mod-pack export/import — zip the files that differ from the baseline.

Manufacturer-agnostic: only relies on ``.checksums.md5`` written by the
shared :mod:`core.checksums` module.
"""

import json
import os
import zipfile

from . import hashcache
from . import staged_originals
from .checksums import CHECKSUMS_FILE, TRACKING_SIDECARS, read_baseline_any
from .extract_source import read_extract_source, version_hint_from_name

# Manifest written into every pack, naming the extract it was built from so
# Import can say what it's applying (and warn on an obvious mismatch).  The
# help text has always promised this; nothing wrote it until batch 16.
MANIFEST_NAME = ".modpack.json"

# Staged-changes keys a pack carries as VALUES rather than files: the Defaults
# tab's edits and the image/scene names.  They live in the folder's
# ``.staged_changes.json`` sidecar, which is not a baselined file, so the
# file diff could never see them — a tester imported his pack into a fresh
# extract and found every default back at stock and every scene un-named
# (batch 31).  ``settings`` / ``high_scores`` / ``image_group_tags`` are all
# keyed by something card-independent (the firmware's ``AD_`` name, the high
# score slot label, the scene's own container id), so they carry across a
# re-extract of the same card the same way they carry across a version.
_EXTRA_MAPS = ("settings", "high_scores", "image_group_tags")
_EXTRA_SCALARS = ("menu_expose_through",)


def _is_packable(rel):
    """False for baseline entries that are pipeline scratch, not card assets.

    ``fl_decrypted.dat`` (JJP's decrypted blob) and any ``.img`` are written
    at extract time — so they ARE in the baseline — and get rewritten by later
    steps, which made them read as "modified" and land in the pack.  They are
    hundreds of MB and useless to the recipient, and they are exactly why an
    audio-only mod pack could weigh 350 MB (feedback batch 16).  The Write
    tab's Modified-Files preview already hides them for the same reason.
    """
    name = os.path.basename(rel)
    return not (name.startswith(".")
                or name == "fl_decrypted.dat"
                or name.lower().endswith(".img")
                or name in TRACKING_SIDECARS)


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


# Extension → kind buckets for the import/export summaries.  The extracted
# forms only (what actually sits in a project folder), pulled from the same
# constants the Replace tabs scan with, so the buckets can't drift from what
# the app itself calls audio/video/images.
def _kind_of(name):
    from .audio_slots import AUDIO_EXTS
    from .image import IMAGE_EXTS
    from .video import VIDEO_EXTS
    ext = os.path.splitext(name)[1].lower()
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS or ext == ".dds":
        return "image"
    return "other"


def kind_summary(names):
    """A human breakdown of *names* by asset kind — "2 audio, 1 video,
    2 images" — so the import log says WHAT a pack changed, not just how
    many files (a tester).  Empty string for an empty list; a bucket with
    no files is left out."""
    counts = {}
    for name in names:
        kind = _kind_of(name)
        counts[kind] = counts.get(kind, 0) + 1
    parts = []
    for kind, label in (("audio", "audio"), ("video", "video"),
                        ("image", "image(s)"), ("other", "other")):
        if counts.get(kind):
            parts.append("%d %s" % (counts[kind], label))
    return ", ".join(parts)


def project_extras(assets_folder):
    """The non-file edits a pack should carry out of *assets_folder*.

    Read straight from the folder's ``.staged_changes.json`` (see
    :data:`_EXTRA_MAPS`), so no GUI state is involved and an export from a
    freshly-opened app carries the same thing as one mid-session.  ``{}`` when
    the folder has none of them.
    """
    from . import staged_changes
    data = staged_changes.load(assets_folder)
    extras = {}
    for key in _EXTRA_MAPS:
        val = data.get(key)
        if isinstance(val, dict) and val:
            extras[key] = {str(k): v for k, v in val.items()}
    for key in _EXTRA_SCALARS:
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            extras[key] = val
    return extras


def card_replacements(assets_folder):
    """The Partitions-tab replaces recorded against *assets_folder*'s own card
    image, as ``[{partition, path, source, when}]`` (newest edit per path).

    A pack CANNOT carry these: the Partitions tab writes straight into the card
    image, which is not part of the project folder the pack is a diff of.  They
    are listed in the manifest anyway so Import can name the files to redo
    rather than leave the user to notice a stock logo on a finished build (a
    tester lost the same ``SternLogo.png`` swap twice).
    """
    from . import card_edits
    rec = read_extract_source(assets_folder) or {}
    image = rec.get("input_path") or ""
    if not image:
        return []
    out = []
    for path, e in sorted(card_edits.replaced(image).items()):
        out.append({"partition": e.get("partition"),
                    "path": path,
                    "source": e.get("source") or "",
                    "when": e.get("when") or ""})
    return out


def describe_card_files(card_files, limit=4):
    """A human phrase naming *card_files* (from :func:`card_replacements`)."""
    paths = [c.get("path") for c in (card_files or []) if c.get("path")]
    if not paths:
        return ""
    shown = ", ".join(paths[:limit])
    if len(paths) > limit:
        shown += ", and %d more" % (len(paths) - limit)
    return shown


def export_mod_pack(assets_folder, zip_path, log_cb=None, progress_cb=None):
    """Zip only files that differ from the baseline checksums.

    The diff is against ``.checksums.md5`` from the LAST extract of this
    folder, so a pack carries every change made since that extract — not just
    this session's.  Re-extracting into a folder re-baselines it, which resets
    what counts as "modified" (see the log line this emits).

    Returns ``(count, zip_path)``.
    """
    # read_baseline_any, not read_checksums: the baseline ships in two
    # flavours (md5sum-style for JJP, path\tmd5 for BOF/Stern) and the
    # tab-only parser silently returns {} for the md5sum form — which
    # here read as "no baseline, extract first" on a valid JJP extract.
    baseline = read_baseline_any(assets_folder)
    if not baseline:
        raise FileNotFoundError(
            f"No {CHECKSUMS_FILE} found in {assets_folder}. Extract first.")

    if log_cb:
        log_cb(f"Comparing {len(baseline)} file(s) against the extract "
               f"baseline...", "info")
    changed = []
    skipped_scratch = 0
    n_base = len(baseline)
    # Size+mtime MD5 cache (shared with the Write change scan): unchanged
    # files skip the re-hash, so an export right after a scan is near-instant.
    hcache = hashcache.load(assets_folder)
    for i, (rel, orig_md5) in enumerate(baseline.items()):
        if progress_cb:
            # The compare pass walks EVERY baseline file (that's how changed
            # ones are found, whatever their type) — say so, or an audio-only
            # modder watching video paths scroll by reads it as wasted work.
            progress_cb(i, n_base,
                        "Comparing %d of %d: %s" % (i + 1, n_base, rel))
        abs_path = os.path.join(assets_folder, rel)
        if not os.path.isfile(abs_path):
            continue
        digest = hashcache.md5_for(abs_path, rel, hcache)
        if digest is not None and digest != orig_md5:
            if _is_packable(rel):
                changed.append(rel)
            else:
                skipped_scratch += 1
    hashcache.save(assets_folder, hcache)

    if not changed:
        raise ValueError("No modified files found. Modify some files first.")

    total_bytes = 0
    for rel in changed:
        try:
            total_bytes += os.path.getsize(os.path.join(assets_folder, rel))
        except OSError:
            pass

    if log_cb:
        log_cb("Packing %d modified file(s), %s of assets..."
               % (len(changed), _human_size(total_bytes)), "info")
        if skipped_scratch:
            log_cb("Skipped %d rebuilt working file(s) (decrypted blobs / raw "
                   "images) — they aren't card assets and would bloat the pack."
                   % skipped_scratch, "info")
        # The pack is a diff against the LAST extract of this folder, so say
        # what that baseline is: re-extracting resets it, which is what makes
        # a pack look like it only holds "this session's" changes.
        log_cb("These are all the changes in this folder since its last "
               "extract (%d baselined file(s) compared), not just this "
               "session's." % n_base, "info")

    src = read_extract_source(assets_folder) or {}
    extras = project_extras(assets_folder)
    card_files = card_replacements(assets_folder)
    manifest = {
        "format": 2,
        "source_name": src.get("input_name") or "",
        "version_hint": version_hint_from_name(src.get("input_name")) or "",
        "file_count": len(changed),
        "total_bytes": total_bytes,
        "files": sorted(changed),
        "extras": extras,
        "card_files": card_files,
    }

    if log_cb:
        n_set = len(extras.get("settings") or {})
        n_hs = len(extras.get("high_scores") or {})
        n_tags = len(extras.get("image_group_tags") or {})
        rode = []
        if n_set:
            rode.append("%d default setting(s)" % n_set)
        if n_hs:
            rode.append("%d high-score default(s)" % n_hs)
        if n_tags:
            rode.append("%d image/scene name(s)" % n_tags)
        if rode:
            log_cb("Also packing " + ", ".join(rode)
                   + " — they are project settings, not files.", "info")
        if card_files:
            # Honest limit, said at pack time rather than discovered on the
            # rebuilt card: these live on the card image, not in this folder.
            log_cb("NOT in the pack: %d file(s) you replaced on the card image "
                   "itself with the Partitions tab (%s). Those are written into "
                   "the .raw, not into this project, so redo them on the "
                   "Partitions tab of whatever card you import this into."
                   % (len(card_files), describe_card_files(card_files)),
                   "warning")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for i, rel in enumerate(changed):
            zf.write(os.path.join(assets_folder, rel), rel)
            if progress_cb:
                progress_cb(i + 1, len(changed),
                            "Archiving %d of %d: %s" % (i + 1, len(changed),
                                                        rel))

    return len(changed), zip_path


def inspect_mod_pack(zip_path, assets_folder):
    """What importing *zip_path* into *assets_folder* would actually do.

    Returns a dict:

    ``names``       every asset member of the pack (manifest excluded)
    ``manifest``    the pack's manifest dict, or ``None`` for an old pack
    ``applicable``  members this extract HAS — the ones a build can use
    ``foreign``     members this extract doesn't have at all
    ``leftovers``   foreign members already sitting in the folder, i.e. what a
                    previous import of this pack dropped there
    ``pack_card`` / ``here_card``   the two source card names, when known
    ``judged``      False when the folder has no baseline to judge against
                    (an old or hand-made folder — then everything is
                    "applicable", exactly as before)

    A pack only ever holds files that were in ITS extract's baseline, so a
    member missing from THIS extract's baseline is not a file this card has:
    writing it creates a stray the Replace tabs list as a slot and no build can
    ever use.  A tester imported his LE pack into a Pro extract and got 201
    phantom audio "slots" (750 where the card has 549), each previewing his own
    mod as the card's original, while only 23 of the 232 files landed on
    anything real (batch 31).
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Directory entries (some zip writers add them) are not files and must
        # not land in the skipped count as if they were.
        names = [n for n in zf.namelist()
                 if n != MANIFEST_NAME and not n.endswith(("/", "\\"))]
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except (KeyError, ValueError, UnicodeDecodeError):
            manifest = None
    if not isinstance(manifest, dict):
        manifest = None

    baseline = read_baseline_any(assets_folder)
    judged = bool(baseline)
    applicable, foreign, leftovers = [], [], []
    for name in names:
        rel = name.replace("\\", "/")
        if not judged or rel in baseline:
            applicable.append(name)
            continue
        foreign.append(name)
        if os.path.isfile(os.path.join(assets_folder, *rel.split("/"))):
            leftovers.append(name)

    pack_card = (manifest or {}).get("source_name") or ""
    here_card = (read_extract_source(assets_folder) or {}).get("input_name") or ""
    return {
        "names": names,
        "manifest": manifest,
        "applicable": applicable,
        "foreign": foreign,
        "leftovers": leftovers,
        "pack_card": pack_card,
        "here_card": here_card,
        "judged": judged,
    }


def mismatch_lines(plan):
    """``[(level, text)]`` describing what's off between the pack and the
    folder in *plan* — shared by the import log and the confirmation box so
    both say the same thing."""
    out = []
    pack_card, here_card = plan.get("pack_card"), plan.get("here_card")
    hint = (plan.get("manifest") or {}).get("version_hint") or ""
    here_hint = version_hint_from_name(here_card)
    made_from = hint or pack_card
    if made_from:
        out.append(("info", "This pack was made from %s." % made_from))
    if here_hint and hint and here_hint != hint:
        out.append(("warning",
                    "This extract is %s — the pack was built against %s. "
                    "Importing across versions can produce a card that won't "
                    "boot; use \"Transfer Mods to New Version\" instead."
                    % (here_hint, hint)))
    elif (pack_card and here_card
            and pack_card.strip().lower() != here_card.strip().lower()):
        # Same firmware version, different card: an LE pack on a Pro extract.
        # The version check can't see this, and it is the one that silently
        # scatters files (batch 31).
        out.append(("warning",
                    "This pack was built from a different card: %s, and this "
                    "extract is %s. The two cards keep their sounds and art in "
                    "different places, so most of the pack does not fit here — "
                    "use \"Transfer Mods to New Version\" on the Mod Pack tab, "
                    "which matches your mods by what they are instead of by "
                    "where they sat." % (pack_card, here_card)))
    n_foreign = len(plan.get("foreign") or ())
    if n_foreign:
        out.append(("warning",
                    "%d of the pack's %d file(s) are not part of this extract "
                    "and will be skipped — nothing on this card matches them, "
                    "so a build could never use them."
                    % (n_foreign, len(plan.get("names") or ()))))
    if plan.get("leftovers"):
        out.append(("warning",
                    "%d of those are already in this folder from an earlier "
                    "import; they are listed as slots that can never build, so "
                    "they will be removed." % len(plan["leftovers"])))
    if not plan.get("judged"):
        out.append(("info",
                    "This folder has no extract baseline (%s), so every file "
                    "in the pack is being written without that check."
                    % CHECKSUMS_FILE))
    return out


def apply_extras(assets_folder, extras, log_cb=None):
    """Merge a pack's non-file edits (:func:`project_extras`) into
    *assets_folder*'s staged-changes sidecar.  Returns ``{key: count}``.

    Merged, not replaced: a value the pack carries wins for that one setting /
    slot / scene, and anything already staged in this folder that the pack says
    nothing about is left alone.
    """
    from . import staged_changes
    if not isinstance(extras, dict) or not extras:
        return {}
    data = staged_changes.load(assets_folder)
    applied = {}
    for key in _EXTRA_MAPS:
        vals = extras.get(key)
        if not isinstance(vals, dict) or not vals:
            continue
        merged = dict(data.get(key) or {})
        merged.update(vals)
        data[key] = merged
        applied[key] = len(vals)
    for key in _EXTRA_SCALARS:
        val = extras.get(key)
        if isinstance(val, str) and val.strip():
            data[key] = val
            applied[key] = 1
    if not applied:
        return {}
    staged_changes.save(assets_folder, data)
    # Scene / image-group names also go into the per-card library, so the very
    # next re-extract of THIS card still has them — the export, re-extract,
    # import loop is exactly how a tester moves a project onto a new firmware.
    tags = extras.get("image_group_tags")
    if isinstance(tags, dict) and tags:
        try:
            from . import tag_library
            tag_library.remember(assets_folder, tags, tags.keys())
        except Exception:
            pass
    if log_cb:
        words = {"settings": "%d default setting(s)",
                 "high_scores": "%d high-score default(s)",
                 "image_group_tags": "%d image/scene name(s)",
                 "menu_expose_through": "the Adjustments-menu reveal"}
        parts = []
        for key, n in applied.items():
            w = words.get(key, "%d " + key)
            parts.append(w % n if "%d" in w else w)
        log_cb("Restored from the pack: " + ", ".join(parts)
               + " — staged for the next Build.", "success")
    return applied


def import_mod_pack(zip_path, assets_folder, log_cb=None, progress_cb=None,
                    remove_leftovers=True, plan=None):
    """Extract a mod-pack zip into *assets_folder*.

    Only members this extract actually has are written (see
    :func:`inspect_mod_pack`); the rest are skipped, and the ones a previous
    import already dropped in the folder are removed unless *remove_leftovers*
    is False.  The pack's staged settings / scene names are merged in as well.

    Returns ``{"applied": [...], "skipped": [...], "removed": [...],
    "extras": {...}, "card_files": [...], "plan": plan}`` — *applied* is the
    list callers count and summarize by kind.
    """
    plan = plan or inspect_mod_pack(zip_path, assets_folder)
    manifest = plan.get("manifest") or {}
    applicable = plan["applicable"]
    if log_cb:
        for level, text in mismatch_lines(plan):
            log_cb(text, level)
        log_cb("Importing %d file(s)..." % len(applicable), "info")
    if not applicable:
        raise ValueError(
            "None of this pack's %d file(s) belong to this extract, so there "
            "is nothing to import.\n\nThe pack was built from %s and this "
            "folder was extracted from %s. Use \"Transfer Mods to New "
            "Version\" on the Mod Pack tab to carry mods between two different "
            "cards."
            % (len(plan["names"]), plan.get("pack_card") or "another card",
               plan.get("here_card") or "a different card"))

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Snapshot each pristine original into .orig/ before it's overwritten
        # (same backup staging takes), so an imported change previews its true
        # original and "Revert" can undo it without a re-extract.  snapshot()
        # verifies against the baseline md5, so a file that already diverged
        # is left un-snapshotted rather than captured wrong.
        baseline = read_baseline_any(assets_folder)
        for i, name in enumerate(applicable):
            rel = name.replace("\\", "/")
            md5 = baseline.get(rel)
            if md5 is not None:
                staged_originals.snapshot(assets_folder, rel, md5)
            zf.extract(name, assets_folder)
            if progress_cb:
                progress_cb(i + 1, len(applicable), name)

    removed = []
    if remove_leftovers:
        for name in plan["leftovers"]:
            rel = name.replace("\\", "/")
            path = os.path.join(assets_folder, *rel.split("/"))
            try:
                os.remove(path)
                removed.append(name)
            except OSError:
                pass
        _prune_empty(assets_folder, removed)
        if removed and log_cb:
            log_cb("Removed %d file(s) an earlier import of this pack left "
                   "here that this card has no slot for." % len(removed),
                   "info")

    extras = apply_extras(assets_folder, manifest.get("extras"), log_cb=log_cb)
    card_files = manifest.get("card_files") or []
    if card_files and log_cb:
        log_cb("This pack's card also had %d file(s) replaced on the card "
               "image itself with the Partitions tab (%s). Those are not in "
               "any pack — redo them on the Partitions tab against this card."
               % (len(card_files), describe_card_files(card_files)), "warning")
    return {"applied": applicable, "skipped": plan["foreign"],
            "removed": removed, "extras": extras, "card_files": card_files,
            "plan": plan}


def _prune_empty(assets_folder, removed):
    """Drop folders left empty by removing *removed* (a foreign card's whole
    ``images/<other_game>/`` tree, say) — never *assets_folder* itself."""
    root = os.path.normpath(assets_folder)
    for name in removed:
        cur = os.path.dirname(
            os.path.join(assets_folder, *name.replace("\\", "/").split("/")))
        while os.path.normpath(cur) != root and os.path.isdir(cur):
            try:
                os.rmdir(cur)          # only succeeds while empty
            except OSError:
                break
            cur = os.path.dirname(cur)
