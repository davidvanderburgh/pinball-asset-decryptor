#!/bin/bash
# run_game.sh <binary> <profile.json> [--visible] [--audio] [--detach]
#
# Start a Barrels of Fun game on this PC: the emulated boards (bofhw.py), the
# port shim, and the game itself.  Run as root (it switches users itself).
#
#   --visible  draw on the WSLg desktop (GPU) instead of the slot's hidden
#              Xvfb display (the default: windows popping up are disruptive;
#              shot.sh shows a hidden run)
#   --audio    play sound through WSLg's PulseAudio (default: muted)
#   --detach   return once the game is up; killgame.sh stops it
#
# THE HOST MUST BE PROTECTED FROM THE GAME.  It shells out through
# OS.execute("sudo", ...) - `mount -o remount,ro /` around every settings save,
# plus sync, systemctl, iwctl, bluetoothctl, dhcpcd, reboot.  As root in a WSL
# distro the first of those remounts the whole distro read-only.  So the game
# runs as an ordinary user, and a logging no-op sudo (and friends) is first on
# its PATH.  Every attempt lands in $BOF_RIG/sudo.log.
#
# Rendering: the Godot 4 compatibility (OpenGL) renderer.  The titles are
# built for Forward+ (Vulkan) but draw identically under it, and OpenGL is what
# both WSLg (GPU, via d3d12) and a hidden Xvfb (llvmpipe) provide without a
# Vulkan driver in the distro.
set -u
. "$(dirname "$0")/bofpath.sh"
BIN=${1:-}; PROFILE=${2:-}; shift 2 2>/dev/null || true
VISIBLE=0; AUDIO=0; DETACH=0
for a in "$@"; do
    case "$a" in
        --visible) VISIBLE=1 ;;
        --audio) AUDIO=1 ;;
        --detach) DETACH=1 ;;
        *) echo "run_game.sh: unknown option $a" >&2; exit 2 ;;
    esac
done
[ -x "$BIN" ] || { echo "run_game.sh: not an executable game binary: $BIN" >&2; exit 2; }
[ -f "$PROFILE" ] || { echo "run_game.sh: no profile: $PROFILE" >&2; exit 2; }
[ -f "$BOF_SHIM" ] || { echo "run_game.sh: missing $BOF_SHIM" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to $BOF_USER itself)" >&2; exit 2; }
[ -n "$BOF_USER" ] || { echo "run_game.sh: no ordinary user account to run the game as" >&2; exit 2; }

bash "$BOF_TOOLS/killgame.sh" >/dev/null 2>&1
AUDIO=$(rigboard_audio "$VISIBLE" "$AUDIO")

TITLE=$(basename "$PROFILE" .json)
HOMEDIR=$BOF_HOMES/$TITLE
rm -rf "$BOF_RIG"
mkdir -p "$BOF_RIG/bin" "$BOF_RIG/hw" "$HOMEDIR"
# The shim is preloaded from this slot's folder, never from the rig's: an
# installed app's rig is /mnt/c/Program Files/..., and LD_PRELOAD is a
# space-separated list - ld.so tried "/mnt/c/Program", "Files/Pinball"...,
# ignored them all, and the game never found its boards (PAD-313).
cp "$BOF_SHIM" "$BOF_RIG/bofhwshim.so"
echo "$BIN" > "$BOF_RIG/binary"
echo "$TITLE" > "$BOF_RIG/title"
echo "$VISIBLE" > "$BOF_RIG/visible"

# The no-op sudo, and the commands the game runs directly.
cat > "$BOF_RIG/bin/sudo" <<'EOF'
#!/bin/sh
echo "$(date +%T) $(basename "$0") $*" >> "$BOFEMU_LOG_DIR/sudo.log"
exit 0
EOF
chmod 755 "$BOF_RIG/bin/sudo"
for t in systemctl iwctl bluetoothctl dhcpcd amixer ping ifconfig reboot shutdown poweroff; do
    ln -sf sudo "$BOF_RIG/bin/$t"
done
chown -R "$BOF_USER": "$BOF_RIG" "$HOMEDIR"

# The boards.  They run as the game's user so it may open their ptys.
#
# EVERYTHING STARTED HERE IS DETACHED WHOLE: `setsid -f` goes OUTSIDE runuser,
# and stdin is closed.  runuser passes the launching session's hang-up on to
# its child, so a game started as `runuser ... setsid game &` quit the moment
# the wsl.exe that ran this returned - i.e. right after watch.sh said Ready.
#
# Plugins (PAD-1305, bofhw.py's doc): PAD's own Visual Pinball bridge
# (bofvpx.py: the kit's PAD.Controller and a line stream for other links),
# then each of BOFHW_PLUGINS (':'-separated) and every *.py in
# $BOF_ROOT/plugins - a folder no PAD update touches, so a link of your own
# keeps working however the run is started.
PLUGINS=(--plugin "$BOF_TOOLS/bofvpx.py")
IFS=: read -ra EXTRA <<< "${BOFHW_PLUGINS:-}"
for p in "${EXTRA[@]}" "$BOF_ROOT"/plugins/*.py; do
    [ -f "$p" ] && PLUGINS+=(--plugin "$p")
done
setsid -f runuser -u "$BOF_USER" -- env BOF_SLOT="$BOF_SLOT" BOF_VPX_PORT="${BOF_VPX_PORT:-}" \
    python3 "$BOF_TOOLS/bofhw.py" \
    --dir "$BOF_RIG/hw" --profile "$PROFILE" --build "$(dirname "$BIN")" "${PLUGINS[@]}" \
    < /dev/null > "$BOF_RIG/hw/daemon.out" 2>&1
for _ in $(seq 1 50); do [ -S "$BOF_RIG/hw/ctl.sock" ] && break; sleep 0.1; done
[ -S "$BOF_RIG/hw/ctl.sock" ] || { echo "run_game.sh: board emulator did not start:" >&2; cat "$BOF_RIG/hw/daemon.out" >&2; exit 3; }

# WHICH GL DRIVER DRAWS A VISIBLE RUN (PAD-1307).  Under WSLg, Mesa in Ubuntu
# 24.04 picks llvmpipe - software, about four CPU cores for one title - with a
# working GPU sitting there behind /dev/dxg.  d3d12 is that GPU (Mesa's d3d12
# gallium driver on WSL's libd3d12core.so), so a visible run asks for it by
# name, exactly as the Spike 2 rig always has (watch.sh), on the GPU Windows
# itself ranks first (gpupick.py; one adapter = nothing picked).
#   * a caller's own GALLIUM_DRIVER wins, as `:-` means everywhere else;
#   * PAD_GL_DRIVER=mesa keeps Mesa's own choice;
#   * a hidden run is untouched: Xvfb has no GPU path, llvmpipe it stays;
#   * off WSL (no /dev/dxg, no WSL D3D12 library) nothing is forced - naming
#     d3d12 on a Linux desktop is a guaranteed failure (PAD-182).
# env -i below drops everything else, so the choice is handed over by name.
GL_ENV=""
if [ $VISIBLE = 1 ]; then
    if [ -n "${GALLIUM_DRIVER:-}" ]; then
        GL_ENV="GALLIUM_DRIVER=$GALLIUM_DRIVER"
    elif [ "${PAD_GL_DRIVER:-}" != mesa ] && [ -e /dev/dxg ] \
            && [ -e /usr/lib/wsl/lib/libd3d12core.so ]; then
        GL_ENV="GALLIUM_DRIVER=d3d12"
        ADAPTER=${PAD_GL_ADAPTER:-$(python3 "$BOF_TOOLS/../spike2_emu/gpupick.py" 2>/dev/null)}
        [ "$ADAPTER" = default ] && ADAPTER=""
        [ -n "$ADAPTER" ] && GL_ENV="$GL_ENV MESA_D3D12_DEFAULT_ADAPTER_NAME=$ADAPTER"
    fi
fi
echo "renderer=${GL_ENV:-mesa-default}"

if [ $VISIBLE = 1 ]; then
    DISP=${DISPLAY:-:0}
else
    DISP=$BOF_DISPLAY
    setsid -f Xvfb "$DISP" -screen 0 3840x1440x24 -nolisten tcp \
        < /dev/null > "$BOF_RIG/xvfb.log" 2>&1
    for _ in $(seq 1 50); do [ -e "/tmp/.X11-unix/X${DISP#:}" ] && break; sleep 0.1; done
    pgrep -xf "Xvfb $DISP .*" | head -1 > "$BOF_RIG/xvfb.pid"
fi
echo "$DISP" > "$BOF_RIG/display"

if [ $AUDIO = 1 ] && [ -S /mnt/wslg/PulseServer ]; then
    AUDIO_ENV="PULSE_SERVER=unix:/mnt/wslg/PulseServer"
    AUDIO_ARG=PulseAudio
else
    AUDIO_ENV=""
    AUDIO_ARG=Dummy
fi

# A window you can move and size.  Every title's project says borderless and
# not resizable (a cabinet's monitor has nothing else on it), which on a desk
# is a 1280x1110 slab with no title bar to drag.  Godot reads override.cfg
# from the executable's folder after the embedded project settings; the game
# code never sets its own window, so this is the whole change.  canvas_items
# stretch scales the picture with the window instead of cropping it (at the
# project size it draws exactly as before).  It opens near the top left, not
# centred: centred, a 1110-high window on a shorter screen puts its title bar
# above the top edge, out of reach.  Only on the desktop: a hidden run stays
# exactly the build as shipped.
#
# PAD_BOF_SPLIT=1 (PAD-1308): the window goes to a cabinet's screens in parts
# (padsplit.py shows each display on its own monitor through a DWM thumbnail
# of this window), so it stays the shipped borderless slab at its own size -
# every part is then at the game's own pixels - and opens off to the left of
# the desktop; padsplit keeps it there.
OVR="$(dirname "$BIN")/override.cfg"
if [ $VISIBLE = 1 ] && [ "${PAD_BOF_SPLIT:-0}" = 1 ]; then
    printf '%s\n' '[display]' 'window/size/borderless=true' \
        'window/size/resizable=false' 'window/size/no_focus=true' > "$OVR"
elif [ $VISIBLE = 1 ]; then
    printf '%s\n' '[display]' 'window/size/borderless=false' \
        'window/size/resizable=true' 'window/stretch/mode="canvas_items"' \
        'window/stretch/aspect="keep"' 'window/size/initial_position_type=0' \
        'window/size/initial_position=Vector2i(40, 40)' > "$OVR"
else
    rm -f "$OVR"
fi

# PAD-1302: AN OLDER CPU'S memcpy INTO THE GPU'S MEMORY - the same fault as the
# Spike 2 renderer's (watch.sh, PAD-357), here in the game itself: Godot draws
# through Mesa d3d12 on WSLg, every frame goes up through an upload buffer in
# GPU-mapped memory (/dev/dxg), and on a CPU without AVX2 (Ivy Bridge: ERMS,
# no AVX2) glibc copies it with `rep movsb`, which crawls on that memory. A
# user's BoF title went from 7-8 to ~20 fps in attract and from 19 to ~32 in
# a game with these thresholds out of reach. No effect on a CPU with AVX2
# (glibc never picks rep movsb at these sizes there), so only those CPUs get
# it. The env is scrubbed below, so a caller's own GLIBC_TUNABLES is passed
# on as it is. PAD_MEMCPY_TUNE=0 never sets it; =1 sets it on any CPU.
BOF_TUNABLES=${GLIBC_TUNABLES:-}
if [ -z "$BOF_TUNABLES" ] && [ "${PAD_MEMCPY_TUNE:-}" != 0 ]; then
    if [ "${PAD_MEMCPY_TUNE:-}" = 1 ] \
            || { grep -q '^flags.*\bsse2\b' /proc/cpuinfo 2>/dev/null \
                 && ! grep -q '^flags.*\bavx2\b' /proc/cpuinfo 2>/dev/null; }; then
        BOF_TUNABLES=glibc.cpu.x86_rep_movsb_threshold=0x40000000:glibc.cpu.x86_rep_stosb_threshold=0x40000000
        echo "run_game.sh: GLIBC_TUNABLES=$BOF_TUNABLES (${PAD_MEMCPY_TUNE:+PAD_MEMCPY_TUNE=1; }vector memcpy into GPU memory on a CPU without AVX2)"
    fi
fi

# PAD-1309: BOF_MENU_SO=<padmenu.so> puts the multi-boot card's EXIT-hold object in front of
# the port shim, as the profile's hook block does on the machine.  The restart it asks for is a
# stand-in that leaves $BOF_RIG/padmenu.restart: a real reboot from the rig is never right (and
# padmenu.so refuses one in a run whose BOFHW_DEV is set and that gives it no stand-in).
MENU_PRE=""
MENU_ARGS=()
if [ -n "${BOF_MENU_SO:-}" ] && [ -f "$BOF_MENU_SO" ]; then
    cp -f "$BOF_MENU_SO" "$BOF_RIG/padmenu.so" && chmod 755 "$BOF_RIG/padmenu.so"
    rm -f "$BOF_RIG/padmenu.restart"
    MENU_PRE="$BOF_RIG/padmenu.so:"
    MENU_ARGS=("CODESELECT_REBOOT=touch $BOF_RIG/padmenu.restart")
    echo "run_game.sh: holding EXIT (switch 5) 5 s asks for a restart ($BOF_RIG/padmenu.restart)"
fi

cd "$BOF_RIG" || exit 3
# shellcheck disable=SC2086
setsid -f runuser -u "$BOF_USER" -- env -i \
    ${BOF_TUNABLES:+GLIBC_TUNABLES=$BOF_TUNABLES} \
    PATH="$BOF_RIG/bin:/usr/local/bin:/usr/bin:/bin" \
    HOME="$HOMEDIR" USER="$BOF_USER" LANG=C.UTF-8 \
    DISPLAY="$DISP" XDG_RUNTIME_DIR="$BOF_RIG" $AUDIO_ENV $GL_ENV \
    BOFEMU_LOG_DIR="$BOF_RIG" GODOT_SILENCE_ROOT_WARNING=1 \
    "${MENU_ARGS[@]}" LD_PRELOAD="$MENU_PRE$BOF_RIG/bofhwshim.so" BOFHW_DEV="$BOF_RIG/hw/dev" BOFHW_SYS="$BOF_RIG/hw/sys" \
    "$BIN" --display-driver x11 --rendering-method gl_compatibility \
        --audio-driver $AUDIO_ARG < /dev/null > "$BOF_RIG/game.log" 2>&1
for _ in $(seq 1 50); do
    GP=$(pgrep -u "$BOF_USER" -xf "$BIN .*" | head -1)
    [ -n "$GP" ] && break
    sleep 0.1
done
[ -n "${GP:-}" ] || { echo "run_game.sh: the game did not start:" >&2; tail -20 "$BOF_RIG/game.log" >&2; exit 4; }
echo "$GP" > "$BOF_RIG/game.pid"
RIGBOARD_ROOT=$BOF_RIG/hw rigboard_post bof "$BOF_SLOT" "$GP" "$TITLE" "${PAD_TITLE:-}" "$VISIBLE" "$AUDIO"
# The playfield window's keys in the game's own window too (PAD-313): on the
# desktop (PAD_GAMEKEYS=1 forces it on a hidden run, for tests).  The game's
# environment carries BOFEMU_LOG_DIR=<this rig>, its mark.  It ends with the
# game.
if [ "${PAD_GAMEKEYS:-$VISIBLE}" = 1 ]; then
    setsid -f python3 -u "$BOF_TOOLS/../ap_emu/gamekeys.py" --display "$DISP" \
        --mark "BOFEMU_LOG_DIR=$BOF_RIG" --sock "$BOF_RIG/hw/ctl.sock" \
        --pidfile "$BOF_RIG/game.pid" --bof-profile "$TITLE" \
        < /dev/null > "$BOF_RIG/gamekeys.log" 2>&1
fi
# A cabinet split (PAD-1308): the window sits under one of padsplit's part
# windows, where PAD_BOF_PLACE says - "<title>:X,Y;...;*:X,Y" in Windows'
# physical pixels, a spot per title (the app only knows the title once the
# .fun is unpacked), "*" for any other, or a bare "X,Y";  bofplace.py puts it
# there and keeps it there.  It ends with the game.
bof_place_at() {
    local kv at="" any="" parts=()
    IFS=';' read -r -a parts <<< "$1"
    for kv in "${parts[@]}"; do
        case "$kv" in
            "$2:"*) at=${kv#*:} ;;
            "*:"*) any=${kv#*:} ;;
            *:*) ;;
            *) any=$kv ;;
        esac
    done
    printf '%s' "${at:-$any}"
}
PLACE_AT=$(bof_place_at "${PAD_BOF_PLACE:-}" "$TITLE")
if [ $VISIBLE = 1 ] && [ "${PAD_BOF_SPLIT:-0}" = 1 ] && [ -n "$PLACE_AT" ]; then
    setsid -f python3 -u "$BOF_TOOLS/bofplace.py" --display "$DISP" \
        --mark "BOFEMU_LOG_DIR=$BOF_RIG" --pidfile "$BOF_RIG/game.pid" \
        --at "$PLACE_AT" < /dev/null > "$BOF_RIG/bofplace.log" 2>&1
fi
echo "pid=$GP"
echo "display=$DISP"
[ $DETACH = 1 ] && exit 0
while kill -0 "$GP" 2>/dev/null; do sleep 1; done
bash "$BOF_TOOLS/killgame.sh" >/dev/null 2>&1
