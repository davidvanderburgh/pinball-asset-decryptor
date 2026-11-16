/* hook_a64.h - the runtime's hook layer on a 64-bit ARM game: Stern Spike 3 (PAD-1269).
 *
 * pad_mode_runtime.c includes this in place of its 32-bit ARM layer (words_match .. hook_call) when it is
 * built for aarch64 (build_mode.sh -a a64). The functions keep their names and what they promise, so the
 * rest of the runtime calls them unchanged:
 *
 *   hook(addr, logger)          the logger sees the registers first, then the function runs as it was
 *   hook_veto(addr, logger)     the logger returns non-zero to refuse: the caller gets x0 = 1
 *   hook_veto_n(..., n, ref)    the same, the logger told which (x1 = n), a refusal answering `ref`
 *   hook_n(addr, logger, n)     a plain hook whose logger is told which (x1 = n)
 *   hook_wrap(addr, wrapper)    the wrapper takes the function's place; the returned pointer is the original
 *   hook_call(addr, wrapper)    one `bl` wrapped where it is made; returns the call's own target
 *   done_thunk(f)               a vtable thunk: the logger sees the registers, then f runs
 *
 * HOW A SITE IS PATCHED. The game is a PIE far (gigabytes) from this object, so the trampolines live in an
 * area mapped within 128 MB of the game's code (tramp_near, at the first hook): ONE instruction at the site
 * changes, to `b <slot>`, and only that instruction moves into the slot. One aligned word is written, so a
 * thread running the function sees the old instruction or the branch, never half of each - the 32-bit layer's
 * two-word patch could not promise that. A site whose first instruction reads the pc cannot move as it is:
 * `adrp`/`adr` are rewritten as a literal load of the address they make; a b, b.cond, cbz/cbnz or tbz/tbnz is
 * re-aimed at a far jump in the slot to where it went (PAD-1271); a bl or a literal load is refused.
 *
 * THE REGISTERS A LOGGER SEES (pm_reg *r): r[0..7] = x0..x7 (the arguments), r[8] = x8 (the indirect result
 * register), r[9] = x30 (the return address), r + 10 = the caller's sp (its stack arguments). q0-q7 are saved
 * and put back too (a float argument survives the logger), and so is every other register the C logger
 * might change; x16/x17 are the slot's own (the ABI leaves them to veneers at any call). A logger may write
 * r[0..8]; the function then runs with what it wrote.
 *
 * Slot layout: SLOT_WORDS words each, the code copied from a template assembled below, its literals at the
 * end (tests read the template's offsets). */
#ifndef PM_HOOK_A64_H
#define PM_HOOK_A64_H

#define PM_REG_LR    9            /* r[PM_REG_LR] is the hooked function's return address */
#define SLOT_WORDS   64           /* 256 bytes a hook */
#define N_SLOTS      512
#define NEAR_BYTES   (SLOT_WORDS * 4 * N_SLOTS)   /* 128 KB */
#define B_RANGE      (128ul << 20)                /* a `b` reaches +-128 MB */
#define TRAMP_SPAN   (NEAR_BYTES / 4)             /* the words a thunk of ours may be in */

typedef void (*hook_fn)(pm_reg *regs);
typedef int (*veto_fn)(pm_reg *regs);
typedef int (*veto_n_fn)(pm_reg *regs, unsigned n);

extern void *mmap(void *, unsigned long, int, int, int, long);
extern int munmap(void *, unsigned long);

static unsigned *tramp;           /* the near area (0 until the first hook maps it) */
static int tramp_used;            /* slots used */
static int tramp_failed;          /* no area could be mapped near the game: every hook is refused */

/* ---- the templates ------------------------------------------------------------------------------------
 * LOGGER: save, call the logger with x0 = the saved registers (x1 = n for hook_n / a veto's n), keep its
 * answer in x17, put everything back, then either run the moved instruction and go on (x17 == 0, or a plain
 * hook), or return to the caller with x0 = the refusal (a veto). The `nop` words are patched per hook. */
__asm__(
    ".text\n"
    ".balign 16\n"
    "pm_a64_tpl:\n"
    "    sub  sp, sp, #208\n"
    "    stp  q0, q1, [sp, #0]\n"
    "    stp  q2, q3, [sp, #32]\n"
    "    stp  q4, q5, [sp, #64]\n"
    "    stp  q6, q7, [sp, #96]\n"
    "    stp  x0, x1, [sp, #128]\n"
    "    stp  x2, x3, [sp, #144]\n"
    "    stp  x4, x5, [sp, #160]\n"
    "    stp  x6, x7, [sp, #176]\n"
    "    stp  x8, x30, [sp, #192]\n"
    "    add  x0, sp, #128\n"
    "pm_a64_tpl_n:\n"
    "    mov  x1, #0\n"                    /* patched: movz x1, #n */
    "    ldr  x16, pm_a64_tpl_logger\n"
    "    blr  x16\n"
    "    mov  w17, w0\n"                  /* PAD-1271: a veto answers an int; the top half of x0 is not its */
    "    ldp  q0, q1, [sp, #0]\n"
    "    ldp  q2, q3, [sp, #32]\n"
    "    ldp  q4, q5, [sp, #64]\n"
    "    ldp  q6, q7, [sp, #96]\n"
    "    ldp  x0, x1, [sp, #128]\n"
    "    ldp  x2, x3, [sp, #144]\n"
    "    ldp  x4, x5, [sp, #160]\n"
    "    ldp  x6, x7, [sp, #176]\n"
    "    ldp  x8, x30, [sp, #192]\n"
    "    add  sp, sp, #208\n"
    "pm_a64_tpl_veto:\n"
    "    nop\n"                            /* patched for a veto: cbz x17, pm_a64_tpl_moved */
    "    nop\n"                            /* patched for a veto: movz x0, #refused */
    "    nop\n"                            /* patched for a veto: ret */
    "pm_a64_tpl_moved:\n"
    "    nop\n"                            /* the site's first instruction (or its rewrite) */
    "    ldr  x16, pm_a64_tpl_back\n"
    "    br   x16\n"
    "    .balign 8\n"
    "pm_a64_tpl_logger:\n"
    "    .quad 0\n"
    "pm_a64_tpl_back:\n"
    "    .quad 0\n"                        /* the site + 4 (a thunk: the function itself) */
    "pm_a64_tpl_lit:\n"
    "    .quad 0\n"                        /* an adrp/adr's address, loaded by the moved instruction's rewrite */
    "pm_a64_tpl_end:\n"
    /* JUMP: a far jump, the wrapper's way in (hook_wrap, hook_call) */
    "pm_a64_jmp:\n"
    "    ldr  x16, pm_a64_jmp_to\n"
    "    br   x16\n"
    "pm_a64_jmp_to:\n"
    "    .quad 0\n"
    "pm_a64_jmp_end:\n"
    ".previous\n");

/* PAD-1271: HIDDEN, so the compiler makes each label's address pc-relative (adrp + add). As plain externs it loaded
 * them from the GOT, and the assembler, the labels being local to the block above, wrote every one of those GOT
 * loads against `.text + offset`: the linker gave them all ONE GOT entry, every label read as the same address,
 * TPL_AT was 0 for each, and no slot got its template - the first hooked call ran into the literals (SIGILL). */
#pragma GCC visibility push(hidden)
extern const unsigned pm_a64_tpl[], pm_a64_tpl_n[], pm_a64_tpl_veto[], pm_a64_tpl_moved[],
    pm_a64_tpl_logger[], pm_a64_tpl_back[], pm_a64_tpl_lit[], pm_a64_tpl_end[],
    pm_a64_jmp[], pm_a64_jmp_to[], pm_a64_jmp_end[];
#pragma GCC visibility pop

#define TPL_AT(sym) ((int)((sym) - pm_a64_tpl))           /* a template label's word index */

/* ---- instructions ------------------------------------------------------------------------------------ */
/* (tests lift these verbatim) */
static int a64_is_adrp(unsigned w) { return (w & 0x9f000000u) == 0x90000000u; }
static int a64_is_adr(unsigned w)  { return (w & 0x9f000000u) == 0x10000000u; }
static int a64_is_bl(unsigned w)   { return (w & 0xfc000000u) == 0x94000000u; }
/* reads the pc in a way a literal rewrite cannot carry: b/bl, b.cond, cbz/cbnz, tbz/tbnz, a literal load */
static int a64_pc_bound(unsigned w)
{
    return (w & 0x7c000000u) == 0x14000000u          /* b, bl */
        || (w & 0xff000010u) == 0x54000000u          /* b.cond */
        || (w & 0x7e000000u) == 0x34000000u          /* cbz, cbnz */
        || (w & 0x7e000000u) == 0x36000000u          /* tbz, tbnz */
        || (w & 0x3b000000u) == 0x18000000u;         /* ldr (literal), ldrsw, prfm, the SIMD forms */
}
/* the address an adrp / adr at `at` makes */
static unsigned long a64_adr_value(unsigned long at, unsigned w)
{
    long imm = (long)(((w >> 5) & 0x7ffffu) << 2 | ((w >> 29) & 3u));
    if (imm & (1l << 20)) imm -= 1l << 21;           /* 21-bit signed */
    if (a64_is_adrp(w)) return (at & ~0xffful) + (unsigned long)(imm << 12);
    return at + (unsigned long)imm;
}
/* where a bl at `at` calls */
static unsigned long a64_bl_target(unsigned long at, unsigned w)
{
    long off = (long)(w & 0x03ffffffu);
    if (off & (1l << 25)) off -= 1l << 26;
    return at + (unsigned long)(off * 4);
}
/* `b` / `bl` from `at` to `to`, or 0 when it does not reach */
static unsigned a64_branch(unsigned long at, unsigned long to, int link)
{
    long d = (long)(to - at);
    if (d & 3 || d >= (long)B_RANGE || d < -(long)B_RANGE) return 0;
    return (link ? 0x94000000u : 0x14000000u) | ((unsigned)(d >> 2) & 0x03ffffffu);
}
/* `ldr x<rd>, <literal at `lit`>` from `at`, or 0 when it does not reach (+-1 MB) */
static unsigned a64_ldr_lit(unsigned long at, unsigned long lit, unsigned rd)
{
    long d = (long)(lit - at);
    if (d & 3 || d >= (1l << 20) || d < -(1l << 20)) return 0;
    return 0x58000000u | (((unsigned)(d >> 2) & 0x7ffffu) << 5) | (rd & 31u);
}

/* ---- the near area ----------------------------------------------------------------------------------- */
/* The game's code: the lowest and highest address of its executable mappings. */
static void game_code_span(unsigned long *lo, unsigned long *hi)
{
    int i;
    *lo = ~0ul;
    *hi = 0;
    for (i = 0; i < n_maps; i++)
        if ((maps[i].how & (MAP_X | MAP_GAME)) == (MAP_X | MAP_GAME)) {
            if (maps[i].lo < *lo) *lo = maps[i].lo;
            if (maps[i].hi > *hi) *hi = maps[i].hi;
        }
}

/* Map the area once, as close below the game's code as it will go (then above its last executable mapping), 1 MB
 * steps; MAP_FIXED_NOREPLACE never takes a page something else has. The whole of the game's code must lie within a
 * branch's reach of the whole area. */
static int near_enough(unsigned long at, unsigned long lo, unsigned long hi)
{
    unsigned long first = at < lo ? at : lo, last = at + NEAR_BYTES > hi ? at + NEAR_BYTES : hi;
    return last - first < B_RANGE;
}

static int tramp_near(void)
{
    unsigned long lo, hi, want;
    long k;
    void *got;
    if (tramp) return 1;
    if (tramp_failed) return 0;
    game_code_span(&lo, &hi);
    if (!hi) { tramp_failed = 1; say("hooks: the game's code is not in the mappings - nothing can be hooked"); return 0; }
    for (k = 0; k < 64; k++) {
        want = k < 32 ? lo - NEAR_BYTES - (unsigned long)k * 0x100000ul
                      : ((hi + 0xfffful) & ~0xfffful) + (unsigned long)(k - 32) * 0x100000ul;
        if (want > lo && k < 32) continue;                     /* wrapped below 0 */
        if (!near_enough(want, lo, hi)) continue;
        got = mmap((void *)want, NEAR_BYTES, 7, 0x22 | 0x100000, -1, 0);   /* PRIVATE|ANON|FIXED_NOREPLACE */
        if (got == (void *)-1l || !got) continue;
        if ((unsigned long)got != want) {                     /* a kernel that took it as a hint only */
            munmap(got, NEAR_BYTES);
            continue;
        }
        tramp = (unsigned *)got;
        say("hooks: 64-bit ARM - %u slots at 0x%lx, the game's code 0x%lx-0x%lx", N_SLOTS, want, lo, hi);
        return 1;
    }
    tramp_failed = 1;
    say("hooks: no room within 128 MB of the game's code (0x%lx-0x%lx) - nothing can be hooked", lo, hi);
    return 0;
}

static unsigned *slot_new(void)
{
    unsigned *t;
    int i;
    if (!tramp_near() || tramp_used >= N_SLOTS) return 0;
    t = tramp + tramp_used++ * SLOT_WORDS;
    for (i = 0; i < SLOT_WORDS; i++) t[i] = 0xd503201fu;      /* nop */
    return t;
}

static void put_quad(unsigned *t, int word, unsigned long v)
{
    t[word] = (unsigned)v;
    t[word + 1] = (unsigned)(v >> 32);
}

/* PAD-1271: where a b / b.cond / cbz / cbnz / tbz / tbnz at `at` goes when taken (0: not one of those) */
static unsigned long a64_cond_target(unsigned long at, unsigned w)
{
    long off;
    if ((w & 0xfc000000u) == 0x14000000u) {                              /* b */
        off = (long)(w & 0x03ffffffu);
        if (off & (1l << 25)) off -= 1l << 26;
    } else if ((w & 0xff000010u) == 0x54000000u || (w & 0x7e000000u) == 0x34000000u) {   /* b.cond, cbz/cbnz */
        off = (long)((w >> 5) & 0x7ffffu);
        if (off & (1l << 18)) off -= 1l << 19;
    } else if ((w & 0x7e000000u) == 0x36000000u) {                       /* tbz/tbnz */
        off = (long)((w >> 5) & 0x3fffu);
        if (off & (1l << 13)) off -= 1l << 14;
    } else
        return 0;
    return at + (unsigned long)(off * 4);
}
/* the same branch re-aimed from `at` to `to` (in the slot, a few words away), or 0 when it does not reach */
static unsigned a64_cond_retarget(unsigned long at, unsigned long to, unsigned w)
{
    long d = (long)(to - at) >> 2;
    if ((w & 0xfc000000u) == 0x14000000u) return 0x14000000u | ((unsigned)d & 0x03ffffffu);
    if ((w & 0x7e000000u) == 0x36000000u)
        return d >= -(1l << 13) && d < (1l << 13) ? (w & 0xfff8001fu) | (((unsigned)d & 0x3fffu) << 5) : 0;
    return d >= -(1l << 18) && d < (1l << 18) ? (w & 0xff00001fu) | (((unsigned)d & 0x7ffffu) << 5) : 0;
}

/* The site's instruction as it is to run from t[at]: itself, or an adrp/adr as a literal load of its address
 * (t[lit] the literal), or (PAD-1271) a b / b.cond / cbz / cbnz / tbz / tbnz re-aimed at a far jump to where it
 * went, t[lit + 2] and t[lit + 3] (`ldr x16, t[lit]; br x16`: x16 is the slot's own, as the ABI leaves it to
 * veneers): Spike 3's agent_header opens with a `cbz x0`. A bl or a literal load still cannot move: 0. */
static unsigned moved_word(unsigned long addr, unsigned w, unsigned *t, int at, int lit)
{
    unsigned long to;
    if (a64_is_adrp(w) || a64_is_adr(w)) {
        put_quad(t, lit, a64_adr_value(addr, w));
        return a64_ldr_lit((unsigned long)(t + at), (unsigned long)(t + lit), w & 31u);
    }
    if (!a64_is_bl(w) && (to = a64_cond_target(addr, w)) != 0) {
        put_quad(t, lit, to);
        t[lit + 2] = a64_ldr_lit((unsigned long)(t + lit + 2), (unsigned long)(t + lit), 16);
        t[lit + 3] = 0xd61f0200u;                                         /* br x16 */
        return t[lit + 2] ? a64_cond_retarget((unsigned long)(t + at), (unsigned long)(t + lit + 2), w) : 0;
    }
    return a64_pc_bound(w) ? 0 : w;
}

/* One word at the site, written; the page made writable for it (and left so: other hooks share pages). */
static int site_write(unsigned long addr, unsigned w)
{
    if (mprotect((void *)(addr & ~0xffful), 0x2000, 7) != 0) return 0;
    __atomic_store_n((unsigned *)addr, w, __ATOMIC_SEQ_CST);
    __builtin___clear_cache((char *)addr, (char *)(addr + 4));
    return 1;
}

/* The logger slot for `addr`, filled but not yet jumped to. back = where it goes on (addr + 4, or a thunk's f). */
static unsigned *logger_slot(unsigned long addr, void *logger, unsigned long back, int move)
{
    unsigned *t = slot_new(), w;
    int n = TPL_AT(pm_a64_tpl_end), i;
    if (!t) return 0;
    for (i = 0; i < n; i++) t[i] = pm_a64_tpl[i];
    put_quad(t, TPL_AT(pm_a64_tpl_logger), (unsigned long)logger);
    put_quad(t, TPL_AT(pm_a64_tpl_back), back);
    if (move) {
        w = moved_word(addr, *(const unsigned *)addr, t, TPL_AT(pm_a64_tpl_moved), TPL_AT(pm_a64_tpl_lit));
        if (!w) { tramp_used--; return 0; }
        t[TPL_AT(pm_a64_tpl_moved)] = w;
    }
    return t;
}

static int slot_go(unsigned long addr, unsigned *t)
{
    unsigned b = a64_branch(addr, (unsigned long)t, 0);
    __builtin___clear_cache((char *)t, (char *)(t + SLOT_WORDS));
    if (!b || !site_write(addr, b)) { tramp_used--; return 0; }
    return 1;
}

/* rule 2: the site's two words as the port has them. A site this runtime hooked already reads `b <our slot>`. */
static int words_match(struct site *x)
{
    const unsigned *p = (const unsigned *)x->addr;
    return p[0] == x->w0 && p[1] == x->w1;
}

static int hook(pm_addr addr, hook_fn logger)
{
    unsigned *t;
    if (!addr) return 0;
    t = logger_slot(addr, (void *)logger, addr + 4, 1);
    return t && slot_go(addr, t);
}

static int hook_full(pm_addr addr, hook_fn logger);   /* PAD-1327: below, after hook_callee */

static int hook_veto_at(pm_addr addr, void *logger, unsigned n, unsigned refused)
{
    unsigned *t;
    int v = TPL_AT(pm_a64_tpl_veto);
    if (!addr || n > 0xffff || refused > 0xffff) return 0;
    t = logger_slot(addr, logger, addr + 4, 1);
    if (!t) return 0;
    t[TPL_AT(pm_a64_tpl_n)] = 0xd2800001u | (n << 5);                 /* movz x1, #n */
    t[v] = 0xb4000011u | ((unsigned)(TPL_AT(pm_a64_tpl_moved) - v) << 5);   /* cbz x17, moved */
    t[v + 1] = 0xd2800000u | (refused << 5);                          /* movz x0, #refused */
    t[v + 2] = 0xd65f03c0u;                                           /* ret */
    return slot_go(addr, t);
}

static int hook_veto(pm_addr addr, veto_fn logger)
{
    return hook_veto_at(addr, (void *)logger, 0, 1);
}

static int hook_veto_n(pm_addr addr, veto_n_fn logger, unsigned n, unsigned refused)
{
    if (n > 255 || refused > 1) return 0;
    return hook_veto_at(addr, (void *)logger, n, refused);
}

/* (the 32-bit layer's hook_veto_bl, for a `push {.., lr}; bl` start, has no counterpart: a bl first is refused) */

typedef void (*hook_n_fn)(pm_reg *regs, unsigned n);
static int hook_n(pm_addr addr, hook_n_fn logger, unsigned n)
{
    unsigned *t;
    if (!addr || n > 255) return 0;
    t = logger_slot(addr, (void *)logger, addr + 4, 1);
    if (!t) return 0;
    t[TPL_AT(pm_a64_tpl_n)] = 0xd2800001u | (n << 5);                 /* movz x1, #n */
    return slot_go(addr, t);
}

/* ---- PAD-1322: a hook whose logger also sees x19..x28 ----------------------------------------------------------
 * A site INSIDE a function (Spike 3's switch drain, at the point each switch edge passes) finds what it needs in the
 * callee-saved registers - the loop's record pointer - which a plain logger cannot see. hook_callee(addr, logger) is
 * hook_n through one shared step: the slot calls pm_a64_callee (x0 = the saved registers, x1 = the logger's index),
 * which stores x19..x28 as they are (the template touches none of them), hands the C logger (r, x) with x[0..9] =
 * x19..x28, and loads them back from x, so a logger may change one. The logger runs with the rest as a plain hook's.
 * PAD-1327: hook_full (below) is the same step with the registers in one array. */
typedef void (*callee_fn)(pm_reg *regs, pm_reg *x19);
#define N_CALLEE 16
static callee_fn callee_tab[N_CALLEE];
static hook_fn full_tab[N_CALLEE];    /* PAD-1327: a hook_full logger's index (callee_tab's is 0 there) */
static int callee_used;

/* ---- PAD-1327: hook_full on 64-bit ARM ------------------------------------------------------------------------------
 * The 32-bit hook_full hands its logger r0-r12 at regs[0..12] and the hooked function's sp at regs + 14, every one
 * writable (Elvira's start menu keeps its count in r5). A 64-bit function keeps such a thing in a callee-saved register
 * (Star Wars ELG 1.10's Spike 3 start menu: the entry count in w22), so the 64-bit hook_full is hook_callee's step with
 * ONE array, by register number: a[0..8] = x0..x8, a[19..28] = x19..x28, a[30] = x30, and a[31] = the hooked function's
 * sp (FULL_SP); a[9..18] and a[29] read 0 (x9-x18 are the caller's scratch, x29 its frame). What the logger writes into
 * a[0..8] and a[19..28] is what the function then runs with. The register numbers a port names (`value
 * challenge_menu_count_reg 22`) are the machine's own on both. */
#define FULL_REG_LAST 28
#define FULL_SP(r) ((unsigned char *)(unsigned long)(r)[31])
#define HOOK_SP(r) ((unsigned char *)((r) + 10))    /* a plain hook's: the caller's sp */

static void full_call(hook_fn f, pm_reg *r, pm_reg *x)
{
    pm_reg a[32];
    unsigned k;
    for (k = 0; k < 32; k++) a[k] = 0;
    for (k = 0; k <= 8; k++) a[k] = r[k];
    for (k = 0; k < 10; k++) a[19 + k] = x[k];
    a[30] = r[PM_REG_LR];
    a[31] = (pm_reg)(unsigned long)(r + 10);
    f(a);
    for (k = 0; k <= 8; k++) r[k] = a[k];
    for (k = 0; k < 10; k++) x[k] = a[19 + k];
}

__attribute__((used, visibility("hidden"))) void pm_a64_callee_call(pm_reg *r, unsigned n, pm_reg *x)
{
    if (n >= N_CALLEE) return;
    if (full_tab[n]) full_call(full_tab[n], r, x);
    else if (callee_tab[n]) callee_tab[n](r, x);
}

__asm__(
    ".text\n"
    ".balign 16\n"
    "pm_a64_callee:\n"
    "    stp  x29, x30, [sp, #-96]!\n"
    "    stp  x19, x20, [sp, #16]\n"
    "    stp  x21, x22, [sp, #32]\n"
    "    stp  x23, x24, [sp, #48]\n"
    "    stp  x25, x26, [sp, #64]\n"
    "    stp  x27, x28, [sp, #80]\n"
    "    add  x2, sp, #16\n"
    "    bl   pm_a64_callee_call\n"
    "    ldp  x19, x20, [sp, #16]\n"
    "    ldp  x21, x22, [sp, #32]\n"
    "    ldp  x23, x24, [sp, #48]\n"
    "    ldp  x25, x26, [sp, #64]\n"
    "    ldp  x27, x28, [sp, #80]\n"
    "    ldp  x29, x30, [sp], #96\n"
    "    ret\n"
    ".previous\n");
#pragma GCC visibility push(hidden)
extern void pm_a64_callee(pm_reg *regs, unsigned n);
#pragma GCC visibility pop

static int hook_callee(pm_addr addr, callee_fn logger)
{
    int k;
    for (k = 0; k < callee_used; k++)
        if (callee_tab[k] == logger) break;
    if (k == callee_used) {
        if (callee_used == N_CALLEE) return 0;
        callee_tab[callee_used++] = logger;
    }
    return hook_n(addr, (hook_n_fn)pm_a64_callee, (unsigned)k);
}

/* PAD-1327: the logger sees (and may change) every register a function keeps across calls; see full_call above */
static int hook_full(pm_addr addr, hook_fn logger)
{
    int k;
    if (!addr || !logger) return 0;
    for (k = 0; k < callee_used; k++)
        if (full_tab[k] == logger) break;
    if (k == callee_used) {
        if (callee_used == N_CALLEE) return 0;
        full_tab[callee_used++] = logger;
    }
    return hook_n(addr, (hook_n_fn)pm_a64_callee, (unsigned)k);
}

/* A wrap: the site jumps to the wrapper (through the slot's far jump), and the slot's other half - the moved
 * instruction, then on to addr + 4 - is the original, returned for the wrapper to call. */
static void *hook_wrap_at(pm_addr addr, void *wrapper, int opens_with_push)
{
    unsigned *t, w;
    int j, i, n = TPL_AT(pm_a64_jmp_end) - TPL_AT(pm_a64_jmp);
    (void)opens_with_push;
    if (!addr || !wrapper || !(t = slot_new())) return 0;
    for (i = 0; i < n; i++) t[i] = pm_a64_jmp[i];                      /* t[0..3]: the way in */
    put_quad(t, TPL_AT(pm_a64_jmp_to) - TPL_AT(pm_a64_jmp), (unsigned long)wrapper);
    j = 8;                                                             /* t[8..]: the original */
    w = moved_word(addr, *(const unsigned *)addr, t, j, 16);
    if (!w) { tramp_used--; return 0; }
    t[j] = w;
    for (i = 0; i < n; i++) t[j + 1 + i] = pm_a64_jmp[i];
    put_quad(t, j + 1 + TPL_AT(pm_a64_jmp_to) - TPL_AT(pm_a64_jmp), addr + 4);
    if (!slot_go(addr, t)) return 0;
    return t + j;
}

static void *hook_wrap(pm_addr addr, void *wrapper)
{
    return hook_wrap_at(addr, wrapper, 1);
}

/* One call, wrapped where it is made: the `bl` at addr calls the slot's far jump to the wrapper instead (the
 * return address is the bl's own, addr + 4). Returns the call's target, for the wrapper to call; 0 = refused. */
static pm_addr hook_call(pm_addr addr, void *wrapper)
{
    unsigned *t, w, b;
    int i, n = TPL_AT(pm_a64_jmp_end) - TPL_AT(pm_a64_jmp);
    pm_addr target;
    if (!addr || !wrapper) return 0;
    w = *(const unsigned *)addr;
    if (!a64_is_bl(w) || !(t = slot_new())) return 0;
    target = a64_bl_target(addr, w);
    for (i = 0; i < n; i++) t[i] = pm_a64_jmp[i];
    put_quad(t, TPL_AT(pm_a64_jmp_to) - TPL_AT(pm_a64_jmp), (unsigned long)wrapper);
    __builtin___clear_cache((char *)t, (char *)(t + SLOT_WORDS));
    b = a64_branch(addr, (unsigned long)t, 1);
    if (!b || !site_write(addr, b)) { tramp_used--; return 0; }
    return target;
}

#endif
