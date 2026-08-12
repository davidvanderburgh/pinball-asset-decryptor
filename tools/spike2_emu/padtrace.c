/* padtrace.c - TRACE-ONLY LD_PRELOAD interposer for item 43.
 *
 * PURPOSE. The emulator can render the turtles service menu correctly only when
 * the get_state/caps lie is active BEFORE menu entry (the door-gate build); the
 * same lie started at menu entry loses to a decision the game latches once. To
 * fix that without guessing one 5-minute boot at a time, this logs what the
 * REAL machine's GStreamer does during door -> Select -> Select: exactly when
 * caps becomes available, when preroll completes (state-changed messages), what
 * width/height the page reads, and the game's own mode/flag words at each call.
 *
 * IT CHANGES NOTHING. Every interposed function chains to the real library via
 * RTLD_NEXT and returns the real result unmodified. It only reads and logs.
 * Safe to LD_PRELOAD on the real machine: if it fails to load, ld.so warns and
 * the game still starts; if it loads, it is a passive tap.
 *
 * BUILD (build_padtrace.sh): armhf, -nostdlib, linked against the CARD'S OWN
 * libc.so.6 / libdl.so.2 / libgstreamer-0.10 so the symbol versions match the
 * machine's glibc 2.21 exactly - the same recipe hwshim.so is built with and
 * runs under on this same rootfs.
 *
 * LOG. Appends to $PAD_TRACE_LOG (default /dump/padtrace.log - /dump is the
 * writable log partition the game already uses). hwshim writes to stderr, which
 * on the real machine is /dev/null; this opens its own file instead.
 *
 * MODE/FLAG. The game is EXEC_P (fixed load address), so its .data/.bss globals
 * sit at the same vaddr on the real machine as in the emulator. For
 * turtles_pro V1.59.0: 0x650744 = app mode (attract=1, menu/boot=0, game=3),
 * 0x663958 = in-service-menu (0/1). Override with PAD_TRACE_MODEADDR /
 * PAD_TRACE_FLAGADDR (hex) on any other build; set either to 0 to skip the read.
 */

#include <stdarg.h>

extern void *dlsym(void *, const char *);
#define RTLD_NEXT ((void *)-1L)
extern int   open(const char *, int, int);
extern long  write(int, const void *, unsigned long);
extern int   snprintf(char *, unsigned long, const char *, ...);
extern int   clock_gettime(int, void *);
extern char *getenv(const char *);

#define O_WRONLY 1
#define O_CREAT  0100
#define O_APPEND 02000
#define CLOCK_MONOTONIC 1

/* ---- config read once ---------------------------------------------------- */

static unsigned long parse_hex(const char *e)
{
    unsigned long a = 0;
    if (!e || !*e) return 0;
    if (e[0] == '0' && (e[1] == 'x' || e[1] == 'X')) e += 2;
    for (; *e; e++) {
        int d;
        if (*e >= '0' && *e <= '9') d = *e - '0';
        else if (*e >= 'a' && *e <= 'f') d = *e - 'a' + 10;
        else if (*e >= 'A' && *e <= 'F') d = *e - 'A' + 10;
        else break;
        a = a * 16 + (unsigned)d;
    }
    return a;
}

static volatile unsigned *g_mode;
static volatile unsigned *g_flag;
static int cfg_done;

static void cfg(void)
{
    const char *e;
    if (cfg_done) return;
    cfg_done = 1;
    e = getenv("PAD_TRACE_MODEADDR");
    g_mode = (volatile unsigned *)(e ? parse_hex(e) : 0x650744ul);
    e = getenv("PAD_TRACE_FLAGADDR");
    g_flag = (volatile unsigned *)(e ? parse_hex(e) : 0x663958ul);
}

/* ---- the log ------------------------------------------------------------- */

static int logfd = -2;   /* -2 = unopened, -1 = failed */

static void ensure_log(void)
{
    const char *p;
    if (logfd != -2) return;
    p = getenv("PAD_TRACE_LOG");
    if (!p || !*p) p = "/dump/padtrace.log";
    logfd = open(p, O_WRONLY | O_CREAT | O_APPEND, 0644);
}

static unsigned long now_ms(void)
{
    /* struct timespec on armhf 32-bit: { long tv_sec; long tv_nsec; } */
    long ts[2];
    ts[0] = ts[1] = 0;
    clock_gettime(CLOCK_MONOTONIC, ts);
    return (unsigned long)ts[0] * 1000ul + (unsigned long)ts[1] / 1000000ul;
}

static void say(const char *s)
{
    char b[400];
    unsigned long m = 0, n = 0, t;
    int k;
    cfg();
    ensure_log();
    if (logfd < 0) return;
    t = now_ms();
    k = snprintf(b, sizeof b, "[%lu.%03lu] mode[%p]=%u flag[%p]=%u | ",
                 t / 1000ul, t % 1000ul,
                 (void *)g_mode, g_mode ? *g_mode : 0u,
                 (void *)g_flag, g_flag ? *g_flag : 0u);
    if (k > 0) m = (unsigned long)k;
    while (s[n] && m < sizeof b - 2) b[m++] = s[n++];
    b[m++] = '\n';
    write(logfd, b, m);
}

/* return address of the caller, so a menu-entry read is attributable to the
 * game code that made it (the same trick gststub uses). */
#define RA() ((unsigned long)__builtin_return_address(0))

static int streq(const char *a, const char *b)
{
    if (!a || !b) return 0;
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

/* One line at load, so "did the preload take?" is answerable from the log
 * alone. Runs after all LOAD segments are mapped (the game's .bss included, so
 * the mode/flag reads are safe = 0 this early) and before the game's own main. */
__attribute__((constructor))
static void padtrace_init(void)
{
    say("==== padtrace loaded (trace-only) ====");
}

/* ---- interposed GStreamer entry points (all TRACE-ONLY) ------------------ */

static const char *st_name(int s)
{
    static const char *n[5] = { "VOID", "NULL", "READY", "PAUSED", "PLAYING" };
    return (s >= 0 && s < 5) ? n[s] : "?";
}

int gst_element_set_state(void *element, int state)
{
    static int (*real)(void *, int);
    int r;
    char b[200];
    if (!real) real = dlsym(RTLD_NEXT, "gst_element_set_state");
    r = real ? real(element, state) : 0;
    snprintf(b, sizeof b, "set_state(%p, %s) -> %d  ra=0x%lx",
             element, st_name(state), r, RA());
    say(b);
    return r;
}

/* GST_STATE_CHANGE: FAILURE 0, SUCCESS 1, ASYNC 2, NO_PREROLL 3 */
int gst_element_get_state(void *element, int *state, int *pending,
                          unsigned long long timeout)
{
    static int (*real)(void *, int *, int *, unsigned long long);
    int r;
    char b[200];
    if (!real) real = dlsym(RTLD_NEXT, "gst_element_get_state");
    r = real ? real(element, state, pending, timeout) : 0;
    snprintf(b, sizeof b, "get_state(%p) -> ret=%d state=%s pending=%s  ra=0x%lx",
             element, r, st_name(state ? *state : -1),
             st_name(pending ? *pending : -1), RA());
    say(b);
    return r;
}

void *gst_pad_get_negotiated_caps(void *pad)
{
    static void *(*real)(void *);
    void *r;
    char b[160];
    if (!real) real = dlsym(RTLD_NEXT, "gst_pad_get_negotiated_caps");
    r = real ? real(pad) : 0;
    snprintf(b, sizeof b, "get_negotiated_caps(%p) -> %s (%p)  ra=0x%lx",
             pad, r ? "CAPS" : "NULL", r, RA());
    say(b);
    return r;
}

void *gst_caps_get_structure(void *caps, unsigned index)
{
    static void *(*real)(void *, unsigned);
    void *r;
    char b[160];
    if (!real) real = dlsym(RTLD_NEXT, "gst_caps_get_structure");
    r = real ? real(caps, index) : 0;
    snprintf(b, sizeof b, "caps_get_structure(%p,%u) -> %p  ra=0x%lx",
             caps, index, r, RA());
    say(b);
    return r;
}

int gst_structure_get_int(void *s, const char *field, int *value)
{
    static int (*real)(void *, const char *, int *);
    int r;
    char b[200];
    if (!real) real = dlsym(RTLD_NEXT, "gst_structure_get_int");
    r = real ? real(s, field, value) : 0;
    snprintf(b, sizeof b, "structure_get_int(\"%s\") -> %d value=%d  ra=0x%lx",
             field ? field : "(null)", r, (r && value) ? *value : -1, RA());
    say(b);
    return r;
}

/* Preroll / state timeline: the game parses these off its bus watch. Logging
 * them here is the direct measure of WHEN the real decoder finished preroll
 * (READY->PAUSED async-done) relative to the menu page build. */
void gst_message_parse_state_changed(void *msg, int *oldst, int *newst,
                                     int *pending)
{
    static void (*real)(void *, int *, int *, int *);
    char b[200];
    if (!real) real = dlsym(RTLD_NEXT, "gst_message_parse_state_changed");
    if (real) real(msg, oldst, newst, pending);
    snprintf(b, sizeof b, "MSG state_changed  %s -> %s (pending %s)  ra=0x%lx",
             st_name(oldst ? *oldst : -1), st_name(newst ? *newst : -1),
             st_name(pending ? *pending : -1), RA());
    say(b);
}

/* g_object_set + g_signal_connect_data forward through glib's _valist/real
 * entry points. Under the EMULATOR that BYPASSES gststub's own g_object_set
 * (which records the clip location for the fake decoder), so the fake video
 * never prerolls and the game wedges at boot - an emulator-only collision, since
 * the real machine has no gststub. Build the emulator VALIDATION variant with
 * -DPAD_TRACE_NO_GSET to drop these two and let the game reach attract, so the
 * live mode/flag read can be checked; the REAL-MACHINE build keeps them. */
#ifndef PAD_TRACE_NO_GSET
/* Which clip is loaded on which pipeline. Varargs: read the value through a
 * va_copy and forward the UNTOUCHED original via g_object_set_valist, exactly
 * as gststub does - reading the caller's list and then forwarding it would set
 * the property to whatever came next. */
void g_object_set(void *obj, const char *first, ...)
{
    static void (*real_valist)(void *, const char *, va_list);
    va_list ap;
    if (!real_valist) real_valist = dlsym(RTLD_NEXT, "g_object_set_valist");
    va_start(ap, first);
    if (streq(first, "location")) {
        va_list peek;
        const char *v;
        char b[300];
        va_copy(peek, ap);
        v = va_arg(peek, const char *);
        snprintf(b, sizeof b, "set %p location=\"%s\"", obj, v ? v : "(null)");
        say(b);
        va_end(peek);
    }
    if (real_valist) real_valist(obj, first, ap);
    va_end(ap);
}

/* The handoff registration: address of the callback that receives decoded
 * frames, so a "did the menu backdrop ever deliver?" question is answerable. */
unsigned long g_signal_connect_data(void *instance, const char *signal,
                                    void *handler, void *data,
                                    void *destroy, int flags)
{
    static unsigned long (*real)(void *, const char *, void *, void *,
                                 void *, int);
    unsigned long r;
    if (!real) real = dlsym(RTLD_NEXT, "g_signal_connect_data");
    r = real ? real(instance, signal, handler, data, destroy, flags) : 0;
    if (streq(signal, "handoff")) {
        char b[200];
        snprintf(b, sizeof b, "connect handoff on %p handler=%p data=%p",
                 instance, handler, data);
        say(b);
    }
    return r;
}
#endif /* PAD_TRACE_NO_GSET */
