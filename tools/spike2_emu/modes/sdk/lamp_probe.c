/* lamp_probe.c - hold and release named playfield inserts by hand, from a trigger file (item mode-leds).
 *
 * Not a game mode: a rig instrument built with the SDK, next to mode_file.c:
 *   build_mode.sh -o mode.so mode_file.c lamp_probe.c
 * Twice a second it looks for /dump/lamp.do, whose first line is ONE command:
 *   set <rrggbb> <solid|blink|pulse|chase> <ms> <name>[,<name>...]    pm_lamp_set
 *   shot <mask> <rrggbb> <pattern> <ms>                              pm_lamp_shot
 *   release <name>[,<name>...]                                        pm_lamp_release
 *   release_shot <mask>                                               pm_lamp_release_shot
 *   release_all                                                       pm_lamp_release_all
 *   prio <1-255>                                                      pm_lamp_priority
 *   layers                                                            the game's lamp layers now
 *   list                                                              every insert the port names
 * and logs each as "[lamps] ..." in /dump/mode.log, with what the call returned, which of the
 * game's own modes is active (pm_stock_mode_running) and the layers. `watch <ms>` logs the
 * layers every <ms> whenever they change (0 = off). Works in attract too.
 */
#include "pad_mode.h"

static unsigned long watch_ms, watch_last;
static char watch_prev[200];

static const char *skip(const char *s)
{
    while (*s == ' ' || *s == '\t') s++;
    return s;
}

static const char *word(const char *s, char *out, unsigned cap)
{
    unsigned n = 0;
    s = skip(s);
    while (*s && *s != ' ' && *s != '\t' && n + 1 < cap) out[n++] = *s++;
    out[n] = 0;
    while (*s && *s != ' ' && *s != '\t') s++;
    return skip(s);
}

static int same(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

static uint64_t hex64(const char *s)
{
    uint64_t v = 0;
    s = skip(s);
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) s += 2;
    for (;; s++) {
        if (*s >= '0' && *s <= '9') v = v * 16 + (unsigned)(*s - '0');
        else if (*s >= 'a' && *s <= 'f') v = v * 16 + (unsigned)(*s - 'a' + 10);
        else if (*s >= 'A' && *s <= 'F') v = v * 16 + (unsigned)(*s - 'A' + 10);
        else break;
    }
    return v;
}

static unsigned dec(const char *s)
{
    unsigned v = 0;
    s = skip(s);
    while (*s >= '0' && *s <= '9') v = v * 10 + (unsigned)(*s++ - '0');
    return v;
}

static int pattern_of(const char *w)
{
    if (same(w, "blink")) return PM_LAMP_BLINK;
    if (same(w, "pulse")) return PM_LAMP_PULSE;
    if (same(w, "chase")) return PM_LAMP_CHASE;
    return PM_LAMP_SOLID;
}

static void layers_text(char *b, unsigned cap)
{
    unsigned p[32];
    int n = pm_lamp_layers(p, 32), i, m = 0;
    b[0] = 0;
    if (n < 0) { pm_snprintf(b, cap, "(no layer list in the port)"); return; }
    for (i = 0; i < n && m + 8 < (int)cap; i++)
        m += pm_snprintf(b + m, cap - (unsigned)m, "%s%u%s", i ? " " : "", p[i] & 0xffu, p[i] & 0x100u ? "*" : "");
}

static const char *stock_now(void)
{
    int k = pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL | PM_STOCK_ANY);
    return k < 0 ? "the port cannot tell" : k == 0 ? "none" : pm_stock_mode_what((unsigned)k);
}

static void run(const char *line)
{
    char cmd[16], a[24], b[24], c[24], lay[200];
    const char *s = word(line, cmd, sizeof cmd);
    int r = 0;
    if (same(cmd, "set")) {
        s = word(s, a, sizeof a);              /* colour */
        s = word(s, b, sizeof b);              /* pattern */
        s = word(s, c, sizeof c);              /* ms */
        r = pm_lamp_set(s, (unsigned)hex64(a), pattern_of(b), dec(c));
    } else if (same(cmd, "shot")) {
        uint64_t mask;
        s = word(s, lay, sizeof lay);
        mask = hex64(lay);
        s = word(s, a, sizeof a);
        s = word(s, b, sizeof b);
        s = word(s, c, sizeof c);
        r = pm_lamp_shot(mask, (unsigned)hex64(a), pattern_of(b), dec(c));
    } else if (same(cmd, "release")) {
        r = pm_lamp_release(s);
    } else if (same(cmd, "release_shot")) {
        r = pm_lamp_release_shot(hex64(s));
    } else if (same(cmd, "release_all")) {
        r = pm_lamp_release_all();
    } else if (same(cmd, "prio")) {
        r = pm_lamp_priority(dec(s));
    } else if (same(cmd, "watch")) {
        watch_ms = dec(s);
        watch_prev[0] = 0;
        r = (int)watch_ms;
    } else if (same(cmd, "list")) {
        int i;
        for (i = 0; i < pm_lamp_count(); i++) {
            uint64_t shots = 0;
            const char *n = pm_lamp_at(i, &shots);
            pm_log("insert %d: %s, shots %08x_%08x", i, n, (unsigned)(shots >> 32), (unsigned)shots);
        }
        r = pm_lamp_count();
    } else if (same(cmd, "slots")) {
        /* slots <layer list heads> <output array pointer> <light>: a porting check, raw reads - every layer's
         * slot for one light (priority, event, slot bytes 0..11 and +36) and the compositor's output record */
        unsigned heads, outp, light, g;
        int guard = 64;
        s = word(s, a, sizeof a);
        heads = (unsigned)hex64(a);
        s = word(s, b, sizeof b);
        outp = (unsigned)hex64(b);
        light = dec(s);
        for (g = *(unsigned *)(unsigned long)(heads + 4); g && guard-- > 0; g = *(unsigned *)(unsigned long)(g + 20)) {
            const unsigned char *sl = (const unsigned char *)(unsigned long)(*(unsigned *)(unsigned long)g + light * 40u);
            pm_log("slot %u in layer 0x%08x prio %u ev 0x%08x cb 0x%08x: %02x%02x %02x %02x .. +8 %02x +16 %08x +32 %02x %02x %02x %02x +36 %02x",
                   light, g, *(const unsigned char *)(unsigned long)(g + 4), *(unsigned *)(unsigned long)(g + 16),
                   *(unsigned *)(unsigned long)(g + 12), sl[1], sl[0], sl[2], sl[3], sl[8],
                   *(const unsigned *)(sl + 16), sl[32], sl[33], sl[34], sl[35], sl[36]);
        }
        {
            const unsigned char *o = (const unsigned char *)(unsigned long)(*(unsigned *)(unsigned long)outp + light * 48u);
            pm_log("out %u: +8 %02x %02x %02x %02x %02x %02x %02x %02x | +16 %02x", light, o[8], o[9], o[10], o[11], o[12],
                   o[13], o[14], o[15], o[16]);
        }
        r = 1;
    } else if (same(cmd, "wiremap")) {
        /* wiremap <board table> <board count>: a porting check, raw reads - the lamp output stage's boards and,
         * for each, the lights it sends and the channel each goes out on: "light:channel" pairs */
        unsigned tab, cnt, k, node;
        char line[240];
        s = word(s, a, sizeof a);
        tab = (unsigned)hex64(a);
        cnt = *(unsigned *)(unsigned long)(unsigned)hex64(s);
        for (k = 0; k < cnt && k < 32; k++) {
            unsigned board = *(unsigned *)(unsigned long)(tab + 8 * k), n = 0, m = 0, guard = 400;
            if (!board) continue;
            line[0] = 0;
            for (node = *(unsigned *)(unsigned long)(tab + 8 * k + 4); node && guard--; node = *(unsigned *)(unsigned long)(node + 16)) {
                unsigned ch = *(unsigned *)(unsigned long)(node + 12);
                m += pm_snprintf(line + m, sizeof line - (unsigned)m, " %u:%u", *(unsigned short *)(unsigned long)node,
                                 ch ? *(unsigned short *)(unsigned long)(ch + 30) : 9999);
                if (++n % 16 == 0) {
                    pm_log("board %u (0x%08x, byte0 %u, +4 %08x, +0x90 %u) lights%s", k, board, *(unsigned char *)(unsigned long)board,
                           *(unsigned *)(unsigned long)(board + 4), *(unsigned short *)(unsigned long)(board + 0x90), line);
                    m = 0;
                    line[0] = 0;
                }
            }
            if (m) pm_log("board %u (0x%08x, byte0 %u) lights%s", k, board, *(unsigned char *)(unsigned long)board, line);
        }
        r = (int)cnt;
    } else if (!same(cmd, "layers")) {
        pm_log("unknown command \"%.60s\"", line);
        return;
    }
    layers_text(lay, sizeof lay);
    pm_log("DO %.120s -> %d | game's mode: %s | layers: %s", line, r, stock_now(), lay);
}

static void on_tick(void)
{
    static unsigned ticks;
    char line[200], lay[200];
    if (++ticks % 30 == 0 && pm_trigger_text("lamp.do", line, sizeof line) && line[0]) run(line);
    if (watch_ms && pm_ms() - watch_last >= watch_ms) {
        int i;
        watch_last = pm_ms();
        layers_text(lay, sizeof lay);
        for (i = 0; lay[i] && lay[i] == watch_prev[i]; i++) ;
        if (lay[i] != watch_prev[i]) {
            pm_log("layers now: %s | game's mode: %s", lay, stock_now());
            for (i = 0; lay[i] && i + 1 < (int)sizeof watch_prev; i++) watch_prev[i] = lay[i];
            watch_prev[i] = 0;
        }
    }
}

static void on_init(void)
{
    pm_log("ready: %d named inserts%s", pm_lamp_count(), pm_can(PM_CAN_LAMPS) ? "" : " - this port has no lamp layer");
}

static const struct pm_mode lamp_probe = { .name = "lamps", .init = on_init, .tick = on_tick };
PM_REGISTER(lamp_probe);
