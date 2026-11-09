#!/bin/bash
# soundlog.sh - THE SOUND AND VIDEO LOG'S HALF OF A BOOT (PAD-1071).
#
#   soundlog.sh        run_game.sh calls it each time it has asked the card for its modes
#                      (modes/cardmodes.sh). The LAST LINE ON STDOUT, when there is one, is the
#                      guest path to preload (PAD_MODE_SO); no stdout, and the boot is what it was.
#
# The Emulate tab's Sound and video log lists every sound the game plays. Only the game's own
# sound worker knows which one, so the mode runtime hooks it and writes "[pad] sound <request> <n>"
# to /dump/mode.log when /dump/soundlog.on is there as the game starts (sdk/pad_mode_runtime.c,
# soundlog_arm); the playfield window reads those lines (soundwatch.py) beside the clips it reads
# from padvid.log, and the app's log window shows both.
#
# THE RULES
#   * PAD_SOUNDLOG=1 (the Emulate tab's runs) puts /dump/soundlog.on there for this boot. Without
#     it the file is taken out, so a scripted run or a rig batch is the run it always was.
#   * A BOOT WITH NO RUNTIME OF ITS OWN (a stock card; a multi-boot image with no modes):
#     PAD_SOUNDLOG_STAGE names the tab's stage - the pinned runtime, the card's port and
#     soundlog.only - and it goes in through tryit.sh install. The object then hooks the sound
#     worker and NOTHING ELSE: no score gate, no Insider hold, the game runs stock. No stage (the
#     app has no port for this build): no sound log, and the boot is today's.
#   * A BOOT WITH A RUNTIME (the card's own modes, the override set, Try it, a scripted
#     PAD_MODE_SO) keeps it, and soundlog.on is all it is given. A soundlog.only an earlier boot's
#     stage left behind is taken out first: it would stop that runtime at the sound log.
#   * IT NEVER STOPS A RUN: an install that fails is a line in the log and a boot without the
#     sound log.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$HERE/../padpath.sh"
DUMP=$ROOT/dump

if [ "${PAD_SOUNDLOG:-}" != 1 ]; then
    rm -f "$DUMP/soundlog.on" "$DUMP/soundlog.only" 2>/dev/null
    exit 0
fi
so=""
if [ -n "${PAD_MODE_SO:-}" ]; then
    rm -f "$DUMP/soundlog.only" 2>/dev/null
elif [ -n "${PAD_SOUNDLOG_STAGE:-}" ] && [ -f "$PAD_SOUNDLOG_STAGE/soundlog.only" ]; then
    if said=$(bash "$HERE/tryit.sh" install "$PAD_SOUNDLOG_STAGE" 2>&1); then
        so=/lib/pad_mode.so
        echo "[soundlog] the sound log's runtime is in the game (it hooks the sound worker and nothing else)" >&2
    else
        echo "[soundlog] the sound log could not be put in the game, so this run lists no sounds: $said" >&2
        rm -f "$DUMP/soundlog.only" 2>/dev/null
    fi
else
    echo "[soundlog] this build has no port, so this run lists no sounds (the clips are still listed)" >&2
fi
if ! echo "PAD-1071" > "$DUMP/soundlog.on" 2>/dev/null; then
    echo "[soundlog] could not write $DUMP/soundlog.on, so this run lists no sounds" >&2
fi
[ -n "$so" ] && echo "$so"
exit 0
