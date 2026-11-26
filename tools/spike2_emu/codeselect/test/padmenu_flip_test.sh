#!/bin/bash
# padmenu_flip_test.sh ROOT PADMENU_SO - the right flipper back to the boot menu (Simon, 2026-11-22), under
# qemu-arm-static.
#
# A small ARM driver plays the game's side of the node bus on a FILE whose path ends in /dev/ttymxc1: every 5 ms
# the node 8 switch scan (`88 03 11 <key> <ck> 0c`, write()), its 12-byte reply put in place with pwrite() (which
# padmenu.so does not look at) and read() back as the game reads it - bytes 0..7 XORed with rol8(key, c), right
# flipper byte 3 bit 0, left bit 1, active low.  The flipper rules go out as the game sends them: command 0x41,
# the input byte at 26 (0x58 the right flipper button, 0x59 the left), cleared by the short form `41 <coil>`.
#
#   attract   no rule ever, right flipper held          -> one restart
#   plain     the same, unkeyed scans (`88 02 11 ck 0c`) -> one restart
#   game      the flipper rules live, right held         -> none
#   left      no rule, LEFT flipper held                 -> none
#   other     only a rule that is not a flipper's live   -> one restart (Godzilla's node 9 coil 2 in attract)
#   tilt      rules live, cleared at once, right held, run shorter than the guard + hold -> none
#   tiltlate  the same, run past the guard + hold        -> one restart
#   tap       right flipper 300 ms down / 60 ms up       -> none (the hold must be unbroken)
#   sparse    the table's way: read once at the press, then other frames only -> one restart
#   sparseup  the same, and read again at the release 200 ms on               -> none
#   conf-off  no PADMENU_FLIP_MS, the card says boot_menu=menu         -> none
#   conf-on   no PADMENU_FLIP_MS, boot_menu=flipper flip_hold=1 flip_guard=0 -> one restart
# THE SERVICE MENU ROW (BOOT MENU FLIPPER, padmenu.cfg; Simon 2026-11-25) - it wins over images.conf:
#   row-off       its own row (the driver's row_word) reads 0 Off, the card says flipper  -> none
#   row-on        it reads 15, the card says boot_menu=menu                               -> one restart
#   row-bad       it reads 9999 (not a value the row holds): the cfg's default, 15        -> one restart
#   row-guard     it reads 15 and no test guard: 15 s with no game on, the run is shorter  -> none
#   row-low       it reads 3 (a shared row steps by one): taken as 15 s, the run is shorter -> none
#   row-unmapped  an address the process has not mapped: never read, the default         -> one restart
#   shared-off    a MORE SETTINGS word, pad_settings.state says "boot_flip 0"             -> none
#   shared-none   the same, no state file yet: the default                                -> one restart
set -e
ROOT=$1
SO=$2
QEMU=${QEMU:-qemu-arm-static}
CC=${CC:-arm-linux-gnueabihf-gcc}
[ -f "$SO" ] || { echo "padmenu_flip_test: no $SO"; exit 1; }
T=$(mktemp -d /tmp/padmenu_flip.XXXXXX)
trap 'rm -rf "$T"' EXIT
GCCINC=$($CC -print-file-name=include)
CF="-std=gnu17 -O2 -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -fno-stack-protector -nostdinc -isystem $GCCINC -isystem $ROOT/usr/include"

cat > "$T/driver.c" <<'EOF'
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
volatile unsigned row_word;                /* the game's BOOT MENU FLIPPER value (padmenu.cfg names its address) */
static long long ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000LL + t.tv_nsec / 1000000; }
static unsigned char ck(const unsigned char *b, int n) { unsigned s = 0; int i; for (i = 0; i < n; i++) s += b[i]; return (unsigned char)(0x100 - (s & 0xff)); }
static void rule(int fd, int node, int coil, int input, int on)
{
    unsigned char f[31];
    if (on) {
        memset(f, 0, sizeof f);
        f[0] = 0x80 | node; f[1] = 28; f[2] = 0x41; f[3] = coil; f[4] = 0x60; f[26] = input;
        f[29] = ck(f, 29); f[30] = 0;
        write(fd, f, 31);
    } else {
        f[0] = 0x80 | node; f[1] = 3; f[2] = 0x41; f[3] = coil; f[4] = ck(f, 4); f[5] = 0;
        write(fd, f, 6);
    }
}
int main(int argc, char **argv)
{
    const char *mode = argv[1];
    int run_ms = atoi(argv[3]), fd = open(argv[2], O_RDWR), plain = !strcmp(mode, "plain");
    long long t0 = ms(), t;
    unsigned key = 0;
    if (fd < 0) return 2;
    if (argc > 4) row_word = (unsigned)atoi(argv[4]);
    if (!strcmp(mode, "game") || !strcmp(mode, "tilt") || !strcmp(mode, "tiltlate")) {
        rule(fd, 8, 0, 0x58, 1);
        rule(fd, 8, 5, 0x59, 1);
    }
    if (!strcmp(mode, "tilt") || !strcmp(mode, "tiltlate")) {
        rule(fd, 8, 0, 0, 0);
        rule(fd, 8, 5, 0, 0);
    }
    if (!strcmp(mode, "other"))
        rule(fd, 9, 2, 0x00, 1);
    while ((t = ms() - t0) < run_ms) {
        unsigned char f[6], r[12];
        int c, n;
        /* THE TABLE'S PATTERN (2026-11-25): node 8 read only when a switch changes - once at the
         * press (sparse; sparseup also once at the release, 200 ms on) - and other frames between */
        if (!strncmp(mode, "sparse", 6)) {
            static int said, upsaid;
            int up = !strcmp(mode, "sparseup") && t >= 200;
            if ((!said || (up && !upsaid))) {
                if (up) upsaid = 1;
                said = 1;
                f[0] = 0x88; f[1] = 3; f[2] = 0x11; f[3] = key; f[4] = ck(f, 4); f[5] = 12;
                write(fd, f, 6);
                memset(r, 0xff, 8);
                if (!up) r[3] &= ~1;
                for (c = 0; c < 8; c++) r[c] ^= ((key << c) | (key >> ((8 - c) & 7))) & 0xff;
                r[8] = r[9] = 0;
                r[10] = ck(r, 10);
                r[11] = 0;
                pwrite(fd, r, 12, 4096);
                lseek(fd, 4096, SEEK_SET);
                read(fd, r, 12);
            } else {
                f[0] = 0x89; f[1] = 2; f[2] = 0x02; f[3] = ck(f, 3); f[4] = 0; n = 5;
                write(fd, f, n);
            }
            usleep(5000);
            continue;
        }
        int right = strcmp(mode, "left") && (strcmp(mode, "tap") || (t % 360) < 300);
        key = (key * 37 + 11) & 0xff;
        if (plain) { f[0] = 0x88; f[1] = 2; f[2] = 0x11; f[3] = ck(f, 3); f[4] = 12; n = 5; }
        else { f[0] = 0x88; f[1] = 3; f[2] = 0x11; f[3] = key; f[4] = ck(f, 4); f[5] = 12; n = 6; }
        write(fd, f, n);
        memset(r, 0xff, 8);
        if (right) r[3] &= ~1;
        if (!strcmp(mode, "left")) r[3] &= ~2;
        if (!plain)
            for (c = 0; c < 8; c++) r[c] ^= ((key << c) | (key >> ((8 - c) & 7))) & 0xff;
        r[8] = r[9] = 0;
        r[10] = ck(r, 10);
        r[11] = 0;
        pwrite(fd, r, 12, 4096);
        lseek(fd, 4096, SEEK_SET);
        read(fd, r, 12);
        usleep(5000);
    }
    return 0;
}
EOF
$CC $CF -fno-pie -no-pie -nostdlib -nostartfiles "$ROOT/usr/lib/crt1.o" "$ROOT/usr/lib/crti.o" \
    "$T/driver.c" "$ROOT/usr/lib/crtn.o" -L"$ROOT/lib" -L"$ROOT/usr/lib" \
    -Wl,-rpath-link,"$ROOT/lib" -Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3 \
    -l:libc.so.6 "$ROOT/usr/lib/libc_nonshared.a" -lgcc -o "$T/driver"
mkdir -p "$T/dev"
cat > "$T/reboot.sh" <<EOF
#!/bin/sh
echo "\$* rb=\$CODESELECT_REBOOT" >> "$T/calls"
EOF
chmod +x "$T/reboot.sh"
printf 'image=p3|A\nimage=p7|B\nboot_menu=menu\n' > "$T/conf-off"
printf 'image=p3|A\nimage=p7|B\nboot_menu=flipper\nflip_hold=1\nflip_guard=0\n' > "$T/conf-on"

fail=0
run() {   # run NAME RUN_MS WANT_CALLS [ENV-ARG...]
    local name=$1 run_ms=$2 want=$3 mode=$1
    shift 3
    case "$name" in conf-*|row-*|shared-*) mode=attract ;; esac
    rm -f "$T/calls" "$T/trace"
    : > "$T/dev/ttymxc1"
    # no row unless the case names one: never the rig's /dump/padmenu.cfg (qemu -L finds $ROOT/dump/padmenu.cfg, which
    # an emulator run of a card with the row leaves there)
    local row=-E\ PADMENU_ROW_CFG="$T/no-row.cfg"
    case " $* " in *PADMENU_ROW_CFG=*) row= ;; esac
    "$QEMU" -L "$ROOT" -E LD_PRELOAD="$SO" -E PADMENU_CMD="$T/reboot.sh" \
        -E "CODESELECT_REBOOT=touch /dump/reboot.req" -E PADMENU_TRACE="$T/trace" $row "$@" \
        "$T/driver" "$mode" "$T/dev/ttymxc1" "$run_ms" "${ROWV:-0}" 2>"$T/err" \
        || { echo "padmenu_flip_test: $name: driver failed"; cat "$T/err"; fail=1; return; }
    sleep 0.3
    got=$( [ -f "$T/calls" ] && wc -l < "$T/calls" || echo 0)
    if [ "$got" -ne "$want" ]; then
        echo "padmenu_flip_test: FAIL $name: $got restart(s), wanted $want"; cat "$T/err" "$T/trace" 2>/dev/null
        fail=1; return
    fi
    if [ "$want" -eq 1 ] && ! grep -q "right flipper held" "$T/err"; then
        echo "padmenu_flip_test: FAIL $name: nothing said on stderr"; fail=1; return
    fi
    echo "padmenu_flip_test: ok $name ($got restart)"
}
FAST="-E PADMENU_FLIP_MS=400 -E PADMENU_FLIP_GUARD_MS=0 -E PADMENU_CONF=$T/conf-off"
run attract  1200 1 $FAST
run plain    1200 1 $FAST
run game     1200 0 $FAST
run left     1200 0 $FAST
run other    1200 1 $FAST
run tilt      900 0 -E PADMENU_FLIP_MS=400 -E PADMENU_FLIP_GUARD_MS=800 -E PADMENU_CONF="$T/conf-off"
run tiltlate 2000 1 -E PADMENU_FLIP_MS=400 -E PADMENU_FLIP_GUARD_MS=800 -E PADMENU_CONF="$T/conf-off"
run tap      1500 0 $FAST
run sparse   1200 1 $FAST
run sparseup 1200 0 $FAST
run conf-off 1600 0 -E PADMENU_CONF="$T/conf-off"
run conf-on  1800 1 -E PADMENU_CONF="$T/conf-on"
ADDR=$(nm "$T/driver" | awk '$3 == "row_word" { print $1 }')
[ -n "$ADDR" ] || { echo "padmenu_flip_test: no row_word in the driver"; exit 1; }
printf 'flip_secs\t0x%s\tboot_flip\t15\n' "$ADDR" > "$T/row.cfg"
printf 'flip_secs\t0x00000010\tboot_flip\t15\n' > "$T/row-unmapped.cfg"
printf 'flip_secs\t0xfade0004\tboot_flip\t15\n' > "$T/shared.cfg"
printf 'more_select 3\nboot_flip 0\n' > "$T/state-off"
ROWFAST="-E PADMENU_FLIP_MS=400 -E PADMENU_FLIP_GUARD_MS=0"
ROWV=0 run row-off      1200 0 $ROWFAST -E PADMENU_CONF="$T/conf-on" -E PADMENU_ROW_CFG="$T/row.cfg"
ROWV=15 run row-on       1200 1 $ROWFAST -E PADMENU_CONF="$T/conf-off" -E PADMENU_ROW_CFG="$T/row.cfg"
ROWV=9999 run row-bad  1200 1 $ROWFAST -E PADMENU_CONF="$T/conf-off" -E PADMENU_ROW_CFG="$T/row.cfg"
ROWV=3 run row-low      1600 0 -E PADMENU_FLIP_MS=400 -E PADMENU_CONF="$T/conf-on" -E PADMENU_ROW_CFG="$T/row.cfg"
ROWV=15 run row-guard    1600 0 -E PADMENU_FLIP_MS=400 -E PADMENU_CONF="$T/conf-on" -E PADMENU_ROW_CFG="$T/row.cfg"
run row-unmapped 1200 1 $ROWFAST -E PADMENU_CONF="$T/conf-off" -E PADMENU_ROW_CFG="$T/row-unmapped.cfg"
run shared-off  1200 0 $ROWFAST -E PADMENU_CONF="$T/conf-on" -E PADMENU_ROW_CFG="$T/shared.cfg" \
    -E PADMENU_ROW_STATE="$T/state-off"
run shared-none 1200 1 $ROWFAST -E PADMENU_CONF="$T/conf-off" -E PADMENU_ROW_CFG="$T/shared.cfg" \
    -E PADMENU_ROW_STATE="$T/no-such-state"
[ "$fail" = 0 ] && echo "padmenu_flip_test: OK" || { echo "padmenu_flip_test: FAILED"; exit 1; }
