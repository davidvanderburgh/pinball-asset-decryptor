#!/bin/bash
# padmenu_test.sh ROOT PADMENU_SO - padmenu.so (PAD-1309) under qemu-arm-static.
#
# A small ARM driver opens a file whose path holds /dev/spidev (hwshim.c's own
# test for one) and loops on the 8-byte cabinet SPI transfer the game makes.
# echospi.so stands in for the kernel: it copies the tx half into rx, so the
# driver says what the coin door reads (tx[1] bit 3 low = BACK held).
# padmenu.so sits in front of both, as the game_monitor hook puts it.
#
#   none    BACK never pressed               -> no restart
#   hold    BACK held for the whole run      -> exactly one `<cmd> --reboot`
#   pulse   BACK 300 ms down / 60 ms up      -> no restart (the hold must be unbroken)
#   i2c     BACK "held" on /dev/i2c-1        -> no restart (only a spidev counts)
#   rig-no-standin  held in an emulator with no CODESELECT_REBOOT -> no restart
set -e
ROOT=$1
SO=$2
QEMU=${QEMU:-qemu-arm-static}
CC=${CC:-arm-linux-gnueabihf-gcc}
[ -f "$SO" ] || { echo "padmenu_test: no $SO"; exit 1; }
T=$(mktemp -d /tmp/padmenu_test.XXXXXX)
trap 'rm -rf "$T"' EXIT
GCCINC=$($CC -print-file-name=include)
CF="-std=gnu17 -O2 -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -fno-stack-protector -nostdinc -isystem $GCCINC -isystem $ROOT/usr/include"

cat > "$T/echospi.c" <<'EOF'
#include <stdint.h>
#include <string.h>
#include <stdarg.h>
int ioctl(int fd, unsigned long req, ...)
{
    va_list ap; unsigned char *x;
    va_start(ap, req); x = va_arg(ap, unsigned char *); va_end(ap);
    if (((req >> 8) & 0xff) == 0x6b && x) {
        uint64_t tx, rx; uint32_t len;
        memcpy(&tx, x, 8); memcpy(&rx, x + 8, 8); memcpy(&len, x + 16, 4);
        memcpy((void *)(uintptr_t)rx, (void *)(uintptr_t)tx, len);
        return (int)len;
    }
    return 0;
}
EOF
cat > "$T/driver.c" <<'EOF'
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
int ioctl(int, unsigned long, ...);
static long long ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000LL + t.tv_nsec / 1000000; }
int main(int argc, char **argv)
{
    const char *mode = argv[1], *path = argv[2];
    int run_ms = atoi(argv[3]);
    unsigned char tx[8], rx[8], x[32];
    uint64_t p; uint32_t len = 8;
    long long t0 = ms(), t;
    int fd = open(path, O_RDWR);
    if (fd < 0) { perror(path); return 2; }
    while ((t = ms() - t0) < run_ms) {
        /* every mode but none and pulse holds BACK the whole run */
        int back = strcmp(mode, "none") && (strcmp(mode, "pulse") || (t % 360) < 300);
        memset(tx, 0xff, 8);
        if (back) tx[1] &= ~(1 << 3);
        memset(x, 0, 32);
        p = (uintptr_t)tx; memcpy(x, &p, 8);
        p = (uintptr_t)rx; memcpy(x + 8, &p, 8);
        memcpy(x + 16, &len, 4);
        ioctl(fd, 0x40206b00UL, x);            /* SPI_IOC_MESSAGE(1) */
        usleep(1000);
    }
    return 0;
}
EOF
sed -i 's/#include <unistd.h>/#include <unistd.h>\n#include <stdlib.h>/' "$T/driver.c"
$CC $CF -fPIC -shared -nostdlib -o "$T/echospi.so" "$T/echospi.c" -L"$ROOT/lib" -l:libc.so.6
$CC $CF -fno-pie -no-pie -nostdlib -nostartfiles "$ROOT/usr/lib/crt1.o" "$ROOT/usr/lib/crti.o" \
    "$T/driver.c" "$ROOT/usr/lib/crtn.o" -L"$ROOT/lib" -L"$ROOT/usr/lib" \
    -Wl,-rpath-link,"$ROOT/lib" -Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3 \
    -l:libc.so.6 "$ROOT/usr/lib/libc_nonshared.a" -lgcc -o "$T/driver"
mkdir -p "$T/dev"
: > "$T/dev/spidev1.0"
: > "$T/dev/i2c-1"
cat > "$T/reboot.sh" <<EOF
#!/bin/sh
echo "\$* rb=\$CODESELECT_REBOOT preload=\${LD_PRELOAD:-none}" >> "$T/calls"
EOF
chmod +x "$T/reboot.sh"

fail=0
run() {   # run NAME DEVICE WANT_CALLS [ENV-ARG]
    local envarg=${4:-CODESELECT_REBOOT=touch /dump/reboot.req}
    rm -f "$T/calls"
    "$QEMU" -L "$ROOT" -E LD_PRELOAD="$SO:$T/echospi.so" -E PADMENU_HOLD_MS=500 \
        -E PADMENU_CMD="$T/reboot.sh" -E "$envarg" \
        "$T/driver" "$1" "$T/dev/$2" 1500 2>"$T/err" || { echo "padmenu_test: $1: driver failed"; cat "$T/err"; fail=1; return; }
    sleep 0.3
    got=$( [ -f "$T/calls" ] && wc -l < "$T/calls" || echo 0)
    if [ "$got" -ne "$3" ]; then
        echo "padmenu_test: FAIL $1: $got restart(s), wanted $3"; cat "$T/err"; fail=1; return
    fi
    if [ "$3" -eq 1 ]; then
        line=$(cat "$T/calls")
        [ "$line" = "--reboot rb=touch /dump/reboot.req preload=none" ] \
            || { echo "padmenu_test: FAIL $1: called as '$line'"; fail=1; return; }
        grep -q "BACK held" "$T/err" || { echo "padmenu_test: FAIL $1: nothing said on stderr"; fail=1; return; }
    fi
    echo "padmenu_test: ok $1 ($got restart)"
}
run none spidev1.0 0
run hold spidev1.0 1
run pulse spidev1.0 0
run i2c i2c-1 0
# in an emulator (its shims' variables set) with no CODESELECT_REBOOT: never a real reboot
run rig-no-standin spidev1.0 0 PAD_AUDIO_OUT=/dump/audio.raw
grep -q "not restarting" "$T/err" || { echo "padmenu_test: FAIL rig-no-standin: nothing said"; cat "$T/err"; fail=1; }
[ $fail -eq 0 ] && echo "padmenu_test: OK"
exit $fail
