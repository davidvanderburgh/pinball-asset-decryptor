/* audio_alsa.c - the machine sink: the game's own playback device through
 * the rootfs libasound.so.2 (alsa-lib 1.0.28). No headers exist on the box,
 * so every prototype is hand-written (export list checked against
 * readelf --dyn-syms; the game itself uses the same entry points).
 *
 *   snd_lib_error_set_handler(quiet)      alsa-lib's stderr chain stays out of the console log
 *   snd_pcm_open(<ALSA_DEVICES[] in order>, PLAYBACK, 0)
 *       any failure = 'no alsa' (-19 in the emulator chroot). NEVER the
 *       'null' device: alsa-lib 1.0.28 asserts inside hw_params on it.
 *   snd_pcm_set_params(S16_LE=2, RW_INTERLEAVED=3, 2 ch, 44100, resample 1, 500 ms)
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
#define LATENCY_US    500000
#define LEAD_MS       500
#define CHUNK_FRAMES  1764          /* the game's period size */

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
 * (The game's other mute stage is byte 7 of the cabinet SPI word - its
 * 0x5a9eac(4 | 32, mute) sets a bit to mute and clears it to play - and
 * input_hw.c has always sent that word as zeros, the unmuted value, from
 * the moment the SPI opens.  That gate was open all along.)
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
    snd_pcm_t *pcm;
    int err_logged, recovered;
    int lo_was[NCTL];         /* LINEOUT_SWITCH per MIXER_CTLS before we touched it: 1/0, -1 = none/unknown */
};

static int lineout_switch(const char *ctl, int on, const char *note);

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

struct audio_sink *audio_alsa_open(char *err, int errlen)
{
    struct alsa *a;
    snd_pcm_t *pcm = NULL;
    const char *dev = NULL;
    size_t i;
    int rc = -1;

    snd_lib_error_set_handler(quiet);
    err[0] = 0;
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
    rc = snd_pcm_set_params(pcm, SND_PCM_FORMAT_S16_LE, SND_PCM_ACCESS_RW_INTERLEAVED,
                            AUDIO_CH, AUDIO_RATE, 1, LATENCY_US);
    if (rc < 0) {
        snprintf(err, errlen, "%s: snd_pcm_set_params: %s", dev,
                 snd_strerror(rc));
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
