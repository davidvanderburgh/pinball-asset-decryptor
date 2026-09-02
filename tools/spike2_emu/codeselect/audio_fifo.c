/* audio_fifo.c - the emulator sink: raw s16le 44100 Hz stereo into the rig's
 * audio FIFO (PAD_AUDIO_PLAY = /dump/audio.fifo), the protocol alsastub.c
 * speaks for the game:
 *
 *   1. write '44100 2\n' to the fmt file first (playaudio.sh blocks up to
 *      60 s on that file and only then opens the read end through the relay)
 *   2. open(O_WRONLY|O_NONBLOCK): ENXIO until a reader exists, so retry
 *      every ~100 ms from the loop; F_SETPIPE_SZ 1 MB once open
 *   3. pace to the wall clock, 200 ms ahead; writes in PIPE_BUF-sized
 *      chunks (atomic: all or EAGAIN, so the stereo frames never desync);
 *      EAGAIN = drop and count; EPIPE = the reader went away, reopen
 *   4. silence keeps streaming while nothing plays (padplay's 25 s no-data
 *      watchdog would otherwise restart the player); SIGPIPE is ignored by
 *      main() before the first write
 *
 * THE READER CAN GO AWAY AND NOT COME BACK, and this file cannot fix that,
 * only keep trying and say so. The read end is the rig's padrelay.py, which
 * holds it only while a Windows padplay.py is on its socket; that player is
 * a WSL interop child of whatever wsl.exe session launched the run, and it
 * dies on its first print() after that session exits (measured 2026-09-02:
 * the menu's sound stopped 31 s in, at the player's sixth 5-s report, the
 * moment the launching shell returned; the game's alsastub, same protocol,
 * never got a reader back either). playaudio.sh's restart loop cannot see
 * the death - the interop stub never returns - so nothing reopens the read
 * end. So: EPIPE -> close and retry every OPEN_RETRY_MS exactly as alsastub
 * does (once per second of audio there); while there is no reader, rewrite
 * the fmt file whenever it has vanished (a restarted playaudio.sh removes
 * it and waits 60 s for a new one before it opens the read end); and after
 * NO_READER_LOG_MS without one, log it once, so the run's log names WHEN the
 * sound went instead of only showing a drop count at exit.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include "audio.h"
#include "log.h"

#ifndef F_SETPIPE_SZ
#define F_SETPIPE_SZ 1031
#endif

#define LEAD_MS      200
#define OPEN_RETRY_MS 100
#define MISSING_RETRY_MS 1000
#define FMT_CHECK_MS 1000           /* no reader: is the fmt file still there? */
#define NO_READER_LOG_MS 3000       /* no reader this long: say so, once */
#define CHUNK_FRAMES 1024           /* 4096 bytes = PIPE_BUF: atomic non-blocking writes */
#define PIPE_BYTES   (1 << 20)

struct fifo {
    struct audio_sink base;
    char path[512], fmt[512];
    int fd;
    long long t0, clock, now, next_open, next_fmt_check;
    long long no_reader_since;      /* valid while waiting */
    int waiting;                    /* 1 = space() has seen us without a reader */
    int lost;                       /* 1 = had a reader and lost it (EPIPE) */
    int missing_logged, eagain_logged, err_logged, no_reader_logged;
};

static void fmt_write(struct fifo *f, const char *why)
{
    FILE *fp;
    if (!f->fmt[0]) return;
    fp = fopen(f->fmt, "w");
    if (!fp) { sel_log("audio: cannot write %s: %s", f->fmt, strerror(errno)); return; }
    fprintf(fp, "%d %d\n", AUDIO_RATE, AUDIO_CH);
    fclose(fp);
    sel_log("audio: fmt %s = %d %d%s", f->fmt, AUDIO_RATE, AUDIO_CH, why);
}

/* Called from space() while there is no reader. Two jobs: keep the fmt file
 * in place (a restarted playaudio.sh does rm -f FIFO FMT, mkfifo, then polls
 * up to 60 s for a fresh fmt before it opens the read end; without this it
 * falls back to 48000 Hz and everything plays sharp), and name a long gap
 * once. The first call without a reader starts the clock. */
static void no_reader(struct fifo *f, long long now)
{
    struct stat st;
    if (!f->waiting) {
        f->waiting = 1;
        f->no_reader_since = now;
        f->no_reader_logged = 0;
        f->next_fmt_check = now;
    }
    if (f->fmt[0] && now >= f->next_fmt_check) {
        f->next_fmt_check = now + FMT_CHECK_MS;
        if (stat(f->fmt, &st) < 0 && errno == ENOENT)
            fmt_write(f, " (rewritten: it had been removed)");
    }
    if (!f->no_reader_logged && now - f->no_reader_since >= NO_READER_LOG_MS) {
        f->no_reader_logged = 1;
        sel_log("audio: no fifo reader for %lld s (%s; is the rig's player up? see padaudio.log): dropping until one appears",
                (now - f->no_reader_since) / 1000, f->lost ? "it went away" : "none came");
    }
}

static void try_open(struct fifo *f, long long now)
{
    int fd;
    if (f->fd >= 0 || now < f->next_open) return;
    fd = open(f->path, O_WRONLY | O_NONBLOCK);
    if (fd < 0) {
        if (errno == ENXIO) {
            f->next_open = now + OPEN_RETRY_MS;          /* no reader yet */
        } else {
            if (!f->missing_logged) {
                sel_log("audio: fifo %s: %s (retrying)", f->path, strerror(errno));
                f->missing_logged = 1;
            }
            f->next_open = now + MISSING_RETRY_MS;
        }
        return;
    }
    if (fcntl(fd, F_SETPIPE_SZ, PIPE_BYTES) < 0)
        sel_log("audio: fifo F_SETPIPE_SZ %d: %s (default size kept)", PIPE_BYTES, strerror(errno));
    f->fd = fd;
    f->missing_logged = 0;
    if (f->waiting && f->lost)
        sel_log("audio: fifo %s open again after %lld ms without a reader", f->path, now - f->no_reader_since);
    else
        sel_log("audio: fifo %s open", f->path);
    f->waiting = 0;
    f->lost = 0;
}

static int fifo_space(struct audio_sink *s, long long now)
{
    struct fifo *f = (struct fifo *)s;
    long long due;
    f->now = now;
    if (!f->t0) f->t0 = now;
    try_open(f, now);
    if (f->fd < 0) no_reader(f, now);
    due = (now - f->t0) * AUDIO_RATE / 1000 + (long long)LEAD_MS * AUDIO_RATE / 1000 - f->clock;
    return due > 0 ? (int)due : 0;
}

static int fifo_write(struct audio_sink *s, const short *pcm, int frames)
{
    struct fifo *f = (struct fifo *)s;
    int done = 0;
    f->clock += frames;                     /* time passes whether or not the reader keeps up */
    if (f->fd < 0) return 0;
    while (done < frames) {
        int chunk = frames - done;
        ssize_t n;
        if (chunk > CHUNK_FRAMES) chunk = CHUNK_FRAMES;
        n = write(f->fd, pcm + (size_t)done * 2, (size_t)chunk * 4);
        if (n < 0) {
            if (errno == EAGAIN) {
                if (!f->eagain_logged) {
                    sel_log("audio: fifo full, dropping (the reader is not keeping up)");
                    f->eagain_logged = 1;
                }
            } else if (errno == EPIPE) {
                sel_log("audio: fifo reader went away, reopening");
                close(f->fd);
                f->fd = -1;
                f->next_open = 0;               /* from the next space(): every OPEN_RETRY_MS */
                f->lost = 1;
                f->waiting = 0;                 /* no_reader() restarts its clock */
            } else if (!f->err_logged) {
                sel_log("audio: fifo write: %s", strerror(errno));
                f->err_logged = 1;
            }
            break;
        }
        done += (int)(n / 4);
        if (n != (ssize_t)chunk * 4) break;           /* cannot happen below PIPE_BUF */
    }
    return done;
}

static void fifo_close(struct audio_sink *s)
{
    struct fifo *f = (struct fifo *)s;
    if (f->fd >= 0)
        close(f->fd);
    else if (f->waiting)
        sel_log("audio: fifo closed without a reader (none for the last %lld ms%s)",
                f->now - f->no_reader_since, f->lost ? "; it went away" : "");
    free(f);
}

struct audio_sink *audio_fifo_open(const char *path, const char *fmt_path)
{
    struct fifo *f = calloc(1, sizeof *f);
    if (!f) return NULL;
    f->base.name = "fifo";
    f->base.space = fifo_space;
    f->base.write = fifo_write;
    f->base.close = fifo_close;
    f->base.lead_ms = LEAD_MS;
    f->fd = -1;
    snprintf(f->path, sizeof f->path, "%s", path);
    if (fmt_path && *fmt_path) snprintf(f->fmt, sizeof f->fmt, "%s", fmt_path);
    fmt_write(f, "");
    try_open(f, 0);
    if (f->fd < 0) sel_log("audio: fifo %s waiting for a reader", f->path);
    return &f->base;
}
