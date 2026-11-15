/* place_probe_mode.c - PAD-1286 rig instrument (never a card's mode): the game's own Orbits start (block id 1) called
 * as its rules call it, 25 s into a game; a mode file `in_place_of 1` takes its place, its 8 s clock completes it
 * (the game's COMPLETED flag 67), and a mode file `starts_on completed 1 1` starts on that. */
#include "pad_mode.h"

static void on_tick(void)
{
    static unsigned long t0, next;
    static int phase;
    if (!pm_in_game()) { t0 = 0; return; }
    if (!t0) { t0 = pm_ms(); next = t0 + 25000; pm_log("[probe] in game: the game's Orbits start at +25 s"); }
    if (pm_ms() < next || phase >= 4) return;
    if (phase == 0) {
        pm_log("[probe] done(1) before %d, can game_done %d", pm_game_mode_done(1), pm_can(PM_CAN_GAME_DONE));
        pm_log("[probe] the game's Orbits start called: %d", pm_game_mode_start(1));
        next = pm_ms() + 12000;
    } else {
        pm_log("[probe] +%lu s: done(1) %d, a mode of ours running %d", (pm_ms() - t0) / 1000, pm_game_mode_done(1),
               pm_running());
        next = pm_ms() + 4000;
    }
    phase++;
}

static const struct pm_mode place_probe = { .name = "placeprobe", .tick = on_tick };
PM_REGISTER(place_probe);
