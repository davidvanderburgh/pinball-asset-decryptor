"""Read-only technical probe of a Spike 2 card for the Image Info tab.

Everything here is derived from sources the app already understands, without
extracting anything: the vendor filename (the only place the firmware version
string survives), the MBR partition table, and the ``.sidx`` validation
manifest on the data partition (game folder, indexed-file count, record
format, ``image.bin`` size), plus on-card asset counts (videos by the same
12-byte ``ftyp`` sniff the extract uses, images/scenes by name).  The probe
walks directory metadata and never reads more than a magic-sniff of any
file, so it stays quick even on a multi-GB image.
"""

import os
import re

from ...core.image_info import human_size
from . import sidx as sidx_mod
from .explorer import CardImage

# ``<title>_<edition>-<version>.Release.<size>.sdcard.raw`` — Stern's own card
# naming (see formats._title_from_filename).  The version is digits joined by
# underscores ("1_27_0"); anything else after the dash is not a version.
_VERSION_RE = re.compile(r"^(\d+(?:_\d+)*)$")
_EDITIONS = {"le": "LE", "pro": "Pro", "prem": "Premium",
             "premium": "Premium", "se": "SE"}


def version_from_filename(path):
    """``(version, edition)`` parsed from a vendor-named card, else
    ``(None, None)``.  ``munsters_le-1_27_0.Release.8G.sdcard.raw`` ->
    ``("1.27.0", "LE")``.  A renamed card yields nothing — the version string
    exists only in the filename, not on the card."""
    stem = os.path.basename(path).split(".", 1)[0]
    title, _, ver = stem.partition("-")
    version = edition = None
    if ver:
        m = _VERSION_RE.match(ver)
        if m:
            version = m.group(1).replace("_", ".")
    words = title.lower().split("_")
    if words and words[-1] in _EDITIONS:
        edition = _EDITIONS[words[-1]]
    return version, edition


# Loose LCD UI images on the card (same list engine.extract_images uses).
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".webp")


def _walk_partition(reader):
    """One metadata walk of a partition: the ``.sidx`` manifest, ``image.bin``,
    and on-card asset counts.  Videos are the same 12-byte ``ftyp`` sniff the
    extract's video scan does (Spike 2 stores them as extensionless
    ``.asset`` files); nothing larger is ever read."""
    sidx_path, sidx_node, image_bin = "", None, None
    videos = images = scenes = 0
    for fpath, _ino, node in reader.iter_regular_files(min_size=1,
                                                       max_depth=20):
        if fpath.endswith(".sidx") and "/spk/index/" in fpath:
            sidx_path, sidx_node = fpath, node
        elif fpath.endswith("/image.bin"):
            image_bin = node
        elif fpath.endswith("/scene.radium"):
            scenes += 1
        elif fpath.lower().endswith(_IMAGE_EXTS):
            images += 1
        elif node["size"] >= 0x1000:
            try:
                b = reader.peek(node, 12)
            except Exception:
                b = b""
            if len(b) >= 12 and b[4:8] == b"ftyp":
                videos += 1
    return sidx_path, sidx_node, image_bin, videos, images, scenes


def _data_partition_probe(card):
    """``(firmware_rows, asset_rows)`` from the card's data partition.

    Walks browsable partitions largest-first (the data partition carrying the
    sidx + assets is the largest ext partition) and stops at the first one
    with a ``.sidx``; falls back to the largest if none has one."""
    parts = [p for p in card.partitions() if p.browsable]
    parts.sort(key=lambda p: p.size, reverse=True)
    best = None
    for p in parts:
        reader = card.reader(p.index)
        found = _walk_partition(reader)
        if best is None:
            best = (reader, found)
        if found[1] is not None:          # the sidx lives here — this is it
            best = (reader, found)
            break
    if best is None:
        return [], []
    reader, (sidx_path, sidx_node, image_bin, videos, images, scenes) = best

    rows = []
    recs, fmt = {}, None
    if sidx_node is not None:
        try:
            recs, _crc, fmt = sidx_mod.parse_records(
                reader.read_file_bytes(sidx_node))
        except Exception:
            recs, fmt = {}, None
    # Record paths are card-relative ("led_zeppelin_pro/image.bin") — the
    # leading folder is the firmware's own game identifier, reliable even
    # on a renamed card.
    folders = {r.split("/", 1)[0] for r in recs if "/" in r}
    if len(folders) == 1:
        rows.append(("Game folder", next(iter(folders))))
    if recs:
        rows.append(("Validated files", "%s (%s manifest)"
                     % (format(len(recs), ","), fmt)))
    elif sidx_path:
        rows.append(("Validation manifest",
                     os.path.basename(sidx_path) + " (unreadable)"))
    if image_bin is not None:
        rows.append(("Asset container", "image.bin — %s (%s bytes)"
                     % (human_size(image_bin["size"]),
                        format(image_bin["size"], ","))))

    # Counted from the card itself, no Extract needed (David).  Sounds are
    # the one thing that can't be counted here: they're packed inside
    # image.bin and enumerating them means booting the firmware codec
    # engine — that's the Extract path, not a tab probe.
    asset_rows = [
        ("Videos", format(videos, ",")),
        ("Images", format(images, ",")),
        ("Scenes", format(scenes, ",")),
        ("Sounds", "packed inside image.bin — run Extract to decode "
                   "and count them"),
    ]
    return rows, asset_rows


def card_info(path):
    """Image-Info sections for a Spike 2 card image."""
    firmware = [("System", "Stern Spike 2")]
    version, edition = version_from_filename(path)
    if version:
        firmware.append(("Version", version + "  (from the filename)"))
    if edition:
        firmware.append(("Edition", edition))
    partitions = []
    asset_rows = []
    try:
        with CardImage(path) as card:
            fw_rows, asset_rows = _data_partition_probe(card)
            firmware.extend(fw_rows)
            for p in card.partitions():
                partitions.append(
                    ("Partition %d" % p.index,
                     "%s — %s" % (p.label, human_size(p.size))))
    except Exception as e:
        firmware.append(("Card read", "Could not open: %s" % e))
    sections = [("Firmware", firmware)]
    if asset_rows:
        sections.append(("Assets on Card", asset_rows))
    if partitions:
        sections.append(("Partitions", partitions))
    # The Spike 2 audio engine is fixed-rate: every decoded sound is 44.1 kHz
    # (see engine.py's WAV writer) — there is no per-card rate to parse.
    sections.append(("Sound System", [("Sample rate", "44,100 Hz")]))
    return sections
