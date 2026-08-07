#!/bin/bash
# setupfix.sh - RUN AS ROOT. Installs what the emulator needs and registers the
# kernel's 32-bit ARM handler, so that "you cannot emulate yet" stops being a
# list of commands for the user to type.
#
# WHY THIS IS ALLOWED TO EXIST, when the rig's standing rule is that
# registering qemu-arm is "printed only, never run" (see ensurebuild.sh):
#
#   THAT RULE IS ABOUT LINUX, AND IT IS STILL RIGHT THERE. On a Linux desktop
#   the rig is an unprivileged process, sudo wants a password, and a GUI app
#   that appears to hang while an invisible prompt waits for one is worse than
#   printing the command.
#
#   ON WSL IT IS SIMPLY NOT TRUE. `wsl -u root` is uid 0 with no password,
#   because it is the WINDOWS side launching the distro - and the app already
#   relies on exactly that to install the WSL packages (install_prerequisites
#   .ps1 has done `wsl -u root -- apt-get install` for several releases). The
#   privilege was always there; nothing was wired to the one check that needed
#   it, so the rig kept printing advice to a user whose app could have acted.
#
# It is therefore called from Windows only, and only after the user has said
# yes to a dialog naming every package and every file it touches. Nothing here
# is silent and nothing here is a surprise.
#
# WHAT IT WILL NOT DO:
#   * it does not `wsl --shutdown`. The registration it just made is live in
#     the running kernel, so nothing needs restarting NOW, and a shutdown from
#     under a running emulator would kill it. Persistence is reported as
#     needs_restart=1 and left to the human.
#   * it does not remove or downgrade anything, and it does not rewrite an
#     /etc/wsl.conf that already has an opinion about systemd.
#
# Output is plain lines for the log pane, then a final `result=` line.

. "$(dirname "$0")/padpath.sh"

if [ "$(id -u)" != 0 ]; then
    echo "setupfix.sh must run as root (the app calls it with 'wsl -u root')" >&2
    echo "result=notroot"
    exit 1
fi

#: The facts, from the ONE place that derives them. setupfix does not repeat
#: setupcheck's probing - it asks it, so the two can never disagree about what
#: is missing or about which register command this distro wants.
_facts() { bash "$RIG/setupcheck.sh" 2>/dev/null; }
_get() { printf '%s\n' "$1" | sed -n "s/^$2=//p" | head -1; }

facts=$(_facts)

# ---- 1. the packages ------------------------------------------------------
#
# Tool -> package, and the tool is what is probed because that is the fact;
# the package name is only how this distro spells it.
pkgs=""
[ "$(_get "$facts" qemu)" = 0 ]    && pkgs="$pkgs qemu-user-static"
[ "$(_get "$facts" armgcc)" = 0 ]  && pkgs="$pkgs gcc-arm-linux-gnueabihf"
[ "$(_get "$facts" debugfs)" = 0 ] && pkgs="$pkgs e2fsprogs"
[ "$(_get "$facts" fuse)" = 0 ]    && pkgs="$pkgs fuse3"

#: Run a command, show its output indented, and RETURN ITS STATUS - which a
#: bare `cmd | sed` does not: the status of a pipeline is the status of its
#: LAST command, so piping apt through sed for indentation reports sed's
#: success and a failed install reads as a clean one.
_run() {
    local out rc
    out=$("$@" 2>&1); rc=$?
    [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/  /'
    return $rc
}

if [ -n "$pkgs" ]; then
    echo "installing:$pkgs"
    export DEBIAN_FRONTEND=noninteractive
    # `update` first: a WSL image that has sat unused for months has an index
    # too old to resolve anything, and the failure that produces ("Unable to
    # locate package") reads like the package does not exist. Not fatal on its
    # own - the install below is what decides.
    _run apt-get update -qq
    if ! _run apt-get install -y -qq $pkgs; then
        echo "apt-get failed - see above"
        echo "result=aptfailed"
        exit 1
    fi
    facts=$(_facts)
else
    echo "every package the emulator needs is already installed"
fi

# ---- 2. the kernel's ARM handler ------------------------------------------
#
# Re-read AFTER the install: installing qemu-user-static is what puts
# /usr/lib/binfmt.d/qemu-arm.conf on disk, and that file is what decides which
# of the three register commands this machine wants. Asking before the install
# gets the answer for the machine as it was.
binfmt=$(_get "$facts" binfmt)
if [ "$binfmt" = 1 ]; then
    echo "the kernel already has a 32-bit ARM handler"
elif [ "$binfmt" = disabled ]; then
    entry=$(_get "$facts" entry)
    echo "enabling the ARM handler that was registered but switched off"
    if ! echo 1 > "$entry" 2>/dev/null; then
        echo "could not enable $entry"
        echo "result=regfailed"
        exit 1
    fi
else
    advice=$(_get "$facts" advice)
    # The advice is written for a HUMAN, so it carries sudo. This is already
    # root; anything else would need sudo to exist, which is not guaranteed in
    # a minimal distro image.
    cmd=${advice#sudo }
    echo "registering the 32-bit ARM handler: $cmd"
    if ! _run bash -c "$cmd"; then
        echo "registration failed - see above"
        echo "result=regfailed"
        exit 1
    fi
fi

# ---- 3. and make it survive a restart -------------------------------------
#
# binfmt registrations live in the running kernel only. systemd-binfmt puts
# them back at boot; a WSL distro started without systemd loses them on every
# `wsl --shutdown`, which is how a machine that was fixed last week arrives
# back here having changed nothing.
needs_restart=0
if [ "$(_get "$facts" iswsl)" = 1 ] && [ "$(_get "$facts" wslconf)" = 0 ]; then
    if grep -qi 'systemd' /etc/wsl.conf 2>/dev/null; then
        # It has an opinion already (systemd=false, or a commented note). That
        # is a deliberate choice by someone and not this script's to overrule.
        echo "/etc/wsl.conf already mentions systemd - leaving it alone."
        echo "The ARM registration will be lost when WSL next restarts, and"
        echo "setting it up again will bring it back."
    else
        echo "adding [boot] systemd=true to /etc/wsl.conf so this survives a"
        echo "WSL restart"
        {
            [ -s /etc/wsl.conf ] && echo ""
            echo "[boot]"
            echo "systemd=true"
        } >> /etc/wsl.conf
        needs_restart=1
    fi
fi

# ---- 4. and PROVE it, rather than reporting the steps that were taken -----
facts=$(_facts)
if [ "$(_get "$facts" binfmt)" = 1 ] && \
   [ "$(_get "$facts" qemu)" = 1 ] && \
   [ "$(_get "$facts" armgcc)" = 1 ] && \
   [ "$(_get "$facts" debugfs)" = 1 ] && \
   [ "$(_get "$facts" fuse)" = 1 ]; then
    echo "needs_restart=$needs_restart"
    echo "result=ok"
    exit 0
fi
echo "something is still missing:"
printf '%s\n' "$facts" | sed 's/^/  /'
echo "result=incomplete"
exit 1
