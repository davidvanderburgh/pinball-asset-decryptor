#!/usr/bin/env python3
"""mkmulticard.py - build a multi-image Stern Spike 2 SD card for the boot-time code selector (item 90).

One card, several complete game images.  p1 (FAT boot) and p2 (ext4 rootfs) are the
PRIMARY image's, p3 is the primary's games partition verbatim, p4 is the extended
partition grown to the end of the card, p5 (/data) and p6 (/dump) are the primary's,
and p7, p8, ... are each EXTRA image's games partition verbatim.  The selector
(/usr/local/codeselect/) and its one guarded hook line in /etc/init.d/game are
injected into p2 with `debugfs -w`; nothing else on the card is touched.

TWO LAYOUTS (--layout auto|parts|multi).  The card's own kernel (i.MX6, 3.14,
CONFIG_MMC_BLOCK_MINORS=8) gives mmcblk0 eight minors: the whole device and p1..p7, so p7 is
the last partition the machine can open.
  parts  ONE extra image, its games partition copied verbatim as p7 (today's layout; a second
         extra would land on p8, which the machine cannot open - refused unless
         --allow-unreachable, for emulator experiments).
  multi  ANY number of extras: p7 is ONE ext4 partition (label 'multi') holding img1/, img2/,
         ... imgK/, each the COMPLETE file tree of that extra's games partition (spk/, the
         title dir, the game/conagent/data symlinks), populated with `debugfs rdump` from the
         read-only source into a scratch tree and `mke2fs -d`, sized to the sum of the extras'
         used bytes + 10% + 256 MiB (rounded to a MiB); ownership put back with debugfs.  The
         selector's devices are '/dev/mmcblk0p7:img1', '/dev/mmcblk0p7:img2', ...; select.sh
         mounts p7 at /mnt/multi and binds the subdirectory over /games.  Never p8.
  auto   parts for one extra, multi for two or more.

THE VALIDATOR BYPASS (--bypass-validation, and the standalone `bypass --card`).  Every games
tree on the OUTPUT card (p3's title dir, p7's title dir, or each p7/imgN/<title>) gets Stern's
game self/asset validator neutered exactly as the app's Write does (plugins/stern/valpatch.py:
find the routine by signature, `bx lr` at its entry, refresh that tree's .sidx record of the
game file); 'validator: bypassed' / 'validator: none on this build' is printed per tree, the
partition's md5 sidecar is rewritten, and verify reports the bypass state per tree.

MEDIA (--media-dir DIR, item 90 v2).  DIR/media.json (written by selectmedia.py) names per image
an art PNG, an animated GIF, a music WAV and a confirm WAV of its own (any of them null) plus the
move/confirm sounds and the volume; only the referenced files are staged into
/usr/local/codeselect/media on p2 (flat, names ^[A-Za-z0-9._-]+$, PNG <= 1360x768, GIF <= 10 MB /
512x288 / 150 frames, WAV pcm_s16le 44100 Hz 1-2 ch, the whole set <= 96 MB), and images.conf gets
the image lines (image=<device>|<title>|<subtitle>|<art>|<anim>|<music>|<confirm>) and the
sound_move= / sound_confirm= / volume= / mixer_volume= / media= keys.  The line is written only as
wide as it needs to be - 3 fields with no media at all, 6 when no image names a confirm of its own -
and every narrower form stays valid.  An image's own confirm is the sound that plays when THAT image
is chosen; an empty field falls back to the menu-wide sound_confirm=.

THE CARD LOG IS A DEVELOPMENT SWITCH.  `build`/`inject --debug-log` writes `log=/dump/log/codeselect.log`
(CARD_LOG) into images.conf and select.sh then passes the selector `--log` (a fresh file each boot, the
previous boot's kept as .1, 1 MiB at most).  Without the flag - the app never passes it - no log= line is
written, the menu writes nothing to /dump boot after boot, and an inject turns an old debug card's log
off; `inspect` prints `log=off` or the path.

THE TWO JSON SIDECARS (item 90, "load a finished card back into the editor").  Beside
images.conf - never inside media/, never in the media budget, never opened by the selector
(it reads images.conf and the files that names) - `build` and `inject` also stage
  build.json  {"tool", "version", "written", "layout",
               "images": [{"device", "source", "title", "subtitle", "art", "anim", "music",
                           "confirm"}],
               "timeout", "default", "volume", "mixer_volume", "sound_move", "sound_confirm",
               "theme", "colors"}
              'source' is the .raw each image came from - the one thing images.conf cannot
              hold and a rebuild needs.  An `inject` given no --primary/--extra reads the
              card's build.json first and carries the old sources through: an inject must
              never lose provenance.
  media.json  the manifest selectmedia.py wrote for the staged set, VERBATIM (absent when the
              card carries no media); an `inject` without --media-dir carries the card's own
              through byte for byte.
`inspect` reads both back; a card written by an older version (no sidecars) degrades to nulls
and a warning rather than an error.

GAME CODE VERSIONS (item 90, the same-version gate).  plan / build / verify / inspect all print
a VERSION table - one line per image: index, device, title directory, game code version, where
that answer came from and the node board firmware set.  `build` REFUSES a card whose images are
not the same game code unless --allow-version-mismatch is given; the refusal itself is the loud
warning, and it says what the difference costs (VERSION_COST below).  The version is read off
each image, never guessed from a file name, from up to three places that are cross-checked:
  sidx  /spk/index/<pkg>-<M_mm_p>.sidx - Stern's own package name ('turtles_pro-1_59_0.sidx'),
        all three components, and what the code updater speaks.  The AUTHORITY.  (A bare
        '<pkg>.sidx' symlink sits beside it on some cards; it names no version and is skipped.)
  ELF   the game's per-build identity record: a run of pointers to the game code, the model
        name(s), the RELEASE DATE and (on most builds) the title directory, followed by the
        version as a uint16 - high byte major, low byte minor.  MAJOR.MINOR only: turtles_le
        1.58.1 and turtles_pro 1.58.0 both hold 0x013a.  The CROSS-CHECK: located on 46 of the
        46 cards in David's library, agreeing with the .sidx name on 45 (dungeons_and_dragons_le
        1.00.0's record says 0.01 - a real disagreement, reported, never silently resolved).
  hex   the title directory's node board firmware ('*-1_33_0.hex' on TMNT 1.59, '*-1_19_0.hex'
        on 1.58).  A DIFFERENT number from the game code version, so it is reported on its own
        line and never used as one - but it is the one difference that needs a service call:
        the machine records the running build's node firmware version at every boot, so images
        with different sets can reflash the node boards on every swap.
  NVM   /data's nv/<title>/NVM would carry the machine's own record - but /data is empty on
        every one of the 49 cards checked (it is written on the machine, not by the factory),
        so nothing here depends on it.

Run under WSL/Linux (needs debugfs, e2fsck, mke2fs, sfdisk, fdisk from e2fsprogs/util-linux);
the pure-python parts (layout, MBR/EBR bytes, hook, images.conf, media checks, the version
record decoder) are tested on Windows.

  mkmulticard.py plan        --primary P --extra E [--extra E2 ...] [--layout L] [--allow-unreachable]
        print the layout, byte totals and whether it fits Stern's 16G / 32G sizes; writes nothing
  mkmulticard.py check-stock IMG
        regenerate IMG's own MBR entries + EBR chain with this writer and byte-compare them
  mkmulticard.py build       --primary P --extra E [...] --out OUT --selector-dir DIR
                             [--layout auto|parts|multi] [--media-dir DIR] [--bypass-validation]
                             [--allow-version-mismatch]
                             [--titles "T0;T1;..."] [--subtitles "S0;S1;..."] [--timeout N]
                             [--default N] [--volume V] [--machine-volume] [--mixer-volume M] [--conf FILE]
                             [--theme NAME] [--color ROLE=RRGGBB ...]
                             [--no-inject] [--dd] [--force] [--workdir DIR] [--allow-unreachable]
        write the sparse OUT (partition ranges copied, MBR entries + EBR chain regenerated; for
        the multi layout the p7 image is built first), then inject DIR/{codeselect,select.sh
        [,font.ttf]} + the media + a generated images.conf + the hooked /etc/init.d/game into
        p2, record md5 sidecars (OUT.p2.md5, and OUT.pN.md5 for every partition the bypass or
        the multi build wrote), and apply the bypass when asked
  mkmulticard.py inject      --card OUT --selector-dir DIR [--media-dir DIR] [--conf FILE]
                             [--primary P] [--extra E ...] [...]
        redo only the p2 injection on an existing multi card (idempotent: re-extract, rm+write,
        verify); without --media-dir the card's media directory, its media.json and the conf's
        media fields are carried through; --primary/--extra are RECORDED in build.json and
        nothing is read from them (without them the card's own provenance is carried through);
        the p2 sidecar is rewritten
  mkmulticard.py inspect     --card X [--json] [--media-out DIR]
        read a finished card back with no mounts and no writes: the table, the menu (images.conf),
        the provenance (build.json), the media (media.json + the files on p2) and every games
        tree's validator state.  A human table by default; --json prints ONE object on stdout
        (the GUI's 'Load card' fills its fields from it) and --media-out DIR extracts the card's
        media directory + media.json into DIR (the flat layout --media-dir reads back), so the
        menu can be previewed and re-injected without a rebuild.  Exit 0 with the report, 2 when
        the file is not a Spike 2 card or carries no selector
  mkmulticard.py bypass      --card OUT
        apply the validator bypass to every games tree on an existing card (this is what fixes
        a card that shows GAME VALIDATION ERROR without a rebuild); sidecars rewritten
  mkmulticard.py verify      --card OUT --primary P --extra E [...] [--selector-dir DIR] [--media-dir DIR]
        table parse-back (own parser + sfdisk -d), md5 of every copied range vs its source (or
        vs its OUT.pN.md5 sidecar when the tool wrote into it - p2 always, and reported as
        'patched' with the /etc/init.d/game diff, the selector file list and the media list),
        e2fsck -fn of every ext4 partition, root listing + validator state of every games tree,
        PASS/FAIL
  mkmulticard.py selftest DIR
        synthetic 10 MiB cards -> 3-image parts card with injection + media -> every check above;
        a 3-image multi card with synthetic games trees (symlinks, ownership, debugfs ls of
        p7/img1) and the bypass on it; in DIR

Every OUTPUT path is explicit.  The tool refuses to overwrite an existing output without
--force, refuses any output under /mnt/d/Pinball/images (David's card library - after
resolving symlinks and junctions, since the repo's own images/ is a link into it) and refuses
an output equal to one of its inputs - a flag whose value turned out to be an output has
destroyed a card image in this project before.

LAYOUT WRITTEN (512-byte sectors; every number was read off the stock cards, see
tools/spike2_emu/codeselect/DESIGN.md):
  sectors 0..8191   copied verbatim from the primary (MBR bootstrap + disk id; u-boot.imx at
                    sectors 2..655), then the four MBR entries are rewritten with the same
                    CHS convention (H=4, S=32, capped at cylinder 1023 = 03 e0 ff)
  p1 p2 p3          verbatim from the primary at the primary's LBAs (8192 / 24576 / 712704)
  p4 (0x0f)         extended container: same start as the primary's, count grown to the last logical
  EBR1 p5, EBR2 p6  the primary's logicals (data, dump) at their exact LBAs; EBR2 gets the link to p7
  EBRk p(6+k)       one games partition per --extra: EBR at prev_end+1, partition at the next 1 MiB
                    boundary (exactly how the stock EBR2/p6 sit after p5), size = the extra's p3
                    sector count verbatim (13402110 for an 8G source)
  image size        last logical end + 1 + 2 tail sectors (every stock card ends 2 sectors after p6)
  Two 8G images = 28755968 sectors = 14,723,055,616 B (fits a 16G card); three would need a 32G
  card AND put the third on p8, which the machine cannot open (see above).
"""
import argparse
import collections
import difflib
import hashlib
import json
import os
import re
import shutil
import stat as statmod
import struct
import subprocess
import sys
import tempfile
import threading
import time

#: The repo root (tools/spike2_emu/../..): the validator bypass and the ext4 reader are the
#: app's own plugins/stern modules, imported lazily so the pure parts need no package.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: This tool's own version, stamped into build.json so a card says what wrote it.  Bump it when
#: the sidecar's SHAPE changes; a reader must accept an older (or missing) one.
#: 1.1 added each image's "title_dir" / "version" / "node_fw_version" (item 90's version gate).
#: 1.2 added trees.json beside it (item 93: what is on every tree, so `update` writes only what changed).
VERSION = "1.2"

SECTOR = 512
HEADS, SPT = 4, 32          # geometry the stock CHS bytes decode with (p1: 64/0/1 .. 191/3/32)
ALIGN = 2048                # every stock partition start is 1 MiB aligned
EXT_TYPES = (0x05, 0x0f)
TAIL = 2                    # stock: image ends 2 sectors after the extended partition
PRE_P1 = 8192               # stock: p1 starts at 8192; u-boot occupies sectors 2..655
CHUNK = 8 << 20
STERN_SIZES = collections.OrderedDict([("8G", 7861174272), ("16G", 15494807552), ("32G", 30359420928)])
STOCK_P1 = (0x0C, 8192, 16384)
STOCK_P2 = (0x83, 24576, 688128)
# The card's kernel (i.MX6, 3.14, CONFIG_MMC_BLOCK_MINORS=8): mmcblk0 + p1..p7 are the only
# minors it allocates, so /dev/mmcblk0p8 never exists on the machine however valid the table.
MMC_BLOCK_MINORS = 8
LAST_REACHABLE_PART = MMC_BLOCK_MINORS - 1          # p7

# ---- what goes on the card -----------------------------------------------------------------
SELECT_DIR = "/usr/local/codeselect"
GAME_SCRIPT = "/etc/init.d/game"
#: Where a --debug-log card's selector writes its diagnostics (images.conf log=).  Without the
#: flag no log= line is written and the menu writes NOTHING to /dump, boot after boot: the card
#: log is for development sessions, never a card the app builds.  With it the selector starts
#: the file afresh each boot (the previous boot's is kept as .1) and writes at most 1 MiB.
CARD_LOG = "/dump/log/codeselect.log"
DEVICE_FMT = "/dev/mmcblk0p%d"
HOST_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
PKILL_LINE = "pkill boot_display "            # the trailing space is Stern's; the anchor is exact
IF_LINE = "if [ -f $GAMES_PATH/game ]; then"
HOOK_LINES = [
    "",
    "# codeselect: boot-time code selector (item 90) - runs the menu and remounts /games",
    "if [ -x /usr/local/codeselect/select.sh ]; then",
    "\t/usr/local/codeselect/select.sh",
    "fi",
]
# staged name -> (card name, mode, required)
SELECTOR_FILES = collections.OrderedDict([
    ("codeselect", ("codeselect", 0o755, True)),
    ("select.sh", ("select.sh", 0o755, True)),
    ("font.ttf", ("font.ttf", 0o644, False)),
])
FORBIDDEN_OUTPUT_PREFIXES = ("/mnt/d/Pinball/images", "D:/Pinball/images", "D:\\Pinball\\images")

# ---- media (item 90 v2) --------------------------------------------------------------------
MEDIA_DIR = SELECT_DIR + "/media"
MEDIA_MANIFEST = "media.json"                 # selectmedia.py writes it; --media-dir reads it
#: The two JSON files staged BESIDE images.conf (item 90, loading a card back).  They are not
#: media: they never go into MEDIA_DIR (where the selector scans), never count against
#: MEDIA_BUDGET and are never subject to the "only what media.json names is staged" rule.
BUILD_MANIFEST = "build.json"
#: trees.json (item 93): what is on every games tree - every file's sha256/size/mode/owner,
#: the source's stamp, which partitions were written in place, a DIRTY flag while an update
#: runs.  Beside build.json; carried through every inject byte for byte like media.json.
TREES_MANIFEST = "trees.json"
SIDECAR_MANIFESTS = (BUILD_MANIFEST, MEDIA_MANIFEST, TREES_MANIFEST)
#: 'codeselect 2.1 - Spike 2 boot-time code selector' lives in the binary's .rodata
SELECTOR_VERSION_RE = re.compile(rb"codeselect (\d+(?:\.\d+)+)")
SELECTOR_VERSION_MAX = 8 << 20                # do not read a huge file just to sniff a version
MEDIA_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
#: The whole set on p2 (194 MB free on a stock rootfs; inject_p2 refuses against
#: the REAL free space).  These four agree with selectmedia.py's contract - a
#: test pins them together.  5 s at 30 fps is 150 frames, ~7.7 MB for a busy
#: clip at 512x288 (David, 2026-09-03: original fps, 5 s clips).
MEDIA_BUDGET = 96 << 20
PNG_MAX = (1360, 768)                         # the panel; the tools pre-scale
GIF_MAX = (512, 288)
GIF_MAX_FRAMES = 150
GIF_MAX_BYTES = 10 << 20                      # 10 MiB
WAV_RATE = 44100
P2_FREE_MARGIN = 8 << 20                      # never fill p2 to the last block
#: images.conf v2: up to 16 images; a device is '/dev/mmcblk0pN' (parts layout),
#: '/dev/mmcblk0pN:<subdir>' (multi layout) or the emulator's 'pN' / 'pN:<subdir>' tokens.
MAX_IMAGES = 16
DEVICE_RE = re.compile(r"^(/dev/mmcblk0p|p)(\d+)(?::([A-Za-z0-9._-]+))?$")
CONF_KEYS = ("default", "timeout", "font", "sound_move", "sound_confirm", "volume", "mixer_volume", "media",
             "theme", "machine_volume")

#: THE MACHINE'S OWN VOLUME (images.conf volume=machine + machine_volume=<store>|<key>|<default>):
#: the selector plays at the MASTER VOLUME SETTING the owner set on the coin door, read off the
#: card's /data/nv/<title>/NVM mirror of the machine's settings (a ring of generation files of
#: 44-byte records keyed by SHA1 of the menu caption - the same key on every version of a title,
#: checked on TMNT and Godzilla).  The default is the title's built-in level (factory_volume) for
#: a machine that has no store yet.  David, 2026-09-03: "it should follow the set volume of the
#: actual machine".
MACHINE_VOLUME_CAPTION = "MASTER VOLUME SETTING"
MACHINE_VOLUME_KEY = hashlib.sha1(MACHINE_VOLUME_CAPTION.encode("ascii")).hexdigest()
MACHINE_VOLUME_STORE = "/data/nv/%s/NVM"

#: THE MENU'S COLOUR THEMES: codeselect/themes.json is the one definition - the selector compiles
#: it in (gen_themes.py -> theme_table.h at build time) and this tool and the app read it as is.
#: images.conf picks one with theme=<name> and may put single colours on top with
#: color_<role>=RRGGBB; theme=custom is the default theme plus those overrides, which is what
#: "make your own theme" in the app writes (every role spelled out).
THEMES_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codeselect", "themes.json")
CUSTOM_THEME = "custom"
COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_THEMES = None


def boot_themes():
    """themes.json, parsed once -> {'roles': [...], 'labels': {role: text}, 'default': name,
    'themes': [{'name', 'title', 'about', 'colors': {role: rrggbb}}]}.  Refused when the file
    is missing or not a themes file: the selector would not build from it either."""
    global _THEMES
    if _THEMES is None:
        try:
            with open(THEMES_JSON, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError) as exc:
            raise Refused("cannot read the menu themes (%s): %s" % (THEMES_JSON, exc))
        roles = list(doc.get("roles") or [])
        themes = list(doc.get("themes") or [])
        names = [t.get("name") for t in themes]
        if not roles or not themes or doc.get("default") not in names:
            raise Refused("%s: no roles, no themes, or a default that is not one of them" % THEMES_JSON)
        for t in themes:
            colors = t.get("colors") or {}
            if sorted(colors) != sorted(roles) or not all(COLOR_RE.match(str(v)) for v in colors.values()):
                raise Refused("%s: theme %r does not name every role as RRGGBB" % (THEMES_JSON, t.get("name")))
            t["colors"] = {r: COLOR_RE.match(str(colors[r])).group(1).lower() for r in roles}
        _THEMES = {"roles": roles, "labels": dict(doc.get("labels") or {}), "default": doc["default"],
                   "themes": themes}
    return _THEMES


def theme_names():
    """The built-in themes' names, in the file's order (the default first)."""
    return [t["name"] for t in boot_themes()["themes"]]


def theme_colors(name):
    """A built-in theme's {role: rrggbb}, or None for a name that is not one ('custom' included)."""
    for t in boot_themes()["themes"]:
        if t["name"] == name:
            return dict(t["colors"])
    return None


def check_theme(theme):
    """A theme= value for images.conf: a built-in's name or 'custom', lower case; '' / None -> None
    (no key written, the selector's default).  Anything else is refused - a typo on the command
    line should be heard here, not read off the machine's log."""
    t = (theme or "").strip().lower()
    if not t:
        return None
    if t != CUSTOM_THEME and t not in theme_names():
        raise Refused("theme %r is not one of %s, or %s" % (theme, ", ".join(theme_names()), CUSTOM_THEME))
    return t


def check_colors(colors):
    """{role: RRGGBB} for images.conf: every role one of themes.json's, every value six hex digits
    (a leading '#' dropped), lower case; None / {} -> {}."""
    out = {}
    roles = boot_themes()["roles"]
    for role, val in (colors or {}).items():
        if role not in roles:
            raise Refused("color_%s: not a colour role (%s)" % (role, ", ".join(roles)))
        m = COLOR_RE.match(str(val).strip())
        if not m:
            raise Refused("color_%s=%r: not RRGGBB" % (role, val))
        out[role] = m.group(1).lower()
    return out


def parse_color_flags(values):
    """``--color ROLE=RRGGBB`` values (a list, or None) -> {role: value}, unchecked."""
    out = {}
    for v in values or []:
        role, sep, val = str(v).partition("=")
        if not sep:
            raise Refused("--color %r: expected ROLE=RRGGBB" % (v,))
        out[role.strip()] = val.strip()
    return out


#: An image's own media, in the order the images.conf line carries it after the device, the title
#: and the subtitle.  `confirm` is that image's own confirm sound; an empty one falls back to the
#: menu-wide sound_confirm=.  Everything that builds or reads a media row measures itself against
#: these two, so widening the line again is one edit here plus the staging.
MEDIA_FIELDS = ("art", "anim", "music", "confirm")
MEDIA_ROW = ("",) * len(MEDIA_FIELDS)

# ---- the multi layout ----------------------------------------------------------------------
MULTI_LABEL = "multi"
MULTI_SUBDIR_RE = re.compile(r"^img(\d+)$")
#: The stock games partition's feature set (dumpe2fs of turtles_pro 1.59's p3), so the card's
#: 3.14 kernel mounts p7 exactly as it mounts p3; the four ^ entries are e2fsprogs 1.47 defaults
#: that kernel does not know (metadata_csum_seed, orphan_file) or that p3 does not use.
MULTI_FEATURES = ("has_journal,ext_attr,resize_inode,dir_index,filetype,extent,flex_bg,sparse_super,"
                  "large_file,huge_file,uninit_bg,dir_nlink,extra_isize,"
                  "^metadata_csum,^metadata_csum_seed,^64bit,^orphan_file")
MULTI_SLACK = 0.10                            # size = used * (1 + slack) + headroom, MiB-rounded
MULTI_HEADROOM = 256 << 20
LAYOUTS = ("auto", "parts", "multi", "store")

# ---- game code versions (item 90: the same-version gate) -----------------------------------
#: A games tree's package manifest, '/spk/index/<pkg>-<M_mm_p>.sidx' - Stern's own name for the
#: build ('turtles_pro-1_59_0.sidx').  A card may carry a bare '<pkg>.sidx' SYMLINK beside it;
#: only the regular file names a version, so the symlink is skipped.
SIDX_NAME_RE = re.compile(r"^(?P<pkg>[A-Za-z0-9_.+-]+?)-(?P<ver>\d+_\d+_\d+)\.sidx$")
#: A node board firmware image in the title directory: 'coil4node-LPC1313-1_33_0.hex'.  Every
#: hex in one tree carries the same <M_mm_p>; that number is what the machine records per boot.
NODE_FW_RE = re.compile(r"^(?P<base>.+)-(?P<ver>\d+_\d+_\d+)\.hex$", re.I)
#: The per-build identity record in the game ELF's data segment: a run of consecutive pointers
#: to short printable strings (the game code, the model name(s), the RELEASE DATE and, on most
#: builds, the title directory) followed by the version as a uint16 - high byte major, low byte
#: minor, exactly what the firmware's own '%c%d.%02d.%d' banner prints.  There is no third
#: (patch) component in this record: turtles_le 1.58.1 and turtles_pro 1.58.0 both hold 0x013a.
#: Verified against all 46 cards in David's library (see the module docstring's VERSIONS note).
IDENT_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
IDENT_DATE_RE = re.compile((r"^" + IDENT_MONTH + r"[a-z]*\.?\s{1,2}\d{1,2},?\s\d{4}$").encode(), re.I)
IDENT_MAX_STR = 80                            # a longer "string" is not one of this record's
IDENT_MAX_VER = 0x6400                        # major <= 99...
IDENT_MAX_MINOR = 99                          # ...and minor <= 99, so 0x4cf0 (a pointer) is out
IDENT_MIN_RUN = 2                             # a lone pointer is a table entry, not this record
#: The record sat in the LAST PT_LOAD on all 46 cards measured.  A build that put it elsewhere
#: falls back to scanning the whole file - but only for a game ELF small enough that the scan
#: costs seconds; the biggest in the library is rush_le's 190 MB, and a tool must not hang.
IDENT_FULL_SCAN_MAX = 32 << 20


class Refused(Exception):
    """A path or an input the tool will not act on."""


def say(msg):
    print("[card] " + msg, flush=True)


# ============================================================================= the work meter
#: One line no more often than this while a long step runs.  The GUI reads them to move its
#: bar and never puts them in the log, so they are cheap - but a line per chunk of an 8 MiB
#: copy is thousands of them, and a pipe that is being read a line at a time is a real cost.
PROGRESS_EVERY = 1.0

#: How often a metered child's own write counter is sampled (one small /proc read).
PROGRESS_SAMPLE = 0.5


class Progress:
    """THE BUILD'S ONE WORK METER - bytes moved out of bytes to move, printed as a line the
    GUI parses and a person can read.

    A build is minutes to an hour and until now said nothing about how far along it was: the
    copy printed its own MB/s per partition, the debugfs extraction printed one line per image
    when it FINISHED, and neither knew about the other, so there was no number for the whole
    run (David: "I have no idea what's going on or when it's supposed to be done").

    The budget is in BYTES, taken from the plan before anything is written - the extraction
    out of every extra's games partition, the mke2fs that writes them back into p7, and every
    partition range of the image copy.  Bytes are the only unit all three share.  They do NOT
    move at the same speed (debugfs onto a Windows drive is slower per byte than a raw copy),
    so the bar is not linear in TIME; it is honest about work, and the estimate that follows
    it comes from the rate actually observed, which is what makes it converge.

    `done` is the bytes of finished sub-steps; `live` is the one now running, capped at its
    own budget so a child that writes more than its size (metadata) cannot run the total past
    100%.  Nothing ever goes backwards."""

    def __init__(self):
        self.total = 0
        self.done = 0
        self.live = 0
        self.budget = 0
        self.stage = ""
        self._last = 0.0
        self._shown = -1

    def start(self, total, stage=""):
        self.total, self.done, self.live, self.budget = max(0, int(total)), 0, 0, 0
        self.stage = stage
        self._last, self._shown = 0.0, -1
        if self.total:
            self.emit(force=True)

    @property
    def on(self):
        return self.total > 0

    @property
    def at(self):
        return min(self.total, self.done + min(self.live, self.budget or self.live))

    def step(self, stage, budget=0):
        """A new sub-step: whatever the last one was still holding is banked first, so a step
        that ends early or writes less than its budget cannot leave the meter short."""
        self.done = min(self.total, self.done + self.budget)
        self.live, self.budget, self.stage = 0, max(0, int(budget)), stage
        self.emit(force=True)

    def finish(self):
        """The writing is over: whatever the byte estimates missed, the meter reads 100%.  A
        bar that stops at 96% and then the run ends is a bar nobody trusts again."""
        if self.on:
            self.done, self.live, self.budget = self.total, 0, 0
            self.stage = "done"
            self.emit(force=True)

    def add(self, n):
        """Bytes finished outright (a copy loop counts its own)."""
        self.done = min(self.total, self.done + max(0, int(n)))
        self.emit()

    def sample(self, n):
        """The running sub-step has written `n` bytes in total so far."""
        if n is not None and n > self.live:
            self.live = int(n)
            self.emit()

    def emit(self, force=False):
        if not self.on:
            return
        now = time.monotonic()
        if not force and now - self._last < PROGRESS_EVERY:
            return
        at = self.at
        pct = 100.0 * at / self.total
        if not force and int(pct * 10) == self._shown:
            return
        self._last, self._shown = now, int(pct * 10)
        print("[card] progress %d/%d %.1f%% %s" % (at, self.total, pct, self.stage), flush=True)


#: The build's meter.  Idle (``total`` 0) unless a build started it, so every other subcommand
#: and every direct caller of the copy helpers prints exactly what it printed before.
PROGRESS = Progress()


def build_work_bytes(plan):
    """The bytes a build of `plan` will move: the multi layout's extraction out of the sources
    and the mke2fs that writes them back, then every range of the image copy."""
    if plan.layout == "store":
        total = PRE_P1 * SECTOR + sum(p.count * SECTOR for p in plan.prims + plan.logs if p.num != 3)
        total += (plan.store_src_count or 0) * SECTOR
        if plan.store_unique:
            total += sum(plan.store_unique[1:])
        return total
    total = PRE_P1 * SECTOR + sum(p.count * SECTOR for p in plan.prims + plan.logs)
    if plan.layout == "multi" and plan.multi_used:
        total += 2 * plan.multi_used
    return total


def proc_written(pid):
    """Bytes the process has written so far, or None.

    ``wchar`` and not ``write_bytes``: the first counts what the process handed to write(2),
    the second what reached a block device - and the tree these children write is usually on
    a Windows drive through DrvFs, where the block counter stays at zero for ever."""
    try:
        with open("/proc/%d/io" % pid, "rb") as f:
            for line in f:
                if line.startswith(b"wchar:"):
                    return int(line.split(b":")[1])
    except (OSError, ValueError):
        return None
    return None


def run_metered(argv, meter=None, tick=PROGRESS_SAMPLE):
    """``subprocess.run(argv, capture)`` with the meter following the child's own write
    counter -> (rc, stdout bytes, stderr bytes).

    The pipes are drained by threads rather than at the end: debugfs prints a line per entry
    it cannot chown, which on a games tree is tens of thousands of them, and a child whose
    pipe fills while the parent is sleeping in a poll loop deadlocks."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = {}

    def drain(key, pipe):
        try:
            out[key] = pipe.read()
        except Exception:                               # noqa: BLE001  - pipe closed under us
            out[key] = out.get(key, b"")
    threads = [threading.Thread(target=drain, args=(k, p), daemon=True)
               for k, p in (("out", proc.stdout), ("err", proc.stderr))]
    for t in threads:
        t.start()
    while proc.poll() is None:
        if meter is not None and meter.on:
            meter.sample(proc_written(proc.pid))
        time.sleep(tick)
    for t in threads:
        t.join()
    return proc.returncode, out.get("out", b""), out.get("err", b"")


# ============================================================================= table bytes
def chs(lba):
    c, r = divmod(lba, HEADS * SPT)
    h, s = divmod(r, SPT)
    s += 1
    if c > 1023:
        c, h, s = 1023, HEADS - 1, SPT
    return bytes((h, (s & 0x3f) | ((c >> 2) & 0xc0), c & 0xff))


def entry(ptype, start, count, chs_base=0):
    """16-byte table entry. `start` goes in the LBA field as given (relative inside an EBR);
    CHS bytes are derived from the absolute LBA chs_base+start (all capped past cylinder 1023)."""
    if not ptype:
        return bytes(16)
    a = chs_base + start
    return bytes((0,)) + chs(a) + bytes((ptype,)) + chs(a + count - 1) + struct.pack("<II", start, count)


def align_up(x, a=ALIGN):
    return (x + a - 1) // a * a


class Geometry:
    """One card's partition table: the MBR primaries and the EBR chain.

    prim     [(num, type, start, count)]                  kernel numbers 1..4
    ext      (start, count) of the 0x05/0x0f container or None
    logical  [(ebr_lba, type, start_abs, count)]          kernel numbers 5, 6, ...
    mbr      the 512-byte MBR (bootstrap + disk id are reused as the template)
    ebr_raw  {ebr_lba: 512 bytes} as read (check-stock compares against these)
    """

    def __init__(self, size, mbr, prim, ext, logical, ebr_raw=None, path=None):
        self.size, self.mbr, self.prim, self.ext, self.logical = size, mbr, list(prim), ext, list(logical)
        self.ebr_raw = ebr_raw or {}
        self.path = path

    @property
    def sectors(self):
        return self.size // SECTOR

    @classmethod
    def from_file(cls, path):
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            def read_sector(lba):
                f.seek(lba * SECTOR)
                return f.read(SECTOR)
            return cls.from_reader(size, read_sector, path)

    @classmethod
    def from_reader(cls, size, read_sector, path=None):
        mbr = read_sector(0)
        if len(mbr) != SECTOR or mbr[510:512] != b"\x55\xaa":
            raise Refused("%s: no MBR signature" % (path or "image"))
        prim, ext, logical, ebr_raw = [], None, [], {}
        for i in range(4):
            e = mbr[0x1BE + 16 * i:0x1BE + 16 * i + 16]
            t = e[4]
            st, cnt = struct.unpack_from("<II", e, 8)
            if t and cnt:
                prim.append((i + 1, t, st, cnt))
                if t in EXT_TYPES and ext is None:
                    ext = (st, cnt)
        if ext:
            base = ext[0]
            cur, seen = base, set()
            while cur not in seen and cur * SECTOR < size:
                seen.add(cur)
                eb = read_sector(cur)
                if len(eb) != SECTOR or eb[510:512] != b"\x55\xaa":
                    break
                ebr_raw[cur] = eb
                e1, e2 = eb[0x1BE:0x1CE], eb[0x1CE:0x1DE]
                t = e1[4]
                rel, cnt = struct.unpack_from("<II", e1, 8)
                lt = e2[4]
                lrel, _lcnt = struct.unpack_from("<II", e2, 8)
                if t and cnt:
                    logical.append((cur, t, cur + rel, cnt))
                if not (lt in EXT_TYPES and lrel):
                    break
                cur = base + lrel
        return cls(size, mbr, prim, ext, logical, ebr_raw, path)

    def part(self, n):
        """(type, start, count) by kernel number: 1-4 primaries, 5.. logicals in chain order."""
        if n <= 4:
            for i, t, st, cnt in self.prim:
                if i == n:
                    return (t, st, cnt)
            raise Refused("%s: no primary partition %d" % (self.path or "image", n))
        if n - 5 >= len(self.logical):
            raise Refused("%s: no logical partition %d" % (self.path or "image", n))
        _e, t, st, cnt = self.logical[n - 5]
        return (t, st, cnt)

    def numbers(self):
        return [n for (n, _t, _s, _c) in self.prim] + [5 + i for i in range(len(self.logical))]

    def shape_issues(self):
        """Why this is not a stock-shaped Spike 2 card (empty list = it is)."""
        out = []
        nums = [n for (n, _t, _s, _c) in self.prim]
        if nums != [1, 2, 3, 4]:
            out.append("primaries are %r, expected [1, 2, 3, 4]" % (nums,))
            return out
        if self.part(1) != STOCK_P1:
            out.append("p1 is %r, stock is %r" % (self.part(1), STOCK_P1))
        if self.part(2) != STOCK_P2:
            out.append("p2 is %r, stock is %r" % (self.part(2), STOCK_P2))
        if self.ext is None:
            out.append("p4 is not an extended partition")
        if len(self.logical) < 2:
            out.append("only %d logical partition(s); stock has p5 (data) and p6 (dump)" % len(self.logical))
        return out


# ============================================================================= the plan
Part = collections.namedtuple("Part", "num ptype start count src src_start ebr")


class Plan:
    """Where every byte of the output comes from.

    prims  [Part] p1, p2, p3 (ebr None)      logs [Part] p5, p6, p7, ... (ebr = their EBR's LBA)
    images [Part] the partitions holding games trees, in order: p3, p7, p8, ... (parts layout)
           or p3, p7 (multi layout)
    trees  [(Part, subdir|None)] every games tree in selector index order - the unit the
           conf, the bypass and verify's root listing work on; subdir is 'img1', 'img2', ...
           for the multi layout's p7 and None for a whole-partition tree
    layout 'parts' (each extra's games partition verbatim as p7, p8, ...), 'multi' (one
           ext4 p7 holding img1/, img2/, ... - see the module docstring) or 'store' (item 95:
           the primary's own p3 grown to hold the extras as img1/, img2/, ... beside its tree
           and one .blobs/ store every file of every tree is a hardlink into; p5/p6 re-laid
           after it, no p7)
    """

    def __init__(self, primary_geom, extra_geoms, primary=None, extras=None, layout="parts",
                 multi_sectors=None, multi_subdirs=None, multi_src=None, store_sectors=None):
        P = primary_geom
        if P.ext is None or len(P.logical) < 1:
            raise Refused("%s: no extended partition / logical chain" % (primary or "primary"))
        for n in (1, 2, 3):
            P.part(n)
        if layout not in ("parts", "multi", "store"):
            raise Refused("layout %r is not 'parts', 'multi' or 'store'" % (layout,))
        self.layout = layout
        self.primary, self.extras = primary, list(extras or [None] * len(extra_geoms))
        self.primary_geom, self.extra_geoms = P, list(extra_geoms)
        self.ext_base = P.ext[0]
        self.prims = [Part(n, P.part(n)[0], P.part(n)[1], P.part(n)[2], primary, P.part(n)[1], None)
                      for n in (1, 2, 3)]
        self.logs = []
        num = 5
        for ebr, t, st, cnt in P.logical:
            self.logs.append(Part(num, t, st, cnt, primary, st, ebr))
            num += 1
        prev_end = self.logs[-1].start + self.logs[-1].count - 1
        self.images = [self.prims[2]]
        self.trees = [(self.prims[2], None)]
        self.multi_part = None
        self.multi_subdirs = []
        self.multi_used = None
        self.multi_each = None          # the used bytes of each extra inside p7, in order
        self.store_subdirs = []         # the store layout's extras, 'img1', 'img2', ... inside p3
        self.store_src_count = None     # ...and the primary's own p3 size in sectors (what build copies)
        self.store_unique = None        # per image, the bytes only it brings to the store (plan/build)
        self.store_shared = None        # the bytes the images share by content, stored once
        self.store_meta = None          # the primary's own filesystem overhead inside p3
        self.manifests = None           # the sources' manifests when the plan hashed them
        if layout == "parts":
            for x, xp in zip(self.extra_geoms, self.extras):
                t, xs, xc = x.part(3)
                ebr = prev_end + 1
                st = align_up(ebr + 1)
                p = Part(num, t, st, xc, xp, xs, ebr)
                self.logs.append(p)
                self.images.append(p)
                self.trees.append((p, None))
                num += 1
                prev_end = st + xc - 1
        elif layout == "multi":
            subs = list(multi_subdirs) if multi_subdirs else ["img%d" % (i + 1) for i in range(len(self.extra_geoms))]
            if multi_sectors is None:
                self.multi_each = multi_used_each(self.extras, self.extra_geoms)
                self.multi_used = sum(self.multi_each)
                multi_sectors = multi_size_sectors(self.multi_used)
            if subs:
                ebr = prev_end + 1
                st = align_up(ebr + 1)
                p = Part(num, 0x83, st, int(multi_sectors), multi_src, 0, ebr)
                self.logs.append(p)
                self.images.append(p)
                self.multi_part = p
                self.multi_subdirs = subs
                for s in subs:
                    self.trees.append((p, s))
                num += 1
                prev_end = st + p.count - 1
        else:
            # THE STORE (item 95): the primary's p3 - Stern's own filesystem, copied verbatim -
            # grown to `store_sectors`; the extras live INSIDE it as img1/, img2/, ...; p5 and
            # p6 follow it at the first aligned sectors after (device names, not LBAs, are what
            # fstab and the game use); there is no p7.
            subs = list(multi_subdirs) if multi_subdirs else ["img%d" % (i + 1) for i in range(len(self.extra_geoms))]
            t3, s3, c3 = P.part(3)
            cnt = int(store_sectors) if store_sectors else c3
            if cnt < c3:
                raise Refused("the store cannot be smaller than the primary's games partition (%d < %d sectors)"
                              % (cnt, c3))
            p3 = Part(3, t3, s3, cnt, primary, s3, None)
            self.prims[2] = p3
            self.store_src_count = c3
            self.store_subdirs = subs
            self.images = [p3]
            self.trees = [(p3, None)] + [(p3, s) for s in subs]
            self.ext_base = align_up(s3 + cnt)
            self.logs = []
            num = 5
            prev_end = self.ext_base - 1
            for _ebr0, t, st0, lcnt in P.logical:
                ebr = prev_end + 1
                st = align_up(ebr + 1)
                self.logs.append(Part(num, t, st, lcnt, primary, st0, ebr))
                num += 1
                prev_end = st + lcnt - 1
        self.ext_count = prev_end + 1 - self.ext_base
        self.total = prev_end + 1 + TAIL

    @property
    def total_bytes(self):
        return self.total * SECTOR

    def table(self):
        """[(num, type, start, count)] as a parser should read the output back."""
        return ([(p.num, p.ptype, p.start, p.count) for p in self.prims]
                + [(4, 0x0F, self.ext_base, self.ext_count)]
                + [(p.num, p.ptype, p.start, p.count) for p in self.logs])

    def devices(self):
        return [device_name(p.num, sub) for (p, sub) in self.trees]

    def with_multi_src(self, path):
        """The same plan with the multi layout's p7 sourced from `path` (the built p7 image)."""
        p = Plan(self.primary_geom, self.extra_geoms, self.primary, self.extras, self.layout,
                 self.multi_part.count if self.multi_part else None, self.multi_subdirs or None, path)
        p.multi_used = self.multi_used
        p.multi_each = self.multi_each
        return p

    def fits(self):
        return collections.OrderedDict((k, v - self.total_bytes) for k, v in STERN_SIZES.items())

    def unreachable(self):
        """The image partitions past p7 - present in the table, absent from the machine's /dev."""
        return [p for p in self.images if p.num > LAST_REACHABLE_PART]

    def unreachable_note(self):
        """'' or 'p8/p9 unreachable on the machine' for the plan printout."""
        bad = self.unreachable()
        return "" if not bad else "%s unreachable on the machine" % "/".join("p%d" % p.num for p in bad)


def device_name(num, subdir=None):
    return DEVICE_FMT % num + ((":" + subdir) if subdir else "")


def parse_device(dev):
    """'/dev/mmcblk0p7:img2' / 'p7:img2' -> (7, 'img2'); (n, None) for a whole partition;
    Refused for anything else (a second ':' or an empty/odd subdirectory included)."""
    m = DEVICE_RE.match(dev or "")
    if not m:
        raise Refused("images.conf: device %r is not /dev/mmcblk0pN[:subdir] or pN[:subdir]" % (dev,))
    return int(m.group(2)), m.group(3)


# ---- the multi layout's size --------------------------------------------------------------
def ext_used_bytes(path, offset):
    """(used bytes, total bytes) of the ext2/3/4 filesystem at `offset` in `path`, from its
    superblock alone (64-bit counts honoured).  Refused when there is no superblock there."""
    with open(path, "rb") as f:
        f.seek(offset + 1024)
        sb = f.read(1024)
    if len(sb) < 1024 or struct.unpack_from("<H", sb, 0x38)[0] != 0xEF53:
        raise Refused("%s@%d: no ext4 superblock (not a games partition?)" % (path, offset))
    bs = 1024 << struct.unpack_from("<I", sb, 0x18)[0]
    blocks = struct.unpack_from("<I", sb, 0x4)[0]
    free = struct.unpack_from("<I", sb, 0xC)[0]
    if struct.unpack_from("<I", sb, 0x60)[0] & 0x80:            # INCOMPAT_64BIT: the hi words count
        blocks |= struct.unpack_from("<I", sb, 0x150)[0] << 32
        free |= struct.unpack_from("<I", sb, 0x158)[0] << 32
    return (blocks - free) * bs, blocks * bs


def multi_used_each(extras, extra_geoms):
    """The used bytes of EVERY extra's games partition, in order - what each game costs inside
    p7.  Per image and not just summed, because "which one do I drop" is the question a card
    that does not fit asks."""
    out = []
    for x, g in zip(extras, extra_geoms):
        _t, st, _cnt = g.part(3)
        if x is None:
            raise Refused("the multi layout needs the extra images' paths to size p7")
        out.append(ext_used_bytes(x, st * SECTOR)[0])
    return out


def multi_used_bytes(extras, extra_geoms):
    """Sum of the used bytes of every extra's games partition (what the multi p7 must hold)."""
    return sum(multi_used_each(extras, extra_geoms))


def multi_size_sectors(used_bytes):
    """used + 10% + 256 MiB, rounded up to a MiB, in sectors."""
    size = int(used_bytes * (1 + MULTI_SLACK)) + MULTI_HEADROOM
    size = (size + (1 << 20) - 1) // (1 << 20) * (1 << 20)
    return size // SECTOR


def resolve_layout(layout, n_extra):
    """'auto' -> parts for one extra (or none), multi for two or more."""
    if layout not in LAYOUTS:
        raise Refused("--layout %r: choose one of %s" % (layout, "/".join(LAYOUTS)))
    if layout == "auto":
        return "multi" if n_extra >= 2 else "parts"
    return layout


STORE_META_SLACK = 0.02                    # what the store's own metadata may add to its content
STORE_HEADROOM = 64 << 20                  # ...and the room a content-sized store keeps
STORE_SIZES = ("content",) + tuple(STERN_SIZES)


def store_sectors_for_class(P, extra_geoms, primary, extras, subs, cls):
    """The biggest p3 (in sectors) that keeps a store card inside the Stern `cls` image size
    with p5 and p6 re-laid after it - found by building the plan, since the alignment of the
    EBR chain is the plan's own arithmetic."""
    total = STERN_SIZES[cls] // SECTOR
    _t3, s3, c3 = P.part(3)
    cnt = total - TAIL - s3 - sum(lc for (_e, _t, _s, lc) in P.logical) - ALIGN * (len(P.logical) + 1)
    cnt = max(c3, cnt - cnt % ALIGN)               # never below the primary's own p3 (an 8G class = the stock p3)

    def total_of(n):
        return Plan(P, extra_geoms, primary, extras, "store", multi_subdirs=subs, store_sectors=n).total
    if total_of(c3) > total:
        raise Refused("--size %s: the primary's games partition alone (%s) does not leave room for the store"
                      % (cls, _gb(c3 * SECTOR)))
    while total_of(cnt) > total and cnt - ALIGN >= c3:
        cnt -= ALIGN
    while total_of(cnt + ALIGN) <= total:
        cnt += ALIGN
    return cnt


def measure_sources(paths, cache_dir=None, progress=None):
    """The manifests of these sources' games trees, hashed (or taken from the cache) one after
    another.  A `progress` with a `step` (the tool's own meter) is told which image is being
    read before each one: the app's size strip shows the name and the percentage while the
    compact plan works - 20-30 s of silence for two images otherwise (David: "show the loading
    state in the size bar")."""
    mans = []
    for path in paths:
        if progress is not None and hasattr(progress, "step"):
            progress.step("measuring %s" % os.path.basename(path))
        mans.append(source_tree(path, cache_dir, progress)[0])
    return mans


def measure_total(paths):
    """The meter's budget for :func:`measure_sources`: the used bytes of every source's games
    partition - what hashing reads, near enough (the meter's finish makes up the difference,
    and a cached source adds nothing).  A source without a readable table or superblock counts
    nothing; the plan itself says what is wrong with it."""
    total = 0
    for path in paths:
        try:
            _t3, s3, _c3 = Geometry.from_file(path).part(3)
        except Exception:                                # noqa: BLE001 - not a card: nothing to budget
            continue
        total += _used_bytes_or_none(path, s3 * SECTOR) or 0
    return total


def make_store_plan(primary, extras, size_class=None, store_sectors=None, subdirs=None, cache_dir=None,
                    progress=None):
    """The Plan of a store card (item 95).  With `store_sectors` (a card that exists, or verify)
    nothing is read but the tables; otherwise every source's games tree is hashed (or taken
    from the cache) so the store can be sized by the UNION of the images' unique content: to
    the smallest Stern image size that holds it (the default), to `size_class`, or - 'content'
    - to just what it needs plus a small headroom.  The plan carries the manifests and the
    per-image unique bytes for the size rows."""
    P = Geometry.from_file(primary)
    XG = [Geometry.from_file(x) for x in extras]
    subs = list(subdirs) if subdirs else ["img%d" % (i + 1) for i in range(len(extras))]
    if store_sectors is not None:
        return Plan(P, XG, primary, list(extras), "store", multi_subdirs=subs, store_sectors=int(store_sectors))
    ts = _treesync()
    mans = measure_sources([primary] + list(extras), cache_dir, progress)
    unique, shared = ts.dedup_costs(mans)
    _t3, s3, c3 = P.part(3)
    used3 = _used_bytes_or_none(primary, s3 * SECTOR)
    meta = max(0, used3 - mans[0].tree.bytes()) if used3 is not None else 0
    need = int((meta + sum(unique)) * (1 + STORE_META_SLACK)) + STORE_HEADROOM
    if size_class == "content":
        grow = int(sum(unique[1:]) * (1 + STORE_META_SLACK)) + STORE_HEADROOM
        cnt = c3 + align_up((grow + SECTOR - 1) // SECTOR)
    elif size_class is None:
        fixed = (s3 + TAIL + sum(lc for (_e, _t, _s, lc) in P.logical) + ALIGN * (len(P.logical) + 1)) * SECTOR
        cls = next((k for k, v in STERN_SIZES.items() if v >= fixed + need), None)
        if cls is None:
            raise Refused("the images' unique content (%s) does not fit the biggest Stern image size even stored once"
                          % _gb(sum(unique)))
        cnt = store_sectors_for_class(P, XG, primary, list(extras), subs, cls)
    else:
        if size_class not in STERN_SIZES:
            raise Refused("--size %r: one of %s" % (size_class, "/".join(STORE_SIZES)))
        cnt = store_sectors_for_class(P, XG, primary, list(extras), subs, size_class)
        if cnt * SECTOR < need:
            raise Refused("--size %s: the images' unique content needs %s of p3 and the class leaves %s"
                          % (size_class, _gb(need), _gb(cnt * SECTOR)))
    plan = Plan(P, XG, primary, list(extras), "store", multi_subdirs=subs, store_sectors=cnt)
    plan.manifests = mans
    plan.store_unique = unique
    plan.store_shared = shared
    plan.store_meta = meta
    return plan


def make_plan(primary, extras, layout="auto", multi_sectors=None, multi_src=None, multi_subdirs=None,
              size_class=None, store_sectors=None, cache_dir=None, progress=None):
    """The Plan for these images.  `size_class` ('8G'/'16G'/'32G', item 93's --size) fills the
    multi layout's p7 to the END of that Stern image size instead of its content-sized default,
    so later updates and added images have room without a re-layout; refused when the content
    does not fit the class.  The store layout (item 95) is sized by :func:`make_store_plan`."""
    lay = resolve_layout(layout, len(extras))
    if lay == "store":
        return make_store_plan(primary, extras, size_class, store_sectors, multi_subdirs, cache_dir, progress)
    if size_class == "content":
        size_class = None
    plan = Plan(Geometry.from_file(primary), [Geometry.from_file(x) for x in extras], primary, list(extras),
                lay, multi_sectors=multi_sectors, multi_subdirs=multi_subdirs, multi_src=multi_src)
    if size_class and lay == "multi" and multi_sectors is None:
        if size_class not in STERN_SIZES:
            raise Refused("--size %r: one of %s" % (size_class, "/".join(STERN_SIZES)))
        want = STERN_SIZES[size_class] // SECTOR - TAIL - plan.multi_part.start
        if want < plan.multi_part.count:
            raise Refused("--size %s: the images need %s of p7 and the class leaves %s"
                          % (size_class, _gb(plan.multi_part.count * SECTOR), _gb(max(0, want) * SECTOR)))
        plan = Plan(plan.primary_geom, plan.extra_geoms, primary, list(extras), lay, multi_sectors=want,
                    multi_subdirs=multi_subdirs or plan.multi_subdirs, multi_src=multi_src)
        plan.multi_each = multi_used_each(list(extras), plan.extra_geoms)
        plan.multi_used = sum(plan.multi_each)
    return plan


def check_reachable(plan, allow=False):
    """Refuse a layout the machine cannot boot from: more than one extra puts an image on p8,
    and the card's kernel exposes minors for p1..p7 only (CONFIG_MMC_BLOCK_MINORS=8).  With
    allow=True (--allow-unreachable) the layout is built anyway - the emulator mounts partitions
    by table offset and does not care - but the refusal is the default so a card is never burnt
    for a machine that will boot the primary and nothing else from it."""
    bad = plan.unreachable()
    if not bad or allow:
        return plan
    raise Refused(
        "%d extra images put %s on %s, and p%d is the last partition the card's kernel can open\n"
        "  (i.MX6 3.14, CONFIG_MMC_BLOCK_MINORS=8: mmcblk0 + p1..p7). The machine could never mount\n"
        "  %s; only ONE --extra fits this layout. A 3-image card needs a different layout - two\n"
        "  images inside one partition - which is a design follow-up. --allow-unreachable builds\n"
        "  it anyway (the emulator can run it; the machine cannot)."
        % (len(plan.images) - 1,
           ", ".join("image %d" % i for i, p in enumerate(plan.images) if p in bad),
           "/".join(DEVICE_FMT % p.num for p in bad), LAST_REACHABLE_PART,
           "/".join(DEVICE_FMT % p.num for p in bad)))


def mbr_entries(plan):
    """The 64 bytes at 0x1be: p1 p2 p3 verbatim, p4 = the grown extended container."""
    ents = [entry(p.ptype, p.start, p.count) for p in plan.prims] + [entry(0x0F, plan.ext_base, plan.ext_count)]
    return b"".join(ents)


def mbr_sector(plan, template=None):
    m = bytearray(template if template is not None else plan.primary_geom.mbr)
    m[0x1BE:0x1FE] = mbr_entries(plan)
    m[510:512] = b"\x55\xaa"
    return bytes(m)


def ebr_sector(plan, i):
    """The EBR sector of logical i (0 = p5): its own entry relative to the EBR, and the 0x05 link
    to the next EBR relative to the extended base (LBA = next EBR, count = through the next end)."""
    p = plan.logs[i]
    eb = bytearray(SECTOR)
    eb[0x1BE:0x1CE] = entry(p.ptype, p.start - p.ebr, p.count, chs_base=p.ebr)
    if i + 1 < len(plan.logs):
        nx = plan.logs[i + 1]
        nend = nx.start + nx.count - 1
        eb[0x1CE:0x1DE] = entry(0x05, nx.ebr - plan.ext_base, nend + 1 - nx.ebr, chs_base=plan.ext_base)
    eb[510:512] = b"\x55\xaa"
    return bytes(eb)


def _gb(n):
    return "%.2f GB" % (n / 1e9)


def _used_bytes_or_none(path, offset):
    """The used bytes of the ext4 at `offset` in `path`, or None when there is no superblock
    there (a synthetic test card, an unreadable source)."""
    try:
        return ext_used_bytes(path, offset)[0]
    except Exception:                                    # noqa: BLE001 - any unreadable superblock
        return None


def image_costs(plan):
    """What each game costs on the finished card -> ([(index, device, bytes or None, source)],
    overhead bytes).  See :func:`plan_room` for the third number the strip needs.

    The unit is the USED bytes of each games tree whatever the layout (item 93: a partition's
    free space is ROOM FOR UPDATES, reported apart, not a cost of the game in it); a source
    whose superblock cannot be read (a synthetic card) falls back to its whole partition.  The
    overhead is everything the games and the room do not account for - boot, rootfs, /data,
    /dump and the filesystems' own metadata - so rows + room + overhead add up to the image
    size exactly."""
    devs = plan.devices()
    srcs = [plan.primary] + list(plan.extras)
    rows = []
    if plan.layout == "store":
        # every image costs the bytes only IT brings to the store (item 95); what the images
        # share is stored once and reported apart as `image-size shared`
        uniq = plan.store_unique
        for i, dev in enumerate(devs):
            rows.append((i, dev, uniq[i] if uniq is not None and i < len(uniq) else None,
                         srcs[i] if i < len(srcs) else None))
        room = plan_room(plan)
        return rows, plan.total_bytes - sum(n for _i, _d, n, _s in rows if n) - room
    if plan.multi_part is not None:
        p3 = plan.prims[2]
        used = _used_bytes_or_none(p3.src, p3.src_start * SECTOR) if p3.src else None
        rows.append((0, devs[0], p3.count * SECTOR if used is None else used, srcs[0]))
        each = plan.multi_each
        for i, sub in enumerate(plan.multi_subdirs):
            rows.append((i + 1, devs[i + 1] if i + 1 < len(devs) else sub,
                         each[i] if each is not None and i < len(each) else None,
                         srcs[i + 1] if i + 1 < len(srcs) else None))
    else:
        for i, part in enumerate(plan.images):
            used = _used_bytes_or_none(part.src, part.src_start * SECTOR) if part.src else None
            rows.append((i, devs[i] if i < len(devs) else device_name(part.num),
                         part.count * SECTOR if used is None else used, srcs[i] if i < len(srcs) else None))
    room = plan_room(plan)
    return rows, plan.total_bytes - sum(n for _i, _d, n, _s in rows if n) - room


def plan_room(plan):
    """The bytes free for in-place updates inside the games partitions the plan writes: each
    image partition's size minus its used bytes (0 for one whose superblock cannot be read),
    and the multi p7's slack over its trees."""
    room = 0
    if plan.layout == "store":
        p3 = plan.prims[2]
        if plan.store_unique is not None:
            return max(0, p3.count * SECTOR - sum(plan.store_unique) - (plan.store_meta or 0))
        used = _used_bytes_or_none(p3.src, p3.src_start * SECTOR) if p3.src else None
        return max(0, p3.count * SECTOR - used) if used is not None else 0
    if plan.multi_part is not None:
        p3 = plan.prims[2]
        used = _used_bytes_or_none(p3.src, p3.src_start * SECTOR) if p3.src else None
        room += max(0, p3.count * SECTOR - used) if used is not None else 0
        if plan.multi_used is not None:
            room += max(0, plan.multi_part.count * SECTOR - plan.multi_used)
        return room
    for part in plan.images:
        used = _used_bytes_or_none(part.src, part.src_start * SECTOR) if part.src else None
        room += max(0, part.count * SECTOR - used) if used is not None else 0
    return room


def print_plan(plan):
    print("primary %s (%d bytes)" % (plan.primary, plan.primary_geom.size))
    for x, g in zip(plan.extras, plan.extra_geoms):
        print("extra   %s (%d bytes)" % (x, g.size))
    for w in plan.primary_geom.shape_issues():
        print("WARNING primary: " + w)
    for x, g in zip(plan.extras, plan.extra_geoms):
        for w in g.shape_issues():
            print("WARNING %s: %s" % (os.path.basename(x or "extra"), w))
    print("layout: %s" % plan.layout)
    print("%-4s %-4s %-12s %-12s %-12s %-16s %s" % ("part", "type", "start", "count", "end", "bytes", "source"))
    rows = [(p.num, p.ptype, p.start, p.count, "%s@%d" % (os.path.basename(p.src or "primary"), p.src_start))
            for p in plan.prims]
    rows.append((4, 0x0F, plan.ext_base, plan.ext_count, "(extended container)"))
    for p in plan.logs:
        if plan.multi_part is not None and p.num == plan.multi_part.num:
            src = "multi ext4: " + ", ".join("%s=%s" % (s, os.path.basename(x or "extra"))
                                            for s, x in zip(plan.multi_subdirs, plan.extras))
        else:
            src = "%s@%d" % (os.path.basename(p.src or "image"), p.src_start)
        rows.append((p.num, p.ptype, p.start, p.count, src))
    for n, t, st, cnt, src in rows:
        print("p%-3d 0x%02x %-12d %-12d %-12d %-16d %s" % (n, t, st, cnt, st + cnt - 1, cnt * SECTOR, src))
    for p in plan.logs:
        print("  EBR for p%d at LBA %d" % (p.num, p.ebr))
    if plan.multi_part is not None:
        mp = plan.multi_part
        used = ("sum of used bytes %s + %d%% + %d MiB" % (_gb(plan.multi_used), int(MULTI_SLACK * 100), MULTI_HEADROOM >> 20)
                if plan.multi_used is not None else "size read from the card")
        print("p%d (multi layout): %d trees %s, %d MiB (%s)" % (mp.num, len(plan.multi_subdirs), "/".join(plan.multi_subdirs),
                                                             mp.count * SECTOR >> 20, used))
    if plan.layout == "store":
        p3 = plan.prims[2]
        print("p3 (store layout): %d trees %s inside the primary's games partition, grown from %d to %d MiB%s"
              % (len(plan.trees), ", ".join(["/"] + plan.store_subdirs), (plan.store_src_count or 0) * SECTOR >> 20,
                 p3.count * SECTOR >> 20,
                 (", %s shared by content and stored once" % _gb(plan.store_shared))
                 if plan.store_shared is not None else ""))
    note = plan.unreachable_note()
    print("images: " + ", ".join("%d=%s" % (i, d) for i, d in enumerate(plan.devices()))
          + ("  (%s)" % note if note else ""))
    # WHAT EACH GAME COSTS, in a line of its own.  The GUI draws its size preview off these
    # (a bar with a band per image, so a card that does not fit says which game to drop) and
    # they read the same way in a terminal.  The 'image-size' word is there so the parse
    # cannot pick up a row of the version table, which also starts with an index.
    costs, overhead = image_costs(plan)
    for i, dev, n, src in costs:
        print("image-size %d %s %s %s" % (i, dev, "?" if n is None else n,
                                          os.path.basename(src or "") or "(no source)"))
    # room for updates (item 93): what an in-place `update` can write before the card needs a
    # rebuild - the games partitions' free space.  A word where the index goes, so an older
    # reader of these rows cannot mistake it for an image.
    print("image-size free %d room for updates in the games partitions" % plan_room(plan))
    if plan.layout == "store":
        # what the images have in common and the store holds once (item 95) - NOT on the card,
        # which is the point; a word where the index goes, like the free row
        print("image-size shared %d stored once, shared by content" % (plan.store_shared or 0))
    print("image-size overhead %d boot + rootfs + data + dump + metadata" % max(0, overhead))
    print("image: %d sectors = %d bytes (%s)" % (plan.total, plan.total_bytes, _gb(plan.total_bytes)))
    for k, spare in plan.fits().items():
        print("  fits Stern %-3s image size %d: %s (spare %d)%s" % (k, STERN_SIZES[k], "YES" if spare >= 0 else "NO", spare,
                                                                 (" - " + note) if note else ""))
    if note:
        print("WARNING: %s - the card's kernel exposes p1..p7 only (CONFIG_MMC_BLOCK_MINORS=8); "
              "the machine boots the primary from such a card and nothing else" % note)


# ============================================================================= the hook
def hook_game_script(text):
    """Insert HOOK_LINES into Stern's /etc/init.d/game right after 'pkill boot_display ' and
    before 'if [ -f $GAMES_PATH/game ]; then'.  Idempotent: an already hooked script comes out
    the same.  Anything unexpected about the anchors raises Refused - never a guess."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    text = strip_hook(text)
    lines = text.split("\n")
    pk = [k for k, l in enumerate(lines) if l == PKILL_LINE]
    if len(pk) != 1:
        raise Refused("game script: expected exactly one %r line, found %d" % (PKILL_LINE, len(pk)))
    iff = [k for k, l in enumerate(lines) if l == IF_LINE]
    if len(iff) != 1:
        raise Refused("game script: expected exactly one %r line, found %d" % (IF_LINE, len(iff)))
    i, j = pk[0], iff[0]
    if not (i < j <= i + 2) or any(l.strip() for l in lines[i + 1:j]):
        raise Refused("game script: %r (line %d) is not directly before %r (line %d)" % (PKILL_LINE, i + 1, IF_LINE, j + 1))
    lines[i + 1:i + 1] = HOOK_LINES
    return "\n".join(lines)


def strip_hook(text):
    """Remove one HOOK_LINES block if present (the inverse of hook_game_script)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    lines = text.split("\n")
    n = len(HOOK_LINES)
    for k in range(len(lines) - n + 1):
        if lines[k:k + n] == HOOK_LINES:
            del lines[k:k + n]
            return "\n".join(lines)
    return text


def has_hook(text):
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return strip_hook(text) != text


# ============================================================================= images.conf
def _media_name_ok(name, what):
    """A media file name as it goes into a conf field: flat, ^[A-Za-z0-9._-]+$ (so never a '|',
    a ':' or a '/'), or empty."""
    if name and not MEDIA_NAME_RE.match(name):
        raise Refused("images.conf: %s %r is not a plain media file name (^[A-Za-z0-9._-]+$; no '|', ':' or '/')"
                      % (what, name))
    return name or ""


def _int_range(val, key, lo, hi):
    try:
        v = int(val)
    except (TypeError, ValueError):
        raise Refused("images.conf: bad %s=%r" % (key, val))
    if not (lo <= v <= hi):
        raise Refused("images.conf: %s=%d is outside %d..%d" % (key, v, lo, hi))
    return v


def check_machine_volume(mv):
    """The machine_volume contract for images.conf, validated: None, or {"store": str|None,
    "key": 40 hex, "default": 0-63|None} (extra keys - title, notes - are kept as given)."""
    if not mv:
        return None
    if not isinstance(mv, dict):
        raise Refused("machine_volume must be a dict with store/key/default, not %r" % (mv,))
    out = dict(mv)
    store = out.get("store") or None
    if store and ("|" in store or "\n" in store):
        raise Refused("machine_volume: the store %r may not contain '|' or a newline" % store)
    key = str(out.get("key") or MACHINE_VOLUME_KEY).lower()
    if not re.fullmatch(r"[0-9a-f]{40}", key):
        raise Refused("machine_volume: the key must be 40 hex digits (SHA1 of the caption), not %r" % key)
    default = out.get("default")
    out.update(store=store, key=key,
               default=None if default in (None, "") else _int_range(default, "machine_volume default", 0, 63))
    return out


def render_images_conf(devices, titles=None, subtitles=None, default=0, timeout=15, font=None,
                       media=None, sound_move=None, sound_confirm=None, volume=None, mixer_volume=None,
                       media_dir=None, theme=None, colors=None, machine_volume=None, debug_log=False):
    """images.conf text.  v2 (item 90 media): `media` is one (art, anim, music, confirm) per image
    (names relative to the media dir, '' = none; a 3-tuple without the confirm is accepted).  The
    line is written only as wide as it needs to be: 7 fields when any image names a confirm of its
    own, 6 when some other media is set, else the 3-field form every older selector reads.  The
    global keys follow.  `theme` (a built-in's name or 'custom') and `colors` ({role: RRGGBB}) are
    the menu's colours (see THEMES_JSON); neither is written when not given.  `debug_log` writes
    `log=CARD_LOG` (the selector's diagnostics on the card - a development build only)."""
    devices = list(devices)
    if not devices:
        raise Refused("images.conf: no images")
    if len(devices) > MAX_IMAGES:
        raise Refused("images.conf: %d images; the selector takes at most %d" % (len(devices), MAX_IMAGES))
    for d in devices:
        parse_device(d)
    titles = list(titles or [])
    subtitles = list(subtitles or [])
    media = [tuple(m) if m else MEDIA_ROW for m in (media or [])]
    # a caller from before the per-image confirm passes 3-tuples; widen them rather than refuse
    media = [m + ("",) * (len(MEDIA_ROW) - len(m)) if len(m) < len(MEDIA_ROW) else m
             for m in media]
    if len(titles) > len(devices) or len(subtitles) > len(devices) or len(media) > len(devices):
        raise Refused("images.conf: %d titles / %d subtitles / %d media rows for %d images"
                      % (len(titles), len(subtitles), len(media), len(devices)))
    titles += ["image %d" % i for i in range(len(titles), len(devices))]
    subtitles += [""] * (len(devices) - len(subtitles))
    media += [MEDIA_ROW] * (len(devices) - len(media))
    for s in titles + subtitles:
        if "|" in s or "\n" in s or "\r" in s:
            raise Refused("images.conf: title/subtitle %r may not contain '|' or a newline" % s)
    rows = []
    for m in media:
        if len(m) != len(MEDIA_ROW):
            raise Refused("images.conf: a media row is (art, anim, music, confirm), got %r" % (m,))
        rows.append(tuple(_media_name_ok(x or "", what) for x, what in zip(m, MEDIA_FIELDS)))
    sound_move = _media_name_ok(sound_move or "", "sound_move")
    sound_confirm = _media_name_ok(sound_confirm or "", "sound_confirm")
    if not (0 <= int(default) < len(devices)):
        raise Refused("images.conf: default=%s is not an image index (0..%d)" % (default, len(devices) - 1))
    if int(timeout) < 0:
        raise Refused("images.conf: timeout must be >= 0")
    if volume is not None:
        volume = _int_range(volume, "volume", 0, 100)
    machine_volume = check_machine_volume(machine_volume)
    if mixer_volume is not None:
        mixer_volume = _int_range(mixer_volume, "mixer_volume", 0, 63)
    if media_dir and ("|" in media_dir or "\n" in media_dir):
        raise Refused("images.conf: media=%r may not contain '|' or a newline" % media_dir)
    theme = check_theme(theme)
    colors = check_colors(colors)
    any_media = any(any(r) for r in rows)
    # the seventh field is written only when some image has a confirm sound of its own, so a menu
    # where every image uses the menu-wide sound reads exactly as it did before this existed
    width = 4 if any(r[3] for r in rows) else (3 if any_media else 0)
    out = ["# images.conf - codeselect, the boot-time code selector (item 90); written by mkmulticard.py",
           "# image=<device>|<title>|<subtitle>[|<art>|<anim>|<music>[|<confirm>]]   index = order (0-based);",
           "# media names are relative to media= (default /usr/local/codeselect/media); <confirm> is that",
           "# image's own confirm sound and an empty one falls back to sound_confirm=; default = highlight",
           "# when no last choice; timeout = seconds before the highlighted image boots by itself (0 = for ever)"]
    for d, t, s, r in zip(devices, titles, subtitles, rows):
        out.append("image=%s|%s|%s" % (d, t, s) + "".join("|" + x for x in r[:width]))
    out.append("default=%d" % int(default))
    out.append("timeout=%d" % int(timeout))
    if font:
        out.append("font=%s" % font)
    if sound_move:
        out.append("sound_move=%s" % sound_move)
    if sound_confirm:
        out.append("sound_confirm=%s" % sound_confirm)
    if machine_volume:
        out.append("volume=machine")
        out.append("machine_volume=%s|%s|%s" % (machine_volume["store"] or "", machine_volume["key"],
                                              "" if machine_volume["default"] is None else machine_volume["default"]))
    elif volume is not None:
        out.append("volume=%d" % volume)
    if mixer_volume is not None:
        out.append("mixer_volume=%d" % mixer_volume)
    if media_dir:
        out.append("media=%s" % media_dir)
    elif any_media or sound_move or sound_confirm:
        out.append("media=%s" % MEDIA_DIR)
    if theme:
        out.append("theme=%s" % theme)
    # in the roles' order, so two confs with the same colours are the same bytes
    for role in boot_themes()["roles"]:
        if role in colors:
            out.append("color_%s=%s" % (role, colors[role]))
    if debug_log:
        out.append("# log: the selector's diagnostics ON THE CARD (a fresh file each boot, the previous")
        out.append("# boot's kept as .1, 1 MiB at most) - a development card; the app writes no log= line")
        out.append("log=%s" % CARD_LOG)
    return "\n".join(out) + "\n"


def parse_images_conf(text):
    """-> {'images': [(device, title, subtitle)], 'media': [(art, anim, music, confirm)] (aligned,
    '' = none), 'default': int, 'timeout': int, 'font': str|None, 'sound_move': str|None,
    'sound_confirm': str|None, 'volume': int|None, 'mixer_volume': int|None, 'media_dir': str|None,
    'theme': str|None, 'colors': {role: rrggbb}, 'debug_log': str|None (the log= path)}.
    3-field and 6-field image lines are valid; more than 7 fields, a bad device, a media name with
    '|' ':' or '/', or more than 16 images is refused.  Unknown keys are ignored (the file may
    grow).  The theme name is kept as the card spells it (an unknown one is what `inspect` should
    show, and the selector falls back on its own); a color_ key with an unknown role or a value
    that is not RRGGBB is dropped, exactly as the selector drops it."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    conf = {"images": [], "media": [], "default": 0, "timeout": 15, "font": None,
            "sound_move": None, "sound_confirm": None, "volume": None, "mixer_volume": None, "media_dir": None,
            "theme": None, "colors": {}, "machine_volume": None, "debug_log": None}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _sep, val = line.partition("=")
        key = key.strip()
        if key == "image":
            f = [x.strip() for x in val.split("|")]
            if len(f) > 3 + len(MEDIA_ROW):
                raise Refused("images.conf: image line has %d fields (at most %d): %r"
                              % (len(f), 3 + len(MEDIA_ROW), raw))
            f += [""] * (3 + len(MEDIA_ROW) - len(f))
            parse_device(f[0])
            conf["images"].append((f[0], f[1], f[2]))
            conf["media"].append(tuple(_media_name_ok(x, what)
                                       for x, what in zip(f[3:3 + len(MEDIA_ROW)], MEDIA_FIELDS)))
            if len(conf["images"]) > MAX_IMAGES:
                raise Refused("images.conf: more than %d images" % MAX_IMAGES)
        elif key in ("default", "timeout"):
            try:
                conf[key] = int(val.strip())
            except ValueError:
                raise Refused("images.conf: bad %s=%r" % (key, val))
        elif key == "font":
            conf["font"] = val.strip() or None
        elif key in ("sound_move", "sound_confirm"):
            conf[key] = _media_name_ok(val.strip(), key) or None
        elif key == "volume":
            conf["volume"] = "machine" if val.strip().lower() == "machine" else _int_range(val.strip(), key, 0, 100)
        elif key == "machine_volume":
            store, _sep, rest = val.strip().partition("|")
            hexkey, _sep, default = rest.partition("|")
            conf["machine_volume"] = check_machine_volume({"store": store.strip() or None,
                                                           "key": hexkey.strip() or MACHINE_VOLUME_KEY,
                                                           "default": default.strip() or None})
        elif key == "mixer_volume":
            conf["mixer_volume"] = _int_range(val.strip(), key, 0, 63)
        elif key == "media":
            conf["media_dir"] = val.strip() or None
        elif key == "theme":
            conf["theme"] = val.strip().lower() or None
        elif key == "log":
            conf["debug_log"] = val.strip() or None
        elif key.startswith("color_"):
            m = COLOR_RE.match(val.strip())
            if key[6:] in boot_themes()["roles"] and m:
                conf["colors"][key[6:]] = m.group(1).lower()
    return conf


def conf_media_names(conf):
    """Every media file name a parsed conf refers to (per-image fields + the two sounds)."""
    names = []
    for row in conf.get("media", []):
        names += [x for x in row if x]
    names += [conf.get(k) for k in ("sound_move", "sound_confirm") if conf.get(k)]
    return sorted(set(names))


# ============================================================================= media
def png_info(data):
    """(w, h) from a PNG's IHDR, or None when `data` is not a PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or len(data) < 24:
        return None
    return struct.unpack_from(">II", data, 16)


def gif_info(data):
    """(w, h, frames) of a GIF, or None when `data` is not one.  Walks the block stream
    (extensions and image descriptors, local colour tables, LZW sub-blocks) to count frames."""
    if data[:6] not in (b"GIF87a", b"GIF89a") or len(data) < 13:
        return None
    w, h = struct.unpack_from("<HH", data, 6)
    flags = data[10]
    pos = 13 + (3 << ((flags & 7) + 1) if flags & 0x80 else 0)
    frames = 0

    def skip_sub_blocks(p):
        while p < len(data) and data[p] != 0:
            p += data[p] + 1
        return p + 1

    while pos < len(data):
        b = data[pos]
        if b == 0x3B:                                  # trailer
            break
        if b == 0x21:                                  # extension: label + sub-blocks
            pos = skip_sub_blocks(pos + 2)
        elif b == 0x2C:                                # image descriptor
            frames += 1
            if pos + 10 > len(data):
                break
            lflags = data[pos + 9]
            pos += 10 + (3 << ((lflags & 7) + 1) if lflags & 0x80 else 0)
            pos = skip_sub_blocks(pos + 1)             # LZW minimum code size, then the data
        else:
            raise Refused("GIF: unexpected block 0x%02x at %d" % (b, pos))
    return w, h, frames


def wav_info(data):
    """(format tag, channels, rate, bits) from a RIFF/WAVE 'fmt ' chunk, or None when `data`
    is not a WAV.  Chunks are walked (Logic exports put JUNK/LGWV/bext before fmt)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        if cid == b"fmt " and pos + 8 + 16 <= len(data):
            tag, ch, rate = struct.unpack_from("<HHI", data, pos + 8)
            bits = struct.unpack_from("<H", data, pos + 8 + 14)[0]
            return tag, ch, rate, bits
        pos += 8 + size + (size & 1)
    return None


def check_media_file(path, kind):
    """Refuse a media file the selector could not use; -> (kind word, size).  `kind` is
    'art' (PNG <= 1360x768), 'anim' (GIF <= 10 MB, 512x288, 150 frames) or 'wav' (RIFF
    pcm_s16le 44100 Hz 1-2 ch: music, sound_move, sound_confirm)."""
    name = os.path.basename(path)
    if not MEDIA_NAME_RE.match(name):
        raise Refused("media %r: names must match ^[A-Za-z0-9._-]+$" % name)
    if not os.path.isfile(path):
        raise Refused("media %s: %s does not exist" % (name, path))
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        data = f.read()
    if kind == "art":
        d = png_info(data)
        if d is None:
            raise Refused("media %s: art must be a PNG" % name)
        if d[0] > PNG_MAX[0] or d[1] > PNG_MAX[1]:
            raise Refused("media %s: PNG is %dx%d, larger than the %dx%d panel (pre-scale it)" % (name, d[0], d[1], PNG_MAX[0], PNG_MAX[1]))
        return "png %dx%d" % d, size
    if kind == "anim":
        g = gif_info(data)
        if g is None:
            raise Refused("media %s: anim must be an animated GIF" % name)
        if size > GIF_MAX_BYTES:
            raise Refused("media %s: GIF is %d bytes, over the %d byte cap" % (name, size, GIF_MAX_BYTES))
        if g[0] > GIF_MAX[0] or g[1] > GIF_MAX[1]:
            raise Refused("media %s: GIF is %dx%d, over %dx%d" % (name, g[0], g[1], GIF_MAX[0], GIF_MAX[1]))
        if g[2] > GIF_MAX_FRAMES:
            raise Refused("media %s: GIF has %d frames, over %d" % (name, g[2], GIF_MAX_FRAMES))
        if g[2] < 1:
            raise Refused("media %s: GIF has no frames" % name)
        return "gif %dx%d %d frames" % g, size
    if kind == "wav":
        w = wav_info(data)
        if w is None:
            raise Refused("media %s: must be a RIFF WAV" % name)
        tag, ch, rate, bits = w
        if tag != 1 or bits != 16 or rate != WAV_RATE or ch not in (1, 2):
            raise Refused("media %s: WAV is fmt %d / %d ch / %d Hz / %d-bit; the selector plays pcm_s16le %d Hz 1-2 ch only"
                          % (name, tag, ch, rate, bits, WAV_RATE))
        return "wav %d Hz %d ch" % (rate, ch), size
    raise Refused("media %s: unknown kind %r" % (name, kind))


def read_media_manifest(media_dir):
    """DIR/media.json -> dict; the shape selectmedia.py writes:
    {"images": [{"art": "art0.png", "anim": "anim0.gif"|null, "music": "music0.wav"|null,
                 "confirm": "confirm0.wav"|null}, ...],
     "sound_move": "move.wav"|null, "sound_confirm": "confirm.wav"|null, "volume": 50}
    ("mixer_volume" optional; "confirm" is that image's OWN confirm sound, null = the menu-wide
    one, and the "*_source" keys selectmedia also writes are provenance this tool ignores)."""
    path = os.path.join(media_dir, MEDIA_MANIFEST)
    if not os.path.isdir(media_dir):
        raise Refused("--media-dir %s is not a directory" % media_dir)
    if not os.path.isfile(path):
        raise Refused("%s has no %s (selectmedia.py prepare writes it)" % (media_dir, MEDIA_MANIFEST))
    with open(path, "r", encoding="utf-8") as f:
        try:
            man = json.load(f)
        except ValueError as e:
            raise Refused("%s: not JSON (%s)" % (path, e))
    if not isinstance(man, dict) or not isinstance(man.get("images"), list):
        raise Refused("%s: expected {\"images\": [...], ...}" % path)
    return man


def plan_media(media_dir, n_images):
    """Validate DIR/media.json against a card with `n_images` images and check every referenced
    file -> {'rows': [(art, anim, music, confirm)], 'sound_move', 'sound_confirm', 'volume', 'mixer_volume',
    'files': OrderedDict name -> source path, 'total': bytes, 'kinds': {name: kind word}}.
    Only referenced files are staged; a missing, misnamed, malformed or over-budget one refuses."""
    man = read_media_manifest(media_dir)
    imgs = man["images"]
    if len(imgs) != n_images:
        raise Refused("%s/%s lists %d images; the card holds %d" % (media_dir, MEDIA_MANIFEST, len(imgs), n_images))
    files = collections.OrderedDict()
    kinds = {}
    total = 0

    def take(name, kind, what):
        nonlocal total
        if name is None or name == "":
            return ""
        if not isinstance(name, str):
            raise Refused("%s: %s must be a file name or null, got %r" % (MEDIA_MANIFEST, what, name))
        name = _media_name_ok(name, what)
        if name not in files:
            src = os.path.join(media_dir, name)
            word, size = check_media_file(src, kind)
            files[name] = src
            kinds[name] = word
            total += size
        return name

    rows = []
    for i, e in enumerate(imgs):
        if not isinstance(e, dict):
            raise Refused("%s: images[%d] must be an object" % (MEDIA_MANIFEST, i))
        rows.append((take(e.get("art"), "art", "images[%d].art" % i),
                     take(e.get("anim"), "anim", "images[%d].anim" % i),
                     take(e.get("music"), "wav", "images[%d].music" % i),
                     take(e.get("confirm"), "wav", "images[%d].confirm" % i)))
    out = {"rows": rows,
           "sound_move": take(man.get("sound_move"), "wav", "sound_move") or None,
           "sound_confirm": take(man.get("sound_confirm"), "wav", "sound_confirm") or None,
           "volume": None, "mixer_volume": None, "files": files, "total": total, "kinds": kinds}
    if man.get("volume") is not None:
        out["volume"] = _int_range(man.get("volume"), "volume", 0, 100)
    if man.get("mixer_volume") is not None:
        out["mixer_volume"] = _int_range(man.get("mixer_volume"), "mixer_volume", 0, 63)
    if total > MEDIA_BUDGET:
        raise Refused("media set is %d bytes, over the %d byte budget (%d files)" % (total, MEDIA_BUDGET, len(files)))
    return out


def default_title(path):
    """'turtles_pro-1_59_0.Release.8G.sdcard.raw' -> 'turtles_pro-1_59_0.Release'."""
    b = os.path.basename(path or "image")
    b = re.sub(r"\.(raw|img|bin|iso)$", "", b, flags=re.I)
    b = re.sub(r"\.\d+G\.sdcard$", "", b, flags=re.I)
    return b


def split_list(s):
    return [x.strip() for x in s.split(";")] if s else []


# ============================================================================= output safety
def _norm(p):
    """Absolute, LINK-RESOLVED, forward slashes, lower case.  Symlinks and junctions are followed
    (os.path.realpath) because the repo's own images/ is a junction into D:\\Pinball\\images -
    the card library the refusal below exists for - and a prefix test on the spelled path
    would let `images/x.raw` straight through.  An output that does not exist yet has its
    PARENT resolved and the basename re-joined."""
    a = os.path.abspath(p)
    if os.path.exists(a):
        r = os.path.realpath(a)
    else:
        r = os.path.join(os.path.realpath(os.path.dirname(a)), os.path.basename(a))
    return os.path.normpath(r).replace("\\", "/").lower()


def check_library_path(path):
    """Refuse ANY output - a file or a directory - inside David's card library."""
    if not path:
        raise Refused("no output path")
    n = _norm(path)
    for pre in FORBIDDEN_OUTPUT_PREFIXES:
        pn = _norm(pre)
        if n == pn or n.startswith(pn + "/"):
            raise Refused("refusing to write under %s (David's card library): %s" % (pre, path))
    return path


def check_output_path(path, inputs, force=False, must_exist=False):
    """Refuse an output the tool must never write.  Raises Refused with the reason."""
    n = _norm(check_library_path(path))
    for inp in inputs:
        if not inp:
            continue
        same = _norm(inp) == n
        if not same and os.path.exists(path) and os.path.exists(inp):
            try:
                same = os.path.samefile(path, inp)
            except OSError:
                same = False
        if same:
            raise Refused("output %s is also an input" % path)
    if os.path.isdir(path):
        raise Refused("output %s is a directory" % path)
    if must_exist:
        if not os.path.isfile(path):
            raise Refused("%s does not exist" % path)
    elif os.path.exists(path) and not force:
        raise Refused("%s exists; pass --force to overwrite it" % path)
    return path


# ============================================================================= copying
ZERO = bytes(CHUNK)


def copy_range(src, soff, out, doff, length, label="", sparse=True, progress=say, meter=None):
    """Copy length bytes src@soff -> out@doff in 8 MiB chunks; sparse=True skips all-zero chunks
    (the output must be a fresh hole there); progress lines every ~2 s.

    `meter` is the build's :class:`Progress`, counted per chunk - including the all-zero ones,
    which are work this loop still has to READ."""
    t0 = last = time.monotonic()
    done = skipped = 0
    with open(src, "rb") as s, open(out, "r+b") as o:
        s.seek(soff)
        left, pos = length, doff
        while left:
            b = s.read(min(CHUNK, left))
            if not b:
                raise EOFError("%s: short read at byte %d" % (src, soff + length - left))
            if sparse and b == ZERO[:len(b)]:
                skipped += len(b)
            else:
                o.seek(pos)
                o.write(b)
            pos += len(b)
            left -= len(b)
            done += len(b)
            if meter is not None:
                meter.add(len(b))
            now = time.monotonic()
            if progress and label and now - last >= 2.0:
                last = now
                progress("  %s %s / %s  %.0f MB/s" % (label, _gb(done), _gb(length), done / 1e6 / max(now - t0, 1e-9)))
        o.flush()
    dt = time.monotonic() - t0
    if progress and label:
        progress("  %s done: %s in %.1f s (%.0f MB/s), %s all-zero skipped" %
                 (label, _gb(length), dt, length / 1e6 / max(dt, 1e-9), _gb(skipped)))
    return dt


def dd_range(src, soff, out, doff, length, label="", meter=None):
    t0 = time.monotonic()
    cmd = ["dd", "if=" + src, "of=" + out, "bs=16M", "iflag=skip_bytes,count_bytes", "oflag=seek_bytes",
           "skip=%d" % soff, "seek=%d" % doff, "count=%d" % length, "conv=sparse,notrunc", "status=none"]
    subprocess.run(cmd, check=True)
    dt = time.monotonic() - t0
    if meter is not None:            # dd says nothing as it goes: the range banks in one piece
        meter.add(length)
    if label:
        say("  %s done (dd): %s in %.1f s (%.0f MB/s)" % (label, _gb(length), dt, length / 1e6 / max(dt, 1e-9)))
    return dt


def md5_range(path, off, length):
    h = hashlib.md5()
    with open(path, "rb") as f:
        f.seek(off)
        left = length
        while left:
            b = f.read(min(CHUNK, left))
            if not b:
                break
            h.update(b)
            left -= len(b)
    return h.hexdigest()


def md5_file(path):
    return md5_range(path, 0, os.path.getsize(path))


# ---- the md5 sidecars -----------------------------------------------------------------------
# verify cannot compare p2 to its source (it is patched), so without this a p2 corrupted
# anywhere OUTSIDE the injected files passed.  Every write-back of p2 records md5 of the whole
# range beside the card, and verify compares the card's p2 to it.  The same file shape covers
# every other partition this tool WRITES INTO after the copy: the validator bypass patches the
# game ELF + .sidx inside p3 / p7, and the multi layout's p7 has no source image at all - so
# those get <card>.pN.md5 too, and verify holds them to it instead of to a source.
def sidecar_path(card, n):
    return card + ".p%d.md5" % n


def p2_sidecar_path(card):
    return sidecar_path(card, 2)


def part_range(card, n):
    """(offset, length) of partition n in bytes; must be a Linux partition."""
    t, st, cnt = Geometry.from_file(card).part(n)
    if t != 0x83:
        raise Refused("%s: p%d is type 0x%02x, not Linux" % (card, n, t))
    return st * SECTOR, cnt * SECTOR


def p2_range(card):
    """(offset, length) of p2 in bytes."""
    return part_range(card, 2)


def write_part_sidecar(card, n):
    """md5 of the card's whole pN range -> <card>.pN.md5 (one line: '<md5>  pN @<offset>+<length>').
    Returns the digest."""
    off, length = part_range(card, n)
    h = md5_range(card, off, length)
    with open(sidecar_path(card, n), "w", newline="\n") as f:
        f.write("%s  p%d @%d+%d\n" % (h, n, off, length))
    return h


def read_part_sidecar(card, n):
    """The digest recorded beside the card for pN, or None when there is no sidecar."""
    side = sidecar_path(card, n)
    if not os.path.isfile(side):
        return None
    with open(side, "r") as f:
        tok = f.read().split()
    if not tok or not re.fullmatch(r"[0-9a-f]{32}", tok[0]):
        raise Refused("%s: not a p%d sidecar (expected '<md5>  p%d @off+len')" % (side, n, n))
    return tok[0]


def check_part_sidecar(card, n):
    """-> (recorded, actual): recorded is None without a sidecar; actual is md5 of pN now."""
    want = read_part_sidecar(card, n)
    off, length = part_range(card, n)
    return want, md5_range(card, off, length)


def write_p2_sidecar(card):
    return write_part_sidecar(card, 2)


def read_p2_sidecar(card):
    return read_part_sidecar(card, 2)


def check_p2_sidecar(card):
    return check_part_sidecar(card, 2)


def drop_stale_sidecars(card, keep=(2,)):
    """Remove <card>.pN.md5 files for partitions a fresh build did not write into."""
    d = os.path.dirname(os.path.abspath(card)) or "."
    base = os.path.basename(card)
    for name in os.listdir(d):
        m = re.fullmatch(re.escape(base) + r"\.p(\d+)\.md5", name)
        if m and int(m.group(1)) not in keep:
            os.unlink(os.path.join(d, name))


def write_tables(plan, out):
    """MBR (bootstrap + disk id from the primary, entries regenerated) and the EBR chain."""
    with open(out, "r+b") as o:
        o.seek(0)
        o.write(mbr_sector(plan))
        for i in range(len(plan.logs)):
            o.seek(plan.logs[i].ebr * SECTOR)
            o.write(ebr_sector(plan, i))
        o.flush()


def build_image(plan, out, use_dd=False):
    """The sparse output: pre-p1 region verbatim, every partition range, then the tables."""
    with open(out, "wb") as o:
        o.truncate(plan.total_bytes)
    say("output %s: %d bytes apparent (sparse), %d partition ranges to copy" % (out, plan.total_bytes, 3 + len(plan.logs)))
    meter = PROGRESS if PROGRESS.on else None
    if meter is not None:
        meter.step("writing the card image")
    copy_range(plan.primary, 0, out, 0, PRE_P1 * SECTOR, "pre-p1 (bootstrap + u-boot)", meter=meter)
    for p in plan.prims + plan.logs:
        label = "p%d %s" % (p.num, default_title(p.src))
        say("copying %s: %s from %s@LBA %d -> LBA %d" % ("p%d" % p.num, _gb(p.count * SECTOR), os.path.basename(p.src), p.src_start, p.start))
        if meter is not None:
            # The multi layout's p7 is sourced from a temp file called p7.img,
            # whose "title" is the word p7 - so it is named for what it holds.
            what = ("the games partition" if plan.multi_part is not None and p.num == plan.multi_part.num
                    else default_title(p.src))
            meter.step("copying p%d (%s) into the card image" % (p.num, what))
        length = p.count * SECTOR
        if plan.layout == "store" and p.num == 3 and plan.store_src_count:
            length = plan.store_src_count * SECTOR         # the primary's own p3; the growth comes after
        if use_dd:
            dd_range(p.src, p.src_start * SECTOR, out, p.start * SECTOR, length, label, meter=meter)
        else:
            copy_range(p.src, p.src_start * SECTOR, out, p.start * SECTOR, length, label, meter=meter)
    write_tables(plan, out)
    say("tables written: MBR entries + %d EBR sector(s)" % len(plan.logs))


def allocated_bytes(path):
    st = os.stat(path)
    blocks = getattr(st, "st_blocks", None)
    return None if blocks is None else blocks * 512


# ============================================================================= ext4 tooling
def need_tools(*names):
    missing = [n for n in names if shutil.which(n) is None]
    if missing:
        raise Refused("missing tool(s): %s (run this under WSL/Linux with e2fsprogs + util-linux)" % ", ".join(missing))


def fs_ref(image, offset):
    """The 'file?offset=N' form debugfs and e2fsck accept for a partition inside a whole-card image."""
    return image if not offset else "%s?offset=%d" % (image, offset)


def debugfs_read(ref, request):
    """Run one read-only debugfs request; return stdout bytes (the banner goes to stderr)."""
    r = subprocess.run(["debugfs", "-R", request, ref], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err = r.stderr.decode("utf-8", "replace")
    bad = [l for l in err.splitlines() if l and not l.startswith("debugfs ")]
    if r.returncode != 0 or bad:
        raise Refused("debugfs %r on %s failed: %s" % (request, ref, " | ".join(bad) or "rc=%d" % r.returncode))
    return r.stdout


def debugfs_cat(ref, path):
    return debugfs_read(ref, "cat " + path)


def debugfs_ls(ref, path):
    """-> [(inode, mode, uid, gid, name, size)] from 'ls -p' (the parseable form)."""
    out = []
    for line in debugfs_read(ref, "ls -p " + path).decode("utf-8", "replace").splitlines():
        f = line.split("/")
        if len(f) >= 7 and f[1].isdigit():
            out.append((int(f[1]), int(f[2], 8), int(f[3]), int(f[4]), f[5], int(f[6] or 0)))
    return out


def debugfs_exists(ref, path):
    r = subprocess.run(["debugfs", "-R", "stat " + path, ref], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode == 0 and b"Inode:" in r.stdout


def debugfs_stat(ref, path):
    """-> {'mode': int, 'uid': int, 'gid': int, 'atime': int, 'ctime': int, 'mtime': int, 'link': str|None}"""
    txt = debugfs_read(ref, "stat " + path).decode("utf-8", "replace")
    info = {"link": None}
    m = re.search(r"Mode:\s+(0[0-7]+)", txt)
    if m:
        info["mode"] = int(m.group(1), 8)
    m = re.search(r"User:\s+(\d+)\s+Group:\s+(\d+)", txt)
    if m:
        info["uid"], info["gid"] = int(m.group(1)), int(m.group(2))
    for k in ("atime", "ctime", "mtime"):
        m = re.search(r"^\s*%s:\s+0x([0-9a-fA-F]+)" % k, txt, re.M)
        if m:
            info[k] = int(m.group(1), 16)
    m = re.search(r'Fast link dest: "([^"]*)"', txt)
    if m:
        info["link"] = m.group(1)
    return info


def dq(path):
    """A path as one debugfs argument.  debugfs parses its requests with libss, which honours
    double quotes - without them `write /tmp/my stage/x /usr/local/x` is three words, and a
    card or output under a directory with a space in its name ('D:\\Pinball\\TMNT 1987\\multi')
    put the staging directory exactly there."""
    if '"' in path:
        raise Refused("path %r: debugfs cannot take a double quote inside an argument" % path)
    return '"%s"' % path


def debugfs_write_script(image, commands):
    """Run a debugfs -w script.  debugfs exits 0 whatever happened, so every output line that is not
    the banner or an 'Allocated inode' note is treated as an error."""
    with tempfile.NamedTemporaryFile("w", suffix=".debugfs", delete=False) as f:
        f.write("\n".join(commands) + "\n")
        script = f.name
    try:
        r = subprocess.run(["debugfs", "-w", "-f", script, image], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    finally:
        os.unlink(script)
    out = r.stdout.decode("utf-8", "replace")
    bad = []
    for l in out.splitlines():
        s = l.strip()
        if not s or s.startswith("debugfs ") or s.startswith("Allocated inode:") or s.startswith("debugfs:"):
            continue
        bad.append(s)
    if r.returncode != 0 or bad:
        raise Refused("debugfs -w reported: %s" % (" | ".join(bad) or "rc=%d" % r.returncode))
    return out


def e2fsck(ref):
    """-> (rc, output); rc 0 is clean."""
    r = subprocess.run(["e2fsck", "-fn", ref], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def e2fsck_blocks(txt):
    """(used, total) blocks from e2fsck's summary line ('...: 4493/86016 files (...), 145489/344064 blocks')."""
    m = re.search(r"(\d+)/(\d+) blocks", txt)
    if not m:
        raise Refused("e2fsck printed no 'used/total blocks' line:\n%s" % txt.strip())
    return int(m.group(1)), int(m.group(2))


def ext_block_size(path, offset=0):
    with open(path, "rb") as f:
        f.seek(offset + 1024 + 0x18)
        return 1024 << struct.unpack("<I", f.read(4))[0]


def debugfs_rdump(ref, src, dest, meter=None):
    """`rdump <src> <dest>` out of a read-only filesystem (symlinks come out as symlinks -
    measured).  As an ordinary user debugfs cannot chown what it extracts and says so on stderr
    for every entry; those lines are the expected noise, anything else is an error.

    `meter` follows the extraction WHILE IT RUNS - debugfs says nothing about its own progress
    and a games tree is gigabytes, so without this the longest step of a build is a silent
    one (see :func:`run_metered`)."""
    rc, out, err_b = run_metered(["debugfs", "-R", "rdump %s %s" % (dq(src), dq(dest)), ref], meter)
    err = err_b.decode("utf-8", "replace") + out.decode("utf-8", "replace")
    bad = [l for l in err.splitlines()
           if l.strip() and not l.startswith("debugfs ") and "while changing ownership" not in l]
    if rc != 0 or bad:
        raise Refused("debugfs rdump %s -> %s failed: %s" % (src, dest, " | ".join(bad) or "rc=%d" % rc))


def debugfs_walk(ref, sub="/"):
    """Every entry under `sub`, recursively: [(relative path, inode, mode, uid, gid, size)].
    Symlinks are listed and not followed; directories are descended."""
    out = []
    for ino, mode, uid, gid, name, size in debugfs_ls(ref, sub):
        if name in (".", ".."):
            continue
        rel = (sub.rstrip("/") + "/" + name).lstrip("/")
        out.append((rel, ino, mode, uid, gid, size))
        if statmod.S_ISDIR(mode):
            out += debugfs_walk(ref, "/" + rel)
    return out


# ============================================================================= injection
def stage_selector(selector_dir, stage, conf_text, hooked_game, media_files=None, manifests=None):
    """Copy the selector files into `stage` with their FINAL modes (debugfs write copies the source
    mode).  `media_files` ({name: source path}, from plan_media) go to stage/media/<name> and
    MEDIA_DIR/<name> on the card, 0644.  `manifests` ({name: text or bytes}, from
    selector_manifests) are the JSON sidecars and land BESIDE images.conf - in SELECT_DIR, never
    in MEDIA_DIR, so the selector's media scan never sees them.  -> [(staged path, card path, mode)]."""
    if not os.path.isdir(selector_dir):
        raise Refused("selector dir %s is not a directory" % selector_dir)
    items = []
    for name, (card, mode, required) in SELECTOR_FILES.items():
        src = os.path.join(selector_dir, name)
        if not os.path.isfile(src):
            if name == "font.ttf" and os.path.isfile(HOST_FONT):
                say("selector dir has no font.ttf; using the host's %s" % HOST_FONT)
                src = HOST_FONT
            elif required:
                raise Refused("selector dir %s lacks %s" % (selector_dir, name))
            else:
                continue
        dst = os.path.join(stage, name)
        shutil.copyfile(src, dst)
        os.chmod(dst, mode)
        items.append((dst, SELECT_DIR + "/" + card, mode))
    conf = os.path.join(stage, "images.conf")
    with open(conf, "w", newline="\n") as f:
        f.write(conf_text)
    os.chmod(conf, 0o644)
    items.append((conf, SELECT_DIR + "/images.conf", 0o644))
    for name, text in (manifests or {}).items():
        if name not in SIDECAR_MANIFESTS:
            raise Refused("%r is not one of the selector's JSON sidecars %r" % (name, list(SIDECAR_MANIFESTS)))
        dst = os.path.join(stage, name)
        with open(dst, "wb") as f:                       # bytes: a carried-through media.json is verbatim
            f.write(text if isinstance(text, bytes) else text.encode("utf-8"))
        os.chmod(dst, 0o644)
        items.append((dst, SELECT_DIR + "/" + name, 0o644))
    if media_files:
        mdir = os.path.join(stage, "media")
        os.makedirs(mdir, exist_ok=True)
        for name, src in media_files.items():
            if not MEDIA_NAME_RE.match(name):
                raise Refused("media %r: names must match ^[A-Za-z0-9._-]+$" % name)
            dst = os.path.join(mdir, name)
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o644)
            items.append((dst, MEDIA_DIR + "/" + name, 0o644))
    game = os.path.join(stage, "game")
    with open(game, "wb") as f:
        f.write(hooked_game.encode("utf-8"))
    os.chmod(game, 0o755)
    items.append((game, GAME_SCRIPT, 0o755))
    return items


def inject_commands(items, existing, times, existing_media=None):
    """The debugfs -w script for one injection (pure, so it is testable without debugfs).

    items           [(staged native path, card path, mode)] from stage_selector
    existing        FILE names already in SELECT_DIR (removed first), or None when the directory
                    is missing; 'media' (a directory) is never in this list
    times           the game script's {atime, ctime, mtime} to put back
    existing_media  the names inside MEDIA_DIR when that directory is to be REPLACED (each is
                    rm'd, then the directory rmdir'd - debugfs's rm cannot take a directory);
                    None leaves an existing media directory alone
    MEDIA_DIR is mkdir'd (+ 040755 root:root) exactly when an item lands in it.
    Every path is double-quoted (dq): the staged path is a NATIVE path and may hold a space."""
    cmds = []
    if existing is None:
        cmds.append("mkdir " + dq(SELECT_DIR))
    else:
        for name in existing:
            cmds.append("rm " + dq(SELECT_DIR + "/" + name))
    if existing_media is not None:
        for name in existing_media:
            cmds.append("rm " + dq(MEDIA_DIR + "/" + name))
        cmds.append("rmdir " + dq(MEDIA_DIR))
    cmds.append("rm " + dq(GAME_SCRIPT))
    media_items = [it for it in items if it[1].startswith(MEDIA_DIR + "/")]
    if media_items:
        cmds.append("mkdir " + dq(MEDIA_DIR))
    for staged, card, _mode in items:
        cmds.append("write %s %s" % (dq(staged), dq(card)))
    cmds.append("set_inode_field %s mode 040755" % dq(SELECT_DIR))
    cmds.append("set_inode_field %s uid 0" % dq(SELECT_DIR))
    cmds.append("set_inode_field %s gid 0" % dq(SELECT_DIR))
    if media_items:
        cmds.append("set_inode_field %s mode 040755" % dq(MEDIA_DIR))
        cmds.append("set_inode_field %s uid 0" % dq(MEDIA_DIR))
        cmds.append("set_inode_field %s gid 0" % dq(MEDIA_DIR))
    for _staged, card, mode in items:
        cmds.append("set_inode_field %s mode 0%o" % (dq(card), statmod.S_IFREG | mode))
        cmds.append("set_inode_field %s uid 0" % dq(card))
        cmds.append("set_inode_field %s gid 0" % dq(card))
    for k in ("atime", "ctime", "mtime"):
        if k in times:
            cmds.append("set_inode_field %s %s @%d" % (dq(GAME_SCRIPT), k, times[k]))
    return cmds


def inject_into_p2(p2_image, selector_dir, conf_text, stage_dir, media_files=None, replace_media=False,
                   manifests=None):
    """Modify an extracted rootfs image in place: /usr/local/codeselect/* (+ media/, + the JSON
    sidecars `manifests` names) and the hooked game script.  Idempotent (existing files are
    removed first; an existing media directory is
    replaced when media is staged or `replace_media` asks, else left alone).  Refuses to fill p2
    past its free space.  Verifies by e2fsck -fn and full read-back."""
    need_tools("debugfs", "e2fsck")
    rc, txt = e2fsck(p2_image)
    if rc != 0:
        raise Refused("p2 is not clean before injection (e2fsck rc=%d):\n%s" % (rc, txt))
    used, total = e2fsck_blocks(txt)
    bs = ext_block_size(p2_image)
    free = (total - used) * bs
    margin = min(P2_FREE_MARGIN, total * bs // 20)          # 8 MiB, or 5% of a small (synthetic) p2
    orig = debugfs_cat(p2_image, GAME_SCRIPT)
    if not orig:
        raise Refused("%s is empty or missing in p2" % GAME_SCRIPT)
    times = debugfs_stat(p2_image, GAME_SCRIPT)
    hooked = hook_game_script(orig)
    items = stage_selector(selector_dir, stage_dir, conf_text, hooked, media_files, manifests)
    existing = existing_media = None
    reclaim = len(orig)                                    # the game script is rm'd and rewritten
    if debugfs_exists(p2_image, SELECT_DIR):
        ents = [e for e in debugfs_ls(p2_image, SELECT_DIR) if e[4] not in (".", "..")]
        existing = [e[4] for e in ents if not statmod.S_ISDIR(e[1])]
        reclaim += sum(e[5] for e in ents if not statmod.S_ISDIR(e[1]))
        has_media = any(e[4] == "media" and statmod.S_ISDIR(e[1]) for e in ents)
        if has_media and (media_files or replace_media):
            ments = [e for e in debugfs_ls(p2_image, MEDIA_DIR) if e[4] not in (".", "..")]
            existing_media = [e[4] for e in ments]
            reclaim += sum(e[5] for e in ments)
    staged_bytes = sum(os.path.getsize(s) for (s, _c, _m) in items)
    if staged_bytes > free + reclaim - margin:
        raise Refused("p2 has %d KB free (+ %d KB the re-injection frees) and the injection needs %d KB (+ %d KB margin)"
                      % (free >> 10, reclaim >> 10, staged_bytes >> 10, margin >> 10))
    debugfs_write_script(p2_image, inject_commands(items, existing, times, existing_media))
    rc, txt = e2fsck(p2_image)
    if rc != 0:
        raise Refused("p2 is not clean after injection (e2fsck rc=%d):\n%s" % (rc, txt))
    for staged, card, mode in items:
        back = debugfs_cat(p2_image, card)
        if hashlib.md5(back).hexdigest() != md5_file(staged):
            raise Refused("%s read back differs from %s" % (card, staged))
        st = debugfs_stat(p2_image, card)
        if st.get("mode") != mode or st.get("uid") != 0 or st.get("gid") != 0:
            raise Refused("%s has mode %o uid %s gid %s after injection" % (card, st.get("mode", 0), st.get("uid"), st.get("gid")))
    after = debugfs_stat(p2_image, GAME_SCRIPT)
    nmedia = len([1 for (_s, c, _m) in items if c.startswith(MEDIA_DIR + "/")])
    say("injected %d files (%d media, %d KB); %s hook %s; game script times %s; p2 had %d KB free" %
        (len(items), nmedia, staged_bytes >> 10, GAME_SCRIPT, "present" if has_hook(hooked) else "MISSING",
         "kept" if all(after.get(k) == times.get(k) for k in ("atime", "ctime", "mtime") if k in times) else "changed",
         free >> 10))
    return [card for (_s, card, _m) in items]


def inject_card(card, selector_dir, conf_text, workdir=None, media_files=None, replace_media=False,
                manifests=None):
    """Extract p2 from the card, inject, e2fsck, write it back.  -> list of card paths written."""
    geom = Geometry.from_file(card)
    t, st, cnt = geom.part(2)
    if t != 0x83:
        raise Refused("%s: p2 is type 0x%02x, not Linux" % (card, t))
    tmp = tempfile.mkdtemp(prefix="mkmulticard.", dir=workdir)
    try:
        p2 = os.path.join(tmp, "p2.img")
        say("extracting p2 (%s) from %s" % (_gb(cnt * SECTOR), card))
        with open(p2, "wb") as f:
            f.truncate(cnt * SECTOR)
        copy_range(card, st * SECTOR, p2, 0, cnt * SECTOR, "p2 extract", sparse=False, progress=None)
        stage = os.path.join(tmp, "stage")
        os.mkdir(stage)
        written = inject_into_p2(p2, selector_dir, conf_text, stage, media_files, replace_media, manifests)
        say("writing the patched p2 back to %s @LBA %d" % (card, st))
        copy_range(p2, 0, card, st * SECTOR, cnt * SECTOR, "p2 write-back", sparse=False, progress=None)
        a, b = md5_file(p2), md5_range(card, st * SECTOR, cnt * SECTOR)
        if a != b:
            raise Refused("p2 write-back mismatch (%s vs %s)" % (a, b))
        # the sidecar verify compares p2 against (rewritten on every injection)
        say("p2 md5 %s recorded in %s" % (write_p2_sidecar(card), p2_sidecar_path(card)))
        return written
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def tree_source_title(plan, part, sub):
    """A default menu title for a games tree: the source image's name."""
    if sub:
        k = plan.multi_subdirs.index(sub) if sub in plan.multi_subdirs else -1
        x = plan.extras[k] if 0 <= k < len(plan.extras) else None
        return default_title(x) if x and x != plan.primary else "image %s" % device_name(part.num, sub)
    return default_title(part.src)


def plan_tree_source(plan, index):
    """(path, part, subdir) to read games tree `index` from: at build the SOURCE image (the card
    does not exist yet), at inject the card itself (plan_from_card lists the card as every
    source).  A part that cannot be located is None; the reader says why."""
    srcs = [plan.primary] + list(plan.extras)
    path = srcs[index] if index < len(srcs) else plan.primary
    if index > 0 and path == plan.primary and index < len(plan.trees):
        part, sub = plan.trees[index]
        return path, part, sub
    try:
        return path, source_part(path), None
    except Exception:
        return path, None, None


def machine_volume_for(path, part, subdir=None):
    """images.conf's machine_volume contract for the games tree at (path, part, subdir): the
    store the machine mirrors its settings to (/data/nv/<title>/NVM), the MASTER VOLUME SETTING
    record's key (SHA1 of the caption) and the title's built-in level for a machine that has no
    store yet (:mod:`plugins.stern.factory_volume`).  Nothing here raises: a tree or an ELF this
    cannot read leaves the store or the default None with the reason in "notes"."""
    _v, _s, ext4, adjustments = _stern_plugins()
    out = {"store": None, "key": MACHINE_VOLUME_KEY, "default": None, "title": None, "notes": []}
    try:
        if part is None:
            raise Refused("no games partition located")
        with open(path, "rb") as f:
            r = ext4.Ext4Reader(f, part.start * SECTOR, part.count * SECTOR)
            root = tree_root_inode(r, subdir)
            title, _gpath, _gino, gnode = tree_game(r, root)
            elf = r.read_file_bytes(gnode)
    except Exception as e:
        out["notes"].append("%s could not be read (%s: %s); no store, no factory level"
                            % (path, type(e).__name__, e))
        return out
    out["title"] = title
    out["store"] = MACHINE_VOLUME_STORE % title
    try:
        from pinball_decryptor.plugins.stern import factory_volume
        table = adjustments.AdjustmentTable(elf)
        idx = table.by_name.get(factory_volume.ADJUSTMENT)
        if idx is not None:
            caption = adjustments.menu_label(table, idx)
            if caption and caption.strip().upper() != MACHINE_VOLUME_CAPTION:
                out["notes"].append("this build captions the volume %r, not %r; the record is looked up "
                                    "under the usual caption" % (caption, MACHINE_VOLUME_CAPTION))
        spot = factory_volume.find(table)
        if spot is not None:
            out["default"] = int(spot["value"])
        else:
            out["notes"].append("the title's built-in volume was not located in %s's game ELF; a machine "
                                "with no settings store plays at the plain volume" % title)
    except Exception as e:
        out["notes"].append("%s's game ELF has no adjustment table this reads (%s: %s); a machine with "
                            "no settings store plays at the plain volume" % (title, type(e).__name__, e))
    return out


def conf_for_plan(plan, args, existing=None, media=None):
    """images.conf text for the card: --conf verbatim, else generated from the layout with the
    flags, falling back to `existing` (a parsed conf already on the card) then to defaults.
    `media` (plan_media's answer) supplies the per-image media rows, the sounds and the volume;
    without it an `existing` conf's media fields are carried through unchanged.  The theme:
    --theme is the whole answer for the name (and, given alone, drops the card's old colour
    overrides); --color alone keeps the card's theme and replaces its overrides; neither flag
    carries the card's own through; a card with none gets none.  The card log (`log=`) is
    --debug-log's alone: it is never carried through from the card, so an inject without the
    flag - the app's - turns a development card's log off."""
    if getattr(args, "conf", None):
        with open(args.conf, "r") as f:
            text = f.read()
        parsed = parse_images_conf(text)
        devs = [d for (d, _t, _s) in parsed["images"]]
        if devs != plan.devices():
            raise Refused("--conf %s lists %r but the card holds %r" % (args.conf, devs, plan.devices()))
        return text
    ex = existing or {"images": [], "media": [], "default": None, "timeout": None, "font": None,
                      "sound_move": None, "sound_confirm": None, "volume": None, "mixer_volume": None,
                      "theme": None, "colors": {}}
    n = len(plan.trees)
    same_n = len(ex["images"]) == n
    titles = split_list(getattr(args, "titles", None))
    subtitles = split_list(getattr(args, "subtitles", None))
    if not titles:
        titles = [t for (_d, t, _s) in ex["images"]][:n] if same_n else \
                 [tree_source_title(plan, p, s) for (p, s) in plan.trees]
    if not subtitles:
        subtitles = [s for (_d, _t, s) in ex["images"]][:n] if same_n else []
    default = args.default if getattr(args, "default", None) is not None else (ex["default"] if ex["default"] is not None else 0)
    timeout = args.timeout if getattr(args, "timeout", None) is not None else (ex["timeout"] if ex["timeout"] is not None else 15)
    font = SELECT_DIR + "/font.ttf"
    sel = getattr(args, "selector_dir", None)
    if sel and not os.path.isfile(os.path.join(sel, "font.ttf")) and not os.path.isfile(HOST_FONT):
        font = None
    if media is not None:
        rows, move, confirm = media["rows"], media["sound_move"], media["sound_confirm"]
        volume, mixer = media["volume"], media["mixer_volume"]
    else:
        rows = list(ex.get("media") or [])[:n] if same_n else []
        move, confirm = ex.get("sound_move"), ex.get("sound_confirm")
        volume, mixer = ex.get("volume"), ex.get("mixer_volume")
    if getattr(args, "volume", None) is not None:
        volume = args.volume
    # THE MACHINE'S OWN VOLUME: --machine-volume reads the default image's title for the store
    # and the factory level; without the flag a card already following its machine keeps doing
    # so unless --volume names a number
    mv = None
    if getattr(args, "machine_volume", False):
        k = int(default) if 0 <= int(default) < n else 0
        mv = machine_volume_for(*plan_tree_source(plan, k))
        for note in mv["notes"]:
            say("note: machine volume: %s" % note)
        say("machine volume: the menu follows %s (key %s..., factory %s)"
            % (mv["store"] or "no store (no title read)", mv["key"][:8],
               "unknown" if mv["default"] is None else "%d/63" % mv["default"]))
    elif ex.get("volume") == "machine" and getattr(args, "volume", None) is None:
        mv = ex.get("machine_volume") or {"store": None, "key": MACHINE_VOLUME_KEY, "default": None}
    if volume == "machine":
        volume = None
    if getattr(args, "mixer_volume", None) is not None:
        mixer = args.mixer_volume
    theme = check_theme(getattr(args, "theme", None))
    colors = check_colors(parse_color_flags(getattr(args, "color", None)))
    if theme is None:
        theme = ex.get("theme")
        if theme and theme != CUSTOM_THEME and theme not in theme_names():
            say("note: the card's theme=%s is not a theme this build knows; the default is written" % theme)
            theme = None
        if not colors:
            colors = dict(ex.get("colors") or {})
    return render_images_conf(plan.devices(), titles, subtitles, default, timeout, font,
                              rows, move, confirm, volume, mixer, theme=theme, colors=colors,
                              machine_volume=mv, debug_log=bool(getattr(args, "debug_log", False)))


# ============================================================================= the JSON sidecars
def build_manifest(plan, conf, sources=None, existing=None, written=None, versions=None):
    """build.json: what the card's menu says, plus WHERE each image came from and WHAT GAME CODE
    it was - the provenance a reload needs and images.conf cannot hold.  Pure.

    plan      the card's Plan (for the layout), or None
    conf      the images.conf about to be written, PARSED (parse_images_conf)
    sources   the build's --primary/--extra in image order; an empty or missing entry falls
              back to `existing`
    existing  the build.json already on the card - its sources AND its recorded versions are
              carried through BY DEVICE, so an inject never loses provenance
    versions  :func:`plan_identities`' records in image order (title dir + game code version):
              what the card was BUILT from.  `inspect` re-reads the live truth off the card, so
              this is a record of the build, not an oracle
    """
    prev = {}
    for im in (existing or {}).get("images") or []:
        if isinstance(im, dict) and im.get("device"):
            prev[im["device"]] = im
    vers = {v["device"]: v for v in (versions or []) if v.get("device")}
    sources = list(sources or [])
    rows = []
    for i, (dev, title, sub) in enumerate(conf["images"]):
        art, anim, music, confirm = conf["media"][i] if i < len(conf["media"]) else MEDIA_ROW
        given = sources[i] if i < len(sources) else None
        # only a freshly given path is absolutised; a carried one is already absolute and may
        # be spelled for another OS (a /mnt/d path read on Windows must not be mangled)
        old = prev.get(dev) or {}
        src = os.path.abspath(given) if given else old.get("source")
        v = vers.get(dev) or {}
        rows.append(collections.OrderedDict([
            ("device", dev), ("source", src or None), ("title", title), ("subtitle", sub),
            ("art", art or None), ("anim", anim or None), ("music", music or None),
            ("confirm", confirm or None),
            ("title_dir", v.get("title") or old.get("title_dir")),
            ("version", v.get("version") or old.get("version")),
            ("node_fw_version", v.get("node_fw_version") or old.get("node_fw_version"))]))
    return collections.OrderedDict([
        ("tool", "mkmulticard"),
        ("version", VERSION),
        ("written", written or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        ("layout", getattr(plan, "layout", None)),
        ("images", rows),
        ("timeout", conf["timeout"]),
        ("default", conf["default"]),
        ("volume", conf["volume"]), ("machine_volume", conf.get("machine_volume")),
        ("mixer_volume", conf["mixer_volume"]),
        ("sound_move", conf["sound_move"]),
        ("sound_confirm", conf["sound_confirm"]),
        ("theme", conf.get("theme")),
        ("colors", dict(conf.get("colors") or {}))])


def selector_manifests(plan, conf_text, media_dir=None, sources=None, existing_build=None,
                       existing_media=None, written=None, versions=None, existing_trees=None, trees=None):
    """The JSON sidecars to stage beside images.conf -> OrderedDict {name: text or bytes}.
    build.json is always written (from `conf_text` + `sources`, carrying `existing_build`'s
    sources through); media.json is --media-dir's file verbatim when one was given, else the
    card's own `existing_media` bytes carried through unchanged, else absent; trees.json is
    `trees` (a CardTrees, or its bytes) when given, else the card's own `existing_trees` bytes
    carried through unchanged - an inject must never un-record a card - else absent."""
    out = collections.OrderedDict()
    out[BUILD_MANIFEST] = json.dumps(
        build_manifest(plan, parse_images_conf(conf_text), sources, existing_build, written, versions),
        indent=1) + "\n"
    if media_dir:
        with open(os.path.join(media_dir, MEDIA_MANIFEST), "rb") as f:
            out[MEDIA_MANIFEST] = f.read()
    elif existing_media:
        out[MEDIA_MANIFEST] = existing_media
    if trees is not None:
        out[TREES_MANIFEST] = trees.to_json() if hasattr(trees, "to_json") else trees
    elif existing_trees:
        out[TREES_MANIFEST] = existing_trees
    return out


def parse_manifest(raw, what, warnings=None):
    """A staged JSON sidecar's bytes -> dict, or None.  A malformed one is a warning (a card
    written by a broken run must still load), or a Refusal when no warning list is offered."""
    if raw is None:
        return None
    try:
        obj = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
        why = None if isinstance(obj, dict) else "top level is %s, not an object" % type(obj).__name__
    except ValueError as exc:                            # 'as' names die with the except block
        why = str(exc)
    if why is None:
        return obj
    msg = "%s on the card is not a JSON object (%s); ignored" % (what, why)
    if warnings is None:
        raise Refused(msg)
    warnings.append(msg)
    return None


# ============================================================================= item 93: writing into a card in place
# `update` changes ONLY what changed: it loop-mounts one partition of the card image (root,
# --direct-io=on: measured ~150 MB/s into a .raw on a Windows drive, 30 MB/s buffered, 13 MB/s
# through debugfs), lets the kernel's ext4 do the file work through treesync.DirOps, and keeps
# the record of what is on each tree in trees.json on p2 beside build.json.  Everything a
# reader needs (plan --quick, update --dry-run, verify, inspect) goes through the pure-Python
# ext4 reader and debugfs and never mounts, so those stay ordinary-user runs.
MOUNT_PREFIX = "/var/tmp/mkmulticard_mnt_"
TMP_MARK_CHILD = ".tmp.drill"                  # what the selftest's crash drill leaves behind
LOCK_SUFFIX = ".lock"
P2_BACKUP_SUFFIX = ".p2.bak"


def _treesync():
    """The treesync module (beside this file), imported when first needed."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import treesync
    return treesync


def read_trees(card, ref=None):
    """The card's trees.json as a CardTrees, or None when the card carries none (built before
    item 93 - `update` then hashes the card's own trees once and records them)."""
    ts = _treesync()
    raw = read_select_file(ref or select_ref(card), TREES_MANIFEST)
    if raw is None:
        return None
    try:
        return ts.CardTrees.from_json(raw)
    except ts.TreesError as e:
        raise Refused("%s on %s cannot be read: %s" % (TREES_MANIFEST, card, e))


def loop_available():
    """(ok, why): can this process attach a loop device and mount it?  Root plus util-linux
    plus a kernel with loop support (WSL2 has it; a container may not)."""
    if os.name != "posix" or not hasattr(os, "geteuid"):
        return False, "not a Linux host"
    if os.geteuid() != 0:
        return False, "not root (run under 'wsl -u root')"
    missing = [n for n in ("losetup", "mount", "umount", "findmnt", "fuser", "e2fsck") if shutil.which(n) is None]
    if missing:
        return False, "missing tool(s): " + ", ".join(missing)
    if not os.path.exists("/dev/loop-control"):
        return False, "no /dev/loop-control (the kernel has no loop device support)"
    return True, "root, losetup and /dev/loop-control present"


def _run(argv, ok_rc=(0,)):
    r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = r.stdout.decode("utf-8", "replace")
    if r.returncode not in ok_rc:
        raise Refused("%s failed (rc=%d): %s" % (" ".join(argv), r.returncode, out.strip()))
    return out


def parse_losetup_j(text):
    """`losetup -j FILE` lines -> [(loop device, offset)].  Format: '/dev/loop3: [2049]:1234
    (/path/to/file), offset 364904448' (the offset field is absent for offset 0)."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^(/dev/loop\d+):.*?(?:,\s*offset\s+(\d+))?\s*$", line.strip())
        if m:
            out.append((m.group(1), int(m.group(2) or 0)))
    return out


def loop_mountpoint(loop):
    """Where a loop device is mounted, or None."""
    r = subprocess.run(["findmnt", "-rn", "-S", loop, "-o", "TARGET"], stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL)
    tgt = r.stdout.decode("utf-8", "replace").strip().splitlines()
    return tgt[0] if tgt else None


def mount_in_use(mountpoint):
    """True when a process holds something under the mountpoint (fuser -m says so)."""
    r = subprocess.run(["fuser", "-m", mountpoint], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return bool(r.stdout.strip())


def sweep_stale_loops(card):
    """Detach loop devices an earlier, killed run of THIS tool left on `card`: only those
    mounted under this tool's own mountpoint prefix and held by nobody.  A loop of the same
    file mounted anywhere else (the app's video grow at /var/tmp/pad_grow_*, or a run still
    writing) is a refusal that names the mountpoint - never something to unmount blind.
    -> the number detached."""
    real = os.path.realpath(card)
    r = subprocess.run(["losetup", "-j", real], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = 0
    for loop, _off in parse_losetup_j(r.stdout.decode("utf-8", "replace")):
        mp = loop_mountpoint(loop)
        if mp is None:
            _run(["losetup", "-d", loop])
            say("detached a stale loop %s of %s (attached, not mounted)" % (loop, os.path.basename(card)))
            n += 1
            continue
        if not mp.startswith(MOUNT_PREFIX):
            raise Refused("%s is already mounted at %s (loop %s) by something else - not this tool's mount; "
                          "unmount it first" % (os.path.basename(card), mp, loop))
        if mount_in_use(mp):
            raise Refused("%s is mounted at %s (loop %s) and a process still holds it - an earlier update is "
                          "still running" % (os.path.basename(card), mp, loop))
        say("unmounting a stale mount %s (loop %s) an interrupted run left" % (mp, loop))
        _run(["umount", mp])
        _run(["losetup", "-d", loop])
        try:
            os.rmdir(mp)
        except OSError:
            pass
        n += 1
    return n


def partition_feature_words(card, offset, length):
    _v, _s, ext4, _a = _stern_plugins()
    with open(card, "rb") as f:
        return ext4.Ext4Reader(f, offset, length).feature_words()


#: Journal (jbd2) incompat features the card's 3.14 kernel knows: REVOKE, 64BIT, ASYNC_COMMIT,
#: CSUM_V2, CSUM_V3.  A first rw mount by any kernel sets REVOKE on a journal made without it;
#: anything above these (FAST_COMMIT, 5.10+) would be a feature the card cannot read.
JOURNAL_INCOMPAT_KNOWN = 0x1F


def feature_words_moved(before, after):
    """True when a mount left the filesystem with a feature the card's kernel may not know:
    any change to the ext4 superblock's three words, or a journal incompat bit outside
    JOURNAL_INCOMPAT_KNOWN.  (A journal gaining REVOKE is the one change every kernel makes.)"""
    if tuple(before[:3]) != tuple(after[:3]):
        return True
    if len(before) >= 6 and len(after) >= 6:
        if after[4] & ~JOURNAL_INCOMPAT_KNOWN:
            return True
        if before[3] != after[3] and (after[3] & ~before[3]):
            return False                                   # compat bits: harmless by definition
    return False


def drop_page_cache(card):
    """After a loop device wrote around the page cache (O_DIRECT), make sure no buffered page
    of the card is stale: sync, then tell the kernel to forget what it cached of the file."""
    os.sync()
    try:
        fd = os.open(card, os.O_RDONLY)
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(fd)
    except (OSError, AttributeError):
        pass


class LoopMount:
    """One partition of a card image, attached to a loop device and (unless mount=False)
    mounted rw for the duration of a `with` block -> the mountpoint (or the loop device).

    Order of business: the stale sweep, `losetup --find --show --direct-io=on -o OFF
    --sizelimit LEN` (a retry without direct-io when the kernel or the filesystem refuses,
    with a warning: it is the 5x slower path), the partition's feature words recorded, the
    mount at a fresh /var/tmp/mkmulticard_mnt_* directory.  On the way out, whatever
    happened: umount, losetup -d, rmdir, sync + fadvise, the feature words asserted (a
    foreign kernel must leave nothing the card's 3.14 kernel has never seen), e2fsck -fn.
    SIGTERM/SIGINT become KeyboardInterrupt while inside so the block's finally clauses run.
    """

    def __init__(self, card, offset, length, direct_io=True, mount=True, options="rw,noatime"):
        self.card, self.offset, self.length = card, offset, length
        self.direct_io, self.mount, self.options = direct_io, mount, options
        self.loop = self.mountpoint = None
        self.words = None
        self._old = {}

    def __enter__(self):
        ok, why = loop_available()
        if not ok:
            raise Refused("cannot loop-mount %s: %s" % (self.card, why))
        sweep_stale_loops(self.card)
        self.words = partition_feature_words(self.card, self.offset, self.length)
        base = ["losetup", "--find", "--show", "-o", str(self.offset), "--sizelimit", str(self.length)]
        argv = base[:3] + (["--direct-io=on"] if self.direct_io else []) + base[3:] + [self.card]
        r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode != 0 and self.direct_io:
            say("WARNING: losetup --direct-io=on refused (%s); attaching without it - writes will be slower"
                % r.stdout.decode("utf-8", "replace").strip())
            r = subprocess.run(base + [self.card], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            raise Refused("losetup %s failed: %s" % (self.card, r.stdout.decode("utf-8", "replace").strip()))
        self.loop = r.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
        import signal

        def interrupt(signum, _frame):
            raise KeyboardInterrupt("signal %d" % signum)
        for sig in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", None)):
            if sig is not None:
                try:
                    self._old[sig] = signal.signal(sig, interrupt)
                except (ValueError, OSError):
                    pass
        if not self.mount:
            return self.loop
        self.mountpoint = tempfile.mkdtemp(prefix=MOUNT_PREFIX)
        try:
            _run(["mount", "-t", "ext4", "-o", self.options, self.loop, self.mountpoint])
        except Refused:
            self._detach()
            raise
        return self.mountpoint

    def _detach(self):
        problems = []
        if self.mountpoint:
            os.sync()
            for attempt in range(5):
                r = subprocess.run(["umount", self.mountpoint], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if r.returncode == 0:
                    break
                time.sleep(0.5 * (attempt + 1))
            else:
                problems.append("umount %s: %s" % (self.mountpoint, r.stdout.decode("utf-8", "replace").strip()))
            try:
                os.rmdir(self.mountpoint)
            except OSError:
                pass
        if self.loop:
            r = subprocess.run(["losetup", "-d", self.loop], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if r.returncode != 0:
                problems.append("losetup -d %s: %s" % (self.loop, r.stdout.decode("utf-8", "replace").strip()))
        import signal
        for sig, old in self._old.items():
            try:
                signal.signal(sig, old)
            except (ValueError, OSError):
                pass
        self._old = {}
        drop_page_cache(self.card)
        return problems

    def __exit__(self, exc_type, exc, tb):
        problems = self._detach()
        if problems:
            raise Refused("releasing %s: %s" % (self.card, "; ".join(problems)))
        after = partition_feature_words(self.card, self.offset, self.length)
        if feature_words_moved(self.words, after):
            raise Refused("the mount CHANGED the filesystem's feature words on %s (%r -> %r): a kernel newer "
                          "than the card's may have added a feature it cannot read; the card is left as "
                          "it is for a look" % (os.path.basename(self.card), self.words, after))
        rc, txt = e2fsck(fs_ref(self.card, self.offset))
        if rc != 0:
            raise Refused("e2fsck -fn is not clean after the mount of %s@%d (rc=%d):\n%s"
                          % (os.path.basename(self.card), self.offset, rc, txt.strip()[-800:]))
        return False


class DirOps(object):
    """treesync.FsOps over a directory - the mounted partition.  Paths are relative to it."""

    def __init__(self, root):
        self.root = root
        self._base = _treesync().FsOps

    def _p(self, rel):
        return os.path.join(self.root, rel) if rel else self.root

    def lstat(self, rel):
        try:
            st = os.lstat(self._p(rel))
        except FileNotFoundError:
            return None
        if statmod.S_ISDIR(st.st_mode):
            kind = "dir"
        elif statmod.S_ISREG(st.st_mode):
            kind = "file"
        elif statmod.S_ISLNK(st.st_mode):
            kind = "symlink"
        else:
            kind = "other"
        d = {"kind": kind, "mode": st.st_mode & 0o7777, "uid": st.st_uid, "gid": st.st_gid, "ino": st.st_ino,
             "size": st.st_size, "nlink": st.st_nlink, "mtime": int(st.st_mtime)}
        if kind == "symlink":
            d["target"] = os.readlink(self._p(rel))
        return d

    def listdir(self, rel):
        return os.listdir(self._p(rel))

    def _own(self, p, uid, gid):
        # Only root can give a file to another owner: a plain-user run (the
        # tests' walk of a scratch directory; every real update is root)
        # leaves ownership alone rather than dying on EPERM.
        if hasattr(os, "chown") and getattr(os, "geteuid", lambda: 0)() == 0:
            os.chown(p, uid, gid)

    def mkdir(self, rel, mode, uid, gid):
        os.mkdir(self._p(rel))
        self._own(self._p(rel), uid, gid)
        os.chmod(self._p(rel), mode)

    def rmdir(self, rel):
        os.rmdir(self._p(rel))

    def symlink(self, rel, target, uid, gid):
        os.symlink(target, self._p(rel))
        try:
            os.lchown(self._p(rel), uid, gid)
        except (OSError, AttributeError):
            pass

    def unlink(self, rel):
        os.unlink(self._p(rel))

    def rename(self, a, b):
        os.replace(self._p(a), self._p(b))

    def link(self, src, dst):
        os.link(self._p(src), self._p(dst))

    def write_stream(self, rel, chunks, mode, uid, gid, mtime):
        p = self._p(rel)
        with open(p, "wb") as f:
            for c in chunks:
                f.write(c)
            f.flush()
            # NO fsync per file: on the loop device each one forces a journal commit that
            # waits on the backing file through 9p (measured: 11 MB/s, in jbd2_log_wait_commit,
            # against ~150 MB/s streaming).  Durability comes from commit() - os.sync() before
            # the record is written - and a crash before it is what the dirty flag repairs.
        self._own(p, uid, gid)
        os.chmod(p, mode)
        os.utime(p, (mtime, mtime))

    def set_attrs(self, rel, mode=None, uid=None, gid=None):
        p = self._p(rel)
        if (uid is not None or gid is not None) and hasattr(os, "chown"):
            st = os.lstat(p)
            os.chown(p, st.st_uid if uid is None else uid, st.st_gid if gid is None else gid)
        if mode is not None:
            os.chmod(p, mode)

    def free_bytes(self):
        return shutil.disk_usage(self.root).free

    def commit(self):
        os.sync()

    # the FsOps helpers, borrowed
    def exists(self, rel):
        return self.lstat(rel) is not None

    def walk_files(self, rel=""):
        return self._base.walk_files(self, rel)

    def rmtree(self, rel):
        return self._base.rmtree(self, rel)


class CardLock:
    """`with CardLock(card):` - one update of a card at a time.  A non-blocking flock on
    <card>.lock; a held lock is a LIVE run, never a stale one (the stale-loop sweep runs
    after this, so it can only ever find a dead run's leftovers)."""

    def __init__(self, card):
        self.path = card + LOCK_SUFFIX
        self.fd = None

    def __enter__(self):
        import fcntl
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            holder = ""
            try:
                holder = os.read(self.fd, 64).decode("utf-8", "replace").strip()
            except OSError:
                pass
            os.close(self.fd)
            self.fd = None
            raise Refused("another update of %s is still running%s (%s is locked)"
                          % (os.path.basename(self.path[:-len(LOCK_SUFFIX)]), (" - pid " + holder) if holder else "",
                             os.path.basename(self.path)))
        os.ftruncate(self.fd, 0)
        os.write(self.fd, ("%d\n" % os.getpid()).encode("utf-8"))
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                os.ftruncate(self.fd, 0)
            except OSError:
                pass
            os.close(self.fd)
            self.fd = None
        return False


def lock_held(card):
    """True when another process holds the card's update lock (a reader then says 'busy')."""
    path = card + LOCK_SUFFIX
    if os.name != "posix" or not os.path.exists(path):
        return False
    import fcntl
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def p2_backup(card):
    """<card>.p2.bak = the card's p2 as it is now (the rootfs: the one partition an interrupted
    write could leave unbootable; `dd` it back).  -> the path."""
    off, length = p2_range(card)
    bak = card + P2_BACKUP_SUFFIX
    with open(bak, "wb") as f:
        f.truncate(length)
    copy_range(card, off, bak, 0, length, "p2 backup", sparse=False, progress=None)
    return bak


def select_write_commands(items, remove=()):
    """The debugfs -w script that puts `items` = [(staged native path, name)] into SELECT_DIR
    IN PLACE (rm + write + mode/uid/gid) and removes `remove` names.  Pure."""
    cmds = []
    for _staged, name in items:
        cmds.append("rm " + dq(SELECT_DIR + "/" + name))
    for name in remove:
        cmds.append("rm " + dq(SELECT_DIR + "/" + name))
    for staged, name in items:
        cmds.append("write %s %s" % (dq(staged), dq(SELECT_DIR + "/" + name)))
    for _staged, name in items:
        card = dq(SELECT_DIR + "/" + name)
        cmds.append("set_inode_field %s mode 0100644" % card)
        cmds.append("set_inode_field %s uid 0" % card)
        cmds.append("set_inode_field %s gid 0" % card)
    return cmds


def write_select_files(card, files, remove=(), workdir=None):
    """Write small files into the card's p2 SELECT_DIR without extracting the partition: a
    debugfs -w script straight into the card (rm + write + mode/uid/gid), e2fsck -fn, the p2
    md5 sidecar rewritten.  `files` = {name: bytes}; names must be selector sidecars.  A kill
    mid-script leaves at worst one small file half written, which e2fsck -fy reconciles - the
    rootfs stays bootable, which the 352 MB extract/write-back of inject_card cannot promise.
    -> the names written."""
    need_tools("debugfs", "e2fsck")
    off, length = p2_range(card)
    ref = fs_ref(card, off)
    if not debugfs_exists(ref, SELECT_DIR):
        raise Refused("%s has no %s on its p2 (not a multi-boot card)" % (card, SELECT_DIR))
    rc, txt = e2fsck(ref)
    if rc != 0:
        raise Refused("p2 of %s is not clean before the write (e2fsck rc=%d):\n%s" % (card, rc, txt.strip()[-600:]))
    used, total = e2fsck_blocks(txt)
    bs = ext_block_size(card, off)
    free = (total - used) * bs
    need = sum(len(b) for b in files.values())
    reclaim = 0
    for e in debugfs_ls(ref, SELECT_DIR):
        if e[4] in files or e[4] in remove:
            reclaim += e[5]
    if need > free + reclaim - min(P2_FREE_MARGIN, total * bs // 20):
        raise Refused("p2 has %d KB free (+ %d KB the rewrite frees) and %s needs %d KB"
                      % (free >> 10, reclaim >> 10, ", ".join(sorted(files)), need >> 10))
    stage = tempfile.mkdtemp(prefix="mkmulticard.p2w.", dir=workdir)
    try:
        items = []
        for name in sorted(files):
            p = os.path.join(stage, name)
            with open(p, "wb") as f:
                f.write(files[name])
            items.append((p, name))
        present = {e[4] for e in debugfs_ls(ref, SELECT_DIR)}
        # rm only what is there (debugfs reports a missing rm as an error line); the script is
        # every rm, then every write, then every attribute - in that order
        cmds = ["rm " + dq(SELECT_DIR + "/" + n) for (_p, n) in items if n in present]
        cmds += ["rm " + dq(SELECT_DIR + "/" + n) for n in remove if n in present]
        cmds += ["write %s %s" % (dq(p), dq(SELECT_DIR + "/" + n)) for (p, n) in items]
        for _p, n in items:
            c = dq(SELECT_DIR + "/" + n)
            cmds += ["set_inode_field %s mode 0100644" % c, "set_inode_field %s uid 0" % c,
                     "set_inode_field %s gid 0" % c]
        debugfs_write_script(ref, cmds)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    rc, txt = e2fsck(ref)
    if rc != 0:
        raise Refused("p2 of %s is not clean after the write (e2fsck rc=%d):\n%s" % (card, rc, txt.strip()[-600:]))
    for name, data in files.items():
        back = debugfs_cat(ref, SELECT_DIR + "/" + name)
        if back != data:
            raise Refused("%s read back from p2 differs from what was written" % name)
    write_p2_sidecar(card)
    return sorted(files)


def write_trees(card, trees, build_json=None, workdir=None):
    """Record `trees` (a CardTrees) on the card's p2 - and, when given, the new build.json -
    through write_select_files."""
    files = {TREES_MANIFEST: trees.to_json()}
    if build_json is not None:
        files[BUILD_MANIFEST] = build_json if isinstance(build_json, bytes) else build_json.encode("utf-8")
    return write_select_files(card, files, workdir=workdir)


def plan_with_p7_sectors(card, new_sectors):
    """The card's own Plan (plan_from_card) with the multi p7 given `new_sectors` - what
    write_tables needs to grow the last partition in place."""
    G = Geometry.from_file(card)
    subs = multi_subdirs_on(card, 7)
    if not subs or len(G.logical) != 3:
        raise Refused("%s is not a multi-layout card with a p7 to grow" % card)
    base = Geometry(G.size, G.mbr, G.prim, G.ext, G.logical[:2], G.ebr_raw, card)
    return Plan(base, [], card, [], "multi", multi_sectors=int(new_sectors), multi_subdirs=subs, multi_src=None)


def grow_last_partition(card, new_sectors):
    """Grow the multi layout's p7 (the last partition) IN PLACE to `new_sectors`: the image
    file is extended, the extended container's and p7's table entries rewritten, then
    resize2fs runs on the loop device (unmounted) and e2fsck -fn checks the result.  The
    filesystem keeps its identity; only its block count moves.  -> the new Plan."""
    need_tools("resize2fs", "e2fsck", "losetup")
    plan = plan_with_p7_sectors(card, new_sectors)
    p7 = plan.multi_part
    old_total = os.path.getsize(card)
    if plan.total_bytes < old_total:
        raise Refused("p7 can only grow (%d -> %d sectors would shrink the image)" % (old_total // SECTOR, plan.total))
    say("growing p%d of %s to %d sectors (%s); the image becomes %s"
        % (p7.num, os.path.basename(card), p7.count, _gb(p7.count * SECTOR), _gb(plan.total_bytes)))
    with open(card, "r+b") as f:
        f.truncate(plan.total_bytes)
    write_tables(plan, card)
    with LoopMount(card, p7.start * SECTOR, p7.count * SECTOR, mount=False) as loop:
        _run(["e2fsck", "-fp", loop], ok_rc=(0, 1))
        out = _run(["resize2fs", loop])
        say("resize2fs: " + " ".join(line.strip() for line in out.splitlines() if "now" in line))
    return plan


# ============================================================================= item 93: the record and `update`
CACHE_DIRNAME_HINT = "pinball_spike2_multiboot"
UPDATE_SLACK = 0.10                            # --expect-bytes tolerance
UPDATE_SLACK_BYTES = 64 << 20
P2_SKIP = ("usr/local/codeselect", "etc/init.d/game")   # what the primary gate leaves out of p2


def partition_free(path, offset, length):
    """(free, total) bytes of the ext4 at `offset`, from its superblock."""
    used, total = ext_used_bytes(path, offset)
    return max(0, total - used), total


def games_free(card, plan):
    """{partition number: (free, total)} of every games partition the plan names."""
    out = {}
    for p, _sub in plan.trees:
        if p.num not in out:
            out[p.num] = partition_free(card, p.start * SECTOR, p.count * SECTOR)
    return out


def source_tree(path, cache_dir=None, progress=None):
    """(SourceManifest, 'cached'|'hashed') of a SOURCE card's games tree (its p3 root)."""
    ts = _treesync()
    part = source_part(path)
    return ts.source_manifest(path, part.start * SECTOR, part.count * SECTOR, root_ino=2, cache_dir=cache_dir,
                              progress=progress)


def card_tree(card, part, sub, cache_dir=None, progress=None, skip=None):
    """(SourceManifest, how) of one games tree ON a card - what `update` reads off a card built
    before trees.json existed, cached under the CARD's own stamp.  `skip` names root entries
    the walk leaves out (a store card's root: the store and the extras' trees)."""
    ts = _treesync()
    _v, _s, ext4, _a = _stern_plugins()
    with open(card, "rb") as f:
        r = ext4.Ext4Reader(f, part.start * SECTOR, part.count * SECTOR)
        root = tree_root_inode(r, sub)
    return ts.source_manifest(card, part.start * SECTOR, part.count * SECTOR, root_ino=root,
                              sub=device_name(part.num, sub), cache_dir=cache_dir, progress=progress, skip=skip)


def tree_skip(plan, sub):
    """What a walk of a games tree's root leaves out: lost+found - and, at a store card's root,
    the store and the extras' trees, which live beside the primary's own (item 95)."""
    ts = _treesync()
    if plan is not None and plan.layout == "store" and not sub:
        return tuple(ts.SKIP_ROOT) + tuple(ts.STORE_SKIP) + tuple(plan.store_subdirs)
    return tuple(ts.SKIP_ROOT)


def p2_digest(path, cache_dir=None):
    """A digest of a card's p2 CONTENT minus what this tool puts there (the selector directory
    and the hooked game script): the same for a source and for the card built from it, however
    many times the menu was re-injected, and unmoved by a rw mount (a range md5 is not).
    Cached under the file's stamp like a games tree."""
    ts = _treesync()
    t, st, cnt = Geometry.from_file(path).part(2)
    if t != 0x83:
        raise Refused("%s: p2 is type 0x%02x, not Linux" % (path, t))
    man, _how = ts.source_manifest(path, st * SECTOR, cnt * SECTOR, root_ino=2, sub="p2", cache_dir=cache_dir)
    keep = ts.TreeManifest(
        {k: v for k, v in man.tree.files.items() if not k.startswith(P2_SKIP[0]) and k != P2_SKIP[1]},
        {k: v for k, v in man.tree.symlinks.items() if not k.startswith(P2_SKIP[0])},
        {k: v for k, v in man.tree.dirs.items() if not k.startswith(P2_SKIP[0])})
    return hashlib.sha256(json.dumps(keep.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def primary_identity(path, cache_dir=None):
    """{'p1_md5', 'p2_tree'}: what the update gate compares a card's primary with a source's."""
    t, st, cnt = Geometry.from_file(path).part(1)
    return {"p1_md5": md5_range(path, st * SECTOR, cnt * SECTOR), "p2_tree": p2_digest(path, cache_dir)}


def primary_gate(card, source, recorded=None, cache_dir=None):
    """Refuse an update whose primary source is a different BUILD from the card's: p1 (the
    kernel) must be the same bytes, p2's content minus this tool's files the same tree, and the
    card's game script must be the source's plus the hook.  `recorded` (trees.json's primary
    identity) stands in for the card's own p2 digest when present.  -> the source's identity."""
    src = primary_identity(source, cache_dir)
    got = dict(recorded or {})
    if not got.get("p1_md5") or not got.get("p2_tree"):
        got = primary_identity(card, cache_dir)
    why = []
    if src["p1_md5"] != got["p1_md5"]:
        why.append("the kernel partition (p1) differs")
    if src["p2_tree"] != got["p2_tree"]:
        why.append("the rootfs (p2) differs beyond the boot menu's own files")
    try:
        cur = debugfs_cat(select_ref(card), GAME_SCRIPT).decode("utf-8", "replace")
        t2, s2, c2 = Geometry.from_file(source).part(2)
        orig = debugfs_cat(fs_ref(source, s2 * SECTOR), GAME_SCRIPT).decode("utf-8", "replace")
        if strip_hook(cur) != orig:
            why.append("%s differs beyond the hook" % GAME_SCRIPT)
    except Refused as e:
        why.append("the game script could not be compared (%s)" % e)
    if why:
        raise Refused("%s is not the primary this card was built from - %s. An update cannot carry that; "
                      "build a fresh card." % (os.path.basename(source), "; ".join(why)))
    return src


def record_sources(plan, cache_dir=None, progress=None):
    """trees.json for a BUILD of `plan`: every source's games tree hashed (or from the cache),
    the primary's identity for the update gate.  -> CardTrees.  Prints one line per source."""
    ts = _treesync()
    images = []
    srcs = [plan.primary] + list(plan.extras)
    for i, (part, sub) in enumerate(plan.trees):
        path = srcs[i] if i < len(srcs) else None
        if not path:
            continue
        t0 = time.monotonic()
        man, how = source_tree(path, cache_dir, progress)
        took = "" if how == "cached" else " in %.0f s" % (time.monotonic() - t0)
        say("%s: %d files, %s (%s%s)" % (os.path.basename(path), len(man.tree.files), _gb(man.tree.bytes()), how, took))
        images.append(ts.ImageTrees(i, device_name(part.num, sub), sub or "", man.tree, man.stamp, man.uuid))
    return ts.CardTrees(images, primary=primary_identity(plan.primary, cache_dir), layout=plan.layout, version=VERSION)


def refuse_if_dirty(card, ref=None):
    rec = read_trees(card, ref)
    if rec is not None and rec.dirty:
        which = ", ".join("p%d" % n for n in rec.dirty)
        raise Refused("%s is mid-update (partition%s %s dirty): run `update` again to finish or repair it before "
                      "anything else writes to it" % (os.path.basename(card), "s" if len(rec.dirty) > 1 else "", which))


def card_in_use(card):
    """A sentence when something else holds the card open the way an in-place write would break:
    a fuse2fs mount of it (the emulator with its cache off mounts the ORIGINAL .raw) or a card
    cache copier whose command line names it (a dd publishing a torn copy as valid).  None when
    the card is free.  Linux only; elsewhere None."""
    if os.name != "posix":
        return None
    real = os.path.realpath(card)
    try:
        r = subprocess.run(["findmnt", "-rn", "-t", "fuse.fuse2fs,fuse.ext4,fuse", "-o", "SOURCE,TARGET"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            parts = line.split()
            if parts and os.path.realpath(parts[0]) == real:
                return "%s is mounted at %s (fuse2fs - the emulator?); stop that first" % (
                    os.path.basename(card), parts[1] if len(parts) > 1 else "?")
    except OSError:
        pass
    home = os.environ.get("PAD_HOME") or os.path.expanduser("~")
    cache = os.path.join(home, "cardcache")
    if os.path.isdir(cache):
        for name in os.listdir(cache):
            if not name.endswith(".pid"):
                continue
            try:
                with open(os.path.join(cache, name)) as f:
                    pid = int(f.read().split()[0])
                with open("/proc/%d/cmdline" % pid, "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
            except (OSError, ValueError, IndexError):
                continue
            if card in cmd or real in cmd:
                return "the emulator's card cache is copying %s right now (pid %d); let it finish" % (
                    os.path.basename(card), pid)
    return None


def bypass_tree_bytes(elf, sdata, gpath, title):
    """PURE: the validator bypass on a tree's bytes -> (state before, new ELF or None, new .sidx
    or None, notes).  The ELF is patched when armed; the .sidx record is refreshed whenever its
    digest disagrees with the ELF as it will be - NEVER gated on the ELF's state (a tree whose
    game was already patched but whose manifest still says otherwise is exactly the case the
    spk layer flags)."""
    valpatch, sidx, _e, _a = _stern_plugins()
    elf = bytearray(elf)
    state = bypass_state(elf)
    notes = ["%s (%d bytes): %s" % (gpath, len(elf), state)]
    new_elf = None
    if state in ("armed", "half"):
        overlay, _status = valpatch.bypass_overlay(bytes(elf))
        for poff, b in sorted(overlay.items()):
            elf[poff:poff + len(b)] = b
        new_elf = bytes(elf)
        notes.append("bx lr at ELF offset 0x%x%s" % (
            valpatch.find_validation_exec(bytes(elf)),
            ", grade restore off at 0x%x" % valpatch.find_grade_restore(bytes(elf))
            if valpatch.find_grade_restore(bytes(elf)) is not None else ", grade restore NOT located"))
    new_sidx = None
    if sdata is not None and state in ("armed", "half", "bypassed"):
        recs, _crc, fmt = sidx.parse_records(sdata)
        cands = [gpath, "%s/game" % title, "%s/game_real" % title]
        rec_path = next((c for c in cands if c in recs), None)
        if rec_path is None:
            notes.append("the .sidx has no record for %s - the spk layer may flag the game file" % gpath)
        else:
            hm, md = sidx.digests(bytes(elf))
            buf = bytearray(sdata)
            for foff, rb in sidx.record_field_writes(recs[rec_path], hm, md, fmt):
                buf[foff:foff + len(rb)] = rb
            if bytes(buf) != bytes(sdata):
                new_sidx = bytes(buf)
                notes.append(".sidx record %r (%s) refreshed" % (rec_path, fmt))
    return state, new_elf, new_sidx, notes


def _find_tree_game(root):
    """(title, game rel, sidx rel or None) inside a MOUNTED tree at `root`, the way tree_game
    and tree_sidx find them through the reader."""
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if name in ("lost+found", "spk") or not os.path.isdir(d) or os.path.islink(d):
            continue
        if not os.path.exists(os.path.join(d, "game")):
            continue
        for cand in ("game_real", "game"):
            p = os.path.join(d, cand)
            if os.path.isfile(p) and not os.path.islink(p) and os.path.getsize(p) > 0:
                spath = None
                idx = os.path.join(root, "spk", "index")
                if os.path.isdir(idx):
                    for s in sorted(os.listdir(idx)):
                        if s.endswith(".sidx") and os.path.isfile(os.path.join(idx, s)) \
                                and not os.path.islink(os.path.join(idx, s)):
                            spath = "spk/index/" + s
                            break
                return name, "%s/%s" % (name, cand), spath
    raise Refused("no title directory with a game file in %s" % root)


def apply_bypass_fs(ops, prefix):
    """The validator bypass on the tree at `prefix` through a mounted filesystem (never a raw
    write behind a mount): the patched ELF and the refreshed .sidx are written tmp + rename
    with the old files' mode/owner/mtime.  -> (state before, {rel: sha256 of what is now on the
    card}, notes)."""
    ts = _treesync()
    root = ops._p(prefix) if prefix else ops.root
    title, gpath, spath = _find_tree_game(root)
    with open(os.path.join(root, gpath), "rb") as f:
        elf = f.read()
    sdata = None
    if spath:
        with open(os.path.join(root, spath), "rb") as f:
            sdata = f.read()
    state, new_elf, new_sidx, notes = bypass_tree_bytes(elf, sdata, gpath, title)
    written = {}
    for rel, data in ((gpath, new_elf), (spath, new_sidx)):
        if data is None or rel is None:
            continue
        full = ts._join(prefix, rel)
        st = ops.lstat(full)
        tmp = ts.tmp_name(full)
        ops.write_stream(tmp, [data], st["mode"], st["uid"], st["gid"], st["mtime"])
        ops.rename(tmp, full)
        written[rel] = hashlib.sha256(data).hexdigest()
    return state, written, notes, gpath, spath


def adopt_written(ops, prefix, written):
    """After the bypass wrote a patched game / a refreshed .sidx into a store card's tree (a
    new inode each, tmp + rename), link them into the store under their own keys - or replace
    them by a link to the identical blob another tree's bypass already made - so every file of
    every tree stays a link to a blob (what verify holds a store card to)."""
    ts = _treesync()
    for rel, sha in written.items():
        full = ts._join(prefix, rel)
        st = ops.lstat(full)
        if st is None or st["kind"] != "file":
            continue
        blob = ts.BLOBS_DIR + "/" + "%s.%04o.%d.%d" % (sha, st["mode"] & 0o7777, st["uid"], st["gid"])
        bst = ops.lstat(blob)
        if bst is None:
            ops.link(full, blob)
        elif bst["ino"] != st["ino"]:
            tmp = ts.tmp_name(full)
            if ops.exists(tmp):
                ops.unlink(tmp)
            ops.link(blob, tmp)
            ops.rename(tmp, full)


def build_store(plan, out, trees):
    """Turn the freshly copied p3 of a store card into the store (item 95): resize2fs on the
    loop device grows Stern's own filesystem to the plan's size (its UUID, label, features and
    inode numbers untouched); through one rw mount the primary's files are linked into
    `.blobs/` without a byte rewritten (adopt_tree), then every extra is synced into its
    imgK/ writing only the blobs the store does not hold yet."""
    ts = _treesync()
    _v, _s, ext4, _a = _stern_plugins()
    need_tools("resize2fs", "e2fsck", "losetup")
    p3 = plan.prims[2]
    off, length = p3.start * SECTOR, p3.count * SECTOR
    t0 = time.monotonic()
    if p3.count > (plan.store_src_count or p3.count):
        PROGRESS.step("growing the games partition to %s" % _gb(length))
        with LoopMount(out, off, length, mount=False) as loop:
            _run(["e2fsck", "-fp", loop], ok_rc=(0, 1))
            res = _run(["resize2fs", loop])
            say("resize2fs p3: " + " ".join(line.strip() for line in res.splitlines() if "now" in line))
    srcs = [plan.primary] + list(plan.extras)
    with LoopMount(out, off, length) as mp:
        ops = DirOps(mp)
        man0 = trees.image(0).tree
        PROGRESS.step("linking the primary's %d files into the store" % len(man0.files))
        st = ts.adopt_tree(ops, "", man0)
        say("store: the primary's tree adopted - %d files became blobs, %d duplicates inside it freed (%s)"
            % (st["adopted"], st["deduped"], _gb(st["bytes_freed"])))
        for i, (part, sub) in enumerate(plan.trees):
            if i == 0:
                continue
            tree = trees.image(i).tree
            if not ops.exists(sub):
                ops.mkdir(sub, 0o755, 0, 0)
            changes = ts.diff_tree(None, tree)
            with open(srcs[i], "rb") as f:
                spart = source_part(srcs[i])
                r = ext4.Ext4Reader(f, spart.start * SECTOR, spart.count * SECTOR)
                if not tree.inodes:                              # a cached manifest: find the inodes
                    for rel, kind, ino, _node in r.iter_tree(2):
                        if kind == "file":
                            tree.inodes[rel] = ino
                PROGRESS.step("writing image %d (%s) into the store" % (i, os.path.basename(srcs[i])),
                              sum(c.size for c in changes if c.op == "write"))
                stats = ts.apply_changes(ops, sub, changes, tree, ts.ReaderSource(r, tree), PROGRESS, store=True)
            say("image %d %s: %d files written (%s), %d linked to blobs the store already held"
                % (i, device_name(part.num, sub), stats["written"], _gb(stats["bytes"]), stats["linked"]))
        ops.commit()
    say("store built in %.0f s" % (time.monotonic() - t0))


def bypass_store(card, plan, trees):
    """The validator bypass on every tree of a store card, THROUGH the mount: a raw write
    behind a shared blob would patch every tree at once and leave the record wrong.  Each
    tree's patched game and refreshed .sidx are written as their own inodes, then linked into
    the store under their own keys (two trees with the same stock game share one patched one);
    the digests go into the record; blobs nothing links any more are removed."""
    print("== validator bypass (through the store's mount)")
    ts = _treesync()
    p3 = plan.prims[2]
    with LoopMount(card, p3.start * SECTOR, p3.count * SECTOR) as mp:
        ops = DirOps(mp)
        for i, (part, sub) in enumerate(plan.trees):
            dev = device_name(part.num, sub)
            try:
                state, written, notes, gpath, spath = apply_bypass_fs(ops, sub or "")
            except Refused as e:
                print("image %d %s: validator: SKIPPED (%s)" % (i, dev, e))
                continue
            adopt_written(ops, sub or "", written)
            im = trees.image(i)
            if written:
                by = {"game_path": gpath, "sidx_path": spath}
                for rel, sha in written.items():
                    by["game" if rel == gpath else "sidx"] = sha
                im.bypass = by
            after = "bypassed" if (written and gpath in written) or state == "bypassed" else state
            line = bypass_words(after)
            if written:
                line += " (%s written)" % ", ".join(sorted(written))
            elif state == "bypassed":
                line += " (already)"
            print("image %d %s: %s - %s" % (i, dev, line, "; ".join(notes)))
        n, nbytes = ts.gc_blobs(ops)
        if n:
            say("store: %d blob(s) no tree links any more removed (%s)" % (n, _gb(nbytes)))
        ops.commit()


def verify_store(card, plan, rec, check, mode="full"):
    """The store's own invariants (item 95): every blob's name parses and its inode's
    mode/owner match the name; every regular file of every tree IS a link into the store (the
    same inode as a blob); every blob's link count is 1 + the links the trees hold; no
    half-written blob, no orphan; and, in 'full' mode, every blob's content hashes to its
    name (the trees' own content is verify_trees' business)."""
    ts = _treesync()
    _v, _s, ext4, _a = _stern_plugins()
    p3 = plan.prims[2]
    with open(card, "rb") as f:
        r = ext4.Ext4Reader(f, p3.start * SECTOR, p3.count * SECTOR)
        ents = _dir_entries(r, 2)
        if ts.BLOBS_DIR not in ents:
            check("store: %s at the root of p3" % ts.BLOBS_DIR, False)
            return
        blobs, bad_names, bad_attrs, tmp = {}, [], [], []
        for name, (c, _t) in _dir_entries(r, ents[ts.BLOBS_DIR][0]).items():
            node = r.read_inode(c)
            if ts.is_tmp(name):
                tmp.append(name)
                continue
            key = ts.parse_blob_key(name)
            if key is None or (node["mode"] & ext4.S_IFMT) != ext4.S_IFREG:
                bad_names.append(name)
                continue
            if (node["mode"] & 0o7777, node["uid"], node["gid"]) != key[1:]:
                bad_attrs.append(name)
            blobs[name] = (c, node)
        check("store: %d blobs, every name a blob's, none half-written" % len(blobs), not bad_names and not tmp,
              "odd %r tmp %r" % (bad_names[:3], tmp[:3]))
        check("store: blob mode/owner match their names", not bad_attrs, "%r" % bad_attrs[:3])
        by_ino = {c: name for name, (c, _n) in blobs.items()}
        refs = collections.Counter()
        unlinked = []
        for i, (part, sub) in enumerate(plan.trees):
            try:
                root = tree_root_inode(r, sub)
            except Refused as e:
                check("store: image %d %s root" % (i, device_name(part.num, sub)), False, str(e))
                continue
            for rel, kind, ino, _node in r.iter_tree(root, skip=tree_skip(plan, sub)):
                if kind != "file":
                    continue
                if ino in by_ino:
                    refs[ino] += 1
                else:
                    unlinked.append("%s:%s" % (device_name(part.num, sub), rel))
        check("store: every file of every tree is a link into the store", not unlinked, "%r" % unlinked[:5])
        bad_links = ["%s links %d refs %d" % (name, node["links"], refs.get(c, 0))
                     for name, (c, node) in blobs.items() if node["links"] != 1 + refs.get(c, 0)]
        check("store: link count = 1 + references, every blob", not bad_links, "%r" % bad_links[:3])
        orphans = [name for name, (c, _n) in blobs.items() if refs.get(c, 0) == 0]
        check("store: no orphan blobs", not orphans, "%r" % orphans[:3])
        if mode == "full":
            t0 = time.monotonic()
            bad, nbytes = [], 0
            for name, (c, node) in sorted(blobs.items()):
                nbytes += node["size"]
                if ts.hash_inode(r, node) != name.split(".")[0]:
                    bad.append(name)
            check("store: %d blobs hash to their names (%s, %.0f s)" % (len(blobs), _gb(nbytes), time.monotonic() - t0),
                  not bad, "%r" % bad[:3])


def verify_trees(card, plan, rec, mode, check, touched=None):
    """Every recorded tree against trees.json: paths, kinds, mode/owner, symlink targets, and
    the CONTENT of every file ('full'), of the touched files + game + .sidx ('touched') or of a
    sample of 32 + game + .sidx ('quick').  The bypass's own digests override the source's for
    the game and the .sidx."""
    ts = _treesync()
    _v, _s, ext4, _a = _stern_plugins()
    import random
    for im in rec.images:
        if im.index >= len(plan.trees):
            check("image %d %s recorded but not on the card" % (im.index, im.device), False)
            continue
        part, sub = plan.trees[im.index]
        dev = device_name(part.num, sub)
        want = im.tree
        by = im.bypass or {}
        override = {by.get("game_path"): by.get("game"), by.get("sidx_path"): by.get("sidx")}
        t0 = time.monotonic()
        with open(card, "rb") as f:
            r = ext4.Ext4Reader(f, part.start * SECTOR, part.count * SECTOR)
            root = tree_root_inode(r, sub)
            files, links, dirs, nodes = {}, {}, {}, {}
            for rel, kind, ino, node in r.iter_tree(root, skip=tree_skip(plan, sub)):
                if kind == "file":
                    files[rel] = node
                elif kind == "symlink":
                    links[rel] = r.read_symlink(node)
                elif kind == "dir":
                    dirs[rel] = node
                nodes[rel] = node
            missing = sorted(set(want.files) - set(files))[:5]
            extra = sorted(set(files) - set(want.files))[:5]
            detail = ("missing %r " % missing if missing else "") + ("extra %r" % extra if extra else "")
            check("image %d %s files: %d recorded, %d on the card" % (im.index, dev, len(want.files), len(files)),
                  set(files) == set(want.files), detail)
            links_ok = set(links) == set(want.symlinks) and all(
                links[k] == want.symlinks[k].target for k in want.symlinks if k in links)
            check("image %d %s symlinks" % (im.index, dev), links_ok)
            check("image %d %s directories" % (im.index, dev), set(dirs) == set(want.dirs))

            def attrs_of(rel):
                return files[rel]["mode"] & 0o7777, files[rel]["uid"], files[rel]["gid"]
            bad_attr = [rel for rel, rr in want.files.items()
                        if rel in files and attrs_of(rel) != (rr.mode, rr.uid, rr.gid)]
            check("image %d %s file mode/owner" % (im.index, dev), not bad_attr, "%r" % bad_attr[:5])
            if mode == "full":
                sample = sorted(want.files)
            else:
                sample = set((touched or {}).get(im.index, ()))
                sample |= {k for k in override if k}
                if mode == "quick":
                    pool = [k for k in want.files if k not in sample]
                    random.seed(1)
                    sample |= set(random.sample(pool, min(32, len(pool))))
                sample = sorted(k for k in sample if k in want.files)
            bad = []
            nbytes = 0
            for rel in sample:
                if rel not in files:
                    continue
                got = ts.hash_inode(r, files[rel])
                nbytes += files[rel]["size"]
                exp = override.get(rel) or want.files[rel].sha256
                if got != exp:
                    bad.append(rel)
            check("image %d %s content: %d of %d files re-hashed (%s, %.0f s)"
                  % (im.index, dev, len(sample), len(want.files), _gb(nbytes), time.monotonic() - t0),
                  not bad, "differ: %r" % bad[:5])


def trees_report(card, plan, rec, warnings):
    """inspect's 'trees' block, or None for a card with no record."""
    if rec is None:
        return None
    ts = _treesync()
    free = None
    if plan is not None:
        try:
            free = sum(fr for fr, _t in games_free(card, plan).values())
        except (Refused, OSError, struct.error) as e:
            warnings.append("the games partitions' free space could not be read: %s" % e)
    images = []
    for im in rec.images:
        changed = None
        if im.stamp and im.stamp.get("path") and os.path.isfile(im.stamp["path"]):
            changed = not ts.stamps_equal(ts.source_stamp(im.stamp["path"]), im.stamp)
        images.append(collections.OrderedDict([
            ("index", im.index), ("device", im.device), ("files", len(im.tree.files)),
            ("tree_bytes", im.tree.bytes()), ("source_stamp", im.stamp), ("source_changed", changed)]))
    store = None
    if plan is not None and plan.layout == "store":
        unique, shared = ts.dedup_costs(rec.images)
        store = collections.OrderedDict([("shared_bytes", shared), ("unique_bytes", unique)])
    return collections.OrderedDict([
        ("recorded", True), ("written", rec.written), ("version", rec.version), ("free_bytes", free),
        ("layout", plan.layout if plan is not None else rec.layout), ("store", store),
        ("synced", rec.synced), ("dirty", rec.dirty), ("images", images)])


def _print_update_rows(u):
    flags = (" dirty" if u["dirty"] else "") + (" unrecorded" if u["unrecorded"] else "")
    print("update-card %s layout %s%s" % (u["card"], u["layout"], flags))
    for i, dev, how, base in u["sources"]:
        print("update-source %d %s %s %s" % (i, dev, how, base or "-"))
    for i, dev, n, nbytes, action, base in u["files"]:
        print("update-files %d %s %d %d %s %s" % (i, dev, n, nbytes, action, base or "-"))
    print("update-inject %s" % ("yes" if u["inject"] else "no"))
    print("update-size %d" % u["size"])
    print("update-peak %d" % u["peak"])
    print("update-free %d" % u["free_after"])
    print("update-grow %s" % ("p%d %d" % u["grow"] if u["grow"] else "none"))
    print("update-fits %s" % ("YES" if u["fits"] else "NO"))
    for note in u["notes"]:
        print("update-note %s" % note)


def update_card(a):
    """`update`: the card changes in place - only what changed since it was built (or last
    updated).  The order of business, each step refusing before anything is written:
    the card is a regular file nobody else holds; the lock; the record (or, for a card built
    before item 93, its trees hashed once off the card); the primary gate; every source's
    stamp against the record (an unchanged source is skipped entirely); the diff per tree and
    the room it needs (the peak, not the net); the dry-run rows.  Then: the p2 backup, the
    dirty flag, the loop mount(s), the changes, the bypass through the mount, the record
    written last, the sidecars, verify."""
    ts = _treesync()
    card = a.card
    if os.path.exists(card) and not os.path.isfile(card):
        raise Refused("%s is not a regular file (a device? flash the finished image instead)" % card)
    check_output_path(card, [a.conf, a.selector_dir, a.media_dir] + ([a.primary] if a.primary else []) + list(a.extra),
                      must_exist=True)
    dry = bool(a.dry_run)
    if a.bypass_validation and getattr(a, "restore_validation", False):
        raise Refused("--bypass-validation and --restore-validation ask for opposite things")
    if not dry:
        ok, why = loop_available()
        if not ok:
            raise Refused("update writes the card in place through a loop mount and cannot here: %s" % why)
        busy = card_in_use(card)
        if busy:
            raise Refused(busy)
    elif lock_held(card):
        raise Refused("card busy: an update of %s is running" % os.path.basename(card))
    need_tools("debugfs", "e2fsck")
    lock = CardLock(card) if not dry else None
    if lock:
        lock.__enter__()
    try:
        if not dry:
            sweep_stale_loops(card)          # a foreign mount of this card refuses here, by name
        return _update_locked(a, ts, card, dry)
    finally:
        if lock:
            lock.__exit__(None, None, None)


def restore_changes(old_im, tree, changes, live=None):
    """The writes that put the SOURCE's own game (and .sidx) back on a tree the card holds
    bypassed (item 98).  Two ways to know: the record's bypass digests (an update patched
    it through the mount) name the two files; or `live` - (state, title, game path) read off
    the card, for a tree a BUILD patched with a raw write and never recorded - says
    'bypassed', and then the game and every spk/index .sidx come from the source (identical
    bytes when the source is bypassed too: harmless).  Never a file the diff already
    writes, never one the source lacks."""
    ts = _treesync()
    by = (old_im.bypass or {}) if old_im is not None else {}
    have = {c.rel for c in changes if c.op == "write"}
    want = []
    if by.get("game") or by.get("sidx"):
        for path_key, digest_key in (("game_path", "game"), ("sidx_path", "sidx")):
            if by.get(digest_key):
                want.append(by.get(path_key))
    elif live and live[0] == "bypassed":
        want.append(live[2])
        want += [rel for rel in sorted(tree.files) if rel.startswith("spk/index/") and rel.endswith(".sidx")]
    out = []
    for rel in want:
        if rel and rel in tree.files and rel not in have and rel not in {c.rel for c in out}:
            out.append(ts.Change("write", rel, tree.files[rel].size))
    return out


def _update_locked(a, ts, card, dry):
    workdir = a.workdir or os.path.dirname(os.path.abspath(card))
    plan = plan_from_card(card)
    ref = select_ref(card)
    conf_now = card_conf(card, ref)
    if conf_now is None:
        raise Refused("%s carries no boot menu (no images.conf on p2) - not a multi-boot card" % card)
    warns = []
    old_build = parse_manifest(read_select_file(ref, BUILD_MANIFEST), BUILD_MANIFEST, warns) or {}
    old_media = None if a.media_dir else read_select_file(ref, MEDIA_MANIFEST)
    rec = read_trees(card, ref)
    dirty = list(rec.dirty) if rec else []
    unrecorded = rec is None
    # the requested list: --primary/--extra, else what build.json recorded
    if a.primary or a.extra:
        sources = [a.primary] + list(a.extra)
        if not a.primary:
            raise Refused("update needs --primary with --extra (or neither, to take both from the card's build.json)")
    else:
        sources = [im.get("source") for im in old_build.get("images") or []]
        if not sources or not all(sources):
            raise Refused("%s records no source paths; pass --primary/--extra" % os.path.basename(card))
    devs_now = plan.devices()
    store = plan.layout == "store"

    def subdir_for(i):
        if i == 0:
            return ""
        return "img%d" % i if plan.layout in ("multi", "store") else (plan.trees[i][1] or "")

    def tree_part(i):
        """The partition image i lives in - p7 for a multi card's new image, p3 for a store's."""
        if i < len(plan.trees):
            return plan.trees[i][0]
        return plan.multi_part if plan.multi_part is not None else plan.prims[2]

    if plan.layout == "parts" and len(sources) != len(plan.trees):
        raise Refused("a parts-layout card holds its extra image as a whole partition: only its CONTENTS can be "
                      "updated (%d images recorded, %d given) - to add, remove or reorder images build a fresh card"
                      % (len(plan.trees), len(sources)))
    u = {"card": card, "layout": plan.layout, "dirty": dirty, "unrecorded": unrecorded, "sources": [], "files": [],
         "grow": None, "inject": False, "size": 0, "peak": 0, "free_after": 0, "fits": True, "notes": []}
    missing = [p for p in sources if not os.path.isfile(p)]
    if missing:
        for i, p in enumerate(sources):
            if p in missing:
                u["sources"].append((i, devs_now[i] if i < len(devs_now) else "?", "missing", os.path.basename(p)))
        _print_update_rows(u)
        raise Refused("image%s %s: the file is not on this machine (%s)" % (
            "s" if len(missing) > 1 else "", ", ".join(str(i) for i, p in enumerate(sources) if p in missing),
            ", ".join(missing)))
    # the card's own trees when it predates the record (hashed once, cached under the card's stamp)
    if rec is None:
        say("%s carries no %s: reading its %d tree(s) once" % (os.path.basename(card), TREES_MANIFEST, len(plan.trees)))
        images = []
        for i, (part, sub) in enumerate(plan.trees):
            man, how = card_tree(card, part, sub, a.cache_dir, skip=tree_skip(plan, sub))
            # a tree the bypass already patched keeps its bypass through an update: without
            # this a source's stock game would be written over it and the machine would show
            # GAME VALIDATION ERROR again
            try:
                carried = {"carried": True} if tree_state(card, part, sub)[0] == "bypassed" else None
            except Exception:                            # noqa: BLE001 - an unreadable tree carries nothing
                carried = None
            images.append(ts.ImageTrees(i, device_name(part.num, sub), sub or "", man.tree, None, man.uuid, carried))
            say("image %d %s: %d files, %s (%s%s)"
                % (i, device_name(part.num, sub), len(man.tree.files), _gb(man.tree.bytes()), how,
                   "; validator bypassed - kept" if carried else ""))
        rec = ts.CardTrees(images, primary=None, layout=plan.layout, version=VERSION)
    if dirty:
        say("WARNING: %s is dirty (%s) - an earlier update was interrupted; its partitions get e2fsck -fy first"
            % (os.path.basename(card), ", ".join("p%d" % n for n in dirty)))
        for n in dirty:
            for p, _sub in plan.trees:
                if p.num == n:
                    r = subprocess.run(["e2fsck", "-fy", fs_ref(card, p.start * SECTOR)], stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT)
                    say("e2fsck -fy p%d: rc %d" % (n, r.returncode))
                    if r.returncode not in (0, 1, 2):
                        raise Refused("e2fsck -fy could not repair p%d (rc=%d):\n%s"
                                      % (n, r.returncode, r.stdout.decode("utf-8", "replace")[-800:]))
                    break
    # the primary gate
    identity = primary_gate(card, sources[0], rec.primary, a.cache_dir)
    # every source: unchanged (skipped), cached, or hashed now
    new_trees = {}                      # index -> (SourceManifest-like tree, stamp, uuid)
    stamps = []
    for i, path in enumerate(sources):
        st = ts.source_stamp(path)
        stamps.append((i, st))
    actions = ts.match_trees(rec, [(i, devs_now[i] if i < len(devs_now) else device_name(tree_part(i).num, "img%d" % i),
                                    st) for i, st in stamps], subdir_for)
    by_index = {a_.index: a_ for a_ in actions if a_.action != "remove"}
    for i, path in enumerate(sources):
        act = by_index[i]
        old_im = rec.image(act.old_index) if act.old_index is not None else None
        st = stamps[i][1]
        if old_im is not None and old_im.stamp and ts.stamps_equal(old_im.stamp, st):
            new_trees[i] = (old_im.tree, st, old_im.uuid, old_im)
            u["sources"].append((i, act.device, "unchanged", os.path.basename(path)))
            continue
        man, how = source_tree(path, a.cache_dir)
        new_trees[i] = (man.tree, st, man.uuid, old_im)
        u["sources"].append((i, act.device, how, os.path.basename(path)))
    for act in actions:
        if act.action == "remove":
            im = rec.image(act.old_index)
            base = os.path.basename((im.stamp or {}).get("path", "")) if im else None
            u["sources"].append((act.index, act.device, "removed", base))
    # the version gate on the new list
    if plan.layout == "parts":
        newplan = plan
    elif store:
        newplan = make_plan(sources[0], sources[1:], "store", store_sectors=plan.prims[2].count,
                            multi_subdirs=["img%d" % i for i in range(1, len(sources))])
    else:
        newplan = make_plan(sources[0], sources[1:], "multi", multi_sectors=plan.multi_part.count,
                            multi_subdirs=["img%d" % i for i in range(1, len(sources))])
    versions = plan_identities(newplan, progress=None)
    report_versions(versions, a.allow_version_mismatch)
    # the diff per tree and the room per partition
    free = games_free(card, plan)
    per_part_adds = {n: 0 for n in free}
    per_part_freed = {n: 0 for n in free}
    changes = {}
    touched = {}
    # on a store card a written file costs nothing when the store already holds its blob
    # (another tree's, or one written earlier in this very update)
    store_keys = {ts.blob_key(fr) for im in rec.images for fr in im.tree.files.values()} if store else set()
    # --bypass-validation: a tree whose validator is still armed - or half done (item 98:
    # the tick off, the grade restore live) - is patched through the mount even when
    # nothing else changed; its game and .sidx count as writes for the room and the rows
    bypass_pending = {}
    for i, path in enumerate(sources):
        act = by_index[i]
        tree, st, uuid, old_im = new_trees[i]
        old_tree = old_im.tree if (old_im is not None and act.action in ("keep", "rename")) else None
        ch = ts.diff_tree(old_tree, tree)
        if a.bypass_validation and i < len(plan.trees):
            try:
                live_b = tree_state(card, plan.trees[i][0], plan.trees[i][1])
            except Exception:                                # noqa: BLE001 - an unreadable tree is left alone
                live_b = None
            if live_b and live_b[0] in ("armed", "half"):
                written_now = {c.rel for c in ch if c.op == "write"}
                rels = [live_b[2]] + [r for r in sorted(tree.files)
                                      if r.startswith("spk/index/") and r.endswith(".sidx")]
                rels = [r for r in rels if r in tree.files and r not in written_now]
                if rels:
                    bypass_pending[i] = rels
        if getattr(a, "restore_validation", False):
            live = None
            if not ((old_im.bypass if old_im is not None else None) or {}).get("game") and i < len(plan.trees):
                try:
                    live = tree_state(card, plan.trees[i][0], plan.trees[i][1])
                    # a source that is bypassed ITSELF (an image this app wrote) has nothing
                    # stock to put back: the same bytes are on the card already
                    if live[0] == "bypassed" and tree_state(path, source_part(path), None)[0] == "bypassed":
                        live = None
                except Exception:                            # noqa: BLE001 - an unreadable tree restores nothing
                    live = None
            ch = ch + restore_changes(old_im, tree, ch, live)
        changes[i] = ch
        part = tree_part(i)
        need, peak = ts.room_needed(ch, old_tree, tree, margin=0)
        adds = sum(c.size for c in ch if c.op == "write")
        if store:
            adds = 0
            for c in ch:
                if c.op == "write":
                    k = ts.blob_key(tree.files[c.rel])
                    if k not in store_keys:
                        store_keys.add(k)
                        adds += c.size
            need = min(need, adds)
        per_part_adds[part.num] = per_part_adds.get(part.num, 0) + adds
        per_part_freed[part.num] = per_part_freed.get(part.num, 0) + (adds - need)
        pend = bypass_pending.get(i, ())
        adds += sum(tree.files[r].size for r in pend)
        per_part_adds[part.num] += sum(tree.files[r].size for r in pend)
        n = len([c for c in ch if c.op != "attr_dir"]) + len(pend)
        touched[i] = [c.rel for c in ch if c.op == "write"]
        action = act.action if act.action != "keep" else ("sync" if ch else ("bypass" if pend else "keep"))
        u["files"].append((i, act.device, n, adds, action, os.path.basename(path)))
    removed_bytes = 0
    for act in actions:
        if act.action == "remove":
            im = rec.image(act.old_index)
            if im is not None:
                removed_bytes += im.tree.bytes()
                u["files"].append((act.index, act.device, len(im.tree.files), 0, "remove", None))
    p7 = plan.multi_part.num if plan.multi_part else None
    u["size"] = sum(per_part_adds.values())
    peak = 0
    fits = True
    grow = None
    for n, (fr, total) in free.items():
        adds = per_part_adds.get(n, 0)
        if n == p7:
            adds -= removed_bytes                  # whole trees go first and free their bytes
        # the margin keeps a partition from being filled to its last block; it scales with a
        # small partition (a synthetic card) and is nothing when nothing is added
        want = (adds + min(ts.ROOM_MARGIN, total // 20)) if adds > 0 else 0
        peak = max(peak, want)
        if want > fr:
            if n == p7 and plan.layout == "multi":
                cls = next((k for k, v in STERN_SIZES.items() if v >= os.path.getsize(card)), None)
                room_in_class = 0
                if cls:
                    p7_end = plan.multi_part.start + plan.multi_part.count
                    room_in_class = (STERN_SIZES[cls] // SECTOR - TAIL - p7_end) * SECTOR
                extra = want - fr
                extra = (extra + (1 << 20) - 1) // (1 << 20) * (1 << 20)
                if extra <= room_in_class:
                    grow = (n, extra)
                else:
                    fits = False
                    u["notes"].append("p%d needs %s more than its %s free and the %s image size has %s left: build "
                                      "a fresh card on a larger size"
                                      % (n, _gb(want - fr), _gb(fr), cls, _gb(room_in_class)))
            else:
                fits = False
                u["notes"].append("p%d needs %s and has %s free: build a fresh card" % (n, _gb(want), _gb(fr)))
    u["peak"] = peak
    u["grow"] = grow
    u["fits"] = fits
    u["free_after"] = sum(fr for fr, _t in free.values()) - u["size"] + removed_bytes + (grow[1] if grow else 0)
    # the menu: re-injected when the image list moved or the menu flags say something new
    list_changed = any(a_.action != "keep" for a_ in actions)
    media = plan_media(a.media_dir, len(newplan.trees)) if a.media_dir else None
    newconf = conf_for_plan(newplan, a, existing=conf_now, media=media)
    u["inject"] = bool(list_changed or a.media_dir or newconf.strip() != render_images_conf_text(conf_now).strip())
    if a.expect_bytes is not None and u["size"] > a.expect_bytes * (1 + UPDATE_SLACK) + UPDATE_SLACK_BYTES:
        u["notes"].append("the update would write %s, more than the %s expected: a source changed since it was measured"
                          % (_gb(u["size"]), _gb(a.expect_bytes)))
        _print_update_rows(u)
        raise Refused(u["notes"][-1])
    _print_update_rows(u)
    if not fits:
        raise Refused("; ".join(u["notes"]))
    if dry:
        return 0
    if (u["size"] == 0 and not any(changes.values()) and not bypass_pending and not list_changed
            and not u["inject"] and not dirty and not unrecorded):
        say("nothing to write: every source is as recorded and the menu is unchanged")
        return 0
    if not a.selector_dir and u["inject"]:
        raise Refused("the menu must be re-injected (the image list or the menu changed): pass --selector-dir")
    # ---- execute
    t0 = time.monotonic()
    # EVERY PARTITION MOUNTED RW IS A SYNCED ONE from here on - a rw mount alone moves the
    # superblock, so a range md5 against the source can never hold for it again - and only a
    # partition with something to write is mounted at all
    touched_set = {tree_part(i).num for i in changes if changes[i] or i in bypass_pending}
    if list_changed and p7:
        touched_set.add(p7)
    if list_changed and store:
        touched_set.add(3)
    touched_set |= set(dirty)
    touched_parts = sorted(touched_set)
    bak = p2_backup(card)
    say("p2 backed up to %s" % bak)
    rec.dirty = touched_parts
    write_trees(card, rec, workdir=workdir)
    PROGRESS.start(u["size"] + 16 << 20, "writing what changed")
    if grow:
        plan = grow_last_partition(card, plan.multi_part.count + grow[1] // SECTOR)
    bypass_digests = {}
    states = {}
    # p3 (image 0) then p7 (every extra): one mount each
    mounts = collections.OrderedDict()
    for i in changes:
        if not changes[i] and i not in bypass_pending:
            continue
        mounts.setdefault(tree_part(i).num, []).append(i)
    if list_changed and p7 and p7 not in mounts:
        mounts[p7] = []
    if list_changed and store and 3 not in mounts:
        mounts[3] = []
    for n in dirty:                     # a dirty partition is mounted for its sweep, changes or not
        mounts.setdefault(n, [])
    for n, idxs in mounts.items():
        part = next(p for p, _s in plan.trees if p.num == n) if n != p7 else plan.multi_part
        with LoopMount(card, part.start * SECTOR, part.count * SECTOR) as mp:
            ops = DirOps(mp)
            if dirty:
                say("sweeping temporary files an interrupted run left in p%d: %d" % (n, ts.sweep_tmp(ops, "")))
                ts.sweep_parked(ops)
            if n == p7 or (store and n == 3):
                for what, old, new in ts.apply_tree_actions(ops, actions):
                    say("p%d: %s %s%s" % (n, what, old or "", (" -> " + new) if new else ""))
            for i in idxs:
                act = by_index[i]
                prefix = "" if i == 0 else (act.new_sub or "")
                tree, st, uuid, old_im = new_trees[i]
                src_reader_ctx = open(sources[i], "rb")
                try:
                    _v, _s, ext4, _a = _stern_plugins()
                    spart = source_part(sources[i])
                    r = ext4.Ext4Reader(src_reader_ctx, spart.start * SECTOR, spart.count * SECTOR)
                    if not tree.inodes:                              # a cached manifest: find the inodes
                        for rel, kind, ino, _node in r.iter_tree(2):
                            if kind == "file":
                                tree.inodes[rel] = ino
                    PROGRESS.step("writing image %d (%s)" % (i, os.path.basename(sources[i])),
                                  sum(c.size for c in changes[i] if c.op == "write"))
                    stats = ts.apply_changes(ops, prefix, changes[i], tree, ts.ReaderSource(r, tree), PROGRESS,
                                             store=store)
                finally:
                    src_reader_ctx.close()
                say("image %d: %d written (%s), %d removed%s"
                    % (i, stats["written"], _gb(stats["bytes"]), stats["removed"],
                       (", %d linked to blobs the store already held" % stats["linked"]) if store else ""))
                # the bypass, through the mount, for a tree whose game or .sidx moved (or that was never done)
                want_bypass = a.bypass_validation or (
                    bool(old_im is not None and old_im.bypass) and not getattr(a, "restore_validation", False))
                if want_bypass:
                    state, written, notes, gpath, spath = apply_bypass_fs(ops, prefix)
                    states[i] = state
                    for line in notes:
                        say("image %d bypass: %s" % (i, line))
                    by = dict(old_im.bypass or {}) if old_im is not None else {}
                    by["game_path"] = gpath
                    by["sidx_path"] = spath
                    for rel, sha in written.items():
                        by["game" if rel == gpath else "sidx"] = sha
                    replaced = old_im is not None and old_im.tree.files.get(gpath) != tree.files.get(gpath)
                    if gpath not in written and by.get("game") and tree.files.get(gpath) and replaced:
                        by.pop("game", None)              # replaced from the source: its digest is the source's
                    bypass_digests[i] = by
                    for rel in written:
                        touched.setdefault(i, []).append(rel)
                    if store:
                        adopt_written(ops, prefix, written)
            if store:
                n_gc, b_gc = ts.gc_blobs(ops)
                say("store: %d blob(s) no tree links any more removed (%s)" % (n_gc, _gb(b_gc)))
            ops.commit()
    # the record, last: the new trees, the stamps, synced, dirty cleared
    images = []
    for i, path in enumerate(sources):
        act = by_index[i]
        tree, st, uuid, old_im = new_trees[i]
        part = tree_part(i)
        sub = "" if i == 0 else (act.new_sub or "")
        carried = old_im is not None and act.action in ("keep", "rename") and not changes[i]
        by = bypass_digests.get(i, old_im.bypass if carried else None)
        images.append(ts.ImageTrees(i, device_name(part.num, sub or None), sub, tree, st, uuid, by))
    synced = sorted(set(rec.synced) | set(touched_parts))
    newrec = ts.CardTrees(images, primary=identity, synced=synced, dirty=[], layout=plan.layout, version=VERSION)
    PROGRESS.step("recording what is on the card")
    if u["inject"]:
        media = plan_media(a.media_dir, len(newplan.trees)) if a.media_dir else None
        manifests = selector_manifests(newplan, newconf, a.media_dir, sources, old_build, old_media,
                                       versions=versions, trees=newrec)
        inject_card(card, a.selector_dir, newconf, workdir=workdir, media_files=media["files"] if media else None,
                    replace_media=bool(a.media_dir), manifests=manifests)
    else:
        bj = json.dumps(build_manifest(newplan, conf_now, sources, old_build, versions=versions), indent=1) + "\n"
        write_trees(card, newrec, build_json=bj, workdir=workdir)
    for n in touched_parts:
        side = sidecar_path(card, n)
        if os.path.isfile(side):
            os.unlink(side)
    os.utime(card)
    PROGRESS.finish()
    say("updated %s: %s written into %s in %.0f s"
        % (os.path.basename(card), _gb(u["size"]), ", ".join("p%d" % n for n in touched_parts) or "nothing",
           time.monotonic() - t0))
    if a.no_verify:
        return 0
    ok = verify_card(card, verify_plan(card, sources), a.selector_dir, a.media_dir, mode="touched", touched=touched)
    return 0 if ok else 1


def verify_plan(card, sources):
    """The Plan `verify` holds `card` to: the card's own layout with the given SOURCES as the
    images (a card is no oracle for its own patched p2)."""
    own = plan_from_card(card)
    if own.layout == "multi":
        return make_plan(sources[0], sources[1:], "multi", multi_sectors=own.multi_part.count,
                         multi_subdirs=own.multi_subdirs)
    if own.layout == "store":
        return make_plan(sources[0], sources[1:], "store", store_sectors=own.prims[2].count,
                         multi_subdirs=own.store_subdirs)
    return make_plan(sources[0], sources[1:], "parts")


def render_images_conf_text(conf):
    """images.conf text from a parsed conf (what the card holds), for a like-for-like compare."""
    # a card that follows the machine's own volume reads back volume="machine" (item 90):
    # that is the machine_volume line's job in the render, not a number to range-check
    mv = conf.get("machine_volume")
    volume = conf["volume"]
    if volume == "machine":
        volume = None
        mv = mv or {"store": None, "key": MACHINE_VOLUME_KEY, "default": None}
    return render_images_conf(
        [d for (d, _t, _s) in conf["images"]], [t for (_d, t, _s) in conf["images"]],
        [s for (_d, _t, s) in conf["images"]], conf["default"], conf["timeout"], conf["font"],
        conf["media"], conf["sound_move"], conf["sound_confirm"], volume, conf["mixer_volume"],
        media_dir=conf.get("media_dir"), theme=conf.get("theme"), colors=conf.get("colors"),
        machine_volume=mv, debug_log=bool(conf.get("debug_log")))


# ============================================================================= reading a card back
def select_ref(card):
    """The debugfs reference for the card's p2 - where the selector, its images.conf and the two
    JSON sidecars live.  The same read path verify uses."""
    geom = Geometry.from_file(card)
    t, st, _cnt = geom.part(2)
    if t != 0x83:
        raise Refused("%s: p2 is type 0x%02x, not Linux (not a Spike 2 card)" % (card, t))
    return fs_ref(card, st * SECTOR)


def read_select_file(ref, name):
    """SELECT_DIR/<name> as bytes, or None when the card does not carry it."""
    path = SELECT_DIR + "/" + name
    if not debugfs_exists(ref, path):
        return None
    return debugfs_cat(ref, path)


def card_conf(card, ref=None):
    """The images.conf already on a card's p2, parsed, or None."""
    raw = read_select_file(ref or select_ref(card), "images.conf")
    return None if raw is None else parse_images_conf(raw)


def multi_subdirs_on(card, part_num=7):
    """The imgN subdirectories at the root of partition `part_num` (the multi layout's marker),
    numerically ordered, or [] when that partition is a plain games tree / not there / not ext4.
    Pure python (the ext4 reader), so a card is recognised on Windows too."""
    try:
        _vp, _sx, ext4, _adj = _stern_plugins()
        off, size = part_range(card, part_num)
        with open(card, "rb") as f:
            r = ext4.Ext4Reader(f, off, size)
            root = r.read_inode(2)
            names = {n: (c, t) for (n, c, t) in r._iter_dir(root) if n not in (".", "..")}
            if "spk" in names:
                return []
            subs = []
            for n, (c, _t) in names.items():
                m = MULTI_SUBDIR_RE.match(n)
                if m and (r.read_inode(c)["mode"] & ext4.S_IFMT) == ext4.S_IFDIR:
                    subs.append((int(m.group(1)), n))
            return [n for (_k, n) in sorted(subs)]
    except Exception:
        return []


def store_subdirs_on(card):
    """The imgN subdirectories at the root of p3 BESIDE its own spk/ - the store layout's
    marker (item 95: the primary's tree at the root, the extras as imgN/ next to it) -
    numerically ordered, or [] for a plain games partition / anything unreadable."""
    try:
        _vp, _sx, ext4, _adj = _stern_plugins()
        off, size = part_range(card, 3)
        with open(card, "rb") as f:
            r = ext4.Ext4Reader(f, off, size)
            root = r.read_inode(2)
            names = {n: (c, t) for (n, c, t) in r._iter_dir(root) if n not in (".", "..")}
            if "spk" not in names:
                return []
            subs = []
            for n, (c, _t) in names.items():
                m = MULTI_SUBDIR_RE.match(n)
                if m and (r.read_inode(c)["mode"] & ext4.S_IFMT) == ext4.S_IFDIR:
                    subs.append((int(m.group(1)), n))
            return [n for (_k, n) in sorted(subs)]
    except Exception:
        return []


def plan_from_card(card):
    """A Plan describing an existing multi card: p3 + every logical after p6 is an image
    partition; a p7 whose root holds img1/, img2/ ... (and no spk/) is the multi layout; a p3
    whose root holds img1/, img2/ ... BESIDE its spk/ is the store layout (item 95)."""
    G = Geometry.from_file(card)
    stock_logs = G.logical[:2]
    base = Geometry(G.size, G.mbr, G.prim, G.ext, stock_logs, G.ebr_raw, card)
    subs3 = store_subdirs_on(card)
    if subs3 and len(G.logical) == 2:
        _t3, _s3, c3 = G.part(3)
        return Plan(base, [], card, [], "store", multi_subdirs=subs3, store_sectors=c3)
    if len(G.logical) == 3:
        subs = multi_subdirs_on(card, 7)
        if subs:
            _e, _t, _st, cnt = G.logical[2]
            return Plan(base, [], card, [], "multi", multi_sectors=cnt, multi_subdirs=subs, multi_src=None)
    extra_geoms = []
    for ebr, t, st, cnt in G.logical[2:]:
        extra_geoms.append(Geometry(cnt * SECTOR, bytes(SECTOR), [(3, t, st, cnt)], None, [], path=card))
    return Plan(base, extra_geoms, card, [card] * len(extra_geoms))


# ============================================================================= the multi layout
def build_multi_partition(plan, workdir=None):
    """Build the multi layout's p7 image: every extra's games partition rdump'd into
    <tmp>/tree/imgK (symlinks survive - measured), mke2fs -d of that tree with the stock p3's
    feature set, ownership put back from the sources (rdump as a user cannot chown, and
    mke2fs -d records the running uid), e2fsck -fn.  -> (p7 image path, tmp dir to remove)."""
    need_tools("debugfs", "e2fsck", "mke2fs")
    mp = plan.multi_part
    tmp = tempfile.mkdtemp(prefix="mkmulticard.multi.", dir=workdir)
    tree = os.path.join(tmp, "tree")
    os.mkdir(tree)
    owners = {}
    t0 = time.monotonic()
    for sub, x, g in zip(plan.multi_subdirs, plan.extras, plan.extra_geoms):
        _t, st, _cnt = g.part(3)
        ref = fs_ref(x, st * SECTOR)
        dest = os.path.join(tree, sub)
        os.mkdir(dest)
        ents = [e for e in debugfs_ls(ref, "/") if e[4] not in (".", "..", "lost+found")]
        say("%s <- %s p3: %d root entries (%s)" % (sub, os.path.basename(x), len(ents),
                                                     ", ".join(e[4] for e in ents)))
        # THE WALK COMES BEFORE THE EXTRACTION, not after it.  It is the same walk the
        # ownership pass has always needed; taken first it also says how big each root entry
        # is, which is what gives the meter a budget per rdump - and one root entry of a games
        # tree is most of the card, so "how far into THIS entry" is the whole question.
        walk = [e for e in debugfs_walk(ref, "/")
                if not (e[0] == "lost+found" or e[0].startswith("lost+found/"))]
        for rel, ino, mode, uid, gid, size in walk:
            owners[sub + "/" + rel] = (uid, gid)
        weigh = {}
        for rel, ino, mode, uid, gid, size in walk:
            if not statmod.S_ISDIR(mode) and not statmod.S_ISLNK(mode):
                top = rel.split("/")[0]
                weigh[top] = weigh.get(top, 0) + (size or 0)
        for ino, mode, uid, gid, name, size in ents:
            if PROGRESS.on:
                PROGRESS.step("reading %s out of %s" % (name, default_title(x)),
                              weigh.get(name, 0))
            debugfs_rdump(ref, "/" + name, dest, PROGRESS if PROGRESS.on else None)
        # the three links the machine boots through must have survived as links
        for name in ("game", "conagent", "data"):
            src_st = debugfs_stat(ref, "/" + name) if any(e[4] == name for e in ents) else None
            if src_st and src_st.get("link") is not None:
                p = os.path.join(dest, name)
                if not os.path.islink(p):
                    if os.path.lexists(p):
                        shutil.rmtree(p) if os.path.isdir(p) else os.unlink(p)
                    os.symlink(src_st["link"], p)
                    say("  %s/%s recreated as a symlink -> %s" % (sub, name, src_st["link"]))
        title = [e[4] for e in ents if statmod.S_ISDIR(e[1]) and e[4] != "spk" and os.path.isfile(os.path.join(dest, e[4], "game"))]
        if not title:
            raise Refused("%s: no title directory with a game file came out of %s's p3" % (sub, x))
        say("  %s: title %s, %d entries copied in %.0f s" % (sub, "/".join(title), len(owners), time.monotonic() - t0))
    img = os.path.join(tmp, "p7.img")
    with open(img, "wb") as f:
        f.truncate(mp.count * SECTOR)
    say("mke2fs -d %s -> %s (%d MiB, label %s)" % (tree, img, mp.count * SECTOR >> 20, MULTI_LABEL))
    if PROGRESS.on:
        PROGRESS.step("writing the games into p%d" % mp.num, plan.multi_used or 0)
    _rc, _so, _se = run_metered(
        ["mke2fs", "-q", "-F", "-t", "ext4", "-m", "0", "-L", MULTI_LABEL, "-O", MULTI_FEATURES,
         "-E", "lazy_itable_init=0,lazy_journal_init=0", "-d", tree, img,
         str(mp.count * SECTOR // 1024) + "k"],
        PROGRESS if PROGRESS.on else None)
    r = argparse.Namespace(returncode=_rc, stdout=_so + _se)
    if r.returncode != 0:
        raise Refused("mke2fs failed (rc=%d):\n%s" % (r.returncode, r.stdout.decode("utf-8", "replace")))
    shutil.rmtree(tree, ignore_errors=True)
    rc, txt = e2fsck(img)
    if rc != 0:
        raise Refused("the multi p7 image is not clean after mke2fs (rc=%d):\n%s" % (rc, txt))
    # ownership: every inode of the new filesystem back to what its source said (by inode
    # number, so symlinks are set and not followed); the root directory is root's
    cmds = ["set_inode_field <2> uid 0", "set_inode_field <2> gid 0"]
    for rel, ino, mode, uid, gid, size in debugfs_walk(img, "/"):
        if rel == "lost+found":
            continue
        want = owners.get(rel, (0, 0))
        if (uid, gid) != want:
            cmds.append("set_inode_field <%d> uid %d" % (ino, want[0]))
            cmds.append("set_inode_field <%d> gid %d" % (ino, want[1]))
    if cmds:
        debugfs_write_script(img, cmds)
        rc, txt = e2fsck(img)
        if rc != 0:
            raise Refused("the multi p7 image is not clean after the ownership fix (rc=%d):\n%s" % (rc, txt))
    say("p7 image built: %d ownership fixes, e2fsck clean, %.0f s" % (len(cmds) // 2, time.monotonic() - t0))
    return img, tmp


# ============================================================================= the validator bypass
def _stern_plugins():
    """(valpatch, sidx, ext4, adjustments) - the app's own Stern modules, imported when first
    needed.  `adjustments` is here for its PT_LOAD parser alone: the game ELF's identity record
    is located exactly the way that module locates the adjustment table, so the two share one
    program-header reader rather than growing a second copy."""
    try:
        from pinball_decryptor.plugins.stern import valpatch, sidx, ext4, adjustments
    except ImportError:
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        try:
            from pinball_decryptor.plugins.stern import valpatch, sidx, ext4, adjustments
        except ImportError as e:
            raise Refused("the validator bypass needs the app's pinball_decryptor package "
                          "(looked beside %s): %s" % (REPO_ROOT, e))
    return valpatch, sidx, ext4, adjustments


def bypass_state(elf):
    """'bypassed' (the entry already holds bx lr), 'armed' (a live validator was located),
    'absent' (this build carries none) or 'unlocated' (it carries one we cannot pin)."""
    valpatch, _s, _e, _adj = _stern_plugins()
    elf = bytes(elf)
    eoff = valpatch.find_validation_exec(elf)
    if eoff is not None:
        if elf[eoff:eoff + 4] != valpatch._BX_LR:
            return "armed"
        # item 98: a bypassed tick whose GRADE RESTORE is still live keeps a fossil
        # grade for ever ('half' - re-apply the bypass to finish the job)
        roff = valpatch.find_grade_restore(elf)
        if roff is not None and elf[roff:roff + 4] != valpatch._MOV_R0_0:
            return "half"
        return "bypassed"
    return "unlocated" if valpatch.carries_validator(elf) else "absent"


def bypass_words(state):
    return {"bypassed": "validator: bypassed", "armed": "validator: ARMED", "absent": "validator: none on this build",
            "half": "validator: HALF bypassed (the tick is off but a stale grade still restores - re-apply)",
            "unlocated": "validator: UNLOCATED (this build carries one the locator cannot pin)"}.get(state, "validator: ?")


def _dir_entries(reader, ino):
    return {n: (c, t) for (n, c, t) in reader._iter_dir(reader.read_inode(ino)) if n not in (".", "..")}


def tree_root_inode(reader, subdir):
    """The inode of a games tree's root: 2, or the subdir's inode under it (multi layout)."""
    _v, _s, ext4, _adj = _stern_plugins()
    if not subdir:
        return 2
    ents = _dir_entries(reader, 2)
    if subdir not in ents:
        raise Refused("no %s directory at the root of this partition" % subdir)
    ino = ents[subdir][0]
    if (reader.read_inode(ino)["mode"] & ext4.S_IFMT) != ext4.S_IFDIR:
        raise Refused("%s is not a directory" % subdir)
    return ino


def tree_game(reader, root_ino):
    """(title, game path relative to the tree root, inode number, inode) of the tree's game ELF:
    the title directory's game_real when it is an ARM ELF, else its game.  Refused when the tree
    has no title directory holding a game."""
    _v, _s, ext4, _adj = _stern_plugins()
    for name, (c, t) in sorted(_dir_entries(reader, root_ino).items()):
        if name in ("lost+found", "spk"):
            continue
        try:
            node = reader.read_inode(c)
        except Exception:
            continue
        if (node["mode"] & ext4.S_IFMT) != ext4.S_IFDIR:
            continue
        inside = _dir_entries(reader, c)
        if "game" not in inside:
            continue
        for cand in ("game_real", "game"):
            if cand in inside:
                gi = inside[cand][0]
                gn = reader.read_inode(gi)
                if (gn["mode"] & ext4.S_IFMT) == ext4.S_IFREG and gn["size"] > 0:
                    return name, "%s/%s" % (name, cand), gi, gn
    raise Refused("no title directory with a game file in this tree")


def tree_sidx(reader, root_ino):
    """(path relative to the tree root, inode) of the tree's /spk/index/*.sidx, or (None, None)."""
    for path, ino, node in reader.iter_regular_files(root_ino=root_ino, max_depth=6, min_size=1):
        if path.endswith(".sidx") and path.lstrip("/").startswith("spk/index/"):
            return path.lstrip("/"), node                   # THIS tree's, never an imgN's beneath a store root
    return None, None


def compute_bypass_writes(reader, root_ino):
    """Neuter the tree's validator and refresh its .sidx record, as plugins/stern/valpatch's
    compute_writes does for a whole partition - but rooted at `root_ino` so a multi layout's
    imgN tree patches ITS game and ITS manifest.  -> (state before, [(disk offset, bytes)],
    notes).  No writes when the state is not 'armed'."""
    valpatch, sidx, _e, _adj = _stern_plugins()
    title, gpath, gino, gnode = tree_game(reader, root_ino)
    elf = bytearray(reader.read_file_bytes(gnode))
    state = bypass_state(elf)
    notes = ["%s (%d bytes)" % (gpath, len(elf))]
    if state not in ("armed", "half"):
        return state, [], notes
    overlay, _status = valpatch.bypass_overlay(bytes(elf))
    writes = []
    for poff, b in sorted(overlay.items()):
        elf[poff:poff + len(b)] = b
        for disk, n in reader.disk_ranges(gnode, poff, len(b)):
            writes.append((disk, b[:n]))
            b = b[n:]
    roff = valpatch.find_grade_restore(bytes(elf))
    notes.append("bx lr at ELF offset 0x%x%s" % (valpatch.find_validation_exec(bytes(elf)),
                                                 (", grade restore off at 0x%x" % roff) if roff is not None
                                                 else ", grade restore NOT located"))
    spath, snode = tree_sidx(reader, root_ino)
    if snode is None:
        notes.append("no .sidx manifest in this tree - the spk layer may flag the game file")
        return state, writes, notes
    sdata = reader.read_file_bytes(snode)
    recs, _crc, fmt = sidx.parse_records(sdata)
    # the manifest names the game file by its path in the tree; match by inode (extent block)
    # like valpatch does, so game vs game_real is settled by what is actually on disk
    want = bytes(gnode["i_block"])
    rec_path = None
    for path, ino, node in reader.iter_regular_files(root_ino=root_ino, max_depth=20, min_size=0x10000):
        if ino == gino or bytes(node["i_block"]) == want:
            if path.lstrip("/") in recs:
                rec_path = path.lstrip("/")
                break
    if rec_path is None and gpath in recs:
        rec_path = gpath
    if rec_path is None:
        notes.append("%s has no record for %s - the spk layer may flag the game file" % (spath, gpath))
        return state, writes, notes
    hm, md = sidx.digests(bytes(elf))
    for foff, rb in sidx.record_field_writes(recs[rec_path], hm, md, fmt):
        for disk, n in reader.disk_ranges(snode, foff, len(rb)):
            writes.append((disk, rb[:n]))
            rb = rb[n:]
    notes.append("%s record %r (%s) refreshed" % (spath, rec_path, fmt))
    return state, writes, notes


def card_trees(card, plan=None):
    """[(index, Part, subdir)] of every games tree on a card, from `plan` (default: read off the card)."""
    plan = plan or plan_from_card(card)
    return [(i, p, s) for i, (p, s) in enumerate(plan.trees)]


def tree_state(card, part, subdir):
    """(bypass state, title, game path) of one tree on `card` - read-only."""
    rec = read_tree(card, part, subdir)
    return rec["bypass"], rec["title"], rec["game_path"]


# ============================================================ game code versions (item 90)
def version_text(ver):
    """Stern's '1_59_0' (a .sidx / .hex name) -> '1.59.0'."""
    return ver.replace("_", ".") if ver else None


def game_identity(elf, title_dir=None):
    """The game ELF's per-build identity record -> {"version", "raw", "strings", "date",
    "name", "title_dir", "offset"} or None.  Reads bytes only; nothing is written.

    HOW IT IS LOCATED (no fixed address, the same shape as :mod:`plugins.stern.adjustments`):
    the record is a MAXIMAL run of consecutive 4-byte words that are pointers to short printable
    C strings, immediately followed by the uint16 version.  The run always holds either the
    build's RELEASE DATE or the title directory's name (usually both), which is what tells this
    record apart from the many other pointer tables in .data.  Everything is derived from the
    ELF's own program headers, so a build that moved the record is found anyway.
    """
    _v, _s, _e, adjustments = _stern_plugins()
    segs = adjustments._load_segments(elf)
    if not segs:
        return None
    want = (title_dir or "").encode()

    def v2o(v):
        for off, va, sz in segs:
            if va <= v < va + sz:
                return off + (v - va)
        return None

    def cstr(v):
        o = v2o(v)
        if o is None:
            return None
        end = elf.find(b"\x00", o, o + IDENT_MAX_STR)
        if end <= o:
            return None
        s = elf[o:end]
        return None if any(c < 0x20 or c > 0x7E for c in s) else s

    # the record lives in the last PT_LOAD (the writable data segment) on every card measured;
    # a build that put it elsewhere falls back to the whole file rather than going unread
    scopes = [(segs[-1][0], segs[-1][0] + segs[-1][2])] if len(segs) > 1 else []
    if not scopes or len(elf) <= IDENT_FULL_SCAN_MAX:
        scopes.append((0, len(elf)))
    best = None
    for lo, hi in scopes:
        run, run_at, o = [], lo, (lo + 3) & ~3
        while o + 4 <= hi:
            s = cstr(struct.unpack_from("<I", elf, o)[0])
            if s is not None:
                if not run:
                    run_at = o
                run.append(s)
                o += 4
                continue
            if len(run) >= IDENT_MIN_RUN and o + 2 <= len(elf):
                v = struct.unpack_from("<H", elf, o)[0]
                dates = [x for x in run if IDENT_DATE_RE.match(x)]
                named = bool(want) and want in run
                if 0 < v < IDENT_MAX_VER and (v & 0xFF) <= IDENT_MAX_MINOR and (dates or named):
                    score = (100 if named else 0) + (50 if dates else 0) + min(len(run), 8)
                    if best is None or score > best[0]:
                        best = (score, run_at, list(run), v, dates)
            run, run_at = [], o
            o += 4
        if best is not None:
            break
    if best is None:
        return None
    _score, at, run, v, dates = best
    texts = [x.decode("ascii") for x in run]
    # the model name is the string just BEFORE the release date ('TMNT PRO', 'GODZILLA LE');
    # with no date in the run (star_wars_le) it is the one before the title directory
    stop = run.index(dates[-1]) if dates else (len(run) - 1 if want and run[-1] == want else len(run))
    return collections.OrderedDict([
        ("version", "%d.%02d" % (v >> 8, v & 0xFF)), ("raw", v), ("offset", at),
        ("name", texts[stop - 1] if stop else texts[-1]),
        ("date", dates[-1].decode("ascii") if dates else None),
        ("title_dir", texts[-1] if want and run[-1] == want else None),
        ("strings", texts)])


def tree_dir_inode(reader, root_ino, *names):
    """The inode number of `root/names...` when every step is a directory, else None."""
    _v, _s, ext4, _adj = _stern_plugins()
    ino = root_ino
    for name in names:
        ents = _dir_entries(reader, ino)
        if name not in ents:
            return None
        ino = ents[name][0]
        if (reader.read_inode(ino)["mode"] & ext4.S_IFMT) != ext4.S_IFDIR:
            return None
    return ino


def tree_packages(reader, root_ino, title=None):
    """[(file name, package, '1.59.0')] for every REGULAR /spk/index/<pkg>-<M_mm_p>.sidx in the
    tree - Stern's own name for the build.  The bare '<pkg>.sidx' symlink beside it names no
    version and is skipped, and so is anything that is not a .sidx.  A tree carrying more than
    one puts the package named after the TITLE DIRECTORY first: that is the game's own."""
    _v, _s, ext4, _adj = _stern_plugins()
    ino = tree_dir_inode(reader, root_ino, "spk", "index")
    out = []
    for name, (child, _t) in (sorted(_dir_entries(reader, ino).items()) if ino else []):
        m = SIDX_NAME_RE.match(name)
        if not m:
            continue
        try:
            node = reader.read_inode(child)
        except Exception:
            continue
        if (node["mode"] & ext4.S_IFMT) == ext4.S_IFREG:
            out.append((name, m.group("pkg"), version_text(m.group("ver"))))
    return sorted(out, key=lambda r: r[1] != title)


def tree_node_firmware(reader, root_ino, title_dir):
    """(sorted .hex names, the one version they share or None) of the title directory's NODE
    BOARD firmware.  This is the set the machine flashes into the node boards, and it is
    recorded per boot: two images whose sets differ can reflash the boards on every swap."""
    _v, _s, ext4, _adj = _stern_plugins()
    ino = tree_dir_inode(reader, root_ino, title_dir) if title_dir else None
    names, vers = [], set()
    for name, (child, _t) in (sorted(_dir_entries(reader, ino).items()) if ino else []):
        m = NODE_FW_RE.match(name)
        if not m:
            continue
        try:
            node = reader.read_inode(child)
        except Exception:
            continue
        if (node["mode"] & ext4.S_IFMT) == ext4.S_IFREG:
            names.append(name)
            vers.add(version_text(m.group("ver")))
    return sorted(names), (vers.pop() if len(vers) == 1 else None)


def read_tree(card, part, subdir=None):
    """Everything one games tree says about ITSELF, read-only and with no mounts: the title
    directory, the game code version, where each answer came from, the node board firmware set
    and the validator state.  -> an OrderedDict; :func:`tree_state` is the two-line view of it.

    THE SOURCES, most reliable first (a disagreement between the first two is reported, never
    silently resolved - it is exactly the kind of thing that means a card was hand-assembled):
      sidx  /spk/index/<pkg>-<M_mm_p>.sidx, Stern's own package name for the build.  It carries
            all three components (1.59.0) and is what the code updater and the menu speak.
      elf   the game ELF's build-identity record (:func:`game_identity`): major.minor only.
      hex   the title directory's node firmware version - a different number (1.33.0 on TMNT
            1.59), never the game code version, so it is reported but never used as one.
    """
    _v, _s, ext4, _adj = _stern_plugins()
    with open(card, "rb") as f:
        r = ext4.Ext4Reader(f, part.start * SECTOR, part.count * SECTOR)
        root = tree_root_inode(r, subdir)
        title, gpath, _gino, gnode = tree_game(r, root)
        elf = r.read_file_bytes(gnode)                    # one read: the version AND the state
        pkgs = tree_packages(r, root, title)
        fw, fwver = tree_node_firmware(r, root, title)
    ident = game_identity(elf, title)
    notes = []
    sidx_name, package, sidx_ver = pkgs[0] if pkgs else (None, None, None)
    if len(pkgs) > 1:
        notes.append("this tree carries %d .sidx packages (%s); %s is used, as the one named "
                     "after the title directory"
                     % (len(pkgs), ", ".join(n for (n, _p, _v) in pkgs), sidx_name))
    elf_ver = ident["version"] if ident else None
    # compare the NUMBERS, not the text: the ELF holds major.minor as two bytes and the package
    # name spells them however Stern spelled them ('1_00_0' would never prefix-match '0.01')
    if ident and _version_pair(sidx_ver) not in (None, (ident["raw"] >> 8, ident["raw"] & 0xFF)):
        notes.append("the package name says %s but the game ELF's own build record says %s - "
                     "these two DISAGREE, and the package name is the one the machine installs by"
                     % (sidx_ver, elf_ver))
    if sidx_ver and elf_ver:
        source = "spk index + game ELF"
    elif sidx_ver:
        source = "spk index"
        notes.append("the game ELF carries no build-identity record this tool can locate; the "
                     "version is the .sidx package name alone")
    elif elf_ver:
        source = "game ELF"
        notes.append("this tree has no /spk/index/<pkg>-<M_mm_p>.sidx; the version is the game "
                     "ELF's build record alone, which carries no third component")
    else:
        source = None
        notes.append("neither a .sidx package name nor a game ELF build record could be read: "
                     "this tree's game code version is UNKNOWN")
    try:
        state = bypass_state(elf)
    except Exception as e:                                # a report never dies on one odd ELF
        state = "error"
        notes.append("the validator locator could not read %s (%s: %s)"
                     % (gpath, type(e).__name__, e))
    return collections.OrderedDict([
        ("device", device_name(part.num, subdir)), ("title", title), ("game_path", gpath),
        ("version", sidx_ver or elf_ver), ("version_source", source),
        ("package", package), ("sidx", sidx_name), ("sidx_version", sidx_ver),
        ("elf_version", elf_ver), ("elf_name", ident["name"] if ident else None),
        ("elf_date", ident["date"] if ident else None),
        ("node_fw", fw), ("node_fw_version", fwver), ("node_fw_digest", _fw_digest(fw)),
        ("bypass", state), ("notes", notes)])


def _version_pair(text):
    """'1.59.0' -> (1, 59), the two components the game ELF's record carries; None when the
    text is missing or not a version."""
    try:
        a, b = text.split(".")[:2]
        return int(a), int(b)
    except (AttributeError, ValueError):
        return None


def _fw_digest(names):
    """A short stable digest of a node firmware SET, so a JSON reader can compare two images
    without carrying twenty file names (the names are carried too; this is the cheap key)."""
    return hashlib.md5("\n".join(sorted(names)).encode("utf-8")).hexdigest()[:12] if names else None


def source_part(path, num=3):
    """The Part of one SOURCE image's games partition - what `plan` and `build` must read
    versions from, since the card does not exist yet."""
    t, st, cnt = Geometry.from_file(path).part(num)
    return Part(num, t, st, cnt, path, st, None)


def plan_identities(plan, progress=say):
    """One :func:`read_tree` record per image, read from the SOURCE images - so `plan` and
    `build` can refuse before a byte is written.  A tree that cannot be read becomes a record
    with version None and the reason in its notes; nothing here raises."""
    out = []
    for i, (dev, path) in enumerate(zip(plan.devices(), [plan.primary] + list(plan.extras))):
        rec = collections.OrderedDict([("index", i), ("device", dev), ("source", path)])
        try:
            rec.update(read_tree(path, source_part(path)))
        except Exception as e:                            # a version read never breaks a build
            rec.update(_unread_tree(dev, "%s could not be read (%s: %s)"
                                    % (path, type(e).__name__, e)))
        rec["device"] = dev                               # the card's device, not the source's
        out.append(rec)
        if progress:
            progress("image %d %s: %s %s (%s)" % (i, dev, rec["title"], rec["version"], rec["version_source"]))
    return out


def card_identities(card, plan=None, progress=None):
    """One :func:`read_tree` record per games tree ON the card (what verify and inspect report)."""
    out = []
    for i, part, sub in card_trees(card, plan):
        dev = device_name(part.num, sub)
        rec = collections.OrderedDict([("index", i), ("device", dev), ("source", card)])
        try:
            rec.update(read_tree(card, part, sub))
        except Exception as e:                            # a version read never breaks a verify
            rec.update(_unread_tree(dev, "this tree could not be read (%s: %s)"
                                    % (type(e).__name__, e)))
        rec["device"] = dev
        out.append(rec)
        if progress:
            progress("image %d %s: %s %s (%s)" % (i, dev, rec["title"], rec["version"], rec["version_source"]))
    return out


def _unread_tree(dev, why):
    """The record of a tree that could not be read: everything unknown, the reason kept."""
    return collections.OrderedDict([
        ("device", dev), ("title", None), ("game_path", None), ("version", None),
        ("version_source", None), ("package", None), ("sidx", None), ("sidx_version", None),
        ("elf_version", None), ("elf_name", None), ("elf_date", None),
        ("node_fw", []), ("node_fw_version", None), ("node_fw_digest", None),
        ("bypass", "error"), ("notes", [why])])


def _distinct(recs, key):
    """The distinct non-None values of `key`, in image order."""
    seen = []
    for r in recs:
        v = r.get(key)
        if v is not None and v not in seen:
            seen.append(v)
    return seen


def version_findings(recs):
    """What the version table found -> OrderedDict of PLAIN-ENGLISH sentences (or None).

    title_mismatch     the images are not even the same game - the larger warning
    version_mismatch   the umbrella 'these images are not the same game code' sentence: it
                       names the title difference when there is one, so a reader that shows
                       only this key never misses the louder problem
    node_fw_mismatch   the images ship different NODE BOARD firmware sets - the one failure
                       here that needs service, and it can happen with matching versions
    unknown_version    a tree whose version could not be read at all
    version_only       the version sentence WITHOUT the title one folded in, so the refusal can
                       put the two on their own lines; readers want version_mismatch
    """
    # only trees that were actually READ can disagree; one that could not be read is its own
    # finding (unknown_version) and never fabricates a mismatch
    known = [r for r in recs if r.get("title") is not None]
    titles, versions = _distinct(known, "title"), _distinct(known, "version")
    known = [dict(r, node_fw_label=_fw_label(r)) for r in known]
    fws = _distinct(known, "node_fw_label")
    unread = [r for r in recs if r.get("version") is None]
    title_bad = version_bad = fw_bad = unknown = None
    if len(titles) > 1:
        title_bad = ("this card mixes DIFFERENT TITLES (%s): %s. Nothing carries between them - "
                     "settings, audits and high scores are stored per title - and each title "
                     "wants its own node boards, coils and switch table."
                     % (", ".join(titles), _image_list(known, "title")))
    if len(versions) > 1:
        version_bad = ("the images do not all run the same GAME CODE VERSION (%s): %s."
                       % (", ".join(versions), _image_list(known, "version")))
    version_only = version_bad
    if title_bad:
        version_bad = title_bad if not version_bad else title_bad + " " + version_bad
    if len(fws) > 1:
        fw_bad = ("the images ship DIFFERENT NODE BOARD FIRMWARE: %s. %s The machine records the "
                  "running build's node firmware version at every boot, so swapping between "
                  "these images can reflash the node boards on every swap."
                  % (_image_list(known, "node_fw_label"), _fw_diff(known)))
    if unread:
        unknown = ("%d image(s) did not say what game code they run: %s."
                   % (len(unread), "; ".join("image %d (%s)" % (r["index"], "; ".join(r["notes"]))
                                             for r in unread)))
    return collections.OrderedDict([("title_mismatch", title_bad), ("version_mismatch", version_bad),
                                    ("node_fw_mismatch", fw_bad), ("unknown_version", unknown),
                                    ("version_only", version_only)])


def _fw_label(rec):
    """What to CALL one image's node firmware set: its shared version, 'no node firmware' when
    the title directory carries none, or the set's digest when the files disagree among
    themselves - never 'unknown', which would read as 'we did not look'."""
    if rec.get("node_fw_version"):
        return rec["node_fw_version"]
    return ("mixed set " + rec["node_fw_digest"]) if rec.get("node_fw") else "no node firmware"


def _image_list(recs, key, fallback=None):
    """'image 0 = 1.59.0, image 1 = 1.58.0' for a findings sentence."""
    return ", ".join("image %d = %s" % (r["index"], r.get(key) or (r.get(fallback) if fallback else None) or "unknown")
                     for r in recs)


def _fw_diff(recs, limit=6):
    """'images 0, 1 carry a.hex, b.hex; image 2 carries c.hex' - WHICH node firmware files
    differ, so the reader is told what is about to be reflashed rather than that something is.
    Images that ship the SAME set are named together: on a three-image card two of them usually
    agree, and calling either one's files 'only its own' would be a lie."""
    common = set.intersection(*[set(r["node_fw"]) for r in recs]) if recs else set()
    groups = collections.OrderedDict()
    for r in recs:
        groups.setdefault(tuple(sorted(r["node_fw"])), []).append(r["index"])
    parts = []
    for names, idx in groups.items():
        only = sorted(set(names) - common)
        if not only:
            continue
        parts.append("image%s %s carr%s %s%s"
                     % ("s" if len(idx) > 1 else "", ", ".join(str(i) for i in idx),
                        "y" if len(idx) > 1 else "ies", ", ".join(only[:limit]),
                        " and %d more" % (len(only) - limit) if len(only) > limit else ""))
    return ("; ".join(parts) + ".") if parts else "(the file names match; only their versions differ.)"


def print_version_table(recs, findings=None):
    """The VERSION table plan / build / verify / inspect all print - one line per image."""
    print("== game code versions")
    print("%-3s %-22s %-24s %-9s %-22s %s" % ("idx", "device", "title", "version", "read from", "node firmware"))
    for r in recs:
        fw = "%s (%d hex)" % (r["node_fw_version"] or "mixed", len(r["node_fw"])) if r["node_fw"] else "none"
        print("%-3d %-22s %-24s %-9s %-22s %s"
              % (r["index"], r["device"], r["title"] or "?", r["version"] or "UNKNOWN",
                 r["version_source"] or "-", fw))
        for note in r["notes"]:
            print("    NOTE image %d: %s" % (r["index"], note))
    found = version_findings(recs) if findings is None else findings
    for key in ("version_mismatch", "node_fw_mismatch", "unknown_version"):
        if found.get(key):                    # title_mismatch is folded into version_mismatch
            print("WARNING: %s" % found[key])


#: What a version difference actually costs, in the operator's own terms.  Measured on a TMNT
#: 1.59 -> 1.58 -> 1.59 round trip (memory: reference_spike2_settings_are_caption_keyed): the
#: board NVRAM keys every setting by the SHA1 of its MENU CAPTION, so 11 of 11 settings survived
#: the trip even though 202 of the 228 shared captions were renumbered between the builds.
VERSION_COST = """\
Two builds of the SAME title do share a machine's settings, audits and scores: those live in the
node board's NVRAM keyed by the SHA1 of each setting's MENU CAPTION, not by its number, so a
caption both builds spell the same way carries over untouched (11 of 11 measured across a TMNT
1.59 -> 1.58 -> 1.59 round trip, with 202 of the 228 shared captions renumbered in between).

What a version difference DOES cost is narrower, and all of it is real:
  * a setting only ONE build has falls back to that build's compiled default whenever you boot
    the other one (43 settings of TMNT 1.59 and 13 of 1.58 on that measured pair);
  * a setting Stern RENAMED between the builds REVERTS - the new caption hashes to a slot that
    has never been written (3 on that pair);
  * the store keeps only THREE generations, so two boots of the other build erase a
    build-exclusive value for good.

And the part that needs a service call rather than a settings pass: each image ships its OWN
NODE BOARD FIRMWARE, and the machine records the running build's node firmware version at every
boot - so a card whose images disagree can REFLASH the node boards on every single swap.

THE FIX is to give every image on the card the same game code version.  Same title AND same
version costs nothing at all - a re-skin of a build, paired with that same build, differs only
in its artwork and shares every setting the machine holds."""


def report_versions(recs, allow=False):
    """Print the VERSION table and apply the gate -> the findings; raises Refused when the images
    are not the same game code and `allow` is not set.  The table always comes out FIRST, and its
    per-finding WARNING lines are left out when the refusal is about to say the same thing at
    length - the reader should meet each sentence once."""
    try:
        found = check_versions(recs, allow)
    except Refused:
        print_version_table(recs, {"unknown_version": version_findings(recs)["unknown_version"]})
        raise
    print_version_table(recs, found)
    return found


def check_versions(recs, allow=False, flag="--allow-version-mismatch"):
    """Refuse a card whose images are not the same game code, unless `allow`.  A refusal you can
    override IS the loud warning, so the message says what it costs and how to fix it.  ->
    the findings (so the caller can report them); raises Refused when it will not proceed."""
    findings = version_findings(recs)
    # one paragraph each, loudest first: a different TITLE, then a different VERSION, then a
    # different NODE FIRMWARE set (which can be the only difference)
    bad = [findings[k] for k in ("title_mismatch", "version_only", "node_fw_mismatch") if findings[k]]
    if not bad or allow:
        return findings
    rows = "\n".join(
        "  image %-2d %-22s %-22s game code %-9s node firmware %s"
        % (r["index"], r["device"], r["title"] or "?", r["version"] or "UNKNOWN",
           _fw_label(r))
        for r in recs)
    raise Refused("%s\n\n%s\n\n%s\n\nIf you know all of that and want this card anyway, pass %s."
                  % ("\n\n".join(bad), rows, VERSION_COST, flag))


def bypass_card(card, plan=None, dry_run=False):
    """Apply the validator bypass to every games tree on `card`, rewrite the sidecar of every
    partition written into, print one line per tree.  -> {index: state after}."""
    _v, _s, ext4, _adj = _stern_plugins()
    plan = plan or plan_from_card(card)
    states = {}
    touched = []
    for i, part, sub in card_trees(card, plan):
        dev = device_name(part.num, sub)
        try:
            with open(card, "rb") as f:
                r = ext4.Ext4Reader(f, part.start * SECTOR, part.count * SECTOR)
                root = tree_root_inode(r, sub)
                before, writes, notes = compute_bypass_writes(r, root)
        except Refused as e:
            print("image %d %s: validator: SKIPPED (%s)" % (i, dev, e))
            states[i] = "error"
            continue
        if before in ("armed", "half") and writes and not dry_run:
            with open(card, "r+b") as f:
                for disk, b in writes:
                    f.seek(disk)
                    f.write(b)
                f.flush()
            touched.append(part.num)
            after = "bypassed"
        else:
            after = before
        line = bypass_words(after)
        if before in ("armed", "half") and after == "bypassed":
            line += " (was %s; %d bytes written)" % (before, sum(len(b) for (_d, b) in writes))
        elif before in ("armed", "half") and dry_run:
            line += " (dry run: %d bytes would be written)" % sum(len(b) for (_d, b) in writes)
        elif before == "bypassed":
            line += " (already)"
        print("image %d %s: %s - %s" % (i, dev, line, "; ".join(notes)))
        states[i] = after
    for n in sorted(set(touched)):
        say("p%d md5 %s recorded in %s" % (n, write_part_sidecar(card, n), sidecar_path(card, n)))
    return states


# ============================================================================= verify
def sfdisk_table(image):
    """[(num, start, count, type)] from `sfdisk -d`.  The device column is the image path plus
    the partition number, and the path may hold a SPACE ('.../TMNT 1987/multi.img7 : start=...'),
    so it is matched with .*? rather than \\S+ - the latter parsed such a card to []."""
    r = subprocess.run(["sfdisk", "-d", image], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = r.stdout.decode("utf-8", "replace")
    rows = []
    for line in out.splitlines():
        m = re.match(r"^(.*?)(\d+)\s*:\s*start=\s*(\d+),\s*size=\s*(\d+),\s*type=\s*([0-9a-fA-F]+)", line)
        if m:
            rows.append((int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5), 16)))
    return rows, out


def verify_card(card, plan, selector_dir=None, media_dir=None, mode="full", touched=None):
    """`mode` (item 93) says how much of a RECORDED games tree's content is re-hashed against
    trees.json: 'full' every file (the default of the verify command), 'touched' the files
    `touched` names {image index: [rel]} plus each tree's game and .sidx (what `update` runs
    after itself), 'quick' a sample of 32 files plus the game and .sidx."""
    ok = True
    hash_mode = mode                      # `mode` is reused below as a listing's mode bits

    def check(label, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print("%-58s %s%s" % (label, "OK" if good else "FAIL", ("  " + detail) if detail else ""))

    need_tools("debugfs", "e2fsck", "sfdisk", "fdisk")
    try:
        trees_rec = read_trees(card)
    except Refused as e:
        trees_rec = None
        check("trees.json readable", False, str(e))
    synced = set(trees_rec.synced) if trees_rec else set()
    O = Geometry.from_file(card)
    got = [(n, t, st, cnt) for (n, t, st, cnt) in O.prim] + [(5 + i, t, st, cnt) for i, (_e, t, st, cnt) in enumerate(O.logical)]
    check("table parse-back (own parser)", plan.table() == got, "" if plan.table() == got else "got %r" % (got,))
    rows, sf = sfdisk_table(card)
    want_sf = [(n, st, cnt, t) for (n, t, st, cnt) in plan.table()]
    check("table parse-back (sfdisk -d)", rows == want_sf, "" if rows == want_sf else "got %r" % (rows,))
    print(sf.rstrip())
    r = subprocess.run(["fdisk", "-l", card], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(r.stdout.decode("utf-8", "replace").rstrip())
    check("image size %d" % plan.total_bytes, os.path.getsize(card) == plan.total_bytes, "actual %d" % os.path.getsize(card))
    # the MBR: bootstrap + disk id verbatim, entries regenerated
    with open(card, "rb") as f:
        mbr = f.read(SECTOR)
    check("MBR bootstrap + disk id verbatim", mbr[:0x1BE] == plan.primary_geom.mbr[:0x1BE])
    check("MBR entries", mbr[0x1BE:] == mbr_sector(plan)[0x1BE:])
    a = md5_range(plan.primary, SECTOR, (PRE_P1 - 1) * SECTOR)
    b = md5_range(card, SECTOR, (PRE_P1 - 1) * SECTOR)
    check("sectors 1..%d (u-boot) md5" % (PRE_P1 - 1), a == b, a)
    for i, p in enumerate(plan.logs):
        with open(card, "rb") as f:
            f.seek(p.ebr * SECTOR)
            eb = f.read(SECTOR)
        check("EBR for p%d @%d" % (p.num, p.ebr), eb == ebr_sector(plan, i))
    # every copied range: against its source, or against the sidecar recorded when this tool
    # wrote into it after the copy (the validator bypass, the multi layout's built p7)
    for p in plan.prims + plan.logs:
        t0 = time.monotonic()
        if p.num == 2:
            continue
        if p.num in synced:
            # written into in place (item 93): a rw mount stamps the superblock, so a range
            # md5 can never hold; the record holds it instead, below
            print("p%d: synced in place - held to %s, not to a range md5%s" % (
                p.num, TREES_MANIFEST, "" if read_part_sidecar(card, p.num) is None else
                " (a pre-sync sidecar is beside the card and ignored)"))
            continue
        try:
            want = read_part_sidecar(card, p.num)
        except Refused as e:
            check("p%d sidecar" % p.num, False, str(e))
            continue
        b = md5_range(card, p.start * SECTOR, p.count * SECTOR)
        if want is not None:
            check("p%d md5 vs sidecar %s (written into; %.0f s)" % (p.num, os.path.basename(sidecar_path(card, p.num)), time.monotonic() - t0),
                  want == b, b if want == b else "card %s sidecar %s" % (b, want))
        elif p.src:
            a = md5_range(p.src, p.src_start * SECTOR, p.count * SECTOR)
            check("p%d md5 vs %s (%.0f s)" % (p.num, os.path.basename(p.src), time.monotonic() - t0), a == b, a)
        else:
            check("p%d md5" % p.num, False, "no source image and no %s sidecar to hold it to" % os.path.basename(sidecar_path(card, p.num)))
    # p2 is patched, so its source is no oracle: the sidecar written at the last write-back is
    t0 = time.monotonic()
    try:
        want, got = check_p2_sidecar(card)
        if want is None:
            print("p2: no sidecar (built before this check)")
        else:
            check("p2 sidecar md5 (%s, %.0f s)" % (os.path.basename(p2_sidecar_path(card)), time.monotonic() - t0),
                  want == got, got if want == got else "card %s sidecar %s" % (got, want))
    except Refused as e:
        check("p2 sidecar md5", False, str(e))
    # p2: patched
    p2 = plan.prims[1]
    ref = fs_ref(card, p2.start * SECTOR)
    pref = fs_ref(plan.primary, p2.src_start * SECTOR)
    print("p2 (rootfs): patched - selector files and the hooked %s:" % GAME_SCRIPT)
    try:
        cur = debugfs_cat(ref, GAME_SCRIPT).decode("utf-8", "replace")
        orig = debugfs_cat(pref, GAME_SCRIPT).decode("utf-8", "replace")
        diff = list(difflib.unified_diff(orig.splitlines(), cur.splitlines(), "primary:" + GAME_SCRIPT, "card:" + GAME_SCRIPT, lineterm="", n=1))
        print("\n".join("    " + l for l in diff) if diff else "    (identical - NOT hooked)")
        check("%s = primary's + the hook block only" % GAME_SCRIPT, has_hook(cur) and strip_hook(cur) == orig)
        st = debugfs_stat(ref, GAME_SCRIPT)
        ost = debugfs_stat(pref, GAME_SCRIPT)
        check("%s mode/uid/gid/mtime kept" % GAME_SCRIPT,
              all(st.get(k) == ost.get(k) for k in ("mode", "uid", "gid", "mtime")),
              "card %r primary %r" % ({k: st.get(k) for k in ("mode", "uid", "gid", "mtime")},
                                      {k: ost.get(k) for k in ("mode", "uid", "gid", "mtime")}))
    except Refused as e:
        check("p2 game script", False, str(e))
    try:
        ents = [e for e in debugfs_ls(ref, SELECT_DIR) if e[4] not in (".", "..")]
        for ino, mode, uid, gid, name, size in ents:
            print("    %s/%-14s mode %o uid %d gid %d %d bytes" % (SELECT_DIR, name, mode & 0o7777, uid, gid, size))
        names = {e[4] for e in ents}
        check("%s holds codeselect, select.sh, images.conf" % SELECT_DIR, {"codeselect", "select.sh", "images.conf"} <= names)
        print("    JSON sidecars: %s" % ", ".join(
            "%s %s" % (n, ("%d bytes" % dict((e[4], e[5]) for e in ents)[n]) if n in names else "absent")
            for n in SIDECAR_MANIFESTS))
        conf = parse_images_conf(debugfs_cat(ref, SELECT_DIR + "/images.conf"))
        devs = [d for (d, _t, _s) in conf["images"]]
        check("images.conf devices = %r" % (plan.devices(),), devs == plan.devices(), "got %r" % (devs,))
        for (d, t, s), m in zip(conf["images"], conf["media"]):
            print("    image %s | %s | %s%s"
                  % (d, t, s, "".join(" | %s" % x for x in m) if any(m) else ""))
        print("    default=%d timeout=%d font=%s log=%s" % (conf["default"], conf["timeout"], conf["font"],
                                                            conf.get("debug_log") or "off"))
        print("    sound_move=%s sound_confirm=%s volume=%s mixer_volume=%s media=%s"
              % (conf["sound_move"], conf["sound_confirm"], conf["volume"], conf["mixer_volume"], conf["media_dir"]))
        if selector_dir:
            for name, (cardname, mode, required) in SELECTOR_FILES.items():
                src = os.path.join(selector_dir, name)
                if os.path.isfile(src) and cardname in names:
                    back = hashlib.md5(debugfs_cat(ref, SELECT_DIR + "/" + cardname)).hexdigest()
                    check("%s/%s == selector dir's" % (SELECT_DIR, cardname), back == md5_file(src))
        # the media directory (item 90 v2): listed, every conf-named file present, md5 vs --media-dir
        wanted = conf_media_names(conf)
        on_card = {}
        if any(e[4] == "media" and statmod.S_ISDIR(e[1]) for e in ents):
            for ino, mode, uid, gid, name, size in debugfs_ls(ref, MEDIA_DIR):
                if name in (".", ".."):
                    continue
                on_card[name] = size
                print("    %s/%-24s mode %o uid %d gid %d %d bytes" % (MEDIA_DIR, name, mode & 0o7777, uid, gid, size))
            print("    media: %d files, %s (budget %s)" % (len(on_card), _gb(sum(on_card.values())), _gb(MEDIA_BUDGET)))
            check("%s total <= budget" % MEDIA_DIR, sum(on_card.values()) <= MEDIA_BUDGET)
            # the JSON sidecars live beside images.conf; the selector scans this directory
            check("no JSON sidecar inside %s" % MEDIA_DIR, not (set(SIDECAR_MANIFESTS) & set(on_card)),
                  "found %r" % sorted(set(SIDECAR_MANIFESTS) & set(on_card)))
        else:
            print("    (no %s)" % MEDIA_DIR)
        missing = [n for n in wanted if n not in on_card]
        check("images.conf media files present on the card (%d named)" % len(wanted), not missing, "missing %r" % (missing,) if missing else "")
        if media_dir:
            for name in sorted(on_card):
                src = os.path.join(media_dir, name)
                if os.path.isfile(src):
                    back = hashlib.md5(debugfs_cat(ref, MEDIA_DIR + "/" + name)).hexdigest()
                    check("%s/%s == %s's" % (MEDIA_DIR, name, os.path.basename(media_dir)), back == md5_file(src))
                else:
                    check("%s/%s in %s" % (MEDIA_DIR, name, media_dir), False, "not in the media dir")
    except Refused as e:
        check("p2 selector files", False, str(e))
    # every ext4 partition
    for p in plan.prims + plan.logs:
        if p.ptype != 0x83:
            continue
        t0 = time.monotonic()
        rc, txt = e2fsck(fs_ref(card, p.start * SECTOR))
        check("e2fsck -fn p%d (%.0f s)" % (p.num, time.monotonic() - t0), rc == 0, "" if rc == 0 else txt.strip().splitlines()[-1])
    # every games tree: its root (title dir + the game link) and the validator's state
    for i, (p, sub) in enumerate(plan.trees):
        dev = device_name(p.num, sub)
        root = ("/" + sub) if sub else "/"
        try:
            ref = fs_ref(card, p.start * SECTOR)
            ents = debugfs_ls(ref, root)
            dirs = [e[4] for e in ents if statmod.S_ISDIR(e[1]) and e[4] not in (".", "..", "lost+found", "spk")]
            has_spk = any(e[4] == "spk" and statmod.S_ISDIR(e[1]) for e in ents)
            links = {}
            for name in ("game", "conagent", "data"):
                if any(e[4] == name and statmod.S_ISLNK(e[1]) for e in ents):
                    links[name] = debugfs_stat(ref, root.rstrip("/") + "/" + name).get("link")
            check("image %d %s root: spk %s, title dir %r, links %r" % (i, dev, "yes" if has_spk else "NO", dirs, links),
                  dirs and has_spk and links.get("game"))
        except Refused as e:
            check("image %d %s root" % (i, dev), False, str(e))
    # every recorded games tree against trees.json (item 93)
    if trees_rec is not None:
        check("%s: not mid-update (dirty %r)" % (TREES_MANIFEST, trees_rec.dirty), not trees_rec.dirty,
              "an update was interrupted; run update again" if trees_rec.dirty else "")
        verify_trees(card, plan, trees_rec, hash_mode, check, touched)
        if plan.layout == "store":
            verify_store(card, plan, trees_rec, check, hash_mode)
    elif plan.layout == "store":
        check("%s: a store card carries its record" % TREES_MANIFEST, False, "none on the card")
    else:
        print("%s: none (built before item 93; `update` records it)" % TREES_MANIFEST)
    # every games tree's game code version + node board firmware, read off the CARD (item 90):
    # the same table plan and build print, so a finished card can be held to what it claims
    recs = card_identities(card, plan)
    for r in recs:
        print("image %d %s bypass_status: %s (%s)"
              % (r["index"], r["device"], r["bypass"], r["game_path"] or "; ".join(r["notes"])))
    print_version_table(recs)
    # a mismatch is REPORTED here, never a FAIL: a card built with --allow-version-mismatch is a
    # card its owner chose, and verify's job is to say what is on it - build's is to refuse
    alloc = allocated_bytes(card)
    if alloc is not None:
        print("allocated %s of %s apparent (sparse)" % (_gb(alloc), _gb(os.path.getsize(card))))
    print("VERIFY %s %s" % (card, "PASS" if ok else "FAIL"))
    return ok


# ============================================================================= inspect
def extract_card_media(ref, out_dir, names, media_json=None):
    """Write the card's media directory (and its media.json when it carries one) into `out_dir`,
    flat - the exact shape selectmedia.py writes and --media-dir reads back, so a loaded card can
    be previewed and re-injected without a rebuild.  -> (names written, names skipped).

    Nothing in `out_dir` is ever deleted (it may be a media set of your own), so give it a
    per-card scratch directory: a file left there by an earlier load is still there afterwards,
    and --media-dir would stage what media.json names, not what the card carries."""
    check_library_path(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    written, skipped = [], []
    for name in names:
        if not MEDIA_NAME_RE.match(name):
            skipped.append(name)                 # never came from this tool; never write it out
            continue
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(debugfs_cat(ref, MEDIA_DIR + "/" + name))
        written.append(name)
    if media_json is not None:
        with open(os.path.join(out_dir, MEDIA_MANIFEST), "wb") as f:
            f.write(media_json)
        written.append(MEDIA_MANIFEST)
    return written, skipped


def inspect_card(card, media_out=None):
    """Read a finished multi card back: everything a loader needs to fill an editor's fields,
    with no mounts and no writes.  -> the report dict (contract B of "load a card back").

    The menu comes from images.conf, the provenance from build.json, the art/animation SPECS
    from media.json, the file list from the media directory and each image's validator state
    from its games tree.  A card written by an older version carries no JSON sidecars: those
    fields degrade to null with a warning - never an error.  Refused only when the file is not
    a Spike 2 card or carries no selector.  `media_out` also extracts the media directory.
    """
    need_tools("debugfs")
    warnings = []
    path = os.path.abspath(card)
    size = os.path.getsize(path)
    geom = Geometry.from_file(path)
    ref = select_ref(path)
    if not debugfs_exists(ref, SELECT_DIR):
        raise Refused("%s: no %s on its p2 - no boot selector is installed (a stock card, or one "
                      "built without --selector-dir)" % (path, SELECT_DIR))
    ents = [e for e in debugfs_ls(ref, SELECT_DIR) if e[4] not in (".", "..")]
    sizes = {e[4]: e[5] for e in ents}
    isdir = {e[4]: statmod.S_ISDIR(e[1]) for e in ents}
    raw_conf = read_select_file(ref, "images.conf")
    if raw_conf is None:
        raise Refused("%s: %s is on the card but holds no images.conf - there is no menu to read"
                      % (path, SELECT_DIR))
    conf = parse_images_conf(raw_conf)
    build = parse_manifest(read_select_file(ref, BUILD_MANIFEST), BUILD_MANIFEST, warnings)
    media_json = read_select_file(ref, MEDIA_MANIFEST)
    media_man = parse_manifest(media_json, MEDIA_MANIFEST, warnings)
    try:
        trees_rec = read_trees(path, ref)
    except Refused as e:
        trees_rec = None
        warnings.append(str(e))
    if build is None:
        warnings.append("no %s on this card (it predates the sidecar, or another tool wrote it): "
                        "the images' source .raw paths are unknown - re-inject with --primary/"
                        "--extra to record them" % BUILD_MANIFEST)
    if media_man is None and any(any(m) for m in conf["media"]):
        warnings.append("no %s on this card: the art/animation SPECS are unknown (the staged file "
                        "names are still in images.conf)" % MEDIA_MANIFEST)
    plan = None
    try:
        plan = plan_from_card(path)
    except Refused as e:
        warnings.append("the partition table does not read as a multi card (%s); the images below "
                        "come from images.conf alone" % e)
    trees = {device_name(p.num, s): (p, s) for (p, s) in (plan.trees if plan else [])}
    prev = {im["device"]: im for im in ((build or {}).get("images") or [])
            if isinstance(im, dict) and im.get("device")}
    mrows = (media_man or {}).get("images") or []
    images, treerecs = [], []
    for i, (dev, title, subtitle) in enumerate(conf["images"]):
        art, anim, music, confirm = conf["media"][i] if i < len(conf["media"]) else MEDIA_ROW
        b = prev.get(dev) or {}
        m = mrows[i] if i < len(mrows) and isinstance(mrows[i], dict) else {}
        src = b.get("source") or None
        exists = bool(src) and os.path.isfile(src)
        if src and not exists:
            warnings.append("image %d: its source %s is not on this machine - the menu can still "
                            "be edited and re-injected, only a rebuild needs it" % (i, src))
        if dev in trees:
            p, s = trees[dev]
            try:
                tree = read_tree(path, p, s)
            except Exception as e:                        # ...nor an inspect
                tree = _unread_tree(dev, "its games tree could not be read (%s: %s)"
                                    % (type(e).__name__, e))
        else:
            tree = _unread_tree(dev, "images.conf names %s but the card carries no such games "
                                     "tree" % dev)
        for note in tree["notes"]:
            warnings.append("image %d (%s): %s" % (i, dev, note))
        tree["index"] = i
        treerecs.append(tree)
        title_dir = tree["title"]
        state = None if tree["bypass"] == "error" else ("none" if tree["bypass"] == "absent" else tree["bypass"])
        images.append(collections.OrderedDict([
            ("index", i), ("device", dev), ("title", title), ("subtitle", subtitle),
            ("art", art or None), ("anim", anim or None), ("music", music or None),
            # this image's OWN confirm sound; null = it plays the menu-wide one
            ("confirm", confirm or None), ("confirm_source", m.get("confirm_source")),
            ("art_source", m.get("art_source")), ("anim_source", m.get("anim_source")),
            # ...and the music's, which media.json has always recorded and this
            # report used to drop.  A loader that cannot see what a sound was
            # MADE from has to compare a card's file name against a source path
            # and can only conclude "stale", which is how a loaded card's sounds
            # came back as "not rendered" with every one of them right there in
            # the media directory.
            ("music_source", m.get("music_source")),
            ("source", src), ("source_exists", exists),
            ("title_dir", title_dir), ("bypass", state),
            # what game code this image actually is, read off the card (item 90's version gate);
            # 'built_version' is what build.json recorded when the card was written
            ("version", tree.get("version")), ("version_source", tree.get("version_source")),
            ("sidx", tree.get("sidx")), ("sidx_version", tree.get("sidx_version")),
            ("elf_version", tree.get("elf_version")), ("elf_name", tree.get("elf_name")),
            ("elf_date", tree.get("elf_date")),
            ("node_fw", tree.get("node_fw") or []), ("node_fw_version", tree.get("node_fw_version")),
            ("node_fw_digest", tree.get("node_fw_digest")),
            ("built_version", b.get("version")), ("built_title_dir", b.get("title_dir"))]))
    findings = version_findings(treerecs)
    media = []
    if isdir.get("media"):
        for _ino, _mode, _uid, _gid, name, msize in debugfs_ls(ref, MEDIA_DIR):
            if name not in (".", ".."):
                media.append(collections.OrderedDict([("name", name), ("bytes", msize)]))
        media.sort(key=lambda x: x["name"])
    have = {x["name"] for x in media}
    missing = [n for n in conf_media_names(conf) if n not in have]
    if missing:
        warnings.append("images.conf names %d media file(s) the card does not carry: %s"
                        % (len(missing), ", ".join(missing)))
    sel = collections.OrderedDict([("bytes", sizes.get("codeselect")), ("version", None)])
    if "codeselect" not in sizes:
        warnings.append("no codeselect binary in %s: this card will not show a menu" % SELECT_DIR)
    elif sizes["codeselect"] <= SELECTOR_VERSION_MAX:
        m = SELECTOR_VERSION_RE.search(read_select_file(ref, "codeselect") or b"")
        if m:
            sel["version"] = m.group(1).decode("ascii", "replace")
    out = None
    if media_out:
        written, skipped = extract_card_media(ref, media_out, [x["name"] for x in media], media_json)
        out = collections.OrderedDict([("dir", os.path.abspath(media_out)), ("files", len(written))])
        if skipped:
            warnings.append("%d media file(s) with names this tool never writes were left on the "
                            "card: %s" % (len(skipped), ", ".join(skipped)))
        if media_json is None and os.path.isfile(os.path.join(media_out, MEDIA_MANIFEST)):
            warnings.append("%s already held a %s and this card carries none - it is an EARLIER "
                            "load's, not this card's; use a fresh directory before re-injecting "
                            "from it" % (media_out, MEDIA_MANIFEST))
    parts = [collections.OrderedDict([("num", n), ("type", t), ("start", st), ("count", cnt),
                                      ("bytes", cnt * SECTOR)])
             for (n, t, st, cnt) in ([(x[0], x[1], x[2], x[3]) for x in geom.prim]
                                     + [(5 + i, t, st, cnt) for i, (_e, t, st, cnt) in enumerate(geom.logical)])]
    return collections.OrderedDict([
        ("card", path), ("size", size),
        ("layout", plan.layout if plan else ("multi" if any(":" in d for (d, _t, _s) in conf["images"]) else "parts")),
        ("partitions", parts), ("images", images),
        # what is on every games tree, and whether its source moved since (item 93)
        ("trees", trees_report(path, plan, trees_rec, warnings)),
        ("timeout", conf["timeout"]), ("default", conf["default"]),
        ("volume", conf["volume"]), ("machine_volume", conf.get("machine_volume")),
        ("mixer_volume", conf["mixer_volume"]),
        ("sound_move", conf["sound_move"]), ("sound_confirm", conf["sound_confirm"]),
        # The SPECS those two were rendered from (media.json's, not the conf's -
        # the conf only knows the file name that landed).  Same reason as
        # music_source above: without them a load cannot tell a sound that is
        # already right from one that needs re-rendering.
        ("sound_move_source", (media_man or {}).get("sound_move_source")),
        ("sound_confirm_source", (media_man or {}).get("sound_confirm_source")),
        ("font", conf["font"]), ("media_dir", conf["media_dir"]),
        ("debug_log", conf.get("debug_log")),
        ("theme", conf.get("theme")), ("colors", dict(conf.get("colors") or {})),
        ("media", media), ("media_out", out),
        ("has_media_json", media_json is not None), ("has_build_json", build is not None),
        ("build", None if build is None else collections.OrderedDict(
            [(k, build.get(k)) for k in ("tool", "version", "written")])),
        # the version gate's answers, ready-made sentences so a GUI shows them without
        # re-deriving anything (null when the images agree)
        ("title_mismatch", findings["title_mismatch"]),
        ("version_mismatch", findings["version_mismatch"]),
        ("node_fw_mismatch", findings["node_fw_mismatch"]),
        ("unknown_version", findings["unknown_version"]),
        ("selector", sel), ("warnings", warnings)])


def print_inspect(rep):
    """The human table `inspect` prints without --json."""
    print("card       %s" % rep["card"])
    print("size       %s (%d bytes)" % (_gb(rep["size"]), rep["size"]))
    print("layout     %s" % rep["layout"])
    print("table      %s" % ", ".join("p%d %s %s" % (p["num"], "0x%02x" % p["type"], _gb(p["bytes"]))
                                      for p in rep["partitions"]))
    sel = rep["selector"]
    print("selector   codeselect %s, %s; build.json %s, media.json %s"
          % (sel["version"] or "(version unknown)",
             "%d bytes" % sel["bytes"] if sel["bytes"] else "MISSING",
             "yes" if rep["has_build_json"] else "no", "yes" if rep["has_media_json"] else "no"))
    if rep.get("build"):
        print("built      %s by %s %s" % (rep["build"].get("written"), rep["build"].get("tool"),
                                          rep["build"].get("version")))
    print("menu       default=%s timeout=%s volume=%s mixer_volume=%s sound_move=%s sound_confirm=%s font=%s log=%s"
          % (rep["default"], rep["timeout"], rep["volume"], rep["mixer_volume"],
             rep["sound_move"], rep["sound_confirm"], rep["font"], rep.get("debug_log") or "off"))
    colors = "".join(" color_%s=%s" % kv for kv in sorted((rep.get("colors") or {}).items()))
    print("theme      %s%s" % (rep.get("theme") or "(the selector's default)", colors))
    for im in rep["images"]:
        print("image %d    %s  %r / %r" % (im["index"], im["device"], im["title"], im["subtitle"]))
        print("           art=%s anim=%s music=%s confirm=%s"
              % (im["art"], im["anim"], im["music"],
                 im["confirm"] or "(the menu's)"))
        if im["art_source"] or im["anim_source"] or im["confirm_source"]:
            print("           art_source=%s anim_source=%s confirm_source=%s"
                  % (im["art_source"], im["anim_source"], im["confirm_source"]))
        print("           source=%s%s" % (im["source"], "" if im["source"] is None else
                                          (" (on this machine)" if im["source_exists"] else " (MISSING here)")))
        print("           title dir=%s  validator=%s" % (im["title_dir"], im["bypass"]))
        print("           game code=%s (%s; sidx=%s, ELF=%s %s)  node firmware=%s (%d hex)"
              % (im["version"] or "UNKNOWN", im["version_source"] or "-", im["sidx_version"],
                 im["elf_version"], im["elf_date"], im["node_fw_version"] or "-", len(im["node_fw"])))
        if im["built_version"] and im["built_version"] != im["version"]:
            print("           BUILT FROM %s per build.json - the tree on this card says %s"
                  % (im["built_version"], im["version"]))
    for key in ("version_mismatch", "node_fw_mismatch", "unknown_version"):
        if rep.get(key):
            print("VERSION WARNING: %s" % rep[key])
    tr = rep.get("trees")
    if tr:
        print("trees      recorded %s; %s free for updates; synced %s%s"
              % (tr["written"], _gb(tr["free_bytes"] or 0),
                 ",".join("p%d" % n for n in tr["synced"]) or "none",
                 ("; DIRTY %s - an update was interrupted" % tr["dirty"]) if tr["dirty"] else ""))
        for im in tr["images"]:
            print("           image %d: %d files, %s%s" % (
                im["index"], im["files"], _gb(im["tree_bytes"]),
                {True: " - SOURCE CHANGED on disk since the card was written",
                 False: " - source unchanged", None: " - source not on this machine"}[im["source_changed"]]))
    else:
        print("trees      not recorded (built before item 93; `update` records it)")
    print("media      %d file(s), %d KB of the %d KB budget"
          % (len(rep["media"]), sum(m["bytes"] for m in rep["media"]) >> 10, MEDIA_BUDGET >> 10))
    for m in rep["media"]:
        print("           %-28s %d bytes" % (m["name"], m["bytes"]))
    if rep.get("media_out"):
        print("extracted  %d file(s) into %s" % (rep["media_out"]["files"], rep["media_out"]["dir"]))
    for w in rep["warnings"]:
        print("WARNING: %s" % w)


def check_stock(path):
    """Regenerate the stock card's own table with this writer and compare bytes."""
    plan = make_plan(path, [])
    P = plan.primary_geom
    m = mbr_sector(plan)
    ok = True
    print("MBR entries 0x1be..0x1ff regenerated == stock: %s" % (m[0x1BE:] == P.mbr[0x1BE:]))
    if m[0x1BE:] != P.mbr[0x1BE:]:
        ok = False
        print("  want", P.mbr[0x1BE:].hex())
        print("  got ", m[0x1BE:].hex())
    for i, p in enumerate(plan.logs):
        e = ebr_sector(plan, i)
        raw = P.ebr_raw.get(p.ebr)
        print("EBR @%d regenerated == stock: %s" % (p.ebr, e == raw))
        if e != raw:
            ok = False
            print("  want", (raw or b"").hex())
            print("  got ", e.hex())
    print("stock image sectors %d, plan total %d (%s)" % (P.sectors, plan.total, "OK" if P.sectors == plan.total else "DIFFERENT"))
    for w in P.shape_issues():
        print("WARNING: " + w)
    return ok and P.sectors == plan.total


# ============================================================================= synthetic cards
SYNTH_PARTS = {1: (0x0C, 8192, 2048), 2: (0x83, 10240, 2048), 3: (0x83, 12288, 2046)}
SYNTH_EXT = 14336
SYNTH_LOGS = [(5, 0x83, 16384, 2046), (6, 0x83, 18432, 2046)]
# (built by concatenation: the anchor's trailing space must never sit at a physical line end,
#  where an editor would strip it)
SYNTH_GAME = ("#!/bin/sh\n"
              "# synthetic stand-in for Stern's /etc/init.d/game (mkmulticard selftest)\n"
              "GAMES_PATH=/games\n\n"
              "echo \"checking network bridge code version...\"\n\n"
              + PKILL_LINE + "\n\n"
              + IF_LINE + "\n"
              "\techo \"starting application...\"\n"
              "fi\n")


def _mkext(path, kib, files, links=()):
    """A 1 KiB-block ext4 image holding `files` {card path: bytes} (parents created) and symlinks."""
    with open(path, "wb") as f:
        f.truncate(kib * 1024)
    subprocess.run(["mke2fs", "-q", "-F", "-t", "ext4", "-b", "1024", path, str(kib)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmds, made = [], set()
    stage = tempfile.mkdtemp(prefix="synth.")
    for k, (cardpath, data) in enumerate(files.items()):
        parts = cardpath.strip("/").split("/")
        for d in range(1, len(parts)):
            dp = "/" + "/".join(parts[:d])
            if dp not in made:
                made.add(dp)
                cmds.append("mkdir " + dp)
        sp = os.path.join(stage, "f%d" % k)
        with open(sp, "wb") as f:
            f.write(data)
        os.chmod(sp, 0o755)
        cmds.append("write %s %s" % (dq(sp), dq(cardpath)))
    for name, target in links:
        cmds.append("symlink %s %s" % (name, target))
    try:
        debugfs_write_script(path, cmds)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def make_synthetic_card(path, tag, seed, with_fs=False, title=None, version=None, node_fw=None):
    """A stock-shaped card, 10 MiB: p1@8192x2048 p2@10240x2048 p3@12288x2046 ext@14336 p5@16384x2046
    EBR2@18430 p6@18432x2046.  with_fs=False: random payloads (pure python, for the tests);
    with_fs=True: real ext4 with a stand-in game script in p2 and a title dir + game link in p3.

    `title` names the games tree's title directory (default '<tag>_title').  `version` ('1_59_0')
    and `node_fw` ('1_33_0') give that tree a real GAME CODE VERSION to read: the /spk/index
    manifest is named '<title>-<version>.sidx', the title directory gets '<node>-<fw>.hex' node
    firmware files, and its `game` becomes a :func:`synth_game_elf` carrying the same version.
    Without them the tree keeps the older shape (an unversioned .sidx, a text `game`) - which is
    itself worth a card: it is what "this tree's version is UNKNOWN" looks like."""
    import random
    rnd = random.Random(seed)
    d = os.path.dirname(os.path.abspath(path))
    ebrs = [SYNTH_EXT, SYNTH_LOGS[0][2] + SYNTH_LOGS[0][3]]
    assert align_up(ebrs[1] + 1) == SYNTH_LOGS[1][2]
    prev_end = SYNTH_LOGS[1][2] + SYNTH_LOGS[1][3] - 1
    ext_count = prev_end + 1 - SYNTH_EXT
    total = prev_end + 1 + TAIL
    payload = {}

    def blob(n):
        return rnd.getrandbits(n * 8).to_bytes(n, "little")

    for n, (t, st, cnt) in SYNTH_PARTS.items():
        payload[n] = None
    for n, t, st, cnt in SYNTH_LOGS:
        payload[n] = None
    for n in payload:
        cnt = SYNTH_PARTS[n][2] if n in SYNTH_PARTS else [l for l in SYNTH_LOGS if l[0] == n][0][3]
        if with_fs and n != 1:
            p = os.path.join(d, "%s_p%d.ext4" % (tag, n))
            if n == 2:
                _mkext(p, cnt * SECTOR // 1024, {"/etc/init.d/game": SYNTH_GAME.encode(), "/usr/local/README": b"synthetic\n"})
            elif n == 3:
                # a stock games root in miniature: spk/, the title dir (game, conagent, data/),
                # and the three symlinks the machine boots through
                td = title or ("%s_title" % tag)
                files = {"/%s/game" % td: (synth_game_elf(td, version_text(version) or "1.59.0",
                                                          model="%s MODEL" % tag)
                                           if version else ("%s p3 game\n" % tag).encode()),
                         "/%s/conagent" % td: ("%s p3 conagent\n" % tag).encode(),
                         "/%s/data/marker" % td: ("%s p3 data\n" % tag).encode(),
                         "/spk/index/%s%s.sidx" % (td, "-" + version if version else ""): b"not a manifest\n"}
                for node in ("pinnode-LPC1313", "coil4node-LPC1313", "lcdnode-LPC1113_302"):
                    if node_fw:
                        files["/%s/%s-%s.hex" % (td, node, node_fw)] = (":00000001FF\n").encode()
                _mkext(p, cnt * SECTOR // 1024, files,
                       links=[("/game", "%s/game" % td), ("/conagent", "%s/conagent" % td),
                              ("/data", "%s/data" % td)])
            else:
                _mkext(p, cnt * SECTOR // 1024, {"/MARKER": ("%s p%d\n" % (tag, n)).encode()})
            with open(p, "rb") as f:
                payload[n] = f.read()
        else:
            payload[n] = blob(cnt * SECTOR)
    boot = bytearray(SECTOR)
    boot[:0x4C] = blob(0x4C)                                # fake bootstrap
    boot[0x1B8:0x1BC] = struct.pack("<I", seed & 0xffffffff)  # disk id
    boot[0x1BE:0x1FE] = b"".join([entry(*SYNTH_PARTS[1]), entry(*SYNTH_PARTS[2]), entry(*SYNTH_PARTS[3]),
                                  entry(0x0F, SYNTH_EXT, ext_count)])
    boot[510:512] = b"\x55\xaa"
    with open(path, "wb") as o:
        o.truncate(total * SECTOR)
    with open(path, "r+b") as o:
        o.seek(0)
        o.write(bytes(boot))
        o.seek(2 * SECTOR)
        o.write(blob(654 * SECTOR))                         # fake u-boot at sectors 2..655
        for n, (t, st, cnt) in SYNTH_PARTS.items():
            o.seek(st * SECTOR)
            o.write(payload[n])
        for i, (n, t, st, cnt) in enumerate(SYNTH_LOGS):
            eb = bytearray(SECTOR)
            eb[0x1BE:0x1CE] = entry(t, st - ebrs[i], cnt, chs_base=ebrs[i])
            if i + 1 < len(SYNTH_LOGS):
                _nn, _nt, nst, ncnt = SYNTH_LOGS[i + 1]
                eb[0x1CE:0x1DE] = entry(0x05, ebrs[i + 1] - SYNTH_EXT, nst + ncnt - ebrs[i + 1], chs_base=SYNTH_EXT)
            eb[510:512] = b"\x55\xaa"
            o.seek(ebrs[i] * SECTOR)
            o.write(bytes(eb))
            o.seek(st * SECTOR)
            o.write(payload[n])
    return path


def synth_game_elf(title_dir="turtles_pro", version="1.59.0", model="TMNT PRO", code="TMT",
                   date="AUGUST 25, 2019", extra_names=(), with_title=True, hi=0):
    """A tiny 32-bit little-endian ARM ELF carrying ONE build-identity record, exactly the shape
    :func:`game_identity` reads off a real card: a .rodata segment of C strings and a .data
    segment holding [code][model...][date][title dir] pointers followed by the uint16 version.

    with_title=False builds the godzilla shape (no title-directory pointer in the record); `hi`
    puts junk in the version word's high half (the james_bond shape, where the version really is
    a uint16 and the word above it is another field).  Pure python - no card, no WSL."""
    major, minor = (int(x) for x in version.split(".")[:2])
    names = [code, model] + list(extra_names) + [date] + ([title_dir] if with_title else [])
    ro, offs = bytearray(), []
    for s in names:
        offs.append(len(ro))
        ro += s.encode("ascii") + b"\x00"
        ro += b"\x00" * (-len(ro) % 4)
    ehsize, phentsize, shentsize = 0x34, 32, 40
    text = b"\x00" * 16                                # empty enough that no locator matches it
    text_off = ehsize + 2 * phentsize
    ro_off = text_off + len(text)
    ro_va = 0x8000 + ro_off
    data = bytearray(b"\x00" * 16)                     # a run of non-pointers before the record
    for o in offs:
        data += struct.pack("<I", ro_va + o)
    data += struct.pack("<HH", (major << 8) | minor, hi)
    data += b"\x00" * 32
    data_off = ro_off + len(ro)
    data_va = 0x100000 + data_off
    shstr = b"\x00.text\x00.shstrtab\x00"
    shstr_off = data_off + len(data)
    sh_off = shstr_off + len(shstr)
    elf = bytearray(b"\x7fELF\x01\x01\x01" + b"\x00" * 9)
    elf += struct.pack("<HHIIIIIHHHHHH", 2, 40, 1, ro_va, ehsize, sh_off, 0,
                       ehsize, phentsize, 2, shentsize, 3, 2)
    for off, va, blob in ((ro_off, ro_va, ro), (data_off, data_va, data)):
        elf += struct.pack("<IIIIIIII", 1, off, va, va, len(blob), len(blob), 6, 4)
    elf += text + ro + data + shstr
    elf += struct.pack("<10I", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)                       # SHT_NULL
    elf += struct.pack("<10I", 1, 1, 6, 0x8000, text_off, len(text), 0, 0, 4, 0)    # .text
    elf += struct.pack("<10I", 7, 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0)       # .shstrtab
    return bytes(elf)


def synth_png(path, w=4, h=3, rgb=(0xC0, 0x30, 0x40)):
    """A tiny valid RGB PNG (zlib only)."""
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)
    return data


def synth_gif(path, w=4, h=3, frames=2):
    """A tiny valid animated GIF (2-colour global table, one uncompressed-ish LZW image per frame)."""
    out = bytearray(b"GIF89a" + struct.pack("<HH", w, h) + bytes([0x80, 0, 0]) + b"\x00\x00\x00\xff\xff\xff")
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"                       # loop for ever
    for i in range(frames):
        out += b"\x21\xf9\x04\x00\x0a\x00\x00\x00"                                # GCE: 100 ms
        out += b"\x2c" + struct.pack("<HHHH", 0, 0, w, h) + b"\x00"               # image descriptor
        # LZW min code size 2: codes clear=4, end=5, 3 bits wide.  A clear before EVERY pixel
        # keeps the decoder's table empty, so the width never grows and each pixel is one
        # 3-bit literal (0 or 1).
        pix = [(x + i) & 1 for x in range(w * h)]
        bits, nb, cur = [], 0, 0
        codes = []
        for p in pix:
            codes += [4, p]
        codes.append(5)
        width = 3
        for c in codes:
            cur |= c << nb
            nb += width
            while nb >= 8:
                bits.append(cur & 0xff)
                cur >>= 8
                nb -= 8
        if nb:
            bits.append(cur & 0xff)
        out += b"\x02"                                                            # LZW minimum code size
        for k in range(0, len(bits), 255):                                        # <= 255-byte sub-blocks
            blk = bits[k:k + 255]
            out += bytes([len(blk)]) + bytes(blk)
        out += b"\x00"
    out += b"\x3b"
    with open(path, "wb") as f:
        f.write(out)
    return bytes(out)


def synth_wav(path, rate=WAV_RATE, ch=2, secs=0.05, bits=16):
    """A short RIFF pcm WAV of silence (the header is what the checks read)."""
    n = int(rate * secs)
    data = bytes(n * ch * (bits // 8))
    fmt = struct.pack("<HHIIHH", 1, ch, rate, rate * ch * bits // 8, ch * bits // 8, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def synth_media_dir(d, n_images):
    """A media directory with media.json for `n_images` images: art for every image, an anim
    and a music for image 1, the two sounds.  -> path."""
    os.makedirs(d, exist_ok=True)
    imgs = []
    for i in range(n_images):
        synth_png(os.path.join(d, "art%d.png" % i))
        imgs.append({"art": "art%d.png" % i, "anim": None, "music": None})
    if n_images > 1:
        synth_gif(os.path.join(d, "anim1.gif"))
        synth_wav(os.path.join(d, "music1.wav"))
        # image 1 gets a confirm sound of its OWN, so the 7-field line, the staging of
        # confirm1.wav and the fallback for the images without one are all exercised
        synth_wav(os.path.join(d, "confirm1.wav"))
        imgs[1]["anim"], imgs[1]["music"] = "anim1.gif", "music1.wav"
        imgs[1]["confirm"] = "confirm1.wav"
    synth_wav(os.path.join(d, "move.wav"), ch=1)
    synth_wav(os.path.join(d, "confirm.wav"))
    synth_wav(os.path.join(d, "wrong_rate.wav"), rate=48000)                # unreferenced, must NOT be staged
    with open(os.path.join(d, MEDIA_MANIFEST), "w", encoding="utf-8") as f:
        json.dump({"images": imgs, "sound_move": "move.wav", "sound_confirm": "confirm.wav", "volume": 40}, f, indent=1)
    return d


class Checks:
    """``ok &= <expression>`` that SAYS WHICH EXPRESSION FAILED.

    The selftest is one long chain of `ok &=`, and a False in the middle of
    it used to print nothing at all: the run just ended in FAIL, and the
    only way to find the check was to swap older copies of this file in and
    bisect.  That happened, once, and one line of output would have saved
    it - so this stands in for the plain bool and names the line."""

    def __init__(self):
        self.ok = True
        self.failed = []

    def __iand__(self, value):
        if not value:
            # the CALLER's frame, file and line together: a name taken from
            # this module and a line taken from the caller would point at a
            # line that is not the check
            frame = sys._getframe(1)
            line = frame.f_lineno
            print("    CHECK FAILED at %s:%d"
                  % (os.path.basename(frame.f_code.co_filename), line))
            self.failed.append(line)
            self.ok = False
        return self

    def __bool__(self):
        return self.ok


def selftest(d, selector_file=None):
    """PART 1 (parts layout): synthetic A+B+C -> 3-image card with injection + media -> verify ->
    inject again with the media dir present (idempotence) -> verify -> a byte of p2 flipped
    outside the injected files -> verify FAILS on the sidecar -> put back.  Three images on
    purpose (p7 AND p8): the layout arithmetic is exercised past the hardware limit; the plan
    printout says p8 is unreachable, and the build here is what --allow-unreachable would do.
    PART 2 (multi layout): the same three sources as a p3 + p7{img1,img2} card: parse-back of
    the devices, the symlinks and ownership of p7/img1 by debugfs ls, e2fsck, the bypass
    subcommand on trees whose game is not an ELF ('none on this build'), verify PASS.
    The staging directory has a SPACE in its name so the debugfs quoting is exercised."""
    need_tools("debugfs", "e2fsck", "mke2fs", "sfdisk", "fdisk")
    d = os.path.join(d, "self test")
    os.makedirs(d, exist_ok=True)
    A = make_synthetic_card(os.path.join(d, "A.img"), "A", 0x0A0A0A0A, with_fs=True)
    B = make_synthetic_card(os.path.join(d, "B.img"), "B", 0x0B0B0B0B, with_fs=True)
    C = make_synthetic_card(os.path.join(d, "C.img"), "C", 0x0C0C0C0C, with_fs=True)
    sel = os.path.join(d, "seldir")
    os.makedirs(sel, exist_ok=True)
    with open(os.path.join(sel, "codeselect"), "wb") as f:
        f.write(open(selector_file, "rb").read() if selector_file else b"#!/bin/sh\necho '[select] chose 0 selftest'\n")
    with open(os.path.join(sel, "select.sh"), "w", newline="\n") as f:
        f.write("#!/bin/sh\n# selftest placeholder\nexit 0\n")
    media = synth_media_dir(os.path.join(d, "media dir"), 3)
    out = os.path.join(d, "multi.img")
    if os.path.exists(out):
        os.unlink(out)
    drop_stale_sidecars(out, keep=())
    plan = make_plan(A, [B, C], layout="parts")
    print("== plan (parts)")
    print_plan(plan)
    ok = Checks()
    ok &= plan.unreachable_note() == "p8 unreachable on the machine"
    try:
        check_reachable(plan)
        print("SELFTEST: check_reachable accepted a p8 image")
        ok &= False
    except Refused as e:
        print("refused without --allow-unreachable, as it should be: %s" % str(e).splitlines()[0])
    check_reachable(plan, allow=True)
    print("== build (parts)")
    build_image(plan, out)
    ms = plan_media(media, 3)
    ok &= list(ms["files"]) == ["art0.png", "art1.png", "anim1.gif", "music1.wav", "confirm1.wav",
                                "art2.png", "move.wav", "confirm.wav"]
    ok &= ms["rows"][1][3] == "confirm1.wav" and ms["rows"][0][3] == ""
    ok &= "wrong_rate.wav" not in ms["files"] and ms["volume"] == 40
    conf = render_images_conf(plan.devices(), ["A stock", "B", "C"], ["synthetic", "", "third"], 1, 7, None,
                              ms["rows"], ms["sound_move"], ms["sound_confirm"], ms["volume"],
                              theme="custom", colors={"frame_hl": "00ff00", "background": "#102030"})
    mans = selector_manifests(plan, conf, media, [A, B, C])
    inject_card(out, sel, conf, workdir=d, media_files=ms["files"], manifests=mans)
    print("== verify")
    ok &= verify_card(out, plan, sel, media)
    print("== inject again with the media directory present (idempotence)")
    inject_card(out, sel, conf, workdir=d, media_files=ms["files"], manifests=mans)
    ok &= verify_card(out, plan, sel, media)
    print("== inject without media: the media directory, media.json and the conf's media fields are carried through")
    ref0 = select_ref(out)
    old_build = parse_manifest(read_select_file(ref0, BUILD_MANIFEST), BUILD_MANIFEST)
    old_media = read_select_file(ref0, MEDIA_MANIFEST)
    carried = conf_for_plan(plan, argparse.Namespace(), existing=card_conf(out, ref0))
    inject_card(out, sel, carried, workdir=d,
                manifests=selector_manifests(plan, carried, None, None, old_build, old_media))
    ok &= verify_card(out, plan, sel, media)
    ref0 = select_ref(out)
    now = parse_manifest(read_select_file(ref0, BUILD_MANIFEST), BUILD_MANIFEST)
    ok &= [im["source"] for im in now["images"]] == [os.path.abspath(x) for x in (A, B, C)]
    ok &= read_select_file(ref0, MEDIA_MANIFEST) == old_media
    print("provenance carried through an inject with no sources: %s"
          % ", ".join(os.path.basename(im["source"] or "?") for im in now["images"]))
    print("== p2 corrupted outside the injected files: verify must FAIL on the sidecar")
    p2off, p2len = p2_range(out)
    spot = p2off + p2len - 3 * 1024            # the last blocks of a 1 MiB ext4: free, so e2fsck stays clean
    with open(out, "r+b") as f:
        f.seek(spot)
        was = f.read(1)
        f.seek(spot)
        f.write(bytes([was[0] ^ 0xff]))
    want, got = check_p2_sidecar(out)
    ok &= want is not None and want != got
    ok &= not verify_card(out, plan, sel)
    with open(out, "r+b") as f:
        f.seek(spot)
        f.write(was)
    want, got = check_p2_sidecar(out)
    ok &= want == got
    print("== p2 put back: verify PASS again")
    ok &= verify_card(out, plan, sel)
    ref = fs_ref(out, plan.prims[1].start * SECTOR)
    back = parse_images_conf(debugfs_cat(ref, SELECT_DIR + "/images.conf"))
    ok &= back["theme"] == "custom" and back["colors"] == {"background": "102030", "frame_hl": "00ff00"}
    ok &= back["images"] == [("/dev/mmcblk0p3", "A stock", "synthetic"), ("/dev/mmcblk0p7", "B", ""), ("/dev/mmcblk0p8", "C", "third")]
    ok &= back["media"] == [("art0.png", "", "", ""),
                            ("art1.png", "anim1.gif", "music1.wav", "confirm1.wav"),
                            ("art2.png", "", "", "")]
    # the seventh field survived the write and the read back: image 1 plays its OWN sound
    ok &= "|art1.png|anim1.gif|music1.wav|confirm1.wav" in conf
    ok &= back["default"] == 1 and back["timeout"] == 7 and back["volume"] == 40
    ok &= (back["sound_move"], back["sound_confirm"], back["media_dir"]) == ("move.wav", "confirm.wav", MEDIA_DIR)
    names = sorted(e[4] for e in debugfs_ls(ref, MEDIA_DIR) if e[4] not in (".", ".."))
    ok &= names == sorted(ms["files"])
    print("media on the card: %s" % ", ".join(names))
    print("== inspect (the card read back) + --media-out")
    mout = os.path.join(d, "loaded media")
    rep = inspect_card(out, mout)
    print_inspect(rep)
    ok &= rep["has_build_json"] and rep["has_media_json"] and rep["layout"] == "parts"
    ok &= [im["device"] for im in rep["images"]] == plan.devices()
    ok &= [im["title"] for im in rep["images"]] == ["A stock", "B", "C"]
    ok &= [im["source"] for im in rep["images"]] == [os.path.abspath(x) for x in (A, B, C)]
    ok &= [im["source_exists"] for im in rep["images"]] == [True, True, True]
    ok &= (rep["default"], rep["timeout"], rep["volume"]) == (1, 7, 40)
    ok &= sorted(m["name"] for m in rep["media"]) == names
    ok &= sorted(os.listdir(mout)) == sorted(names + [MEDIA_MANIFEST])
    # the extracted directory is a --media-dir again: the round trip a GUI reload needs
    ok &= list(plan_media(mout, 3)["files"]) == list(ms["files"])
    for n in (7, 8):
        _t, st, _c = Geometry.from_file(out).part(n)
        link = debugfs_stat(fs_ref(out, st * SECTOR), "/game").get("link")     # a fast symlink has no blocks to cat
        marker = debugfs_cat(fs_ref(out, st * SECTOR), "/" + (link or "game")).decode().strip()
        print("p%d /game -> %r -> %r" % (n, link, marker))
        ok &= marker == ("%s p3 game" % ("B" if n == 7 else "C"))
    print("== a media set that names a missing file / a 48 kHz WAV is refused before anything is written")
    bad = synth_media_dir(os.path.join(d, "bad media"), 3)
    with open(os.path.join(bad, MEDIA_MANIFEST), "w", encoding="utf-8") as f:
        json.dump({"images": [{"art": "art0.png"}, {"art": "nope.png"}, {}], "sound_move": "move.wav"}, f)
    for want_msg, man in (("does not exist", None),
                          ("48000 Hz", {"images": [{}, {}, {}], "sound_move": "wrong_rate.wav"}),
                          ("plain media file name", {"images": [{"art": "../x.png"}, {}, {}]}),
                          ("lists 2 images", {"images": [{}, {}]})):
        if man is not None:
            with open(os.path.join(bad, MEDIA_MANIFEST), "w", encoding="utf-8") as f:
                json.dump(man, f)
        try:
            plan_media(bad, 3)
            print("SELFTEST: a bad media set was accepted (%s)" % want_msg)
            ok &= False
        except Refused as e:
            print("refused: %s" % e)
            ok &= want_msg in str(e)
    print("SELFTEST part 1 (parts layout)", "PASS" if ok else "FAIL")

    # ---------------------------------------------------------------- part 2: the multi layout
    print("== plan (multi)")
    out2 = os.path.join(d, "multi3.img")
    if os.path.exists(out2):
        os.unlink(out2)
    drop_stale_sidecars(out2, keep=())
    plan2 = make_plan(A, [B, C], layout="auto")
    ok &= plan2.layout == "multi" and plan2.multi_subdirs == ["img1", "img2"]
    ok &= plan2.devices() == ["/dev/mmcblk0p3", "/dev/mmcblk0p7:img1", "/dev/mmcblk0p7:img2"]
    ok &= [p.num for p in plan2.logs] == [5, 6, 7] and plan2.unreachable() == []
    print_plan(plan2)
    print("== build (multi)")
    p7img, tmp = build_multi_partition(plan2, workdir=d)
    try:
        plan2 = plan2.with_multi_src(p7img)
        build_image(plan2, out2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    say("p7 md5 %s recorded in %s" % (write_part_sidecar(out2, 7), sidecar_path(out2, 7)))
    conf2 = conf_for_plan(plan2, argparse.Namespace(titles="A stock;B;C", subtitles="synthetic;;third", timeout=9))
    inject_card(out2, sel, conf2, workdir=d, manifests=selector_manifests(plan2, conf2, None, [A, B, C]))
    print("== the card reads back as a multi card")
    back2 = plan_from_card(out2)
    ok &= back2.layout == "multi" and back2.devices() == plan2.devices() and back2.table() == plan2.table()
    for sub, tag in (("img1", "B"), ("img2", "C")):
        _t, st, _c = Geometry.from_file(out2).part(7)
        ref7 = fs_ref(out2, st * SECTOR)
        ents = {e[4]: e for e in debugfs_ls(ref7, "/" + sub)}
        print("p7/%s: %s" % (sub, ", ".join("%s(%o uid %d)" % (n, e[1] & 0o170777, e[2]) for n, e in sorted(ents.items()) if n not in (".", ".."))))
        ok &= statmod.S_ISDIR(ents["spk"][1]) and statmod.S_ISDIR(ents["%s_title" % tag][1])
        for name in ("game", "conagent", "data"):
            ok &= name in ents and statmod.S_ISLNK(ents[name][1]) and ents[name][2] == 0 and ents[name][3] == 0
        link = debugfs_stat(ref7, "/%s/game" % sub).get("link")
        marker = debugfs_cat(ref7, "/%s/%s" % (sub, link)).decode().strip()
        print("p7/%s/game -> %r -> %r" % (sub, link, marker))
        ok &= marker == "%s p3 game" % tag and link == "%s_title/game" % tag
        ok &= ents["%s_title" % tag][2] == 0 and ents["spk"][2] == 0
    print("== bypass on trees whose game is not an ELF: 'none on this build', nothing written")
    before = md5_file(out2)
    states = bypass_card(out2)
    ok &= states == {0: "absent", 1: "absent", 2: "absent"} and md5_file(out2) == before
    print("== verify (multi)")
    ok &= verify_card(out2, plan2, sel)
    ref2 = fs_ref(out2, plan2.prims[1].start * SECTOR)
    cb = parse_images_conf(debugfs_cat(ref2, SELECT_DIR + "/images.conf"))
    ok &= [dv for (dv, _t, _s) in cb["images"]] == plan2.devices() and cb["timeout"] == 9
    ok &= [t for (_d, t, _s) in cb["images"]] == ["A stock", "B", "C"]
    print("== inspect (multi): the subdirectory devices and the provenance of each tree")
    rep2 = inspect_card(out2)
    print_inspect(rep2)
    ok &= rep2["layout"] == "multi" and [im["device"] for im in rep2["images"]] == plan2.devices()
    ok &= [im["source"] for im in rep2["images"]] == [os.path.abspath(x) for x in (A, B, C)]
    ok &= [im["title_dir"] for im in rep2["images"]] == ["A_title", "B_title", "C_title"]
    ok &= rep2["has_build_json"] and not rep2["has_media_json"] and rep2["media"] == []
    ok &= all(im["version"] is None for im in rep2["images"])          # no versioned .sidx here
    ok &= rep2["title_mismatch"] and "DIFFERENT TITLES" in rep2["title_mismatch"]
    ok &= rep2["unknown_version"] and "did not say what game code" in rep2["unknown_version"]
    print("SELFTEST part 2 (multi layout)", "PASS" if ok else "FAIL")

    # ------------------------------------------------- part 3: the same-version gate (item 90)
    print("== the game code version gate")
    V = [make_synthetic_card(os.path.join(d, "V%d.img" % i), "V%d" % i, 0x0D0D0D00 + i, with_fs=True,
                             title="turtles_pro", version=v, node_fw=fw)
         for i, (v, fw) in enumerate([("1_59_0", "1_33_0"), ("1_59_0", "1_33_0"), ("1_58_0", "1_19_0")])]
    same = plan_identities(make_plan(V[0], [V[1]], "parts"), progress=None)
    print_version_table(same)
    ok &= [r["version"] for r in same] == ["1.59.0", "1.59.0"]
    ok &= [r["version_source"] for r in same] == ["spk index + game ELF"] * 2
    ok &= [r["node_fw_version"] for r in same] == ["1.33.0", "1.33.0"]
    ok &= all(v is None for v in check_versions(same).values())        # same version: SILENT
    diff = plan_identities(make_plan(V[0], [V[2]], "parts"), progress=None)
    print_version_table(diff)
    try:
        check_versions(diff)
        print("SELFTEST: a mismatched pair was accepted")
        ok &= False
    except Refused as e:
        ok &= "GAME CODE VERSION" in str(e) and "NODE BOARD FIRMWARE" in str(e)
        ok &= "--allow-version-mismatch" in str(e) and "1.59.0" in str(e) and "1.58.0" in str(e)
        print("refused, as it should be:\n%s" % e)
    ok &= check_versions(diff, allow=True)["version_mismatch"] is not None
    out3 = os.path.join(d, "versions.img")
    args = ["build", "--primary", V[0], "--extra", V[2], "--out", out3, "--selector-dir", sel,
            "--layout", "parts", "--force"]
    ok &= main(args) == 2 and not os.path.exists(out3)         # refused BEFORE a byte was written
    print("build refused and wrote nothing: %s" % (not os.path.exists(out3)))
    ok &= main(args + ["--allow-version-mismatch"]) == 0 and os.path.isfile(out3)
    rep3 = inspect_card(out3)
    print_inspect(rep3)
    ok &= [im["version"] for im in rep3["images"]] == ["1.59.0", "1.58.0"]
    ok &= [im["built_version"] for im in rep3["images"]] == ["1.59.0", "1.58.0"]
    ok &= [im["node_fw_version"] for im in rep3["images"]] == ["1.33.0", "1.19.0"]
    ok &= rep3["version_mismatch"] and rep3["node_fw_mismatch"] and not rep3["title_mismatch"]
    print("SELFTEST part 3 (version gate)", "PASS" if ok else "FAIL")

    # ------------------------------------------------- part 4: the record (item 93), any user
    print("== the record: build wrote trees.json, verify reads it, inject carries it, a dirty card refuses")
    ts = _treesync()
    plan3 = verify_plan(out3, [V[0], V[2]])
    rec3 = read_trees(out3)
    ok &= rec3 is not None and [im.index for im in rec3.images] == [0, 1]
    ok &= rec3.layout == "parts" and rec3.synced == [] and rec3.dirty == []
    ok &= all(im.stamp and im.stamp["size"] == os.path.getsize(im.stamp["path"]) for im in rec3.images)
    ok &= "turtles_pro/game" in rec3.images[0].tree.files
    ok &= rec3.images[0].tree.symlinks["game"].target == "turtles_pro/game"
    ok &= rec3.primary.get("p1_md5") and rec3.primary.get("p2_tree")
    rep3b = inspect_card(out3)
    ok &= rep3b["trees"] and rep3b["trees"]["recorded"]
    ok &= [i["source_changed"] for i in rep3b["trees"]["images"]] == [False, False]
    print("== verify holds the trees to the record (full)")
    ok &= verify_card(out3, plan3, sel, mode="full")
    raw_before = read_select_file(select_ref(out3), TREES_MANIFEST)
    print("== inject (a menu change) carries trees.json through byte for byte")
    ok &= main(["inject", "--card", out3, "--selector-dir", sel, "--titles", "One;Two"]) == 0
    ok &= read_select_file(select_ref(out3), TREES_MANIFEST) == raw_before
    ok &= card_conf(out3)["images"][0][1] == "One"
    print("== a dirty record refuses an inject, and verify FAILs it")
    rec3.dirty = [7]
    write_trees(out3, rec3, workdir=d)
    ok &= main(["inject", "--card", out3, "--selector-dir", sel]) == 2
    ok &= not verify_card(out3, plan3, sel, mode="quick")
    rec3.dirty = []
    write_trees(out3, rec3, workdir=d)
    ok &= verify_card(out3, plan3, sel, mode="quick")
    print("== plan prints the room for updates")
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_plan(plan3)
    lines = buf.getvalue().splitlines()
    free_row = [ln for ln in lines if ln.startswith("image-size free ")]
    ok &= len(free_row) == 1 and int(free_row[0].split()[2]) > 0
    rows = [int(ln.split()[3]) for ln in lines if ln.startswith("image-size ") and ln.split()[1].isdigit()]
    over = [int(ln.split()[2]) for ln in lines if ln.startswith("image-size overhead ")]
    ok &= sum(rows) + int(free_row[0].split()[2]) + over[0] == plan3.total_bytes
    print("== the p2 write primitive: a small file in, read back, sidecar right, e2fsck clean")
    write_select_files(out3, {"notes.json": b'{"a": 1}'}, workdir=d)
    ok &= read_select_file(select_ref(out3), "notes.json") == b'{"a": 1}'
    want, got = check_p2_sidecar(out3)
    ok &= want == got
    print("SELFTEST part 4 (the record)", "PASS" if ok else "FAIL")

    # ------------------------------------------------- part 5: update (item 93), root only
    avail, why = loop_available()
    if not avail:
        print("SELFTEST NOTE: part 5 (update) not exercised - %s; run: wsl -u root python3 %s selftest DIR"
              % (why, os.path.abspath(__file__)))
        print("SELFTEST", "PASS" if ok else "FAIL")
        return bool(ok)
    print("== update: nothing changed -> nothing written")
    ok &= main(["update", "--card", out3, "--selector-dir", sel, "--dry-run"]) == 0
    ok &= main(["update", "--card", out3, "--selector-dir", sel]) == 0
    print("== update: one file changed in the extra's source -> only that file written")
    v2 = V[2]
    _t, st2, cnt2 = Geometry.from_file(v2).part(3)
    stage_new = os.path.join(d, "newfile.bin")
    with open(stage_new, "wb") as f:
        f.write(b"N" * 70000)
    debugfs_write_script(fs_ref(v2, st2 * SECTOR), ["write %s /turtles_pro/newfile.bin" % dq(stage_new),
                                                    "set_inode_field /turtles_pro/newfile.bin mode 0100644"])
    os.utime(v2)                                          # the stamp moves as a rewrite would move it
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["update", "--card", out3, "--selector-dir", sel, "--dry-run"])
    dry = buf.getvalue()
    print(dry)
    ok &= rc == 0
    files_rows = [ln.split() for ln in dry.splitlines() if ln.startswith("update-files ")]
    ok &= any(r[1] == "1" and r[3] == "1" and r[4] == "70000" and r[5] == "sync" for r in files_rows), files_rows
    ok &= any(r[1] == "0" and r[5] == "keep" for r in files_rows)
    ok &= "update-source 1 /dev/mmcblk0p7 hashed" in dry and "update-source 0 /dev/mmcblk0p3 unchanged" in dry
    ok &= "update-size 70000" in dry and "update-fits YES" in dry and "update-inject no" in dry
    ok &= main(["update", "--card", out3, "--selector-dir", sel]) == 0
    _t, st7, cnt7 = Geometry.from_file(out3).part(7)
    ok &= debugfs_cat(fs_ref(out3, st7 * SECTOR), "/turtles_pro/newfile.bin") == b"N" * 70000
    rec3 = read_trees(out3)
    ok &= rec3.synced == [7] and rec3.dirty == [] and "turtles_pro/newfile.bin" in rec3.images[1].tree.files
    ok &= ts.stamps_equal(rec3.images[1].stamp, ts.source_stamp(v2))
    ok &= os.path.isfile(out3 + P2_BACKUP_SUFFIX) and not os.path.isfile(sidecar_path(out3, 7))
    ok &= verify_card(out3, plan3, sel, mode="full")
    print("== update: the primary's own tree changes -> p3 synced in place")
    v0 = V[0]
    _t, st0, cnt0 = Geometry.from_file(v0).part(3)
    debugfs_write_script(fs_ref(v0, st0 * SECTOR), ["rm /turtles_pro/conagent",
                                                    "write %s /turtles_pro/conagent" % dq(stage_new),
                                                    "set_inode_field /turtles_pro/conagent mode 0100644"])
    os.utime(v0)
    ok &= main(["update", "--card", out3, "--selector-dir", sel]) == 0
    _t, st3, cnt3 = Geometry.from_file(out3).part(3)
    ok &= debugfs_cat(fs_ref(out3, st3 * SECTOR), "/turtles_pro/conagent") == b"N" * 70000
    ok &= read_trees(out3).synced == [3, 7]
    ok &= verify_card(out3, plan3, sel, mode="full")
    print("== update: a parts card refuses a list change")
    ok &= main(["update", "--card", out3, "--primary", v0, "--extra", v2, "--extra", V[1], "--dry-run"]) == 2
    print("== update: a primary that is another build is refused by the gate")
    other = os.path.join(d, "other.img")
    shutil.copyfile(v0, other)
    _t, sto2, cnto2 = Geometry.from_file(other).part(2)
    debugfs_write_script(fs_ref(other, sto2 * SECTOR), ["write %s /usr/local/OTHER" % dq(stage_new),
                                                        "set_inode_field /usr/local/OTHER mode 0100644"])
    ok &= main(["update", "--card", out3, "--primary", other, "--extra", v2, "--dry-run"]) == 2
    print("== update: a card built before the record is hashed once, then updated")
    ok &= read_trees(out2) is None
    ok &= main(["update", "--card", out2, "--primary", A, "--extra", B, "--extra", C, "--selector-dir", sel,
                "--allow-version-mismatch"]) == 0
    rec2 = read_trees(out2)
    ok &= rec2 is not None and [im.sub for im in rec2.images] == ["", "img1", "img2"]
    print("== update (multi): reorder = renames and no bytes; remove; add")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["update", "--card", out2, "--primary", A, "--extra", C, "--extra", B, "--selector-dir", sel,
                   "--allow-version-mismatch", "--dry-run"])
    dry2 = buf.getvalue()
    ok &= rc == 0 and "update-size 0" in dry2 and "rename" in dry2 and "update-inject yes" in dry2
    ok &= main(["update", "--card", out2, "--primary", A, "--extra", C, "--extra", B, "--selector-dir", sel,
                "--allow-version-mismatch"]) == 0
    ref7 = fs_ref(out2, Geometry.from_file(out2).part(7)[1] * SECTOR)
    ok &= debugfs_cat(ref7, "/img1/C_title/game") == b"C p3 game\n"
    ok &= debugfs_cat(ref7, "/img2/B_title/game") == b"B p3 game\n"
    ok &= card_conf(out2)["images"][1][0] == "/dev/mmcblk0p7:img1"
    ok &= main(["update", "--card", out2, "--primary", A, "--extra", C, "--selector-dir", sel,
                "--allow-version-mismatch"]) == 0
    ok &= not debugfs_exists(ref7, "/img2") and [im.sub for im in read_trees(out2).images] == ["", "img1"]
    ok &= main(["update", "--card", out2, "--primary", A, "--extra", C, "--extra", B, "--selector-dir", sel,
                "--allow-version-mismatch"]) == 0
    ok &= debugfs_cat(ref7, "/img2/B_title/game") == b"B p3 game\n"
    ok &= verify_card(out2, verify_plan(out2, [A, C, B]), sel, mode="full")
    print("== grow: p7 gains room in place")
    before7 = Geometry.from_file(out2).part(7)[2]
    grow_last_partition(out2, before7 + 4096)
    ok &= Geometry.from_file(out2).part(7)[2] == before7 + 4096
    ok &= plan_from_card(out2).multi_part.count == before7 + 4096
    ok &= verify_card(out2, verify_plan(out2, [A, C, B]), sel, mode="quick")
    print("== the lock: a held lock refuses an update")
    holder = subprocess.Popen([sys.executable, "-c",
                               "import fcntl,os,sys,time; fd=os.open(sys.argv[1], os.O_RDWR|os.O_CREAT); "
                               "fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(30)",
                               out2 + LOCK_SUFFIX], stdout=subprocess.PIPE)
    holder.stdout.readline()
    try:
        ok &= lock_held(out2)
        ok &= main(["update", "--card", out2, "--primary", A, "--extra", C, "--extra", B, "--selector-dir", sel,
                    "--allow-version-mismatch"]) == 2
    finally:
        holder.kill()
        holder.wait()
    print("== the crash drill: a writer killed mid-file leaves a mounted loop and a dirty record; update repairs")
    child = subprocess.Popen([sys.executable, __file__, "selftest-crash", out2], stdout=subprocess.PIPE)
    line = child.stdout.readline().decode("utf-8", "replace").strip()
    ok &= line.startswith("mounted ")
    child.kill()
    child.wait()
    r = subprocess.run(["losetup", "-j", os.path.realpath(out2)], stdout=subprocess.PIPE)
    ok &= bool(parse_losetup_j(r.stdout.decode("utf-8", "replace")))
    ok &= read_trees(out2).dirty == [7]
    ok &= not verify_card(out2, verify_plan(out2, [A, C, B]), sel, mode="quick")
    ok &= main(["update", "--card", out2, "--primary", A, "--extra", C, "--extra", B, "--selector-dir", sel,
                "--allow-version-mismatch"]) == 0
    r = subprocess.run(["losetup", "-j", os.path.realpath(out2)], stdout=subprocess.PIPE)
    ok &= not parse_losetup_j(r.stdout.decode("utf-8", "replace"))
    ok &= read_trees(out2).dirty == []
    ok &= not any(ts.is_tmp(n) for n in [e[4] for e in debugfs_ls(ref7, "/img1/C_title")])
    ok &= verify_card(out2, verify_plan(out2, [A, C, B]), sel, mode="full")
    print("== a loop of the same file mounted by someone else is refused by name")
    _t, st7b, cnt7b = Geometry.from_file(out2).part(7)
    foreign = tempfile.mkdtemp(prefix="foreign_mnt_")
    loop = _run(["losetup", "--find", "--show", "-o", str(st7b * SECTOR), "--sizelimit", str(cnt7b * SECTOR),
                 out2]).strip()
    try:
        _run(["mount", "-t", "ext4", "-o", "ro", loop, foreign])
        try:
            rc = main(["update", "--card", out2, "--primary", A, "--extra", C, "--extra", B, "--selector-dir", sel,
                       "--allow-version-mismatch"])
            ok &= rc == 2
        finally:
            _run(["umount", foreign])
    finally:
        _run(["losetup", "-d", loop])
        os.rmdir(foreign)
    print("SELFTEST part 5 (update)", "PASS" if ok else "FAIL")

    # ------------------------------------------------- part 6: the store layout (item 95), root only
    print("== the store layout: one blob per unique (content, mode, owner); the primary adopted in place")
    _vp6, _sx6, ext4m, _adj6 = _stern_plugins()
    shared = os.path.join(d, "shared.bin")
    with open(shared, "wb") as f:
        f.write(bytes(range(256)) * 300)                      # 76800 bytes, the same in three trees
    only = os.path.join(d, "only.bin")
    with open(only, "wb") as f:
        f.write(b"C" * 40000)
    S = os.path.getsize(shared)

    def put(src, rel, stage, mode="0100644"):
        _t, st_, _c = Geometry.from_file(src).part(3)
        debugfs_write_script(fs_ref(src, st_ * SECTOR), ["write %s %s" % (dq(stage), rel),
                                                         "set_inode_field %s mode %s" % (rel, mode)])
        os.utime(src)
    put(A, "/A_title/shared.bin", shared)
    put(B, "/B_title/shared.bin", shared)                     # the same bytes at ANOTHER path
    put(C, "/C_title/other.bin", shared)                      # ...and another
    put(C, "/C_title/exec.bin", shared, "0100755")            # the same bytes, another mode: its own blob
    put(C, "/C_title/only.bin", only)
    out6 = os.path.join(d, "store3.img")
    ok &= main(["build", "--primary", A, "--extra", B, "--extra", C, "--out", out6, "--selector-dir", sel,
                "--layout", "store", "--size", "content", "--allow-version-mismatch", "--bypass-validation",
                "--force"]) == 0
    G6 = Geometry.from_file(out6)
    _t3, s3, c3 = G6.part(3)
    ok &= c3 > Geometry.from_file(A).part(3)[2] and len(G6.logical) == 2
    plan6 = plan_from_card(out6)
    ok &= plan6.layout == "store" and plan6.store_subdirs == ["img1", "img2"]
    ok &= plan6.devices() == ["/dev/mmcblk0p3", "/dev/mmcblk0p3:img1", "/dev/mmcblk0p3:img2"]
    ok &= [(p.num, p.start, p.count) for p in plan6.logs] == [(5 + i, st_, cnt_) for i, (_e, _t, st_, cnt_) in enumerate(G6.logical)]
    ok &= card_conf(out6)["images"][2][0] == "/dev/mmcblk0p3:img2"

    def card_inos(sub):
        with open(out6, "rb") as f:
            r = ext4m.Ext4Reader(f, s3 * SECTOR, c3 * SECTOR)
            root = tree_root_inode(r, sub)
            return {rel: (ino, node["links"]) for rel, kind, ino, node in r.iter_tree(root, skip=tree_skip(plan6, sub))}
    i0, i1, i2 = card_inos(None), card_inos("img1"), card_inos("img2")
    ok &= i0["A_title/shared.bin"] == i1["B_title/shared.bin"] == i2["C_title/other.bin"], (i0.get("A_title/shared.bin"), i1.get("B_title/shared.bin"), i2.get("C_title/other.bin"))
    ok &= i0["A_title/shared.bin"][1] == 4                    # three trees + the store's own name
    ok &= i2["C_title/exec.bin"][0] != i0["A_title/shared.bin"][0] and i2["C_title/exec.bin"][1] == 2
    with open(A, "rb") as f:                                  # the primary's inode numbers are the source's
        _t, sa, ca = Geometry.from_file(A).part(3)
        ra = ext4m.Ext4Reader(f, sa * SECTOR, ca * SECTOR)
        src_inos = {rel: ino for rel, kind, ino, _n in ra.iter_tree(2)}
    ok &= {rel: ino for rel, (ino, _l) in i0.items()} == src_inos
    rec6 = read_trees(out6)
    ok &= rec6 is not None and rec6.layout == "store" and rec6.synced == [3] and rec6.dirty == []
    print("== verify holds the store to its invariants (full)")
    ok &= verify_card(out6, verify_plan(out6, [A, B, C]), sel, mode="full")
    print("== plan prints unique bytes per image and the shared row; the rows add up")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_plan(make_plan(A, [B, C], "store", size_class="content"))
    lines = buf.getvalue().splitlines()
    shared_row = [ln for ln in lines if ln.startswith("image-size shared ")]
    # the shared bytes by the same arithmetic on the sources: at least the two copies of
    # shared.bin's content (the synthetic cards share a little more, their .sidx stubs)
    _uq, want_shared = ts.dedup_costs([source_tree(x)[0] for x in (A, B, C)])
    ok &= want_shared >= 2 * S
    ok &= len(shared_row) == 1 and int(shared_row[0].split()[2]) == want_shared, (shared_row, want_shared)
    rows = [int(ln.split()[3]) for ln in lines if ln.startswith("image-size ") and ln.split()[1].isdigit()]
    free_row = [int(ln.split()[2]) for ln in lines if ln.startswith("image-size free ")]
    over = [int(ln.split()[2]) for ln in lines if ln.startswith("image-size overhead ")]
    total6 = [int(ln.split()[4]) for ln in lines if ln.startswith("image: ")]
    ok &= sum(rows) + free_row[0] + over[0] == total6[0], (rows, free_row, over, total6)
    rep6 = inspect_card(out6)
    ok &= rep6["layout"] == "store" and rep6["trees"]["layout"] == "store"
    ok &= rep6["trees"]["store"]["shared_bytes"] == want_shared, (rep6["trees"]["store"], want_shared)
    ok &= [im["title_dir"] for im in rep6["images"]] == ["A_title", "B_title", "C_title"]
    print("== parts.py --list-games lists the store's trees under p3")
    parts_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parts.py")
    r = subprocess.run([sys.executable, parts_py, "--list-games", out6], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    rows6 = [ln.split() for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    ok &= r.returncode == 0 and [(rw[0], rw[3], rw[4] if len(rw) > 4 else None) for rw in rows6] == [
        ("3", "A_title", None), ("3", "B_title", "img1"), ("3", "C_title", "img2")], rows6
    print("== update on a store card: a new unique file writes once; a file the store holds writes nothing")
    ref3 = fs_ref(out6, s3 * SECTOR)
    ok &= main(["update", "--card", out6, "--selector-dir", sel, "--allow-version-mismatch", "--dry-run"]) == 0
    put(C, "/C_title/new.bin", stage_new)                     # 70000 new bytes
    put(B, "/B_title/again.bin", shared)                      # bytes the store already holds
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["update", "--card", out6, "--selector-dir", sel, "--allow-version-mismatch", "--dry-run"])
    dry6 = buf.getvalue()
    print(dry6)
    ok &= rc == 0 and "update-size 70000" in dry6 and "update-fits YES" in dry6
    rows_f = [ln.split() for ln in dry6.splitlines() if ln.startswith("update-files ")]
    ok &= any(rw[1] == "1" and rw[3] == "1" and rw[4] == "0" for rw in rows_f), rows_f
    ok &= any(rw[1] == "2" and rw[3] == "1" and rw[4] == "70000" for rw in rows_f), rows_f
    ok &= main(["update", "--card", out6, "--selector-dir", sel, "--allow-version-mismatch"]) == 0
    ok &= debugfs_cat(ref3, "/img2/C_title/new.bin") == b"N" * 70000
    i1 = card_inos("img1")
    ok &= i1["B_title/again.bin"] == i1["B_title/shared.bin"] and i1["B_title/again.bin"][1] == 5
    ok &= verify_card(out6, verify_plan(out6, [A, B, C]), sel, mode="full")
    print("== update on a store card: reorder = renames; remove = its blobs go; add = only its own bytes")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["update", "--card", out6, "--primary", A, "--extra", C, "--extra", B, "--selector-dir", sel,
                   "--allow-version-mismatch", "--dry-run"])
    dry6b = buf.getvalue()
    ok &= rc == 0 and "update-size 0" in dry6b and "rename" in dry6b and "update-inject yes" in dry6b
    ok &= main(["update", "--card", out6, "--primary", A, "--extra", C, "--extra", B, "--selector-dir", sel,
                "--allow-version-mismatch"]) == 0
    ok &= debugfs_cat(ref3, "/img1/C_title/game") == b"C p3 game\n" and debugfs_cat(ref3, "/img2/B_title/game") == b"B p3 game\n"
    ok &= card_conf(out6)["images"][1][0] == "/dev/mmcblk0p3:img1"
    ok &= verify_card(out6, verify_plan(out6, [A, C, B]), sel, mode="full")
    n_blobs = len([e for e in debugfs_ls(ref3, "/.blobs") if e[4] not in (".", "..")])
    ok &= main(["update", "--card", out6, "--primary", A, "--extra", C, "--selector-dir", sel,
                "--allow-version-mismatch"]) == 0
    ok &= not debugfs_exists(ref3, "/img2")
    n_after = len([e for e in debugfs_ls(ref3, "/.blobs") if e[4] not in (".", "..")])
    ok &= n_after < n_blobs, (n_blobs, n_after)                # B's own blobs were collected
    ok &= verify_card(out6, verify_plan(out6, [A, C]), sel, mode="full")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["update", "--card", out6, "--primary", A, "--extra", C, "--extra", B, "--selector-dir", sel,
                   "--allow-version-mismatch", "--dry-run"])
    dry6c = buf.getvalue()
    size_c = [int(ln.split()[1]) for ln in dry6c.splitlines() if ln.startswith("update-size ")]
    b_bytes = read_trees(out6) and sum(fr.size for fr in source_tree(B)[0].tree.files.values())
    ok &= rc == 0 and 0 < size_c[0] < b_bytes, (size_c, b_bytes)    # B's shared bytes are linked, not written
    ok &= main(["update", "--card", out6, "--primary", A, "--extra", C, "--extra", B, "--selector-dir", sel,
                "--allow-version-mismatch"]) == 0
    ok &= debugfs_cat(ref3, "/img2/B_title/game") == b"B p3 game\n"
    ok &= verify_card(out6, verify_plan(out6, [A, C, B]), sel, mode="full")
    print("== update on a store card: the primary's own tree changes -> synced in place, still a link")
    put(A, "/A_title/newa.bin", only)
    ok &= main(["update", "--card", out6, "--selector-dir", sel, "--allow-version-mismatch"]) == 0
    i0, i1 = card_inos(None), card_inos("img1")               # img1 is C now: newa.bin is its only.bin's blob
    ok &= debugfs_cat(ref3, "/A_title/newa.bin") == b"C" * 40000
    ok &= i0["A_title/newa.bin"] == i1["C_title/only.bin"] and i0["A_title/newa.bin"][1] == 3
    ok &= verify_card(out6, verify_plan(out6, [A, C, B]), sel, mode="full")
    print("== a raw bypass of a store card is refused")
    ok &= main(["bypass", "--card", out6, "--dry-run"]) == 2
    print("SELFTEST part 6 (store)", "PASS" if ok else "FAIL")
    print("SELFTEST", "PASS" if ok else "FAIL")
    return bool(ok)


def selftest_crash(card):
    """The crash drill's child: take the dirty flag and a mounted loop of p7, start a slow write,
    say so, and wait to be killed."""
    rec = read_trees(card)
    rec.dirty = [7]
    write_trees(card, rec)
    _t, st, cnt = Geometry.from_file(card).part(7)
    lm = LoopMount(card, st * SECTOR, cnt * SECTOR)
    mp = lm.__enter__()
    tmp = os.path.join(mp, "img1", "C_title", "big.bin" + TMP_MARK_CHILD)
    with open(tmp, "wb") as f:
        print("mounted %s" % mp, flush=True)
        while True:
            f.write(b"x" * 4096)
            f.flush()
            time.sleep(0.05)


# ============================================================================= CLI
def _add_images(s, out_flag, reach_flag=True, layout_flag=True):
    s.add_argument("--primary", required=True, help="the image whose p1/p2/p3/p5/p6 the card gets (index 0)")
    s.add_argument("--extra", action="append", default=[], metavar="IMG",
                   help="an extra image (its games partition becomes p7 [parts layout] or p7/imgN [multi layout])")
    if out_flag:
        s.add_argument(out_flag, required=True, help="the multi-image card image")
    if layout_flag:
        s.add_argument("--layout", choices=LAYOUTS, default="auto",
                       help="parts = one extra as p7 verbatim; multi = every extra as a tree inside one ext4 p7; "
                            "auto = parts for one extra, multi for two or more; store = EXPERIMENTAL, opt-in "
                            "(item 95): the primary's p3 grown to hold every extra as img1/, img2/ ... and one "
                            "store of the files the images share (root only; never USB-update such a card)")
    if reach_flag:
        _add_reach_flag(s)


def _add_reach_flag(s):
    s.add_argument("--allow-unreachable", action="store_true",
                   help="accept a parts layout with an image past p7 (the machine's kernel exposes p1..p7 only; "
                        "the emulator can still run it)")


def _add_conf_flags(s):
    s.add_argument("--selector-dir", help="directory holding codeselect (ARM binary), select.sh and optionally font.ttf")
    s.add_argument("--media-dir", help="directory holding media.json (selectmedia.py prepare) and the art/anim/sound files it names")
    s.add_argument("--titles", help="';'-separated titles, one per image (index order)")
    s.add_argument("--subtitles", help="';'-separated subtitles, one per image")
    s.add_argument("--timeout", type=int, help="images.conf timeout in seconds (default 15; 0 = wait for ever)")
    s.add_argument("--default", type=int, help="images.conf default index (default 0)")
    s.add_argument("--volume", type=int, help="images.conf volume 0-100 (software mix gain; overrides media.json)")
    s.add_argument("--mixer-volume", type=int, help="images.conf mixer_volume 0-63 (the game's codec curve on selem PCM; only when set)")
    s.add_argument("--machine-volume", action="store_true",
                   help="images.conf volume=machine: the menu plays at the machine's own MASTER VOLUME SETTING, "
                        "read off the card's /data/nv mirror (the default image's title names the store and the "
                        "factory level for a machine with no store yet); --volume is then only the preview's")
    s.add_argument("--theme", help="the menu's colours: one of codeselect/themes.json's names, or custom "
                                   "(the default theme plus --color overrides); an existing card's is kept when absent")
    s.add_argument("--color", action="append", metavar="ROLE=RRGGBB",
                   help="one colour on top of the theme (repeatable; the roles are in themes.json)")
    s.add_argument("--conf", help="use this images.conf verbatim instead of generating one")
    s.add_argument("--debug-log", action="store_true",
                   help="DEVELOPMENT ONLY: images.conf log=%s - the selector writes its diagnostics to the card "
                        "(a fresh file each boot, the previous boot's kept as .1, 1 MiB at most). Without it the "
                        "menu writes nothing to /dump; an inject without it turns a card's log off again" % CARD_LOG)


def _bypass_after_build(card, plan):
    print("== validator bypass")
    return bypass_card(card, plan)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan", help="print the layout + byte totals; writes nothing")
    _add_images(s, None)
    s.add_argument("--size", choices=list(STORE_SIZES), help="as for build (the store layout is sized by it)")
    s.add_argument("--cache-dir", help="where hashed source manifests are kept (the store layout hashes to plan)")
    s = sub.add_parser("check-stock", help="regenerate a stock card's tables with this writer and byte-compare")
    s.add_argument("image")
    s = sub.add_parser("build", help="write the sparse multi card and inject the selector into p2")
    _add_images(s, "--out")
    _add_conf_flags(s)
    s.add_argument("--size", choices=list(STORE_SIZES), help="fill the multi layout's p7 - or the store layout's "
                   "p3 - to the end of this Stern image size (room for later updates and images without a "
                   "re-layout); default: content-sized for multi, the smallest class that fits for store "
                   "('content' = just the content plus a small headroom)")
    s.add_argument("--cache-dir", help="where hashed source manifests are kept (default: the Windows TEMP "
                   "directory's %s seen from WSL, or $MULTIBOOT_CACHE)" % CACHE_DIRNAME_HINT)
    s.add_argument("--bypass-validation", action="store_true",
                   help="neuter Stern's game validator in EVERY games tree on the output card (+ refresh its .sidx record)")
    s.add_argument("--allow-version-mismatch", action="store_true",
                   help="build a card whose images are NOT the same game code - a different game code version, "
                        "a different title, or a different node board firmware set. Read the refusal first: it "
                        "says what each of those costs")
    s.add_argument("--no-inject", action="store_true", help="only copy + tables; leave p2 stock")
    s.add_argument("--dd", action="store_true", help="copy the ranges with dd bs=16M conv=sparse instead of python")
    s.add_argument("--force", action="store_true", help="overwrite an existing --out")
    s.add_argument("--workdir", help="scratch directory for the p2 extract and the multi layout's tree + p7 image (default: beside --out)")
    s = sub.add_parser("inject", help="redo only the p2 injection on an existing multi card (idempotent)")
    s.add_argument("--card", required=True, help="the multi card to modify IN PLACE")
    _add_conf_flags(s)
    s.add_argument("--primary", help="RECORD this path as image 0's source in build.json; nothing is read "
                                     "from it (without it the card's own build.json is carried through)")
    s.add_argument("--extra", action="append", default=[], metavar="IMG",
                   help="RECORD this path as the next image's source in build.json (repeatable); nothing is read from it")
    _add_reach_flag(s)
    s = sub.add_parser("inspect", help="read a finished card back: table, menu, provenance, media, validator state")
    s.add_argument("--card", required=True, help="the card to read (READ-ONLY; nothing is written to it)")
    s.add_argument("--json", action="store_true", dest="as_json",
                   help="print ONE JSON object on stdout instead of the table (the GUI's 'Load card' reads it)")
    s.add_argument("--media-out", help="also extract the card's media directory + media.json into this directory "
                                       "(give it a per-card scratch directory: nothing there is deleted)")
    s = sub.add_parser("bypass", help="apply the validator bypass to every games tree on an existing card (in place)")
    s.add_argument("--card", required=True, help="the card to modify IN PLACE")
    s.add_argument("--dry-run", action="store_true", help="report every tree's state; write nothing")
    s = sub.add_parser("verify", help="check an existing multi card against its sources")
    s.add_argument("--card", required=True)
    _add_images(s, None, reach_flag=False, layout_flag=False)
    s.add_argument("--selector-dir", help="also compare the injected files against this directory")
    s.add_argument("--media-dir", help="also compare the media files against this directory")
    s.add_argument("--quick", action="store_true",
                   help="re-hash a sample of each recorded tree (plus its game and .sidx) instead of every file")
    s = sub.add_parser("update", help="write ONLY what changed since the card was built - in place, in about a "
                                      "minute (root: a loop mount of the card's partitions)")
    s.add_argument("--card", required=True, help="the multi card to update IN PLACE")
    s.add_argument("--primary", help="image 0's source (default: what the card's build.json recorded)")
    s.add_argument("--extra", action="append", default=[], metavar="IMG",
                   help="the extra images in their new order (default: what build.json recorded)")
    _add_conf_flags(s)
    s.add_argument("--bypass-validation", action="store_true",
                   help="neuter Stern's validator in every tree whose game changed (the others keep their state)")
    s.add_argument("--restore-validation", action="store_true",
                   help="put the SOURCE's own game and .sidx back on every tree this tool bypassed, so the validator "
                        "runs again (item 98: a bypassed image never re-grades, so a GAME VALIDATION ERROR an earlier "
                        "card left in the machine's NVRAM stays latched; a pristine image re-grades P and clears it, "
                        "and Insider Connected sees a genuine game); the other trees keep their state")
    s.add_argument("--allow-version-mismatch", action="store_true", help="as for build")
    s.add_argument("--dry-run", action="store_true", help="say what an update would write; write nothing")
    s.add_argument("--expect-bytes", type=int,
                   help="refuse when the update would write more than this (x1.1 + 64 MiB): the number a dialog "
                        "showed before the press")
    s.add_argument("--cache-dir", help="where hashed manifests are kept (see build)")
    s.add_argument("--workdir", help="scratch directory (default: beside --card)")
    s.add_argument("--no-verify", action="store_true", help="skip the verify pass after the update")
    s = sub.add_parser("selftest", help="synthetic end-to-end test (needs debugfs/mke2fs/e2fsck/sfdisk/fdisk)")
    s.add_argument("dir")
    s.add_argument("--selector", help="any small file to stand in for the codeselect binary")
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if argv and argv[0] == "selftest-crash":          # the selftest's own child, not a subcommand
        selftest_crash(argv[1])
        return 0
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            meter = None
            if resolve_layout(a.layout, len(a.extra)) == "store":
                # the store plan HASHES every image (the first time; the cache answers after):
                # the meter's lines are what the app's size strip shows meanwhile
                PROGRESS.start(measure_total([a.primary] + list(a.extra)), "measuring")
                meter = PROGRESS
            plan = make_plan(a.primary, a.extra, a.layout, size_class=a.size, cache_dir=a.cache_dir,
                             progress=meter)
            if meter is not None:
                meter.finish()
            print_plan(plan)
            check_reachable(plan, a.allow_unreachable)
            recs = plan_identities(plan, progress=None)
            try:                                 # plan writes nothing, so it reports and does
                report_versions(recs)            # not refuse - but it says what build will do
            except Refused as e:
                print("\n== build will REFUSE this card\n%s" % e)
        elif a.cmd == "check-stock":
            return 0 if check_stock(a.image) else 1
        elif a.cmd == "build":
            check_output_path(a.out, [a.primary] + a.extra + [a.conf, a.selector_dir, a.media_dir], force=a.force)
            if not a.no_inject and not a.selector_dir:
                raise Refused("build needs --selector-dir (or --no-inject)")
            plan = make_plan(a.primary, a.extra, a.layout, size_class=a.size, cache_dir=a.cache_dir)
            print_plan(plan)
            check_reachable(plan, a.allow_unreachable)       # before a byte is written
            if plan.layout == "store":
                ok, why = loop_available()
                if not ok:
                    raise Refused("--layout store grows the primary's games partition and writes the store through "
                                  "a loop mount; it cannot here: %s" % why)
                if a.no_inject:
                    raise Refused("--layout store needs its record on the card: drop --no-inject")
                need_tools("resize2fs")
            if not a.extra:
                say("WARNING: no --extra given; building a one-image card")
            versions = plan_identities(plan)                 # read off the SOURCE images...
            report_versions(versions, a.allow_version_mismatch)  # ...and refuse before --out exists
            workdir = a.workdir or os.path.dirname(os.path.abspath(a.out))
            os.makedirs(workdir, exist_ok=True)
            conf = media = manifests = None
            trees = None
            if not a.no_inject:
                if a.media_dir:
                    media = plan_media(a.media_dir, len(plan.trees))
                    for name in media["files"]:
                        say("media %s: %s" % (name, media["kinds"][name]))
                    say("media: %d files, %s" % (len(media["files"]), _gb(media["total"])))
                conf = conf_for_plan(plan, a, media=media)          # generated (and validated) before the long copy
                manifests = selector_manifests(plan, conf, a.media_dir, [a.primary] + list(a.extra),
                                               versions=versions)
                stage_selector(a.selector_dir, tempfile.mkdtemp(prefix="mkmulticard.chk."), conf, hook_game_script(SYNTH_GAME),
                               media["files"] if media else None, manifests)
                print("== images.conf to inject\n" + conf.rstrip())
                print("== %s\n%s" % (BUILD_MANIFEST, manifests[BUILD_MANIFEST].rstrip()))
            if a.bypass_validation:
                _stern_plugins()                                  # refuse up front, not after the copy
            for x, g in zip(plan.extras, plan.extra_geoms):
                t2, s2, c2 = g.part(2)
                same = md5_range(x, s2 * SECTOR, c2 * SECTOR) == md5_range(plan.primary, plan.prims[1].src_start * SECTOR, plan.prims[1].count * SECTOR)
                say("extra %s rootfs (p2) == primary rootfs: %s" % (os.path.basename(x), "YES" if same else
                    "NO - only its games partition is carried; its rootfs changes are NOT on this card"))
            t0 = time.monotonic()
            tmp = None
            # THE RECORD (item 93): every source's tree hashed (or taken from the cache) before
            # the copy, so the card can say what is on it and a later update knows what moved.
            if not a.no_inject:
                trees = record_sources(plan, a.cache_dir)
            # THE METER STARTS HERE - the last moment before anything long happens and the
            # first at which every number it needs is known.  Everything above this line
            # refuses in seconds; everything below is the hour the GUI had nothing to show for.
            PROGRESS.start(build_work_bytes(plan), "preparing")
            try:
                if plan.layout == "multi":
                    p7img, tmp = build_multi_partition(plan, workdir)
                    plan = plan.with_multi_src(p7img)
                build_image(plan, a.out, use_dd=a.dd)
            finally:
                if tmp:
                    shutil.rmtree(tmp, ignore_errors=True)
            say("copy + tables took %.0f s" % (time.monotonic() - t0))
            drop_stale_sidecars(a.out, keep=())
            if plan.layout == "store":
                build_store(plan, a.out, trees)
                if a.bypass_validation:
                    bypass_store(a.out, plan, trees)
                trees.synced = [3]                       # written in place: held to the record, never a range md5
            if plan.layout == "multi":
                say("p%d md5 %s recorded in %s" % (plan.multi_part.num, write_part_sidecar(a.out, plan.multi_part.num),
                                                  sidecar_path(a.out, plan.multi_part.num)))
            if not a.no_inject:
                t1 = time.monotonic()
                PROGRESS.step("writing the menu into the card")
                manifests = selector_manifests(plan, conf, a.media_dir, [a.primary] + list(a.extra),
                                               versions=versions, trees=trees)
                inject_card(a.out, a.selector_dir, conf, workdir=workdir, media_files=media["files"] if media else None,
                            replace_media=bool(a.media_dir), manifests=manifests)
                say("injection took %.0f s" % (time.monotonic() - t1))
            else:
                # stock p2, still recorded: verify then has something to hold p2 against
                say("p2 md5 %s recorded in %s" % (write_p2_sidecar(a.out), p2_sidecar_path(a.out)))
            if a.bypass_validation and plan.layout != "store":
                _bypass_after_build(a.out, plan)
            PROGRESS.finish()
            alloc = allocated_bytes(a.out)
            say("wrote %s: %d bytes apparent%s in %.0f s" % (a.out, plan.total_bytes,
                (", %s allocated" % _gb(alloc)) if alloc is not None else "", time.monotonic() - t0))
            if conf:
                print(conf.rstrip())
        elif a.cmd == "inject":
            check_output_path(a.card, [a.conf, a.selector_dir, a.media_dir, a.primary] + list(a.extra), must_exist=True)
            if not a.selector_dir:
                raise Refused("inject needs --selector-dir")
            plan = plan_from_card(a.card)
            if len(plan.trees) < 2:
                say("WARNING: %s holds no extra images (p7...); injecting a one-image selector" % a.card)
            check_reachable(plan, a.allow_unreachable)       # an images.conf naming p8 is one the machine cannot honour
            media = None
            if a.media_dir:
                media = plan_media(a.media_dir, len(plan.trees))
                for name in media["files"]:
                    say("media %s: %s" % (name, media["kinds"][name]))
            # read the card's own sidecars BEFORE touching it: an inject that is given no source
            # paths carries the old provenance through, and one without --media-dir carries the
            # card's media.json through byte for byte
            ref = select_ref(a.card)
            warns = []
            old_build = parse_manifest(read_select_file(ref, BUILD_MANIFEST), BUILD_MANIFEST, warns)
            old_media = None if a.media_dir else read_select_file(ref, MEDIA_MANIFEST)
            old_trees = read_select_file(ref, TREES_MANIFEST)
            refuse_if_dirty(a.card, ref)
            for w in warns:
                say("WARNING: " + w)
            conf = conf_for_plan(plan, a, existing=card_conf(a.card, ref), media=media)
            sources = [a.primary] + list(a.extra) if (a.primary or a.extra) else None
            manifests = selector_manifests(plan, conf, a.media_dir, sources, old_build, old_media,
                                           existing_trees=old_trees)
            say("%s: %s; %s: %s" % (
                BUILD_MANIFEST,
                "sources given" if sources else ("sources carried through from the card" if old_build
                                                 else "no sources known (pass --primary/--extra to record them)"),
                MEDIA_MANIFEST,
                "from --media-dir" if a.media_dir else ("carried through (%d bytes)" % len(old_media) if old_media
                                                        else "absent")))
            print("== images.conf to inject\n" + conf.rstrip())
            print("== %s\n%s" % (BUILD_MANIFEST, manifests[BUILD_MANIFEST].rstrip()))
            written = inject_card(a.card, a.selector_dir, conf, workdir=os.path.dirname(os.path.abspath(a.card)),
                                  media_files=media["files"] if media else None, replace_media=bool(a.media_dir),
                                  manifests=manifests)
            say("injected into %s: %s" % (a.card, ", ".join(written)))
        elif a.cmd == "inspect":
            if not os.path.isfile(a.card):
                raise Refused("%s does not exist" % a.card)
            rep = inspect_card(a.card, a.media_out)
            if a.as_json:
                json.dump(rep, sys.stdout, indent=1)
                sys.stdout.write("\n")
            else:
                print_inspect(rep)
        elif a.cmd == "bypass":
            check_output_path(a.card, [], must_exist=True)
            plan = plan_from_card(a.card)
            print("layout: %s; trees: %s" % (plan.layout, ", ".join(plan.devices())))
            if plan.layout == "store":
                raise Refused("a store card's trees share their files: the bypass is applied through the mount by "
                              "build --bypass-validation and by update, never by a raw write")
            states = bypass_card(a.card, plan, dry_run=a.dry_run)
            bad = [i for i, st in states.items() if st not in ("bypassed", "absent")]
            if bad:
                print("[card] %d tree(s) NOT bypassed: %s" % (len(bad), ", ".join("image %d (%s)" % (i, states[i]) for i in bad)))
                return 1
        elif a.cmd == "update":
            return update_card(a)
        elif a.cmd == "verify":
            subs = multi_subdirs_on(a.card, 7)
            subs3 = store_subdirs_on(a.card)
            if subs3 and len(Geometry.from_file(a.card).logical) == 2:
                if a.extra and len(a.extra) != len(subs3):
                    raise Refused("%s holds %d trees in its store (%s) but %d --extra were given"
                                  % (a.card, len(subs3), "/".join(subs3), len(a.extra)))
                plan = make_plan(a.primary, a.extra, "store", store_sectors=Geometry.from_file(a.card).part(3)[2],
                                 multi_subdirs=subs3)
            elif subs:
                # the multi layout: p7's size and subdirectories as the build chose them, off the card
                if a.extra and len(a.extra) != len(subs):
                    raise Refused("%s holds %d trees in p7 (%s) but %d --extra were given" % (a.card, len(subs), "/".join(subs), len(a.extra)))
                plan = make_plan(a.primary, a.extra, "multi", multi_sectors=Geometry.from_file(a.card).part(7)[2],
                                 multi_subdirs=subs)
            else:
                plan = make_plan(a.primary, a.extra, "parts")
            return 0 if verify_card(a.card, plan, a.selector_dir, a.media_dir,
                                    mode="quick" if a.quick else "full") else 1
        elif a.cmd == "selftest":
            return 0 if selftest(a.dir, a.selector) else 1
    except Refused as e:
        print("[card] error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
