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

# 3a. which firmware ERA this card is.  build_rootfs.py leaves .game_exe (and
#     .game_path, .display) beside the game only for an EARLY card — the 2012
#     home models such as Transformers The Pin (PAD-101) — whose firmware
#     predates the node-bus framework the rest of this script assumes: the
#     responder speaks that era's wire format (s1early.py via nodebus.py),
#     none of the s1patch.py boot patches exist to apply, and the switch map
#     cannot be walked with the DMD-generation anchor (yet).  Absent = the
#     2015-2016 titles, and nothing below changes for them.
S1_ERA=dmd
if [ -e "$S1_WORK/game/.game_exe" ]; then
    S1_ERA=early
    # the DAC rate this era runs at (its WAVs are 24000/12000 Hz mono s16 and
    # the mixer writes 128-frame stereo blocks) — the i2s pacing in emu_root
    # reads it from the environment; the DMD generation stays at 44100.
    export S1_PCM_RATE="${S1_PCM_RATE:-24000}" S1_PCM_CH="${S1_PCM_CH:-2}"
    # cabinet switches live on CPU-board GPIO pins in this era; this file is
    # how the switch window and the keeper press them (byte per pin, 0=held)
    export S1_GPIO_FILE="$S1_WORK/s1gpio.input"
    rm -f "$S1_GPIO_FILE"
    log "Early Spike 1 card: $(cat "$S1_WORK/game/.game_name" 2>/dev/null) launches $(cat "$S1_WORK/game/.game_exe"), $(cat "$S1_WORK/game/.display" 2>/dev/null) display."
    # What the app's display window needs to draw this machine instead of a
    # DMD: WHICH display it is, and the game's own font so the window can
    # decode segments to characters.  Without the first the window falls back
    # to the 128x32 DMD and reads EIGHT of this era's 256-byte frames as one
    # 2048-byte frame - solid stripes (PAD-101).
    cat "$S1_WORK/game/.display" > "$S1_WORK/s1display" 2>/dev/null
    python3 "$HERE/s1alpha.py" --font \
        "$S1_WORK/game/$(cat "$S1_WORK/game/.game_exe")" \
        "$S1_WORK/s1font.json" >/dev/null 2>&1 \
        || log "  (no font table: the display shows segments without text)"
else
    rm -f "$S1_WORK/s1display" "$S1_WORK/s1font.json"
fi
export S1_ERA

# 3b. mains line-frequency self-test: the emulator has no real AC line, so the
#     game's factory check sits on "CHECK POWER DISTRIBUTION BOARD" forever.
#     Patch the extracted game to report a valid 60 Hz (idempotent; see s1patch.py).
if [ -e "$S1_WORK/game/game" ]; then
    log "Game patches: $(python3 "$HERE/s1patch.py" "$S1_WORK/game/$(cat "$S1_WORK/game/.game_exe" 2>/dev/null || echo game)" 2>&1)"
    # switch names for the viewer's matrix window: the title's own (node,index)
    # -> name map.  The switch window reads this over the UNC path, labels and
    # lays out its rows from it, binds the play keys through it, and the ball
    # keeper resolves its trough/shooter/start slots from it — so a map with
    # the wrong POSITIONS is not a cosmetic problem, it is "the switches do
    # nothing".
    #
    # Two sources, in this order:
    #   1. a sweep-verified curated map for this card (switchmaps/<CARD>.json),
    #      which also carries the "_trough_coils" the keeper serves on;
    #   2. otherwise the LIVE registry walk (s1swmap.py), started with the game
    #      below and written as soon as the game has registered its switches.
    #
    # What is NOT a source any more: the static ELF decode (s1elf --switches).
    # Its names are right and its (node,index) attribution is wrong — GOT LE's
    # START is really (1,11), not the (9,5) it emits — because the tables it
    # reads are populated at RUNTIME and the file's copies are stale.  It used
    # to be the default, with the 7 curated files as the only correction, so
    # every other card (including the Pro build of a title whose LE is curated)
    # played with every click, key and trough slot pointed somewhere else.
    # That was PAD-101: "switches not working on any spike 1 game".
    _title=$(basename "$(dirname "$(readlink -f "$S1_WORK/game")")")
    _title=${_title%-*}
    S1_SWMAP_LIVE=0
    if [ -e "$HERE/switchmaps/$_title.json" ]; then
        cp "$HERE/switchmaps/$_title.json" "$S1_WORK/s1switches.json"
        log "Switch names: curated map for $_title."
    elif [ "$S1_ERA" = "early" ]; then
        rm -f "$S1_WORK/s1switches.json"
        log "Switch names: none yet for an early card (the switch window shows the raw matrix)."
    else
        # a map from a PREVIOUS card would name this title's switches wrongly
        rm -f "$S1_WORK/s1switches.json"
        S1_SWMAP_LIVE=1
        log "Switch names: no curated map for $_title — reading them from the"
        log "  game itself once it boots (they appear in the switch window)."
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
# The responder is killed BY PID, OURS only — `pkill -f nodebus.py` matches the
# SPIKE 2 rig's responder too (it has a nodebus.py of its own), so starting
# Spike 1 killed a running Spike 2 game's node bus.  s1own.sh owns that
# distinction (PAD-98); status.sh and stop.sh already asked it and this one did
# not.  (The keeper's name is unique to this rig, so it stays a plain pkill —
# the same pair stop.sh does.)
_nb=$(S1_WORK="$S1_WORK" bash "$HERE/s1own.sh" nodebus 2>/dev/null)
[ -n "$_nb" ] && kill -KILL $_nb 2>/dev/null
pkill -KILL -f s1ball.py 2>/dev/null
rm -f "$S1_WORK/spi0.cap" "$S1_WORK/ttyS4.cap" "$S1_WORK/ttyS4.slave" \
      "$S1_WORK/s1sw.input" "$S1_WORK/s1auto.input" "$S1_WORK/s1ball.cmd"
# S1_NB_LOG: optional path for a per-request/response node-bus log (nodebus.py
# argv[3]) — every REQ + the exact reply bytes, for debugging node registration.
# S1_SW_AUTO: second SwitchInput bitmap (the s1ball.py ball-keeper daemon);
# merged with the viewer's s1sw.input by the responder.
# S1_ERA / S1_EEP_FILE: the early era's responder (s1early.py) and where it
# keeps that machine's 64-byte settings EEPROM, which lives on the net bridge
# and is read over this same serial port.
setsid env S1_SW_INPUT="$S1_WORK/s1sw.input" \
    S1_SW_AUTO="$S1_WORK/s1auto.input" \
    S1_GAME_ELF="$S1_WORK/game/$(cat "$S1_WORK/game/.game_exe" 2>/dev/null || echo game)" \
    S1_ERA="$S1_ERA" S1_EEP_FILE="$S1_WORK/s1eep.bin" S1_WORK="$S1_WORK" \
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
       S1_STRACE="${S1_STRACE:-0}" S1_I2C_LOG=0 S1_RUNS=1000 S1_DROP_SIGFPE=1 \
       S1_EE_FILE=/data/board_eeprom.bin S1_TTYS4_CAP="$SLAVE" \
       S1_SPI0_CAP="$S1_WORK/spi0.cap" S1_DMD_FPS="${S1_DMD_FPS:-60}" \
       PAD_AUDIO="${PAD_AUDIO:-0}" S1_AUDIO_FIFO="$S1_WORK/audio.fifo" \
       S1_CPUSW_FILE=/data/s1cpusw.input \
       S1_PIVOT="${S1_PIVOT:-0}" S1_HOLDOFF="$S1_WORK/holdoff"
rm -f "$S1_WORK/holdoff"    # a stale holdoff would park the loop before run 1
# S1_PIVOT=1: checkpointable boot (pivot_root instead of chroot), the save-
# state prerequisite (item 87).  Same game, same devices; that run's game
# stdout moves to <rootfs>/dump/game.out.  See emu_root.sh.
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

# 6c. the live switch-map walk, for a title with no curated map.  It waits for
#     the game to register its switches (a couple of minutes on a cold boot),
#     then writes s1switches.json; the switch window and the ball keeper both
#     pick the file up while they run, so the names, the play keys and the
#     trough all start working without a restart.  Best-effort and quiet: a
#     title it cannot read simply leaves the window on its raw matrix grid.
if [ "${S1_SWMAP_LIVE:-0}" = "1" ]; then
    setsid python3 "$HERE/s1swmap.py" --work "$S1_WORK" \
        --out "$S1_WORK/s1switches.json" --wait "${S1_SWMAP_WAIT:-600}" \
        >"$S1_WORK/s1swmap.log" 2>&1 &
    log "Reading this title's switch names from the running game…"
fi

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
    # VERIFIED launch, with one retry.  Seen live (2026-08-31, David's first
    # app-started pivot run): the keeper died between fork and its first
    # print — zero log output, no dmesg record — while nodebus, launched the
    # same setsid way 25 s earlier, survived.  Unreproduced since; the
    # watchdog turns a silent death into either a healthy retry or a spoken
    # line, and the game without a keeper is exactly the "stuck on LOCATING
    # PINBALLS" report.  The proof of life is the keeper's own first act:
    # writing s1auto.input (its held-trough bitmap).
    _keeper_up() {
        setsid python3 "$HERE/s1ball.py" daemon --work "$S1_WORK" \
            >"$S1_WORK/s1ball.log" 2>&1 < /dev/null &
        for _i in $(seq 1 25); do
            [ -s "$S1_WORK/s1auto.input" ] && return 0
            sleep 0.2
        done
        return 1
    }
    if _keeper_up; then
        log "Ball keeper up (S1_BALL=0 to disable)."
    elif _keeper_up; then
        log "Ball keeper up (second try — first launch died silently)."
    else
        log "WARNING: the ball keeper did not come up — the game will sit on"
        log "LOCATING PINBALLS. See s1ball.log; relaunch by hand:"
        log "  wsl -u root python3 $HERE/s1ball.py daemon --work $S1_WORK"
    fi
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
