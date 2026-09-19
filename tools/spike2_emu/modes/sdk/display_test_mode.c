/* display_test_mode.c - a mode that holds a DISPLAY PRIORITY, shows its screen, plays its clip and
 * rewrites its words every tick, started from a trigger file (item 154 display).
 *
 * Not a game mode to ship: a rig instrument built with the SDK, next to mode_file.c:
 *   build_mode.sh -o mode.so mode_file.c display_test_mode.c
 * Twice a second it looks for, in /dump:
 *   display_test.start "<priority> <seconds> <folder> [clip]"
 *        starts (pm_begin) with pm_display_priority(priority) (0 = none), shows
 *        PadMode_<folder>_Screen, plays [clip] (default PadMode_<folder>_Clip), and ends after
 *        <seconds>; e.g. "230 25 shin_godzilla"
 *   display_test.stop    ends it now
 * While it runs it writes "<seconds>.<tenths> S  <hits> HITS" on its screen EVERY TICK (the words
 * change ten times a second; pm_set_text sends only a change to the game), logs every change of
 * pm_display_covered(), and once a second how many times it called pm_set_text. Any playfield shot
 * counts as a hit. Its screen is found and hidden at load, like every mode's.
 * Log lines: "[DISPLAY TEST] ..." in /dump/mode.log.
 */
#include "pad_mode.h"

#define TICKS 60

static struct {
    int on;
    unsigned priority, ticks_left, hits, calls, hide_ticks;
    int covered;
    char folder[48], clip[96];
} t;
static void *screen, *words;
static char want_screen[96], want_words[160];

static unsigned number(const char **p)
{
    unsigned v = 0;
    while (**p == ' ') (*p)++;
    while (**p >= '0' && **p <= '9') v = v * 10 + (unsigned)(*(*p)++ - '0');
    return v;
}

static void word(const char **p, char *out, unsigned cap)
{
    unsigned n = 0;
    while (**p == ' ') (*p)++;
    while (**p && **p != ' ' && n + 1 < cap) out[n++] = *(*p)++;
    out[n] = 0;
}

static void find_screen(void)
{
    if (screen || !want_screen[0]) return;
    screen = pm_node("hud", want_screen);
    if (!screen) return;
    words = pm_text("hud", want_words);
    pm_show(screen, t.on);
    pm_log("screen %s found (words %s) - %s", want_screen, words ? "found" : "missing", t.on ? "shown" : "hidden");
}

static void stop(const char *why)
{
    if (!t.on) return;
    t.on = 0;
    pm_display_priority(0);
    if (words) pm_set_text(words, "TEST OVER");
    t.hide_ticks = 3 * TICKS;
    pm_end();
    pm_log("END (%s): %u hits, %u pm_set_text calls", why, t.hits, t.calls);
}

static void start(const char *args)
{
    const char *p = args;
    if (t.on) { pm_log("already running"); return; }
    if (!pm_in_game()) { pm_log("not started: no game in play"); return; }
    t.priority = number(&p);
    t.ticks_left = number(&p) * TICKS;
    word(&p, t.folder, sizeof t.folder);
    word(&p, t.clip, sizeof t.clip);
    if (!t.ticks_left) t.ticks_left = 20 * TICKS;
    if (!t.folder[0]) { pm_log("not started: display_test.start needs \"<priority> <seconds> <folder> [clip]\""); return; }
    if (!t.clip[0]) pm_snprintf(t.clip, sizeof t.clip, "PadMode_%s_Clip", t.folder);
    if (!pm_begin()) return;
    t.on = 1;
    t.hits = t.calls = 0;
    t.covered = 0;
    pm_snprintf(want_screen, sizeof want_screen, "PadMode_%s_Screen", t.folder);
    pm_snprintf(want_words, sizeof want_words, "PadMode_%s_Screen.PadMode_%s_Screen_Words", t.folder, t.folder);
    screen = words = 0;
    find_screen();
    pm_log("START: priority %u (%s), %u s, screen %s (%s), clip %s", t.priority,
           t.priority ? (pm_display_priority(t.priority) ? "held" : "NOT held: no display arbitration on this port") : "none",
           t.ticks_left / TICKS, want_screen, screen ? "shown" : "not found", t.clip);
    pm_log("clip %s %s", t.clip, pm_clip(t.clip) ? "played" : "NOT played");
}

static void on_tick(void)
{
    static unsigned ticks;
    char buf[160];
    ticks++;
    if (ticks % 30 == 0) {
        if (pm_trigger_text("display_test.start", buf, sizeof buf)) start(buf);
        if (pm_trigger("display_test.stop")) stop("trigger file");
        find_screen();
    }
    if (t.hide_ticks && --t.hide_ticks == 0 && !t.on && screen) {
        pm_show(screen, 0);
        pm_log("screen hidden");
    }
    if (!t.on) return;
    if (!pm_in_game()) { stop("left the game"); return; }
    if (t.ticks_left) t.ticks_left--;
    if (words) {                                  /* every tick: the runtime sends only a change */
        pm_snprintf(buf, sizeof buf, "%u.%u S  %u HITS", t.ticks_left / TICKS, t.ticks_left % TICKS / 6, t.hits);
        pm_set_text(words, buf);
        t.calls++;
    }
    if (pm_display_covered() != t.covered) {
        t.covered = pm_display_covered();
        pm_log("%s (%u.%u s left)", t.covered ? "covered by a game display that beat the priority" : "in view again",
               t.ticks_left / TICKS, t.ticks_left % TICKS / 6);
    }
    if (ticks % TICKS == 0) pm_log("%u.%u s left, %u hits, pm_set_text called %u times", t.ticks_left / TICKS,
                                    t.ticks_left % TICKS / 6, t.hits, t.calls);
    if (!t.ticks_left) stop("time ran out");
}

static void on_shot(uint64_t shot)
{
    if (!t.on || shot == 1) return;
    t.hits++;
    pm_log("shot %08x_%08x: hit %u", (unsigned)(shot >> 32), (unsigned)shot, t.hits);
}

static void on_ball_end(void) { stop("ball ended"); }

static const struct pm_mode display_test = {
    .name = "DISPLAY TEST",
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
};
PM_REGISTER(display_test);
