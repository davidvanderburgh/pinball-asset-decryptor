#!/bin/bash
# prereqs.sh - SOURCED, never run.  "Can this machine BUILD the Spike 1 rig?",
# asked ALL AT ONCE and BEFORE the first build step, rather than one package at
# a time, minutes apart, as each build dies on its own missing tool.
#
#   . "$(dirname "$0")/prereqs.sh"
#   s1_prereq_report qemu shim || exit 2
#
# WHY THIS EXISTS.  A machine's first Start compiles two things - a patched
# qemu-user (build_qemu.sh, minutes) and the CUSE device model (s1hwshim.c,
# seconds) - and until now each named what it wanted only by FAILING, in a
# fixed sentence written from memory.  What a user actually met (eyeamred2u,
# 2026-09-08, on a Python 3.14 distro) was:
#
#     Python's ensurepip module is not found.
#     ERROR: python venv creation failed
#     ERROR: could not build qemu - install: meson ninja-build libglib2.0-dev
#            pkg-config flex bison gcc 2
#
# Three things are wrong in those two lines and every one of them cost that
# user the fix: the package that would have solved it - python3-venv - is NOT
# in the list; `meson` IS in the list although qemu installs its own from a
# wheel it ships, so it was never the answer; and the trailing `2` is the exit
# code, printed by a `fail` that logged all of its arguments.
#
# THE PROBES ARE THE THING ITSELF, NOT A GUESS ABOUT IT.  A header is not a
# command, so glib and fuse3 are asked of pkg-config; the venv question is
# asked of the interpreter, in exactly the terms qemu's own mkvenv.py asks it
# (ensurepip, or pip AND setuptools already importable, plus pyexpat), so this
# cannot predict a failure qemu will not have or miss one it will.
#
# IT ONLY LOOKS.  Installing is the user's to do - the same stance the Spike 2
# rig settled on with setupcheck.sh (look) and setupfix.sh (fix), so that
# finding out what is missing is never something anyone has to consent to.
#
# ONE LIST.  start.sh and build_qemu.sh both read this file, and the pacman
# column is held against the app's own Debian-to-Arch table (core/pkgnames.py)
# by tests/test_spike1_prereqs.py, so what is EXPLAINED and what is NEEDED
# cannot drift apart.

#: capability | groups | probe | apt | pacman | what it is for
#:
#: `@name` runs the shell function `name` instead of looking for a command on
#: the PATH.  An empty pacman field means Arch needs no package for it: its
#: python carries ensurepip, which is the whole of the break above.
_S1_PREREQS=(
    "python|qemu shim|python3|python3|python|runs the build scripts and qemu's configure"
    "venv|qemu|@_s1_have_venv|python3-venv||qemu builds its own meson in a private venv"
    "ninja|qemu|ninja|ninja-build|ninja|the build tool qemu generates for"
    "flex|qemu|flex|flex|flex|generates qemu's lexers"
    "bison|qemu|bison|bison|bison|generates qemu's parsers"
    "glib|qemu|@_s1_have_glib|libglib2.0-dev|glib2|the one library qemu-user links against"
    "fetch|qemu|@_s1_have_fetch|wget|wget|fetches the qemu tarball, once"
    "xz|qemu|xz|xz-utils|xz|unpacks it"
    "cc|qemu shim|gcc|gcc|gcc|compiles the emulator and the device model"
    "pkgconfig|qemu shim|pkg-config|pkg-config|pkgconf|finds the two libraries above"
    "fuse3|shim|@_s1_have_fuse3|libfuse3-dev|fuse3|the device model is a CUSE character device"
)

_s1_have_glib(){ pkg-config --exists glib-2.0; }
_s1_have_fuse3(){ pkg-config --exists fuse3; }
_s1_have_fetch(){ command -v wget >/dev/null 2>&1 || command -v curl >/dev/null 2>&1; }

#: THE VENV QUESTION, ASKED THE WAY QEMU ASKS IT.  qemu 8.2's configure builds
#: a private venv to run meson out of, and mkvenv.py takes one of two roads
#: into it: ensurepip, or - when pip AND setuptools are already importable -
#: no pip bootstrap at all.  Either is enough, which is why a machine with
#: python3-pip and python3-setuptools needs no python3-venv.  pyexpat is
#: mkvenv.py's second check and part of the same answer.
_s1_python_can_venv() {
    [ -n "${1:-}" ] || return 1
    command -v "$1" >/dev/null 2>&1 || return 1
    "$1" - <<'PY' >/dev/null 2>&1
import sys
from importlib.util import find_spec
ok = bool(find_spec("pyexpat")) and (
    bool(find_spec("ensurepip"))
    or (find_spec("pip") is not None and find_spec("setuptools") is not None))
sys.exit(0 if ok else 1)
PY
}

#: EVERY python3 THIS MACHINE HAS, newest first after the default one.  A
#: distro that splits ensurepip out has usually only split it out of the NEW
#: interpreter, and qemu's configure takes --python=, so a machine with a
#: complete python3.12 beside a stripped python3.14 can build today rather
#: than after an apt install.
_s1_python_candidates() {
    printf '%s\n' python3
    ls /usr/bin/python3.* /usr/local/bin/python3.* 2>/dev/null \
        | grep -E '/python3\.[0-9]+$' | sort -Vr
}

# s1_python - the interpreter qemu's configure should be pointed at: the first
# one that can make its venv.  Prints `python3` and returns 1 when none can, so
# a caller that ignores the status still gets a working command name.
s1_python() {
    if [ -n "${S1_PY:-}" ]; then echo "$S1_PY"; return 0; fi
    local p
    while read -r p; do
        [ -n "$p" ] || continue
        if _s1_python_can_venv "$p"; then echo "$p"; return 0; fi
    done <<< "$(_s1_python_candidates)"
    echo python3
    return 1
}

_s1_have_venv(){ s1_python >/dev/null; }

_s1_pkg_manager() {
    if command -v apt-get >/dev/null 2>&1; then echo apt
    elif command -v pacman >/dev/null 2>&1; then echo pacman
    else echo ""; fi
}

#: WHAT DEBIAN CALLS THE VENV PACKAGE HERE.  `python3-venv` is the metapackage
#: for the DEFAULT interpreter, which is the right name on an ordinary Debian
#: or Ubuntu.  It is the wrong name on a machine whose python3 came from
#: somewhere else (a deadsnakes PPA, a newer python installed beside the
#: distro's), where only the versioned one exists - so the versioned name is
#: worked out from the interpreter itself and offered beside it.
_s1_venv_pkg_alt() {
    local v
    v=$(python3 -c 'import sys;print("python%d.%d"%sys.version_info[:2])' 2>/dev/null)
    [ -n "$v" ] && echo "$v-venv"
}

#: The suffix core/payloads.py writes its stamp under.  Named once, here,
#: because the app writes it and this reads it.
S1_PAYLOAD_STAMP_SUFFIX=".pad-payload"

# s1_paths - the rig's path defaults, set only where the caller has not.
# WHERE THE RIG LIVES IS ONE FACT.  start.sh worked them out at the top of
# itself, which was fine while it was the only script that needed them and
# stopped being fine the moment a second one (prereqcheck.sh, the "Fix setup"
# button's read-only half) had to agree with it about which qemu it is asking
# about.  Field 6 of the passwd entry, not /home/<user>: a distro that puts
# home somewhere else is not this rig's business to guess at.
s1_paths() {
    : "${S1_DESKTOP_USER:=$(getent passwd 1000 2>/dev/null | cut -d: -f1)}"
    : "${S1_HOME:=$(getent passwd 1000 2>/dev/null | cut -d: -f6)}"
    : "${S1_HOME:=/home/${S1_DESKTOP_USER:-david}}"
    : "${S1_WORK:=$S1_HOME/s1emu}"
    : "${QEMU_WORK:=$S1_HOME/qemubuild}"
    : "${S1_QEMU:=$QEMU_WORK/qemu-arm}"
    export S1_DESKTOP_USER S1_HOME S1_WORK QEMU_WORK S1_QEMU
}

# s1_build_groups RIGDIR - which build steps this machine still has to run:
# "qemu", "shim", both, or nothing at all.  Call s1_paths first.
#
# THE DEVICE MODEL IS "IS THIS BINARY FOR THESE SOURCES", NOT "IS IT OLDER".
# A binary the APP installed (core/payloads.py - built and hashed by us in CI,
# so no user needs a compiler for it) carries a stamp naming the s1hwshim.c it
# was built from.  While that matches the .c here, nothing is rebuilt however
# the timestamps fall - and that matters because installing an app update
# rewrites this .c with today's date, which under the old rule turned "the
# user updated the app" into "the user now needs gcc and libfuse3-dev".
# With no stamp (a developer's own build) the timestamp rule still decides, so
# working from a checkout is unchanged.
s1_build_groups() {
    local here="$1" need="" stamp want have
    [ -x "$S1_QEMU" ] || need="$need qemu"
    stamp="$S1_WORK/s1hwshim$S1_PAYLOAD_STAMP_SUFFIX"
    if [ ! -x "$S1_WORK/s1hwshim" ]; then
        need="$need shim"
    elif [ -f "$stamp" ]; then
        want=$(sed -n 's/^source_sha256=//p' "$stamp")
        have=$(sha256sum "$here/s1hwshim.c" 2>/dev/null | cut -d' ' -f1)
        [ -n "$want" ] && [ "$want" = "$have" ] || need="$need shim"
    elif [ "$here/s1hwshim.c" -nt "$S1_WORK/s1hwshim" ]; then
        need="$need shim"
    fi
    echo $need
}

# s1_prereq_missing GROUP... - one line per missing capability:
#     key|apt name|pacman name|what it is for
# The separator is `|` and not a tab BECAUSE A FIELD CAN BE EMPTY: bash's
# `read` collapses runs of whitespace separators, so a tab-separated line whose
# pacman name is blank (the venv row on Arch) arrives with the purpose text
# read into the package field.
s1_prereq_missing() {
    local want row key groups probe apt pac why g hit
    want=" ${*:-qemu shim} "
    for row in "${_S1_PREREQS[@]}"; do
        IFS='|' read -r key groups probe apt pac why <<< "$row"
        hit=0
        for g in $groups; do
            case $want in *" $g "*) hit=1 ;; esac
        done
        [ "$hit" = 1 ] || continue
        case $probe in
            @*) "${probe#@}" >/dev/null 2>&1 && continue ;;
            *)  command -v "$probe" >/dev/null 2>&1 && continue ;;
        esac
        printf '%s|%s|%s|%s\n' "$key" "$apt" "$pac" "$why"
    done
}

# s1_prereq_report GROUP... - prints nothing and returns 0 when this machine
# can build the groups asked about; prints the whole answer and returns 1 when
# it cannot.  Written to be read one line at a time: the GUI logs each line as
# it arrives, so the install command has to stand on a line of its own.
s1_prereq_report() {
    local missing pm names key apt pac why alt cmd shown
    missing=$(s1_prereq_missing "$@")
    [ -n "$missing" ] || return 0
    pm=$(_s1_pkg_manager)
    echo "The emulator is compiled once on this machine, and these build tools are missing:"
    names=""
    while IFS='|' read -r key apt pac why; do
        [ -n "$key" ] || continue
        if [ "$pm" = pacman ]; then shown="$pac"; else shown="$apt"; fi
        if [ -n "$shown" ]; then
            printf '  %-11s %s  (%s)\n' "$key" "$why" "$shown"
            names="$names $shown"
        else
            printf '  %-11s %s\n' "$key" "$why"
        fi
    done <<< "$missing"
    names=$(echo $names)
    if [ -n "$names" ]; then
        if [ "$pm" = pacman ]; then
            cmd="pacman -S --needed $names"
        else
            cmd="apt-get install -y $names"
        fi
        [ "$(id -u 2>/dev/null)" = 0 ] || cmd="sudo $cmd"
        echo "Install them, then press Start again:"
        echo "  $cmd"
        case " $names " in
            *" python3-venv "*)
                alt=$(_s1_venv_pkg_alt)
                [ -n "$alt" ] && echo "  (no python3-venv on this distro? its own interpreter wants $alt)"
                ;;
        esac
    else
        echo "This distro packages none of them separately - it needs a complete python3."
    fi
    return 1
}
