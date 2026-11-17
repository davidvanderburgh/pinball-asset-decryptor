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
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define SDK_VERSION "1"

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

/* ---- definitions ----------------------------------------------------------- */
#define MAX_MODES 24
#define MAX_LIST  24
#define MAX_SW    96
#define POLICY_PAUSE 0
#define POLICY_END 1
#define POLICY_IGNORE 2
#define POLICY_HOLD 3     /* PAD-1348, the default: the game's starts are refused while ours runs */

typedef struct {
    char file[64], name[48], title[64];
    int nstart, start_sw[MAX_LIST], start_count;
    int nshot, shot_sw[MAX_LIST];
    long long points, complete_points;
    int seconds, complete;
    void *snd_start, *snd_shot, *snd_end, *snd_complete;
    char snd_names[4][96];
    int nlamp; void *lamp[MAX_LIST];
    unsigned lamp_rgb; int lamp_blink;
    void *font_title, *font_value, *font_timer;
    unsigned title_rgba, value_rgba, timer_rgba, panel_rgba;
    int game_modes, panel;     /* panel: 0 middle, 1 bottom, 2 top */
    int hold_multiballs;       /* with game_modes = hold: refuse the game's multiball starts too (default yes) */
    char allow[1024];          /* allow_game_modes: " name name " the game may still start while ours holds */
    /* runtime */
    void *mode;
    int count, hits, secs, paused, ended_logged;
    const char *volatile want_end;     /* an end asked for outside a proc, done in the mode's own tick */
    long long total;
    int running_seen;
} pm_t;

static pm_t pms[MAX_MODES];
static int npm;

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
    else if (!strcmp(k, "sound_start")) snprintf(m->snd_names[0], 96, "%s", v);
    else if (!strcmp(k, "sound_shot")) snprintf(m->snd_names[1], 96, "%s", v);
    else if (!strcmp(k, "sound_end")) snprintf(m->snd_names[2], 96, "%s", v);
    else if (!strcmp(k, "sound_complete")) snprintf(m->snd_names[3], 96, "%s", v);
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
    else if (!strcmp(k, "panel")) m->panel = !strcmp(v, "bottom") ? 1 : !strcmp(v, "top") ? 2 : 0;
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
        if (!*m->title) snprintf(m->title, sizeof m->title, "%s", m->name);
        if (!m->nshot) { m->nshot = m->nstart; memcpy(m->shot_sw, m->start_sw, sizeof m->shot_sw); }
        for (int s = 0; s < 4; s++) {
            void **slot = s == 0 ? &m->snd_start : s == 1 ? &m->snd_shot : s == 2 ? &m->snd_end : &m->snd_complete;
            *slot = sym(m->snd_names[s]);
            if (*m->snd_names[s] && !*slot) lg("%s: no sound called %s in this game", m->file, m->snd_names[s]);
        }
        if (!m->nstart) { lg("%s: no start shot found; mode skipped", m->file); continue; }
        if (m->seconds < 1) m->seconds = 1;
        lg("mode %d \"%s\" (%s): %d start shot(s) x%d, %d scoring, %lld a shot, %d s, complete %d (+%lld), "
           "%d lamp(s), game modes=%s%s%s%s",
           npm, m->name, m->file, m->nstart, m->start_count, m->nshot, m->points, m->seconds, m->complete,
           m->complete_points, m->nlamp,
           m->game_modes == POLICY_END ? "end" : m->game_modes == POLICY_IGNORE ? "ignore"
           : m->game_modes == POLICY_PAUSE ? "pause" : "hold",
           m->game_modes == POLICY_HOLD ? (m->hold_multiballs ? " (multiballs too)" : " (not multiballs)") : "",
           m->game_modes == POLICY_HOLD && m->allow[1] ? ", allowed:" : "",
           m->game_modes == POLICY_HOLD && m->allow[1] ? m->allow : "");
        npm++;
    }
    for (int i = 0; i < nn; i++) free(names[i]);
}

/* ---- the game's own modes (for yielding) ----------------------------------- */
#define MAX_GAME_MODES 256
static void *gmodes[MAX_GAME_MODES];
static const char *gmode_sym[MAX_GAME_MODES];
static unsigned char gmode_bg[MAX_GAME_MODES];
static int ngm;

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

static int gm_running(int i)
{
    void *o = gmodes[i];
    if (*(uintptr_t *)o == 0) return 0;
    return ((vbool_t)vslot(o, VT_IS_RUNNING))(o) & 0xff;
}

/* What a custom mode would be yielding to right now, or NULL. */
static long multiball_since;     /* ms clock when more than one ball came into play, 0 = not */
static const char *game_busy(void)
{
    /* A multiball is more than one ball for half a second: the count blips
     * (GnR read 6 for one frame while a ball sat in the shooter lane). */
    if (multiball_since && now_ms() - multiball_since >= 500) return "multiball";
    for (int i = 0; i < ngm; i++)
        if (!gmode_bg[i] && !is_ours(gmodes[i]) && gm_running(i)) return gmode_sym[i];
    return NULL;
}

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

/* ---- lamps ----------------------------------------------------------------- */
static void *our_lb;
static lamp_set_t lamp_set;
static lamp_tr_t lamp_tr;
static uintptr_t lamp_vts[8]; static int nlvt;

static int lamp_like(void *o)
{
    uintptr_t w = *(uintptr_t *)o;
    for (int i = 0; i < nlvt; i++) if (w == lamp_vts[i]) return 1;
    return 0;
}

static void our_lb_render(void *lb) { (void)lb; }

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
    /* Above the game's mode layers (GnR: ~0x400-0x4ff), below its award,
     * Bluetooth and flasher layers (1e9+). */
    int prio = 0x7fff;
    our_lb = calloc(1, 0x200);
    ctor(our_lb, prio, our_lb_render, "pad_custom_modes", 0);
    find_lb_active();
    lg("lamps: our LampBuffer %p at priority %#x", our_lb, prio);
    for (int i = 0; i < npm; i++)
        for (int l = 0; l < pms[i].nlamp; l++)
            if (!lamp_like(pms[i].lamp[l])) {
                lg("%s: lamp #%d is not a Lamp object; dropped", pms[i].file, l);
                pms[i].lamp[l] = pms[i].lamp[--pms[i].nlamp]; l--;
            }
}

static void lamps_show(pm_t *m, int on)
{
    if (!our_lb) return;
    lb_activate(1);
    unsigned r = (m->lamp_rgb >> 16) & 0xff, g = (m->lamp_rgb >> 8) & 0xff, b = m->lamp_rgb & 0xff;
    for (int l = 0; l < m->nlamp; l++) {
        if (on) lamp_set(m->lamp[l], our_lb, r, g, b, 255);
        else lamp_set(m->lamp[l], our_lb, 0, 0, 0, 255);
    }
}

static void lamps_release(pm_t *m)
{
    if (!our_lb) return;
    for (int l = 0; l < m->nlamp; l++) lamp_tr(m->lamp[l], our_lb);
    lb_activate(0);
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
static void pad_tick_work(void *self, int arg)
{
    (void)arg;
    pm_t *m = pm_of(self);
    if (!m) return;
    m->secs = *(int *)((char *)self + mode_seconds_off);
    /* The lamps, from the mode's own run proc (the game's proc thread, ~125
     * ticks a second, where the game sets its own lamps) - not from the frame
     * hook, whose rate is the renderer's (about 1 a second on a busy hidden
     * rig, which aliased a 1/s blink into solid).  lamp_blink = flashes a
     * second by the clock; 0 = solid. */
    if (!m->paused && !m->want_end) {
        long half = m->lamp_blink > 0 ? 500L / m->lamp_blink : 0;
        lamps_show(m, half == 0 || ((now_ms() / (half ? half : 1)) & 1) == 0);
    }
    const char *why = m->want_end;
    if (why) {      /* in the mode's own run proc: where the game itself ends a mode */
        m->want_end = NULL;
        ((vfn0_t)vslot(self, VT_END))(self);
        lg("\"%s\" ENDED by %s", m->name, why);
    }
}
static int pad_is_timer_paused(void *self)
{
    pm_t *m = pm_of(self);
    return m ? m->paused : 0;
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
        if (mode_start_fn) slots[VT_START / 8] = mode_start_fn;   /* _ZTV4Mode's own slots are gated (PAD-1348) */
        if (mode_re_slot >= 0 && sym("_ZN4Mode7restartEv")) slots[mode_re_slot / 8] = (uintptr_t)sym("_ZN4Mode7restartEv");
    }
    if (*(uintptr_t **)m->mode != mode_vt + 2)
        lg("WARN ctor vptr %p != Mode vtable %p", *(void **)m->mode, (void *)(mode_vt + 2));
    *(uintptr_t **)m->mode = &our_vt[2];
    return 1;
}

static int running(pm_t *m) { return m->mode && (((vbool_t)vslot(m->mode, VT_IS_RUNNING))(m->mode) & 0xff); }
static int any_ours_running(void) { for (int i = 0; i < npm; i++) if (running(&pms[i])) return 1; return 0; }

static void start_mode(pm_t *m, int idx)
{
    if (!build_mode(m, idx)) return;
    m->hits = 0; m->total = 0; m->paused = 0; m->ended_logged = 0; m->running_seen = 1;
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
    m->secs = m->seconds;
    lg("\"%s\" STARTED for %d s", m->name, m->seconds);
}

/* Mode::end runs on the game's proc thread like all the game's own mode
 * changes: called from a proc (a switch dispatch) it ends the mode at once;
 * called from the render thread it is handed to the mode's own tick hook. */
static int (*am_proc)(void);
static void end_mode(pm_t *m, const char *why)
{
    if (!running(m)) return;
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

static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static int in_list(const int *l, int n, int v) { for (int i = 0; i < n; i++) if (l[i] == v) return 1; return 0; }

/* Test hook for the emulator, where no ball can reach a game mode's start:
 * JJP_MODS_TEST_GAMEMODE=<Mode global> JJP_MODS_TEST_SWITCH=<switch> starts
 * that game mode (its own Mode::start) when that switch is hit, so a proof run
 * can show a custom mode yielding to it.  Unset on a machine. */
static void *test_gm; static int test_sw = -1;
static void test_hook(int si)
{
    if (si != test_sw || !test_gm) return;
    if (((vbool_t)vslot(test_gm, VT_IS_RUNNING))(test_gm) & 0xff) return;
    lg("TEST: starting game mode %s", getenv("JJP_MODS_TEST_GAMEMODE"));
    ((vbool_t)vslot(test_gm, VT_START))(test_gm);
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
        if (!m->paused && in_list(m->shot_sw, m->nshot, si)) {
            ((vull_t)vslot(m->mode, VT_SCORE))(m->mode, (unsigned long long)m->points);
            m->total += m->points; m->hits++;
            lg("\"%s\" shot %s: +%lld (hits %d, mode total %lld)", m->name, wsw[si].name, m->points, m->hits, m->total);
            if (m->complete > 0 && m->hits >= m->complete) {
                if (m->complete_points) {
                    ((vull_t)vslot(m->mode, VT_SCORE))(m->mode, (unsigned long long)m->complete_points);
                    m->total += m->complete_points;
                }
                lg("\"%s\" COMPLETED (+%lld, mode total %lld)", m->name, m->complete_points, m->total);
                play(m->snd_complete ? m->snd_complete : m->snd_shot);
                end_mode(m, "completion");
            } else play(m->snd_shot);
        } else if (m->paused && in_list(m->shot_sw, m->nshot, si))
            lg("\"%s\" shot %s while paused: not scored", m->name, wsw[si].name);
        pthread_mutex_unlock(&mu);
        return;
    }
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        if (!in_list(m->start_sw, m->nstart, si)) continue;
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
    m->running_seen = 0; m->paused = 0;
    lamps_release(m);
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
        for (int i = 0; i < npm; i++) end_mode(&pms[i], "ball end");
        lg("ball over");
    }
    was_ingame = ig;
    if (!ig) {
        for (int i = 0; i < npm; i++) mode_over(&pms[i]);
        return;
    }
    if (bg_snapshot_at >= 0 && now_ms() >= bg_snapshot_at) {
        bg_snapshot_at = -1;
        if (!any_ours_running())
            for (int i = 0; i < ngm; i++)
                if (!gmode_bg[i] && gm_running(i)) { gmode_bg[i] = 1; lg("always-on game mode: %s", gmode_sym[i]); }
    }
    if ((frames & 7) == 0) log_running_set();
    {   /* evidence for every multiball yield */
        static int last_bip = -1;
        int bip = balls_in_play ? balls_in_play() : -1;
        if (bip != last_bip) { lg("balls in play: %d", bip); last_bip = bip; }
        if (bip > 1 && !multiball_since) multiball_since = now_ms();
        else if (bip <= 1) multiball_since = 0;
    }
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        if (!m->mode) continue;
        int r = running(m);
        if (r) {
            const char *busy = m->game_modes == POLICY_IGNORE ? NULL : game_busy();
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
    snprintf(secs, sizeof secs, "%d", m->secs);
    ALLEGRO_COLOR black = { 0, 0, 0, 1 };
    void *ft = m->font_title && jfont ? jfont(m->font_title) : NULL;
    void *fv = m->font_value && jfont ? jfont(m->font_value) : NULL;
    void *fm = m->font_timer && jfont ? jfont(m->font_timer) : NULL;
    float cx = W / 2;
    if (plot_os && ft) plot_os(ft, col(m->title_rgba), black, 2, black, 3, cx, y0 + H * 0.01f, 1, m->title);
    if (plot_os && fv) plot_os(fv, col(m->value_rgba), black, 2, black, 3, cx, y0 + H * 0.10f, 1, total);
    if (plot_os && fm) plot_os(fm, col(m->timer_rgba), black, 2, black, 3, x1 - W * 0.05f, y0 + H * 0.06f, 1, secs);
    if (!ft || !fv || !fm || !plot_os) {     /* the built-in font for whatever has no game font */
        if (!bfont && builtin_font) bfont = builtin_font();
        if (bfont && scale_xf && trans_xf) {
            const char *s[3] = { ft ? NULL : m->title, fv ? NULL : total, fm ? NULL : secs };
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
        per_frame();
        stock_frame();
        for (int i = 0; i < npm; i++)
            if (running(&pms[i]) && !pms[i].paused) { draw_screen(&pms[i]); break; }
        pthread_mutex_unlock(&mu);
    }
    if (real_flip) real_flip();
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
    mode_ctor = (mode_ctor_t)need("_ZN4ModeC1EPKciP11ModeManagerP4LampjjjP5AuditS7_");
    state_get = (int_fn_t)need("_Z14jjpe_state_getv");
    balls_in_play = (int_fn_t)sym("_Z28mb_get_logical_balls_in_playv");
    if (!balls_in_play) balls_in_play = (int_fn_t)sym("_Z20mb_get_balls_in_playv");
    am_proc = (int (*)(void))sym("_Z16proc_am_i_a_procv");
    ball_flag = (int (*)(void))sym("_Z26game_flow_get_ball_in_playv");
    if (!resolve_vtable() || !mode_ctor || !state_get) { lg("FAIL: this game's engine lacks what a mode needs"); return NULL; }
    find_game_modes();
    install_hold();
    if (getenv("JJP_MODS_TEST_GAMEMODE") && getenv("JJP_MODS_TEST_SWITCH")) {
        test_gm = sym(getenv("JJP_MODS_TEST_GAMEMODE"));
        test_sw = sw_index(getenv("JJP_MODS_TEST_SWITCH"));
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
    const char *must[] = { "_ZN4ModeC1EPKciP11ModeManagerP4LampjjjP5AuditS7_", "_Z14jjpe_state_getv",
                           "_ZN11SoundEffect4playEv", "_ZN10LampBufferC1EiPFvPS_EPKc9lb_flag_t",
                           "_ZN4Lamp3setER10LampBufferhhhh", "_ZN4Lamp11transparentER10LampBuffer",
                           "_ZN10LampBuffer10render_allEv", "_ZN8JJPEFont4fontEv", "al_flip_display" };
    for (unsigned i = 0; i < sizeof must / sizeof *must; i++)
        if (!sym(must[i])) { lg("SELFTEST missing %s", must[i]); bad++; }
    if (!resolve_vtable()) { lg("SELFTEST Mode vtable did not resolve"); bad++; }
    load_modes();
    for (int i = 0; i < nwsw; i++)
        if (!wsw[i].obj) bad++;
    for (int i = 0; i < npm; i++) {
        pm_t *m = &pms[i];
        for (int s2 = 0; s2 < 4; s2++)
            if (*m->snd_names[s2] && !(s2 == 0 ? m->snd_start : s2 == 1 ? m->snd_shot : s2 == 2 ? m->snd_end : m->snd_complete)) bad++;
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
    if (getenv("JJP_MODS_SELFTEST")) selftest();
    pthread_t t;
    if (pthread_create(&t, NULL, installer, NULL) == 0) pthread_detach(t);
}
