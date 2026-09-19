#!/bin/bash
# regress.sh <label> [seconds] - godzilla's regression numbers for item 125.
#
# The acceptance: "with the .so absent the godzilla regression bar is unchanged".
# The bar, measured the same way on a run WITH mode.so/padmode.so and a stock run
# WITHOUT them, over the same window in the same state (a game in progress):
#   - renderer fps and video uploads (padglhost prints both every ~2 s)
#   - the guest's own frame rate (eglshim, in game.out)
#   - new [segv] / fatal-signal / FATAL lines, and Radium Error lines
#   - whether the probe or the mode wrote a log (a stock run must not have one)
# Writes /var/tmp/item125_regress_<label>.txt as well as printing it. Read-only.
. "$(dirname "$0")/../padpath.sh"
LABEL=${1:?usage: regress.sh <label> [seconds]}
SECS=${2:-60}
G=$HOME/padglhost.log
O=$ROOT/dump/game.out
OUT=/var/tmp/item125_regress_$LABEL.txt
g0=$(wc -l < "$G")
o0=$(wc -l < "$O")
sleep "$SECS"
fps=$(tail -n +$((g0 + 1)) "$G" | grep -a '^\[padglhost\] [0-9.]* fps' \
      | awk '{ s += $2; n++ } END { if (n) printf "%.1f (%d samples)", s / n, n; else print "none" }')
vid=$(tail -n +$((g0 + 1)) "$G" | grep -a 'NEW/s' \
      | awk '{ for (i = 1; i <= NF; i++) if ($i == "NEW/s") { s += $(i - 1); n++ } } END { if (n) printf "%.1f", s / n; else print "none" }')
guest=$(tail -n +$((o0 + 1)) "$O" | grep -a '^\[eglshim\] .* fps' \
      | awk '{ s += $(NF - 1); n++ } END { if (n) printf "%.1f (%d samples)", s / n, n; else print "none" }')
faults=$(tail -n +$((o0 + 1)) "$O" | grep -acE '\[segv\] pc|uncaught target signal|FATAL')
radium=$(tail -n +$((o0 + 1)) "$O" | grep -ac 'Radium Error')
probe=$([ -f "$ROOT/dump/padmode.log" ] && echo "present ($(wc -l < "$ROOT/dump/padmode.log") lines)" || echo absent)
mode=$([ -f "$ROOT/dump/mode.log" ] && echo "present ($(wc -l < "$ROOT/dump/mode.log") lines)" || echo absent)
{
  echo "regress $LABEL over ${SECS}s:"
  echo "  renderer fps        $fps"
  echo "  video NEW/s         $vid"
  echo "  guest (eglshim) fps $guest"
  echo "  new fault lines     $faults"
  echo "  new Radium Errors   $radium"
  echo "  padmode.log         $probe"
  echo "  mode.log            $mode"
} | tee "$OUT"
