/* census_mode.c - the SHOT CENSUS mode: which shot does each switch make? (item 135)
 *
 * Not a game mode: a measuring instrument built with the SDK. It logs every shot mask the
 * game dispatches, and a marker line whenever /dump/census.mark appears (holding the id
 * of the switch about to be pressed), so shot_census.py can say which switch made which
 * shot. Build it with any port's game and run it with a game in play:
 *
 *   build_mode.sh -o census.so census_mode.c
 *   for each switch: echo <id> > /dump/census.mark; swpoke.py <id> 150; wait ~1.5 s
 *   shot_census.py <mode.log> <switch_list.txt> [--ref-port <port>]
 */
#include "pad_mode.h"

static void on_init(void)
{
    pm_log("census ready on %s %s", pm_game(), pm_version());
}

static void on_tick(void)
{
    char mark[32];
    if (pm_trigger_text("census.mark", mark, sizeof mark))
        pm_log("mark %s", mark);
}

static void on_shot(uint64_t shot)
{
    pm_log("shot 0x%llx player %u in_game %d", (unsigned long long)shot, pm_player(), pm_in_game());
}

static void on_ball_end(void)
{
    pm_log("ball end");
}

static void on_event(unsigned id)     /* item 147: every event the port names */
{
    const char *name = pm_event_name(id);
    pm_log("event %s (0x%02x) player %u in_game %d", name ? name : "?", id, pm_player(), pm_in_game());
}

static const struct pm_mode census = {
    .name = "census",
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(census);
