#!/bin/bash
# Open the switch/LED matrix beside a running game - or, on a multi-boot image,
# beside its boot menu, before any game exists.
#
#   jjpsw_launch.sh               after the game step (watch.sh): read the live
#                                 device tables and open the matrix onto them
#   jjpsw_launch.sh --menu        before the game step, a multi-boot image: open
#                                 it NOW, so the flippers and Start (the menu's
#                                 only controls) have keys while the menu is up
#   jjpsw_launch.sh --await-game  detached, while the menu is up: once the game
#                                 runs, read its tables, and reopen a
#                                 cabinet-only matrix onto them
#
# Runs as the DESKTOP USER, not root, even though the rest of the rig is root:
# the UI is a Tk window and needs that user's WSLg session.  The shared block
# is created by root (the CUSE daemons), so it is chmod'd 0666 for exactly this
# hand-off.
#
# Also refreshes the device dump first.  Every device object is zeroed in the
# ELF and filled by constructors, so names, positions and frame addressing only
# exist while a game is running - a stale dump from a previous title would
# draw the wrong playfield.
#
# WHY A MENU MATRIX (item 118, David 2026-09-13: "the emulator did not hand over
# control of the flipper buttons during the boot menu" and "the virtual
# playfield is not showing up").  A multi-boot run sits in its menu with no game
# process, and this script refused outright without one - so the matrix, and
# with it every key the cabinet has, never opened until the countdown had
# already booted the default.  Both images of a multi-boot install run the SAME
# game binary (mkjjpmulti.py refuses any other pair), so this title's saved
# tables are exactly right before the game starts; with none saved yet, the
# three switches the menu reads are enough until the game is up.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

DUMP=${JJP_DEVICES_JSON:-/var/tmp/jjp_devices.json}
CAB=${JJP_CABINET_JSON:-/var/tmp/jjp_devices_cabinet.json}
# Which tables the open matrix was started from: full / cached / cabinet.
MODE_FILE=${JJP_MATRIX_MODE_FILE:-/var/tmp/jjp_matrix_mode}
MODE=${1:-}
# The playfield photo comes out of whichever game is MOUNTED, not from a
# checked-in file: a hard-coded wonka_pf_image.png drew a Wonka playfield for
# every title.  Cached per image so it is decrypted once.
PF=${JJP_PF_PNG:-$JJP_BASE/pf_image.png}
if [ "$MODE" != "--await-game" ] && [ ! -s "$PF" ]; then
    python3 "$HERE/pfimage.py" --root "$JJP_ROOT" --out "$PF" || {
        echo "jjpsw_launch.sh: no playfield image for this title - the matrix" >&2
        echo "  will still show the grid, just without the photo." >&2
        PF=""
    }
fi
[ -s "$PF" ] || PF=""
USER_NAME=${JJP_DESKTOP_USER:-$(getent passwd 1000 | cut -d: -f1)}

# The switch/lamp tables are filled by the game's constructors a few seconds
# AFTER it starts, so a dump taken the instant the window appears is half-empty:
# names read "not used", no lamps are placed, and calibration fails (which makes
# the matrix UI show every switch as "not used" and zero LEDs).  Retry until the
# dump is populated - calibration succeeding, or a real switch-name count - then
# use whatever we have.  Read-only, so retrying costs nothing but time.
dump_ok() {
    python3 - "$1" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
if d.get('cabinet_only'):
    sys.exit(1)
cal = d.get('calibration', {}).get('ok')
named = sum(1 for s in d.get('switches', [])
            if (s.get('name') or '') not in ('', 'not used'))
sys.exit(0 if (cal or named >= 60) else 1)
PY
}

# Is this dump THIS game's, or the last one's?
#
# The dump file is one fixed path reused by every title, so a read that fails
# leaves the PREVIOUS game's tables sitting there looking perfectly valid.  That
# is how a Guns N' Roses run came up showing Wonka's switches - gobstopper
# targets and a 6-ball trough on a GnR playfield - which is worse than showing
# nothing, because every name, number and frame address in it is a confident
# lie about the machine that is actually running.
#
# swdump records the ELF it read, which carries the title, so the check is exact
# and needs nothing new written.
dump_is_this_title() {
    python3 - "$1" "$2" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
want = ('/%s/' % sys.argv[2])
sys.exit(0 if want in (d.get('elf') or '') else 1)
PY
}

matrix_count() {
    local n
    n=$(pgrep -fc 'jjpsw\.py' 2>/dev/null)
    echo "${n:-0}"
}

# Read the RUNNING game's tables into $DUMP.  0 = they are there (full, or
# sparse but this title's); otherwise the reason is printed and returned.
read_tables() {
    # Each read goes to a SIDE file and replaces $DUMP only when it is good.
    # $DUMP is what the boot menu's matrix opens from before the next game
    # exists, so a read that never completed must not stand in for tables that
    # did: a Stop that landed mid-read left a 23-name, uncalibrated dump over
    # good saved ones (2026-09-13), and the next menu opened cabinet-only.
    local ok=0 title tmp="$DUMP.reading"
    rm -f "$tmp"
    for _ in $(seq 1 16); do
        # --pf is the PHOTO'S SIZE, not the photo: calibrate() needs it to tell
        # an impossible inches->pixels scale from a possible one (a scale whose
        # playfield would be taller than the picture of it is wrong).  Without
        # it the calibration still works, just without that check.
        if python3 "$HERE/swdump.py" --out "$tmp" --quiet \
                ${PF:+--pf "$PF"} 2>/dev/null \
                && dump_ok "$tmp"; then
            ok=1; break
        fi
        sleep 2
    done
    title=$(jjp_title)
    if [ "$ok" = "1" ]; then
        mv -f "$tmp" "$DUMP"
        return 0
    fi
    if [ -s "$DUMP" ] && dump_is_this_title "$DUMP" "$title" && dump_ok "$DUMP"; then
        rm -f "$tmp"
        echo "jjpsw_launch.sh: the game's tables were not complete yet - keeping $title's saved ones" >&2
        return 0
    fi
    [ -s "$tmp" ] && mv -f "$tmp" "$DUMP"
    if [ ! -s "$DUMP" ]; then
        echo "jjpsw_launch.sh: could not read the device tables" >&2; return 4
    fi
    # A sparse dump OF THIS TITLE is worth opening - the names fill in as the
    # game finishes its constructors.  A dump of a DIFFERENT title is not: it
    # would draw another game's switches on this game's playfield, every one of
    # them wrong and none of them saying so.
    if ! dump_is_this_title "$DUMP" "$title"; then
        echo "jjpsw_launch.sh: the cached device tables are NOT $title's" >&2
        echo "  ($DUMP was left by a different title), and reading this" >&2
        echo "  game's tables failed.  Refusing to open the matrix onto" >&2
        echo "  another game's switches - start the game again, or wait for" >&2
        echo "  it to finish initialising and re-run this script." >&2
        return 5
    fi
    echo "jjpsw_launch.sh: device tables still sparse after retries -" >&2
    echo "  opening the matrix with what was read (some switches may" >&2
    echo "  show 'not used' until the game finishes initialising)." >&2
    return 0
}

# open_matrix TABLES MODE [what the log line adds]
open_matrix() {
    chmod 666 "$1" 2>/dev/null
    chmod 666 /dev/shm${JJP_SHM_NAME:-/jjp_switches} 2>/dev/null
    # Backgrounded, not exec'd: this is one of watch.sh's steps and must RETURN.
    # setsid so the window outlives the WSL session that started it.
    # --game-display: the game's own window takes the matrix keys too
    # (jjpkeys.py grabs them on the nested display), so either window works.
    setsid sudo -u "$USER_NAME" env DISPLAY="${JJP_UI_DISPLAY:-:0}" \
        python3 "$HERE/jjpsw.py" --devices "$1" ${PF:+--pf "$PF"} \
        --game-display "${JJP_NESTED:-:1}" \
        >>/var/tmp/jjp_ui.log 2>&1 </dev/null &
    sleep 2
    local ui
    ui=$(matrix_count)
    if [ "$ui" = "0" ]; then
        echo "jjpsw_launch.sh: the matrix exited immediately; see /var/tmp/jjp_ui.log" >&2
        tail -3 /var/tmp/jjp_ui.log >&2 2>/dev/null
        return 5
    fi
    echo "$2" > "$MODE_FILE"
    # Put it back on the monitor it was closed on.  Tk cannot do this itself:
    # under WSLg it reads its own position as -32768, so jjpsw.py keeps the SIZE
    # and the position is settled here, the same way the game window's is.
    bash "$HERE/winpos.sh" restore matrix || true
    echo "switch matrix: ${ui} process(es) on ${JJP_UI_DISPLAY:-:0}${3:+ - $3}"
    return 0
}

# Close the matrix the way stop.sh does - asked, so WSLg releases its surface
# instead of leaving a ghost - after saving where it is.
close_matrix() {
    bash "$HERE/winpos.sh" save matrix || true
    pkill -TERM -f 'jjpsw\.py' 2>/dev/null
    for _ in 1 2 3 4 5 6; do
        [ "$(matrix_count)" = "0" ] && break
        sleep 0.5
    done
    pkill -9 -f 'jjpsw\.py' 2>/dev/null
    rm -f "$MODE_FILE"
}

# The five switches a boot menu reads, at the JJP I/O board's addresses - the
# same bytes jjpselect's input_jjpio.c reads: LEFT flipper byte 1 bit 0, RIGHT
# flipper byte 1 bit 2, START byte 3 bit 0 (jjpcrt's, platform-wide), and the
# front Volume+ / Volume- buttons byte 1 bits 5 and 6 (GNR's device table;
# item 120) - the direct region, active LOW; frame_bit is a MASK, as swdump
# writes it.  The symbols are the ones the matrix's keymap resolves, so Left /
# Right / 1 / Up / Down work as in a game.
write_cabinet_dump() {
    python3 - "$CAB" "$(jjp_title)" <<'PY'
import json, sys
sw = [('dswitch_l_flipper_lo', 'Left Flipper', 1, 0x01),
      ('dswitch_r_flipper_lo', 'Right Flipper', 1, 0x04),
      ('dswitch_start', 'Start Button', 3, 0x01),
      ('dswitch_plus', 'Up / Volume+ Button', 1, 0x20),
      ('dswitch_minus', 'Down / Volume- Button', 1, 0x40)]
json.dump({'cabinet_only': True, 'elf': '', 'title': sys.argv[2],
           'calibration': {'ok': False}, 'lamps': [], 'coils': [],
           'switches': [{'index': i, 'symbol': s, 'name': n, 'addr': 0,
                         'kind': 'switch', 'frame_byte': fb, 'frame_bit': m,
                         'group': 0, 'inverted': False, 'live_closed': False,
                         'x': None, 'y': None}
                        for i, (s, n, fb, m) in enumerate(sw)]},
          open(sys.argv[1], 'w'))
PY
}

# The matrix for a boot menu: this title's saved tables when there are some,
# the three cabinet switches when there are none.
open_for_menu() {
    if [ "$(matrix_count)" != "0" ]; then
        echo "switch matrix: already open"
        return 0
    fi
    if [ -s "$DUMP" ] && dump_is_this_title "$DUMP" "$(jjp_title)" && dump_ok "$DUMP"; then
        open_matrix "$DUMP" cached \
            "the flippers and Start work now (Left / Right / 1, in it or in the game window)"
    else
        write_cabinet_dump || { echo "jjpsw_launch.sh: could not write $CAB" >&2; return 4; }
        open_matrix "$CAB" cabinet \
            "the flippers and Start only (Left / Right / 1, in it or in the game window) - the playfield opens once the game is up"
    fi
}

# Once the game is up: its tables into $DUMP, and a cabinet-only matrix
# reopened onto them (a matrix opened from saved tables already has them).
after_game() {
    read_tables || return $?
    if [ "$(cat "$MODE_FILE" 2>/dev/null)" = "cabinet" ] && [ "$(matrix_count)" != "0" ]; then
        close_matrix
        open_matrix "$DUMP" full "reopened onto the game's own tables"
        return $?
    fi
    echo "switch matrix: open; this title's tables refreshed"
    return 0
}

spawn_waiter() {
    pkill -f 'jjpsw_launch\.sh --await-game' 2>/dev/null
    setsid bash "$HERE/jjpsw_launch.sh" --await-game >>/var/tmp/jjp_ui.log 2>&1 </dev/null &
}

if [ "$(id -u)" = "0" ]; then
    case "$MODE" in
    --menu)
        open_for_menu
        exit $?
        ;;
    --await-game)
        # Up to ten minutes in the menu, and gone as soon as the run is: a menu
        # that closed with no game after it (a Stop) has nothing to read.
        quiet=0
        for _ in $(seq 1 300); do
            [ "$(jjp_game_count)" != "0" ] && break
            if [ "$(jjp_select_count)" = "0" ]; then
                quiet=$((quiet + 1))
                [ "$quiet" -ge 6 ] && exit 0
            else
                quiet=0
            fi
            sleep 2
        done
        [ "$(jjp_game_count)" = "0" ] && exit 0
        echo "$(date +%H:%M:%S) jjpsw_launch.sh: the game is up after the boot menu - reading its tables"
        after_game
        exit $?
        ;;
    "")
        if [ "$(matrix_count)" != "0" ]; then
            if [ "$(jjp_game_count)" = "0" ]; then
                spawn_waiter
                echo "switch matrix: open for the boot menu; the game's own tables are read once it is up"
                exit 0
            fi
            after_game
            exit $?
        fi
        if [ "$(jjp_game_count)" = "0" ]; then
            if [ "$(jjp_select_count)" != "0" ]; then
                open_for_menu || exit $?
                spawn_waiter
                exit 0
            fi
            echo "jjpsw_launch.sh: no game running - start one first" >&2
            exit 3
        fi
        read_tables || exit $?
        open_matrix "$DUMP" full
        exit $?
        ;;
    *)
        echo "usage: jjpsw_launch.sh [--menu | --await-game]" >&2
        exit 64
        ;;
    esac
fi

# Already the desktop user (a Linux desktop, or someone ran it by hand).
# NOTE reading the game's memory needs root, so this branch only works when the
# game is running as this same user - which is why the GUI calls the script as
# root and lets the root branch above drop privileges for the UI alone.
python3 "$HERE/swdump.py" --out "$DUMP" --quiet || {
    echo "jjpsw_launch.sh: cannot read the game's tables as $(id -un);" >&2
    echo "  run this as root - it drops to the desktop user for the UI." >&2
    exit 4; }
exec python3 "$HERE/jjpsw.py" --devices "$DUMP" ${PF:+--pf "$PF"} --game-display "${JJP_NESTED:-:1}"
