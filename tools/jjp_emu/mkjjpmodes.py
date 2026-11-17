#!/usr/bin/env python3
"""mkjjpmodes.py - a JJP install ISO in, the same ISO with custom modes out (PAD-1337).

The JJP mode SDK runs custom modes inside a retail JJP game from outside its
binary (jjpmodes.c, MODES.md).  On the rig run_game.sh preloads it.  On a real
machine nothing preloads anything, so this writes an install ISO whose root
carries the SDK and one guarded line in scripts/rungame.sh that loads it:

  /jjpe/gen1/padmodes/jjpmodes.so      the runtime (built by buildmods.sh)
  /jjpe/gen1/padmodes/modes/           title.cfg + *.mode + the modes' own sound,
                                       picture and video files, as given
  /jjpe/gen1/padmodes/build.json       what was written, with sha256s
  /jjpe/gen1/scripts/padmodes.sh       exports LD_PRELOAD + JJP_MODS_DIR
  /jjpe/gen1/scripts/rungame.sh        + MODES_HOOK_LINES after runonce.sh

and nothing else changes.  JJP's own installer restores sda3 into BOTH root
slots, so only the sda3 pieces are replaced: no installer or boot-config edit
(unlike mkjjpmulti.py, whose building blocks this reuses).  The installer only
gunzip-tests the pieces, so the ISO installs as a stock one does.  A multi-boot
ISO in gives a multi-boot ISO out with modes in root A; title.cfg's `game` key
keeps them out of image 1's game.

Turning the modes off on a machine without reinstalling: create
/jjpe/perm/padmodes.off (padmodes.sh checks for it).

    mkjjpmodes.py check --modes DIR [--port PORT.json]
    mkjjpmodes.py code --modes DIR [--all]     (the modes' own C++ -> <name>.so; needs g++, root installs it)
    mkjjpmodes.py build --iso IN.iso --modes DIR --out OUT.iso [--port P.json] [--so jjpmodes.so]   (root, WSL)
        (no --so: the runtime is built from jjpmodes.c against the ISO's own glibc)
    mkjjpmodes.py inspect --iso OUT.iso
"""
import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TOOL = "mkjjpmodes"
VERSION = "1"
JJPEDIR = "/jjpe/gen1"
PADMODES_DIR = JJPEDIR + "/padmodes"
MODES_HOOK = JJPEDIR + "/scripts/padmodes.sh"
RUNGAME = JJPEDIR + "/scripts/rungame.sh"
RUNONCE_LINE = "$JJPEDIR/scripts/runonce.sh"
ISO_MODES_DIR = "/jjp/padmodes"
OFF_SWITCH = "/jjpe/perm/padmodes.off"
SO_DEFAULT = "/var/tmp/jjpmodes.so"
#: the image's glibc, where the runtime is linked against it (buildmods.sh JJP_MODS_LIBDIR)
ROOT_LIBDIR = "/lib/x86_64-linux-gnu"
MODES_HOOK_MARK = "# PAD custom modes:"
MODES_HOOK_LINES = [
    "",
    MODES_HOOK_MARK + " the JJP mode SDK and its modes (padmodes.sh)",
    "[ -r $JJPEDIR/scripts/padmodes.sh ] && . $JJPEDIR/scripts/padmodes.sh",
]

PADMODES_SH = """#!/bin/sh
# PAD custom modes (PAD-1337).  Sourced by rungame.sh after runonce.sh, so the
# exports below reach ./game.  Loads the JJP mode SDK runtime with the modes in
# $JJPEDIR/padmodes/modes.  To turn the modes off without reinstalling, create
# %(off)s.
if [ -r $JJPEDIR/padmodes/jjpmodes.so ] && [ ! -e %(off)s ]; then
    export LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD }$JJPEDIR/padmodes/jjpmodes.so"
    export JJP_MODS_DIR=$JJPEDIR/padmodes/modes
    echo "PAD custom modes: $(ls $JJPEDIR/padmodes/modes | grep -c '\\.mode$') mode(s), $(ls $JJPEDIR/padmodes/modes | grep -c '\\.stock$') changed game mode(s) loaded"
fi
""" % {"off": OFF_SWITCH}


class Refused(Exception):
    pass


# ============================================================================= USB stick
# A mode stick (PAD-1349): modes onto a machine with no reinstall.  The game's
# service menu Update USB screen has a hot fix: on that screen Plus, Minus, Plus,
# Minus asks "Press ENTER to apply HOTFIX", two ENTERs run scripts/hotfix.sh,
# and that runs /mnt/usb/hotfix/runme.sh with /bin/dash (as the game, root)
# and reboots.  Nothing is verified, and nothing outside what runme.sh writes
# changes: scores and settings in /jjpe/perm stay as they are.  The same stick
# turns the modes off, on, or takes them out again.
STICK_ACTIONS = ("install", "off", "on", "remove")
STICK_DIR = "hotfix"
STICK_LOG = "padmodes_install.log"
RUNME_SH = r"""#!/bin/dash
# PAD custom modes stick (mkjjpmodes.py stick, PAD-1349), written @WRITTEN@.
# Run by the game's own scripts/hotfix.sh from the service menu's Update USB
# screen (Plus, Minus, Plus, Minus, then ENTER twice); the game reboots after.
# Scores and settings in /jjpe/perm are never touched (only @OFF@).
ACTION=@ACTION@
GAME=@GAME@
SRC=$(dirname "$0")
STICK=$(dirname "$SRC")
J=${JJPEDIR:-/jjpe/gen1}
OFF=${PAD_STICK_OFF:-@OFF@}            # the two overrides are for tests only
LOG=${PAD_STICK_LOG:-/jjpe/temp/@LOG@}
MARK='@MARK@'
ANCHOR='@ANCHOR@'
say() {
    echo "$(date '+%F %T') $*" >> "$LOG"
    echo "$(date '+%F %T') $*" >> "$STICK/@LOG@" 2>/dev/null
}
fail() { say "FAILED: $*"; exit 1; }
say "PAD custom modes stick: $ACTION${GAME:+ for $GAME} on $J"
if [ -n "$GAME" ] && [ ! -e "$J/$GAME/game" ]; then
    fail "this stick is for $GAME, and this machine has no $J/$GAME/game - nothing changed"
fi
unhook() {
    # rungame.sh without the hook lines (mkjjpmodes.strip_modes_hook)
    awk -v m="$MARK" '
        index($0, m) == 1 { h = 0; s = 1; next }
        s { s = 0; next }
        { if (h) print ""; h = 0 }
        $0 == "" { h = 1; next }
        { print }
        END { if (h) print "" }' "$J/scripts/rungame.sh" > "$J/scripts/rungame.sh.pad" || return 1
    cat "$J/scripts/rungame.sh.pad" > "$J/scripts/rungame.sh" && rm -f "$J/scripts/rungame.sh.pad"
}
case "$ACTION" in
off)
    mkdir -p "$(dirname "$OFF")" && touch "$OFF" || fail "could not create $OFF"
    sync; say "modes OFF ($OFF created); a stick with 'on' turns them back on"
    ;;
on)
    rm -f "$OFF"; sync; say "modes ON ($OFF removed)"
    ;;
remove)
    if grep -q "^$MARK" "$J/scripts/rungame.sh"; then unhook || fail "could not edit rungame.sh"; fi
    rm -rf "$J/padmodes" "$J/scripts/padmodes.sh"
    sync; say "modes REMOVED: $J/padmodes gone, rungame.sh as shipped"
    ;;
install)
    [ -r "$SRC/padmodes/jjpmodes.so" ] || fail "no padmodes/jjpmodes.so on the stick"
    ( cd "$SRC" && sha256sum -c --quiet padmodes.sha256 ) >> "$LOG" 2>&1 \
        || fail "a file on the stick does not match what was written (copy it again)"
    if ! grep -q "^$MARK" "$J/scripts/rungame.sh"; then
        n=$(awk -v a="$ANCHOR" '{ t = $0; gsub(/^[ \t]+|[ \t]+$/, "", t) } t == a { n++ } END { print n + 0 }' "$J/scripts/rungame.sh")
        [ "$n" = 1 ] || fail "rungame.sh has $n '$ANCHOR' lines, not 1 - not edited, nothing changed"
    fi
    rm -rf "$J/padmodes.new" && mkdir -p "$J/padmodes.new" \
        && cp -r "$SRC/padmodes/." "$J/padmodes.new/" || fail "could not copy the modes"
    chown -R 0:0 "$J/padmodes.new"; chmod 0755 "$J/padmodes.new/jjpmodes.so"
    chmod 0644 "$J/padmodes.new/modes/"* "$J/padmodes.new/build.json"
    rm -rf "$J/padmodes" && mv "$J/padmodes.new" "$J/padmodes" || fail "could not put the modes in place"
    cp "$SRC/padmodes.sh" "$J/scripts/padmodes.sh" && chmod 0755 "$J/scripts/padmodes.sh" \
        || fail "could not write scripts/padmodes.sh"
    if ! grep -q "^$MARK" "$J/scripts/rungame.sh"; then
        awk -v a="$ANCHOR" -v m='@HOOK1@' -v g='@HOOK2@' '
            { print; t = $0; gsub(/^[ \t]+|[ \t]+$/, "", t) }
            t == a { print ""; print m; print g }' "$J/scripts/rungame.sh" > "$J/scripts/rungame.sh.pad" \
            && cat "$J/scripts/rungame.sh.pad" > "$J/scripts/rungame.sh" && rm -f "$J/scripts/rungame.sh.pad" \
            || fail "could not hook rungame.sh"
    fi
    rm -f "$OFF"
    sync
    say "INSTALLED $(ls "$J/padmodes/modes" | grep -c '\.mode$') mode(s): @NAMES@"
    ;;
*)
    fail "unknown action $ACTION"
    ;;
esac
exit 0
"""

STICK_README = """PAD custom modes stick: %(what)s
Written %(written)s by mkjjpmodes.py %(version)s.

1. Copy the folder "hotfix" (and this file) to the top of a USB stick (FAT32).
2. Machine on, coin door open: open the service menu and go to its USB update
   screen (Software Update > USB Update), stick in. It says "No update data
   was found"; that is expected.
3. Hold the LEFT FLIPPER button and, still holding it, press
   Plus, Minus, Plus, Minus. It asks "Press ENTER to apply HOTFIX".
   Press ENTER, then ENTER again.
4. The game reboots. Take the stick out. What happened is written to
   %(log)s on the stick (and /jjpe/temp/%(log)s on the machine).

Scores, audits and settings are not touched. This stick only runs on
%(game)s.
"""


def stick(a):
    """A USB stick folder that installs the modes (or turns them off/on, or removes them) through
    the game's own Update USB hot fix.  No root, no ISO: plain files, any OS."""
    action = a.action
    written = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = os.path.abspath(a.out)
    hot = os.path.join(out, STICK_DIR)
    if os.path.exists(hot) and not a.force:
        raise Refused("%s already exists (--force replaces it)" % hot)
    game = a.game or ""
    modes, names = [], ""
    if action == "install":
        if not a.modes:
            raise Refused("install needs --modes")
        so = a.so
        if not so and a.iso:
            so = runtime(argparse.Namespace(iso=a.iso, out=os.path.join(tempfile.mkdtemp(prefix="padmodes_rt_"), "jjpmodes.so"),
                                            workdir=None, cache_dir=None), quiet=True)
        so = os.path.abspath(so or SO_DEFAULT)
        if not os.path.isfile(so):
            raise Refused("%s does not exist - build it with buildmods.sh, or give --iso (the stock ISO) "
                          "and it is built against the game's own glibc" % so)
        with open(so, "rb") as f:
            if f.read(4) != b"\x7fELF":
                raise Refused("%s is not an ELF library" % so)
        port = json.load(open(a.port)) if a.port else None
        modes, problems = check_modes(a.modes, port)
        for p in problems:
            print("problem: " + p)
        if problems and not a.force:
            raise Refused("%d problem(s) in %s (--force writes it anyway)" % (len(problems), a.modes))
        if not modes:
            raise Refused("no .mode files in %s" % a.modes)
        tc = os.path.join(a.modes, "title.cfg")
        if not game and os.path.isfile(tc):
            with open(tc, encoding="utf-8") as f:
                game = next((v for _n, k, v in parse_cfg(f.read()) if k == "game"), "")
        names = ", ".join(m.get("name") or m["file"] for m in modes)
    if not re.match(r"^[A-Za-z0-9_.-]*$", game):
        raise Refused("game %r: letters, digits, _ . - only" % game)
    if not game and not a.any_game:
        raise Refused("which game is this stick for? title.cfg's 'game' key or --game "
                      "(--any-game writes one that runs on any title)")
    if os.path.exists(hot):
        shutil.rmtree(hot)
    os.makedirs(hot)

    def write(rel, data, binary=False):
        p = os.path.join(hot, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data if binary else data.encode("utf-8"))
        return p

    sums = []
    if action == "install":
        def put(src, rel):
            with open(src, "rb") as f:
                data = f.read()
            write(rel, data, binary=True)
            sums.append((hashlib.sha256(data).hexdigest(), rel))
        put(so, "padmodes/jjpmodes.so")
        for fn, p in folder_files(a.modes):       # .mode, .stock, title.cfg and the modes' own media
            put(p, "padmodes/modes/" + fn)
        manifest = collections.OrderedDict([
            ("tool", TOOL), ("version", VERSION), ("written", written), ("via", "usb hot fix"),
            ("game", game),
            ("modes", [collections.OrderedDict((k, m_.get(k, "")) for k in ("file", "name", "start", "seconds", "points"))
                       for m_ in modes]),
            ("media", [fn for fn, _p in folder_files(a.modes) if media_kind(fn)]),
            ("so_sha256", sums[0][0]),
        ])
        bj = (json.dumps(manifest, indent=1) + "\n").encode()
        write("padmodes/build.json", bj, binary=True)
        sums.append((hashlib.sha256(bj).hexdigest(), "padmodes/build.json"))
        write("padmodes.sh", PADMODES_SH)
        write("padmodes.sha256", "".join("%s  %s\n" % s for s in sums))
    runme = RUNME_SH
    for k, v in (("@WRITTEN@", written), ("@ACTION@", action), ("@GAME@", game), ("@OFF@", OFF_SWITCH),
                 ("@LOG@", STICK_LOG), ("@MARK@", MODES_HOOK_MARK), ("@ANCHOR@", RUNONCE_LINE),
                 ("@HOOK1@", MODES_HOOK_LINES[1]), ("@HOOK2@", MODES_HOOK_LINES[2]),
                 ("@NAMES@", names.replace("'", "").replace('"', "").replace("$", "").replace("`", ""))):
        runme = runme.replace(k, v)
    write("runme.sh", runme)
    what = {"install": "install %d mode(s): %s" % (len(modes), names), "off": "turn the custom modes OFF",
            "on": "turn the custom modes back ON", "remove": "take the custom modes out"}[action]
    with open(os.path.join(out, "PADMODES_README.txt"), "wb") as f:
        f.write((STICK_README % {"what": what, "written": written, "version": VERSION, "log": STICK_LOG,
                                 "game": game or "any JJP title"}).replace("\n", "\r\n").encode())
    print("wrote %s: %s%s" % (hot, what, " (%s only)" % game if game else ""))
    return 0


# ============================================================================= mode files
#: every key jjpmodes.c reads (apply_kv), and what its value is
KEYS = collections.OrderedDict([
    ("name", "text"), ("title", "text"), ("start", "switches"), ("start_count", "int"),
    ("shots", "switches"), ("points", "int"), ("seconds", "int"), ("complete", "int"),
    ("complete_points", "int"), ("sound_start", "sound_or_file"), ("sound_shot", "sound_or_file"),
    ("sound_end", "sound_or_file"), ("sound_complete", "sound_or_file"),
    ("sound_channel", ("fanfare", "fx", "speech", "music")), ("sound_like", "sound"), ("music_like", "sound"),
    ("music", "sound_file"), ("picture", "picture_file"), ("picture_at", "box"),
    ("video", "video_file"), ("video_at", "box"), ("video_loop", ("yes", "no")),
    ("lamps", "lamps"), ("lamp_color", "rgb"),
    ("lamp_blink", "int"), ("font_title", "font"), ("font_value", "font"), ("font_timer", "font"),
    ("title_color", "rgba"), ("value_color", "rgba"), ("timer_color", "rgba"), ("panel_color", "rgba"),
    ("game_modes", ("hold", "pause", "end", "ignore")),
    ("hold_multiballs", ("yes", "no")), ("allow_game_modes", "text"),
    ("panel", ("middle", "bottom", "top", "none")),
    # PAD-1353: balls and coils
    ("multiball", "multiball"), ("multiball_on", "switches"), ("add_ball", "add_ball"), ("ball_save", "ball_save"),
    ("coil_start", "coil_pulse"), ("coil_shot", "coil_pulse"), ("coil_complete", "coil_pulse"),
    ("coil_hold", "coil_hold"), ("coil_hold_on", "hold_on"),
    # PAD-1354 start rules (jjpmodes.c "start rules")
    ("start_on", "events"), ("start_after", "after"), ("start_score", "int"),
    ("start_combo", "switches"), ("combo_seconds", "int"),
    ("start_count_reset", ("game", "ball")), ("start_once", ("no", "ball", "game")),
    # PAD-1384: its own C++ - <name>.cpp, built to <name>.so in the mode folder (modes/sdk/jjp_mode.h)
    ("code", "code"),
])
#: start_on words -> the game's Hook<...>::list each one needs (jjpmodes.c EVENTS)
START_EVENTS = collections.OrderedDict([
    ("ball_start", "HookBallStart_"), ("first_ball", "HookFirstBall_"), ("last_ball", "HookLastBall_"),
    ("valid_playfield", "HookValidPlayfield_"), ("ball_saved", "HookBallSave_"),
    ("extra_ball", "HookExtraBallAwarded_"), ("multiball_end", "HookMultiballEnd_"),
])
#: keys that start a mode on their own
START_RULES = ("start", "start_on", "start_after", "start_score", "start_combo")


def start_text(m):
    """What starts a mode, for a summary line: its start switches and any start rules."""
    parts = [m["start"]] if m.get("start") else []
    for k, label in (("start_on", "on"), ("start_after", "after"), ("start_score", "score"), ("start_combo", "combo")):
        if m.get(k):
            parts.append("%s %s" % (label, m[k]))
    return "; ".join(parts)
#: keys only title.cfg takes
TITLE_KEYS = collections.OrderedDict([
    ("game", "text"), ("ingame_state", "int"), ("background_modes", "modes"),
    ("coil_holds", ("on", "off")),
])
#: keys a .stock file takes (jjpmodes.c apply_stock_kv): one of the GAME's own modes, changed (PAD-1351)
STOCK_KEYS = collections.OrderedDict([
    ("mode", "stockmode"), ("seconds", "int"), ("points", "int"), ("points_x", "decimal"),
    ("shots_off", "shots"), ("shots_add", "shotadds"),
])
MAX_MODES, MAX_LIST, MAX_SHOT_SWITCHES, MAX_STOCK = 24, 24, 96, 32
MODE_FILES = (".mode", ".stock")
#: a mode's own files (PAD-1352): what the runtime's Allegro / FFmpeg read, by extension
MEDIA_EXTS = {
    "sound_file": ("wav", "ogg", "flac", "opus"),
    "picture_file": ("png", "jpg", "jpeg", "bmp", "tga"),
    "video_file": ("webm", "mkv", "mp4"),
}
_INT = re.compile(r"^-?[0-9][0-9,_]*$")
_BOX = re.compile(r"^\s*-?[0-9.]+%?([ ,\t]+-?[0-9.]+%?){3}\s*$")


def media_kind(fn):
    """'sound_file' / 'picture_file' / 'video_file' for a file name by its extension, or None."""
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
    for kind, exts in MEDIA_EXTS.items():
        if ext in exts:
            return kind
    return None


def is_sound_file(v):
    """A sound_* value naming a file of the mode's own (as jjpmodes.c's is_media_file reads it)."""
    return media_kind(v) == "sound_file"
_HEX = re.compile(r"^#?[0-9A-Fa-f]+$")
_DEC = re.compile(r"^[0-9]+(\.[0-9]+)?$")


def parse_cfg(text):
    """`key = value` lines -> [(lineno, key, value)] as jjpmodes.c reads them (# and ; comment
    lines, a trailing ' #' comment)."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s[0] in "#;" or "=" not in s:
            continue
        k, v = s.split("=", 1)
        v = v.strip()
        if " #" in v:
            v = v.split(" #", 1)[0].strip()
        out.append((n, k.strip(), v))
    return out


def _names(v):
    return [t for t in re.split(r"[ ,\t]+", v) if t]


def _coil_problem(name, want, port):
    """A coil a mode names, against the port's `coils` (jjpport.py coil_rules)."""
    if not name.startswith("coil_"):
        return "%s is not a coil name (coil_...)" % name
    coils = {c["symbol"]: c for c in (port or {}).get("coils", [])}
    if not coils:
        return None
    c = coils.get(name)
    if c is None:
        return "not in %s: %s" % (port.get("title", "this game"), name)
    if not c["pulse"]:
        return "%s is one of the game's own ball, flipper, power or motor coils: a mode may not fire it" % name
    if want == "hold" and not c["hold"]:
        return "%s is not built to stay on (a magnet, diverter, post, gate, shaker or light): a mode may only pulse it" % name
    return None


def _int_in(v, lo, hi, what):
    if not _INT.match(v):
        return "%s must be a whole number" % what
    return None if lo <= int(v.replace(",", "").replace("_", "")) <= hi else "%s must be %d-%d" % (what, lo, hi)


def check_value(kind, v, port=None):
    """-> a problem string, or None."""
    words = _names(v)
    if kind == "code":
        return None if CODE_NAME.match(v) else "must be a name of letters, digits and _ (its <name>.cpp)"
    if kind == "multiball":       # <balls in play 2-6> [ball save s 0-120]
        if not 1 <= len(words) <= 2:
            return "must be <balls in play> [ball save seconds]"
        return _int_in(words[0], 2, 6, "balls") or (len(words) > 1 and _int_in(words[1], 0, 120, "ball save")) or None
    if kind == "ball_save":
        return _int_in(v, 1, 120, "seconds")
    if kind == "add_ball":        # <switches> [times 1-6]
        if words and _INT.match(words[-1]):
            p = _int_in(words[-1], 1, 6, "times")
            if p:
                return p
            words = words[:-1]
        if not words:
            return "must name a switch"
        return check_value("switches", " ".join(words), port)
    if kind == "coil_pulse":      # <coil> [ms]
        if not 1 <= len(words) <= 2:
            return "must be <coil> [ms]"
        return (len(words) > 1 and _int_in(words[1], 1, 1000, "ms")) or _coil_problem(words[0], "pulse", port)
    if kind == "coil_hold":       # <coil> <ms> [power of 32]
        if not 2 <= len(words) <= 3:
            return "must be <coil> <ms> [power of 32]"
        return (_int_in(words[1], 100, 5000, "ms") or (len(words) > 2 and _int_in(words[2], 1, 16, "power"))
                or _coil_problem(words[0], "hold", port))
    if kind == "hold_on":
        return None if v in ("start", "shots") else check_value("switches", v, port)
    if isinstance(kind, tuple):
        return None if v in kind else "must be one of %s" % ", ".join(kind)
    if kind == "int":
        return None if _INT.match(v) else "must be a whole number"
    if kind == "sound_or_file":
        if is_sound_file(v):
            return None
        kind = "sound"
    if kind in MEDIA_EXTS:
        ok = media_kind(v) == kind and "/" not in v and "\\" not in v
        return None if ok else "must be a file in the mode folder ending .%s" % ", .".join(MEDIA_EXTS[kind])
    if kind == "box":
        if not _BOX.match(v):
            return "must be x y w h, percent of the screen"
        w, h = [float(t.rstrip("%")) for t in re.split(r"[ ,\t]+", v.strip())][2:]
        return None if w > 0 and h > 0 else "width and height must be above 0"
    if kind == "decimal":
        return None if _DEC.match(v) else "must be a number such as 2 or 1.5"
    if kind == "shotadds":
        bad = [t for t in _names(v) if t.count(":") != 1 or t.startswith(":") or t.endswith(":")]
        if bad:
            return "wants switch:shot pairs, not %s" % " ".join(bad)
        if port is None:
            return None
        p = check_value("switches", " ".join(t.split(":")[0] for t in _names(v)), port)
        return p or check_value("shots", " ".join(t.split(":")[1] for t in _names(v)), port)
    if kind == "shots":
        stock = (port or {}).get("stock") or {}
        known = set(s["name"] for s in stock.get("shots") or [])
        if not known:
            return None       # this title's shot names are read on the machine (jjpmodes.log)
        missing = [t for t in _names(v) if t not in known and not t.isdigit()]
        return None if not missing else "no shot called %s on this title" % " ".join(missing)
    if kind == "stockmode":
        stock = (port or {}).get("stock") or {}
        if port is None or not stock:
            return None
        known = set(stock.get("classes") or {}) | set(stock.get("objects") or {})
        return None if v in known else "is not one of this title's modes (its mode global or class)"
    if kind in ("rgb", "rgba"):
        h = v.lstrip("#")
        ok = _HEX.match(v) and len(h) in ((6,) if kind == "rgb" else (6, 8))
        return None if ok else "must be %s hex" % ("rrggbb" if kind == "rgb" else "rrggbb or rrggbbaa")
    if kind == "events":
        bad = [t for t in _names(v) if t not in START_EVENTS]
        if bad:
            return "%s: not a start event (%s)" % (" ".join(bad), ", ".join(START_EVENTS))
        hooks = (port or {}).get("hooks")
        if hooks:
            missing = [t for t in _names(v) if not hooks.get(START_EVENTS[t])]
            if missing:
                return "%s: %s has no %s hook" % (" ".join(missing), port.get("title", "this game"),
                                                  " ".join(START_EVENTS[t] for t in missing))
        return None
    if kind == "after":
        # the game's mode globals are known only from a live map (stock.objects, jjpstock.py
        # live); without one a name cannot be refused, as a global is not in the file
        names = [t for t in _names(v) if t != "any"]
        st = (port or {}).get("stock") or {}
        # PAD-1365: on the proc engine (no Mode class) a game mode is one of its mode procs
        objects = (set(st.get("objects") or ()) | set((port or {}).get("game_modes") or ())
                   | set((port or {}).get("proc_modes") or ()))
        if port is None or not objects:
            return None
        known = objects | set(st.get("classes") or ()) | set(port.get("mode_classes") or ())
        missing = [t for t in names if t not in known]
        return None if not missing else "not a game mode or Mode class of %s: %s" % (
            port.get("title", "this game"), " ".join(missing))
    if port is None:
        return None
    table = {"switches": "switches", "lamps": "lamps", "sound": "sounds", "font": "fonts",
             "modes": "game_modes"}.get(kind)
    if table is None:
        return None
    known = set(port.get(table, []))
    if table == "lamps":
        # a mode lights lamps (lp_*) or whole lamp groups (ls_*): MODES.md, jjpmodes.c find_lamps
        known |= set(port.get("lamp_groups", []))
    if table == "switches":
        known = set(s["symbol"] if isinstance(s, dict) else s for s in port.get("switches", []))
    if not known:
        return None
    missing = [t for t in (_names(v) if kind in ("switches", "lamps", "modes") else [v]) if t not in known]
    return None if not missing else "not in %s: %s" % (port.get("title", "this game"), " ".join(missing))


def check_modes(mode_dir, port=None):
    """A mode folder checked the way jjpmodes.c will read it -> (modes, problems):
    modes = [{file, name, start, ...}], problems = ["file:line: ..."]."""
    problems, modes = [], []
    if not os.path.isdir(mode_dir):
        raise Refused("%s is not a folder" % mode_dir)
    title = {}
    tpath = os.path.join(mode_dir, "title.cfg")
    if os.path.isfile(tpath):
        with open(tpath, encoding="utf-8", errors="replace") as f:
            for n, k, v in parse_cfg(f.read()):
                kind = TITLE_KEYS.get(k) or KEYS.get(k)
                if kind is None:
                    problems.append("title.cfg:%d: unknown key %s" % (n, k))
                    continue
                p = check_value(kind, v, port)
                if p:
                    problems.append("title.cfg:%d: %s %s" % (n, k, p))
                title[k] = v
    files = sorted(f for f in os.listdir(mode_dir) if f.endswith(".mode"))
    stocks = sorted(f for f in os.listdir(mode_dir) if f.endswith(".stock"))
    if not files and not stocks:
        problems.append("no .mode or .stock files in %s" % mode_dir)
    if len(files) > MAX_MODES:
        problems.append("%d modes: the runtime takes %d, the rest are ignored" % (len(files), MAX_MODES))
    shot_switches = set()
    for fn in files:
        with open(os.path.join(mode_dir, fn), encoding="utf-8", errors="replace") as f:
            rows = parse_cfg(f.read())
        m = dict(title)
        for n, k, v in rows:
            if k in TITLE_KEYS:
                problems.append("%s:%d: %s belongs in title.cfg" % (fn, n, k))
                continue
            kind = KEYS.get(k)
            if kind is None:
                problems.append("%s:%d: unknown key %s" % (fn, n, k))
                continue
            p = check_value(kind, v, port)
            if p:
                problems.append("%s:%d: %s %s" % (fn, n, k, p))
            if kind in ("switches", "lamps") and len(_names(v)) > MAX_LIST:
                problems.append("%s:%d: %s lists %d; the runtime takes %d" % (fn, n, k, len(_names(v)), MAX_LIST))
            m[k] = v
        for k in ("sound_start", "sound_shot", "sound_end", "sound_complete", "music", "picture", "video"):
            v = m.get(k, "")
            if v and (k in ("music", "picture", "video") or is_sound_file(v)) and media_kind(v) \
                    and "/" not in v and not os.path.isfile(os.path.join(mode_dir, v)):
                problems.append("%s: %s = %s, but there is no %s in the mode folder" % (fn, k, v, v))
        code = m.get("code", "")
        if code and CODE_NAME.match(code):
            problems.extend(code_problems(mode_dir, fn, code, port, shot_switches))
        if not any(m.get(k) for k in START_RULES) and not (code and code_starts_itself(mode_dir, code)):
            problems.append("%s: no start rule (start, start_on, start_after, start_score or start_combo%s):"
                            " the mode would never start" % (fn, ", or an idle() in its code that calls jm_start" if code else ""))
        if m.get("start_combo") and len(_names(m["start_combo"])) < 2:
            problems.append("%s: start_combo needs two switches or more" % fn)
        if m.get("start_score") and _INT.match(m["start_score"]) and int(m["start_score"].replace(",", "").replace("_", "")) <= 0:
            problems.append("%s: start_score must be above 0" % fn)
        complete = (m.get("complete") or "0").replace(",", "").replace("_", "")
        if not m.get("start") and not m.get("shots") and _INT.match(complete) and int(complete) > 0:
            problems.append("%s: complete = %s but no shots = (nothing can score it)" % (fn, m["complete"]))
        m["file"] = fn
        m.setdefault("name", fn[:-5])
        for k in ("start", "shots", "start_combo", "multiball_on", "add_ball", "coil_hold_on"):
            shot_switches.update(t for t in _names(m.get(k, "")) if t.startswith(("switch_", "dswitch_")))
        if (m.get("game_modes") or "").strip().lower() == "hold" and port is not None and port.get("engine") == "proc":
            problems.append("%s: game_modes = hold, but %s has no Mode class to hold off: use pause (hold "
                            "runs as pause there)" % (fn, port.get("title", "this game")))
        if m.get("multiball_on") and not m.get("multiball"):
            problems.append("%s: multiball_on without a multiball line (it is ignored)" % fn)
        if m.get("coil_hold") and title.get("coil_holds") != "on":
            problems.append("%s: coil_hold is off on this title until title.cfg says coil_holds = on "
                            "(after a check on the machine)" % fn)
        modes.append(m)
    if stocks and port is not None and port.get("engine") == "proc":
        problems.append("%s: %s has no Mode class, so its own modes cannot be changed (.stock files are "
                        "ignored there)" % (" ".join(stocks), port.get("title", "this game")))
    if len(stocks) > MAX_STOCK:
        problems.append("%d .stock files: the runtime takes %d, the rest are ignored" % (len(stocks), MAX_STOCK))
    seen = {}
    for fn in stocks:
        with open(os.path.join(mode_dir, fn), encoding="utf-8", errors="replace") as f:
            rows = parse_cfg(f.read())
        m = {"file": fn, "stock": True}
        for n, k, v in rows:
            kind = STOCK_KEYS.get(k)
            if kind is None:
                problems.append("%s:%d: unknown key %s (a .stock file takes %s)" % (fn, n, k, ", ".join(STOCK_KEYS)))
                continue
            p = check_value(kind, v, port)
            if p:
                problems.append("%s:%d: %s %s" % (fn, n, k, p))
            if kind in ("shots", "shotadds") and len(_names(v)) > MAX_LIST:
                problems.append("%s:%d: %s lists %d; the runtime takes %d" % (fn, n, k, len(_names(v)), MAX_LIST))
            m[k] = v
        if not m.get("mode"):
            problems.append("%s: no mode = <the game's mode> (its global, e.g. cl_mode, or its class)" % fn)
        elif m["mode"] in seen:
            problems.append("%s: %s is already changed by %s (the runtime keeps the first)" % (fn, m["mode"], seen[m["mode"]]))
        else:
            seen[m["mode"]] = fn
        if m.get("points") and m.get("points_x"):
            problems.append("%s: points and points_x both set (points wins)" % fn)
        if not any(m.get(k) for k in ("seconds", "points", "points_x", "shots_off", "shots_add")):
            problems.append("%s: changes nothing (seconds, points, points_x, shots_off or shots_add)" % fn)
        shot_switches.update(t.split(":")[0] for t in _names(m.get("shots_add", "")))
        modes.append(m)
    if len(shot_switches) > MAX_SHOT_SWITCHES:
        problems.append("%d different shot switches; the runtime wraps %d" % (len(shot_switches), MAX_SHOT_SWITCHES))
    return modes, problems


# ============================================================================= a mode's own C++ (PAD-1384)
CODE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")
#: string literals in a mode's C++ that name the game's things, by prefix -> (what, port check)
_CODE_LITERAL = re.compile(r'"((?:switch|dswitch|coil|lp|ls|se)_[A-Za-z0-9_]+)"')


def code_source(mode_dir, code):
    p = os.path.join(mode_dir, code + ".cpp")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def code_starts_itself(mode_dir, code):
    """A mode whose C++ registers idle() starts itself (jm_start), so needs no start rule. With no
    source here (a built .so alone), it is taken at its word."""
    src = code_source(mode_dir, code)
    return src is None or re.search(r"\.idle\s*=", src) is not None


def code_names(src):
    return sorted(set(_CODE_LITERAL.findall(src or "")))


def code_problems(mode_dir, fn, code, port, shot_switches):
    """A mode's code: built, and every game name its C++ writes is one the game has."""
    out = []
    so = os.path.join(mode_dir, code + ".so")
    src_path = os.path.join(mode_dir, code + ".cpp")
    src = code_source(mode_dir, code)
    if src is None and not os.path.isfile(so):
        return ["%s: code = %s, but there is no %s.cpp (or %s.so) in the mode folder" % (fn, code, code, code)]
    if not os.path.isfile(so):
        out.append("%s: %s.cpp is not built yet (Check builds it)" % (fn, code))
    elif src is not None and os.path.getmtime(src_path) > os.path.getmtime(so) + 1:
        out.append("%s: %s.cpp changed since it was built (Check builds it)" % (fn, code))
    for name in code_names(src):
        if name.startswith(("switch_", "dswitch_")):
            p = check_value("switches", name, port)
            shot_switches.add(name)
        elif name.startswith("coil_"):
            p = _coil_problem(name, "pulse", port) if port else None
        elif name.startswith(("lp_", "ls_")):
            p = check_value("lamps", name, port)
        else:
            p = check_value("sound", name, port)
        if p:
            out.append("%s: %s.cpp names %s: %s" % (fn, code, name, p))
    return out


def build_code(mode_dir, code, cxx=None):
    """<code>.cpp -> <code>.so in the mode folder with modes/sdk/build_code.sh (g++ in this Linux)
    -> (ok, output)."""
    env = dict(os.environ)
    if cxx:
        env["CXX"] = cxx
    r = subprocess.run(["bash", os.path.join(HERE, "modes", "sdk", "build_code.sh"),
                        os.path.join(mode_dir, code + ".cpp"), os.path.join(mode_dir, code + ".so")],
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    return r.returncode == 0, r.stdout


def code_modes(mode_dir):
    """[(mode file, code name)] of the folder's modes that have code."""
    out = []
    for fn in sorted(f for f in os.listdir(mode_dir) if f.endswith(".mode")):
        with open(os.path.join(mode_dir, fn), encoding="utf-8", errors="replace") as f:
            for _n, k, v in parse_cfg(f.read()):
                if k == "code" and CODE_NAME.match(v):
                    out.append((fn, v))
    return out


def ensure_cxx():
    """g++ here, installed the first time (as root: the app's Linux), as the JJP pipeline does
    gcc -> None, or why there is none."""
    if shutil.which("g++"):
        return None
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("g++ is not in this Linux: installing it (once)...", flush=True)
        for cmd in ("DEBIAN_FRONTEND=noninteractive apt-get install -y g++",
                    "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y g++",
                    "dnf install -y gcc-c++", "pacman -S --noconfirm gcc", "apk add --no-cache g++"):
            if subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0                     and shutil.which("g++"):
                return None
    return "no g++ in this Linux (install it: apt-get install g++)"


def build_codes(a):
    """`code`: build every mode's C++ in a folder (only those changed, or all with --all)."""
    bad = 0
    todo = [c for _f, c in code_modes(a.modes) if os.path.isfile(os.path.join(a.modes, c + ".cpp"))]
    why = ensure_cxx() if todo else None
    if why:
        print("refused: " + why)
        return 2
    for fn, code in code_modes(a.modes):
        src, so = os.path.join(a.modes, code + ".cpp"), os.path.join(a.modes, code + ".so")
        if not os.path.isfile(src):
            print("%s: no %s.cpp (keeping %s)" % (fn, code, "its .so" if os.path.isfile(so) else "nothing"))
            continue
        if not a.all and os.path.isfile(so) and os.path.getmtime(so) + 1 >= os.path.getmtime(src):
            print("%s: %s.so is up to date" % (fn, code))
            continue
        ok, out = build_code(a.modes, code)
        print("%s: %s" % (fn, out.strip() or ("built" if ok else "FAILED")))
        bad += not ok
    return 1 if bad else 0


# ============================================================================= rungame.sh
def has_modes_hook(text):
    return any(ln.startswith(MODES_HOOK_MARK) for ln in text.split("\n"))


def hook_rungame_modes(text):
    """rungame.sh with MODES_HOOK_LINES after the runonce.sh line (idempotent; refused when the
    anchor is not exactly one line - a rungame.sh this tool does not know is not edited blind)."""
    if has_modes_hook(text):
        return text
    lines = text.split("\n")
    at = [i for i, ln in enumerate(lines) if ln.strip() == RUNONCE_LINE]
    if len(at) != 1:
        raise Refused("rungame.sh: expected exactly one '%s' line to hook after, found %d" % (RUNONCE_LINE, len(at)))
    i = at[0] + 1
    return "\n".join(lines[:i] + MODES_HOOK_LINES + lines[i:])


def strip_modes_hook(text):
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith(MODES_HOOK_MARK):
            if out and out[-1] == "":
                out.pop()
            i += 2
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


# ============================================================================= build
def folder_files(mode_dir):
    """The files a mode folder carries to the machine: title.cfg, every .mode and .stock, every
    sound, picture and video file (a mode's own media, PAD-1352) and every mode's built code
    (<name>.so, PAD-1384; its .cpp and blocks stay home)."""
    out = []
    for fn in sorted(os.listdir(mode_dir)):
        p = os.path.join(mode_dir, fn)
        if os.path.isfile(p) and (fn.endswith(MODE_FILES + (".so",)) or fn == "title.cfg" or media_kind(fn)):
            out.append((fn, p))
    return out


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build_runtime(libdir, out):
    """jjpmodes.c built by buildmods.sh against the glibc in *libdir* (an image's own) -> out.
    Raises Refused with the build's last lines when it fails (no gcc, a glibc too new...)."""
    import subprocess
    env = dict(os.environ, JJP_MODS_LIBDIR=libdir, JJP_MODS_SO=out)
    r = subprocess.run(["bash", os.path.join(HERE, "buildmods.sh")], env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True, errors="replace")
    if r.returncode != 0 or not os.path.isfile(out):
        tail = " | ".join([ln for ln in (r.stdout or "").splitlines() if ln.strip()][-4:])
        raise Refused("building the mode runtime failed (rc %d): %s" % (r.returncode, tail))
    print("runtime: built against the image's glibc (%d bytes)" % os.path.getsize(out), flush=True)
    return out


def stage_modes(mj, raw, so_path, mode_dir, manifest):
    """The SDK + modes into a root image (loop-mounted rw), rungame.sh hooked; e2fsck after.
    *so_path* None builds the runtime against this root's own glibc first (PAD-1350: the app
    builds with no runtime of its own lying about).  -> {path in the root: sha256}."""
    staged = collections.OrderedDict()

    def put(src, rel, mode):
        dest = mnt + rel
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if isinstance(src, bytes):
            with open(dest, "wb") as f:
                f.write(src)
        else:
            shutil.copyfile(src, dest)
        os.chmod(dest, mode)
        try:
            os.chown(dest, 0, 0)
        except (OSError, AttributeError):
            pass
        staged[rel] = sha256_file(dest)

    with mj.LoopRW(raw) as mnt:
        rg = mnt + RUNGAME
        if not os.path.isfile(rg):
            raise Refused("%s: no %s in this root - not a JJP game image" % (raw, RUNGAME))
        d = mnt + PADMODES_DIR
        if os.path.isdir(d):
            shutil.rmtree(d)
        if so_path is None:
            so_path = build_runtime(mnt + ROOT_LIBDIR, os.path.join(os.path.dirname(raw), "jjpmodes.so"))
        manifest["so_sha256"] = sha256_file(so_path)
        put(so_path, PADMODES_DIR + "/jjpmodes.so", 0o755)
        for fn, p in folder_files(mode_dir):
            put(p, PADMODES_DIR + "/modes/" + fn, 0o644)
        put(PADMODES_SH.encode(), MODES_HOOK, 0o755)
        with open(rg, "r", encoding="utf-8", errors="surrogateescape") as f:
            text = f.read()
        hooked = hook_rungame_modes(text)
        if hooked != text:
            mode = os.stat(rg).st_mode & 0o7777
            with open(rg, "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write(hooked)
            os.chmod(rg, mode)
        staged[RUNGAME] = sha256_file(rg)
        manifest["staged"] = dict(staged)
        put((json.dumps(manifest, indent=1) + "\n").encode(), PADMODES_DIR + "/build.json", 0o644)
        mj.syncfs(mnt)
    rc = mj.e2fsck(raw)
    mj.say("staged %d file(s) into %s (e2fsck rc %d)" % (len(staged), os.path.basename(raw), rc))
    return staged


class _UnpackMeter:
    """PAD-1375: the first use of an ISO restores its game partition (2.5 GB compressed, about
    20 minutes reading from a Windows drive); a line every 2% so the app's status line moves."""

    def __init__(self, mj, info, iso):
        self.total = max(1, info.piece_bytes(mj.ROOT_PART))
        self.name = os.path.basename(iso)
        self.t0, self.last = time.time(), -1

    def sample(self, fed):
        pct = int(100 * fed / self.total)
        if pct // 2 != self.last // 2 and pct < 100:
            self.last = pct
            el = time.time() - self.t0
            left = el * (100 - pct) / pct if pct else 0
            print("unpacking %s's game partition (once per ISO): %d%%%s" % (
                self.name, pct, ", about %d min left" % max(1, round(left / 60)) if pct >= 4 else ""), flush=True)


def _stop_on_sigterm():
    """A SIGTERM (the app's Cancel) raises Refused, so the with-blocks unmount and the
    finally deletes the scratch, instead of dying with the ISO and the root still mounted."""
    import signal

    def stop(*_a):
        raise Refused("cancelled")
    try:
        signal.signal(signal.SIGTERM, stop)
    except (ValueError, OSError):                       # not the main thread
        pass


def build(a):
    import mkjjpmulti as mj
    mj.require_root("build")
    _stop_on_sigterm()
    mj.need_tools("partclone.ext4", "partclone.restore", "gunzip", "split", "e2fsck", "losetup", "mount",
                  "umount", "debugfs", "xorriso", "cp")
    iso = os.path.abspath(a.iso)
    if not os.path.isfile(iso):
        raise Refused("%s does not exist" % iso)
    so = None
    if a.so:
        so = os.path.abspath(a.so)
        if not os.path.isfile(so):
            raise Refused("%s does not exist - build it with buildmods.sh (or leave out --so)" % so)
        with open(so, "rb") as f:
            if f.read(4) != b"\x7fELF":
                raise Refused("%s is not an ELF library" % so)
    else:
        mj.need_tools("gcc", "objdump", "nm")
    port = json.load(open(a.port)) if a.port else None
    modes, problems = check_modes(a.modes, port)
    for p in problems:
        print("problem: " + p)
    if problems and not a.force:
        raise Refused("%d problem(s) in %s (--force writes it anyway)" % (len(problems), a.modes))
    out = os.path.abspath(mj.check_output_path(a.out, [iso], force=a.force or a.overwrite))
    work = os.path.abspath(a.workdir) if a.workdir else os.path.join(os.path.dirname(out), ".mkjjpmodes_" + os.path.basename(out))
    os.makedirs(work, exist_ok=True)
    t0 = time.time()
    try:
        with mj.IsoMount(iso, os.path.join(work, "iso")) as m:
            info = mj.iso_info(iso, m)
            info.check_stock_shape("the ISO")
            cache = mj.cached_root_raw(iso, a.cache_dir, m, info, _UnpackMeter(mj, info, iso))
            work_raw = os.path.join(work, "sda3.raw")
            mj.say("copying the cached root %s -> %s" % (cache, work_raw))
            mj.sparse_copy(cache, work_raw)
            manifest = collections.OrderedDict([
                ("tool", TOOL), ("version", VERSION), ("written", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                ("source_iso", os.path.basename(iso)), ("title", info.title or info.name),
                ("game_version", info.game_version),
                ("modes", [collections.OrderedDict((k, m_.get(k, "")) for k in ("file", "name", "start", "seconds", "points"))
                           for m_ in modes if not m_.get("stock")]),
                ("stock", [collections.OrderedDict((k, m_.get(k, "")) for k in ("file",) + tuple(STOCK_KEYS))
                           for m_ in modes if m_.get("stock")]),
                ("media", [fn for fn, _p in folder_files(a.modes) if media_kind(fn)]),
                # so_sha256: stage_modes records it - with no --so the runtime is built there,
                # against the root's own glibc (PAD-1350)
            ])
            staged = stage_modes(mj, work_raw, so, a.modes, manifest)
            chunks = mj.partclone_root(work_raw, os.path.join(work, "chunks"), info.split_size(), None, None)
            mj.say("root: %d piece(s), %s compressed" % (len(chunks), mj._gb(sum(os.path.getsize(c) for c in chunks))))
            iso_dir = os.path.join(work, "isofiles", "padmodes")
            if os.path.isdir(iso_dir):
                shutil.rmtree(iso_dir)
            os.makedirs(os.path.join(iso_dir, "modes"))
            for fn, p in folder_files(a.modes):
                shutil.copyfile(p, os.path.join(iso_dir, "modes", fn))
            manifest["staged"] = dict(staged)
            with open(os.path.join(iso_dir, "build.json"), "w") as f:
                f.write(json.dumps(manifest, indent=1) + "\n")
            maps = [(c, mj.PARTIMAG + "/" + os.path.basename(c)) for c in chunks]
            maps.append((iso_dir, ISO_MODES_DIR))
            removes = [ISO_MODES_DIR] if os.path.isdir(os.path.join(m, ISO_MODES_DIR.lstrip("/"))) else []
            if os.path.exists(out):
                os.unlink(out)
            mj.xorriso_build(iso, out, removes, [(mj.PARTIMAG, mj.ROOT_PIECE + ".gz.*")], maps, [], None, None)
        size = os.path.getsize(out)
        mj.say("wrote %s: %s in %d s, %d mode(s)" % (out, mj._gb(size), int(time.time() - t0), len(modes)))
        print("iso-size %d written" % size)
        return 0
    finally:
        if not a.keep_work and os.path.isdir(work):
            shutil.rmtree(work, ignore_errors=True)


def runtime(a, quiet=False):
    """PAD-1375: jjpmodes.so built against the glibc in a stock ISO's own root, the same build
    ``build`` runs, without writing an ISO: what a stick installs.  The root comes from the
    rig-shaped root cache (restored once per ISO) and is mounted read-only.  -> the .so path."""
    import mkjjpmulti as mj
    mj.require_root("runtime")
    _stop_on_sigterm()
    mj.need_tools("partclone.restore", "gunzip", "losetup", "mount", "umount", "gcc", "objdump", "nm")
    iso = os.path.abspath(a.iso)
    if not os.path.isfile(iso):
        raise Refused("%s does not exist" % iso)
    out = os.path.abspath(a.out)
    work = os.path.abspath(a.workdir or "/var/tmp/pad_jjpmodes_runtime")
    os.makedirs(work, exist_ok=True)
    built = os.path.join(work, "jjpmodes.so")
    with mj.IsoMount(iso, os.path.join(work, "iso")) as m:
        info = mj.iso_info(iso, m)
        info.check_stock_shape("the ISO")
        raw = mj.cached_root_raw(iso, a.cache_dir, m, info, _UnpackMeter(mj, info, iso))
    with mj.LoopRW(raw, readonly=True) as mnt:
        if not os.path.isfile(mnt + RUNGAME):
            raise Refused("%s: no %s in its root - not a JJP game image" % (iso, RUNGAME))
        build_runtime(mnt + ROOT_LIBDIR, built)
    with open(built, "rb") as f:
        data = f.read()
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out + ".part", "wb") as f:
        f.write(data)
    os.replace(out + ".part", out)
    if not quiet:
        print("runtime %s: %d bytes, sha256 %s" % (out, len(data), hashlib.sha256(data).hexdigest()))
    return out


def inspect(a):
    """What a mode ISO carries (its /jjp/padmodes/build.json), read with xorriso: no root needed."""
    import subprocess
    import tempfile
    d = tempfile.mkdtemp(prefix="mkjjpmodes_")
    try:
        r = subprocess.run(["xorriso", "-osirrox", "on", "-indev", a.iso, "-extract", ISO_MODES_DIR + "/build.json",
                            os.path.join(d, "build.json")], capture_output=True, text=True)
        p = os.path.join(d, "build.json")
        if r.returncode != 0 or not os.path.isfile(p):
            print("no custom modes on %s" % a.iso)
            return 1
        man = json.load(open(p))
        print("%s %s: %d custom mode(s), written %s by %s %s" % (man.get("title"), man.get("game_version"),
              len(man.get("modes", [])), man.get("written"), man.get("tool"), man.get("version")))
        for m in man.get("modes", []):
            print("  %-24s start %-28s %s s, %s a shot" % (m.get("name"), start_text(m), m.get("seconds") or "20",
                                                           m.get("points") or "1000000"))
        for m in man.get("stock", []):
            print("  game mode %-14s %s" % (m.get("mode"), ", ".join("%s %s" % (k, m[k]) for k in STOCK_KEYS
                                                                      if k != "mode" and m.get(k))))
        return 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check", help="check a mode folder (and, with --port, its names against a title)")
    s.add_argument("--modes", required=True)
    s.add_argument("--port", help="the title's port JSON (jjpport.py) to check every name against")
    s = sub.add_parser("code", help="build the modes' own C++ (<name>.cpp -> <name>.so; needs g++)")
    s.add_argument("--modes", required=True)
    s.add_argument("--all", action="store_true", help="build them all, not only the changed ones")
    s = sub.add_parser("build", help="write the install ISO with the modes (root, WSL)")
    s.add_argument("--iso", required=True)
    s.add_argument("--modes", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--so", help="a runtime built already (buildmods.sh's %s); left out, it is built "
                              "against the ISO's own glibc" % SO_DEFAULT)
    s.add_argument("--port")
    s.add_argument("--cache-dir")
    s.add_argument("--workdir")
    s.add_argument("--keep-work", action="store_true")
    s.add_argument("--force", action="store_true", help="write it despite problems in the modes")
    s.add_argument("--overwrite", action="store_true", help="replace an earlier output")
    s = sub.add_parser("inspect", help="list the modes a mode ISO carries")
    s.add_argument("--iso", required=True)
    s = sub.add_parser("stick", help="write a USB stick folder: the Update USB hot fix installs the modes "
                                     "(or turns them off/on, or removes them), no reinstall")
    s.add_argument("--out", required=True, help="the stick (or a folder to copy to one)")
    s.add_argument("--action", choices=STICK_ACTIONS, default="install")
    s.add_argument("--modes", help="the mode folder (install)")
    s.add_argument("--so", help="the runtime (left out: built from --iso, else buildmods.sh's %s)" % SO_DEFAULT)
    s.add_argument("--iso", help="the stock install ISO: the runtime is built against its glibc (root, WSL)")
    s.add_argument("--port")
    s.add_argument("--game", help="the game directory it runs on (default: title.cfg's 'game')")
    s.add_argument("--any-game", action="store_true", help="no title check (off/on/remove)")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("runtime", help="build the mode runtime against a stock ISO's own glibc (root, WSL): "
                                       "what a stick installs")
    s.add_argument("--iso", required=True)
    s.add_argument("--out", required=True, help="where the jjpmodes.so goes")
    s.add_argument("--workdir")
    s.add_argument("--cache-dir")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "check":
            port = json.load(open(a.port)) if a.port else None
            modes, problems = check_modes(a.modes, port)
            for m in modes:
                if m.get("stock"):
                    print("game mode %-23s %s" % (m.get("mode", "?"), m["file"]))
                else:
                    print("mode %-28s start %s" % (m["name"], start_text(m)))
            for p in problems:
                print("problem: " + p)
            print("%d mode(s), %d problem(s)" % (len(modes), len(problems)))
            return 1 if problems else 0
        if a.cmd == "code":
            return build_codes(a)
        if a.cmd == "build":
            return build(a)
        if a.cmd == "stick":
            return stick(a)
        if a.cmd == "runtime":
            runtime(a)
            return 0
        return inspect(a)
    except Refused as e:
        print("refused: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
