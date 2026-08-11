#!/bin/bash
# setupcheck.sh - "can this machine emulate AT ALL?", answered as key=value
# facts, before a run rather than half way through one.
#
# WHY THIS EXISTS. Every tool the rig needs was discovered ONE AT A TIME, by
# failing on it: rootfs.sh dies without debugfs, the guest-exec probe dies
# without a registered qemu-arm, build.sh dies without the ARM cross compiler.
# Each of those prints a good sentence naming its own missing package, and a
# user who is missing three of them meets those sentences on three separate
# runs, minutes apart. A tester reached the second one on 2026-08-07 - no ARM
# handler, on a machine that had never had qemu-user-static - and what he saw
# was a wall of log text arriving after Start appeared to work.
#
# THIS ASKS ALL OF IT AT ONCE, COSTS ONE ROUND TRIP, AND CHANGES NOTHING. It is
# read-only on purpose: what to DO about the answer is setupfix.sh, and the two
# are separate so that looking is never something a user has to consent to.
#
# NO SECOND SOURCE OF TRUTH. The ARM handler is found by ensurebuild.sh's own
# _pad_binfmt_arm, and the command that would register it by its own
# _pad_binfmt_advice - the same functions the real run uses, so this can never
# disagree with the thing it is predicting. That rule is this rig's oldest one
# (alive.sh and killgame.sh disagreeing about what a running rig is has already
# cost a session).
#
# OUTPUT: key=value lines, one per fact, parsed by the Emulate tab.
#
#   qemu|armgcc|debugfs|fuse   1 = the tool is on PATH, 0 = it is not
#   ffmpeg                     1 = it is on PATH. It decodes BOTH the picture
#                              and the sound - see PAD_SETUP_TOOLS
#   nativecc                   1 = this machine can compile and link a NATIVE
#                              program, which is a different question from
#                              whether gcc is on PATH - see _pad_cc_works
#   busybox                    1 = there is a native STATIC busybox, which is
#                              what a checkpointable (save-state) boot needs
#                              and an ordinary one does not - see
#                              pad_static_busybox. Its absence costs SAVE
#                              STATES, not the emulator, so the tab reports it
#                              apart from the six above
#   criu                       1 = there is a criu to freeze the guest with.
#                              NOT A PACKAGE ON ANY UBUNTU - it is built from
#                              source by getcriu.sh, which is why its `-`
#                              package field keeps it out of `need` below
#   need                       the packages that would supply the missing
#                              ones, in apt's spelling
#   indexed                    1 = apt has index metadata to answer questions
#                              about the archive from. 0 = it has none, and
#                              `nocand` and `universe` are therefore not asked
#   nocand                     those of `need` that apt CANNOT install on this
#                              machine - see below
#   universe                   1 = nothing to say. 0 = this is Ubuntu, a
#                              needed package is unavailable, and the
#                              `universe` component that carries it is
#                              switched off in apt's sources
#   components                 the archive components apt actually has indexes
#                              for, so a message about the sources can be
#                              built from what IS configured
#   distro                     `ID VERSION_ID CODENAME` from /etc/os-release,
#                              so nothing downstream has to guess which Linux
#                              this is before telling the user about it
#   binfmt                     1 = a 32-bit ARM handler is registered and
#                              enabled, disabled = registered but switched
#                              off, 0 = the kernel has none
#   entry                      the binfmt_misc file, when there is one
#   advice                     the command that would register it ON THIS
#                              MACHINE (Ubuntu 24.04 and Debian differ, which
#                              is why this is asked rather than assumed)
#   wslconf                    1 = this distro boots systemd, so the
#                              registration survives a restart. Only
#                              meaningful on WSL, where it is the difference
#                              between fixing this once and fixing it weekly.
#   iswsl                      1 = WSL, 0 = a Linux machine or a container

. "$(dirname "$0")/padpath.sh"
. "$(dirname "$0")/ensurebuild.sh"

#: SOME FACTS ARE NOT A PATH LOOKUP. `@name` runs the shell function `name`
#: instead - which for the native compiler is the only honest test there is,
#: because gcc can be installed and unusable (see _pad_cc_works). The function
#: comes from ensurebuild.sh, so the run and the prediction share it.
_have() {
    case $1 in
        @*) "${1#@}" >/dev/null 2>&1 && echo 1 || echo 0 ;;
        *)  command -v "$1" >/dev/null 2>&1 && echo 1 || echo 0 ;;
    esac
}

#: WHAT THE EMULATOR NEEDS BEYOND THE RIG: fact key, the tool (or `@function`)
#: that IS the fact, the package that is only how apt spells it, and whether
#: that package may be fetched from ANOTHER Ubuntu release when this one has no
#: version of it. THE RIG'S ONE COPY - setupfix.sh installs what this reports
#: as missing rather than keeping a second list, because two lists in two
#: scripts is exactly how the thing that is explained and the thing that is
#: installed stop being the same four.
#:
#: THE PACKAGE FIELD IS COMMA-SEPARATED because one fact can need more than one
#: package and this list is whitespace-split. Exactly one entry needs that
#: today: `gcc libc6-dev`, which is one capability apt happens to spell in two
#: words - gcc only RECOMMENDS the headers, so installing half of it is how a
#: machine ends up with a compiler it cannot compile with.
#:
#: THE LAST FIELD IS A PERMISSION, NOT A PROMISE, and only one package has it.
#: qemu-user-static is a statically linked binary that Depends on NOTHING (a
#: 133 MB static-pie interpreter and a binfmt.d config file), so a .deb built
#: for one Ubuntu installs cleanly on another and drags nothing in with it.
#: The other three are ordinary dynamically linked packages whose dependency
#: chains belong to their own release; cross-installing those would be how you
#: turn "the emulator will not start" into "apt is broken". setupfix.sh checks
#: the actual downloaded file's Depends before it installs anything, so this
#: flag can only ever narrow what is attempted, never widen what is allowed.
#: THE DECODER WAS MISSING FROM THIS LIST TOO, and it is the one whose absence
#: looks least like a missing package: every tool above it builds or mounts
#: something, so lacking one stops the run with a build error, while lacking
#: this one lets the run SUCCEED all the way to an open, black window. The
#: game's own gstreamer-0.10 has no software H.264 element (padvidhost.py's
#: header prices that out), so the picture is decoded out here by ffmpeg and so
#: is the sound (playaudio.sh uses its `pulse` muxer because this distro ships
#: no pulseaudio client tools at all). The Mac container has installed it since
#: the day it was written - docker/Dockerfile, "the host-side H.264 decode the
#: guest cannot do itself" - and the WSL side was simply never asked.
#: AND THE ONE THAT IS NOT ABOUT STARTING AT ALL. Every line above is a
#: condition of running the game; this one is a condition of SAVING it. The
#: app asks for a checkpointable boot on every start (item 13), that boot
#: needs a native static busybox, and the package carrying it was on no list
#: anywhere - so v0.126.0 refused to start any title on a machine without it
#: (reported 2026-08-11). watch.sh now drops the request and runs anyway, so
#: what this fact costs is the save-state controls; it is reported here all
#: the same, because the alternative is a user finding out from a log line
#: mid-run - which is the thing this whole script exists to prevent. The tab
#: keeps it out of "this PC cannot run the emulator" for the same reason.
#: AND THE ONE APT CANNOT SUPPLY AT ALL, which is why the package field is `-`.
#: criu is the program that does the freezing, and NO Ubuntu publishes it -
#: `apt-cache policy criu` prints an empty version table on 24.04. Putting a
#: name there would hand `apt-get install` a package that cannot resolve and
#: turn one missing extra into "could not install", i.e. a machine told its
#: emulator setup failed when the emulator is fine. getcriu.sh builds it from
#: source instead, and setupfix.sh calls that when this fact is 0.
PAD_SETUP_TOOLS="qemu:qemu-arm-static:qemu-user-static:1
armgcc:arm-linux-gnueabihf-gcc:gcc-arm-linux-gnueabihf:0
nativecc:@_pad_cc_works:gcc,libc6-dev:0
debugfs:debugfs:e2fsprogs:0
fuse:fusermount3:fuse3:0
ffmpeg:ffmpeg:ffmpeg:0
busybox:@pad_static_busybox:busybox-static:0
criu:@pad_criu:-:0"

need= _xrel_ok=
for _t in $PAD_SETUP_TOOLS; do
    _key=${_t%%:*}; _rest=${_t#*:}; _tool=${_rest%%:*}
    _rest=${_rest#*:}; _pkg=${_rest%%:*}; _xrel=${_rest#*:}
    _pkg=${_pkg//,/ }
    # ASKED ONCE. It used to be probed twice - once for the line and once for
    # the `need` list - which is free for `command -v` and is a compile for the
    # entry below it.
    _ok=$(_have "$_tool")
    echo "$_key=$_ok"
    # `-` is "no package can supply this", and it must not reach `need`:
    # setupfix.sh installs that list verbatim, and a name apt has never heard
    # of fails the whole install for the packages beside it.
    [ "$_pkg" = "-" ] && continue
    [ "$_xrel" = 1 ] && _xrel_ok="$_xrel_ok $_pkg"
    [ "$_ok" = 1 ] || need="$need $_pkg"
done
echo "need=${need# }"

#: CAN apt actually install them? "Missing" and "installable" are two
#: different facts, and only asking the first is what put a tester in front of
#:
#:     E: Package 'qemu-user-static' has no installation candidate
#:
#: after the tab had told him a button would install it. That message is not a
#: download that failed: it is apt saying it knows the NAME and has no VERSION
#: - which on Ubuntu means the `universe` component that carries
#: qemu-user-static is switched off. `main` packages beside it in the same
#: command resolve fine, which is why exactly one of his four was named.
#:
#: Asked only about what is already missing, so a healthy machine pays nothing.
#:
#: FIRST, THOUGH: IS THERE AN INDEX TO ASK? Both questions below are answered
#: out of apt's DOWNLOADED metadata in /var/lib/apt/lists, not out of the
#: sources config, and a distro that has never run `apt-get update` has none of
#: it - which is the state every freshly installed WSL Ubuntu is in, because
#: the image ships with the lists emptied. With no index:
#:
#:   * `apt-cache policy <a package that is not installed>` prints NOTHING, so
#:     the Candidate test below finds no candidate and marks it uninstallable;
#:   * `apt-get indextargets` prints nothing at all, so the universe test finds
#:     no universe component and blames one that is in fact switched on.
#:
#: Together those told a brand-new WSL Ubuntu that its package sources offered
#: none of the four packages the emulator needs and that universe was off. Both
#: false, and both about the most common machine state there is. An empty index
#: is not evidence: it is the absence of it, so neither question is asked and
#: setupfix.sh's `apt-get update` is what turns the answers real.
components=$(apt-get indextargets --format '$(COMPONENT)' 2>/dev/null |
             sort -u | tr '\n' ' ')
components=${components% }
[ -n "$components" ] && indexed=1 || indexed=0
echo "indexed=$indexed"
echo "components=$components"

nocand=
if [ -n "$need" ] && [ "$indexed" = 1 ] &&
   command -v apt-cache >/dev/null 2>&1; then
    for _pkg in $need; do
        apt-cache policy -- "$_pkg" 2>/dev/null |
            sed -n 's/^[[:space:]]*Candidate:[[:space:]]*//p' |
            grep -qv '^(none)$' || nocand="$nocand $_pkg"
    done
fi
echo "nocand=${nocand# }"

#: ...and if that is why, say so, because it is repairable. Ubuntu only: on
#: Debian qemu-user-static is in `main` and an unavailable package means
#: something else entirely, which a wrong-but-confident answer would hide.
#: `components` is apt's own view of what it has indexes for, so a country
#: mirror, ports.ubuntu.com and a deb822 ubuntu.sources all answer correctly
#: where grepping a file for a hostname would not.
if [ -n "$nocand" ] &&
   grep -qs '^ID=ubuntu' /etc/os-release &&
   ! printf '%s\n' $components | grep -qx universe; then
    echo "universe=0"
else
    echo "universe=1"
fi

#: ...and of the ones apt has no version of, which the rig is willing to go
#: and FETCH from an Ubuntu release that does publish it. Reported here rather
#: than decided in setupfix.sh so that the tab can promise, before the user
#: presses anything, exactly what the button is about to do.
xrel=
for _pkg in $nocand; do
    case " $_xrel_ok " in *" $_pkg "*) xrel="$xrel $_pkg" ;; esac
done
echo "xrel=${xrel# }"

#: WHICH Linux this is, so that nothing downstream has to guess. A package apt
#: has no version of is a fact about a RELEASE, and the message about it named
#: two causes it had never checked ("out of support", "sources trimmed") in
#: front of a tester on a current Ubuntu whose archive had installed twenty-one
#: packages seconds earlier. Reported rather than inferred for the same reason
#: the tools are probed rather than assumed.
_osrel() { sed -n "s/^$1=//p" /etc/os-release 2>/dev/null | tr -d '"' | head -1; }
distro="$(_osrel ID) $(_osrel VERSION_ID) $(_osrel VERSION_CODENAME)"
echo "distro=$(printf '%s' "$distro" | sed 's/[[:space:]]\{1,\}/ /g;s/^ //;s/ $//')"

entry=$(_pad_binfmt_arm)
if [ -z "$entry" ]; then
    echo "binfmt=0"
elif [ "$(head -1 "$entry" 2>/dev/null)" = disabled ]; then
    echo "binfmt=disabled"
    echo "entry=$entry"
else
    echo "binfmt=1"
    echo "entry=$entry"
fi

echo "advice=$(_pad_binfmt_advice)"

if pad_is_wsl; then
    echo "iswsl=1"
    # The registration lives in the RUNNING kernel and is put back at boot by
    # systemd-binfmt. A distro started without systemd loses it on every
    # `wsl --shutdown`, so this is not cosmetic: without it the same repair is
    # needed again next week, and the user has no way to know why.
    if [ "$(ps -p 1 -o comm= 2>/dev/null)" = systemd ]; then
        echo "wslconf=1"
    else
        echo "wslconf=0"
    fi
else
    echo "iswsl=0"
    echo "wslconf=1"
fi
