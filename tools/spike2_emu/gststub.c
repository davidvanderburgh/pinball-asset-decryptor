/* gststub.c - GStreamer interposer for the video path.
 *
 * TRACE ONLY, FOR NOW. Every function here logs and then chains straight to
 * the real libgstreamer, so behaviour is unchanged and this can be left in the
 * build safely. PAD_GST_TRACE=1 turns the logging on; with it unset the
 * overhead is one comparison per call.
 *
 * WHY TRACE BEFORE FAKING. The plan for video is the same split the GL bridge
 * already uses: decode on the HOST, because the guest has no software H.264
 * decoder at all (checked - of 175 plugins in gstreamer-0.10, the only one that
 * decodes h264 is libmfw_vpu.so, the i.MX6 hardware element; every other hit is
 * a demuxer, parser or muxer). Faking the API means answering for 37 entry
 * points, and guessing what the game does with them is how this rig
 * manufactures wrong conclusions. PAD_GL_TRACE established the whole GL
 * workload before glraster.c was written and made that job small; this is the
 * same move.
 *
 * What the trace is for, specifically:
 *   - which elements the game builds, in what order, and how it links them
 *   - the FILE it puts on filesrc (g_object_set "location")
 *   - the "handoff" callback it registers on the fakesink - that is where
 *     decoded frames arrive, and therefore where a host decoder must inject
 *   - the width/height it reads back through gst_structure_get_int
 *   - whether the appsrc path is used as well as the filesrc one
 *
 * VARARGS ARE FORWARDED PROPERLY, not re-implemented. g_object_set goes to
 * g_object_set_valist; the *_many calls are walked to NULL and re-dispatched
 * through their single-item forms. Getting this wrong silently corrupts the
 * pipeline, which would look like a video bug and would be this file's fault.
 */

#include <stdarg.h>

extern void *dlsym(void *, const char *);
#define RTLD_NEXT ((void *)-1L)
extern int snprintf(char *, unsigned long, const char *, ...);
extern char *getenv(const char *);
extern void pad_say(const char *);          /* hwshim.c's timestamped logger */

/* gstvid.c - the bridge that actually answers for the video pipelines. This
 * file stays the API surface and the trace; that one owns the state and the
 * frames. Everything that used to be implicit "the one current clip" now
 * carries the object the game passed - the pipeline for state and seeks, the
 * pad for caps, the caps/structure pointer for reads - because since the
 * multi-stream rework there can be several clips alive at once and the
 * pipeline IS the stream's identity. */
extern void pad_vid_note_location(void *, const char *);
extern void pad_vid_note_pipeline(void *);
extern void pad_vid_note_handoff(void *, void *, void *);
extern int  pad_vid_prepare(void *);
extern void *pad_vid_caps_for_pad(void *);
extern void *pad_vid_structure_for(void *);
extern int  pad_vid_get_int(void *, const char *, int *);
extern void pad_vid_play(void *);
extern void pad_vid_stop(void *);
extern int  pad_vid_is_ours(void *);
extern int  pad_vid_is_pipeline(void *);
extern long long pad_vid_duration_ns(void *);
extern long long pad_vid_position_ns(void *);
extern void pad_vid_note_decoder(void *);
extern int  pad_vid_seek(void *, long long);
extern void pad_vid_announce(void *, int, int);

static int gst_trace_on(void)
{
    static int on = -1;
    if (on == -1) {
        const char *e = getenv("PAD_GST_TRACE");
        on = (e && *e && *e != '0') ? 1 : 0;
    }
    return on;
}

#define GSTLOG(...)                                                     \
    do {                                                                \
        if (gst_trace_on()) {                                           \
            char b_[400];                                               \
            snprintf(b_, sizeof b_, __VA_ARGS__);                       \
            pad_say(b_);                                                \
        }                                                               \
    } while (0)

/* ---- element construction ------------------------------------------------ */

/* gst_element_factory_make is NOT here: hwshim.c has interposed it since the
 * audio work, and its `[gst] factory_make` count is the rig's yes/no for "has
 * the game left Tech Alerts" (status.sh, autoattract.sh). Two definitions in
 * one .so is a link error, and moving it here would quietly change a signal
 * several other things depend on. */

void *gst_pipeline_new(const char *name)
{
    static void *(*real)(const char *);
    void *r;
    if (!real) real = dlsym(RTLD_NEXT, "gst_pipeline_new");
    r = real ? real(name) : 0;
    pad_vid_note_pipeline(r);
    GSTLOG("[gst] pipeline_new(\"%s\") -> %p\n", name ? name : "(null)", r);
    return r;
}

/* g_object_set is where the FILENAME arrives, and it is variadic. Forward
 * through g_object_set_valist - the standard and only safe way to interpose a
 * varargs GObject setter. Re-implementing the property walk here would mean
 * parsing GTypes by hand and getting it wrong quietly. */
static int str_eq(const char *a, const char *b)
{
    if (!a || !b) return 0;
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

void g_object_set(void *obj, const char *first, ...)
{
    static void (*real_valist)(void *, const char *, va_list);
    va_list ap;
    if (!real_valist) real_valist = dlsym(RTLD_NEXT, "g_object_set_valist");

    /* Log the VALUE, not just the property name. "location" is the video file
     * the game wants to play and "output-format" decides the pixel layout a
     * host decoder would have to produce, so a trace without values answers
     * neither of the two questions this is here to answer.
     *
     * Read through a va_copy and forward the UNTOUCHED original. Reading the
     * caller's va_list and then handing the same one to g_object_set_valist
     * would forward a list already advanced past its first value, i.e. set the
     * property to whatever came next. The type is chosen by property name
     * because there is nothing else to go on at this layer; it is a log line,
     * not a decision, and only these five names are decoded. */
    va_start(ap, first);
    {
        va_list peek;
        va_copy(peek, ap);
        if (str_eq(first, "location")) {
            const char *v = va_arg(peek, const char *);
            /* `obj` matters, and it is item 15. The game keeps two pipelines
             * for a whole run and re-points them by filename, so the object
             * being set is the ONLY thing that says which stream this clip is
             * for - "the pipeline built most recently" stopped being the
             * answer the moment a second one existed. */
            pad_vid_note_location(obj, v);
            GSTLOG("[gst] set %p location=\"%s\"\n", obj, v ? v : "(null)");
        } else if (str_eq(first, "output-format") || str_eq(first, "frame-plus") ||
                   str_eq(first, "sync") || str_eq(first, "signal-handoffs")) {
            int v = va_arg(peek, int);
            GSTLOG("[gst] set %p %s=%d\n", obj, first, v);
        } else {
            GSTLOG("[gst] g_object_set(%p, \"%s\", ...)\n", obj, first ? first : "(null)");
        }
        va_end(peek);
    }
    if (real_valist) real_valist(obj, first, ap);
    va_end(ap);
}

/* The handoff callback: this is where decoded frames are delivered, so its
 * address is the single most important thing in the whole trace. */
unsigned long g_signal_connect_data(void *instance, const char *signal,
                                    void *handler, void *data,
                                    void *destroy, int flags)
{
    static unsigned long (*real)(void *, const char *, void *, void *, void *, int);
    unsigned long r;
    if (!real) real = dlsym(RTLD_NEXT, "g_signal_connect_data");
    r = real ? real(instance, signal, handler, data, destroy, flags) : 0;
    if (str_eq(signal, "handoff")) pad_vid_note_handoff(instance, handler, data);
    GSTLOG("[gst] connect(%p, \"%s\", handler=%p, data=%p) -> %lu\n",
           instance, signal ? signal : "(null)", handler, data, r);
    return r;
}

/* GST_STATE_CHANGE_FAILURE 0, SUCCESS 1, ASYNC 2, NO_PREROLL 3 */
int gst_element_set_state(void *element, int state)
{
    static int (*real)(void *, int);
    static const char *nm[5] = { "VOID", "NULL", "READY", "PAUSED", "PLAYING" };
    int r;
    if (!real) real = dlsym(RTLD_NEXT, "gst_element_set_state");

    /* OUR pipeline never goes near the real state machine. Letting the real
     * one run first would start vpudec, which is the thing that cannot work
     * and the thing that wedged the boot the last time its firmware loaded. */
    if (pad_vid_is_pipeline(element)) {
        if (state <= 2) {                 /* NULL / READY: tear down */
            pad_vid_stop(element);
            r = 1;
        } else if (state == 3) {          /* PAUSED: this is where it used to
                                           * fail, and where the host is asked
                                           * to open the file */
            r = pad_vid_prepare(element) ? 1 : 0;
            if (r) pad_vid_announce(element, 2, 3);   /* READY -> PAUSED, prerolled */
        } else {                          /* PLAYING */
            pad_vid_play(element);
            pad_vid_announce(element, 3, 4);          /* PAUSED -> PLAYING */
            r = 1;
        }
        GSTLOG("[gst] set_state(%p, %s) -> %d  [bridge]\n", element,
               (state >= 0 && state < 5) ? nm[state] : "?", r);
        return r;
    }

    r = real ? real(element, state) : 0;
    GSTLOG("[gst] set_state(%p, %s) -> %d\n", element,
           (state >= 0 && state < 5) ? nm[state] : "?", r);
    return r;
}

/* The game polls this after set_state. Answer for our pipeline without going
 * near the real one, which has no idea any of this happened. */
int gst_element_get_state(void *element, int *state, int *pending, unsigned long long timeout)
{
    static int (*real)(void *, int *, int *, unsigned long long);
    if (pad_vid_is_pipeline(element)) {
        if (state) *state = 4;            /* PLAYING */
        if (pending) *pending = 0;        /* VOID_PENDING */
        return 1;                         /* SUCCESS */
    }
    if (!real) real = dlsym(RTLD_NEXT, "gst_element_get_state");
    return real ? real(element, state, pending, timeout) : 0;
}

int gst_element_query_duration(void *element, int *format, long long *dur)
{
    static int (*real)(void *, int *, long long *);
    if (pad_vid_is_pipeline(element)) {
        if (dur) *dur = pad_vid_duration_ns(element);
        return 1;
    }
    if (!real) real = dlsym(RTLD_NEXT, "gst_element_query_duration");
    return real ? real(element, format, dur) : 0;
}

/* ---- the *_many calls: walk to NULL, re-dispatch singly ------------------ */

int gst_bin_add_many(void *bin, void *first, ...)
{
    static int (*real_add)(void *, void *);
    va_list ap;
    void *e = first;
    int n = 0;
    if (!real_add) real_add = dlsym(RTLD_NEXT, "gst_bin_add");
    va_start(ap, first);
    while (e) {
        if (real_add) real_add(bin, e);
        n++;
        e = va_arg(ap, void *);
    }
    va_end(ap);
    GSTLOG("[gst] bin_add_many(%p, %d elements)\n", bin, n);
    return 1;
}

int gst_element_link_many(void *first, ...)
{
    static int (*real_link)(void *, void *);
    va_list ap;
    void *a = first, *b;
    int n = 0, ok = 1;
    if (!real_link) real_link = dlsym(RTLD_NEXT, "gst_element_link");
    va_start(ap, first);
    for (;;) {
        b = va_arg(ap, void *);
        if (!b) break;
        if (real_link && !real_link(a, b)) ok = 0;
        n++;
        a = b;
    }
    va_end(ap);
    GSTLOG("[gst] link_many(%d links) -> %d\n", n, ok);
    return ok;
}

/* ---- what the game reads back ------------------------------------------- */

/* This returning NULL is the error the game reports. Once the host has probed
 * the file we hand back our own caps object instead. */
void *gst_pad_get_negotiated_caps(void *pad)
{
    static void *(*real)(void *);
    void *r;
    void *ours = pad_vid_caps_for_pad(pad);
    if (ours) {
        GSTLOG("[gst] pad_get_negotiated_caps(%p) -> bridge caps %p\n", pad, ours);
        return ours;
    }
    if (!real) real = dlsym(RTLD_NEXT, "gst_pad_get_negotiated_caps");
    r = real ? real(pad) : 0;
    GSTLOG("[gst] pad_get_negotiated_caps(%p) -> %p%s\n", pad, r,
           r ? "" : "   <-- NULL, and the bridge is not ready either");
    return r;
}

void *gst_caps_get_structure(void *caps, unsigned index)
{
    static void *(*real)(void *, unsigned);
    if (pad_vid_is_ours(caps)) return pad_vid_structure_for(caps);
    if (!real) real = dlsym(RTLD_NEXT, "gst_caps_get_structure");
    return real ? real(caps, index) : 0;
}

int gst_structure_get_int(void *s, const char *field, int *value)
{
    static int (*real)(void *, const char *, int *);
    int r;
    if (pad_vid_is_ours(s)) {
        r = pad_vid_get_int(s, field, value);
        GSTLOG("[gst] structure_get_int(\"%s\") -> %d value=%d  [bridge]\n",
               field ? field : "(null)", r, (r && value) ? *value : -1);
        return r;
    }
    if (!real) real = dlsym(RTLD_NEXT, "gst_structure_get_int");
    r = real ? real(s, field, value) : 0;
    GSTLOG("[gst] structure_get_int(\"%s\") -> %d value=%d\n",
           field ? field : "(null)", r, (r && value) ? *value : -1);
    return r;
}

/* OUR caps and structure are plain static arrays, not GObjects. Handing either
 * to the real refcounting would corrupt the heap, so every unref path has to
 * recognise them. Missing one of these is the kind of bug that shows up as a
 * crash somewhere unrelated, minutes later. */
void gst_caps_unref(void *caps)
{
    static void (*real)(void *);
    if (pad_vid_is_ours(caps)) return;
    if (!real) real = dlsym(RTLD_NEXT, "gst_caps_unref");
    if (real) real(caps);
}

void gst_object_unref(void *obj)
{
    static void (*real)(void *);
    if (pad_vid_is_ours(obj)) return;
    if (!real) real = dlsym(RTLD_NEXT, "gst_object_unref");
    if (real) real(obj);
}

void gst_mini_object_unref(void *obj)
{
    static void (*real)(void *);
    if (pad_vid_is_ours(obj)) return;
    if (!real) real = dlsym(RTLD_NEXT, "gst_mini_object_unref");
    if (real) real(obj);
}

/* THE BUS. A real pipeline posts state-changed and async-done messages when it
 * prerolls, and the game watches for them - it imports gst_bus_add_watch,
 * gst_message_parse_state_changed and gst_message_parse_error. Our fake
 * set_state posts nothing at all, so if the video object waits on the bus
 * before it will accept frames, it waits forever. Trace it before assuming. */
void *gst_pipeline_get_bus(void *pipeline)
{
    static void *(*real)(void *);
    void *r;
    if (!real) real = dlsym(RTLD_NEXT, "gst_pipeline_get_bus");
    r = real ? real(pipeline) : 0;
    GSTLOG("[gst] pipeline_get_bus(%p) -> %p%s\n", pipeline, r,
           pad_vid_is_pipeline(pipeline) ? "  [ours]" : "");
    return r;
}

unsigned gst_bus_add_watch(void *bus, void *func, void *data)
{
    static unsigned (*real)(void *, void *, void *);
    unsigned r;
    if (!real) real = dlsym(RTLD_NEXT, "gst_bus_add_watch");
    r = real ? real(bus, func, data) : 0;
    /* `data` is the SpiVideoStreamDecoder itself - the bus callback thunk at
     * 0x5c1390 passes it straight through as `this`. Keeping it lets the video
     * bridge read the object's own state out of guest memory instead of
     * inferring it, which is the only honest way to tell "the game ignored our
     * EOS" from "the game acted on it and its own gate said no". */
    pad_vid_note_decoder(data);
    GSTLOG("[gst] bus_add_watch(bus=%p, func=%p, data=%p) -> %u\n",
           bus, func, data, r);
    return r;
}

int gst_element_query_position(void *element, int *format, long long *pos)
{
    static int (*real)(void *, int *, long long *);
    static unsigned long n;
    if (pad_vid_is_pipeline(element)) {
        /* A flat 0 here was not harmless. The bus handler only acts on EOS
         * when duration - position is inside 0.2 s, so a constant 0 position
         * against a multi-second duration made every end-of-clip look like a
         * mid-clip hiccup and the game never moved on. */
        if (pos) *pos = pad_vid_position_ns(element);
        if ((n++ % 200) == 0) GSTLOG("[gst] query_position #%lu [ours]\n", n);
        return 1;
    }
    if (!real) real = dlsym(RTLD_NEXT, "gst_element_query_position");
    return real ? real(element, format, pos) : 0;
}

/* The game's ONLY way of repeating a clip: its EOS handler seeks to 0 rather
 * than tearing the pipeline down and building another. rate arrives in d0 under
 * the armhf calling convention, which is why it is a real `double` parameter
 * here and not something read off the stack. */
int gst_element_seek(void *element, double rate, int format, int flags,
                     int cur_type, long long cur, int stop_type, long long stop)
{
    static int (*real)(void *, double, int, int, int, long long, int, long long);
    (void)stop_type; (void)stop;
    if (pad_vid_is_pipeline(element)) {
        int r = pad_vid_seek(element, cur_type ? cur : 0);
        GSTLOG("[gst] seek(rate=%d/100 fmt=%d flags=%d to=%d ms) -> %d  [bridge]\n",
               (int)(rate * 100), format, flags, (int)(cur / 1000000ll), r);
        return r;
    }
    if (!real) real = dlsym(RTLD_NEXT, "gst_element_seek");
    return real ? real(element, rate, format, flags, cur_type, cur, stop_type, stop) : 0;
}

void *gst_bin_get_by_name(void *bin, const char *name)
{
    static void *(*real)(void *, const char *);
    void *r;
    if (!real) real = dlsym(RTLD_NEXT, "gst_bin_get_by_name");
    r = real ? real(bin, name) : 0;
    GSTLOG("[gst] bin_get_by_name(\"%s\") -> %p\n", name ? name : "(null)", r);
    return r;
}

int gst_app_src_push_buffer(void *appsrc, void *buffer)
{
    static int (*real)(void *, void *);
    static unsigned long n;
    int r;
    if (!real) real = dlsym(RTLD_NEXT, "gst_app_src_push_buffer");
    r = real ? real(appsrc, buffer) : 0;
    if ((n++ % 200) == 0)
        GSTLOG("[gst] app_src_push_buffer #%lu (%p) -> %d\n", n, buffer, r);
    return r;
}
