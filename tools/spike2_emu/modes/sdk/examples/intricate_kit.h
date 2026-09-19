/* intricate_kit.h - small helpers the INTRICATE example modes share (item 152).
 *
 * Each example mode (ghidorah_heads.c, oxygen_destroyer.c, maser_barrage.c, final_wars.c,
 * anguirus_assist.c) is one .c file that includes this header. Everything here is `static`,
 * so a mode built on its own still builds, and a mode copied out of this folder takes the
 * header with it. Nothing here calls the game except through pad_mode.h, and nothing here
 * runs from a constructor (MODE_SDK.md, "The rules").
 *
 * What is in it:
 *   - kit_fresh()      a shot DEBOUNCE: the same shot inside KIT_DEBOUNCE_MS counts once. A
 *                      standup target that bounces, or a switch pressed twelve times in a
 *                      second, must never pay twelve times.
 *   - struct kit_screen  the mode's own screen: find it, hide it, a STATUS line that can
 *                      alternate between two texts, a FLASH that covers it for a moment, and
 *                      the TOTAL at the end. The words are written only when they change
 *                      (every pm_set_text leaks a small string inside the game).
 *   - kit_lights()     the port's example light sweep in any colour, sent only on a change (the
 *                      five modes no longer use it: its light set includes the inserts around the
 *                      shots, measured in item 157, so it made unlit shots look lit).
 *   - struct kit_lamps  the playfield's INSERTS the mode holds (item 157): each tick the mode says
 *                      which shots are lit and how (a colour, a pattern, a speed), and only a
 *                      change reaches the game; kit_lamps_off() hands every one back.
 *   - kit_end()        also gives up the mode's display priority (item 157); a flash on the
 *                      screen counts its time only while the screen is in view.
 *   - kit_is_tilt()    the game's tilt event: every mode ends on it, lights and all.
 *   - struct kit_timer  a countdown in ticks with the game's ten-second and 5..1 callouts.
 *   - struct kit_game  "a new game began" (player 1's score back to 0), for per-game counts.
 *   - kit_ledger       what each pack mode did this game, for FINAL WARS's qualification.
 */
#ifndef INTRICATE_KIT_H
#define INTRICATE_KIT_H

#include "pad_mode.h"

#define KIT_TICKS        60          /* ticks a second */
#define KIT_POLL         30          /* trigger files, the screen search: twice a second */
#define KIT_DEBOUNCE_MS  250         /* one shot counts once in this long */
#define KIT_WORDS        48          /* the longest line a screen is given */

#define KIT_UNUSED __attribute__((unused))

/* ---- small string helpers (no libc) --------------------------------------------------- */
static KIT_UNUSED void kit_copy(char *dst, unsigned cap, const char *src)
{
    unsigned i;
    for (i = 0; src && src[i] && i + 1 < cap; i++) dst[i] = src[i];
    dst[i] = 0;
}

static KIT_UNUSED int kit_same(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

/* "12,340,000" */
static KIT_UNUSED const char *kit_num(char *buf, unsigned cap, uint64_t v)
{
    pm_commas(buf, cap, v);
    return buf;
}

/* ---- the debounce ------------------------------------------------------------------------
 * One slot per shot bit that has been seen: its last time. A shot bit seen again inside
 * KIT_DEBOUNCE_MS is not fresh. Measured motive (David, the film pack): one target hit
 * twelve times in a second paid 150,000,000 from a 30 s mode. */
#define KIT_DB_SLOTS 24
struct kit_db { uint64_t bit[KIT_DB_SLOTS]; unsigned long at[KIT_DB_SLOTS]; unsigned next; };

/* 1 if this shot (one bit, or a mask treated as one shot) counts now; it is then remembered */
static KIT_UNUSED int kit_fresh(struct kit_db *db, uint64_t bit)
{
    unsigned long now = pm_ms();
    unsigned i;
    if (!bit) return 0;
    for (i = 0; i < KIT_DB_SLOTS; i++)
        if (db->bit[i] == bit) {
            if (now - db->at[i] < KIT_DEBOUNCE_MS) {
                pm_log("%s again %lu ms after the last: counted once (debounce %d ms)",
                       pm_shot_name(bit) ? pm_shot_name(bit) : "a shot", now - db->at[i], KIT_DEBOUNCE_MS);
                return 0;
            }
            db->at[i] = now;
            return 1;
        }
    i = db->next++ % KIT_DB_SLOTS;
    db->bit[i] = bit;
    db->at[i] = now;
    return 1;
}

/* ---- the mode's own screen -----------------------------------------------------------------
 * A screen the card build added to the HUD scene for modes/<folder>/: the node
 * PadMode_<folder>_Screen and its words PadMode_<folder>_Screen.PadMode_<folder>_Screen_Words
 * (MODE_SDK.md, "Screens"). A mode must work without it: every call here is a no-op then. */
struct kit_screen {
    const char *node_name, *text_name;
    void *node, *text;
    unsigned tries;
    int up;                                /* shown */
    char status[2][KIT_WORDS];             /* the status line, and its alternate ("" = none) */
    unsigned alt_ms;                       /* alternate every this long */
    char flash[KIT_WORDS];
    unsigned long flash_until, hide_at;    /* pm_ms() */
    char written[KIT_WORDS];               /* what the text node holds now */
    unsigned long seen;                    /* pm_ms() of the last tick (item 157: covered time) */
};

static KIT_UNUSED void kit_screen_write(struct kit_screen *s, const char *words)
{
    if (kit_same(s->written, words)) return;
    kit_copy(s->written, sizeof s->written, words);
    if (s->text) pm_set_text(s->text, s->written);
}

/* The pack's screen that is up now. Every pack screen sits in the same place on the HUD, so a
 * screen coming up takes the place of the one showing (a mode's TOTAL from a moment ago). Weak and
 * shared, like the ledger below. */
__attribute__((weak, visibility("hidden"))) struct kit_screen *kit_screen_up;

static KIT_UNUSED void kit_screen_show(struct kit_screen *s, int on)
{
    if (on && kit_screen_up && kit_screen_up != s) {
        struct kit_screen *o = kit_screen_up;
        o->up = 0;
        o->hide_at = 0;
        o->flash[0] = 0;
        if (o->node) pm_show(o->node, 0);
    }
    if (on) kit_screen_up = s;
    else if (kit_screen_up == s) kit_screen_up = 0;
    s->up = on;
    s->hide_at = 0;
    if (s->node) pm_show(s->node, on);
}

/* Twice a second until found: the HUD scene can load after init. Found while the mode is
 * not using it, it is hidden at once (a built screen is visible until a mode hides it). */
static KIT_UNUSED void kit_screen_find(struct kit_screen *s)
{
    if (s->node || !pm_can(PM_CAN_SCREENS) || (s->tries++ % KIT_POLL) != 0) return;
    s->node = pm_node("hud", s->node_name);
    if (!s->node) return;
    s->text = pm_text("hud", s->text_name);
    s->written[0] = 0;
    pm_show(s->node, s->up);
    if (s->up && s->text) {
        const char *w = s->flash[0] ? s->flash : s->status[0];
        kit_copy(s->written, sizeof s->written, w);
        pm_set_text(s->text, s->written);
    }
    pm_log("screen %s found%s - %s", s->node_name, s->text ? ", with its words" : ", but NOT its words",
           s->up ? "shown, the mode is using it" : "hidden until the mode uses it");
}

/* the status line; `alt` ("" or 0 for none) alternates with it every `alt_ms` */
static KIT_UNUSED void kit_screen_status(struct kit_screen *s, const char *line, const char *alt)
{
    kit_copy(s->status[0], sizeof s->status[0], line);
    kit_copy(s->status[1], sizeof s->status[1], alt ? alt : "");
}

/* a message over the status line for `ms` */
static KIT_UNUSED void kit_screen_flash(struct kit_screen *s, unsigned ms, const char *line)
{
    kit_copy(s->flash, sizeof s->flash, line);
    s->flash_until = pm_ms() + ms;
    if (!s->up) kit_screen_show(s, 1);
    kit_screen_write(s, s->flash);
}

/* a message on a screen the mode is NOT using (qualification progress): shown for `ms`, then
 * hidden again. It is polite: while another pack screen is up (a mode running, or the total of
 * one that just ended) nothing is shown, since every screen sits in the same place. 1 = shown. */
static KIT_UNUSED int kit_screen_note(struct kit_screen *s, unsigned ms, const char *line)
{
    if (kit_screen_up && kit_screen_up != s) return 0;
    s->status[0][0] = s->status[1][0] = 0;
    kit_screen_flash(s, ms, line);
    s->hide_at = pm_ms() + ms;
    return 1;
}

/* hide the screen `ms` from now (0 = now) */
static KIT_UNUSED void kit_screen_hide_in(struct kit_screen *s, unsigned ms)
{
    if (!ms) { kit_screen_show(s, 0); return; }
    s->hide_at = pm_ms() + ms;
}

/* every tick: expire a flash, alternate the status, hide on time. While a display of the game's
 * that beat the mode's display priority covers the screen (pm_display_covered), a flash and a
 * pending hide do not use up their time: the player reads them once the screen is back. */
static KIT_UNUSED void kit_screen_tick(struct kit_screen *s)
{
    unsigned long now = pm_ms();
    if (s->up && s->seen && now > s->seen && pm_display_covered()) {
        unsigned long d = now - s->seen;
        if (s->flash[0] && s->flash_until) s->flash_until += d;
        if (s->hide_at) s->hide_at += d;
    }
    s->seen = now;
    kit_screen_find(s);
    if (s->hide_at && now >= s->hide_at) {
        s->flash[0] = 0;
        kit_screen_show(s, 0);
        return;
    }
    if (!s->up) return;
    if (s->flash[0]) {
        if (now < s->flash_until) { kit_screen_write(s, s->flash); return; }
        s->flash[0] = 0;
    }
    if (s->status[1][0] && s->alt_ms && (now / s->alt_ms) % 2)
        kit_screen_write(s, s->status[1]);
    else if (s->status[0][0])
        kit_screen_write(s, s->status[0]);
}

/* ---- lights ----------------------------------------------------------------------------------
 * The port's example sweep (MODE_SDK.md, "Lights") with its colour replaced. Which lamps that
 * light set covers is not decoded (on Godzilla it is the set the game's powerline-tower award
 * uses), so a colour stands for WHAT IS LIT: each mode says which colour means which shot. A
 * command is sent only when the colour changes. */
static KIT_UNUSED int kit_token_is(const char *t, unsigned len, const char *word)
{
    unsigned i;
    for (i = 0; i < len; i++)
        if (t[i] != word[i]) return 0;
    return word[len] == 0;
}

static KIT_UNUSED int kit_recolour(char *out, unsigned cap, const char *example, unsigned r, unsigned g, unsigned b)
{
    char val[3][8];
    unsigned n = 0, found = 0;
    const char *s = example, *replace = 0;
    if (!example || cap < 2) return 0;
    pm_snprintf(val[0], sizeof val[0], "%u", r);
    pm_snprintf(val[1], sizeof val[1], "%u", g);
    pm_snprintf(val[2], sizeof val[2], "%u", b);
    while (*s) {
        const char *t;
        unsigned len, i;
        if (*s == ' ' || *s == '\t') {
            if (n + 1 >= cap) return 0;
            out[n++] = *s++;
            continue;
        }
        for (t = s, len = 0; t[len] && t[len] != ' ' && t[len] != '\t'; len++) ;
        s = t + len;
        if (replace) {
            for (i = 0; replace[i]; i++) {
                if (n + 1 >= cap) return 0;
                out[n++] = replace[i];
            }
            replace = 0;
            continue;
        }
        if (kit_token_is(t, len, "--red")) { replace = val[0]; found |= 1u; }
        else if (kit_token_is(t, len, "--green")) { replace = val[1]; found |= 2u; }
        else if (kit_token_is(t, len, "--blue")) { replace = val[2]; found |= 4u; }
        for (i = 0; i < len; i++) {
            if (n + 1 >= cap) return 0;
            out[n++] = t[i];
        }
    }
    out[n] = 0;
    return found == 7u && !replace;
}

struct kit_lights { unsigned rgb; int on; };   /* rgb = r << 16 | g << 8 | b of the sweep running */

static KIT_UNUSED void kit_lights(struct kit_lights *l, unsigned r, unsigned g, unsigned b)
{
    char cmd[200];
    unsigned rgb = (r & 255u) << 16 | (g & 255u) << 8 | (b & 255u);
    if (l->on && l->rgb == rgb) return;
    if (!kit_recolour(cmd, sizeof cmd, pm_port_text("example_lights_on"), r, g, b)) return;
    l->on = 1;
    l->rgb = rgb;
    pm_lights(cmd);
}

static KIT_UNUSED void kit_lights_off(struct kit_lights *l)
{
    const char *off = pm_port_text("example_lights_off");
    if (!l->on) return;
    l->on = 0;
    if (off) pm_lights(off);
}

/* ---- the playfield's inserts (item 157; MODE_SDK.md "Lights: named inserts") -------------------
 * The sweep above colours a light set nobody decoded. The INSERTS say exactly what is lit: the
 * lamp in front of each shot, held in a colour and a pattern while the mode wants it, over the
 * game's own light shows, while every insert the mode does not hold keeps doing what the game
 * wants (its modes, battles, multiballs around ours).
 *
 * A mode describes, every tick, what it wants lit:
 *
 *     kit_lamps_begin(&lamps);
 *     kit_lamps_shot(&lamps, collect_mask, KIT_GREEN, PM_LAMP_BLINK, 400);   the inserts of a shot
 *     kit_lamps_name(&lamps, "MASER READY", KIT_WHITE, PM_LAMP_BLINK, 150);  or of a name (list)
 *     kit_lamps_commit(&lamps);
 *
 * and the kit sends the game only a CHANGE: a group the same as last time is left alone (a blink
 * keeps its phase), a changed group is held again, and an insert no group names any more is
 * handed back at once. No insert may be in two groups of one tick. kit_lamps_off() hands back
 * every insert the mode holds: at its end, a drain, a tilt. Every mode of the pack holds its
 * inserts in ONE layer at KIT_LAMP_PRIORITY: above every light show the game ran in the measured
 * runs (1 to 145), so a lit shot of ours is never hidden by a show of the game's, and below 255,
 * where a mode file's inserts sit by default.
 *
 * How the pack speaks with lights (so the five read as one game):
 *   solid      lit and worth shooting, no clock on it
 *   blink      lit with a clock: the faster, the less time is left (kit_hurry_ms)
 *   pulse      optional: adds time, or a head that is growing back
 *   dim solid  part of the sequence, not next yet (MASER BARRAGE) */
#define KIT_LAMP_PRIORITY 200
#define KIT_LAMP_GROUPS   8
#define KIT_GOLD          PM_RGB(255, 170, 0)
#define KIT_ORANGE        PM_RGB(255, 80, 0)
#define KIT_GREEN         PM_RGB(0, 255, 60)
#define KIT_YELLOW        PM_RGB(255, 200, 0)
#define KIT_RED           PM_RGB(255, 0, 0)
#define KIT_WHITE         PM_RGB(255, 255, 255)
#define KIT_CYAN          PM_RGB(0, 230, 255)
#define KIT_BLUE          PM_RGB(0, 90, 255)
#define KIT_BLUE_DIM      PM_RGB(0, 30, 90)
#define KIT_PURPLE        PM_RGB(170, 0, 255)

struct kit_lamp_group { const char *names; uint64_t shots; unsigned rgb, ms; int pattern; };
struct kit_lamps {
    struct kit_lamp_group now[KIT_LAMP_GROUPS], want[KIT_LAMP_GROUPS];
    unsigned n_now, n_want;
    int prio_set;                          /* pm_lamp_priority called for this mode */
    unsigned changes;                      /* how many commits changed something (tests, logs) */
};

static KIT_UNUSED void kit_lamps_begin(struct kit_lamps *l) { l->n_want = 0; }

static KIT_UNUSED void kit_lamps_add(struct kit_lamps *l, const char *names, uint64_t shots, unsigned rgb,
                                     int pattern, unsigned ms)
{
    struct kit_lamp_group *g;
    if ((!names || !names[0]) && !shots) return;
    if (l->n_want >= KIT_LAMP_GROUPS) return;
    g = &l->want[l->n_want++];
    g->names = names && names[0] ? names : 0;
    g->shots = g->names ? 0 : shots;
    g->rgb = rgb;
    g->pattern = pattern;
    g->ms = pattern == PM_LAMP_SOLID ? 0 : ms;
}

/* the inserts the port ties to these shot bits (the same shot names every port uses) */
static KIT_UNUSED void kit_lamps_shot(struct kit_lamps *l, uint64_t shots, unsigned rgb, int pattern, unsigned ms)
{
    kit_lamps_add(l, 0, shots, rgb, pattern, ms);
}

/* inserts by the game's own name, one or a comma-separated list (a port without the name skips it) */
static KIT_UNUSED void kit_lamps_name(struct kit_lamps *l, const char *names, unsigned rgb, int pattern, unsigned ms)
{
    kit_lamps_add(l, names, 0, rgb, pattern, ms);
}

static KIT_UNUSED int kit_group_same(const struct kit_lamp_group *a, const struct kit_lamp_group *b)
{
    if (a->shots != b->shots || a->rgb != b->rgb || a->pattern != b->pattern || a->ms != b->ms) return 0;
    if (!a->names || !b->names) return a->names == b->names;
    return kit_same(a->names, b->names);
}

/* 1 if the comma-separated list names `name` (the port's names, as pm_lamp_at gives them) */
static KIT_UNUSED int kit_names_have(const char *list, const char *name)
{
    const char *s = list;
    while (s && *s) {
        const char *e = s, *n = name;
        while (*e && *e != ',') e++;
        while (s < e && *s == ' ') s++;
        while (s < e && *n && (*s == *n || (*s >= 'a' && *s <= 'z' && *s - 32 == *n))) { s++; n++; }
        while (s < e && *s == ' ') s++;
        if (s == e && !*n) return 1;
        s = *e ? e + 1 : e;
    }
    return 0;
}

static KIT_UNUSED int kit_groups_have(const struct kit_lamp_group *g, unsigned n, const char *name, uint64_t shots)
{
    unsigned i;
    for (i = 0; i < n; i++)
        if ((g[i].names && kit_names_have(g[i].names, name)) || (g[i].shots && (g[i].shots & shots))) return 1;
    return 0;
}

/* "lights: shot 0x100000 ffaa00 solid; MASER READY ffffff blink 150" - one line a change, in the
 * mode's own log (the runtime's own lamp lines stop after 400 a boot) */
static KIT_UNUSED void kit_lamps_say(const struct kit_lamps *l)
{
    static const char *const pat[] = { "solid", "blink", "pulse", "chase" };
    char b[240];
    unsigned j, k = 0;
    for (j = 0; j < l->n_want && k + 48 < sizeof b; j++) {
        const struct kit_lamp_group *g = &l->want[j];
        int p = g->pattern >= 0 && g->pattern <= 3 ? g->pattern : 0;
        if (g->names) k += (unsigned)pm_snprintf(b + k, sizeof b - k, "%s%.40s", j ? "; " : "", g->names);
        else k += (unsigned)pm_snprintf(b + k, sizeof b - k, "%sshot 0x%llx", j ? "; " : "", (unsigned long long)g->shots);
        if (k + 24 < sizeof b)
            k += (unsigned)pm_snprintf(b + k, sizeof b - k, " %06x %s", g->rgb & 0xffffffu, pat[p]);
        if (g->ms && k + 8 < sizeof b)
            k += (unsigned)pm_snprintf(b + k, sizeof b - k, " %u", g->ms);
    }
    if (k >= sizeof b) k = sizeof b - 1;
    b[k] = 0;
    pm_log("lights: %s", l->n_want ? b : "none held");
}

static KIT_UNUSED void kit_lamps_commit(struct kit_lamps *l)
{
    unsigned j, changed = l->n_want != l->n_now;
    int i, n;
    for (j = 0; j < l->n_want && !changed; j++)
        if (!kit_group_same(&l->want[j], &l->now[j])) changed = 1;
    if (!changed) return;
    l->changes++;
    kit_lamps_say(l);
    if (pm_can(PM_CAN_LAMPS)) {
        /* hand back every insert the old groups held and the new ones do not name */
        n = pm_lamp_count();
        for (i = 0; i < n && l->n_now; i++) {
            uint64_t shots = 0;
            const char *name = pm_lamp_at(i, &shots);
            if (name && kit_groups_have(l->now, l->n_now, name, shots) && !kit_groups_have(l->want, l->n_want, name, shots))
                pm_lamp_release(name);
        }
        if (l->n_want && !l->prio_set) {
            pm_lamp_priority(KIT_LAMP_PRIORITY);
            l->prio_set = 1;
        }
        for (j = 0; j < l->n_want; j++) {
            const struct kit_lamp_group *g = &l->want[j];
            if (j < l->n_now && kit_group_same(g, &l->now[j])) continue;
            if (g->names) pm_lamp_set(g->names, g->rgb, g->pattern, g->ms);
            else pm_lamp_shot(g->shots, g->rgb, g->pattern, g->ms);
        }
    }
    for (j = 0; j < l->n_want; j++) l->now[j] = l->want[j];
    l->n_now = l->n_want;
}

/* every insert the mode holds, back to the game at once */
static KIT_UNUSED void kit_lamps_off(struct kit_lamps *l)
{
    l->n_want = 0;
    if (!l->n_now) return;
    if (pm_can(PM_CAN_LAMPS)) pm_lamp_release_all();
    l->changes++;
    l->n_now = 0;
    pm_log("lights: all handed back to the game");
}

/* A blink's period for a clock: slow with most of the time left, faster as it runs down, a flicker
 * in the last three seconds. Four steps only, so the inserts change a handful of times a mode. */
static KIT_UNUSED unsigned kit_hurry_ms(unsigned long left_ms, unsigned long total_ms)
{
    if (left_ms * 3 > total_ms * 2) return 700;
    if (left_ms * 3 > total_ms) return 400;
    if (left_ms > 3000) return 200;
    return 100;
}

/* ---- the tilt (item 157) -------------------------------------------------------------------------
 * The game's own tilt event (the third pendulum hit; MODE_SDK.md "Events"). The tilted ball's
 * ball_end comes only at its drain, seconds later, and a tilted game's lights go dark: a mode ends
 * on the tilt itself, so none of its inserts stays lit over a tilted playfield. */
static KIT_UNUSED int kit_is_tilt(unsigned id)
{
    static int tilt = -2;
    if (tilt == -2) tilt = pm_event("tilt");
    return tilt >= 0 && (int)id == tilt;
}

/* ---- a countdown with the game's own voice -------------------------------------------------- */
struct kit_timer { unsigned ticks, shown; int voice; };

static KIT_UNUSED void kit_timer_set(struct kit_timer *t, unsigned seconds, int voice)
{
    t->ticks = seconds * KIT_TICKS;
    t->shown = seconds;
    t->voice = voice;
}

static KIT_UNUSED void kit_timer_add(struct kit_timer *t, unsigned seconds)
{
    t->ticks += seconds * KIT_TICKS;
}

static KIT_UNUSED unsigned kit_timer_seconds(const struct kit_timer *t)
{
    return (t->ticks + KIT_TICKS - 1) / KIT_TICKS;
}

/* one tick; 1 = it just ran out. With `voice`, the game says "ten seconds" and counts 5..1. */
static KIT_UNUSED int kit_timer_tick(struct kit_timer *t)
{
    unsigned s;
    if (!t->ticks) return 0;
    t->ticks--;
    s = kit_timer_seconds(t);
    if (s != t->shown) {
        t->shown = s;
        if (t->voice && s == 10) pm_callout(pm_callout_id("ten_seconds"));
        if (t->voice && s >= 1 && s <= 5) pm_callout_nth(pm_callout_id("countdown"), s - 1);
    }
    return t->ticks == 0;
}

/* ---- a new game ------------------------------------------------------------------------------
 * mode_file.c's witness (MODE_SDK.md, "What marks a new game"): player 1's score falling to 0,
 * or pm_in_game() rising while it is 0; recognised once, then not again until player 1 scores
 * or pm_in_game() falls. Returns 1 on the tick a new game is seen. */
struct kit_game { int seen, was_in, was_zero, armed; };

static KIT_UNUSED int kit_new_game(struct kit_game *g)
{
    int in = pm_in_game(), zero = pm_score(1) == 0, fresh = 0;
    if (!g->seen) {
        g->seen = g->armed = 1;
        g->was_in = in;
        g->was_zero = zero;
        return 0;
    }
    if (!zero || (g->was_in && !in)) g->armed = 1;
    if (zero && g->armed && (!g->was_zero || (in && !g->was_in))) {
        g->armed = 0;
        fresh = 1;
    }
    g->was_in = in;
    g->was_zero = zero;
    return fresh;
}

/* ---- the pack ledger ---------------------------------------------------------------------------
 * What each pack mode did this game, per player: FINAL WARS lights from it. A WEAK definition in
 * every file that includes this header: the linker keeps ONE, so all the modes built into one
 * mode.so share it, and a mode built alone still links. FINAL WARS clears it at every new game. */
#define KIT_LEDGER_MODES 3
#define KIT_GHIDORAH     0
#define KIT_OXYGEN       1
#define KIT_MASER        2
struct kit_ledger_t {
    unsigned char played[5][KIT_LEDGER_MODES];   /* [player 1-4][mode]: started this game */
    unsigned char won[5][KIT_LEDGER_MODES];      /* ... and won (its success path) */
};
__attribute__((weak, visibility("hidden"))) struct kit_ledger_t kit_ledger;

static KIT_UNUSED void kit_ledger_note(unsigned which, unsigned player, int won)
{
    if (which >= KIT_LEDGER_MODES || player < 1 || player > 4) return;
    kit_ledger.played[player][which] = 1;
    if (won) kit_ledger.won[player][which] = 1;
}

/* ---- one of OUR modes at a time ----------------------------------------------------------------
 * pm_begin()/pm_end() keep our modes to one at a time; kit_running also tells the others WHICH
 * pack mode holds it, so a mode never flashes its qualification screen over another's (the
 * screens share one place). Weak and shared, like the ledger. */
__attribute__((weak, visibility("hidden"))) const char *kit_running;
/* A pack mode that asked to start while another of ours ran (item 157): a mode that is only
 * showing its total (ANGUIRUS after the game's battle) gives way at once when it sees this. */
__attribute__((weak, visibility("hidden"))) const char *kit_asked;

static KIT_UNUSED int kit_begin(const char *name)
{
    if (!pm_begin()) {
        kit_asked = name;
        return 0;
    }
    kit_running = name;
    kit_asked = 0;
    return 1;
}

/* The mode's display priority (item 157; MODE_SDK.md "Display priority"): taken right after
 * kit_begin, before the screen and the clip, so the game's displays that do not beat it wait while
 * the mode runs. 180 is a mode's value: BATTLE IS LIT waits and plays at the end, and the game's
 * full-screen shot awards (LOOPS, POWERLINE ATTACK) are not shown while it runs (a waiting one
 * froze the game's drawing: the runtime drops them, item 157); its jackpots, battle and multiball
 * starts, the battle select screen and the tilt warning still come through, and the screen is in
 * view again when they end. */
#define KIT_DISPLAY_MODE    180
#define KIT_DISPLAY_WIZARD  190     /* also jackpots wait; multiball and battle start screens are not shown */

static KIT_UNUSED int kit_display(unsigned priority)
{
    int held = pm_display_priority(priority);
    if (priority)
        pm_log("display priority %u %s", priority, held ? "held: the game's displays that do not beat it wait"
                                                           : "NOT held (this port has no display arbitration)");
    return held;
}

static KIT_UNUSED void kit_end(void)
{
    pm_display_priority(0);                /* given up before pm_end (MODE_SDK.md) */
    pm_end();
    kit_running = 0;
}

/* ---- the stacking question -------------------------------------------------------------------
 * 1 = one of the game's own modes of `kinds` is active (the mode should wait); the port cannot
 * tell (-1) counts as none, once logged. */
static KIT_UNUSED int kit_stock_busy(unsigned kinds, const char *who, const char **what)
{
    static int said;
    int k = pm_stock_mode_running(kinds);
    if (k < 0) {
        if (!said) pm_log("%s: this port cannot tell when the game's own modes run - it does not wait for them", who);
        said = 1;
        return 0;
    }
    if (what) *what = k ? pm_stock_mode_what((unsigned)k) : "";
    return k > 0;
}

#endif
