#!/bin/bash
# padselect.sh - the Spooky Pinball multi-boot launcher (PAD-980, tools/spooky_emu/MULTIBOOT.md).
#
# A multi-boot is ONE update file of the game's own kind (a .scooby, a .beetlejuice, a
# .looney ...), installed with the machine's own UPDATE SOFTWARE.  The machine unpacks it
# into /game/code/uptest, the folder its desktop (sway or i3) starts the game from, as
# uptest/main.x86_64 - which in a multi-boot update is THIS script.  At every power-up it:
#
#   0. the first time after an install, moves the update's pad/ out of uptest into /game/pad:
#      the machine's next install backs up ALL of uptest and then wipes it, so builds kept
#      there would be copied once more and lost; outside it they cost nothing then, and a
#      stock update leaves the menu out of the picture by replacing main.x86_64;
#   1. makes every build the update carries that is not made yet (builds.txt): a hard-linked
#      copy of build 0 (the stock one, carried whole) with the build's own files laid over;
#   2. points the machine's paths at the chosen build: every entry of uptest/ except this
#      script (and the game's .update_file / .backup_file markers) is a symlink into
#      /game/pad/live/uptest/, every other root the conf names
#      (root=<name> <absolute path>: /game/code/assets on the titles that keep media there)
#      a symlink to pad/live/<name>, and pad/live itself a symlink to pad/b<k> - so the
#      switch is one rename;
#   3. shows the boot menu (spkselect on the X server, the flippers and START through spksw
#      on the playfield board);
#   4. starts the chosen build's program from its own folder (pad/b<k>/<exe>), so the
#      engine finds its data beside it (Unity: main_Data; Godot: the pack inside), with the
#      working directory the game always had.
#
#   pad/spk.conf     the machine: board=warden|pinotaur, dev=, L=, R=, S= (switch numbers),
#                    exe= (the program under a build, default uptest/main.x86_64), root= lines
#   pad/images.conf  the menu; image=b<k>|<title>|<subtitle>...
#   pad/builds.txt   "b<k> <files>" per build after the first: <files> its files' folder
#                    under pad/ (a tree like a build's: uptest/..., assets/...)
#
# EVERY FAILURE ENDS ON BUILD 0, the stock build the update carries whole, and if even that
# cannot start, on whatever pad/live points at.  Nothing here is allowed to keep the machine
# from starting a game: no conf, no menu program, a menu that dies or hangs (killed after
# its own timeout and a minute), a build that cannot be made, a choice that names nothing.
#
# PADSELECT_HOME moves /game/pad; PADSELECT_TOP moves uptest (the tests: the folder this script stands in by default);
# PADSELECT_SW replaces spksw (the tests: a script printing its lines); PADSELECT_MENU_ARGS
# adds menu options; PADSELECT_AUDIO_PLAYER replaces aplay; PADSELECT_DRY=1 prints what
# would be started instead of starting it.
SELF=$(readlink -f "$0" 2>/dev/null || echo "$0")
TOP=${PADSELECT_TOP:-$(dirname "$SELF")}
P=${PADSELECT_HOME:-/game/pad}
SPK=$P/spk.conf
CONF=$P/images.conf
BUILDS=$P/builds.txt
CHOICE=$P/choice
LOG=$P/padselect.log
ME=$(basename "$SELF")

# ---- 0. a fresh install: uptest/pad -> /game/pad (one rename: the same file system) ----
moved=""
if [ -d "$TOP/pad" ] && [ ! -L "$TOP/pad" ]; then
    mkdir -p "$(dirname "$P")" 2>/dev/null
    rm -rf "$P.old"
    { [ ! -e "$P" ] || mv -T "$P" "$P.old"; } && mv -T "$TOP/pad" "$P" && moved=1
    if [ -n "$moved" ]; then rm -rf "$P.old"; sync
    else P=$TOP/pad                 # cannot move it: run it where it is
    fi
fi
[ -f "$LOG" ] && mv -f "$LOG" "$LOG.1" 2>/dev/null
{ exec 3>>"$LOG"; } 2>/dev/null || exec 3>/dev/null
say() { echo "$(date '+%F %T') $*" >&3; }
say "start ($*) in $TOP, home $P${moved:+ (moved there from the update)}"
ARGS=("$@")

conf() {        # conf <key> <default>: the last <key>= line of spk.conf
    local v=""
    [ -f "$SPK" ] && v=$(sed -n "s/^$1=//p" "$SPK" | tail -1 | tr -d '\r')
    echo "${v:-$2}"
}
EXE=$(conf exe uptest/main.x86_64)

# ---- 2. the machine's paths -> pad/live ------------------------------------
# uptest's own entries: a symlink per entry of the build's uptest/, through pad/live
# (never this script, never pad/); an entry the build lacks is removed when it is one of
# our links and left alone otherwise
link_top() {
    local src=$P/live/uptest e name
    [ -d "$src" ] || { say "paths: pad/live has no uptest/"; return 1; }
    for e in "$src"/* "$src"/.[!.]*; do
        [ -e "$e" ] || [ -L "$e" ] || continue
        name=${e##*/}
        case "$name" in "$ME"|pad|.update_file|.backup_file) continue ;; esac
        if [ -L "$TOP/$name" ] && [ "$(readlink "$TOP/$name")" = "$P/live/uptest/$name" ]; then continue; fi
        rm -rf "$TOP/$name" 2>/dev/null
        ln -s "$P/live/uptest/$name" "$TOP/$name" || say "paths: cannot link $name"
    done
    for e in "$TOP"/* "$TOP"/.[!.]*; do
        [ -L "$e" ] || continue
        name=${e##*/}
        case "$(readlink "$e")" in "$P"/live/uptest/*|pad/live/uptest/*) [ -e "$e" ] || rm -f "$e" ;; esac
    done
}
# the other roots: /game/code/assets and the like, each a symlink to pad/live/<name>.  A
# real folder there (the stock install's) moves into pad/stock_<name> once - build 0's own
# copy wins when it carries one.
link_roots() {
    local name path
    [ -f "$SPK" ] || return 0
    while read -r name path; do
        [ -n "$name" ] && [ -n "$path" ] || continue
        if [ -L "$path" ]; then
            [ "$(readlink "$path")" = "$P/live/$name" ] && continue
            rm -f "$path"
        elif [ -e "$path" ]; then
            rm -rf "$P/stock_$name"
            mv "$path" "$P/stock_$name" || { say "paths: cannot move $path aside"; continue; }
            say "paths: the machine's $path kept as pad/stock_$name"
        fi
        ln -s "$P/live/$name" "$path" || say "paths: cannot link $path"
    done < <(sed -n 's/^root=//p' "$SPK" | tr -d '\r')
}
point_at() {    # point_at b<k>: pad/live -> b<k> (one rename), then every path
    ln -sfn "$1" "$P/live.new" && mv -T "$P/live.new" "$P/live" || return 1
    sync
    link_top && link_roots
    say "paths: live = $1"
}

boot() {        # boot b<k>: never returns when it starts something
    local b=$1 prog
    prog=$P/$b/$EXE
    if [ -n "${PADSELECT_DRY:-}" ]; then echo "would start $prog ${ARGS[*]}"; say "dry run: $b"; exit 0; fi
    say "starting $b: $prog"
    exec 3>&-
    chmod +x "$prog" 2>/dev/null
    cd "$TOP" 2>/dev/null
    exec "$prog" "${ARGS[@]}"
}
fallback() {    # build 0, whatever happened
    say "falling back: $*"
    if [ -f "$P/b0/$EXE" ]; then
        point_at b0 && boot b0
    fi
    local cur
    cur=$(readlink "$P/live" 2>/dev/null)
    [ -n "$cur" ] && [ -f "$P/$cur/$EXE" ] && boot "$cur"
    say "nothing to start"
    exit 1
}

[ -f "$P/b0/$EXE" ] || fallback "no build 0 ($P/b0/$EXE)"
[ -f "$CONF" ] || fallback "no $CONF"

# ---- 1. the builds -----------------------------------------------------------
make_build() {  # make_build b<k> <files>
    local b=$1 files=$2 part=$P/$1.partial stamp
    stamp="$files $(stat -c %Y "$P/$files" 2>/dev/null)"
    if [ -f "$P/$b/$EXE" ] && [ "$(cat "$P/$b/.pad_build" 2>/dev/null)" = "$stamp" ]; then
        return 0
    fi
    [ -d "$P/$files" ] || { say "build $b: no $P/$files"; return 1; }
    say "build $b: making it from b0 + $files"
    rm -rf "$part"
    cp -al "$P/b0" "$part" || { rm -rf "$part"; say "build $b: cannot copy b0"; return 1; }
    # the build's files over it: links into pad/, each name removed first (a copy onto a
    # hard link would write through it into build 0's file)
    cp -al --remove-destination "$P/$files/." "$part/" \
        || { rm -rf "$part"; say "build $b: cannot lay its files"; return 1; }
    # files the build deletes from build 0 (one path per line, relative to the build)
    if [ -f "$P/$files.removed" ]; then
        while IFS= read -r rel; do
            case "$rel" in ""|/*|*..*) continue ;; esac
            rm -rf "$part/$rel"
        done < "$P/$files.removed"
    fi
    [ -f "$part/$EXE" ] || { rm -rf "$part"; say "build $b: no $EXE in it"; return 1; }
    rm -rf "$P/$b" && mv "$part" "$P/$b" || { rm -rf "$part"; return 1; }
    echo "$stamp" > "$P/$b/.pad_build"
    sync
    say "build $b: made"
}
if [ -f "$BUILDS" ]; then
    while read -r b files rest; do
        case "$b" in ""|\#*) continue ;; esac
        case "$b" in b[1-9]|b[1-9][0-9]) ;; *) say "build line '$b': not a build name"; continue ;; esac
        make_build "$b" "$files" || say "build $b: left out"
    done < <(tr -d '\r' < "$BUILDS")
fi

# ---- the menu's cards: what each boots --------------------------------------
targets=()
while IFS= read -r line; do
    case "$line" in image=*) f=${line#image=}; targets+=("${f%%|*}") ;; esac
done < <(tr -d '\r' < "$CONF")
n=${#targets[@]}
[ "$n" -ge 1 ] || fallback "no image= lines"
# the first boot has no pad/live yet: build 0's paths, so the menu's sounds and anything
# the desktop reads are there while it shows
[ -L "$P/live" ] || point_at b0 || fallback "cannot point the paths at b0"

# ---- 3. the menu ---------------------------------------------------------------
timeout_s=$(sed -n 's/^timeout=\([0-9][0-9]*\).*/\1/p' "$CONF" | tail -1)
[ -n "$timeout_s" ] || timeout_s=10
[ "$timeout_s" -gt 0 ] 2>/dev/null || timeout_s=600

# SOUND: as the Big Lebowski hook - the static menu streams its mix into a pipe and the
# machine's own player plays it, started only when the conf names a sound, and stopped and
# WAITED FOR before the game opens the sound card
has_sound() {
    grep -qE '^sound_(move|confirm)=[^[:space:]]' "$CONF" && return 0
    awk -F'|' '/^(image|group)=/ { for (i = 6; i <= 7; i++) if ($i != "" && $i != "none") f = 1 }
               END { exit !f }' "$CONF"
}
AUDIO=none; FIFO=""; player=""
start_player() {
    local play=${PADSELECT_AUDIO_PLAYER:-}
    if [ -z "$play" ]; then
        if command -v pacat >/dev/null 2>&1; then play="pacat --raw --format=s16le --rate=44100 --channels=2"
        elif command -v pw-cat >/dev/null 2>&1; then play="pw-cat --playback --format=s16 --rate=44100 --channels=2 -"
        elif command -v aplay >/dev/null 2>&1; then play="aplay -q -t raw -f S16_LE -r 44100 -c 2 -B 80000 -F 20000"
        else say "sound: no player on this machine: the menu is silent"; return 0
        fi
    fi
    FIFO=$(mktemp -u /tmp/padselect.audio.XXXXXX) || return 0
    mkfifo -m 600 "$FIFO" 2>/dev/null || { say "sound: no pipe: the menu is silent"; FIFO=""; return 0; }
    ( exec timeout -k 2 $((timeout_s + 70)) $play <"$FIFO" >/dev/null 2>>"$P/audio.log" ) &
    player=$!
    AUDIO="fifo:$FIFO"
    say "sound: ${play%% *}, pid $player"
}
stop_player() {
    local i
    if [ -n "$player" ]; then
        for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$player" 2>/dev/null || break; sleep 0.2; done
        kill "$player" 2>/dev/null; wait "$player" 2>/dev/null
        say "sound: player stopped"
    fi
    [ -n "$FIFO" ] && rm -f "$FIFO"
    player=""; FIFO=""
}

choice=""
if [ "$n" -lt 2 ]; then
    say "one image: no menu"
    choice=0
elif [ ! -x "$P/spkselect" ]; then
    say "no menu program at $P/spkselect"
else
    rm -f "$CHOICE"
    BTN=$(mktemp -u /tmp/padselect.buttons.XXXXXX)
    sw=""
    board=$(conf board warden)
    if [ "$board" = pinotaur ]; then dl=81; ddev=/dev/pinheck; else dl=86; ddev=/dev/WARDEN; fi
    L=$(conf L $dl); R=$(conf R 80); S=$(conf S 87); dev=$(conf dev $ddev)
    if mkfifo -m 600 "$BTN" 2>/dev/null; then
        if [ -n "${PADSELECT_SW:-}" ]; then
            $PADSELECT_SW L="$L" R="$R" S="$S" >"$BTN" 2>>"$P/spksw.log" &
        else
            "$P/spksw" --dev "$dev" --board "$board" L="$L" R="$R" S="$S" >"$BTN" 2>>"$P/spksw.log" &
        fi
        sw=$!
        say "buttons: $board at $dev, L=$L R=$R S=$S, reader pid $sw"
    else
        say "cannot make the button pipe: no buttons"; BTN=/dev/null
    fi
    if has_sound; then start_player; fi
    say "menu: $n images, timeout ${timeout_s}s"
    timeout -k 5 $((timeout_s + 60)) "$P/spkselect" --input pipe --conf "$CONF" --out "$CHOICE" \
        --last "$P/last" --log "$P/spkselect.log" --audio "$AUDIO" --font "$P/font.ttf" \
        --media "$P/media" --no-invert ${PADSELECT_MENU_ARGS:-} <"$BTN" >/dev/null 2>&1
    rc=$?
    # the board is the game's next: the reader must be gone before it opens the port
    if [ -n "$sw" ]; then
        kill "$sw" 2>/dev/null
        for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$sw" 2>/dev/null || break; sleep 0.1; done
        kill -9 "$sw" 2>/dev/null; wait "$sw" 2>/dev/null
    fi
    [ "$BTN" != /dev/null ] && rm -f "$BTN"
    stop_player
    choice=$(head -c 16 "$CHOICE" 2>/dev/null | tr -dc '0-9')
    say "menu exit $rc, choice '$choice'"
fi
case "$choice" in ''|*[!0-9]*) choice=0 ;; esac
[ "$choice" -lt "$n" ] || choice=0
target=${targets[$choice]}
case "$target" in b[0-9]|b[1-9][0-9]) ;; *) fallback "image $choice names '$target'" ;; esac
[ -f "$P/$target/$EXE" ] || fallback "image $choice ($target) is not made"

# ---- 4. the game ----------------------------------------------------------------
point_at "$target" || fallback "cannot point the paths at $target"
boot "$target"
