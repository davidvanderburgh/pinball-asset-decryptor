/* input_pipe.c - the menu's buttons as lines on standard input (--input
 * pipe): a Dutch Pinball machine (The Big Lebowski, PAD-853), whose buttons
 * dpprocsw reads off the P3-ROC through the game's own libpinproc - a
 * library this static program cannot load.  The boot hook runs
 *
 *     dpprocsw L=SD67 R=SD65 S=SD68 | dpselect --input pipe ...
 *
 * and these are the lines (dpprocsw.c):
 *
 *     sw L|R|S 1|0     LEFT / RIGHT / START closed (pressed) / open
 *     ready            the board answered          (logged)
 *     wait <why>       no board yet                (logged)
 *
 * Anything else is ignored.  The end of the pipe (the helper died, or no
 * board library) is logged once and leaves no buttons: the countdown boots
 * the highlighted image, the rule every backend follows.
 *
 * The lines are levels, not presses: they go through input_sample like
 * every backend's, and the shared debouncer makes the presses.  A level is
 * held until the next line changes it, so it is fed every poll.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include "input.h"
#include "log.h"

struct pipe_in {
    struct input base;
    int fd;
    char rx[512];
    int rxn;
    int level[3];             /* L, R, S: 1 pressed */
    long long lines, changes;
};

static const int EV_OF[3] = { EV_LEFT, EV_RIGHT, EV_START };

static void on_line(struct pipe_in *p, const char *l)
{
    p->lines++;
    if (!strncmp(l, "sw ", 3) && l[3] && l[4] == ' ' && (l[5] == '0' || l[5] == '1')) {
        int k = l[3] == 'L' ? 0 : l[3] == 'R' ? 1 : l[3] == 'S' ? 2 : -1;
        if (k >= 0 && p->level[k] != l[5] - '0') {
            p->level[k] = l[5] - '0';
            p->changes++;
        }
    } else if (!strcmp(l, "ready") || !strncmp(l, "wait", 4)) {
        sel_log("pipe: %s", l);
    }
}

static void pipe_poll(struct input *in, long long now_ms)
{
    struct pipe_in *p = (struct pipe_in *)in;
    int k;
    (void)now_ms;
    while (p->fd >= 0) {
        ssize_t r = read(p->fd, p->rx + p->rxn, sizeof p->rx - 1 - (size_t)p->rxn);
        char *nl;
        if (r < 0 && (errno == EAGAIN || errno == EINTR)) break;
        if (r <= 0) {
            sel_log("pipe: the button reader's pipe ended (%s): no buttons from here on",
                    r < 0 ? strerror(errno) : "end of file");
            close(p->fd);
            p->fd = -1;
            for (k = 0; k < 3; k++) p->level[k] = 0;
            break;
        }
        p->rxn += (int)r;
        p->rx[p->rxn] = 0;
        while ((nl = memchr(p->rx, '\n', (size_t)p->rxn))) {
            int used = (int)(nl - p->rx) + 1;
            *nl = 0;
            if (nl > p->rx && nl[-1] == '\r') nl[-1] = 0;
            on_line(p, p->rx);
            memmove(p->rx, nl + 1, (size_t)(p->rxn - used));
            p->rxn -= used;
        }
        if (p->rxn >= (int)sizeof p->rx - 1) p->rxn = 0;
    }
    for (k = 0; k < 3; k++)
        input_sample(&p->base, KEY_OF(EV_OF[k]), p->level[k]);
}

static void pipe_close(struct input *in)
{
    struct pipe_in *p = (struct pipe_in *)in;
    sel_log("pipe: %lld lines, %lld level changes", p->lines, p->changes);
    if (p->fd >= 0) close(p->fd);
    pthread_mutex_destroy(&p->base.lock);
    free(p);
}

static const struct input_ops pipe_ops = { pipe_poll, pipe_close };

struct input *input_pipe_open(const struct input_cfg *cfg)
{
    struct pipe_in *p = calloc(1, sizeof *p);
    int k;
    (void)cfg;
    if (!p) return NULL;
    input_base_init(&p->base, &pipe_ops);
    p->fd = dup(0);
    if (p->fd >= 0) fcntl(p->fd, F_SETFL, fcntl(p->fd, F_GETFL) | O_NONBLOCK);
    else sel_log("pipe: no standard input: no buttons");
    for (k = 0; k < KEY_COUNT; k++) p->base.present[k] = 0;
    for (k = 0; k < 3; k++) p->base.present[KEY_OF(EV_OF[k])] = 1;
    sel_log("pipe: LEFT, RIGHT and START from the lines on standard input");
    return &p->base;
}
