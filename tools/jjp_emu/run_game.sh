#!/bin/bash
# Launch the JJP game in the jail.  This is the launch that WORKS as of
# 2026-08-19: it reaches a live, stable game process with the dongle attached.
#
# WHAT IT DELIBERATELY DOES NOT DO.  It does not use the image's own
# scripts/rungame.sh.  That script is a `while true` supervisor that reboots the
# machine on exit codes 42/68/69 - fine on a cabinet, wrong here, where "reboot"
# would mean the WSL distro.  We run the game directly and let watch.sh decide
# what an exit code means.  The environment below is exactly what rungame.sh
# exports, minus the reboots.
#
# EXIT CODES (from the image's own rungame.sh case table):
#     1 dongle missing   42 net/delta update   43 settings restore
#    44 setting changed  68 maintenance reboot (hostname set)
#    69 maintenance reboot  127 exe not found  254 escape pressed
#   255 unexpected exit   137 SIGKILL (ours - it was still running)
#
# 68 IS NORMAL ON A FIRST RUN, and this script now handles it.  The golden disk
# ships a Guns N' Roses hostname; on first boot the game renames itself
# (WONKA-<n>) and asks to be restarted.  A FRESH JAIL IS A FIRST BOOT EVERY
# TIME, because the overlay's upper layer starts empty - so without the restart
# loop below the game appears to die instantly with an empty log, which is
# exactly how this presented.  Restarts are bounded (JJP_MAX_RESTARTS) so a
# genuine crash loop cannot spin forever.
#
# We deliberately do NOT use the image's own scripts/rungame.sh, which answers
# 42/68/69 by rebooting the machine - here that would mean the WSL distro.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

[ "$(id -u)" = "0" ] || { echo "run_game.sh: must run as root" >&2; exit 2; }
mountpoint -q "$JJP_JAIL" || { echo "run_game.sh: jail not mounted; run jail.sh" >&2; exit 3; }

DETACH=0; CAP=""
while [ $# -gt 0 ]; do
    case "$1" in
        --detach) DETACH=1 ;;
        --cap) shift; CAP="$1" ;;      # seconds; SIGKILL after.  Native x86-64,
                                       # so a bounded run is safe here (unlike
                                       # the Spike 2 qemu rig, where `timeout`
                                       # leaks 140%-CPU processes forever).
        *) echo "unknown arg: $1" >&2; exit 64 ;;
    esac
    shift
done

# The hardware shim is opt-in.  Set JJP_SHIM=1 (build it first with build.sh)
# to give the game a fake set of playfield boards it can read switches from.
# Without it the game still runs - missing boards are non-fatal - it just never
# sees a switch close.
SHIM_ENV=""
if [ "${JJP_SHIM:-0}" = "1" ]; then
    SO=${JJP_SHIM_SO:-/var/tmp/jjphwshim.so}
    if [ ! -f "$SO" ]; then
        echo "run_game.sh: JJP_SHIM=1 but $SO is missing; run build.sh" >&2
        exit 5
    fi
    # The .so must be reachable from INSIDE the jail.
    cp -f "$SO" "$JJP_JAIL/tmp/jjphwshim.so"
    SHIM_ENV='export LD_PRELOAD=/tmp/jjphwshim.so'
    [ -n "${JJP_SHIM_DEBUG:-}" ] && SHIM_ENV="$SHIM_ENV; export JJP_SHIM_DEBUG=1"
fi

# The JJP mode SDK runtime (PAD-1335/1337, jjpmodes.c), opt-in: JJP_MODS_SO=<path>
# and JJP_MODS_DIR=<folder of title.cfg + *.mode>.  Both are copied into the
# jail as /tmp/padmodes/jjpmodes.so + /tmp/padmodes/modes/ - the layout a
# PAD-written install ISO puts at $JJPEDIR/padmodes - and preloaded beside the
# hardware shim.  Its log goes to /jjpe/temp/jjpmodes.log inside the jail.
# An image that carries the SDK itself (scripts/padmodes.sh, written by
# mkjjpmodes.py) needs neither: the RUN below sources that hook exactly where
# the machine's rungame.sh does.  JJP_MODS_SO wins over an image's own copy.
MODS_ENV=
if [ -n "${JJP_MODS_SO:-}" ]; then
    [ -f "$JJP_MODS_SO" ] || { echo "run_game.sh: JJP_MODS_SO=$JJP_MODS_SO is missing" >&2; exit 5; }
    rm -rf "$JJP_JAIL/tmp/padmodes"; mkdir -p "$JJP_JAIL/tmp/padmodes/modes"
    cp -f "$JJP_MODS_SO" "$JJP_JAIL/tmp/padmodes/jjpmodes.so"
    if [ -n "${JJP_MODS_DIR:-}" ]; then
        [ -d "$JJP_MODS_DIR" ] || { echo "run_game.sh: JJP_MODS_DIR=$JJP_MODS_DIR is not a folder" >&2; exit 5; }
        cp -f "$JJP_MODS_DIR"/* "$JJP_JAIL/tmp/padmodes/modes/" 2>/dev/null
    fi
    MODS_ENV='export PADMODES_RIG=1; export JJP_MODS_DIR=/tmp/padmodes/modes; export LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD }/tmp/padmodes/jjpmodes.so"'
    # proof runs only: start a game mode from a switch (jjpmodes.c, test_hook)
    [ -n "${JJP_MODS_TEST_GAMEMODE:-}" ] && MODS_ENV="$MODS_ENV; export JJP_MODS_TEST_GAMEMODE='$JJP_MODS_TEST_GAMEMODE' JJP_MODS_TEST_SWITCH='${JJP_MODS_TEST_SWITCH:-}'"
fi
rm -f "$JJP_JAIL/jjpe/temp/jjpmodes.log"

# PAD multi-boot (item 117).  JJP_SELECT is the three-way switch padpath.sh
# documents; it rides into the chroot as an export so the RUN can read it.
# JJP_SELECT_LOG=1 makes the hook hand the selector `--log /jjpe/temp/jjpselect.log`
# (PADSELECT_SELECT_LOG, the same knob the hook's tests use): a scripted run
# waits for that log's `menu:` line before it pokes a button, because a poke
# that lands while the menu is still starting is simply lost - the first run
# of 2026-09-13 recorded no choice for exactly that reason.
SELECT_ENV="export JJP_SELECT='${JJP_SELECT:-}'"
if [ -n "${JJP_SELECT_LOG:-}" ]; then
    SELECT_ENV="$SELECT_ENV; export PADSELECT_SELECT_LOG=/jjpe/temp/jjpselect.log"
    rm -f "$JJP_JAIL/jjpe/temp/jjpselect.log"
fi
# JJP_SELECT_DUMP=1 (item 120): the menu also writes everything it mixes to
# /jjpe/temp/jjpselect.mix.raw (s16le 44100 Hz stereo, the selector's
# --audio-dump) - how a proof run hears the move sound follow the Volume+/-
# buttons on a MUTED rig, where the sink itself is the null device.
if [ -n "${JJP_SELECT_DUMP:-}" ]; then
    SELECT_ENV="$SELECT_ENV; export PADSELECT_AUDIO_DUMP=/jjpe/temp/jjpselect.mix.raw"
    rm -f "$JJP_JAIL/jjpe/temp/jjpselect.mix.raw"
fi

# NO GLOBAL sync() (PAD-1340).  The game's NVRAM and scene-preload threads call
# libc sync() (syscall 162) after they write.  Under WSL2 sync(2) is GLOBAL: it
# also flushes the virtiofs mounts of the Windows drives, waits on the Windows
# side (ksys_sync -> fuse_sync_fs -> request_wait_answer) and never returns.
# The thread sits in D state, SIGKILL cannot finish it, the run is left as a
# zombie whose PulseAudio stream stays open, and only `wsl --shutdown` clears
# it.  PAD-1337 left nine of them on 2026-11-15, and every later run queued
# behind them in super_lock.  The Spike 2 rig's no-op sync (pad_nosync.c, the
# same source) built for x86-64 and preloaded for EVERY process in the jail via
# its /etc/ld.so.preload (the overlay's upper layer: the image is never
# written), so the game's scripts' `sync` is covered too.  syncfs()/fsync() are
# left alone, and they are all the NVRAM's durability needs on a tmpfs upper.
jjp_nosync() {
    local src="$HERE/../spike2_emu/pad_nosync.c" so="${JJP_NOSYNC_SO:-/var/tmp/pad_nosync_x86_64.so}"
    if [ ! -f "$so" ] || [ "$src" -nt "$so" ]; then
        gcc -std=gnu17 -fno-stack-protector -fPIC -shared -O2 -nostdlib \
            -Wl,-soname,pad_nosync.so -o "$so.tmp" "$src" && mv -f "$so.tmp" "$so" || {
            echo "run_game.sh: WARNING - could not build $so; the game's sync() can wedge this run" >&2
            return 0; }
    fi
    install -m 0755 "$so" "$JJP_JAIL/lib/pad_nosync.so"
    touch "$JJP_JAIL/etc/ld.so.preload"
    grep -qx /lib/pad_nosync.so "$JJP_JAIL/etc/ld.so.preload" \
        || echo /lib/pad_nosync.so >> "$JJP_JAIL/etc/ld.so.preload"
}
jjp_nosync

# NO REBOOTS FROM THE GAME (PAD-1349).  The game's own scripts reboot the
# machine when they are done: hotfix.sh (the Update USB screen's hot fix),
# waitforusbremoval.sh, factoryreset.pl.  In the jail reboot/poweroff/halt/
# shutdown are links to systemctl, which must never get a chance to reach this
# WSL distro.  Each is replaced, in the overlay's upper layer only, by a note in
# /jjpe/temp/rig_reboot.log; a proof restarts the game itself where the machine
# would have rebooted.
jjp_noreboot() {
    local b f
    for b in reboot poweroff halt shutdown; do
        f="$JJP_JAIL/usr/sbin/$b"
        grep -qs "PAD rig: no reboots" "$f" && continue
        rm -f "$f"
        printf '#!/bin/sh\n# PAD rig: no reboots from the game (run_game.sh, PAD-1349)\necho "$(date "+%%F %%T") %s $*: asked for, not done on the rig" >> /jjpe/temp/rig_reboot.log\nexit 0\n' "$b" > "$f"
        chmod 0755 "$f"
    done
}
jjp_noreboot

# MUTED UNLESS ASKED (PAD-1340).  audio.sh's PAD_AUDIO=0 null asound.conf was
# not enough: Allegro's autodetect tries PulseAudio BEFORE ALSA, and with
# PULSE_SERVER pointing at WSLg and the desktop cookie in the jail it reached
# the speakers directly - every hidden PAD-1337 run played Guns N' Roses on
# David's speakers.  A muted run now gets a Pulse server that does not exist and
# no cookie, so Allegro falls through to ALSA's null device, and any
# allegro5.cfg an earlier audible run left (driver=pulseaudio, which does NOT
# fall back) is removed.  PAD_AUDIO=1 (the app's Emulate JJP tab) is unchanged.
if [ "${PAD_AUDIO:-0}" = "1" ]; then
    RUN_PULSE=$JJP_PULSE
else
    RUN_PULSE=unix:/nonexistent/pad-muted
    rm -f "$JJP_JAIL/root/.config/pulse/cookie" "$JJP_JAIL$JJPEDIR/$(jjp_title)/allegro5.cfg"
    echo "run_game.sh: audio MUTED (PAD_AUDIO=1 to hear it)"
fi

RUN='
  export JJPEDIR='"$JJPEDIR"'
  . $JJPEDIR/setenv.sh
  export GAMENAME
  export GAMEDIR=$JJPEDIR/$GAMENAME
  export DISPLAY='"$JJP_DISPLAY"'
  export PULSE_SERVER='"$RUN_PULSE"'
  export HOME=/root
  '"$SHIM_ENV"'
  '"$MODS_ENV"'
  '"$SELECT_ENV"'
  # PAD custom modes (PAD-1337): the hook a mode install ISO adds to rungame.sh,
  # sourced at the same point (after runonce.sh, before the game loop).  It
  # exports LD_PRELOAD for ./game.  A rig run with JJP_MODS_SO set skips it.
  if [ -z "${PADMODES_RIG:-}" ] && [ -r $JJPEDIR/scripts/padmodes.sh ]; then
    . $JJPEDIR/scripts/padmodes.sh
    echo "[rig] image hook padmodes.sh: LD_PRELOAD=$LD_PRELOAD"
  fi
  # PAD multi-boot (item 117): the hook root A carries on a multi-boot install
  # (padselect.sh, item 115), run at the point the machine'"'"'s rungame.sh runs it -
  # display up, before ./game - and in the mount namespace of THIS run (the
  # unshare -m below), so its binds die with the run.  BEFORE the cd: a shell
  # already sitting in $GAMEDIR would keep the old directory under the bind and
  # ./game would be image 0 whatever the menu said.  JJP_SELECT: unset = ask the
  # image, 1 = insist on the menu, 0 = skip it.
  if [ "${JJP_SELECT:-}" != "0" ] && [ -x $JJPEDIR/scripts/padselect.sh ]; then
    $JJPEDIR/scripts/padselect.sh
  elif [ "${JJP_SELECT:-}" = "1" ]; then
    echo "[rig] JJP_SELECT=1 but this image carries no $JJPEDIR/scripts/padselect.sh"
    exit 9
  fi
  echo "[rig] game tree: $(findmnt -n -o SOURCE,OPTIONS $GAMEDIR 2>/dev/null || echo "$GAMEDIR (no bind: image 0)")"
  cd $GAMEDIR
  n=0
  while [ $n -lt '"${JJP_MAX_RESTARTS:-6}"' ]; do
    ./game
    rc=$?
    case "$rc" in
      # 43/44/68 are "exit and be restarted" - a settings restore, a changed
      # setting, or the once-per-fresh-jail hostname reboot.  Restart, bounded.
      #
      # We do NOT try to detect a closed window and skip the restart here.  An
      # earlier attempt checked for the display socket inside the chroot and got
      # it wrong - the Xephyr :1 socket is not where the check looked, so a
      # perfectly normal exit-68 was read as "window closed" and the game was
      # never restarted, leaving a black screen.  It is also unnecessary:
      # closing the window makes the game lose its X server and exit 1 (an X I/O
      # error), which falls through to the "*" case and stops - and even a true
      # loop is capped by JJP_MAX_RESTARTS.
      43|44|68) n=$((n+1)); echo "[rig] game exit $rc - restarting ($n)" ;;
      # SAY THE CODE.  This used to exit silently, so a game that died the
      # moment it started left a log ending at "[rig] game tree:" and a tab
      # saying Stopped, with nothing anywhere to say why (David, 2026-09-13).
      *) echo "[rig] game exit $rc - not a restart code, stopping"; exit $rc ;;
    esac
  done
  echo "[rig] too many restarts; giving up"
  exit 1
'

# H0007 - "Sentinel key not found" - turned into a message that says what is
# ACTUALLY wrong, which is not always what it first looks like.
#
# H0007 COVERS TWO DIFFERENT FAULTS and they need opposite fixes:
#
#   * the key is not this TITLE's.  JJP keys are per-title: the envelope's AES
#     key differs per game and a key carries only its own title's crypto, so a
#     Wonka key H0007s on Godfather even though both present the same vendor
#     code and Feature 0.  Fix: plug in the right key.
#   * the key is fine but the LICENCE DAEMON cannot read it - a usbipd
#     passthrough that enumerated but that hasplmd never picked up.  Fix: the
#     key plumbing, and no amount of swapping keys helps.
#
# This used to report the first unconditionally, and on 2026-08-20 that cost an
# hour: it said "WRONG KEY ... plug in the GunsNRoses key" while the truth was
# that the daemon could see NO key at all - every title failed the same way,
# including the one whose key was plugged in.  The key was healthy (its USB
# descriptors read back 0529:0001 "Sentinel HL"), it simply never reached
# hasplmd.  So: report what can be checked, and name the way to tell them apart.
# key_visible() lives in padpath.sh - watch.sh needs the same answer to decide
# whether a retry can possibly help, and two scripts with their own idea of
# "is the key there" is exactly the split this rig has been bitten by before.
report_wrong_key() {
    grep -q 'H0007\|Sentinel key not found' "$JJP_GAME_LOG" 2>/dev/null || return 1
    if ! key_visible; then
        echo "NO KEY: $(jjp_title) exited because no Sentinel key is visible inside WSL."
        echo "  The key is not passed through (or the passthrough dropped).  From Windows:"
        echo "      usbipd attach --wsl --hardware-id $JJP_HASP_VIDPID"
        return 0
    fi
    echo "KEY NOT ACCEPTED: $(jjp_title) could not open the plugged-in Sentinel key."
    echo "  The key IS visible in WSL ($JJP_HASP_VIDPID), so this is one of two things:"
    echo "    1. it is ANOTHER TITLE's key - JJP keys are per-title; or"
    echo "    2. the licence daemon never picked it up, which no key swap will fix."
    echo "  Tell them apart - the Admin Control Center lists what the daemon can see:"
    echo "      curl -s http://127.0.0.1:1947/_int_/devices.html | grep -ci 'sentinel hl'"
    echo "  An EMPTY key list means (2), the plumbing.  Re-attach it from Windows:"
    echo "      usbipd detach --busid <N> && usbipd attach --wsl --busid <N>"
    echo "  and if that does not take, 'wsl --shutdown' and start the rig again."
    return 0
}

# The run gets a mount namespace of its OWN (unshare -m, private propagation):
# the multi-boot hook bind-mounts the chosen game tree over root A's and masks
# JJP's updater, and those mounts must vanish with the run instead of piling up
# in the host's table where unjail.sh would have to hunt them down.  Nothing the
# rig does from outside changes: the jail's own mounts were made in the host
# namespace and are inherited; only what the run adds is private.  status.sh
# asks about the bind from INSIDE the namespace (nsenter on the leader's pid).
NS="unshare -m --propagation private"

: > "$JJP_GAME_LOG"
if [ "$DETACH" = "1" ]; then
    setsid $NS chroot "$JJP_JAIL" /bin/bash -c "$RUN" >>"$JJP_GAME_LOG" 2>&1 &
    echo $! > "$JJP_PID_FILE"

    # WATCH the first few seconds instead of a flat `sleep 3` then one check.
    # Two things end this wait early, and both matter to the GUI:
    #
    #   * an H0007 - the plugged-in key does not decrypt THIS title.  A Sentinel
    #     key is per-title, so a Wonka key on Guns N' Roses prints H0007 at the
    #     very first envelope call (before the game touches boards or a display)
    #     and exits.  We fail fast with exit 7 and the WRONG KEY message the
    #     instant it appears - typically ~1 s - instead of waiting a flat 3 and
    #     then only noticing if the process already happened to be gone.
    #   * the game actually coming up - reported the moment it is up rather than
    #     after a fixed delay.
    #
    # "Up for two consecutive checks" avoids a race: a wrong-key game exists for
    # a heartbeat before it H0007s, and we must not read that heartbeat as a
    # healthy launch.  The window is bounded (JJP_LAUNCH_WAIT) so a genuine wedge
    # still returns.
    up=0
    for _ in $(seq 1 "${JJP_LAUNCH_WAIT:-12}"); do
        sleep 1
        if report_wrong_key; then
            exit 7
        fi
        # A live MENU counts as up: on a multi-boot image the run sits in
        # jjpselect for up to the conf's timeout before a game process exists.
        if [ "$(jjp_game_count)" != "0" ] || [ "$(jjp_select_count)" != "0" ]; then
            up=$((up + 1))
            [ "$up" -ge 2 ] && break
        else
            up=0
        fi
    done
    if [ "$up" -lt 2 ]; then
        # No H0007, but the game is not staying up either - it exited for some
        # other reason (see the exit-code table above).  Surface the log tail
        # rather than claiming a launch that did not happen.
        echo "run_game.sh: the game did not stay up and did not report a key error."
        tail -n 6 "$JJP_GAME_LOG" 2>/dev/null | sed 's/^/  game: /'
        exit 8
    fi
    echo "launched detached; pid=$(cat "$JJP_PID_FILE") procs=$(jjp_game_count) selector=$(jjp_select_count)"
    # JJP's game is always on a window (Xephyr, or WSLg's :0); audio.sh set
    # the sound from PAD_AUDIO.
    rigboard_post jjp 0 "$(cat "$JJP_PID_FILE")" "$(jjp_title)" "${PAD_TITLE:-}" 1 "${PAD_AUDIO:-0}"
    echo "log: $JJP_GAME_LOG"
else
    if [ -n "$CAP" ]; then
        setsid timeout -s KILL "$CAP" $NS chroot "$JJP_JAIL" /bin/bash -c "$RUN" >>"$JJP_GAME_LOG" 2>&1
    else
        setsid $NS chroot "$JJP_JAIL" /bin/bash -c "$RUN" >>"$JJP_GAME_LOG" 2>&1
    fi
    rc=$?
    report_wrong_key || true
    echo "EXIT CODE: $rc"
fi
