#!/bin/bash
# mkprobe.sh <build> <out>  - PAD-1387 proof: a copy of a prepared P-ROC build (proc/prepare.py,
# under /var/tmp/pad_spkproc/cache) with PAD's mode runtime in it, the way an update would
# carry it: padmodes_proc.py + padmodes.json beside the game's launcher, and ONE line added to
# the folder's config.yaml (pinproc_class: padmodes_proc.PinPROC).  No game file else changes.
# The copy is hard-linked (cp -al); config.yaml is replaced, not edited, so the cache's own
# inode is untouched.  Run as root.  Then: PAD_SLOT=N bash proc/run_game.sh <out>
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
B=/var/tmp/pad_spkproc/cache/$1; O=$2
[ -f "$B/title" ] || { echo "mkprobe.sh: not a prepared build: $B" >&2; exit 2; }
rm -rf "$O"; mkdir -p "$(dirname "$O")"
cp -al "$B" "$O"
rm -f "$O/config.yaml" "$O/used"
cp "$B/config.yaml" "$O/config.yaml"
printf '\n# PAD custom modes (padmodes_proc.py beside the launcher)\npinproc_class: padmodes_proc.PinPROC\n' >> "$O/config.yaml"
install -m 644 "$HERE/padmodes_proc.py" "$O/padmodes_proc.py"
install -m 644 "$HERE/padmodes.json" "$O/padmodes.json"
echo "mkprobe.sh: $O ready ($(cat "$O/title"))"
