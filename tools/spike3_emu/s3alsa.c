/* s3alsa.c - the Spike 3 game's sound cards, faked (PAD-1090, stage 4).
 *
 * LD_PRELOAD (aarch64) into the card's own game, beside s3kms.so. Under
 * qemu-user in the chroot there is no ALSA card, so snd_pcm_open fails, the
 * game keeps the NULL handle and asserts in snd_pcm_prepare (pcm.c:1239) a
 * few seconds into the boot. The game imports 18 PCM calls and no mixer
 * (pokemon_le 0.82.0); those are answered here, for every card name it asks
 * for, with a card that accepts whatever format it sets.
 *
 * snd_pcm_writei is PACED to the wall clock, as a real card's DMA would pace
 * it: a blocking write waits until no more than one buffer is queued ahead,
 * a non-blocking one answers -EAGAIN instead. Without that the audio thread
 * would spin as fast as qemu can run it and starve the game.
 *
 * The samples are dropped: rig runs are muted. PAD_S3_AUDIO_OUT=<path> writes
 * each card's raw PCM to <path>.<card> for a listen afterwards.
 * [s3alsa] lines go to stderr.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

struct params { unsigned rate, channels; int format, access;
                unsigned long period, buffer; };

struct pcm {
    char name[64];
    struct params p;
    int nonblock, fd;
    double t0;                    /* wall time of the first frame since prepare */
    unsigned long long frames;    /* frames written since then */
};

static double wall(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

/* bytes per sample for the formats a game would set (snd_pcm_format_t) */
static int sample_bytes(int f)
{
    switch (f) {
    case 0: case 1: return 1;                    /* S8, U8 */
    case 2: case 3: case 4: case 5: return 2;    /* S16/U16 LE/BE */
    default: return 4;                           /* S24/S32/FLOAT */
    }
}

static void defaults(struct params *p)
{
    p->rate = 48000; p->channels = 2; p->format = 2; p->access = 3;
    p->period = 1024; p->buffer = 4096;
}

int snd_pcm_open(void **pcmp, const char *name, int stream, int mode)
{
    struct pcm *c = calloc(1, sizeof(*c));
    const char *out = getenv("PAD_S3_AUDIO_OUT");
    if (!c)
        return -ENOMEM;
    snprintf(c->name, sizeof(c->name), "%s", name ? name : "default");
    defaults(&c->p);
    c->nonblock = (mode & 1) != 0;    /* SND_PCM_NONBLOCK */
    c->fd = -1;
    if (out && *out) {
        char path[512];
        snprintf(path, sizeof(path), "%s.%s", out, c->name);
        c->fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    }
    fprintf(stderr, "[s3alsa] open '%s' stream %d mode %d\n", c->name, stream, mode);
    *pcmp = c;
    return 0;
}

int snd_pcm_close(void *pcm)
{
    struct pcm *c = pcm;
    if (c) {
        if (c->fd >= 0)
            close(c->fd);
        free(c);
    }
    return 0;
}

int snd_pcm_prepare(void *pcm)
{
    struct pcm *c = pcm;
    if (!c)
        return -EBADFD;
    c->frames = 0;
    c->t0 = 0;
    return 0;
}

int snd_pcm_drain(void *pcm) { (void)pcm; return 0; }

int snd_pcm_nonblock(void *pcm, int on)
{
    struct pcm *c = pcm;
    if (c)
        c->nonblock = on != 0;
    return 0;
}

/* hw params: a struct of ours, copied into the pcm by snd_pcm_hw_params */
unsigned long snd_pcm_hw_params_sizeof(void) { return sizeof(struct params) + 64; }

int snd_pcm_hw_params_any(void *pcm, void *p)
{
    (void)pcm;
    defaults(p);
    return 0;
}

int snd_pcm_hw_params(void *pcm, void *p)
{
    struct pcm *c = pcm;
    if (!c)
        return -EBADFD;
    c->p = *(struct params *)p;
    fprintf(stderr, "[s3alsa] '%s': %u Hz, %u ch, format %d, period %lu, buffer %lu\n",
            c->name, c->p.rate, c->p.channels, c->p.format, c->p.period, c->p.buffer);
    return 0;
}

int snd_pcm_hw_params_set_access(void *pcm, void *p, int a)
{ (void)pcm; ((struct params *)p)->access = a; return 0; }
int snd_pcm_hw_params_set_format(void *pcm, void *p, int f)
{ (void)pcm; ((struct params *)p)->format = f; return 0; }
int snd_pcm_hw_params_set_channels(void *pcm, void *p, unsigned ch)
{ (void)pcm; ((struct params *)p)->channels = ch ? ch : 2; return 0; }
int snd_pcm_hw_params_set_rate(void *pcm, void *p, unsigned r, int dir)
{ (void)pcm; (void)dir; ((struct params *)p)->rate = r ? r : 48000; return 0; }

int snd_pcm_hw_params_set_rate_near(void *pcm, void *p, unsigned *r, int *dir)
{
    (void)pcm;
    if (r && *r)
        ((struct params *)p)->rate = *r;
    if (dir)
        *dir = 0;
    return 0;
}

int snd_pcm_hw_params_set_period_size(void *pcm, void *p, unsigned long s, int dir)
{ (void)pcm; (void)dir; if (s) ((struct params *)p)->period = s; return 0; }
int snd_pcm_hw_params_set_buffer_size(void *pcm, void *p, unsigned long s)
{ (void)pcm; if (s) ((struct params *)p)->buffer = s; return 0; }

int snd_pcm_hw_params_get_channels(const void *p, unsigned *v)
{ *v = ((const struct params *)p)->channels; return 0; }

int snd_pcm_hw_params_get_rate(const void *p, unsigned *v, int *dir)
{
    *v = ((const struct params *)p)->rate;
    if (dir)
        *dir = 0;
    return 0;
}

long snd_pcm_writei(void *pcm, const void *buf, unsigned long frames)
{
    struct pcm *c = pcm;
    double now, played, ahead, wait;
    if (!c)
        return -EBADFD;
    now = wall();
    if (c->t0 == 0)
        c->t0 = now;
    played = (now - c->t0) * c->p.rate;           /* frames the "DMA" has taken */
    if (played > c->frames)                       /* an underrun: start over now */
        c->t0 = now - (double)c->frames / c->p.rate, played = c->frames;
    ahead = c->frames + frames - played;          /* queued after this write */
    if (ahead > c->p.buffer) {
        wait = (ahead - c->p.buffer) / c->p.rate;
        if (c->nonblock)
            return -EAGAIN;
        struct timespec ts = { (time_t)wait, (long)((wait - (time_t)wait) * 1e9) };
        nanosleep(&ts, NULL);
    }
    if (c->fd >= 0)
        (void)!write(c->fd, buf, frames * c->p.channels * sample_bytes(c->p.format));
    c->frames += frames;
    return (long)frames;
}
