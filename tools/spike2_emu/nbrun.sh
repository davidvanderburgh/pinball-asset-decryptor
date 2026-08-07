#!/bin/bash
# nbrun.sh <log> <secs> [VAR=VAL ...] - a bridged run set up to answer
# "did a node board leave Not Initialized?", with the Tech Alerts screen as the
# readout and the registry dump as the corroborating instrument.
#
# PAD_NB_LOG is raised on purpose: the tracer's default budget is 400 lines and
# the [nb] lines stop about 6 s into a 60 fps run, which reads exactly like the
# game giving up on the bus and is nothing of the kind.
. "$(dirname "$0")/padpath.sh"
set -u
cd $HOME
LOG=${1:-gznb.log}
SECS=${2:-25}
shift 2 || true

mkdir -p "$HOME/shots"
rm -f "$HOME/shots/"*.png

# PAD_GL_DUMP is read by the HOST, a native WSL process, so it takes a WSL path
# and not the chroot's /dump. Pointed at /dump the host writes nothing at all
# and stale PNGs get re-read as if they were this run's.
export PAD_GL_DUMP=$HOME/shots
export PAD_GL_FRAME_EVERY=${PAD_GL_FRAME_EVERY:-30}
export PAD_GL_MAX_FRAMES=${PAD_GL_MAX_FRAMES:-24}
export PAD_NB_LOG=${PAD_NB_LOG:-200000}
export PAD_NB_DUMP=${PAD_NB_DUMP:-400}
# Node 2 has no devices in the game's own config, so it is not populated on a
# real Godzilla Pro. Answering for it manufactures a board that cannot ever be
# graded clean. See PAD_NB_SILENT in hwshim.c.
export PAD_NB_SILENT=${PAD_NB_SILENT:-2}
for kv in "$@"; do export "$kv"; done

bash "$RIG/runbridge.sh" "$LOG" "$SECS" gpu

echo "--- node board registry, last dump ---"
awk '/\[nbtbl\] --- /{buf=""} {if (/\[nbtbl\]/) buf = buf $0 "\n"} END{printf "%s", buf}' "$LOG" | tail -20
echo "--- identity exchanges ---"
grep -a '\[nb\] TX len=5 8[0-9a-f]02fe' "$LOG" | sort | uniq -c | head
grep -a '\[nb\] TX-reply len=13' "$LOG" | sort | uniq -c | head -4
echo "--- subcommands at or below 0xef (only sent to REGISTERED boards) ---"
grep -aoE '\[nb\] TX len=[0-9]+ 8[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]' "$LOG" \
  | awk '{print $4}' | cut -c5-6 | sort | uniq -c | sort -rn | head -20
echo "--- frames ---"
ls -l "$HOME/shots/"*.png 2>/dev/null | tail -5
