/* magnet_test_mode.c - a rig instrument for pm_magnet_grab (PAD-381), never a card's mode.
 *
 * Trigger files in /dump (read twice a second):
 *   magnet.grab    "<ms>"   begin (when not running) and grab for ms
 *   magnet.release          pm_magnet_release
 *   magnet.end              pm_end: the mode ends with the magnet held - the runtime must let go
 *   magnet.wedge   "<ms>"   begin, grab, then this mode does NOTHING more, ever (no release, no end,
 *                           no trigger reading): the runtime's own deadline must let go
 *   magnet.flood            grab 8 times in a row, one a second: the refusals the limits give
 *   magnet.burst            8 grabs of 100 ms, 3.5 s apart: the seventh meets the per-minute cap
 * It logs what it asked and what came back; the runtime's "magnet:" lines and hwshim's
 * [coildrive] lines say what reached the board. */
#include "pad_mode.h"

static unsigned ticks, flood_left, burst_left, wedged;

static void grab(unsigned ms)
{
    if (!pm_running() && !pm_begin()) {
        pm_log("magnet test: could not begin");
        return;
    }
    pm_log("magnet test: grab %u ms -> %d (holding %d)", ms, pm_magnet_grab(ms), pm_magnet_holding());
}

static unsigned number(const char *s)
{
    unsigned v = 0;
    while (*s >= '0' && *s <= '9') v = v * 10 + (unsigned)(*s++ - '0');
    return v;
}

static void on_tick(void)
{
    char t[32];
    if (wedged) return;
    if (++ticks % 30) return;
    if (pm_trigger_text("magnet.grab", t, sizeof t)) grab(number(t));
    if (pm_trigger("magnet.release")) {
        pm_magnet_release();
        pm_log("magnet test: released (holding %d)", pm_magnet_holding());
    }
    if (pm_trigger("magnet.end")) {
        pm_log("magnet test: ending the mode while holding %d", pm_magnet_holding());
        pm_end();
    }
    if (pm_trigger_text("magnet.wedge", t, sizeof t)) {
        grab(number(t));
        wedged = 1;
        pm_log("magnet test: WEDGED - this mode does nothing more");
    }
    if (pm_trigger("magnet.flood")) flood_left = 8, burst_left = 0;
    if (flood_left && ticks % 60 == 0) {
        flood_left--;
        grab(1000);
    }
    if (pm_trigger("magnet.burst")) burst_left = 8, flood_left = 0;
    if (burst_left && ticks % 210 == 0) {     /* 100 ms grabs 3.5 s apart: past the cool-down */
        burst_left--;
        grab(100);
    }
}

static void on_init(void)
{
    pm_log("magnet test: can %d", pm_can(PM_CAN_COILS));
}

static const struct pm_mode magnet_test = {
    .name = "MAGNET TEST",
    .init = on_init,
    .tick = on_tick,
};
PM_REGISTER(magnet_test);
