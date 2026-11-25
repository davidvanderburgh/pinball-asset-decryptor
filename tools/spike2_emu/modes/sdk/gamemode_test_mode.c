/* gamemode_test_mode.c - a rig instrument that makes the game start or stop one of its own modes, as its rules do,
 * never a card's mode (PAD-1555: the place / done / with / stack proofs of a new build; PAD-710's p710test.c and
 * PAD-1537's test path, re-made as one object with mode_file.c).
 *
 * Trigger files in /dump (read twice a second), each holding a game mode number:
 *   gm.start  "<id>"   pm_game_mode_start: the game's START of mode <id> (PAD_TEST_PLAIN_START=1 on plain-C titles)
 *   gm.stop   "<id>"   pm_game_mode_stop: the game's STOP of it, won, for the player up
 * Build: build_mode.sh -o gm.so mode_file.c gamemode_test_mode.c (the mode files run beside it). */
#include "pad_mode.h"

static unsigned ticks;

static unsigned num(const char *s)
{
    unsigned v = 0;
    while (*s >= '0' && *s <= '9') v = v * 10 + (unsigned)(*s++ - '0');
    return v;
}

static void on_tick(void)
{
    char t[16];
    if (++ticks % 30) return;
    if (pm_trigger_text("gm.start", t, sizeof t)) pm_log("gm start %u: %d", num(t), pm_game_mode_start(num(t)));
    if (pm_trigger_text("gm.stop", t, sizeof t)) pm_log("gm stop %u: %d", num(t), pm_game_mode_stop(num(t), 1));
}

static const struct pm_mode gamemode_test = {
    .name = "GM TEST",
    .tick = on_tick,
};
PM_REGISTER(gamemode_test);
