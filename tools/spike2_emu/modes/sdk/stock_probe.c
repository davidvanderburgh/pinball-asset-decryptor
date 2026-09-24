/* stock_probe.c - an INSTRUMENT, never put on a card: start one of the game's OWN compiled rules
 * on demand and log what its shot handler does with each shot (item 158).
 *
 * The game's own rules (a battle, a multiball) are compiled C++ objects: one object per rule,
 * each with a vtable. The table MODE_SDK.md describes ("The game's own modes") names the slots:
 * START, STOP, the SHOT HANDLER, the LIT-SHOT query, the "active" query. This object reads a
 * small config, finds each watched rule through the game's own manager, and WRAPS three of its
 * vtable slots (start, stop, shot) with a function that logs and then calls the original with
 * the same registers and stack words. Nothing the game does changes: every call goes through,
 * and the only code of ours that runs inside the game is the logging around it.
 *
 * Build it WITH the runtime (it needs the tick, the triggers and the log):
 *     build_mode.sh -o stockprobe.so stock_probe.c
 * and run it like any code object: PAD_MODE_SO=/lib/<name>.so, the title's port as
 * /dump/game.port, and its config as /dump/stockprobe.cfg (stock_probe/<game>-<version>.cfg).
 *
 * THE CONFIG (one fact a line, '#' starts a comment; numbers are 0x hex or decimal):
 *   game <name> / version <v>      refused unless the port's game and version are these
 *   get <addr> <w0> <w1>           the manager's get(manager, id); called only if its first two
 *                                  words are these
 *   mgr <addr>                     the manager singleton (get's first argument)
 *   slots start <n> stop <n> shot <n> lit <n> active <n> [mask <n>]   vtable slot numbers on
 *                                  this build; mask = the rule's initial-mask getter, CALLED
 *                                  after each start so the log shows what it returns beside
 *                                  what the start actually stored
 *   field <off>                    the rule's per-player shot mask: u64 at obj + off + 8 * player
 *   gamelit <addr> <w0> <w1>       optional: the manager's "every lit shot" query, f(mgr) -> u64
 *   award <name> <addr> <w0> <w1>  optional: hook an award function's ENTRY; logs its value
 *                                  (r2:r3), r0, r1, its first stack word and the caller (lr)
 *   dispatch <addr>                optional: the shot dispatch, for the SYNTHETIC shot trigger
 *   watch <id> <label> vt <vptr> [pw <off>]... [w <off>]... [vec <off> <stride> <flag> <mask>]
 *                                  a rule to wrap. vt is checked before anything is written;
 *                                  pw = a per-player u32 at obj + off + 4 * player, w = a u32 at
 *                                  obj + off, vec = a std::vector at obj + off (begin, end) of
 *                                  <stride>-byte records, each logged as its byte at <flag> and
 *                                  its u64 at <mask> (Godzilla's tanks); all logged with every
 *                                  state change and shot.
 *
 * TRIGGERS (files in /dump, read twice a second from the tick, deleted when read):
 *   stockprobe.start  "<id>"            START the rule for the player up: get(mgr, id), then
 *                                       vtable[start] - the game's own start, through our wrap
 *   stockprobe.stop   "<id> [reason]"   vtable[stop](obj, reason) (reason 0 when not given)
 *   stockprobe.mark   "<label>"         a MARK line, to line the log up with switch presses
 *   stockprobe.shot   "<mask> [x]"      SYNTHETIC: the shot dispatch called with this mask, as if
 *                                       a switch had made it (x = the dispatch's stack word, 1
 *                                       when not given). Only the rules see it, not the switch.
 * Every start and stop is refused, and logged, unless a player is up and a game is on.
 *
 * THE LOG (/dump/mode.log, every line starts "SP "):
 *   SP ready ... / SP watch <id> ...   what was found and wrapped
 *   SP player a -> b, in_game x -> y   the player up and "a game is on" changed (the player byte
 *                                      reads 1 in attract too on Godzilla: in_game is the signal)
 *   SP event <name>                    each event the port names (game_start, ball_start, ...)
 *   SP shot 0x<mask> p<n>              every shot the game dispatched (before any rule saw it)
 *   SP START / STOP <id> ...           the rule's own start and stop, the caller (lr), the
 *                                      field before -> after, and the pw / w words
 *   SP SHOT <id> p<n> shot 0x.. x ..   an entry into the rule's shot handler: the incoming
 *                                      mask, then field, lit (the lit-shot query) and the
 *                                      words, each BEFORE -> AFTER the handler ran
 *   SP STATE <id> active a lit .. field ..   every 100 ms, when anything changed
 *   SP GAMELIT 0x..                    the game's union of lit shots, when it changed
 *   SP AWARD <name> val <value> lr 0x..   each call of an award function while a player is up
 * stock_probe_read.py turns it into a table. A caller (lr) inside THIS object means the call came
 * through a wrap: a START or STOP from a trigger, or a wrapped handler that TAIL-called the award
 * function (Godzilla LE's tank handler does: its last award's lr is in w_shot).
 *
 * Emulator-proven on Godzilla Premium/LE 1.16 (item 158 smoke, muted, the app's rig): both rules
 * started from the trigger with a ball in play and played their own start screens; every handler
 * entry logged with the shot, the field and lit shots before -> after and the rule's words (a
 * spinner's count went 15 -> 14 on its middle bit; a tank on the Right ramp was destroyed, lit
 * 0x2800200000 -> 0x2800000000); STOP from the trigger; awards with their callers.
 * The .shot trigger has never run.
 *
 * The rules this keeps (MODE_SDK.md): nothing happens from a constructor; the wraps go in
 * from the tick, once the manager has built its rules; the log is capped.
 */
#include "pad_mode.h"

extern int mprotect(void *, __SIZE_TYPE__, int);

#define MAXW 6
#define MAXA 4
#define MAXV 6
#define MAXR 8

typedef uint64_t (*vfn8)(unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned);
typedef uint64_t (*vfn1)(unsigned);
typedef void *(*getfn)(void *, unsigned);

struct watch {
    unsigned id, obj, vt;
    char label[32];
    unsigned npw, pw[MAXV], nw, w[MAXV];
    unsigned vec_off, vec_stride, vec_flag, vec_mask, has_vec;
    vfn8 orig_start, orig_stop, orig_shot;
    int wrapped;
    int have_last, last_active;
    uint64_t last_lit, last_field;
    unsigned last_pw[MAXV], last_w[MAXV];
    unsigned last_nrec, last_rflag[MAXR];
    uint64_t last_rmask[MAXR];
};

struct snap {
    uint64_t field, lit;
    int lit_ok;
    unsigned pw[MAXV], w[MAXV];
    unsigned nrec, rflag[MAXR];
    uint64_t rmask[MAXR];
};

static struct watch W[MAXW];
static int nwatch;
static struct { char name[24]; unsigned addr, w0, w1; int hooked; } A[MAXA];
static int naward;
static char cfg_game[32], cfg_version[16];
static unsigned get_addr, get_w0, get_w1, mgr, field_off = 0x18, dispatch_addr;
static unsigned gamelit_addr, gamelit_w0, gamelit_w1;
static int slot_start = -1, slot_stop = -1, slot_shot = -1, slot_lit = -1, slot_active = -1, slot_mask = -1;
static int cfg_ok, ready, refused;
static unsigned long ticks;
static uint64_t last_gamelit;
static int have_gamelit;
static unsigned award_lines, shot_lines;
static unsigned last_player = 99;
static int last_in_game = -9;

/* ---- small helpers (no libc here) ------------------------------------------------------ */
static int sp_eq(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

static void sp_copy(char *d, unsigned cap, const char *s)
{
    unsigned i;
    for (i = 0; i + 1 < cap && s[i]; i++) d[i] = s[i];
    d[i] = 0;
}

static unsigned rd32(unsigned a) { return *(volatile const unsigned *)(unsigned long)a; }
static uint64_t rd64(unsigned a) { return (uint64_t)rd32(a) | (uint64_t)rd32(a + 4) << 32; }

/* one token of a line: returns its start, NUL-terminates it, advances *p */
static char *tok(char **p)
{
    char *s = *p, *t;
    while (*s == ' ' || *s == '\t') s++;
    if (!*s) { *p = s; return 0; }
    t = s;
    while (*s && *s != ' ' && *s != '\t') s++;
    if (*s) *s++ = 0;
    *p = s;
    return t;
}

static unsigned num(const char *s)
{
    unsigned v = 0, base = 10, d;
    if (!s) return 0;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { base = 16; s += 2; }
    for (;; s++) {
        if (*s >= '0' && *s <= '9') d = (unsigned)(*s - '0');
        else if (base == 16 && *s >= 'a' && *s <= 'f') d = (unsigned)(*s - 'a' + 10);
        else if (base == 16 && *s >= 'A' && *s <= 'F') d = (unsigned)(*s - 'A' + 10);
        else break;
        v = v * base + d;
    }
    return v;
}

static uint64_t num64(const char *s)
{
    uint64_t v = 0;
    unsigned base = 10, d;
    if (!s) return 0;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { base = 16; s += 2; }
    for (;; s++) {
        if (*s >= '0' && *s <= '9') d = (unsigned)(*s - '0');
        else if (base == 16 && *s >= 'a' && *s <= 'f') d = (unsigned)(*s - 'a' + 10);
        else if (base == 16 && *s >= 'A' && *s <= 'F') d = (unsigned)(*s - 'A' + 10);
        else break;
        v = v * base + d;
    }
    return v;
}

/* ---- the config -------------------------------------------------------------------------- */
static void parse_line(char *line)
{
    char *p = line, *k, *t;
    for (t = line; *t; t++) if (*t == '#') { *t = 0; break; }
    k = tok(&p);
    if (!k) return;
    if (sp_eq(k, "game")) { t = tok(&p); if (t) sp_copy(cfg_game, sizeof cfg_game, t); }
    else if (sp_eq(k, "version")) { t = tok(&p); if (t) sp_copy(cfg_version, sizeof cfg_version, t); }
    else if (sp_eq(k, "get")) { get_addr = num(tok(&p)); get_w0 = num(tok(&p)); get_w1 = num(tok(&p)); }
    else if (sp_eq(k, "mgr")) mgr = num(tok(&p));
    else if (sp_eq(k, "field")) field_off = num(tok(&p));
    else if (sp_eq(k, "dispatch")) dispatch_addr = num(tok(&p));
    else if (sp_eq(k, "gamelit")) { gamelit_addr = num(tok(&p)); gamelit_w0 = num(tok(&p)); gamelit_w1 = num(tok(&p)); }
    else if (sp_eq(k, "slots")) {
        while ((t = tok(&p)) != 0) {
            char *v = tok(&p);
            if (!v) break;
            if (sp_eq(t, "start")) slot_start = (int)num(v);
            else if (sp_eq(t, "stop")) slot_stop = (int)num(v);
            else if (sp_eq(t, "shot")) slot_shot = (int)num(v);
            else if (sp_eq(t, "lit")) slot_lit = (int)num(v);
            else if (sp_eq(t, "active")) slot_active = (int)num(v);
            else if (sp_eq(t, "mask")) slot_mask = (int)num(v);
        }
    } else if (sp_eq(k, "award") && naward < MAXA) {
        t = tok(&p);
        if (!t) return;
        sp_copy(A[naward].name, sizeof A[naward].name, t);
        A[naward].addr = num(tok(&p));
        A[naward].w0 = num(tok(&p));
        A[naward].w1 = num(tok(&p));
        naward++;
    } else if (sp_eq(k, "watch") && nwatch < MAXW) {
        struct watch *x = &W[nwatch];
        x->id = num(tok(&p));
        t = tok(&p);
        sp_copy(x->label, sizeof x->label, t ? t : "?");
        while ((t = tok(&p)) != 0) {
            char *v = tok(&p);
            if (!v) break;
            if (sp_eq(t, "vt")) x->vt = num(v);
            else if (sp_eq(t, "pw") && x->npw < MAXV) x->pw[x->npw++] = num(v);
            else if (sp_eq(t, "w") && x->nw < MAXV) x->w[x->nw++] = num(v);
            else if (sp_eq(t, "vec")) {
                x->vec_off = num(v);
                x->vec_stride = num(tok(&p));
                x->vec_flag = num(tok(&p));
                x->vec_mask = num(tok(&p));
                x->has_vec = x->vec_stride != 0;
            }
        }
        nwatch++;
    }
}

static int read_cfg(void)
{
    static char buf[4096];
    long n = pm_read_file("/dump/stockprobe.cfg", buf, sizeof buf - 1);
    char *s, *e;
    if (n <= 0) return 0;
    buf[n] = 0;
    for (s = buf; *s; s = e) {
        for (e = s; *e && *e != '\n'; e++) ;
        if (*e) *e++ = 0;
        if (e > s + 1 && e[-2] == '\r') e[-2] = 0;
        parse_line(s);
    }
    return 1;
}

/* ---- the trampoline (the runtime's, copied: an entry hook that logs, then runs the original) */
typedef void (*hook_fn)(unsigned *regs);      /* r0..r3, ip, lr, then the caller's stack words */
static unsigned tramp[MAXA * 16] __attribute__((aligned(4096)));
static int tramp_used;

static void relocate_literal(unsigned *t, int i, unsigned addr, unsigned w)
{
    unsigned imm, at;
    if ((w & 0xFF7F0000u) != 0xE51F0000u || ((w >> 12) & 0xF) == 15) return;
    imm = w & 0xFFF;
    at = addr + (unsigned)i * 4 + 8;
    at = (w & 0x00800000u) ? at + imm : at - imm;
    t[12 + i] = rd32(at);
    t[6 + i] = 0xE59F0010u | (w & 0xF000u);
}

static int hook(unsigned addr, hook_fn logger)
{
    unsigned *p = (unsigned *)(unsigned long)addr, *t;
    int i;
    if (!addr || tramp_used >= MAXA) return 0;
    t = tramp + tramp_used++ * 16;
    t[0] = 0xe92d500fu;   /* push {r0,r1,r2,r3,ip,lr} */
    t[1] = 0xe1a0000du;   /* mov r0, sp */
    t[2] = 0xe1a00000u;   /* nop */
    t[3] = 0xe59fc014u;   /* ldr ip, [pc, #20] -> t[10] */
    t[4] = 0xe12fff3cu;   /* blx ip */
    t[5] = 0xe8bd500fu;   /* pop {r0,r1,r2,r3,ip,lr} */
    t[6] = p[0];
    t[7] = p[1];
    t[8] = 0xe59ff004u;   /* ldr pc, [pc, #4] -> t[11] */
    t[9] = 0u;
    t[10] = (unsigned)(unsigned long)logger;
    t[11] = addr + 8u;
    t[14] = p[0];         /* the original words, as the runtime keeps them */
    t[15] = p[1];
    for (i = 0; i < 2; i++) relocate_literal(t, i, addr, p[i]);
    mprotect(tramp, sizeof tramp, 7);
    mprotect((void *)(unsigned long)(addr & ~0xfffu), 0x2000, 7);
    p[1] = (unsigned)(unsigned long)t;
    p[0] = 0xe51ff004u;   /* ldr pc, [pc, #-4] */
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    __builtin___clear_cache((char *)p, (char *)(p + 2));
    return 1;
}

static void award_log(int k, unsigned *r)
{
    if (!pm_player() || award_lines >= 6000) return;
    award_lines++;
    pm_log("SP AWARD %s val %llu lr 0x%x r0 0x%x r1 0x%x r2 0x%x r3 0x%x stk 0x%x p%u", A[k].name,
           (unsigned long long)((uint64_t)r[2] | (uint64_t)r[3] << 32), r[5], r[0], r[1], r[2], r[3], r[6],
           pm_player());
}
static void award0(unsigned *r) { award_log(0, r); }
static void award1(unsigned *r) { award_log(1, r); }
static void award2(unsigned *r) { award_log(2, r); }
static void award3(unsigned *r) { award_log(3, r); }
static const hook_fn AWARD_FN[MAXA] = { award0, award1, award2, award3 };

/* ---- one rule's state ------------------------------------------------------------------------ */
static unsigned *vtab(const struct watch *x) { return (unsigned *)(unsigned long)x->vt; }

static int is_active(const struct watch *x)
{
    if (slot_active < 0) return -1;
    return (int)(((vfn1)(unsigned long)vtab(x)[slot_active])(x->obj) & 0xff);
}

static void take(const struct watch *x, struct snap *s, int want_lit)
{
    unsigned p = pm_player(), i;
    s->field = p ? rd64(x->obj + field_off + 8u * p) : 0;
    s->lit_ok = 0;
    s->lit = 0;
    if (want_lit && slot_lit >= 0) {
        s->lit = ((vfn1)(unsigned long)vtab(x)[slot_lit])(x->obj);
        s->lit_ok = 1;
    }
    for (i = 0; i < x->npw; i++) s->pw[i] = p ? rd32(x->obj + x->pw[i] + 4u * p) : 0;
    for (i = 0; i < x->nw; i++) s->w[i] = rd32(x->obj + x->w[i]);
    s->nrec = 0;
    if (x->has_vec) {
        unsigned b = rd32(x->obj + x->vec_off), e = rd32(x->obj + x->vec_off + 4), r;
        if (b && e > b && (e - b) / x->vec_stride <= 64)
            for (r = b; r + x->vec_stride <= e && s->nrec < MAXR; r += x->vec_stride, s->nrec++) {
                s->rflag[s->nrec] = *(volatile const unsigned char *)(unsigned long)(r + x->vec_flag);
                s->rmask[s->nrec] = rd64(r + x->vec_mask);
            }
    }
}

static int recs_differ(const struct snap *a, const struct snap *b)
{
    unsigned i;
    if (a->nrec != b->nrec) return 1;
    for (i = 0; i < a->nrec; i++)
        if (a->rflag[i] != b->rflag[i] || a->rmask[i] != b->rmask[i]) return 1;
    return 0;
}

/* " rec[a1:0x800000000 a1:0x200000 a0:0x0]" */
static unsigned recs_text(const struct snap *s, char *out, unsigned cap)
{
    unsigned i, n = 0;
    if (!s->nrec || cap < 16) return 0;
    n += (unsigned)pm_snprintf(out + n, cap - n, " rec[");
    for (i = 0; i < s->nrec && n + 28 < cap; i++)
        n += (unsigned)pm_snprintf(out + n, cap - n, "%sa%u:0x%llx", i ? " " : "", s->rflag[i],
                                   (unsigned long long)s->rmask[i]);
    n += (unsigned)pm_snprintf(out + n, cap - n, "]");
    return n;
}

/* "pw 0x8c:15,0x9c:40" for the words; before -> after when both are given */
static void words_text(const struct watch *x, const struct snap *a, const struct snap *b, char *out, unsigned cap)
{
    unsigned i, n = 0;
    out[0] = 0;
    for (i = 0; i < x->npw && n + 32 < cap; i++) {
        if (b && a->pw[i] != b->pw[i])
            n += (unsigned)pm_snprintf(out + n, cap - n, " pw+0x%x %u->%u", x->pw[i], a->pw[i], b->pw[i]);
        else
            n += (unsigned)pm_snprintf(out + n, cap - n, " pw+0x%x %u", x->pw[i], a->pw[i]);
    }
    for (i = 0; i < x->nw && n + 32 < cap; i++) {
        if (b && a->w[i] != b->w[i])
            n += (unsigned)pm_snprintf(out + n, cap - n, " w+0x%x %u->%u", x->w[i], a->w[i], b->w[i]);
        else
            n += (unsigned)pm_snprintf(out + n, cap - n, " w+0x%x %u", x->w[i], a->w[i]);
    }
    n += recs_text(a, out + n, cap - n);
    if (b && recs_differ(a, b)) {
        if (n + 4 < cap) n += (unsigned)pm_snprintf(out + n, cap - n, " ->");
        n += recs_text(b, out + n, cap - n);
    }
}

static struct watch *find(unsigned self)
{
    int i;
    for (i = 0; i < nwatch; i++) if (W[i].wrapped && W[i].obj == self) return &W[i];
    for (i = 0; i < nwatch; i++) if (W[i].wrapped && W[i].vt == rd32(self)) return &W[i];
    return 0;
}

/* ---- the wraps: log, call the original with every register and four stack words, log -------- */
static uint64_t w_start(unsigned r0, unsigned r1, unsigned r2, unsigned r3,
                        unsigned s0, unsigned s1, unsigned s2, unsigned s3)
{
    struct watch *x = find(r0);
    struct snap a, b;
    char words[420];
    unsigned lr = (unsigned)(unsigned long)__builtin_return_address(0);
    uint64_t ret, getter;
    take(x, &a, 0);
    ret = x->orig_start(r0, r1, r2, r3, s0, s1, s2, s3);
    take(x, &b, is_active(x) > 0);
    words_text(x, &a, &b, words, sizeof words);
    getter = slot_mask >= 0 ? ((vfn1)(unsigned long)vtab(x)[slot_mask])(x->obj) : 0;
    pm_log("SP START %u %s p%u lr 0x%x field 0x%llx -> 0x%llx (getter v[%d] 0x%x returns 0x%llx) lit %s0x%llx active %d%s",
           x->id, x->label, pm_player(), lr, (unsigned long long)a.field, (unsigned long long)b.field,
           slot_mask, slot_mask >= 0 ? vtab(x)[slot_mask] : 0, (unsigned long long)getter,
           b.lit_ok ? "" : "(not asked) ", (unsigned long long)b.lit, is_active(x), words);
    return ret;
}

static uint64_t w_stop(unsigned r0, unsigned r1, unsigned r2, unsigned r3,
                       unsigned s0, unsigned s1, unsigned s2, unsigned s3)
{
    struct watch *x = find(r0);
    struct snap a, b;
    char words[420];
    unsigned lr = (unsigned)(unsigned long)__builtin_return_address(0);
    int act = is_active(x);
    uint64_t ret;
    take(x, &a, act > 0);
    pm_log("SP STOP %u %s p%u reason %u lr 0x%x (before: field 0x%llx lit 0x%llx active %d)", x->id, x->label,
           pm_player(), r1, lr, (unsigned long long)a.field, (unsigned long long)a.lit, act);
    ret = x->orig_stop(r0, r1, r2, r3, s0, s1, s2, s3);
    take(x, &b, 0);
    words_text(x, &a, &b, words, sizeof words);
    pm_log("SP STOPPED %u %s field 0x%llx active %d%s", x->id, x->label, (unsigned long long)b.field,
           is_active(x), words);
    return ret;
}

static uint64_t w_shot(unsigned r0, unsigned r1, unsigned r2, unsigned r3,
                       unsigned s0, unsigned s1, unsigned s2, unsigned s3)
{
    struct watch *x = find(r0);
    struct snap a, b;
    char words[460];
    unsigned lr = (unsigned)(unsigned long)__builtin_return_address(0);
    uint64_t ret, shot = (uint64_t)r2 | (uint64_t)r3 << 32;
    int act;
    take(x, &a, 1);
    ret = x->orig_shot(r0, r1, r2, r3, s0, s1, s2, s3);
    act = is_active(x);
    take(x, &b, act > 0);
    words_text(x, &a, &b, words, sizeof words);
    if (shot_lines < 8000) {
        shot_lines++;
        pm_log("SP SHOT %u %s p%u shot 0x%llx x %u lr 0x%x field 0x%llx -> 0x%llx lit 0x%llx -> %s0x%llx active %d%s",
               x->id, x->label, pm_player(), (unsigned long long)shot, s0, lr,
               (unsigned long long)a.field, (unsigned long long)b.field, (unsigned long long)a.lit,
               b.lit_ok ? "" : "(inactive) ", (unsigned long long)b.lit, act, words);
    }
    return ret;
}

/* ---- setting up, from the tick ------------------------------------------------------------ */
static int words_ok(unsigned addr, unsigned w0, unsigned w1)
{
    return addr && rd32(addr) == w0 && rd32(addr + 4) == w1;
}

static void setup(void)
{
    int i, k, top;
    void *m;
    if (!words_ok(get_addr, get_w0, get_w1)) {
        pm_log("SP REFUSED: the manager's get at 0x%x does not start %08x %08x (the words there: %08x %08x)",
               get_addr, get_w0, get_w1, get_addr ? rd32(get_addr) : 0, get_addr ? rd32(get_addr + 4) : 0);
        refused = 1;
        return;
    }
    if (!mgr || !rd32(mgr)) return;                 /* the manager is not built yet: try later */
    for (i = 0; i < nwatch; i++) {
        m = ((getfn)(unsigned long)get_addr)((void *)(unsigned long)mgr, W[i].id);
        if (!m) return;                              /* not built yet */
    }
    top = slot_start > slot_stop ? slot_start : slot_stop;
    if (slot_shot > top) top = slot_shot;
    for (i = 0; i < nwatch; i++) {
        struct watch *x = &W[i];
        unsigned *vt;
        x->obj = (unsigned)(unsigned long)((getfn)(unsigned long)get_addr)((void *)(unsigned long)mgr, x->id);
        if (rd32(x->obj) != x->vt) {
            pm_log("SP watch %u %s REFUSED: its vtable is 0x%x, the config says 0x%x", x->id, x->label,
                   rd32(x->obj), x->vt);
            continue;
        }
        vt = vtab(x);
        x->orig_start = (vfn8)(unsigned long)vt[slot_start];
        x->orig_stop = (vfn8)(unsigned long)vt[slot_stop];
        x->orig_shot = (vfn8)(unsigned long)vt[slot_shot];
        mprotect((void *)(unsigned long)(x->vt & ~0xfffu), ((x->vt & 0xfffu) + 4u * (unsigned)top + 4u + 0xfffu) & ~0xfffu, 7);
        x->wrapped = 1;
        vt[slot_start] = (unsigned)(unsigned long)w_start;
        vt[slot_stop] = (unsigned)(unsigned long)w_stop;
        vt[slot_shot] = (unsigned)(unsigned long)w_shot;
        pm_log("SP watch %u %s obj 0x%x vtable 0x%x: start v[%d] 0x%x, stop v[%d] 0x%x, shot v[%d] 0x%x wrapped;"
               " lit v[%d] 0x%x, active v[%d] 0x%x called", x->id, x->label, x->obj, x->vt,
               slot_start, (unsigned)(unsigned long)x->orig_start, slot_stop, (unsigned)(unsigned long)x->orig_stop,
               slot_shot, (unsigned)(unsigned long)x->orig_shot, slot_lit, slot_lit >= 0 ? vt[slot_lit] : 0,
               slot_active, slot_active >= 0 ? vt[slot_active] : 0);
    }
    for (k = 0; k < naward; k++) {
        if (words_ok(A[k].addr, A[k].w0, A[k].w1)) A[k].hooked = hook(A[k].addr, AWARD_FN[k]);
        pm_log("SP award %s 0x%x %s", A[k].name, A[k].addr,
               A[k].hooked ? "hooked" : "NOT hooked (its first two words differ, or it is hooked already)");
    }
    if (gamelit_addr && !words_ok(gamelit_addr, gamelit_w0, gamelit_w1)) {
        pm_log("SP gamelit 0x%x NOT used (its first two words differ)", gamelit_addr);
        gamelit_addr = 0;
    }
    ready = 1;
    pm_log("SP ready on %s %s: %d rule(s) watched, field +0x%x, triggers stockprobe.start/.stop/.mark/.shot",
           pm_game(), pm_version(), nwatch, field_off);
}

static void poll(void)
{
    int i;
    unsigned j;
    for (i = 0; i < nwatch; i++) {
        struct watch *x = &W[i];
        struct snap s;
        int act, changed;
        char words[420];
        if (!x->wrapped) continue;
        act = is_active(x);
        take(x, &s, act > 0);
        changed = !x->have_last || act != x->last_active || s.field != x->last_field
                  || (act > 0 && s.lit != x->last_lit);
        for (j = 0; j < x->npw; j++) changed |= s.pw[j] != x->last_pw[j];
        for (j = 0; j < x->nw; j++) changed |= s.w[j] != x->last_w[j];
        changed |= s.nrec != x->last_nrec;
        for (j = 0; j < s.nrec && j < x->last_nrec; j++)
            changed |= s.rflag[j] != x->last_rflag[j] || s.rmask[j] != x->last_rmask[j];
        if (changed && (x->have_last || act > 0)) {
            words_text(x, &s, 0, words, sizeof words);
            pm_log("SP STATE %u %s p%u active %d lit %s0x%llx field 0x%llx%s", x->id, x->label, pm_player(), act,
                   act > 0 ? "" : "(inactive) ", (unsigned long long)s.lit, (unsigned long long)s.field, words);
        }
        x->have_last = 1;
        x->last_active = act;
        x->last_field = s.field;
        x->last_lit = s.lit;
        for (j = 0; j < x->npw; j++) x->last_pw[j] = s.pw[j];
        for (j = 0; j < x->nw; j++) x->last_w[j] = s.w[j];
        x->last_nrec = s.nrec;
        for (j = 0; j < s.nrec; j++) { x->last_rflag[j] = s.rflag[j]; x->last_rmask[j] = s.rmask[j]; }
    }
    if (gamelit_addr) {
        uint64_t g = ((vfn1)(unsigned long)gamelit_addr)(mgr);
        if (!have_gamelit || g != last_gamelit) pm_log("SP GAMELIT 0x%llx p%u", (unsigned long long)g, pm_player());
        have_gamelit = 1;
        last_gamelit = g;
    }
}

static struct watch *by_id(unsigned id)
{
    int i;
    for (i = 0; i < nwatch; i++) if (W[i].wrapped && W[i].id == id) return &W[i];
    return 0;
}

static void triggers(void)
{
    char arg[64], *p, *t;
    if (pm_trigger_text("stockprobe.mark", arg, sizeof arg)) pm_log("SP MARK %s", arg);
    if (pm_trigger_text("stockprobe.start", arg, sizeof arg)) {
        unsigned id;
        struct watch *x;
        void *m;
        p = arg;
        id = num(tok(&p));
        x = by_id(id);
        if (!pm_player() || !pm_in_game()) {
            pm_log("SP FORCE START %u refused: no player up, or no game on (player %u, in_game %d)", id,
                   pm_player(), pm_in_game());
        } else {
            m = ((getfn)(unsigned long)get_addr)((void *)(unsigned long)mgr, id);
            if (!m) {
                pm_log("SP FORCE START %u refused: the manager has no rule %u", id, id);
            } else {
                pm_log("SP FORCE START %u %s p%u: get(mgr, %u) = 0x%x, then its v[%d]", id, x ? x->label : "(not watched)",
                       pm_player(), id, (unsigned)(unsigned long)m, slot_start);
                ((vfn8)(unsigned long)((unsigned *)(unsigned long)rd32((unsigned)(unsigned long)m))[slot_start])(
                    (unsigned)(unsigned long)m, 0, 0, 0, 0, 0, 0, 0);
                pm_log("SP FORCE START %u returned", id);
            }
        }
    }
    if (pm_trigger_text("stockprobe.stop", arg, sizeof arg)) {
        unsigned id, reason;
        void *m;
        p = arg;
        id = num(tok(&p));
        t = tok(&p);
        reason = t ? num(t) : 0;
        if (!pm_player() || !pm_in_game()) {
            pm_log("SP FORCE STOP %u refused: no player up, or no game on", id);
        } else if ((m = ((getfn)(unsigned long)get_addr)((void *)(unsigned long)mgr, id)) != 0) {
            pm_log("SP FORCE STOP %u reason %u: its v[%d]", id, reason, slot_stop);
            ((vfn8)(unsigned long)((unsigned *)(unsigned long)rd32((unsigned)(unsigned long)m))[slot_stop])(
                (unsigned)(unsigned long)m, reason, 0, 0, 0, 0, 0, 0);
        }
    }
    if (pm_trigger_text("stockprobe.shot", arg, sizeof arg)) {
        uint64_t mask;
        unsigned xw;
        p = arg;
        mask = num64(tok(&p));
        t = tok(&p);
        xw = t ? num(t) : 1;
        if (!dispatch_addr || !pm_player() || !pm_in_game() || !mask) {
            pm_log("SP SYNTHETIC SHOT 0x%llx refused (no dispatch in the config, no player, or an empty mask)",
                   (unsigned long long)mask);
        } else {
            pm_log("SP SYNTHETIC SHOT 0x%llx x %u: the dispatch at 0x%x called", (unsigned long long)mask, xw, dispatch_addr);
            ((vfn8)(unsigned long)dispatch_addr)(mgr, 0, (unsigned)mask, (unsigned)(mask >> 32), xw, 0, 0, 0);
        }
    }
}

/* ---- the callbacks ------------------------------------------------------------------------------ */
static void sp_init(void)
{
    cfg_ok = read_cfg();
    if (!cfg_ok) { pm_log("SP REFUSED: no /dump/stockprobe.cfg"); refused = 1; return; }
    if ((cfg_game[0] && !sp_eq(cfg_game, pm_game())) || (cfg_version[0] && !sp_eq(cfg_version, pm_version()))) {
        pm_log("SP REFUSED: the config is for %s %s, the port for %s %s", cfg_game, cfg_version, pm_game(), pm_version());
        refused = 1;
        return;
    }
    if (slot_start < 0 || slot_stop < 0 || slot_shot < 0 || !nwatch) {
        pm_log("SP REFUSED: the config names no slots or no rules");
        refused = 1;
        return;
    }
    pm_log("SP config: %d rule(s), %d award hook(s), get 0x%x, manager 0x%x", nwatch, naward, get_addr, mgr);
}

static void sp_tick(void)
{
    ++ticks;
    if (refused) return;
    if (!ready) {
        if (ticks % 30 == 0) setup();
        return;
    }
    if (ticks % 6 == 0 && (pm_player() != last_player || pm_in_game() != last_in_game)) {
        pm_log("SP player %u -> %u, in_game %d -> %d", last_player, pm_player(), last_in_game, pm_in_game());
        last_player = pm_player();
        last_in_game = pm_in_game();
    }
    if (ticks % 6 == 0 && pm_player()) poll();
    if (ticks % 30 == 0) triggers();
}

static void sp_shot(uint64_t shot)
{
    if (ready && pm_player() && shot_lines < 8000) {
        shot_lines++;
        pm_log("SP shot 0x%llx p%u", (unsigned long long)shot, pm_player());
    }
}

static void sp_ball_end(void)
{
    if (ready) pm_log("SP ball end p%u", pm_player());
}

static void sp_event(unsigned id)     /* every event the port names (game_start, ball_start...) */
{
    const char *name = pm_event_name(id);
    if (ready) pm_log("SP event %s (0x%x) p%u in_game %d", name ? name : "?", id, pm_player(), pm_in_game());
}

static const struct pm_mode stock_probe = {
    .name = "stockprobe",
    .init = sp_init,
    .tick = sp_tick,
    .shot = sp_shot,
    .ball_end = sp_ball_end,
    .event = sp_event,
};
PM_REGISTER(stock_probe);
