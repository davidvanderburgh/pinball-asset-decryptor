/* shot_probe_mode.c - PAD-1290 rig instrument (never a card's mode): logs every shot mask the runtime hands the modes.
 * With a census port (every switch id a bit of its own, s3census.sh) it says which id each switch press reaches. */
#include "pad_mode.h"

static void on_shot(uint64_t s)
{
    pm_log("[probe] shot %08x_%08x", (unsigned)(s >> 32), (unsigned)s);
}

static const struct pm_mode shot_probe = { .name = "shotprobe", .shot = on_shot };
PM_REGISTER(shot_probe);
