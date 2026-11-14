#!/bin/bash
# padselect_s3_test.sh - the Spike 3 hook (padselect_s3.sh, PAD-1263) with
# stand-ins for the menu, mount and pkill: which tree it binds for each
# choice, that it becomes that tree's game (argv and exit code passed on), and
# that every failure boots img0.
#
# The stand-in mount cannot bind anything, so the hook's GAMES is a directory
# whose `game` is a link to $T/bound, and "binding" SRC re-points $T/bound at
# SRC/game: the hook's `exec $GAMES/game` then runs the bound tree's game.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fails=0

mkdir -p "$T/games/pad" "$T/gamesdir"
for i in 0 1; do
    mkdir -p "$T/games/pad/img$i/t$i"
    cat > "$T/games/pad/img$i/t$i/game" <<EOF
#!/bin/sh
echo "GAME img$i \$*"
exit 7
EOF
    chmod +x "$T/games/pad/img$i/t$i/game"
    ln -s "t$i/game" "$T/games/pad/img$i/game"
done
ln -s "$T/bound" "$T/gamesdir/game"
conf_ok() { printf 'image=img0|A|a\nimage=img1|B|b\ndefault=0\ntimeout=0\n' > "$T/games/pad/images.conf"; }
conf_ok

# the menu: writes $CHOICE (when set) to --out, exits $MENU_RC
cat > "$T/sel" <<'EOF'
#!/bin/sh
while [ $# -gt 0 ]; do [ "$1" = --out ] && o=$2; shift; done
[ -n "$CHOICE" ] && echo "$CHOICE" > "$o"
exit ${MENU_RC:-0}
EOF
# mount: the last two arguments are SRC DST (--bind and -o bind alike)
cat > "$T/mount" <<EOF
#!/bin/sh
for a; do s=\$d; d=\$a; done
if [ -n "\$MOUNT_FAIL" ]; then case "\$s" in *"\$MOUNT_FAIL"*) exit 1 ;; esac; fi
echo "\$s" >> "$T/mounts"
rm -f "$T/bound"; ln -s "\$s/game" "$T/bound"
EOF
chmod +x "$T/sel" "$T/mount"

run() {  # run WANT LABEL [VAR=value ...]
    local want=$1 label=$2; shift 2
    rm -f "$T/mounts" "$T/out" "$T/bound"
    out=$(env CHOICE= MOUNT_FAIL= PADSELECT_DIR="$T/games/pad" PADSELECT_GAMES="$T/gamesdir" \
        PADSELECT_BIN="$T/sel" PADSELECT_OUT="$T/out" PADSELECT_MOUNTCMD="$T/mount" \
        PADSELECT_PKILL=true PADSELECT_LOG= "$@" sh "$HERE/padselect_s3.sh" ARG 2>/dev/null)
    rc=$?
    if [ "$out" = "$want" ] && [ "$rc" = 7 ]; then
        echo "ok   $label"
    else
        echo "FAIL $label: rc=$rc out=[$out] want=[$want] mounts=[$(tr '\n' ' ' < "$T/mounts" 2>/dev/null)]"
        fails=$((fails + 1))
    fi
}

run "GAME img1 ARG" "choice 1 binds img1 and becomes its game" CHOICE=1
run "GAME img0 ARG" "choice 0 binds img0" CHOICE=0
run "GAME img0 ARG" "no choice boots img0" CHOICE=
run "GAME img0 ARG" "a choice past the list boots img0" CHOICE=5
run "GAME img0 ARG" "the bind of img1 refused boots img0" CHOICE=1 MOUNT_FAIL=img1
run "GAME img0 ARG" "no bind at all runs img0's game directly" CHOICE=1 MOUNT_FAIL=img
run "GAME img0 ARG" "no menu program boots img0" CHOICE=1 PADSELECT_BIN="$T/none"
run "GAME img1 ARG" "a menu that exits non-zero but chose is obeyed" CHOICE=1 MENU_RC=3
mv "$T/games/pad/images.conf" "$T/ic"
run "GAME img0 ARG" "no images.conf boots img0" CHOICE=1
printf 'image=../x|A|a\nimage=img1|B|b\n' > "$T/games/pad/images.conf"
run "GAME img0 ARG" "a directory name with a slash is refused" CHOICE=0
conf_ok
rm "$T/games/pad/img1/game"
run "GAME img0 ARG" "an image directory without a game boots img0" CHOICE=1
if [ "$fails" = 0 ]; then echo "padselect_s3_test: OK"; else echo "padselect_s3_test: $fails failed"; exit 1; fi
