#!/bin/bash
# PAD-510 proof, run as ROOT in WSL (the app's runs are root's):
#
#   pad510_scenario.sh <rig dir> <tag> <out dir> [watch_s]
#
# A run whose game has stopped writing sound, the Windows player on
# playaudio.sh's restart loop, and then the game window closed: <rig>'s own
# watch.sh teardown() is extracted and run AS IS, then what is left of the run
# is counted every 2 s with that rig's alive.sh, which is the count the app's
# one button reads. Nothing boots and nothing plays: <rig>/padplay.py is a
# stand-in that never opens a sound device (shot_pad510.py writes it). Slot 3,
# a scratch PAD_HOME, port 46000. Everything it started is gone at the end.
R=$1; TAG=$2; OUT=$3; WATCH_S=${4:-60}
mkdir -p "$OUT"
TL=$OUT/$TAG.timeline.txt; : > "$TL"
T0=$(date +%s.%N)
since() { awk -v a="$(date +%s.%N)" -v b="$T0" 'BEGIN { printf "%6.1f s", a - b }'; }
say() { printf '%s  %s\n' "$(since)" "$*" | tee -a "$TL"; }
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe

export PAD_HOME=/tmp/pad510home PAD_SLOT=3 PAD_LABEL=PAD-510-check
rm -rf "$PAD_HOME"; mkdir -p "$PAD_HOME"
. "$R/padpath.sh"
export PAD_WINPYTHON="/mnt/c/Program Files/Pinball Asset Decryptor/python/python.exe"
export PAD_AUDIO_SINK=win PAD_AUDIO_FMT_FIXED=1
mkdir -p "$ROOT/dump" "$PAD_LOGDIR"
# the helpers drop to the desktop user, as the tester's run did ("running the
# guest as root, helpers as simon")
U=$(getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 { print $1; exit }')
[ -n "$U" ] && chown -R "$U" "$PAD_HOME"
AUD_HOST=$ROOT/dump/audio.fifo; AUD_FMT_HOST=$ROOT/dump/audio.fmt
win_players() {
    "$PS" -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object {
        \$_.Name -like 'py*' -and \$_.CommandLine -like '*padplay.py*' -and
        \$_.CommandLine -like '* $PAD_AUDIO_PORT *' } | Measure-Object).Count" \
        2>/dev/null | tr -d '\r'
}
say "rig $R  slot $PAD_SLOT  port $PAD_AUDIO_PORT"

# The run's sound, started the way watch.sh starts it. Its own HOLD writer
# keeps the fifo open and nothing else ever writes to it: the tester's dead
# feed (writei calls frozen at 133197 for the last two minutes of the run).
if [ -n "$U" ]; then
    runuser -u "$U" -- setsid bash "$R/playaudio.sh" "$AUD_HOST" 44100 2 "$AUD_FMT_HOST" \
        > "$PAD_LOGDIR/padaudio.log" 2>&1 < /dev/null &
else
    setsid bash "$R/playaudio.sh" "$AUD_HOST" 44100 2 "$AUD_FMT_HOST" \
        > "$PAD_LOGDIR/padaudio.log" 2>&1 < /dev/null &
fi
AUDPG=$!
say "playaudio.sh up${U:+ (as $U)}; the game writes no sound"

# The tester's moment: the first player gave up on the dead feed and the loop
# started another (13 s before his close; 4 s here).
for _ in $(seq 1 120); do
    grep -q 'restarting it' "$PAD_LOGDIR/padaudio.log" && break
    sleep 0.5
done
grep -q 'restarting it' "$PAD_LOGDIR/padaudio.log" \
    || { say "NO RESTART SEEN"; cat "$PAD_LOGDIR/padaudio.log"; }
say "player gave up on the dead feed; playaudio.sh restarted it"
sleep 4
say "BEFORE_CLOSE rig processes up = $(bash "$R/alive.sh" --procs), sound player $(pad_count -f 'padplay\.py')"

# ---- the game window closes: watch.sh's own teardown -----------------------
eval "$(sed -n '/^teardown() {$/,/^}$/p' "$R/watch.sh")"
BOARD_RUN=$PAD_HOME/no.run
GAMEPG=; GAMEOUTTAIL=; HOSTPG=; VIDPG=; AUTOPG=; BALLPG=; SPEEDPG=; KEEPPG=
EVTPG=; TBLPG=
LED_HOST=$ROOT/dump/padled; LCD_HOST=$ROOT/dump/padlcd
DROP=0; PF_WINLAUNCH=0; CARD_MNT=; PAD_CARD=; CARD_MNTS=(); S=$RIG
PF_SLOTMATCH="-like '*--pad-slot=$PAD_SLOT*'"
pf_up() { [ -n "$(pad_pids -f '^(/init|python3?) .*playfield\.py')" ]; }
say "WINDOW CLOSED: running $TAG's watch.sh teardown"
T1=$(date +%s.%N)
teardown 2>&1 | grep -v 'Killed' | sed 's/^/          | /' | tee -a "$TL"
say "TEARDOWN_DONE in $(awk -v a="$(date +%s.%N)" -v b="$T1" 'BEGIN { printf "%.1f", a - b }') s"
say "Windows side: $(win_players) sound player process(es) on port $PAD_AUDIO_PORT"

for _ in $(seq 1 $((WATCH_S / 2))); do
    say "after the close: rig processes up = $(bash "$R/alive.sh" --procs), sound player $(pad_count -f 'padplay\.py')"
    sleep 2
done
say "Windows side: $(win_players) sound player process(es) on port $PAD_AUDIO_PORT"

# ---- leave nothing behind, whichever rig ran ------------------------------
"$PS" -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object {
    \$_.Name -like 'py*' -and \$_.CommandLine -like '*padplay.py*' -and
    \$_.CommandLine -like '* $PAD_AUDIO_PORT *' } |
    ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1
pad_pkill -9 -f 'playaudio\.sh|padrelay\.py|padplay\.py'
cp "$PAD_LOGDIR/padaudio.log" "$OUT/$TAG.padaudio.log"
rm -rf "$PAD_HOME"
say "SCENARIO_END"
