#!/bin/bash
# Start the Spike 1 emulator and open its DMD + switch/LED windows.  Run as
# root (wsl -u root): the device model needs a privileged host setup, then the
# viewer windows drop to the desktop user for their WSLg session.
#
# Streams a plain progress line per step to stdout — the GUI panel logs each as
# it prints (pinball_decryptor/gui/spike1_emulate_tab).  The last line is READY.
#
# Optional arg: a Spike 1 card image (Windows or WSL path) to extract the game
# from.  Omit it once a game has been extracted — the work dir keeps it.
#
# The rig's python scripts are run FROM HERE (the repo tree), never copied into
# the work dir: build_rootfs.py / s1view.py import the ``pinball_decryptor``
# package by resolving the repo root from their own location, so a copy sitting
# somewhere else cannot find it.  Only runtime DATA (rootfs, game, captures,
# EEPROM) lives in the work dir.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
: "${S1_DESKTOP_USER:=$(getent passwd 1000 2>/dev/null | cut -d: -f1)}"
UHOME="/home/${S1_DESKTOP_USER:-david}"
: "${S1_WORK:=$UHOME/s1emu}"
: "${QEMU_WORK:=$UHOME/qemubuild}"
: "${S1_QEMU:=$QEMU_WORK/qemu-arm}"
CARD="${1:-}"

log(){ echo "$*"; }
fail(){ log "ERROR: $*"; exit "${2:-1}"; }

mkdir -p "$S1_WORK"

# 1. patched qemu-user (one-time build, a few minutes on first run)
if [ ! -x "$S1_QEMU" ]; then
    log "Setup: building the patched ARM emulator (one time, a few minutes)…"
    QEMU_WORK="$QEMU_WORK" QEMU_OUT="$QEMU_WORK" bash "$HERE/build_qemu.sh" 2>&1 \
        || fail "could not build qemu — install: meson ninja-build libglib2.0-dev pkg-config flex bison gcc" 2
fi

# 2. CUSE device model (quick compile; rebuild when the source changed)
if [ ! -x "$S1_WORK/s1hwshim" ] || [ "$HERE/s1hwshim.c" -nt "$S1_WORK/s1hwshim" ]; then
    log "Setup: compiling the device model…"
    gcc -O2 -o "$S1_WORK/s1hwshim" "$HERE/s1hwshim.c" \
        $(pkg-config --cflags --libs fuse3) 2>&1 \
        || fail "could not compile the device model (need libfuse3-dev)" 3
fi

# 3. extract the game (cache-aware).  Each card's extraction is kept under
#    $S1_WORK/cache/<label>/{rootfs,game}; the ACTIVE one is exposed as the
#    symlinks $S1_WORK/rootfs and $S1_WORK/game, so steps 4-6 (and nodebus) are
#    unchanged.  Switching titles reuses a past extraction instead of the ~1 min
#    re-extract.  Run from $HERE with the repo on PYTHONPATH so the reader imports.
if [ -n "$CARD" ]; then
    case "$CARD" in [A-Za-z]:*)
        CARD="/mnt/$(printf '%s' "${CARD:0:1}" | tr 'A-Z' 'a-z')${CARD:2}";; esac
    CARD="${CARD//\\//}"
    [ -e "$CARD" ] || fail "card not found: $CARD" 4
    LABEL=$(bash "$HERE/cache.sh" label "$CARD")
    ENTRY="$S1_WORK/cache/$LABEL"
    if bash "$HERE/cache.sh" valid "$CARD" "$S1_WORK"; then
        log "Using the cached extraction for $LABEL."
    else
        log "Extracting the game from the card (first time for this card)…"
        bash "$HERE/cache.sh" evict "$S1_WORK" 5 2>/dev/null || true
        rm -rf "$ENTRY"; mkdir -p "$ENTRY"
        # -u: unbuffered, so build_rootfs.py's progress lines stream to the GUI.
        PYTHONPATH="$REPO" python3 -u "$HERE/build_rootfs.py" \
            "$CARD" "$ENTRY/rootfs" "$ENTRY/game" 2>&1 \
            || { rm -rf "$ENTRY"; fail "extraction failed" 5; }
        bash "$HERE/cache.sh" stamp "$CARD" > "$ENTRY/.src"
    fi
    bash "$HERE/cache.sh" activate "$LABEL" "$S1_WORK" \
        || fail "could not activate the extracted game" 5
elif [ ! -e "$S1_WORK/game/game" ]; then
    fail "no game extracted yet — pick a Spike 1 card image" 4
fi

# 3b. mains line-frequency self-test: the emulator has no real AC line, so the
#     game's factory check sits on "CHECK POWER DISTRIBUTION BOARD" forever.
#     Patch the extracted game to report a valid 60 Hz (idempotent; see s1patch.py).
if [ -e "$S1_WORK/game/game" ]; then
    log "Game patches: $(python3 "$HERE/s1patch.py" "$S1_WORK/game/game" 2>&1)"
    # switch names for the viewer's matrix window: the title's own (node,index)
    # -> name map, straight from the game ELF (s1elf --switches).  The switch
    # window reads this over the UNC path and labels each cell.  Best-effort.
    if python3 "$HERE/s1elf.py" --switches "$S1_WORK/game/game" \
            > "$S1_WORK/s1switches.json" 2>/dev/null; then
        log "Switch names: $(python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1]))),"switches")' "$S1_WORK/s1switches.json" 2>/dev/null)"
    fi
    # A curated per-title map OVERRIDES the s1elf decode: the static decode's
    # (node,index) attribution is wrong (its bit/device fields don't match the
    # game's runtime registration — GOT LE's START is really (1,11), not the
    # (9,5) it emits).  switchmaps/<TITLE>.json files are sweep-verified live.
    _title=$(basename "$(dirname "$(readlink -f "$S1_WORK/game")")")
    _title=${_title%-*}
    if [ -e "$HERE/switchmaps/$_title.json" ]; then
        cp "$HERE/switchmaps/$_title.json" "$S1_WORK/s1switches.json"
        log "Switch names: curated map for $_title."
    fi
fi

# 3c. hide the DMD panel firmware from the boot updater.  With the node
#     boards reporting matching firmware (nodebus.py cmd-0xFE fw), the update
#     manager's NEXT item is the display panel itself: it reads the panel's
#     version over i2c 0x51 (the qemu stub answers 0xff), mismatches
#     display.hex, "flashes" the whole 19 MB image into the void (the stub
#     accepts writes), fails verify — and retries with the DMD dark.  An
#     image that cannot be OPENED means "no update available": the item is
#     skipped and the panel keeps running as-is, which under emulation it
#     always does.  Idempotent, and start.sh re-applies it after any fresh
#     extraction.
_dhex="$S1_WORK/rootfs/usr/local/spike/display.hex"
if [ -L "$_dhex" ] || [ -e "$_dhex" ]; then
    ln -sfn display-hex-hidden-under-emulation "$_dhex" 2>/dev/null \
        && log "Display firmware image hidden from the boot updater."
fi

# 4. valid board EEPROM (unlocks the boot; see docs/architecture/spike1_emulation.md)
mkdir -p "$S1_WORK/rootfs/data"
python3 "$HERE/make_seed.py" "$S1_WORK/rootfs/data/board_eeprom.bin" >/dev/null 2>&1

# 5. node-bus responder (a pty bound at /dev/ttyS4) + fresh captures
pkill -KILL -f nodebus.py 2>/dev/null
pkill -KILL -f s1ball.py 2>/dev/null
rm -f "$S1_WORK/spi0.cap" "$S1_WORK/ttyS4.cap" "$S1_WORK/ttyS4.slave" \
      "$S1_WORK/s1sw.input" "$S1_WORK/s1auto.input" "$S1_WORK/s1ball.cmd"
# S1_NB_LOG: optional path for a per-request/response node-bus log (nodebus.py
# argv[3]) — every REQ + the exact reply bytes, for debugging node registration.
# S1_SW_AUTO: second SwitchInput bitmap (the s1ball.py ball-keeper daemon);
# merged with the viewer's s1sw.input by the responder.
setsid env S1_SW_INPUT="$S1_WORK/s1sw.input" \
    S1_SW_AUTO="$S1_WORK/s1auto.input" \
    S1_GAME_ELF="$S1_WORK/game/game" \
    python3 "$HERE/nodebus.py" "$S1_WORK/ttyS4.slave" "$S1_WORK/ttyS4.cap" \
    ${S1_NB_LOG:+"$S1_NB_LOG"} \
    >/dev/null 2>&1 &
for i in $(seq 1 25); do [ -s "$S1_WORK/ttyS4.slave" ] && break; sleep 0.2; done
SLAVE=$(cat "$S1_WORK/ttyS4.slave" 2>/dev/null)
[ -n "$SLAVE" ] || fail "node-bus responder did not come up" 6
log "Node-bus responder up."

# 6. run the game (MUTED; drops the fatal SIGFPE; binds the responder pty; captures
#    the DMD).  emu_root.sh owns the namespace/chroot/CUSE/binfmt loop.
export S1_ROOT="$S1_WORK/rootfs" S1_GAME="$S1_WORK/game" S1_QEMU="$S1_QEMU" \
       S1_HWSHIM="$S1_WORK/s1hwshim" S1_CPUINFO="$HERE/cpuinfo" \
       S1_STRACE=0 S1_I2C_LOG=0 S1_RUNS=1000 S1_DROP_SIGFPE=1 \
       S1_EE_FILE=/data/board_eeprom.bin S1_TTYS4_CAP="$SLAVE" \
       S1_SPI0_CAP="$S1_WORK/spi0.cap" S1_DMD_FPS="${S1_DMD_FPS:-60}" \
       PAD_AUDIO="${PAD_AUDIO:-0}" S1_AUDIO_FIFO="$S1_WORK/audio.fifo" \
       S1_CPUSW_FILE=/data/s1cpusw.input
# S1_CPUSW_FILE: the CPU I/O-expander injection file (qemu patch 4) that
# carries the DEDICATED switches — coin-door interlock + the service cluster
# (BACK/−/+/SELECT).  The path is CHROOT-relative (qemu runs chrooted); the
# ball keeper writes the same file from outside via /proc/<pid>/root/data/….
# Without this export qemu's getenv finds nothing and every door/service
# press is silently dropped — exactly the "these controls aren't doing
# anything" failure.
: > "$S1_WORK/emu.log"
setsid bash "$HERE/emu_root.sh" >"$S1_WORK/emu.log" 2>&1 < /dev/null &
log "Game starting under the emulator…"

# 6a. sound: the i2s shim tees the game's paced 44.1 kHz s16 stereo PCM into
#     $S1_AUDIO_FIFO; the Spike 2 rig's speaker chain (playaudio.sh ->
#     padrelay.py -> Windows padplay.py over TCP, bypassing the damaged WSLg
#     audio hop) plays it.  ONE speaker implementation for both rigs — the
#     "which sink / which python / how to tear down a Windows child" lessons
#     all live in playaudio.sh.  PAD_AUDIO=1 opts in (the GUI's Emulate tab
#     sets it; scripted runs stay muted by default).  The volume/mute knob
#     reaches padplay.py through PAD_AUDIO_CTL, forwarded by playaudio.sh.
if [ "${PAD_AUDIO:-0}" = "1" ]; then
    pkill -f "playaudio.sh $S1_AUDIO_FIFO" 2>/dev/null
    pkill -f "padrelay.py $S1_AUDIO_FIFO" 2>/dev/null
    # PAD_AUDIO_FMT_FIXED: this rig KNOWS its PCM format (44100x2 s16, from
    # the game ELF), so playaudio.sh takes it from the args instead of
    # polling its fmt file — pre-writing that file RACED playaudio's own
    # rm -f (up to 10 s in, behind its WSLg-socket wait) and cost a boot a
    # 60 s silent stall.
    # Spike 1 speaks on ITS OWN TCP port: sharing Spike 2's 45997 meant the
    # two rigs' port-matched player cleanups could reap each other's LIVE
    # player, and one wedged WSL localhost-proxy binding silenced both.
    setsid env PAD_GAME="Spike 1" PAD_AUDIO_FMT_FIXED=1 \
        PAD_AUDIO_PORT="${S1_AUDIO_PORT:-45998}" \
        bash "$REPO/tools/spike2_emu/playaudio.sh" \
        "$S1_AUDIO_FIFO" 44100 2 "$S1_WORK/audio.fmt" \
        >"$S1_WORK/audio.log" 2>&1 &
    log "Audio up (PAD_AUDIO=0 to mute)."
fi

# 6b. the invisible-ball keeper: holds a full trough + closed interlock and
#     answers trough-eject/auto-plunger coil fires with the switch changes a
#     real ball would make, so START actually serves a playable ball.  It also
#     runs one-shot commands ("s1ball.py coin/start/press/drain").  S1_BALL=0
#     opts out (bare-wire behaviour: nothing held, nothing automated).
if [ "${S1_BALL:-1}" != "0" ]; then
    setsid python3 "$HERE/s1ball.py" daemon --work "$S1_WORK" \
        >"$S1_WORK/s1ball.log" 2>&1 &
    log "Ball keeper up (S1_BALL=0 to disable)."
fi

# 7. the DMD and switch/LED viewers are NATIVE windows the Windows app opens
#    (pinball_decryptor/gui/spike1_windows.py), reading this run dir over the
#    \\wsl.localhost UNC path — reliable and on-screen, unlike a WSLg window.
#    The old WSLg s1view viewer is kept only as an opt-in fallback (a Linux
#    desktop with no Windows app), behind S1_WSLG_VIEWER=1.
if [ -n "${S1_WSLG_VIEWER:-}" ]; then
    setsid sudo -u "$S1_DESKTOP_USER" env \
        DISPLAY="${S1_UI_DISPLAY:-:0}" \
        WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" \
        XDG_RUNTIME_DIR="/run/user/$(id -u "$S1_DESKTOP_USER" 2>/dev/null)" \
        PYTHONPATH="$REPO" \
        python3 "$HERE/s1view.py" --run-dir "$S1_WORK" >/dev/null 2>&1 &
    sleep 1
    log "Opened the WSLg switch/LED window (fallback)."
fi
log "The DMD and switch windows open in the app."
log "READY"
