/* gpmset_mode.c - a rig instrument that sets the game-play mode index of a GamePlayModes build in attract, as the start
 * menu's pick does, never a card's mode (PAD-1555: the challenge-list proof of Metallica 1.05; PAD-619's rig/ch619.c
 * `gpm set`, re-made).
 *
 * Trigger file in /dump (read twice a second): gpm.set "<singleton address> <offset> <index>" (the port's `data
 * game_play_modes`, `value game_play_mode_at`, and the challenge's game-mode index) - the word is written once per
 * file, and logged before and after.
 * Build: build_mode.sh -o gpm.so mode_file.c gpmset_mode.c (the mode files run beside it). */
#include "pad_mode.h"

static unsigned ticks;

static unsigned long word(const char **s)
{
    unsigned long v = 0;
    int hex = 0;
    while (**s == ' ') (*s)++;
    if ((*s)[0] == '0' && ((*s)[1] == 'x' || (*s)[1] == 'X')) { hex = 1; *s += 2; }
    for (;; (*s)++) {
        char c = **s;
        if (c >= '0' && c <= '9') v = v * (hex ? 16 : 10) + (unsigned long)(c - '0');
        else if (hex && c >= 'a' && c <= 'f') v = v * 16 + (unsigned long)(c - 'a' + 10);
        else if (hex && c >= 'A' && c <= 'F') v = v * 16 + (unsigned long)(c - 'A' + 10);
        else break;
    }
    return v;
}

static void on_tick(void)
{
    char t[64];
    const char *s = t;
    unsigned long at, off, idx;
    volatile unsigned *w;
    if (++ticks % 30 || !pm_trigger_text("gpm.set", t, sizeof t)) return;
    at = word(&s); off = word(&s); idx = word(&s);
    if (!at) { pm_log("gpm set: no address in gpm.set"); return; }
    w = (volatile unsigned *)(at + off);
    pm_log("gpm set: the game-play mode at 0x%lx+%lu was %u", at, off, *w);
    *w = (unsigned)idx;
    pm_log("gpm set: now %u (in game %d)", *w, pm_in_game());
}

static const struct pm_mode gpmset = {
    .name = "GPM SET",
    .tick = on_tick,
};
PM_REGISTER(gpmset);
