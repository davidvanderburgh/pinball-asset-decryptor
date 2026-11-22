/* gstclip.c - a TEST CARD clip through the machine's own video chain: see gstclip.h.
 *
 * Simon (2026-11-22), for judging a replacement clip with the game's overlay on it:
 * "It is vitally important that regardless of methodology the look must match exactly
 * how it would look in the game normally on the machine".  The decode is the game's:
 * the same elements, linked in the same order, the same VPU.  The YUV -> RGB step is
 * still this file's (BT.601 limited range); matching the game's own conversion is
 * the next step.
 *
 * GStreamer 0.10 is called through hand prototypes (the card has no headers for it)
 * and looked up with dlsym(RTLD_DEFAULT) AFTER the libraries are opened RTLD_GLOBAL,
 * so in the emulator a preloaded bridge's gst_* (padgst.so) are the ones called. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <time.h>
#include <pthread.h>
#include "gstclip.h"
#include "log.h"

int gclip_is_clip(const char *path)
{
    const char *dot = path ? strrchr(path, '.') : NULL;
    return dot && (!strcasecmp(dot, ".mp4") || !strcasecmp(dot, ".mov") || !strcasecmp(dot, ".m4v"));
}

#ifndef PAD_GSTCLIP

/* every machine but the Spike 2: no GStreamer 0.10 video chain to borrow */
struct gclip { int unused; };
struct gclip *gclip_open(const char *path, int max_w, int max_h, char *err, int errlen)
{
    (void)path; (void)max_w; (void)max_h;
    snprintf(err, errlen, "this machine has no video decoder for a clip (only a .padv plays here)");
    return NULL;
}
const struct art_image *gclip_frame(struct gclip *g, long long now_ms, int *k)
{ (void)g; (void)now_ms; (void)k; return NULL; }
const struct art_image *gclip_current(struct gclip *g) { (void)g; return NULL; }
int gclip_loops(const struct gclip *g) { (void)g; return 0; }
float gclip_fps(const struct gclip *g) { (void)g; return 0; }
int gclip_frames(const struct gclip *g) { (void)g; return 0; }
void gclip_stats(const struct gclip *g, int *shown, int *dropped)
{ (void)g; if (shown) *shown = 0; if (dropped) *dropped = 0; }
const char *gclip_error(const struct gclip *g) { (void)g; return ""; }
void gclip_close(struct gclip *g) { (void)g; }

#else

#include <dlfcn.h>
#include <unistd.h>

/* GStreamer 0.10 / GLib 2 values (gstelement.h, gstformat.h, gstevent.h) */
enum { GST_STATE_NULL = 1, GST_STATE_PAUSED = 3, GST_STATE_PLAYING = 4 };
enum { GST_STATE_CHANGE_FAILURE = 0 };
enum { GST_FORMAT_TIME = 3 };
enum { GST_SEEK_FLAG_FLUSH = 1, GST_SEEK_FLAG_KEY_UNIT = 4 };
enum { GST_SEEK_TYPE_NONE = 0, GST_SEEK_TYPE_SET = 1 };
#define FOURCC(a, b, c, d) ((unsigned)(a) | (unsigned)(b) << 8 | (unsigned)(c) << 16 | (unsigned)(d) << 24)

static struct {
    int tried, ok;
    char why[160];
    void (*init)(int *, char ***);
    void *(*pipeline_new)(const char *);
    void *(*factory_make)(const char *, const char *);
    int (*bin_add_many)(void *, void *, ...);
    int (*link_many)(void *, void *, ...);
    void (*object_set)(void *, const char *, ...);
    unsigned long (*signal_connect)(void *, const char *, void *, void *, void *, int);
    int (*set_state)(void *, int);
    int (*get_state)(void *, int *, int *, unsigned long long);
    void *(*static_pad)(void *, const char *);
    void *(*negotiated_caps)(void *);
    void *(*caps_structure)(void *, unsigned);
    int (*structure_int)(void *, const char *, int *);
    int (*structure_fourcc)(void *, const char *, unsigned *);
    int (*structure_fraction)(void *, const char *, int *, int *);
    void (*caps_unref)(void *);
    void (*object_unref)(void *);
    int (*query_position)(void *, int *, long long *);
    int (*query_duration)(void *, int *, long long *);
    int (*seek)(void *, double, int, int, int, long long, int, long long);
    void *(*buf_alloc)(unsigned);
    void (*mini_unref)(void *);
    int off_data, off_size;
} G;

static void *sym(const char *name)
{
    void *p = dlsym(RTLD_DEFAULT, name);
    if (!p && !G.why[0]) snprintf(G.why, sizeof G.why, "GStreamer has no %s", name);
    return p;
}

/* where a GstBuffer keeps its data pointer and size: found, not assumed (a real
 * buffer with an unusual size, its size field, the pointer just before it) -
 * the same probe as the emulator's bridge (gstvid.c buf_layout) */
static int buffer_layout(void)
{
    unsigned probe = 0x00ABCDE0u;
    unsigned long *w;
    void *b = G.buf_alloc(probe);
    int i;
    if (!b) return 0;
    w = (unsigned long *)b;
    for (i = 2; i < 16; i++)
        if ((unsigned)w[i] == probe && w[i - 1] > 0x1000) {
            G.off_size = i * (int)sizeof(long);
            G.off_data = (i - 1) * (int)sizeof(long);
            break;
        }
    if (G.mini_unref) G.mini_unref(b);
    return G.off_data > 0;
}

static int load(void)
{
    if (G.tried) return G.ok;
    G.tried = 1;
    if (!dlopen("libgstreamer-0.10.so.0", RTLD_NOW | RTLD_GLOBAL)
        || !dlopen("libgobject-2.0.so.0", RTLD_NOW | RTLD_GLOBAL)) {
        snprintf(G.why, sizeof G.why, "no GStreamer 0.10 on this card: %s", dlerror());
        return 0;
    }
    G.init = sym("gst_init");
    G.pipeline_new = sym("gst_pipeline_new");
    G.factory_make = sym("gst_element_factory_make");
    G.bin_add_many = sym("gst_bin_add_many");
    G.link_many = sym("gst_element_link_many");
    G.object_set = sym("g_object_set");
    G.signal_connect = sym("g_signal_connect_data");
    G.set_state = sym("gst_element_set_state");
    G.get_state = sym("gst_element_get_state");
    G.static_pad = sym("gst_element_get_static_pad");
    G.negotiated_caps = sym("gst_pad_get_negotiated_caps");
    G.caps_structure = sym("gst_caps_get_structure");
    G.structure_int = sym("gst_structure_get_int");
    G.caps_unref = sym("gst_caps_unref");
    G.object_unref = sym("gst_object_unref");
    G.query_position = sym("gst_element_query_position");
    G.query_duration = sym("gst_element_query_duration");
    G.seek = sym("gst_element_seek");
    G.buf_alloc = sym("gst_buffer_new_and_alloc");
    /* optional: the frame format and rate.  NOT under the emulator's bridge
     * (padgst.so, found by its own pad_vid_prepare): its caps are a stand-in
     * that only answers width and height, and the real library reading one
     * segfaulted the menu (2026-11-22) - its frames are I420, its rate is the
     * clip's own */
    if (!dlsym(RTLD_DEFAULT, "pad_vid_prepare")) {
        G.structure_fourcc = dlsym(RTLD_DEFAULT, "gst_structure_get_fourcc");
        G.structure_fraction = dlsym(RTLD_DEFAULT, "gst_structure_get_fraction");
    } else {
        sel_say("clip: the emulator's video bridge answers (frames I420)");
    }
    G.mini_unref = dlsym(RTLD_DEFAULT, "gst_mini_object_unref");
    if (G.why[0]) return 0;
    G.init(NULL, NULL);
    if (!buffer_layout()) {
        snprintf(G.why, sizeof G.why, "could not find the GstBuffer layout");
        return 0;
    }
    sel_say("clip: GStreamer 0.10 loaded (buffer data at +%d, size at +%d)", G.off_data, G.off_size);
    G.ok = 1;
    return 1;
}

struct gclip {
    void *pipe, *src, *demux, *queue, *dec, *sink;
    int w, h;                       /* the decoded size, from the caps */
    unsigned fourcc;                /* the decoded format (0: not said - taken as I420) */
    float fps;
    long long dur_ns;
    int ow, oh;                     /* what the caller is handed (fitted to the screen) */
    int max_w, max_h;
    pthread_mutex_t mu;
    unsigned char *px[2];           /* RGBA, ow * oh * 4: [front] is the caller's */
    int front;
    long long made, taken;          /* frames converted / frames handed out */
    long long last_frame_ms;
    int loops, seeking;
    int shown, dropped;
    struct art_image out;
    int have_out;
    char err[200];
    char path[600];
};

static long long now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static unsigned char clamp8(int v) { return v < 0 ? 0 : v > 255 ? 255 : (unsigned char)v; }

/* one decoded frame -> RGBA in the back buffer (BT.601, limited range, nearest
 * sample when it is fitted down) */
static void convert(struct gclip *g, const unsigned char *data, unsigned size, unsigned char *dst)
{
    int sw = g->w, sh = g->h, x, y;
    int ys = sw, ph = sh, nv12 = g->fourcc == FOURCC('N', 'V', '1', '2');
    int yv12 = g->fourcc == FOURCC('Y', 'V', '1', '2');
    const unsigned char *Y, *U, *V;
    /* a decoder may pad the planes to 16: find the stride the size says */
    static const int al[] = { 1, 16, 32, 64 };
    int i, j;
    for (i = 0; i < 4; i++)
        for (j = 0; j < 4; j++) {
            int aw = (sw + al[i] - 1) / al[i] * al[i], ah = (sh + al[j] - 1) / al[j] * al[j];
            if ((unsigned)(aw * ah * 3 / 2) == size) { ys = aw; ph = ah; i = j = 4; }
        }
    Y = data;
    if (nv12) { U = data + ys * ph; V = U + 1; }
    else {
        const unsigned char *p1 = data + ys * ph, *p2 = p1 + (ys / 2) * (ph / 2);
        U = yv12 ? p2 : p1;
        V = yv12 ? p1 : p2;
    }
    for (y = 0; y < g->oh; y++) {
        int sy = (int)((long long)y * sh / g->oh);
        unsigned char *o = dst + (size_t)y * g->ow * 4;
        for (x = 0; x < g->ow; x++) {
            int sx = (int)((long long)x * sw / g->ow);
            int c = Y[sy * ys + sx] - 16, d, e;
            if (nv12) {
                int k = (sy / 2) * ys + (sx / 2) * 2;
                d = U[k] - 128;
                e = V[k] - 128;
            } else {
                int k = (sy / 2) * (ys / 2) + sx / 2;
                d = U[k] - 128;
                e = V[k] - 128;
            }
            o[0] = clamp8((298 * c + 409 * e + 128) >> 8);
            o[1] = clamp8((298 * c - 100 * d - 208 * e + 128) >> 8);
            o[2] = clamp8((298 * c + 516 * d + 128) >> 8);
            o[3] = 255;
            o += 4;
        }
    }
}

/* fakesink's "handoff", on GStreamer's streaming thread: (sink, buffer, pad, data) */
static void on_handoff(void *sink, void *buf, void *pad, void *data)
{
    struct gclip *g = data;
    const unsigned char *px = *(const unsigned char **)((char *)buf + G.off_data);
    unsigned size = *(unsigned *)((char *)buf + G.off_size);
    int back;
    (void)sink; (void)pad;
    if (!px || !g->ow) return;
    pthread_mutex_lock(&g->mu);
    back = !g->front;
    pthread_mutex_unlock(&g->mu);
    convert(g, px, size, g->px[back]);
    pthread_mutex_lock(&g->mu);
    if (g->made > g->taken) g->dropped++;   /* the one before was never shown */
    g->front = back;
    g->made++;
    g->last_frame_ms = now_ms();
    pthread_mutex_unlock(&g->mu);
}

/* the size (and format) vpudec negotiated with the sink */
static int read_caps(struct gclip *g)
{
    void *pad = G.static_pad(g->sink, "sink"), *caps, *s;
    int ok = 0, n = 0, d = 0;
    if (!pad) return 0;
    caps = G.negotiated_caps(pad);
    if (caps) {
        s = G.caps_structure(caps, 0);
        if (s && G.structure_int(s, "width", &g->w) && G.structure_int(s, "height", &g->h)
            && g->w > 0 && g->h > 0) ok = 1;
        if (s && G.structure_fourcc) G.structure_fourcc(s, "format", &g->fourcc);
        if (s && G.structure_fraction && G.structure_fraction(s, "framerate", &n, &d) && n > 0 && d > 0)
            g->fps = (float)n / (float)d;
        G.caps_unref(caps);
    }
    G.object_unref(pad);
    return ok;
}

struct gclip *gclip_open(const char *path, int max_w, int max_h, char *err, int errlen)
{
    struct gclip *g;
    int fmt = GST_FORMAT_TIME, st = 0, pend = 0, r;
    if (!load()) { snprintf(err, errlen, "clip: %s", G.why); return NULL; }
    g = calloc(1, sizeof *g);
    if (!g) { snprintf(err, errlen, "clip: out of memory"); return NULL; }
    pthread_mutex_init(&g->mu, NULL);
    g->max_w = max_w;
    g->max_h = max_h;
    snprintf(g->path, sizeof g->path, "%s", path);
    /* the game's own chain, made and linked in the game's order (gstvid.c's header) */
    g->pipe = G.pipeline_new("padclip");
    g->src = G.factory_make("filesrc", "src");
    g->demux = G.factory_make("qtdemux", "demux");
    g->queue = G.factory_make("queue", "queue");
    g->dec = G.factory_make("vpudec", "dec");
    g->sink = G.factory_make("fakesink", "sink");
    if (!g->pipe || !g->src || !g->demux || !g->queue || !g->dec || !g->sink) {
        snprintf(err, errlen, "clip: the card's GStreamer lacks %s",
                 !g->src ? "filesrc" : !g->demux ? "qtdemux" : !g->queue ? "queue"
                 : !g->dec ? "vpudec (the video chip's decoder)" : !g->sink ? "fakesink" : "a pipeline");
        goto fail;
    }
    G.object_set(g->src, "location", path, NULL);
    /* the frames at the clip's own pace (sync), each one handed to us */
    G.object_set(g->sink, "signal-handoffs", 1, "sync", 1, NULL);
    G.signal_connect(g->sink, "handoff", (void *)on_handoff, g, NULL, 0);
    G.bin_add_many(g->pipe, g->src, g->demux, g->queue, g->dec, g->sink, NULL);
    /* qtdemux's pad appears once the file is read: 0.10 links it then */
    G.link_many(g->src, g->demux, g->queue, g->dec, g->sink, NULL);
    r = G.set_state(g->pipe, GST_STATE_PAUSED);
    if (r == GST_STATE_CHANGE_FAILURE) { snprintf(err, errlen, "clip: %s would not start", path); goto fail; }
    /* preroll: up to 5 s for the first frame to reach the sink */
    G.get_state(g->pipe, &st, &pend, 5000000000ULL);
    if (!read_caps(g)) { snprintf(err, errlen, "clip: the decoder gave no picture size for %s", path); goto fail; }
    g->ow = g->w;
    g->oh = g->h;
    if (g->ow > max_w || g->oh > max_h) {       /* fitted down, never up */
        if ((long long)g->w * max_h > (long long)g->h * max_w) { g->ow = max_w; g->oh = (int)((long long)g->h * max_w / g->w); }
        else { g->oh = max_h; g->ow = (int)((long long)g->w * max_h / g->h); }
    }
    g->px[0] = calloc((size_t)g->ow * g->oh, 4);
    g->px[1] = calloc((size_t)g->ow * g->oh, 4);
    if (!g->px[0] || !g->px[1]) { snprintf(err, errlen, "clip: out of memory for %dx%d", g->ow, g->oh); goto fail; }
    if (G.query_duration(g->pipe, &fmt, &g->dur_ns) && fmt == GST_FORMAT_TIME && g->dur_ns > 0) {}
    else g->dur_ns = 0;
    if (G.set_state(g->pipe, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
        snprintf(err, errlen, "clip: %s would not play", path);
        goto fail;
    }
    if (g->fps <= 0) g->fps = 30.0f;
    sel_say("clip: %s %dx%d %c%c%c%c%s, %.3f s, shown at %dx%d", path, g->w, g->h,
            g->fourcc ? (char)(g->fourcc & 255) : 'I', g->fourcc ? (char)(g->fourcc >> 8 & 255) : '4',
            g->fourcc ? (char)(g->fourcc >> 16 & 255) : '2', g->fourcc ? (char)(g->fourcc >> 24) : '0',
            g->fourcc ? "" : " (format not said)", g->dur_ns / 1e9, g->ow, g->oh);
    g->last_frame_ms = now_ms();
    return g;
fail:
    gclip_close(g);
    return NULL;
}

/* at the end, back to the start: by position when the clip says its length,
 * else when no frame has come for a second */
static void maybe_loop(struct gclip *g, long long now)
{
    int fmt = GST_FORMAT_TIME;
    long long pos = 0, quiet;
    pthread_mutex_lock(&g->mu);
    quiet = now - g->last_frame_ms;
    pthread_mutex_unlock(&g->mu);
    if (quiet < 300) { g->seeking = 0; return; }
    if (g->seeking && quiet < 3000) return;
    if (g->dur_ns > 0 && quiet < 1000
        && !(G.query_position(g->pipe, &fmt, &pos) && fmt == GST_FORMAT_TIME
             && pos >= g->dur_ns - 200000000LL)) return;
    G.seek(g->pipe, 1.0, GST_FORMAT_TIME, GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_KEY_UNIT,
           GST_SEEK_TYPE_SET, 0, GST_SEEK_TYPE_NONE, -1);
    G.set_state(g->pipe, GST_STATE_PLAYING);
    g->seeking = 1;
    g->loops++;
    pthread_mutex_lock(&g->mu);
    g->last_frame_ms = now;
    pthread_mutex_unlock(&g->mu);
}

const struct art_image *gclip_frame(struct gclip *g, long long now, int *k)
{
    int fresh = 0;
    (void)now;
    maybe_loop(g, now_ms());
    pthread_mutex_lock(&g->mu);
    if (g->made > g->taken) {
        g->taken = g->made;
        g->out.w = g->ow;
        g->out.h = g->oh;
        g->out.rgba = g->px[g->front];
        g->have_out = 1;
        g->shown++;
        fresh = 1;
        if (k) *k = (int)g->taken;
    }
    pthread_mutex_unlock(&g->mu);
    return fresh ? &g->out : NULL;
}

/* NOTE: the caller draws from out.rgba while the streaming thread may be
 * converting into the OTHER buffer - never into the one handed out, unless two
 * frames arrive between two looks; then a frame may tear (seen as a dropped one) */
const struct art_image *gclip_current(struct gclip *g) { return g->have_out ? &g->out : NULL; }
int gclip_loops(const struct gclip *g) { return g->loops; }
float gclip_fps(const struct gclip *g) { return g->fps; }
int gclip_frames(const struct gclip *g)
{
    return g->dur_ns > 0 ? (int)(g->dur_ns / 1e9 * g->fps + 0.5) : 0;
}
void gclip_stats(const struct gclip *g, int *shown, int *dropped)
{
    if (shown) *shown = g->shown;
    if (dropped) *dropped = g->dropped;
}
const char *gclip_error(const struct gclip *g) { return g->err; }

void gclip_close(struct gclip *g)
{
    if (!g) return;
    if (g->pipe) {
        G.set_state(g->pipe, GST_STATE_NULL);
        G.object_unref(g->pipe);            /* the bin's elements go with it */
    } else {
        void *e[] = { g->src, g->demux, g->queue, g->dec, g->sink };
        int i;
        for (i = 0; i < 5; i++) if (e[i]) G.object_unref(e[i]);
    }
    free(g->px[0]);
    free(g->px[1]);
    pthread_mutex_destroy(&g->mu);
    free(g);
}

#endif
