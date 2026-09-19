/* desk_harness.c - play modes at the DESK, without the game (item 152).
 *
 * Compiled for the PC (Linux, or any ELF toolchain: it finds the modes through the same
 * pm_modes section the runtime walks) with one or more mode files, it stands in for the
 * runtime: it calls every mode's init, ticks, shots, ball ends and events the way the game
 * does, and answers every pm_ call from a small fake game that prints what the modes do.
 *
 *   gcc -std=gnu17 -I.. -o harness desk_harness.c ghidorah_heads.c oxygen_destroyer.c ...
 *   ./harness shot "Powerline left" shot "Powerline center" shot "Powerline right" secs 5
 *
 * Commands (arguments, in order):
 *   tick <n>            n game ticks (60 a second; the clock advances 1000/60 ms each)
 *   secs <s>            s seconds of ticks
 *   ms <n>              n milliseconds of ticks
 *   shot <name>         the game dispatches 0x1, then the named shot's bit (as Godzilla does),
 *                       then 50 ms of ticks pass
 *   raw <mask>          one dispatch of a mask as given
 *   event <name>        the game fires a named event (skill_shot, ball_start ...)
 *   battle <0|1>        the game's own kaiju battle is active or not
 *   multiball <0|1>     the game's own multiball is active or not
 *   ball_end            the ball drained
 *   player <n>          the player up
 *   game_over           pm_in_game() falls
 *   new_game            a new game: player 1, every score 0, pm_in_game() 1
 *   trigger <file>      /dump/<file> appears (a mode's test trigger), with optional text: trigger f=text
 *   covered <0|1>       a display of the game's that beats the held display priority has the screen
 *   lamps               print every insert held now: "HELD <name> <rrggbb> <pattern> <ms> <mode>"
 *
 * Every line a mode logs is printed as "<ms> [<mode>] <text>", every score as "SCORE +<n>",
 * every word written to a screen as "WORDS <node>: <words>", every show/hide as "SHOW <node> 0|1",
 * every light command as "LIGHTS <command>" and every callout as "CALLOUT <id> [n]".
 * A mode's OWN sounds and clip (pad_mode_assets.h) print as "SOUND <request>", "FADE <request> <ms>",
 * "STOP <request>", "SID <request> <sid>", "PRIO <request> <priority> <flags>" and "CLIP <name>";
 * its <folder>.assets file is read from $HARNESS_DUMP (the rig's /dump).
 * The playfield's inserts (item 157) print as "LAMP <name> <rrggbb> <pattern> <ms> <mode>" when held,
 * "LAMP OFF <name> <mode>" when handed back and "LAMP PRIORITY <p> <mode>"; the display priority as
 * "DISPLAY <p> <mode>" ("DISPLAY 0" given up, "DISPLAY released" when its mode ended without it).
 * The last line says how many inserts are still held and the display priority still held.
 */
#define _GNU_SOURCE
#include "pad_mode.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

extern const struct pm_mode *const __start_pm_modes[];
extern const struct pm_mode *const __stop_pm_modes[];

/* ---- the fake game ------------------------------------------------------------------------ */
static const struct { const char *name; uint64_t mask; } SHOTS[] = {    /* godzilla_le-1.16.port */
    { "Left ramp", 0x00100000ull }, { "Right ramp", 0x00200000ull }, { "Building", 0x00400000ull },
    { "Godzilla target", 0x00080000ull }, { "Maser target", 0x08000000ull },
    { "Powerline left", 0x10000000ull }, { "Powerline center", 0x20000000ull },
    { "Powerline right", 0x40000000ull }, { "Shield target left", 0x80000000ull },
    { "Shield target center", 0x100000000ull }, { "Shield target right", 0x200000000ull },
    { "Skill shot", 0x400000000ull }, { "Big loop", 0x1000000000ull }, { "Slingshot", 0x2ull },
    { "Left return lane", 0x4ull }, { "Right return lane", 0x10ull }, { "Pop bumper", 0x40ull },
    { "Mecha exit bottom", 0x10000000000ull },
};
#define N_SHOTS (int)(sizeof SHOTS / sizeof SHOTS[0])
static const struct { const char *name; int id; } EVENTS[] = {
    { "game_start", 0x4d }, { "ball_start", 0x25 }, { "ball_end", 0x34 }, { "bonus_start", 0x27 },
    { "bonus_end", 0x28 }, { "tilt_warning", 0xc8 }, { "tilt", 0xc6 }, { "game_over", 0x47 },
    { "skill_shot", 0xd0 }, { "multiball_start", 0xd1 }, { "multiball_end", 0xd2 },
};
#define N_EVENTS (int)(sizeof EVENTS / sizeof EVENTS[0])

static unsigned long now_ms, ticks;
static unsigned player = 1;
static int in_game = 1, battle, multiball;
static uint64_t score[5];
static const struct pm_mode *current, *running;
static char trigger_file[64], trigger_text[128];

struct fake_node { char name[160]; };
static struct fake_node nodes[64];
static int n_nodes;

static void *fake(const char *path)
{
    int i;
    for (i = 0; i < n_nodes; i++)
        if (!strcmp(nodes[i].name, path)) return &nodes[i];
    if (n_nodes == 64) return 0;
    snprintf(nodes[n_nodes].name, sizeof nodes[n_nodes].name, "%s", path);
    return &nodes[n_nodes++];
}

void pm_log(const char *fmt, ...)
{
    va_list ap;
    printf("%6lu [%s] ", now_ms, current && current->name ? current->name : "?");
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    putchar('\n');
}
int pm_snprintf(char *o, unsigned long cap, const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(o, cap, fmt, ap);
    va_end(ap);
    return n;
}
void pm_commas(char *out, unsigned cap, uint64_t v)
{
    char d[32];
    int n = snprintf(d, sizeof d, "%llu", (unsigned long long)v), i, k = 0;
    for (i = 0; i < n && k + 2 < (int)cap; i++) {
        if (i && (n - i) % 3 == 0) out[k++] = ',';
        out[k++] = d[i];
    }
    out[k] = 0;
}
unsigned long pm_ms(void) { return now_ms; }
int pm_can(unsigned what) { (void)what; return 1; }
const char *pm_game(void) { return "godzilla_le"; }
const char *pm_version(void) { return "1.16"; }
int pm_in_game(void) { return in_game && player; }
unsigned pm_player(void) { return player; }
uint64_t pm_score(unsigned p) { return p >= 1 && p <= 4 ? score[p] : 0; }
uint64_t pm_score_add(unsigned p, uint64_t v)
{
    if (p < 1 || p > 4) return 0;
    score[p] += v;
    printf("%6lu SCORE +%llu (player %u: %llu)\n", now_ms, (unsigned long long)v, p, (unsigned long long)score[p]);
    return v;
}
uint64_t pm_shot(const char *name)
{
    int i;
    for (i = 0; i < N_SHOTS; i++)
        if (!strcmp(SHOTS[i].name, name)) return SHOTS[i].mask;
    return 0;
}
const char *pm_shot_name(uint64_t shot)
{
    int i;
    for (i = 0; i < N_SHOTS; i++)
        if (shot & SHOTS[i].mask) return SHOTS[i].name;
    return 0;
}
int pm_shot_count(void) { return N_SHOTS; }
const char *pm_shot_at(int i, uint64_t *mask)
{
    if (i < 0 || i >= N_SHOTS) return 0;
    if (mask) *mask = SHOTS[i].mask;
    return SHOTS[i].name;
}
int pm_begin(void)
{
    if (running && running != current) {
        pm_log("not started: %s is running", running->name);
        return 0;
    }
    running = current;
    return 1;
}
void pm_end(void) { if (running == current) running = 0; }
int pm_running(void) { return running && running == current; }
unsigned pm_callout_id(const char *role)
{
    return !strcmp(role, "countdown") ? 1287 : !strcmp(role, "ten_seconds") ? 1291 : !strcmp(role, "time_up") ? 1295 : 0;
}
void pm_callout(unsigned id) { if (id) printf("%6lu CALLOUT %u\n", now_ms, id); }
void pm_callout_nth(unsigned id, unsigned n) { if (id) printf("%6lu CALLOUT %u %u\n", now_ms, id, n); }
int pm_lights(const char *c) { printf("%6lu LIGHTS %s\n", now_ms, c); return 1; }
int pm_lights_as(unsigned o, const char *c) { (void)o; return pm_lights(c); }
const char *pm_scene_id(const char *role) { (void)role; return 0; }
void *pm_node(const char *scene, const char *path) { (void)scene; return fake(path); }
void *pm_text(const char *scene, const char *path) { (void)scene; return fake(path); }
void pm_show(void *node, int on) { printf("%6lu SHOW %s %d\n", now_ms, ((struct fake_node *)node)->name, on); }
void pm_set_text(void *text, const char *words)
{
    const char *n = ((struct fake_node *)text)->name, *dot = strrchr(n, '.');
    printf("%6lu WORDS %s: %s\n", now_ms, dot ? dot + 1 : n, words);
}
int pm_clip(const char *name) { printf("%6lu CLIP %s\n", now_ms, name); return 1; }
int pm_clip_playing(void) { return 0; }
void pm_clip_stop(void) {}
const char *pm_port_text(const char *name)
{
    if (!strcmp(name, "example_lights_on"))
        return "blele --sweep 0 --lts 224 --red 0 --green 255 --blue 0 --freq 10 --use_alpha 1 --alpha 255";
    if (!strcmp(name, "example_lights_off"))
        return "blele --sweep 1 --lts 224 --fade 20 --rgb 0 --freq 10 --delay_start 15 --end 1";
    return 0;
}
long pm_port_value(const char *name, long fallback) { (void)name; return fallback; }
int pm_trigger_text(const char *name, char *out, unsigned cap)
{
    if (!trigger_file[0] || strcmp(name, trigger_file)) return 0;
    trigger_file[0] = 0;
    if (out && cap) snprintf(out, cap, "%s", trigger_text);
    return 1;
}
int pm_trigger(const char *name) { return pm_trigger_text(name, 0, 0); }
/* /dump/<name> is read from $HARNESS_DUMP/<name> when that is set (a code mode's <folder>.assets,
 * pad_mode_assets.h); the card's /usr/local/padmode is never there */
long pm_read_file(const char *path, char *buf, unsigned long cap)
{
    const char *dir = getenv("HARNESS_DUMP");
    char p[512];
    FILE *f;
    long n;
    if (!dir || strncmp(path, "/dump/", 6)) return -1;
    snprintf(p, sizeof p, "%s/%s", dir, path + 6);
    f = fopen(p, "rb");
    if (!f) return -1;
    n = (long)fread(buf, 1, cap, f);
    fclose(f);
    return n;
}

/* ---- the fake sound engine (the mode's own sounds, pad_mode_assets.h) -------------------------------
 * A request plays until it is stopped or faded. Request 125 (Godzilla's music carrier) plays on the
 * music bus, every other on the voice bus. The GAME'S music, request 67 at priority 1, plays from the
 * start, as in attract and in play. Every call is printed: SOUND, FADE, STOP, SID, PRIO. */
#define MUSIC_CARRIER 125u
#define GAME_MUSIC    67u
static struct { unsigned req, bus; } snd_on[16] = { { GAME_MUSIC, 1 } };
static int snd_n = 1;
static struct { unsigned req; int pair; } snd_prio[32];
static int snd_prio_n;

static int snd_find(unsigned req)
{
    int i;
    for (i = 0; i < snd_n; i++)
        if (snd_on[i].req == req) return i;
    return -1;
}
static void snd_drop(unsigned req)
{
    int i = snd_find(req);
    if (i >= 0) snd_on[i] = snd_on[--snd_n];
}
int pm_sound(unsigned request)
{
    printf("%6lu SOUND %u\n", now_ms, request);
    if (snd_find(request) < 0 && snd_n < 16) {
        snd_on[snd_n].req = request;
        snd_on[snd_n++].bus = (request == MUSIC_CARRIER || request == GAME_MUSIC) ? 1u : 2u;
    }
    return 1;
}
int pm_sound_active(unsigned request) { return snd_find(request) >= 0; }
int pm_sound_stop(unsigned request)
{
    int was = snd_find(request) >= 0;
    printf("%6lu STOP %u\n", now_ms, request);
    snd_drop(request);
    return was;
}
int pm_sound_fade(unsigned request, unsigned ms)
{
    int was = snd_find(request) >= 0;
    if (was) printf("%6lu FADE %u %u\n", now_ms, request, ms);
    snd_drop(request);
    return was;
}
int pm_sound_sid(unsigned request, unsigned sid)
{
    printf("%6lu SID %u %u\n", now_ms, request, sid);
    return 1;
}
int pm_sound_playing(unsigned *requests, unsigned *buses, int max)
{
    int i;
    for (i = 0; i < snd_n && i < max; i++) {
        requests[i] = snd_on[i].req;
        buses[i] = snd_on[i].bus;
    }
    return snd_n;
}
int pm_sound_priority(unsigned request, int priority, int flags)
{
    int i, old;
    for (i = 0; i < snd_prio_n && snd_prio[i].req != request; i++) ;
    if (i == snd_prio_n) {
        if (snd_prio_n == 32) return -1;
        snd_prio[snd_prio_n].req = request;
        snd_prio[snd_prio_n++].pair = (request == MUSIC_CARRIER || request == GAME_MUSIC) ? (1 << 8 | 1) : (2 << 8 | 1);
    }
    old = snd_prio[i].pair;
    if (priority >= 0 || flags >= 0) {
        snd_prio[i].pair = ((priority >= 0 ? priority : old >> 8) << 8) | (flags >= 0 ? flags : (old & 0xff));
        printf("%6lu PRIO %u %d %d\n", now_ms, request, snd_prio[i].pair >> 8, snd_prio[i].pair & 0xff);
    }
    return old;
}
int pm_stock_mode_running(unsigned kinds)
{
    if ((kinds & PM_STOCK_BATTLE) && battle) return PM_STOCK_BATTLE;
    if ((kinds & PM_STOCK_MULTIBALL) && multiball) return PM_STOCK_MULTIBALL;
    if ((kinds & PM_STOCK_ANY) && (battle || multiball)) return PM_STOCK_ANY;
    return 0;
}
const char *pm_stock_mode_what(unsigned kind)
{
    return kind & PM_STOCK_BATTLE ? "a battle" : kind & PM_STOCK_MULTIBALL ? "a multiball" : "a stock mode";
}
int pm_event(const char *name)
{
    int i;
    for (i = 0; i < N_EVENTS; i++)
        if (!strcmp(EVENTS[i].name, name)) return EVENTS[i].id;
    return -1;
}
const char *pm_event_name(unsigned id)
{
    int i;
    for (i = 0; i < N_EVENTS; i++)
        if (EVENTS[i].id == (int)id) return EVENTS[i].name;
    return 0;
}

/* ---- the fake inserts (item 157): the Premium 1.16 port's lamp lines the modes can reach ---------- */
static const struct { const char *name; uint64_t shot; } LAMPS[] = {    /* godzilla_le-1.16.port `lamp` */
    { "LEFT RAMP", 0x100000ull }, { "RIGHT RAMP", 0x200000ull }, { "BUILDING", 0xc00000ull },
    { "MAGNA GRAB", 0x80000ull }, { "MASER", 0x8000000ull }, { "MASER READY", 0 },
    { "POWERLINE LEFT", 0x10000000ull }, { "POWERLINE CENTER", 0x20000000ull }, { "POWERLINE RIGHT", 0x40000000ull },
    { "SHIELD LEFT", 0x80000000ull }, { "SHIELD CENTER", 0x100000000ull }, { "SHIELD RIGHT", 0x200000000ull },
    { "SKILL SHOT", 0x400000000ull }, { "BIG LOOP", 0x1000000000ull }, { "TOP SPINNER", 0x1800ull },
    { "POP BUMPER", 0x40ull }, { "TANK 2", 0 }, { "HEAT RAY", 0 },
};
#define N_LAMPS (int)(sizeof LAMPS / sizeof LAMPS[0])
static const char *const PATTERN[] = { "solid", "blink", "pulse", "chase" };
static struct { const struct pm_mode *owner; unsigned rgb, ms; int pattern; } held[N_LAMPS];
static const struct pm_mode *disp_owner;
static unsigned disp_prio;
static int covered;

static const char *mode_name(const struct pm_mode *m) { return m && m->name ? m->name : "?"; }

static int lamp_is(int k, const char *s, size_t len)
{
    size_t i;
    while (len && *s == ' ') { s++; len--; }
    while (len && s[len - 1] == ' ') len--;
    if (strlen(LAMPS[k].name) != len) return 0;
    for (i = 0; i < len; i++)
        if ((s[i] >= 'a' && s[i] <= 'z' ? s[i] - 32 : s[i]) != LAMPS[k].name[i]) return 0;
    return 1;
}

int pm_lamp_count(void) { return N_LAMPS; }
const char *pm_lamp_at(int i, uint64_t *shots)
{
    if (i < 0 || i >= N_LAMPS) return 0;
    if (shots) *shots = LAMPS[i].shot;
    return LAMPS[i].name;
}
int pm_lamp_find(const char *name)
{
    int k;
    for (k = 0; k < N_LAMPS; k++)
        if (lamp_is(k, name, strlen(name))) return k;
    return -1;
}
static void lamp_hold(int k, unsigned rgb, int pattern, unsigned ms)
{
    if (pattern < 0 || pattern > 3) pattern = 0;
    if (!ms) ms = pattern == PM_LAMP_BLINK ? 500 : pattern == PM_LAMP_PULSE ? 1600 : pattern == PM_LAMP_CHASE ? 150 : 0;
    held[k].owner = current;
    held[k].rgb = rgb & 0xffffffu;
    held[k].pattern = pattern;
    held[k].ms = ms;
    printf("%6lu LAMP %s %06x %s %u %s\n", now_ms, LAMPS[k].name, held[k].rgb, PATTERN[pattern], ms, mode_name(current));
}
static void lamp_off(int k)
{
    printf("%6lu LAMP OFF %s %s\n", now_ms, LAMPS[k].name, mode_name(current));
    held[k].owner = 0;
}
/* each name of a comma-separated list: fn(k) for an insert found; unknown names are printed */
static int lamp_each(const char *names, void (*fn)(int, unsigned, int, unsigned), unsigned rgb, int pattern, unsigned ms,
                     int release)
{
    const char *s = names, *e;
    int n = 0, k;
    while (s && *s) {
        for (e = s; *e && *e != ','; e++) ;
        for (k = 0; k < N_LAMPS && !lamp_is(k, s, (size_t)(e - s)); k++) ;
        if (k == N_LAMPS) printf("%6lu LAMP UNKNOWN %.*s\n", now_ms, (int)(e - s), s);
        else if (!release) { fn(k, rgb, pattern, ms); n++; }
        else if (held[k].owner == current) { lamp_off(k); n++; }
        s = *e ? e + 1 : e;
    }
    return n;
}
int pm_lamp_set(const char *names, unsigned rgb, int pattern, unsigned ms)
{
    return lamp_each(names, lamp_hold, rgb, pattern, ms, 0);
}
int pm_lamp_shot(uint64_t shots, unsigned rgb, int pattern, unsigned ms)
{
    int k, n = 0;
    for (k = 0; k < N_LAMPS; k++)
        if (LAMPS[k].shot & shots) { lamp_hold(k, rgb, pattern, ms); n++; }
    return n;
}
int pm_lamp_release(const char *names) { return lamp_each(names, 0, 0, 0, 0, 1); }
int pm_lamp_release_shot(uint64_t shots)
{
    int k, n = 0;
    for (k = 0; k < N_LAMPS; k++)
        if ((LAMPS[k].shot & shots) && held[k].owner == current) { lamp_off(k); n++; }
    return n;
}
int pm_lamp_release_all(void)
{
    int k, n = 0;
    for (k = 0; k < N_LAMPS; k++)
        if (held[k].owner && held[k].owner == current) { lamp_off(k); n++; }
    return n;
}
int pm_lamp_priority(unsigned p)
{
    printf("%6lu LAMP PRIORITY %u %s\n", now_ms, p, mode_name(current));
    return (int)p;
}
int pm_lamp_layers(unsigned *priorities, int max) { (void)priorities; (void)max; return -1; }
static int lamps_held(void)
{
    int k, n = 0;
    for (k = 0; k < N_LAMPS; k++) n += held[k].owner != 0;
    return n;
}

/* the display arbitration, as the runtime keeps it: only the RUNNING mode may hold a priority */
int pm_display_priority(unsigned p)
{
    if (!p) {
        if (disp_prio && disp_owner == current) {
            printf("%6lu DISPLAY 0 %s\n", now_ms, mode_name(current));
            disp_prio = 0;
            disp_owner = 0;
        }
        return 1;
    }
    if (!running || running != current) return 0;
    disp_prio = p > 255 ? 255 : p;
    disp_owner = current;
    printf("%6lu DISPLAY %u %s\n", now_ms, disp_prio, mode_name(current));
    return 1;
}
int pm_display_covered(void) { return disp_prio && covered; }

/* ---- the runtime's part: call every mode ----------------------------------------------------- */
#define EACH_MODE(m) for (const struct pm_mode *const *pp = __start_pm_modes; pp < __stop_pm_modes && ((m) = *pp, 1); pp++)

static void tick(void)
{
    const struct pm_mode *m;
    ticks++;
    now_ms = ticks * 1000 / 60;
    EACH_MODE(m) if (m->tick) { current = m; m->tick(); }
    current = 0;
    if (disp_prio && running != disp_owner) {           /* the runtime's display_tick does the same */
        printf("%6lu DISPLAY released %s (the mode that held it ended)\n", now_ms, mode_name(disp_owner));
        disp_prio = 0;
        disp_owner = 0;
    }
}

static void dispatch(uint64_t mask)
{
    const struct pm_mode *m;
    EACH_MODE(m) if (m->shot) { current = m; m->shot(mask); }
    current = 0;
}

static void ticks_for_ms(unsigned long ms)
{
    unsigned long until = now_ms + ms;
    while (now_ms < until) tick();
}

int main(int argc, char **argv)
{
    const struct pm_mode *m;
    int k;
    EACH_MODE(m) if (m->init) { current = m; m->init(); }
    current = 0;
    ticks_for_ms(1000);
    for (k = 1; k < argc; k++) {
        const char *c = argv[k];
        if (!strcmp(c, "tick")) { long n = atol(argv[++k]); while (n-- > 0) tick(); }
        else if (!strcmp(c, "secs")) ticks_for_ms((unsigned long)(atof(argv[++k]) * 1000.0));
        else if (!strcmp(c, "ms")) ticks_for_ms((unsigned long)atol(argv[++k]));
        else if (!strcmp(c, "shot")) {
            uint64_t mask = pm_shot(argv[++k]);
            if (!mask) { fprintf(stderr, "no shot named %s\n", argv[k]); return 2; }
            printf("%6lu >> shot %s\n", now_ms, argv[k]);
            dispatch(0x1);
            dispatch(mask);
            ticks_for_ms(50);
        } else if (!strcmp(c, "raw")) {
            dispatch(strtoull(argv[++k], 0, 0));
        } else if (!strcmp(c, "event")) {
            int id = pm_event(argv[++k]);
            printf("%6lu >> event %s\n", now_ms, argv[k]);
            EACH_MODE(m) if (m->event && id >= 0) { current = m; m->event((unsigned)id); }
            current = 0;
        } else if (!strcmp(c, "battle")) { battle = atoi(argv[++k]); printf("%6lu >> battle %d\n", now_ms, battle); }
        else if (!strcmp(c, "multiball")) { multiball = atoi(argv[++k]); printf("%6lu >> multiball %d\n", now_ms, multiball); }
        else if (!strcmp(c, "ball_end")) {
            printf("%6lu >> ball_end\n", now_ms);
            EACH_MODE(m) if (m->ball_end) { current = m; m->ball_end(); }
            current = 0;
        } else if (!strcmp(c, "player")) player = (unsigned)atoi(argv[++k]);
        else if (!strcmp(c, "game_over")) in_game = 0;
        else if (!strcmp(c, "new_game")) {
            int p;
            for (p = 0; p < 5; p++) score[p] = 0;
            in_game = 1;
            player = 1;
            printf("%6lu >> new_game\n", now_ms);
        } else if (!strcmp(c, "trigger")) {
            const char *eq = strchr(argv[++k], '=');
            size_t n = eq ? (size_t)(eq - argv[k]) : strlen(argv[k]);
            snprintf(trigger_file, sizeof trigger_file, "%.*s", (int)n, argv[k]);
            snprintf(trigger_text, sizeof trigger_text, "%s", eq ? eq + 1 : "");
            ticks_for_ms(600);                 /* the modes look twice a second */
        } else if (!strcmp(c, "covered")) {
            covered = atoi(argv[++k]);
            printf("%6lu >> covered %d\n", now_ms, covered);
        } else if (!strcmp(c, "lamps")) {
            int n = 0;
            for (int i = 0; i < N_LAMPS; i++)
                if (held[i].owner) {
                    printf("%6lu HELD %s %06x %s %u %s\n", now_ms, LAMPS[i].name, held[i].rgb, PATTERN[held[i].pattern],
                           held[i].ms, mode_name(held[i].owner));
                    n++;
                }
            if (!n) printf("%6lu HELD none\n", now_ms);
        } else {
            fprintf(stderr, "unknown command %s\n", c);
            return 2;
        }
    }
    printf("%6lu END score player 1 %llu\n", now_ms, (unsigned long long)score[1]);
    printf("%6lu END lamps held %d, display priority %u\n", now_ms, lamps_held(), disp_prio);
    return 0;
}
