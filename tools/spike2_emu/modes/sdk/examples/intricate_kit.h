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

/* a value that fits a HUD counter's 200 px in the big font (hud-layers): 950,000 / 4.25M / 42.5M / 425M */
static KIT_UNUSED const char *kit_short(char *buf, unsigned cap, uint64_t v)
{
    if (v < 1000000u) return kit_num(buf, cap, v);
    if (v < 10000000u) pm_snprintf(buf, cap, "%u.%02uM", (unsigned)(v / 1000000u), (unsigned)(v % 1000000u / 10000u));
    else if (v < 100000000u) pm_snprintf(buf, cap, "%u.%uM", (unsigned)(v / 1000000u), (unsigned)(v % 1000000u / 100000u));
    else pm_snprintf(buf, cap, "%uM", (unsigned)(v / 1000000u));
    return buf;
}

/* ---- the debounce ------------------------------------------------------------------------
 * One slot per shot bit that has been seen: its last time. A shot bit seen again inside
 * KIT_DEBOUNCE_MS is not fresh. Measured motive (David, the film pack): one target hit
 * twelve times in a second paid 150,000,000 from a 30 s mode. */
#define KIT_DB_SLOTS 24
struct kit_db { uint64_t bit[KIT_DB_SLOTS]; unsigned long at[KIT_DB_SLOTS]; unsigned next; };

static KIT_UNUSED void kit_hit(uint64_t shot);    /* the lights section, below */

/* 1 if this shot (one bit, or a mask treated as one shot) counts now; it is then remembered. A hit that counts
 * while this mode runs also answers at once (kit_hit, PAD-415): every scoring shot of the pack passes here. */
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
            if (pm_running()) kit_hit(bit);
            return 1;
        }
    i = db->next++ % KIT_DB_SLOTS;
    db->bit[i] = bit;
    db->at[i] = now;
    if (pm_running()) kit_hit(bit);
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
 * How the pack speaks with lights - the game's own language, so a lit shot never looks broken (PAD-415, David after
 * a machine test: "the inserts that are lit for shots should pretty much always be flashing - when they're solid,
 * they look broken"):
 *   blink KIT_LIT_MS  lit and worth shooting, no clock on it (slower for one far off, faster as it gets close)
 *   blink faster      lit with a clock: the faster, the less time is left (kit_hurry_ms)
 *   pulse             optional: adds time, a head growing back; dim, a step of a sequence not next yet
 *   solid             done (a spike charged): never a shot still to make
 * And a hit answers: the hit shot's inserts strobe white for a moment over all of this (kit_hit). */
#define KIT_LAMP_PRIORITY 200
#define KIT_LAMP_GROUPS   8
#define KIT_LIT_MS        500      /* a lit shot's blink with no clock on it */
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

/* ---- a hit answers (PAD-415) ----------------------------------------------------------------------
 * While one of ours runs the game's rules see no shots, so the game plays none of its own sounds or insert flashes
 * for them: a hit has to answer from here. Every hit that counts (kit_fresh) strobes the shot's inserts white for
 * KIT_HIT_FLASH_MS over whatever the mode lights them in (pm_lamp_flash), and plays one of the game's own hit
 * sounds, a step higher each hit (pm_hit_sound: on Godzilla its eight pitched orchestra hits, so a run of hits
 * climbs, and starts low again after the eighth). kit_hit_reset() starts the climb again (kit_begin does).
 * Nothing plays on a port without them. */
#define KIT_HIT_FLASH_MS 480
static unsigned kit_hits;
static KIT_UNUSED void kit_hit_reset(void) { kit_hits = 0; }
static KIT_UNUSED void kit_hit(uint64_t shot)
{
    int n = pm_hit_sounds();
    if (pm_can(PM_CAN_LAMPS)) pm_lamp_flash(shot, KIT_WHITE, KIT_HIT_FLASH_MS);
    if (n) pm_hit_sound((int)(kit_hits % (unsigned)n) + 1);
    kit_hits++;
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

/* PAD-371: at least this many seconds left - a clock under it goes back up to it (the "ten seconds" call is not
 * said again; the 5..1 count is, when it gets there). 1 = it was put back up. */
static KIT_UNUSED int kit_timer_at_least(struct kit_timer *t, unsigned seconds)
{
    if (!t->ticks || t->ticks >= seconds * KIT_TICKS) return 0;
    t->ticks = seconds * KIT_TICKS;
    t->shown = seconds;
    return 1;
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
/* PAD-379: pm_ms() when one of ours last ended (0 = never). A shot that ends a mode (BIOLLANTE's final blow at the
 * Building) must not also START another one lit on the same shot (GODZILLA ANGRY's Building, emulator run fullA):
 * a mode started by a shot asks kit_just_ended() first. Weak and shared, like the ledger. */
__attribute__((weak, visibility("hidden"))) unsigned long kit_ended_ms;

static KIT_UNUSED int kit_begin(const char *name)
{
    if (!pm_begin()) {
        kit_asked = name;
        return 0;
    }
    kit_running = name;
    kit_asked = 0;
    kit_hit_reset();                       /* PAD-415: its hits climb from the bottom */
    return 1;
}

/* The mode's display priority (item 157; MODE_SDK.md "Display priority"), asked for right after
 * kit_begin. PAD-353: it no longer makes any display of the game's wait. On a Godzilla Premium the
 * Magna-Grab's screen waited for KING GHIDORAH's 180 and the game kept its magnet ON the whole time (it
 * holds the ball until that screen has played). Now the runtime only WATCHES: pm_display_covered() says
 * when a display of the game's has the screen, and the HUD keeps its middle words off it until it is gone. */
#define KIT_DISPLAY_MODE    180
#define KIT_DISPLAY_WIZARD  190     /* also jackpots wait; multiball and battle start screens are not shown */

static KIT_UNUSED int kit_display(unsigned priority)
{
    int held = pm_display_priority(priority);
    if (priority)
        pm_log("display priority %u %s", priority, held ? "noted: the game's displays still play as they come"
                                                           : "not watched (this port has no display lines)");
    return held;
}

static KIT_UNUSED void kit_end(void)
{
    pm_block_game_modes(0);                /* PAD-347: the game's modes may start again */
    pm_display_priority(0);                /* given up before pm_end (MODE_SDK.md) */
    pm_end();
    kit_running = 0;
    kit_ended_ms = pm_ms() ? pm_ms() : 1;
}

/* PAD-379: 1 = one of ours ended less than `ms` ago (the shot that ended it is not a start for the next) */
static KIT_UNUSED int kit_just_ended(unsigned long ms)
{
    return kit_ended_ms && pm_ms() - kit_ended_ms < ms;
}

/* The mode is over but its ENDING is still to play: the full-screen clip, then the total (hud-layers,
 * run t7). Giving the display priority up at the end let the game's award that waited through the mode
 * (FINAL WARS: POWERLINE ATTACK) take the one video surface 22 ms later, stopping the ending clip and
 * covering the total. pm_end_holding ends the mode (another of ours may start at once, and the hold
 * goes to it) and keeps the hold for `ms`. A drain or a tilt calls kit_end_now() after its end(), so
 * those hand the display back at the same tick. */
static KIT_UNUSED void kit_end_after(unsigned long ms)
{
    pm_block_game_modes(0);                /* PAD-347: its ending blocks nothing */
    if (!ms || !pm_end_holding((unsigned)ms)) {
        kit_end();
        return;
    }
    kit_running = 0;
    kit_ended_ms = pm_ms() ? pm_ms() : 1;
    pm_log("the ending keeps the screen for %lu s", ms / 1000);
}

static KIT_UNUSED void kit_hud_drop_now(void);    /* the HUD section, below */

/* PAD-411: one of the GAME's own light shows, by the port's name for it ("Strobe burst"), in the place of a kit
 * show: its start's and its end's (David, 2026-10-06: "mode start should be flashy and mode end should be more
 * subdued"). 1 = the game's plays; 0 = not on this game (a Pro, another title): the caller plays its own. */
static KIT_UNUSED int kit_game_show(const char *name, const char *why)
{
    if (!name || !pm_game_show_named(name)) return 0;
    pm_log("light show: the game's %s (%s)", name, why);
    return 1;
}

static KIT_UNUSED void kit_end_now(void)
{
    pm_display_priority(0);                /* an ending's hold, given up at once */
    /* PAD-301: and the mode's HUD with it. A drain or a tilt hands the screen to the game's own end-of-ball
     * bonus (or the tilt) at once; a total left up for TOTAL_SHOWN_MS sat on the bonus screen's words
     * (David's Premium, 2026-10-01: MASER BARRAGE ended by a drain, "text sitting over the top of other
     * text"). */
    kit_hud_drop_now();
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

/* PAD-347: ISOLATED. After a machine run with the modes stacked on the game's own (their words aside), David
 * (2026-10-04): "there is still a bit too much overlap with other modes. i'd prefer to try them isolated from
 * other ones." So the pack's modes (ANGUIRUS apart: it exists to join the game's battles) keep to themselves:
 * - one starts only while none of the game's own modes runs (a battle, a multiball, a timed mode such as JET
 *   FIGHTER ATTACK) and fewer than two balls are in play; a refused start stays ready, so its qualifying shot
 *   after the game's mode starts it (kit_wait_game);
 * - one of the game's modes beginning while ours runs ends ours at once, its words, lights and display given
 *   back in the same tick, as a tilt does (kit_game_began). */
static KIT_UNUSED int kit_game_busy(const char *who, const char **what)
{
    int n = pm_can(PM_CAN_MULTIBALL) ? pm_balls_in_play() : -1;
    if (kit_stock_busy(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL | PM_STOCK_ANY, who, what)) return 1;
    if (n < 2) return 0;
    if (what) *what = "a multiball";                         /* two balls in play, none of the game's */
    return 1;
}

/* PAD-399: 1 = `key` differs from what `last` (cap bytes) held, now remembered: say it. A line a shot can repeat
 * (a spinner asks on every spin) is said once until its reason changes; "" in `last` forgets. */
static KIT_UNUSED int kit_once(char *last, unsigned long cap, const char *key)
{
    if (kit_same(last, key)) return 0;
    pm_snprintf(last, cap, "%s", key);
    return 1;
}

/* 1 = wait: said once until the reason changes (PAD-399: a machine run's mode.log carried 107 of these, a
 * spinner asking on every spin); `then` says what starts it after. The game's mode ending forgets it. */
static KIT_UNUSED int kit_wait_game(const char *who, const char *why, const char *then)
{
    static char said[64];                                     /* the reason said: what is running */
    const char *what = 0;
    if (!kit_game_busy(who, &what)) {
        said[0] = 0;
        return 0;
    }
    if (!what || !what[0]) what = "one of the game's modes";
    if (kit_once(said, sizeof said, what)) pm_log("not started (%s): %s is running - still ready, %s", why, what, then);
    return 1;
}

/* PAD-379: 1 = the mode ended by itself (won, lost on its clock, its multiball over, a stop) - its ending call
 * plays; 0 = a drain, a tilt, the game moving on or one of the game's own modes beginning took it away, when the
 * game's own sounds (the bonus, the tilt, that mode's start) have the speakers. */
static KIT_UNUSED int kit_natural_end(const char *why)
{
    return !(kit_same(why, "ball ended") || kit_same(why, "tilted") || kit_same(why, "the game moved on") ||
             kit_same(why, "the game's own mode began"));
}

/* ---- PAD-379: the shield platform ------------------------------------------------------------------------------
 * Godzilla Premium/LE carries its shield targets on a platform a motor turns (pm_shield): AWAY, the game's home,
 * where the spinner side faces the player and the shields cannot be hit; or TOWARD the flippers. A mode that plays
 * the shield targets turns them in KIT_SHIELD_DELAY_MS after it starts (the ball that started it is clear of the
 * platform first) and back AWAY when it ends - unless the game's own mode began, which has the platform now. A
 * Pro's shield targets are fixed and face the player: nothing turns. kit_shields_reachable() says whether a shield
 * can be hit now: a mode puts nothing it NEEDS on the shields while it says 0 (still turning, or an operator
 * switched the motor off).
 * The GAME turns the platform away by itself when a shield target is hit while it faces the player (its own
 * Mechagodzilla shield reaction: emulator run shield2, 30 ms after each hit), and its ball search pulses it: the kit
 * turns it back KIT_SHIELD_BACK_MS after it was left facing away, for as long as the mode runs. */
#define KIT_SHIELD_DELAY_MS 1500
#define KIT_SHIELD_BACK_MS  1500           /* knocked away under the mode: toward the player again after this */
struct kit_shields { int asked; unsigned again; unsigned long due, away_since; };

static KIT_UNUSED void kit_shields_in(struct kit_shields *s)
{
    s->asked = 0;
    s->due = 0;
    if (pm_shield_position() < 0) return;                  /* fixed shields (a Pro) */
    s->due = pm_ms() + KIT_SHIELD_DELAY_MS;
}

static KIT_UNUSED void kit_shields_tick(struct kit_shields *s)
{
    if (s->asked) {
        if (pm_shield_position() != PM_SHIELD_AWAY) s->away_since = 0;
        else if (!s->away_since) s->away_since = pm_ms() ? pm_ms() : 1;
        else if (pm_ms() - s->away_since >= KIT_SHIELD_BACK_MS) {
            s->away_since = 0;
            s->again++;
            if (s->again <= 3 || s->again % 10 == 0)
                pm_log("the shields were turned away under the mode (a shield hit, the ball search): toward the "
                       "player again (%u)", s->again);
            pm_shield(PM_SHIELD_TOWARD);
        }
    }
    if (!s->due || pm_ms() < s->due) return;
    s->due = 0;
    if (pm_shield_position() == PM_SHIELD_TOWARD) {
        pm_log("the shields already face the player");
        return;
    }
    s->asked = pm_shield(PM_SHIELD_TOWARD);
    s->again = 0;
    s->away_since = 0;
    pm_log(s->asked ? "the shields turn toward the player" : "the shields stay away: the motor refused (switched off?)");
}

static KIT_UNUSED void kit_shields_out(struct kit_shields *s, const char *why)
{
    int asked = s->asked;
    s->asked = 0;
    s->due = 0;
    if (!asked) return;
    if (kit_same(why, "the game's own mode began")) {
        pm_log("the shields stay where they are: the game's own mode has the platform now");
        return;
    }
    if (pm_shield(PM_SHIELD_AWAY)) pm_log("the shields turn away again (%s)", why);
}

/* 1 = a shield target can be hit now: fixed shields, or the platform stopped facing the player */
static KIT_UNUSED int kit_shields_reachable(void)
{
    int at = pm_shield_position();
    return at < 0 || at == PM_SHIELD_TOWARD;
}

/* 1 = one of the game's own modes is running now (asked by a mode of ours that is running) */
static KIT_UNUSED int kit_game_began(void)
{
    return pm_aside() != 0;
}

/* PAD-347 (David, 2026-10-04: "isolated modes like our own custom ones that prevent the stock modes from
 * starting"): right after kit_begin, a mode BLOCKS the game's modes the port lets it refuse (on Godzilla Jet
 * Fighter Attack and Tesla Strike, which shots start) for as long as it runs, unless its assets file says `game_modes
 * give_way`. A multiball or a battle of the game's is never refused: kit_game_began still ends ours for those.
 * 1 = blocking. Given back in kit_end / kit_end_after / kit_end_now (and by the runtime when the mode ends). */
static KIT_UNUSED int kit_isolate_list(int give_way, const unsigned char *ids, int n);
static KIT_UNUSED int kit_isolate(int give_way)
{
    return kit_isolate_list(give_way, 0, 0);
}

/* PAD-363: with the mode's own list of the game's modes to hold off (its assets file's `block_modes`; none = the
 * port's checked defaults) */
static KIT_UNUSED int kit_isolate_list(int give_way, const unsigned char *ids, int n)
{
    if (!give_way) pm_block_list(ids, n);
    if (give_way) {
        pm_log("isolated: gives way - one of the game's modes starting ends it");
        return 0;
    }
    if (pm_block_game_modes(1)) {
        pm_log("isolated: blocks the game's modes the port lets it refuse while it runs (any other mode of the "
               "game's starting still ends it)");
        return 1;
    }
    pm_log("isolated: this port cannot block the game's modes - it gives way to them");
    return 0;
}

/* ---- the mode's HUD at the glass's EDGES (hud-layers) ----------------------------------------------
 * The card build puts ONE Sprite group per mode in the HUD scene (pinball_decryptor/plugins/stern/
 * mode_hud.py), laid out as the game's own battles are: the title and an instruction line above the
 * score panel, three counters across the top, a big award line, a timer badge on the left edge (the
 * stock BATTLE badge with the mode's label and icon, one slot above it) and a gauge of pips on the right
 * edge. The names are the build's (PadMode_<folder>_Hud_...). Texts are written only when they change
 * (every pm_set_text leaks a small string inside the game) and HIDDEN by writing a space - only a
 * Sprite may be shown or hidden (a Text's visibility slot is another virtual), so every piece that comes
 * and goes (the badge, the gauge, each pip's lit and dark picture) is its own Sprite group. A mode that
 * finds no HUD (another title, an older card) runs the same with nothing on the glass. */
#define KIT_HUD_PIPS   40             /* a bar gauge's slices (PAD-416); a pip gauge has up to 12 */
#define KIT_HUD_WORDS  48

struct kit_hud {
    const char *slug;                      /* the mode's folder */
    void *group, *timer, *timer2, *gauge, *pip_on[KIT_HUD_PIPS], *pip_off[KIT_HUD_PIPS];
    void *t_title, *t_line, *t_award, *t_awardsub, *t_timer, *t_timer2, *t_glabel, *t_c[3][3];
    unsigned tries;
    int found, up, timer_up, timer2_up, gauge_up, n_pips, pip_lit[KIT_HUD_PIPS];
    int aside;                             /* PAD-347: the kind of the game's mode it stepped aside for, 0 = none */
    char w_title[KIT_HUD_WORDS], w_line[KIT_HUD_WORDS], w_award[KIT_HUD_WORDS], w_awardsub[KIT_HUD_WORDS];
    char w_timer[8], w_timer2[8], w_glabel[24], w_c[3][3][24];
    /* what is wanted (written to the glass when found and up) */
    char want_title[KIT_HUD_WORDS], want_line[KIT_HUD_WORDS], want_award[KIT_HUD_WORDS], want_awardsub[KIT_HUD_WORDS];
    char want_c[3][3][24], want_glabel[24];
    int want_timer, want_gauge;            /* -1 = hidden */
    int pips;                              /* pips in use: 0 = all the build made (kit_hud_pips) */
    unsigned long award_until, hide_at;
    int noting;                            /* up only for a qualification note */
    int metering;                          /* PAD-379: up only for a meter (kit_hud_meter) */
    int off;                               /* PAD-353: its words wait for a display of the game's */
    unsigned long checked_at;              /* PAD-390: the last look at the scene's HUD group */
};

/* The pack's HUD that is up now: a HUD coming up takes the place of the one showing (a mode's TOTAL
 * from a moment ago). Weak and shared, like the ledger. */
__attribute__((weak, visibility("hidden"))) struct kit_hud *kit_hud_up;

static KIT_UNUSED void kit_hud_text(void *node, char *written, unsigned cap, const char *want)
{
    const char *w = want && want[0] ? want : " ";
    if (!node || kit_same(written, w)) return;
    kit_copy(written, cap, w);
    pm_set_text(node, written);
}

static KIT_UNUSED void *kit_hud_find1(const struct kit_hud *h, const char *fmt, int text, int k)
{
    char path[160];
    int n = pm_snprintf(path, sizeof path, "PadMode_%s_Hud", h->slug);
    if (fmt) n += pm_snprintf(path + n, sizeof path - (unsigned)n, fmt, h->slug, k, k);
    (void)n;
    return text ? pm_text("hud", path) : pm_node("hud", path);
}

/* Twice a second until found: the HUD scene can load after init. Found while the mode is not using
 * it, the whole group is hidden at once (a built HUD is visible until a mode hides it). */
static KIT_UNUSED void kit_hud_find(struct kit_hud *h)
{
    static const char *const cl[3] = { "Label", "Value", "Sub" };
    int k, j;
    char f[96];
    if (h->found || !h->slug || !pm_can(PM_CAN_SCREENS) || (h->tries++ % KIT_POLL) != 0) return;
    h->group = kit_hud_find1(h, 0, 0, 0);
    if (!h->group) return;
    h->found = 1;
    h->checked_at = pm_ms();
    h->t_title = kit_hud_find1(h, ".PadMode_%s_Hud_Title", 1, 0);
    h->t_line = kit_hud_find1(h, ".PadMode_%s_Hud_Line", 1, 0);
    h->t_award = kit_hud_find1(h, ".PadMode_%s_Hud_Award", 1, 0);
    h->t_awardsub = kit_hud_find1(h, ".PadMode_%s_Hud_AwardSub", 1, 0);
    h->timer = kit_hud_find1(h, ".PadMode_%s_Hud_Timer", 0, 0);
    if (h->timer) {
        char p[96];
        pm_snprintf(p, sizeof p, ".PadMode_%s_Hud_Timer.PadMode_%s_Hud_Timer_Num", h->slug, h->slug);
        h->t_timer = kit_hud_find1(h, p, 1, 0);
    }
    h->timer2 = kit_hud_find1(h, ".PadMode_%s_Hud_Timer2", 0, 0);      /* PAD-347: a card built before has none */
    if (h->timer2) {
        char p[96];
        pm_snprintf(p, sizeof p, ".PadMode_%s_Hud_Timer2.PadMode_%s_Hud_Timer2_Num", h->slug, h->slug);
        h->t_timer2 = kit_hud_find1(h, p, 1, 0);
    }
    for (k = 0; k < 3; k++)
        for (j = 0; j < 3; j++) {
            pm_snprintf(f, sizeof f, ".PadMode_%%s_Hud_C%%d_%s", cl[j]);
            h->t_c[k][j] = kit_hud_find1(h, f, 1, k + 1);
        }
    h->gauge = kit_hud_find1(h, ".PadMode_%s_Hud_Gauge", 0, 0);
    if (h->gauge) {
        char p[128];
        pm_snprintf(p, sizeof p, ".PadMode_%s_Hud_Gauge.PadMode_%s_Hud_Gauge_Label", h->slug, h->slug);
        h->t_glabel = kit_hud_find1(h, p, 1, 0);
        for (k = 0; k < KIT_HUD_PIPS; k++) {
            pm_snprintf(p, sizeof p, ".PadMode_%s_Hud_Gauge.PadMode_%s_Hud_G%d_On", h->slug, h->slug, k + 1);
            h->pip_on[k] = kit_hud_find1(h, p, 0, 0);
            pm_snprintf(p, sizeof p, ".PadMode_%s_Hud_Gauge.PadMode_%s_Hud_G%d_Off", h->slug, h->slug, k + 1);
            h->pip_off[k] = kit_hud_find1(h, p, 0, 0);
            if (!h->pip_on[k] || !h->pip_off[k]) break;
            h->pip_lit[k] = -1;
        }
        h->n_pips = k;
    }
    h->w_title[0] = h->w_line[0] = h->w_award[0] = h->w_awardsub[0] = h->w_timer[0] = h->w_timer2[0] = h->w_glabel[0] = 0;
    for (k = 0; k < 3; k++) for (j = 0; j < 3; j++) h->w_c[k][j][0] = 0;
    h->timer_up = h->timer2_up = h->gauge_up = -1;
    pm_show(h->group, h->up);
    pm_log("hud %s found: title %s, line %s, award %s, timer %s%s, counters %s, gauge %s (%d pips) - %s",
           h->slug, h->t_title ? "yes" : "NO", h->t_line ? "yes" : "NO", h->t_award ? "yes" : "NO",
           h->timer ? (h->t_timer ? "yes" : "no number") : "none", h->timer2 ? " (and its second slot)" : "",
           h->t_c[0][1] ? "yes" : "none", h->gauge ? "yes" : "none", h->n_pips,
           h->up ? "shown, the mode is using it" : "hidden until the mode uses it");
}

static KIT_UNUSED void kit_hud_show(struct kit_hud *h, int on)
{
    if (on && kit_hud_up && kit_hud_up != h) {
        struct kit_hud *o = kit_hud_up;
        o->up = 0;
        o->hide_at = 0;
        o->noting = 0;
        o->metering = 0;
        if (o->group) pm_show(o->group, 0);
    }
    if (on) kit_hud_up = h;
    else if (kit_hud_up == h) kit_hud_up = 0;
    h->up = on;
    h->hide_at = 0;
    if (!on) {
        h->want_award[0] = h->want_awardsub[0] = 0;
        h->award_until = 0;
        h->noting = 0;
        h->metering = 0;
        h->aside = 0;                      /* PAD-347: said again the next time it is up beside a game mode */
    }
    if (h->group) pm_show(h->group, on);
}

/* whichever mode's HUD is up, down now (kit_end_now: a drain or a tilt) */
static KIT_UNUSED void kit_hud_drop_now(void)
{
    if (kit_hud_up) kit_hud_show(kit_hud_up, 0);
}

/* hide the HUD `ms` from now (0 = now): a mode's TOTAL stays up that long after its end */
static KIT_UNUSED void kit_hud_hide_in(struct kit_hud *h, unsigned ms)
{
    if (!ms) { kit_hud_show(h, 0); return; }
    h->hide_at = pm_ms() + ms;
}

/* the battle's own two lines: the mode's title (orange) and what to shoot (white) */
static KIT_UNUSED void kit_hud_title(struct kit_hud *h, const char *title, const char *line)
{
    if (title) kit_copy(h->want_title, sizeof h->want_title, title);
    if (line) kit_copy(h->want_line, sizeof h->want_line, line);
}

/* counter k (0-2, left to right): a label, a big value, a sub-label; all three 0/"" hides it */
static KIT_UNUSED void kit_hud_counter(struct kit_hud *h, int k, const char *label, const char *value, const char *sub)
{
    if (k < 0 || k > 2) return;
    kit_copy(h->want_c[k][0], sizeof h->want_c[k][0], label ? label : "");
    kit_copy(h->want_c[k][1], sizeof h->want_c[k][1], value ? value : "");
    kit_copy(h->want_c[k][2], sizeof h->want_c[k][2], sub ? sub : "");
}

/* the timer badge's seconds; -1 hides the badge */
static KIT_UNUSED void kit_hud_timer(struct kit_hud *h, int seconds) { h->want_timer = seconds; }

/* How many of the build's pips the gauge uses (a port with fewer of the shots than the card was built
 * for: ANGUIRUS's spikes on Godzilla Pro, two shield targets where Premium has three). The rest are hidden
 * rather than left dark, so a full charge reads full. 0 = all of them. Kept across the mode's starts. */
static KIT_UNUSED void kit_hud_pips(struct kit_hud *h, int n)
{
    h->pips = n;
}

/* the gauge: `level` pips of the build's count lit (-1 hides it), and its label */
static KIT_UNUSED void kit_hud_gauge(struct kit_hud *h, int level, const char *label)
{
    h->want_gauge = level;
    if (label) kit_copy(h->want_glabel, sizeof h->want_glabel, label);
}

/* a big line and a smaller one under it, for `ms` (a jackpot, a head severed) */
static KIT_UNUSED void kit_hud_award(struct kit_hud *h, unsigned ms, const char *big, const char *sub)
{
    kit_copy(h->want_award, sizeof h->want_award, big ? big : "");
    kit_copy(h->want_awardsub, sizeof h->want_awardsub, sub ? sub : "");
    h->award_until = pm_ms() + ms;
}

/* A QUALIFICATION note on a HUD the mode is not using ("POWERLINES 2 OF 3"): the award line alone for
 * `ms`, then hidden. Polite: while another of the pack's HUDs is up (a mode running, or the total of
 * one that just ended) nothing is shown - a METER of another mode (kit_hud_meter) gives way to it. On a HUD
 * showing its own meter the note goes in the award line and the meter stays. 1 = shown. */
static KIT_UNUSED int kit_hud_note(struct kit_hud *h, unsigned ms, const char *big, const char *sub)
{
    int k;
    if (kit_hud_up && kit_hud_up != h && !kit_hud_up->metering) return 0;
    /* PAD-390 (David's Premium, 2026-10-05: MELTDOWN IS READY during the game's multiball, a SPACEGODZILLA lock
     * while one of the game's modes ran): a note's line IS the award line, in the middle, so it has no place to
     * step aside to - while the game's mode or multiball has the middle it is not shown (a meter's gauge at the
     * edge stays; a note already up waits in kit_hud_tick) */
    if (pm_aside() && !h->metering) return 0;
    if (h->up && !h->noting) return 0;
    h->want_title[0] = h->want_line[0] = 0;
    for (k = 0; k < 3; k++) kit_hud_counter(h, k, 0, 0, 0);
    h->want_timer = -1;
    if (!h->metering) h->want_gauge = -1;
    kit_hud_award(h, ms, big, sub);
    if (!h->up) kit_hud_show(h, 1);
    h->noting = 1;
    h->hide_at = h->metering ? 0 : pm_ms() + ms;
    return 1;
}

/* PAD-379: a METER on a HUD the mode is not using - qualification progress that STAYS on the glass (David: "a
 * switch hit counter on the UI and feedback that it's progressing towards the mode"): the gauge on the right
 * edge, `level` pips lit, and its label, nothing in the middle. Call it every tick while it should show, and
 * with level -1 to take it down. It is the politest thing on the glass: it waits while another pack HUD is up (a
 * mode, a total, a note), a note or a mode of the pack takes its place at once, and it comes back by itself once
 * they are gone. A note of its own (kit_hud_note) goes in the award line above it and the meter stays. */
static KIT_UNUSED void kit_hud_meter(struct kit_hud *h, int level, const char *label)
{
    int k;
    if (level < 0) {
        if (!h->metering) return;
        h->metering = 0;
        if (h->up && h->noting) {
            if (h->award_until) h->hide_at = h->award_until;     /* its own note finishes first */
            else kit_hud_show(h, 0);
        }
        return;
    }
    if (h->up && !h->noting) return;                 /* the mode itself has its HUD */
    if (kit_hud_up && kit_hud_up != h) return;       /* another pack HUD is up: wait for it */
    h->want_gauge = level;
    if (label) kit_copy(h->want_glabel, sizeof h->want_glabel, label);
    if (h->up && h->metering) return;
    h->want_title[0] = h->want_line[0] = 0;
    for (k = 0; k < 3; k++) kit_hud_counter(h, k, 0, 0, 0);
    h->want_timer = -1;
    if (!h->up) {
        h->want_award[0] = h->want_awardsub[0] = 0;
        h->award_until = 0;
        kit_hud_show(h, 1);
    }
    h->noting = 1;
    h->metering = 1;
    h->hide_at = 0;
}

/* PAD-347: STACKING (pm_aside). While one of the game's own modes runs, its title, instruction line and
 * counters have the places ours copy (David's Premium, 2026-10-03: ours sat word for word on JET FIGHTER
 * ATTACK's). Ours step aside the way ANGUIRUS has always stacked on a battle: the mode's two lines move
 * into the award line between the game's counters and its title (an award still takes that line for its
 * moment), the counters along the top are hidden, the gauge on the right edge stays, and the timer badge
 * moves one slot down while a battle's BATTLE badge has the top one (a card built before PAD-347 has no
 * second slot: the badge is hidden then rather than drawn over the game's). */
static KIT_UNUSED void kit_hud_aside_note(struct kit_hud *h, int aside)
{
    if (aside == h->aside) return;
    if (aside && !h->aside)
        pm_log("hud %s: aside for %s - its lines in the award line, its counters hidden%s", h->slug,
               pm_stock_mode_what((unsigned)aside), aside != (int)PM_STOCK_BATTLE ? ""
               : h->timer2 ? ", its badge one slot down" : ", its badge hidden (no second slot on this card)");
    else if (!aside)
        pm_log("hud %s: back in its places - the game's mode is over", h->slug);
    h->aside = aside;
}

/* PAD-390: every HUD of the pack on the glass at once, each with the words the card build gave it (David's
 * Premium, 2026-10-05, ball 2: CORE 20% TEMPERATURE, HURRY-UP 20,000,000, MULTIPLIER, both badge slots "00").
 * A HUD is authored visible and the mode hid it once, when it found it; the game had the scene back in its
 * authored state - a fresh copy of it, or its nodes shown again - and nothing hid ours again. So every 2 s
 * the HUD looks again: the group the scene has now is not the one it found (a fresh copy, or none), it is
 * found afresh (and hidden, or written whole while the mode uses it); the same group, its state is sent
 * again - hidden while the mode is not using it, else shown with its badge, gauge and pips re-sent. */
#define KIT_HUD_RECHECK_MS 2000

static KIT_UNUSED void kit_hud_recheck(struct kit_hud *h)
{
    void *g;
    int k;
    if (!h->found || pm_ms() - h->checked_at < KIT_HUD_RECHECK_MS) return;
    h->checked_at = pm_ms();
    g = kit_hud_find1(h, 0, 0, 0);
    if (g != h->group) {
        pm_log("hud %s: the game made its HUD scene again - %s", h->slug,
               g ? "found afresh" : "gone for now, looked for twice a second");
        h->found = 0;
        h->tries = 0;
        h->group = 0;                      /* never shown or hidden again: the old copy's */
        kit_hud_find(h);
        return;
    }
    pm_show(h->group, h->up);
    if (!h->up) return;
    h->timer_up = h->timer2_up = h->gauge_up = -1;
    for (k = 0; k < h->n_pips; k++) h->pip_lit[k] = -1;
}

/* every tick: find, expire the award, and send the glass what changed */
static KIT_UNUSED void kit_hud_tick(struct kit_hud *h)
{
    int k, j, aside, low, off, covered;
    const char *title, *line, *award, *awardsub;
    kit_hud_find(h);
    kit_hud_recheck(h);
    if (h->hide_at && pm_ms() >= h->hide_at) {
        kit_hud_show(h, 0);
        return;
    }
    if (h->award_until && pm_ms() >= h->award_until) {
        h->award_until = 0;
        h->want_award[0] = h->want_awardsub[0] = 0;
    }
    if (!h->found || !h->up) return;
    /* PAD-353: a display of the game's has the screen (an award, a mode's start screen): its words are where
     * ours are, so ours are blank until it is gone; the badge and the gauge at the edges stay. PAD-390: a
     * qualification note's words too while one of the game's modes or multiballs has the middle - a note's line
     * is the award line already, so it has nowhere to step aside to */
    aside = pm_aside();
    covered = pm_display_covered();
    off = covered || (h->noting && aside);
    if (off != h->off) {
        pm_log("hud %s: %s", h->slug, !off ? "its words are back"
               : covered ? "its words wait while a display of the game's has the screen"
               : "its note waits while the game's mode has the middle of the screen");
        h->off = off;
    }
    if (h->noting) aside = 0;                    /* a qualification note is in the award line already */
    kit_hud_aside_note(h, aside);
    title = h->want_title;
    line = h->want_line;
    award = h->want_award;
    awardsub = h->want_awardsub;
    if (off) {
        title = line = award = awardsub = "";
    } else if (aside) {
        if (!award[0] && !awardsub[0]) {
            award = title;
            awardsub = line;
        }
        title = line = "";
    }
    kit_hud_text(h->t_title, h->w_title, sizeof h->w_title, title);
    kit_hud_text(h->t_line, h->w_line, sizeof h->w_line, line);
    kit_hud_text(h->t_award, h->w_award, sizeof h->w_award, award);
    kit_hud_text(h->t_awardsub, h->w_awardsub, sizeof h->w_awardsub, awardsub);
    for (k = 0; k < 3; k++)
        for (j = 0; j < 3; j++)
            kit_hud_text(h->t_c[k][j], h->w_c[k][j], sizeof h->w_c[k][j], aside || off ? "" : h->want_c[k][j]);
    low = aside == (int)PM_STOCK_BATTLE;          /* the game's BATTLE badge has the top slot */
    if (h->timer) {
        int up = h->want_timer >= 0 && !low;
        if (up != h->timer_up) { pm_show(h->timer, up); h->timer_up = up; }
        if (up) {
            char b[8];
            pm_snprintf(b, sizeof b, "%02d", h->want_timer > 99 ? 99 : h->want_timer);
            kit_hud_text(h->t_timer, h->w_timer, sizeof h->w_timer, b);
        }
    }
    if (h->timer2) {
        int up = h->want_timer >= 0 && low;
        if (up != h->timer2_up) { pm_show(h->timer2, up); h->timer2_up = up; }
        if (up) {
            char b[8];
            pm_snprintf(b, sizeof b, "%02d", h->want_timer > 99 ? 99 : h->want_timer);
            kit_hud_text(h->t_timer2, h->w_timer2, sizeof h->w_timer2, b);
        }
    }
    if (h->gauge) {
        int up = h->want_gauge >= 0;
        if (up != h->gauge_up) { pm_show(h->gauge, up); h->gauge_up = up; }
        if (up) {
            kit_hud_text(h->t_glabel, h->w_glabel, sizeof h->w_glabel, h->want_glabel);
            for (k = 0; k < h->n_pips; k++) {
                int lit = k < h->want_gauge, gone = h->pips > 0 && k >= h->pips;
                int state = gone ? 2 : lit;        /* 2: a pip past the ones in use, both pictures hidden */
                if (state == h->pip_lit[k]) continue;
                pm_show(h->pip_on[k], state == 1);
                pm_show(h->pip_off[k], state == 0);
                h->pip_lit[k] = state;
            }
        }
    }
}

/* a mode's start: everything cleared, the badge and gauge hidden until asked, the group shown */
static KIT_UNUSED void kit_hud_begin(struct kit_hud *h, const char *title, const char *line)
{
    int k;
    h->noting = 0;
    h->metering = 0;
    h->hide_at = 0;
    h->want_award[0] = h->want_awardsub[0] = 0;
    h->award_until = 0;
    for (k = 0; k < 3; k++) kit_hud_counter(h, k, 0, 0, 0);
    h->want_timer = h->want_gauge = -1;
    h->want_glabel[0] = 0;
    kit_hud_title(h, title, line ? line : "");
    kit_hud_show(h, 1);
}

/* ---- LIGHT SHOWS at a mode's start and end (hud-layers) --------------------------------------------
 * David, 2026-09-26: "add some intricate light shows when the modes start and end. They should be
 * unique and colorful." A show is a short list of STEPS, each a pattern over the playfield's inserts by
 * their PLACE (the port's "at X,Y": x 0-300 across, y 0-600 down the playfield picture) for some ms, in
 * the step's colours. Every tick the show paints each placed insert (pm_lamp_paint: held in the mode's
 * layer, only a change reaches the game), and the GI strings (not placed) follow the step's GI setting:
 * dark for a spotlight show, flashed white on a strobe. When it ends every insert goes back to the game
 * and the mode's own shot lights are sent again. */
enum kit_fx {
    KIT_FX_BURST,        /* a ring from (x, y) outwards, colour a, trailing into colour b */
    KIT_FX_IMPLODE,      /* the same ring coming IN to (x, y) */
    KIT_FX_SWEEP_UP,     /* a band from the flippers to the top, a then b behind it */
    KIT_FX_SWEEP_DOWN,   /* the band from the top down */
    KIT_FX_SWEEP_LR,     /* left to right */
    KIT_FX_SWEEP_RL,     /* right to left */
    KIT_FX_SPIN,         /* a beam turning round (x, y): a on the beam, b off it */
    KIT_FX_RAINBOW,      /* the hue turns round (x, y) */
    KIT_FX_STROBE,       /* all a / all b, every `rate` ms */
    KIT_FX_SPARKLE,      /* b, with inserts flashing a at random */
    KIT_FX_FIRE,         /* a flickering blaze: b at the bottom rising into a */
    KIT_FX_PULSE,        /* all inserts breathing between a and b (a heartbeat when rate is short) */
    KIT_FX_CHASE_RING,   /* inserts in order round (x, y) lighting one after another */
    KIT_FX_FADE_OUT,     /* a fading to black */
    KIT_FX_BOLTS         /* lightning: jagged bands from the top striking down, a on b */
};
#define KIT_GI_KEEP   0   /* the GI does what the game says */
#define KIT_GI_DARK   1   /* the GI off: only the show lights the playfield */
#define KIT_GI_FLASH  2   /* the GI flashing white with a strobe */
struct kit_fx_step { int fx; unsigned ms; unsigned a, b; int x, y; unsigned rate; int gi; };
/* places on Godzilla's playfield picture (the port's lamp lines), for a show's (x, y) */
#define KIT_AT_CENTER     150, 330
#define KIT_AT_BUILDING   123, 202
#define KIT_AT_MASER       51, 417
#define KIT_AT_SHIELDS    199, 346
#define KIT_AT_FLIPPERS   150, 560
#define KIT_AT_TOP        150, 120
#define KIT_AT_MAGNA       89, 260
#define KIT_SHOW_STEPS 10
#define KIT_SHOW_LAMPS 128

struct kit_show {
    const char *name;
    struct kit_fx_step steps[KIT_SHOW_STEPS];
    int n, step, on;
    unsigned long t0, step_t0;
    unsigned seed;
    int gi[8], n_gi, placed;
};

static KIT_UNUSED unsigned kit_mix(unsigned a, unsigned b, int f256)       /* a..b by f/256 */
{
    int k, out = 0;
    if (f256 < 0) f256 = 0;
    if (f256 > 256) f256 = 256;
    for (k = 0; k < 3; k++) {
        int ca = (int)((a >> (16 - 8 * k)) & 255u), cb = (int)((b >> (16 - 8 * k)) & 255u);
        out |= ((ca + (cb - ca) * f256 / 256) & 255) << (16 - 8 * k);
    }
    return (unsigned)out;
}

static KIT_UNUSED unsigned kit_scale(unsigned c, int f256) { return kit_mix(0, c, f256); }

static KIT_UNUSED unsigned kit_hue(int h)             /* 0..1535 round the colour wheel, full brightness */
{
    int s = ((h % 1536) + 1536) % 1536, i = s / 256, f = s % 256;
    switch (i) {
    case 0: return PM_RGB(255, f, 0);
    case 1: return PM_RGB(255 - f, 255, 0);
    case 2: return PM_RGB(0, 255, f);
    case 3: return PM_RGB(0, 255 - f, 255);
    case 4: return PM_RGB(f, 0, 255);
    default: return PM_RGB(255, 0, 255 - f);
    }
}

static KIT_UNUSED unsigned kit_rand(unsigned *s)
{
    *s = *s * 1103515245u + 12345u;
    return (*s >> 16) & 0x7fffu;
}

static KIT_UNUSED int kit_isqrt(int v)
{
    int r = 0, b = 1 << 14;
    if (v <= 0) return 0;
    while (b > v) b >>= 2;
    while (b) {
        if (v >= r + b) { v -= r + b; r = (r >> 1) + b; } else r >>= 1;
        b >>= 2;
    }
    return r;
}

/* atan2 in 1/1536 turns (the hue wheel's), good to a few degrees */
static KIT_UNUSED int kit_angle(int dx, int dy)
{
    int ax = dx < 0 ? -dx : dx, ay = dy < 0 ? -dy : dy, a;
    if (!ax && !ay) return 0;
    a = ax >= ay ? (ay * 192) / (ax ? ax : 1) : 384 - (ax * 192) / (ay ? ay : 1);   /* 0..384 = 0..90 deg */
    if (dx < 0) a = 768 - a;
    if (dy < 0) a = 1536 - a;
    return a % 1536;
}

static KIT_UNUSED void kit_show_start(struct kit_show *s, const char *name, const struct kit_fx_step *steps, int n)
{
    int i, k, cnt = pm_lamp_count();
    if (n > KIT_SHOW_STEPS) n = KIT_SHOW_STEPS;
    for (i = 0; i < n; i++) s->steps[i] = steps[i];
    s->n = n;
    s->name = name;
    s->step = 0;
    s->on = pm_can(PM_CAN_LAMPS) && n > 0;
    s->t0 = s->step_t0 = pm_ms();
    s->seed = (unsigned)s->t0 | 1u;
    s->n_gi = s->placed = 0;
    for (k = 0; k < cnt && k < KIT_SHOW_LAMPS; k++) {
        const char *nm = pm_lamp_at(k, 0);
        int x, y;
        if (pm_lamp_xy(k, &x, &y)) s->placed++;
        else if (nm && s->n_gi < 8 && nm[0] && (nm[0] == 'L' || nm[0] == 'U') && kit_names_have(
                     "LOWER PLAYFIELD GI-WHT(X9),UPPER PLAYFIELD GI-WHT(X12),LOWER PLAYFIELD GI-RED(X4),UPPER PLAYFIELD GI-RED(X9)", nm))
            s->gi[s->n_gi++] = k;
    }
    if (s->on) pm_log("show %s: %d step(s) over %d placed inserts, %d GI string(s)", name, n, s->placed, s->n_gi);
}

/* the colour of the insert at (x, y) for step st at `t` ms into it */
static KIT_UNUSED unsigned kit_fx_colour(struct kit_show *s, const struct kit_fx_step *st, int x, int y, int idx, unsigned t)
{
    int f = st->ms ? (int)((unsigned long)t * 256u / st->ms) : 256;     /* 0..256 through the step */
    int dx = x - st->x, dy = y - st->y, d, r, w, v;
    unsigned rate = st->rate ? st->rate : 100;
    switch (st->fx) {
    case KIT_FX_BURST:
    case KIT_FX_IMPLODE:
        d = kit_isqrt(dx * dx + dy * dy);
        r = st->fx == KIT_FX_BURST ? f * 700 / 256 : (256 - f) * 700 / 256;
        w = d - r;
        if (w > 0 && w < 60) return kit_scale(st->a, 256 - w * 4);          /* the ring's leading edge */
        if (w <= 0 && w > -140) return kit_mix(st->a, st->b, -w * 256 / 140); /* its wake */
        return w <= 0 ? st->b : 0;
    case KIT_FX_SWEEP_UP:
    case KIT_FX_SWEEP_DOWN:
        r = st->fx == KIT_FX_SWEEP_UP ? 640 - f * 720 / 256 : f * 720 / 256 - 40;
        w = st->fx == KIT_FX_SWEEP_UP ? y - r : r - y;
        if (w >= 0 && w < 50) return st->a;
        if (w >= 50) return kit_mix(st->a, st->b, (w - 50) * 3);
        return 0;
    case KIT_FX_SWEEP_LR:
    case KIT_FX_SWEEP_RL:
        r = st->fx == KIT_FX_SWEEP_LR ? f * 380 / 256 - 40 : 340 - f * 380 / 256;
        w = st->fx == KIT_FX_SWEEP_LR ? r - x : x - r;
        if (w >= 0 && w < 30) return st->a;
        if (w >= 30) return kit_mix(st->a, st->b, (w - 30) * 4);
        return 0;
    case KIT_FX_SPIN:
        v = (kit_angle(dx, dy) - (int)(t * 1536u / (rate * 8u))) % 1536;
        if (v < 0) v += 1536;
        return v < 160 ? st->a : v < 400 ? kit_mix(st->a, st->b, (v - 160) * 256 / 240) : st->b;
    case KIT_FX_RAINBOW:
        return kit_hue(kit_angle(dx, dy) + (int)(t * 1536u / (rate * 10u)) + kit_isqrt(dx * dx + dy * dy) * 2);
    case KIT_FX_STROBE:
        return (t / rate) % 2 ? st->b : st->a;
    case KIT_FX_SPARKLE:
        return ((kit_rand(&s->seed) + (unsigned)idx * 7u) % 100u) < 18u ? st->a : st->b;
    case KIT_FX_FIRE:
        v = (int)(kit_rand(&s->seed) % 90u);
        w = (600 - y) * 256 / 600;                                           /* 0 at the flippers */
        return kit_scale(kit_mix(st->b, st->a, w + v - 45), 150 + v);
    case KIT_FX_PULSE:
        v = (int)((t % (rate * 2u)) * 512u / (rate * 2u));
        v = v < 256 ? v : 512 - v;
        return kit_mix(st->b, st->a, v);
    case KIT_FX_CHASE_RING:
        v = (kit_angle(dx, dy) * 12 / 1536 + 12 - (int)((t / rate) % 12u)) % 12;
        return v == 0 ? st->a : v == 1 ? kit_scale(st->a, 110) : st->b;
    case KIT_FX_FADE_OUT:
        return kit_scale(st->a, 256 - f);
    case KIT_FX_BOLTS:
        v = (int)((t / rate) % 5u);                                          /* five strikes */
        r = 40 + v * 55 + (int)((unsigned)(y * 13 + v * 71) % 40u) - 20;     /* the bolt's jagged x */
        w = x - r;
        if (w < 0) w = -w;
        return w < 18 && (t % rate) < rate * 2 / 3 ? st->a : st->b;
    }
    return 0;
}

/* Every tick while the show runs. `lamps` is the mode's own shot lights, sent again at the end.
 * Returns 1 while it runs. */
static KIT_UNUSED int kit_show_tick(struct kit_show *s, struct kit_lamps *lamps)
{
    const struct kit_fx_step *st;
    unsigned long now = pm_ms();
    unsigned t;
    int k, cnt;
    if (!s->on) return 0;
    while (s->step < s->n && now - s->step_t0 >= s->steps[s->step].ms) {
        s->step_t0 += s->steps[s->step].ms;
        s->step++;
    }
    if (s->step >= s->n) {
        s->on = 0;
        pm_lamp_release_all();
        if (lamps) lamps->n_now = 0;       /* the mode's own lights: all sent again at its next commit */
        pm_log("show %s: over, %lu ms", s->name, now - s->t0);
        return 0;
    }
    st = &s->steps[s->step];
    t = (unsigned)(now - s->step_t0);
    cnt = pm_lamp_count();
    for (k = 0; k < cnt && k < KIT_SHOW_LAMPS; k++) {
        int x, y;
        if (pm_lamp_xy(k, &x, &y)) pm_lamp_paint(k, kit_fx_colour(s, st, x, y, k, t));
    }
    for (k = 0; k < s->n_gi; k++) {
        if (st->gi == KIT_GI_DARK) pm_lamp_paint(s->gi[k], 0);
        else if (st->gi == KIT_GI_FLASH) pm_lamp_paint(s->gi[k], ((t / (st->rate ? st->rate : 100)) % 2) ? 0 : KIT_WHITE);
        else pm_lamp_release(pm_lamp_at(s->gi[k], 0));
    }
    return 1;
}

static KIT_UNUSED void kit_show_stop(struct kit_show *s, struct kit_lamps *lamps)
{
    if (!s->on) return;
    s->on = 0;
    pm_lamp_release_all();
    if (lamps) lamps->n_now = 0;
}

#endif
