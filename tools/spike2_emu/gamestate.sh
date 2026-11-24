#!/bin/bash
# gamestate.sh - WHERE THE GAME IS, decided in ONE place.
#
# Sourced, not run:  . "$S/gamestate.sh"
#
# WHY THIS FILE EXISTS. Two scripts answered "has the game reached attract
# mode?" and they answered it DIFFERENTLY, so the rig acted on one answer and
# reported the other. Measured 2026-08-05 on a live run, with the game sitting
# in attract mode on its high-score screen (screenshot-confirmed):
#
#   autoattract.sh : "past Tech Alerts after 3 press(es)"   <- correct
#   status.sh      : state=techalerts                       <- wrong, and this
#                                                              is the one the
#                                                              app shows David
#
# autoattract.sh had already been through this and had written the lesson down
# in its own comments; status.sh kept the discredited test. That is the same
# drift that let alive.sh report a clean machine over seven leaked processes.
# So: one definition, one file, and both callers source it.
#
# THE DISCREDITED TESTS, for anyone tempted to reinvent them:
#
# 1. Counting `gst] factory_make` and calling >10 "past Tech Alerts". It worked
#    by accident and only while the video bug was live - the game used to tear
#    the pipeline down and rebuild it ~25 times a second, so ten arrived within
#    half a second of reaching attract. With that bug fixed a WHOLE RUN makes
#    about eight, which is why the app sat at "Waiting at Tech Alerts" forever
#    while the game played its attract loop. The proxy was measuring the bug,
#    and the bug is gone.
#
# 2. `factory_make("filesrc")` >= 1, i.e. "the game has opened a clip". Correct
#    on godzilla_pro and jaws_le, and DEAD WRONG on star_wars_le, measured
#    2026-08-10: that title serves clips WHILE SITTING ON the Tech Alerts
#    screen (ch0 looped one 168-frame clip from t=2 s, continuously, on both
#    sides of the Service Back press), so autoattract said "already past Tech
#    Alerts; nothing to do" and the game sat on the alerts for ever unless a
#    human pressed. Its attract clip set is a SUPERSET of its alerts clip set -
#    nothing on the video side can see this state, the alerts screen is a UI
#    overlay on a show that is already running underneath.

# `grep -c` PRINTS 0 and ALSO exits non-zero when it finds nothing, so the
# idiomatic `|| echo 0` emits "0\n0" and breaks every arithmetic use. Take the
# value and default it only when grep produced nothing at all.
gs_count() {
    local c=""
    [ -r "$2" ] && c=$(grep -ac "$1" "$2" 2>/dev/null)
    echo "${c:-0}"
}

# The game has reached its boot screen: the three factories built at t=0
# (qtdemux, queue, vpudec) are the video bring-up probe.
gs_booted() { [ "$(gs_count 'gst\] factory_make' "$1")" -ge 3 ]; }

# PAST TECH ALERTS = THE ATTRACT LIGHT SHOW IS RUNNING. The shim prints
# `[led] light show running` ONCE, when 30 lamp-class commands (97/a2..a6/
# b4/b5, any board; each lamp a swelf-family frame writes counts as one
# since PAD-255) land inside 3 seconds - a RATE, not a count, because a
# stray press entering the service menu emits a small lamp burst and a bare
# 10-count tripped on exactly that (star_wars, 2026-08-10). Measured on the
# full godzilla_pro boot trace: the whole Tech Alerts wait carried 2 such
# frames (strip-board boot config) against ~40/s sustained in attract, so
# attract declares within its first second and nothing else can. Unlike every
# video-side proxy this is the game's own OUTPUT deciding to run the show, and
# it is title-independent - no node numbering, no clip identity. This is the
# test that agrees with a screenshot of the screen, on the title that killed
# test 2. (Emitter: led_publish() in hwshim.c, before its insert-node gate.)
#
# ★ AND THE RATE IS ONLY HALF OF IT SINCE PAD-129: the line is printed when 30
# lamp commands land inside 3 seconds AND the published picture has CHANGED
# inside the same 3 seconds. A rate on its own says a board is being talked
# to, which is not the same claim: a Home Edition rewrites its one board's
# twenty levels, unchanged, about eleven times a second from boot, so this
# said "attract" at 12.3 s over jurassic_park_the_pin sitting on its alerts
# screen, autoattract.sh stood down without pressing anything, and the machine
# stayed there. led_show_gate() in hwshim.c carries the measurements.
#
# A run whose lamp traffic never moves the picture now says so in its own log,
# once - `[led] lamp traffic with a STILL picture` - which is deliberately not
# this phrase: it is the shape of a machine parked on Tech Alerts, and reading
# it as attract is the fault above.
gs_past_alerts() { [ "$(gs_count '\[led\] light show running' "$1")" -ge 1 ]; }

# THE ATTRACT SHOW IS ON THE SCREEN (PAD-1541): past Tech Alerts, AND the game
# has opened a video clip since its light show began (gstvid.c's `[vid] chN
# owns source` / `location ->`). The lamps come first: the game starts its
# light show, then loads the attract scene and its clips, and on the rig that
# load is the card's and the CPU's time, not the game's, so the gap does not
# shrink at 4x. A Start inside the gap is not merely ignored: elvira3-1.13's
# Start handler calls through the attract scene's VideoSurface before it is
# bound and dies on a null pointer (pc 0x1c96fc, every run, any NVRAM), so
# whatever presses Start waits for this. Measured across ~120 rig runs of the
# other titles: their first clip always opened before the Start, which is why
# only Elvira 3 showed it.
gs_show_up() {
    [ -r "$1" ] || return 1
    awk '/\[led\] light show running/ { lit = 1; next }
         lit && /\[vid\] ch[0-9]+ (owns source|location ->)/ { ok = 1; exit }
         END { exit !ok }' "$1" 2>/dev/null
}

# gs_wait_show <log> [wall seconds, default PAD_SHOW_WAIT or 120]: until gs_show_up, the guest gone, or the cap.
# 0 = the show is up; 1 = not by the cap (a title with no clip in its attract: the caller goes on regardless).
gs_wait_show() {
    local end=$(( $(date +%s) + ${2:-${PAD_SHOW_WAIT:-120}} ))
    until gs_show_up "$1"; do
        [ "$(date +%s)" -lt "$end" ] || return 1
        # this slot's guest only (padpath.sh's pad_pids, where the caller has it): another rig's game is not ours
        if declare -F pad_pids > /dev/null; then [ -n "$(pad_pids -x game | head -1)" ] || return 1; fi
        sleep 1
    done
}

# One word for the whole state, for anything that just wants to print it.
# Deliberately does NOT try to tell attract mode from the operator menu or from
# a ball in play: nothing measurable from outside distinguishes them yet, and
# inventing a distinction here is how the last wrong answer got written.
gs_state() {
    gs_past_alerts "$1" && { echo attract; return; }
    gs_booted "$1"      && { echo techalerts; return; }
    echo booting
}
