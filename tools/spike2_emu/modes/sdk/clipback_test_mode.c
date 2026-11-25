/* clipback_test_mode.c - a rig instrument for a mode's clip coming back after the game's (PAD-530 / PAD-725), never a
 * card's mode. PAD-1555: proves a build's surface_seek / surface_duration / surface_position (the November 2026 builds
 * moved them: a third player layout).
 *
 * Trigger files in /dump (read twice a second), each holding a clip name of the video bank:
 *   clipback.mine  "<clip>"   pm_begin + pm_clip: the clip is this mode's
 *   clipback.game  "<clip>"   pm_game_clip: a clip put on the bank's surface as the game's own (it takes the surface)
 *   clipback.end              pm_end
 * The runtime then says "is back on the surface at W ms of LEN" (seek, duration) and, a second on, "plays at P ms, 1 s
 * after it was put back at W" (position): P near W + 1000 is the proof. */
#include "pad_mode.h"

static unsigned ticks;
static int mine;

static void on_tick(void)
{
    char name[96];
    if (++ticks % 30) return;
    if (pm_trigger_text("clipback.mine", name, sizeof name)) {
        mine = mine || pm_begin();
        pm_log("mine \"%s\": begun %d, clip %d", name, mine, mine ? pm_clip(name) : 0);
    }
    if (pm_trigger_text("clipback.game", name, sizeof name)) pm_log("game \"%s\": %d", name, pm_game_clip(name, 0));
    if (pm_trigger("clipback.end") && mine) {
        pm_end();
        mine = 0;
        pm_log("ended");
    }
}

static void on_init(void)
{
    pm_log("clipback test: can clips %d", pm_can(PM_CAN_CLIPS));
}

static const struct pm_mode clipback_test = {
    .name = "CLIPBACK TEST",
    .init = on_init,
    .tick = on_tick,
};
PM_REGISTER(clipback_test);
