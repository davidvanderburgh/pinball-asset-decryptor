"""Read-only technical probe of a Spike 2 card for the Image Info tab.

Everything here is derived from sources the app already understands, without
extracting anything: the vendor filename and the on-card ``.sidx`` name (both
carry the firmware version), the MBR partition table, the ``.sidx`` validation
manifest (game folder, indexed-file count, record format, ``image.bin`` size),
the plaintext count words in the ``image.bin`` container header (sounds +
sound fragments), the game ELF's objective namespace (the title's three-letter
code, e.g. ``VEN``) and its adjustment table (how many operator settings and
high-score places the game has), plus on-card asset counts (videos by the
same 12-byte ``ftyp`` sniff the extract uses, images/scenes by name).  Apart
from one pass over the game ELF, the probe walks directory metadata and never
reads more than a magic-sniff of any file, so it stays quick even on a
multi-GB image.
"""

import os
import re
import struct
from collections import Counter

from ...core.image_info import human_size
from . import sidx as sidx_mod
from .explorer import CardImage

# ``<title>_<edition>-<version>.Release.<size>.sdcard.raw`` — Stern's own card
# naming (see formats._title_from_filename).  The version is digits joined by
# underscores ("1_27_0"); anything else after the dash is not a version.  The
# same convention names the on-card ``/spk/index/<...>.sidx``, which is where
# a renamed card still carries its version.
_VERSION_RE = re.compile(r"^(\d+(?:_\d+)*)$")
_EDITIONS = {"le": "LE", "pro": "Pro", "prem": "Premium",
             "premium": "Premium", "se": "SE"}


def version_from_filename(path):
    """``(version, edition)`` parsed from a vendor-named card or sidx, else
    ``(None, None)``.  ``munsters_le-1_27_0.Release.8G.sdcard.raw`` ->
    ``("1.27.0", "LE")``."""
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


def container_counts(head):
    """``(sound_fragments, sounds)`` from the ``image.bin`` header, else
    ``(None, None)``.

    The container header is NOT obfuscated: it opens with its own size
    (0xb0 on most titles, 0x4d0 on the multi-category Metallica remaster)
    and carries two plaintext count words —

      * ``u32 @ 0x5c`` — the sound fragments: every audio piece the booted
        firmware's ``get_asset_descriptor`` resolver can hand out.  On Led
        Zeppelin 1.22 the resolver accepts exactly sids ``0..w5c-1`` (578),
        each landing on a master-directory record, i.e. a physical recording
        (see sfx_names for the chain).  This is NOT the game-code *sound
        request* count — requests sit a level above and chain/share
        fragments, so a tester comparing counts on Venom caught the old
        "Sound requests" label as wrong.  The request tally is not a header
        word at all; it is mined out of the game ELF's own request table by
        :mod:`spike2.sound_requests`, which takes the fragment count from
        here as its sid ceiling.
      * ``u32 @ 0x60`` — the packed cat-0 sounds.  Equals
        ``len(derive_params())`` (the Extract decode count) on every card
        with a cached derive (LZ 1.22 both editions = 549, Elvira 3 = 5597).

    Verified across all 33 vendor images on hand (word @ 0x58 is always 0,
    fragments >= sounds always holds); anything off-pattern returns
    ``(None, None)`` so the caller degrades to the honest "run Extract" row.
    """
    if len(head) < 0x68:
        return None, None
    hdr_size, = struct.unpack_from("<Q", head, 0)
    zero, fragments, sounds = struct.unpack_from("<III", head, 0x58)
    if not (0x68 <= hdr_size <= 0x10000) or hdr_size % 8 or zero != 0:
        return None, None
    if not (0 < sounds <= fragments < 500_000):
        return None, None
    return fragments, sounds


# The game firmware names its objectives/flags ``OB_<CODE>_*`` / ``FG_<CODE>_*``
# with the title's own short code (OB_VEN_*, FG_STR_*, ...) — the same code
# Stern uses in its short version id ("VEN106LE").  A census of those
# prefixes recovers the code from the ELF alone: on all 33 vendor images on
# hand the true code dominates by >=3x over incidental words (VEN 102 vs
# BEAT 20, STR 56 vs CANT 7, ...).  SYS is the shared system namespace.
_TITLE_CODE_RE = re.compile(rb"(?:OB|FG)_([A-Z0-9]{2,4})_")
_TITLE_CODE_STOP = {b"SYS"}


def title_code_from_firmware(fw):
    """The title's short code ("VEN", "STR", "RUSH", ...) mined from the game
    ELF's objective namespace, or ``None`` when no prefix clearly dominates."""
    census = Counter(m.group(1) for m in _TITLE_CODE_RE.finditer(fw))
    for stop in _TITLE_CODE_STOP:
        census.pop(stop, None)
    top = census.most_common(2)
    if not top or top[0][1] < 24:
        return None
    if len(top) > 1 and top[0][1] < 3 * top[1][1]:
        return None
    return top[0][0].decode("ascii")


_VERSION_ID_EDITIONS = {"LE": "LE", "Pro": "PRO", "Premium": "PREM",
                        "SE": "SE"}


def version_id(code, version, edition):
    """Stern's short version id — ``("VEN", "1.06.0", "LE") -> "VEN106LE"``
    (title code + major/minor digits + edition), or ``None`` if the pieces
    don't assemble."""
    if not code or not version:
        return None
    parts = version.split(".")
    if len(parts) < 2:
        return None
    try:
        digits = "%d%02d" % (int(parts[0]), int(parts[1]))
    except ValueError:
        return None
    return code + digits + _VERSION_ID_EDITIONS.get(edition or "", "")


# Loose LCD UI images on the card (same list engine.extract_images uses).
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".webp")


def _walk_partition(reader):
    """One metadata walk of a partition: the ``.sidx`` manifest, ``image.bin``,
    per-category music banks, and on-card asset counts.  Videos are the same
    12-byte ``ftyp`` sniff the extract's video scan does (Spike 2 stores them
    as extensionless ``.asset`` files); nothing larger is ever read."""
    found = {"sidx_path": "", "sidx_node": None, "image_bin": None,
             "image_bin_path": "", "videos": 0, "images": 0, "scenes": 0,
             "music_banks": 0, "game_elves": {}, "video_paths": []}
    for fpath, _ino, node in reader.iter_regular_files(min_size=1,
                                                       max_depth=20):
        base = fpath.rsplit("/", 1)[-1]
        if fpath.endswith(".sidx") and "/spk/index/" in fpath:
            found["sidx_path"], found["sidx_node"] = fpath, node
        elif fpath.endswith("/image.bin"):
            found["image_bin"], found["image_bin_path"] = node, fpath
        elif base.startswith("image-sc") and base.endswith(".bin"):
            found["music_banks"] += 1
        elif base == "game":
            found["game_elves"][fpath] = node
        elif fpath.endswith("/scene.radium"):
            found["scenes"] += 1
        elif fpath.lower().endswith(_IMAGE_EXTS):
            found["images"] += 1
        elif node["size"] >= 0x1000:
            try:
                b = reader.peek(node, 12)
            except Exception:
                b = b""
            if len(b) >= 12 and b[4:8] == b"ftyp":
                found["videos"] += 1
                # The paths too, not just the count — the Compare tab
                # classifies changed files by them.
                found["video_paths"].append(fpath)
    return found


def _game_elf_bytes(reader, found):
    """The game firmware ELF next to ``image.bin`` (the top-level ``game``
    symlink elsewhere on the card doesn't match the sibling path), or ``b""``.
    One bounded read — the ELF is a few tens of MB at most."""
    img_path = found["image_bin_path"]
    if not img_path:
        return b""
    node = found["game_elves"].get(
        img_path.rsplit("/", 1)[0] + "/game")
    if node is None or not (0 < node["size"] <= 256 << 20):
        return b""
    try:
        if reader.peek(node, 4) != b"\x7fELF":
            return b""
        return reader.read_file_bytes(node)
    except Exception:
        return b""


def _adjustment_rows(fw):
    """``[("Adjustments", …), ("High scores", …)]`` from the game ELF's own
    adjustment table, or ``[]`` when this build's table can't be located.

    Both numbers are firmware facts, not card contents: the operator's *chosen*
    settings and the scores actually on the board live in the machine's i2c
    NVRAM, which a card reader never sees.  What the card carries is the table
    the game seeds a fresh machine from, and that table is also the definitive
    list of what the menu offers (a tester asked for both counts).
    """
    try:
        from .adjustments import AdjustmentTable, high_score_names
        table = AdjustmentTable(fw)
    except Exception:
        return []
    # Id 0 is the AD_INVALID placeholder, never an operator-visible setting.
    total = table.count - (1 if table.names[:1] == ["AD_INVALID"] else 0)
    # Count the PLACES off the game's own high-score board (the record table
    # the Defaults tab edits), not the adjustment names that look like score
    # slots.  Counting names undercounts badly wherever a place has no score
    # adjustment of its own: TMNT keeps separate boards for co-op and for
    # 2- and 3-player team play, and only 14 of its 57 places carry an
    # adjustment, so the name census reported 27 against the 57 the Defaults
    # tab lists.  Falling back to the census keeps a build whose board table
    # can't be located reporting something rather than nothing.
    try:
        from .high_scores import HighScoreDefaults
        slots = HighScoreDefaults(fw, table).rows
    except Exception:
        slots = high_score_names(table.names)
    rows = [("Adjustments",
             "%s — operator settings in the machine's menu; the Defaults tab "
             "edits the values a fresh machine starts from"
             % format(total, ","))]
    if slots:
        rows.append(
            ("High scores",
             "%s — high-score and champion places the game keeps (the scores "
             "themselves are stored in the machine, not on the card)"
             % format(len(slots), ",")))
    return rows


def _data_partition_probe(card):
    """``(firmware_rows, asset_rows, sidx_name, title_code)`` from the card's
    data partition.

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
        if found["sidx_node"] is not None:  # the sidx lives here — this is it
            best = (reader, found)
            break
    if best is None:
        return [], [], "", None
    reader, found = best
    sidx_path, sidx_node = found["sidx_path"], found["sidx_node"]
    image_bin = found["image_bin"]

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

    # Counted from the card itself, no Extract needed (David).  The sound and
    # sound-fragment counts are the container header's own plaintext words
    # (see container_counts) — a tester: the old row could only say "run
    # Extract", and asked for the second count separately.
    fragments = sounds = None
    if image_bin is not None:
        try:
            fragments, sounds = container_counts(reader.peek(image_bin, 0x68))
        except Exception:
            fragments = sounds = None

    # One ELF read serves the title code, the adjustment/high-score counts and
    # the sound-request tally, so the extra rows cost a parse rather than
    # another pass over the card.  Read before the asset rows are assembled:
    # the request count belongs beside the other two sound tallies.
    try:
        fw = _game_elf_bytes(reader, found)
    except Exception:
        fw = b""
    requests = None
    if fw and fragments:
        try:
            from .spike2.sound_requests import count_sound_requests
            requests = count_sound_requests(fw, fragments)
        except Exception:
            requests = None

    asset_rows = [
        ("Videos", format(found["videos"], ",")),
        ("Images", format(found["images"], ",")),
        ("Scenes", format(found["scenes"], ",")),
    ]
    if sounds is not None:
        asset_rows.append(
            ("Sounds", "%s — packed in image.bin; Extract decodes them "
                       "to WAVs" % format(sounds, ",")))
        asset_rows.append(
            ("Sound fragments", "%s — audio pieces the firmware can "
                                "resolve and play (the game's sound "
                                "requests chain and share them)"
             % format(fragments, ",")))
        if requests is not None:
            asset_rows.append(
                ("Sound requests", "%s — the calls the game code can make to "
                                   "play audio; each one chains one or more "
                                   "fragments (from the game's own request "
                                   "table, not a header count)"
                 % format(requests, ",")))
    else:
        asset_rows.append(
            ("Sounds", "packed inside image.bin — run Extract to decode "
                       "and count them"))
    if found["music_banks"]:
        asset_rows.append(
            ("Music banks", "%d (per-category image-scNN.bin song banks)"
             % found["music_banks"]))

    title_code = None
    try:
        if fw:
            title_code = title_code_from_firmware(fw)
            rows.extend(_adjustment_rows(fw))
    except Exception:
        title_code = None
    return rows, asset_rows, os.path.basename(sidx_path), title_code


def card_info(path):
    """Image-Info sections for a Spike 2 card image."""
    firmware = [("System", "Stern Spike 2")]
    version, edition = version_from_filename(path)
    version_src = "the filename"
    partitions = []
    asset_rows = []
    sidx_name, title_code = "", None
    try:
        with CardImage(path) as card:
            fw_rows, asset_rows, sidx_name, title_code = \
                _data_partition_probe(card)
            for p in card.partitions():
                partitions.append(
                    ("Partition %d" % p.index,
                     "%s — %s" % (p.label, human_size(p.size))))
    except Exception as e:
        fw_rows = [("Card read", "Could not open: %s" % e)]
    # A renamed card has no version in its filename, but the on-card
    # ``/spk/index/<title>_<edition>-<version>.sidx`` still names it.
    if sidx_name:
        s_version, s_edition = version_from_filename(sidx_name)
        if version is None and s_version is not None:
            version, version_src = s_version, "the card's update index"
        if edition is None:
            edition = s_edition
    if version:
        firmware.append(("Version", "%s  (from %s)" % (version, version_src)))
    if edition:
        firmware.append(("Edition", edition))
    vid = version_id(title_code, version, edition)
    if vid:
        firmware.append(("Version ID", vid))
    firmware.extend(fw_rows)
    sections = [("Firmware", firmware)]
    if asset_rows:
        sections.append(("Assets on Card", asset_rows))
    if partitions:
        sections.append(("Partitions", partitions))
    # The Spike 2 audio engine is fixed-rate: every decoded sound is 44.1 kHz
    # (see engine.py's WAV writer) — there is no per-card rate to parse.
    sections.append(("Sound System", [("Sample rate", "44,100 Hz")]))
    return sections
