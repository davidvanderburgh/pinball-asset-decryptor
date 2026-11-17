/* spare_sweep_mode.c - a rig instrument for the spare inputs and outputs on every build (PAD-826), never a card's mode.
 *
 * It finds its own: once the switch struct checks out (pm_spare_switch stops saying -1 everywhere), the input is the
 * first spare bit from 8 up on the board with the most of the game's switches, the output the first spare one on the
 * lowest driver board. It logs both ("sweep: input N:B output N:O") and takes the input as a shot. A close of it
 * begins the mode and pulses the output 200 for 30 ms. spare_sweep_job.sh reads the line, flips the input through
 * /dump/spare_in and looks for the shot and the board's [coildrive] line. */
#include "pad_mode.h"

static unsigned ticks, in_node, in_bit, out_node, out_no, closes, off_at;
static unsigned char held[32];   /* PAD-1329: the output held per board on the second close (0xff none) */
static int chosen;
static uint64_t mask;

static void choose(void)
{
    unsigned n, b, best = 0, used, o;
    int any = 0;
    in_node = 99;
    for (n = 0; n < 32; n++) {
        used = 0;
        for (b = 0; b < 64; b++) {
            int s = pm_spare_switch(n, b);
            if (s >= 0) any = 1;
            else used++;
        }
        if (used < 64 && used > best) best = used, in_node = n;
    }
    if (!any) return;                       /* the struct has not checked out (yet) */
    for (b = 8; b < 64 && in_node < 32; b++)
        if (pm_spare_switch(in_node, b) >= 0) { in_bit = b; break; }
    out_node = 99;
    for (n = 0; n < 32 && out_node == 99; n++)
        for (o = 0; o <= 8; o++)
            if (pm_spare_output(n, o)) { out_node = n; out_no = o; break; }
    chosen = 1;
    mask = in_node < 32 ? pm_spare_shot(in_node, in_bit, "Sweep spare", 0) : 0;
    pm_log("sweep: input %u:%u output %u:%u (the input's board has %u of the game's switches; shot 0x%llx)", in_node,
           in_bit, out_node, out_no, best, (unsigned long long)mask);
}

static void on_shot(uint64_t shot)
{
    if (!mask || !(shot & mask)) return;
    if (!pm_running() && !pm_begin()) { pm_log("sweep: could not begin"); return; }
    {   /* PAD-1329: the first spare output of EVERY driver board (chosen now: the game builds its coil records late
         * on some builds), so the bus trace shows which boards take a frame - a CPU board's outputs are no node's */
        unsigned n, o;
        for (n = 0; n < 32; n++)
            for (o = 0; o <= 8; o++)
                if (pm_spare_output(n, o)) {
                    if (closes == 0) pm_log("sweep: pulse %u:%u -> %d", n, o, pm_spare_pulse(n, o, 200, 30));
                    else if (pm_spare_drive(n, o, 200, 30, 60, 3000)) {   /* held, then let go early: the OFF */
                        pm_log("sweep: hold %u:%u for 3 s, let go in 1 s", n, o);
                        held[n] = (unsigned char)(o + 1);
                        off_at = ticks + 60;
                    }
                    break;
                }
        closes++;
    }
}

static void on_tick(void)
{
    if (off_at && ticks + 1 >= off_at) {
        unsigned n;
        for (n = 0; n < 32; n++)
            if (held[n]) { pm_spare_off(n, held[n] - 1u); pm_log("sweep: let go %u:%u", n, held[n] - 1u); held[n] = 0; }
        off_at = 0;
    }
    if (++ticks % 30 || chosen) return;
    if (pm_can(PM_CAN_SPARE_SWITCHES) || pm_can(PM_CAN_SPARE_COILS)) choose();
    if (!chosen && ticks == 60 * 60) pm_log("sweep: nothing chosen in 60 s (can %d %d)", pm_can(PM_CAN_SPARE_SWITCHES),
                                            pm_can(PM_CAN_SPARE_COILS));
}

static const struct pm_mode spare_sweep = {
    .name = "SPARE SWEEP",
    .tick = on_tick,
    .shot = on_shot,
};
PM_REGISTER(spare_sweep);
