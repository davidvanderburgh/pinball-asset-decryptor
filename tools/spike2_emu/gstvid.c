/* gstvid.c - the GUEST half of the video bridge.
 *
 * The game builds a real GStreamer pipeline
 *     filesrc -> qtdemux -> queue -> vpudec -> fakesink
 * and it fails at `set_state(PAUSED)` because vpudec needs an i.MX6 VPU that
 * does not exist here, after which `gst_pad_get_negotiated_caps` returns NULL
 * and Radium reports "Unable to get pad width or height".
 *
 * This file does NOT implement a decoder or a GStreamer element. It answers the
 * four questions the game asks and then calls the game's own callback:
 *
 *   1. set_state(pipeline, ...)      -> SUCCESS, and kick the host decoder
 *   2. pad_get_negotiated_caps(pad)  -> a caps object of our own
 *   3. structure_get_int("width")    -> what the host probed
 *   4. the "handoff" signal          -> we call it ourselves, per frame
 *
 * STREAMS, PLURAL. The first version kept ONE of everything - one pipeline
 * pointer, one location, one shm request slot - because Godzilla's attract
 * loop only ever played one clip at a time. Then the attract playlist
 * crossfaded: a second pipeline was built WHILE the first was still looping,
 * the two prepares raced on the single request slot, the loser waited for an
 * ack generation the host had already jumped past ("[vid] host did not
 * answer"), and the game spent the rest of the run retrying seek+play on a
 * pipeline this file no longer recognised - at ~25 errors a second. Now every
 * pipeline the game creates gets its own stream slot with its own shm CHANNEL
 * (padvid.h v2), and nothing is shared between clips but the code.
 *
 * ZERO COPY IN THE GUEST, and this is the whole performance story. The frame
 * buffer handed to the game points DIRECTLY into the shared ring the host
 * decoded into. Nothing in the emulated guest touches the 1.5 MB of pixels -
 * copying them here would be 47 MB/s of emulated-ARM memcpy at 30 fps, which is
 * exactly the mistake glraster.c already paid for once (correct, and 1 fps).
 *
 * The GstBuffer LAYOUT IS DERIVED AT RUN TIME, not hardcoded. We allocate one
 * real buffer through the real gst_buffer_new_and_alloc() with an unusual size,
 * find that size in the struct, and take `data` as the word before it. Writing
 * 0.10 header offsets from memory is the kind of thing that works on one build
 * and silently corrupts on another.
 */

#include "padvid.h"

extern void *dlsym(void *, const char *);
#define RTLD_NEXT ((void *)-1L)
extern int snprintf(char *, unsigned long, const char *, ...);
extern char *getenv(const char *);
extern int open(const char *, int, ...);
extern int close(int);
extern void *mmap(void *, unsigned long, int, int, int, long);
extern int usleep(unsigned);
extern void pad_say(const char *);
extern int pthread_create(unsigned long *, void *, void *(*)(void *), void *);
extern int clock_gettime(int, unsigned long *);

#define O_RDWR 2

static int vid_on(void)
{
    static int on = -1;
    if (on == -1) {
        const char *e = getenv("PAD_VID");
        on = (e && *e && *e != '0') ? 1 : 0;
    }
    return on;
}

#define VLOG(...)                                                       \
    do { char b_[300]; snprintf(b_, sizeof b_, __VA_ARGS__); pad_say(b_); } while (0)

static struct padvid_shm *vshm;
static unsigned char *vring;

static void vid_map(void)
{
    const char *path;
    int fd;
    void *p;
    static int tried;
    if (vshm || tried) return;
    tried = 1;
    path = getenv("PAD_VID_SHM");
    if (!path || !*path) return;
    fd = open(path, O_RDWR, 0);
    if (fd < 0) { VLOG("[vid] cannot open %s\n", path); return; }
    p = mmap(0, PADVID_BYTES, 3 /* R|W */, 1 /* MAP_SHARED */, fd, 0);
    close(fd);
    if (!p || p == (void *)-1) { VLOG("[vid] mmap failed\n"); return; }
    if (((struct padvid_shm *)p)->magic != PADVID_MAGIC) {
        VLOG("[vid] bad magic - is padvidhost running?\n");
        return;
    }
    if (((struct padvid_shm *)p)->version != PADVID_VERSION) {
        VLOG("[vid] block version %u, this shim wants %u - rebuild the other side\n",
             ((struct padvid_shm *)p)->version, PADVID_VERSION);
        return;
    }
    vshm = (struct padvid_shm *)p;
    vring = (unsigned char *)p + PADVID_HDR;
    VLOG("[vid] bridge attached: %s (%u channels)\n", path, PADVID_CHANNELS);
}

/* ---- the streams --------------------------------------------------------- */

struct stream {
    void *pipeline;             /* identity; 0 = free slot                   */
    void *filesrc;              /* the object the game sets "location" on.
                                 *
                                 * ITEM 15 IS THIS FIELD. The game does NOT
                                 * build a pipeline per clip - it builds TWO
                                 * for the whole run and changes the FILENAME
                                 * on them, so "the pipeline created last" is
                                 * not the pipeline being re-pointed. See
                                 * pad_vid_note_location() for the numbers. */
    void *fakesink;             /* the object that got signal-handoffs       */
    void *sinkpad;              /* its real "sink" pad - the handoff callback
                                 * is handed this, and a consumer that asks
                                 * the pad for caps must get OUR caps.       */
    void *decoder;              /* SpiVideoStreamDecoder, for diagnostics    */
    void (*handoff)(void *, void *, void *, void *);
    void *handoff_data;
    char location[PADVID_PATH_MAX];
    int  ready;                 /* host answered with a size                 */
    int  playing;
    unsigned run_id;            /* bumped per play(); a thread that wakes to
                                 * find it changed belongs to a PREVIOUS run
                                 * and must touch nothing on its way out. The
                                 * old single-stream code let a late-waking
                                 * thread clear `playing` under the run that
                                 * had just re-armed it, and the host read
                                 * that as "guest stopped playback".         */
    unsigned w, h;
    /* The size the GAME was actually told, which is NOT the same as w/h.
     *
     * ITEM 6 IS THIS FIELD. The game asks for caps ONCE per pipeline, builds a
     * texture that size, and then loops the clip by SEEKING - measured, 2026-08-06:
     * one "caps ... -> its own pad" line and then nine "streaming" lines, with
     * the size changing under it and no second question ever asked. w/h follow
     * the channel because pad_vid_prepare() refreshes them; the game's texture
     * does not follow anything. So w/h cannot answer "does the game agree with
     * what is in the ring", and that is the only question that matters before
     * handing over a pointer. */
    unsigned told_w, told_h;
    /* item 11's runaway detector. `delivered` is what the last streaming run
     * actually handed the game before it was superseded; `prep_streak` counts
     * consecutive re-arms of `prep_path` that each delivered at most one
     * frame. See "WHY a channel is being re-armed" above. */
    unsigned delivered;
    unsigned prep_streak;
    char prep_path[PADVID_PATH_MAX];
    unsigned seek_absorbed;     /* redundant rewinds swallowed; see pad_vid_seek */
    unsigned long last_seek_us; /* when the previous seek arrived; 0 = never  */
    unsigned last_use;          /* bumped per frame; picks the stealing victim */
    long long pos_ns;
    void *buf;                  /* this stream's GstBuffer                   */
    /* Our own caps/structure objects. Never handed to real GStreamer - every
     * unref path recognises them by address. Per stream, because two live
     * clips can have two different sizes. */
    unsigned long fake_caps[8];
    unsigned long fake_struct[8];
};

static struct stream streams[PADVID_CHANNELS];

/* A monotonic tick, bumped once per delivered frame, so "least recently used"
 * is a real ordering rather than array position. Wrapping after 4 billion
 * frames would only cost one bad steal, which the size check then catches. */
static unsigned use_tick;

/* Where construction-time facts attach. The game builds one pipeline at a
 * time on its UI thread: pipeline_new, then the elements, then the filesrc
 * location, then the handoff connect - so "the stream created last" is the
 * right home for each of those calls, none of which carries the pipeline. */
static struct stream *last_created;

/* ---- item 11: WHY a channel is being re-armed ---------------------------
 *
 * A serve is expensive on the GUEST'S side, not just the host's:
 * pad_vid_prepare() blocks the game's own UI thread until the host acks. The
 * 2026-08-06 recording caught one channel being re-served the SAME file 17
 * times a second, and eglshim's counter fell from 60.0 fps to 17.7 in exactly
 * those windows - two independent instruments, one inside the guest and one a
 * screen capture outside WSL, agreeing on the same seconds.
 *
 * The host can see the storm - it logs one - but it cannot see the CALLER, and
 * the caller is what decides the fix. There are only two:
 *   "state"  - gst_element_set_state(PAUSED), i.e. the game re-arming a
 *              pipeline it already has;
 *   "rewind" - pad_vid_seek(), the game's EOS handler looping the clip.
 * Those want opposite fixes, so nobody should guess between them.
 *
 * RATE LIMITED ON PURPOSE: one line when a runaway is recognised and one when
 * it ends, not one per prepare. A per-prepare line would be 17 lines a second
 * describing the thing it is measuring.
 *
 * NO CLOCK. The obvious definition is "N prepares within M milliseconds", and
 * this file has no clock - it declares its own externs and pulls in no libc
 * headers, so struct timespec would have to be hand-written for the emulated
 * ARM ABI to get a number the host already logs. The pathology has a better
 * definition that needs no time at all: a re-arm of the SAME path whose
 * previous run delivered at most one frame. That is precisely what the host
 * reports as "superseded after 1 frames" - 116 of that run's 140 serves - seen
 * from the other end, and it cannot be fooled by a slow machine. */
static const char *prepare_why = "state";

#define PREPARE_STORM_N 8

static int str_eq(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

static int chan_of(const struct stream *s) { return (int)(s - streams); }

static struct stream *find_pipeline(void *p)
{
    int i;
    if (!p) return 0;
    for (i = 0; i < PADVID_CHANNELS; i++)
        if (streams[i].pipeline == p) return &streams[i];
    return 0;
}

int pad_vid_is_pipeline(void *p) { return find_pipeline(p) != 0; }

int pad_vid_is_ours(void *p)
{
    int i;
    if (!p) return 0;
    for (i = 0; i < PADVID_CHANNELS; i++)
        if (p == (void *)streams[i].fake_caps ||
            p == (void *)streams[i].fake_struct) return 1;
    return 0;
}

/* The GL bridge needs to NAME the frame it is about to upload without copying
 * it. The pointer the game hands glTexDirectVIVMap is one of our ring slots, so
 * a byte offset from the ring base identifies it completely, and the host - which
 * has the same block open - reads the pixels itself. Returns -1 for anything
 * that is not ours, which is the bridge's signal to fall back to copying.
 *
 * glbridge.c reaches this as a WEAK symbol: hwshim.so is LD_PRELOADed so it is
 * always found in a real run, and libGLESv2 still loads without it. */
long pad_vid_ring_offset(const void *p)
{
    unsigned long base = (unsigned long)vring;
    unsigned long q = (unsigned long)p;
    unsigned long span = (unsigned long)PADVID_RING_BYTES;
    if (!vring || q < base || q >= base + span) return -1;
    return (long)(q - base);
}

static void str_copy(char *d, const char *s, int n)
{
    int i = 0;
    if (!s) { d[0] = 0; return; }
    for (; i < n - 1 && s[i]; i++) d[i] = s[i];
    d[i] = 0;
}

/* PAD_VID_NOSRCROUTE=1 goes back to attaching the filename to whatever pipeline
 * was created last, which is what shipped before 2026-08-06. It exists so the
 * change below can be A/B'd on ONE build in ONE run - this rig has been fooled
 * by comparing two runs before. */
static int src_route(void)
{
    static int on = -1;
    if (on == -1) {
        const char *e = getenv("PAD_VID_NOSRCROUTE");
        on = (e && *e && *e != '0') ? 0 : 1;
    }
    return on;
}

/* WHICH STREAM DOES THIS FILENAME BELONG TO?
 *
 * ★ ITEM 15, AND IT WAS MEASURED OFF AN EXISTING LOG, NOT GUESSED. In the
 * gameplay run of 2026-08-06 the game created exactly TWO video pipelines in
 * five minutes - one complete factory_make set at gzpad.log:5027 (ch0) and one
 * at :6566 (ch1), and NOT ONE after that. Every clip change in the rest of the
 * run was g_object_set(filesrc, "location", ...) on a pipeline that already
 * existed. The game reuses its pipelines; it does not rebuild them.
 *
 * That is fatal to `last_created`, which only moves on gst_pipeline_new. From
 * the moment the second pipeline was built, EVERY filename the game set landed
 * on the second stream, whichever element it was actually meant for. padvid.log
 * says it in one line: ch0 was handed a new clip four times, the last at
 * 127.7 s - 7 SECONDS BEFORE ch1 WAS CREATED - and then served
 * 2.asset/383.asset SIXTY-ONE TIMES over the following 182 seconds, while ch1
 * caught the strays meant for ch0 (2.asset/567.asset and 2.asset/446.asset,
 * one prepare each, in between its own background loop).
 *
 * On screen that is item 15 exactly: every video element in the game drawing
 * the same footage, PLAYING rather than frozen, because the element really is
 * playing - it is playing the last file it was ever correctly told about.
 *
 * It also explains why attract mode always looked fine and only a GAME showed
 * it: attract mostly runs one clip at a time, so there is only one stream and
 * `last_created` is right by luck. The bug needs two live pipelines, which is
 * what a game has.
 *
 * So route by the SOURCE OBJECT the property was set on. The binding is made
 * the first time we see a source, when `last_created` IS still the right
 * answer (the game builds pipeline, then elements, then sets the filename),
 * and after that the object's identity carries it - no ordering assumption
 * survives past construction. */
void pad_vid_note_location(void *src, const char *loc)
{
    struct stream *s = 0;
    int i;
    if (src && src_route()) {
        for (i = 0; i < PADVID_CHANNELS; i++)
            if (streams[i].filesrc == src) { s = &streams[i]; break; }
        if (!s && last_created) {
            /* First sighting of this source. Bind it to the stream under
             * construction, and take it off any other stream first: a freed
             * element can come back at the same heap address, and two streams
             * claiming one source would put us back where we started. */
            for (i = 0; i < PADVID_CHANNELS; i++)
                if (streams[i].filesrc == src) streams[i].filesrc = 0;
            s = last_created;
            s->filesrc = src;
            VLOG("[vid] ch%d owns source %p\n", chan_of(s), src);
        }
    }
    if (!s) s = last_created;
    if (!s) return;
    /* Only when it CHANGES. A rewind re-sets the same filename, and a line per
     * rewind would bury the one event this log is here to show. */
    {
        const char *a = s->location, *b = loc ? loc : "";
        int same = 1, j = 0;
        for (; a[j] || b[j]; j++)
            if (a[j] != b[j]) { same = 0; break; }
        if (!same)
            VLOG("[vid] ch%d location -> %s\n", chan_of(s), b);
    }
    str_copy(s->location, loc, sizeof s->location);
}

void pad_vid_note_pipeline(void *p)
{
    struct stream *s;
    int i;
    if (!p) return;
    /* The same heap address coming back from pipeline_new means the OLD
     * pipeline was freed and its slot is stale - reuse it, do not double it. */
    s = find_pipeline(p);
    if (!s) {
        for (i = 0; i < PADVID_CHANNELS && !s; i++)
            if (!streams[i].pipeline) s = &streams[i];
        /* STEAL THE LEAST RECENTLY USED, not the first one found.
         *
         * `pipeline` is never cleared - there is no reliable teardown signal to
         * clear it on, since the game sets NULL and then sometimes plays the
         * same pipeline object again - so after the first four clips EVERY new
         * pipeline is a steal, and the victim is whichever non-playing stream
         * comes first in the array. That put the freshest corpse first: a clip
         * that has just hit EOS has playing == 0 while its decoder is very
         * probably still on screen, and taking its channel is how item 6's TV
         * inset ended up reading a 1360x768 background frame.
         *
         * Least-recently-used takes the stream that has gone longest without a
         * frame instead, which is the one least likely to still be drawn.
         * vid_thread's size check is what makes a wrong guess HARMLESS; this
         * only makes a wrong guess RARE. */
        if (!s) {
            struct stream *lru = 0;
            for (i = 0; i < PADVID_CHANNELS; i++) {
                if (streams[i].playing) continue;
                if (!lru || streams[i].last_use < lru->last_use) lru = &streams[i];
            }
            s = lru;
        }
        if (!s) {
            /* Every slot is playing. Steal the oldest; a fifth simultaneous
             * clip is beyond anything the game has shown, and stealing is
             * still strictly better than the old behaviour, which stole slot
             * ONE of one on every new clip. */
            s = &streams[0];
            for (i = 1; i < PADVID_CHANNELS; i++)
                if (streams[i].last_use < s->last_use) s = &streams[i];
            VLOG("[vid] all %u channels busy, stealing ch%d (least recently used)\n",
                 PADVID_CHANNELS, chan_of(s));
        }
    }
    s->playing = 0;
    if (vshm) vshm->ch[chan_of(s)].playing = 0;
    s->pipeline = p;
    s->fakesink = 0; s->sinkpad = 0; s->decoder = 0;
    /* Drop the old pipeline's source binding with the rest of its identity. The
     * elements are about to be rebuilt, and keeping the pointer would let a
     * dead filesrc keep steering this channel - or, if the allocator hands the
     * same address to somebody else, steer it wrongly. */
    s->filesrc = 0;
    s->handoff = 0; s->handoff_data = 0;
    s->location[0] = 0;
    s->ready = 0;
    /* The new pipeline has been told nothing yet, and the old one's answer must
     * not be inherited - it would let a stale decoder's geometry validate this
     * stream's frames. */
    s->told_w = 0; s->told_h = 0;
    s->pos_ns = 0;
    /* A BRAND NEW STREAM IS THE MOST RECENTLY USED, NOT THE LEAST, and getting
     * this backwards is worse than not having LRU at all.
     *
     * last_use is otherwise bumped only when a frame is DELIVERED, so a stream
     * that has just been created - or prepared and not yet played - still
     * carries its previous life's tick, or zero. Under plain LRU that makes the
     * newest stream the FIRST thing the next pipeline steals. The Planet X
     * Controller taunt builds three pipelines in 130 ms, so that is not a
     * theoretical ordering problem: it is the exact sequence that took the
     * taunt's channel away from it 0 frames in. */
    s->last_use = ++use_tick;
    last_created = s;
}

void pad_vid_note_handoff(void *sink, void *fn, void *data)
{
    static void *(*get_pad)(void *, const char *);
    struct stream *s = last_created;
    if (!s) return;
    s->fakesink = sink;
    if (!get_pad) get_pad = dlsym(RTLD_NEXT, "gst_element_get_static_pad");
    s->sinkpad = (get_pad && sink) ? get_pad(sink, "sink") : 0;
    s->handoff = (void (*)(void *, void *, void *, void *))fn;
    s->handoff_data = data;
}

void pad_vid_note_decoder(void *p) { if (last_created) last_created->decoder = p; }

/* ---- GstBuffer, layout derived at run time ------------------------------ */

static int   off_data = -1, off_size = -1;
static void *(*real_buf_alloc)(unsigned);

static int buf_layout(void)
{
    unsigned probe = 0x00ABCDE0u;
    void *b;
    unsigned long *w;
    int i;
    if (off_data >= 0) return 1;
    if (!real_buf_alloc)
        real_buf_alloc = dlsym(RTLD_NEXT, "gst_buffer_new_and_alloc");
    if (!real_buf_alloc) { VLOG("[vid] no gst_buffer_new_and_alloc\n"); return 0; }
    b = real_buf_alloc(probe);
    if (!b) return 0;
    w = (unsigned long *)b;
    for (i = 2; i < 16; i++) {
        if ((unsigned)w[i] == probe && w[i - 1] > 0x1000) {
            off_size = i * 4;
            off_data = (i - 1) * 4;
            VLOG("[vid] GstBuffer layout: data at +%d, size at +%d\n",
                 off_data, off_size);
            return 1;
        }
    }
    VLOG("[vid] could NOT find the GstBuffer layout - video disabled\n");
    return 0;
}

/* One GstBuffer per stream: two live streams hand frames to two different
 * handoffs, and a single shared buffer would have each overwrite the other's
 * data pointer mid-frame. The buffer is real (from the real allocator) so any
 * timestamp sort or unref the game does sees a well-formed object. */
static int stream_buf(struct stream *s)
{
    if (s->buf) return 1;
    if (!buf_layout()) return 0;
    s->buf = real_buf_alloc(64);
    return s->buf != 0;
}

/* ---- the streaming thread ----------------------------------------------- */

static void post_eos(void *pipeline);
long long pad_vid_duration_ns(void *pipeline);

static void vid_dump_decoder(struct stream *s, const char *when)
{
    const unsigned char *b = (const unsigned char *)s->decoder;
    if (!b) return;
    VLOG("[vid] ch%d decoder %s: loop=%u count=%u state=%u done19=%u new49=%u\n",
         chan_of(s), when, b[4], *(const unsigned *)(b + 8),
         *(const unsigned *)(b + 12), b[0x19], b[0x49]);
}

/* Microseconds, CLOCK_MONOTONIC, for the frame schedule below. 32-bit and it
 * WRAPS every ~71 minutes - only ever subtract two readings, never compare
 * absolutes. Same two-long timespec shape pad_ms() in hwshim.c already
 * proves against this guest's ABI. */
static unsigned long vid_us(void)
{
    unsigned long t[2] = { 0, 0 };
    clock_gettime(1 /* CLOCK_MONOTONIC */, t);
    return t[0] * 1000000ul + t[1] / 1000ul;
}

static void *vid_thread(void *arg)
{
    struct stream *s = (struct stream *)arg;
    struct padvid_chan *c = &vshm->ch[chan_of(s)];
    unsigned char *ring = vring + (unsigned long)chan_of(s)
                                * PADVID_SLOTS * PADVID_SLOT_BYTES;
    unsigned my_run = s->run_id;
    /* The request generation this thread's clip was opened under.
     *
     * THE SIZE CHECK BELOW CANNOT SEE A SAME-SIZE TAKEOVER, and most of this
     * game's clips are 1360x768, so most takeovers ARE same-size: the victim
     * then reads the thief's frames at a geometry that happens to match, which
     * shows the wrong CLIP rather than stripes and would never be reported as
     * a video bug. Only this stream's own prepare() bumps req_gen for its own
     * run, so a generation that has moved under a running thread means some
     * other pipeline took the channel - whatever size it took it at. */
    unsigned my_gen = vshm->ch[chan_of(s)].req_gen;
    unsigned consumed = 0;
    unsigned delay = 33333;
    unsigned long t_epoch = 0;   /* set at frame 0; the schedule's zero */
    if (c->fps_num && c->fps_den)
        delay = (unsigned)(1000000ull * c->fps_den / c->fps_num);
    VLOG("[vid] ch%d streaming %ux%u at %u/%u fps (%u us/frame)\n",
         chan_of(s), c->width, c->height, c->fps_num, c->fps_den, delay);
    while (s->run_id == my_run && s->playing && c->playing) {
        unsigned produced = c->write_idx;
        if (consumed >= produced) {
            if (c->eos) {
                /* Looping is the game's business: it seeks or rebuilds. Stop
                 * here rather than inventing a loop it did not ask for - but it
                 * cannot make that decision until it is TOLD the clip ended,
                 * and EOS is the only message that tells it. Report the
                 * position as exactly the duration first, because the handler
                 * checks that before it acts. */
                if (s->run_id != my_run) return 0;   /* superseded mid-wake */
                s->pos_ns = pad_vid_duration_ns(s->pipeline);
                VLOG("[vid] ch%d end of stream after %u frames, posting EOS "
                     "(pos=dur=%u ms)\n", chan_of(s), consumed,
                     (unsigned)(s->pos_ns / 1000000ll));
                vid_dump_decoder(s, "at EOS");
                /* STAND DOWN BEFORE POSTING, not after. The handler runs on
                 * the game's main loop and it answers EOS by seeking straight
                 * back to 0, which arrives about a millisecond later. If this
                 * thread were still flagged as playing at that moment,
                 * pad_vid_play() would decline to start the next one and the
                 * loop would die silently. */
                s->playing = 0;
                c->playing = 0;
                post_eos(s->pipeline);
                return 0;
            }
            /* ★ ITEM 11: THE RING WAS EMPTY WHEN A FRAME WAS DUE. The census
             * on the host side only ever logged the ring being FULL (the
             * guest not draining); this is the opposite and untested case -
             * the DECODER not keeping up, which starves the schedule and
             * makes the handoff late. Measured 2026-08-06: the guest handed
             * the game 14.3-28/s during gameplay instead of 30 while the
             * machine was 67% IDLE, so it is not CPU starvation and this is
             * the remaining candidate. Counts waits that outlast the frame
             * they were due for, budgeted so a stall cannot flood. */
            {
                static unsigned long waited_us[PADVID_CHANNELS];
                static unsigned budget = 60;
                int ch = chan_of(s);
                waited_us[ch] += 1000;
                if (waited_us[ch] == delay && budget) {
                    char m[112];
                    budget--;
                    snprintf(m, sizeof m,
                             "[vid] ch%d RING EMPTY for a whole frame period"
                             " at frame %u - the decoder is behind\n",
                             ch, consumed);
                    pad_say(m);
                }
                if (waited_us[ch] > delay * 8) waited_us[ch] = 0;
            }
            usleep(1000);
            continue;
        }
        {
            unsigned slot = consumed % PADVID_SLOTS;
            unsigned char *px = ring + (unsigned long)slot * PADVID_SLOT_BYTES;
            if (s->run_id != my_run) return 0;       /* superseded mid-wake */
            /* ---- ITEM 6'S FIX: NEVER HAND OVER PIXELS THE GAME WILL READ AT
             * THE WRONG GEOMETRY.
             *
             * The game holds a texture of whatever size it was told when the
             * pipeline was built, and it never asks again. This channel's
             * contents, on the other hand, change whenever the channel is
             * re-served - which happens constantly, because the game builds far
             * more pipelines over a run than there are channels and `pipeline`
             * is never cleared, so a new pipeline takes over the slot of any
             * stream that is not currently playing. A stream whose clip has
             * just ended is exactly such a victim, and its decoder may still be
             * on screen. Raising PADVID_CHANNELS to 8 made that rarer; only
             * this check makes it harmless.
             *
             * When that happens the old decoder keeps calling Invalidate on a
             * pointer into a ring the host is now filling with somebody else's
             * frames, at somebody else's size. That is item 6: the TV inset's
             * 229,320-byte read landing on a 1360x768 frame, which framewidth.py
             * measured off the capture (1360 at 2.02 against a shuffled control
             * of 23.84, while the 520 it was read at scored 22.34 against 23.80).
             *
             * Holding the last good frame is the honest answer. The game cannot
             * be made to re-negotiate - it is not asking - so the choice is a
             * frozen picture or a stream of another clip's bytes rendered as
             * pink and green stripes. */
            if (c->req_gen != my_gen) {
                VLOG("[vid] ch%d TAKEN OVER: opened at gen %u, channel is now "
                     "at gen %u (%ux%u). Holding the last frame after %u.\n",
                     chan_of(s), my_gen, c->req_gen, c->width, c->height,
                     consumed);
                s->playing = 0;
                return 0;
            }
            if (s->told_w && (c->width != s->told_w || c->height != s->told_h)) {
                VLOG("[vid] ch%d NOT MINE ANY MORE: the game holds %ux%u but "
                     "this channel now serves %ux%u. Holding the last frame "
                     "after %u.\n", chan_of(s), s->told_w, s->told_h,
                     c->width, c->height, consumed);
                s->playing = 0;
                return 0;
            }
            /* POINT the buffer at the ring. No copy. */
            *(unsigned long *)((char *)s->buf + off_data) = (unsigned long)px;
            *(unsigned *)((char *)s->buf + off_size) = c->frame_bytes;
            /* timestamp/duration sit right after size in the 0.10 layout, both
             * 64-bit. A consumer that sorts or drops on timestamp sees every
             * buffer at 0 otherwise, which looks like one frame repeated. */
            if (off_size + 4 + 8 <= 64) {
                unsigned long long *ts =
                    (unsigned long long *)((char *)s->buf + off_size + 4);
                ts[0] = (unsigned long long)consumed * delay * 1000ull;
                ts[1] = (unsigned long long)delay * 1000ull;
            }
            if (s->handoff)
                s->handoff(s->fakesink, s->buf, s->sinkpad, s->handoff_data);
            /* ITEM 11's OTHER STAGE COUNTER, paired with padglhost's
             * "vid N NEW/s". This is the moment the GAME is handed a frame;
             * that one is the moment the frame reaches the renderer. Two
             * numbers on the same seconds are what separate "the guest was
             * late" from "the game did not upload what it was given" - and
             * David's recording proved neither could be read off the
             * healthy-looking per-serve logs. Rate-limited to one line per
             * ~2 s per stream. */
            {
                static unsigned long said_at[PADVID_CHANNELS];
                static unsigned said_n[PADVID_CHANNELS];
                int ch = chan_of(s);
                unsigned long nowu = vid_us();
                said_n[ch]++;
                if (!said_at[ch]) said_at[ch] = nowu;
                else if ((long)(nowu - said_at[ch]) >= 2000000) {
                    char m[96];
                    unsigned long el = nowu - said_at[ch];
                    snprintf(m, sizeof m,
                             "[vid] ch%d handed the game %u frames in %lu ms"
                             " (%lu.%lu/s)\n", ch, said_n[ch], el / 1000,
                             (unsigned long)(said_n[ch] * 1000000ul / el),
                             (unsigned long)(said_n[ch] * 10000000ul / el) % 10);
                    pad_say(m);
                    said_at[ch] = nowu;
                    said_n[ch] = 0;
                }
            }
            s->last_use = ++use_tick;
            consumed++;
            /* Updated per frame rather than on each of the five exit paths:
             * a return that forgot to record it would read as a runaway. */
            s->delivered = consumed;
            s->pos_ns = (long long)consumed * delay * 1000ll;
            /* Only now may the host reuse this slot. */
            c->read_idx = consumed;
        }
        /* ★ ITEM 11's CADENCE FIX: SCHEDULE FRAMES ABSOLUTELY, DO NOT SLEEP
         * A PERIOD. The old `usleep(delay)` ran AFTER each frame's work, so
         * the true period was delay + handoff time + the kernel timer's
         * overshoot - always a little slower than the clip's rate, and the
         * error ACCUMULATED until the picture slipped one whole frame, over
         * and over. Measured off the screen itself (screenrec.py), which is
         * how David sees it: 163 freezes in 90 s of attract and 300 in 90 s
         * of the in-game freeway loop, every one exactly ONE duplicated
         * frame, 2-3 per second in beat-frequency bursts - while the game's
         * own overlays stayed smooth (his observation, and the instrument
         * agreed). An excess of just 0.5-3 ms per frame predicts 0.5-3
         * slips/s; 2-3.3/s was measured.
         *
         * Frame N now targets t_epoch + N*delay, so per-frame error never
         * accumulates. A thread that falls behind simply does not sleep
         * until it has caught up - no spiral, and clips still end at the
         * same total duration. */
        if (!t_epoch) t_epoch = vid_us();
        {
            unsigned long target = t_epoch + (unsigned long)consumed * delay;
            long ahead = (long)(target - vid_us());
            if (ahead > 0) usleep((unsigned)ahead);
        }
    }
    /* Reaching here means someone else already cleared a flag (stop, or a new
     * run superseding this one). Write NOTHING: clearing c->playing now could
     * land on top of a prepare() that just re-armed the channel, and the host
     * would read it as "guest stopped playback" on a clip that is starting. */
    return 0;
}

/* ---- entry points called from gststub.c --------------------------------- */

/* Ask the host to open a stream's location. Returns 1 if it can be played. */
int pad_vid_prepare(void *pipeline)
{
    struct stream *s = find_pipeline(pipeline);
    struct padvid_chan *c;
    unsigned gen;
    int spins = 0;
    if (!s || !vid_on()) return 0;
    vid_map();
    if (!vshm || !s->location[0]) return 0;
    if (!stream_buf(s)) return 0;
    c = &vshm->ch[chan_of(s)];

    /* ★ ITEM 11, THE STATE-PATH HALF: A RE-ARM OF A CLIP THAT IS STILL
     * PLAYING THE SAME FILE IS ABSORBED, exactly like the rewind absorb in
     * pad_vid_seek() and for the same reason seen from the other caller.
     *
     * At a clip-to-clip transition the game re-arms the OUTGOING pipeline
     * (set_state(PAUSED), no stop first - gststub.c) BEFORE it sets the new
     * location. A real pipeline answers PAUSED by holding position; this
     * host cannot seek, so prepare() restarts ffmpeg from frame 0 and the
     * outgoing clip visibly jumps back to its own start. David watched it
     * live 2026-08-06 - "the last 500ms - 1 second of a video stutters
     * before the next one loads in" - and his session log shows ch0 283
     * frames into 2.asset/290.asset being re-served the same file from 0,
     * with the real next clip arriving 1.3 s later. Keeping the in-flight
     * serve IS the PAUSED-holds-position semantics, to within the frames the
     * thread keeps delivering.
     *
     * A location CHANGE fails the path check and re-arms; a stopped stream
     * (playing==0, i.e. after EOS or a real stop) re-arms. What is lost is a
     * true freeze - a game that sets PAUSED and STAYS paused would see the
     * clip keep advancing - but this game's churn goes straight back to
     * PLAYING, and the alternative was the jump-back. */
    if (s->playing && str_eq(s->prep_path, s->location)) {
        s->seek_absorbed++;
        if (s->seek_absorbed == 1)
            VLOG("[vid] ch%d state re-arm of the clip it is already playing "
                 "(delivered %u); absorbing it\n", chan_of(s), s->delivered);
        return 1;
    }
    if (s->seek_absorbed) {
        VLOG("[vid] ch%d absorbed %u redundant re-arms while it played\n",
             chan_of(s), s->seek_absorbed);
        s->seek_absorbed = 0;
    }

    /* item 11's runaway detector - see "WHY a channel is being re-armed". */
    if (str_eq(s->prep_path, s->location) && s->delivered <= 1) {
        s->prep_streak++;
        if (s->prep_streak == PREPARE_STORM_N)
            VLOG("[vid] ch%d RE-ARM STORM: %u prepares of %s in a row, each "
                 "delivering <=1 frame, caller=%s. Every one blocks this "
                 "thread until the host acks.\n",
                 chan_of(s), s->prep_streak, s->location, prepare_why);
    } else {
        if (s->prep_streak >= PREPARE_STORM_N)
            VLOG("[vid] ch%d re-arm storm ended after %u prepares (caller=%s)\n",
                 chan_of(s), s->prep_streak, prepare_why);
        s->prep_streak = 0;
        str_copy(s->prep_path, s->location, sizeof s->prep_path);
    }

    /* ★ ITEM 11's SECOND STATE-PATH DEFECT: THE ARMED-BUT-UNPLAYED STALL.
     *
     * From here down this call is committed to re-arming the channel, which
     * dooms any thread still running - it will stand down on the req_gen
     * check the moment it wakes. But "the moment it wakes" is up to 33 ms
     * away, and the game's set_state(PLAYING) arrives well inside that -
     * and pad_vid_play() declines while s->playing is still 1. The new arm
     * was then served by the host into a 4-slot ring that NOBODY drained:
     * that is the `superseded while throttled after 4 frames` line all over
     * every run log, a stalled picture until the game's SECOND
     * PAUSED->PLAYING cycle landed, and the serve-pairs at every transition.
     * Clearing the flag here makes the play() that follows a prepare always
     * start the thread; a repeated PLAYING with no prepare in between is
     * still declined, which is what the flag was for. The orphaned thread
     * exits on run_id/req_gen and touches nothing on its way out. */
    s->playing = 0;

    /* RESET THE POSITION HERE, not just in pad_vid_play().
     *
     * The game queries position and duration while the pipeline is at PAUSED,
     * before it ever plays. Leaving pos_ns holding the PREVIOUS clip's
     * duration meant it compared a stale position against the new clip's
     * duration, decided the new clip was already finished, and tore the
     * pipeline down - then built it again, ~25 times a second, so nothing ever
     * played and the video panel stayed black. */
    s->pos_ns = 0;
    str_copy(c->path, s->location, PADVID_PATH_MAX);
    /* PREROLL: tell the host to start decoding NOW, at PAUSED, not at PLAYING.
     *
     * This was a real race and it produced a perfectly healthy-looking bridge
     * that decoded nothing: the host acked the probe and immediately checked
     * `playing`, which the guest only set later at PLAYING, so it returned at
     * once and then sat idle - status OK, width and height correct, write_idx
     * stuck at 0 forever.
     *
     * Starting here is also what a real pipeline does. PAUSED means preroll,
     * and the ring is only 4 frames deep, so the host fills it and blocks
     * rather than running away. */
    c->playing = 1;
    gen = c->req_gen + 1;
    c->req_gen = gen;
    /* 3 s is generous: a probe measured 0.08 s. It exists so a dead host
     * cannot wedge the game's UI thread, which is what calls this. Nothing
     * else can bump this channel's req_gen - that is the whole point of
     * channels - so the generation we wait for cannot be jumped past. */
    while (c->ack_gen != gen && spins++ < 3000) usleep(1000);
    if (c->ack_gen != gen) { VLOG("[vid] ch%d host did not answer\n", chan_of(s)); return 0; }
    if (c->status != PADVID_OK) return 0;
    s->w = c->width;
    s->h = c->height;
    s->ready = 1;
    /* Same reasoning as pad_vid_note_pipeline: a stream that has just been
     * armed with a file and a size is about to draw, so it is the last thing
     * that should be recycled. Without this a clip is stealable for the whole
     * window between PAUSED and PLAYING. */
    s->last_use = ++use_tick;
    return 1;
}

/* Tell the game's bus watch what a real pipeline would have told it.
 *
 * These are REAL GStreamer messages posted on the REAL bus of a real pipeline
 * object - only the state transitions they describe are invented. That means
 * gst_message_parse_state_changed, the message type field and the main-loop
 * dispatch all work exactly as the game expects, with no struct layout to
 * guess. Fabricating a GstMessage by hand would have meant deriving another
 * layout and getting GST_MESSAGE_TYPE right by luck. */
static void post_state(void *pipeline, int oldst, int newst, int pending)
{
    static void *(*new_sc)(void *, int, int, int);
    static void *(*new_async)(void *);
    static void *(*get_bus)(void *);
    static int (*post)(void *, void *);
    static void (*unref)(void *);
    void *bus, *msg;
    if (!get_bus) {
        new_sc   = dlsym(RTLD_NEXT, "gst_message_new_state_changed");
        new_async= dlsym(RTLD_NEXT, "gst_message_new_async_done");
        get_bus  = dlsym(RTLD_NEXT, "gst_pipeline_get_bus");
        post     = dlsym(RTLD_NEXT, "gst_bus_post");
        unref    = dlsym(RTLD_NEXT, "gst_object_unref");
    }
    if (!get_bus || !post || !new_sc) return;
    bus = get_bus(pipeline);
    if (!bus) return;
    msg = new_sc(pipeline, oldst, newst, pending);
    if (msg) post(bus, msg);
    if (newst == 3 && new_async) {          /* PAUSED == prerolled */
        msg = new_async(pipeline);
        if (msg) post(bus, msg);
    }
    if (unref) unref(bus);
}

/* The end-of-clip message, on the same real bus and by the same reasoning as
 * post_state: a genuine GstMessage from the library, so its type field and the
 * main-loop dispatch are whatever GStreamer says they are rather than whatever
 * we guessed. The game's handler is vtable+0x5c -> 0x5c1e3c, and message type
 * 1 (GST_MESSAGE_EOS) is one of only three it looks at - the other two, ERROR
 * and STATE_CHANGED, it already gets. */
static void post_eos(void *pipeline)
{
    static void *(*new_eos)(void *);
    static void *(*get_bus)(void *);
    static int (*post)(void *, void *);
    static void (*unref)(void *);
    static int looked;
    void *bus, *msg;
    if (!pipeline) return;
    if (!looked) {
        looked = 1;
        new_eos = dlsym(RTLD_NEXT, "gst_message_new_eos");
        get_bus = dlsym(RTLD_NEXT, "gst_pipeline_get_bus");
        post    = dlsym(RTLD_NEXT, "gst_bus_post");
        unref   = dlsym(RTLD_NEXT, "gst_object_unref");
    }
    if (!new_eos || !get_bus || !post) { VLOG("[vid] cannot post EOS\n"); return; }
    bus = get_bus(pipeline);
    if (!bus) return;
    msg = new_eos(pipeline);
    if (msg) post(bus, msg);
    if (unref) unref(bus);
}

void pad_vid_announce(void *pipeline, int oldst, int newst)
{
    if (find_pipeline(pipeline)) post_state(pipeline, oldst, newst, 0);
}

/* The caps question arrives on a PAD, not a pipeline: the game asks the
 * fakesink's sink pad what got negotiated. Streams remember their pad. A pad
 * that is no stream's pad but SOME stream is ready falls back - the game has
 * only ever been seen asking about the pad it connected the handoff to, but a
 * NULL here is precisely the error state this whole file exists to prevent.
 *
 * THE FALLBACK IS LOGGED, LOUDLY AND ALWAYS, because it is the one place in
 * this file where a wrong answer is indistinguishable from a right one. With
 * a single live stream any fallback is correct by luck; the moment two streams
 * of DIFFERENT sizes are alive - a 520x294 TV inset over a 1360x768
 * background - the same lucky guess hands the game the wrong width, and the
 * wrong width is exactly what pink/green stripes are (item 6). So it says so,
 * with both sizes, rather than being silently right until it is not.
 *
 * The fallback is `last_created`, not "any ready stream". The game builds one
 * pipeline at a time on its UI thread and asks for caps immediately after
 * PAUSED, so the stream under construction is the one being asked about; the
 * old code took whichever ready stream came last in the ARRAY, which is an
 * arbitrary channel number. */
void *pad_vid_caps_for_pad(void *pad)
{
    int i, ready = 0;
    struct stream *fb = 0;
    for (i = 0; i < PADVID_CHANNELS; i++) {
        if (!streams[i].ready) continue;
        ready++;
        if (pad && streams[i].sinkpad == pad) {
            /* Say it once per channel per size: "the pad matched" is the
             * healthy answer and a log that only prints the sick one cannot
             * tell "never happened" from "logging is off". */
            static unsigned said_w[PADVID_CHANNELS], said_h[PADVID_CHANNELS];
            if (said_w[i] != streams[i].w || said_h[i] != streams[i].h) {
                said_w[i] = streams[i].w; said_h[i] = streams[i].h;
                VLOG("[vid] ch%d caps %ux%u -> its own pad %p\n",
                     i, streams[i].w, streams[i].h, pad);
            }
            return (void *)streams[i].fake_caps;
        }
        if (!fb) fb = &streams[i];
    }
    if (last_created && last_created->ready) fb = last_created;
    if (fb) {
        static int said;
        static unsigned last_w, last_h;
        if (said < 8 || fb->w != last_w || fb->h != last_h) {
            said++;
            last_w = fb->w; last_h = fb->h;
            VLOG("[vid] caps asked for pad %p, which no stream owns - "
                 "answering ch%d %ux%u (%d streams ready)\n",
                 pad, chan_of(fb), fb->w, fb->h, ready);
        }
    }
    return fb ? (void *)fb->fake_caps : 0;
}

void *pad_vid_structure_for(void *caps)
{
    int i;
    for (i = 0; i < PADVID_CHANNELS; i++)
        if (caps == (void *)streams[i].fake_caps)
            return (void *)streams[i].fake_struct;
    return 0;
}

/* This is the moment the game LEARNS a size, and therefore the moment its
 * texture is fixed. Recording it here rather than at prepare() is the whole
 * point: prepare() runs again on every rewind and would keep told_* in step
 * with the channel, which is exactly the disagreement vid_thread has to be
 * able to see. */
int pad_vid_get_int(void *strct, const char *field, int *value)
{
    int i;
    if (!value || !field) return 0;
    for (i = 0; i < PADVID_CHANNELS; i++) {
        if (strct != (void *)streams[i].fake_struct) continue;
        if (field[0] == 'w') {
            *value = (int)streams[i].w;
            streams[i].told_w = streams[i].w;
            streams[i].told_h = streams[i].h;
            return 1;
        }
        if (field[0] == 'h') {
            *value = (int)streams[i].h;
            streams[i].told_w = streams[i].w;
            streams[i].told_h = streams[i].h;
            return 1;
        }
        return 0;
    }
    return 0;
}

void pad_vid_play(void *pipeline)
{
    struct stream *s = find_pipeline(pipeline);
    unsigned long th;
    if (!s || !s->ready || s->playing || !vshm) return;
    s->pos_ns = 0;
    /* Cleared HERE and not at the top of vid_thread: prepare() reads it to
     * decide whether the previous run got anywhere, and the thread starts
     * after prepare() has already run. Clearing it in the thread would race
     * that read and make a healthy clip look like a runaway. */
    s->delivered = 0;
    s->run_id++;                /* orphan any thread from a previous run */
    s->playing = 1;
    vshm->ch[chan_of(s)].playing = 1;
    if (pthread_create(&th, 0, vid_thread, s) != 0) {
        s->playing = 0;
        vshm->ch[chan_of(s)].playing = 0;
        VLOG("[vid] ch%d could not start the streaming thread\n", chan_of(s));
    }
}

void pad_vid_stop(void *pipeline)
{
    struct stream *s = find_pipeline(pipeline);
    if (!s) return;
    s->playing = 0;
    if (vshm) vshm->ch[chan_of(s)].playing = 0;
}

/* LOOPING. The game does not rebuild a pipeline per repeat: its bus handler
 * answers EOS with gst_element_seek(pipeline, rate, TIME, FLUSH, SET, 0, NONE,
 * -1) and expects playback to carry on from the start. That seek used to fall
 * through to real GStreamer, which knows nothing about any of this, so a clip
 * played exactly once and the last frame sat frozen on screen.
 *
 * The host decoder cannot seek - it is one ffmpeg per request - so a rewind is
 * served by asking for the same file again, which starts it from frame 0.
 * That is the only position the game ever asks for. */
int pad_vid_seek(void *pipeline, long long pos_ns)
{
    struct stream *s = find_pipeline(pipeline);
    if (!s || !s->ready || !vshm || !s->location[0]) return 0;
    if (pos_ns != 0)
        VLOG("[vid] ch%d seek to %u ms requested; only rewind is supported, "
             "restarting from 0\n", chan_of(s), (unsigned)(pos_ns / 1000000ll));

    /* ★ ITEM 11'S FIX: A REDUNDANT REWIND IS ABSORBED, NOT SERVED.
     *
     * The 2026-08-06 gameplay log answered the caller= question: both storms
     * were caller=rewind, 93 and 56 prepares, one seek per ~33 ms - the game's
     * own 30 fps tick. Each seek killed the host's ffmpeg MID-COLD-START
     * (~35 ms to first frame, measured) and re-armed it, so no arm ever got
     * past frame 0: the picture froze on the clip's first frame for the whole
     * storm and the UI thread ate a blocking prepare per tick. The storm ended
     * exactly when one arm finally delivered the full clip - which is the
     * observation this fix turns into policy.
     *
     * THE DISCRIMINATOR IS SEEK RATE, and it took three predicates to land
     * here, each killed by a measurement:
     *
     *   delivered <= 1      too NARROW - the game seeks every 33 ms tick for
     *                       the whole scene step, so the cycle became re-arm,
     *                       absorb 4, re-arm, and the host storm detector
     *                       still fired (run 1, 2026-08-06).
     *   playing+same-path   too WIDE - it swallowed DELIBERATE mid-clip
     *                       restarts. At a ball change the game seeks its
     *                       still-playing backgrounds back to 0; this absorb
     *                       refused a seek at delivered=1780, the game's
     *                       timeline restarted while the picture played on
     *                       mid-clip, and David reported the stutter back
     *                       "very obvious" on ball 2 while every delivery
     *                       counter read clean.
     *   burst-only (this)   a storm seeks every 33 ms; a restart is isolated.
     *                       Only a seek arriving within 3 frame periods of
     *                       the previous seek on this stream is absorbed, so
     *                       the FIRST seek of any burst re-arms - which is
     *                       correct for both cases: a restart is honoured,
     *                       and a storm pays one re-arm instead of 93.
     *
     * A normal loop-at-EOS seek arrives with playing==0 (the thread stands
     * down BEFORE posting EOS) and re-arms as before; a location change
     * fails the path check and re-arms as before. */
    {
        unsigned long now = vid_us();
        long since = (long)(now - s->last_seek_us);
        int burst = s->last_seek_us != 0 && since >= 0 && since < 100000;
        s->last_seek_us = now;
        if (burst && s->playing && str_eq(s->prep_path, s->location)) {
            s->seek_absorbed++;
            if (s->seek_absorbed == 1)
                VLOG("[vid] ch%d seek %ld us after the last one (delivered "
                     "%u); absorbing the burst\n",
                     chan_of(s), since, s->delivered);
            s->pos_ns = 0;
            return 1;
        }
    }
    if (s->seek_absorbed) {
        VLOG("[vid] ch%d absorbed %u burst seeks\n",
             chan_of(s), s->seek_absorbed);
        s->seek_absorbed = 0;
    }
    pad_vid_stop(pipeline);
    /* Name the caller for the re-arm storm line. The two callers of prepare()
     * want opposite fixes - a game re-arming a pipeline it already has is not
     * the same fault as a clip looping too fast - and the host, which is where
     * the storm is visible as a cost, cannot see which one this is. */
    prepare_why = "rewind";
    if (!pad_vid_prepare(pipeline)) {
        prepare_why = "state";
        VLOG("[vid] ch%d rewind failed to re-arm the host\n", chan_of(s));
        return 0;
    }
    prepare_why = "state";
    pad_vid_play(pipeline);
    return 1;
}

/* Duration in nanoseconds, for query_duration. */
long long pad_vid_duration_ns(void *pipeline)
{
    struct stream *s = find_pipeline(pipeline);
    struct padvid_chan *c;
    if (!s || !vshm) return 0;
    c = &vshm->ch[chan_of(s)];
    if (!c->nframes || !c->fps_num) return 0;
    return (long long)c->nframes * 1000000000ll * c->fps_den / c->fps_num;
}

/* Playback position in nanoseconds, for query_position. Set to exactly the
 * duration at end of stream so the bus handler's "are we actually at the end"
 * test passes; it compares only the LOW 32 bits of the difference, so anything
 * approximate here would be a coin toss rather than a small error. */
long long pad_vid_position_ns(void *pipeline)
{
    struct stream *s = find_pipeline(pipeline);
    return s ? s->pos_ns : 0;
}
