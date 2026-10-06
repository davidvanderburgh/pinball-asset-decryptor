/* building_test_mode.c - a rig instrument for pm_building (PAD-393), never a card's mode.
 *
 * Trigger files in /dump (read twice a second):
 *   building.go    "<floor>"  begin (when not running) and move the building to that floor
 *   building.end              pm_end: the runtime must put the building back
 * Every second while the mode runs it logs pm_building_floor(). The runtime's "building:" lines and
 * hwshim's [stepper] lines say what reached the board. */
#include "pad_mode.h"

static unsigned ticks;
static int last = -3;

static unsigned number(const char *s)
{
    unsigned v = 0;
    while (*s >= '0' && *s <= '9') v = v * 10 + (unsigned)(*s++ - '0');
    return v;
}

static void on_tick(void)
{
    char t[32];
    int f;
    if (++ticks % 30) return;
    if (pm_trigger_text("building.go", t, sizeof t)) {
        if (!pm_running() && !pm_begin()) pm_log("building test: could not begin");
        else pm_log("building test: floor %u -> %d", number(t), pm_building((int)number(t)));
    }
    if (pm_trigger("building.end")) {
        pm_log("building test: ending the mode at floor %d", pm_building_floor());
        pm_end();
    }
    f = pm_building_floor();
    if (f != last) {
        pm_log("building test: pm_building_floor %d", f);
        last = f;
    }
}

static void on_init(void)
{
    pm_log("building test: can %d", pm_can(PM_CAN_BUILDING));
}

static const struct pm_mode building_test = {
    .name = "BUILDING TEST",
    .init = on_init,
    .tick = on_tick,
};
PM_REGISTER(building_test);
