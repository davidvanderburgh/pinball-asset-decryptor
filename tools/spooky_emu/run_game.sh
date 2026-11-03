#!/bin/bash
# run_game.sh <build> [--visible] [--audio]
#
# Start a Spooky Warden-era game (spktitles.py: Beetlejuice, Scooby-Doo,
# Texas Chainsaw Massacre, Evil Dead, Looney Tunes) on this PC, on the rig's
# emulated Warden board (spkwarden.py).  <build> is a folder prepare.sh made
# (a name under $SPK_CACHE or a path).  Run as root; it drops to $SPK_USER
# itself.  Returns once the game reached attract mode (or it died).
#
#   --visible    draw on the WSLg desktop instead of the slot's hidden Xvfb
#                display (the default: windows popping up are disruptive;
#                shot.sh shows a hidden run)
#   --audio      play sound through WSLg's PulseAudio (default: no audio
#                device - the game runs silent).  PAD_AUDIO_CTL (the app's
#                audio_ctl.json, a WSL path) makes its level follow the
#                app's Volume / Mute, live (spkvol.py)
#
# The game sees the machine's /game in a private mount namespace.  /game
# itself is $NV/game, kept between runs, because that is where the games
# keep settings, audits and high scores - each in folders of its own
# choosing (code/config, audits, game_settings...).  Bound over it:
#   /game/code/uptest   the game, hard-linked into $SPK_RIG/game (the game
#                       writes marker files beside itself, never the cache)
#   /game/code/assets   its media, for the titles that keep it apart
#                       (Texas Chainsaw, Evil Dead)
#   /game/logs, /game/tmp, /game/media, /game/backup, /game/update  per run
# and its own hostname ("pad-rig-<slot>"): Beetlejuice is in its built-in
# VIRTUAL mode unless the hostname says "haunted-mansion".  The other titles
# have no such mode, so the machine's root and power commands they shell
# out to (sudo, unlock-root, reboot, avrdude, timedatectl...) are no-ops
# first on the game's PATH, logged to $SPK_RIG/shell.log.
# Switches: sw.py.  Picture: shot.sh.  Stop: killgame.sh.
set -u
. "$(dirname "$0")/spkpath.sh"
ARGS=("$@")             # a start again on the CPU runs this script again
BUILD=${1:-}; shift 2>/dev/null || true
VISIBLE=0; AUDIO=0
while [ $# -gt 0 ]; do
    case "$1" in
        --visible) VISIBLE=1 ;;
        --audio) AUDIO=1 ;;
        *) echo "run_game.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
case "$BUILD" in /*) ;; "") ;; *) BUILD=$SPK_CACHE/$BUILD ;; esac
[ -n "$BUILD" ] && { [ -x "$BUILD/main.x86_64" ] || [ -x "$BUILD/uptest/main.x86_64" ]; } ||
    { echo "run_game.sh: not a prepared build: ${BUILD:-<none>} (prepare.sh)" >&2; exit 2; }
[ -f "$SPK_SHIM" ] || { echo "run_game.sh: no $SPK_SHIM (build.sh)" >&2; exit 2; }
AUDIO=$(rigboard_audio "$VISIBLE" "$AUDIO")
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to $SPK_USER itself)" >&2; exit 2; }
[ -n "$SPK_USER" ] || { echo "run_game.sh: no ordinary user account to run the game as" >&2; exit 2; }

# Which game: prepare.sh wrote it; a cache from before it did is Beetlejuice.
TITLE=$(cat "$BUILD/.pad_title" 2>/dev/null || echo bj)
tget() { python3 "$SPK_TOOLS/spktitles.py" get "$TITLE" "$1"; }
ENGINE=$(tget engine); LAYOUT=$(tget layout)
SPK_TITLE_KEY=$TITLE; SPK_ATTRACT=$(tget attract); SPK_ATTRACT_IN=$(tget attract_in)
FACTORY=$(tget factory_defaults)
[ -n "$ENGINE" ] || { echo "run_game.sh: unknown title $TITLE" >&2; exit 2; }

bash "$SPK_TOOLS/killgame.sh" >/dev/null 2>&1

rm -rf "$SPK_RIG"
G=$SPK_RIG/game
mkdir -p "$SPK_RIG"/{logs,tmp,media,backup,update,bin,lib}
# The shim and the Godot titles' libXinerama stub are loaded from this slot's
# folder, never from the rig's: an installed app's rig is /mnt/c/Program
# Files/..., and both the launch line below (word-split) and LD_PRELOAD
# itself (a space-separated list) break a path at its spaces - env ran
# "Files/Pinball" and the game never started (PAD-313).
cp "$SPK_SHIM" "$SPK_RIG/spkshim.so"
cp "$SPK_TOOLS"/lib/* "$SPK_RIG/lib/" 2>/dev/null
cp -al "$(realpath "$BUILD")" "$G"
UPTEST=$G; [ "$LAYOUT" = code ] && UPTEST=$G/uptest
# Settings, audits, high scores and the game's home outlive a run, as on a
# machine: per slot and title, outside the rig dir.  SPK_FRESH=1 starts over.
NV=$SPK_ROOT/nv$SPK_SLOT/$TITLE
[ "${SPK_FRESH:-0}" = 1 ] && rm -rf "$NV"
CFG=$NV/game/code/config
mkdir -p "$CFG" "$NV/game/audits" "$NV/home"
# An update's config/ (light and asset lists) is the game's, fresh each time.
[ -d "$G/config" ] && cp -a "$G/config/." "$CFG/"
# A machine leaves the factory with its defaults saved (service menu); a
# fresh Beetlejuice settings folder without them stops attract behind a
# "FACTORY DEFAULT SETTINGS HAVE NOT BEEN SAVED" dialog.  {} = the build's own.
[ -n "$FACTORY" ] && [ ! -f "$CFG/$FACTORY" ] && echo '{}' > "$CFG/$FACTORY"
# Files a machine leaves the factory with, from the update's own defaults
# (spktitles "seed": <in /game>:<in the update>).  Halloween without its
# highscores.config writes one from its defaults and then dies syncing it
# through a board it has not opened yet; the file it leaves (vanity awards
# "null") kills every later start too, so that one is replaced.
for s in $(tget seed); do
    dst=$NV/game/${s%%:*}; src=$G/${s#*:}
    { [ ! -s "$dst" ] || grep -qx null "$dst"; } && [ -f "$src" ] && cp "$src" "$dst"
done
# Scooby-Doo compares ~/.profile with its own and reboots to install it.
[ -f "$UPTEST/_profile" ] && cp "$UPTEST/_profile" "$NV/home/.profile"
chown -R "$SPK_USER": "$NV"
for c in sudo unlock-root lock-root reboot shutdown poweroff halt systemctl \
         avrdude timedatectl hwclock swaymsg xrandr wpctl; do
    printf '#!/bin/sh\necho "$(date +%%T) %s $*" >> %s/shell.log\nexit 0\n' \
        "$c" "$SPK_RIG" > "$SPK_RIG/bin/$c"
done
# The cabinet's kernel, for a game that picks its PC model by it.
UNAME=$(tget uname)
[ -n "$UNAME" ] && printf '#!/bin/sh\n[ "$*" = -r ] && echo %s && exit 0\nexec /bin/uname "$@"\n' \
    "$UNAME" > "$SPK_RIG/bin/uname"
chmod 755 "$SPK_RIG"/bin/*
echo "$BUILD" > "$SPK_RIG/build"
echo "$TITLE" > "$SPK_RIG/title"
touch "$(realpath "$BUILD")/used"            # the Cache window's "Last played"
echo "$VISIBLE" > "$SPK_RIG/visible"
chown -R "$SPK_USER": "$SPK_RIG"

# The board first: the games open /dev/WARDEN once at start, then retry.
# At real-time priority: Beetlejuice gives each serial write 20 ms, and while
# it loads (or draws on llvmpipe) it has every core busy; an ordinary-priority
# board that misses its turn makes the game reset its board link and stop
# reacting to switches (PAD-266).  The board sleeps in select(), so this
# costs nothing when idle.  Plain nice where chrt is refused.
PRIO="nice -n -10"
chrt -r 10 true 2>/dev/null && PRIO="chrt -r 10"
setsid -f env SPK_MARK="$SPK_RIG" SPK_TITLE="$TITLE" $PRIO runuser -u "$SPK_USER" -- \
    python3 -u "$SPK_TOOLS/spkwarden.py" "$SPK_RIG" < /dev/null > "$SPK_RIG/warden.out" 2>&1
for _ in $(seq 1 50); do [ -s "$SPK_RIG/warden.tty" ] && break; sleep 0.1; done
TTY=$(cat "$SPK_RIG/warden.tty" 2>/dev/null)
[ -n "$TTY" ] || { echo "run_game.sh: the board did not come up:" >&2; cat "$SPK_RIG/warden.out" >&2; exit 1; }
# The virtual playfield's table (the AP window's format; spkswitches.py).
SPK_TITLE=$TITLE python3 "$SPK_TOOLS/spkswitches.py" "$SPK_RIG" || echo "run_game.sh: no switches.json - the virtual playfield will not open" >&2

# The cabinet's screen is 1920x1080; on the desktop a window that size
# would cover it, so a visible run draws at 1280x720 (the games scale).
W=1920; H=1080
if [ $VISIBLE = 1 ]; then
    DISP=${DISPLAY:-:0}
    W=1280; H=720
else
    DISP=$SPK_DISPLAY
    setsid -f Xvfb "$DISP" -screen 0 1920x1080x24 -nolisten tcp \
        < /dev/null > "$SPK_RIG/xvfb.log" 2>&1
    for _ in $(seq 1 50); do [ -e "/tmp/.X11-unix/X${DISP#:}" ] && break; sleep 0.1; done
    pgrep -xf "Xvfb $DISP .*" | head -1 > "$SPK_RIG/xvfb.pid"
fi
echo "$DISP" > "$SPK_RIG/display"
echo "${W}x${H}" > "$SPK_RIG/window"

if [ $AUDIO = 1 ] && [ -S "$SPK_PULSE" ]; then
    AUDIO_ENV="PULSE_SERVER=unix:$SPK_PULSE"; GODOT_AUDIO=PulseAudio
else
    AUDIO_ENV="PULSE_SERVER=unix:/nonexistent SDL_AUDIODRIVER=dummy"; GODOT_AUDIO=Dummy
fi

LIBS=
if [ "$ENGINE" = godot ]; then
    # Godot 4.1 will not start without a libXinerama (xinerama_stub.c).
    ldconfig -p | grep -q 'libXinerama\.so\.1 ' || LIBS="LD_LIBRARY_PATH=$SPK_RIG/lib"
    # The project asks for Vulkan (Forward+); the compatibility renderer
    # runs on Mesa's OpenGL (the GPU through d3d12, below, or llvmpipe).
    # Its log is stdout.
    RUN="./main.x86_64 --rendering-method gl_compatibility --rendering-driver opengl3 \\
    --windowed --resolution ${W}x${H} --position 0,0 --max-fps 60 \\
    --audio-driver $GODOT_AUDIO >> $SPK_RIG/player.log 2>&1"
else
    RUN="./main.x86_64 -logFile $SPK_RIG/player.log -screen-fullscreen 0 \\
    -screen-width $W -screen-height $H -force-glcore"
fi

# The renderer.  Mesa's llvmpipe (software, on the CPU) was the default and
# drew the game at a crawl on the desktop.  WSL gives Linux the Windows GPU
# (/dev/dxg + /usr/lib/wsl/lib/libd3d12.so) and Mesa's d3d12 driver renders
# OpenGL on it - on WSLg's desktop and on a hidden Xvfb alike.  SPK_GL=
# llvmpipe forces the CPU.  Mesa does NOT fall back by itself: with d3d12
# named and a GPU it cannot use, every GL context is refused ("glx: failed
# to create drisw screen", X_GLXCreateContext BadValue) and the game dies
# before attract - so a start that died that way runs again on llvmpipe
# (PAD-917, the end of this script).  The frame rate: Mesa's HUD samples
# it, draws nothing (GALLIUM_HUD_VISIBLE=false) and appends it to
# $SPK_RIG/hud/fps; status.sh reports the latest.
GL=${SPK_GL:-auto}
if [ "$GL" = auto ]; then
    GL=llvmpipe
    [ -e /dev/dxg ] && [ -e /usr/lib/wsl/lib/libd3d12.so ] && GL=d3d12
fi
echo "$GL" > "$SPK_RIG/gl"
# What a refused GL context leaves in the logs (Mesa/X for Unity, Godot's own).
SPK_GL_REFUSED='glx: failed|X_GLXCreateContext|libGL error|Unable to create .*context|Your video card drivers seem not to support'
mkdir -p "$SPK_RIG/hud"; chown "$SPK_USER": "$SPK_RIG/hud"
GL_ENV="GALLIUM_DRIVER=$GL GALLIUM_HUD=fps GALLIUM_HUD_VISIBLE=false GALLIUM_HUD_PERIOD=1 GALLIUM_HUD_DUMP_DIR=$SPK_RIG/hud"
# libd3d12 lives in /usr/lib/wsl/lib; it joins $LIBS (a Godot title's
# libXinerama stub folder may already be there) - one LD_LIBRARY_PATH.
if [ "$GL" = d3d12 ]; then
    if [ -n "$LIBS" ]; then LIBS="$LIBS:/usr/lib/wsl/lib"; else LIBS="LD_LIBRARY_PATH=/usr/lib/wsl/lib"; fi
fi

cat > "$SPK_RIG/ns.sh" <<EOF
hostname pad-rig-$SPK_SLOT
mkdir -p /game && mount --bind "$NV/game" /game || exit 1
mkdir -p /game/code/uptest /game/code/assets /game/logs /game/tmp /game/media \\
    /game/backup /game/update /game/vosk
mount --bind "$UPTEST" /game/code/uptest
[ -d "$G/assets" ] && [ "$LAYOUT" = code ] && mount --bind "$G/assets" /game/code/assets
for d in logs tmp media backup update; do mount --bind "$SPK_RIG/\$d" /game/\$d; done
chown "$SPK_USER": /game /game/code /game/vosk
cd /game/code/uptest || exit 1
exec runuser -u $SPK_USER -- env -i PATH=$SPK_RIG/bin:/usr/local/bin:/usr/bin:/bin \\
    HOME=$NV/home USER=$SPK_USER LANG=C.UTF-8 DISPLAY=$DISP $AUDIO_ENV \\
    SPK_MARK=$SPK_RIG LP_NUM_THREADS=${SPK_LP_THREADS:-4} $GL_ENV \\
    SPK_WARDEN=$TTY LD_PRELOAD=$SPK_RIG/spkshim.so $LIBS \\
    $RUN
EOF
# Detached whole (setsid -f, stdin closed): a child of runuser dies with the
# wsl.exe that started this (tools/bof_emu learned it).
setsid -f unshare -m -u --propagation private bash "$SPK_RIG/ns.sh" \
    < /dev/null > "$SPK_RIG/game.out" 2>&1
# The app's Volume / Mute, live, as on the AP rig: spkvol.py holds this
# slot's stream at the level in the control file every Emulate tab writes.
# It waits for the game, and ends with it.
if [ $AUDIO = 1 ] && [ -n "${PAD_AUDIO_CTL:-}" ] && [ -S "$SPK_PULSE" ]; then
    setsid -f python3 "$SPK_TOOLS/spkvol.py" --ctl "$PAD_AUDIO_CTL" --rig "$SPK_RIG" --pulse "unix:$SPK_PULSE" \
        < /dev/null >> "$SPK_RIG/spkvol.log" 2>&1
fi
for _ in $(seq 1 50); do
    p=$(spk_slot_pids | while read -r q; do grep -q main.x86_64 /proc/$q/cmdline 2>/dev/null && echo $q; done | head -1)
    [ -n "$p" ] && { echo "$p" > "$SPK_RIG/game.pid"; break; }
    sleep 0.1
done

# Up = attract mode started (spk_attract: the game's log says so, or for
# Looney Tunes the board's).  Loading several GB of media takes a while on a
# spinning disk.
for i in $(seq 1 3000); do
    spk_attract && break
    [ "$i" -gt 100 ] && ! spk_game_alive && break
    sleep 0.1
done
if spk_game_alive && spk_attract; then
    echo "Ready: $(basename "$BUILD"), slot $SPK_SLOT, display $DISP"
    # the rig folder rides the record (PAD-952): a Visual Pinball table's
    # controller finds the board's vpxhw.state there (spkbridge.py)
    RIGBOARD_ROOT=$SPK_RIG rigboard_post spooky "$SPK_SLOT" "$(spk_game_pid)" "$(basename "$BUILD")" "${PAD_TITLE:-$(tget name)}" "$VISIBLE" "$AUDIO"
    # The playfield window's keys in the game's own window too (PAD-313),
    # except the keys the game already acts on there (spktitles own_keys):
    # on the desktop (PAD_GAMEKEYS=1 forces it on a hidden run, for tests).
    # It ends with the game.
    if [ "${PAD_GAMEKEYS:-$VISIBLE}" = 1 ]; then
        setsid -f python3 -u "$SPK_TOOLS/../ap_emu/gamekeys.py" --display "$DISP" \
            --mark "SPK_MARK=$SPK_RIG" --sock "$SPK_RIG/ctl.sock" \
            --pidfile "$SPK_RIG/game.pid" --table "$SPK_RIG/switches.json" \
            --skip "$(tget own_keys 2>/dev/null)" \
            < /dev/null > "$SPK_RIG/gamekeys.log" 2>&1
    fi
elif [ "$GL" = d3d12 ] && [ "${SPK_GL:-auto}" = auto ] && ! spk_game_alive &&
     grep -qsE "$SPK_GL_REFUSED" "$SPK_RIG/player.log" "$SPK_RIG/game.out"; then
    # The GPU path refused a GL context (PAD-917: Evil Dead and Ultraman on
    # a PC whose d3d12 would not start, every start "exit 6").  The GPU is
    # only faster; the CPU still plays.  Once: SPK_GL=llvmpipe is no "auto".
    echo "run_game.sh: the GPU renderer (d3d12) would not start on this PC; starting again on the CPU (llvmpipe):" >&2
    grep -hsE "$SPK_GL_REFUSED" "$SPK_RIG/player.log" "$SPK_RIG/game.out" | head -n 3 >&2
    bash "$SPK_TOOLS/killgame.sh" >/dev/null 2>&1
    SPK_GL=llvmpipe exec bash "$SPK_TOOLS/run_game.sh" "${ARGS[@]}"
else
    echo "run_game.sh: the game did not reach attract:" >&2
    # each log on its own: `tail -20 a b` is refused outright ("option used
    # in invalid context") and printed nothing at all (PAD-313)
    for f in "$SPK_RIG/player.log" "$SPK_RIG/warden.log" "$SPK_RIG/warden.out" \
             "$SPK_RIG/game.out"; do
        [ -s "$f" ] && { echo "--- $(basename "$f")"; tail -n 20 "$f"; }
    done >&2
    exit 1
fi
