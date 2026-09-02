/* audio_alsa.c - the machine sink: the game's own playback device through
 * the rootfs libasound.so.2 (alsa-lib 1.0.28). No headers exist on the box,
 * so every prototype is hand-written (export list checked against
 * readelf --dyn-syms; the game itself uses the same entry points).
 *
 *   snd_lib_error_set_handler(quiet)      alsa-lib's stderr chain stays out of the console log
 *   snd_pcm_open("sysdefault:CARD=sgtl5000main", PLAYBACK, 0)
 *       any failure = 'no alsa' (-19 in the emulator chroot). NEVER the
 *       'null' device: alsa-lib 1.0.28 asserts inside hw_params on it.
 *   snd_pcm_set_params(S16_LE=2, RW_INTERLEAVED=3, 2 ch, 44100, resample 1, 500 ms)
 *   snd_pcm_nonblock(1); avail_update says how much fits; writei in
 *       <= 1764-frame chunks (the game's period); -EPIPE -> snd_pcm_recover
 *   close: nonblock(0), drain, close - BEFORE the choice file is written and
 *       before the EGL teardown, so the game's later open finds hw:0 free.
 *
 * The mixer is untouched unless mixer_volume= is set: then the game's own
 * recipe (function 0x1fa490 of the godzilla_pro ELF) puts
 * 192*(v/63)^0.2 into 'PCM Playback Volume' on ctl backbox and cabinet.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <math.h>
#include "audio.h"
#include "log.h"

typedef struct snd_pcm snd_pcm_t;
typedef struct snd_mixer snd_mixer_t;
typedef struct snd_mixer_elem snd_mixer_elem_t;
typedef struct snd_mixer_selem_id snd_mixer_selem_id_t;
typedef void (*snd_lib_error_handler_t)(const char *file, int line, const char *function,
                                        int err, const char *fmt, ...);

extern int  snd_lib_error_set_handler(snd_lib_error_handler_t);
extern const char *snd_strerror(int);
extern int  snd_pcm_open(snd_pcm_t **, const char *, int stream, int mode);
extern int  snd_pcm_set_params(snd_pcm_t *, int format, int access, unsigned channels,
                               unsigned rate, int soft_resample, unsigned latency_us);
extern int  snd_pcm_nonblock(snd_pcm_t *, int);
extern long snd_pcm_avail_update(snd_pcm_t *);
extern long snd_pcm_writei(snd_pcm_t *, const void *, unsigned long frames);
extern int  snd_pcm_recover(snd_pcm_t *, int err, int silent);
extern int  snd_pcm_drain(snd_pcm_t *);
extern int  snd_pcm_close(snd_pcm_t *);
extern int  snd_mixer_open(snd_mixer_t **, int mode);
extern int  snd_mixer_attach(snd_mixer_t *, const char *name);
extern int  snd_mixer_selem_register(snd_mixer_t *, void *options, void **classp);
extern int  snd_mixer_load(snd_mixer_t *);
extern int  snd_mixer_close(snd_mixer_t *);
extern unsigned long snd_mixer_selem_id_sizeof(void);
extern void snd_mixer_selem_id_set_index(snd_mixer_selem_id_t *, unsigned);
extern void snd_mixer_selem_id_set_name(snd_mixer_selem_id_t *, const char *);
extern snd_mixer_elem_t *snd_mixer_find_selem(snd_mixer_t *, const snd_mixer_selem_id_t *);
extern int  snd_mixer_selem_get_playback_volume_range(snd_mixer_elem_t *, long *, long *);
extern int  snd_mixer_selem_set_playback_volume_all(snd_mixer_elem_t *, long);

#define SND_PCM_STREAM_PLAYBACK      0
#define SND_PCM_FORMAT_S16_LE        2
#define SND_PCM_ACCESS_RW_INTERLEAVED 3
#define ALSA_DEVICE   "sysdefault:CARD=sgtl5000main"
#define LATENCY_US    500000
#define LEAD_MS       500
#define CHUNK_FRAMES  1764          /* the game's period size */

struct alsa {
    struct audio_sink base;
    snd_pcm_t *pcm;
    int err_logged, recovered;
};

static void quiet(const char *file, int line, const char *function, int err, const char *fmt, ...)
{
    (void)file; (void)line; (void)function; (void)err; (void)fmt;
}

static int alsa_space(struct audio_sink *s, long long now)
{
    struct alsa *a = (struct alsa *)s;
    long av;
    (void)now;
    av = snd_pcm_avail_update(a->pcm);
    if (av < 0) {
        int rc = snd_pcm_recover(a->pcm, (int)av, 1);
        if (rc < 0) {
            if (!a->err_logged) { sel_log("audio: alsa recover: %s", snd_strerror(rc)); a->err_logged = 1; }
            return 0;
        }
        a->recovered++;
        av = snd_pcm_avail_update(a->pcm);
        if (av < 0) return 0;
    }
    return av > 0 ? (int)av : 0;
}

static int alsa_write(struct audio_sink *s, const short *pcm, int frames)
{
    struct alsa *a = (struct alsa *)s;
    int done = 0, retries = 0;
    while (done < frames) {
        int chunk = frames - done;
        long rc;
        if (chunk > CHUNK_FRAMES) chunk = CHUNK_FRAMES;
        rc = snd_pcm_writei(a->pcm, pcm + (size_t)done * 2, (unsigned long)chunk);
        if (rc == -EAGAIN) break;                       /* buffer full: the rest waits for the next pump */
        if (rc == -EPIPE || rc == -ESTRPIPE) {
            int r = snd_pcm_recover(a->pcm, (int)rc, 1);
            a->recovered++;
            if (r < 0 || ++retries > 2) {
                if (!a->err_logged) { sel_log("audio: alsa writei: %s", snd_strerror((int)rc)); a->err_logged = 1; }
                break;
            }
            continue;
        }
        if (rc < 0) {
            if (!a->err_logged) { sel_log("audio: alsa writei: %s", snd_strerror((int)rc)); a->err_logged = 1; }
            break;
        }
        done += (int)rc;
        if (rc < chunk) break;
    }
    return done;
}

static void alsa_close(struct audio_sink *s)
{
    struct alsa *a = (struct alsa *)s;
    int rc;
    snd_pcm_nonblock(a->pcm, 0);
    rc = snd_pcm_drain(a->pcm);
    if (rc < 0) sel_log("audio: alsa drain: %s", snd_strerror(rc));
    rc = snd_pcm_close(a->pcm);
    sel_log("audio: alsa closed (%s), %d recover(s)", rc < 0 ? snd_strerror(rc) : "ok", a->recovered);
    free(a);
}

struct audio_sink *audio_alsa_open(char *err, int errlen)
{
    struct alsa *a;
    snd_pcm_t *pcm = NULL;
    int rc;

    snd_lib_error_set_handler(quiet);
    rc = snd_pcm_open(&pcm, ALSA_DEVICE, SND_PCM_STREAM_PLAYBACK, 0);
    if (rc < 0) {
        snprintf(err, errlen, "snd_pcm_open(%s): %s", ALSA_DEVICE, snd_strerror(rc));
        return NULL;
    }
    rc = snd_pcm_set_params(pcm, SND_PCM_FORMAT_S16_LE, SND_PCM_ACCESS_RW_INTERLEAVED,
                            AUDIO_CH, AUDIO_RATE, 1, LATENCY_US);
    if (rc < 0) {
        snprintf(err, errlen, "snd_pcm_set_params: %s", snd_strerror(rc));
        snd_pcm_close(pcm);
        return NULL;
    }
    rc = snd_pcm_nonblock(pcm, 1);
    if (rc < 0) sel_log("audio: alsa nonblock: %s (writes may block briefly)", snd_strerror(rc));
    a = calloc(1, sizeof *a);
    if (!a) { snd_pcm_close(pcm); snprintf(err, errlen, "out of memory"); return NULL; }
    a->base.name = "alsa";
    a->base.space = alsa_space;
    a->base.write = alsa_write;
    a->base.close = alsa_close;
    a->base.lead_ms = LEAD_MS;
    a->pcm = pcm;
    sel_log("audio: alsa %s ok", ALSA_DEVICE);
    return &a->base;
}

static int mixer_set(const char *ctl, int v63)
{
    snd_mixer_t *m = NULL;
    snd_mixer_selem_id_t *id;
    snd_mixer_elem_t *e;
    long lo = 0, hi = 0, value;
    int rc;

    rc = snd_mixer_open(&m, 0);
    if (rc < 0) { sel_log("audio: mixer %s: open: %s", ctl, snd_strerror(rc)); return -1; }
    rc = snd_mixer_attach(m, ctl);
    if (rc < 0) { sel_log("audio: mixer %s: attach: %s", ctl, snd_strerror(rc)); snd_mixer_close(m); return -1; }
    rc = snd_mixer_selem_register(m, NULL, NULL);
    if (rc < 0) { sel_log("audio: mixer %s: register: %s", ctl, snd_strerror(rc)); snd_mixer_close(m); return -1; }
    rc = snd_mixer_load(m);
    if (rc < 0) { sel_log("audio: mixer %s: load: %s", ctl, snd_strerror(rc)); snd_mixer_close(m); return -1; }
    id = calloc(1, snd_mixer_selem_id_sizeof());
    if (!id) { snd_mixer_close(m); return -1; }
    snd_mixer_selem_id_set_index(id, 0);
    snd_mixer_selem_id_set_name(id, "PCM");
    e = snd_mixer_find_selem(m, id);
    free(id);
    if (!e) { sel_log("audio: mixer %s: no 'PCM' selem", ctl); snd_mixer_close(m); return -1; }
    snd_mixer_selem_get_playback_volume_range(e, &lo, &hi);
    /* the game's curve: 127*(v/63)^0.2 on a 0..127 scale, mapped onto the range */
    value = (long)(127.0f * powf((float)v63 / 63.0f, 0.2f) / 127.0f * (float)hi);
    rc = snd_mixer_selem_set_playback_volume_all(e, value);
    sel_log("audio: mixer %s PCM = %ld/%ld (mixer_volume %d)%s%s", ctl, value, hi, v63,
            rc < 0 ? ": " : "", rc < 0 ? snd_strerror(rc) : "");
    snd_mixer_close(m);
    return rc < 0 ? -1 : 0;
}

int audio_alsa_mixer(int v63)
{
    int rc = 0;
    if (v63 < 0) v63 = 0;
    if (v63 > 63) v63 = 63;
    snd_lib_error_set_handler(quiet);
    if (mixer_set("backbox", v63) < 0) rc = -1;
    if (mixer_set("cabinet", v63) < 0) rc = -1;
    return rc;
}
