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

#define SDK_VERSION "2"

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
    else if (!strcmp(k, "panel")) m->panel = !strcmp(v, "bottom") ? 1 : !strcmp(v, "top") ? 2 : !strcmp(v, "none") ? 3 : 0;
    else if (!strcmp(k, "ingame_state")) { ingame_state = (int)num(v); ingame_explicit = 1; }
    else if (!strcmp(k, "game")) snprintf(game_name, sizeof game_name, "%s", v);
    else if (!strcmp(k, "background_modes")) {
        background_explicit = 1;
        snprintf(background_names, sizeof background_names, " %s ", v);
    } else lg("%s: unknown key %s (ignored)", m->file, k);
}

static int load_file(pm_t *m, const char *path)
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
        apply_kv(m, k, v);
    }
    fclose(f);
    return 1;
}

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
}

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
    struct dirent *de;
    while ((de = readdir(d)) && nn < MAX_MODES * 2) {
        size_t L = strlen(de->d_name);
        if (L > 5 && !strcmp(de->d_name + L - 5, ".mode")) names[nn++] = strdup(de->d_name);
    }
    closedir(d);
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
            if (m->own_snd[s]) { *slot = NULL; continue; }     /* a file of ours: made once the game's sounds are in (media_loader) */
            *slot = sym(m->snd_names[s]);
            if (*m->snd_names[s] && !*slot) lg("%s: no sound called %s in this game", m->file, m->snd_names[s]);
        }
        if (!m->nstart) { lg("%s: no start shot found; mode skipped", m->file); continue; }
        if (m->seconds < 1) m->seconds = 1;
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
static void walk_dynsym(void (*cb)(const char *name, uintptr_t addr, size_t size))
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
        if (ELF64_ST_TYPE(s->st_info) != STT_OBJECT || !s->st_value || s->st_shndx == SHN_UNDEF) continue;
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

static void install_hold(void)
{
    for (int i = 0; i < npm; i++) if (pms[i].game_modes == POLICY_HOLD) hold_wanted = 1;
    if (!hold_wanted) { lg("hold: no mode holds the game off (game_modes pause/end/ignore); the game's starts untouched"); return; }
    ti_mode = (uintptr_t)sym("_ZTI4Mode");
    ti_mbr = (uintptr_t)sym("_ZTI13MultiballRule");
    uintptr_t si = (uintptr_t)sym("_ZTVN10__cxxabiv120__si_class_type_infoE");
    uintptr_t vmi = (uintptr_t)sym("_ZTVN10__cxxabiv121__vmi_class_type_infoE");
    si_ti_vt = si ? si + 16 : 0; vmi_ti_vt = vmi ? vmi + 16 : 0;
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
    if (m->music && update_music_fn) {    /* our music on while the mode has the floor, the game's otherwise */
        int idx = (int)(m - pms);
        int want = music_wanted(m), have = music_claimed == idx + 1;
        if (want != have && now_ms() - music_asked_at >= 500) music_reconsider(want ? "mode running" : "mode over or paused");
    }
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
    if (*m->vid_file && !m->vid) m->vid = video_start(m);
    if (m->music) music_reconsider("mode started");
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
    if (m->vid) { video_stop(m->vid); m->vid = NULL; }
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
        if (m->vid) m->vid->pause = r && m->paused;
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
        load_pictures();                          /* on the render thread: bitmaps are GL textures */
        per_frame();
        for (int i = 0; i < npm; i++)
            if (running(&pms[i]) && !pms[i].paused) { draw_screen(&pms[i]); break; }
        pthread_mutex_unlock(&mu);
    }
    if (real_flip) real_flip();
}

static void hook_crashes(int chain);

/* ---- install --------------------------------------------------------------- */
static void *installer(void *arg)
{
    (void)arg;
    lg("PAD JJP mode SDK %s, modes from %s", SDK_VERSION, moddir);
    load_modes();
    if (!npm) { lg("no modes to run"); return NULL; }
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
    mode_ctor = (mode_ctor_t)need("_ZN4ModeC1EPKciP11ModeManagerP4LampjjjP5AuditS7_");
    state_get = (int_fn_t)need("_Z14jjpe_state_getv");
    balls_in_play = (int_fn_t)sym("_Z28mb_get_logical_balls_in_playv");
    if (!balls_in_play) balls_in_play = (int_fn_t)sym("_Z20mb_get_balls_in_playv");
    am_proc = (int (*)(void))sym("_Z16proc_am_i_a_procv");
    ball_flag = (int (*)(void))sym("_Z26game_flow_get_ball_in_playv");
    if (!resolve_vtable() || !mode_ctor || !state_get) { lg("FAIL: this game's engine lacks what a mode needs"); return NULL; }
    find_game_modes();
    install_hold();
    install_music_node();
    {   pthread_t mt;                             /* own sound files, once the game's sounds are in */
        if (pthread_create(&mt, NULL, media_loader, NULL) == 0) pthread_detach(mt); }
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
    lg("installed: %d mode(s), %d shot switch(es), ball-in-play state %d (now %d)", npm, hooked,
       ingame_state, attract_state);
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
    lg("SELFTEST %s: pid %d, GAMENAME %s, %d mode(s), %d shot switch(es), %d problem(s)",
       bad ? "FAIL" : "PASS", getpid(), getenv("GAMENAME") ? getenv("GAMENAME") : "?", npm, nwsw, bad);
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
