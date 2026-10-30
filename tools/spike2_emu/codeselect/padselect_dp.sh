#!/bin/bash
# padselect.sh - The Big Lebowski multi-boot launcher (PAD-853, tools/dp_emu/MULTIBOOT.md).
#
# A multi-boot is a TBL update zip, TBL-v<V>.zip, installed with the machine's own USB
# update into ~/game/<V>/ and picked once with its own Version Select.  From then on
# ~/game/run.sh starts THIS, as <V>/start, at every power-up (and at every restart the
# game asks for), with the game's arguments.  It:
#
#   1. makes every build folder the menu names that is not there yet (builds.txt): a
#      hard-linked copy of its base version, the build's files laid over it, its
#      database/ a real copy - what the USB update does with a delta, beside it;
#   2. shows the boot menu (dpselect on the X server, the flippers and START through
#      dpprocsw on the game's own libpinproc);
#   3. carries the settings database to the chosen build when another one ran last -
#      what Version Select does;
#   4. starts the chosen build: cd ../<folder>; exec ./start "$@".  `version` keeps
#      naming <V>, so the next power-up comes back here.
#
#   pad/images.conf  the menu; image=<folder>|<title>|<subtitle>...  <folder> is a
#                    version folder in ~/game, or "stock": the newest stock version there
#   pad/builds.txt   "<folder> <bases> <files>" per build: <bases> the versions it may be
#                    laid over, comma-separated (newest one present wins; "-" = the build
#                    is whole, no base), <files> its files' folder under pad/
#
# EVERY FAILURE ENDS ON THE STOCK VERSION (the newest digits-and-dots folder that is not
# this one and not a build), the way the machine boots without us.  Nothing here is
# allowed to keep the machine from starting a game: no conf, no menu program, a menu that
# dies or hangs (killed after its own timeout and a minute), a build that cannot be made,
# a choice that names nothing.
#
# PADSELECT_GAME moves ~/game (the tests); PADSELECT_PROCSW replaces dpprocsw (the
# tests: a script printing its lines); PADSELECT_MENU_ARGS adds menu options;
# PADSELECT_AUDIO_PLAYER replaces aplay; PADSELECT_DRY=1 prints what would be started
# instead of starting it.
SELF=$(readlink -f "$0" 2>/dev/null || echo "$0")
V_DIR=$(dirname "$SELF")
V=$(basename "$V_DIR")
G=${PADSELECT_GAME:-$(dirname "$V_DIR")}
P=$V_DIR/pad
CONF=$P/images.conf
BUILDS=$P/builds.txt
CHOICE=$P/choice
LOG=$P/padselect.log

[ -f "$LOG" ] && mv -f "$LOG" "$LOG.1" 2>/dev/null
{ exec 3>>"$LOG"; } 2>/dev/null || exec 3>/dev/null
say() { echo "$(date '+%F %T') $*" >&3; }
say "start $V ($*)"

is_version() { case "$1" in ""|*[!0-9.]*) return 1 ;; *[0-9]*) return 0 ;; *) return 1 ;; esac; }

# the builds' folders (never "stock")
build_folders=()
if [ -f "$BUILDS" ]; then
    while read -r folder bases files rest; do
        case "$folder" in ""|\#*) continue ;; esac
        build_folders+=("$folder")
    done < "$BUILDS"
fi
is_build() { local b; for b in "${build_folders[@]}"; do [ "$b" = "$1" ] && return 0; done; return 1; }

# the stock version: the newest digits-and-dots folder with a program, not ours
stock=""
for d in $(cd "$G" && ls -1d */ 2>/dev/null | tr -d / | sort -V); do
    is_version "$d" || continue
    [ "$d" = "$V" ] && continue
    is_build "$d" && continue
    [ -f "$G/$d/start" ] && stock=$d
done
say "stock version: ${stock:-none}"

boot() {        # boot <folder>: never returns when it starts something
    local f=$1
    shift
    if [ -n "${PADSELECT_DRY:-}" ]; then echo "would start $f $*"; say "dry run: $f"; exit 0; fi
    say "starting $f"
    exec 3>&-
    cd "$G/$f" && chmod +x start 2>/dev/null; exec ./start "$@"
}
fallback() {    # the machine's own choice, whatever happened
    say "falling back: $*"
    [ -n "$stock" ] && boot "$stock" "${ARGS[@]}"
    say "no stock version to start either"
    exit 1
}
ARGS=("$@")

[ -f "$CONF" ] || fallback "no $CONF"

# ---- 1. the builds ---------------------------------------------------------
make_build() {  # make_build <folder> <bases> <files>
    local folder=$1 bases=$2 files=$3 base="" b part=$G/$1.partial stamp
    stamp="$bases $files $(stat -c %Y "$P/$files" 2>/dev/null)"
    if [ -f "$G/$folder/start" ] && [ "$(cat "$G/$folder/.pad_build" 2>/dev/null)" = "$stamp" ]; then
        return 0
    fi
    [ -d "$P/$files" ] || { say "build $folder: no $P/$files"; return 1; }
    if [ "$bases" != "-" ]; then
        for b in $(echo "$bases" | tr ',' '\n' | sort -V); do
            is_version "$b" && [ -f "$G/$b/start" ] && ! is_build "$b" && base=$b
        done
        [ -n "$base" ] || { say "build $folder: none of its bases ($bases) is on this machine"; return 1; }
    fi
    say "build $folder: making it from ${base:-its own files} + $files"
    rm -rf "$part"
    if [ -n "$base" ]; then
        cp -al "$G/$base" "$part" || { rm -rf "$part"; say "build $folder: cannot copy $base"; return 1; }
        # the game writes its database: never through a link into the base's
        rm -rf "$part/database"
        if [ -d "$G/$base/database" ]; then
            cp -a "$G/$base/database" "$part/database" || { rm -rf "$part"; return 1; }
        fi
    else
        mkdir -p "$part"
    fi
    # the build's files over it: links into pad/, each name removed first (a copy onto
    # a hard link would write through it into the base's file)
    cp -al --remove-destination "$P/$files/." "$part/" \
        || { rm -rf "$part"; say "build $folder: cannot lay its files"; return 1; }
    if [ -d "$P/$files/database" ]; then          # its own database files: real copies
        rm -rf "$part/database.tmp"
        cp -a "$part/database" "$part/database.tmp" && rm -rf "$part/database" \
            && mv "$part/database.tmp" "$part/database"
    fi
    [ -f "$part/start" ] || { rm -rf "$part"; say "build $folder: no start program in it"; return 1; }
    rm -rf "$G/$folder" && mv "$part" "$G/$folder" || { rm -rf "$part"; return 1; }
    echo "$stamp" > "$G/$folder/.pad_build"
    sync
    say "build $folder: made"
}
if [ -f "$BUILDS" ]; then
    while read -r folder bases files rest; do
        case "$folder" in ""|\#*) continue ;; esac
        case "$folder" in */*|.*|"$V") say "build line '$folder': not a folder name"; continue ;; esac
        make_build "$folder" "$bases" "$files" || say "build $folder: left out"
    done < "$BUILDS"
fi

# ---- the menu's cards: what each boots ------------------------------------
targets=()
while IFS= read -r line; do
    case "$line" in image=*) f=${line#image=}; targets+=("${f%%|*}") ;; esac
done < "$CONF"
resolve() {     # resolve <target>: the folder it boots, "" if none
    local t=$1
    [ "$t" = stock ] && t=$stock
    case "$t" in ""|*/*|.*|"$V") return 0 ;; esac
    [ -f "$G/$t/start" ] && echo "$t"
}
n=${#targets[@]}
[ "$n" -ge 1 ] || fallback "no image= lines"

# ---- 2. the menu -------------------------------------------------------------
timeout_s=$(sed -n 's/^timeout=\([0-9][0-9]*\).*/\1/p' "$CONF" | tail -1)
[ -n "$timeout_s" ] || timeout_s=10
[ "$timeout_s" -gt 0 ] 2>/dev/null || timeout_s=600

# the buttons, as the stock version's machine.yaml names them (its PRSwitches section)
switch_of() {   # switch_of <name> <default>
    local y=$G/$stock/config/machine.yaml v=""
    [ -f "$y" ] && v=$(awk -v want="$1" '
        /^[A-Za-z]/ { sec = $1 }
        sec == "PRSwitches:" && $1 == want ":" { inside = 1; next }
        inside && /^    [A-Za-z]/ { inside = 0 }
        inside && $1 == "number:" { gsub(/["\047\r]/, "", $2); print $2; exit }' "$y")
    echo "${v:-$2}"
}

# SOUND: as the Barrels of Fun hook - the static menu streams its mix into a pipe and
# the machine's own aplay plays it, started only when the conf names a sound, and
# stopped and WAITED FOR before the game opens the sound card
has_sound() {
    grep -qE '^sound_(move|confirm)=[^[:space:]]' "$CONF" && return 0
    awk -F'|' '/^(image|group)=/ { for (i = 6; i <= 7; i++) if ($i != "" && $i != "none") f = 1 }
               END { exit !f }' "$CONF"
}
AUDIO=none; FIFO=""; player=""
start_player() {
    local play=${PADSELECT_AUDIO_PLAYER:-aplay}
    command -v "${play%% *}" >/dev/null 2>&1 || { say "sound: no ${play%% *}: the menu is silent"; return 0; }
    FIFO=$(mktemp -u /tmp/padselect.audio.XXXXXX) || return 0
    mkfifo -m 600 "$FIFO" 2>/dev/null || { say "sound: no pipe: the menu is silent"; FIFO=""; return 0; }
    timeout -k 2 $((timeout_s + 70)) $play -q -t raw -f S16_LE -r 44100 -c 2 -B 80000 -F 20000 \
        "$FIFO" </dev/null >/dev/null 2>>"$P/audio.log" &
    player=$!
    AUDIO="fifo:$FIFO"
    say "sound: $(basename "${play%% *}"), pid $player"
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
elif [ ! -x "$P/dpselect" ]; then
    say "no menu program at $P/dpselect"
else
    rm -f "$CHOICE"
    BTN=$(mktemp -u /tmp/padselect.buttons.XXXXXX)
    procsw=""
    if mkfifo -m 600 "$BTN" 2>/dev/null; then
        L=$(switch_of flipperLwL SD67); R=$(switch_of flipperLwR SD65); S=$(switch_of startButton SD68)
        if [ -n "${PADSELECT_PROCSW:-}" ]; then
            $PADSELECT_PROCSW L="$L" R="$R" S="$S" >"$BTN" 2>>"$P/dpprocsw.log" &
            procsw=$!
        elif [ -n "$stock" ] && [ -f "$G/$stock/libpinproc.so.2.0" ]; then
            # the board through the stock version's own libpinproc / libftdi1 / libusb
            # (PADSELECT_PROCSW_PRELOAD: the rig's fake P3-ROC, for the reader alone)
            env ${PADSELECT_PROCSW_PRELOAD:+LD_PRELOAD="$PADSELECT_PROCSW_PRELOAD"} LD_LIBRARY_PATH="$G/$stock" \
                "$P/dpprocsw" L="$L" R="$R" S="$S" >"$BTN" 2>>"$P/dpprocsw.log" &
            procsw=$!
        else
            say "no libpinproc.so.2.0 in '${stock}': no buttons, the countdown boots"
            ( exec >"$BTN" ) &
        fi
        say "buttons: L=$L R=$R S=$S${procsw:+, reader pid $procsw}"
    else
        say "cannot make the button pipe: no buttons"; BTN=/dev/null
    fi
    if has_sound; then start_player; fi
    say "menu: $n images, timeout ${timeout_s}s"
    timeout -k 5 $((timeout_s + 60)) "$P/dpselect" --input pipe --conf "$CONF" --out "$CHOICE" \
        --last "$P/last" --log "$P/dpselect.log" --audio "$AUDIO" --font "$P/font.ttf" \
        --media "$P/media" --no-invert ${PADSELECT_MENU_ARGS:-} <"$BTN" >/dev/null 2>&1
    rc=$?
    # the board is the game's next: the reader must be gone before it opens it
    if [ -n "$procsw" ]; then
        kill "$procsw" 2>/dev/null
        for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$procsw" 2>/dev/null || break; sleep 0.1; done
        kill -9 "$procsw" 2>/dev/null; wait "$procsw" 2>/dev/null
    fi
    [ "$BTN" != /dev/null ] && rm -f "$BTN"
    stop_player
    choice=$(head -c 16 "$CHOICE" 2>/dev/null | tr -dc '0-9')
    say "menu exit $rc, choice '$choice'"
fi
case "$choice" in ''|*[!0-9]*) choice=0 ;; esac
[ "$choice" -lt "$n" ] || choice=0
target=$(resolve "${targets[$choice]}")
[ -n "$target" ] || fallback "image $choice (${targets[$choice]}) is not on this machine"

# ---- 3. the settings database follows the player ----------------------------
# From the build that ran last; the first time, from this version's own database/, where
# Version Select put the database of the version the owner was running when they picked
# the multi-boot.  Version Select back into <V> later puts the running one there again:
# whichever of the two is newer is the one the player last played on.
ran=$(cat "$P/ran" 2>/dev/null)
src=""; from=""
if [ -n "$ran" ] && [ -f "$G/$ran/database/database.db" ]; then src=$G/$ran/database/database.db; from=$ran; fi
if [ -f "$V_DIR/database/database.db" ] && { [ -z "$src" ] || [ "$V_DIR/database/database.db" -nt "$src" ]; }; then
    src=$V_DIR/database/database.db; from="$V (Version Select)"
fi
if [ -n "$src" ] && [ "$src" != "$G/$target/database/database.db" ]; then
    mkdir -p "$G/$target/database"
    if cp -f "$src" "$G/$target/database/database.db.pad" \
        && mv -f "$G/$target/database/database.db.pad" "$G/$target/database/database.db"; then
        say "database: carried from $from to $target"
        # once carried, <V>'s copy is older than the build's from now on
        [ "$src" = "$V_DIR/database/database.db" ] && touch -r "$G/$target/database/database.db" -d '-1 sec' "$src" 2>/dev/null
    else
        say "database: could not carry it from $from to $target"
    fi
fi
echo "$target" > "$P/ran"
sync

# ---- 4. the game ---------------------------------------------------------------
boot "$target" "${ARGS[@]}"
