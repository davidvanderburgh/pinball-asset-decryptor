/* audio_pulse.c - a JJP machine's sink: PulseAudio through libpulse-simple,
 * the way the game itself plays (its Allegro build uses libpulse-simple).
 *
 * WHY NOT ALSA'S `default`.  On a JJP root `default` is the ALSA pulse
 * PLUGIN, and item 120's 60 ms buffer through it left David's GNR silent
 * three sticks running (2026-09-14): an underrun's recover reconnects the
 * plugin's stream and a fresh stream pays about a second before the server
 * pulls again, so the machine's hiccups chained into silence, while the rig's
 * null sink could reproduce only parts of it.  libpulse-simple is a plain
 * blocking stream on the server's own terms: an underrun is silence inserted
 * by the server and the stream carries on, nothing reconnects, nothing keeps
 * an ALSA-style pointer.  The JJP build tries this first and falls back to
 * ALSA (audio_alsa.c) when no server answers - the rig with PAD_AUDIO=0, a
 * root with pulse stopped.
 *
 * No headers on the box: the two structs and the entry points are written
 * out by hand from pulse/sample.h, pulse/def.h and pulse/simple.h (PULSE_0
 * symbol version, libpulse 15).
 *
 * PACING.  The pump asks space() how much to mix, and this sink answers from
 * the wall clock: enough to stay PULSE_LEAD_MS ahead of real time, so the
 * server holds about that much and a write never blocks in the steady state
 * (tlength is PULSE_TLENGTH_MS, more than the lead).  After a stall the
 * backlog is DROPPED, not written: writing it would play the stall's worth
 * late for the rest of the run.  pa_simple_write blocks only when the server
 * is full, for the few ms it takes to free a request.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "audio.h"
#include "log.h"

typedef struct pa_simple pa_simple;
typedef struct { int format; uint32_t rate; uint8_t channels; } pa_sample_spec;   /* pulse/sample.h */
typedef struct { uint32_t maxlength, tlength, prebuf, minreq, fragsize; } pa_buffer_attr;  /* pulse/def.h */
#define PA_SAMPLE_S16LE    3
#define PA_STREAM_PLAYBACK 1

extern pa_simple *pa_simple_new(const char *server, const char *name, int dir, const char *dev,
                                const char *stream_name, const pa_sample_spec *ss, const void *map,
                                const pa_buffer_attr *attr, int *error);
extern int  pa_simple_write(pa_simple *s, const void *data, size_t bytes, int *error);
extern int  pa_simple_drain(pa_simple *s, int *error);
extern void pa_simple_free(pa_simple *s);
extern uint64_t pa_simple_get_latency(pa_simple *s, int *error);
extern const char *pa_strerror(int error);

#ifndef PULSE_TLENGTH_MS
#define PULSE_TLENGTH_MS 80         /* the server-side buffer asked for */
#endif
#ifndef PULSE_LEAD_MS
#define PULSE_LEAD_MS    60         /* how far ahead of the wall clock the pump keeps it: the lag */
#endif
#define FRAME_BYTES      (AUDIO_CH * 2)
#define RETRY_MS         1000       /* a dead stream is tried again this often */
#define MAX_PUMP_FRAMES  4096       /* the mixer's own ceiling per pump (audio.c MIX_MAX) */

struct pulse {
    struct audio_sink base;
    pa_simple *s;
    long long t0, clock;         /* wall-clock start, frames written since */
    long long retry_at;
    int errors, resyncs, err_logged, reconnects;
};

static int pulse_connect(struct pulse *p, char *err, int errlen)
{
    pa_sample_spec ss;
    pa_buffer_attr attr;
    int e = 0;
    ss.format = PA_SAMPLE_S16LE;
    ss.rate = AUDIO_RATE;
    ss.channels = AUDIO_CH;
    attr.maxlength = (uint32_t)-1;
    attr.tlength = (uint32_t)(PULSE_TLENGTH_MS * AUDIO_RATE / 1000) * FRAME_BYTES;
    attr.prebuf = attr.tlength / 4;                 /* starts once a quarter is in */
    attr.minreq = attr.tlength / 4;
    attr.fragsize = (uint32_t)-1;
    p->s = pa_simple_new(NULL, "jjpselect", PA_STREAM_PLAYBACK, NULL, "boot menu", &ss, NULL, &attr, &e);
    if (!p->s) {
        snprintf(err, errlen, "pulse: %s", pa_strerror(e));
        return -1;
    }
    p->t0 = 0;
    p->clock = 0;
    return 0;
}

static int pulse_space(struct audio_sink *s, long long now)
{
    struct pulse *p = (struct pulse *)s;
    long long lead = (long long)PULSE_LEAD_MS * AUDIO_RATE / 1000, due;
    if (!p->s) {
        char err[120];
        if (now < p->retry_at) return 0;
        if (pulse_connect(p, err, sizeof err) < 0) {
            p->retry_at = now + RETRY_MS;
            if (p->err_logged < 3) { sel_log("audio: pulse reconnect: %s", err); p->err_logged++; }
            return 0;
        }
        p->reconnects++;
        if (p->reconnects <= 3) sel_log("audio: pulse reconnected (#%d)", p->reconnects);
    }
    if (!p->t0) p->t0 = now;
    due = (now - p->t0) * AUDIO_RATE / 1000 + lead - p->clock;
    if (due > 2 * lead) {
        /* a stall: the backlog is dropped, the timeline moves on */
        p->clock += due - lead;
        due = lead;
        p->resyncs++;
        if (p->resyncs <= 3) sel_log("audio: pulse resync after a stall (#%d)", p->resyncs);
    }
    if (due > MAX_PUMP_FRAMES) due = MAX_PUMP_FRAMES;
    return due > 0 ? (int)due : 0;
}

static int pulse_write(struct audio_sink *s, const short *pcm, int frames)
{
    struct pulse *p = (struct pulse *)s;
    int e = 0;
    if (!p->s || frames <= 0) return 0;
    if (pa_simple_write(p->s, pcm, (size_t)frames * FRAME_BYTES, &e) < 0) {
        p->errors++;
        if (p->err_logged < 3) { sel_log("audio: pulse write: %s (the stream is dropped and retried)", pa_strerror(e)); p->err_logged++; }
        pa_simple_free(p->s);
        p->s = NULL;
        p->retry_at = sel_now_ms() + RETRY_MS;
        return 0;
    }
    p->clock += frames;
    return frames;
}

static void pulse_close(struct audio_sink *s)
{
    struct pulse *p = (struct pulse *)s;
    int e = 0;
    if (p->s) {
        if (pa_simple_drain(p->s, &e) < 0) sel_log("audio: pulse drain: %s", pa_strerror(e));
        pa_simple_free(p->s);
    }
    sel_log("audio: pulse closed, %lld frames, %d error(s), %d reconnect(s), %d resync(s)",
            p->clock, p->errors, p->reconnects, p->resyncs);
    free(p);
}

struct audio_sink *audio_pulse_open(char *err, int errlen)
{
    struct pulse *p = calloc(1, sizeof *p);
    int e = 0;
    uint64_t lat;
    if (!p) { snprintf(err, errlen, "out of memory"); return NULL; }
    if (pulse_connect(p, err, errlen) < 0) { free(p); return NULL; }
    p->base.name = "pulse";
    p->base.space = pulse_space;
    p->base.write = pulse_write;
    p->base.close = pulse_close;
    p->base.lead_ms = PULSE_LEAD_MS;
    lat = pa_simple_get_latency(p->s, &e);
    sel_log("audio: pulse ok (%d ch, %d Hz; tlength %d ms, lead %d ms, latency %s%llu ms)",
            AUDIO_CH, AUDIO_RATE, PULSE_TLENGTH_MS, PULSE_LEAD_MS, e ? "unreadable " : "",
            e ? 0ULL : (unsigned long long)(lat / 1000));
    return &p->base;
}
