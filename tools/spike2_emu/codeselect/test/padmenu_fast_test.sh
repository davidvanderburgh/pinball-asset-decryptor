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
run() {   # run NAME FILE CONTENT CHUNK WANT [ENV]
    local name=$1 file=$2 content=$3 chunk=$4 want=$5 envarg=${6:-CODESELECT_REBOOT=touch /x}
    rm -f "$T/calls"
    printf -- "$content" > "$file"
    env LD_PRELOAD="$SO" PADMENU_HOLD_MS=400 PADMENU_CMD="$T/reboot.sh" "$envarg" \
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
[ $fail -eq 0 ] && echo "padmenu_fast_test: OK"
exit $fail
