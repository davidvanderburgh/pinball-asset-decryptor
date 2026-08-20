"""Transfer a user's pending mods from one extract folder to another — the
"I modded version N, now version N+1 shipped, move my work over" workflow.

Mods live as two artifacts inside an extract folder (see :mod:`staged_changes`
and :mod:`text_manifest`):

* ``.staged_changes.json`` — the Replace-Audio/Video/Image assignments
  (``rel_path -> external replacement file``) plus the per-slot audio Loop/Keep
  flags, the trim toggles, and the Defaults tab's staged settings / high-score
  slots.
* ``text/strings.tsv`` — the on-screen-text edits, keyed by the *original*
  string.

Transferring is not a blind copy, because a new firmware version can change the
asset layout.  Two hazards, handled differently:

* **Audio** slots are ``audio/idxNNNN.wav`` where ``NNNN`` is the master-
  directory index.  A new version can insert / remove / reorder sounds, so the
  same index can be a *different sound*.  We therefore match audio by the
  **content of the stock WAV** (a cheap size + head/tail digest), not by the raw
  index — so a replacement follows its sound even if it moved to a new index,
  and an index that now holds a *different* sound is flagged rather than
  silently mis-applied.  The stock bytes are NOT always the ones at
  ``audio/idxNNNN.wav``: building writes the replacement over the extracted
  file, so :func:`_stock_path` reads the ``.orig/`` snapshot for any slot that
  has one, and :func:`_plan_audio` falls back to the two folders' Extract
  baselines when even that is missing.
* **Image / Video / Text** are keyed by stable identities: loose images and
  videos by rel path / on-card path, scene textures by the manifest's asset
  card path, radium-embedded images by (radium card path, occurrence ordinal)
  — and because radium images are extracted content-deduplicated, ONE source
  image can own SEVERAL occurrence slots, each of which may be a distinct
  file on the target side; the remap fans a single source rel out to every
  target rel it identifies.  Font glyph slices key one level deeper, by
  (radium card path, atlas occurrence ordinal, char).  For text the key is
  the original string.  A rel_path / original that no longer exists in the
  target is dropped (a safe no-op), never re-pointed.  The user's renamed
  image groups (``image_group_tags``) ride along too — their group keys are
  container identities that transfer when the container still exists.

Every one of those on-card identities begins with the card's **game folder**,
which Stern names after the MODEL of the title (``godzilla_pro`` on a Pro card,
``godzilla_le`` on the Premium/LE build of the same game).  A transfer between
the two models therefore shares no identity at all unless that one component is
swapped, which is what :func:`_model_remap` does — see its docstring for why the
rest of the path lines up exactly.

``plan_transfer`` computes a reconciliation report without touching anything;
``apply_transfer`` merges the resolved edits into the target folder.  Nothing
here re-encodes or writes card data — the user still runs Write against the new
extract afterwards, which re-encodes each replacement for the new firmware.

There is also a second source of mods this module can recover: game code that
was modded *outside* this app (another tool wrote the replacements into the
firmware itself) and then extracted.  Such an extract has no sidecar — the mods
are baked into the decoded files.  :func:`diff_baked_mods` detects them by
diffing the modded extract against a **stock extract of the same version**,
producing the same ``saved``-shaped assignment maps (each detected slot's
replacement is the modded extract's own file), which then feed
``plan_transfer``/``apply_transfer`` via their ``saved``/``src_saved``
overrides — with the *stock* extract as the transfer source, so the content
matching still keys off stock sounds.

Both baked-mod routes (:func:`diff_baked_mods` and :func:`plan_direct_diff`)
diff by file bytes, but an image pair that decodes to identical pixels is NOT
a mod — vendor re-bakes and external-tool re-encodes change the compression /
metadata without touching a pixel — so those are skipped (and counted) rather
than staged.
"""

import hashlib
import os
import re

from . import checksums, staged_changes, staged_originals, text_manifest

# Slot categories that carry ``rel_path -> replacement`` assignment maps.
_ASSIGN_KEYS = ("audio", "video", "image")
# Per-audio-slot flag maps that must follow a remapped audio key.
_AUDIO_FLAG_KEYS = ("audio_loop", "audio_keep")
# Toggle values copied verbatim (not per-slot).
_TOGGLE_KEYS = ("audio_trim", "video_trim", "video_no_conversion",
                "menu_expose_through")
# Staged Defaults-tab edits.  These need no reconciliation at all: they are
# keyed by the firmware's own ``AD_`` names and high-score slot labels, which
# are the same words on a new version and on the other model of the same title
# (a tester building a Pro edition of his Prem/LE work), and the build-time
# apply already skips a name the target image doesn't carry and pulls every
# value into that image's own range.  Merged per key so an edit already made
# on the target wins.
_MERGE_KEYS = ("settings", "high_scores")

_HEAD = 256 * 1024
_TAIL = 64 * 1024


def content_signature(path):
    """A cheap, collision-safe signature of a file's *content*: its size plus a
    digest of the head and tail.  Two distinct extracted sounds never collide in
    practice (their WAV headers + leading samples differ), and it's fast even for
    a multi-hundred-MB music track.  Returns ``None`` if the file is unreadable.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            h.update(f.read(_HEAD))
            if size > _HEAD + _TAIL:
                f.seek(-_TAIL, os.SEEK_END)
                h.update(f.read(_TAIL))
    except OSError:
        return None
    return (size, h.hexdigest())


def _abs(root, rel):
    return os.path.join(root, rel.replace("/", os.sep))


def _stock_exists(root, rel):
    return os.path.isfile(_abs(root, rel))


def _stock_path(root, rel):
    """Path holding *rel*'s PRISTINE, as-extracted bytes.

    Not always ``root/rel``: the Replace tabs stage an edit by writing the
    converted replacement *over* the extracted file and parking the original in
    ``.orig/`` (:mod:`core.staged_originals`), so in any project the user has
    actually BUILT — which is how you get a card — every modded slot holds the
    replacement.  Audio pairs across versions and models by content, so reading
    the replacement there matches nothing in the target and the sounds the user
    modded (the only ones a transfer is about) all flag or drop.  Prefer the
    snapshot; fall back to the file itself for an un-built folder.
    """
    return staged_originals.snapshot_path(root, rel) or _abs(root, rel)


# Stable per-slot tokens in extracted WAV names, mirroring the Stern engine's
# ``_wav_idx`` / ``_MUSIC_WAV_RE`` (plugins/stern/engine.py): every naming
# option (duration prefix, Auto-transcribe rename) preserves the ``idxNNNN``
# token / ``music_catNN_MMMM`` prefix, so two extracts of the same version pair
# up slot-for-slot even if they were extracted with different naming settings.
_IDX_TOKEN_RE = re.compile(r"\bidx0*(\d+)", re.IGNORECASE)
_MUSIC_TOKEN_RE = re.compile(r"(music_cat\d+_\d+)", re.IGNORECASE)


def _audio_slot_key(name):
    """A naming-setting-independent identity for an extracted audio file."""
    stem = os.path.splitext(name)[0]
    m = _MUSIC_TOKEN_RE.search(stem)
    if m:
        return ("music", m.group(1).lower())
    m = _IDX_TOKEN_RE.search(stem)
    if m:
        return ("idx", int(m.group(1)))
    return ("name", os.path.normcase(name))


def _audio_by_slot_key(root):
    """``{slot_key: rel}`` for every WAV under *root*/audio (flat, like the
    extract lays them out).  Sorted so a duplicate key deterministically keeps
    the first name."""
    d = os.path.join(root, "audio")
    out = {}
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.startswith(".") or not name.lower().endswith(".wav"):
                continue
            out.setdefault(_audio_slot_key(name), "audio/" + name)
    return out


def _walk_rels(root, topdir):
    """Forward-slash rel paths of every file under *root*/*topdir*
    (recursive — images nest, e.g. ``images/scene_textures/``), skipping
    dot-entries and ``.txt`` files (the extractor's ``manifest.txt`` /
    ``radium_images.txt`` bookkeeping lists names + sizes, so they always
    differ across versions — never slots).  Empty when the folder doesn't
    exist."""
    rels = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, topdir)):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.startswith(".") or fn.lower().endswith(".txt"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            rels.append(rel.replace(os.sep, "/"))
    return rels


def _files_differ(path_a, path_b):
    """True when the two files' contents differ: a size compare short-circuits
    (no reads — matters for multi-hundred-MB videos), equal sizes fall back to
    :func:`content_signature`.  Unreadable on either side → False: we can't
    stage what we can't read, and a phantom diff is worse than a skip."""
    try:
        if os.path.getsize(path_a) != os.path.getsize(path_b):
            return True
    except OSError:
        return False
    sig_a, sig_b = content_signature(path_a), content_signature(path_b)
    return sig_a is not None and sig_b is not None and sig_a != sig_b


def _pixels_identical(path_a, path_b):
    """True when two image files decode to the SAME RGBA pixels even though
    their bytes differ — vendor re-bakes and external-tool re-encodes change
    the compression / metadata without touching a pixel, and staging those as
    "mods" writes stale old-version bytes over assets the new firmware
    re-baked.  Any failure (unreadable, not an image Pillow can decode, size
    mismatch) returns False: fail open and treat the pair as different —
    staging a vendor no-op is recoverable, silently dropping a real mod
    isn't."""
    try:
        from PIL import Image
        with Image.open(path_a) as im_a, Image.open(path_b) as im_b:
            if im_a.size != im_b.size:
                return False
            return (im_a.convert("RGBA").tobytes()
                    == im_b.convert("RGBA").tobytes())
    except Exception:
        return False


def _video_card_paths(root):
    """``{on_card_path: rel}`` parsed from the extractor's
    ``video/manifest.txt`` (columns: output filename, on-card path, bytes).

    The on-card path is a video's STABLE identity across versions.  The
    extractor derives output FILENAMES from scene titles — duplicate-title
    suffixes renumber and unnamed clips fall back to positional
    ``video_NNNN`` names, so a new version reshuffles most filenames and
    name-pairing misses the real matches (seen on TMNT 1.58→1.59: 822
    'old-only' files that were actually the same clips renamed).  Empty when
    the manifest is missing (older extracts) — callers fall back to
    filenames."""
    out = {}
    try:
        with open(os.path.join(root, "video", "manifest.txt"),
                  encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) >= 2 and cols[0] and cols[1]:
                    out.setdefault(cols[1], "video/" + cols[0])
    except OSError:
        return {}
    return out


def _manifest_rows(path):
    """Tab-split data rows of an extractor manifest (comment/blank lines
    skipped); ``[]`` when the file is missing."""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) >= 2 and cols[0] and cols[1]:
                    rows.append(cols)
    except OSError:
        return []
    return rows


def _game_folder(root):
    """The extract's own game-folder name (``godzilla_pro``), or ``None``.

    Every on-card path starts with it, and a loose image's rel carries it one
    level down (``images/godzilla_pro/...``) because the extract preserves the
    card's directory structure.  Read from whichever extract manifest is
    present, and only accepted when every row of that manifest agrees on one
    leading component — so the answer can only ever be the game identifier
    itself, never half a path.
    """
    for parts in (("video", "manifest.txt"),
                  ("images", "scene_textures", "manifest.txt"),
                  ("images", "manifest.txt"),
                  ("images", "scene_textures", "radium_images.txt")):
        firsts = set()
        for cols in _manifest_rows(os.path.join(root, *parts)):
            head, sep, tail = cols[1].lstrip("/").partition("/")
            firsts.add(head if sep and tail else None)
        if len(firsts) == 1 and None not in firsts:
            return firsts.pop()
    return None


def _model_remap(source_dir, target_dir, log_cb=None):
    """A rewrite of SOURCE-side identities into their TARGET-side form when the
    two extracts are different MODELS of one title — a Pro extract's mods
    moving onto the Premium/LE build, which is how Stern ships the other half
    of a title and a very ordinary thing for a re-theme to want.

    Without it that transfer carries nothing but audio: the game folder
    (:func:`_game_folder`) is the first component of every video / scene
    texture / radium card path and of every loose image's rel, so none of them
    pair and the whole image+video half of the plan drops with "no ... in the
    new version".  What FOLLOWS that component is a content hash of the scene
    bundle, so the two models' asset trees line up exactly once it is swapped:
    on the ``godzilla_pro`` 1.15 / ``godzilla_le`` 1.13 vendor pair all 658
    videos pair this way and every pair is the same byte size (0 pair without
    it), and on ``led_zeppelin_pro`` / ``led_zeppelin_le`` 1.22 all 163 do.

    Only the first whole component equal to the source's game folder is
    swapped, so a path that repeats the name deeper down keeps it.  Returns the
    identity function when either side's folder is unknown or the two agree, so
    the ordinary same-model new-version transfer is untouched.
    """
    src, tgt = _game_folder(source_dir), _game_folder(target_dir)
    if not src or not tgt or src == tgt:
        return lambda s: s
    if log_cb:
        log_cb("These are two different models of the same title (%s -> %s) — "
               "pairing assets across the two builds." % (src, tgt))
    pat = re.compile(r"(?<![^/])" + re.escape(src) + r"(?=/)")
    return lambda s: pat.sub(tgt, s, count=1)


def _scene_texture_cards(root):
    """``{asset_card_path: rel}`` from ``images/scene_textures/manifest.txt``
    (columns: out_rel-under-images/, card path, bytes, w, h, fmt).  Scene
    texture FILENAMES are ``<scene8>_<ref>_<WxH>`` with dedup suffixes —
    version-unstable like video names — so the on-card asset path is the
    stable identity."""
    return {cols[1]: "images/" + cols[0]
            for cols in _manifest_rows(os.path.join(
                root, "images", "scene_textures", "manifest.txt"))}


def _radium_occurrences(root):
    """``{radium_card_path: [rel, rel, ...]}`` — one entry per on-card
    occurrence, in manifest (= data offset) order — from
    ``images/scene_textures/radium_images.txt``.

    Radium-embedded images are deduplicated by content and their FILENAME
    embeds a content hash, so a MODDED image can never pair by name (not even
    between same-version extracts).  The stable identity is (radium card
    path, occurrence ordinal): offsets shift across versions but the order of
    images inside a radium doesn't, as long as none were added/removed."""
    out = {}
    for cols in _manifest_rows(os.path.join(
            root, "images", "scene_textures", "radium_images.txt")):
        out.setdefault(cols[1], []).append("images/" + cols[0])
    return out


def _glyph_identities(root, radium_occ, radiums):
    """``{(radium_card_path, occurrence_ordinal, char): rel}`` for every font
    glyph slice, from ``images/scene_textures/glyph_images.txt``.

    A glyph PNG's path embeds its ATLAS's content hash (version-unstable —
    same trap as the atlases themselves), but a character has a stable
    identity: the (radium card path, occurrence ordinal) slots its atlas
    occupies plus its char code.  *radium_occ* is :func:`_radium_occurrences`
    for *root*; only radiums in *radiums* contribute keys (the caller
    restricts to radiums whose occurrence count matches on both sides, the
    same guard ordinal pairing itself uses)."""
    atlas_occ = {}
    for radium, rels in radium_occ.items():
        if radium not in radiums:
            continue
        for k, rel in enumerate(rels):
            atlas_occ.setdefault(rel, []).append((radium, k))
    out = {}
    for cols in _manifest_rows(os.path.join(
            root, "images", "scene_textures", "glyph_images.txt")):
        if len(cols) < 3:
            continue
        for radium, k in atlas_occ.get("images/" + cols[1], ()):
            out[(radium, k, cols[2])] = "images/" + cols[0]
    return out


def _image_rel_remap(src_dir, tgt_dir, to_target=None):
    """``(remap, identified)`` pairing *src_dir*'s manifest-identified images
    with *tgt_dir*'s.  *to_target* is :func:`_model_remap`'s rewrite, applied
    to every source-side card path before the target lookup (identity by
    default).

    *remap* maps ``src_rel -> [tgt_rel, ...]`` (ordered, deduped) for every
    pairable image.  It's a MULTImap because radium images are extracted
    content-deduplicated: one src file can occupy many occurrence slots — an
    animation whose frames were all baked identical is ONE src PNG — while
    the target side has a distinct file per slot; every one of those target
    rels is that src image's slot.  *identified* is the set of src rels a
    manifest claims — for those the manifest verdict is authoritative
    (``rel in identified`` but not in *remap* means the counterpart is really
    gone; do NOT fall back to name matching, the name may have been reused by
    a different image).  Loose images (their rel IS the card path) are never
    ``identified`` — plain rel pairing is correct for them.  A src store
    whose TARGET-side manifest is missing (older extract) stays unidentified
    so name pairing still gets a chance.

    Font glyph slices pair the same way as their atlases, one level deeper:
    by (radium card path, atlas occurrence ordinal, char) via
    :func:`_glyph_identities` — a glyph edit follows its character even when
    the atlas art (and thus every path under ``glyphs/``) changed."""
    to_target = to_target or (lambda s: s)
    remap, identified = {}, set()

    def _pair(s, t):
        tgts = remap.setdefault(s, [])
        if t not in tgts:
            tgts.append(t)

    src_st = _scene_texture_cards(src_dir)
    tgt_st = _scene_texture_cards(tgt_dir)
    if src_st and tgt_st:
        for card, rel in src_st.items():
            identified.add(rel)
            tgt_rel = tgt_st.get(to_target(card))
            if tgt_rel is not None:
                _pair(rel, tgt_rel)

    src_rad = _radium_occurrences(src_dir)
    tgt_rad = _radium_occurrences(tgt_dir)
    if src_rad and tgt_rad:
        for radium, rels in src_rad.items():
            identified.update(rels)
            tgt_rels = tgt_rad.get(to_target(radium))
            if tgt_rels is not None and len(tgt_rels) == len(rels):
                for s, t in zip(rels, tgt_rels):
                    _pair(s, t)
        stable = {r for r, rels in src_rad.items()
                  if len(tgt_rad.get(to_target(r)) or ()) == len(rels)}
        src_gl = _glyph_identities(src_dir, src_rad, stable)
        # The target's own radium keys are its own model's, so the same guard
        # has to be expressed in the target's names.
        tgt_gl = _glyph_identities(tgt_dir, tgt_rad,
                                   {to_target(r) for r in stable})
        if src_gl and tgt_gl:
            for (radium, k, char), rel in src_gl.items():
                identified.add(rel)
                tgt_rel = tgt_gl.get((to_target(radium), k, char))
                if tgt_rel is not None:
                    _pair(rel, tgt_rel)
    return remap, identified


def diff_baked_mods(modded_dir, stock_dir, log_cb=None):
    """Detect mods that are BAKED INTO an extract (the game code itself was
    modded, e.g. with another tool, before extraction) by diffing it against a
    stock extract of the SAME code version.  Read-only.  Returns::

        {"saved": {"audio": {stock_rel: modded_abs_path},
                   "video": {...}, "image": {...}},
         "text_rows": [{path, original, replacement}, ...],
         "notes": {"paired_audio": int, "unpaired_audio": int,
                   "skipped_text_assets": int, "image_rebake_skipped": int}}

    ``image_rebake_skipped`` counts image pairs whose bytes differ but whose
    pixels are identical (a re-encode, not a mod — see
    :func:`_pixels_identical`); those are not staged.

    ``saved`` is shaped like the staged-changes sidecar with the *stock*
    extract's rels as keys and the *modded* extract's files as the replacement
    sources — ready to feed ``plan_transfer(stock_dir, target_dir,
    saved=...)``.  ``text_rows`` pairs the two manifests positionally per
    asset (original = stock string, replacement = modded string).
    *log_cb(text, level="info")* streams progress (see
    :func:`plan_direct_diff` — run off the UI thread).
    """
    log = log_cb or (lambda *_a, **_k: None)
    saved = {"audio": {}, "video": {}, "image": {}}
    notes = {"paired_audio": 0, "unpaired_audio": 0, "skipped_text_assets": 0,
             "image_rebake_skipped": 0}

    mod_keys = _audio_by_slot_key(modded_dir)
    stk_keys = _audio_by_slot_key(stock_dir)
    log("Comparing %d sound slot(s)..." % len(stk_keys))
    for i, (key, stk_rel) in enumerate(stk_keys.items(), 1):
        if i % 250 == 0:
            log("  ...%d/%d sounds compared" % (i, len(stk_keys)))
        mod_rel = mod_keys.get(key)
        if mod_rel is None:
            notes["unpaired_audio"] += 1
            continue
        notes["paired_audio"] += 1
        if _files_differ(_abs(stock_dir, stk_rel), _abs(modded_dir, mod_rel)):
            saved["audio"][stk_rel] = os.path.abspath(_abs(modded_dir, mod_rel))
    notes["unpaired_audio"] += sum(1 for k in mod_keys if k not in stk_keys)
    log("Sounds: %d differ (%d unpaired)."
        % (len(saved["audio"]), notes["unpaired_audio"]))

    # Videos pair by on-card path when both extracts carry a manifest (same
    # version, so filenames USUALLY agree — but the manifest is authoritative
    # and costs nothing).  Images pair via _image_rel_remap: even between
    # same-version extracts a MODDED radium image never name-matches (its
    # filename embeds a content hash).  Keys stay STOCK rels so the follow-up
    # plan_transfer(stock, target) can remap them onto the target.
    mod_cards = _video_card_paths(modded_dir)
    stk_rel_to_card = {r: c for c, r in _video_card_paths(stock_dir).items()}
    img_remap, img_identified = _image_rel_remap(stock_dir, modded_dir)
    for cat, top in (("video", "video"), ("image", "images")):
        rels = _walk_rels(stock_dir, top)
        log("Comparing %d %s file(s)..." % (len(rels), cat))
        for i, rel in enumerate(rels, 1):
            if i % 100 == 0:
                log("  ...%d/%d %ss compared" % (i, len(rels), cat))
            if cat == "video" and mod_cards and stk_rel_to_card:
                card = stk_rel_to_card.get(rel)
                mod_rel = mod_cards.get(card) if card else None
            elif cat == "image" and rel in img_identified:
                # First mapped element: the walk visits each STOCK file once
                # and ``saved`` can only hold one replacement per stock rel
                # anyway; occurrence order is preserved, so the first pairing
                # is the deterministic representative.
                mod_rels = img_remap.get(rel)
                mod_rel = mod_rels[0] if mod_rels else None
            else:
                mod_rel = rel
            mod_abs = _abs(modded_dir, mod_rel) if mod_rel else None
            if not mod_abs or not os.path.isfile(mod_abs):
                continue
            if _files_differ(mod_abs, _abs(stock_dir, rel)):
                if cat == "image" and _pixels_identical(
                        mod_abs, _abs(stock_dir, rel)):
                    notes["image_rebake_skipped"] += 1
                    continue
                saved[cat][rel] = os.path.abspath(mod_abs)
        extra = (" (%d pixel-identical re-encode(s) skipped)"
                 % notes["image_rebake_skipped"]
                 if cat == "image" and notes["image_rebake_skipped"] else "")
        log("%s: %d differ.%s"
            % (cat.capitalize(), len(saved[cat]), extra))

    # Text: pair the manifests positionally per asset.  Text patches are
    # same-length in-place edits, so both extracts see the same string count
    # per asset; a count mismatch means we can't pair reliably — skip it.
    stk_by_path, mod_by_path = {}, {}
    for r in text_manifest.load(stock_dir):
        stk_by_path.setdefault(r["path"], []).append(r["original"])
    for r in text_manifest.load(modded_dir):
        mod_by_path.setdefault(r["path"], []).append(r["original"])
    text_rows = []
    for path, stk_originals in stk_by_path.items():
        mod_originals = mod_by_path.get(path)
        if mod_originals is None:
            continue
        if len(mod_originals) != len(stk_originals):
            notes["skipped_text_assets"] += 1
            continue
        for stock_s, modded_s in zip(stk_originals, mod_originals):
            if modded_s != stock_s:
                text_rows.append({"path": path, "original": stock_s,
                                  "replacement": modded_s})

    return {"saved": saved, "text_rows": text_rows, "notes": notes}


def plan_direct_diff(modded_dir, target_dir, log_cb=None):
    """The no-baseline fallback of :func:`diff_baked_mods`: diff a modded
    OLD-version extract DIRECTLY against the new stock extract, for users who
    no longer have a stock extract of the old version.

    Videos pair by their on-card path (``video/manifest.txt``, filenames are
    version-unstable — see :func:`_video_card_paths`; name-pairing is the
    fallback for extracts without a manifest).  Loose images pair by rel path
    (the extractor preserves the card's directory structure); scene textures
    and radium-embedded images pair via the extract manifests (see
    :func:`_image_rel_remap`).  A paired file whose content differs is staged
    with the modded extract's file as the replacement, keyed by the TARGET's
    rel.  The caller must surface the
    result for review — without an old-version baseline a difference can also
    be the vendor's own between-version change.  Audio (indexes shift,
    content matching needs stock content) and text (originals change
    legitimately) can NOT be attributed this way; ``notes`` carries heads-up
    counts so the caller can warn that those need the baseline flow:

        notes = {"video_old_only": old videos with no counterpart in the new
                                   version (by card path, or name w/o manifest),
                 "image_old_only": old images with no same-named new file,
                 "audio_unmatched": old sounds with no identical sound in the
                                    new extract (vendor changes OR audio mods),
                 "text_unmatched":  old strings absent from the new manifest,
                 "image_rebake_skipped": image pairs whose bytes differ but
                                    whose pixels are identical (a vendor /
                                    tool re-encode, not a mod — not staged)}

    *log_cb(text, level="info")* streams progress — comparing thousands of
    files is minutes of I/O on big/cloud-synced extracts, so callers run this
    off the UI thread and surface the lines in the log.

    Returns the same plan shape as :func:`plan_transfer` (audio/text empty)
    plus the ``"notes"`` key — feed it to ``apply_transfer(...,
    src_saved={})``.
    """
    log = log_cb or (lambda *_a, **_k: None)
    plan = {"audio": {"matched": [], "remapped": [], "flagged": [],
                      "dropped": []},
            "video": {"matched": [], "dropped": []},
            "image": {"matched": [], "dropped": []},
            "text": {"matched": [], "dropped": []},
            "toggles": {}}
    notes = {"video_old_only": 0, "image_old_only": 0,
             "audio_unmatched": 0, "text_unmatched": 0,
             "image_rebake_skipped": 0}

    to_target = _model_remap(modded_dir, target_dir, log_cb=log_cb)

    # ---- Videos: card-path pairing, filename fallback -------------------
    mod_cards = _video_card_paths(modded_dir)
    tgt_cards = _video_card_paths(target_dir)
    pairs = []          # (mod_rel, tgt_rel)
    manifest_paired = set()
    if mod_cards and tgt_cards:
        for card, mod_rel in mod_cards.items():
            manifest_paired.add(mod_rel)
            tgt_rel = tgt_cards.get(to_target(card))
            if tgt_rel is None:
                notes["video_old_only"] += 1
            else:
                pairs.append((mod_rel, tgt_rel))
        log("Videos: %d paired by on-card path, %d only in the old version."
            % (len(pairs), notes["video_old_only"]))
    # Videos the manifests don't cover (older extract / hand-added files).
    for rel in _walk_rels(modded_dir, "video"):
        if rel in manifest_paired:
            continue
        cand = to_target(rel)
        if _stock_exists(target_dir, cand):
            pairs.append((rel, cand))
        else:
            notes["video_old_only"] += 1
    log("Comparing %d video pair(s)..." % len(pairs))
    for i, (mod_rel, tgt_rel) in enumerate(pairs, 1):
        if i % 100 == 0:
            log("  ...%d/%d videos compared" % (i, len(pairs)))
        mod_abs = _abs(modded_dir, mod_rel)
        if _files_differ(mod_abs, _abs(target_dir, tgt_rel)):
            plan["video"]["matched"].append(
                {"rel": tgt_rel, "repl": os.path.abspath(mod_abs),
                 "content_changed": True})
    log("Videos: %d differ." % len(plan["video"]["matched"]))

    # ---- Images ----------------------------------------------------------
    # Loose images pair by rel (their rel IS the card path); scene textures
    # and radium-embedded images pair via the extract manifests — their
    # filenames are version-unstable / content-hashed, so name pairing would
    # miss exactly the modded ones (see _image_rel_remap).
    rel_remap, identified = _image_rel_remap(modded_dir, target_dir,
                                             to_target)
    image_rels = _walk_rels(modded_dir, "images")
    log("Comparing %d image(s) (%d manifest-identified)..."
        % (len(image_rels), len(identified)))
    staged_img = set()
    for i, rel in enumerate(image_rels, 1):
        if i % 250 == 0:
            log("  ...%d/%d images compared" % (i, len(image_rels)))
        if rel in identified:
            tgt_rels = rel_remap.get(rel) or []
        else:
            cand = to_target(rel)
            tgt_rels = [cand] if _stock_exists(target_dir, cand) else []
        if not tgt_rels:
            notes["image_old_only"] += 1
            continue
        # A content-deduped source image can own several target slots (see
        # _image_rel_remap) — stage EVERY one, first assignment per target
        # slot wins.
        mod_abs = _abs(modded_dir, rel)
        for tgt_rel in tgt_rels:
            if tgt_rel in staged_img or not _files_differ(
                    mod_abs, _abs(target_dir, tgt_rel)):
                continue
            if _pixels_identical(mod_abs, _abs(target_dir, tgt_rel)):
                notes["image_rebake_skipped"] += 1
                continue
            staged_img.add(tgt_rel)
            plan["image"]["matched"].append(
                {"rel": tgt_rel, "repl": os.path.abspath(mod_abs),
                 "content_changed": True})
    log("Images: %d differ, %d only in the old version, %d pixel-identical "
        "re-encode(s) skipped."
        % (len(plan["image"]["matched"]), notes["image_old_only"],
           notes["image_rebake_skipped"]))

    # Heads-up counts only — differences we can't attribute without a stock
    # old-version extract.  Guarded so a category the target extract simply
    # doesn't have (not extracted) isn't miscounted as all-unmatched.
    tgt_audio = _audio_by_slot_key(target_dir)
    if tgt_audio:
        log("Indexing %d new-version sound(s)..." % len(tgt_audio))
    tgt_sigs = set()
    for i, rel in enumerate(tgt_audio.values(), 1):
        if i % 250 == 0:
            log("  ...%d/%d sounds indexed" % (i, len(tgt_audio)))
        sig = content_signature(_abs(target_dir, rel))
        if sig is not None:
            tgt_sigs.add(sig)
    if tgt_sigs:
        mod_audio = _audio_by_slot_key(modded_dir)
        log("Checking %d old sound(s) against the index..." % len(mod_audio))
        for i, rel in enumerate(mod_audio.values(), 1):
            if i % 250 == 0:
                log("  ...%d/%d sounds checked" % (i, len(mod_audio)))
            sig = content_signature(_abs(modded_dir, rel))
            if sig is not None and sig not in tgt_sigs:
                notes["audio_unmatched"] += 1

    tgt_originals = {r["original"] for r in text_manifest.load(target_dir)}
    if tgt_originals:
        for r in text_manifest.load(modded_dir):
            if r["original"] not in tgt_originals:
                notes["text_unmatched"] += 1

    transfer = len(plan["video"]["matched"]) + len(plan["image"]["matched"])
    plan["totals"] = {"transfer": transfer, "flagged": 0, "dropped": 0}
    plan["notes"] = notes
    return plan


def _plan_audio(source_dir, target_dir, saved_audio, log_cb=None):
    """Reconcile audio assignments by stock-WAV content.

    "Stock" means the bytes the Extract produced, which on a BUILT project is
    the ``.orig/`` snapshot rather than the slot file — see :func:`_stock_path`.

    Returns ``(matched, remapped, flagged, dropped)`` where each entry is a dict
    the caller can render and :func:`apply_transfer` can consume:
      matched  {src_rel, tgt_rel==src_rel, repl}
      remapped {src_rel, tgt_rel, repl}          (sound moved to a new index)
      flagged  {src_rel, repl, reason}           (index reused for another sound)
      dropped  {src_rel, repl, reason}           (sound no longer present)
    """
    log = log_cb or (lambda *_a, **_k: None)
    matched, remapped, flagged, dropped = [], [], [], []
    if not saved_audio:
        return matched, remapped, flagged, dropped

    # Index the target's stock WAVs by content signature (audio/ only).  Via
    # _stock_path, so a target the user has already staged edits on — which
    # apply_transfer explicitly supports — still indexes by its stock sounds.
    tgt_audio_dir = os.path.join(target_dir, "audio")
    sig_to_rels = {}
    if os.path.isdir(tgt_audio_dir):
        names = [n for n in os.listdir(tgt_audio_dir)
                 if n.lower().endswith(".wav")]
        log("Indexing %d new-version sound(s) by content..." % len(names))
        for i, name in enumerate(names, 1):
            if i % 250 == 0:
                log("  ...%d/%d sounds indexed" % (i, len(names)))
            rel = "audio/" + name
            sig = content_signature(_stock_path(target_dir, rel))
            if sig is not None:
                sig_to_rels.setdefault(sig, []).append(rel)

    # Last-resort identity for a slot whose pristine bytes are gone entirely:
    # no ``.orig`` snapshot because it was edited before snapshots shipped, or
    # replaced by hand outside the Replace tabs (snapshot() refuses a file that
    # has already diverged).  Both folders' Extract baselines still record what
    # every file hashed to when it came off the card, so the pair can be made
    # from bookkeeping alone, with no file read at all.  Built lazily: a folder
    # whose sounds all match by content never touches it.
    _base = {}

    def _baseline_cands(src_rel):
        if not _base:
            _base["src"] = checksums.read_baseline_any(source_dir)
            by_md5 = {}
            for rel, md5 in checksums.read_baseline_any(target_dir).items():
                if rel.startswith("audio/"):
                    by_md5.setdefault(md5, []).append(rel)
            _base["tgt"] = by_md5
        md5 = _base["src"].get(src_rel)
        if not md5:
            return []
        return [r for r in _base["tgt"].get(md5, ())
                if _stock_exists(target_dir, r)]

    for src_rel, repl in saved_audio.items():
        src_sig = content_signature(_stock_path(source_dir, src_rel))
        cands = sig_to_rels.get(src_sig, []) if src_sig is not None else []
        if not cands:
            cands = _baseline_cands(src_rel)
        if src_rel in cands:
            matched.append({"src_rel": src_rel, "tgt_rel": src_rel, "repl": repl})
        elif cands:
            # Same sound, moved to a different index. Prefer a deterministic pick.
            remapped.append({"src_rel": src_rel, "tgt_rel": sorted(cands)[0],
                             "repl": repl})
        elif _stock_exists(target_dir, src_rel):
            flagged.append({"src_rel": src_rel, "repl": repl,
                            "reason": "the sound at %s differs in the new "
                                      "version (index reused)" % src_rel})
        else:
            dropped.append({"src_rel": src_rel, "repl": repl,
                            "reason": "no matching sound in the new version"})
    return matched, remapped, flagged, dropped


def _plan_image(source_dir, target_dir, saved_map, to_target=None):
    """Reconcile an image assignment map.  Loose images pair by rel_path (the
    extractor preserves the card's directory structure); scene textures and
    radium-embedded images pair via the extract manifests (their filenames
    are version-unstable / content-hashed — see :func:`_image_rel_remap`).
    *to_target* is :func:`_model_remap`'s rewrite (identity by default) — a
    loose image's rel IS its card path, so it carries the game folder too.

    Returns ``(matched, dropped)`` — matched entries carry the TARGET's rel
    and note whether the stock asset's *content* changed (same slot, new art)
    so the caller can surface it.  A content-deduped source image can own
    several target slots (see :func:`_image_rel_remap`) — the assignment fans
    out to one matched entry per target rel."""
    matched, dropped = [], []
    if not saved_map:
        return matched, dropped
    to_target = to_target or (lambda s: s)
    rel_remap, identified = _image_rel_remap(source_dir, target_dir, to_target)
    for rel, repl in saved_map.items():
        if rel in identified:
            tgt_rels = rel_remap.get(rel) or []
        else:
            tgt_rels = [to_target(rel)]
        tgt_rels = [t for t in tgt_rels if _stock_exists(target_dir, t)]
        if tgt_rels:
            src_sig = content_signature(_abs(source_dir, rel))
            for tgt_rel in tgt_rels:
                changed = (src_sig
                           != content_signature(_abs(target_dir, tgt_rel)))
                matched.append({"rel": tgt_rel, "repl": repl,
                                "content_changed": changed})
        else:
            dropped.append({"rel": rel, "repl": repl,
                            "reason": "no %s in the new version" % rel})
    return matched, dropped


def _plan_video(source_dir, target_dir, saved_map, to_target=None):
    """Reconcile a video assignment map: by on-card path when both extracts
    have a ``video/manifest.txt`` (output filenames are version-unstable —
    see :func:`_video_card_paths`), by rel_path otherwise.  *to_target* is
    :func:`_model_remap`'s rewrite (identity by default).

    Matched entries carry the TARGET's rel (the slot the assignment lands
    on), which the card-path remap may have renamed."""
    to_target = to_target or (lambda s: s)
    src_cards = _video_card_paths(source_dir)   # card -> rel
    tgt_cards = _video_card_paths(target_dir)
    rel_to_card = {rel: card for card, rel in src_cards.items()}

    matched, dropped = [], []
    for rel, repl in (saved_map or {}).items():
        card = rel_to_card.get(rel)
        if card and tgt_cards:
            # Both manifests know this clip: the card path is authoritative —
            # even a same-named target file could be a DIFFERENT clip (the
            # title-derived name was reused).  Missing card ⇒ really gone.
            tgt_rel = tgt_cards.get(to_target(card))
        else:
            cand = to_target(rel)
            tgt_rel = cand if _stock_exists(target_dir, cand) else None
        if tgt_rel and _stock_exists(target_dir, tgt_rel):
            changed = (content_signature(_abs(source_dir, rel))
                       != content_signature(_abs(target_dir, tgt_rel)))
            matched.append({"rel": tgt_rel, "repl": repl,
                            "content_changed": changed})
        else:
            dropped.append({"rel": rel, "repl": repl,
                            "reason": "no %s in the new version" % rel})
    return matched, dropped


def _plan_text(source_dir, target_dir, src_rows=None):
    """Reconcile text edits: a source edit transfers if its *original* string
    still exists somewhere in the target manifest.  Returns ``(matched,
    dropped)`` where matched entries carry the number of target rows they'll
    fill (edits apply to every scene sharing the original text).  *src_rows*
    overrides the source manifest (rows synthesized by
    :func:`diff_baked_mods`)."""
    if src_rows is None:
        src_rows = text_manifest.load(source_dir)
    tgt_rows = text_manifest.load(target_dir)
    tgt_originals = {}
    for r in tgt_rows:
        tgt_originals.setdefault(r["original"], 0)
        tgt_originals[r["original"]] += 1

    matched, dropped = [], []
    seen = set()
    for r in src_rows:
        rep = r["replacement"]
        if not rep or rep == r["original"]:
            continue
        key = (r["original"], rep)
        if key in seen:
            continue
        seen.add(key)
        n = tgt_originals.get(r["original"], 0)
        if n:
            matched.append({"original": r["original"], "new": rep, "targets": n})
        else:
            dropped.append({"original": r["original"], "new": rep,
                            "reason": "that original text isn't in the new "
                                      "version"})
    return matched, dropped


_GLYPH_DIR_RE = re.compile(r"^images/scene_textures/glyphs/([^/]+)$")


def _plan_group_tags(source_dir, target_dir, saved, to_target=None):
    """Reconcile the user's renamed image groups (the ``image_group_tags``
    sidecar map, written by the Replace Images tab's "Rename group…").

    Group keys are container identities and mostly version-stable already:
    ``rad::<radium card path>`` / ``scn::<scene dir>`` / ``dir::<card or
    extract folder>`` — a tag transfers when its container still exists in
    the target extract.  The exception is a glyph folder
    (``dir::images/scene_textures/glyphs/<atlas stem>``): the stem embeds the
    atlas's content hash, so it's remapped through the atlas identity like
    the glyph slices themselves.  *to_target* is :func:`_model_remap`'s
    rewrite (identity by default) — every one of those container identities
    starts with the game folder, and a matched entry carries the TARGET's key
    so :func:`apply_transfer` writes the name under the key the new extract's
    own scan will produce.  Returns ``(matched, dropped)``."""
    to_target = to_target or (lambda s: s)
    tags = {k: v for k, v in
            ((saved or {}).get("image_group_tags") or {}).items() if v}
    if not tags:
        return [], []
    tgt_rad = set(_radium_occurrences(target_dir))
    tgt_scenes = set()
    for card in _scene_texture_cards(target_dir):
        if "/scene.assets/" in card:
            tgt_scenes.add(card.rsplit("/scene.assets/", 1)[0])
        else:
            tgt_scenes.add(card.rsplit("/", 1)[0] or card)
    tgt_dirs = set()
    for cols in _manifest_rows(os.path.join(target_dir, "images",
                                            "manifest.txt")):
        card_dir = cols[1].rsplit("/", 1)[0] if "/" in cols[1] else ""
        tgt_dirs.add(card_dir or "(root)")

    rel_remap = None
    matched, dropped = [], []
    for key, name in sorted(tags.items()):
        tgt_keys = []
        if key.startswith("rad::"):
            card = to_target(key[5:])
            if card in tgt_rad:
                tgt_keys = ["rad::" + card]
        elif key.startswith("scn::"):
            scene = to_target(key[5:])
            if scene in tgt_scenes:
                tgt_keys = ["scn::" + scene]
        elif key.startswith("dir::"):
            folder = key[5:]
            gm = _GLYPH_DIR_RE.match(folder)
            if gm:
                if rel_remap is None:
                    rel_remap, _ident = _image_rel_remap(source_dir, target_dir,
                                                         to_target)
                src_atlas = "images/scene_textures/%s.png" % gm.group(1)
                for t in rel_remap.get(src_atlas) or ():
                    stem = os.path.splitext(os.path.basename(t))[0]
                    tk = "dir::images/scene_textures/glyphs/" + stem
                    if tk not in tgt_keys:
                        tgt_keys.append(tk)
            else:
                folder = to_target(folder)
                if folder in tgt_dirs or (
                        folder != "(root)" and os.path.isdir(
                            _abs(target_dir, folder))):
                    tgt_keys = ["dir::" + folder]
        for k in tgt_keys:
            matched.append({"key": k, "name": name})
        if not tgt_keys:
            dropped.append({"key": key, "name": name,
                            "reason": "that group isn't in the new version"})
    return matched, dropped


def plan_transfer(source_dir, target_dir, saved=None, src_text_rows=None,
                  log_cb=None):
    """Compute a reconciliation plan moving *source_dir*'s mods onto
    *target_dir*.  Read-only.  Returns a dict::

        {"audio": {matched, remapped, flagged, dropped},
         "video": {matched, dropped},
         "image": {matched, dropped},
         "text":  {matched, dropped},
         "group_tags": {matched, dropped},
         "toggles": {key: value, ...},
         "defaults": {key: {name: value, ...}, ...},
         "totals": {"transfer": int, "flagged": int, "dropped": int}}

    *saved* / *src_text_rows* override the source folder's sidecar / text
    manifest — used for baked-in mods recovered by :func:`diff_baked_mods`,
    where *source_dir* must be the STOCK same-version extract (the audio
    matching reads its WAVs as the stock content).  *log_cb* streams progress
    (the audio content index hashes every target sound).

    The two folders may be different MODELS of one title (Pro -> Premium/LE)
    as well as different versions; :func:`_model_remap` is what makes their
    on-card identities comparable.
    """
    if saved is None:
        saved = staged_changes.load(source_dir)
    to_target = _model_remap(source_dir, target_dir, log_cb=log_cb)

    a_matched, a_remapped, a_flagged, a_dropped = _plan_audio(
        source_dir, target_dir, saved.get("audio"), log_cb=log_cb)
    v_matched, v_dropped = _plan_video(
        source_dir, target_dir, saved.get("video"), to_target)
    i_matched, i_dropped = _plan_image(
        source_dir, target_dir, saved.get("image"), to_target)
    t_matched, t_dropped = _plan_text(source_dir, target_dir,
                                      src_rows=src_text_rows)
    g_matched, g_dropped = _plan_group_tags(source_dir, target_dir, saved,
                                            to_target)

    plan = {
        "audio": {"matched": a_matched, "remapped": a_remapped,
                  "flagged": a_flagged, "dropped": a_dropped},
        "video": {"matched": v_matched, "dropped": v_dropped},
        "image": {"matched": i_matched, "dropped": i_dropped},
        "text": {"matched": t_matched, "dropped": t_dropped},
        "group_tags": {"matched": g_matched, "dropped": g_dropped},
        "toggles": {k: saved[k] for k in _TOGGLE_KEYS if k in saved},
        "defaults": {k: dict(saved[k]) for k in _MERGE_KEYS
                     if isinstance(saved.get(k), dict) and saved[k]},
    }
    n_defaults = sum(len(v) for v in plan["defaults"].values())
    transfer = (len(a_matched) + len(a_remapped) + len(v_matched)
                + len(i_matched) + len(t_matched) + len(g_matched)
                + n_defaults)
    flagged = len(a_flagged)
    dropped = (len(a_dropped) + len(v_dropped) + len(i_dropped)
               + len(t_dropped) + len(g_dropped))
    plan["totals"] = {"transfer": transfer, "flagged": flagged,
                      "dropped": dropped}
    return plan


def apply_transfer(source_dir, target_dir, plan, include_flagged=False,
                   src_saved=None):
    """Merge *plan*'s transferable edits into *target_dir*'s sidecar + text
    manifest.  Existing target edits are preserved unless a transferred entry
    targets the same slot/string.  ``include_flagged`` also applies the audio
    entries whose index was reused (off by default — those are the risky ones).
    ``src_saved`` overrides the source sidecar (pairs with ``plan_transfer``'s
    ``saved``).  Returns ``{"audio", "video", "image", "text", "group_tags",
    "defaults"}`` counts actually written."""
    if src_saved is None:
        src_saved = staged_changes.load(source_dir)
    tgt = staged_changes.load(target_dir)

    src_loop = src_saved.get("audio_loop") or {}
    src_keep = src_saved.get("audio_keep") or {}
    tgt_audio = dict(tgt.get("audio") or {})
    tgt_loop = dict(tgt.get("audio_loop") or {})
    tgt_keep = dict(tgt.get("audio_keep") or {})

    def _put_audio(src_rel, tgt_rel, repl):
        tgt_audio[tgt_rel] = repl
        if src_rel in src_loop:
            tgt_loop[tgt_rel] = src_loop[src_rel]
        if src_rel in src_keep:
            tgt_keep[tgt_rel] = src_keep[src_rel]

    n_audio = 0
    for e in plan["audio"]["matched"] + plan["audio"]["remapped"]:
        _put_audio(e["src_rel"], e["tgt_rel"], e["repl"])
        n_audio += 1
    if include_flagged:
        for e in plan["audio"]["flagged"]:
            _put_audio(e["src_rel"], e["src_rel"], e["repl"])
            n_audio += 1
    if tgt_audio:
        tgt["audio"] = tgt_audio
    if tgt_loop:
        tgt["audio_loop"] = tgt_loop
    if tgt_keep:
        tgt["audio_keep"] = tgt_keep

    tgt_video = dict(tgt.get("video") or {})
    for e in plan["video"]["matched"]:
        tgt_video[e["rel"]] = e["repl"]
    if tgt_video:
        tgt["video"] = tgt_video

    tgt_image = dict(tgt.get("image") or {})
    for e in plan["image"]["matched"]:
        tgt_image[e["rel"]] = e["repl"]
    if tgt_image:
        tgt["image"] = tgt_image

    # Renamed image groups: a name the user already gave a group on the
    # TARGET extract wins over the transferred one (same rule as toggles).
    n_tags = 0
    tgt_tags = dict(tgt.get("image_group_tags") or {})
    for e in (plan.get("group_tags") or {}).get("matched", ()):
        if e["key"] not in tgt_tags:
            tgt_tags[e["key"]] = e["name"]
            n_tags += 1
    if tgt_tags:
        tgt["image_group_tags"] = tgt_tags

    # Toggles copy over only if the target doesn't already set them.
    for k, v in plan.get("toggles", {}).items():
        tgt.setdefault(k, v)

    # Staged Defaults-tab edits, merged per setting / per high-score slot so
    # anything already set on the target extract stays as the user left it.
    n_defaults = 0
    for k, vals in (plan.get("defaults") or {}).items():
        merged = dict(tgt.get(k) or {})
        for name, v in vals.items():
            if name not in merged:
                merged[name] = v
                n_defaults += 1
        if merged:
            tgt[k] = merged

    staged_changes.save(target_dir, tgt)

    # Text: fill matching originals in the target manifest.
    n_text = 0
    new_by_original = {e["original"]: e["new"] for e in plan["text"]["matched"]}
    if new_by_original:
        rows = text_manifest.load(target_dir)
        for r in rows:
            if r["original"] in new_by_original:
                r["replacement"] = new_by_original[r["original"]]
                n_text += 1
        if n_text:
            text_manifest.save(target_dir, rows)

    return {"audio": n_audio, "video": len(plan["video"]["matched"]),
            "image": len(plan["image"]["matched"]), "text": n_text,
            "group_tags": n_tags, "defaults": n_defaults}
