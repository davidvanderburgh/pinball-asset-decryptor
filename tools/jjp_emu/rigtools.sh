#!/bin/bash
# What this rig needs from the Linux it runs in - and, when something is
# missing, the one apt-get that puts it there.  watch.sh runs this first.
#
# WHY THE RIG INSTALLS ITS OWN TOOLS (PAD-1590).  The rig runs in the
# machine's default distro (tests/test_jjp_emulate_tab.py says why it has not
# moved into the app's own Linux), and install_prerequisites.ps1 used to fill
# that distro with these packages.  Once the app brought its own Linux
# (PAD-Runtime, core/runtime.py) the installer filled THAT instead, and a new
# PC's default Ubuntu stayed bare - so Start died on "mount.sh: missing
# partclone.restore" while the JJP extract, running in PAD-Runtime, restored
# the same ISO fine a minute later.  So the rig checks for itself, in whatever
# Linux it is in, and installs what is missing on the first Start.  On a PC
# whose only distro is PAD-Runtime that is the default, and the same holds:
# the runtime image has partclone, gcc and Xvfb, but not Xephyr, the board
# daemon's FUSE headers or the switch window's Tk.
#
# THE TABLE, one row per need:  <probe> <package...>
#   a probe is a command name (found on PATH), "py:<module>" (python3 can
#   import it) or "pc:<name>" (pkg-config knows the library).  Each row is a
#   thing a later step really calls; the step is named below the table.
set -u

TOOLS='
partclone.restore                partclone
gunzip                           gzip
gcc                              gcc libc6-dev
pc:fuse3                         pkg-config libfuse3-dev fuse3
Xephyr                           xserver-xephyr
xdpyinfo                         x11-utils
Xvfb                             xvfb
xdotool                          xdotool
xwd                              x11-apps
py:tkinter                       python3-tk
py:PIL.ImageTk                   python3-pil python3-pil.imagetk
pgrep                            procps
setsid                           util-linux
modprobe                         kmod
'
# (the row comments, which would break the table's parsing, live here:)
#   partclone.restore, gunzip   mount.sh restores the ISO's partitions
#   gcc + libc6-dev             build.sh: the hardware shim
#   pkg-config + libfuse3-dev   build.sh: the CUSE board daemon (jjpcuse.c
#                               includes cuse_lowlevel.h); fuse3 at run time
#   Xephyr, xdpyinfo            display.sh: the nested screen the game draws in
#   Xvfb                        display.sh: a hidden run's screen (PAD_HIDDEN=1)
#   xdotool                     winpos.sh: where the game's windows go
#   xwd                         grab.sh: the Emulate tab's picture of the game
#   python3-tk, python3-pil(.imagetk)  jjpsw.py: the switch-matrix window
#   procps, util-linux, kmod    every step: pgrep/pkill, setsid, modprobe cuse

have() {
    case "$1" in
        py:*) python3 -c "import ${1#py:}" >/dev/null 2>&1 ;;
        pc:*) pkg-config --exists "${1#pc:}" >/dev/null 2>&1 ;;
        *)    command -v "$1" >/dev/null 2>&1 ;;
    esac
}

MISSING=""
while read -r probe pkgs; do
    [ -n "$probe" ] || continue
    have "$probe" || MISSING="$MISSING $pkgs"
done <<EOF
$TOOLS
EOF

# --list: print the packages (all of them, or with --missing only those not
# here) and stop.  The test reads the table this way rather than re-parsing it.
if [ "${1:-}" = "--list" ]; then
    if [ "${2:-}" = "--missing" ]; then
        echo $MISSING
    else
        while read -r probe pkgs; do [ -n "$probe" ] && echo $pkgs; done <<EOF
$TOOLS
EOF
    fi
    exit 0
fi

[ -n "$MISSING" ] || { echo "rigtools: everything the rig needs is here"; exit 0; }

# One line per package would be noise; one line naming them is the record.
MISSING=$(echo $MISSING | tr ' ' '\n' | awk '!seen[$0]++' | tr '\n' ' ')
echo "rigtools: this Linux is missing: $MISSING- installing them (once; needs the internet)"

[ "$(id -u)" = "0" ] || { echo "rigtools: must run as root" >&2; exit 2; }
command -v apt-get >/dev/null || {
    echo "rigtools: no apt-get here; install these yourself: $MISSING" >&2; exit 3; }

export DEBIAN_FRONTEND=noninteractive
APT="apt-get -o Acquire::Retries=5 -o DPkg::Lock::Timeout=120 -q"
# The runtime image ships with its package lists removed, so ask for them
# first; a distro that has them just refreshes them.
if ! $APT update >/tmp/jjp_rigtools.log 2>&1 \
   || ! $APT install -y --no-install-recommends $MISSING >>/tmp/jjp_rigtools.log 2>&1; then
    echo "rigtools: installing failed (no internet in WSL?). The last lines:" >&2
    tail -n 5 /tmp/jjp_rigtools.log | sed 's/^/  /' >&2
    exit 4
fi

LEFT=""
while read -r probe pkgs; do
    [ -n "$probe" ] || continue
    have "$probe" || LEFT="$LEFT $probe"
done <<EOF
$TOOLS
EOF
if [ -n "$LEFT" ]; then
    echo "rigtools: installed, but still not working:$LEFT" >&2
    exit 5
fi
echo "rigtools: installed $MISSING"
