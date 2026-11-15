/* block_probe_mode.c - PAD-1285 rig instrument (never a card's mode): the game's own mode start (Ramps, block id 2)
 * called as its rules call it, once while a mode of ours blocks the game's modes, once while none does.
 * A: pm_begin + pm_block_game_modes(1), claim 2 not taken -> the start's veto must refuse it (flag 87 stays clear).
 * B: pm_end, claim 2 not taken -> the game's own start runs: flag 87 set, pm_stock_mode_running sees a mode. */
#include "pad_mode.h"

static int not_taken(unsigned id) { pm_log("[probe] claim callback for %u: not taken", id); return 0; }

static void on_tick(void)
{
    static unsigned long t0, next;
    static int phase;
    if (!pm_in_game()) { t0 = 0; return; }
    if (!t0) { t0 = pm_ms(); next = t0 + 25000; pm_log("[probe] in game: phase A at +25 s"); }
    if (pm_ms() < next || phase >= 3) return;
    if (phase == 0) {
        pm_log("[probe] A: begin %d, block %d, stock before %d", pm_begin(), pm_block_game_modes(1),
               pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL | PM_STOCK_ANY));
        pm_log("[probe] A: claim %d, the game's start called %d", pm_place_claim(2, not_taken), pm_game_mode_start(2));
        pm_place_release(2);
        pm_log("[probe] A: stock after %d", pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_ANY));
        pm_end();
        next = pm_ms() + 3000;
    } else if (phase == 1) {
        pm_log("[probe] B: running %d, claim %d, the game's start called %d", pm_running(), pm_place_claim(2, not_taken),
               pm_game_mode_start(2));
        pm_place_release(2);
        next = pm_ms() + 1000;
    } else {
        pm_log("[probe] B: stock after %d (%s)", pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_ANY),
               pm_stock_mode_what(PM_STOCK_BATTLE));
    }
    phase++;
}

static const struct pm_mode block_probe = { .name = "blockprobe", .tick = on_tick };
PM_REGISTER(block_probe);
