"""Records which source image an extract came from, so the GUI can warn
when the underlying image is swapped/reverted *after* assets were extracted.

The "Original Track / Image / Text" names the Replace tabs show come from the
files in the extract *output* folder, not from the source ``.raw``/``.img``.
If a user reverts the source image on disk (e.g. overwrites it with a fresh
copy of the same name) and re-opens the app, the previously-extracted assets
folder is unchanged, so the app keeps showing the old (modified) state — there
is nothing that ties those assets back to the now-changed image.

This module drops a tiny sidecar (:data:`SIDE_CAR`) into the extract output
folder recording the source image's path + ``(size, mtime)`` at extract time.
:func:`stale_source_message` re-checks that signature with a single ``stat``
(no multi-GB read) and returns a human warning when it no longer matches.

Not every change to the image is a reason to re-extract, though.  PAD's own
Partitions-tab Replace writes into the card image and moves its mtime, so the
warning used to fire on an edit the user had just made *in the app* — and told
him to re-run Extract over a file (``/usr/local/spike/SternLogo.png`` on the OS
partition) that no extracted asset came from.  :mod:`core.card_edits` remembers
those replaces, so the check can now tell "PAD changed this image, and not in a
way that matters here" from "something else changed it".

And when the warning is right but the user has decided it doesn't matter to
them ("I know I am fine but will have to see that message the entire time"),
:func:`dismiss_stale_source` parks the *current* source signature in the same
sidecar and :func:`stale_dismissed` reports it, so the banner's Dismiss
survives a restart.  It is deliberately pinned to that one signature: the next
change to the image no longer matches it and the warning comes back.
"""

import json
import os
import re
from typing import Optional

# Sidecar file written at the root of every extract output folder.  Dotfile so
# the audio/video/image slot scanners (which skip dot-entries) ignore it.
SIDE_CAR = ".extract_source.json"

# Stern names its card images ``<game>-<maj>_<min>_<patch>.<channel>.<size>...``
# (e.g. ``turtles_pro-1_59_0.Release.8G.sdcard.raw``).  The card's own
# ``/spk/index/<...>.sidx`` name is the version AUTHORITY (it survives a
# renamed file — see stern info.resolve_version); reading it costs opening
# the image, so the extract stamps it into this sidecar as ``card_version``
# (via amend_extract_source, probed off-thread after the extract) and this
# filename parse is the fallback hint for extracts that predate the stamp.
_VER_RE = re.compile(r"-(\d+)_(\d+)_(\d+)(?:\.([A-Za-z0-9]+))?")
# Channel-position tokens that are media-size markers, not a build tag.
_SIZE_TOKENS = frozenset({"8g", "4g", "16g", "2g", "32g"})

# Sidecar key holding the source signature the user dismissed the warning for.
# Lives beside the extract-time signature rather than in settings.json so it
# travels with the project folder — and so a re-Extract, which rewrites the
# whole sidecar, drops it without anyone having to remember to.
_DISMISSED = "dismissed"


def _signature(input_path: str) -> Optional[dict]:
    try:
        st = os.stat(input_path)
    except OSError:
        return None
    return {
        "input_path": os.path.abspath(input_path),
        "input_name": os.path.basename(input_path),
        "size": st.st_size,
        # Whole seconds — avoids float-jitter false positives across
        # filesystems with differing mtime precision.
        "mtime": int(st.st_mtime),
    }


def write_extract_source(output_dir: str, input_path: str) -> None:
    """Record *input_path*'s identity into ``output_dir``/:data:`SIDE_CAR`.

    Best-effort: silently no-ops if *input_path* isn't a regular file (e.g. a
    Direct-SSD ``\\\\.\\PHYSICALDRIVE`` device) or the folder isn't writable.
    """
    if not output_dir or not os.path.isdir(output_dir):
        return
    if not input_path or not os.path.isfile(input_path):
        return
    sig = _signature(input_path)
    if sig is None:
        return
    try:
        with open(os.path.join(output_dir, SIDE_CAR), "w", encoding="utf-8") as f:
            json.dump(sig, f, indent=2)
    except OSError:
        pass


def read_extract_source(assets_dir: str) -> Optional[dict]:
    """Return the source signature recorded for *assets_dir* (the dict written
    by :func:`write_extract_source`), or ``None`` when there's no readable
    sidecar.  Lets callers recover the ``.raw``/``.img`` an extract came from —
    e.g. the transfer panel auto-fills the build's base image from the new
    extract's own recorded source."""
    if not assets_dir:
        return None
    try:
        with open(os.path.join(assets_dir, SIDE_CAR), encoding="utf-8") as f:
            recorded = json.load(f)
    except (OSError, ValueError):
        return None
    return recorded if isinstance(recorded, dict) else None


def _names_this_image(rec: dict, image_path: str) -> bool:
    """Does the sidecar *rec* describe an extract of *image_path*?

    The recorded absolute path is the strong answer.  The weak one — same file
    NAME and same byte size — exists because a card gets moved or copied far
    more often than it gets rebuilt, and refusing to pair a folder with the
    card it plainly came from would put the report back on "run an Extract"
    for a user who already has.  The mtime is deliberately NOT part of this:
    that is :func:`stale_source_message`'s job, and a stale extract is still
    the extract of this card.
    """
    if not rec:
        return False
    recorded = rec.get("input_path") or ""
    if recorded and os.path.normcase(os.path.abspath(recorded)) == \
            os.path.normcase(os.path.abspath(image_path)):
        return True
    if os.path.normcase(rec.get("input_name") or "") != \
            os.path.normcase(os.path.basename(image_path)):
        return False
    try:
        return rec.get("size") == os.path.getsize(image_path)
    except OSError:
        return False


def find_extract_for(image_path: str, roots) -> Optional[str]:
    """The extract folder *image_path* was extracted to, or ``None``.

    *roots* are folders to look in; each is checked itself and one level down,
    which is exactly the shape "Extract Both" leaves behind (one parent folder,
    a sub-folder per card).  Only the sidecars are read — no walking, no
    hashing — so this stays cheap enough to run on every Compare click.

    Deliberately NOT a filesystem search.  Guessing at an extract folder from
    a name would eventually pair a report with the wrong card's sounds, and a
    confidently wrong audio diff is worse than the honest "extract both, then
    compare again" the caller falls back to.
    """
    if not image_path:
        return None
    seen = set()
    for root in roots or ():
        if not root or not os.path.isdir(root):
            continue
        candidates = [root]
        try:
            candidates += [os.path.join(root, n)
                           for n in sorted(os.listdir(root))]
        except OSError:
            pass
        for cand in candidates:
            key = os.path.normcase(os.path.abspath(cand))
            if key in seen or not os.path.isdir(cand):
                continue
            seen.add(key)
            if _names_this_image(read_extract_source(cand), image_path):
                return cand
    return None


def other_card_recorded(assets_dir: str, image_path: str) -> Optional[str]:
    """The card *assets_dir* was extracted from, when a build is about to
    patch a DIFFERENT one; ``None`` when it is the same card or the folder
    records no source at all.

    A build applies the replacements the folder has, not the folder's whole
    contents: every sound, video, image and line of text it does not replace
    comes from the card being built.  So building a folder extracted from an
    already-modded card onto a stock card produces a stock card plus that
    build's replacements, and every mod baked in by the earlier builds is
    gone.  A modder lost several editions' worth of work to exactly this,
    trying to get back to a card without longer audio (PAD-176), and nothing
    in the app said a word.  The carry-over route is Transfer mods, which
    reads the baked mods out by comparing against a stock extract.

    Returns the recorded card's NAME (for the warning) rather than a bool, so
    the caller can name both cards.
    """
    rec = read_extract_source(assets_dir)
    if not rec:
        return None
    name = (rec.get("input_name")
            or os.path.basename(rec.get("input_path") or ""))
    if not name or not image_path:
        return None
    return None if _names_this_image(rec, image_path) else name


#: Mirrors ``plugins.stern.engine.BUILD_MANIFEST_SUFFIX``: the record a Build
#: leaves beside the card it wrote.  Duplicated rather than imported so this
#: module stays plugin-free; a test pins the two together.
BUILD_RECORD_SUFFIX = ".pad-build.json"


def built_card_source(assets_dir: str) -> Optional[str]:
    """The card *assets_dir* was extracted from, when that card is one this
    app BUILT; ``None`` for a stock card, an unknown one, or no sidecar.

    A build record sits beside every card a Build writes, so this answers
    "does this folder's own content already carry mods?" with one ``stat``
    and no reading of the card.  It is the difference that decides what a mod
    transfer can carry: an extract of a built card holds that card's mods as
    its BASELINE, and a transfer driven by the folder's pending replacements
    leaves every one of them behind (PAD-176).
    """
    rec = read_extract_source(assets_dir)
    if not rec:
        return None
    path = rec.get("input_path") or ""
    if not path or not os.path.isfile(path + BUILD_RECORD_SUFFIX):
        return None
    return rec.get("input_name") or os.path.basename(path)


def _build_project(card_path: str) -> Optional[str]:
    """The project folder the build record beside *card_path* names, or
    ``None`` when PAD did not build that card (or the build never
    finished)."""
    try:
        with open(card_path + BUILD_RECORD_SUFFIX, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict) or rec.get("building"):
        return None
    return str(rec.get("assets") or "") or None


def _same_dir(a: str, b: str) -> bool:
    return bool(a and b) and (os.path.normcase(os.path.abspath(a))
                              == os.path.normcase(os.path.abspath(b)))


def latest_build(assets_dir: str) -> Optional[str]:
    """The newest card PAD built from *assets_dir* into the project's build
    folder, or ``None``.  Only the build folder's own files are looked at,
    and only the ones whose build record names this project."""
    from .project_file import project_build_dir
    try:
        folder = project_build_dir(assets_dir)
        names = os.listdir(folder)
    except (OSError, ValueError):
        return None
    best, best_t = None, None
    for name in names:
        if not name.endswith(BUILD_RECORD_SUFFIX):
            continue
        card = os.path.join(folder, name[:-len(BUILD_RECORD_SUFFIX)])
        if not _same_dir(_build_project(card) or "", assets_dir):
            continue
        try:
            t = os.path.getmtime(card)
        except OSError:
            continue
        if best_t is None or t > best_t:
            best, best_t = card, t
    return best


def card_relation(card_path: str, assets_dir: str) -> Optional[dict]:
    """How the card picked to run relates to the project folder (PAD-199).

    The Emulate tab runs whatever card is picked, while the header and the
    "Apply my replaced assets" box both follow the project; nothing on the
    page said whether those were the same game.  ``None`` when either is
    unset; otherwise a dict:

    - ``kind``: ``"source"`` (the card the project was extracted from),
      ``"build"`` (a card PAD built from this project), ``"other_build"``
      (a card PAD built from ANOTHER project, named in ``other``) or
      ``"other"`` (anything else).
    - ``source`` / ``build``: the project's extracted card and its newest
      build, when they are on disk (``""`` when not), so the page can offer
      to switch to them.
    - ``source_name``: the recorded source card's file name, even when the
      file is gone.

    File reads only (a sidecar, a build record, one folder listing); the
    card itself is never opened, but the caller still keeps it off the UI
    loop because a card on a sleeping share can stall a ``stat``.
    """
    if not card_path or not assets_dir:
        return None
    rec = read_extract_source(assets_dir) or {}
    src = str(rec.get("input_path") or "")
    built_from = _build_project(card_path)
    if rec and _names_this_image(rec, card_path):
        kind = "source"
    elif built_from and _same_dir(built_from, assets_dir):
        kind = "build"
    elif built_from:
        kind = "other_build"
    else:
        kind = "other"
    build = latest_build(assets_dir) or ""
    return {
        "kind": kind,
        "project": os.path.basename(os.path.normpath(assets_dir)),
        "other": (os.path.basename(os.path.normpath(built_from))
                  if kind == "other_build" else ""),
        "source": src if src and os.path.isfile(src) else "",
        "source_name": (rec.get("input_name") or os.path.basename(src)
                        if rec else ""),
        "build": build,
    }


def version_hint_from_name(name: Optional[str]) -> Optional[str]:
    """A human version label parsed from a card-image filename, or ``None``.

    ``turtles_pro-1_59_0.Release.8G.sdcard.raw`` -> ``"1.59.0 (Release)"``;
    ``turtles_pro-1_58_1.1987.8G.sdcard.raw``    -> ``"1.58.1 (1987)"``.
    Filename-derived (the card carries no game-version string), so callers
    should present it as a hint, not ground truth."""
    if not name:
        return None
    m = _VER_RE.search(name)
    if not m:
        return None
    ver = "%s.%s.%s" % (m.group(1), m.group(2), m.group(3))
    tag = m.group(4)
    if tag and tag.lower() not in _SIZE_TOKENS:
        return "%s (%s)" % (ver, tag)
    return ver


def version_hint_for_dir(assets_dir: str) -> Optional[str]:
    """:func:`version_hint_from_name` of the source recorded for *assets_dir*."""
    rec = read_extract_source(assets_dir)
    if not rec:
        return None
    return version_hint_from_name(rec.get("input_name"))


def amend_extract_source(assets_dir: str, **extra) -> None:
    """Merge *extra* keys into *assets_dir*'s recorded source sidecar.

    Best-effort like the writer.  Used to stamp facts that take a real read
    of the source image to learn — e.g. ``card_version``, probed off-thread
    after the extract finishes — without disturbing the signature fields."""
    rec = read_extract_source(assets_dir)
    if rec is None:
        return
    rec.update(extra)
    try:
        with open(os.path.join(assets_dir, SIDE_CAR), "w",
                  encoding="utf-8") as f:
            json.dump(rec, f, indent=2)
    except OSError:
        pass


def version_for_dir(assets_dir: str):
    """``(version_label, exact)`` for *assets_dir* — the recorded
    ``card_version`` (read from the source card's own update index at extract
    time, so it survives any renaming) when the extract carries one, else the
    filename hint with ``exact=False``, else ``(None, False)``."""
    rec = read_extract_source(assets_dir)
    if not rec:
        return None, False
    exact = rec.get("card_version")
    if exact:
        return exact, True
    return version_hint_from_name(rec.get("input_name")), False


def stale_source_message(assets_dir: str) -> Optional[str]:
    """Return a warning string if the source image recorded for *assets_dir*
    has changed on disk since the extract, else ``None``.

    Returns ``None`` (no warning) when there's no sidecar — older extracts and
    non-file inputs simply opt out — or when the recorded source is missing or
    still matches.  Cheap: one ``stat`` of the source, no large reads.
    """
    if not assets_dir:
        return None
    try:
        with open(os.path.join(assets_dir, SIDE_CAR), encoding="utf-8") as f:
            recorded = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(recorded, dict):
        return None
    path = recorded.get("input_path")
    if not path or not os.path.isfile(path):
        # Source moved/deleted — can't prove it's stale, so stay quiet rather
        # than nag about a path the user may have intentionally relocated.
        return None
    current = _signature(path)
    if current is None:
        return None
    if (current["size"] == recorded.get("size")
            and current["mtime"] == recorded.get("mtime")):
        return None
    name = recorded.get("input_name") or os.path.basename(path)
    own = _own_edit_verdict(path, assets_dir, name)
    if own is not _NOT_OURS:
        return own
    return (
        f"The source image “{name}” has changed on disk since these "
        "assets were extracted. The original-track names and replacements "
        "shown may not match the current image — re-run Extract to refresh."
    )


def dismiss_stale_source(assets_dir: str) -> bool:
    """Remember that the user accepted the source image exactly as it is now.

    Records the source's *current* ``(size, mtime)`` in the sidecar, so
    :func:`stale_dismissed` can answer "this is the state they already waved
    through" and the banner stays down across restarts.  Any later change to
    the image produces a different signature, so the warning returns.

    Best-effort — returns False (and changes nothing) when there is no sidecar,
    the source is gone, or the folder isn't writable.  Callers pair it with an
    in-memory flag so a failed write still hides the banner for the session.
    """
    recorded = read_extract_source(assets_dir)
    if not recorded:
        return False
    path = recorded.get("input_path")
    sig = _signature(path) if path else None
    if sig is None:
        return False
    recorded[_DISMISSED] = {"size": sig["size"], "mtime": sig["mtime"]}
    try:
        with open(os.path.join(assets_dir, SIDE_CAR), "w",
                  encoding="utf-8") as f:
            json.dump(recorded, f, indent=2)
    except OSError:
        return False
    return True


def stale_dismissed(assets_dir: str) -> bool:
    """True when the source image's current state is one the user dismissed.

    Cheap (one ``stat``) and deliberately exact: it answers only for the
    signature that was dismissed, never "warnings are off for this folder".
    """
    recorded = read_extract_source(assets_dir)
    if not recorded:
        return False
    ack = recorded.get(_DISMISSED)
    path = recorded.get("input_path")
    if not isinstance(ack, dict) or not path:
        return False
    sig = _signature(path)
    if sig is None:
        return False
    return (sig["size"] == ack.get("size")
            and sig["mtime"] == ack.get("mtime"))


#: "PAD's own edits do not explain this image" — distinct from the ``None`` that
#: means "explained, and nothing is wrong".
_NOT_OURS = object()


def _own_edit_verdict(image_path, assets_dir, name):
    """What to say when the source image's own change was PAD's doing.

    The Partitions tab's Replace writes into the card image, which moves its
    mtime — so a tester swapping ``/usr/local/spike/SternLogo.png`` on sda2 got
    told his extract was stale and to re-run Extract, which was both alarming
    and wrong: that file is not where any extracted asset came from, and the
    only thing that changed about the image was the swap he had just watched
    PAD make.

    Returns ``None`` when PAD's journal accounts for the image exactly and the
    extract is unaffected (no banner), a warning naming the file when a replace
    DID hit one of the extract's own source files, or :data:`_NOT_OURS` when
    the journal can't account for the change — something else touched the
    image, so the general warning stands.
    """
    from . import card_edits, card_paths
    if not card_edits.signature_current(image_path):
        return _NOT_OURS
    ours = card_edits.replaced(image_path)
    if not ours:
        return _NOT_OURS
    covered = card_paths.extracted_card_paths(assets_dir)
    if not covered:
        # No manifests to check against (an older or device-sourced extract) —
        # can't prove the swap missed the extract, so don't suppress.
        return _NOT_OURS
    hits = sorted(p for p in ours
                  if card_paths.is_extract_source(assets_dir, p))
    if hits:
        return (
            f"You replaced {hits[0]} on “{name}” with the Partitions tab, and "
            "these assets were extracted from that file. The original-track "
            "names and replacements shown may not match it any more — re-run "
            "Extract to refresh."
        )
    return None
