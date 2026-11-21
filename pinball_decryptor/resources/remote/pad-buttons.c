/* padbtn.c - PAD remote buttons for a real Spike 2 machine (PAD-1467).
 *
 * Preloaded into the game beside PAD's mode runtime. The game's cabinet-switch thread loops on an 8-byte
 * SPI_IOC_MESSAGE on /dev/spidev1.0; the 8 bytes it reads back are one bit a cabinet switch, ACTIVE LOW (a 0 is a
 * switch that is made). This wraps ioctl(), lets the real transfer happen, and then:
 *
 *   - OBSERVE: when a bit of the word changes, appends "<uptime cs> bit <n> <old>-><new>" to LOG (a few hundred
 *     lines at most), which is how the bits of the service buttons and the coin door were found;
 *   - PRESS: reads CTL at most every 20 ms. It holds one line, "<mask hex> <deadline cs> <need bit> <need value>":
 *     until the deadline (uptime, centiseconds, never more than 3 s ahead) every bit in the mask is cleared in the
 *     word the game sees - but only while the REAL word's <need bit> reads <need value> (the coin door open), so a
 *     press from the PC does nothing a hand at the open coin door could not do.
 *
 * It uses no library: raw system calls only, so nothing here can clash with the game's own libraries, and every
 * path that is not exactly the 8-byte cabinet transfer is passed straight through.
 */
typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;

#ifndef CTL
#define CTL "/run/pad-buttons"
#endif
#ifndef STATE
#define STATE "/run/pad-buttons.state"
#endif
/* LOG is defined only for the build that watches the real buttons (-DLOG='"/dump/pad-buttons.log"'): the one
 * that ships writes no log. */
#define MAX_LOG_LINES 600
#define MAX_AHEAD_CS 300

#define SYS_read 3
#define SYS_write 4
#define SYS_open 5
#define SYS_close 6
#define SYS_ioctl 54
#define SYS_clock_gettime 263

static long sc3(long nr, long a, long b, long c)
{
    register long r7 __asm__("r7") = nr;
    register long r0 __asm__("r0") = a;
    register long r1 __asm__("r1") = b;
    register long r2 __asm__("r2") = c;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r7), "r"(r1), "r"(r2) : "memory");
    return r0;
}

extern int *__errno_location(void) __attribute__((weak));

struct ts { long sec; long nsec; };

static u32 now_cs(void)
{
    struct ts t;
    if (sc3(SYS_clock_gettime, 1 /* CLOCK_MONOTONIC */, (long)&t, 0) != 0)
        return 0;
    return (u32)t.sec * 100u + (u32)(t.nsec / 10000000L);
}

static int put_num(char *p, u32 v)
{
    char tmp[12];
    int n = 0, i = 0;
    do { tmp[n++] = (char)('0' + v % 10u); v /= 10u; } while (v && n < 11);
    while (n) p[i++] = tmp[--n];
    return i;
}

/* STATE: "<uptime cs> <the real word, 16 hex digits>", rewritten twice a second: the app reads from it that the
 * shim is in the running game, and whether the coin door is open, before it offers a press. */
static u32 state_at;

static void write_state(u32 cs, const u8 *rx)
{
    static const char hex[] = "0123456789abcdef";
    char line[40];
    int n = 0, i, fd;
    state_at = cs;
    n += put_num(line + n, cs);
    line[n++] = ' ';
    for (i = 0; i < 8; i++) { line[n++] = hex[rx[i] >> 4]; line[n++] = hex[rx[i] & 15]; }
    line[n++] = '\n';
    fd = (int)sc3(SYS_open, (long)STATE, 01 | 0100 | 01000 /* O_WRONLY|O_CREAT|O_TRUNC */, 0644);
    if (fd < 0)
        return;
    sc3(SYS_write, fd, (long)line, n);
    sc3(SYS_close, fd, 0, 0);
}

#ifdef LOG
static int log_lines;

static void log_edge(u32 cs, int bit, int was, int is)
{
    char line[48];
    int n = 0, fd;
    if (log_lines >= MAX_LOG_LINES)
        return;
    log_lines++;
    n += put_num(line + n, cs);
    line[n++] = ' '; line[n++] = 'b'; line[n++] = 'i'; line[n++] = 't'; line[n++] = ' ';
    n += put_num(line + n, (u32)bit);
    line[n++] = ' ';
    line[n++] = (char)('0' + was); line[n++] = '-'; line[n++] = '>'; line[n++] = (char)('0' + is);
    line[n++] = '\n';
    fd = (int)sc3(SYS_open, (long)LOG, 01 | 0100 | 02000 /* O_WRONLY|O_CREAT|O_APPEND */, 0644);
    if (fd < 0)
        return;
    sc3(SYS_write, fd, (long)line, n);
    sc3(SYS_close, fd, 0, 0);
}
#else
#define log_edge(cs, bit, was, is) ((void)0)
#endif

/* the press being asked for, re-read from CTL at most every 20 ms */
static u64 want_mask;
static u32 want_until;
static int need_bit = -1, need_val;
static u32 ctl_read_at;

static void read_ctl(u32 cs)
{
    char buf[64];
    int fd, n, i = 0;
    u64 mask = 0;
    u32 until = 0, nb = 0, nv = 0;
    int neg = 0, got = 0;

    ctl_read_at = cs;
    want_mask = 0;
    fd = (int)sc3(SYS_open, (long)CTL, 0 /* O_RDONLY */, 0);
    if (fd < 0)
        return;
    n = (int)sc3(SYS_read, fd, (long)buf, sizeof buf - 1);
    sc3(SYS_close, fd, 0, 0);
    if (n <= 0)
        return;
    buf[n] = 0;
    for (; i < n; i++) {                                   /* mask, hexadecimal */
        char c = buf[i];
        int d = (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10 : -1;
        if (d < 0) break;
        mask = (mask << 4) | (u64)d; got = 1;
    }
    if (!got || buf[i] != ' ') return;
    for (i++, got = 0; i < n && buf[i] >= '0' && buf[i] <= '9'; i++) { until = until * 10u + (u32)(buf[i] - '0'); got = 1; }
    if (!got || buf[i] != ' ') return;
    i++;
    if (buf[i] == '-') { neg = 1; i++; }
    for (got = 0; i < n && buf[i] >= '0' && buf[i] <= '9'; i++) { nb = nb * 10u + (u32)(buf[i] - '0'); got = 1; }
    if (!got || buf[i] != ' ') return;
    for (i++, got = 0; i < n && buf[i] >= '0' && buf[i] <= '9'; i++) { nv = nv * 10u + (u32)(buf[i] - '0'); got = 1; }
    if (!got) return;
    if (until < cs || until - cs > MAX_AHEAD_CS) return;   /* over, or further ahead than any press is held */
    if (!neg && nb > 63) return;
    want_mask = mask;
    want_until = until;
    need_bit = neg ? -1 : (int)nb;
    need_val = nv ? 1 : 0;
}

static u8 last[8];
static int have_last;

static void cabinet_word(u8 *rx)
{
    u32 cs = now_cs();
    int i, b;

    if (have_last) {
        for (i = 0; i < 8; i++) {
            u8 diff = (u8)(rx[i] ^ last[i]);
            if (!diff) continue;
            for (b = 0; b < 8; b++)
                if (diff & (1u << b))
                    log_edge(cs, i * 8 + b, (last[i] >> b) & 1, (rx[i] >> b) & 1);
        }
    }
    for (i = 0; i < 8; i++) last[i] = rx[i];
    have_last = 1;
    if (cs - state_at >= 50u)
        write_state(cs, rx);

    if (cs - ctl_read_at >= 2u)
        read_ctl(cs);
    if (!want_mask || cs > want_until)
        return;
    if (need_bit >= 0 && (((rx[need_bit >> 3] >> (need_bit & 7)) & 1) != need_val))
        return;                                            /* the coin door is not open: no press */
    for (i = 0; i < 64; i++)
        if (want_mask & (1ULL << i))
            rx[i >> 3] = (u8)(rx[i >> 3] & ~(1u << (i & 7)));   /* active low: 0 = made */
}

int ioctl(int fd, unsigned long req, void *arg)
{
    long r = sc3(SYS_ioctl, fd, (long)req, (long)arg);
    if (r < 0 && r > -4096) {
        if (__errno_location) *__errno_location() = (int)-r;
        return -1;
    }
    /* SPI_IOC_MESSAGE(n): type 'k' (0x6b), nr 0, size n*32; one 8-byte full-duplex transfer is the cabinet word */
    if (arg && ((req >> 8) & 0xffu) == 0x6bu && (req & 0xffu) == 0u && ((req >> 16) & 0x3fffu) == 32u) {
        const u32 *t = (const u32 *)arg;                   /* +8 rx_buf (u64), +16 len (u32) */
        u8 *rx = (u8 *)(unsigned long)t[2];
        if (rx && t[4] == 8u)
            cabinet_word(rx);
    }
    return (int)r;
}

#ifdef PADBTN_TEST
void test_word(u8 *rx) { cabinet_word(rx); }
#endif
