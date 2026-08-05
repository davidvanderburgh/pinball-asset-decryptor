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
# THE DISCREDITED TEST, for anyone tempted to reinvent it: counting
# `gst] factory_make` and calling >10 "past Tech Alerts". It worked by accident
# and only while the video bug was live - the game used to tear the pipeline
# down and rebuild it ~25 times a second, so ten arrived within half a second
# of reaching attract. With that bug fixed a WHOLE RUN makes about eight, which
# is why the app now sits at "Waiting at Tech Alerts" forever while the game
# plays its attract loop. The proxy was measuring the bug, and the bug is gone.

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

# PAST TECH ALERTS = THE GAME HAS OPENED A CLIP, which is what `filesrc` means.
# The bring-up probe carries no source; only a real attract clip adds filesrc.
# This is the test that agrees with a screenshot of the screen.
gs_past_alerts() { [ "$(gs_count 'factory_make("filesrc"' "$1")" -ge 1 ]; }

# One word for the whole state, for anything that just wants to print it.
# Deliberately does NOT try to tell attract mode from the operator menu or from
# a ball in play: nothing measurable from outside distinguishes them yet, and
# inventing a distinction here is how the last wrong answer got written.
gs_state() {
    gs_past_alerts "$1" && { echo attract; return; }
    gs_booted "$1"      && { echo techalerts; return; }
    echo booting
}
