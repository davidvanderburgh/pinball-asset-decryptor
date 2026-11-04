/* spksw.c - the cabinet buttons of a Spooky Pinball machine (Beetlejuice,
 * Scooby-Doo, Texas Chainsaw, Evil Dead, Looney Tunes on the Warden board;
 * Halloween and Ultraman on the Pinotaur), read off the playfield board's
 * USB serial port for the boot menu (PAD-980, tools/spooky_emu/MULTIBOOT.md).
 *
 *     spksw [--dev PATH] [--board warden|pinotaur] [--period MS] NAME=[!]SW ...
 *
 * NAME is what to print (L, R, S ...); SW is the board's switch number (the
 * cabinet rows of tools/spooky_emu/spktitles.py: Warden L=86 R=80 S=87,
 * Pinotaur L=81 R=80 S=87); a leading ! inverts it.  Printed on stdout, one
 * line each - dpprocsw's lines, so the menu reads them the same way
 * (--input pipe, input_pipe.c):
 *
 *     ready            the board answered; the levels below are from now on
 *     sw NAME 1|0      NAME is pressed / released; every NAME once after
 *                      ready, then on every change
 *     wait <why>       no board yet (retried every half second, said once)
 *
 * It exits when the menu closes the pipe (a write fails).
 *
 * WHY NOT INSIDE THE MENU.  It could be: the board is a plain tty and this
 * needs no library.  Kept apart so the menu stays the one static X11 build
 * the Big Lebowski already proved (input_pipe), and so the launcher can kill
 * the reader - and with it the open port - before the game opens the board.
 *
 * WHAT IS WRITTEN TO THE BOARD is only "what is switch n" - Warden
 * get_switch_state ('>' 152 n), Pinotaur ('<' 0x58 0x83 n) - three
 * switches every period.  Nothing is configured, no coil and no power is
 * ever enabled.  Both boards push switch changes too (Warden '<' 1|0 n;
 * Pinotaur '>' 0x59 [0x80|]n once a host has set its report type); those are
 * taken as well.
 *
 * PRESSED = ACTIVE.  The flippers and START are normally-open buttons; a
 * board that has not been told which switches are inverted reports them as
 * they are (the Pinotaur always reports raw levels), so active is pressed.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

#define MAXSW 8

static const char *names[MAXSW];
static int sws[MAXSW], inv[MAXSW], level[MAXSW], seen[MAXSW];
static int nsw;
static int pinotaur;

static void say(const char *fmt, const char *a, int b)
{
    if (printf(fmt, a, b) < 0 || fflush(stdout) == EOF) exit(0);
}

static void set_level(int sw, int on)
{
    int k;
    for (k = 0; k < nsw; k++) {
        int v;
        if (sws[k] != sw) continue;
        v = (on ? 1 : 0) ^ inv[k];
        if (seen[k] && level[k] == v) continue;
        seen[k] = 1;
        level[k] = v;
        say("sw %s %d\n", names[k], v);
    }
}

static int open_board(const char *dev)
{
    struct termios t;
    int fd = open(dev, O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd < 0) return -1;
    if (tcgetattr(fd, &t) == 0) {
        cfmakeraw(&t);
        cfsetispeed(&t, B115200);
        cfsetospeed(&t, B115200);
        t.c_cflag |= CLOCAL | CREAD;
        tcsetattr(fd, TCSANOW, &t);       /* a pty takes it too; a failure is harmless */
    }
    tcflush(fd, TCIOFLUSH);
    return fd;
}

static void ask(int fd)
{
    unsigned char m[4 * MAXSW];
    int k, n = 0;
    for (k = 0; k < nsw; k++) {
        if (pinotaur) { m[n++] = 0x3C; m[n++] = 0x58; m[n++] = 0x83; }
        else { m[n++] = 0x3E; m[n++] = 152; }
        m[n++] = (unsigned char)sws[k];
    }
    if (write(fd, m, (size_t)n) < 0 && errno != EAGAIN) { /* the read side notices */ }
}

/* Parse what the board said; returns the bytes left over (a message cut in
 * two).  Anything this does not know is skipped a byte at a time until the
 * next start byte: the menu only needs switches, and a reply to another
 * host's question cannot be in flight - no other host is running. */
static int parse(unsigned char *b, int n, int *ready)
{
    int i = 0;
    while (i < n) {
        if (!pinotaur && b[i] == 0x3C) {
            if (i + 1 >= n) break;
            if (b[i + 1] == 0x01 || b[i + 1] == 0x00) {
                if (i + 2 >= n) break;
                set_level(b[i + 2], b[i + 1]);
                i += 3;
                continue;
            }
            if (b[i + 1] == 152) {
                if (i + 3 >= n) break;
                *ready = 1;
                set_level(b[i + 2], b[i + 3]);
                i += 4;
                continue;
            }
        } else if (pinotaur && b[i] == 0x3E) {
            if (i + 1 >= n) break;
            if (b[i + 1] == 0x58) {
                if (i + 3 >= n) break;
                *ready = 1;
                set_level(b[i + 2], b[i + 3]);
                i += 4;
                continue;
            }
            if (b[i + 1] == 0x59) {
                if (i + 2 >= n) break;
                if (b[i + 2] != 0x7F) set_level(b[i + 2] & 0x7F, b[i + 2] & 0x80);
                i += 3;
                continue;
            }
        }
        i++;
    }
    if (i < n) memmove(b, b + i, (size_t)(n - i));
    return n - i;
}

static long long now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static int usage(void)
{
    fprintf(stderr, "usage: spksw [--dev PATH] [--board warden|pinotaur] "
                    "[--period MS] NAME=[!]SW ...\n");
    return 2;
}

int main(int argc, char **argv)
{
    const char *dev = NULL;
    int period = 20, i, fd = -1, said_wait = 0, ready = 0, said_ready = 0, rn = 0;
    unsigned char rx[512];
    long long next_ask = 0, next_open = 0, next_beat = 0;

    signal(SIGPIPE, SIG_DFL);
    for (i = 1; i < argc; i++) {
        char *eq;
        if (!strcmp(argv[i], "--dev") && i + 1 < argc) dev = argv[++i];
        else if (!strcmp(argv[i], "--board") && i + 1 < argc) {
            i++;
            if (!strcmp(argv[i], "pinotaur")) pinotaur = 1;
            else if (strcmp(argv[i], "warden")) return usage();
        } else if (!strcmp(argv[i], "--period") && i + 1 < argc) {
            period = atoi(argv[++i]);
            if (period < 5) period = 5;
        } else if ((eq = strchr(argv[i], '=')) && nsw < MAXSW && eq > argv[i]) {
            char *v = eq + 1, *end;
            long n;
            *eq = 0;
            if (*v == '!') { inv[nsw] = 1; v++; }
            n = strtol(v, &end, 10);
            if (end == v || *end || n < 0 || n > 127) return usage();
            names[nsw] = argv[i];
            sws[nsw++] = (int)n;
        } else return usage();
    }
    if (!nsw) return usage();
    if (!dev) dev = pinotaur ? "/dev/pinheck" : "/dev/WARDEN";

    for (;;) {
        long long t = now_ms();
        if (fd < 0) {
            if (t >= next_open) {
                fd = open_board(dev);
                if (fd < 0) {
                    if (!said_wait) {
                        printf("wait no board at %s (%s)\n", dev, strerror(errno));
                        if (fflush(stdout) == EOF) return 0;
                        said_wait = 1;
                    }
                    next_open = t + 500;
                }
            }
            if (fd < 0) { usleep(50 * 1000); continue; }
        }
        if (t >= next_ask) {
            ask(fd);
            next_ask = t + period;
        }
        {
            ssize_t r = read(fd, rx + rn, sizeof rx - (size_t)rn);
            if (r > 0) {
                rn = parse(rx, rn + (int)r, &ready);
                if (rn >= (int)sizeof rx) rn = 0;
                if (ready && !said_ready) {
                    int k;
                    said_ready = 1;
                    say("%sready\n", "", 0);
                    /* every NAME once after ready: the ones the first replies
                     * have not named yet start released */
                    for (k = 0; k < nsw; k++)
                        if (!seen[k]) { seen[k] = 1; level[k] = 0; say("sw %s %d\n", names[k], 0); }
                }
            } else if (r == 0 || (r < 0 && errno != EAGAIN && errno != EINTR)) {
                close(fd);              /* unplugged: open it again */
                fd = -1;
                rn = 0;
                continue;
            }
        }
        /* an empty line every 5 s, which the menu ignores, so a closed pipe
         * ends this even while no button moves */
        if (said_ready && t >= next_beat) {
            say("%s\n", "", 0);
            next_beat = t + 5000;
        }
        usleep(5 * 1000);
    }
}
