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
    vshm = (struct padvid_shm *)p;
    vring = (unsigned char *)p + PADVID_HDR;
    VLOG("[vid] bridge attached: %s\n", path);
}

/* ---- the pipeline we are standing in for -------------------------------- */

static void *cur_pipeline;          /* the last pipeline_new() result        */
static void *cur_fakesink;          /* the object that got signal-handoffs   */
static void *cur_sinkpad;           /* its real "sink" pad - the handoff
                                     * callback is handed this and a consumer
                                     * that asks the pad for caps gets NULL, or
                                     * worse, if it is not a real pad. */
static void (*cur_handoff)(void *, void *, void *, void *);
static void *cur_handoff_data;
static char cur_location[PADVID_PATH_MAX];
static int  cur_ready;              /* host answered with a size             */
static int  cur_playing;
static unsigned cur_w, cur_h;

/* Our own caps/structure. Never handed to real GStreamer - every unref path is
 * interposed and recognises these two by address. */
static unsigned long fake_caps[8];
static unsigned long fake_struct[8];

int pad_vid_is_ours(void *p)
{
    return p && (p == (void *)fake_caps || p == (void *)fake_struct);
}

int pad_vid_is_pipeline(void *p) { return p && p == cur_pipeline; }

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
    unsigned long span = (unsigned long)PADVID_SLOTS * PADVID_SLOT_BYTES;
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

void pad_vid_note_location(const char *loc)
{
    str_copy(cur_location, loc, sizeof cur_location);
}

void pad_vid_note_pipeline(void *p) { cur_pipeline = p; cur_ready = 0; cur_playing = 0; }

void pad_vid_note_handoff(void *sink, void *fn, void *data)
{
    static void *(*get_pad)(void *, const char *);
    cur_fakesink = sink;
    if (!get_pad) get_pad = dlsym(RTLD_NEXT, "gst_element_get_static_pad");
    cur_sinkpad = (get_pad && sink) ? get_pad(sink, "sink") : 0;
    cur_handoff = (void (*)(void *, void *, void *, void *))fn;
    cur_handoff_data = data;
}

/* ---- GstBuffer, layout derived at run time ------------------------------ */

static void *vid_buf;
static int   off_data = -1, off_size = -1;

static int buf_layout(void)
{
    static void *(*real_alloc)(unsigned);
    unsigned probe = 0x00ABCDE0u;
    void *b;
    unsigned long *w;
    int i;
    if (off_data >= 0) return 1;
    if (!real_alloc) real_alloc = dlsym(RTLD_NEXT, "gst_buffer_new_and_alloc");
    if (!real_alloc) { VLOG("[vid] no gst_buffer_new_and_alloc\n"); return 0; }
    b = real_alloc(probe);
    if (!b) return 0;
    w = (unsigned long *)b;
    for (i = 2; i < 16; i++) {
        if ((unsigned)w[i] == probe && w[i - 1] > 0x1000) {
            off_size = i * 4;
            off_data = (i - 1) * 4;
            VLOG("[vid] GstBuffer layout: data at +%d, size at +%d\n",
                 off_data, off_size);
            vid_buf = b;
            return 1;
        }
    }
    VLOG("[vid] could NOT find the GstBuffer layout - video disabled\n");
    return 0;
}

/* ---- the streaming thread ----------------------------------------------- */

/* Defined below; the thread needs them before the file gets to them. */
static void post_eos(void *pipeline);
long long pad_vid_duration_ns(void);

/* The SpiVideoStreamDecoder, straight from gst_bus_add_watch's user_data. Its
 * own fields decide what the EOS handler at 0x5c1e7c does, so read them rather
 * than reason about them:
 *   +0x04 loop flag     +0x08 loop count   +0x0c its state (the EOS path needs
 *   1 or 2)             +0x19 frame-completed flag   +0x49 new-frame flag  */
static void *cur_decoder;

void pad_vid_note_decoder(void *p) { cur_decoder = p; }

static void vid_dump_decoder(const char *when)
{
    const unsigned char *b = (const unsigned char *)cur_decoder;
    if (!b) return;
    VLOG("[vid] decoder %s: loop=%u count=%u state=%u done19=%u new49=%u\n",
         when, b[4], *(const unsigned *)(b + 8), *(const unsigned *)(b + 12),
         b[0x19], b[0x49]);
}

/* Where playback has got to. This is not decoration: the game's bus handler
 * (0x5c1e3c) only acts on EOS if gst_element_query_position and
 * query_duration come back within 0.2 s of each other, and query_position used
 * to answer a flat 0. With a duration of several seconds the difference was
 * always too large, so even a correctly posted EOS would have been discarded. */
static long long cur_pos_ns;

static void *vid_thread(void *arg)
{
    unsigned consumed = 0;
    unsigned delay;
    (void)arg;
    if (!vshm) return 0;
    delay = 33333;
    if (vshm->fps_num && vshm->fps_den)
        delay = (unsigned)(1000000ull * vshm->fps_den / vshm->fps_num);
    VLOG("[vid] streaming %ux%u at %u/%u fps (%u us/frame)\n",
         vshm->width, vshm->height, vshm->fps_num, vshm->fps_den, delay);
    while (cur_playing && vshm->playing) {
        unsigned produced = vshm->write_idx;
        if (consumed >= produced) {
            if (vshm->eos) {
                /* Looping is the game's business: it seeks or rebuilds. Stop
                 * here rather than inventing a loop it did not ask for - but it
                 * cannot make that decision until it is TOLD the clip ended,
                 * and EOS is the only message that tells it. Without this the
                 * game stayed in its playing state with the last frame frozen
                 * on screen, which is exactly what "the video plays and then
                 * stalls" was. Report the position as exactly the duration
                 * first, because the handler checks that before it acts. */
                cur_pos_ns = pad_vid_duration_ns();
                VLOG("[vid] end of stream after %u frames, posting EOS "
                     "(pos=dur=%u ms)\n", consumed,
                     (unsigned)(cur_pos_ns / 1000000ll));
                vid_dump_decoder("at EOS");
                /* STAND DOWN BEFORE POSTING, not after. The handler runs on
                 * the game's main loop and it answers EOS by seeking straight
                 * back to 0, which arrives about a millisecond later. If this
                 * thread were still flagged as playing at that moment,
                 * pad_vid_play() would decline to start the next one and the
                 * loop would die silently. */
                cur_playing = 0;
                vshm->playing = 0;
                post_eos(cur_pipeline);
                return 0;
            }
            usleep(1000);
            continue;
        }
        {
            unsigned slot = consumed % PADVID_SLOTS;
            unsigned char *px = vring + (unsigned long)slot * PADVID_SLOT_BYTES;
            /* POINT the buffer at the ring. No copy. */
            *(unsigned long *)((char *)vid_buf + off_data) = (unsigned long)px;
            *(unsigned *)((char *)vid_buf + off_size) = vshm->frame_bytes;
            /* timestamp/duration sit right after size in the 0.10 layout, both
             * 64-bit. A consumer that sorts or drops on timestamp sees every
             * buffer at 0 otherwise, which looks like one frame repeated. */
            if (off_size + 4 + 8 <= 64) {
                unsigned long long *ts =
                    (unsigned long long *)((char *)vid_buf + off_size + 4);
                ts[0] = (unsigned long long)consumed * delay * 1000ull;
                ts[1] = (unsigned long long)delay * 1000ull;
            }
            if (cur_handoff)
                cur_handoff(cur_fakesink, vid_buf, cur_sinkpad, cur_handoff_data);
            consumed++;
            cur_pos_ns = (long long)consumed * delay * 1000ll;
            /* Only now may the host reuse this slot. */
            vshm->read_idx = consumed;
        }
        usleep(delay);
    }
    cur_playing = 0;
    vshm->playing = 0;
    return 0;
}

/* ---- entry points called from gststub.c --------------------------------- */

/* Ask the host to open the current location. Returns 1 if it can be played. */
int pad_vid_prepare(void)
{
    unsigned gen;
    int spins = 0;
    if (!vid_on()) return 0;
    vid_map();
    if (!vshm || !cur_location[0]) return 0;
    if (!buf_layout()) return 0;

    str_copy(vshm->path, cur_location, PADVID_PATH_MAX);
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
    vshm->playing = 1;
    gen = vshm->req_gen + 1;
    vshm->req_gen = gen;
    /* 3 s is generous: a probe measured 0.08 s. It exists so a dead host
     * cannot wedge the game's UI thread, which is what calls this. */
    while (vshm->ack_gen != gen && spins++ < 3000) usleep(1000);
    if (vshm->ack_gen != gen) { VLOG("[vid] host did not answer\n"); return 0; }
    if (vshm->status != PADVID_OK) return 0;
    cur_w = vshm->width;
    cur_h = vshm->height;
    cur_ready = 1;
    return 1;
}

/* Tell the game's bus watch what a real pipeline would have told it.
 *
 * The game adds a bus watch (gst_bus_add_watch) and imports
 * gst_message_parse_state_changed, so its video object is waiting to be told
 * the pipeline prerolled. Our set_state posts nothing, so it waited forever:
 * frames arrived at the handoff and were dropped because, as far as the object
 * was concerned, playback had never started.
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

void pad_vid_announce(int oldst, int newst)
{
    if (cur_pipeline) post_state(cur_pipeline, oldst, newst, 0);
}

int  pad_vid_ready(void) { return cur_ready; }
void *pad_vid_caps(void) { return (void *)fake_caps; }
void *pad_vid_structure(void) { return (void *)fake_struct; }

int pad_vid_get_int(const char *field, int *value)
{
    if (!value || !field) return 0;
    if (field[0] == 'w') { *value = (int)cur_w; return 1; }
    if (field[0] == 'h') { *value = (int)cur_h; return 1; }
    return 0;
}

void pad_vid_play(void)
{
    unsigned long th;
    if (!cur_ready || cur_playing || !vshm) return;
    cur_pos_ns = 0;
    cur_playing = 1;
    vshm->playing = 1;
    if (pthread_create(&th, 0, vid_thread, 0) != 0) {
        cur_playing = 0;
        vshm->playing = 0;
        VLOG("[vid] could not start the streaming thread\n");
    }
}

void pad_vid_stop(void)
{
    cur_playing = 0;
    if (vshm) vshm->playing = 0;
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
int pad_vid_seek(long long pos_ns)
{
    if (!cur_ready || !vshm || !cur_location[0]) return 0;
    if (pos_ns != 0)
        VLOG("[vid] seek to %u ms requested; only rewind is supported, "
             "restarting from 0\n", (unsigned)(pos_ns / 1000000ll));
    pad_vid_stop();
    if (!pad_vid_prepare()) { VLOG("[vid] rewind failed to re-arm the host\n"); return 0; }
    pad_vid_play();
    return 1;
}

/* Duration in nanoseconds, for query_duration. */
long long pad_vid_duration_ns(void)
{
    if (!vshm || !vshm->nframes || !vshm->fps_num) return 0;
    return (long long)vshm->nframes * 1000000000ll * vshm->fps_den / vshm->fps_num;
}

/* Playback position in nanoseconds, for query_position. Set to exactly the
 * duration at end of stream so the bus handler's "are we actually at the end"
 * test passes; it compares only the LOW 32 bits of the difference, so anything
 * approximate here would be a coin toss rather than a small error. */
long long pad_vid_position_ns(void) { return cur_pos_ns; }
