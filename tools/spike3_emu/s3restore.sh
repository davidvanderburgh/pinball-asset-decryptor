#!/bin/bash
# s3restore.sh - bring a Spike 3 save state (s3save.sh) back to life in a rig
# slot whose helpers s3run.sh has just started (PAD-1147).
#
#   s3restore.sh SLOT DIR        (root; called by s3run.sh --restore DIR)
#
# s3run.sh has already made this run's renderer ring, node-bus pty, video
# feed and SPI input in the slot directory, exactly as for a boot. This
# script then, instead of booting the card:
#   1. puts the save's overlay uppers in as the slot's (the game's settings,
#      NVRAM and logs as its memory remembers them),
#   2. replays the save's GL world into the fresh renderer,
#   3. builds the mounts the game had - on the host side, in a private mount
#      namespace - and hands each to criu as the external it was dumped as,
#   4. runs criu restore inside a fresh loopback-only network namespace (the
#      game had one; s3save.sh dumped from inside it, so criu neither locked
#      nor saved it), detached.
# It prints "[s3restore] pid N" (the game's host pid) and exits 0, or says
# why not and exits 1. The restored game is the run's game from then on.
#
#   s3restore.sh --check SLOT DIR TREE   the pre-flight alone: exit 0 when DIR
#                                        can be loaded into a run of TREE (a
#                                        running game is ended only after it)
set -u
S=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHECK=0; RUNTREE=""
[ "${1:-}" = --check ] && { CHECK=1; shift; RUNTREE=${3:-}; }
SLOT=${1:?usage: s3restore.sh SLOT DIR}
DDIR=${2:?usage: s3restore.sh SLOT DIR}
SD=/var/tmp/pad-s3/slot$SLOT
. "$S/../spike2_emu/padpath.sh" 2>/dev/null
CRIU=${CRIU:-$(pad_criu 2>/dev/null)}
say() { echo "[s3restore] $*"; }
[ "$(id -u)" = 0 ] || { say "needs root"; exit 2; }
[ -x "${CRIU:-}" ] || { say "this machine has no criu; Set up emulator... builds it"; exit 1; }
[ -s "$DDIR/restore.env" ] && [ -s "$DDIR/inventory.img" ] || { say "not a save state: $DDIR"; exit 1; }
TREE=$(awk '$1 == "tree" {print $2}' "$DDIR/restore.env")
[ -d "$TREE/rootfs" ] || { say "the card this was saved from is not in the Spike 3 store ($TREE)"; exit 1; }
if [ -n "$RUNTREE" ] && [ "$(readlink -f "$RUNTREE")" != "$(readlink -f "$TREE")" ]; then
    say "this save is of another card ($(basename "$TREE")); start that card to load it"
    exit 1
fi
[ "$CHECK" = 1 ] && exit 0

# --- 1. the disk as it was --------------------------------------------------
for l in root games data connectivity; do
    rm -rf "${SD:?}/$l.up" "${SD:?}/$l.wk"
    if [ -d "$DDIR/up/$l" ]; then cp -a "$DDIR/up/$l" "$SD/$l.up"; else mkdir -p "$SD/$l.up"; fi
    mkdir -p "$SD/$l.wk"
done

# --- 2. the renderer's GL world ---------------------------------------------
# padglhost answers glreplay.req from its idle poll (no guest yet): it resets
# its world and feeds the journal through dispatch, then writes glreplay.ok.
if [ -s "$DDIR/glstate.bin" ] && [ -e "$SD/padgl.ring" ]; then
    rm -f "$SD/glreplay.ok"
    cp -f "$DDIR/glstate.bin" "$SD/glreplay.bin"
    : > "$SD/glreplay.req"
    for _ in $(seq 1 300); do [ -e "$SD/glreplay.ok" ] && break; sleep 0.1; done
    if [ -e "$SD/glreplay.ok" ]; then
        say "GL world replayed into the renderer"
    else
        rm -f "$SD/glreplay.req"
        say "NOTE: the renderer did not take the GL journal; pictures come back as the game redraws"
    fi
    rm -f "$SD/glreplay.bin" "$SD/glreplay.ok"
fi

# --- the video feed: a new session, every channel closed -------------------
# A cold load's feed is new anyway; a load into a running run's feed finds the
# old game's streams still open on the host. A new session makes the restored
# game re-open each of its streams (s3vid.c resync); closing the rest ends the
# old game's decoders. The offsets are s3vidhost.py's (s3vid.h's layout).
if [ -s "$SD/s3vid.feed" ]; then
    python3 "$S/s3vidhost.py" --new-session "$SD/s3vid.feed" \
        || say "NOTE: the video feed could not be reset; clips may stall until the next one"
fi

# --- 3. the externals, and 4. the restore -----------------------------------
EXTD=$SD/rst                       # where the non-root overlays are mounted
mkdir -p "$SD/root" "$EXTD"
REST=()
PTY=$(cat "$SD/bridge.path" 2>/dev/null)
TTYKEY=""
while read -r kind key a b; do
    case "$kind" in
    ovl)  mkdir -p "$EXTD/$b"; REST+=(--external "mnt[$key]:$EXTD/$b") ;;
    dev)  REST+=(--external "mnt[$key]:$b") ;;
    pty)  [ -n "$PTY" ] || { say "this run has no node bus to give the game"; exit 1; }
          REST+=(--external "mnt[$key]:$PTY") ;;
    file) if [ ! -e "$SD/$b" ]; then
              say "this run has no $b for the game's $a"; exit 1
          fi
          REST+=(--external "mnt[$key]:$SD/$b") ;;
    tty)  TTYKEY=$a ;;
    esac
done < "$DDIR/restore.env"

rm -f "$DDIR/restored.pid"
# The namespace criu restores from: private mounts (the overlays, made here
# so the host never sees them), a fresh network namespace with only loopback,
# and fd 9 = the new node-bus pty, for --inherit-fd.
INNER=$DDIR/.restore_ns.sh
cat > "$INNER" <<'EOF'
set -u
SD=$1 TREE=$2 EXTD=$3; shift 3
mount --make-rprivate /
ip link set lo up 2>/dev/null
ov() { mount -t overlay overlay -o "lowerdir=$1,upperdir=$SD/$3.up,workdir=$SD/$3.wk" "$2"; }
ov "$TREE/rootfs" "$SD/root" root || exit 1
for d in games data connectivity; do
    [ -d "$TREE/$d" ] || continue
    ov "$TREE/$d" "$EXTD/$d" "$d" || exit 1
done
mount --bind "$SD/root" "$SD/root"
exec "$@"
EOF
INH=()
if [ -n "$TTYKEY" ]; then
    exec 9<>"$PTY" || { say "could not open the node bus $PTY"; exit 1; }
    INH=(--inherit-fd "fd[9]:tty[$TTYKEY]")
fi
say "restoring..."
# NOT DETACHED (-d): criu stays the game's parent for the whole run. The game
# arms PR_SET_PDEATHSIG (SIGKILL) on itself, criu restores that faithfully,
# and a detached restore's game was killed the instant criu exited - "Restore
# finished successfully", then gone within a second. As the parent, criu
# waits for the game and exits with its status, as unshare did for a boot;
# a run that ends criu (Stop) ends the game, as it ended unshare.
rm -f "$DDIR/restore.log"
setsid unshare -m -n bash "$INNER" "$SD" "$TREE" "$EXTD" \
    "$CRIU" restore -D "$DDIR" -v4 -o restore.log ${PAD_S3_RESTORE_STOPPED:+--leave-stopped} \
        --pidfile "$DDIR/restored.pid" --root "$SD/root" \
        "${REST[@]}" ${INH[@]+"${INH[@]}"} </dev/null >"$DDIR/restore.out" 2>&1 &
CPID=$!
exec 9>&-
OK=0
for _ in $(seq 1 600); do
    grep -aq 'Restore finished successfully' "$DDIR/restore.log" 2>/dev/null && { OK=1; break; }
    grep -aq 'Restoring FAILED' "$DDIR/restore.log" 2>/dev/null && break
    kill -0 "$CPID" 2>/dev/null || break
    sleep 0.1
done
if [ "$OK" != 1 ] || [ ! -s "$DDIR/restored.pid" ]; then
    kill -KILL "$CPID" 2>/dev/null
    grep -a 'Error' "$DDIR/restore.log" | tail -8 | sed 's/^/    /'
    why=$(grep -a 'Error' "$DDIR/restore.log" | grep -av 'Restoring FAILED' | head -1 \
          | sed 's/^([^)]*) *//; s/^Error ([^)]*): *//')
    say "could not load: ${why:-criu stopped without saying why}"
    exit 1
fi
echo "$CPID" > "$DDIR/restore.criupid"
say "pid $(cat "$DDIR/restored.pid")"
