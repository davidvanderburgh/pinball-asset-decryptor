/* idle_test_mode.c - a rig instrument for inactivity pausing the game's timers (PAD-1022), never a card's mode.
 *
 * Trigger file in /dump (read twice a second):
 *   idle.start "<procs> <song_now> <positions> <song> <start> <proc> [<song> <start> <proc> ...]"   (hex)
 *       the build's own addresses: the game's process list (the first at *<procs>, the next at +0x84, its number the
 *       u16 at +0), the song tracker's words (<song_now>: [0] the song, [2] where the voice is) and the song table
 *       (<positions>: [song * 4 + player - 1]); then one triple per mission: its song, its start function, its timer
 *       process's number. On Guardians the ball's song is picked at the plunge and a mission's clock follows its own
 *       song only while that song plays, so the mission started is the one whose song is playing: its start is called
 *       with (0, 0) on the game's tick. Then once a second it logs the clock as the game keeps it (the timer
 *       process's seconds byte, +0xa8) beside the song and the table.
 * The runtime's "inactivity:" lines say when it held the clocks; this says what the clock did meanwhile. */
#include "pad_mode.h"

#define MISSIONS 16
static unsigned ticks, proc_no, procs, song_now, positions, logging;
static unsigned mission[MISSIONS][3], missions;

static unsigned hex(const char **s)
{
    unsigned v = 0;
    while (**s == ' ') (*s)++;
    if ((*s)[0] == '0' && ((*s)[1] == 'x' || (*s)[1] == 'X')) *s += 2;
    for (;; (*s)++) {
        char c = **s;
        if (c >= '0' && c <= '9') v = v * 16 + (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f') v = v * 16 + (unsigned)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') v = v * 16 + (unsigned)(c - 'A' + 10);
        else return v;
    }
}

static unsigned find_proc(void)
{
    unsigned p = procs ? *(const unsigned *)(unsigned long)procs : 0, n = 0;
    for (; p && n < 400; p = *(const unsigned *)(unsigned long)(p + 0x84), n++)
        if (*(const unsigned short *)(unsigned long)p == proc_no) return p;
    return 0;
}

static unsigned song_playing(void)
{
    return song_now ? ((const unsigned *)(unsigned long)song_now)[0] : 0;
}

static void on_tick(void)
{
    char t[256];
    const char *s = t;
    unsigned p, song, at, held, player, k;
    if (++ticks % 30 == 0 && pm_trigger_text("idle.start", t, sizeof t)) {
        procs = hex(&s);
        song_now = hex(&s);
        positions = hex(&s);
        for (missions = 0; missions < MISSIONS && *s; missions++) {
            mission[missions][0] = hex(&s);
            mission[missions][1] = hex(&s);
            mission[missions][2] = hex(&s);
            if (!mission[missions][1]) break;
        }
        song = song_playing();
        for (k = 0; k < missions && mission[k][0] != song; k++) {}
        pm_log("idle test: in game %d, player %u, song %u playing - %s", pm_in_game(), pm_player(), song,
               k < missions ? "its mission starts" : "no mission of this song");
        if (k < missions && pm_in_game()) {
            proc_no = mission[k][2];
            pm_log("idle test: calling 0x%08x (0, 0), its timer process 0x%x", mission[k][1], proc_no);
            ((void (*)(unsigned, unsigned))(unsigned long)mission[k][1])(0, 0);
            logging = 1;
        }
    }
    if (!logging || ticks % 60) return;
    p = find_proc();
    song = song_playing();
    at = song_now ? ((const unsigned *)(unsigned long)song_now)[2] : 0;
    player = pm_player();
    held = song && song <= 20 && player >= 1 && player <= 4 && positions
               ? ((const unsigned *)(unsigned long)positions)[song * 4 + player - 1] : 0;
    pm_log("idle test: clock %s%u s, song %u at %u.%02u s, the table holds %u.%02u s", p ? "" : "(no timer) ",
           p ? *(const unsigned char *)(unsigned long)(p + 0xa8) : 0, song, at / 44100, at % 44100 * 100 / 44100,
           held / 44100, held % 44100 * 100 / 44100);
}

static const struct pm_mode idle_test = { .name = "idle_test", .tick = on_tick };
PM_REGISTER(idle_test);
