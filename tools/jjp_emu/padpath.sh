#!/bin/bash
# The ONE place that knows where things live.  Every other script in this rig
# sources this and never hard-codes a path - the Spike 2 rig's hardest-won rule
# is "never let two scripts define the same fact" (plans/TODO.md).
#
# Override any of these from the environment before sourcing.

# --- path helpers ----------------------------------------------------------

# A Windows path from the GUI's file dialog -> a WSL path.  Doing this HERE
# means every script accepts either spelling and none of them has its own idea
# of the conversion.
jjp_norm_path() {
    case "$1" in
        [A-Za-z]:*)
            printf '/mnt/%s%s\n' \
                "$(printf '%s' "${1%%:*}" | tr 'A-Z' 'a-z')" \
                "$(printf '%s' "${1#*:}" | tr '\\' '/')" ;;
        *) printf '%s\n' "$1" ;;
    esac
}

# An ISO path -> the slug its restored filesystem is cached under.
jjp_slug() {
    basename "$(jjp_norm_path "$1")" \
        | sed 's/\.[Ii][Ss][Oo]$//' \
        | tr -c 'A-Za-z0-9._-' '_' \
        | sed 's/_*$//'
}

# --- where the image lives -------------------------------------------------
#
# KEYED ON THE ISO, not a fixed directory.  It used to be a literal
# /var/tmp/jjp_wonka, which meant a second title mounted nothing: mount.sh saw
# that path already mounted and returned "already mounted" no matter which ISO
# had been asked for, so the GUI's picker appeared to do nothing at all.
#
# Each ISO therefore gets its own restore, and they coexist - switching back to
# a title you have already run is instant rather than another multi-GB restore.
#
# Scripts that are NOT given an ISO (status.sh, run_game.sh, a poll from the
# GUI) read the pointer mount.sh leaves behind, so they follow whatever was
# mounted last without having to be told again.
: "${JJP_CURRENT:=/var/tmp/jjp_current}"
: "${JJP_ISO:=}"
if [ -n "$JJP_ISO" ]; then
    : "${JJP_BASE:=/var/tmp/jjp_$(jjp_slug "$JJP_ISO")}"
elif [ -r "$JJP_CURRENT" ]; then
    : "${JJP_BASE:=$(cat "$JJP_CURRENT")}"
else
    : "${JJP_BASE:=/var/tmp/jjp_image}"
fi
: "${JJP_ROOT:=$JJP_BASE/root}"        # sda3 = the Ubuntu root + /jjpe
: "${JJP_BOOTP:=$JJP_BASE/boot}"       # sda2 = kernel/initrd
: "${JJP_PERM:=$JJP_BASE/perm}"        # sda4 = persistent (scores/video)

# The writable jail the game actually runs in.  overlayfs: the image is the
# read-only lower, a tmpfs is the upper, so a run can NEVER modify the image.
: "${JJP_JAIL:=/var/tmp/jjp_run}"
: "${JJP_OVL:=/var/tmp/jjp_ovl}"
: "${JJP_OVL_SIZE:=3G}"

# Title.  setenv.sh inside the image is authoritative and jjp_title() asks it;
# this is only the fallback for when nothing is mounted yet.
: "${JJP_GAME:=Wonka}"
: "${JJPEDIR:=/jjpe/gen1}"

# The mounted image's own title, asked of the image rather than assumed.  This
# is what makes the rig title-agnostic: nothing downstream should contain the
# word "Wonka".
jjp_title() {
    local d
    for d in "$JJP_ROOT$JJPEDIR"/*/; do
        [ -x "$d/game" ] && basename "$d" && return 0
    done
    printf '%s\n' "$JJP_GAME"
}

# Logs, on the WSL side (outside the jail) so a wedged run is still readable.
: "${JJP_LOG_DIR:=/var/tmp}"
: "${JJP_GAME_LOG:=$JJP_LOG_DIR/jjp_game.log}"
: "${JJP_PID_FILE:=$JJP_LOG_DIR/jjp_game.pid}"

# Sentinel LDK (the purple dongle).  0529:0001 is the HASP HL key.
: "${JJP_HASP_VIDPID:=0529:0001}"
: "${JJP_AKSUSBD:=/usr/sbin/aksusbd_x86_64}"
: "${JJP_HASPLMD:=/usr/sbin/hasplmd_x86_64}"

# WSLg.  These are what makes a Linux game draw and speak on a Windows desktop.
: "${JJP_DISPLAY:=:0}"
: "${JJP_PULSE:=unix:/mnt/wslg/PulseServer}"
: "${JJP_PULSE_COOKIE:=/home/david/.config/pulse/cookie}"
