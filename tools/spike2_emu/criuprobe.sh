#!/bin/bash
# Is CRIU viable in THIS WSL, for THIS rig? (item 13, save states)
#
#   wsl -e bash tools/spike2_emu/criuprobe.sh
#
# READ-ONLY. Starts nothing, installs nothing, needs no emulator run and no
# root. Run it before spending a pass on checkpoint/restore.
#
# WHY THIS EXISTS. The handoff carried a five-row table (criu not installed,
# CHECKPOINT_RESTORE=y, UNIX/PACKET_DIAG=m, INET_DIAG_DESTROY not set) and the
# design was built on it. Five rows is not CRIU's requirement list, and the one
# row that mattered most was never checked: a kernel can have every CONFIG CRIU
# wants and still refuse the syscalls it needs. So this prints the whole list,
# and then actually CALLS the three interfaces that decide it.
#
# It answers three separate questions and never blurs them:
#   1. is criu OBTAINABLE here             (packaged? buildable? deps present?)
#   2. does the KERNEL carry what it needs (config, then live probes)
#   3. does the RIG's guest have a shape criu could ever restore
# A no at 2 kills the design; a no at 1 only costs a build.

say()  { printf '%s\n' "$*"; }
hdr()  { printf '\n=== %s\n' "$*"; }
# ok/no/hm: a verdict column that can be grepped, so a later pass can diff two
# runs of this script rather than re-reading its prose.
ok()   { printf '  ok   %s\n' "$*"; }
no()   { printf '  NO   %s\n' "$*"; }
hm()   { printf '  ?    %s\n' "$*"; }

say "criuprobe - CRIU viability for the Spike 2 rig (item 13)"
say "kernel: $(uname -r)"
say "distro: $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"

# ---------------------------------------------------------------- 1. obtain
hdr "1. can criu be obtained here"

if command -v criu >/dev/null 2>&1; then
    ok "criu on PATH: $(criu --version 2>&1 | head -1)"
    HAVE_CRIU=1
else
    no "criu is not on PATH"
    HAVE_CRIU=0
fi

# apt-cache policy prints an empty version table for a package that exists in
# no enabled component. Ubuntu 24.04 (noble) DROPPED criu - it is in jammy and
# not in noble - so this is expected to say NOT PACKAGED and that is the point:
# "needs installing" in the handoff implied an apt install, and there is none.
CAND=$(apt-cache policy criu 2>/dev/null | awk '/Candidate:/{print $2}')
if [ -n "$CAND" ] && [ "$CAND" != "(none)" ]; then
    ok "apt candidate: $CAND"
else
    no "not packaged for this release (apt candidate: ${CAND:-none})"
    say "       -> the route is a source build; deps checked below"
fi

# Build dependencies for criu 3.x on Debian/Ubuntu. Missing ones are an
# apt-get away, so this is a cost estimate and not a verdict.
hdr "1b. source-build dependencies"
MISSING=""
for p in build-essential libprotobuf-dev libprotobuf-c-dev protobuf-c-compiler \
         protobuf-compiler libnl-3-dev libnet1-dev libcap-dev pkg-config \
         python3-protobuf libbsd-dev iproute2; do
    if dpkg -s "$p" >/dev/null 2>&1; then
        ok "$p"
    else
        no "$p"
        MISSING="$MISSING $p"
    fi
done
[ -n "$MISSING" ] && say "       apt-get install -y$MISSING"

# ---------------------------------------------------------------- 2. kernel
hdr "2. kernel config"

# WSL2 ships its config at /proc/config.gz. If that is absent there is no
# second source - there is no /boot/config-* for a Microsoft kernel - so say so
# rather than reporting a wall of NOT SET that only means "could not look".
CFG=""
if [ -r /proc/config.gz ]; then
    CFG="/proc/config.gz"
elif [ -r "/boot/config-$(uname -r)" ]; then
    CFG="/boot/config-$(uname -r)"
fi

if [ -z "$CFG" ]; then
    hm "no kernel config readable (/proc/config.gz absent)"
    say "       every row below would read NOT SET for the wrong reason;"
    say "       skipping to the live probes, which do not need it"
else
    say "  config: $CFG"
    # cat|gunzip rather than zgrep: zgrep is in the `gzip` package and this
    # WSL image does not carry it, which cost a reading once already.
    if [ "${CFG##*.}" = "gz" ]; then
        CFGTXT=$(gzip -dc "$CFG" 2>/dev/null)
    else
        CFGTXT=$(cat "$CFG")
    fi

    # REQUIRED: criu will not work without these.
    for k in CHECKPOINT_RESTORE NAMESPACES UTS_NS IPC_NS PID_NS NET_NS \
             USER_NS FHANDLE EVENTFD EPOLL INOTIFY_USER UNIX_DIAG \
             NETLINK_DIAG CGROUPS; do
        v=$(printf '%s\n' "$CFGTXT" | grep -m1 "^CONFIG_$k=")
        if [ -n "$v" ]; then ok "$v"; else no "CONFIG_$k is not set  (REQUIRED)"; fi
    done

    # OPTIONAL: each disables one feature rather than the tool.
    #   INET_DIAG_DESTROY - TCP connections cannot be restored
    #   MEM_SOFT_DIRTY    - no iterative pre-dump (irrelevant to a save state)
    say "  -- optional (each costs one feature, not the tool):"
    for k in INET_DIAG INET_TCP_DIAG INET_UDP_DIAG INET_DIAG_DESTROY \
             PACKET_DIAG MEM_SOFT_DIRTY TUN FUSE_FS; do
        v=$(printf '%s\n' "$CFGTXT" | grep -m1 "^CONFIG_$k=")
        if [ -n "$v" ]; then ok "$v"; else hm "CONFIG_$k is not set  (optional)"; fi
    done
fi

hdr "2b. live kernel probes - what the config says vs what the kernel does"

# /proc/<pid>/map_files is how criu learns which file backs each mapping. It is
# gated on CAP_SYS_ADMIN, so as a normal user this is EXPECTED to fail, and a
# failure here is not a verdict - it is why criu wants root.
if [ -d /proc/self/map_files ]; then
    if ls /proc/self/map_files >/dev/null 2>&1; then
        ok "/proc/self/map_files readable ($(ls /proc/self/map_files 2>/dev/null | wc -l) entries)"
    else
        hm "/proc/self/map_files exists but is not readable as $(id -un) (wants CAP_SYS_ADMIN - expected)"
    fi
else
    no "/proc/self/map_files does not exist  (REQUIRED - no CHECKPOINT_RESTORE)"
fi

# ns_last_pid is the old way to pin a restored pid. Modern criu uses clone3's
# set_tid instead (kernel >= 5.5, and this is 6.6), so absence is survivable.
if [ -e /proc/sys/kernel/ns_last_pid ]; then
    ok "/proc/sys/kernel/ns_last_pid present"
else
    hm "/proc/sys/kernel/ns_last_pid absent (criu >= 3.14 uses clone3 set_tid)"
fi

for f in /proc/self/stat /proc/self/maps /proc/self/mountinfo /proc/self/status; do
    [ -r "$f" ] && ok "$f readable" || no "$f unreadable  (REQUIRED)"
done

# The diag modules are how criu enumerates sockets. They are =m, so they have
# to be LOADED, and nothing loads them by accident.
say "  -- netlink diag modules (=m in config, must be loaded):"
for m in unix_diag netlink_diag packet_diag tcp_diag udp_diag inet_diag; do
    if lsmod 2>/dev/null | grep -q "^$m "; then
        ok "$m loaded"
    elif modinfo "$m" >/dev/null 2>&1; then
        hm "$m available but NOT loaded (modprobe $m, needs root)"
    else
        no "$m not available"
    fi
done

# ---------------------------------------------------------------- 3. the rig
hdr "3. the rig's own restore surface"

# THE POINT OF THIS SECTION. The handoff's design is "checkpoint the guest
# side, restart the host helpers". Whether that is even expressible depends on
# what the GUEST holds, and the guest is not a bare process: run_game.sh puts
# it inside `unshare -r -m -p -f` (user + mount + pid namespaces) and then
# chroots it. Everything below is read off run_game.sh and hwshim.c, and each
# line is a thing criu must be TOLD about with --external or refuse to dump.
say "  from run_game.sh and hwshim.c, at the desk:"
say "    namespaces   : user (-r), mount (-m), pid (-p -f), then chroot"
say "    mounts       : proc, 3x tmpfs (/sys /tmp /run /dev/shm), 3 self-binds"
say "    EXTERNAL fs  : the card, a fuse2fs mount made OUTSIDE the namespace"
say "                   and bind mounted in  -> criu --external mnt[]"
say "    EXTERNAL tty : nodebus.py's pty MASTER is held outside; the SLAVE is"
say "                   bind mounted onto /dev/ttymxc1  -> criu --external tty[]"
say "    rings        : file-backed MAP_SHARED of ordinary files under dump/"
say "                   (PAD_SW_SHM, PAD_LED_SHM ...) - criu re-opens these"
say "                   from the file, and the CONTENT lives in the file, so"
say "                   the rings survive a checkpoint without being in it"
say "    sockets      : hwshim.c opens NONE (grep: no socket/connect/AF_INET)"

# If a run happens to be up, print the truth instead of the theory. This is the
# only part of the script that depends on one, and it never starts one.
GPID=$(pgrep -x game 2>/dev/null | head -1)
if [ -n "$GPID" ]; then
    say ""
    ok "a run IS up (game pid $GPID) - reading its real fds and maps"
    say "    fds: $(ls /proc/$GPID/fd 2>/dev/null | wc -l)"
    ls -l /proc/$GPID/fd 2>/dev/null | awk '{print "      " $NF}' | sort | uniq -c | sort -rn | head -15
    say "    shared file maps:"
    awk '$4 !~ /^00:00/ && $2 ~ /s/ {print "      " $6}' /proc/$GPID/maps 2>/dev/null | sort -u | head -15
    say "    threads: $(cat /proc/$GPID/status 2>/dev/null | awk '/^Threads:/{print $2}')"
else
    say ""
    hm "no run is up - section 3 is read from the source, not from a process"
    say "       start one and re-run to get the guest's real fd and map list"
fi

hdr "verdict"
if [ "$HAVE_CRIU" = 1 ]; then
    say "  criu is present; run 'criu check --all' next."
else
    say "  criu is ABSENT and unpackaged on this release. Nothing about the"
    say "  design can be tested until it is built from source. The kernel rows"
    say "  above say whether that build would be worth making."
fi
