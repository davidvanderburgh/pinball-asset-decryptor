/* show_reel_mode.c - PAD-411: the game's own light shows, one per press, to pick from on the machine.
 *
 * In a game, each press of the Action button plays the next of the game's shows (pm_game_show) and puts
 * "LIGHT SHOW" and its number on the game's award screen (a borrowed stock message, restored when the reel
 * ends). A press while a show still plays stops it and plays the next. The reel ends 30 s after the last press, or with the
 * ball. It holds nothing of the game's off: it is a test, not a mode to play.
 * Trigger files in /dump (read twice a second), for the rig:
 *   reel.go    "<n>"  begin (when not running) and play show n
 *   reel.end          end the reel
 * Every show's start, and how long its process lived, is logged. */
#include "pad_mode.h"

#define REEL_IDLE_MS 30000ul
#define REEL_MSG     3242u                 /* Tesla Strike's title, borrowed while the reel runs */

static unsigned ticks, next = 1, playing;
static unsigned long last_press, started;
static uint64_t action;

static unsigned number(const char *s)
{
    unsigned v = 0;
    while (*s >= '0' && *s <= '9') v = v * 10 + (unsigned)(*s++ - '0');
    return v;
}

static void end(const char *why)
{
    if (!pm_running()) return;
    pm_log("reel: ends (%s)", why);
    pm_message_restore(REEL_MSG);
    pm_end();
}

static void play(unsigned n)
{
    if (!pm_running()) {
        if (!pm_begin()) {
            pm_log("reel: could not begin");
            return;
        }
        pm_running_name("SHOW REEL");
        pm_message_set(REEL_MSG, "LIGHT SHOW");
    }
    last_press = pm_ms();
    if (n < 1 || n > (unsigned)pm_game_shows()) n = 1;
    if (pm_game_show((int)n)) {
        playing = n;
        started = pm_ms();
        next = n + 1 > (unsigned)pm_game_shows() ? 1 : n + 1;
        pm_award_screen((unsigned)pm_port_value("award_screen_type", 122), REEL_MSG, n);
        pm_log("reel: LIGHT SHOW %u of %d", n, pm_game_shows());
    }
}

static void on_shot(uint64_t shot)
{
    if (!action) action = pm_shot("Action button");
    if (action && (shot & action) && pm_in_game()) play(next);
}

static void on_tick(void)
{
    char t[16];
    if (playing && !pm_game_show_playing()) {
        pm_log("reel: show %u over after %lu ms", playing, pm_ms() - started);
        playing = 0;
    }
    if (++ticks % 30) return;
    if (pm_trigger_text("reel.go", t, sizeof t)) play(number(t));
    if (pm_trigger("reel.end")) end("trigger file");
    if (pm_running() && !playing && pm_ms() - last_press > REEL_IDLE_MS) end("no press for 30 s");
}

static void on_ball_end(void)
{
    end("the ball ended");
}

static void on_init(void)
{
    pm_log("reel: %d of the game's own light shows (can %d)", pm_game_shows(), pm_can(PM_CAN_GAME_SHOWS));
}

static const struct pm_mode show_reel = {
    .name = "SHOW REEL",
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
};
PM_REGISTER(show_reel);
