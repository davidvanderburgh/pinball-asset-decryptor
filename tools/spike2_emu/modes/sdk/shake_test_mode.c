/* shake_test_mode.c - a rig instrument for the shaker (PAD-414), never a card's mode.
 *
 * Trigger files in /dump (read twice a second):
 *   shake.go    "<words>"  begin (when not running), then:
 *                 <ms> <strength>   pm_shake(ms, strength)
 *                 game <name>       pm_shake_game(name)
 *                 stop              pm_shake_stop
 *                 outlast           pm_shake_outlast
 *   shake.end             pm_end: the runtime must stop a shake of the mode's (unless it outlasts)
 * Every change of pm_shaking() is logged with the time since the mode began. The runtime's "shaker:" lines and
 * hwshim's [coildrive] lines (PAD_COIL_PROBE=1) say what reached the board. */
#include "pad_mode.h"

static unsigned ticks;
static int was = -1;
static unsigned long t0;

static int same(const char *a, const char *b)
{
    while (*a && *a == *b) a++, b++;
    return *a == *b;
}

static unsigned number(const char **s)
{
    unsigned v = 0;
    while (**s == ' ') (*s)++;
    while (**s >= '0' && **s <= '9') v = v * 10 + (unsigned)(*(*s)++ - '0');
    return v;
}

static void on_tick(void)
{
    char t[48];
    const char *p;
    unsigned ms, strength;
    int now;
    if (++ticks % 30 == 0) {
        if (pm_trigger_text("shake.go", t, sizeof t)) {
            if (!pm_running()) {
                if (!pm_begin()) pm_log("shake test: could not begin");
                t0 = pm_ms();
            }
            if (same(t, "stop")) {
                pm_shake_stop();
                pm_log("shake test: pm_shake_stop");
            } else if (same(t, "outlast")) {
                pm_shake_outlast();
                pm_log("shake test: pm_shake_outlast");
            } else if (t[0] == 'g' && t[1] == 'a' && t[2] == 'm' && t[3] == 'e' && t[4] == ' ') {
                pm_log("shake test: pm_shake_game(%s) = %d", t + 5, pm_shake_game(t + 5));
            } else {
                p = t;
                ms = number(&p);
                strength = number(&p);
                pm_log("shake test: pm_shake(%u, %u) = %d", ms, strength, pm_shake(ms, strength));
            }
        }
        if (pm_trigger("shake.end") && pm_running()) {
            pm_log("shake test: pm_end at +%lu ms", pm_ms() - t0);
            pm_end();
        }
    }
    now = pm_shaking();
    if (now != was) {
        pm_log("shake test: +%lu ms shaking %d", t0 ? pm_ms() - t0 : 0ul, now);
        was = now;
    }
}

static void on_init(void)
{
    pm_log("shake test: PM_CAN_SHAKER %d", pm_can(PM_CAN_SHAKER));
}

static const struct pm_mode shake_test = {
    .name = "SHAKE TEST",
    .init = on_init,
    .tick = on_tick,
};
PM_REGISTER(shake_test);
