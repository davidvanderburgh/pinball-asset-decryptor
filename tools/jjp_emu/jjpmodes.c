/* jjpmodes.c - the JJP mode SDK runtime: custom modes, defined as data, inside
 * any JJP game, from outside its binary.
 *
 * PAD-1335 proved one hard-coded mode on Guns N' Roses; PAD-1337 makes it the
 * SDK.  This library is preloaded into the game (the rig: run_game.sh with
 * JJP_MODS_SO; a machine: the guarded padmodes.sh hook a PAD-written install
 * ISO adds to scripts/rungame.sh).  It patches NO game code.  The retail game
 * is a Sentinel LDK Envelope whose functions are ciphertext until called, but
 * it EXPORTS its whole C++ engine in .dynsym, and everything a mode needs is a
 * callable function or a plain data pointer:
 *
 *   mode     one engine `Mode` per definition, built by the game's own
 *            Mode::Mode and run by Mode::start on the game's proc system and
 *            timer.  Its vtable is a copy of Mode's with four virtuals of ours
 *            (start choreo, tick work, is_timer_paused, total choreo).  Slots
 *            are found by ADDRESS in _ZTV4Mode, never by a fixed offset: the
 *            compiler folded several empty virtuals into one body, so equal
 *            addresses are told apart by declaration order.
 *   shots    every named Switch is a global whose +0x10 is the dispatch the
 *            game runs as a proc; we wrap that pointer (one aligned store) and
 *            call the game's dispatch first.  The game never loses a switch.
 *   points   Mode::score_and_total: the game scores, totals and draws them.
 *   sounds   SoundEffect globals (se_*), played through their own vtable.
 *   lamps    one LampBuffer of our own, above the game's mode layers and
 *            below its award / attract layers, built by the game's own
 *            LampBuffer::LampBuffer; our lamps are lp_* / ls_* globals set
 *            with Lamp::set and handed back with Lamp::transparent.
 *   screen   drawn on the backbuffer before the real al_flip_display, with
 *            the GAME's own fonts (JJPEFont globals, font_*) through the
 *            game's own font_plot_outline_shadow - the look of its own modes.
 *   hold     (PAD-1348, the default) while a custom mode runs, the game's
 *            mode and multiball starts are refused: the start and restart
 *            slots of every Mode / MultiballRule class (found by the game's
 *            typeinfo) point at a gate (see "run alone" below).
 *   yield    a custom mode never starts while a game mode or a multiball
 *            runs, and pauses (timer held, shots ignored, screen hidden) when
 *            one starts under it (a mode the game starts past the gate, or
 *            with game_modes = pause) - unless its file says otherwise.  The game's
 *            modes are found by scanning the game's own symbols for objects
 *            whose vtable carries Mode::is_running; modes already running at
 *            ball start (a title's always-on modes) do not count.
 *
 * Definitions: JJP_MODS_DIR (default: the "modes" folder beside this library)
 * holds title.cfg (title-wide defaults) and one <name>.mode per mode, both
 * `key = value` lines (MODES.md beside this file documents every key).
 * Log: /jjpe/temp/jjpmodes.log.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <execinfo.h>
#include <signal.h>
#include <sys/ucontext.h>
#include <dlfcn.h>
#include <elf.h>
#include <link.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stddef.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define SDK_VERSION "3"
#include "modes/sdk/jjp_mode.h"     /* PAD-1384: a mode's own C++ (code = <name>) */

/* ---- log ------------------------------------------------------------------ */
static FILE *logf_;
static pthread_mutex_t log_mu = PTHREAD_MUTEX_INITIALIZER;
static void lg(const char *fmt, ...)
{
    pthread_mutex_lock(&log_mu);
    if (!logf_) {
        const char *p = getenv("JJP_MODS_LOG");
        logf_ = fopen(p && *p ? p : "/jjpe/temp/jjpmodes.log", "a");
        if (!logf_) logf_ = stderr;
    }
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    fprintf(logf_, "[jjpmodes %ld.%03ld] ", (long)ts.tv_sec, ts.tv_nsec / 1000000);
    va_list ap; va_start(ap, fmt); vfprintf(logf_, fmt, ap); va_end(ap);
    fputc('\n', logf_); fflush(logf_);
    pthread_mutex_unlock(&log_mu);
}

static long now_ms(void)
{
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

static void *sym(const char *name) { return name && *name ? dlsym(RTLD_DEFAULT, name) : NULL; }
static void *need(const char *name)
{
    void *p = sym(name);
    if (!p) lg("MISSING engine symbol %s", name);
    return p;
}

/* ---- the game's engine, by exported name ---------------------------------- */
typedef void (*mode_ctor_t)(void *self, const char *name, int id, void *mgr, void *lamp,
                            unsigned run_id, unsigned grace_id, unsigned gg_id,
                            void *audit_a, void *audit_b);
typedef void (*swd_t)(unsigned int);
typedef int (*int_fn_t)(void);
typedef void (*vfn0_t)(void *);
typedef int (*vbool_t)(void *);
typedef void (*vint_t)(void *, int);
typedef void (*vull_t)(void *, unsigned long long);
typedef struct { float r, g, b, a; } ALLEGRO_COLOR;
typedef struct { float m[4][4]; } ALLEGRO_TRANSFORM;
typedef void (*lb_ctor_t)(void *self, int prio, void (*fn)(void *), const char *name, int flags);
typedef void (*lamp_set_t)(void *lamp, void *lb, unsigned char r, unsigned char g,
                           unsigned char b, unsigned char a);
typedef void (*lamp_tr_t)(void *lamp, void *lb);
typedef void *(*jfont_t)(void *jjpefont);
typedef void (*plot_os_t)(const void *font, ALLEGRO_COLOR c, ALLEGRO_COLOR outline, int ow,
                          ALLEGRO_COLOR shadow, int so, float x, float y, int flags, const char *t);

static mode_ctor_t mode_ctor;
static int_fn_t state_get, balls_in_play;
static int ingame_state = 5;
static int ingame_explicit;            /* title.cfg set ingame_state */
static int ingame_learned;             /* ...or the runtime learned it (learn_ingame) */
static int (*ball_flag)(void);         /* game_flow_get_ball_in_play: 0 in attract, 1 with a ball in play */

/* Mode vtable slot byte offsets (from the vptr), found at install. */
static int VT_START = -1, VT_END = -1, VT_SET_TIME = -1, VT_IS_RUNNING = -1,
           VT_SCORE = -1, VT_TIMER_PAUSED = -1, VT_TICK = -1, VT_START_CHOREO = -1,
           VT_TOTAL_CHOREO = -1;
static int mode_seconds_off = 0x48;   /* int, whole seconds left; checked at first start */
#define MODE_OBJ_BYTES 0x1000         /* GnR's Mode is 0x118; room for any title */
#define MODE_VT_SLOTS  64
static uintptr_t *mode_vt;            /* _ZTV4Mode */
static uintptr_t our_vt[MODE_VT_SLOTS + 2];

static inline void *vslot(void *obj, int off) { return *(void **)(*(char **)obj + off); }

/* PAD-1365: JJP's first engine generation (The Wizard of Oz 08.02) has no
 * Mode class; its modes are plain functions run on procs (twister_mode_start,
 * twister_mode_proc_run ...).  There a custom mode runs as the engine's
 * Mode::start does it, read off Wonka 03.03's decrypted Mode code, but with
 * our own function as the run proc: proc_cret(id, fn, survive 0) (=
 * proc_create flag 2), one proc_sleep(1) a tick at 125 ticks a second, the
 * seconds counted by us, points through score_add_to_player_up(points, false)
 * (Mode::score_and_total's own call).  The ball end kills it as it kills every
 * proc without a survive flag; proc_id_exists says so.  Every name is the
 * same mangled engine function on both generations (same sizes too), so the
 * path is proven on Wonka with JJP_MODS_ENGINE=proc. */
static int engine_proc;                /* 1: modes run on procs of ours (no Mode class, or JJP_MODS_ENGINE=proc) */
static unsigned (*p_cret)(unsigned, void (*)(unsigned), int);
static unsigned (*p_create)(unsigned, void (*)(unsigned), int, int);
static void (*p_sleep)(unsigned);
static int (*p_exists)(unsigned);
static unsigned long long (*score_up)(unsigned long long, int);
#define PROC_TICKS 125                 /* Mode::run_proc: 0x7d ticks of proc_sleep(1) to the second */

/* ---- definitions ----------------------------------------------------------- */
#define MAX_MODES 24
#define MAX_LIST  24
#define MAX_SW    96
#define POLICY_PAUSE 0
#define POLICY_END 1
#define POLICY_IGNORE 2
#define POLICY_HOLD 3     /* PAD-1348, the default: the game's starts are refused while ours runs */
#define MAX_GAME_MODES 256

/* PAD-1354: start rules from the game's own hook lists.  Each start_on word is
 * one Hook<...>::list the game runs at that moment; our node on it raises the
 * start (see "start rules" below). */
static const struct { const char *word, *hook; } EVENTS[] = {
    { "ball_start", "HookBallStart_" }, { "first_ball", "HookFirstBall_" }, { "last_ball", "HookLastBall_" },
    { "valid_playfield", "HookValidPlayfield_" }, { "ball_saved", "HookBallSave_" },
    { "extra_ball", "HookExtraBallAwarded_" }, { "multiball_end", "HookMultiballEnd_" },
};
#define NEVENTS ((int)(sizeof EVENTS / sizeof *EVENTS))
#define ONCE_NO 0
#define ONCE_BALL 1
#define ONCE_GAME 2

typedef struct {
    char file[64], name[48], title[64];
    int nstart, start_sw[MAX_LIST], start_count;
    unsigned start_on;                    /* bit i = EVENTS[i] (PAD-1354) */
    char after[512];                      /* start_after: " name name " game mode globals / classes, or any */
    unsigned char after_sel[MAX_GAME_MODES];
    long long start_score;                /* the player up's score reaching it starts the mode */
    int ncombo, combo_sw[MAX_LIST], combo_ms;
    int count_reset_ball, start_once;     /* start_count_reset = ball; start_once = ONCE_* */
    int nshot, shot_sw[MAX_LIST];
    long long points, complete_points;
    int seconds, complete;
    void *snd_start, *snd_shot, *snd_end, *snd_complete;
    char snd_names[4][96];
    int nlamp; void *lamp[MAX_LIST];
    unsigned lamp_rgb; int lamp_blink;
    void *font_title, *font_value, *font_timer;
    unsigned title_rgba, value_rgba, timer_rgba, panel_rgba;
    int game_modes, panel;     /* panel: 0 middle, 1 bottom, 2 top, 3 none */
    int hold_multiballs;       /* with game_modes = hold: refuse the game's multiball starts too (default yes) */
    char allow[1024];          /* allow_game_modes: " name name " the game may still start while ours holds */
    /* own media (PAD-1352): files in the mode folder */
    unsigned char own_snd[4];  /* sound_* names a file of ours, not a game se_* */
    int sound_kind;            /* the game channel our sound files play on (se_type_t: 2 fanfare...) */
    char sound_like[96], music_like[96];   /* a game se_* to copy instead of the channel's first */
    char music_file[160];
    void *music;               /* our music: a game SoundEffect on the music channel, our sample */
    char pic_file[160]; float pic_at[4]; void *pic_bmp; int pic_w, pic_h; int pic_failed;
    char vid_file[160]; float vid_at[4]; int vid_loop;
    struct video *vid;
    /* balls (PAD-1353), all through the engine's one ball saver (see "balls") */
    int mb_balls, mb_save;     /* multiball = <balls in play> [ball save s]; 0 = no multiball */
    int nmb_on, mb_on_sw[MAX_LIST];    /* multiball_on: the balls come at the first hit, not at the start */
    int nadd, add_sw[MAX_LIST], add_max;   /* add_ball = <switches> [times] */
    int ball_save;             /* ball_save = <s>, a mode without a multiball */
    int no_clock;              /* seconds = 0 on a multiball: one ball left ends it, no timer */
    /* coils (PAD-1353): an index into wcs[], -1 = none */
    int coil_start, coil_shot, coil_complete, coil_start_ms, coil_shot_ms, coil_complete_ms;
    int coil_hold, coil_hold_ms, coil_hold_power;
    int hold_on;               /* coil_hold_on: 0 = the scoring shots, 1 = the start, 2 = its own switches */
    int nhold_sw, hold_sw[MAX_LIST];
    /* runtime */
    void *mode;
    int count, hits, secs, paused, ended_logged;
    const char *volatile want_end;     /* an end asked for outside a proc, done in the mode's own tick */
    long long total;
    int running_seen;
    int mb_served, mb_seen2, adds, saver_ours;
    long mb_served_at, one_ball_since;
    int saver_cs;              /* the saver's time left (1/100 s) just after our last request */
    int combo_pos; long combo_t;          /* combo: how far along, and when the last step was */
    const char *pending;                  /* a start raised by a rule, waiting for a free moment in this ball */
    long pending_log;
    unsigned score_done;                  /* start_score: bit p = player p already started it this game */
    int runs_ball, runs_game;
    /* the proc engine (PAD-1365): our own run proc, our own clock */
    unsigned pid;                         /* its proc id */
    volatile int p_on, p_seen;            /* running; the proc has run once */
    long p_at;                            /* ms clock it was created */
    /* its own C++ (PAD-1384): code = <name> -> <name>.so in the mode folder */
    char code[64];
    const struct jm_mode *cm;
    int ncl; struct { void *o; unsigned rgb; int blink; } cl[MAX_LIST];   /* lamps its code lit */
    char ctitle[64];                      /* jm_title: the panel's title this run */
    long started_at, code_tick_at;
    const char *end_why;                  /* why it is ending (for the code's end()) */
    unsigned short sw_hits[MAX_SW];       /* each switch's hits this run */
} pm_t;

static pm_t pms[MAX_MODES];
static int npm;
static void code_started(pm_t *m), code_tick(pm_t *m), code_over(pm_t *m, const char *why);   /* PAD-1384 */
static int load_code(pm_t *m);

typedef struct { char name[96]; void *obj; void *orig; } wsw_t;
static wsw_t wsw[MAX_SW];
static int nwsw;

static char moddir[512];
static int background_explicit;                 /* title.cfg named them */
static char game_name[64];                      /* title.cfg `game`: GAMENAME these modes are for */
static char background_names[1024];

/* ---- config parsing -------------------------------------------------------- */
static char *trim(char *s)
{
    while (*s == ' ' || *s == '\t') s++;
    char *e = s + strlen(s);
    while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r' || e[-1] == '\n')) *--e = 0;
    return s;
}

/* Own number parsers: glibc 2.38+ headers send atoi/strtol to __isoc23_strtol
 * under _GNU_SOURCE, which the image's glibc (Ubuntu 21.10) does not have. */
static long long num(const char *v)
{
    long long x = 0; int neg = 0;
    while (*v == ' ') v++;
    if (*v == '-') { neg = 1; v++; }
    for (; *v; v++) {
        if (*v >= '0' && *v <= '9') x = x * 10 + (*v - '0');
        else if (*v == ',' || *v == '_') continue;
        else break;
    }
    return neg ? -x : x;
}
static unsigned long hexnum(const char *v)
{
    unsigned long x = 0;
    for (; *v; v++) {
        int c = *v, d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10
                      : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (d < 0) break;
        x = x * 16 + (unsigned)d;
    }
    return x;
}

static unsigned parse_rgba(const char *v, unsigned dflt)
{
    if (!v || !*v) return dflt;
    if (*v == '#') v++;
    size_t n = strlen(v);
    unsigned long x = hexnum(v);
    if (n == 6) return (unsigned)((x << 8) | 0xff);
    if (n == 8) return (unsigned)x;
    return dflt;
}

/* "12.5" (own parser, as num(): no libc number calls the image's glibc may lack) */
static float fnum(const char **pv)
{
    const char *v = *pv; float x = 0, f = 0.1f; int neg = 0;
    while (*v == ' ' || *v == '	' || *v == ',') v++;
    if (*v == '-') { neg = 1; v++; }
    for (; *v >= '0' && *v <= '9'; v++) x = x * 10 + (float)(*v - '0');
    if (*v == '.') for (v++; *v >= '0' && *v <= '9'; v++, f /= 10) x += (float)(*v - '0') * f;
    if (*v == '%') v++;
    *pv = v;
    return neg ? -x : x;
}

/* `x y w h`, percent of the screen; a bad box leaves the default. */
static void parse_box(const char *v, float *out)
{
    float b[4]; const char *p = v;
    for (int i = 0; i < 4; i++) { const char *q = p; b[i] = fnum(&p); if (p == q) return; }
    if (b[2] <= 0 || b[3] <= 0) return;
    memcpy(out, b, sizeof b);
}

/* A sound value that names a file of ours (by its extension) rather than a game se_*. */
static int is_media_file(const char *v, const char *const *exts)
{
    const char *dot = strrchr(v, '.');
    if (!dot || strchr(dot, '/')) return 0;
    for (; *exts; exts++) if (!strcasecmp(dot + 1, *exts)) return 1;
    return 0;
}
static const char *const SOUND_EXTS[] = { "wav", "ogg", "flac", "opus", NULL };

/* se_type_t, the game's sound channels (read off Wonka 03.03: music/ (.ogg) are 1,
 * fanfare/ 2, speech/ 3 and 4, fx/ 5, loops 6 - the engine's, shared by every title). */
static int sound_kind_of(const char *v)
{
    return !strcmp(v, "music") ? 1 : !strcmp(v, "fanfare") ? 2 : !strcmp(v, "speech") ? 3
         : !strcmp(v, "fx") || !strcmp(v, "effects") ? 5 : 2;
}

static int sw_index(const char *name)
{
    for (int i = 0; i < nwsw; i++) if (!strcmp(wsw[i].name, name)) return i;
    if (nwsw >= MAX_SW) { lg("too many shots (max %d): %s ignored", MAX_SW, name); return -1; }
    void *o = sym(name);
    if (!o) { lg("no switch called %s in this game", name); return -1; }
    snprintf(wsw[nwsw].name, sizeof wsw[nwsw].name, "%s", name);
    wsw[nwsw].obj = o;
    return nwsw++;
}

static int parse_switches(char *v, int *out)
{
    int n = 0;
    for (char *t = strtok(v, " ,\t"); t && n < MAX_LIST; t = strtok(NULL, " ,\t")) {
        int i = sw_index(t);
        if (i >= 0) out[n++] = i;
    }
    return n;
}

static int lamp_like(void *o);

/* ---- coils (PAD-1353): which a mode may touch, decided here, never by the file ----
 * A JJP coil is a named `Coil` global (coil_magnet_1, coil_vuk_tv...) in the
 * engine's coil_table: +0x08 its label, +0x10 the pulse ms the game built it
 * with, +0x28 what it is doing (0 off, 3 a pulse, 4 a duty-cycled hold for
 * +0x30 ms, 2 a duty-cycled hold with no end), +0x3c the hold's 32-step on/off
 * pattern.  A hold of ours is always the timed kind (state 4), so the engine
 * ends it by itself; the watchdog below ends it sooner when it should, and at
 * its time at the latest.  The lists are
 * by name, as JJP names its coils on every title, and jjpport.py carries the
 * same lists (tests hold the two together). */
static const char *const COIL_NEVER[] = {      /* the game's own ball handling and flippers */
    "flipper", "trough", "autolaunch", "auto_launch", "autoplunge", "plunger", "sling", "jet", "bumper",
    "stepper", "relay", "power", "ticket", "null", "motor", NULL };
static const char *const COIL_ANYWAY[] = {     /* ...except these, whatever else the name says */
    "shaker", NULL };
static const char *const COIL_HOLDABLE[] = {   /* built to stay on: magnets, diverters, posts, lights */
    "magnet", "divert", "post", "gate", "shaker", "flash", "lamp", "light", "led", NULL };
#define COIL_PULSE_GAP_MS   250     /* between two pulses of one coil */
#define COIL_PULSES_A_MIN   20      /* per coil */
#define COIL_PULSE_MAX_MS   1000    /* and never longer than the game's own pulse for it */
#define COIL_HOLD_MIN_MS    100
#define COIL_HOLD_MAX_MS    5000    /* Spike 2's longest magnet grab (PAD-381) */
#define COIL_HOLD_COOL_MS   3000    /* off at least this long between holds */
#define COIL_HOLDS_A_MIN    6
#define COIL_HOLD_POWER_MAX 16      /* of 32: at most half on */
#define COIL_OBJ_STATE 0x28
#define COIL_OBJ_PATTERN 0x3c
#define MAX_COILS 32

static int name_has(const char *n, const char *const *list)
{
    for (int i = 0; list[i]; i++) if (strstr(n, list[i])) return 1;
    return 0;
}

typedef struct {
    char name[64]; void *obj; int cap_ms; unsigned char pulse_ok, hold_ok;
    long last_pulse, win_at; int win_n;
    volatile int holding; void *owner; long held_at, until, hold_end, hwin_at; int hwin_n; unsigned pattern;
} wc_t;
static wc_t wcs[MAX_COILS];
static int nwc;
static int coil_holds_on;           /* title.cfg coil_holds = on: holds wait for a machine check */
static volatile int coil_watch_up;  /* the watchdog that ends every hold is running */

static int coil_index(const char *name)
{
    for (int i = 0; i < nwc; i++) if (!strcmp(wcs[i].name, name)) return i;
    if (strncmp(name, "coil_", 5)) { lg("%s is not a coil name (coil_...)", name); return -1; }
    if (nwc >= MAX_COILS) { lg("too many coils (max %d): %s ignored", MAX_COILS, name); return -1; }
    if (!sym(name)) { lg("no coil called %s in this game", name); return -1; }
    snprintf(wcs[nwc].name, sizeof wcs[nwc].name, "%s", name);
    wcs[nwc].pulse_ok = !name_has(name, COIL_NEVER) || name_has(name, COIL_ANYWAY);
    wcs[nwc].hold_ok = wcs[nwc].pulse_ok && name_has(name, COIL_HOLDABLE);
    if (!wcs[nwc].pulse_ok) lg("%s is one of the game's own ball, flipper or power coils: a mode may not fire it", name);
    return nwc++;
}

/* "<coil> [ms]" -> index, ms (0 = the coil's own pulse) */
static int parse_coil(char *v, int *ms)
{
    char *t = strtok(v, " ,\t"), *a = strtok(NULL, " ,\t");
    *ms = a ? (int)num(a) : 0;
    return t ? coil_index(t) : -1;
}

static int parse_lamps(char *v, void **out)
{
    int n = 0;
    for (char *t = strtok(v, " ,\t"); t && n < MAX_LIST; t = strtok(NULL, " ,\t")) {
        void *o = sym(t);
        if (!o) { lg("no lamp called %s in this game", t); continue; }
        out[n++] = o;
    }
    return n;
}

/* `key = value` lines (# and ; comment lines, a trailing ' #' comment) -> fn. */
static int read_kv(const char *path, void (*fn)(void *ctx, const char *k, char *v), void *ctx)
{
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char line[1200];
    while (fgets(line, sizeof line, f)) {
        char *s = trim(line);
        if (!*s || *s == '#' || *s == ';') continue;
        char *eq = strchr(s, '=');
        if (!eq) continue;
        *eq = 0;
        char *k = trim(s), *v = trim(eq + 1);
        char *hash = strstr(v, " #");               /* trailing comment */
        if (hash) { *hash = 0; v = trim(v); }
        fn(ctx, k, v);
    }
    fclose(f);
    return 1;
}

static void apply_kv(pm_t *m, const char *k, char *v)
{
    char buf[1024]; snprintf(buf, sizeof buf, "%s", v);
    if (!strcmp(k, "name")) snprintf(m->name, sizeof m->name, "%s", v);
    else if (!strcmp(k, "title")) snprintf(m->title, sizeof m->title, "%s", v);
    else if (!strcmp(k, "start")) m->nstart = parse_switches(buf, m->start_sw);
    else if (!strcmp(k, "start_count")) m->start_count = (int)num(v);
    else if (!strcmp(k, "shots")) m->nshot = parse_switches(buf, m->shot_sw);
    else if (!strcmp(k, "points")) m->points = num(v);
    else if (!strcmp(k, "seconds")) m->seconds = (int)num(v);
    else if (!strcmp(k, "complete")) m->complete = (int)num(v);
    else if (!strcmp(k, "complete_points")) m->complete_points = num(v);
    else if (!strcmp(k, "sound_start") || !strcmp(k, "sound_shot") || !strcmp(k, "sound_end")
             || !strcmp(k, "sound_complete")) {
        int i = k[6] == 's' && k[7] == 't' ? 0 : k[6] == 's' ? 1 : k[6] == 'e' ? 2 : 3;
        snprintf(m->snd_names[i], 96, "%s", v);
        m->own_snd[i] = (unsigned char)is_media_file(v, SOUND_EXTS);
    }
    else if (!strcmp(k, "sound_channel")) m->sound_kind = sound_kind_of(v);
    else if (!strcmp(k, "sound_like")) snprintf(m->sound_like, sizeof m->sound_like, "%s", v);
    else if (!strcmp(k, "music_like")) snprintf(m->music_like, sizeof m->music_like, "%s", v);
    else if (!strcmp(k, "music")) snprintf(m->music_file, sizeof m->music_file, "%s", v);
    else if (!strcmp(k, "picture")) snprintf(m->pic_file, sizeof m->pic_file, "%s", v);
    else if (!strcmp(k, "picture_at")) parse_box(v, m->pic_at);
    else if (!strcmp(k, "video")) snprintf(m->vid_file, sizeof m->vid_file, "%s", v);
    else if (!strcmp(k, "video_at")) parse_box(v, m->vid_at);
    else if (!strcmp(k, "video_loop"))
        m->vid_loop = !(!strcmp(v, "no") || !strcmp(v, "0") || !strcmp(v, "off") || !strcmp(v, "false"));
    else if (!strcmp(k, "lamps")) m->nlamp = parse_lamps(buf, m->lamp);
    else if (!strcmp(k, "lamp_color")) m->lamp_rgb = parse_rgba(v, 0xffffffff) >> 8;
    else if (!strcmp(k, "lamp_blink")) m->lamp_blink = (int)num(v);
    else if (!strcmp(k, "font_title")) m->font_title = sym(v);
    else if (!strcmp(k, "font_value")) m->font_value = sym(v);
    else if (!strcmp(k, "font_timer")) m->font_timer = sym(v);
    else if (!strcmp(k, "title_color")) m->title_rgba = parse_rgba(v, m->title_rgba);
    else if (!strcmp(k, "value_color")) m->value_rgba = parse_rgba(v, m->value_rgba);
    else if (!strcmp(k, "timer_color")) m->timer_rgba = parse_rgba(v, m->timer_rgba);
    else if (!strcmp(k, "panel_color")) m->panel_rgba = parse_rgba(v, m->panel_rgba);
    else if (!strcmp(k, "game_modes"))
        m->game_modes = !strcmp(v, "end") ? POLICY_END : !strcmp(v, "ignore") ? POLICY_IGNORE
                      : !strcmp(v, "pause") ? POLICY_PAUSE : POLICY_HOLD;
    else if (!strcmp(k, "hold_multiballs"))
        m->hold_multiballs = !(!strcmp(v, "no") || !strcmp(v, "0") || !strcmp(v, "off") || !strcmp(v, "false"));
    else if (!strcmp(k, "allow_game_modes")) {
        char *o = m->allow; size_t room = sizeof m->allow; o[0] = ' '; o[1] = 0;
        for (char *t = strtok(buf, " ,	"); t; t = strtok(NULL, " ,	")) {
            size_t L = strlen(o);
            if (L + strlen(t) + 2 < room) snprintf(o + L, room - L, "%s ", t);
        }
    }
    else if (!strcmp(k, "multiball")) {            /* <balls in play> [ball save s] */
        char *a = strtok(buf, " ,\t"), *b = strtok(NULL, " ,\t");
        m->mb_balls = a ? (int)num(a) : 0; m->mb_save = b ? (int)num(b) : 10;
        if (m->mb_balls && (m->mb_balls < 2 || m->mb_balls > 6)) {
            lg("%s: multiball %d: 2-6 balls; %d used", m->file, m->mb_balls, m->mb_balls < 2 ? 2 : 6);
            m->mb_balls = m->mb_balls < 2 ? 2 : 6;
        }
        if (m->mb_save < 0) m->mb_save = 0;
        if (m->mb_save > 120) m->mb_save = 120;
    }
    else if (!strcmp(k, "multiball_on")) m->nmb_on = parse_switches(buf, m->mb_on_sw);
    else if (!strcmp(k, "add_ball")) {             /* <switches> [times] */
        char *last = strrchr(buf, ' ');
        m->add_max = 1;
        if (last && last[1] >= '0' && last[1] <= '9') { m->add_max = (int)num(last + 1); *last = 0; }
        if (m->add_max < 1) m->add_max = 1;
        if (m->add_max > 6) m->add_max = 6;
        m->nadd = parse_switches(buf, m->add_sw);
    }
    else if (!strcmp(k, "ball_save")) {
        m->ball_save = (int)num(v);
        if (m->ball_save < 0) m->ball_save = 0;
        if (m->ball_save > 120) m->ball_save = 120;
    }
    else if (!strcmp(k, "coil_start")) m->coil_start = parse_coil(buf, &m->coil_start_ms);
    else if (!strcmp(k, "coil_shot")) m->coil_shot = parse_coil(buf, &m->coil_shot_ms);
    else if (!strcmp(k, "coil_complete")) m->coil_complete = parse_coil(buf, &m->coil_complete_ms);
    else if (!strcmp(k, "coil_hold")) {            /* <coil> <ms> [power of 32] */
        char *c = strtok(buf, " ,\t"), *a = strtok(NULL, " ,\t"), *p = strtok(NULL, " ,\t");
        m->coil_hold = c ? coil_index(c) : -1;
        m->coil_hold_ms = a ? (int)num(a) : 1000;
        m->coil_hold_power = p ? (int)num(p) : 8;
        if (m->coil_hold >= 0 && !wcs[m->coil_hold].hold_ok) {
            lg("%s: %s is not a coil built to stay on (a magnet, diverter, post, gate, shaker or light): no hold",
               m->file, wcs[m->coil_hold].name);
            m->coil_hold = -1;
        }
    }
    else if (!strcmp(k, "coil_hold_on")) {
        if (!strcmp(v, "start")) m->hold_on = 1;
        else if (!strcmp(v, "shots")) m->hold_on = 0;
        else { m->hold_on = 2; m->nhold_sw = parse_switches(buf, m->hold_sw); }
    }
    else if (!strcmp(k, "coil_holds")) coil_holds_on = !strcmp(v, "on") || !strcmp(v, "yes");
    else if (!strcmp(k, "start_on")) {
        m->start_on = 0;
        for (char *t = strtok(buf, " ,\t"); t; t = strtok(NULL, " ,\t")) {
            int e = 0;
            while (e < NEVENTS && strcmp(EVENTS[e].word, t)) e++;
            if (e < NEVENTS) m->start_on |= 1u << e;
            else lg("%s: start_on %s is not a start event (ignored)", m->file, t);
        }
    }
    else if (!strcmp(k, "start_after")) {
        char *o = m->after; size_t room = sizeof m->after; o[0] = ' '; o[1] = 0;
        for (char *t = strtok(buf, " ,\t"); t; t = strtok(NULL, " ,\t")) {
            size_t L = strlen(o);
            if (L + strlen(t) + 2 < room) snprintf(o + L, room - L, "%s ", t);
        }
    }
    else if (!strcmp(k, "start_score")) m->start_score = num(v);
    else if (!strcmp(k, "start_combo")) m->ncombo = parse_switches(buf, m->combo_sw);
    else if (!strcmp(k, "combo_seconds")) m->combo_ms = (int)(num(v) * 1000);
    else if (!strcmp(k, "start_count_reset")) m->count_reset_ball = !strcmp(v, "ball");
    else if (!strcmp(k, "start_once"))
        m->start_once = !strcmp(v, "ball") ? ONCE_BALL : !strcmp(v, "game") ? ONCE_GAME : ONCE_NO;
    else if (!strcmp(k, "panel")) m->panel = !strcmp(v, "bottom") ? 1 : !strcmp(v, "top") ? 2 : !strcmp(v, "none") ? 3 : 0;
    else if (!strcmp(k, "code")) snprintf(m->code, sizeof m->code, "%s", v);
    else if (!strcmp(k, "ingame_state")) { ingame_state = (int)num(v); ingame_explicit = 1; }
    else if (!strcmp(k, "game")) snprintf(game_name, sizeof game_name, "%s", v);
    else if (!strcmp(k, "background_modes")) {
        background_explicit = 1;
        snprintf(background_names, sizeof background_names, " %s ", v);
    } else lg("%s: unknown key %s (ignored)", m->file, k);
}

static void mode_kv(void *m, const char *k, char *v) { apply_kv((pm_t *)m, k, v); }
static int load_file(pm_t *m, const char *path) { return read_kv(path, mode_kv, m); }

static void defaults(pm_t *m)
{
    memset(m, 0, sizeof *m);
    m->start_count = 1; m->points = 1000000; m->seconds = 20;
    m->lamp_rgb = 0xffffff; m->lamp_blink = 4;
    m->title_rgba = 0xffffffff; m->value_rgba = 0xffdc00ff; m->timer_rgba = 0xffffffff;
    m->panel_rgba = 0x000000b0;
    m->game_modes = POLICY_HOLD; m->hold_multiballs = 1;
    m->sound_kind = 2;                                   /* fanfare: what the game's own mode sounds are */
    m->pic_at[2] = m->pic_at[3] = 100; m->vid_at[2] = m->vid_at[3] = 100;   /* the whole screen */
    m->vid_loop = 1;
    m->coil_start = m->coil_shot = m->coil_complete = m->coil_hold = -1;
    m->coil_hold_ms = 1000; m->coil_hold_power = 8; m->add_max = 1;
    m->combo_ms = 5000;
}

/* ---- .stock files: the game's own modes, changed (PAD-1351; see below) ----- */
#define MAX_STOCK 32
#define MAX_SHOT_IDS 256
#define MAX_SHOT_FNS 192
#define NEED_TIMER 1
#define NEED_POINTS 2
#define NEED_SHOTS 4

typedef struct {
    uintptr_t vt;
    uintptr_t orig_run, orig_score, orig_isr[3];
    uintptr_t sd_lo, sd_hi;            /* the class's own shot_dispatch */
    int wired;                          /* NEED_* slots wrapped */
} sc_t;

typedef struct {
    char file[64], mode[96];
    int seconds;                        /* 0 = the game's own */
    long long points;                   /* 0 = the game's own */
    long points_x;                      /* thousandths; 1000 = the game's own */
    char off_names[512];
    int noff, off[MAX_LIST];
    int nadd, add_sw[MAX_LIST], add_shot[MAX_LIST];
    char add_name[MAX_LIST][48];
    /* runtime */
    void *obj; sc_t *c; int ok;
    int was_running, nscores, blocked, added;
    long started_ms; long long asked, scored;
} st_t;

static st_t sts[MAX_STOCK]; static int nst;
static sc_t scs[MAX_STOCK]; static int nsc;
static volatile int stock_ready;
static int VT_RUN = -1, VT_ISR[3] = { -1, -1, -1 };
static int (*get_shot)(void);
static void (*set_shot_fn)(int);
static unsigned (*proc_handle)(void);
static void (*proc_setarg)(unsigned, int, long);
static int shot_arg = -1;
typedef struct { int id; char name[48]; } shot_t;
static shot_t shots[MAX_SHOT_IDS]; static int nshots;

/* "2" -> 2000, "1.5" -> 1500, "0.25" -> 250 (thousandths; own parser, see num) */
static long milli(const char *v)
{
    long whole = 0, frac = 0, scale = 1000;
    while (*v == ' ') v++;
    for (; *v >= '0' && *v <= '9'; v++) whole = whole * 10 + (*v - '0');
    if (*v == '.')
        for (v++; *v >= '0' && *v <= '9' && scale > 1; v++) { scale /= 10; frac += (*v - '0') * scale; }
    return whole * 1000 + frac;
}

static void apply_stock_kv(st_t *s, const char *k, char *v)
{
    if (!strcmp(k, "mode")) snprintf(s->mode, sizeof s->mode, "%s", v);
    else if (!strcmp(k, "seconds")) s->seconds = (int)num(v);
    else if (!strcmp(k, "points")) s->points = num(v);
    else if (!strcmp(k, "points_x")) s->points_x = milli(v);
    else if (!strcmp(k, "shots_off")) snprintf(s->off_names, sizeof s->off_names, "%s", v);
    else if (!strcmp(k, "shots_add")) {
        /* switch:shot pairs.  The switch is wrapped at install with the rest,
         * so it is registered now; the shot is named once the table is read. */
        char buf[1024]; snprintf(buf, sizeof buf, "%s", v);
        for (char *t = strtok(buf, " ,\t"); t && s->nadd < MAX_LIST; t = strtok(NULL, " ,\t")) {
            char *colon = strchr(t, ':');
            if (!colon || colon == t || !colon[1]) { lg("%s: shots_add wants switch:shot, not %s", s->file, t); continue; }
            *colon = 0;
            int si = sw_index(t);
            if (si < 0) continue;
            s->add_sw[s->nadd] = si;
            snprintf(s->add_name[s->nadd], sizeof s->add_name[0], "%s", colon + 1);
            s->add_shot[s->nadd++] = -1;
        }
    } else lg("%s: unknown key %s (ignored)", s->file, k);
}

static void stock_kv(void *s, const char *k, char *v) { apply_stock_kv((st_t *)s, k, v); }

static int cmp_names(const void *a, const void *b) { return strcmp(*(char *const *)a, *(char *const *)b); }

static void load_modes(void)
{
    pm_t base; defaults(&base);
    char path[700];
    snprintf(base.file, sizeof base.file, "title.cfg");
    snprintf(path, sizeof path, "%s/title.cfg", moddir);
    if (load_file(&base, path)) lg("title defaults from %s", path);
    /* A mode ISO made from a multi-boot ISO hooks root A's rungame.sh, which
     * also starts image 1's game: modes written for one title stay out of
     * another. */
    const char *gn = getenv("GAMENAME");
    if (*game_name && gn && *gn && strcmp(gn, game_name)) {
        lg("these modes are for %s; this game is %s - not loading them", game_name, gn);
        return;
    }
    DIR *d = opendir(moddir);
    if (!d) { lg("no mode folder %s", moddir); return; }
    char *names[MAX_MODES * 2]; int nn = 0;
    char *snames[MAX_STOCK]; int nsn = 0;
    struct dirent *de;
    while ((de = readdir(d)) && nn < MAX_MODES * 2) {
        size_t L = strlen(de->d_name);
        if (L > 5 && !strcmp(de->d_name + L - 5, ".mode")) names[nn++] = strdup(de->d_name);
        else if (L > 6 && !strcmp(de->d_name + L - 6, ".stock") && nsn < MAX_STOCK) snames[nsn++] = strdup(de->d_name);
    }
    closedir(d);
    /* the game's own modes, changed (PAD-1351): one .stock file each */
    qsort(snames, nsn, sizeof *snames, cmp_names);
    for (int i = 0; i < nsn; i++) {
        st_t *s = &sts[nst];
        memset(s, 0, sizeof *s); s->points_x = 1000;
        snprintf(s->file, sizeof s->file, "%s", snames[i]);
        snprintf(path, sizeof path, "%s/%s", moddir, snames[i]);
        read_kv(path, stock_kv, s);
        free(snames[i]);
        if (!*s->mode) { lg("%s: no mode = <the game's mode>; file skipped", s->file); continue; }
        lg("stock %d %s: %s, seconds %d, points %lld, points_x %ld/1000, shots_off [%s], %d added",
           nst, s->file, s->mode, s->seconds, s->points, s->points_x, s->off_names, s->nadd);
        nst++;
    }
    qsort(names, nn, sizeof *names, cmp_names);
    for (int i = 0; i < nn; i++) {
        if (npm >= MAX_MODES) { lg("more than %d modes; %s and after ignored", MAX_MODES, names[i]); break; }
        pm_t *m = &pms[npm];
        *m = base;
        snprintf(m->file, sizeof m->file, "%s", names[i]);
        snprintf(path, sizeof path, "%s/%s", moddir, names[i]);
        load_file(m, path);
        if (!*m->name) { snprintf(m->name, sizeof m->name, "%.*s", (int)strlen(names[i]) - 5, names[i]); }
        if (!*m->title) memcpy(m->title, m->name, sizeof m->name);   /* name[48] fits title[64] */
        if (!m->nshot) { m->nshot = m->nstart; memcpy(m->shot_sw, m->start_sw, sizeof m->shot_sw); }
        for (int s = 0; s < 4; s++) {
            void **slot = s == 0 ? &m->snd_start : s == 1 ? &m->snd_shot : s == 2 ? &m->snd_end : &m->snd_complete;
            if (m->own_snd[s]) { *slot = NULL; continue; }     /* a file of ours: made once the game's sounds are in (media_loader) */
            *slot = sym(m->snd_names[s]);
            if (*m->snd_names[s] && !*slot) lg("%s: no sound called %s in this game", m->file, m->snd_names[s]);
        }
        if (*m->code && !load_code(m)) { lg("%s: mode skipped (its code)", m->file); continue; }
        if (!m->nstart && !m->start_on && !m->after[1] && m->start_score <= 0 && m->ncombo < 2 && !(m->cm && m->cm->idle)) {
            lg("%s: no start rule (start, start_on, start_after, start_score, start_combo or its code's idle); mode skipped", m->file);
            continue;
        }
        /* seconds = 0 on a multiball: no clock, one ball left ends it (Spike 2's item 167) */
        if (m->seconds < 1 && m->mb_balls) { m->no_clock = 1; m->seconds = 600; }
        if (m->seconds < 1) m->seconds = 1;
        if (m->nmb_on && !m->mb_balls) { lg("%s: multiball_on without a multiball line: ignored", m->file); m->nmb_on = 0; }
        if (m->nmb_on && m->no_clock) { lg("%s: multiball_on needs seconds (the time to hit it); 30 used", m->file); m->no_clock = 0; m->seconds = 30; }
        if (m->mb_balls || m->ball_save || m->nadd)
            lg("%s: balls: multiball %d%s (ball save %d s), add a ball on %d switch(es) up to %d, ball save %d s",
               m->file, m->mb_balls, m->nmb_on ? " on its switch" : m->mb_balls ? " at the start" : "", m->mb_save,
               m->nadd, m->add_max, m->ball_save);
        if (m->coil_start >= 0 || m->coil_shot >= 0 || m->coil_complete >= 0 || m->coil_hold >= 0)
            lg("%s: coils: start %s, shot %s, complete %s, hold %s %d ms at %d/32 on %s", m->file,
               m->coil_start >= 0 ? wcs[m->coil_start].name : "-", m->coil_shot >= 0 ? wcs[m->coil_shot].name : "-",
               m->coil_complete >= 0 ? wcs[m->coil_complete].name : "-", m->coil_hold >= 0 ? wcs[m->coil_hold].name : "-",
               m->coil_hold_ms, m->coil_hold_power, m->hold_on == 1 ? "the start" : m->hold_on == 2 ? "its switches" : "every shot");
        lg("mode %d \"%s\" (%s): %d start shot(s) x%d, %d scoring, %lld a shot, %d s, complete %d (+%lld), "
           "%d lamp(s), game modes=%s%s%s%s%s%s%s%s",
           npm, m->name, m->file, m->nstart, m->start_count, m->nshot, m->points, m->seconds, m->complete,
           m->complete_points, m->nlamp,
           m->game_modes == POLICY_END ? "end" : m->game_modes == POLICY_IGNORE ? "ignore"
           : m->game_modes == POLICY_PAUSE ? "pause" : "hold",
           m->game_modes == POLICY_HOLD ? (m->hold_multiballs ? " (multiballs too)" : " (not multiballs)") : "",
           m->game_modes == POLICY_HOLD && m->allow[1] ? ", allowed:" : "",
           m->game_modes == POLICY_HOLD && m->allow[1] ? m->allow : "",
           *m->music_file ? ", music " : "", m->music_file, *m->pic_file ? ", picture " : "", m->pic_file);
        if (*m->vid_file) lg("mode %d \"%s\": video %s (%s)", npm, m->name, m->vid_file, m->vid_loop ? "loops" : "plays once");
        if (m->start_on || m->after[1] || m->start_score > 0 || m->ncombo >= 2) {
            char ev[256]; size_t o = 0; ev[0] = 0;
            for (int e = 0; e < NEVENTS; e++)
                if (m->start_on & (1u << e)) o += snprintf(ev + o, sizeof ev - o, " %s", EVENTS[e].word);
            lg("  \"%s\" starts also on:%s%s%s%s%s%s", m->name, ev, m->after[1] ? " after" : "",
               m->after[1] ? m->after : "", m->start_score > 0 ? " score" : "",
               m->ncombo >= 2 ? " combo" : "", m->start_once ? (m->start_once == ONCE_BALL ? " (once a ball)" : " (once a game)") : "");
        }
        npm++;
    }
    for (int i = 0; i < nn; i++) free(names[i]);
}

/* ---- the game's own modes (for yielding) ----------------------------------- */
static void *gmodes[MAX_GAME_MODES];
static const char *gmode_sym[MAX_GAME_MODES];
static unsigned char gmode_bg[MAX_GAME_MODES];
static int ngm;
/* PAD-1365, the proc engine: a game mode is a proc whose entry is one of the
 * game's exported mode functions (gmode_isproc: gmodes[i] is that function).
 * It runs while more procs run it than ran it two seconds into the ball (one
 * function can run several modes: Wonka's Mode::start_run_func runs all). */
static unsigned char gmode_isproc[MAX_GAME_MODES];
static int gmode_bgn[MAX_GAME_MODES];

/* Walk the main program's dynamic symbol table in memory (DT_HASH nchain is
 * the count, as jjpelf.py reads it).  cb gets every defined object symbol. */
static void walk_dynsym_type(int type, void (*cb)(const char *name, uintptr_t addr, size_t size));
static void walk_dynsym(void (*cb)(const char *name, uintptr_t addr, size_t size))
{
    walk_dynsym_type(STT_OBJECT, cb);
}
static void walk_dynsym_type(int type, void (*cb)(const char *name, uintptr_t addr, size_t size))
{
    struct link_map *lm = dlopen(NULL, RTLD_NOW | RTLD_NOLOAD);
    if (!lm) return;
    ElfW(Sym) *symtab = NULL; const char *strtab = NULL; uint32_t *hash = NULL;
    for (ElfW(Dyn) *d = lm->l_ld; d->d_tag != DT_NULL; d++) {
        if (d->d_tag == DT_SYMTAB) symtab = (ElfW(Sym) *)(d->d_un.d_ptr);
        else if (d->d_tag == DT_STRTAB) strtab = (const char *)(d->d_un.d_ptr);
        else if (d->d_tag == DT_HASH) hash = (uint32_t *)(d->d_un.d_ptr);
    }
    if (!symtab || !strtab || !hash) { lg("dynsym walk: no DT_SYMTAB/STRTAB/HASH"); return; }
    uint32_t n = hash[1];
    for (uint32_t i = 1; i < n; i++) {
        ElfW(Sym) *s = &symtab[i];
        if (ELF64_ST_TYPE(s->st_info) != type || !s->st_value || s->st_shndx == SHN_UNDEF) continue;
        cb(strtab + s->st_name, (uintptr_t)s->st_value + lm->l_addr, s->st_size);
    }
}

#define MAX_MODE_VTS 512
static uintptr_t mode_vts[MAX_MODE_VTS]; static int nmvt;
static uintptr_t is_running_fn;
static void cb_vtables(const char *name, uintptr_t a, size_t sz)
{
    if (strncmp(name, "_ZTV", 4) || nmvt >= MAX_MODE_VTS || sz < 32) return;
    uintptr_t *v = (uintptr_t *)a;
    size_t n = sz / 8; if (n > 40) n = 40;
    for (size_t i = 2; i < n; i++) if (v[i] == is_running_fn) { mode_vts[nmvt++] = a + 16; return; }
}
static void cb_modes(const char *name, uintptr_t a, size_t sz)
{
    if (sz < 0x60 || ngm >= MAX_GAME_MODES || !strncmp(name, "_ZT", 3)) return;
    uintptr_t w = *(uintptr_t *)a;
    for (int i = 0; i < nmvt; i++)
        if (w == mode_vts[i]) { gmode_sym[ngm] = name; gmodes[ngm++] = (void *)a; return; }
}

static void find_game_modes(void)
{
    is_running_fn = (uintptr_t)sym("_ZN4Mode10is_runningEv");
    if (!is_running_fn) return;
    walk_dynsym(cb_vtables);
    walk_dynsym(cb_modes);
    for (int i = 0; i < ngm; i++)
        if (background_explicit) {
            char k[160]; snprintf(k, sizeof k, " %s ", gmode_sym[i]);
            gmode_bg[i] = strstr(background_names, k) != NULL;
        }
    lg("game modes: %d Mode classes, %d live modes%s", nmvt, ngm,
       background_explicit ? " (always-on ones named by title.cfg)" : "");
}

static int is_ours(void *o) { for (int i = 0; i < npm; i++) if (pms[i].mode == o) return 1; return 0; }

/* ---- the game's procs (PAD-1365) -------------------------------------------
 * The engine keeps its procs in a list whose head is not exported.  Read off
 * Wonka 03.03's decrypted proc_id_exists (the same function, same size, on
 * The Wizard of Oz 08.02):
 *     mov  MUTEX(%rip),%rdi ; call al_lock_mutex ; mov HEAD(%rip),%rax
 *     ... node {proc *, next}: mov (%rax),%rdx ; cmp ID(%rdx),%ebx
 *     testb $0x10,FLAGS(%rdx)          (a proc on its way out)
 * and proc_create's `mov %rsi,%r13` ... `mov %r13,FN(%rbx)` (the entry
 * function, stored twice: 0x1b8 and 0x1e8 on Wonka).  Everything is read off
 * the code at install; a title whose code differs gets no proc yields (logged). */
static void *call_import(const unsigned char *c);
static void **plist_head, **plist_mutex;
static int poff_id = -1, poff_flags = -1, poff_fn[2] = { -1, -1 };
static void (*al_lock_)(void *), (*al_unlock_)(void *);
static int plist_ok;
static int learn_proc_list(void)
{
    const unsigned char *c = sym("_Z14proc_id_existsj"), *pc = sym("_Z11proc_createjPFvjE18proc_create_flag_t14proc_survive_t");
    al_lock_ = (void (*)(void *))sym("al_lock_mutex"); al_unlock_ = (void (*)(void *))sym("al_unlock_mutex");
    if (!c || !pc || !p_exists || !al_lock_ || !al_unlock_) { lg("procs: proc_id_exists/proc_create/al_lock_mutex missing"); return 0; }
    p_exists(0);                         /* decrypt it (it returns at once for id 0) */
    for (int i = 0; i < 0x40 && !plist_head; i++)
        if (c[i] == 0x48 && c[i + 1] == 0x8b && c[i + 2] == 0x3d && c[i + 7] == 0xe8
            && c[i + 12] == 0x48 && c[i + 13] == 0x8b && c[i + 14] == 0x05) {
            void *lock = call_import(c + i + 7);
            if (lock != (void *)al_lock_) { lg("procs: proc_id_exists locks through %p, not al_lock_mutex", lock); return 0; }
            int32_t d1, d2; memcpy(&d1, c + i + 3, 4); memcpy(&d2, c + i + 15, 4);
            plist_mutex = (void **)(c + i + 7 + d1);
            plist_head = (void **)(c + i + 19 + d2);
        }
    for (int i = 0; i < 0x80 && plist_head; i++) {
        if (poff_id < 0 && c[i] == 0x3b && c[i + 1] == 0x9a) memcpy(&poff_id, c + i + 2, 4);
        if (poff_flags < 0 && c[i] == 0xf6 && c[i + 1] == 0x82 && c[i + 6] == 0x10) memcpy(&poff_flags, c + i + 2, 4);
    }
    int nf = 0, r13 = 0;
    for (int i = 0; i < 0x500 && nf < 2; i++) {
        if (pc[i] == 0x49 && pc[i + 1] == 0x89 && pc[i + 2] == 0xf5) r13 = 1;
        if (r13 && pc[i] == 0x4c && pc[i + 1] == 0x89 && pc[i + 2] == 0xab) memcpy(&poff_fn[nf++], pc + i + 3, 4);
    }
    plist_ok = plist_head && poff_id > 0 && poff_flags > 0 && poff_fn[0] > 0 && poff_id < 0x1000 && poff_flags < 0x1000
               && poff_fn[0] < 0x1000 && poff_fn[1] < 0x1000;
    lg("procs: list %s (head %p, lock %p; id +%#x, flags +%#x, entry +%#x/+%#x)", plist_ok ? "read" : "NOT READ",
       (void *)plist_head, (void *)plist_mutex, poff_id, poff_flags, poff_fn[0], poff_fn[1]);
    return plist_ok;
}

/* How many live procs run each game-mode function, cached for 20 ms. */
static int pcount[MAX_GAME_MODES];
static long pcount_at = -1000;
static pthread_mutex_t pcount_mu = PTHREAD_MUTEX_INITIALIZER;
static void proc_counts(void)
{
    long t = now_ms();
    if (!plist_ok || t - pcount_at < 20) return;
    pthread_mutex_lock(&pcount_mu);
    if (t - pcount_at >= 20) {
        int n[MAX_GAME_MODES]; memset(n, 0, sizeof n);
        void *mx = *plist_mutex;
        if (mx) al_lock_(mx);
        int k = 0;
        for (void **node = (void **)*plist_head; node && k < 4096; node = (void **)node[1], k++) {
            char *p = (char *)node[0];
            if (!p || (*(unsigned *)(p + poff_flags) & 0x30)) continue;    /* 0x10 dying, 0x20 being made */
            uintptr_t f0 = *(uintptr_t *)(p + poff_fn[0]), f1 = poff_fn[1] > 0 ? *(uintptr_t *)(p + poff_fn[1]) : f0;
            for (int i = 0; i < ngm; i++)
                if (gmode_isproc[i] && ((uintptr_t)gmodes[i] == f1 || (uintptr_t)gmodes[i] == f0)) { n[i]++; break; }
        }
        if (mx) al_unlock_(mx);
        memcpy(pcount, n, sizeof pcount);
        pcount_at = t;
    }
    pthread_mutex_unlock(&pcount_mu);
}

static int gm_running(int i)
{
    if (gmode_isproc[i]) { proc_counts(); return pcount[i] > gmode_bgn[i]; }
    void *o = gmodes[i];
    if (*(uintptr_t *)o == 0) return 0;
    return ((vbool_t)vslot(o, VT_IS_RUNNING))(o) & 0xff;
}

/* `_Z<n>NAMEj` -> NAME, `_ZN<n>A<n>BEj` -> A::B (a function of one unsigned), else NULL. */
static const char *demangle_proc_fn(const char *n, char *out, size_t cap)
{
    size_t L = strlen(n);
    if (L < 5 || strncmp(n, "_Z", 2) || n[L - 1] != 'j') return NULL;
    const char *p = n + 2; size_t o = 0; int nested = 0;
    if (*p == 'N') { nested = 1; p++; }
    for (;;) {
        if (*p < '1' || *p > '9') break;
        long k = 0; const char *e = p;
        while (*e >= '0' && *e <= '9' && k < 100000) k = k * 10 + (*e++ - '0');
        if (k <= 0 || (size_t)k > strlen(e) || o + (size_t)k + 3 >= cap) return NULL;
        if (o) { out[o++] = ':'; out[o++] = ':'; }
        memcpy(out + o, e, (size_t)k); o += (size_t)k; out[o] = 0;
        p = e + k;
        if (!nested) break;
    }
    if (!o) return NULL;
    if (nested) { if (strcmp(p, "Ej")) return NULL; }
    else if (strcmp(p, "j")) return NULL;
    return out;
}
/* The game's mode functions, by exported name: a function of the proc's
 * unsigned argument (`_Z<n>NAMEj`, or a member `_ZN...Ej`) that is
 *   - named for a mode ("mode" in it: twister_mode_proc_run, Mode::start_run_func),
 *   - or named like Mode's own procs: <x>_run_proc, <x>_grace_proc,
 *     <x>_grace_grace_proc (The Wizard of Oz 08.02: ecmb_, haunted_, sotr_,
 *     rescue_mb_, witch_melt_, fireball_frenzy_, hurry_build_ ...),
 *   - or a proc <x>_proc with a kill function of its own, <x>_proc_kill_func
 *     (mmf_proc, mml_proc, mmm_proc, mmw_proc, tnplh_proc, cbm_proc ...).
 * Not: attract, kill, test, diagnostic, menu, timer, lamp effect (leff),
 * lamp, tilt, music, match, choreography and hook functions (Wonka's
 * WonkaBarAwardModes::timer_run_proc runs on to the ball's end after its mode
 * ended).  jjpport.py proc_modes is the twin. */
static const char *const PROC_MODE_NOT[] = { "amode", "attract", "kill", "jukebox", "timer", "test", "diag", "menu",
                                              "leff", "_lef", "lamp", "tilt", "music", "match", "hook_", "multiled",
                                              "choreo", NULL };
static int ends_with(const char *s, const char *t) { size_t a = strlen(s), b = strlen(t); return a >= b && !strcmp(s + a - b, t); }
static void cb_proc_modes(const char *name, uintptr_t a, size_t sz)
{
    (void)sz;
    char d[160];
    if (ngm >= MAX_GAME_MODES || !demangle_proc_fn(name, d, sizeof d)) return;
    char low[160]; size_t i = 0;
    for (; d[i] && i < sizeof low - 1; i++) low[i] = (char)((d[i] >= 'A' && d[i] <= 'Z') ? d[i] + 32 : d[i]);
    low[i] = 0;
    for (int k = 0; PROC_MODE_NOT[k]; k++) if (strstr(low, PROC_MODE_NOT[k])) return;
    int is = strstr(low, "mode") || ends_with(low, "run_proc") || ends_with(low, "grace_proc")
             || ends_with(low, "proc_run") || ends_with(low, "proc_grace") || ends_with(low, "proc_grace_grace");
    if (!is && ends_with(low, "_proc") && !strchr(d, ':')) {
        char kf[200]; snprintf(kf, sizeof kf, "_Z%zu%s_kill_funcj", strlen(d) + 10, d);
        is = sym(kf) != NULL;
    }
    if (!is) return;
    gmode_sym[ngm] = strdup(d); gmodes[ngm] = (void *)a; gmode_isproc[ngm] = 1; ngm++;
}
static void find_proc_modes(void)
{
    walk_dynsym_type(STT_FUNC, cb_proc_modes);
    for (int i = 0; i < ngm; i++)
        if (background_explicit) {
            char k[160]; snprintf(k, sizeof k, " %s ", gmode_sym[i]);
            gmode_bg[i] = strstr(background_names, k) != NULL;
        }
    int ok = learn_proc_list();
    char names[1024]; size_t o = 0; names[0] = 0;
    for (int i = 0; i < ngm && o < sizeof names - 80; i++) o += snprintf(names + o, sizeof names - o, " %s", gmode_sym[i]);
    lg("game modes: %d mode function(s) run as procs%s:%s", ngm, ok ? "" : " (NOT watched: the proc list was not read)", names);
}

/* What a custom mode would be yielding to right now, or NULL. */
static long multiball_since;     /* ms clock when more than one ball came into play, 0 = not */
static const char *game_busy_except(const pm_t *m)
{
    /* A multiball is more than one ball for half a second: the count blips
     * (GnR read 6 for one frame while a ball sat in the shooter lane).  The
     * balls a mode of ours asked for (PAD-1353) are its own, not the game's. */
    if (multiball_since && now_ms() - multiball_since >= 500 && !(m && (m->mb_served || m->adds))) return "multiball";
    for (int i = 0; i < ngm; i++)
        if (!gmode_bg[i] && !is_ours(gmodes[i]) && gm_running(i)) return gmode_sym[i];
    return NULL;
}
static const char *game_busy(void) { return game_busy_except(NULL); }

/* Log every change in which game modes run: the evidence for a title's
 * always-on modes, and for every yield. */
static void log_running_set(void)
{
    static char last[2048];
    char now[2048]; size_t o = 0; now[0] = 0;
    for (int i = 0; i < ngm && o < sizeof now - 64; i++)
        if (!is_ours(gmodes[i]) && gm_running(i))
            o += snprintf(now + o, sizeof now - o, "%s%s%s", o ? " " : "", gmode_sym[i], gmode_bg[i] ? "(bg)" : "");
    if (strcmp(now, last)) { lg("game modes running: [%s]", now); snprintf(last, sizeof last, "%s", now); }
}

/* ---- run alone: the game's starts held off while ours runs (PAD-1348) ------
 * The repo's rule for custom modes (Spike 2, PAD-363): while one of ours runs,
 * no game mode, award mode or multiball starts.  On JJP every one of those is
 * an object of a class derived from the engine's Mode (modes, award modes,
 * hurry-ups) or MultiballRule (multiballs), and each class's start is a
 * virtual: the slot Mode::start / MultiballRule::start fills in that base's
 * vtable.  The classes are found by the game's own exported typeinfo (each
 * vtable's word 1, walked up its base chain), never by name, so a title's
 * own classes come with it.  Each class's start slot is pointed at gate_start
 * (data only: the vtables are relocated read-only data, made writable for the
 * one store); the gate refuses the start (returns false, which the game's
 * callers read as "did not start") while a mode of ours holds, and otherwise
 * calls the class's own start as before.  A start the gate never sees (a call
 * the compiler made direct) still meets the old safety net: ours pauses for
 * it, as with game_modes = pause, and the log says it got through. */
#define MAX_HELD_VTS 1024
typedef struct { uintptr_t vt; uintptr_t orig, orig_re; unsigned char mb; unsigned refused; long last_log; } hvt_t;
static hvt_t hvts[MAX_HELD_VTS];
static int nhvt, hvt_modes, hvt_mbs;
static uintptr_t ti_mode, ti_mbr, si_ti_vt, vmi_ti_vt;
static int mb_start_slot = -1;           /* byte offset of MultiballRule::start from the vptr */
static int mode_re_slot = -1, mb_re_slot = -1;   /* ...and of each base's restart: a mode can come back through it */
static uintptr_t mode_start_fn;          /* Mode::start: our own modes' vtable keeps it */
static int hold_wanted;                  /* a loaded mode says game_modes = hold */
static volatile int installed;
static int running(pm_t *m);

static int derives(uintptr_t ti, uintptr_t base, int depth)
{
    if (!ti || depth > 12) return 0;
    if (ti == base) return 1;
    uintptr_t tv = *(uintptr_t *)ti;
    if (si_ti_vt && tv == si_ti_vt) return derives(*(uintptr_t *)(ti + 16), base, depth + 1);
    if (vmi_ti_vt && tv == vmi_ti_vt) {
        unsigned n = *(unsigned *)(ti + 20);
        if (n > 16) return 0;
        for (unsigned i = 0; i < n; i++)
            if (derives(*(uintptr_t *)(ti + 24 + 16 * i), base, depth + 1)) return 1;
    }
    return 0;
}

/* A class's name off its typeinfo: "14MikeTeaveeMode" -> "MikeTeaveeMode". */
static const char *class_name(uintptr_t vt)
{
    uintptr_t ti = ((uintptr_t *)vt)[-1];
    const char *n = ti ? *(const char **)(ti + 8) : NULL;
    if (!n) return "?";
    if (*n == '*') n++;
    while (*n >= '0' && *n <= '9') n++;
    return n;
}

/* The mode's own global's name ("mtv_mode"), or its class's. */
static const char *object_name(void *o)
{
    Dl_info di;
    if (dladdr(o, &di) && di.dli_sname && di.dli_saddr == o) return di.dli_sname;
    return class_name(*(uintptr_t *)o);
}

static int byte_off_in(const char *vtname, const char *fn)
{
    uintptr_t *v = sym(vtname); uintptr_t a = (uintptr_t)sym(fn);
    if (!v || !a) return -1;
    for (int i = 2; i < MODE_VT_SLOTS; i++) if (v[i] == a) return (i - 2) * 8;
    return -1;
}

static int page_prot(uintptr_t a)
{
    FILE *f = fopen("/proc/self/maps", "r");
    int prot = PROT_READ;
    if (!f) return prot;
    char line[512];
    while (fgets(line, sizeof line, f)) {
        /* "lo-hi rwxp ..." (no sscanf: glibc 2.38 headers bind it to a symbol the image lacks) */
        char *dash = strchr(line, '-'), *sp = dash ? strchr(dash, ' ') : NULL;
        if (!sp) continue;
        unsigned long lo = hexnum(line), hi = hexnum(dash + 1);
        const char *p = sp + 1;
        if (a >= lo && a < hi) {
            prot = (p[0] == 'r' ? PROT_READ : 0) | (p[1] == 'w' ? PROT_WRITE : 0) | (p[2] == 'x' ? PROT_EXEC : 0);
            break;
        }
    }
    fclose(f);
    return prot;
}

static int store_slot(uintptr_t *slot, uintptr_t val)
{
    uintptr_t page = (uintptr_t)slot & ~(uintptr_t)4095;
    int prot = page_prot((uintptr_t)slot);
    if (!(prot & PROT_WRITE) && mprotect((void *)page, 4096, prot | PROT_WRITE)) return 0;
    __atomic_store_n(slot, val, __ATOMIC_SEQ_CST);
    if (!(prot & PROT_WRITE)) mprotect((void *)page, 4096, prot);
    return 1;
}

static int game_mode_bg(void *o)
{
    for (int i = 0; i < ngm; i++) if (gmodes[i] == o) return gmode_bg[i];
    return 0;
}

/* The mode of ours that holds the game off right now, or NULL: running, not
 * paused for something that got through, not on its way out. */
static pm_t *holder(int mb)
{
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        if (m->game_modes != POLICY_HOLD || !m->mode || m->paused || m->want_end) continue;
        if (mb && !m->hold_multiballs) continue;
        if (running(m)) return m;
    }
    return NULL;
}

static int allowed(pm_t *m, void *o, uintptr_t vt)
{
    if (!m->allow[1]) return 0;
    char k[160];
    snprintf(k, sizeof k, " %s ", object_name(o));
    if (strstr(m->allow, k)) return 1;
    snprintf(k, sizeof k, " %s ", class_name(vt));
    return strstr(m->allow, k) != NULL;
}

static hvt_t *hvt_of(uintptr_t vt)
{
    for (int i = 0; i < nhvt; i++) if (hvts[i].vt == vt) return &hvts[i];
    return NULL;
}

/* 1 = refuse this start/restart now (and log it, once a second per class). */
static int refuse(void *self, hvt_t *h, const char *what)
{
    if (!installed || is_ours(self) || game_mode_bg(self)) return 0;
    pm_t *m = holder(h->mb);
    if (!m || allowed(m, self, h->vt)) return 0;
    h->refused++;
    long t = now_ms();
    if (t - h->last_log >= 1000) {     /* a rule may ask on every switch */
        h->last_log = t;
        lg("HELD OFF the game's %s %s (%s) %s: \"%s\" is running (%u refused)", h->mb ? "multiball" : "mode",
           object_name(self), class_name(h->vt), what, m->name, h->refused);
    }
    return 1;
}

static void passed(void *self, hvt_t *h, const char *what, int r)
{
    if (installed && !is_ours(self) && !game_mode_bg(self))
        lg("game %s %s (%s) %s: %s", h->mb ? "multiball" : "mode", object_name(self), class_name(h->vt), what,
           r ? "went ahead" : "declined by the game");
}

static int gate_start(void *self)
{
    hvt_t *h = hvt_of(*(uintptr_t *)self);
    if (!h) {
        lg("WARN start gate called for an unknown class %s; starting it as a Mode", class_name(*(uintptr_t *)self));
        return mode_start_fn ? ((int (*)(void *))mode_start_fn)(self) & 0xff : 0;
    }
    if (refuse(self, h, "start")) return 0;
    int r = ((int (*)(void *))h->orig)(self) & 0xff;
    passed(self, h, "start", r);
    return r;
}

static int gate_restart(void *self)
{
    hvt_t *h = hvt_of(*(uintptr_t *)self);
    if (!h || !h->orig_re) { lg("WARN restart gate: unknown class %s; not restarted", class_name(*(uintptr_t *)self)); return 0; }
    if (refuse(self, h, "restart")) return 0;
    int r = ((int (*)(void *))h->orig_re)(self) & 0xff;
    passed(self, h, "restart", r);
    return r;
}

static void cb_hold_vts(const char *name, uintptr_t a, size_t sz)
{
    if (strncmp(name, "_ZTV", 4) || sz < 32 || nhvt >= MAX_HELD_VTS) return;
    uintptr_t *v = (uintptr_t *)a;
    int mb = 0, off, re;
    if (ti_mode && derives(v[1], ti_mode, 0)) { off = VT_START; re = mode_re_slot; }
    else if (ti_mbr && mb_start_slot >= 0 && derives(v[1], ti_mbr, 0)) { off = mb_start_slot; re = mb_re_slot; mb = 1; }
    else return;
    if (off < 0 || (size_t)(16 + off + 8) > sz) return;
    uintptr_t *slot = (uintptr_t *)(a + 16 + off);
    if (!*slot || *slot == (uintptr_t)gate_start) return;
    hvt_t *h = &hvts[nhvt];
    h->vt = a + 16; h->orig = *slot; h->mb = (unsigned char)mb;
    if (!store_slot(slot, (uintptr_t)gate_start)) { lg("hold: could not write %s's start slot", name); return; }
    if (re >= 0 && (size_t)(16 + re + 8) <= sz) {
        uintptr_t *rs = (uintptr_t *)(a + 16 + re);
        if (*rs && *rs != (uintptr_t)gate_restart) {
            h->orig_re = *rs;
            if (!store_slot(rs, (uintptr_t)gate_restart)) h->orig_re = 0;
        }
    }
    nhvt++;
    if (mb) hvt_mbs++; else hvt_modes++;
}

static void types_init(void)
{
    ti_mode = (uintptr_t)sym("_ZTI4Mode");
    ti_mbr = (uintptr_t)sym("_ZTI13MultiballRule");
    uintptr_t si = (uintptr_t)sym("_ZTVN10__cxxabiv120__si_class_type_infoE");
    uintptr_t vmi = (uintptr_t)sym("_ZTVN10__cxxabiv121__vmi_class_type_infoE");
    si_ti_vt = si ? si + 16 : 0; vmi_ti_vt = vmi ? vmi + 16 : 0;
}

static void install_hold(void)
{
    for (int i = 0; i < npm; i++) if (pms[i].game_modes == POLICY_HOLD) hold_wanted = 1;
    if (!hold_wanted) { lg("hold: no mode holds the game off (game_modes pause/end/ignore); the game's starts untouched"); return; }
    types_init();
    mode_start_fn = (uintptr_t)sym("_ZN4Mode5startEv");
    mb_start_slot = byte_off_in("_ZTV13MultiballRule", "_ZN13MultiballRule5startEv");
    mode_re_slot = byte_off_in("_ZTV4Mode", "_ZN4Mode7restartEv");
    mb_re_slot = byte_off_in("_ZTV13MultiballRule", "_ZN13MultiballRule7restartEv");
    if (!ti_mode || !si_ti_vt || VT_START < 0 || !mode_start_fn) {
        lg("hold: FAIL - typeinfo for Mode %p, si typeinfo %p, start slot %#x: the game's starts cannot be held; "
           "a hold mode pauses for them instead", (void *)ti_mode, (void *)si_ti_vt, VT_START);
        return;
    }
    walk_dynsym(cb_hold_vts);
    lg("hold: start gate on %d Mode class(es) (start %#x, restart %#x) and %d MultiballRule class(es) "
       "(start %#x, restart %#x%s)", hvt_modes, VT_START, mode_re_slot, hvt_mbs, mb_start_slot, mb_re_slot,
       ti_mbr ? "" : ", no MultiballRule on this title");
}

/* ---- sound ----------------------------------------------------------------- */
static void play(void *se)
{
    if (!se) return;
    void **vt = *(void ***)se;
    if (!vt) return;
    for (int i = 0; i < 24; i++) {
        Dl_info di;
        if (vt[i] && dladdr(vt[i], &di) && di.dli_sname) {
            size_t L = strlen(di.dli_sname);
            if (L > 18 && !strcmp(di.dli_sname + L - 18, "SoundEffect4playEv")) { ((vfn0_t)vt[i])(se); return; }
        }
    }
    void *base = sym("_ZN11SoundEffect4playEv");
    if (base) ((vfn0_t)base)(se);
}

/* ---- own media: a mode's own sounds, music, picture and video (PAD-1352) ---
 * Files in the mode folder.  Nothing goes through the game's file manager (its
 * loader decrypts every file with a key made from its path and checks it
 * against the dongle-encrypted file list, so a file of ours cannot pass):
 *
 *   sounds   a SoundEffect OF THE GAME'S OWN, copied from one of its se_*
 *            objects on the wanted channel (fanfare by default), given our
 *            sample (al_load_sample, the Allegro the game plays through) and
 *            fresh voices by the game's own SoundEffect::create_sample_instances,
 *            which attaches them to that channel's mixer.  It is played by the
 *            game's own SoundEffect::play, so the game's volume, channel gain,
 *            fades and ducking apply as to its own sounds.
 *   music    the same, copied from a music-channel sound, and made the game's
 *            music the game's own way: a node of ours at the head of
 *            Update<UpdateBGMusic_>::list, the list update_music() asks "what
 *            music now?".  While the mode runs our node answers with our music;
 *            otherwise it passes and the game's own music comes back, stopped
 *            and started by the game's music_request.
 *   picture  al_load_bitmap (PNG/JPG, the game's allegro_image), drawn in the
 *            frame hook.
 *   video    decoded on a thread of ours by the game's own FFmpeg (libavformat/
 *            libavcodec 58 on every JJP title), drawn in the frame hook.  WebM
 *            (VP8/VP9), the format the game's own clips are; no sound.
 *
 * The SoundEffect layout (where its sample, channel and "loaded" byte are) is
 * read off the game's own code, decrypted by the time we look, by matching the
 * instructions that use each field - never a fixed offset.  The offsets on
 * Wonka 03.03: sample +0x58, channel +0x18, loaded +0xd8, stream +0xf0, flags +0x54. */
static int se_sample_off = -1, se_type_off = -1, se_loaded_off = -1, se_stream_off = -1, se_flags_off = -1;
static int media_sound_ok;              /* layout learned: own sound files can be made */
static void *(*al_load_sample_)(const char *);
static void (*se_csi)(void *, const char *);
static int (*se_is_loaded)(void *), (*se_is_playing)(void *);
static void (*update_music_fn)(void);
static volatile int music_claimed;      /* 1 + the mode whose music our list node gave, 0 = passed */
static long music_asked_at;

typedef struct { const char *name; uintptr_t addr; size_t size; } se_obj_t;
static se_obj_t *ses; static int nses, cap_ses;
static void cb_ses(const char *name, uintptr_t a, size_t sz)
{
    if (strncmp(name, "se_", 3) || sz < 0x100 || sz > 0x1000) return;
    if (nses == cap_ses) { cap_ses = cap_ses ? cap_ses * 2 : 1024; ses = realloc(ses, cap_ses * sizeof *ses); }
    ses[nses].name = name; ses[nses].addr = a; ses[nses].size = sz; nses++;
}

/* The import a `call rel32` at c reaches through the PLT: the stub's
 * `jmp *GOT(%rip)` (after an endbr64 / bnd prefix), its GOT entry. */
static void *call_import(const unsigned char *c)
{
    if (c[0] != 0xe8) return NULL;
    int32_t rel; memcpy(&rel, c + 1, 4);
    const unsigned char *t = c + 5 + rel;
    for (int i = 0; i < 8; i++)
        if (t[i] == 0xff && t[i + 1] == 0x25) {
            int32_t d; memcpy(&d, t + i + 2, 4);
            return *(void *const *)(t + i + 6 + d);
        }
    return NULL;
}
static const unsigned char *call_target(const unsigned char *c)
{
    int32_t rel; memcpy(&rel, c + 1, 4);
    return c + 5 + rel;
}

/* `mov disp(%rbx|%rdi|%rbp),%rdi` ending just before p -> disp, or -1. */
static int disp_before(const unsigned char *p)
{
    if (p[-4] == 0x48 && p[-3] == 0x8b && (p[-2] == 0x7b || p[-2] == 0x7f || p[-2] == 0x7d)) return p[-1];
    if (p[-7] == 0x48 && p[-6] == 0x8b && (p[-5] == 0xbb || p[-5] == 0xbf || p[-5] == 0xbd)) { int32_t d; memcpy(&d, p - 4, 4); return d; }
    return -1;
}

static void learn_se_layout(void)
{
    const unsigned char *csi = (const unsigned char *)se_csi, *dp = sym("_ZN11SoundEffect7do_playEb");
    void *create_inst = sym("al_create_sample_instance");
    const unsigned char *pas = sym("_ZN11SoundEffect17play_audio_streamEv");
    if (csi && create_inst)
        for (int i = 8; i < 0x400 && se_sample_off < 0; i++)
            if (csi[i] == 0xe8 && call_import(csi + i) == create_inst) se_sample_off = disp_before(csi + i);
    /* the channel: `movslq disp8(%rbx),%rax` then `mov table(,%rax,8),%rax` */
    if (csi)
        for (int i = 16; i < 0x400 && se_type_off < 0; i++)
            if (csi[i] == 0x48 && csi[i + 1] == 0x8b && csi[i + 2] == 0x04 && csi[i + 3] == 0xc5)
                for (int j = i - 4; j >= i - 16; j--)
                    if (csi[j] == 0x48 && csi[j + 1] == 0x63 && csi[j + 2] == 0x43) { se_type_off = csi[j + 3]; break; }
    if (dp) {
        for (int i = 0; i < 0x40 && se_flags_off < 0; i++)       /* testb $0x2,disp8(%rdi): "loaded on demand" */
            if (dp[i] == 0xf6 && dp[i + 1] == 0x47 && dp[i + 3] == 0x02) se_flags_off = dp[i + 2];
        for (int i = 0; i < 0x60 && se_loaded_off < 0; i++)      /* then cmpb $0,disp32(%rdi): is it loaded */
            if (dp[i] == 0x80 && dp[i + 1] == 0xbf && dp[i + 6] == 0x00) memcpy(&se_loaded_off, dp + i + 2, 4);
        /* cmpb $0,disp32(%rbx); jne -> a block calling play_audio_stream: the stream flag */
        for (int i = 0; i < 0x200 && se_stream_off < 0 && pas; i++)
            if (dp[i] == 0x80 && dp[i + 1] == 0xbb && dp[i + 6] == 0x00 && dp[i + 7] == 0x0f && dp[i + 8] == 0x85) {
                int32_t rel; memcpy(&rel, dp + i + 9, 4);
                const unsigned char *t = dp + i + 13 + rel;
                for (int k = 0; k < 24; k++) if (t[k] == 0xe8 && call_target(t + k) == pas) { memcpy(&se_stream_off, dp + i + 2, 4); break; }
            }
    }
    media_sound_ok = se_sample_off > 0 && se_type_off > 0 && se_loaded_off > 0 && al_load_sample_ && se_csi;
    lg("own sounds: SoundEffect sample +%#x, channel +%#x, loaded +%#x, stream +%#x, flags +%#x (read off the game's "
       "create_sample_instances / do_play)%s", se_sample_off, se_type_off, se_loaded_off, se_stream_off, se_flags_off,
       media_sound_ok ? "" : " - INCOMPLETE: a mode's own sound files are off on this title");
}

static int se_type(const se_obj_t *o) { return *(int *)(o->addr + se_type_off); }
static int se_usable(const se_obj_t *o, int kind)
{
    char *b = (char *)o->addr;
    if (*(uintptr_t *)b == 0 || se_type(o) != kind || !se_is_loaded((void *)b)) return 0;
    if (se_flags_off > 0 && (*(unsigned char *)(b + se_flags_off) & 2)) return 0;    /* loaded on demand: may be unloaded */
    if (se_is_playing && se_is_playing((void *)b)) return 0;                         /* copy it at rest */
    if (kind != 1 && !*(void **)(b + se_sample_off)) return 0;                      /* a sample, not a stream */
    return 1;
}

/* A game SoundEffect on the channel `kind` (or a copy of the named one) with
 * our file as its sample. */
static void *make_own_sound(pm_t *m, const char *file, int kind, const char *like)
{
    char path[700];
    snprintf(path, sizeof path, "%s%s%s", *file == '/' ? "" : moddir, *file == '/' ? "" : "/", file);
    if (access(path, R_OK)) { lg("%s: no file %s", m->file, path); return NULL; }
    const se_obj_t *t = NULL;
    for (int i = 0; i < nses && !t; i++)
        if (*like ? !strcmp(ses[i].name, like) : se_usable(&ses[i], kind)) t = &ses[i];
    if (!t) { lg("%s: no game sound %s to copy for %s", m->file, *like ? like : "on that channel", file); return NULL; }
    void *smp = al_load_sample_(path);
    if (!smp) { lg("%s: Allegro could not read %s (wav, ogg, flac or opus)", m->file, path); return NULL; }
    char *o = calloc(1, t->size < 0x200 ? 0x200 : t->size);
    memcpy(o, (void *)t->addr, t->size);
    *(void **)(o + se_sample_off) = smp;
    if (se_stream_off > 0) o[se_stream_off] = 0;             /* ours is a sample in memory */
    if (se_flags_off > 0) o[se_flags_off] &= (char)~2;
    se_csi(o, path);                                         /* voices on the channel's mixer */
    o[se_loaded_off] = 1;
    lg("%s: own sound %s on channel %d (the game's %s's settings), %s", m->file, file, *(int *)(o + se_type_off),
       t->name, se_is_loaded(o) ? "ready" : "NOT loaded");
    return o;
}

/* ---- our music: a node at the head of the game's music list ---------------- */
typedef struct { void *fn; const char *name; } upd_desc_t;
typedef struct upd_node { int prio; int pad_; upd_desc_t *desc; void *unused; struct upd_node *next; } upd_node_t;
static int music_wanted(pm_t *m)
{
    return m->music && running(m) && !m->paused && !m->want_end && (m->game_modes == POLICY_IGNORE || !game_busy());
}
static void music_play(int i) { if (i < npm && pms[i].music) { play(pms[i].music); lg("\"%s\": music %s", pms[i].name, pms[i].music_file); } }
#define MU(i) static void music_fn_##i(void) { music_play(i); }
MU(0) MU(1) MU(2) MU(3) MU(4) MU(5) MU(6) MU(7) MU(8) MU(9) MU(10) MU(11)
MU(12) MU(13) MU(14) MU(15) MU(16) MU(17) MU(18) MU(19) MU(20) MU(21) MU(22) MU(23)
static void (*const music_fns[MAX_MODES])(void) = { music_fn_0, music_fn_1, music_fn_2, music_fn_3, music_fn_4,
    music_fn_5, music_fn_6, music_fn_7, music_fn_8, music_fn_9, music_fn_10, music_fn_11, music_fn_12, music_fn_13,
    music_fn_14, music_fn_15, music_fn_16, music_fn_17, music_fn_18, music_fn_19, music_fn_20, music_fn_21,
    music_fn_22, music_fn_23 };
_Static_assert(sizeof music_fns / sizeof *music_fns == MAX_MODES, "one music function per mode");

/* Called by the game's update_music() before all its own music rules: nonzero
 * with *out set = "this music", 0 = "not me, ask the next". */
static int pad_music_update(void (**out)(void))
{
    for (int i = 0; i < npm; i++)
        if (music_wanted(&pms[i])) {
            *out = music_fns[i];
            if (music_claimed != i + 1) lg("music: \"%s\"'s own music is the game's music now", pms[i].name);
            music_claimed = i + 1;
            return 1;
        }
    if (music_claimed) lg("music: handed back to the game's own");
    music_claimed = 0;
    return 0;
}
static upd_desc_t music_desc = { (void *)pad_music_update, "pad_custom_mode_music" };
static upd_node_t music_node = { -0x7fffffff, 0, &music_desc, NULL, NULL };

static void install_music_node(void)
{
    int need = 0;
    for (int i = 0; i < npm; i++) need |= *pms[i].music_file != 0;
    if (!need) return;
    void **list = sym("_ZN6UpdateI14UpdateBGMusic_PPFvvEE4listE");
    update_music_fn = (void (*)(void))sym("_Z12update_musicv");
    if (!list || !update_music_fn || *(int *)((char *)list + 8) != 0x45) {
        lg("music: the game's music list %p (magic %#x) / update_music %p not found; a mode's music is off",
           (void *)list, list ? *(int *)((char *)list + 8) : 0, (void *)update_music_fn);
        update_music_fn = NULL;
        return;
    }
    music_node.next = *list;
    __atomic_store_n((upd_node_t **)list, &music_node, __ATOMIC_SEQ_CST);
    lg("music: our rule heads the game's music list (Update<UpdateBGMusic_>)");
}

/* Ask the game to pick its music again (from a proc, where the game does). */
static void music_reconsider(const char *why)
{
    if (!update_music_fn) return;
    music_asked_at = now_ms();
    lg("music: update_music (%s)", why);
    update_music_fn();
}

/* ---- video ------------------------------------------------------------------ */
typedef struct video {
    char path[700]; int loop;
    volatile int stop, pause, ended, failed;
    pthread_t th; int started;
    pthread_mutex_t mu;
    unsigned char *front, *back; int w, h; long seq, shown;
    void *bmp; long frames;
} video_t;

static struct {
    int ok;
    int (*open_input)(void **, const char *, void *, void **);
    int (*find_info)(void *, void **);
    int (*best)(void *, int, int, int, const void **, int);
    void *(*alloc_ctx)(const void *);
    int (*par_to_ctx)(void *, const void *);
    int (*open2)(void *, const void *, void **);
    void *(*pkt_alloc)(void);
    void *(*frame_alloc)(void);
    int (*read_frame)(void *, void *);
    int (*send)(void *, const void *);
    int (*recv)(void *, void *);
    void (*pkt_unref)(void *);
    int (*seek)(void *, int, long long, int);
    void (*flush)(void *);
    void (*close_input)(void **);
    void (*free_ctx)(void **);
    void (*pkt_free)(void **);
    void (*frame_free)(void **);
    unsigned (*version)(void);
} av;

static void av_resolve(void)
{
    av.open_input = sym("avformat_open_input"); av.find_info = sym("avformat_find_stream_info");
    av.best = sym("av_find_best_stream"); av.alloc_ctx = sym("avcodec_alloc_context3");
    av.par_to_ctx = sym("avcodec_parameters_to_context"); av.open2 = sym("avcodec_open2");
    av.pkt_alloc = sym("av_packet_alloc"); av.frame_alloc = sym("av_frame_alloc");
    av.read_frame = sym("av_read_frame"); av.send = sym("avcodec_send_packet");
    av.recv = sym("avcodec_receive_frame"); av.pkt_unref = sym("av_packet_unref");
    av.seek = sym("av_seek_frame"); av.flush = sym("avcodec_flush_buffers");
    av.close_input = sym("avformat_close_input"); av.free_ctx = sym("avcodec_free_context");
    av.pkt_free = sym("av_packet_free"); av.frame_free = sym("av_frame_free"); av.version = sym("avformat_version");
    void **f = (void **)&av.open_input;
    av.ok = 1;
    for (unsigned i = 0; i < (sizeof av - offsetof(__typeof__(av), open_input)) / sizeof(void *); i++) if (!f[i]) av.ok = 0;
    unsigned v = av.version ? av.version() : 0;
    if (av.ok && (v >> 16 < 57 || v >> 16 > 60)) av.ok = 0;     /* the struct reads below are FFmpeg 3.4-6.x's */
    lg("video: the game's FFmpeg %s (libavformat %u.%u)", av.ok ? "ok" : "MISSING or unknown", v >> 16, (v >> 8) & 0xff);
}

/* FFmpeg 3.4-6.x structs, read by the few long-stable fields we need (no
 * FFmpeg headers in the build: the game's own libraries, found by name). */
#define AVF_NB_STREAMS 44
#define AVF_STREAMS    48
#define AVS_TIME_BASE  24
#define AVFR_W 104
#define AVFR_H 108
#define AVFR_FMT 116
#define AVFR_PTS 136
#define AVPKT_STREAM 36

/* The stream's AVCodecParameters: the pointer in the AVStream whose struct
 * says (video, this decoder's codec id, a plausible size). */
/* Is [p, p+n) mapped?  (mincore fails ENOMEM on an unmapped page; never faults.) */
static int mapped(const void *p, size_t n)
{
    uintptr_t a = (uintptr_t)p & ~(uintptr_t)4095, e = (uintptr_t)p + n;
    unsigned char v;
    for (; a < e; a += 4096) if (mincore((void *)a, 4096, &v)) return 0;
    return 1;
}
static const void *find_codecpar(const char *st, const void *dec)
{
    int id = *(const int *)((const char *)dec + 20);           /* AVCodec.id */
    /* FFmpeg 4.x (libavformat 58): AVStream.codecpar is at +208; look there
     * first, then anywhere in the struct - only through mapped pointers: the
     * struct also holds int64 fields (an unset pts is 0x8000000000000000). */
    for (int k = -1; k < 0x200 / 8; k++) {
        int off = k < 0 ? 208 : k * 8;
        const int *p = *(const int *const *)(st + off);
        if (!p || (uintptr_t)p < 0x10000 || ((uintptr_t)p & 7) || (uintptr_t)p >> 47 || !mapped(p, 64)) continue;
        if (p[0] == 0 && p[1] == id && p[14] > 0 && p[15] > 0 && p[14] <= 8192 && p[15] <= 8192) return p;
    }
    return NULL;
}

static inline unsigned char clamp8(int v) { return (unsigned char)(v < 0 ? 0 : v > 255 ? 255 : v); }

/* A decoded frame into premultiplied RGBA (R,G,B,A bytes), BT.601. */
static int frame_to_rgba(const char *fr, unsigned char *out, int w, int h)
{
    int fmt = *(const int *)(fr + AVFR_FMT);
    int sx, sy, full = 0, alpha = 0;
    switch (fmt) {
    case 0: sx = 1; sy = 1; break;              /* yuv420p */
    case 12: sx = 1; sy = 1; full = 1; break;   /* yuvj420p */
    case 4: sx = 1; sy = 0; break;              /* yuv422p */
    case 13: sx = 1; sy = 0; full = 1; break;   /* yuvj422p */
    case 5: sx = 0; sy = 0; break;              /* yuv444p */
    case 14: sx = 0; sy = 0; full = 1; break;   /* yuvj444p */
    case 33: sx = 1; sy = 1; alpha = 1; break;  /* yuva420p (VP8/VP9 with alpha) */
    default: return 0;
    }
    unsigned char *const *d = (unsigned char *const *)fr;
    const int *ls = (const int *)(fr + 64);
    for (int y = 0; y < h; y++) {
        const unsigned char *Y = d[0] + (long)y * ls[0], *U = d[1] + (long)(y >> sy) * ls[1],
                            *V = d[2] + (long)(y >> sy) * ls[2], *A = alpha ? d[3] + (long)y * ls[3] : NULL;
        unsigned char *o = out + (long)y * w * 4;
        for (int x = 0; x < w; x++, o += 4) {
            int c = Y[x], dd = U[x >> sx] - 128, e = V[x >> sx] - 128, r, g, b;
            if (full) { c <<= 8; r = (c + 359 * e) >> 8; g = (c - 88 * dd - 183 * e) >> 8; b = (c + 454 * dd) >> 8; }
            else { c = 298 * (c - 16) + 128; r = (c + 409 * e) >> 8; g = (c - 100 * dd - 208 * e) >> 8; b = (c + 516 * dd) >> 8; }
            int a = A ? A[x] : 255;
            o[0] = (unsigned char)(clamp8(r) * a / 255); o[1] = (unsigned char)(clamp8(g) * a / 255);
            o[2] = (unsigned char)(clamp8(b) * a / 255); o[3] = (unsigned char)a;
        }
    }
    return 1;
}

static void vsleep(video_t *v, long ms) { while (ms > 0 && !v->stop) { usleep(ms > 20 ? 20000 : (unsigned)ms * 1000); ms -= 20; } }

static void *video_worker(void *arg)
{
    video_t *v = arg;
    void *ic = NULL, *ctx = NULL, *pkt = NULL, *fr = NULL; const void *dec = NULL;
    int idx = -1, opened = 0;
    if (av.open_input(&ic, v->path, NULL, NULL) < 0 || !ic) { lg("video: cannot open %s", v->path); goto out; }
    if (av.find_info(ic, NULL) < 0) { lg("video: %s: no stream info", v->path); goto out; }
    idx = av.best(ic, 0 /* AVMEDIA_TYPE_VIDEO */, -1, -1, &dec, 0);
    if (idx < 0 || !dec || (unsigned)idx >= *(unsigned *)((char *)ic + AVF_NB_STREAMS)) { lg("video: %s has no video this FFmpeg decodes", v->path); goto out; }
    const char *st = (*(char *const *const *)((char *)ic + AVF_STREAMS))[idx];
    const void *par = find_codecpar(st, dec);
    int tb_num = *(const int *)(st + AVS_TIME_BASE), tb_den = *(const int *)(st + AVS_TIME_BASE + 4);
    if (tb_num <= 0 || tb_den <= 0) { tb_num = 1; tb_den = 1000; }
    ctx = av.alloc_ctx(dec);
    if (!ctx || !par || av.par_to_ctx(ctx, par) < 0 || av.open2(ctx, dec, NULL) < 0) { lg("video: %s: decoder %s did not open", v->path, *(const char *const *)dec); goto out; }
    opened = 1;
    pkt = av.pkt_alloc(); fr = av.frame_alloc();
    lg("video: %s: %s %dx%d, time base %d/%d", v->path, *(const char *const *)dec, ((const int *)par)[14], ((const int *)par)[15], tb_num, tb_den);
    long t0 = now_ms(); long long first = -1;
    while (!v->stop) {
        if (v->pause) { usleep(20000); t0 += 20; continue; }
        int r = av.read_frame(ic, pkt);
        if (r < 0) {
            if (!v->loop) { v->ended = 1; lg("video: %s ended (%ld frames); its last frame stays", v->path, v->frames); break; }
            av.seek(ic, idx, 0, 1 /* AVSEEK_FLAG_BACKWARD */); av.flush(ctx);
            t0 = now_ms(); first = -1;
            continue;
        }
        if (*(int *)((char *)pkt + AVPKT_STREAM) != idx) { av.pkt_unref(pkt); continue; }
        av.send(ctx, pkt); av.pkt_unref(pkt);
        while (!v->stop && av.recv(ctx, fr) == 0) {
            int w = *(int *)((char *)fr + AVFR_W), h = *(int *)((char *)fr + AVFR_H);
            long long pts = *(long long *)((char *)fr + AVFR_PTS);
            if (pts == (long long)0x8000000000000000ULL) pts = first < 0 ? 0 : first + v->frames;
            if (first < 0) first = pts;
            long due = t0 + (long)((pts - first) * 1000LL * tb_num / tb_den);
            long late = now_ms() - due;
            if (late < 0) vsleep(v, -late);
            if (late > 250) continue;                          /* behind: drop it, keep the clock */
            if (w <= 0 || h <= 0 || w > 8192 || h > 8192) continue;
            if (!v->back || w != v->w || h != v->h) {
                pthread_mutex_lock(&v->mu);
                free(v->back); free(v->front);
                v->back = malloc((size_t)w * h * 4); v->front = calloc(1, (size_t)w * h * 4);
                v->w = w; v->h = h;
                pthread_mutex_unlock(&v->mu);
            }
            if (!frame_to_rgba(fr, v->back, w, h)) {
                if (!v->failed) lg("video: %s: pixel format %d is not one we draw (yuv420p, yuva420p...)", v->path, *(int *)((char *)fr + AVFR_FMT));
                v->failed = 1; continue;
            }
            pthread_mutex_lock(&v->mu);
            unsigned char *t = v->front; v->front = v->back; v->back = t; v->seq++;
            pthread_mutex_unlock(&v->mu);
            v->frames++;
        }
    }
out:
    if (fr) av.frame_free(&fr);
    if (pkt) av.pkt_free(&pkt);
    if (ctx) av.free_ctx(&ctx);
    if (ic) av.close_input(&ic);
    if (!opened) v->failed = 1;
    return NULL;
}

static video_t *video_start(pm_t *m)
{
    if (!*m->vid_file || !av.ok) return NULL;
    video_t *v = calloc(1, sizeof *v);
    snprintf(v->path, sizeof v->path, "%s%s%s", *m->vid_file == '/' ? "" : moddir, *m->vid_file == '/' ? "" : "/", m->vid_file);
    v->loop = m->vid_loop;
    pthread_mutex_init(&v->mu, NULL);
    if (pthread_create(&v->th, NULL, video_worker, v) == 0) v->started = 1;
    return v;
}

static void (*al_destroy_bitmap_)(void *);
static void video_stop(video_t *v)       /* render thread: the bitmap is a GL texture */
{
    if (!v) return;
    v->stop = 1;
    if (v->started) pthread_join(v->th, NULL);
    if (v->bmp && al_destroy_bitmap_) al_destroy_bitmap_(v->bmp);
    lg("video: %s stopped after %ld frame(s)", v->path, v->frames);
    free(v->front); free(v->back); pthread_mutex_destroy(&v->mu); free(v);
}

/* ---- the loader: once the game's own sounds are in ---------------------------- */
static void *media_loader(void *arg)
{
    (void)arg;
    int want = 0;
    for (int i = 0; i < npm; i++)
        want |= pms[i].own_snd[0] | pms[i].own_snd[1] | pms[i].own_snd[2] | pms[i].own_snd[3] | (*pms[i].music_file != 0);
    if (!want) return NULL;
    al_load_sample_ = sym("al_load_sample");
    se_csi = sym("_ZN11SoundEffect23create_sample_instancesEPKc");
    se_is_loaded = sym("_ZN11SoundEffect9is_loadedEv");
    se_is_playing = sym("_ZN11SoundEffect10is_playingEv");
    if (!se_is_loaded || !se_csi || !al_load_sample_) { lg("own sounds: the game's SoundEffect API is missing; off"); return NULL; }
    walk_dynsym(cb_ses);
    /* the game loads its sounds at power-up: wait until the count settles */
    int last = -1, same = 0;
    for (int t = 0; t < 360 && same < 4; t++) {
        int n = 0;
        for (int i = 0; i < nses; i++) if (*(uintptr_t *)ses[i].addr && se_is_loaded((void *)ses[i].addr)) n++;
        same = n == last && n > 0 ? same + 1 : 0; last = n;
        usleep(500000);
    }
    lg("own sounds: %d of the game's %d sounds loaded", last, nses);
    learn_se_layout();
    if (!media_sound_ok) return NULL;
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        for (int s = 0; s < 4; s++) {
            if (!m->own_snd[s]) continue;
            void *o = make_own_sound(m, m->snd_names[s], m->sound_kind, m->sound_like);
            if (s == 0) m->snd_start = o; else if (s == 1) m->snd_shot = o; else if (s == 2) m->snd_end = o; else m->snd_complete = o;
        }
        if (*m->music_file && update_music_fn) m->music = make_own_sound(m, m->music_file, 1, m->music_like);
    }
    return NULL;
}

/* ---- pictures and video on the screen (render thread) ------------------------ */
static struct {
    int ok;
    void *(*load)(const char *);
    int (*bw)(void *), (*bh)(void *);
    void (*draw_scaled)(void *, float, float, float, float, float, float, float, float, int);
    void *(*create)(int, int);
    void *(*lock)(void *, int, int);
    void (*unlock)(void *);
    int (*get_flags)(void);
    void (*set_flags)(int);
} al;

static void al_media_resolve(void)
{
    al.load = sym("al_load_bitmap"); al.bw = sym("al_get_bitmap_width"); al.bh = sym("al_get_bitmap_height");
    al.draw_scaled = sym("al_draw_scaled_bitmap"); al.create = sym("al_create_bitmap");
    al.lock = sym("al_lock_bitmap"); al.unlock = sym("al_unlock_bitmap");
    al.get_flags = sym("al_get_new_bitmap_flags"); al.set_flags = sym("al_set_new_bitmap_flags");
    al_destroy_bitmap_ = sym("al_destroy_bitmap");
    al.ok = al.load && al.bw && al.bh && al.draw_scaled && al.create && al.lock && al.unlock && al.get_flags
            && al.set_flags && al_destroy_bitmap_;
}

#define AL_VIDEO_BITMAP 0x400
#define AL_PIXEL_ABGR_8888_LE 25
#define AL_LOCK_WRITEONLY 2

static void load_pictures(void)
{
    static int done;
    if (done) return;
    done = 1;
    int any = 0;
    for (int i = 0; i < npm; i++) any |= *pms[i].pic_file || *pms[i].vid_file;
    if (!any) return;
    al_media_resolve();
    if (!al.ok) { lg("screen: Allegro bitmap calls missing; pictures and video off"); return; }
    av_resolve();
    int fl = al.get_flags(); al.set_flags(AL_VIDEO_BITMAP);
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        if (!*m->pic_file) continue;
        char path[700];
        snprintf(path, sizeof path, "%s%s%s", *m->pic_file == '/' ? "" : moddir, *m->pic_file == '/' ? "" : "/", m->pic_file);
        m->pic_bmp = al.load(path);
        if (m->pic_bmp) { m->pic_w = al.bw(m->pic_bmp); m->pic_h = al.bh(m->pic_bmp); lg("%s: picture %s %dx%d", m->file, m->pic_file, m->pic_w, m->pic_h); }
        else { m->pic_failed = 1; lg("%s: Allegro could not read picture %s (png or jpg)", m->file, path); }
    }
    al.set_flags(fl);
}

/* Fitted into the box (percent of the screen), aspect kept, centred. */
static void draw_fit(void *bmp, int bw, int bh, const float *at, float W, float H)
{
    float x = at[0] * W / 100, y = at[1] * H / 100, w = at[2] * W / 100, h = at[3] * H / 100;
    float s = w / bw < h / bh ? w / bw : h / bh, dw = bw * s, dh = bh * s;
    al.draw_scaled(bmp, 0, 0, (float)bw, (float)bh, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh, 0);
}

static void draw_media(pm_t *m, float W, float H)
{
    if (!al.ok) return;
    video_t *v = m->vid;
    if (v && v->seq) {
        if (v->seq != v->shown) {
            pthread_mutex_lock(&v->mu);
            if (v->bmp && (al.bw(v->bmp) != v->w || al.bh(v->bmp) != v->h)) { al_destroy_bitmap_(v->bmp); v->bmp = NULL; }
            if (!v->bmp) { int fl = al.get_flags(); al.set_flags(AL_VIDEO_BITMAP); v->bmp = al.create(v->w, v->h); al.set_flags(fl); }
            if (v->bmp) {
                struct { void *data; int format, pitch, pixel_size; } *lr = al.lock(v->bmp, AL_PIXEL_ABGR_8888_LE, AL_LOCK_WRITEONLY);
                if (lr) {
                    for (int y = 0; y < v->h; y++) memcpy((char *)lr->data + (long)y * lr->pitch, v->front + (long)y * v->w * 4, (size_t)v->w * 4);
                    al.unlock(v->bmp);
                }
            }
            v->shown = v->seq;
            pthread_mutex_unlock(&v->mu);
        }
        if (v->bmp) draw_fit(v->bmp, v->w, v->h, m->vid_at, W, H);
    }
    if (m->pic_bmp) draw_fit(m->pic_bmp, m->pic_w, m->pic_h, m->pic_at, W, H);
}

/* ---- lamps ----------------------------------------------------------------- */
static void *our_lb;
static lamp_set_t lamp_set;
static lamp_tr_t lamp_tr;
static uintptr_t lamp_vts[8]; static int nlvt;
/* A lamp group (ls_*) is a LampString, not a Lamp: Lamp::set on one writes
 * through a Lamp's layout and lit nothing (PAD-1350, Wonka: lp_gobstopper +
 * ls_golden_tickets stayed dark for the whole mode, lp_gobstopper alone
 * blinked).  A LampString has its own on()/transparent() of the same shape. */
static lamp_set_t ls_on;
static lamp_tr_t ls_tr;
static uintptr_t ls_vt;
static int is_string(void *o) { return ls_vt && *(uintptr_t *)o == ls_vt; }
static void lamp_put(void *o, unsigned r, unsigned g, unsigned b)
{
    if (is_string(o)) ls_on(o, our_lb, r, g, b, 255);
    else lamp_set(o, our_lb, r, g, b, 255);
}
static void lamp_give_back(void *o)
{
    if (is_string(o)) ls_tr(o, our_lb);
    else lamp_tr(o, our_lb);
}

static int lamp_like(void *o)
{
    uintptr_t w = *(uintptr_t *)o;
    for (int i = 0; i < nlvt; i++) if (w == lamp_vts[i]) return 1;
    return 0;
}

static void our_lb_render(void *lb) { (void)lb; }

static int v_is(void *o, const char *vtable)
{
    void *v = sym(vtable);
    return v && *(uintptr_t *)o == (uintptr_t)v + 16;
}

/* LampBuffer::render_all skips a layer whose public `active` bool is false;
 * the game sets that member inline, so no exported call does it.  Its offset
 * is read off render_all's own (decrypted by the time we run) first
 * `cmpb $0x0,disp8(%reg)` - GnR: 80 7d 2c 00, +0x2c. */
static int lb_active_off = -1;
static void find_lb_active(void)
{
    const unsigned char *c = sym("_ZN10LampBuffer10render_allEv");
    if (c)
        for (int i = 0; i < 0x200; i++)
            if (c[i] == 0x80 && c[i + 1] >= 0x78 && c[i + 1] <= 0x7f && c[i + 1] != 0x7c && c[i + 3] == 0x00
                && c[i + 2] >= 0x20 && c[i + 2] < 0x80) { lb_active_off = c[i + 2]; break; }
    if (lb_active_off < 0) { lb_active_off = 0x2c; lg("lamps: render_all pattern not found; active flag assumed at +0x2c"); }
    else lg("lamps: a LampBuffer is composited while its byte +%#x is set (read off render_all)", lb_active_off);
}
static void lb_activate(int on)
{
    if (our_lb && lb_active_off > 0) *((volatile unsigned char *)our_lb + lb_active_off) = (unsigned char)(on != 0);
}

static void build_lamp_buffer(void)
{
    lb_ctor_t ctor = (lb_ctor_t)sym("_ZN10LampBufferC1EiPFvPS_EPKc9lb_flag_t");
    lamp_set = (lamp_set_t)sym("_ZN4Lamp3setER10LampBufferhhhh");
    lamp_tr = (lamp_tr_t)sym("_ZN4Lamp11transparentER10LampBuffer");
    const char *vts[] = { "_ZTV4Lamp", "_ZTV10LampString", "_ZTV14MultiLEDInsert", "_ZTV5Light" };
    for (unsigned i = 0; i < sizeof vts / sizeof *vts; i++) { void *v = sym(vts[i]); if (v) lamp_vts[nlvt++] = (uintptr_t)v + 16; }
    if (!ctor || !lamp_set || !lamp_tr) { lg("lamps: LampBuffer/Lamp API missing; modes run without lamps"); return; }
    ls_on = (lamp_set_t)sym("_ZN10LampString2onER10LampBufferhhhh");
    ls_tr = (lamp_tr_t)sym("_ZN10LampString11transparentER10LampBuffer");
    { void *v = sym("_ZTV10LampString"); ls_vt = (v && ls_on && ls_tr) ? (uintptr_t)v + 16 : 0; }
    /* Above the game's mode layers (GnR: ~0x400-0x4ff), below its award,
     * Bluetooth and flasher layers (1e9+). */
    int prio = 0x7fff;
    our_lb = calloc(1, 0x200);
    ctor(our_lb, prio, our_lb_render, "pad_custom_modes", 0);
    find_lb_active();
    lg("lamps: our LampBuffer %p at priority %#x", our_lb, prio);
    for (int i = 0; i < npm; i++)
        for (int l = 0; l < pms[i].nlamp; l++)
            if (!lamp_like(pms[i].lamp[l])
                || (!ls_vt && v_is(pms[i].lamp[l], "_ZTV10LampString"))) {
                lg("%s: lamp #%d is not a Lamp object (or a lamp group this game cannot set); dropped",
                   pms[i].file, l);
                pms[i].lamp[l] = pms[i].lamp[--pms[i].nlamp]; l--;
            } else if (is_string(pms[i].lamp[l]))
                lg("%s: lamp #%d is a lamp group", pms[i].file, l);
}

static void (*upd_soon)(void);
static void lamps_show(pm_t *m, int on)
{
    if (!our_lb) return;
    lb_activate(1);
    unsigned r = (m->lamp_rgb >> 16) & 0xff, g = (m->lamp_rgb >> 8) & 0xff, b = m->lamp_rgb & 0xff;
    for (int l = 0; l < m->nlamp; l++) {
        if (on) lamp_put(m->lamp[l], r, g, b);
        else lamp_put(m->lamp[l], 0, 0, 0);
    }
    for (int l = 0; l < m->ncl; l++) {     /* the lamps its code lit (PAD-1384), each at its own rate */
        unsigned c = m->cl[l].rgb;
        long half = m->cl[l].blink > 0 ? 500L / m->cl[l].blink : 0;
        int lit = !m->paused && (half == 0 || ((now_ms() / (half ? half : 1)) & 1) == 0);
        lamp_put(m->cl[l].o, lit ? (c >> 16) & 0xff : 0, lit ? (c >> 8) & 0xff : 0, lit ? c & 0xff : 0);
    }
}

static void lamps_release(pm_t *m)
{
    if (!our_lb) return;
    for (int l = 0; l < m->nlamp; l++) lamp_give_back(m->lamp[l]);
    for (int l = 0; l < m->ncl; l++) lamp_give_back(m->cl[l].o);
    m->ncl = 0;
    lb_activate(0);
}

/* ---- balls (PAD-1353) -------------------------------------------------------
 * The engine keeps ONE ball saver (proc 0x191 on Wonka 03.03): "keep N balls
 * in play for T hundredths of a second".  mb_request_balls_into_play(N, T)
 * starts it or raises either; while it runs it serves balls until N are in
 * play and serves back any that drain.  Read off the decrypted code: the game's
 * own ball save is mb_request(balls in play now, s * 100) and its add-a-ball
 * mb_add_balls_into_play(n, n * 200).  So a mode's multiball, add-a-ball and
 * ball save are those calls - engine code, the same on every title. */
static void (*mb_request)(int, int), (*mb_add)(int, int), (*mb_kill_saver)(void);
static int (*saver_running)(void), (*saver_time)(void), (*balls_known)(void);
static int in_game(void);

static int ball_api(void) { return mb_request && mb_add && balls_in_play; }

/* Right after a request of ours: the saver's own clock, which only counts down
 * (in the game's time, not the wall's: the hidden rig runs slow) unless someone
 * asks again.  A request that did not raise it (the game's ran longer) is not ours. */
static void saver_note(pm_t *m, int before)
{
    int t = saver_time && saver_running && saver_running() ? saver_time() : 0;
    if (t > before) { m->saver_ours = 1; m->saver_cs = t; }
}
static int saver_now(void) { return saver_time && saver_running && saver_running() ? saver_time() : 0; }

static void serve_multiball(pm_t *m, const char *why)
{
    if (!ball_api()) { lg("\"%s\": MULTIBALL refused: this game exports no ball saver to ask", m->name); return; }
    int bip = balls_in_play(), known = balls_known ? balls_known() : -1, before = saver_now();
    mb_request(m->mb_balls, m->mb_save * 100);
    m->mb_served = 1; m->mb_served_at = now_ms(); m->one_ball_since = 0;
    saver_note(m, before);
    lg("\"%s\" MULTIBALL on %s: %d ball(s) in play asked for (%d in play, %d accounted for), ball save %d s",
       m->name, why, m->mb_balls, bip, known, m->mb_save);
}

static void add_a_ball(pm_t *m, const char *sw)
{
    if (!ball_api()) { lg("\"%s\": ADD A BALL refused: this game exports no ball saver to ask", m->name); return; }
    if (m->adds >= m->add_max) { lg("\"%s\" add a ball on %s: already %d this run", m->name, sw, m->adds); return; }
    int save = m->mb_save > 2 ? m->mb_save : 2;      /* the game's own add-a-ball saves for 2 s */
    int bip = balls_in_play(), before = saver_now();
    mb_add(1, save * 100);
    m->adds++;
    saver_note(m, before);
    lg("\"%s\" ADD A BALL on %s (%d of %d): %d in play, ball save %d s", m->name, sw, m->adds, m->add_max, bip, save);
}

static void ball_save_start(pm_t *m)
{
    if (!ball_api()) { lg("\"%s\": BALL SAVE refused: this game exports no ball saver to ask", m->name); return; }
    int bip = balls_in_play(), before = saver_now();
    mb_request(bip > 0 ? bip : 1, m->ball_save * 100);
    saver_note(m, before);
    lg("\"%s\" BALL SAVE %d s (%d in play)", m->name, m->ball_save, bip);
}

/* At the mode's end: a ball save of ours still running stops with it.  The
 * engine has one saver for everyone, so one raised since our last request
 * (its time left is more than it was then) is the game's, and left to run. */
static void saver_release(pm_t *m, const char *why)
{
    if (!m->saver_ours) return;
    m->saver_ours = 0;
    if (!saver_running || !mb_kill_saver || !saver_running()) return;
    int t = saver_now();
    if (t > m->saver_cs) {
        lg("\"%s\": the ball save was raised since ours (%d.%02d s left, %d.%02d after ours): the game's, left to run",
           m->name, t / 100, t % 100, m->saver_cs / 100, m->saver_cs % 100);
        return;
    }
    mb_kill_saver();
    lg("\"%s\": ball save ended with the mode (%s, %d.%02d s were left)", m->name, why, t / 100, t % 100);
}

/* ---- coils (PAD-1353) ------------------------------------------------------- */
typedef void (*coil_pulse_t)(void *, unsigned);
typedef void (*coil_duty_t)(void *, unsigned, unsigned, unsigned char);
static coil_pulse_t c_pulse;
static coil_duty_t c_duty;
static vfn0_t c_off;
static unsigned (*c_pattern)(int);
static pthread_mutex_t coil_mu = PTHREAD_MUTEX_INITIALIZER;

static int coil_state(wc_t *c) { return *(volatile int *)((char *)c->obj + COIL_OBJ_STATE); }

/* After the game's static constructors: each named coil checked against the
 * engine's coil_table, its own pulse time read, and the coils the game's trough
 * and plunger use (hook_*_coil) refused whatever they are called. */
static void resolve_coils(void)
{
    if (!nwc) return;
    c_pulse = (coil_pulse_t)sym("_ZN4Coil10coil_pulseEj");
    c_duty = (coil_duty_t)sym("_ZN4Coil9coil_dutyEjjh");
    c_off = (vfn0_t)sym("_ZN4Coil8coil_offEv");
    c_pattern = (unsigned (*)(int))sym("_Z21coil_get_duty_patterni");
    void **tab = sym("coil_table");
    size_t ntab = 0;
    {
        Dl_info di; const ElfW(Sym) *es = NULL;
        if (tab && dladdr1(tab, &di, (void **)&es, RTLD_DL_SYMENT) && es) ntab = es->st_size / sizeof(void *);
    }
    void *ball_coils[3] = { 0 };
    const char *bc[3] = { "hook_trough_coil", "hook_autoplunger_coil", "hook_trough_jam_coil" };
    for (int i = 0; i < 3; i++) { void **p = sym(bc[i]); if (p) ball_coils[i] = *p; }
    if (!c_pulse || !c_off || !tab || !ntab) {
        lg("coils: FAIL - Coil::coil_pulse %p, coil_off %p, coil_table %p (%zu): modes fire no coils",
           (void *)c_pulse, (void *)c_off, (void *)tab, ntab);
        for (int i = 0; i < nwc; i++) wcs[i].pulse_ok = wcs[i].hold_ok = 0;
        return;
    }
    for (int i = 0; i < nwc; i++) {
        wc_t *c = &wcs[i];
        void *o = sym(c->name);
        size_t k = 0;
        while (k < ntab && tab[k] != o) k++;
        if (!o || k == ntab) { lg("coils: %s is not in the game's coil table: not fired", c->name); c->pulse_ok = c->hold_ok = 0; continue; }
        c->obj = o;
        for (int b = 0; b < 3; b++)
            if (o == ball_coils[b] && c->pulse_ok) { lg("coils: %s is the game's %s: a mode may not fire it", c->name, bc[b] + 5); c->pulse_ok = c->hold_ok = 0; }
        int own = *(int *)((char *)o + 0x10);
        c->cap_ms = own >= 1 && own <= COIL_PULSE_MAX_MS ? own : own > COIL_PULSE_MAX_MS ? COIL_PULSE_MAX_MS : 32;
        const char *label = *(const char **)((char *)o + 8);
        lg("coils: %s \"%s\": pulse up to %d ms (the game's own %d)%s%s", c->name, label ? label : "?", c->cap_ms, own,
           c->pulse_ok ? "" : " - refused", c->hold_ok ? (coil_holds_on && c_duty && c_pattern ? ", holds on" : ", holds off") : "");
    }
}

static int within_a_minute(long *at, int *n, int cap, long t)
{
    if (t - *at >= 60000) { *at = t; *n = 0; }
    return *n < cap;
}

/* A pulse: the coil's own pulse time, or less, never more. */
static void coil_fire(pm_t *m, int ci, int ms, const char *why)
{
    if (ci < 0) return;
    wc_t *c = &wcs[ci];
    pthread_mutex_lock(&coil_mu);
    long t = now_ms();
    const char *no = NULL;
    if (!c->obj || !c->pulse_ok || !c_pulse) no = "not a coil a mode may fire";
    else if (!in_game()) no = "no ball in play";
    else if (c->holding) no = "a mode holds it";
    else if (coil_state(c)) no = "the game is driving it";
    else if (c->last_pulse && t - c->last_pulse < COIL_PULSE_GAP_MS) no = "it fired under 250 ms ago";
    else if (!within_a_minute(&c->win_at, &c->win_n, COIL_PULSES_A_MIN, t)) no = "20 pulses this minute already";
    if (no) { lg("\"%s\" %s: %s NOT fired (%s)", m->name, why, c->name, no); pthread_mutex_unlock(&coil_mu); return; }
    int use = ms > 0 && ms < c->cap_ms ? ms : c->cap_ms;
    c_pulse(c->obj, (unsigned)use);
    c->last_pulse = t; c->win_n++;
    lg("\"%s\" %s: PULSE %s %d ms%s", m->name, why, c->name, use, ms > c->cap_ms ? " (the game's own pulse is the most)" : "");
    pthread_mutex_unlock(&coil_mu);
}

/* coil_mu held.  Ends a hold of ours, unless the game drove the coil since:
 * then it is the game's, and no off is sent over it. */
static void coil_let_go(wc_t *c, const char *why)
{
    if (!c->holding) return;
    int st = coil_state(c);
    unsigned pat = *(volatile unsigned *)((char *)c->obj + COIL_OBJ_PATTERN);
    long held = now_ms() - c->held_at;
    if (st == 0 && now_ms() >= c->until - 60)
        lg("%s: hold ended at its time, %ld ms (the engine's own off)", c->name, held);
    else if ((st != 4 && st != 2) || pat != c->pattern)
        lg("%s: the game drove it during our hold (state %d after %ld ms): left to the game, no off", c->name, st, held);
    else {
        c_off(c->obj);
        lg("%s: hold OFF after %ld ms (%s)", c->name, held, why);
    }
    c->holding = 0; c->owner = NULL; c->hold_end = now_ms();
}

static void coil_hold(pm_t *m, const char *why)
{
    int ci = m->coil_hold;
    if (ci < 0) return;
    wc_t *c = &wcs[ci];
    pthread_mutex_lock(&coil_mu);
    long t = now_ms();
    const char *no = NULL;
    if (!coil_holds_on) no = "coil holds are off on this title until title.cfg says coil_holds = on";
    else if (!c->obj || !c->hold_ok || !c_duty || !c_pattern || !c_off) no = "not a coil a mode may hold";
    else if (!coil_watch_up) no = "no watchdog to end it";
    else if (!in_game()) no = "no ball in play";
    else if (c->holding) no = "it is held already";
    else if (coil_state(c)) no = "the game is driving it";
    else if (c->hold_end && t - c->hold_end < COIL_HOLD_COOL_MS) no = "3 s off between holds";
    else if (!within_a_minute(&c->hwin_at, &c->hwin_n, COIL_HOLDS_A_MIN, t)) no = "6 holds this minute already";
    if (no) { lg("\"%s\" %s: %s NOT held (%s)", m->name, why, c->name, no); pthread_mutex_unlock(&coil_mu); return; }
    int ms = m->coil_hold_ms < COIL_HOLD_MIN_MS ? COIL_HOLD_MIN_MS : m->coil_hold_ms > COIL_HOLD_MAX_MS ? COIL_HOLD_MAX_MS : m->coil_hold_ms;
    int pw = m->coil_hold_power < 1 ? 1 : m->coil_hold_power > COIL_HOLD_POWER_MAX ? COIL_HOLD_POWER_MAX : m->coil_hold_power;
    unsigned pat = c_pattern(pw);
    /* Coil::coil_duty(ms, pattern, steps): the realtime loop plays the pattern
     * for ms and then turns the coil off itself (state 4, counting +0x30 down;
     * Wonka 03.03, emulator-measured).  So the engine bounds the hold too, even
     * if this library stopped; the watchdog ends it earlier when it should. */
    c_duty(c->obj, (unsigned)ms, pat, 32);
    c->pattern = *(volatile unsigned *)((char *)c->obj + COIL_OBJ_PATTERN);
    c->owner = m; c->held_at = t; c->until = t + ms; c->holding = 1; c->hwin_n++;
    lg("\"%s\" %s: HOLD %s %d ms at %d/32 on (pattern %08x)", m->name, why, c->name, ms, pw, pat);
    pthread_mutex_unlock(&coil_mu);
}

static void coil_release_mode(pm_t *m, const char *why)
{
    pthread_mutex_lock(&coil_mu);
    for (int i = 0; i < nwc; i++) if (wcs[i].holding && wcs[i].owner == m) coil_let_go(&wcs[i], why);
    pthread_mutex_unlock(&coil_mu);
}

/* The deadline that does not trust the mode to tick: every 5 ms, off at its
 * time, at the ball's end (the game stops our run proc there), when the mode
 * stops or pauses, and given up the moment the game drives the coil itself. */
static void *coil_watch(void *arg)
{
    (void)arg;
    for (;;) {
        usleep(5000);
        pthread_mutex_lock(&coil_mu);
        long t = now_ms();
        for (int i = 0; i < nwc; i++) {
            wc_t *c = &wcs[i];
            if (!c->holding) continue;
            pm_t *m = c->owner;
            int st = coil_state(c);
            unsigned pat = *(volatile unsigned *)((char *)c->obj + COIL_OBJ_PATTERN);
            const char *why = (st != 4 && st != 2) || pat != c->pattern ? "the game"
                            : t >= c->until + 20 ? "its time" : !in_game() ? "ball end"
                            : !m || !running(m) || m->want_end ? "mode end" : m->paused ? "the mode paused" : NULL;
            if (why) coil_let_go(c, why);
        }
        pthread_mutex_unlock(&coil_mu);
    }
    return NULL;
}

/* ---- our virtuals ---------------------------------------------------------- */
static pm_t *pm_of(void *self) { for (int i = 0; i < npm; i++) if (pms[i].mode == self) return &pms[i]; return NULL; }

static void pad_start_choreo(void *self)
{
    pm_t *m = pm_of(self);
    if (!m) return;
    lg("\"%s\": start choreo", m->name);
    play(m->snd_start);
}
static void pad_total_choreo(void *self)
{
    pm_t *m = pm_of(self);
    if (m) lg("\"%s\": total choreo (mode total %lld)", m->name, m->total);
}
/* One tick of a running mode, on its run proc (either engine). */
static void mode_tick(pm_t *m)
{
    /* The lamps, from the mode's own run proc (the game's proc thread, ~125
     * ticks a second, where the game sets its own lamps) - not from the frame
     * hook, whose rate is the renderer's (about 1 a second on a busy hidden
     * rig, which aliased a 1/s blink into solid).  lamp_blink = flashes a
     * second by the clock; 0 = solid. */
    if (!m->paused && !m->want_end) {
        long half = m->lamp_blink > 0 ? 500L / m->lamp_blink : 0;
        lamps_show(m, half == 0 || ((now_ms() / (half ? half : 1)) & 1) == 0);
    }
    code_tick(m);
    if (m->music && update_music_fn) {    /* our music on while the mode has the floor, the game's otherwise */
        int idx = (int)(m - pms);
        int want = music_wanted(m), have = music_claimed == idx + 1;
        if (want != have && now_ms() - music_asked_at >= 500) music_reconsider(want ? "mode running" : "mode over or paused");
    }
}
static void pad_tick_work(void *self, int arg)
{
    (void)arg;
    pm_t *m = pm_of(self);
    if (!m) return;
    m->secs = *(int *)((char *)self + mode_seconds_off);
    mode_tick(m);
    const char *why = m->want_end;
    if (why) {      /* in the mode's own run proc: where the game itself ends a mode */
        m->want_end = NULL;
        ((vfn0_t)vslot(self, VT_END))(self);
        lg("\"%s\" ENDED by %s", m->name, why);
    }
}
/* Mode::end, then the game asked for its own music back (the mode is over). */
static uintptr_t mode_end_fn;
static void pad_end(void *self)
{
    ((vfn0_t)mode_end_fn)(self);
    pm_t *m = pm_of(self);
    if (m && m->music && music_claimed == (int)(m - pms) + 1) music_reconsider("mode ended");
}
/* a multiball with no clock, or one whose balls came on its switch, runs to one ball left */
static int timer_held(pm_t *m) { return m->paused || m->no_clock || (m->nmb_on && m->mb_served); }
static int pad_is_timer_paused(void *self)
{
    pm_t *m = pm_of(self);
    return m ? timer_held(m) : 0;
}

/* ---- the proc engine's run proc (PAD-1365) ----------------------------------
 * Mode::run_proc's loop with our own body: tick, proc_sleep(1), and a second
 * off the clock every 125 ticks the timer is not held.  It ends by returning
 * (the time, or an end asked for: completion, a multiball down to one ball,
 * game_modes = end); a ball end kills it without a return, as the game's own. */
static void proc_run(int idx)
{
    pm_t *m = &pms[idx];
    m->p_seen = 1;
    int ticks = PROC_TICKS;
    const char *why = "time";
    while (m->p_on) {
        mode_tick(m);
        if (m->want_end) { why = m->want_end; break; }
        p_sleep(1);
        if (!m->p_on) { why = "the runtime"; break; }
        if (!timer_held(m) && --ticks <= 0) {
            ticks = PROC_TICKS;
            if (m->secs > 0) m->secs--;
            if (m->secs <= 0) break;
        }
    }
    m->want_end = NULL;
    m->p_on = 0;
    lg("\"%s\" ENDED by %s (mode total %lld)", m->name, why, m->total);
    if (m->music && music_claimed == idx + 1) music_reconsider("mode ended");
}
#define PR(i) static void proc_run_##i(unsigned h) { (void)h; proc_run(i); }
PR(0) PR(1) PR(2) PR(3) PR(4) PR(5) PR(6) PR(7) PR(8) PR(9) PR(10) PR(11)
PR(12) PR(13) PR(14) PR(15) PR(16) PR(17) PR(18) PR(19) PR(20) PR(21) PR(22) PR(23)
static void (*const proc_runs[])(unsigned) = {
    proc_run_0, proc_run_1, proc_run_2, proc_run_3, proc_run_4, proc_run_5, proc_run_6, proc_run_7, proc_run_8,
    proc_run_9, proc_run_10, proc_run_11, proc_run_12, proc_run_13, proc_run_14, proc_run_15, proc_run_16,
    proc_run_17, proc_run_18, proc_run_19, proc_run_20, proc_run_21, proc_run_22, proc_run_23 };
_Static_assert(sizeof proc_runs / sizeof *proc_runs == MAX_MODES, "one run proc per mode slot");

/* The proc engine's pieces, all engine functions exported on both generations. */
static int proc_api(void)
{
    p_cret = (unsigned (*)(unsigned, void (*)(unsigned), int))sym("_Z9proc_cretjPFvjE14proc_survive_t");
    p_create = (unsigned (*)(unsigned, void (*)(unsigned), int, int))sym("_Z11proc_createjPFvjE18proc_create_flag_t14proc_survive_t");
    p_sleep = (void (*)(unsigned))sym("_Z10proc_sleepj");
    p_exists = (int (*)(unsigned))sym("_Z14proc_id_existsj");
    score_up = (unsigned long long (*)(unsigned long long, int))sym("_Z22score_add_to_player_upyb");
    return (p_cret || p_create) && p_sleep && p_exists && score_up;
}

/* Find each virtual by address.  `nth` picks among equal addresses: the
 * compiler folds identical empty bodies (GnR: is_timer_paused ==
 * ModeManager::hook_start_final_mode; the start and total choreo hooks are one
 * body), and vtable order is declaration order. */
static int vt_find(const char *mangled, int nth, int after)
{
    uintptr_t a = (uintptr_t)sym(mangled);
    if (!a || !mode_vt) return -1;
    for (int i = 2; i < MODE_VT_SLOTS; i++)
        if (mode_vt[i] == a && (i - 2) * 8 > after && nth-- == 0) return (i - 2) * 8;
    return -1;
}

static int resolve_vtable(void)
{
    mode_vt = (uintptr_t *)need("_ZTV4Mode");
    if (!mode_vt) return 0;
    VT_START = vt_find("_ZN4Mode5startEv", 0, -1);
    VT_END = vt_find("_ZN4Mode3endEv", 0, -1);
    VT_SET_TIME = vt_find("_ZN4Mode8set_timeEi", 0, -1);
    VT_IS_RUNNING = vt_find("_ZN4Mode10is_runningEv", 0, -1);
    VT_TIMER_PAUSED = vt_find("_ZN4Mode15is_timer_pausedEv", 0, -1);
    VT_SCORE = vt_find("_ZN4Mode15score_and_totalEy", 0, -1);
    VT_TICK = vt_find("_ZN4Mode14hook_tick_workEi", 0, -1);
    /* the two choreo hooks come right after hook_tick_work */
    VT_START_CHOREO = vt_find("_ZN4Mode25hook_do_mode_start_choreoEv", 0, VT_TICK);
    VT_TOTAL_CHOREO = vt_find("_ZN4Mode25hook_do_mode_total_choreoEv", 0, VT_START_CHOREO);
    if (VT_TOTAL_CHOREO < 0 && VT_START_CHOREO >= 0) VT_TOTAL_CHOREO = vt_find("_ZN4Mode25hook_do_mode_start_choreoEv", 1, VT_TICK);
    lg("Mode vtable: start %#x end %#x set_time %#x is_running %#x timer_paused %#x score %#x tick %#x "
       "start_choreo %#x total_choreo %#x", VT_START, VT_END, VT_SET_TIME, VT_IS_RUNNING, VT_TIMER_PAUSED,
       VT_SCORE, VT_TICK, VT_START_CHOREO, VT_TOTAL_CHOREO);
    return VT_START >= 0 && VT_END >= 0 && VT_SET_TIME >= 0 && VT_IS_RUNNING >= 0 && VT_TIMER_PAUSED >= 0
           && VT_SCORE >= 0 && VT_TICK >= 0 && VT_START_CHOREO >= 0;
}

static int build_mode(pm_t *m, int idx)
{
    if (m->mode) return 1;
    if (engine_proc) {          /* no engine object: m->mode only marks the mode built (and ours) */
        m->mode = calloc(1, 16);
        m->pid = 0x7e00 + idx * 3;    /* clear of the game's (Wonka: 0x7531-0x7535 the highest seen) */
        return 1;
    }
    if (!mode_ctor) return 0;
    m->mode = calloc(1, MODE_OBJ_BYTES);
    /* ids and proc ids clear of the game's (GnR's modes: 0..911, procs 0x27xx-0x28xx) */
    mode_ctor(m->mode, m->name, 990 + idx, NULL, NULL, 0x7e00 + idx * 3, 0x7e01 + idx * 3, 0x7e02 + idx * 3, NULL, NULL);
    if (our_vt[0] == 0 && our_vt[1] == 0) {
        memcpy(our_vt, mode_vt, sizeof our_vt);
        uintptr_t *slots = &our_vt[2];
        slots[VT_START_CHOREO / 8] = (uintptr_t)pad_start_choreo;
        if (VT_TOTAL_CHOREO >= 0) slots[VT_TOTAL_CHOREO / 8] = (uintptr_t)pad_total_choreo;
        slots[VT_TICK / 8] = (uintptr_t)pad_tick_work;
        slots[VT_TIMER_PAUSED / 8] = (uintptr_t)pad_is_timer_paused;
        mode_end_fn = mode_vt[2 + VT_END / 8];
        slots[VT_END / 8] = (uintptr_t)pad_end;
        if (mode_start_fn) slots[VT_START / 8] = mode_start_fn;   /* _ZTV4Mode's own slots are gated (PAD-1348) */
        if (mode_re_slot >= 0 && sym("_ZN4Mode7restartEv")) slots[mode_re_slot / 8] = (uintptr_t)sym("_ZN4Mode7restartEv");
    }
    if (*(uintptr_t **)m->mode != mode_vt + 2)
        lg("WARN ctor vptr %p != Mode vtable %p", *(void **)m->mode, (void *)(mode_vt + 2));
    *(uintptr_t **)m->mode = &our_vt[2];
    return 1;
}

static int running(pm_t *m)
{
    if (!m->mode) return 0;
    if (engine_proc)      /* on, and its proc alive (or not yet run: made, waiting for its first turn) */
        return m->p_on && ((p_exists(m->pid) & 0xff) || (!m->p_seen && now_ms() - m->p_at < 2000));
    return ((vbool_t)vslot(m->mode, VT_IS_RUNNING))(m->mode) & 0xff;
}
/* Points through the game's scoring: Mode::score_and_total, or (the proc
 * engine) the call it makes itself. */
static void mode_score(pm_t *m, long long pts)
{
    if (engine_proc) {
        unsigned long long got = score_up((unsigned long long)pts, 0);
        lg("\"%s\": the game scored %llu (score_add_to_player_up)", m->name, got);
    }
    else ((vull_t)vslot(m->mode, VT_SCORE))(m->mode, (unsigned long long)pts);
}
static int any_ours_running(void) { for (int i = 0; i < npm; i++) if (running(&pms[i])) return 1; return 0; }

static void start_mode(pm_t *m, int idx)
{
    if (!build_mode(m, idx)) return;
    m->hits = 0; m->total = 0; m->paused = 0; m->ended_logged = 0; m->running_seen = 1;
    m->mb_served = m->mb_seen2 = m->adds = m->saver_ours = m->saver_cs = 0; m->mb_served_at = m->one_ball_since = 0;
    m->pending = NULL; m->combo_pos = 0; m->runs_ball++; m->runs_game++;
    m->want_end = NULL;         /* an end asked for at a ball end the game got to first is not this run's */
    if (engine_proc) {
        m->secs = m->seconds; m->p_seen = 0; m->p_at = now_ms(); m->p_on = 1;
        unsigned h = p_cret ? p_cret(m->pid, proc_runs[idx], 0) : p_create(m->pid, proc_runs[idx], 2, 0);
        if (!h) { m->p_on = 0; m->running_seen = 0; lg("\"%s\": FAIL - the engine made no proc %#x", m->name, m->pid); return; }
        if (upd_soon) upd_soon();
        lg("\"%s\": start choreo (proc %#x, handle %u)", m->name, m->pid, h);
        play(m->snd_start);
    } else {
        ((vbool_t)vslot(m->mode, VT_START))(m->mode);
        ((vint_t)vslot(m->mode, VT_SET_TIME))(m->mode, m->seconds);
        /* The seconds field: 0x48 on GnR.  Check it, and find it if a title moved it. */
        if (*(int *)((char *)m->mode + mode_seconds_off) != m->seconds) {
            for (int off = 0x20; off < 0x200; off += 4)
                if (*(int *)((char *)m->mode + off) == m->seconds) {
                    lg("mode seconds field is at %#x on this title (not %#x)", off, mode_seconds_off);
                    mode_seconds_off = off; break;
                }
        }
    }
    m->secs = m->seconds;
    if (m->no_clock) lg("\"%s\" STARTED (no clock: one ball left ends it)", m->name);
    else lg("\"%s\" STARTED for %d s", m->name, m->seconds);
    if (m->mb_balls && !m->nmb_on) serve_multiball(m, "the start");
    else if (m->mb_balls) lg("\"%s\": the multiball waits for its switch (%d s to hit it)", m->name, m->seconds);
    else if (m->ball_save) ball_save_start(m);
    coil_fire(m, m->coil_start, m->coil_start_ms, "start");
    if (m->hold_on == 1) coil_hold(m, "start");
    if (*m->vid_file && !m->vid) m->vid = video_start(m);
    if (m->music) music_reconsider("mode started");
    code_started(m);
}

/* Mode::end runs on the game's proc thread like all the game's own mode
 * changes: called from a proc (a switch dispatch) it ends the mode at once;
 * called from the render thread it is handed to the mode's own tick hook. */
static int (*am_proc)(void);
static void end_mode(pm_t *m, const char *why)
{
    if (!running(m)) return;
    if (!m->end_why) m->end_why = why;
    if (engine_proc) {          /* our run proc ends itself within a tick (8 ms) */
        if (!m->want_end) { m->want_end = why; m->paused = 0; lg("\"%s\" ending (%s)", m->name, why); }
        return;
    }
    if (am_proc && !am_proc()) {
        if (!m->want_end) { m->want_end = why; m->paused = 0; lg("\"%s\" ending (%s)", m->name, why); }
        return;
    }
    ((vfn0_t)vslot(m->mode, VT_END))(m->mode);
    lg("\"%s\" ENDED by %s", m->name, why);
}

/* ---- the game's own modes, changed (PAD-1351) ------------------------------
 * A <name>.stock file in the mode folder names one of the GAME's modes - its
 * global (Wonka 03.03: cl_mode is Candy Lane) or its class (CandyLaneMode) -
 * and changes how it plays.  No game code is patched: only slots of that
 * class's vtable (relocated read-only data, made writable for the store, as
 * the hold gate does).  Read off Wonka 03.03's decrypted engine:
 *   timer   Mode::start sets a default and each class then sets its own (the
 *           Wonka Bar award modes from an adjustment, 60 - 15 x the setting,
 *           into a timer the class keeps itself).  The mode's run proc is
 *           Mode::start_run_func, which jumps through the class's run_proc
 *           slot: ours runs first and calls the class's own set_time (a
 *           virtual).  With the run proc alive, set_time's restart is a no-op,
 *           exactly as when the game sets a time.
 *   points  every award a mode makes goes through this->score_and_total.  The
 *           game's call sites check the slot still holds the class's own
 *           function and call the slot when it does not, so ours sees every
 *           award and scales or replaces it.
 *   shots   a made shot reaches each mode by a DIRECT call to its class's
 *           shot_dispatch (no vtable), which reads the shot from its proc's
 *           argument (shot_get_proc_shot_id) and first asks this->is_running
 *           (or _or_grace, _or_grace_grace) through the vtable.  Those slots
 *           are wrapped: asked from inside the class's own shot_dispatch (the
 *           return address says so) about a shot in shots_off, the mode
 *           answers "not running" and the shot goes by it.  shots_add gives
 *           the mode a shot when a switch is hit: from the switch's own proc,
 *           the shot id is set (shot_set_proc_shot_id, or the proc argument
 *           shot_get_proc_shot_id reads) and the class's shot_dispatch called.
 * Shot names come from the game's shot table (one entry per shot id, each
 * pointing at its exported shot_made_<name> handler), found in the game's own
 * data by those handlers' addresses; the runtime logs it. */
/* -- the shot table ----------------------------------------------------------- */
static uintptr_t sfn[MAX_SHOT_FNS], sfn_lo, sfn_hi; static char sfn_name[MAX_SHOT_FNS][48]; static int nsfn;
static void cb_shot_fns(const char *name, uintptr_t a, size_t sz)
{
    (void)sz;
    if (strncmp(name, "_Z", 2) || nsfn >= MAX_SHOT_FNS) return;
    const char *p = name + 2;
    while (*p >= '0' && *p <= '9') p++;
    if (strncmp(p, "shot_made_", 10)) return;
    size_t L = strlen(p + 10);
    if (L < 2 || p[10 + L - 1] != 'v') return;       /* takes no arguments: one handler per shot */
    sfn[nsfn] = a;
    snprintf(sfn_name[nsfn], sizeof sfn_name[0], "%.*s", (int)(L - 1), p + 10);
    nsfn++;
}
static int sfn_index(uintptr_t v) { for (int i = 0; i < nsfn; i++) if (sfn[i] == v) return i; return -1; }

static void normalise(char *out, size_t n, const char *in)
{
    size_t o = 0; int us = 0;
    for (; *in && o + 1 < n; in++) {
        char c = *in;
        if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) { out[o++] = c; us = 0; }
        else if (o && !us) { out[o++] = '_'; us = 1; }
    }
    while (o && out[o - 1] == '_') o--;
    out[o] = 0;
}

/* The game's shot table, by the addresses of its shot_made_* handlers in the
 * game's own (non-code) segments: entries of one stride, each with its shot id
 * a fixed distance from the handler pointer.  jjpstock.py shot_table does the
 * same on a live game's memory. */
#define MAX_HITS 1024
static void read_shot_table(void)
{
    walk_dynsym_type(STT_FUNC, cb_shot_fns);
    if (!nsfn) { lg("shots: no shot_made_* handlers exported; shots are named by number"); return; }
    sfn_lo = sfn_hi = sfn[0];
    for (int i = 1; i < nsfn; i++) { if (sfn[i] < sfn_lo) sfn_lo = sfn[i]; if (sfn[i] > sfn_hi) sfn_hi = sfn[i]; }
    char exe[512]; ssize_t L = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (L <= 0) return;
    exe[L] = 0;
    static uintptr_t hit[MAX_HITS], hlo[MAX_HITS], hhi[MAX_HITS]; static short hfn[MAX_HITS]; int nh = 0;
    FILE *f = fopen("/proc/self/maps", "r");
    if (!f) return;
    char line[700];
    while (fgets(line, sizeof line, f) && nh < MAX_HITS) {
        char *dash = strchr(line, '-'), *sp = dash ? strchr(dash, ' ') : NULL;
        if (!sp || sp[1] != 'r') continue;   /* the Envelope maps the game's data rwx: code segments too */
        char *path = strchr(line, '/');
        if (!path) continue;
        path[strcspn(path, "\n")] = 0;
        if (strcmp(path, exe)) continue;
        uintptr_t lo = hexnum(line), hi = hexnum(dash + 1);
        for (uintptr_t a = (lo + 7) & ~(uintptr_t)7; a + 8 <= hi && nh < MAX_HITS; a += 8) {
            uintptr_t w = *(uintptr_t *)a;
            if (w < sfn_lo || w > sfn_hi) continue;
            int i = sfn_index(w);
            if (i >= 0) { hit[nh] = a; hlo[nh] = lo; hhi[nh] = hi; hfn[nh++] = (short)i; }
        }
    }
    fclose(f);
    if (nh < 4) { lg("shots: the shot table was not found (%d handler pointers); shots are named by number", nh); return; }
    /* the stride: the most common gap between neighbouring hits */
    uintptr_t best_gap = 0; int best_n = 0;
    for (int i = 1; i < nh; i++) {
        uintptr_t g = hit[i] - hit[i - 1]; int n = 0;
        if (g < 16 || g > 512) continue;
        for (int j = 1; j < nh; j++) if (hit[j] - hit[j - 1] == g) n++;
        if (n > best_n) { best_n = n; best_gap = g; }
    }
    if (!best_gap) { lg("shots: no stride in %d handler pointers; shots are named by number", nh); return; }
    /* the longest run of hits a whole number of strides apart (missing entries allowed) */
    int bs = 0, bl = 0;
    for (int i = 0; i < nh;) {
        int j = i + 1;
        while (j < nh && (hit[j] - hit[j - 1]) % best_gap == 0 && (hit[j] - hit[j - 1]) / best_gap <= 8) j++;
        if (j - i > bl) { bl = j - i; bs = i; }
        i = j;
    }
    /* the id: an int a fixed distance from the pointer that counts up one per entry */
    int id_at = 0; int found = 0;
    for (int d = -(int)best_gap + 4; d < (int)best_gap && !found; d += 4) {
        if (d == 0 || d == 4) continue;
        int inside = 1;     /* every probe within the mapping its pointer is in */
        for (int j = bs; inside && j < bs + bl; j++)
            inside = (intptr_t)hit[j] + d >= (intptr_t)hlo[j] && hit[j] + (uintptr_t)(intptr_t)d + 4 <= hhi[j];
        if (!inside) continue;
        int base = *(int *)(hit[bs] + d), ok = base >= 0 && base < MAX_SHOT_IDS;
        for (int j = bs + 1; ok && j < bs + bl; j++)
            ok = *(int *)(hit[j] + d) == base + (int)((hit[j] - hit[bs]) / best_gap);
        if (ok) { id_at = d; found = 1; }
    }
    const char *(*disp)(int) = (const char *(*)(int))sym("_Z13get_shot_name9shot_id_t");
    if (!disp) disp = (const char *(*)(int))sym("_Z13get_shot_name10_shot_id_e");
    nshots = 0;
    for (int j = bs; j < bs + bl && nshots < MAX_SHOT_IDS; j++) {
        int id = found ? *(int *)(hit[j] + id_at) : (int)((hit[j] - hit[bs]) / best_gap);
        shots[nshots].id = id;
        snprintf(shots[nshots++].name, sizeof shots[0].name, "%s", sfn_name[hfn[j]]);
    }
    /* one handler for several shots (Wonka: slings, jets, the 3-bank): the
     * game's own display names when each is distinct, else <name>_<id> */
    static char seen[MAX_SHOT_IDS];
    memset(seen, 0, sizeof seen);
    for (int i = 0; i < nshots; i++) {
        if (seen[i]) continue;
        int grp[MAX_SHOT_IDS], ng = 0;
        for (int j = i; j < nshots; j++) if (!strcmp(shots[j].name, shots[i].name)) { grp[ng++] = j; seen[j] = 1; }
        if (ng < 2) continue;
        char dn[MAX_SHOT_IDS][48]; int distinct = disp != NULL;
        for (int g = 0; g < ng && distinct; g++) {
            const char *s = disp(shots[grp[g]].id);
            normalise(dn[g], sizeof dn[g], s ? s : "");
            if (!dn[g][0]) distinct = 0;
            for (int h = 0; h < g && distinct; h++) if (!strcmp(dn[g], dn[h])) distinct = 0;
            for (int h = 0; h < nshots && distinct; h++) if (!strcmp(dn[g], shots[h].name)) distinct = 0;
        }
        for (int g = 0; g < ng; g++) {
            shot_t *s = &shots[grp[g]];
            if (distinct) snprintf(s->name, sizeof s->name, "%s", dn[g]);
            else if (g) { char t[48]; snprintf(t, sizeof t, "%.40s_%d", s->name, s->id); snprintf(s->name, sizeof s->name, "%s", t); }
        }
    }
    char out[4096]; size_t o = 0; out[0] = 0;
    for (int i = 0; i < nshots && o < sizeof out - 64; i++)
        o += snprintf(out + o, sizeof out - o, "%s%d %s", i ? ", " : "", shots[i].id, shots[i].name);
    lg("shots: %d in the game's table (stride %lu, id %s): %s", nshots, (unsigned long)best_gap,
       found ? "read from it" : "by position", out);
}

static int shot_by_name(const char *n)
{
    if (*n >= '0' && *n <= '9') return (int)num(n);
    for (int i = 0; i < nshots; i++) if (!strcmp(shots[i].name, n)) return shots[i].id;
    return -1;
}
static const char *shot_name(int id)
{
    for (int i = 0; i < nshots; i++) if (shots[i].id == id) return shots[i].name;
    static char b[16]; snprintf(b, sizeof b, "#%d", id); return b;
}

/* -- the wrapped slots ------------------------------------------------------------ */
static sc_t *sc_of(uintptr_t vt) { for (int i = 0; i < nsc; i++) if (scs[i].vt == vt) return &scs[i]; return NULL; }
static st_t *st_of(void *self)
{
    for (int i = 0; i < nst; i++) if (sts[i].ok && sts[i].obj == self) return &sts[i];
    return NULL;
}

static int st_isr(void *self, int k, void *ra)
{
    sc_t *c = sc_of(*(uintptr_t *)self);
    if (!c || !c->orig_isr[k]) return 0;
    int r = ((vbool_t)c->orig_isr[k])(self) & 0xff;
    if (!r || !stock_ready || (uintptr_t)ra < c->sd_lo || (uintptr_t)ra >= c->sd_hi || !get_shot) return r;
    st_t *s = st_of(self);
    if (!s || !s->noff) return r;
    int shot = get_shot();
    for (int i = 0; i < s->noff; i++)
        if (s->off[i] == shot) {
            s->blocked++;
            lg("STOCK %s: shot %s goes by it (shots_off, %s)", s->mode, shot_name(shot), s->file);
            return 0;
        }
    return r;
}
static int st_isr0(void *s) { return st_isr(s, 0, __builtin_return_address(0)); }
static int st_isr1(void *s) { return st_isr(s, 1, __builtin_return_address(0)); }
static int st_isr2(void *s) { return st_isr(s, 2, __builtin_return_address(0)); }
static int (*const isr_wrap[3])(void *) = { st_isr0, st_isr1, st_isr2 };

static void st_run(void *self, unsigned arg)
{
    sc_t *c = sc_of(*(uintptr_t *)self);
    st_t *s = st_of(self);
    if (s && stock_ready && s->seconds > 0 && VT_SET_TIME >= 0) {
        ((void (*)(void *, int))vslot(self, VT_SET_TIME))(self, s->seconds);
        lg("STOCK %s: timer set to %d s (%s)", s->mode, s->seconds, s->file);
    }
    if (c && c->orig_run) ((void (*)(void *, unsigned))c->orig_run)(self, arg);
}

static unsigned long long st_score(void *self, unsigned long long amt)
{
    sc_t *c = sc_of(*(uintptr_t *)self);
    st_t *s = st_of(self);
    unsigned long long a = amt;
    if (s && stock_ready && amt) {
        if (s->points > 0) a = (unsigned long long)s->points;
        else if (s->points_x != 1000) a = amt / 1000 * (unsigned long long)s->points_x
                                          + amt % 1000 * (unsigned long long)s->points_x / 1000;
        s->asked += (long long)amt; s->scored += (long long)a; s->nscores++;
        int shot = get_shot && am_proc && am_proc() ? get_shot() : -1;
        lg("STOCK %s: award %llu (the game's own %llu)%s%s", s->mode, a, amt, shot >= 0 ? ", shot " : "",
           shot >= 0 ? shot_name(shot) : "");
    }
    return c && c->orig_score ? ((unsigned long long (*)(void *, unsigned long long))c->orig_score)(self, a) : 0;
}

static int wrap_slot(uintptr_t vt, int off, uintptr_t fn, uintptr_t *orig)
{
    if (off < 0) return 0;
    uintptr_t *slot = (uintptr_t *)(vt + (uintptr_t)off);
    if (*slot == fn) return 1;
    *orig = *slot;
    if (!store_slot(slot, fn)) { *orig = 0; return 0; }
    return 1;
}

static sc_t *sc_wire(uintptr_t vt, int need)
{
    sc_t *c = sc_of(vt);
    if (!c) {
        if (nsc >= MAX_STOCK) return NULL;
        c = &scs[nsc++]; memset(c, 0, sizeof *c); c->vt = vt;
        char n[200]; const char *cn = class_name(vt);
        snprintf(n, sizeof n, "_ZN%zu%s13shot_dispatchEv", strlen(cn), cn);
        void *sd = sym(n); Dl_info di; ElfW(Sym) *es = NULL;
        if (sd && dladdr1(sd, &di, (void **)&es, RTLD_DL_SYMENT) && es && es->st_size) {
            c->sd_lo = (uintptr_t)sd; c->sd_hi = (uintptr_t)sd + es->st_size;
        }
    }
    int w = need & ~c->wired;
    if ((w & NEED_TIMER) && wrap_slot(vt, VT_RUN, (uintptr_t)st_run, &c->orig_run)) c->wired |= NEED_TIMER;
    if ((w & NEED_POINTS) && wrap_slot(vt, VT_SCORE, (uintptr_t)st_score, &c->orig_score)) c->wired |= NEED_POINTS;
    if (w & NEED_SHOTS) {
        int ok = 1;
        for (int k = 0; k < 3; k++)
            if (VT_ISR[k] >= 0) ok &= wrap_slot(vt, VT_ISR[k], (uintptr_t)isr_wrap[k], &c->orig_isr[k]);
        if (ok) c->wired |= NEED_SHOTS;
    }
    return c;
}

static uintptr_t find_vt; static void *found_obj;
static void cb_obj_of_vt(const char *name, uintptr_t a, size_t sz)
{
    (void)name;
    if (!found_obj && sz >= 0x60 && *(uintptr_t *)a == find_vt) found_obj = (void *)a;
}

/* The mode a .stock file names: a game global whose vtable derives Mode, or a
 * class name (its object found by vtable). */
static void stock_resolve(st_t *s)
{
    uintptr_t vt = 0; void *o = sym(s->mode);
    if (o && *(uintptr_t *)o) vt = *(uintptr_t *)o;
    else {
        char n[200]; snprintf(n, sizeof n, "_ZTV%zu%s", strlen(s->mode), s->mode);
        uintptr_t v = (uintptr_t)sym(n);
        if (v) { vt = v + 16; find_vt = vt; found_obj = NULL; walk_dynsym(cb_obj_of_vt); o = found_obj; }
    }
    if (!vt || !o) { lg("STOCK %s: no mode called %s in this game (a mode global or its class)", s->file, s->mode); return; }
    if (!ti_mode || !derives(((uintptr_t *)vt)[-1], ti_mode, 0) || (mode_vt && vt == (uintptr_t)(mode_vt + 2))) {
        lg("STOCK %s: %s (%s) is not one of the game's modes", s->file, s->mode, class_name(vt));
        return;
    }
    for (int i = 0; i < nst; i++)
        if (&sts[i] != s && sts[i].ok && sts[i].obj == o) {
            lg("STOCK %s: %s is already changed by %s; this file ignored", s->file, s->mode, sts[i].file);
            return;
        }
    s->obj = o;
    /* the shots, now the table is read */
    char buf[512]; snprintf(buf, sizeof buf, "%s", s->off_names);
    for (char *t = strtok(buf, " ,\t"); t && s->noff < MAX_LIST; t = strtok(NULL, " ,\t")) {
        int id = shot_by_name(t);
        if (id < 0) lg("STOCK %s: no shot called %s in this game (shots_off)", s->file, t);
        else s->off[s->noff++] = id;
    }
    for (int i = 0; i < s->nadd; i++) {
        s->add_shot[i] = shot_by_name(s->add_name[i]);
        if (s->add_shot[i] < 0) lg("STOCK %s: no shot called %s in this game (shots_add)", s->file, s->add_name[i]);
    }
    int need = (s->seconds > 0 ? NEED_TIMER : 0) | (s->points > 0 || s->points_x != 1000 ? NEED_POINTS : 0)
             | (s->noff ? NEED_SHOTS : 0) | NEED_POINTS;   /* awards are always logged */
    s->c = sc_wire(vt, need);
    if (!s->c) { lg("STOCK %s: too many changed classes (max %d)", s->file, MAX_STOCK); return; }
    if ((s->noff || s->nadd) && !s->c->sd_lo)
        lg("STOCK %s: %s has no shot_dispatch of its own; shots_off / shots_add do nothing for it", s->file, class_name(vt));
    if ((need & ~s->c->wired) & (NEED_TIMER | NEED_POINTS | NEED_SHOTS))
        lg("STOCK %s: could not wrap every slot it needs (wanted %#x, have %#x)", s->file, need, s->c->wired);
    s->ok = 1;
    char pts[64];
    if (s->points > 0) snprintf(pts, sizeof pts, "%lld an award", s->points);
    else if (s->points_x != 1000) snprintf(pts, sizeof pts, "x%ld.%03ld", s->points_x / 1000, s->points_x % 1000);
    else snprintf(pts, sizeof pts, "the game's");
    lg("STOCK %s: %s (%s, %p): timer %s%d, points %s, %d shot(s) off, %d added%s", s->file, s->mode,
       class_name(vt), o, s->seconds > 0 ? "" : "the game's/", s->seconds, pts, s->noff, s->nadd,
       s->c->sd_lo ? "" : " (no shot_dispatch)");
}

/* Main thread, first frame after install: the game is fully up (its shot
 * table and objects built), and any engine call here is on a game thread. */
static void stock_install(void)
{
    types_init();
    VT_RUN = byte_off_in("_ZTV4Mode", "_ZN4Mode8run_procEj");
    VT_ISR[0] = byte_off_in("_ZTV4Mode", "_ZN4Mode10is_runningEv");
    VT_ISR[1] = byte_off_in("_ZTV4Mode", "_ZN4Mode19is_running_or_graceEv");
    VT_ISR[2] = byte_off_in("_ZTV4Mode", "_ZN4Mode25is_running_or_grace_graceEv");
    get_shot = (int (*)(void))sym("_Z21shot_get_proc_shot_idv");
    set_shot_fn = (void (*)(int))sym("_Z21shot_set_proc_shot_id9shot_id_t");
    if (!set_shot_fn) set_shot_fn = (void (*)(int))sym("_Z21shot_set_proc_shot_id10_shot_id_e");
    proc_handle = (unsigned (*)(void))sym("_Z18proc_get_my_handlev");
    proc_setarg = (void (*)(unsigned, int, long))sym("_Z12proc_set_argji11proc_args_t");
    lg("stock: run_proc %#x, score %#x, set_time %#x, is_running %#x/%#x/%#x; shot id %s, set by %s",
       VT_RUN, VT_SCORE, VT_SET_TIME, VT_ISR[0], VT_ISR[1], VT_ISR[2], get_shot ? "read" : "NOT READABLE",
       set_shot_fn ? "shot_set_proc_shot_id" : proc_setarg ? "the proc argument" : "nothing");
    read_shot_table();
    for (int i = 0; i < nst; i++) stock_resolve(&sts[i]);
    stock_ready = 1;
}

static int set_shot(int id)
{
    if (set_shot_fn) { set_shot_fn(id); return 1; }
    if (shot_arg < 0 && get_shot) {
        /* shot_get_proc_shot_id = proc_get_arg(proc_get_my_handle(), N): N is
         * its `mov $N,%esi` (be N 00 00 00), readable once the game has called it */
        const unsigned char *c = (const unsigned char *)get_shot;
        for (int i = 0; i < 40; i++)
            if (c[i] == 0xbe && c[i + 2] == 0 && c[i + 3] == 0 && c[i + 4] == 0 && c[i + 1] < 16) { shot_arg = c[i + 1]; break; }
        if (shot_arg < 0) { shot_arg = -2; lg("stock: the shot's proc argument could not be read; shots_add does nothing"); }
        else lg("stock: a shot is the proc's argument %d", shot_arg);
    }
    if (shot_arg < 0 || !proc_handle || !proc_setarg) return 0;
    proc_setarg(proc_handle(), shot_arg, id);
    return 1;
}

/* A switch hit (its own proc, after the game's dispatch): shots_add. */
static void stock_on_switch(int si)
{
    if (!stock_ready) return;
    for (int i = 0; i < nst; i++) {
        st_t *s = &sts[i];
        if (!s->ok || !s->c || !s->c->sd_lo) continue;
        for (int k = 0; k < s->nadd; k++) {
            if (s->add_sw[k] != si || s->add_shot[k] < 0) continue;
            if (!(((vbool_t)vslot(s->obj, VT_IS_RUNNING))(s->obj) & 0xff)) continue;
            int old = get_shot ? get_shot() : -1;
            if (!set_shot(s->add_shot[k])) continue;
            s->added++;
            lg("STOCK %s: %s gives it shot %s (shots_add, %s)", s->mode, wsw[si].name, shot_name(s->add_shot[k]), s->file);
            ((vbool_t)s->c->sd_lo)(s->obj);
            if (old >= 0) set_shot(old);
        }
    }
}

/* Every frame: install once, then log each changed mode's runs. */
static void stock_frame(void)
{
    if (!nst || !installed) return;
    if (!stock_ready) { stock_install(); return; }
    for (int i = 0; i < nst; i++) {
        st_t *s = &sts[i];
        if (!s->ok) continue;
        int r = ((vbool_t)vslot(s->obj, VT_IS_RUNNING))(s->obj) & 0xff;
        if (r && !s->was_running) {
            s->started_ms = now_ms(); s->asked = s->scored = 0; s->nscores = s->blocked = s->added = 0;
            lg("STOCK %s STARTED (the game's own %s)", s->mode, class_name(*(uintptr_t *)s->obj));
        } else if (!r && s->was_running) {
            long t = now_ms() - s->started_ms;
            lg("STOCK %s ENDED after %ld.%ld s: %d award(s), %lld scored (the game's own %lld), %d shot(s) let by, %d added",
               s->mode, t / 1000, t % 1000 / 100, s->nscores, s->scored, s->asked, s->blocked, s->added);
        }
        s->was_running = r;
    }
}

/* ---- game state ------------------------------------------------------------ */
static int in_game(void) { return state_get && state_get() == ingame_state; }

/* Recursive: the game's score hook fires inside our own scoring (on_switch holds mu). */
static pthread_mutex_t mu = PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP;
static int in_list(const int *l, int n, int v) { for (int i = 0; i < n; i++) if (l[i] == v) return 1; return 0; }

/* Test hook for the emulator, where no ball can reach a game mode's start:
 * JJP_MODS_TEST_GAMEMODE=<Mode global> JJP_MODS_TEST_SWITCH=<switch> starts
 * that game mode (its own Mode::start) when that switch is hit, so a proof run
 * can show a custom mode yielding to it.  Unset on a machine. */
static void *test_gm; static int test_sw = -1, test_end_sw = -1;   /* JJP_MODS_TEST_END_SWITCH ends it (PAD-1354) */
static void test_hook(int si)
{
    if (VT_START < 0 || VT_END < 0 || VT_IS_RUNNING < 0) return;    /* a title with no Mode class */
    if (si == test_end_sw && test_gm && (((vbool_t)vslot(test_gm, VT_IS_RUNNING))(test_gm) & 0xff)) {
        lg("TEST: ending game mode %s", getenv("JJP_MODS_TEST_GAMEMODE"));
        ((vfn0_t)vslot(test_gm, VT_END))(test_gm);
        return;
    }
    if (si != test_sw || !test_gm) return;
    if (((vbool_t)vslot(test_gm, VT_IS_RUNNING))(test_gm) & 0xff) return;
    lg("TEST: starting game mode %s", getenv("JJP_MODS_TEST_GAMEMODE"));
    ((vbool_t)vslot(test_gm, VT_START))(test_gm);
}

/* ---- start rules (PAD-1354) ------------------------------------------------
 * Besides its start switches a mode can start on a game event (start_on), when
 * one of the game's modes ends (start_after), when the player up's score
 * reaches a value (start_score), or on a combo of switches in order
 * (start_combo).  The events are the game's own hook lists: each
 * Hook<HookX_, Arg>::list global is a FastLinkedList, head {first, magic 0x45},
 * node {int prio, desc *, name, next at +0x18}, desc {fn, name}.  The game
 * walks it (node->desc->fn(arg), stopping at a return > 0) wherever that event
 * happens.  We add one node of ours at the tail of each list a rule needs (an
 * aligned pointer store; the game's own nodes run first), and our fn returns 0.
 *
 * A rule never starts a mode inside the hook: the ball-start hooks run before
 * the ball is in play.  It raises the start (start_count counts it), and the
 * start is done on the game's proc thread at the first moment this ball when
 * no mode of ours runs and nothing the mode yields to does: our nodes on the
 * game's lamp-render, update and switch-dispatch hooks are those moments.  A
 * raised start not done by the ball's end is dropped. */
typedef struct { void *fn; const char *name; } hdesc_t;
typedef struct hnode { int prio, pad; hdesc_t *desc; const char *name; struct hnode *next; char room[64]; } hnode_t;
#define MAX_HOOKS 16
static hnode_t hnodes[MAX_HOOKS];
static hdesc_t hdescs[MAX_HOOKS];
static int nhooks;
static unsigned events_hooked;          /* bit i = EVENTS[i] has our node */
static unsigned want_events;            /* bit i = a loaded mode uses EVENTS[i] */
static long long (*score_get)(int);     /* score_get_player_score(1..4) */
static int (*player_up)(void);          /* game_flow_get_player_up(): 1..4 */
static unsigned char gm_was[MAX_GAME_MODES];
static const char *tick_via;
static int rules_on;                    /* a loaded mode has a rule needing the hooks */

static char hook_want[80]; static uintptr_t hook_found;
static void cb_hook(const char *name, uintptr_t a, size_t sz)
{
    size_t L = strlen(hook_want), n = strlen(name);
    if (!hook_found && sz == 16 && !strncmp(name, hook_want, L) && n > 6 && !strcmp(name + n - 6, "4listE")) hook_found = a;
}
/* Hook<HookX_, ...>::list by its hook name: the mangled name is
 * _ZN4HookI<len>HookX_<arg>E4listE, the arg varying per hook. */
static void **hook_list(const char *hook)
{
    snprintf(hook_want, sizeof hook_want, "_ZN4HookI%zu%s", strlen(hook), hook);
    hook_found = 0;
    walk_dynsym(cb_hook);
    return (void **)hook_found;
}
static int hook_add(const char *hook, void *fn, const char *name)
{
    void **list = hook_list(hook);
    if (!list) { lg("hooks: this game has no %s list", hook); return 0; }
    int magic = *(int *)((char *)list + 8);
    if (magic != 0x45) { lg("hooks: %s list not set up (magic %#x); not used", hook, magic); return 0; }
    if (nhooks >= MAX_HOOKS) { lg("hooks: too many"); return 0; }
    hdesc_t *d = &hdescs[nhooks]; hnode_t *n = &hnodes[nhooks]; nhooks++;
    d->fn = fn; d->name = name;
    n->prio = 0x7ffffff0; n->desc = d; n->name = name;
    hnode_t **pp = (hnode_t **)list; int before = 0;
    while (*pp && (*pp)->prio <= n->prio) { pp = &(*pp)->next; before++; }
    n->next = *pp;
    __atomic_store_n(pp, n, __ATOMIC_SEQ_CST);
    lg("hooks: %s on %s (after the game's %d)", name, hook, before);
    return 1;
}

static int game_busy_for(pm_t *m) { return m->game_modes != POLICY_IGNORE && game_busy() != NULL; }

/* A rule raised a start: count it, and leave it for the tick to start. */
static void raise_start(pm_t *m, const char *why)
{
    if ((m->start_once == ONCE_BALL && m->runs_ball) || (m->start_once == ONCE_GAME && m->runs_game)) {
        lg("\"%s\" %s: already ran this %s (start_once)", m->name, why, m->start_once == ONCE_BALL ? "ball" : "game");
        return;
    }
    if (running(m) || m->pending) return;
    if (++m->count < m->start_count) { lg("\"%s\" %s: %d of %d", m->name, why, m->count, m->start_count); return; }
    m->count = 0;
    m->pending = why; m->pending_log = 0;
    lg("\"%s\" start raised: %s", m->name, why);
}

static int ticking;
static int multiball_seen;      /* a multiball ran since the last multiball_end (set in per_frame) */
static void starts_tick(const char *via, int force)
{
    static long last;
    if (!installed || !rules_on || ticking || (am_proc && !am_proc())) return;
    long t = now_ms();
    if (!force && t - last < 20) return;
    last = t;
    pthread_mutex_lock(&mu);
    ticking = 1;
    if (!tick_via) { tick_via = via; lg("start rules: ticking on the game's proc thread (first via %s)", via); }
    int ig = in_game();
    /* a game mode that ended */
    for (int i = 0; i < ngm; i++) {
        if (is_ours(gmodes[i])) continue;
        int r = gm_running(i);
        if (gm_was[i] && !r && ig)
            for (int k = 0; k < npm; k++)
                if (pms[k].after_sel[i]) {
                    static char why[MAX_MODES][128];
                    snprintf(why[k], sizeof why[k], "after %s ended", gmode_sym[i]);
                    raise_start(&pms[k], why[k]);
                }
        gm_was[i] = (unsigned char)r;
    }
    /* the player up's score */
    if (ig && score_get && player_up) {
        int p = player_up();
        if (p >= 1 && p <= 8) {
            long long sc = score_get(p);
            for (int k = 0; k < npm; k++) {
                pm_t *m = &pms[k];
                if (m->start_score > 0 && !(m->score_done & (1u << p)) && sc >= m->start_score) {
                    m->score_done |= 1u << p;
                    static char why[MAX_MODES][96];
                    snprintf(why[k], sizeof why[k], "player %d score %lld reached %lld", p, sc, m->start_score);
                    raise_start(m, why[k]);
                }
            }
        }
    }
    /* do one raised start, if the moment is free */
    if (ig && !any_ours_running())
        for (int k = 0; k < npm; k++) {
            pm_t *m = &pms[k];
            if (!m->pending) continue;
            if (game_busy_for(m)) {
                if (t - m->pending_log > 5000) {
                    lg("\"%s\" start (%s) waiting for %s", m->name, m->pending, game_busy());
                    m->pending_log = t;
                }
                continue;
            }
            lg("\"%s\" starting: %s", m->name, m->pending);
            start_mode(m, k);
            break;
        }
    ticking = 0;
    pthread_mutex_unlock(&mu);
}

static int last_ball_done = -1;  /* the ball last_ball was raised for (player * 1000 + balls completed) */
static int (*done_balls)(int);   /* score_get_balls_completed(player) */
static void on_event(int e)
{
    if (!installed) return;
    if (!strcmp(EVENTS[e].word, "last_ball")) {
        int p = player_up ? player_up() : 0, key = p * 1000 + (done_balls && p > 0 ? done_balls(p) : 0);
        if (key == last_ball_done) return;      /* the game's hook and its count both said it */
        last_ball_done = key;
    }
    pthread_mutex_lock(&mu);
    {   /* which ball of which player: the evidence for first/last ball */
        static int (*left)(void); static int r2;
        if (!r2) { r2 = 1; left = (int (*)(void))sym("_Z34game_flow_get_balls_left_player_upv"); }
        int p = player_up ? player_up() : 0;
        if (p > 0 && done_balls) lg("event %s (player %d, %d ball(s) completed, %d left)", EVENTS[e].word, p,
                                    done_balls(p), left ? left() : -1);
        else lg("event %s", EVENTS[e].word);
    }
    /* The game runs its multiball-end hook whenever the ball count settles
     * (MultiballDevice::system_stabilize_proc), one ball or not: it is a
     * multiball's end only after a multiball (Wonka 03.03, PAD-1354). */
    if (!strcmp(EVENTS[e].word, "multiball_end")) {
        if (!multiball_seen) { lg("  (no multiball ran: not a multiball end)"); pthread_mutex_unlock(&mu); return; }
        multiball_seen = 0;
    }
    for (int k = 0; k < npm; k++)
        if (pms[k].start_on & (1u << e)) raise_start(&pms[k], EVENTS[e].word);
    pthread_mutex_unlock(&mu);
    starts_tick(EVENTS[e].hook, 1);
}
#define EV(i) static int ev##i(void *a) { (void)a; on_event(i); return 0; }
EV(0) EV(1) EV(2) EV(3) EV(4) EV(5) EV(6)
static int (*const ev_fns[])(void *) = { ev0, ev1, ev2, ev3, ev4, ev5, ev6 };
_Static_assert(sizeof ev_fns / sizeof *ev_fns == NEVENTS, "one fn per start event");

static int hk_game_start(void *a)
{
    (void)a;
    if (!installed) return 0;
    pthread_mutex_lock(&mu);
    for (int k = 0; k < npm; k++) {
        pm_t *m = &pms[k];
        m->count = 0; m->score_done = 0; m->runs_game = 0; m->runs_ball = 0; m->pending = NULL; m->combo_pos = 0;
    }
    last_ball_done = -1;
    lg("game start: start counts, score marks and runs reset");
    pthread_mutex_unlock(&mu);
    return 0;
}
static int hk_ball_start(void *a)
{
    (void)a;
    if (!installed) return 0;
    pthread_mutex_lock(&mu);
    for (int k = 0; k < npm; k++) {
        pm_t *m = &pms[k];
        m->runs_ball = 0; m->combo_pos = 0;
        if (m->count_reset_ball && m->count) { lg("\"%s\": start count %d reset (new ball)", m->name, m->count); m->count = 0; }
    }
    pthread_mutex_unlock(&mu);
    /* last_ball: the game runs HookLastBall_ just before the last ball (Wonka
     * 03.03: a list with no node of the game's own); its own count backs that up
     * on a title that does not, the player up's last ball starting with no balls
     * left (2, 1, 0 on a 3-ball game).  Either raises it once a ball. */
    static int (*left)(void); static int r;
    if (!r) { r = 1; left = (int (*)(void))sym("_Z34game_flow_get_balls_left_player_upv"); }
    if (left && left() == 0 && (want_events & (1u << 2))) on_event(2);
    return 0;
}
static int hk_score(void *a) { (void)a; starts_tick("HookScore_", 0); return 0; }
static int hk_tick_lamp(void *a) { (void)a; starts_tick("HookLampRender_", 0); return 0; }
static int hk_tick_update(void *a) { (void)a; starts_tick("HookUpdate_", 0); return 0; }
static int hk_tick_sw(void *a) { (void)a; starts_tick("HookSwitchDispatchStart_", 0); return 0; }

static void install_rules(void)
{
    for (int k = 0; k < npm; k++) {
        pm_t *m = &pms[k];
        if (m->start_on || m->after[1] || m->start_score > 0 || m->start_once || m->count_reset_ball || m->ncombo >= 2
            || (m->cm && m->cm->idle))
            rules_on = 1;
        if (!m->after[1]) continue;
        int any = strstr(m->after, " any ") != NULL, hit = 0;
        for (int i = 0; i < ngm; i++) {
            char k1[160], k2[160];
            snprintf(k1, sizeof k1, " %s ", gmode_sym[i]);
            snprintf(k2, sizeof k2, " %s ", gmode_isproc[i] ? gmode_sym[i] : class_name(*(uintptr_t *)gmodes[i]));
            if ((any && !gmode_bg[i]) || strstr(m->after, k1) || strstr(m->after, k2)) { m->after_sel[i] = 1; hit++; }
        }
        lg("\"%s\": start_after%smatches %d game mode(s)", m->name, m->after, hit);
    }
    if (!rules_on) { lg("start rules: switches only; no game hooks used"); return; }
    score_get = (long long (*)(int))sym("_Z22score_get_player_scorei");
    player_up = (int (*)(void))sym("_Z23game_flow_get_player_upv");
    done_balls = (int (*)(int))sym("_Z25score_get_balls_completedi");
    unsigned want = 0; int score = 0;
    for (int k = 0; k < npm; k++) { want |= pms[k].start_on; if (pms[k].start_score > 0) score = 1; }
    want_events = want;
    hook_add("HookGameStart_", (void *)hk_game_start, "pad game start");
    hook_add("HookBallStart_", (void *)hk_ball_start, "pad ball start");
    for (int e = 0; e < NEVENTS; e++)
        if (want & (1u << e)) {
            if (hook_add(EVENTS[e].hook, (void *)ev_fns[e], EVENTS[e].word)) events_hooked |= 1u << e;
            else lg("start rules: start_on %s cannot work on this title", EVENTS[e].word);
        }
    int ticks = hook_add("HookLampRender_", (void *)hk_tick_lamp, "pad tick")
              + hook_add("HookUpdate_", (void *)hk_tick_update, "pad tick")
              + hook_add("HookSwitchDispatchStart_", (void *)hk_tick_sw, "pad tick");
    if (score) {
        if (!score_get || !player_up) lg("start rules: start_score cannot work (no score_get_player_score/game_flow_get_player_up)");
        else hook_add("HookScore_", (void *)hk_score, "pad score");
    }
    lg("start rules: %d hook(s) in, %d tick hook(s)%s", nhooks, ticks, ticks ? "" : " - FAIL: no moment to start a raised mode");
}

/* ---- a mode's own C++ (PAD-1384) -----------------------------------------------
 * `code = <name>` in a .mode file: <name>.so in the mode folder (built from
 * <name>.cpp by modes/sdk/build_code.sh, or written from blocks by the app),
 * loaded here with dlopen.  Its jm_mode_def points at the callbacks of
 * modes/sdk/jjp_mode.h; its jm_* calls land below, on the mode whose callback
 * is running (code_cur), all on the game's proc thread like the rest of a mode.
 * The .so links no library: its few libc calls and our jm_* resolve against
 * the game's process, so it loads whatever glibc the image has. */
static pm_t *code_cur;
#define JMAPI __attribute__((visibility("default")))

/* The game's names its code uses: its switches must be wrapped and its coils
 * resolved at install, like the ones a .mode file names, so they are read off
 * the library's own string literals (a C++ "switch_x" is one in .rodata). */
static void code_names(pm_t *m, const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return;
    static char buf[1 << 20];
    size_t n = fread(buf, 1, sizeof buf - 1, f);
    fclose(f);
    buf[n] = 0;
    int nsw = 0, nco = 0;
    for (size_t i = 0; i + 6 < n; i++) {
        if (i && buf[i - 1]) continue;                      /* a string's start: after a NUL */
        int is_sw = !strncmp(buf + i, "switch_", 7), is_co = !strncmp(buf + i, "coil_", 5);
        if (!is_sw && !is_co) continue;
        size_t L = 0;
        while (i + L < n && ((buf[i + L] >= 'a' && buf[i + L] <= 'z') || (buf[i + L] >= 'A' && buf[i + L] <= 'Z')
                             || (buf[i + L] >= '0' && buf[i + L] <= '9') || buf[i + L] == '_')) L++;
        if (buf[i + L] || L < 8 || L >= 95) continue;        /* the whole string is one name */
        if (!sym(buf + i)) { lg("%s: its code names %s, which this game does not have", m->file, buf + i); continue; }
        if (is_sw) { if (sw_index(buf + i) >= 0) nsw++; }
        else if (coil_index(buf + i) >= 0) nco++;
    }
    if (nsw || nco) lg("%s: its code uses %d switch(es) and %d coil(s) of the game's", m->file, nsw, nco);
}

static int load_code(pm_t *m)
{
    char path[700];
    snprintf(path, sizeof path, "%s/%s.so", moddir, m->code);
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h) { lg("%s: FAIL - its code %s.so did not load: %s", m->file, m->code, dlerror()); return 0; }
    const struct jm_mode **def = (const struct jm_mode **)dlsym(h, "jm_mode_def");
    if (!def || !*def) { lg("%s: FAIL - %s.so has no JM_REGISTER (jm_mode_def)", m->file, m->code); return 0; }
    if ((*def)->api != JM_API) { lg("%s: FAIL - %s.so is for mode API %d, this runtime is %d", m->file, m->code, (*def)->api, JM_API); return 0; }
    m->cm = *def;
    code_names(m, path);
    lg("%s: its code %s.so:%s%s%s%s%s%s", m->file, m->code, m->cm->start ? " start" : "", m->cm->shot ? " shot" : "",
       m->cm->scored ? " scored" : "", m->cm->tick ? " tick" : "", m->cm->end ? " end" : "", m->cm->idle ? " idle" : "");
    return 1;
}

/* a callback of its code, with the jm_* calls pointed at it */
#define CODE_CALL(m, cb, ...) do { pm_t *was_ = code_cur; code_cur = (m); (m)->cm->cb(__VA_ARGS__); code_cur = was_; } while (0)

static void code_started(pm_t *m)
{
    m->ncl = 0; m->ctitle[0] = 0; m->started_at = m->code_tick_at = now_ms(); m->end_why = NULL;
    memset(m->sw_hits, 0, sizeof m->sw_hits);
    if (m->cm && m->cm->start) CODE_CALL(m, start);
}
static void code_tick(pm_t *m)
{
    if (!m->cm || !m->cm->tick || m->paused || m->want_end) return;
    long t = now_ms();
    if (t - m->code_tick_at < 100) return;
    m->code_tick_at = t;
    CODE_CALL(m, tick);
}
static void code_over(pm_t *m, const char *why)
{
    if (m->cm && m->cm->end) CODE_CALL(m, end, why);
}

static pm_t *jm(const char *fn)
{
    if (!code_cur) lg("%s called outside a mode's callback: ignored", fn);
    return code_cur;
}
JMAPI void jm_log(const char *fmt, ...)
{
    char b[400]; va_list ap; va_start(ap, fmt); vsnprintf(b, sizeof b, fmt, ap); va_end(ap);
    lg("\"%s\" code: %s", code_cur ? code_cur->name : "?", b);
}
JMAPI void jm_score(long long pts)
{
    pm_t *m = jm("jm_score");
    if (!m || !running(m) || pts <= 0) return;
    mode_score(m, pts);
    m->total += pts;
    lg("\"%s\" code scored %lld (mode total %lld)", m->name, pts, m->total);
}
JMAPI long long jm_total(void) { pm_t *m = jm("jm_total"); return m ? m->total : 0; }
JMAPI int jm_hits(void) { pm_t *m = jm("jm_hits"); return m ? m->hits : 0; }
JMAPI int jm_switch_hits(const char *sw)
{
    pm_t *m = jm("jm_switch_hits");
    int si = m && sw ? sw_index(sw) : -1;
    return si >= 0 ? m->sw_hits[si] : 0;
}
JMAPI int jm_seconds_left(void) { pm_t *m = jm("jm_seconds_left"); return m ? m->secs : 0; }
JMAPI void jm_set_seconds(int s)
{
    pm_t *m = jm("jm_set_seconds");
    if (!m || !running(m)) return;
    if (s < 1) s = 1;
    if (!engine_proc) ((vint_t)vslot(m->mode, VT_SET_TIME))(m->mode, s);
    m->secs = s;
    lg("\"%s\" code: the clock to %d s", m->name, s);
}
JMAPI void jm_add_seconds(int s) { pm_t *m = jm("jm_add_seconds"); if (m) jm_set_seconds(m->secs + s); }
JMAPI long jm_ms(void) { pm_t *m = jm("jm_ms"); return m && m->started_at ? now_ms() - m->started_at : 0; }
JMAPI int jm_running(void) { pm_t *m = jm("jm_running"); return m ? running(m) : 0; }
JMAPI void jm_end(void)
{
    pm_t *m = jm("jm_end");
    if (m && running(m)) end_mode(m, "its code");
}
JMAPI void jm_start(void)
{
    pm_t *m = jm("jm_start");
    if (!m || running(m) || m->pending) return;
    if ((m->start_once == ONCE_BALL && m->runs_ball) || (m->start_once == ONCE_GAME && m->runs_game)) {
        lg("\"%s\" code start: already ran this %s (start_once)", m->name, m->start_once == ONCE_BALL ? "ball" : "game");
        return;
    }
    m->pending = "its code"; m->pending_log = 0;
    lg("\"%s\" start raised: its code", m->name);
}
JMAPI void jm_title(const char *text)
{
    pm_t *m = jm("jm_title");
    if (m) snprintf(m->ctitle, sizeof m->ctitle, "%s", text ? text : "");
}
JMAPI int jm_sound(const char *name)
{
    pm_t *m = jm("jm_sound");
    if (!m) return 0;
    void *se = sym(name);
    if (!se) { lg("\"%s\" code: no sound called %s in this game", m->name, name ? name : "(null)"); return 0; }
    play(se);
    return 1;
}
JMAPI int jm_lamp(const char *name, unsigned rgb, int blink)
{
    pm_t *m = jm("jm_lamp");
    if (!m) return 0;
    void *o = sym(name);
    if (!o || !lamp_like(o)) { lg("\"%s\" code: no lamp called %s in this game", m->name, name ? name : "(null)"); return 0; }
    int i = 0;
    while (i < m->ncl && m->cl[i].o != o) i++;
    if (i == m->ncl) { if (m->ncl >= MAX_LIST) { lg("\"%s\" code: more than %d lamps lit", m->name, MAX_LIST); return 0; } m->ncl++; }
    m->cl[i].o = o; m->cl[i].rgb = rgb & 0xffffff; m->cl[i].blink = blink < 0 ? 0 : blink;
    return 1;
}
JMAPI void jm_lamp_off(const char *name)
{
    pm_t *m = jm("jm_lamp_off");
    void *o = m ? sym(name) : NULL;
    for (int i = 0; o && i < m->ncl; i++)
        if (m->cl[i].o == o) {
            if (our_lb) lamp_give_back(o);
            m->cl[i] = m->cl[--m->ncl];
            return;
        }
}
JMAPI int jm_coil(const char *name, int ms)
{
    pm_t *m = jm("jm_coil");
    if (!m) return 0;
    int ci = coil_index(name);
    if (ci < 0) { lg("\"%s\" code: %s is not a coil a mode may fire on this game", m->name, name ? name : "(null)"); return 0; }
    coil_fire(m, ci, ms, "its code");
    return 1;
}
JMAPI int jm_multiball(int balls, int save)
{
    pm_t *m = jm("jm_multiball");
    if (!m || !running(m) || balls < 2 || balls > 6) return 0;
    m->mb_balls = balls; m->mb_save = save < 0 ? 0 : save > 120 ? 120 : save;
    serve_multiball(m, "its code");
    return 1;
}
JMAPI int jm_ball_save(int s)
{
    pm_t *m = jm("jm_ball_save");
    if (!m || !running(m) || s < 1) return 0;
    m->ball_save = s > 120 ? 120 : s;
    ball_save_start(m);
    return 1;
}

static void on_switch(int si)
{
    if (!installed || !in_game()) return;
    test_hook(si);
    stock_on_switch(si);
    pthread_mutex_lock(&mu);
    int active = -1;
    for (int i = 0; i < npm; i++) if (running(&pms[i])) { active = i; break; }
    if (active >= 0) {
        pm_t *m = &pms[active];
        if (!m->paused && !m->want_end) {     /* balls and holds first: a switch may also score */
            if (m->nadd && in_list(m->add_sw, m->nadd, si)) add_a_ball(m, wsw[si].name);
            if (m->nmb_on && !m->mb_served && in_list(m->mb_on_sw, m->nmb_on, si)) serve_multiball(m, wsw[si].name);
            if (m->hold_on == 2 && in_list(m->hold_sw, m->nhold_sw, si)) coil_hold(m, wsw[si].name);
        }
        int taken = 0;
        if (!m->paused && !m->want_end) {     /* its code first (PAD-1384): it may take the hit */
            if (m->sw_hits[si] < 65535) m->sw_hits[si]++;
            if (m->cm && m->cm->shot) {
                pm_t *was = code_cur; code_cur = m;
                taken = m->cm->shot(wsw[si].name) == JM_TAKEN;
                code_cur = was;
                if (taken) lg("\"%s\" %s: taken by its code", m->name, wsw[si].name);
            }
        }
        if (!taken && !m->paused && !m->want_end && in_list(m->shot_sw, m->nshot, si)) {
            mode_score(m, m->points);
            m->total += m->points; m->hits++;
            lg("\"%s\" shot %s: +%lld (hits %d, mode total %lld)", m->name, wsw[si].name, m->points, m->hits, m->total);
            if (m->cm && m->cm->scored) CODE_CALL(m, scored, wsw[si].name);
            if (m->want_end) { /* its code ended it */ }
            else if (m->complete > 0 && m->hits >= m->complete) {
                if (m->complete_points) {
                    mode_score(m, m->complete_points);
                    m->total += m->complete_points;
                }
                lg("\"%s\" COMPLETED (+%lld, mode total %lld)", m->name, m->complete_points, m->total);
                play(m->snd_complete ? m->snd_complete : m->snd_shot);
                coil_fire(m, m->coil_complete, m->coil_complete_ms, "completion");
                end_mode(m, "completion");
            } else {
                play(m->snd_shot);
                coil_fire(m, m->coil_shot, m->coil_shot_ms, wsw[si].name);
                if (m->hold_on == 0) coil_hold(m, wsw[si].name);
            }
        } else if (m->paused && in_list(m->shot_sw, m->nshot, si))
            lg("\"%s\" shot %s while paused: not scored", m->name, wsw[si].name);
        pthread_mutex_unlock(&mu);
        return;
    }
    /* its code's idle() (PAD-1384): every switch while no mode of ours runs */
    for (int i = 0; i < npm; i++)
        if (pms[i].cm && pms[i].cm->idle) CODE_CALL(&pms[i], idle, wsw[si].name);
    /* combos: the switches in order, each within combo_seconds of the one before */
    long t = now_ms();
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        if (m->ncombo < 2 || !in_list(m->combo_sw, m->ncombo, si)) continue;
        if (m->combo_pos > 0 && t - m->combo_t > m->combo_ms) m->combo_pos = 0;
        if (m->combo_sw[m->combo_pos] == si) m->combo_pos++;
        else m->combo_pos = m->combo_sw[0] == si ? 1 : 0;
        m->combo_t = t;
        if (m->combo_pos >= m->ncombo) {
            m->combo_pos = 0;
            lg("\"%s\" combo made (%d switches)", m->name, m->ncombo);
            raise_start(m, "combo");
        } else if (m->combo_pos > 1) lg("\"%s\" combo %d of %d", m->name, m->combo_pos, m->ncombo);
    }
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        if (!in_list(m->start_sw, m->nstart, si)) continue;
        if ((m->start_once == ONCE_BALL && m->runs_ball) || (m->start_once == ONCE_GAME && m->runs_game)) continue;
        const char *busy = m->game_modes == POLICY_IGNORE ? NULL : game_busy();
        if (busy) { lg("\"%s\" start shot %s: yielded to %s", m->name, wsw[si].name, busy); continue; }
        if (++m->count < m->start_count) {
            lg("\"%s\" start shot %s: %d of %d", m->name, wsw[si].name, m->count, m->start_count);
            break;
        }
        m->count = 0;
        start_mode(m, i);
        break;
    }
    pthread_mutex_unlock(&mu);
    starts_tick("switch", 1);      /* a combo may just have raised a start */
}

/* One wrapper per wrapped switch: the dispatch is called with the proc's arg
 * only, so each needs its own function to know which switch it is. */
#define W(b, k) static void w##b##_##k(unsigned a)     { if (wsw[(b) * 8 + (k)].orig) ((swd_t)wsw[(b) * 8 + (k)].orig)(a); on_switch((b) * 8 + (k)); }
#define W8(b) W(b, 0) W(b, 1) W(b, 2) W(b, 3) W(b, 4) W(b, 5) W(b, 6) W(b, 7)
W8(0) W8(1) W8(2) W8(3) W8(4) W8(5) W8(6) W8(7) W8(8) W8(9) W8(10) W8(11)
#define R8(b) w##b##_0, w##b##_1, w##b##_2, w##b##_3, w##b##_4, w##b##_5, w##b##_6, w##b##_7
static swd_t wrappers[MAX_SW] = { R8(0), R8(1), R8(2), R8(3), R8(4), R8(5), R8(6), R8(7), R8(8), R8(9), R8(10), R8(11) };
_Static_assert(sizeof wrappers / sizeof *wrappers == MAX_SW, "one wrapper per shot slot");

/* ---- per frame: pause / end rules, lamps, screen --------------------------- */
/* A mode that stopped running (time, completion, or the game stopping it at
 * ball end): lamps back to the game, the end sound, the log.  Runs in every
 * game state, so the lamps go back during the bonus, not at the next ball. */
static void mode_over(pm_t *m)
{
    if (!m->running_seen || running(m)) return;
    m->running_seen = 0; m->paused = 0; m->p_on = 0;
    code_over(m, m->end_why ? m->end_why : in_game() ? "time" : "ball end");
    lamps_release(m);
    if (m->vid) { video_stop(m->vid); m->vid = NULL; }
    coil_release_mode(m, "mode end");
    saver_release(m, in_game() ? "mode end" : "ball end");
    play(m->snd_end);
    lg("\"%s\" over: %d hits, mode total %lld", m->name, m->hits, m->total);
}

static int was_ingame, last_state = -1, attract_state = -1;
static unsigned long frames;
static long bg_snapshot_at = -1;      /* ms clock */

/* jjpe_state_get() == ingame_state (5) means a BALL is in play: the state
 * leaves it between balls (bonus) and in attract.  A ball ending ends a custom
 * mode, as it ends the game's own: the game stops the mode's run proc there
 * whatever we do.  Start-shot counts reset when a new game leaves attract (the
 * state seen when we installed). */
/* 5 is the ball-in-play state on Guns N' Roses.  On a title whose engine
 * numbers its states otherwise (and whose title.cfg does not say), learn it:
 * the state that holds for a second, away from attract, while the game's own
 * ball-in-play flag is set. */
static void learn_ingame(int st)
{
    static int cand = -1; static long since;
    if (ingame_explicit || ingame_learned || !ball_flag) return;
    if (!ball_flag() || st == attract_state) { cand = -1; return; }
    if (st != cand) { cand = st; since = now_ms(); return; }
    if (now_ms() - since >= 1000) {
        ingame_learned = 1;
        if (st != ingame_state) lg("ball-in-play state is %d on this title (not %d)", st, ingame_state);
        else lg("ball-in-play state %d confirmed", st);
        ingame_state = st;
    }
}

static void per_frame(void)
{
    int st = state_get();
    learn_ingame(st);
    if (st != last_state) {
        lg("game state %d -> %d", last_state, st);
        if (last_state == attract_state && st != attract_state)
            for (int i = 0; i < npm; i++) pms[i].count = 0;
        last_state = st;
    }
    int ig = st == ingame_state;
    if (ig && !was_ingame) {
        lg("ball in play");
        /* modes running two seconds into a ball, before any of ours, are the
         * title's always-on modes (unless title.cfg named them) */
        if (!background_explicit) bg_snapshot_at = now_ms() + 2000;
    }
    if (!ig && was_ingame) {
        for (int i = 0; i < npm; i++) {
            end_mode(&pms[i], "ball end");
            if (pms[i].pending) { lg("\"%s\" start (%s) dropped: the ball ended first", pms[i].name, pms[i].pending); pms[i].pending = NULL; }
        }
        multiball_seen = 0;
        lg("ball over");
    }
    was_ingame = ig;
    if (!ig) {
        for (int i = 0; i < npm; i++) mode_over(&pms[i]);
        return;
    }
    if (bg_snapshot_at >= 0 && now_ms() >= bg_snapshot_at) {
        bg_snapshot_at = -1;
        if (!any_ours_running()) {
            for (int i = 0; i < ngm; i++) {
                if (gmode_isproc[i]) {
                    proc_counts();
                    if (pcount[i] > gmode_bgn[i]) { gmode_bgn[i] = pcount[i]; lg("always-on game mode: %s (x%d)", gmode_sym[i], pcount[i]); }
                } else if (!gmode_bg[i] && gm_running(i)) { gmode_bg[i] = 1; lg("always-on game mode: %s", gmode_sym[i]); }
            }
        }
    }
    if ((frames & 7) == 0) log_running_set();
    {   /* evidence for every multiball yield */
        static int last_bip = -1;
        int bip = balls_in_play ? balls_in_play() : -1;
        if (bip != last_bip) { lg("balls in play: %d", bip); last_bip = bip; }
        if (bip > 1 && !multiball_since) multiball_since = now_ms();
        if (multiball_since && now_ms() - multiball_since >= 500) multiball_seen = 1;
        else if (bip <= 1) multiball_since = 0;
    }
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        if (!m->mode) continue;
        int r = running(m);
        if (r) {
            const char *busy = m->game_modes == POLICY_IGNORE ? NULL : game_busy_except(m);
            if (m->want_end) r = 1;                       /* ending: leave it be */
            else if (busy && m->game_modes == POLICY_END) end_mode(m, busy);
            else {
                int p2 = busy != NULL;
                if (p2 != m->paused) {
                    m->paused = p2;
                    lg("\"%s\" %s%s%s", m->name, p2 ? "PAUSED for " : "RESUMED", p2 ? busy : "",
                       p2 && m->game_modes == POLICY_HOLD ? " (it started past the hold)" : "");
                }
            }
        }
        if (m->vid) m->vid->pause = r && m->paused;
        if (r && m->mb_balls && m->mb_served && !m->want_end && balls_in_play) {
            /* item 167's rule: one ball (or none) for 2 s, once the ball save and 3 s more have passed */
            long t = now_ms();
            if (balls_in_play() > 1) { m->mb_seen2 = 1; m->one_ball_since = 0; }
            else {
                if (!m->one_ball_since) m->one_ball_since = t;
                if (t - m->mb_served_at >= m->mb_save * 1000L + 3000 && t - m->one_ball_since >= 2000)
                    end_mode(m, m->mb_seen2 ? "one ball left" : "no second ball was served");
            }
        }
        if (r && m->paused) lamps_release(m);          /* the game mode has the lamps */
        else if (!r) mode_over(m);          /* lamps are lit from pad_tick_work */
    }
}

static void (*real_flip)(void);
static plot_os_t plot_os;
static jfont_t jfont;

static ALLEGRO_COLOR col(unsigned rgba)
{
    ALLEGRO_COLOR c = { ((rgba >> 24) & 0xff) / 255.0f, ((rgba >> 16) & 0xff) / 255.0f,
                        ((rgba >> 8) & 0xff) / 255.0f, (rgba & 0xff) / 255.0f };
    /* Allegro blends premultiplied */
    c.r *= c.a; c.g *= c.a; c.b *= c.a;
    return c;
}

static void draw_screen(pm_t *m)
{
    static void (*fill_rect)(float, float, float, float, ALLEGRO_COLOR);
    static void (*draw_text)(const void *, ALLEGRO_COLOR, float, float, int, const char *);
    static void *(*builtin_font)(void);
    static const ALLEGRO_TRANSFORM *(*cur_xf)(void);
    static void (*copy_xf)(ALLEGRO_TRANSFORM *, const ALLEGRO_TRANSFORM *);
    static void (*ident_xf)(ALLEGRO_TRANSFORM *);
    static void (*scale_xf)(ALLEGRO_TRANSFORM *, float, float);
    static void (*trans_xf)(ALLEGRO_TRANSFORM *, float, float);
    static void (*use_xf)(const ALLEGRO_TRANSFORM *);
    static void (*get_blender)(int *, int *, int *);
    static void (*set_blender)(int, int, int);
    static void *(*cur_display)(void);
    static int (*disp_w)(void *), (*disp_h)(void *);
    static void *bfont;
    static int ready = -1;
    if (ready < 0) {
        fill_rect = sym("al_draw_filled_rectangle"); draw_text = sym("al_draw_text");
        builtin_font = sym("al_create_builtin_font"); cur_xf = sym("al_get_current_transform");
        copy_xf = sym("al_copy_transform"); ident_xf = sym("al_identity_transform");
        scale_xf = sym("al_scale_transform"); trans_xf = sym("al_translate_transform");
        use_xf = sym("al_use_transform"); get_blender = sym("al_get_blender"); set_blender = sym("al_set_blender");
        cur_display = sym("al_get_current_display"); disp_w = sym("al_get_display_width");
        disp_h = sym("al_get_display_height");
        plot_os = (plot_os_t)sym("_Z24font_plot_outline_shadowPK12ALLEGRO_FONT13ALLEGRO_COLORS2_iS2_iffiPKc");
        jfont = (jfont_t)sym("_ZN8JJPEFont4fontEv");
        ready = fill_rect && draw_text && cur_xf && copy_xf && ident_xf && use_xf && set_blender && get_blender;
        lg("screen: allegro %s, game text %s", ready ? "ok" : "MISSING", plot_os && jfont ? "ok" : "missing (built-in font)");
    }
    if (!ready) return;
    float W = 1360, H = 768;
    void *d = cur_display ? cur_display() : NULL;
    if (d && disp_w && disp_h) { W = (float)disp_w(d); H = (float)disp_h(d); }
    int bop, bsrc, bdst; get_blender(&bop, &bsrc, &bdst);
    set_blender(0 /*ADD*/, 1 /*ONE*/, 3 /*INVERSE_ALPHA*/);
    ALLEGRO_TRANSFORM old, t; copy_xf(&old, cur_xf()); ident_xf(&t); use_xf(&t);
    draw_media(m, W, H);                          /* the mode's video, then its picture, under the panel */
    if (m->panel == 3) { use_xf(&old); set_blender(bop, bsrc, bdst); return; }
    float ph = H * 0.27f, y0 = m->panel == 1 ? H * 0.70f : m->panel == 2 ? H * 0.03f : H * 0.36f;
    float x0 = W * 0.16f, x1 = W * 0.84f, y1 = y0 + ph;
    fill_rect(x0, y0, x1, y1, col(m->panel_rgba));
    char total[48], secs[16];
    {   /* 12,345,678 */
        char raw[32]; snprintf(raw, sizeof raw, "%lld", m->total);
        int L = (int)strlen(raw), o = 0;
        for (int i = 0; i < L; i++) { total[o++] = raw[i]; if ((L - i - 1) % 3 == 0 && i < L - 1) total[o++] = ','; }
        total[o] = 0;
    }
    if (m->no_clock || (m->nmb_on && m->mb_served)) secs[0] = 0;   /* runs to one ball left */
    else snprintf(secs, sizeof secs, "%d", m->secs);
    ALLEGRO_COLOR black = { 0, 0, 0, 1 };
    void *ft = m->font_title && jfont ? jfont(m->font_title) : NULL;
    void *fv = m->font_value && jfont ? jfont(m->font_value) : NULL;
    void *fm = m->font_timer && jfont ? jfont(m->font_timer) : NULL;
    float cx = W / 2;
    const char *title = *m->ctitle ? m->ctitle : m->title;     /* its code's jm_title (PAD-1384) */
    if (plot_os && ft) plot_os(ft, col(m->title_rgba), black, 2, black, 3, cx, y0 + H * 0.01f, 1, title);
    if (plot_os && fv) plot_os(fv, col(m->value_rgba), black, 2, black, 3, cx, y0 + H * 0.10f, 1, total);
    if (plot_os && fm) plot_os(fm, col(m->timer_rgba), black, 2, black, 3, x1 - W * 0.05f, y0 + H * 0.06f, 1, secs);
    if (!ft || !fv || !fm || !plot_os) {     /* the built-in font for whatever has no game font */
        if (!bfont && builtin_font) bfont = builtin_font();
        if (bfont && scale_xf && trans_xf) {
            const char *s[3] = { ft ? NULL : title, fv ? NULL : total, fm ? NULL : secs };
            float xs[3] = { cx, cx, x1 - W * 0.05f }, ys[3] = { y0 + H * 0.02f, y0 + H * 0.12f, y0 + H * 0.07f };
            unsigned cs[3] = { m->title_rgba, m->value_rgba, m->timer_rgba };
            for (int i = 0; i < 3; i++) if (s[i]) {
                ident_xf(&t); scale_xf(&t, 4, 4); trans_xf(&t, xs[i], ys[i]); use_xf(&t);
                draw_text(bfont, col(cs[i]), 0, 0, 1, s[i]);
            }
        }
    }
    use_xf(&old);
    set_blender(bop, bsrc, bdst);
}

void al_flip_display(void)
{
    if (!real_flip) real_flip = dlsym(RTLD_NEXT, "al_flip_display");
    if (++frames == 1) lg("al_flip_display interposed (first frame)");
    if (installed) {
        pthread_mutex_lock(&mu);
        if (!our_lb && npm) build_lamp_buffer();
        load_pictures();                          /* on the render thread: bitmaps are GL textures */
        per_frame();
        stock_frame();
        for (int i = 0; i < npm; i++)
            if (running(&pms[i]) && !pms[i].paused) { draw_screen(&pms[i]); break; }
        pthread_mutex_unlock(&mu);
    }
    if (real_flip) real_flip();
}

static void hook_crashes(int chain);

/* Which engine runs our modes: Mode objects when the title has the Mode class
 * (every title but The Wizard of Oz), else our own procs (PAD-1365).
 * JJP_MODS_ENGINE=proc runs the proc engine on a title that has both: how it
 * is proven on Wonka. */
static int pick_engine(void)
{
    const char *want = getenv("JJP_MODS_ENGINE");
    int force = want && !strcmp(want, "proc");
    mode_ctor = (mode_ctor_t)sym("_ZN4ModeC1EPKciP11ModeManagerP4LampjjjP5AuditS7_");
    int mode_ok = mode_ctor && sym("_ZTV4Mode") && resolve_vtable();
    if (mode_ok && !force) { lg("engine: Mode objects"); return 1; }
    if (proc_api()) {
        engine_proc = 1;
        lg("engine: our own procs (%s): proc %s, proc_sleep, proc_id_exists, score_add_to_player_up%s", force ? "JJP_MODS_ENGINE=proc" :
           "no Mode class", p_cret ? "proc_cret" : "proc_create", upd_soon ? ", update_all_soon" : "");
        return 1;
    }
    lg("engine: no Mode class%s and no proc API (proc_cret/proc_create, proc_sleep, proc_id_exists, score_add_to_player_up)",
       mode_ctor ? " that resolves" : "");
    return 0;
}

/* ---- install --------------------------------------------------------------- */
static void *installer(void *arg)
{
    (void)arg;
    lg("PAD JJP mode SDK %s, modes from %s", SDK_VERSION, moddir);
    load_modes();
    if (!npm && !nst) { lg("no modes to run"); return NULL; }
    /* Wait for the game's static constructors: a Switch gets its dispatch
     * pointer at +0x10 when its ctor runs. */
    for (int t = 0; t < 600; t++) {
        int ok = 1;
        for (int i = 0; i < nwsw; i++) if (!*(void **)((char *)wsw[i].obj + 0x10)) { ok = 0; break; }
        if (ok) break;
        usleep(100000);
    }
    sleep(3);   /* let power-up finish before we touch anything */
    hook_crashes(1);   /* the game has its own crash handler by now: ours logs first, then hands over to it */
    state_get = (int_fn_t)need("_Z14jjpe_state_getv");
    upd_soon = (void (*)(void))sym("_Z15update_all_soonv");
    balls_in_play = (int_fn_t)sym("_Z28mb_get_logical_balls_in_playv");
    if (!balls_in_play) balls_in_play = (int_fn_t)sym("_Z20mb_get_balls_in_playv");
    am_proc = (int (*)(void))sym("_Z16proc_am_i_a_procv");
    ball_flag = (int (*)(void))sym("_Z26game_flow_get_ball_in_playv");
    if (!pick_engine() || !state_get) { lg("FAIL: this game's engine lacks what a mode needs"); return NULL; }
    if (engine_proc) {
        find_proc_modes();
        for (int i = 0; i < npm; i++)
            if (pms[i].game_modes == POLICY_HOLD) { pms[i].game_modes = POLICY_PAUSE; hold_wanted = 1; }
        if (hold_wanted) lg("hold: this engine has no Mode class to hold off; game_modes = hold runs as pause (a game mode that starts under ours pauses it)");
        if (nst) { lg("stock: %d .stock file(s) ignored: changing the game's own modes needs its Mode class", nst); nst = 0; }
    } else {
        find_game_modes();
        install_hold();
    }
    install_music_node();
    {   pthread_t mt;                             /* own sound files, once the game's sounds are in */
        if (pthread_create(&mt, NULL, media_loader, NULL) == 0) pthread_detach(mt); }
    mb_request = (void (*)(int, int))sym("_Z26mb_request_balls_into_playii");
    mb_add = (void (*)(int, int))sym("_Z22mb_add_balls_into_playii");
    mb_kill_saver = (void (*)(void))sym("_Z17mb_kill_ballsaverv");
    saver_running = (int_fn_t)sym("_Z23mb_ballsaver_is_runningv");
    saver_time = (int_fn_t)sym("_Z21mb_get_ballsaver_timev");
    balls_known = (int_fn_t)sym("_Z35ball_search_get_balls_accounted_forv");
    {
        int want = 0;
        for (int i = 0; i < npm; i++) if (pms[i].mb_balls || pms[i].ball_save || pms[i].nadd) want = 1;
        if (want) lg("balls: the game's ball saver %s (request %p, add %p, kill %p)", ball_api() ? "ok" : "MISSING",
                     (void *)mb_request, (void *)mb_add, (void *)mb_kill_saver);
    }
    resolve_coils();
    {
        int holds = 0;
        for (int i = 0; i < npm; i++) if (pms[i].coil_hold >= 0) holds = 1;
        if (holds) {
            if (!coil_holds_on) lg("coils: holds are off on this title until title.cfg says coil_holds = on (a check on the machine comes first)");
            pthread_t ct;
            if (pthread_create(&ct, NULL, coil_watch, NULL) == 0) { coil_watch_up = 1; pthread_detach(ct); }
            else lg("coils: FAIL - no watchdog thread; no holds");
        }
    }
    install_rules();
    if (getenv("JJP_MODS_TEST_GAMEMODE") && getenv("JJP_MODS_TEST_SWITCH")) {
        test_gm = sym(getenv("JJP_MODS_TEST_GAMEMODE"));
        test_sw = sw_index(getenv("JJP_MODS_TEST_SWITCH"));
        if (getenv("JJP_MODS_TEST_END_SWITCH")) test_end_sw = sw_index(getenv("JJP_MODS_TEST_END_SWITCH"));
        lg("TEST hook: %s starts game mode %s (%p)", getenv("JJP_MODS_TEST_SWITCH"), getenv("JJP_MODS_TEST_GAMEMODE"), test_gm);
    }
    int hooked = 0;
    for (int i = 0; i < nwsw; i++) {
        void **slot = (void **)((char *)wsw[i].obj + 0x10);
        void *orig = *slot;
        if (!orig) { lg("switch %s has no dispatch; not a shot on this title", wsw[i].name); continue; }
        Dl_info di; const char *on = "?";
        if (dladdr(orig, &di) && di.dli_sname) on = di.dli_sname;
        const char *label = *(char **)((char *)wsw[i].obj + 8);
        wsw[i].orig = orig;
        __atomic_store_n(slot, (void *)wrappers[i], __ATOMIC_SEQ_CST);
        lg("shot %s \"%s\": dispatch %p (%s) wrapped", wsw[i].name, label ? label : "?", orig, on);
        hooked++;
    }
    attract_state = last_state = state_get();
    lg("installed: %d mode(s), %d changed game mode file(s), %d shot switch(es), ball-in-play state %d (now %d)", npm, nst,
       hooked, ingame_state, attract_state);
    installed = 1;
    return NULL;
}

/* JJP_MODS_SELFTEST=1: resolve the engine, the Mode vtable and every name the
 * mode folder uses, print the verdict, and _exit before the game's main()
 * runs: nothing on screen, no hostname or reboot side effects.  It still needs
 * the TITLE's key: Sentinel's start-up check runs before any preloaded
 * constructor, so without the key the game exits H0007 first.  For a title
 * whose key we lack, the library is load-checked in that image's /bin/true
 * (LD_BIND_NOW) and the engine side by jjpport.py.  Exit 0 = ready, 3 = not. */
static void selftest(void)
{
    int bad = 0;
    const char *must[] = { "_Z14jjpe_state_getv",
                           "_ZN11SoundEffect4playEv", "_ZN10LampBufferC1EiPFvPS_EPKc9lb_flag_t",
                           "_ZN4Lamp3setER10LampBufferhhhh", "_ZN4Lamp11transparentER10LampBuffer",
                           "_ZN10LampBuffer10render_allEv", "_ZN8JJPEFont4fontEv", "al_flip_display" };
    for (unsigned i = 0; i < sizeof must / sizeof *must; i++)
        if (!sym(must[i])) { lg("SELFTEST missing %s", must[i]); bad++; }
    if (!pick_engine()) { lg("SELFTEST no engine to run modes on (no Mode class, no proc API)"); bad++; }
    load_modes();
    for (int i = 0; i < nwsw; i++)
        if (!wsw[i].obj) bad++;
    unsigned want = 0; int score = 0, ticked = 0;
    for (int i = 0; i < npm; i++) {
        want |= pms[i].start_on;
        if (pms[i].start_score > 0) score = 1;
        if (pms[i].start_on || pms[i].after[1] || pms[i].start_score > 0 || pms[i].ncombo >= 2) ticked = 1;
    }
    for (int e = 0; e < NEVENTS; e++)
        if ((want & (1u << e)) && !hook_list(EVENTS[e].hook)) { lg("SELFTEST start_on %s: no %s list", EVENTS[e].word, EVENTS[e].hook); bad++; }
    if (ticked && !hook_list("HookLampRender_") && !hook_list("HookUpdate_") && !hook_list("HookSwitchDispatchStart_")) {
        lg("SELFTEST no tick hook list: a raised start could never be done"); bad++;
    }
    if (score && (!sym("_Z22score_get_player_scorei") || !sym("_Z23game_flow_get_player_upv"))) {
        lg("SELFTEST start_score: no score_get_player_score / game_flow_get_player_up"); bad++;
    }
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        for (int s2 = 0; s2 < 4; s2++)
            if (*m->snd_names[s2] && !m->own_snd[s2] && !(s2 == 0 ? m->snd_start : s2 == 1 ? m->snd_shot : s2 == 2 ? m->snd_end : m->snd_complete)) bad++;
        /* own media: the files are there; the engine pieces that play them are */
        const char *files[7] = { m->own_snd[0] ? m->snd_names[0] : "", m->own_snd[1] ? m->snd_names[1] : "",
                                 m->own_snd[2] ? m->snd_names[2] : "", m->own_snd[3] ? m->snd_names[3] : "",
                                 m->music_file, m->pic_file, m->vid_file };
        for (int f = 0; f < 7; f++) {
            if (!*files[f]) continue;
            char path[700];
            snprintf(path, sizeof path, "%s%s%s", *files[f] == '/' ? "" : moddir, *files[f] == '/' ? "" : "/", files[f]);
            if (access(path, R_OK)) { lg("SELFTEST %s: no file %s", m->file, path); bad++; }
        }
        const char *media[] = { "_ZN11SoundEffect23create_sample_instancesEPKc", "_ZN11SoundEffect9is_loadedEv",
                                "_ZN11SoundEffect7do_playEb", "al_load_sample", "al_create_sample_instance",
                                "_ZN6UpdateI14UpdateBGMusic_PPFvvEE4listE", "_Z12update_musicv", "al_load_bitmap",
                                "al_draw_scaled_bitmap", "al_lock_bitmap", "avformat_open_input", "avcodec_receive_frame" };
        int uses = m->own_snd[0] | m->own_snd[1] | m->own_snd[2] | m->own_snd[3] | *m->music_file | *m->pic_file | *m->vid_file;
        for (unsigned k = 0; uses && k < sizeof media / sizeof *media; k++)
            if (!sym(media[k])) { lg("SELFTEST %s: own media needs %s, missing", m->file, media[k]); bad++; }
    }
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        if ((m->mb_balls || m->ball_save || m->nadd) && !(sym("_Z26mb_request_balls_into_playii") && sym("_Z22mb_add_balls_into_playii"))) {
            lg("SELFTEST %s: balls asked for, but no ball saver exported", m->file); bad++;
        }
        if ((m->coil_start >= 0 || m->coil_shot >= 0 || m->coil_complete >= 0 || m->coil_hold >= 0)
            && !(sym("_ZN4Coil10coil_pulseEj") && sym("_ZN4Coil9coil_dutyEjjh") && sym("_ZN4Coil8coil_offEv") && sym("coil_table"))) {
            lg("SELFTEST %s: coils named, but no Coil API exported", m->file); bad++;
        }
    }
    /* .stock files: the game's objects are not built yet (this runs before
     * main), so a mode is checked by name: its global or its class's vtable */
    for (int i = 0; i < nst; i++) {
        char n[200]; snprintf(n, sizeof n, "_ZTV%zu%s", strlen(sts[i].mode), sts[i].mode);
        if (!sym(sts[i].mode) && !sym(n)) { lg("SELFTEST %s: no mode called %s", sts[i].file, sts[i].mode); bad++; }
    }
    lg("SELFTEST %s: pid %d, GAMENAME %s, %d mode(s), %d changed game mode(s), %d shot switch(es), %d problem(s)",
       bad ? "FAIL" : "PASS", getpid(), getenv("GAMENAME") ? getenv("GAMENAME") : "?", npm, nst, nwsw, bad);
    fprintf(stderr, "jjpmodes selftest: %s (%d mode(s), %d problem(s))\n", bad ? "FAIL" : "PASS", npm, bad);
    _exit(bad ? 3 : 0);
}

/* A crash while a mode of ours is loaded leaves its trace in our log before
 * the game dies as it would have (the handler resets itself and re-raises):
 * a machine's log then says where, not just that the game restarted. */
static struct sigaction game_sa[32];      /* the game's own handlers (its trace-F writer), chained to */
static void on_crash(int sig, siginfo_t *si, void *uc)
{
    void *fr[32]; int n = backtrace(fr, 32);
    void *rip = uc ? (void *)((ucontext_t *)uc)->uc_mcontext.gregs[REG_RIP] : NULL;
    Dl_info ri; const char *rn = rip && dladdr(rip, &ri) && ri.dli_sname ? ri.dli_sname : "?";
    lg("CRASH signal %d at %p, pc %p (%s+%#lx)", sig, si ? si->si_addr : NULL, rip, rn,
       rip && ri.dli_saddr ? (unsigned long)((char *)rip - (char *)ri.dli_saddr) : 0UL);
    for (int i = 0; i < n; i++) {
        Dl_info di;
        if (dladdr(fr[i], &di) && di.dli_fname)
            lg("  #%d %p %s(%s+%#lx)", i, fr[i], strrchr(di.dli_fname, '/') ? strrchr(di.dli_fname, '/') + 1 : di.dli_fname,
               di.dli_sname ? di.dli_sname : "?", (unsigned long)((char *)fr[i] - (char *)(di.dli_saddr ? di.dli_saddr : di.dli_fbase)));
        else lg("  #%d %p", i, fr[i]);
    }
    struct sigaction *g = sig < 32 ? &game_sa[sig] : NULL;
    if (g && (g->sa_flags & SA_SIGINFO) && g->sa_sigaction) { g->sa_sigaction(sig, si, uc); return; }
    if (g && g->sa_handler != SIG_DFL && g->sa_handler != SIG_IGN && g->sa_handler) { g->sa_handler(sig); return; }
    signal(sig, SIG_DFL);
    raise(sig);
}
static const int crash_sigs[] = { SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGABRT };
static void hook_crashes(int chain)
{
    struct sigaction sa; memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = on_crash; sa.sa_flags = SA_SIGINFO | (chain ? 0 : SA_RESETHAND);
    for (unsigned i = 0; i < sizeof crash_sigs / sizeof *crash_sigs; i++) {
        struct sigaction old;
        sigaction(crash_sigs[i], &sa, &old);
        if (chain && old.sa_sigaction != on_crash) game_sa[crash_sigs[i]] = old;
    }
}

__attribute__((constructor)) static void jjpmodes_init(void)
{
    /* LD_PRELOAD rides into every child the game starts (its shell scripts,
     * aplay, ...).  Only the game exports the engine; stay silent elsewhere. */
    if (!dlsym(RTLD_DEFAULT, "_Z14jjpe_state_getv")) return;
    const char *d = getenv("JJP_MODS_DIR");
    if (d && *d) snprintf(moddir, sizeof moddir, "%s", d);
    else {
        Dl_info di;
        if (dladdr((void *)jjpmodes_init, &di) && di.dli_fname) {
            snprintf(moddir, sizeof moddir, "%s", di.dli_fname);
            char *s = strrchr(moddir, '/');
            if (s) snprintf(s, sizeof moddir - (size_t)(s - moddir), "/modes");
        }
    }
    lg("loaded into pid %d", getpid());
    hook_crashes(0);
    if (getenv("JJP_MODS_SELFTEST")) selftest();
    pthread_t t;
    if (pthread_create(&t, NULL, installer, NULL) == 0) pthread_detach(t);
}
