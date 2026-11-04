#!/bin/bash
# padselect.sh - the Spooky Pinball P-ROC multi-boot launcher: Rick and Morty, Alice Cooper's
# Nightmare Castle (PAD-980, tools/spooky_emu/MULTIBOOT.md, "P-ROC titles").
#
# Both games run only AT their own folder - Rick and Morty /game/RickAndMorty (a font path is
# baked into its bytecode), Alice Cooper /game/code (its Unity screen and its Python game
# both name it) - so a build cannot run from a folder of its own: it is MOVED there.  The
# multi-boot update installs the stock build into that folder the machine's own way, and
# everything of ours in <folder>/.pad, which both updaters' `rm -rf <folder>/*` leave alone.
# The machine's start script runs THIS where it ran the game (installed by the update's hook:
# Rick and Morty's run-on-update.sh as ~/.local/rmstart.sh, Alice Cooper's xinitrc).  At every
# power-up it:
#
#   1. checks the folder is still ours: PAD_MULTIBOOT_LIVE in it says which build it holds
#      ("b<k> <stamp>"; the update ships it as b0's).  A normal update installed since
#      emptied the folder (rm -rf <folder>/*, which takes the marker and leaves .pad):
#      then it starts that, exactly as the machine would.  A new stamp is a new multi-boot:
#      the last one's builds go.  A swap a power cut interrupted is finished first;
#   2. makes every build not made yet: a hard-linked copy of b0 (the stock build, kept in
#      .pad/b0 while another build is live) with the build's own files laid over, its
#      settings files real copies;
#   3. shows the boot menu (spkselect on the X server, the flippers and START through
#      dpprocsw on the machine's own libpinproc);
#   4. when the choice is not the build in the folder: carries the settings files (the
#      game's audits, settings and scores) from the live build to the chosen one, moves the
#      live build's entries into .pad/<it> and the chosen one's into the folder (renames,
#      the same file system), recording each step in .pad/live;
#   5. starts the game: the conf's start= line, in the folder.
#
#   .pad/proc.conf   game=<folder>, start=<command>, lib=<libpinproc's folder>, L= R= S=
#                    (the machine yaml's SD numbers), keep=<a settings file, relative> lines
#   .pad/images.conf the menu; image=b<k>|<title>|<subtitle>...
#   .pad/builds.txt  "b<k> d<k>" per build after the first (d<k>.removed: what it lacks)
#
# EVERY FAILURE ENDS ON WHATEVER IS IN THE FOLDER, which is a whole build at every step a
# power cut can interrupt (or the stock one).  Nothing here may keep the machine from
# starting a game: no conf, no menu program, a menu that dies or hangs, a build that cannot
# be made, a choice that names nothing.
#
# PADSELECT_GAME moves the folder (the tests); PADSELECT_START replaces the start= line (the
# rig: ":" hands back to its own start); PADSELECT_PROCSW replaces dpprocsw;
# PADSELECT_PROCSW_PRELOAD preloads the rig's fake board under the reader only;
# PADSELECT_MENU_ARGS adds menu options; PADSELECT_AUDIO_PLAYER replaces the player;
# PADSELECT_DRY=1 prints what would be started instead of starting it.
SELF=$(readlink -f "$0" 2>/dev/null || echo "$0")
HOME_P=$(dirname "$SELF")                     # the launcher lives in <folder>/.pad
CONFF=$HOME_P/proc.conf
conf() {        # conf <key> <default>: the last <key>= line of proc.conf
    local v=""
    [ -f "$CONFF" ] && v=$(sed -n "s/^$1=//p" "$CONFF" | tail -1 | tr -d '\r')
    echo "${v:-$2}"
}
G=${PADSELECT_GAME:-$(conf game "$(dirname "$HOME_P")")}
P=$G/.pad
CONF=$P/images.conf
BUILDS=$P/builds.txt
CHOICE=$P/choice
LOG=$P/padselect.log
START=${PADSELECT_START:-$(conf start "")}

[ -f "$LOG" ] && mv -f "$LOG" "$LOG.1" 2>/dev/null
{ exec 3>>"$LOG"; } 2>/dev/null || exec 3>/dev/null
say() { echo "$(date '+%F %T') $*" >&3; }
say "start in $G ($*)"
ARGS=("$@")

play() {        # start the game in the folder: never returns when it starts
    if [ -n "${PADSELECT_DRY:-}" ]; then echo "would start '$START' in $G"; say "dry run"; exit 0; fi
    say "starting: $START"
    exec 3>&-
    cd "$G" || exit 1
    exec bash -c "$START"
}
[ -n "$START" ] || { say "no start= in $CONFF"; exit 1; }

# ---- 1. still ours? ----------------------------------------------------------
MARK=$G/PAD_MULTIBOOT_LIVE
read -r live stamp < "$MARK" 2>/dev/null
case "$live" in b[0-9]|b[1-9][0-9]) ;; *) live="" ;; esac
if [ -z "$live" ]; then
    say "no $MARK: a normal update is installed - starting it"
    play
fi
if [ "$stamp" != "$(cat "$P/stamp" 2>/dev/null)" ]; then
    # a multi-boot installed over another: the folder is the new one's b0 and the old
    # builds are not this update's
    say "a new multi-boot ($stamp): the folder is b0"
    rm -rf "$P"/b[0-9] "$P"/b[1-9][0-9] "$P"/b*.made "$P"/b*.partial "$P"/b*.out "$P/swap" "$P/last"
    echo "$stamp" > "$P/stamp"
    live=b0
    echo "b0 $stamp" > "$MARK"
    sync
fi
# A SWAP A POWER CUT INTERRUPTED.  .pad/swap says "out <from> <to>" while the live build's
# entries move out, "in <from> <to>" while the chosen one's move in; the marker is written
# when it is over.  Out: put back what went out.  In: finish bringing the rest in.
if read -r phase from to < "$P/swap" 2>/dev/null; then
    say "a swap was interrupted ($phase $from -> $to): finishing it"
    if [ "$phase" = out ]; then
        for e in "$P/$from.out"/* "$P/$from.out"/.[!.]*; do
            [ -e "$e" ] || [ -L "$e" ] || continue
            mv "$e" "$G/" 2>/dev/null
        done
        rmdir "$P/$from.out" 2>/dev/null
        live=$from
    else
        for e in "$P/$to"/* "$P/$to"/.[!.]*; do
            [ -e "$e" ] || [ -L "$e" ] || continue
            mv "$e" "$G/" 2>/dev/null
        done
        rmdir "$P/$to" 2>/dev/null
        live=$to
    fi
    echo "$live $stamp" > "$MARK"
    rm -f "$P/swap"
    sync
fi
[ -f "$CONF" ] || { say "no $CONF"; play; }

# ---- 2. the builds -------------------------------------------------------------
# a build is made from b0, and b0 is in the folder while it is live, in .pad/b0 otherwise
b0dir() { if [ "$live" = b0 ]; then echo "$G"; else echo "$P/b0"; fi; }
keeps() { [ -f "$CONFF" ] && sed -n 's/^keep=//p' "$CONFF" | tr -d '\r'; }
make_build() {  # make_build b<k> <files>
    local b=$1 files=$2 part=$P/$1.partial src rel k
    [ -f "$P/$b.made" ] && { [ -d "$P/$b" ] || [ "$live" = "$b" ]; } && return 0
    [ -d "$P/$files" ] || { say "build $b: no $P/$files"; return 1; }
    src=$(b0dir)
    say "build $b: making it from b0 + $files"
    rm -rf "$part"
    mkdir -p "$part" || return 1
    for e in "$src"/* "$src"/.[!.]*; do
        [ -e "$e" ] || [ -L "$e" ] || continue
        case "${e##*/}" in .pad|PAD_MULTIBOOT_LIVE) continue ;; esac
        cp -al "$e" "$part/" || { rm -rf "$part"; say "build $b: cannot copy b0"; return 1; }
    done
    cp -al --remove-destination "$P/$files/." "$part/" \
        || { rm -rf "$part"; say "build $b: cannot lay its files"; return 1; }
    if [ -f "$P/$files.removed" ]; then
        while IFS= read -r rel; do
            case "$rel" in ""|/*|*..*) continue ;; esac
            rm -rf "$part/$rel"
        done < "$P/$files.removed"
    fi
    # the game WRITES its settings files: never through a link into b0's
    while IFS= read -r k; do
        [ -n "$k" ] && [ -f "$part/$k" ] || continue
        cp -f "$part/$k" "$part/$k.pad" && mv -f "$part/$k.pad" "$part/$k"
    done < <(keeps)
    rm -rf "$P/$b" && mv -T "$part" "$P/$b" && touch "$P/$b.made" || { rm -rf "$part"; return 1; }
    sync
    say "build $b: made"
}
if [ -f "$BUILDS" ]; then
    while read -r b files rest; do
        case "$b" in ""|\#*) continue ;; esac
        case "$b" in b[1-9]|b[1-9][0-9]) ;; *) continue ;; esac
        [ "$live" = "$b" ] && continue
        make_build "$b" "$files" || say "build $b: left out"
    done < <(tr -d '\r' < "$BUILDS")
fi
touch "$P/b0.made"

# ---- 3. the menu ---------------------------------------------------------------------
targets=()
while IFS= read -r line; do
    case "$line" in image=*) f=${line#image=}; targets+=("${f%%|*}") ;; esac
done < <(tr -d '\r' < "$CONF")
n=${#targets[@]}
has() { [ "$1" = "$live" ] || { [ -f "$P/$1.made" ] && [ -d "$P/$1" ]; }; }
timeout_s=$(sed -n 's/^timeout=\([0-9][0-9]*\).*/\1/p' "$CONF" | tail -1)
[ -n "$timeout_s" ] || timeout_s=10
[ "$timeout_s" -gt 0 ] 2>/dev/null || timeout_s=600
choice=""
if [ "$n" -lt 2 ]; then
    choice=0
elif [ ! -x "$P/spkselect" ]; then
    say "no menu program at $P/spkselect"
else
    rm -f "$CHOICE"
    BTN=$(mktemp -u /tmp/padselect.buttons.XXXXXX)
    procsw=""
    L=$(conf L SD14); R=$(conf R SD8); S=$(conf S SD15); lib=$(conf lib /usr/local/lib)
    if mkfifo -m 600 "$BTN" 2>/dev/null; then
        if [ -n "${PADSELECT_PROCSW:-}" ]; then
            $PADSELECT_PROCSW L="$L" R="$R" S="$S" >"$BTN" 2>>"$P/dpprocsw.log" &
        else
            env ${PADSELECT_PROCSW_PRELOAD:+LD_PRELOAD="$PADSELECT_PROCSW_PRELOAD"} \
                LD_LIBRARY_PATH="$lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
                "$P/dpprocsw" L="$L" R="$R" S="$S" >"$BTN" 2>>"$P/dpprocsw.log" &
        fi
        procsw=$!
        say "buttons: L=$L R=$R S=$S through $lib, reader pid $procsw"
    else
        BTN=/dev/null
    fi
    say "menu: $n images, timeout ${timeout_s}s"
    timeout -k 5 $((timeout_s + 60)) "$P/spkselect" --input pipe --conf "$CONF" --out "$CHOICE" \
        --last "$P/last" --log "$P/spkselect.log" --audio none --font "$P/font.ttf" \
        --media "$P/media" --no-invert ${PADSELECT_MENU_ARGS:-} <"$BTN" >/dev/null 2>&1
    rc=$?
    # the board is the game's next: the reader must be gone before it opens it
    if [ -n "$procsw" ]; then
        kill "$procsw" 2>/dev/null
        for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$procsw" 2>/dev/null || break; sleep 0.1; done
        kill -9 "$procsw" 2>/dev/null; wait "$procsw" 2>/dev/null
    fi
    [ "$BTN" != /dev/null ] && rm -f "$BTN"
    choice=$(head -c 16 "$CHOICE" 2>/dev/null | tr -dc '0-9')
    say "menu exit $rc, choice '$choice'"
fi
case "$choice" in ''|*[!0-9]*) choice=0 ;; esac
[ "$choice" -lt "$n" ] || choice=0
want=${targets[$choice]}
case "$want" in b[0-9]|b[1-9][0-9]) ;; *) say "image $choice names '$want'"; play ;; esac
has "$want" || { say "image $choice ($want) is not made: $live stays"; play; }

# ---- 4. the swap -------------------------------------------------------------------
if [ "$want" != "$live" ]; then
    say "switching $live -> $want"
    # the settings follow the player: the live build's into the chosen one's
    while IFS= read -r k; do
        [ -n "$k" ] && [ -f "$G/$k" ] || continue
        mkdir -p "$(dirname "$P/$want/$k")"
        cp -f "$G/$k" "$P/$want/$k.pad" && mv -f "$P/$want/$k.pad" "$P/$want/$k" \
            && say "settings: $k carried"
    done < <(keeps)
    # the live build out: every entry but ours, into .pad/<live>.out (one rename each)
    echo "out $live $want" > "$P/swap"; sync
    mkdir -p "$P/$live.out" || play
    for e in "$G"/* "$G"/.[!.]*; do
        [ -e "$e" ] || [ -L "$e" ] || continue
        case "${e##*/}" in .pad|PAD_MULTIBOOT_LIVE) continue ;; esac
        mv "$e" "$P/$live.out/" || say "cannot move ${e##*/} out"
    done
    rm -rf "$P/$live"; mv -T "$P/$live.out" "$P/$live"
    # the chosen one in
    echo "in $live $want" > "$P/swap"; sync
    for e in "$P/$want"/* "$P/$want"/.[!.]*; do
        [ -e "$e" ] || [ -L "$e" ] || continue
        mv "$e" "$G/" || say "cannot move ${e##*/} in"
    done
    rmdir "$P/$want" 2>/dev/null
    echo "$want $stamp" > "$MARK"
    rm -f "$P/swap"
    live=$want
    sync
    say "live = $want"
fi

# ---- 5. the game -------------------------------------------------------------------
play
