/* shield_test_mode.c - a rig instrument for the shield platform (PAD-392), never a card's mode.
 *
 * Trigger files in /dump (read twice a second):
 *   shield.go    "<word>"  begin (when not running), then:
 *                  toward / away       pm_shield once
 *                  keep / keep_away    pm_shield_keep: turn it and keep it there while the mode runs
 *                  keep_off            stop keeping (it stays where it is)
 *                  blind               pm_block_game_modes(1): the game's modes refused, its rules see no shots
 *                  blind_keep_shield   the same, but the game's Mechagodzilla Shield feature keeps counting
 *   shield.end            pm_end: the runtime must put the platform back
 * Every change of pm_shield_position(), and every shot while it runs, is logged with the time since the mode
 * began. The runtime's
 * "shield:" lines and hwshim's [motor] lines (node 9 coil 2) say what reached the board. */
#include "pad_mode.h"

static unsigned ticks;
static int last = -3;
static unsigned long t0;

static int same(const char *a, const char *b)
{
    while (*a && *a == *b) a++, b++;
    return *a == *b;
}

static void on_tick(void)
{
    char t[32];
    int at;
    if (++ticks % 30 == 0) {
        if (pm_trigger_text("shield.go", t, sizeof t)) {
            if (!pm_running()) {
                if (!pm_begin()) pm_log("shield test: could not begin");
                t0 = pm_ms();
            }
            if (same(t, "toward")) pm_log("shield test: pm_shield(TOWARD) = %d", pm_shield(PM_SHIELD_TOWARD));
            else if (same(t, "away")) pm_log("shield test: pm_shield(AWAY) = %d", pm_shield(PM_SHIELD_AWAY));
            else if (same(t, "keep")) pm_log("shield test: pm_shield_keep(TOWARD) = %d", pm_shield_keep(PM_SHIELD_TOWARD));
            else if (same(t, "keep_away")) pm_log("shield test: pm_shield_keep(AWAY) = %d", pm_shield_keep(PM_SHIELD_AWAY));
            else if (same(t, "keep_off")) pm_log("shield test: pm_shield_keep(0) = %d", pm_shield_keep(0));
            else if (same(t, "blind")) {
                pm_block_game_modes(0);
                pm_block_rules_keep(0, 0);
                pm_log("shield test: pm_block_game_modes(1) = %d", pm_block_game_modes(1));
            }
            else if (same(t, "blind_keep_shield")) {
                pm_block_game_modes(0);
                pm_log("shield test: keep Mechagodzilla Shield %d, pm_block_game_modes(1) = %d",
                       pm_block_rules_keep_names("Mechagodzilla Shield"), pm_block_game_modes(1));
            }
            else pm_log("shield test: no such word \"%s\"", t);
        }
        if (pm_trigger("shield.end")) {
            pm_log("shield test: ending the mode at position %d", pm_shield_position());
            pm_end();
        }
    }
    at = pm_shield_position();
    if (at != last) {
        pm_log("shield test: position %d (%s) at +%lu ms", at, at == PM_SHIELD_TOWARD ? "toward" :
               at == PM_SHIELD_AWAY ? "away" : at == 0 ? "turning" : "no platform", t0 ? pm_ms() - t0 : 0ul);
        last = at;
    }
}

static void on_shot(uint64_t shot)
{
    if (pm_running())
        pm_log("shield test: shot %08x_%08x at +%lu ms, position %d", (unsigned)(shot >> 32), (unsigned)shot,
               pm_ms() - t0, pm_shield_position());
}

static void on_init(void)
{
    pm_log("shield test: can %d", pm_can(PM_CAN_SHIELD));
}

static const struct pm_mode shield_test = {
    .name = "SHIELD TEST",
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
};
PM_REGISTER(shield_test);
