/* video.c - see video.h */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include "video.h"
#include "art.h"

#define MAX_THREADS 4

enum { SL_EMPTY, SL_DECODING, SL_READY, SL_SKIP };

struct slot {
    long long k;              /* the frame (counted from the start, across loops) */
    int state;
    unsigned char *px;        /* w * h * 4 */
};

struct vid {
    int fd;
    int w, h, n;
    float fps;
    unsigned *off;            /* n + 1 */
    int nthreads;
    pthread_t th[MAX_THREADS];
    int started;
    int R;
    struct slot *slot;
    pthread_mutex_t mu;
    pthread_cond_t cv;
    long long next_k;         /* the next frame a decoder takes */
    long long done_k;         /* the last frame the caller has walked past (-1) */
    long long target;         /* the frame due at the caller's last look */
    long long held;           /* the frame handed out last, whose slot is kept (-1) */
    long long t0;
    int gen;                  /* bumped by a restart: in-flight decodes are thrown away */
    int stop;
    int shown, dropped;
    struct art_image out;
    char err[200];
};

static unsigned rd32(const unsigned char *p)
{
    return (unsigned)p[0] | (unsigned)p[1] << 8 | (unsigned)p[2] << 16 | (unsigned)p[3] << 24;
}

static long long due_k(const struct vid *v, long long now_ms)
{
    long long dt = now_ms - v->t0;
    if (dt < 0) return 0;
    return (long long)((double)dt * v->fps / 1000.0);
}

static void *decoder(void *arg)
{
    struct vid *v = arg;
    unsigned char *buf = NULL;
    size_t cap = 0;
    setpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid), 5);
    pthread_mutex_lock(&v->mu);
    while (!v->stop) {
        long long k = v->next_k;
        struct slot *s = &v->slot[k % v->R];
        int gen, fk, ok = 0, w = 0, h = 0;
        size_t len;
        unsigned char *rgba;
        char why[160] = "";
        if (s->state != SL_EMPTY) {
            pthread_cond_wait(&v->cv, &v->mu);
            continue;
        }
        v->next_k++;
        s->k = k;
        if (k < v->target) {                 /* already late: not worth decoding */
            s->state = SL_SKIP;
            pthread_cond_broadcast(&v->cv);
            continue;
        }
        s->state = SL_DECODING;
        gen = v->gen;
        pthread_mutex_unlock(&v->mu);

        fk = (int)(k % v->n);
        len = v->off[fk + 1] - v->off[fk];
        if (len > cap) {
            unsigned char *nb = realloc(buf, len);
            if (nb) { buf = nb; cap = len; }
        }
        if (len > cap) {
            snprintf(why, sizeof why, "frame %d: no memory for %zu bytes", fk, len);
        } else if (pread(v->fd, buf, len, v->off[fk]) != (ssize_t)len) {
            snprintf(why, sizeof why, "frame %d: cannot be read: %s", fk, strerror(errno));
        } else if (!(rgba = art_jpeg_decode(buf, (int)len, &w, &h, why, sizeof why))) {
            /* why says it */
        } else {
            if (w == v->w && h == v->h) {
                memcpy(s->px, rgba, (size_t)w * h * 4);
                ok = 1;
            } else {
                snprintf(why, sizeof why, "frame %d is %dx%d, the video %dx%d", fk, w, h, v->w, v->h);
            }
            free(rgba);
        }

        pthread_mutex_lock(&v->mu);
        if (gen != v->gen) {
            s->state = SL_EMPTY;            /* a restart came while it decoded */
        } else {
            s->state = ok ? SL_READY : SL_SKIP;
            if (!ok && !v->err[0]) snprintf(v->err, sizeof v->err, "%s", why);
        }
        pthread_cond_broadcast(&v->cv);
    }
    pthread_mutex_unlock(&v->mu);
    free(buf);
    return NULL;
}

static int threads_wanted(void)
{
    const char *forced = getenv("PAD_VID_THREADS");
    long n;
    if (forced && *forced && (n = strtol(forced, NULL, 10)) > 0)
        return n > MAX_THREADS ? MAX_THREADS : (int)n;
    n = sysconf(_SC_NPROCESSORS_ONLN);
    if (n < 1) n = 1;
    return n > MAX_THREADS ? MAX_THREADS : (int)n;
}

struct vid *vid_open(const char *path, int max_w, int max_h, long long now_ms,
                     char *err, int errlen)
{
    unsigned char hd[VID_HEADER];
    off_t fsize;
    ssize_t got;
    struct vid *v;
    int k, fd = open(path, O_RDONLY | O_CLOEXEC);
    unsigned fps1000;
    if (fd < 0) {
        snprintf(err, (size_t)errlen, "%s: %s", path, strerror(errno));
        return NULL;
    }
    fsize = lseek(fd, 0, SEEK_END);
    got = pread(fd, hd, sizeof hd, 0);
    if (fsize < 0 || got < 0) {
        snprintf(err, (size_t)errlen, "%s: %s", path, strerror(errno));
        close(fd);
        return NULL;
    }
    if (got != (ssize_t)sizeof hd || memcmp(hd, VID_MAGIC, 8)) {
        snprintf(err, (size_t)errlen, "%s is not a test video (.padv)", path);
        close(fd);
        return NULL;
    }
    v = calloc(1, sizeof *v);
    if (!v) { close(fd); snprintf(err, (size_t)errlen, "no memory"); return NULL; }
    v->fd = fd;
    v->w = (int)rd32(hd + 8);
    v->h = (int)rd32(hd + 12);
    fps1000 = rd32(hd + 16);
    v->n = (int)rd32(hd + 20);
    v->fps = fps1000 / 1000.0f;
    if (v->w <= 0 || v->h <= 0 || v->w > max_w || v->h > max_h) {
        snprintf(err, (size_t)errlen, "the video is %dx%d, the screen %dx%d", v->w, v->h, max_w, max_h);
        goto bad;
    }
    if (v->n <= 0 || v->n > VID_MAX_FRAMES || fps1000 < 1000 || fps1000 > 120000) {
        snprintf(err, (size_t)errlen, "the video says %d frames at %.3f fps", v->n, v->fps);
        goto bad;
    }
    v->off = malloc(((size_t)v->n + 1) * 4);
    if (!v->off) { snprintf(err, (size_t)errlen, "no memory"); goto bad; }
    {
        size_t ib = ((size_t)v->n + 1) * 4;
        unsigned char *raw = malloc(ib);
        if (!raw || pread(fd, raw, ib, VID_HEADER) != (ssize_t)ib) {
            free(raw);
            snprintf(err, (size_t)errlen, "the video's frame index cannot be read");
            goto bad;
        }
        for (k = 0; k <= v->n; k++) v->off[k] = rd32(raw + 4 * k);
        free(raw);
        if (v->off[0] < VID_HEADER + ib || (off_t)v->off[v->n] > fsize) {
            snprintf(err, (size_t)errlen, "the video's frame index points outside the file");
            goto bad;
        }
        for (k = 0; k < v->n; k++)
            if (v->off[k + 1] <= v->off[k]) {
                snprintf(err, (size_t)errlen, "the video's frame %d is empty", k);
                goto bad;
            }
    }
    v->nthreads = threads_wanted();
    v->R = 2 * v->nthreads + 2;
    v->slot = calloc((size_t)v->R, sizeof *v->slot);
    if (!v->slot) { snprintf(err, (size_t)errlen, "no memory"); goto bad; }
    for (k = 0; k < v->R; k++) {
        v->slot[k].px = malloc((size_t)v->w * v->h * 4);
        if (!v->slot[k].px) {
            snprintf(err, (size_t)errlen, "no memory for %d frames of %dx%d", v->R, v->w, v->h);
            goto bad;
        }
    }
    pthread_mutex_init(&v->mu, NULL);
    pthread_cond_init(&v->cv, NULL);
    v->done_k = -1;
    v->held = -1;
    v->t0 = now_ms;
    v->started = 0;
    for (k = 0; k < v->nthreads; k++) {
        if (pthread_create(&v->th[k], NULL, decoder, v)) break;
        v->started++;
    }
    if (!v->started) {
        snprintf(err, (size_t)errlen, "the decoder thread cannot start");
        pthread_mutex_destroy(&v->mu);
        pthread_cond_destroy(&v->cv);
        goto bad;
    }
    v->nthreads = v->started;
    return v;
bad:
    if (v->slot) {
        for (k = 0; k < v->R; k++) free(v->slot[k].px);
        free(v->slot);
    }
    free(v->off);
    close(fd);
    free(v);
    return NULL;
}

const struct art_image *vid_frame(struct vid *v, long long now_ms, int *k)
{
    long long target;
    int fresh = 0, released = 0;
    pthread_mutex_lock(&v->mu);
    target = due_k(v, now_ms);
    v->target = target;
    for (;;) {
        long long nk = v->done_k + 1;
        struct slot *s = &v->slot[nk % v->R];
        if (nk > target || s->k != nk || (s->state != SL_READY && s->state != SL_SKIP)) break;
        if (s->state == SL_READY) {
            if (v->held >= 0) {
                v->slot[v->held % v->R].state = SL_EMPTY;
                if (fresh) v->dropped++;      /* overtaken before it was shown */
            }
            v->held = nk;
            fresh = 1;
        } else {
            s->state = SL_EMPTY;
            v->dropped++;
        }
        released = 1;
        v->done_k = nk;
    }
    if (released) pthread_cond_broadcast(&v->cv);
    if (fresh) {
        v->shown++;
        v->out.w = v->w;
        v->out.h = v->h;
        v->out.rgba = v->slot[v->held % v->R].px;
        if (k) *k = (int)(v->held % v->n);
    }
    pthread_mutex_unlock(&v->mu);
    return fresh ? &v->out : NULL;
}

const struct art_image *vid_current(struct vid *v)
{
    return v->held >= 0 ? &v->out : NULL;
}

void vid_restart(struct vid *v, long long now_ms)
{
    int i;
    pthread_mutex_lock(&v->mu);
    v->gen++;
    for (i = 0; i < v->R; i++)
        if (v->slot[i].state != SL_DECODING) v->slot[i].state = SL_EMPTY;
        else v->slot[i].k = -1;           /* never mistaken for a frame of the new start */
    v->next_k = 0;
    v->done_k = -1;
    v->held = -1;
    v->target = 0;
    v->t0 = now_ms;
    v->shown = v->dropped = 0;
    pthread_cond_broadcast(&v->cv);
    pthread_mutex_unlock(&v->mu);
}

int vid_frames(const struct vid *v) { return v->n; }
float vid_fps(const struct vid *v) { return v->fps; }
int vid_threads(const struct vid *v) { return v->nthreads; }

int vid_loops(const struct vid *v)
{
    long long d = v->done_k;
    return d < 0 ? 0 : (int)(d / v->n);
}

void vid_stats(const struct vid *v, int *shown, int *dropped)
{
    if (shown) *shown = v->shown;
    if (dropped) *dropped = v->dropped;
}

const char *vid_error(const struct vid *v)
{
    return v->err;
}

void vid_close(struct vid *v)
{
    int k;
    if (!v) return;
    pthread_mutex_lock(&v->mu);
    v->stop = 1;
    pthread_cond_broadcast(&v->cv);
    pthread_mutex_unlock(&v->mu);
    for (k = 0; k < v->started; k++) pthread_join(v->th[k], NULL);
    pthread_mutex_destroy(&v->mu);
    pthread_cond_destroy(&v->cv);
    for (k = 0; k < v->R; k++) free(v->slot[k].px);
    free(v->slot);
    free(v->off);
    close(v->fd);
    free(v);
}
