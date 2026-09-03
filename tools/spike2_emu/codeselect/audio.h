/* audio.h - the selector's sounds: a single-threaded s16 44100 Hz stereo
 * mixer (4 voices, saturating, master gain from volume=) paced to the wall
 * clock from the main loop, feeding ONE sink:
 *
 *   alsa       the machine: the game's own device, sysdefault:CARD=sgtl5000main
 *              through the rootfs libasound (audio_alsa.c, hand prototypes)
 *   fifo:PATH  the emulator: raw s16le into the rig's audio FIFO after
 *              declaring '44100 2' in the fmt file (audio_fifo.c)
 *   none       silence (still mixes into --audio-dump when one is given)
 *
 * WAVs must be RIFF PCM 16-bit 44100 Hz with 1 or 2 channels (mono is
 * duplicated at load); anything else is refused with a log line. Every
 * failure here is NON-FATAL: the menu runs silent rather than not at all.
 */
#ifndef CODESELECT_AUDIO_H
#define CODESELECT_AUDIO_H

#define AUDIO_RATE 44100
#define AUDIO_CH   2

struct audio_clip {
    int frames;
    short *pcm;               /* frames*2 interleaved stereo */
};

struct audio_clip *audio_load_wav(const char *path, char *err, int errlen);
void audio_clip_free(struct audio_clip *c);

/* A sink. write() takes `frames` interleaved stereo frames and returns how
 * many it accepted (the rest is counted as dropped); space() says how many
 * frames it can take right now (it owns the pacing: the FIFO paces to the
 * wall clock with a lead, ALSA reports its buffer space); close() drains,
 * closes and frees. */
struct audio_sink {
    const char *name;
    int  (*space)(struct audio_sink *s, long long now_ms);
    int  (*write)(struct audio_sink *s, const short *pcm, int frames);
    void (*close)(struct audio_sink *s);
    int  lead_ms;             /* how far ahead of real time the sink runs */
};

struct audio_sink *audio_fifo_open(const char *path, const char *fmt_path);
/* NULL = no ALSA on this box (snd_pcm_open failed); the reason in err */
struct audio_sink *audio_alsa_open(char *err, int errlen);
/* the game's codec curve on selem 'PCM' of ctl backbox + cabinet; 0 ok */
int  audio_alsa_mixer(int v63);
/* THE MACHINE'S OWN VOLUME as a software gain (0-100): the codec's
 * 192*(v/63)^0.2 curve, for a sink with no mixer to hand the number to
 * (the emulator's fifo, a dump); 0 stays silent */
int  audio_machine_gain(int v63);

struct audio;

/* mode: auto | alsa | fifo:PATH | none. fmt_path: the rig's fmt file (may be
 * NULL/""). volume 0..100. dump_path: raw s16le of everything mixed, or NULL.
 * Never returns NULL; a silent instance when nothing could be opened. Logs
 * 'audio: alsa <dev> ok' | 'audio: fifo <path> open' | 'audio: none (<reason>)'. */
struct audio *audio_open(const char *mode, const char *fmt_path, int volume, const char *dump_path);
int  audio_active(const struct audio *a);            /* 1 when a sink or a dump is live */
void audio_set_volume(struct audio *a, int volume);  /* the mix gain 0-100, after open */
const char *audio_sink_name(const struct audio *a);  /* "alsa" | "fifo" | "dump" | "none" */
/* start a clip on a free voice; loop = restart at the end. Voice id or -1. */
int  audio_play(struct audio *a, const struct audio_clip *c, int loop);
void audio_stop(struct audio *a, int voice);         /* short fade, then free */
int  audio_playing(const struct audio *a, int voice);
void audio_pump(struct audio *a, long long now_ms);  /* every loop iteration */
/* how long the sink runs ahead (ms): after a voice ends, keep pumping this
 * long before closing so the sink has really played it */
int  audio_lead_ms(const struct audio *a);
/* drain + close + log 'audio: N frames written, M dropped'; frees a */
void audio_close(struct audio *a);

#endif
