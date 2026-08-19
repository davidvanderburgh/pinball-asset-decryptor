#!/bin/bash
# The ONE place that knows where things live.  Every other script in this rig
# sources this and never hard-codes a path - the Spike 2 rig's hardest-won rule
# is "never let two scripts define the same fact" (plans/TODO.md).
#
# Override any of these from the environment before sourcing.

# Where the restored JJP game image lives (loop-mounted READ ONLY).
: "${JJP_BASE:=/var/tmp/jjp_wonka}"
: "${JJP_ROOT:=$JJP_BASE/root}"        # sda3 = the Ubuntu root + /jjpe
: "${JJP_BOOTP:=$JJP_BASE/boot}"       # sda2 = kernel/initrd
: "${JJP_PERM:=$JJP_BASE/perm}"        # sda4 = persistent (scores/video)

# The writable jail the game actually runs in.  overlayfs: the image is the
# read-only lower, a tmpfs is the upper, so a run can NEVER modify the image.
: "${JJP_JAIL:=/var/tmp/jjp_run}"
: "${JJP_OVL:=/var/tmp/jjp_ovl}"
: "${JJP_OVL_SIZE:=3G}"

# Title.  setenv.sh inside the image is authoritative; this is the fallback.
: "${JJP_GAME:=Wonka}"
: "${JJPEDIR:=/jjpe/gen1}"

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
