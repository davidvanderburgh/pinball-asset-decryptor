/* audio_alsa.c - the machine sink: the game's own playback device through
 * the rootfs libasound.so.2 (alsa-lib 1.0.28). No headers exist on the box,
 * so every prototype is hand-written (export list checked against
 * readelf --dyn-syms; the game itself uses the same entry points).
 *
 *   snd_lib_error_set_handler(quiet)      alsa-lib's stderr chain stays out of the console log
 *   snd_pcm_open(<ALSA_DEVICES[] in order>, PLAYBACK, 0)
 *       any failure = 'no alsa' (-19 in the emulator chroot). NEVER the
 *       'null' device: alsa-lib 1.0.28 asserts inside hw_params on it.
 *   snd_pcm_set_params(S16_LE=2, RW_INTERLEAVED=3, 2 ch, 44100, resample 1, ALSA_LATENCY_US)
 *   snd_pcm_get_params: the buffer the device really granted, into the log
 *   snd_pcm_nonblock(1); avail_update says how much fits; writei in
 *       <= 1764-frame chunks (the game's period); -EPIPE -> snd_pcm_recover
 *   the amplifier gate: 'Line Out Mute' switched ON on ctl backbox and
 *       cabinet (LINEOUT_SWITCH below) - without it the codec plays into a
 *       muted amplifier and the machine is silent
 *   close: nonblock(0), drain, close - BEFORE the choice file is written and
 *       before the EGL teardown, so the game's later open finds hw:0 free -
 *       then a 'Line Out Mute' that was OFF goes back OFF.
 *
 * The volume is untouched unless mixer_volume= or volume=machine asks: then
 * the game's own recipe (function 0x1fa490 of the godzilla_pro ELF) puts
 * 192*(v/63)^0.2 into 'PCM Playback Volume' on ctl backbox and cabinet.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <math.h>
#include <alloca.h>
#include "audio.h"
#include "codec.h"
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
extern int  snd_pcm_get_params(snd_pcm_t *, unsigned long *buffer_size, unsigned long *period_size);
extern int  snd_pcm_state(snd_pcm_t *);
extern unsigned long snd_pcm_sw_params_sizeof(void);
extern int  snd_pcm_sw_params_current(snd_pcm_t *, void *sw);
extern int  snd_pcm_sw_params_set_start_threshold(snd_pcm_t *, void *sw, unsigned long frames);
extern int  snd_pcm_sw_params_set_avail_min(snd_pcm_t *, void *sw, unsigned long frames);
extern int  snd_pcm_sw_params(snd_pcm_t *, void *sw);
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
extern int  snd_mixer_selem_has_playback_switch(snd_mixer_elem_t *);
extern int  snd_mixer_selem_get_playback_switch(snd_mixer_elem_t *, int channel, int *value);
extern int  snd_mixer_selem_set_playback_switch_all(snd_mixer_elem_t *, int value);

#define SND_PCM_STREAM_PLAYBACK      0
#define SND_PCM_FORMAT_S16_LE        2
#define SND_PCM_ACCESS_RW_INTERLEAVED 3
/* THE DEVICES TO TRY, IN ORDER - and "default" is first for a reason.
 *
 * The machine's own /etc/asound.conf (read off a Godzilla card) makes
 * `default` a plug over `cabinet_and_backbox`: a route over a multi of
 * dmixer_backbox (card 0) and dmixer_cabinet (card 1), which is how the
 * game reaches BOTH the backbox pair and the cabinet speaker.  Two things
 * follow, and the menu was getting both of them wrong by opening the raw
 * card instead:
 *
 *   1. dmix means SHARED.  `sysdefault:CARD=sgtl5000main` is a plug over
 *      hw:0 with no mixing, so anything else holding card 0 when the menu
 *      starts makes the open fail outright - and a failed open is silence
 *      with a line in the log nobody reads (David, after a card that plays
 *      fine in the emulator: "it's not playing audio through the speakers
 *      at all").  The emulator never showed it: with no sound card there,
 *      the ALSA open fails anyway and the rig's fifo takes over.
 *   2. hw:0 is the BACKBOX ONLY.  The cabinet speaker is a second card, and
 *      only `cabinet_and_backbox` feeds it.
 *
 * The raw card stays last so a machine without that asound.conf still gets
 * sound, and `plughw:0,0` after it as the crudest thing that can work.
 */
static const char *const ALSA_DEVICES[] = {
    "default", "cabinet_and_backbox", "sysdefault:CARD=sgtl5000main",
    "plughw:0,0",
};
/* THE BUFFER IS THE LAG.  audio_pump() fills whatever the device has room for,
 * so the buffer is always full and a new sound joins BEHIND all of it: a move
 * sound comes out one buffer after the press.  500 ms was the Stern card's
 * number and nobody heard it there; the first JJP machine did (David's GNR,
 * 2026-09-14: "the sound effect for changing the option was a little
 * delayed").  The JJP build asks for 60 ms (Makefile) - the menu pumps every
 * frame, 16 ms at 60 Hz, so that is several frames of slack - and the buffer
 * the device actually granted is logged, because a plugin may round it. */
#ifndef ALSA_LATENCY_US
#define ALSA_LATENCY_US 500000
#endif
#ifndef ALSA_LEAD_MS
#define ALSA_LEAD_MS    500
#endif
#define CHUNK_FRAMES  1764          /* the game's period size */
#define ALSA_STALL_MS 3000          /* nothing accepted for this long while open = stuck: reopen (JJP).
                                     * Generous on purpose: a fresh stream through the pulse plugin
                                     * takes ~1.1 s after its first fill before the server asks for
                                     * more (the rig's null sink), and a watchdog under that reopened
                                     * into the pause forever; the pump thread is what keeps xruns
                                     * rare, this only catches a stream that truly stopped */

/* THE AMPLIFIER GATE - why a stream the codec accepted made no sound.
 *
 * David's Godzilla, 2026-09-04, /dump/log/codeselect.log: `audio: alsa
 * sysdefault:CARD=sgtl5000main ok`, the PCM volume set on both controls,
 * 1,007,616 frames written over 23 s with 0 dropped - and silence from the
 * speakers.  The game ELF does one more thing the menu never did.  Its
 * audio bring-up (godzilla_pro 0x1fb2a8: open both cards, PCM volume, prime
 * 18 buffers of silence, clear SPI bits, 80 ms, unmute) ends in its mute
 * helper 0x1faad4, which on ctl `backbox` and ctl `cabinet` finds the simple
 * mixer element "Line Out Mute" and sets its PLAYBACK SWITCH to !mute: ON to
 * play, OFF when the headphone kit says mute the speakers.  Stern's own
 * spike_menu binary on the rootfs carries the same string.  Nothing in
 * alsactl's asound.state names that control, so a boot leaves it at the
 * driver's power-up value - muted - and the codec plays into an amplifier
 * that never hears it.  The emulator could not show any of this: with no
 * sound card there the ALSA open fails and the rig's fifo takes over.
 *
 * (The real gate turned out to be neither this switch nor the codec: it is
 * tx[7] of the cabinet SPI word, the AMPLIFIER ENABLE - see input_hw.c.
 * This switch is kept ON regardless because the game keeps it ON and it
 * costs nothing; on David's machine it read `on (was on)`, never the fault.)
 *
 * So: once the device is open, the switch goes ON on both controls and what
 * it read first is kept; at close, after the drain, a switch that was OFF
 * goes back OFF, so the game boots from the state a stock card gives it (its
 * own bring-up switches it ON again, unconditionally).  A rootfs whose
 * driver has no such element logs that once per control and plays as before.
 */
#define LINEOUT_SWITCH "Line Out Mute"
static const char *const MIXER_CTLS[] = { "backbox", "cabinet" };
#define NCTL ((int)(sizeof MIXER_CTLS / sizeof *MIXER_CTLS))

struct alsa {
    struct audio_sink base;
    snd_pcm_t *pcm;                /* NULL between a failed reopen and the next try */
    const char *dev;               /* the device that opened, for a reopen */
    unsigned latency_us;           /* the buffer that was granted, for a reopen */
    int err_logged, recovered, reopens, stalls, first_logged, dbg;
    long long last_accept_ms;      /* when the device last took frames (the stall watchdog) */
    int lo_was[NCTL];         /* LINEOUT_SWITCH per MIXER_CTLS before we touched it: 1/0, -1 = none/unknown */
};

static int lineout_switch(const char *ctl, int on, const char *note);
#ifdef ALSA_REOPEN_ON_XRUN
static int alsa_reopen(struct alsa *a);
#endif

static void quiet(const char *file, int line, const char *function, int err, const char *fmt, ...)
{
    (void)file; (void)line; (void)function; (void)err; (void)fmt;
}

static int alsa_space(struct audio_sink *s, long long now)
{
    struct alsa *a = (struct alsa *)s;
    long av;
    (void)now;
#ifdef ALSA_REOPEN_ON_XRUN
    if (!a->pcm && alsa_reopen(a) < 0) return 0;      /* a failed reopen: try again each pump */
    /* THE WATCHDOG.  A stream through the pulse plugin can stop taking frames
     * without ever reporting an underrun - the rig, stopped 80 ms of every
     * 200, sat 2 s at a time accepting nothing after every reopen.  Nothing
     * accepted for ALSA_STALL_MS while the device is open is stuck, whatever
     * the cause: reopened, said up to three times, counted always. */
    if (!getenv("PADSELECT_NO_WATCHDOG") && a->last_accept_ms && now - a->last_accept_ms > ALSA_STALL_MS) {
        a->stalls++;
        if (a->stalls <= 3)
            sel_log("audio: alsa stalled: nothing accepted for %lld ms, reopening (#%d)",
                    now - a->last_accept_ms, a->stalls);
        if (alsa_reopen(a) < 0) return 0;
        a->last_accept_ms = now;
    }
#else
    if (!a->pcm) return 0;
#endif
    av = snd_pcm_avail_update(a->pcm);
    if (a->dbg < 60 && getenv("PADSELECT_AUDIO_DEBUG")) {
        a->dbg++;
        sel_log("audio: dbg space t=%lld av=%ld state=%d", now, av, snd_pcm_state(a->pcm));
    }
    if (av < 0) {
#ifdef ALSA_REOPEN_ON_XRUN
        a->recovered++;
        if (alsa_reopen(a) < 0) return 0;
#else
        int rc = snd_pcm_recover(a->pcm, (int)av, 1);
        if (rc < 0) {
            if (!a->err_logged) { sel_log("audio: alsa recover: %s", snd_strerror(rc)); a->err_logged = 1; }
            return 0;
        }
        a->recovered++;
#endif
        av = snd_pcm_avail_update(a->pcm);
        if (av < 0) return 0;
    }
    return av > 0 ? (int)av : 0;
}

static int alsa_write(struct audio_sink *s, const short *pcm, int frames)
{
    struct alsa *a = (struct alsa *)s;
    int done = 0;
#ifndef ALSA_REOPEN_ON_XRUN
    int retries = 0;
#endif
    if (!a->pcm) return 0;
    while (done < frames) {
        int chunk = frames - done;
        long rc;
        if (chunk > CHUNK_FRAMES) chunk = CHUNK_FRAMES;
        rc = snd_pcm_writei(a->pcm, pcm + (size_t)done * 2, (unsigned long)chunk);
        if (a->dbg < 60 && getenv("PADSELECT_AUDIO_DEBUG")) sel_log("audio: dbg write %d -> %ld state=%d", chunk, rc, snd_pcm_state(a->pcm));
        if (rc == -EAGAIN) break;                       /* buffer full: the rest waits for the next pump */
        if (rc == -EPIPE || rc == -ESTRPIPE) {
#ifdef ALSA_REOPEN_ON_XRUN
            a->recovered++;
            alsa_reopen(a);                             /* the rest waits for the next pump */
            break;
#else
            int r = snd_pcm_recover(a->pcm, (int)rc, 1);
            a->recovered++;
            if (r < 0 || ++retries > 2) {
                if (!a->err_logged) { sel_log("audio: alsa writei: %s", snd_strerror((int)rc)); a->err_logged = 1; }
                break;
            }
            continue;
#endif
        }
        if (rc < 0) {
            if (!a->err_logged) { sel_log("audio: alsa writei: %s", snd_strerror((int)rc)); a->err_logged = 1; }
            break;
        }
        done += (int)rc;
        if (rc < chunk) break;
    }
    if (done > 0) {
        long long t = sel_now_ms();
        /* the first frames after the first fill: how long the stream took to
         * get going, once per open, for the machine's log */
        if (!a->first_logged && a->last_accept_ms && t - a->last_accept_ms > 50) {
            sel_log("audio: alsa took %lld ms after the first fill to take more", t - a->last_accept_ms);
            a->first_logged = 1;
        }
        a->last_accept_ms = t;
    }
    return done;
}

static void alsa_close(struct audio_sink *s)
{
    struct alsa *a = (struct alsa *)s;
    int rc = 0;
    if (a->pcm) {
        snd_pcm_nonblock(a->pcm, 0);
        rc = snd_pcm_drain(a->pcm);
        if (rc < 0) sel_log("audio: alsa drain: %s", snd_strerror(rc));
        rc = snd_pcm_close(a->pcm);
    }
    sel_log("audio: alsa closed (%s), %d recover(s), %d reopen(s), %d stall(s)", rc < 0 ? snd_strerror(rc) : "ok",
            a->recovered, a->reopens, a->stalls);
    /* the codecs back as found (after the kernel's own close-time writes),
     * and the kernel's switch back where it was shut */
    codec_restore();
    {
        int i;
        for (i = 0; i < NCTL; i++)
            if (a->lo_was[i] == 0) lineout_switch(MIXER_CTLS[i], 0, ", back as found");
    }
    free(a);
}

/* Open the device - the first of ALSA_DEVICES that opens, or *devp when a
 * reopen names the one that did - and set it up: the buffer asked for (with
 * the ladder), what was granted into the log, the start threshold, nonblock.
 * NULL with err filled in.  *devp and *latency_us come back as what was used,
 * so a reopen asks for exactly the same again.  chatty = the log lines a
 * first open writes; a reopen after the first few is quiet. */
static snd_pcm_t *open_pcm(const char **devp, unsigned *latency_us, char *err, int errlen, int chatty)
{
    snd_pcm_t *pcm = NULL;
    const char *dev = *devp;
    unsigned lat = *latency_us;
    size_t i;
    int rc = -1;

    err[0] = 0;
    if (dev) {
        rc = snd_pcm_open(&pcm, dev, SND_PCM_STREAM_PLAYBACK, 0);
        if (rc < 0) { snprintf(err, errlen, "%s: %s", dev, snd_strerror(rc)); return NULL; }
    } else {
        for (i = 0; i < sizeof ALSA_DEVICES / sizeof *ALSA_DEVICES; i++) {
            rc = snd_pcm_open(&pcm, ALSA_DEVICES[i], SND_PCM_STREAM_PLAYBACK, 0);
            if (rc >= 0) { dev = ALSA_DEVICES[i]; break; }
            /* every failure is kept: which devices a machine HAS NOT got is the
             * whole diagnosis when a card comes back silent */
            sel_log("audio: alsa %s: %s", ALSA_DEVICES[i], snd_strerror(rc));
            if (err[0]) {
                size_t n = strlen(err);
                snprintf(err + n, (size_t)errlen > n ? errlen - n : 0, "; ");
            }
            {
                size_t n = strlen(err);
                snprintf(err + n, (size_t)errlen > n ? errlen - n : 0, "%s: %s",
                         ALSA_DEVICES[i], snd_strerror(rc));
            }
            pcm = NULL;
        }
        if (!pcm) return NULL;
    }
    /* THE LADDER: a device that refuses the buffer asked for is tried at 120, 250
     * and 500 ms before the menu gives up on sound - the lag of a bigger buffer is
     * a nuisance, a silent menu is a fault nobody can diagnose from the glass. */
    {
        static const unsigned ladder[] = { 120000u, 250000u, 500000u };
        size_t k;
        rc = snd_pcm_set_params(pcm, SND_PCM_FORMAT_S16_LE, SND_PCM_ACCESS_RW_INTERLEAVED,
                                AUDIO_CH, AUDIO_RATE, 1, lat);
        for (k = 0; rc < 0 && k < sizeof ladder / sizeof *ladder; k++) {
            if (ladder[k] <= lat) continue;
            sel_log("audio: alsa %s: snd_pcm_set_params(%u ms): %s; trying %u ms", dev,
                    lat / 1000u, snd_strerror(rc), ladder[k] / 1000u);
            lat = ladder[k];
            rc = snd_pcm_set_params(pcm, SND_PCM_FORMAT_S16_LE, SND_PCM_ACCESS_RW_INTERLEAVED,
                                    AUDIO_CH, AUDIO_RATE, 1, lat);
        }
    }
    if (rc < 0) {
        snprintf(err, errlen, "%s: snd_pcm_set_params(%u ms): %s", dev, lat / 1000u, snd_strerror(rc));
        snd_pcm_close(pcm);
        return NULL;
    }
    {
        /* what the lag really is: the buffer granted, not the one asked for */
        unsigned long bufsz = 0, persz = 0;
        if (snd_pcm_get_params(pcm, &bufsz, &persz) == 0) {
            if (chatty)
                sel_log("audio: alsa buffer %lu frames (%d ms), period %lu frames (%lu ms); asked %d ms",
                        bufsz, (int)(bufsz * 1000UL / AUDIO_RATE), persz, persz * 1000UL / AUDIO_RATE,
                        (int)(lat / 1000));
        } else if (chatty) {
            sel_log("audio: alsa buffer size unreadable; asked %d ms", (int)(lat / 1000));
        }
#ifdef ALSA_START_PERIODS
        /* START ON ONE PERIOD, NOT A WHOLE BUFFER: snd_pcm_set_params leaves the
         * start threshold at the buffer size; at ALSA_START_PERIODS period(s) the
         * stream starts as soon as that much is queued.  The JJP build only: the
         * Stern card's sink stays exactly as it was. */
        if (persz) {
            void *sw = alloca(snd_pcm_sw_params_sizeof());
            unsigned long thr = persz * (unsigned long)ALSA_START_PERIODS;
            if (snd_pcm_sw_params_current(pcm, sw) == 0
                && snd_pcm_sw_params_set_start_threshold(pcm, sw, thr) == 0
                && snd_pcm_sw_params_set_avail_min(pcm, sw, persz) == 0
                && snd_pcm_sw_params(pcm, sw) == 0) {
                if (chatty)
                    sel_log("audio: alsa start threshold %lu frames (%d period%s)", thr,
                            (int)ALSA_START_PERIODS, ALSA_START_PERIODS == 1 ? "" : "s");
            } else if (chatty) {
                sel_log("audio: alsa start threshold could not be set; the library's (a whole buffer) stays");
            }
        }
#endif
    }
    rc = snd_pcm_nonblock(pcm, 1);
    if (rc < 0 && chatty) sel_log("audio: alsa nonblock: %s (writes may block briefly)", snd_strerror(rc));
    *devp = dev;
    *latency_us = lat;
    return pcm;
}

#ifdef ALSA_REOPEN_ON_XRUN
/* AN UNDERRUN REOPENS THE DEVICE.  snd_pcm_recover (prepare) is what the Stern
 * card gets, and through the pulse plugin it is not enough: after a recover
 * the plugin's own bookkeeping leaves the stream stalled - the rig, stopped
 * 80 ms of every 200, recovered 7 times and then wrote almost nothing for the
 * rest of the run (David's GNR, silent, 2026-09-14) - so the JJP build closes
 * the PCM and opens it again, the same device, the same buffer: a fresh plugin
 * instance every time.  A pump on its own thread makes this rare. */
static int alsa_reopen(struct alsa *a)
{
    char err[200];
    const char *dev = a->dev;
    unsigned lat = a->latency_us;
    snd_pcm_t *pcm;
    if (a->pcm) { snd_pcm_close(a->pcm); a->pcm = NULL; }
    pcm = open_pcm(&dev, &lat, err, sizeof err, a->reopens < 2);
    if (!pcm) {
        if (!a->err_logged) { sel_log("audio: alsa reopen: %s", err); a->err_logged = 1; }
        return -1;
    }
    a->pcm = pcm;
    a->reopens++;
    a->last_accept_ms = sel_now_ms();
    a->first_logged = 0;
    if (a->reopens <= 3) sel_log("audio: alsa %s reopened after an underrun (#%d)", dev, a->reopens);
    return 0;
}
#endif

struct audio_sink *audio_alsa_open(char *err, int errlen)
{
    struct alsa *a;
    snd_pcm_t *pcm;
    const char *dev = NULL;
    size_t i;
    unsigned latency_us = ALSA_LATENCY_US;

    snd_lib_error_set_handler(quiet);
    /* the buffer asked for: the build's, or PADSELECT_ALSA_LATENCY_MS (the rig's
     * knob for trying another against a real sink without a rebuild) */
    {
        const char *e = getenv("PADSELECT_ALSA_LATENCY_MS");
        if (e && atoi(e) > 0) latency_us = (unsigned)atoi(e) * 1000u;
    }
    pcm = open_pcm(&dev, &latency_us, err, errlen, 1);
    if (!pcm) return NULL;
    a = calloc(1, sizeof *a);
    if (!a) { snd_pcm_close(pcm); snprintf(err, errlen, "out of memory"); return NULL; }
    a->base.name = "alsa";
    a->base.space = alsa_space;
    a->base.write = alsa_write;
    a->base.close = alsa_close;
    /* the build's own lead, as it always was: the granted buffer is only
     * logged, so the Stern card's sink behaves exactly as before item 120 */
    a->base.lead_ms = ALSA_LEAD_MS;
    a->pcm = pcm;
    a->dev = dev;
    a->latency_us = latency_us;
    a->last_accept_ms = sel_now_ms();
    sel_log("audio: alsa %s ok (%d ch, %d Hz)", dev, AUDIO_CH, AUDIO_RATE);
    /* THE LINE-OUT, over i2c, the way the game does it (codec.h): after
     * snd_pcm_set_params, so the kernel's own hw_params and DAPM writes are
     * done and cannot undo it.  The kernel powers only the headphone path
     * for a stream (the device tree routes nothing else); the amplifiers
     * hang off LINE_OUT, which only this powers. */
    codec_power_up();
    /* and the kernel's own 'Line Out Mute' switch, kept ON either way */
    for (i = 0; i < (size_t)NCTL; i++)
        a->lo_was[i] = lineout_switch(MIXER_CTLS[i], 1, "");
    return &a->base;
}

/* open ctl and look for simple mixer element `name` (index 0): the open
 * mixer in *mp when the attach worked (the caller closes it once, element
 * or not), the element or NULL.  Every failure is a log line naming the
 * step, never a fatal one. */
static snd_mixer_elem_t *mixer_find(const char *ctl, const char *name, snd_mixer_t **mp)
{
    snd_mixer_t *m = NULL;
    snd_mixer_selem_id_t *id;
    snd_mixer_elem_t *e;
    int rc;

    *mp = NULL;
    rc = snd_mixer_open(&m, 0);
    if (rc < 0) { sel_log("audio: mixer %s: open: %s", ctl, snd_strerror(rc)); return NULL; }
    rc = snd_mixer_attach(m, ctl);
    if (rc < 0) { sel_log("audio: mixer %s: attach: %s", ctl, snd_strerror(rc)); snd_mixer_close(m); return NULL; }
    rc = snd_mixer_selem_register(m, NULL, NULL);
    if (rc < 0) { sel_log("audio: mixer %s: register: %s", ctl, snd_strerror(rc)); snd_mixer_close(m); return NULL; }
    rc = snd_mixer_load(m);
    if (rc < 0) { sel_log("audio: mixer %s: load: %s", ctl, snd_strerror(rc)); snd_mixer_close(m); return NULL; }
    id = calloc(1, snd_mixer_selem_id_sizeof());
    if (!id) { snd_mixer_close(m); return NULL; }
    snd_mixer_selem_id_set_index(id, 0);
    snd_mixer_selem_id_set_name(id, name);
    e = snd_mixer_find_selem(m, id);
    free(id);
    *mp = m;
    return e;
}

/* LINEOUT_SWITCH on ctl: on = 1 / 0, the way the game's 0x1faad4 does it.
 * Returns what the switch read BEFORE (1/0), or -1 when the control has no
 * such switch, could not be read, or refused the write - the caller then
 * leaves it alone at close.  `note` ends the log line. */
static int lineout_switch(const char *ctl, int on, const char *note)
{
    snd_mixer_t *m;
    snd_mixer_elem_t *e = mixer_find(ctl, LINEOUT_SWITCH, &m);
    int was = -1, rc;

    if (!m) return -1;
    if (!e || !snd_mixer_selem_has_playback_switch(e)) {
        sel_log("audio: mixer %s: no '%s' switch (nothing to %s)", ctl, LINEOUT_SWITCH,
                on ? "unmute" : "restore");
        snd_mixer_close(m);
        return -1;
    }
    if (snd_mixer_selem_get_playback_switch(e, 0, &was) < 0) was = -1;
    rc = snd_mixer_selem_set_playback_switch_all(e, on ? 1 : 0);
    sel_log("audio: mixer %s '%s' switch %s (was %s)%s%s%s", ctl, LINEOUT_SWITCH, on ? "on" : "off",
            was < 0 ? "unreadable" : was ? "on" : "off", note,
            rc < 0 ? ": " : "", rc < 0 ? snd_strerror(rc) : "");
    snd_mixer_close(m);
    if (rc < 0) return -1;
    return was < 0 ? -1 : (was ? 1 : 0);
}

static int mixer_set(const char *ctl, int v63)
{
    snd_mixer_t *m;
    snd_mixer_elem_t *e = mixer_find(ctl, "PCM", &m);
    long lo = 0, hi = 0, value;
    int rc;

    if (!m) return -1;
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
