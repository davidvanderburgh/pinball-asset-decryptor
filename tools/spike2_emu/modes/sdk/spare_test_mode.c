/* spare_test_mode.c - a rig instrument for the spare inputs and outputs (PAD-826), never a card's mode.
 *
 * At init it takes the spare input SPARE_IN (node:bit, default 9:24) as a shot. A close of that input begins the
 * mode (when none runs) and pulses the spare output SPARE_OUT (default 9:4) 255 for 40 ms, then 128 for 500 ms.
 * Trigger files in /dump (read twice a second):
 *   spare.pulse  "<node> <out> <power> <ms> [<hold power> <hold ms>]"  begin if need be, then pm_spare_drive
 *   spare.end                                                          pm_end: the runtime must send OFF
 * Every second it logs pm_spare_switch(SPARE_IN). The runtime's "spare" lines and hwshim's [coildrive] lines say
 * what reached the board. */
#include "pad_mode.h"

#define IN_NODE 9u
#define IN_BIT 24u
#define OUT_NODE 9u
#define OUT_NO 4u

static unsigned ticks;
static uint64_t mask;
static int last = -2;

static const char *number(const char *s, unsigned *v)
{
    while (*s == ' ') s++;
    for (*v = 0; *s >= '0' && *s <= '9'; s++) *v = *v * 10 + (unsigned)(*s - '0');
    return s;
}

static void on_shot(uint64_t shot)
{
    if (!mask || !(shot & mask)) return;
    pm_log("spare test: shot %s", pm_shot_name(mask));
    if (!pm_running() && !pm_begin()) { pm_log("spare test: could not begin"); return; }
    pm_log("spare test: pulse %u:%u -> %d", OUT_NODE, OUT_NO, pm_spare_drive(OUT_NODE, OUT_NO, 255, 40, 128, 500));
}

static void on_tick(void)
{
    char t[64];
    int s;
    if (++ticks % 30) return;
    if (!mask && ticks < 60 * 120) mask = pm_spare_shot(IN_NODE, IN_BIT, "Spare 9:24", 0);
    if (pm_trigger_text("spare.pulse", t, sizeof t)) {
        unsigned n, o, p, ms, hp = 0, hms = 0;
        const char *q = number(number(number(number(t, &n), &o), &p), &ms);
        q = number(number(q, &hp), &hms);
        if (!pm_running() && !pm_begin()) pm_log("spare test: could not begin");
        else pm_log("spare test: drive %u:%u %u/%u ms then %u/%u ms -> %d (spare: %d)", n, o, p, ms, hp, hms,
                    pm_spare_drive(n, o, p, ms, hp, hms), pm_spare_output(n, o));
    }
    if (pm_trigger("spare.end")) {
        pm_log("spare test: ending the mode");
        pm_end();
    }
    s = pm_spare_switch(IN_NODE, IN_BIT);
    if (s != last) {
        pm_log("spare test: pm_spare_switch(%u, %u) = %d", IN_NODE, IN_BIT, s);
        last = s;
    }
}

static void on_init(void)
{
    unsigned n, o;
    pm_log("spare test: can switches %d outputs %d", pm_can(PM_CAN_SPARE_SWITCHES), pm_can(PM_CAN_SPARE_COILS));
    for (n = 8; n <= 9; n++)
        for (o = 0; o <= 8; o++)
            pm_log("spare test: output %u:%u spare %d", n, o, pm_spare_output(n, o));
}

static const struct pm_mode spare_test = {
    .name = "SPARE TEST",
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
};
PM_REGISTER(spare_test);
