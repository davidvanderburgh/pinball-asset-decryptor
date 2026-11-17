// MODE_NAME - a JJP custom mode in C++ (PAD-1384). Its settings (name, start,
// scoring shots, seconds, sounds, lamps, screen) are in its .mode file - the
// Modes tab's Settings page; its own rules are here, written against
// jjp_mode.h (the Modes tab's "C++ API" button opens it).
//
// This one: each scoring shot scores the form's points, and the code adds a
// growing bonus on top (250,000 more for every shot made this run) and asks
// for 10 more seconds at the fifth shot. Change anything; Check builds it.
#include "jjp_mode.h"

static long long bonus;
static bool extended;

static void start()
{
    bonus = 0;
    extended = false;
    jm_title("MODE_TITLE");
    jm_log("started with %d s on the clock", jm_seconds_left());
}

// After the form scored one of its scoring shots
static void scored(const char *sw)
{
    bonus += 250000;
    jm_score(bonus);
    jm_log("%s: bonus %lld, mode total %lld", sw, bonus, jm_total());
    if (jm_hits() >= 5 && !extended) {
        extended = true;
        jm_add_seconds(10);
    }
}

static void end(const char *why)
{
    jm_log("over (%s): %d shots, %lld points", why, jm_hits(), jm_total());
}

JM_REGISTER({ .api = JM_API, .start = start, .scored = scored, .end = end });
