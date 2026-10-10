#!/bin/bash
# padselect.sh - the Barrels of Fun multi-boot hook (PAD-342).
#
# A multi-boot update puts this in /home/pinball/extracted/decrypt/padselect/
# and one line into ~/.bash_profile, just before the profile's loop starts the
# game: on the console, this runs first.  It shows the boot menu (bofselect,
# the same menu a Stern card and a JJP machine show), and then makes the
# chosen program THE program: /home/pinball/craze/GDCraze.x86_64, which the
# profile's ./startgame runs exactly as it always has.
#
#   images.conf   image=<program>|<title>|<subtitle>...  <program> is a file
#                 in extracted/decrypt/: GDCraze.x86_64 (image 0, the one BOF's
#                 updater installed) or pad_image1.bin ... (the install step
#                 rebuilt them, pad_install.sh)
#   programs      "<index> <file> <size> <md5> [<delta>]" per image, the
#                 builder's record; the size is what this checks every boot
#
# HOW A PROGRAM BECOMES THE GAME: a hard link.  craze/GDCraze.x86_64 is
# removed and linked to the chosen file - instant, no copy, no space - and
# craze/GAMEFILESIZE gets its size, so the profile's own check ("is the game
# the size the updater recorded?") is satisfied and never copies image 0 back
# over it.  The REMOVE comes first, always: a copy onto a hard link would
# write through it into the other image's file.
#
# EVERY FAILURE ENDS ON IMAGE 0, the machine's stock behaviour: no conf, one
# image, an update in progress, no menu program, a menu that dies or hangs
# (it is killed after its own timeout and a minute), a choice that names no
# usable program, a link that fails.  This script never exits non-zero into
# the profile and never blocks it.
#
# The root filesystem may be mounted read-only (BOF's game remounts it rw only
# around its own saves); when it is, it is made writable for the swap and put
# back read-only after.
#
# THE SWAP RUNS AS pinball, BUT BOF'S UPDATER RUNS AS ROOT (PAD-506).  A
# craze/GAMEFILESIZE the updater created is root's, so writing the size failed
# and every choice ended on image 0; an image the install step rebuilt is
# root's too, and a Linux that protects hard links will not let pinball link
# it, so it was copied (4 GB, every boot).  Before the menu opens, both are
# given to the user this runs as, with pinball's passwordless sudo.
#
# SOUND.  The menu mixes its own sounds (44100 Hz stereo, 16 bit), but it is
# one static program and cannot load the machine's sound library, so it
# streams the mix into a pipe (--audio fifo:) and the machine's own aplay
# plays it on the USB sound card the game uses.  The player starts only when
# the conf names a sound, and it is stopped and WAITED FOR before the game
# starts, so the game's sound server finds the card free.  No aplay, or no
# card: the menu is silent and nothing else changes.  aplay keeps an 80 ms
# buffer (-B), not its default half second, and the menu's mix runs 40 ms
# ahead of the clock (the BOF build's FIFO_LEAD_MS): together they are the
# lag between a flipper and its click, which was a second (David, 2026-10-04).
#
# PADSELECT_HOME moves /home/pinball (the tests); PADSELECT_NO_SUDO=1 runs the
# menu without sudo; PADSELECT_AUDIO_PLAYER replaces aplay (the tests) and
# PADSELECT_AUDIO_DEV names the ALSA device (default: the first USB sound card,
# else card 0).
H=${PADSELECT_HOME:-/home/pinball}
D=$H/extracted/decrypt
P=$D/padselect
CONF=$P/images.conf
PROGS=$P/programs
GAME=$H/craze/GDCraze.x86_64
SIZEF=$H/craze/GAMEFILESIZE
CHOICE=${PADSELECT_CHOICE:-/tmp/padselect.choice}
LOG=$P/padselect.log

[ -f "$CONF" ] || exit 0
[ -f "$LOG" ] && mv -f "$LOG" "$LOG.1" 2>/dev/null
{ exec 3>>"$LOG"; } 2>/dev/null || exec 3>/dev/null
exec 2>&3                         # nothing of this reaches the console the menu draws on
say() { echo "$(date '+%F %T') $*" >&3; }

SUDO=""
if [ -z "${PADSELECT_NO_SUDO:-}" ] && [ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1 \
   && sudo -n true 2>/dev/null; then
    SUDO="sudo -n"
fi

# ---- what the images are -------------------------------------------------
# image N's program: the first field of the Nth image= line
progs=()
while IFS= read -r line; do
    case "$line" in
        image=*) f=${line#image=}; progs+=("${f%%|*}") ;;
    esac
done < "$CONF"
n=${#progs[@]}
if [ "$n" -lt 2 ]; then say "$n image(s) in $CONF: no menu"; exit 0; fi
if [ -f "$H/GAMEUPDATING" ]; then say "an update is running: no menu"; exit 0; fi
if pgrep -x main >/dev/null 2>&1; then say "the updater is running: no menu"; exit 0; fi

# the size the builder recorded for program file $1 ("" = none recorded)
want_size() {
    [ -f "$PROGS" ] || return 0
    while read -r idx file size rest; do
        [ "$file" = "$1" ] && { echo "$size"; return 0; }
    done < "$PROGS"
}

# is image $1 usable: its file there, the recorded size
usable() {
    local f=$D/${progs[$1]} want have
    case "${progs[$1]}" in ""|*/*|.*) return 1 ;; esac
    [ -f "$f" ] || return 1
    want=$(want_size "${progs[$1]}")
    have=$(stat -c %s "$f" 2>/dev/null) || return 1
    [ -z "$want" ] || [ "$want" = "$have" ]
}

# ---- the root filesystem, writable for the swap --------------------------
was_ro=0
if awk '$2 == "/" { split($4, o, ","); for (i in o) if (o[i] == "ro") r = 1 } END { exit !r }' /proc/mounts 2>/dev/null; then
    was_ro=1
    if $SUDO mount -o remount,rw / 2>/dev/null; then say "root was read-only: remounted rw for the swap"
    else say "root is read-only and could not be remounted"; fi
fi
put_back() {
    sync
    if [ "$was_ro" = 1 ]; then $SUDO mount -o remount,ro / 2>/dev/null && say "root back to read-only"; fi
}

# ---- the swap's files, this user's (the header's THE SWAP RUNS AS pinball) --
# GAMEFILESIZE ours and writable, every image's program ours; root needs neither
if [ "$(id -u)" != 0 ]; then
    me="$(id -un):$(id -gn)"
    if [ -e "$SIZEF" ] && { [ ! -O "$SIZEF" ] || [ ! -w "$SIZEF" ]; }; then
        say "$SIZEF: $(stat -c '%U:%G mode %a' "$SIZEF"), the swap could not write it"
        $SUDO chown "$(id -u):$(id -g)" "$SIZEF" && say "$SIZEF: owner $me" \
            || say "$SIZEF: could not chown it to $me"
        $SUDO chmod 644 "$SIZEF" && say "$SIZEF: mode 644" \
            || say "$SIZEF: could not chmod it to 644"
    fi
    for f in "${progs[@]}"; do
        case "$f" in ""|*/*|.*) continue ;; esac
        [ -f "$D/$f" ] && [ ! -O "$D/$f" ] || continue
        was=$(stat -c %U:%G "$D/$f")
        if $SUDO chown "$(id -u):$(id -g)" "$D/$f"; then say "$f: owner $me (was $was), so it can be linked"
        else say "$f: $was's, could not chown it to $me: it is copied, not linked"; fi
    done
fi

# ---- the menu --------------------------------------------------------------
timeout_s=$(sed -n 's/^timeout=\([0-9][0-9]*\).*/\1/p' "$CONF" | tail -1)
[ -n "$timeout_s" ] || timeout_s=10
[ "$timeout_s" -gt 0 ] 2>/dev/null || timeout_s=600       # 0 = wait for ever: still bounded here

# ---- sound (the header's SOUND) --------------------------------------------
# does the conf name a sound: sound_move= / sound_confirm=, or a card's music or
# confirm field (the 6th and 7th of an image= or group= line)
has_sound() {
    grep -qE '^sound_(move|confirm)=[^[:space:]]' "$CONF" && return 0
    awk -F'|' '/^(image|group)=/ { for (i = 6; i <= 7; i++) if ($i != "" && $i != "none") f = 1 }
               END { exit !f }' "$CONF"
}
AUDIO=none
FIFO=""
player=""
start_player() {
    local play=${PADSELECT_AUDIO_PLAYER:-aplay} dev=${PADSELECT_AUDIO_DEV:-} card
    if ! command -v "${play%% *}" >/dev/null 2>&1; then
        say "sound: no ${play%% *} on this machine: the menu is silent"; return 0
    fi
    if [ -z "$dev" ]; then
        card=$(awk '/USB-Audio/ { print $1; exit }' /proc/asound/cards 2>/dev/null)
        [ -n "$card" ] || card=$(awk '$1 ~ /^[0-9]+$/ { print $1; exit }' /proc/asound/cards 2>/dev/null)
        dev="plughw:${card:-0},0"
    fi
    FIFO=$(mktemp -u /tmp/padselect.audio.XXXXXX) || return 0
    if ! mkfifo -m 600 "$FIFO" 2>/dev/null; then
        say "sound: cannot make the pipe $FIFO: the menu is silent"; FIFO=""; return 0
    fi
    # bounded like the menu; the player reads the pipe until the menu closes it
    timeout -k 2 $((timeout_s + 70)) $SUDO $play -q -t raw -f S16_LE -r 44100 -c 2 -B 80000 -F 20000 \
        -D "$dev" "$FIFO" \
        </dev/null >/dev/null 2>>"$P/audio.log" &
    player=$!
    AUDIO="fifo:$FIFO"
    say "sound: $(basename "${play%% *}") on $dev, pid $player"
}
stop_player() {
    local i
    if [ -n "$player" ]; then
        # the menu closing the pipe ends the player by itself; this is for one that did not
        for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$player" 2>/dev/null || break; sleep 0.2; done
        kill "$player" 2>/dev/null
        for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$player" 2>/dev/null || break; sleep 0.2; done
        kill -9 "$player" 2>/dev/null
        wait "$player" 2>/dev/null
        say "sound: player stopped: the sound card is free for the game"
    fi
    [ -n "$FIFO" ] && rm -f "$FIFO"
    player=""; FIFO=""
}

choice=""
if [ -x "$P/bofselect" ]; then
    rm -f "$CHOICE"
    if has_sound; then start_player; else say "sound: none in the conf"; fi
    say "menu: $n images, timeout ${timeout_s}s"
    timeout -k 5 $((timeout_s + 60)) $SUDO "$P/bofselect" --input fast --conf "$CONF" --out "$CHOICE" --last "$P/last" \
        --log "$P/bofselect.log" --audio "$AUDIO" --no-invert --font "$P/font.ttf" \
        ${PADSELECT_MENU_ARGS:-} </dev/null >/dev/null 2>&1
    rc=$?
    stop_player
    choice=$(head -c 16 "$CHOICE" 2>/dev/null | tr -dc '0-9')
    say "menu exit $rc, choice '${choice}'"
else
    say "no menu program at $P/bofselect"
fi
case "$choice" in ''|*[!0-9]*) choice=0 ;; esac
[ "$choice" -lt "$n" ] || choice=0
if ! usable "$choice"; then
    say "image $choice (${progs[$choice]}) is not usable: image 0"
    choice=0
fi

# ---- the swap ---------------------------------------------------------------
swap_in() {
    local src=$D/${progs[$1]} size
    size=$(stat -c %s "$src") || return 1
    if [ -e "$GAME" ] && [ "$(stat -c %i "$GAME" 2>/dev/null)" = "$(stat -c %i "$src")" ]; then
        say "image $1 (${progs[$1]}) is already the game"
    else
        rm -f "$GAME" || return 1
        if ! ln "$src" "$GAME" 2>/dev/null; then
            say "cannot link ${progs[$1]} (another filesystem, or another user's?): copying"
            cp -f "$src" "$GAME" || { rm -f "$GAME"; return 1; }
        fi
        say "image $1 (${progs[$1]}, $size bytes) is the game"
    fi
    echo "$size" > "$SIZEF"
}
if ! swap_in "$choice"; then
    say "the swap to image $choice failed: image 0"
    if [ "$choice" != 0 ]; then swap_in 0 || say "the swap to image 0 failed too: the profile's own check restores it"; fi
fi
put_back
exit 0
