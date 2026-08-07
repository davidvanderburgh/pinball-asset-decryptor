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

#: The WSL distro to send someone to when their own cannot supply a package.
#: An LTS, and the one this rig is developed and tested against, so it is a
#: recommendation with evidence behind it rather than "try something newer".
#: emulate_tab.py names the same one to the user before they ever get here;
#: test_the_two_halves_recommend_the_same_distro keeps the two from drifting.
PAD_KNOWN_GOOD_DISTRO=Ubuntu-24.04

facts=$(_facts)

# ---- 1. the packages ------------------------------------------------------
#
# WHICH packages is setupcheck.sh's answer, not a second list here: it probes
# the TOOLS, which is the fact, and knows how apt spells each one.
pkgs=$(_get "$facts" need)

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

#: Turn Ubuntu's `universe` component on. THE ONLY REASON THIS IS HERE: a
#: tester's WSL Ubuntu had it off, so qemu-user-static - which lives there -
#: had no version for apt to install, while gcc-arm-linux-gnueabihf beside it
#: in `main` was fine. Nothing else the emulator needs comes from universe, so
#: this runs only when setupcheck has said that is what is wrong.
#:
#: add-apt-repository is the official way and inherits the mirror, the suite
#: names and the signing key from what is already configured - all three of
#: which a hand-written source line would have to guess, and would get wrong
#: on ports.ubuntu.com or a country mirror. It lives in
#: software-properties-common, which a slim WSL image often does not have, so
#: there is a fallback that edits the distro's OWN sources in place.
#:
#: ONLY those two files. A PPA or a vendor repo under sources.list.d has no
#: universe component, and appending one turns a working repository into a 404
#: on every apt-get update from then on.
_add_universe() {
    local f touched=0
    if command -v add-apt-repository >/dev/null 2>&1 &&
       _run add-apt-repository -y universe; then
        return 0
    fi
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources; do
        [ -f "$f" ] || continue
        # -n: keep the FIRST backup. A second run must not overwrite the
        # pristine copy with one this script has already edited.
        cp -n "$f" "$f.pad-backup" 2>/dev/null
        case $f in
        *.sources)
            # deb822: one `Components:` line per stanza.
            sed -i '/^Components:/{/universe/!s/$/ universe/}' "$f"
            grep -qs '^Components:.*universe' "$f" && touched=1 ;;
        *)
            # One-line format, components last. Narrow on purpose: an
            # UBUNTU.COM archive line that already carries `main`. A PPA line
            # looks almost identical - `deb https://ppa.launchpadcontent.net/
            # x/y/ubuntu noble main` - and has no universe component, so
            # appending one to it 404s every apt-get update from then on.
            # Someone whose sources are a private mirror gets no repair here
            # and is told so, which is the right way round.
            sed -i '/^deb.*ubuntu\.com\/.*[[:space:]]main\([[:space:]]\|$\)/{/universe/!s/$/ universe/}' "$f"
            # ...and prove it on a DIRECTIVE line: Ubuntu's own sources file
            # carries a paragraph of comments explaining what universe is, so
            # a bare grep for the word always succeeds and proves nothing.
            grep -qs '^deb.*universe' "$f" && touched=1 ;;
        esac
    done
    [ "$touched" = 1 ]
}

#: WHY apt has no version, said only from facts this run established.
#:
#: WHAT USED TO STAND HERE, and why it is gone. The sentence was "a WSL distro
#: that is out of support, or one whose sources have been trimmed, does this;
#: installing a current Ubuntu in WSL is the way back." It named two causes
#: nothing had checked, and the first machine to meet it was on a CURRENT
#: Ubuntu whose archive had installed twenty-one packages seconds earlier with
#: universe switched on. The one piece of advice it gave him was the thing he
#: had already done.
#:
#: So: the release, the components, and whether the index is one we just
#: refreshed - all reported, none inferred - and then the route that is left.
_why_nocand() {
    local f=$1 updated=$2 nocand=$3 distro comps
    distro=$(_get "$f" distro); comps=$(_get "$f" components)
    [ -n "$distro" ] && echo "This Linux is: $distro"
    [ -n "$comps" ] && echo "apt has these archive components switched on:"
    [ -n "$comps" ] && echo "  $comps"
    if [ "$updated" = 1 ]; then
        echo "The index was refreshed a moment ago and the archive answered,"
        echo "so this is not a stale index and not a download that failed:"
        echo "this release does not publish the package at all."
    else
        # apt-get update FAILED, so "the release does not have it" is not a
        # claim this run has earned - the index may simply be incomplete.
        echo "apt-get update did not succeed just now, so the index may be"
        echo "incomplete too. Whatever is wrong with the package sources is"
        echo "worth fixing before reading anything into the line above."
    fi
    case " $nocand " in
    *" qemu-user-static "*)
        echo "The emulator cannot do without this one: qemu-user-static is"
        echo "the only package that carries a statically linked ARM"
        echo "interpreter, and the game is a 32-bit ARM binary." ;;
    esac
    # PAD talks to whichever distro WSL calls the default, so a distro that
    # does carry the package, made the default, is a real way through and does
    # not disturb the one that is there. Run on the WINDOWS side, not in here.
    echo "A WSL distro that does have it, made the default, is the way"
    echo "through. In a Windows terminal:"
    echo "  wsl --install -d $PAD_KNOWN_GOOD_DISTRO"
    echo "  wsl --set-default $PAD_KNOWN_GOOD_DISTRO"
}

if [ -n "$pkgs" ]; then
    echo "installing: $pkgs"
    export DEBIAN_FRONTEND=noninteractive
    # `update` first: a WSL image that has sat unused for months has an index
    # too old to resolve anything, and the failure that produces ("Unable to
    # locate package") reads like the package does not exist. Not fatal on its
    # own - the install below is what decides.
    #
    # ITS STATUS IS KEPT, though, because it is the difference between two
    # verdicts that read the same and are not: "this release does not publish
    # the package" can only be said about an index that was actually
    # refreshed. Without it, an unreachable archive looks exactly like a
    # package that does not exist.
    if _run apt-get update -qq; then updated=1; else updated=0; fi

    # Ask again with a fresh index before installing: "apt has no version of
    # this" is a different fault from "the download failed", it is knowable
    # BEFORE the attempt, and on Ubuntu it has a repair.
    facts=$(_facts)
    if [ -n "$(_get "$facts" nocand)" ] && [ "$(_get "$facts" universe)" = 0 ]
    then
        echo "apt has no version of $(_get "$facts" nocand) to install:"
        echo "Ubuntu keeps it in the 'universe' component and this distro has"
        echo "that switched off. Turning it on."
        if _add_universe; then
            _run apt-get update -qq
            facts=$(_facts)
        else
            echo "could not turn universe on"
        fi
    fi

    # ONE AT A TIME, and this is not tidiness. `apt-get install a b` is all or
    # nothing: the tester's run named two packages, apt could not resolve one
    # of them, and so it installed NEITHER - he was left with none of the four
    # he was missing and a log that mentioned only one of them.
    failed=
    for pkg in $pkgs; do
        _run apt-get install -y -qq "$pkg" || failed="$failed $pkg"
    done

    if [ -n "$failed" ]; then
        facts=$(_facts)
        nocand=$(_get "$facts" nocand)
        echo "could not install:$failed"
        if [ -n "$nocand" ]; then
            # Not a failed download: apt has a record of the name and no
            # VERSION, in an index refreshed seconds ago, which no amount of
            # retrying changes - so say which, WHY, and what would.
            echo "apt has no version of $nocand to install."
            _why_nocand "$facts" "$updated" "$nocand"
            echo "result=nocandidate"
        else
            echo "apt-get failed - see above"
            echo "result=aptfailed"
        fi
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
