#!/bin/bash
# padmenu_fast_test.sh PADMENU_SO - the Barrels of Fun build of padmenu.so (PAD-1309), natively.
#
# The FAST Neuron's switch lines ("-L:05" active, "/L:05" inactive, '\r' ended) are put in a
# FILE whose path ends in /dev/ttyACM0, which a small driver reads CHUNK bytes at a time - as the
# game reads its NET port - and then waits WAIT_MS reading nothing (the board sends nothing while
# a button stays held, so the 5 s are timed by padmenu.so's own thread).
#
#   held        -L:05                  -> one restart
#   split       -L:05, 2 bytes a read  -> one restart (a line across reads)
#   released    -L:05 /L:05            -> none
#   other       -L:04                  -> none (only EXIT, switch 5)
#   notserial   -L:05 in a plain file  -> none (only a USB serial port's lines)
#   rig         held, BOFHW_DEV set, no CODESELECT_REBOOT -> none (never a real reboot in the rig)
set -e
SO=$1
[ -f "$SO" ] || { echo "padmenu_fast_test: no $SO"; exit 1; }
T=$(mktemp -d /tmp/padmenu_fast.XXXXXX)
trap 'rm -rf "$T"' EXIT
cat > "$T/driver.c" <<'EOF'
#include <fcntl.h>
#include <stdlib.h>
#include <unistd.h>
int main(int argc, char **argv)
{
    char b[64];
    int fd = open(argv[1], O_RDONLY), chunk = atoi(argv[2]);
    if (fd < 0) return 2;
    while (read(fd, b, chunk) > 0) ;
    usleep(atoi(argv[3]) * 1000);
    return 0;
}
EOF
gcc -O2 -o "$T/driver" "$T/driver.c"
mkdir -p "$T/dev" "$T/data"
cat > "$T/reboot.sh" <<EOF
#!/bin/sh
echo "\$* rb=\$CODESELECT_REBOOT" >> "$T/calls"
EOF
chmod +x "$T/reboot.sh"
fail=0
run() {   # run NAME FILE CONTENT CHUNK WANT [ENV...]
    local name=$1 file=$2 content=$3 chunk=$4 want=$5
    shift 5
    [ $# -gt 0 ] || set -- "CODESELECT_REBOOT=touch /x"
    rm -f "$T/calls"
    printf -- "$content" > "$file"
    env LD_PRELOAD="$SO" PADMENU_HOLD_MS=400 PADMENU_CMD="$T/reboot.sh" "$@" \
        "$T/driver" "$file" "$chunk" 1200 2> "$T/err" || { echo "padmenu_fast_test: FAIL $name: driver"; fail=1; return; }
    sleep 0.3
    got=$( [ -f "$T/calls" ] && wc -l < "$T/calls" || echo 0)
    if [ "$got" -ne "$want" ]; then
        echo "padmenu_fast_test: FAIL $name: $got restart(s), wanted $want"; cat "$T/err"; fail=1; return
    fi
    if [ "$want" = 1 ] && [ "$(cat "$T/calls")" != "--reboot rb=touch /x" ]; then
        echo "padmenu_fast_test: FAIL $name: called as '$(cat "$T/calls")'"; fail=1; return
    fi
    echo "padmenu_fast_test: ok $name ($got restart)"
}
run held      "$T/dev/ttyACM0" 'ID:NET FP-CPU-2000 01.05\r-L:05\r' 64 1
run split     "$T/dev/ttyACM0" 'SA:0E,00\r-L:05\r' 2 1
run released  "$T/dev/ttyACM0" '-L:05\r/L:05\r' 64 0
run other     "$T/dev/ttyACM0" '-L:04\r' 64 0
run notserial "$T/data/x" '-L:05\r' 64 0
run rig       "$T/dev/ttyACM0" '-L:05\r' 64 0 BOFHW_DEV=/tmp/hw
grep -q "not restarting" "$T/err" || { echo "padmenu_fast_test: FAIL rig: nothing said"; fail=1; }

# HOW LONG: the card's back_hold= (seconds; 0 = off) when nothing is handed in
conf_run() {   # conf_run NAME BACK_HOLD_LINE WANT [ENV...]
    local name=$1 line=$2 want=$3; shift 3
    rm -f "$T/calls"
    printf '%s\n' "image=a|A" "$line" > "$T/images.conf"
    printf -- '-L:05\r' > "$T/dev/ttyACM0"
    env LD_PRELOAD="$SO" PADMENU_CONF="$T/images.conf" PADMENU_CMD="$T/reboot.sh" \
        CODESELECT_REBOOT="touch /x" "$@" "$T/driver" "$T/dev/ttyACM0" 64 1800 2> "$T/err"
    sleep 0.3
    got=$( [ -f "$T/calls" ] && wc -l < "$T/calls" || echo 0)
    if [ "$got" -ne "$want" ]; then echo "padmenu_fast_test: FAIL $name: $got restart(s), wanted $want"; fail=1
    else echo "padmenu_fast_test: ok $name ($got restart)"; fi
}
conf_run conf-1s  "back_hold=1" 1
conf_run conf-off "back_hold=0" 0
conf_run conf-3s  "back_hold = 3" 0
conf_run env-wins "back_hold=0" 1 PADMENU_HOLD_MS=400

# SPOOKY: the Warden (BACK 94 = 0x5e) and the Pinotaur (BACK 63 = 0x3f), binary, a message at a time
W=(CODESELECT_REBOOT="touch /x" PADMENU_PROTO=warden PADMENU_SWITCH=94)
P=(CODESELECT_REBOOT="touch /x" PADMENU_PROTO=pinotaur PADMENU_SWITCH=63)
run w-push      "$T/dev/WARDEN" '\x3c\x97WARDEN\x00\x3c\x01\x5e' 3 1 "${W[@]}"
run w-reply     "$T/dev/WARDEN" '\x3c\xd4\x03\x3c\x98\x5e\x01' 64 1 "${W[@]}"
run w-released  "$T/dev/WARDEN" '\x3c\x01\x5e\x3c\x00\x5e' 64 0 "${W[@]}"
run w-in-config "$T/dev/WARDEN" '\x3c\xa8\x3c\x01\x5e\x00\x00' 64 0 "${W[@]}"
run w-other     "$T/dev/WARDEN" '\x3c\x01\x5d' 64 0 "${W[@]}"
run p-push      "$T/dev/pinheck" '\x3e\x00Pinotaur\x00\x3e\x59\xbf' 64 1 "${P[@]}"
run p-reply     "$T/dev/pinheck" '\x3e\x58\x3f\x01' 1 1 "${P[@]}"
run p-in-row    "$T/dev/pinheck" '\x3e\x28\x3e\x59\xbf\x3e\x59\xbf\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00' 64 0 "${P[@]}"
run p-nochange  "$T/dev/pinheck" '\x3e\x59\x7f' 64 0 "${P[@]}"
[ $fail -eq 0 ] && echo "padmenu_fast_test: OK"
exit $fail
