# padpath.sh - SOURCED, never run. The shell twin of padpath.py.
#
#   . "$(dirname "$0")/padpath.sh"
#
# Sets the four things every script in this rig used to carry as a literal:
#
#   RIG     this directory, from the path this file was sourced by
#   ROOT    the guest rootfs      ($PAD_ROOT, else ~/spike2root)
#   TABLES  derived per-title data ($PAD_TABLES, else $ROOT/dump/tables)
#   WINENV  the WSLENV additions a Windows child needs to find all of the above
#
# WHY $0 IS NOT GOOD ENOUGH ON ITS OWN. Several scripts here are sourced by
# others and several are run through `bash <path>`, so BASH_SOURCE is the only
# thing that names THIS file in both cases. It is a bashism and that is fine:
# every script in the rig is `#!/bin/bash` and is invoked as bash.
#
# PATHS ARE EXPORTED, not just set, because run_game.sh, playaudio.sh and the
# rest are separate processes and inherit rather than re-derive. The `:=` form
# means an caller who has already chosen a rootfs keeps it.
RIG=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)
export RIG

: "${PAD_ROOT:=$HOME/spike2root}"
export PAD_ROOT
ROOT=$PAD_ROOT

: "${PAD_TABLES:=$ROOT/dump/tables}"
export PAD_TABLES
TABLES=$PAD_TABLES

# Which distro this is, so a Windows child can ask questions of the RIGHT one.
# WSL sets WSL_DISTRO_NAME; if it is somehow unset the Windows side falls back
# to the default distro, which is right far more often than it is wrong.
: "${PAD_WSL_DISTRO:=${WSL_DISTRO_NAME:-}}"
export PAD_WSL_DISTRO

# WSLENV is how any of this reaches a Windows process, and it is the only way:
# nothing in this environment crosses interop unless it is named there. `/p`
# asks WSL to translate the value from a WSL path to a Windows one, so the
# playfield window receives `\\wsl.localhost\<distro>\...` without either side
# having to know how that string is spelled on this machine.
pad_export_win() {
    WSLENV="${WSLENV:+$WSLENV:}PAD_ROOT/p:PAD_TABLES/p:PAD_WSL_DISTRO"
    export WSLENV
}

# A rig path as Windows sees it. Used to launch the playfield window, which is
# a Windows process and cannot be handed a POSIX path.
pad_win() {
    wslpath -w "$1"
}
