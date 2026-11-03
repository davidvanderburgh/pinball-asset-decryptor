#!/bin/bash
# entrypoint.sh - the Spooky box's PID 1 (PAD-953): the display, VNC and the
# sound server, then idle until the box is removed. spkbox.sh starts the box
# with this and runs the rig's scripts in it with `docker exec`, so the game
# is a child of nobody here and a run ends with `docker rm -f`.
#
# The rig's own scripts never change for the box: a VISIBLE run (PAD_VISIBLE=1,
# which the app always asks for) draws on $DISPLAY, the way it draws on WSLg's
# desktop on Windows, and a run with sound plays to $PAD_PULSE_SOCK, the way it
# plays to WSLg's PulseServer there.
set -u

TOOLS=${PAD_TOOLS:-/pad/app/tools}
XDISPLAY=${DISPLAY:-:99}
GEOM=${PAD_VNC_GEOMETRY:-2400x1080x24}
PORT=${PAD_VNC_PORT:-5900}
AUDIO_PORT=${PAD_AUDIO_PORT:-45998}
RATE=${PAD_AUDIO_RATE:-48000}
PULSE_DIR=$(dirname "${PAD_PULSE_SOCK:-/run/pad-pulse/native}")

[ -f "$TOOLS/spooky_emu/watch.sh" ] || {
    if [ -z "$(ls -A "$TOOLS" 2>/dev/null)" ]; then
        echo "[box] no rig at $TOOLS: the folder is empty in here, so the container" >&2
        echo "[box] engine did not share the folder it was given" >&2
    else
        echo "[box] no rig at $TOOLS - mount the app's folder at /pad/app" >&2
    fi
    exit 1
}

as_pad() { runuser -u pad -- "$@"; }

echo "[box] starting Xvfb on $XDISPLAY at $GEOM"
Xvfb "$XDISPLAY" -screen 0 "$GEOM" -nolisten tcp >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
for _ in $(seq 1 40); do
    xdpyinfo -display "$XDISPLAY" >/dev/null 2>&1 && break
    sleep 0.25
done
xdpyinfo -display "$XDISPLAY" >/dev/null 2>&1 || {
    echo "[box] Xvfb did not come up:" >&2; cat /tmp/xvfb.log >&2; exit 1; }
# Click-to-focus and title bars: the game and the playfield share the screen,
# side by side - the playfield (about 1000 px wide) at the left edge, every
# other window (the game: 1280 or 1366 wide) beside it, so neither covers the
# other. On Windows they are two windows on the desktop; here one screen holds
# both, which is why it is wider than the cabinet's 1920.
cat > /tmp/openbox-rc.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <applications>
    <application class="*">
      <position force="yes"><x>1010</x><y>0</y></position>
    </application>
    <application title="*virtual playfield*">
      <position force="yes"><x>0</x><y>0</y></position>
    </application>
  </applications>
</openbox_config>
EOF
DISPLAY=$XDISPLAY as_pad openbox --config-file /tmp/openbox-rc.xml >/tmp/openbox.log 2>&1 &

# A password, because macOS Screen Sharing refuses a VNC server with none
# (the Spike 2 box learned it); the port is loopback only.
VNC_AUTH=(-nopw)
if [ -n "${PAD_VNC_PASSWD:-}" ]; then
    as_pad x11vnc -storepasswd "$PAD_VNC_PASSWD" /home/pad/.vncpw >/dev/null 2>&1 \
        && VNC_AUTH=(-rfbauth /home/pad/.vncpw)
fi
(
    while :; do
        as_pad x11vnc -display "$XDISPLAY" -rfbport "$PORT" -forever -shared -quiet \
               -threads "${VNC_AUTH[@]}"
        echo "[box] x11vnc exited ($?); starting it again"
        sleep 1
    done
) >/tmp/x11vnc.log 2>&1 &
echo "[box] VNC on port $PORT"

# THE SOUND: one null sink, its monitor served raw (s16le, $RATE Hz, stereo)
# to whoever connects to $AUDIO_PORT - spkbox.sh's player on the Mac. VNC
# carries no sound. The socket is anonymous so the games (pad) and spkvol.py
# (root) both reach it.
mkdir -p "$PULSE_DIR" && chown pad: "$PULSE_DIR"
as_pad env HOME=/home/pad pulseaudio -n --daemonize=no --exit-idle-time=-1 \
    --disallow-exit --log-target=file:/tmp/pulse.log \
    -L "module-null-sink sink_name=box rate=$RATE channels=2 format=s16le" \
    -L "module-native-protocol-unix socket=$PULSE_DIR/native auth-anonymous=1" \
    -L "module-simple-protocol-tcp source=box.monitor record=true playback=false port=$AUDIO_PORT listen=0.0.0.0 rate=$RATE channels=2 format=s16le" \
    -L "module-always-sink" >/tmp/pulse.out 2>&1 &
for _ in $(seq 1 40); do [ -S "$PULSE_DIR/native" ] && break; sleep 0.25; done
[ -S "$PULSE_DIR/native" ] && chmod 777 "$PULSE_DIR/native" \
    || echo "[box] the sound server did not start; runs will be silent" >&2

cleanup() {
    for s in stop.sh; do bash "$TOOLS/spooky_emu/$s" >/dev/null 2>&1; done
    kill -9 "$XVFB_PID" 2>/dev/null
    pkill -9 -x x11vnc 2>/dev/null
    pkill -9 -x pulseaudio 2>/dev/null
}
trap 'cleanup; exit 0' INT TERM

# spkbox.sh waits for this before it runs anything in the box.
echo "$RATE" > /run/pad-box.ready
echo "[box] ready"
while :; do sleep 3600 & wait $!; done
