/* jjpmodes.c - a custom mode inside a JJP game, from outside its binary.
 *
 * PAD-1335.  Preloaded into the game by run_game.sh (JJP_MODS_SO=...).  It
 * patches NO code: the retail binary is a Sentinel LDK Envelope whose
 * functions are ciphertext until called, but the game EXPORTS its whole C++
 * engine in .dynsym (22k names on Guns N' Roses), and every piece a mode needs
 * is either a callable function or a plain data pointer:
 *
 *   - A mode is a `Mode` object (280 bytes on GnR) built by the game's own
 *     Mode::Mode(name, id, ModeManager*, Lamp*, run_id, grace_id,
 *     grace_grace_id, Audit*, Audit*).  Its vtable is a COPY of Mode's with
 *     three virtuals replaced (start choreo, tick work, is_timer_paused).
 *     Mode::start() then runs it on the game's own proc system with the
 *     game's own timer (125 ticks a second, Mode +0x48 seconds / +0x4c
 *     ticks), grace and end - exactly as Slash Solo runs.
 *   - The trigger is a switch.  Every Switch is a global object whose +0x10
 *     is the dispatch function Switch::do_dispatches runs as a proc; we wrap
 *     that pointer (one aligned 8-byte store) and call the original first.
 *   - Points go through the mode's own Mode::score_and_total, so the game
 *     scores and totals them.
 *   - Sound is one of the game's SoundEffect globals, played by its vtable.
 *   - The banner is drawn with Allegro (a shared library the game imports)
 *     by interposing al_flip_display: draw on the backbuffer, then flip.
 *
 * Title-specific choices are environment variables so the same library runs
 * on any JJP title that shares the engine:
 *   JJP_MODS_SWITCH   trigger switch object      (switch_target_jam)
 *   JJP_MODS_SOUND    SoundEffect global          (se_FX_GnR_..._Cheers_3sec)
 *   JJP_MODS_SECONDS  mode length                 (20)
 *   JJP_MODS_POINTS   points per switch hit       (1000000)
 *   JJP_MODS_INGAME   jjpe state meaning in-game  (5)
 *   JJP_MODS_ANYSTATE=1  start even outside a game (machinery test; no score)
 * Log: /jjpe/temp/jjpmodes.log inside the jail.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* ---- log ------------------------------------------------------------------ */
static FILE *logf_;
static pthread_mutex_t log_mu = PTHREAD_MUTEX_INITIALIZER;
static void lg(const char *fmt, ...)
{
    pthread_mutex_lock(&log_mu);
    if (!logf_) {
        logf_ = fopen("/jjpe/temp/jjpmodes.log", "a");
        if (!logf_) logf_ = stderr;
    }
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    fprintf(logf_, "[jjpmodes %ld.%03ld] ", (long)ts.tv_sec, ts.tv_nsec / 1000000);
    va_list ap; va_start(ap, fmt); vfprintf(logf_, fmt, ap); va_end(ap);
    fputc('\n', logf_); fflush(logf_);
    pthread_mutex_unlock(&log_mu);
}

static const char *envs(const char *k, const char *d) { const char *v = getenv(k); return v && *v ? v : d; }
static long envl(const char *k, long d) { const char *v = getenv(k); return v && *v ? strtol(v, 0, 0) : d; }

static void *sym(const char *name)
{
    void *p = dlsym(RTLD_DEFAULT, name);
    if (!p) lg("MISSING symbol %s", name);
    return p;
}

/* ---- the game's engine, by exported name ---------------------------------- */
typedef void (*mode_ctor_t)(void *self, const char *name, int id, void *mgr, void *lamp,
                            unsigned run_id, unsigned grace_id, unsigned gg_id,
                            void *audit_a, void *audit_b);
typedef void (*swd_t)(unsigned int);
typedef int (*state_get_t)(void);
typedef void (*vfn0_t)(void *);
typedef int (*vbool_t)(void *);
typedef void (*vint_t)(void *, int);
typedef void (*vull_t)(void *, unsigned long long);

/* Mode vtable byte offsets (from the vptr), read out of GnR's _ZTV4Mode and
 * the live, decrypted Mode::start / run_proc / end. */
enum {
    VT_START = 0x10, VT_END = 0x20, VT_SET_TIME = 0x28, VT_IS_TIMER_PAUSED = 0x38,
    VT_IS_RUNNING = 0x48, VT_SCORE_AND_TOTAL = 0x88, VT_TICK_WORK = 0xa8,
    VT_START_CHOREO = 0xb0,
};
#define MODE_SECONDS_OFF 0x48     /* int: whole seconds left (run_proc) */
#define MODE_OBJ_BYTES   0x400    /* GnR Mode is 0x118; generous for other titles */
#define MODE_VT_SLOTS    64       /* copied; the real one is 24 + 2 header */

static mode_ctor_t mode_ctor;
static state_get_t state_get;
static void *switch_obj;
static swd_t orig_swd;
static void *sound_obj;

static void *our_mode;            /* the Mode object, built on first use */
static uintptr_t our_vt[MODE_VT_SLOTS + 2];

static volatile int banner_on;    /* read by the render thread */
static volatile int banner_secs;
static volatile unsigned long long banner_total;
static volatile int hits;

static inline void *vslot(void *obj, int off) { return *(void **)(*(char **)obj + off); }

static void play_sound(void)
{
    if (!sound_obj) return;
    /* SoundEffect::play is virtual on some titles (GnrSoundEffect overrides
     * it); find it in the object's own vtable, else call the base. */
    void *base = dlsym(RTLD_DEFAULT, "_ZN11SoundEffect4playEv");
    void *gnr = dlsym(RTLD_DEFAULT, "_ZN14GnrSoundEffect4playEv");
    void **vt = *(void ***)sound_obj;
    for (int i = 0; i < 24; i++) {
        if (vt[i] && (vt[i] == base || vt[i] == gnr)) {
            ((vfn0_t)vt[i])(sound_obj);
            lg("sound: played by vtable slot %d", i);
            return;
        }
    }
    if (base) { ((vfn0_t)base)(sound_obj); lg("sound: played (non-virtual)"); }
}

/* ---- our virtuals ---------------------------------------------------------- */
static void pad_start_choreo(void *self)
{
    lg("mode %p: start choreo", self);
    banner_total = 0;
    banner_on = 1;
    play_sound();
}

static void pad_tick_work(void *self, int arg)
{
    (void)arg;
    banner_secs = *(int *)((char *)self + MODE_SECONDS_OFF);
}

static int pad_is_timer_paused(void *self) { (void)self; return 0; }

static int build_mode(void)
{
    if (our_mode) return 1;
    void *mode_vt = sym("_ZTV4Mode");
    if (!mode_ctor || !mode_vt) return 0;
    our_mode = calloc(1, MODE_OBJ_BYTES);
    mode_ctor(our_mode, "PAD custom mode", 990, NULL, NULL, 0x7e00, 0x7e01, 0x7e02, NULL, NULL);
    /* The ctor set Mode's vptr; copy that table (header + slots) and replace. */
    uintptr_t *src = (uintptr_t *)mode_vt;
    memcpy(our_vt, src, sizeof our_vt);
    uintptr_t *slots = &our_vt[2];
    slots[VT_START_CHOREO / 8]   = (uintptr_t)pad_start_choreo;
    slots[VT_TICK_WORK / 8]      = (uintptr_t)pad_tick_work;
    slots[VT_IS_TIMER_PAUSED / 8] = (uintptr_t)pad_is_timer_paused;
    if (*(uintptr_t **)our_mode != src + 2)
        lg("WARN ctor vptr %p != Mode vtable %p", *(void **)our_mode, (void *)(src + 2));
    *(uintptr_t **)our_mode = slots;
    lg("built mode %p name=\"%s\" vptr=%p", our_mode, *(char **)((char *)our_mode + 8), (void *)slots);
    return 1;
}

/* ---- the trigger: our wrapper around the switch's dispatch ---------------- */
static void pad_swd(unsigned int arg)
{
    if (orig_swd) orig_swd(arg);
    int st = state_get ? state_get() : -1;
    int ingame = st == (int)envl("JJP_MODS_INGAME", 5);
    hits++;
    lg("switch hit #%d (arg %u) state=%d ingame=%d", hits, arg, st, ingame);
    if (!ingame && !envl("JJP_MODS_ANYSTATE", 0)) return;
    if (!build_mode()) return;
    int running = ((vbool_t)vslot(our_mode, VT_IS_RUNNING))(our_mode) & 0xff;
    if (!running) {
        ((vbool_t)vslot(our_mode, VT_START))(our_mode);
        ((vint_t)vslot(our_mode, VT_SET_TIME))(our_mode, (int)envl("JJP_MODS_SECONDS", 20));
        lg("mode STARTED for %ld s", envl("JJP_MODS_SECONDS", 20));
    } else if (ingame) {
        unsigned long long pts = (unsigned long long)envl("JJP_MODS_POINTS", 1000000);
        ((vull_t)vslot(our_mode, VT_SCORE_AND_TOTAL))(our_mode, pts);
        banner_total += pts;
        lg("mode SCORED %llu (mode total %llu)", pts, banner_total);
        play_sound();
    }
}

/* ---- the banner: interpose al_flip_display -------------------------------- */
typedef struct { float r, g, b, a; } ALLEGRO_COLOR;
typedef struct { float m[4][4]; } ALLEGRO_TRANSFORM;
static void (*real_flip)(void);
static void *font;
static unsigned long flips;

static void draw_banner(void)
{
    static ALLEGRO_COLOR (*map_rgba)(unsigned char, unsigned char, unsigned char, unsigned char);
    static void (*fill_rect)(float, float, float, float, ALLEGRO_COLOR);
    static void (*draw_text)(const void *, ALLEGRO_COLOR, float, float, int, const char *);
    static void *(*builtin_font)(void);
    static const ALLEGRO_TRANSFORM *(*cur_xf)(void);
    static void (*copy_xf)(ALLEGRO_TRANSFORM *, const ALLEGRO_TRANSFORM *);
    static void (*ident_xf)(ALLEGRO_TRANSFORM *);
    static void (*scale_xf)(ALLEGRO_TRANSFORM *, float, float);
    static void (*trans_xf)(ALLEGRO_TRANSFORM *, float, float);
    static void (*use_xf)(const ALLEGRO_TRANSFORM *);
    static int ready = -1;
    if (ready < 0) {
        map_rgba = dlsym(RTLD_DEFAULT, "al_map_rgba");
        fill_rect = dlsym(RTLD_DEFAULT, "al_draw_filled_rectangle");
        draw_text = dlsym(RTLD_DEFAULT, "al_draw_text");
        builtin_font = dlsym(RTLD_DEFAULT, "al_create_builtin_font");
        cur_xf = dlsym(RTLD_DEFAULT, "al_get_current_transform");
        copy_xf = dlsym(RTLD_DEFAULT, "al_copy_transform");
        ident_xf = dlsym(RTLD_DEFAULT, "al_identity_transform");
        scale_xf = dlsym(RTLD_DEFAULT, "al_scale_transform");
        trans_xf = dlsym(RTLD_DEFAULT, "al_translate_transform");
        use_xf = dlsym(RTLD_DEFAULT, "al_use_transform");
        ready = map_rgba && fill_rect && draw_text && builtin_font && cur_xf && copy_xf
                && ident_xf && scale_xf && trans_xf && use_xf;
        lg("allegro drawing api %s", ready ? "resolved" : "MISSING");
    }
    if (!ready) return;
    if (!font) font = builtin_font();
    if (!font) return;
    /* Premultiplied-alpha blending for the built-in font, or every glyph cell
     * draws as a black box; put the game's blender back afterwards. */
    static void (*get_blender)(int *, int *, int *);
    static void (*set_blender)(int, int, int);
    if (!get_blender) {
        get_blender = dlsym(RTLD_DEFAULT, "al_get_blender");
        set_blender = dlsym(RTLD_DEFAULT, "al_set_blender");
    }
    int bop = 0, bsrc = 1, bdst = 3;
    if (get_blender) get_blender(&bop, &bsrc, &bdst);
    if (set_blender) set_blender(0 /*ADD*/, 1 /*ONE*/, 3 /*INVERSE_ALPHA*/);
    ALLEGRO_TRANSFORM old, t;
    copy_xf(&old, cur_xf());
    ident_xf(&t);
    use_xf(&t);
    fill_rect(330, 600, 1030, 740, map_rgba(120, 0, 0, 230));
    ident_xf(&t); scale_xf(&t, 4, 4); trans_xf(&t, 350, 615); use_xf(&t);
    draw_text(font, map_rgba(255, 255, 255, 255), 0, 0, 0, "PAD MODE - HIT THE JAM!");
    char line[96];
    snprintf(line, sizeof line, "%2d s   %llu", banner_secs, banner_total);
    ident_xf(&t); scale_xf(&t, 4, 4); trans_xf(&t, 350, 680); use_xf(&t);
    draw_text(font, map_rgba(255, 220, 0, 255), 0, 0, 0, line);
    use_xf(&old);
    if (set_blender) set_blender(bop, bsrc, bdst);
}

void al_flip_display(void)
{
    if (!real_flip) real_flip = dlsym(RTLD_NEXT, "al_flip_display");
    if (++flips == 1) lg("al_flip_display interposed (first frame)");
    if (our_mode && banner_on) {
        int running = ((vbool_t)vslot(our_mode, VT_IS_RUNNING))(our_mode) & 0xff;
        if (running) draw_banner();
        else { banner_on = 0; lg("mode ENDED (total %llu, %d hits)", banner_total, hits); }
    }
    if (real_flip) real_flip();
}

/* ---- install --------------------------------------------------------------- */
static void *installer(void *arg)
{
    (void)arg;
    const char *swname = envs("JJP_MODS_SWITCH", "switch_target_jam");
    const char *sename = envs("JJP_MODS_SOUND", "se_FX_GnR_GenericCrowds_DifferentLengthCheers_3sec");
    /* Wait for the game's static constructors: the switch object gets its
     * dispatch pointer at +0x10 when the Switch ctor runs. */
    for (int i = 0; i < 600; i++) {
        switch_obj = dlsym(RTLD_DEFAULT, swname);
        if (switch_obj && *(void **)((char *)switch_obj + 0x10)) break;
        usleep(100000);
    }
    if (!switch_obj || !*(void **)((char *)switch_obj + 0x10)) {
        lg("FAIL: switch %s never got a dispatch function", swname);
        return NULL;
    }
    sleep(3);   /* let power-up finish before we touch anything */
    mode_ctor = (mode_ctor_t)sym("_ZN4ModeC1EPKciP11ModeManagerP4LampjjjP5AuditS7_");
    state_get = (state_get_t)sym("_Z14jjpe_state_getv");
    sound_obj = sym(sename);
    void **slot = (void **)((char *)switch_obj + 0x10);
    orig_swd = (swd_t)*slot;
    Dl_info di; const char *on = "?";
    if (dladdr((void *)orig_swd, &di) && di.dli_sname) on = di.dli_sname;
    __atomic_store_n(slot, (void *)pad_swd, __ATOMIC_SEQ_CST);
    lg("installed: %s \"%s\" dispatch %p (%s) -> pad_swd; sound %s=%p",
       swname, *(char **)((char *)switch_obj + 8), (void *)orig_swd, on, sename, sound_obj);
    return NULL;
}

__attribute__((constructor)) static void jjpmodes_init(void)
{
    /* LD_PRELOAD rides into every child the game starts (its shell scripts,
     * aplay, ...).  Only the game exports the engine; stay silent elsewhere. */
    if (!dlsym(RTLD_DEFAULT, "_Z14jjpe_state_getv")) return;
    lg("loaded into pid %d", getpid());
    pthread_t t;
    if (pthread_create(&t, NULL, installer, NULL) == 0) pthread_detach(t);
}
