#!/bin/bash
# shot.sh <out.png> - capture this slot's game screen (hidden or visible).
# A hidden run's display is bigger than the game's window, so the frame is
# trimmed to the window: the bounding box of everything not black, found from
# one grey frame (plain python - the runtime has no PIL) and cut by ffmpeg.
. "$(dirname "$0")/bofpath.sh"
OUT=${1:?usage: shot.sh <out.png>}
bof_game_alive || { echo "shot.sh: rig $BOF_SLOT not running" >&2; exit 1; }
DISP=$(cat "$BOF_RIG/display")
if [ "$(cat "$BOF_RIG/visible" 2>/dev/null)" = 1 ]; then
    SIZE=${BOF_SHOT_SIZE:-1920x1080}
else
    SIZE=3840x1440
fi
W=${SIZE%x*}; H=${SIZE#*x}
FULL=$BOF_RIG/shot_full.png
ffmpeg -loglevel error -y -f x11grab -video_size "$SIZE" -i "$DISP" -frames:v 1 "$FULL" || exit 1
CROP=$(ffmpeg -loglevel error -i "$FULL" -f rawvideo -pix_fmt gray - |
    python3 -c '
import sys
w, h = int(sys.argv[1]), int(sys.argv[2])
buf = sys.stdin.buffer.read()
rows = [y for y in range(h) if max(buf[y * w:(y + 1) * w]) > 8]
if not rows:
    print(""); sys.exit()
y0, y1 = rows[0], rows[-1]
cols = [x for x in range(w) if max(buf[x + y * w] for y in range(y0, y1 + 1, 4)) > 8]
x0, x1 = cols[0], cols[-1]
print("crop=%d:%d:%d:%d" % (x1 - x0 + 1, y1 - y0 + 1, x0, y0))
' "$W" "$H")
if [ -n "$CROP" ]; then
    ffmpeg -loglevel error -y -i "$FULL" -vf "$CROP" "$OUT" || exit 1
else
    cp "$FULL" "$OUT"
fi
echo "$OUT"
