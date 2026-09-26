/* audio.c - see audio.h: the WAV loader, the mixer and the sink selection.
 *
 * The pump - mix exactly as many frames as the sink can take (the FIFO paces
 * to the wall clock with a 200 ms lead, ALSA reports its buffer space) and
 * hand them over without ever blocking - ran from the main loop until
 * 2026-09-14.  A JJP machine's loop is vsync-paced and hiccups, and its
 * 60 ms buffer (item 120) underran on every hiccup until the stream through
 * the pulse plugin stopped restarting: David's GNR, silent.  So the pump now
 * runs on ITS OWN THREAD every PUMP_MS, started with the sink; the main
 * loop's audio_pump() is then a no-op, and every entry point takes the
 * mutex.  A stalled loop (a silent node board on hardware can hold an
 * iteration for a second) is now no gap at all; a stalled PROCESS still
 * becomes one, never a crash, and the sinks count what they had to drop.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include "audio.h"
#include "log.h"

#define VOICES      4
#define PUMP_MS     5               /* the pump thread's period: a 60 ms buffer gets 12 visits */
#define MIX_MAX     4096            /* frames per pump */
#define FADE_FRAMES 882             /* 20 ms: a stopped voice ramps out instead of clicking */
#define CLIP_CAP_S  120             /* longer WAVs are cut, with a log line */
#define NULL_LEAD_MS 200

/* ------------------------------------------------------------------- WAV */

static unsigned rd16(const unsigned char *p) { return p[0] | (p[1] << 8); }
static unsigned rd32(const unsigned char *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((unsigned)p[3] << 24); }

struct audio_clip *audio_load_wav(const char *path, char *err, int errlen)
{
    FILE *f = fopen(path, "rb");
    unsigned char *buf;
    long n;
    unsigned pos, fmt_off = 0, fmt_len = 0, data_off = 0, data_len = 0;
    unsigned tag, ch, rate, bits;
    struct audio_clip *c;
    int frames, i;

    if (!f) { snprintf(err, errlen, "%s: %s", path, strerror(errno)); return NULL; }
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n < 44 || n > 64L * 1024 * 1024) {
        snprintf(err, errlen, "%s: %ld bytes is not a usable WAV", path, n);
        fclose(f);
        return NULL;
    }
    buf = malloc((size_t)n);
    if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n) {
        snprintf(err, errlen, "%s: short read", path);
        fclose(f);
        free(buf);
        return NULL;
    }
    fclose(f);
    if (memcmp(buf, "RIFF", 4) || memcmp(buf + 8, "WAVE", 4)) {
        snprintf(err, errlen, "%s: not a RIFF WAVE file", path);
        free(buf);
        return NULL;
    }
    /* walk the chunks: fmt and data, skipping LIST/JUNK/bext and the rest */
    pos = 12;
    while (pos + 8 <= (unsigned)n) {
        unsigned len = rd32(buf + pos + 4);
        unsigned body = pos + 8;
        if (len > (unsigned)n - body) len = (unsigned)n - body;
        if (!memcmp(buf + pos, "fmt ", 4)) { fmt_off = body; fmt_len = len; }
        else if (!memcmp(buf + pos, "data", 4)) { data_off = body; data_len = len; break; }
        pos = body + len + (len & 1);
    }
    if (!fmt_off || fmt_len < 16 || !data_off) {
        snprintf(err, errlen, "%s: no fmt/data chunk", path);
        free(buf);
        return NULL;
    }
    tag = rd16(buf + fmt_off);
    ch = rd16(buf + fmt_off + 2);
    rate = rd32(buf + fmt_off + 4);
    bits = rd16(buf + fmt_off + 14);
    if (tag == 0xfffe && fmt_len >= 26 && rd16(buf + fmt_off + 24) == 1) tag = 1;   /* extensible PCM */
    if (tag != 1 || bits != 16 || rate != AUDIO_RATE || (ch != 1 && ch != 2)) {
        snprintf(err, errlen, "%s: unsupported (format %u, %u-bit, %u Hz, %u ch; need PCM 16-bit 44100 Hz 1-2 ch)",
                 path, tag, bits, rate, ch);
        free(buf);
        return NULL;
    }
    frames = (int)(data_len / (ch * 2));
    if (frames > CLIP_CAP_S * AUDIO_RATE) {
        sel_log("audio: %s: %d s long, cut to %d s", path, frames / AUDIO_RATE, CLIP_CAP_S);
        frames = CLIP_CAP_S * AUDIO_RATE;
    }
    c = calloc(1, sizeof *c);
    if (c) c->pcm = malloc((size_t)frames * 2 * sizeof(short));
    if (!c || !c->pcm) {
        snprintf(err, errlen, "%s: out of memory", path);
        free(buf);
        free(c);
        return NULL;
    }
    c->frames = frames;
    for (i = 0; i < frames; i++) {
        const unsigned char *s = buf + data_off + (size_t)i * ch * 2;
        short l = (short)rd16(s);
        short r = ch == 2 ? (short)rd16(s + 2) : l;
        c->pcm[i * 2] = l;
        c->pcm[i * 2 + 1] = r;
    }
    free(buf);
    return c;
}

void audio_clip_free(struct audio_clip *c)
{
    if (!c) return;
    free(c->pcm);
    free(c);
}

/* ------------------------------------------------------------- the mixer */

struct voice {
    const struct audio_clip *clip;
    int pos, loop, active;
    int fade_left;            /* > 0: ramping out over this many frames */
};

struct audio {
    struct audio_sink *sink;
    int gain_q8;
    struct voice v[VOICES];
    long long written, dropped;
    FILE *dump;
    char missing[200];        /* why a WANTED sink is absent, "" otherwise */
    pthread_mutex_t lock;     /* the voices, the gain, the dump, the counts */
    pthread_t th;
    int th_on, th_stop;       /* the pump thread runs; it is asked to stop */
    short buf[MIX_MAX * 2];
};

static void pump_locked(struct audio *a, long long now_ms);

static void *pump_thread(void *p)
{
    struct audio *a = p;
    while (!a->th_stop) {
        pthread_mutex_lock(&a->lock);
        pump_locked(a, sel_now_ms());
        pthread_mutex_unlock(&a->lock);
        sel_sleep_ms(PUMP_MS);
    }
    return NULL;
}

/* the sink used when there is nothing to play into but a --audio-dump: paces
 * to the wall clock like the FIFO and accepts everything */
struct null_sink {
    struct audio_sink base;
    long long t0, clock;
};

static int null_space(struct audio_sink *s, long long now)
{
    struct null_sink *ns = (struct null_sink *)s;
    long long due;
    if (!ns->t0) ns->t0 = now;
    due = (now - ns->t0) * AUDIO_RATE / 1000 + (long long)NULL_LEAD_MS * AUDIO_RATE / 1000 - ns->clock;
    return due > 0 ? (int)due : 0;
}

static int null_write(struct audio_sink *s, const short *pcm, int frames)
{
    struct null_sink *ns = (struct null_sink *)s;
    (void)pcm;
    ns->clock += frames;
    return frames;
}

static void null_close(struct audio_sink *s)
{
    free(s);
}

static struct audio_sink *null_open(void)
{
    struct null_sink *ns = calloc(1, sizeof *ns);
    if (!ns) return NULL;
    ns->base.name = "dump";
    ns->base.space = null_space;
    ns->base.write = null_write;
    ns->base.close = null_close;
    ns->base.lead_ms = NULL_LEAD_MS;
    return &ns->base;
}

/* THE FULL SCALE (PAD-219): what volume 100 plays at, as a percent of the
 * samples.  100 on every build but JJP's, which sets 10: a JJP machine runs
 * its amplifiers at full while the menu plays, and on the old 0-40 scale 20
 * was already high on David's GNR and 8 "at max" on cooltoy's Sonic - so the
 * new loudest is the old 10 (-20 dB), under both, and the default of 50 is
 * the old 5 (-26 dB).  The number the operator sees and sets stays 0-100;
 * only what it buys changed. */
#ifndef VOLUME_FULL_PCT
#define VOLUME_FULL_PCT 100
#endif

static int gain_of(int volume)
{
    if (volume < 0) volume = 0;
    if (volume > 100) volume = 100;
    return volume * VOLUME_FULL_PCT * 256 / 10000;
}

struct audio *audio_open(const char *mode, const char *fmt_path, int volume, const char *dump_path)
{
    struct audio *a = calloc(1, sizeof *a);
    char err[200] = "";
    if (!a) return NULL;
    pthread_mutex_init(&a->lock, NULL);
    if (volume < 0) volume = 0;
    if (volume > 100) volume = 100;
    a->gain_q8 = gain_of(volume);
    if (!mode || !*mode) mode = "auto";

    if (!strcmp(mode, "none")) {
        sel_log("audio: none (--audio none)");
    } else if (!strcmp(mode, "alsa")) {
        a->sink = audio_alsa_open(err, sizeof err);
        if (!a->sink) {
            sel_log("audio: none (no alsa: %s)", err);
            snprintf(a->missing, sizeof a->missing, "no alsa: %s", err);
        }
    } else if (!strcmp(mode, "pulse")) {
#ifdef AUDIO_PULSE
        a->sink = audio_pulse_open(err, sizeof err);
        if (!a->sink) {
            sel_log("audio: none (%s)", err);
            snprintf(a->missing, sizeof a->missing, "%s", err);
        }
#else
        sel_log("audio: none (this build has no pulse sink)");
        snprintf(a->missing, sizeof a->missing, "no pulse sink in this build");
#endif
    } else if (!strncmp(mode, "fifo:", 5)) {
        if (mode[5]) a->sink = audio_fifo_open(mode + 5, fmt_path);
        else sel_log("audio: none (fifo: without a path)");
    } else if (!strcmp(mode, "auto")) {
        const char *play = getenv("PAD_AUDIO_PLAY");
#ifdef AUDIO_PULSE
        /* A JJP MACHINE: PulseAudio itself first (audio_pulse.c says why the
         * ALSA pulse plugin is not enough), ALSA when no server answers */
        a->sink = audio_pulse_open(err, sizeof err);
        if (!a->sink) sel_log("audio: no pulse server (%s); trying alsa", err);
        if (!a->sink) a->sink = audio_alsa_open(err, sizeof err);
#else
        a->sink = audio_alsa_open(err, sizeof err);
#endif
        if (!a->sink) {
            if (play && *play) {
                sel_log("audio: no alsa (%s), using the rig's fifo", err);
                a->sink = audio_fifo_open(play, fmt_path);
            } else {
                sel_log("audio: none (no alsa: %s; PAD_AUDIO_PLAY unset)", err);
                snprintf(a->missing, sizeof a->missing, "no alsa: %s", err);
            }
        }
    } else {
        sel_log("audio: none (unknown --audio mode '%s')", mode);
    }

    if (dump_path && *dump_path) {
        a->dump = fopen(dump_path, "wb");
        if (!a->dump) sel_log("audio: cannot write dump %s: %s", dump_path, strerror(errno));
        else sel_log("audio: dumping the mix to %s", dump_path);
        if (a->dump && !a->sink) a->sink = null_open();
    }
    if (a->sink) sel_log("audio: sink %s, lead %d ms, volume %d (gain %d/256; 100 = %d%% of full)",
                         a->sink->name, a->sink->lead_ms, volume, a->gain_q8, VOLUME_FULL_PCT);
    if (a->sink) {
        if (pthread_create(&a->th, NULL, pump_thread, a) == 0) {
            a->th_on = 1;
            sel_log("audio: pump thread every %d ms", PUMP_MS);
        } else {
            sel_log("audio: no pump thread (%s): the main loop pumps", strerror(errno));
        }
    }
    return a;
}

/* round(100 * (v/63)^0.2) for v = 0..63: the codec curve the game applies
 * (audio_alsa_mixer), as a percentage of the mix, with 0 = silent */
static const unsigned char machine_gain_pct[64] = {
    0, 44, 50, 54, 58, 60, 62, 64, 66, 68, 69, 71, 72, 73, 74, 75,
    76, 77, 78, 79, 79, 80, 81, 82, 82, 83, 84, 84, 85, 86, 86, 87,
    87, 88, 88, 89, 89, 90, 90, 91, 91, 92, 92, 93, 93, 93, 94, 94,
    95, 95, 95, 96, 96, 97, 97, 97, 98, 98, 98, 99, 99, 99, 100, 100 };

int audio_machine_gain(int v63)
{
    if (v63 < 0) v63 = 0;
    if (v63 > 63) v63 = 63;
    return machine_gain_pct[v63];
}

void audio_set_volume(struct audio *a, int volume)
{
    if (!a) return;
    if (volume < 0) volume = 0;
    if (volume > 100) volume = 100;
    pthread_mutex_lock(&a->lock);
    a->gain_q8 = gain_of(volume);
    pthread_mutex_unlock(&a->lock);
    if (a->sink) sel_log("audio: volume %d (gain %d/256)", volume, a->gain_q8);
}

int audio_active(const struct audio *a)
{
    return a && a->sink != NULL;
}

const char *audio_sink_name(const struct audio *a)
{
    return a && a->sink ? a->sink->name : "none";
}

const char *audio_missing(const struct audio *a)
{
    return a && !a->sink ? a->missing : "";
}

int audio_play(struct audio *a, const struct audio_clip *c, int loop)
{
    int i;
    if (!a || !a->sink || !c || c->frames <= 0) return -1;
    pthread_mutex_lock(&a->lock);
    for (i = 0; i < VOICES; i++) {
        if (!a->v[i].active) {
            a->v[i].clip = c;
            a->v[i].pos = 0;
            a->v[i].loop = loop;
            a->v[i].active = 1;
            a->v[i].fade_left = 0;
            pthread_mutex_unlock(&a->lock);
            return i;
        }
    }
    /* all busy: steal the oldest non-looping voice, else the first */
    for (i = 0; i < VOICES; i++)
        if (!a->v[i].loop) break;
    if (i == VOICES) i = 0;
    a->v[i].clip = c;
    a->v[i].pos = 0;
    a->v[i].loop = loop;
    a->v[i].active = 1;
    a->v[i].fade_left = 0;
    pthread_mutex_unlock(&a->lock);
    return i;
}

void audio_stop(struct audio *a, int voice)
{
    if (!a || voice < 0 || voice >= VOICES) return;
    pthread_mutex_lock(&a->lock);
    if (a->v[voice].active && !a->v[voice].fade_left) a->v[voice].fade_left = FADE_FRAMES;
    pthread_mutex_unlock(&a->lock);
}

int audio_playing(const struct audio *a, int voice)
{
    int r;
    if (!a || voice < 0 || voice >= VOICES) return 0;
    pthread_mutex_lock((pthread_mutex_t *)&a->lock);
    r = a->v[voice].active;
    pthread_mutex_unlock((pthread_mutex_t *)&a->lock);
    return r;
}

int audio_playing_clip(const struct audio *a, int voice, const struct audio_clip *c)
{
    if (!a || !c || voice < 0 || voice >= VOICES) return 0;
    /* a voice fading out was stopped, and one stolen since belongs to
     * whatever clip took it */
    {
        int r;
        pthread_mutex_lock((pthread_mutex_t *)&a->lock);
        r = a->v[voice].active && !a->v[voice].fade_left && a->v[voice].clip == c;
        pthread_mutex_unlock((pthread_mutex_t *)&a->lock);
        return r;
    }
}

static void mix(struct audio *a, short *out, int frames)
{
    int i, k;
    for (i = 0; i < frames; i++) {
        int l = 0, r = 0;
        for (k = 0; k < VOICES; k++) {
            struct voice *v = &a->v[k];
            int sl, sr;
            if (!v->active) continue;
            sl = v->clip->pcm[v->pos * 2];
            sr = v->clip->pcm[v->pos * 2 + 1];
            if (v->fade_left) {
                sl = sl * v->fade_left / FADE_FRAMES;
                sr = sr * v->fade_left / FADE_FRAMES;
                if (--v->fade_left == 0) v->active = 0;
            }
            l += sl;
            r += sr;
            if (++v->pos >= v->clip->frames) {
                if (v->loop) v->pos = 0;
                else v->active = 0;
            }
        }
        l = l * a->gain_q8 >> 8;
        r = r * a->gain_q8 >> 8;
        if (l > 32767) l = 32767; else if (l < -32768) l = -32768;
        if (r > 32767) r = 32767; else if (r < -32768) r = -32768;
        out[i * 2] = (short)l;
        out[i * 2 + 1] = (short)r;
    }
}

void audio_pump(struct audio *a, long long now_ms)
{
    if (!a || !a->sink || a->th_on) return;     /* the thread pumps */
    pthread_mutex_lock(&a->lock);
    pump_locked(a, now_ms);
    pthread_mutex_unlock(&a->lock);
}

static void pump_locked(struct audio *a, long long now_ms)
{
    int want, n;
    if (!a->sink) return;
    want = a->sink->space(a->sink, now_ms);
    if (want <= 0) return;
    if (want > MIX_MAX) want = MIX_MAX;
    mix(a, a->buf, want);
    if (a->dump) fwrite(a->buf, 4, (size_t)want, a->dump);
    n = a->sink->write(a->sink, a->buf, want);
    if (n < 0) n = 0;
    if (n > want) n = want;
    a->written += n;
    a->dropped += want - n;
}

int audio_lead_ms(const struct audio *a)
{
    return a && a->sink ? a->sink->lead_ms : 0;
}

void audio_close(struct audio *a)
{
    if (!a) return;
    if (a->th_on) {                      /* the pump first: the sink is closed under nobody */
        a->th_stop = 1;
        pthread_join(a->th, NULL);
        a->th_on = 0;
    }
    if (a->dump) { fclose(a->dump); a->dump = NULL; }
    if (a->sink) {
        a->sink->close(a->sink);
        a->sink = NULL;
        sel_log("audio: %lld frames written, %lld dropped", a->written, a->dropped);
    }
    free(a);
}
