/* alsastub.c - a fake ALSA card.
 *
 * There is no sound hardware and no snd-dummy module inside the container, so
 * snd_mixer_find_selem() returns NULL and the game hands that straight to
 * snd_mixer_selem_get_playback_volume_range(), which asserts. The game calls
 * only 36 libasound entry points, so interposing them is enough to give it a
 * card that accepts every frame it writes.
 *
 * PAD_AUDIO_OUT names a file to receive the raw interleaved PCM the game
 * plays, which is the cheapest way to hear what a triggered mode does.
 *
 * PAD_AUDIO_PLAY names a FIFO to receive the same PCM live, so it can be played
 * out of the WSL side to the Windows speakers. The write is NON-BLOCKING and
 * drops on EAGAIN on purpose: a FIFO with no reader, or a reader that falls
 * behind, must never be able to stall the emulated game. A gap in the sound is
 * a nuisance; a wedged guest spinning at 140% CPU is the one failure mode this
 * rig must never create.
 */

extern void *dlsym(void *, const char *);
#define RTLD_NEXT ((void *)-1L)
extern long write(int, const void *, unsigned long);
extern int open(const char *, int, ...);
extern int close(int);
extern char *getenv(const char *);
extern int snprintf(char *, unsigned long, const char *, ...);
extern int *__errno_location(void);
extern int fcntl(int, int, ...);
extern int ioctl(int, unsigned long, ...);

#define O_WRONLY    1
#define O_NONBLOCK  0x800
#define E_AGAIN     11
#define E_PIPE      32
#define F_SETPIPE_SZ 1031
#define F_GETPIPE_SZ 1032

#define RATE      48000
#define CHANNELS  2
#define PERIOD    1024
#define BUFFER    8192

/* Routed through hwshim.c's logmsg so these lines get the PAD_LOG_TIME stamp.
 * Writing straight to fd 2 meant every [alsa] line was untimestamped even with
 * PAD_LOG_TIME=1, which made "how often does the game touch the mixer" an
 * unanswerable question in the middle of an audio investigation. */
extern void pad_say(const char *);
static void say(const char *s) { pad_say(s); }
static long play_scaled(int fd, const void *buf, unsigned long bytes);

/* Forward declaration: snd_pcm_hw_params_get_buffer_size() below reports this
 * and is defined long before it. Without this the call compiles as an implicit
 * int-returning function and the real definition then collides with it. */
static long buf_frames(void);

/* ---------------- PCM ---------------- */

/* The game opens TWO cards, sgtl5000main and sgtl5000center. They used to share
 * one fake handle, so nothing downstream could tell them apart and the capture
 * file was whichever of them happened to write - two streams interleaved into
 * one. Distinct handles, and the writes are attributed. */
#define NPCM 4
static char pcm_obj[NPCM][64];
static char pcm_name[NPCM][32];
static int  pcm_n;
static char params_obj[2048];

static int pcm_index(void *p)
{
    int i;
    for (i = 0; i < pcm_n; i++) if (p == (void *)pcm_obj[i]) return i;
    return 0;
}

int snd_pcm_open(void **pcm, const char *name, int stream, int mode)
{
    char line[160];
    int i = pcm_n < NPCM ? pcm_n++ : NPCM - 1;
    unsigned k;
    (void)stream; (void)mode;
    for (k = 0; name && name[k] && k < sizeof pcm_name[0] - 1; k++)
        pcm_name[i][k] = name[k];
    if (pcm) *pcm = pcm_obj[i];
    snprintf(line, sizeof line, "[alsa] snd_pcm_open(\"%s\") -> fake card #%d\n",
             name ? name : "(null)", i);
    say(line);
    return 0;
}

/* THESE ARE LOGGED because a stream that restarts ~10 times a second is exactly
 * what an XRUN-recovery loop looks like from outside, and prepare/drain are how
 * a caller performs one. They were silent no-ops, so the one question worth
 * asking about a retriggering sound - "is the game tearing the stream down and
 * building it again?" - could not be answered at all. Counted, not just logged,
 * because at 10 Hz the log alone would drown everything else. */
static unsigned long alsa_prepare_n, alsa_drain_n, alsa_close_n, alsa_nonblock_n;

static void alsa_call(const char *what, unsigned long *n, int card)
{
    char line[120];
    (*n)++;
    if (*n <= 8 || (*n % 50) == 0) {
        snprintf(line, sizeof line, "[alsa] %s card #%d (call #%lu)\n",
                 what, card, *n);
        say(line);
    }
}

int snd_pcm_close(void *pcm)
{ alsa_call("snd_pcm_close", &alsa_close_n, pcm_index(pcm)); return 0; }
int snd_pcm_prepare(void *pcm)
{ alsa_call("snd_pcm_prepare", &alsa_prepare_n, pcm_index(pcm)); return 0; }
int snd_pcm_drain(void *pcm)
{ alsa_call("snd_pcm_drain", &alsa_drain_n, pcm_index(pcm)); return 0; }
int snd_pcm_nonblock(void *pcm, int on)
{ (void)on; alsa_call("snd_pcm_nonblock", &alsa_nonblock_n, pcm_index(pcm)); return 0; }

unsigned long snd_pcm_hw_params_sizeof(void) { return sizeof params_obj; }
int snd_pcm_hw_params_any(void *pcm, void *p) { (void)pcm; (void)p; return 0; }
int snd_pcm_hw_params(void *pcm, void *p) { (void)pcm; (void)p; return 0; }
int snd_pcm_hw_params_current(void *pcm, void *p) { (void)pcm; (void)p; return 0; }

/* The requested format used to be thrown away, so RATE/CHANNELS below were an
 * ASSUMPTION - and everything that reads the capture (pitch, duration, the
 * player's -ar) inherits it. Record what the game actually asks for and say so
 * once, so nobody has to guess 44100 vs 48000 off the file size again. */
unsigned pad_pcm_rate = RATE;          /* card #0's rate: what actually plays */
unsigned pad_pcm_channels = CHANNELS;
/* PER CARD, because they are configured independently and they DIFFER: the game
 * asks for 48000 on one and 44100 on the other. A single global recorded
 * whichever was configured last, so the player was told 44100 while card #0 -
 * the one being played - was running at 48000. */
static unsigned pcm_rate[NPCM];
static unsigned pcm_ch[NPCM];

/* Reported on every CHANGE, not once. The first version said it once and so
 * recorded "48000 Hz" while the stream that actually played was 44100 - the two
 * cards are configured separately and the second one moved it. A player started
 * on the wrong number plays ~9% sharp, which is exactly the kind of thing that
 * gets blamed on the codec.
 *
 * The format is also written to PAD_AUDIO_FMT, because the player has to know
 * the rate BEFORE it opens the fifo: it cannot be told over the fifo itself
 * (the guest's non-blocking open fails until a reader exists, and the reader is
 * waiting for the rate - a deadlock). Written from the CONFIGURE call, which
 * happens long before the first frame. */
static void note_fmt(int card)
{
    static unsigned last_rate, last_ch;
    char line[128];
    int fd;
    if (card >= 0 && card < NPCM) {
        if (!pcm_rate[card]) pcm_rate[card] = RATE;
        if (!pcm_ch[card]) pcm_ch[card] = CHANNELS;
    }
    /* card #0 is the one routed to the speakers, so it is the one the player
     * must be told about. */
    if (pcm_rate[0]) pad_pcm_rate = pcm_rate[0];
    if (pcm_ch[0]) pad_pcm_channels = pcm_ch[0];
    snprintf(line, sizeof line, "[alsa] card #%d asked for %u Hz x %u ch\n",
             card, card >= 0 && card < NPCM ? pcm_rate[card] : 0,
             card >= 0 && card < NPCM ? pcm_ch[card] : 0);
    say(line);
    if (pad_pcm_rate == last_rate && pad_pcm_channels == last_ch) return;
    last_rate = pad_pcm_rate;
    last_ch = pad_pcm_channels;
    {
        const char *p = getenv("PAD_AUDIO_FMT");
        if (p && *p) {
            fd = open(p, 0x241 /* O_WRONLY|O_CREAT|O_TRUNC */, 0644);
            if (fd >= 0) {
                unsigned n = 0;
                snprintf(line, sizeof line, "%u %u\n",
                         pad_pcm_rate, pad_pcm_channels);
                while (line[n]) n++;
                write(fd, line, n);
                close(fd);
            }
        }
    }
}

int snd_pcm_hw_params_set_access(void *pcm, void *p, int a) { (void)pcm; (void)p; (void)a; return 0; }
int snd_pcm_hw_params_set_format(void *pcm, void *p, int f) { (void)pcm; (void)p; (void)f; return 0; }
int snd_pcm_hw_params_set_channels(void *pcm, void *p, unsigned c)
{
    int i = pcm_index(pcm);
    (void)p;
    if (c) { pcm_ch[i] = c; note_fmt(i); }
    return 0;
}
int snd_pcm_hw_params_set_rate(void *pcm, void *p, unsigned r, int d)
{
    int i = pcm_index(pcm);
    (void)p; (void)d;
    if (r) { pcm_rate[i] = r; note_fmt(i); }
    return 0;
}
int snd_pcm_hw_params_set_rate_near(void *pcm, void *p, unsigned *r, int *d)
{
    int i = pcm_index(pcm);
    (void)p; (void)d;
    if (r) {
        if (*r == 0) *r = RATE;
        else { pcm_rate[i] = *r; note_fmt(i); }
    }
    return 0;
}
int snd_pcm_hw_params_set_period_size(void *pcm, void *p, unsigned long s, int d)
{ (void)pcm; (void)p; (void)s; (void)d; return 0; }
int snd_pcm_hw_params_set_buffer_size(void *pcm, void *p, unsigned long s)
{ (void)pcm; (void)p; (void)s; return 0; }

int snd_pcm_hw_params_get_rate(const void *p, unsigned *v, int *d)
{ (void)p; if (v) *v = RATE; if (d) *d = 0; return 0; }
int snd_pcm_hw_params_get_channels(const void *p, unsigned *v)
{ (void)p; if (v) *v = CHANNELS; return 0; }
int snd_pcm_hw_params_get_format(const void *p, int *v)
{ (void)p; if (v) *v = 2; return 0; }          /* SND_PCM_FORMAT_S16_LE */
int snd_pcm_hw_params_get_period_size(const void *p, unsigned long *v, int *d)
{ (void)p; if (v) *v = PERIOD; if (d) *d = 0; return 0; }
int snd_pcm_hw_params_get_period_time(const void *p, unsigned *v, int *d)
{ (void)p; if (v) *v = (unsigned)((1000000ULL * PERIOD) / RATE); if (d) *d = 0; return 0; }
int snd_pcm_hw_params_get_buffer_size(const void *p, unsigned long *v)
{ (void)p; if (v) *v = (unsigned long)buf_frames(); return 0; }

/* ---- pacing -------------------------------------------------------------
 *
 * A real card paces the game two ways: snd_pcm_avail() reports how much room is
 * left, and snd_pcm_writei() BLOCKS when there is none. The stub only did the
 * first, and the game only imports those two symbols - measured, `objdump -T`
 * on the game lists snd_pcm_avail and snd_pcm_writei and nothing else - so the
 * stub was the only thing that could throttle it and it did not.
 *
 * The result: 24.3 million frames in 100 s, i.e. 550 seconds of audio produced
 * in 100 seconds of wall clock. Everything downstream then has to throw ~90% of
 * it away, which is what "no sound" actually sounded like once the pipe existed.
 *
 * Both counters are now PER CARD. Sharing one made each card see the other's
 * frames as its own backlog, which is wrong in both directions.
 */
static unsigned long long frames_written;             /* total, for the log */
static unsigned long long card_written[NPCM];
static unsigned long long card_t0[NPCM];
static unsigned long long card_queued[NPCM];   /* the leaky bucket, in frames */
static unsigned long long t0_us;
extern int clock_gettime(int, void *);
extern int usleep(unsigned);
struct ts { long sec, nsec; };

/* PAD-932: THE RAW MONOTONIC CLOCK, NOT THE WALL'S.  This bucket drains at
 * the rate time passes, so whatever moves the clock moves the sound.  It read
 * gettimeofday, and the wall clock is the one clock that gets SET: on WSL 2
 * every distro shares one kernel and one clock, so systemd-timesyncd in the
 * user's own Ubuntu (or Windows' resync after a sleep) steps it under a rig
 * running in PAD-Runtime, which has no time service at all.  Every step,
 * either way, emptied the bucket at once and the game wrote a whole buffer
 * ahead in one burst - measured on Godzilla Pro, 0.4 s of sound extra at each
 * of two 2 s steps - stutter on Deadpool and Jurassic Park (David,
 * 2026-11-01) that went away when he disabled timesyncd.
 *
 * RAW, because what timesyncd does most is not step but SLEW (offsets under
 * 0.4 s), and a slew speeds or slows CLOCK_MONOTONIC too, by up to 500 ppm.
 * MONOTONIC_RAW is the hardware's (Hyper-V's reference clock on WSL) and
 * nothing disciplines it.  The plain symbol is hwshim's interposer, so pause
 * and game speed still apply, as they do to gstvid's video schedule. */
static unsigned long long now_us(void)
{
    struct ts t;
    clock_gettime(4 /* CLOCK_MONOTONIC_RAW */, &t);
    return (unsigned long long)t.sec * 1000000ULL + (unsigned long long)t.nsec / 1000ULL;
}

static unsigned card_rate(int i)
{
    return pcm_rate[i] ? pcm_rate[i] : RATE;
}

/* PAD_AUDIO_BUFFER=<frames> - what snd_pcm_avail() reports room against, and
 * what card_pace() blocks on. A knob because BUFFER is the only number in this
 * stub with a period anywhere near the ~100 ms of the boot retrigger (8192
 * frames is 186 ms, half of it 93 ms), and the way to find out whether the
 * retrigger is OURS is to move this and see whether the retrigger moves with
 * it. Reading the two as related without testing it would be a guess. */
static long buf_frames(void)
{
    static long v = -1;
    if (v < 0) {
        const char *e = getenv("PAD_AUDIO_BUFFER");
        v = BUFFER;
        if (e && *e) {
            long n = 0;
            while (*e >= '0' && *e <= '9') n = n * 10 + (*e++ - '0');
            if (n > 0) v = n;
        }
    }
    return v;
}

/* Frames this card has queued but not yet played, draining at wall-clock speed.
 *
 * A LEAKY BUCKET, and it has to be, which the first version of this was not.
 * That one measured `written - elapsed_since_the_very_first_write * rate` and
 * clamped the result at zero. The game is silent most of the time, so elapsed
 * ran away from written and the clamp meant this returned **0 for the entire
 * run** - snd_pcm_avail() always offered the full buffer, card_pace() never
 * blocked once, and the card effectively advertised INFINITE room. Every gap in
 * the game's output became credit it could spend on one instantaneous burst
 * later. A real card gives no such credit: silence you never sent is not room
 * you have banked.
 *
 * The visible cost was two things at once, which is why it was hard to name:
 * bursts overran the FIFO (172600 of 291000 frames dropped on card 0 at a 64 KB
 * pipe), and where the FIFO was big enough to swallow them instead, they simply
 * played out at 1x and everything queued behind them arrived late. */
static long card_backlog(int i)
{
    unsigned long long t = now_us();
    unsigned rate = card_rate(i);
    unsigned long long drained;
    if (!rate) return 0;
    if (!card_t0[i]) { card_t0[i] = t; return (long)card_queued[i]; }
    /* A clock behind the last reading drains nothing, rather than wrapping
     * into a huge unsigned gap. */
    if (t < card_t0[i]) { card_t0[i] = t; return (long)card_queued[i]; }
    drained = ((t - card_t0[i]) * rate) / 1000000ULL;
    if (drained) {
        /* Advance the clock by exactly the frames accounted for, so the
         * remainder is carried rather than repeatedly rounded away. */
        card_t0[i] += drained * 1000000ULL / rate;
        card_queued[i] = card_queued[i] > drained ? card_queued[i] - drained : 0;
    }
    return (long)card_queued[i];
}

long snd_pcm_avail(void *pcm)
{
    long room = buf_frames() - card_backlog(pcm_index(pcm));
    return room < 0 ? 0 : room;
}

/* Block like a real card would. Capped hard: this runs on the game's audio
 * thread and an uncapped wait here is exactly the class of bug that leaves a
 * guest wedged at 140% CPU. PAD_AUDIO_PACE=0 disables it.
 *
 * THE CAP IS NOT WHERE THE PACING COMES FROM, and widening it is a trap worth
 * recording. The runaway - 366 SECONDS of audio written in the first 10 s,
 * measured with PAD_AUDIO_PACE=0 - is stopped by card_backlog() being a real
 * leaky bucket, which makes snd_pcm_avail() report a full card and the game
 * throttle itself. Blocking here is only the backstop for a game that writes
 * anyway. Widening it to 400 x 2 ms did nothing for drops (already 0) and took
 * boot voice restarts 3 -> 5, because a longer block on the game's own audio
 * thread is exactly the starvation the boot buzz is made of. Left at the
 * original 0.2 s; PAD_AUDIO_PACE_MS moves it if a case ever needs it. */
static void card_pace(int i)
{
    static int on = -1;
    static long cap_ms = -1;
    int spins = 0;
    if (on == -1) {
        const char *p = getenv("PAD_AUDIO_PACE");
        on = !(p && p[0] == '0');
    }
    if (!on) return;
    if (cap_ms < 0) {
        const char *e = getenv("PAD_AUDIO_PACE_MS");
        long n = 0;
        cap_ms = 200;
        if (e && *e) {
            while (*e >= '0' && *e <= '9') n = n * 10 + (*e++ - '0');
            if (n > 0) cap_ms = n;
        }
    }
    while (card_backlog(i) > buf_frames() && spins++ < cap_ms / 5)
        usleep(5000);
}

static int out_fd = -1;          /* card 0, sgtl5000main - what you hear */
static int out_fd_other = -1;    /* card 1, sgtl5000center - captured separately */
static int out_tried;

/* Deliberately NOT static: hwshim.c's PAD_AUDIO_DUMP reads these. The two files
 * are separate translation units linked into the one hwshim.so, so a plain
 * global crosses. This is the only honest answer to "does the game produce any
 * PCM at all" - every other audio number in this rig is upstream of here. */
unsigned long pad_pcm_frames;
unsigned long pad_pcm_calls;
int pad_pcm_card;        /* which of the two cards wrote last */

/* ---- live playback to the WSL side ----
 *
 * A FIFO, drained by ffmpeg into WSLg's PulseAudio (see playaudio.sh). Opened
 * O_NONBLOCK so a missing reader gives ENXIO instead of blocking forever in
 * open(), and written O_NONBLOCK so a slow reader gives EAGAIN instead of
 * blocking forever in write(). Both are dropped, counted and reported. */
static int play_fd = -1;
static unsigned long long play_dropped, play_written, play_next_try;
static unsigned long long pad_pcm_other;   /* frames the CENTER card wrote */

static void play_open(void)
{
    const char *path = getenv("PAD_AUDIO_PLAY");
    char line[200];
    if (!path || !*path) return;
    /* Retry about once a second of audio: the player is started alongside the
     * renderer and may not have opened the read end yet when the game's first
     * frames arrive. One attempt would silently mean no sound for the run. */
    if (frames_written < play_next_try) return;
    play_next_try = frames_written + pad_pcm_rate;
    play_fd = open(path, O_WRONLY | O_NONBLOCK);
    if (play_fd >= 0) {
        /* THE PIPE IS A LATENCY BUDGET, NOT JUST A SAFETY MARGIN, and it was
         * sized as though it were only the latter.
         *
         * It used to be forced to 1 MB - 5.9 SECONDS at 44100x2x16 - to stop
         * EAGAIN drops back when the game's bursts met a 64 KB default and 87%
         * of every period was lost. That fixed the stutter and quietly bought a
         * multi-second worst case: producer and consumer both run at 1x, so
         * whatever backlog a hiccup puts in this pipe NEVER drains, it just
         * becomes permanent lateness. card_backlog() cannot see it either -
         * that model assumes the far end consumes in real time - so the `[aud]
         * latency=` figure is a FLOOR, not the whole story.
         *
         * DO NOT just shrink it: tried at 64 KB and 172600 of 291000 frames on
         * card 0 were dropped, because at that point card_backlog() was broken
         * and nothing paced the game at all. The pacing is the fix; the pipe
         * size is only the backstop. 1 MB stays the default so a bad pacing
         * regression is audible as lateness rather than as shredded audio, and
         * `pipe=` on the [aud] line says what is really sitting in it.
         * PAD_AUDIO_FIFO_KB tunes it. Failure is harmless: kernel default. */
        {
            const char *e = getenv("PAD_AUDIO_FIFO_KB");
            long kb = 1024;
            if (e && *e) {
                long n = 0;
                while (*e >= '0' && *e <= '9') n = n * 10 + (*e++ - '0');
                if (n > 0) kb = n;
            }
            fcntl(play_fd, F_SETPIPE_SZ, (int)(kb << 10));
        }
        snprintf(line, sizeof line,
                 "[alsa] playing to %s (%u Hz x %u ch s16le, pipe %d bytes = %lu ms)\n",
                 path, pad_pcm_rate, pad_pcm_channels,
                 fcntl(play_fd, F_GETPIPE_SZ, 0),
                 pad_pcm_rate && pad_pcm_channels
                     ? (unsigned long)fcntl(play_fd, F_GETPIPE_SZ, 0) * 1000UL
                           / (pad_pcm_rate * pad_pcm_channels * 2UL)
                     : 0UL);
        say(line);
    }
}

long snd_pcm_writei(void *pcm, const void *buf, unsigned long frames)
{
    int card = pcm_index(pcm);
    unsigned long bytes = frames * (pcm_ch[card] ? pcm_ch[card] : CHANNELS) * 2;
    /* PAD_AUDIO_TRACE=<n> - log the first n writei calls per card: how many
     * frames, from what address, and the first two samples.
     *
     * This exists because the captured PCM turned out to repeat BYTE-IDENTICALLY
     * every 2200 frames, and "the game hands us the same block over and over"
     * and "the game hands us advancing blocks that happen to contain the same
     * audio" are completely different faults with the same capture. Only the
     * call itself can tell them apart. */
    {
        static int trace = -1;
        static unsigned long traced[NPCM];
        if (trace < 0) {
            const char *e = getenv("PAD_AUDIO_TRACE");
            trace = 0;
            if (e && *e) { while (*e >= '0' && *e <= '9') trace = trace * 10 + (*e++ - '0'); }
        }
        if (trace > 0 && card >= 0 && card < NPCM && traced[card] < (unsigned long)trace) {
            const short *s = (const short *)buf;
            char line[160];
            traced[card]++;
            snprintf(line, sizeof line,
                     "[alsa] writei card #%d n=%lu buf=%p [0]=%d [1]=%d\n",
                     card, frames, buf, s ? s[0] : 0, s ? s[1] : 0);
            say(line);
        }
    }
    /* PAD_LATENCY=1 - the other end of the latency probe; see lat_on() in
     * hwshim.c. The game writes NOTHING while nothing is making a sound, so a
     * writei after a gap is the game answering an event. Against hwshim's
     * "[lat] switch gen=N observed" line on the same clock, the difference is
     * how long the GAME took, with no buffering in it at all. */
    {
        static int lat = -1;
        static unsigned long long last_us;
        unsigned long long t;
        if (lat < 0) { const char *e = getenv("PAD_LATENCY"); lat = (e && *e && *e != '0'); }
        if (lat) {
            t = now_us();
            if (last_us && t - last_us > 200000ULL) {
                char line[120];
                snprintf(line, sizeof line,
                         "[lat] pcm resumed on card #%d after %lu ms of silence\n",
                         card, (unsigned long)((t - last_us) / 1000ULL));
                say(line);
            }
            last_us = t;
        }
    }
    card_pace(card);
    card_backlog(card);                  /* drain first, then enqueue */
    card_queued[card] += frames;
    card_written[card] += frames;
    pad_pcm_calls++;
    pad_pcm_frames += frames;
    pad_pcm_card = card;
    /* ONE FILE PER CARD, and this was a real trap.
     *
     * This used to write BOTH cards into the single PAD_AUDIO_OUT file, while
     * only card 0 is ever played to the speakers (see below). main and center
     * are independent streams, so the capture was the two of them interleaved
     * in whatever order they happened to be written - the same "noise, not a
     * mix" the comment below warns about, except silently, in the file everyone
     * reaches for when they want to know what the game sounded like.
     *
     * It produced a convincing artefact: an envelope that ramps up over ~100 ms
     * and cuts back to zero, over and over at ~10 Hz, which reads exactly like
     * a sound being retriggered ten times a second. It is not - it is two
     * streams' periods alternating. Anything measured off the old combined file
     * is measuring the capture, not the game. Card 0 is what you hear;
     * PAD_AUDIO_OUT is now card 0 alone and the centre channel goes to
     * "<path>.center". */
    if (!out_tried) {
        const char *path = getenv("PAD_AUDIO_OUT");
        out_tried = 1;
        if (path && *path) {
            char other[256];
            unsigned i = 0;
            out_fd = open(path, 0x241 /* O_WRONLY|O_CREAT|O_TRUNC */, 0644);
            while (path[i] && i < sizeof other - 8) { other[i] = path[i]; i++; }
            other[i++] = '.'; other[i++] = 'c'; other[i++] = 'e';
            other[i++] = 'n'; other[i++] = 't'; other[i++] = 'e';
            other[i++] = 'r'; other[i] = 0;
            out_fd_other = open(other, 0x241, 0644);
            say("[alsa] capturing PCM: card 0 -> PAD_AUDIO_OUT, card 1 -> .center\n");
        }
    }
    if (buf) {
        int fd = (card == 0) ? out_fd : out_fd_other;
        if (fd >= 0) write(fd, buf, bytes);
    }

    /* ONLY card #0 (sgtl5000main) is played. The game opens two cards, main and
     * center, and they are independent streams: shovelling both down one fifo
     * interleaves them and what comes out is noise, not a mix. Playing the main
     * card is the honest first cut; mixing the centre channel in properly needs
     * a real mixer and is a separate job. */
    if (card != 0) {
        pad_pcm_other += frames;
        if (!t0_us) t0_us = now_us();
        frames_written += frames;
        return (long)frames;
    }

    if (play_fd < 0) play_open();
    if (play_fd >= 0 && buf) {
        long r = play_scaled(play_fd, buf, bytes);
        if (r < 0) {
            int e = *__errno_location();
            if (e == E_PIPE) {           /* player exited - stop and retry later */
                close(play_fd);
                play_fd = -1;
                play_next_try = frames_written + pad_pcm_rate;
                say("[alsa] audio player went away\n");
            }
            play_dropped += frames;      /* EAGAIN: reader behind, drop the period */
        } else {
            play_written += frames;
        }
    }

    if (!t0_us) t0_us = now_us();
    frames_written += frames;
    return (long)frames;
}

/* Exposed for PAD_AUDIO_DUMP, so "no sound" can be split into "the game wrote
 * nothing", "we dropped it" and "it went out and you still cannot hear it". */
unsigned long pad_pcm_played(void) { return (unsigned long)play_written; }
unsigned long pad_pcm_drops(void)  { return (unsigned long)play_dropped; }
unsigned long pad_pcm_center(void) { return (unsigned long)pad_pcm_other; }

/* HOW FAR AHEAD OF THE SPEAKER THE GAME HAS WRITTEN, in ms. This is the rig's
 * audio LATENCY, and it is not an accident: snd_pcm_avail() offers room up to
 * buf_frames() and card_pace() blocks past it, so a game that keeps its card fed
 * sits permanently at that limit. Everything written is already in the FIFO, so
 * this number IS the fifo depth. PAD_AUDIO_BUFFER moves it directly.
 * The pulse buffer in playaudio.sh adds to it and is not counted here. */
unsigned long pad_pcm_backlog_ms(void)
{
    unsigned r = card_rate(0);
    if (!r) return 0;
    /* 64-bit on purpose: `long` is 32 bits on this target and the backlog has
     * been seen at 16 million frames, so frames*1000 overflows and prints as a
     * huge bogus number. A broken instrument in the middle of a latency hunt is
     * worse than no instrument. */
    return (unsigned long)((unsigned long long)card_backlog(0) * 1000ULL / r);
}
unsigned long pad_pcm_buffer_ms(void)
{
    unsigned r = card_rate(0);
    if (!r) return 0;
    return (unsigned long)(buf_frames() * 1000 / (long)r);
}

/* WHAT IS ACTUALLY SITTING IN THE FIFO, in ms - the term card_backlog() cannot
 * see, because that models our own queue and not the far end's. FIONREAD on a
 * pipe reports the unread bytes regardless of which end the fd is, so the guest
 * can read it off the write end it already holds. This is the honest answer to
 * "is the sound late", and no amount of reasoning about the producer replaces
 * it: the consumer is ffmpeg and PulseAudio, neither of which we control. */
unsigned long pad_pcm_fifo_ms(void)
{
    int n = 0;
    unsigned long bps;
    if (play_fd < 0 || !pad_pcm_rate || !pad_pcm_channels) return 0;
    if (ioctl(play_fd, 0x541B /* FIONREAD */, &n) < 0 || n <= 0) return 0;
    bps = (unsigned long)pad_pcm_rate * pad_pcm_channels * 2UL;
    return bps ? (unsigned long)n * 1000UL / bps : 0;
}

/* ---------------- mixer ----------------
 *
 * PAD-1302: THE SERVICE-MENU VOLUME. The game sets its volume the way it does
 * on the machine: alsa-lib's simple mixer, the SGTL5000's PCM volume on ctl
 * `backbox` and on ctl `cabinet`, at bring-up and on every change from the
 * menu or the coin-door buttons (codeselect/audio_alsa.c: the godzilla_pro
 * recipe 0x1fa490 writes 192*(v/63)^0.2). This mixer used to be one shared
 * fake element that said its range was 0..100 and threw every value away, so
 * a run always played at full level whatever the menu said.
 *
 * Now each mixer remembers the ctl it was attached to and each element its
 * name, the range is the codec's own 0..192 (0xfc - 0x3c), and a value is read
 * the way the codec reads it: 192 = 0 dB, every step below is 0.5 dB quieter,
 * 0 = mute. That gain scales ONLY what goes to the speakers (the FIFO), never
 * the PAD_AUDIO_OUT capture, which stays the game's own full-level PCM for
 * every tool that matches it against the sound banks. Card 0 (`backbox`, the
 * one we play) takes its gain from ctl backbox. PAD_GAME_VOLUME=0 plays full
 * level as before. "Line Out Mute" is recorded and logged but never mutes:
 * the machine's real speaker gate is the SPI amplifier enable (codeselect
 * input_hw.c), and this switch read ON on David's machine either way.
 */

#define MIX_MAX   8
#define ELEM_MAX  16
#define PCM_VOL_MAX 192L

struct fake_mixer { int used; int card; char ctl[32]; };
struct fake_elem  { int used; int card; char name[48]; long vol; int sw; };
static struct fake_mixer mixers[MIX_MAX];
static struct fake_elem  elems[ELEM_MAX];
static struct fake_elem  elem_spare;      /* table full: the old behaviour */

/* The gain each card's PCM is scaled by on its way to the speakers, Q16
 * (65536 = the game's full level). Written by the mixer, read by
 * snd_pcm_writei; an aligned int is never torn on ARM. */
static int card_gain_q16[NPCM] = { 65536, 65536, 65536, 65536 };

static int str_eq(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}
static void str_cpy(char *d, const char *s, unsigned n)
{
    unsigned i = 0;
    if (!n) return;
    while (s && s[i] && i + 1 < n) { d[i] = s[i]; i++; }
    d[i] = 0;
}
static int has_word(const char *s, const char *w)
{
    for (; s && *s; s++) {
        const char *a = s, *b = w;
        while (*a && *b && *a == *b) { a++; b++; }
        if (!*b) return 1;
    }
    return 0;
}

/* Which of our PCM cards a mixer ctl is. The game's own names first
 * (asound.conf: ctl backbox = card 0 sgtl5000main, ctl cabinet = card 1
 * sgtl5000center), then the raw spellings a title might use instead.
 * -1: none we know. */
static int ctl_card(const char *ctl)
{
    if (!ctl || !*ctl) return -1;
    if (has_word(ctl, "backbox") || has_word(ctl, "main") || str_eq(ctl, "hw:0")
        || str_eq(ctl, "default") || has_word(ctl, "CARD=0"))
        return 0;
    if (has_word(ctl, "cabinet") || has_word(ctl, "center") || str_eq(ctl, "hw:1")
        || has_word(ctl, "CARD=1"))
        return 1;
    return -1;
}

static int game_volume_on(void)
{
    static int on = -1;
    if (on < 0) {
        const char *e = getenv("PAD_GAME_VOLUME");
        on = !(e && e[0] == '0' && !e[1]);
        if (!on) say("[alsa] PAD_GAME_VOLUME=0: the game's volume is ignored, full level\n");
    }
    return on;
}

/* The codec's curve, without libm (this .so is -nostdlib): 0.5 dB a step
 * below 192, so the gain is 10^(-0.025) to the power of the steps. */
int pad_pcm_vol_gain_q16(long v)
{
    double g = 65536.0;
    long k;
    if (v <= 0) return 0;
    if (v >= PCM_VOL_MAX) return 65536;
    for (k = v; k < PCM_VOL_MAX; k++) g *= 0.94406087628592;   /* -0.5 dB */
    return (int)(g + 0.5);
}

static void mixer_apply(struct fake_elem *el)
{
    char line[200];
    int q, tenths;
    if (el->card < 0 || el->card >= NPCM) return;
    q = game_volume_on() ? pad_pcm_vol_gain_q16(el->vol) : 65536;
    /* ONLY "PCM" is the speakers' volume. Godzilla also sets "Headphone" on
     * ctl backbox (48/192 at boot): the codec's headphone amplifier, which
     * the speakers never pass through - letting it set card 0's gain put a
     * run 72 dB down. Every other element is logged and left alone. */
    if (!str_eq(el->name, "PCM")) {
        snprintf(line, sizeof line, "[alsa] game volume: \"%s\" on card #%d = %ld/%ld (not the speakers: logged only)\n",
                 el->name, el->card, el->vol, PCM_VOL_MAX);
        say(line);
        return;
    }
    card_gain_q16[el->card] = q;
    tenths = (int)((PCM_VOL_MAX - el->vol) * 5);      /* 0.5 dB = 5 tenths */
    if (el->vol <= 0)
        snprintf(line, sizeof line, "[alsa] game volume: \"%s\" on card #%d = 0/%ld (mute)%s\n",
                 el->name, el->card, PCM_VOL_MAX, el->card ? " (card not played)" : "");
    else
        snprintf(line, sizeof line,
                 "[alsa] game volume: \"%s\" on card #%d = %ld/%ld (-%d.%d dB, gain %d/65536)%s\n",
                 el->name, el->card, el->vol, PCM_VOL_MAX, tenths / 10, tenths % 10, q,
                 el->card ? " (card not played)" : "");
    say(line);
}

int snd_mixer_open(void **mixer, int mode)
{
    int i;
    (void)mode;
    for (i = 0; i < MIX_MAX && mixers[i].used; i++) ;
    if (i == MIX_MAX) i = MIX_MAX - 1;         /* reuse the last: never fail the game */
    mixers[i].used = 1;
    mixers[i].card = -1;
    mixers[i].ctl[0] = 0;
    if (mixer) *mixer = &mixers[i];
    say("[alsa] snd_mixer_open -> fake mixer\n");
    return 0;
}
int snd_mixer_close(void *m)
{
    struct fake_mixer *x = m;
    if (x >= mixers && x < mixers + MIX_MAX) x->used = 0;
    return 0;
}
int snd_mixer_attach(void *m, const char *card)
{
    struct fake_mixer *x = m;
    if (x >= mixers && x < mixers + MIX_MAX) {
        str_cpy(x->ctl, card, sizeof x->ctl);
        x->card = ctl_card(card);
    }
    return 0;
}
int snd_mixer_selem_register(void *m, void *opts, void **classp)
{ (void)m; (void)opts; (void)classp; return 0; }
int snd_mixer_load(void *m) { (void)m; return 0; }

/* The id is the game's own buffer of this size (alloca of the sizeof), so
 * the name it sets is kept IN it, for find_selem to read back. */
unsigned long snd_mixer_selem_id_sizeof(void) { return 128; }
void snd_mixer_selem_id_set_name(void *id, const char *name)
{ if (id) str_cpy((char *)id, name, 64); }
void snd_mixer_selem_id_set_index(void *id, unsigned idx) { (void)id; (void)idx; }

void *snd_mixer_find_selem(void *m, const void *id)
{
    struct fake_mixer *x = m;
    int known = x >= mixers && x < mixers + MIX_MAX;
    const char *name = id ? (const char *)id : "";
    int card = known ? x->card : -1;
    int i, fr = -1;
    char line[160];
    for (i = 0; i < ELEM_MAX; i++) {
        if (!elems[i].used) { if (fr < 0) fr = i; continue; }
        if (elems[i].card == card && str_eq(elems[i].name, name)) return &elems[i];
    }
    if (fr < 0) return &elem_spare;            /* never NULL: the game does not check */
    elems[fr].used = 1;
    elems[fr].card = card;
    elems[fr].vol = PCM_VOL_MAX;
    elems[fr].sw = 1;
    str_cpy(elems[fr].name, name, sizeof elems[fr].name);
    snprintf(line, sizeof line, "[alsa] mixer element \"%s\" on ctl %s (card #%d)\n",
             elems[fr].name, known && x->ctl[0] ? x->ctl : "?", card);
    say(line);
    return &elems[fr];
}

/* The SGTL5000's own range for its PCM volume, as the machine reports it. */
int snd_mixer_selem_get_playback_volume_range(void *elem, long *min, long *max)
{
    (void)elem;
    if (min) *min = 0;
    if (max) *max = PCM_VOL_MAX;
    return 0;
}
int snd_mixer_selem_set_playback_volume_all(void *elem, long value)
{
    struct fake_elem *el = elem;
    if (!(el >= elems && el < elems + ELEM_MAX)) return 0;
    if (value < 0) value = 0;
    if (value > PCM_VOL_MAX) value = PCM_VOL_MAX;
    if (el->used > 1 && el->vol == value) return 0;   /* the same again: no log line */
    el->vol = value;
    el->used = 2;
    mixer_apply(el);
    return 0;
}
int snd_mixer_selem_set_playback_switch_all(void *elem, int value)
{
    struct fake_elem *el = elem;
    char line[160];
    if (!(el >= elems && el < elems + ELEM_MAX)) return 0;
    if (el->sw != !!value) {
        el->sw = !!value;
        snprintf(line, sizeof line, "[alsa] mixer switch \"%s\" on card #%d -> %s (logged only)\n",
                 el->name, el->card, value ? "on" : "off");
        say(line);
    }
    return 0;
}

/* Card 0's PCM at the game's volume, for the speakers only. A short write
 * returns what went, like write() itself. */
static long play_scaled(int fd, const void *buf, unsigned long bytes)
{
    static short tmp[4096];
    const short *in = buf;
    unsigned long n = bytes / 2, done = 0;
    int q = card_gain_q16[0];
    if (q >= 65536) return write(fd, buf, bytes);
    while (done < n) {
        unsigned long c = n - done, i;
        long r;
        if (c > sizeof tmp / sizeof *tmp) c = sizeof tmp / sizeof *tmp;
        for (i = 0; i < c; i++) tmp[i] = (short)(((long long)in[done + i] * q + 32768) >> 16);   /* nearest */
        r = write(fd, tmp, c * 2);
        if (r < 0) return done ? (long)(done * 2) : r;
        done += (unsigned long)r / 2;
        if ((unsigned long)r < c * 2) break;
    }
    return (long)(done * 2);
}
