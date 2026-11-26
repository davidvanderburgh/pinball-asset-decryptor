/* padgst.c - the emulator's video bridge for a program that is NOT the game.
 *
 * hwshim.so carries the bridge (gststub.c + gstvid.c) that answers the game's
 * GStreamer calls from the PC's decoder, but hwshim cannot be preloaded into the
 * boot menu: it reads the game's own heap and hooks its device nodes
 * (run_game.sh: "NO LD_PRELOAD, deliberately").  A test card's clip (Simon,
 * 2026-11-22: codeselect/gstclip.c) builds the game's chain - filesrc ! qtdemux !
 * queue ! vpudec ! fakesink - so padgst.so is the same two files with only the
 * two things they borrow from hwshim, given here:
 *
 *   pad_say            the log line (stderr, as hwshim's logger writes it)
 *   pad_real_sleep_us  a wall-clock sleep (the menu has no game clock to warp)
 *
 * Built by build.sh beside hwshim.so; run_game.sh preloads it into the menu of
 * a test card when the video host is up (PAD_VID=1). */

extern long write(int, const void *, unsigned long);
extern int nanosleep(const void *, void *);

void pad_say(const char *s)
{
    unsigned long n = 0;
    while (s[n]) n++;
    write(2, s, n);
}

void pad_real_sleep_us(long long us)
{
    struct { long tv_sec, tv_nsec; } ts;
    if (us <= 0) return;
    ts.tv_sec = (long)(us / 1000000);
    ts.tv_nsec = (long)(us % 1000000) * 1000;
    nanosleep(&ts, 0);
}
