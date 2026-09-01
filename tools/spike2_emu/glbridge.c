/* glbridge.c - guest side of the GL bridge. Becomes libGLESv2.so.2 INSTEAD of
 * glraster.c when the rig is run in bridge mode.
 *
 * It implements no rendering at all. Every GL call is serialised into a shared
 * memory ring (see padgl.h) and replayed by a native x86-64 helper on real
 * GLES, because guest ARM code under qemu-user cannot reach a GPU itself.
 *
 * The design rests on measurements, not hope:
 *   - the ONLY per-frame readbacks are glGetIntegerv(GL_BLEND_SRC/DST), which
 *     are shadowed locally here, so nothing blocks per frame
 *   - object names are allocated BY THE GUEST and mirrored on the host, so the
 *     glGen and glCreate calls need no round trip either
 *   - uniform locations are guest-assigned slot numbers; the host maps slot ->
 *     real location using the name registered once at glGetUniformLocation
 *
 * Anything not implemented must fail LOUDLY. A GL bridge that silently drops
 * calls produces a plausible-looking wrong picture, which is the same trap as
 * the shim that faked successful reads.
 */

#include "padgl.h"

extern void *memcpy(void *, const void *, unsigned long);
extern void *memset(void *, int, unsigned long);
extern unsigned long strlen(const char *);
extern int strcmp(const char *, const char *);
extern char *strstr(const char *, const char *);
extern int snprintf(char *, unsigned long, const char *, ...);
extern long write(int, const void *, unsigned long);
extern int open(const char *, int, ...);
extern int close(int);
extern char *getenv(const char *);
extern void *mmap(void *, unsigned long, int, int, int, long);
extern int usleep(unsigned int);

static void say(const char *s) { write(2, s, strlen(s)); }

/* ---------------- ring ---------------- */
static padgl_hdr *hdr;
static unsigned char *ring;
static unsigned int ring_bytes;
static int bridge_dead;

static int bridge_init(void)
{
    static int tried;
    const char *path;
    int fd;
    void *p;
    unsigned long total;

    if (hdr) return 1;
    if (tried) return 0;
    tried = 1;

    path = getenv("PAD_GL_BRIDGE");
    if (!path || !path[0]) return 0;

    fd = open(path, 2 /*O_RDWR*/);
    if (fd < 0) { say("[bridge] cannot open the shared ring; is padgl-host running?\n"); return 0; }

    /* Map the header alone first so the real size can be read from it. */
    p = mmap(0, PADGL_HDR_BYTES, 3 /*RW*/, 1 /*MAP_SHARED*/, fd, 0);
    if (!p || p == (void *)-1) { say("[bridge] mmap of the header failed\n"); close(fd); return 0; }
    {
        padgl_hdr *h = (padgl_hdr *)p;
        if (h->magic != PADGL_MAGIC || h->version != PADGL_VERSION) {
            say("[bridge] ring magic/version mismatch\n"); close(fd); return 0;
        }
        ring_bytes = h->ring_bytes;
    }
    total = (unsigned long)PADGL_HDR_BYTES + ring_bytes;
    p = mmap(0, total, 3, 1, fd, 0);
    close(fd);
    if (!p || p == (void *)-1) { say("[bridge] mmap of the ring failed\n"); return 0; }

    hdr  = (padgl_hdr *)p;
    ring = (unsigned char *)p + PADGL_HDR_BYTES;
    hdr->guest_alive = 1;
    {
        char t[120];
        snprintf(t, sizeof t, "[bridge] attached, ring %u MB, host target %ux%u\n",
                 ring_bytes >> 20, hdr->fb_w, hdr->fb_h);
        say(t);
    }
    return 1;
}

/* Head value reserve() captured for the command now being emitted.  emit()
 * publishes head as resv_base + need — an ABSOLUTE store, never `+=` on the
 * live header.  A leave-running save can freeze the guest INSIDE emit()
 * (between reserve and publish) while the not-yet-killed guest plays on and
 * advances the shared head; a `+=` after restore then publishes `need` bytes
 * at the LIVE head while the payload sits at the save-time offset, and the
 * host dispatches lap-old ring bytes as a command — the Mesa
 * memcpy-from-near-NULL padglhost crash.  The absolute store makes a
 * mid-emit restore step head BACKWARD to the guest's true position instead,
 * which is exactly the state padglhost's rewound-counters guard resyncs on
 * (one command dropped, renderer lives).  Single producer, one emitting
 * thread, so outside that restore window this is identical to `+=`. */
static unsigned long long resv_base;

/* Reserve n bytes, waiting for the host to drain if the ring is full. */
static unsigned char *reserve(unsigned int n, unsigned int *at)
{
    unsigned long long head, tail;
    int spins = 0;
    if (!hdr || bridge_dead) return 0;
    n = (n + 7u) & ~7u;
    if (n > ring_bytes / 2) { say("[bridge] command too large for the ring\n"); return 0; }
    for (;;) {
        head = hdr->head;
        tail = hdr->tail;
        if (head - tail + n <= ring_bytes) break;
        if (++spins > 200000) { bridge_dead = 1; say("[bridge] host stalled; giving up\n"); return 0; }
        usleep(50);
    }
    resv_base = head;
    *at = (unsigned int)(resv_base % ring_bytes);
    return ring;
}

static void ring_put(unsigned int off, const void *src, unsigned int n)
{
    unsigned int first = ring_bytes - off;
    if (n <= first) memcpy(ring + off, src, n);
    else { memcpy(ring + off, src, first);
           memcpy(ring, (const unsigned char *)src + first, n - first); }
}

/* One command: header + up to two payload chunks (fixed args, then bulk data). */
static void emit(unsigned int op, const void *a, unsigned int alen,
                 const void *b, unsigned int blen)
{
    padgl_cmd c;
    unsigned int need, off;
    if (!bridge_init()) return;
    c.op = op;
    c.len = alen + blen;
    need = (unsigned int)sizeof c + ((c.len + 7u) & ~7u);
    if (!reserve(need, &off)) return;
    ring_put(off, &c, sizeof c);
    off = (off + (unsigned int)sizeof c) % ring_bytes;
    if (alen) { ring_put(off, a, alen); off = (off + alen) % ring_bytes; }
    if (blen) { ring_put(off, b, blen); }
    hdr->head = resv_base + need;      /* absolute, not += — see resv_base */
}

static void emit_u(unsigned int op, const unsigned int *v, unsigned int count)
{ emit(op, v, count * 4u, 0, 0); }

/* ---------------- guest-side shadow state ---------------- */
#define MAXPROG 128
#define MAXUNI  32

typedef struct { char name[40]; } Uni;
static struct { Uni u[MAXUNI]; int n; } prog_uni[MAXPROG];

static int id_tex = 1, id_buf = 1, id_fbo = 1, id_vao = 1, id_obj = 1;
static int blend_src = 1, blend_dst = 0;          /* shadowed: read back per frame */
static int fb_w = 1920, fb_h = 1080;
static int frame_no;

static int envint(const char *n, int dflt)
{
    char *p = getenv(n);
    int v = 0, any = 0;
    if (!p) return dflt;
    while (*p >= '0' && *p <= '9') { v = v * 10 + (*p - '0'); p++; any = 1; }
    return any ? v : dflt;
}

int pad_fb_width(void)  { fb_w = envint("PAD_GL_W", 1920); return fb_w; }
int pad_fb_height(void) { fb_h = envint("PAD_GL_H", 1080); return fb_h; }

/* eglshim reports these; keep the symbols so it links against either backend. */
long pad_readback_counts(long *e, long *i, long *u, long *a, long *s, long *p)
{ *e = *i = *u = *a = *s = *p = 0; return frame_no; }
long pad_getintegerv_hist(unsigned int *names, long *counts)
{ int k; for (k = 0; k < 8; k++) { names[k] = 0; counts[k] = 0; } return 8; }

/* item 44: eglshim announces which display the ops that follow belong to.
 * Through emit_u so it is ordered with the draws in the ring - a target that
 * bypassed the ring could overtake the scene it labels. */
void pad_target(int disp)
{
    unsigned int v[1];
    if (!bridge_init()) return;
    v[0] = (unsigned int)disp;
    emit_u(PADGL_TARGET, v, 1);
}

void pad_present(void)
{
    unsigned int v[1];
    if (!bridge_init()) return;
    frame_no++;
    v[0] = (unsigned int)frame_no;
    emit_u(PADGL_SWAP, v, 1);
    hdr->frame_seq++;
    /* Frames in flight. Every one of these is 16.7 ms between the game reacting
     * to a switch and the picture showing it, so this is an input-latency knob
     * as much as a throughput one. 1 is the responsive setting and costs a
     * little guest/host overlap; PAD_GL_INFLIGHT raises it if a slower host ever
     * needs the slack back. */
    {
        static int inflight = -1;
        int spins = 0;
        if (inflight < 0) inflight = envint("PAD_GL_INFLIGHT", 1);
        while (hdr->frame_seq - hdr->frame_ack > (unsigned long long)inflight) {
            if (++spins > 200000) { bridge_dead = 1; break; }
            usleep(50);
        }
    }
}

/* ---------------- GL entry points ---------------- */
#define U(...) do { unsigned int _v[] = { __VA_ARGS__ }; \
                    emit_u(op_, _v, sizeof _v / 4u); } while (0)

/* PAD_GL_VPLOG=1 - say what rectangle the GUEST asked to draw into.
 *
 * Item 42: a menu came up with the picture in a band exactly half the
 * framebuffer height, vertically centred, and no menu text - with ZERO GL
 * errors, zero Radium errors, and the guest rendering happily at 52.9 fps.
 * Nothing was failing, so the only question is who chose that rectangle: the
 * game, or us placing its output. Both viewport and scissor are forwarded to
 * the host and NEITHER SIDE PRINTED THEM, so those two answers were
 * indistinguishable from outside the process.
 *
 * DEDUPED, because these are per-frame calls and an undeduped log at 50 fps
 * buries the run in its own noise. Only a CHANGE prints - which is exactly the
 * interesting event, since a screen that switches to a half-height viewport
 * says so in one line and then stays quiet.
 */
static int vplog = -1;
static void vp_say(const char *what, int x, int y, int w, int h)
{
    static int lx[2], ly[2], lw[2], lh[2], seen[2];
    int i = what[0] == 'v' ? 0 : 1;
    char b[120];
    if (vplog < 0) vplog = envint("PAD_GL_VPLOG", 0);
    if (!vplog) return;
    if (seen[i] && lx[i] == x && ly[i] == y && lw[i] == w && lh[i] == h) return;
    lx[i] = x; ly[i] = y; lw[i] = w; lh[i] = h; seen[i] = 1;
    snprintf(b, sizeof b, "[gl] %s %d,%d %dx%d   (fb %dx%d, frame %d)\n",
             what, x, y, w, h, fb_w, fb_h, frame_no);
    say(b);
}

int glViewport(int x, int y, int w, int h)
{ const unsigned int op_ = PADGL_VIEWPORT; vp_say("viewport", x, y, w, h);
  U((unsigned)x,(unsigned)y,(unsigned)w,(unsigned)h); return 0; }

int glScissor(int x, int y, int w, int h)
{ const unsigned int op_ = PADGL_SCISSOR; vp_say("scissor ", x, y, w, h);
  U((unsigned)x,(unsigned)y,(unsigned)w,(unsigned)h); return 0; }

int glClearColor(float r, float g, float b, float a)
{ float v[4]; v[0]=r; v[1]=g; v[2]=b; v[3]=a; emit(PADGL_CLEARCOLOR, v, 16, 0, 0); return 0; }

int glClear(unsigned int mask)
{ const unsigned int op_ = PADGL_CLEAR; U(mask); return 0; }

int glEnable(unsigned int cap)  { const unsigned int op_ = PADGL_ENABLE;  U(cap); return 0; }
int glDisable(unsigned int cap) { const unsigned int op_ = PADGL_DISABLE; U(cap); return 0; }
int glIsEnabled(unsigned int cap) { (void)cap; return 1; }

int glBlendFunc(unsigned int s, unsigned int d)
{ const unsigned int op_ = PADGL_BLENDFUNC; blend_src = (int)s; blend_dst = (int)d; U(s,d); return 0; }

int glBlendFuncSeparate(unsigned int s, unsigned int d, unsigned int as, unsigned int ad)
{ const unsigned int op_ = PADGL_BLENDFUNCSEP; blend_src = (int)s; blend_dst = (int)d; U(s,d,as,ad); return 0; }

int glBlendEquation(unsigned int m) { const unsigned int op_ = PADGL_BLENDEQ; U(m); return 0; }
int glBlendEquationSeparate(unsigned int r, unsigned int a)
{ const unsigned int op_ = PADGL_BLENDEQSEP; U(r,a); return 0; }

/* ---- textures ---- */
static int next_of(int *c, int max) { int v = *c; if (++(*c) >= max) *c = 1; return v; }

int glGenTextures(int n, unsigned int *ids)
{
    int i;
    for (i = 0; i < n; i++) {
        const unsigned int op_ = PADGL_GENTEX;
        ids[i] = (unsigned int)next_of(&id_tex, 4096);
        U(ids[i]);
    }
    return 0;
}
int glDeleteTextures(int n, const unsigned int *ids)
{ int i; for (i = 0; i < n; i++) { const unsigned int op_ = PADGL_DELTEX; U(ids[i]); } return 0; }

/* ★ ITEM 43: WHICH TEXTURE THE VIVANTE DIRECT-TEXTURE CALLS MEAN.
 *
 * glTexDirectVIVMap / glTexDirectVIV / glTexDirectInvalidateVIV take a TARGET
 * and no texture name - the extension names the texture implicitly, by what is
 * bound. So the only way to answer "which texture is this registration for" is
 * to shadow the binding here, and until 2026-08-12 this file did not: it kept
 * ONE process-global registration, and the service menu paid for it for a week.
 * The menu binds its own 1024x256 RGBA DMD texture and invalidates it; the
 * global was last written by the video path; so the bridge sent the VIDEO's
 * 1360x768 I420 registration and the host uploaded video pixels into the menu's
 * quad. That is the band, and the game was drawing its menu correctly the whole
 * time. Captured proof, C:\tmp\item43_pathA_phase1.txt: `BINDTEX 3553 2`
 * immediately followed by `TEXDIRECT 1360 768 36805` - texture 2 asked for,
 * video's registration sent.
 *
 * Keying on the bound GL_TEXTURE_2D name is sound for every user in this
 * binary, checked in the disassembly rather than assumed: Texture::Texture
 * (0x4d9dd4) binds at 0x4d9e10 BEFORE both direct calls and unbinds only at
 * 0x4d9fac; Texture::SetPixels binds through the virtual Bind() at 0x4da10c
 * before invalidating at 0x4da12c; and the video path binds [this+332] before
 * its Map. Every one of them has its texture bound at both moments. */
static unsigned cur_unit;                /* index, not the GL_TEXTURE0 enum */
static unsigned cur_tex2d[16];

/* item 51: two guest texture names can wrap ONE buffer (star_wars allocates
 * its playfield-LCD framebuffer through glTexDirectVIV on one name and Maps
 * the returned pointer under another - render target and sampler of the
 * same memory, the Vivante zero-copy idiom). The host has no shared backing,
 * so the EMITTED name is translated to the canonical one; the guest-side
 * shadows keep the game's own names. */
static unsigned viv_alias(unsigned name);

int glBindTexture(unsigned int t, unsigned int id)
{ const unsigned int op_ = PADGL_BINDTEX;
  if (t == 0x0DE1u) cur_tex2d[cur_unit & 15u] = id;   /* GL_TEXTURE_2D */
  U(t,viv_alias(id)); return 0; }
int glActiveTexture(unsigned int u)
{ const unsigned int op_ = PADGL_ACTIVETEX; cur_unit = (u - 0x84C0u) & 15u; U(u); return 0; }
int glTexParameteri(unsigned int t, unsigned int p, int v)
{ const unsigned int op_ = PADGL_TEXPARAM; U(t,p,(unsigned)v); return 0; }

static unsigned int pixel_bytes(unsigned int fmt, unsigned int type, int w, int h)
{
    unsigned int c = 4;
    switch (fmt) {
    case 0x1908: c = 4; break;                       /* RGBA            */
    case 0x1907: c = 3; break;                       /* RGB             */
    case 0x190A: c = 2; break;                       /* LUMINANCE_ALPHA */
    case 0x1909: case 0x1906: case 0x1903: c = 1; break;
    default: c = 4; break;
    }
    if (type != 0x1401) c = 2;                       /* packed 16-bit types */
    return c * (unsigned)w * (unsigned)h;
}

int glTexImage2D(unsigned int target, int level, int ifmt, int w, int h,
                 int border, unsigned int fmt, unsigned int type, const void *px)
{
    unsigned int a[7];
    (void)target; (void)border;
    a[0] = (unsigned)level; a[1] = (unsigned)ifmt; a[2] = (unsigned)w; a[3] = (unsigned)h;
    a[4] = fmt; a[5] = type; a[6] = px ? pixel_bytes(fmt, type, w, h) : 0;
    emit(PADGL_TEXIMAGE, a, sizeof a, px, a[6]);
    return 0;
}

int glTexSubImage2D(unsigned int target, int level, int x, int y, int w, int h,
                    unsigned int fmt, unsigned int type, const void *px)
{
    unsigned int a[8];
    (void)target;
    a[0] = (unsigned)level; a[1] = (unsigned)x; a[2] = (unsigned)y;
    a[3] = (unsigned)w; a[4] = (unsigned)h; a[5] = fmt; a[6] = type;
    a[7] = px ? pixel_bytes(fmt, type, w, h) : 0;
    emit(PADGL_TEXSUBIMAGE, a, sizeof a, px, a[7]);
    return 0;
}

int glCompressedTexImage2D(unsigned int target, int level, unsigned int ifmt,
                           int w, int h, int border, int size, const void *data)
{
    unsigned int a[5];
    (void)target; (void)border;
    a[0] = (unsigned)level; a[1] = ifmt; a[2] = (unsigned)w; a[3] = (unsigned)h;
    a[4] = (unsigned)(size > 0 ? size : 0);
    emit(PADGL_TEXCOMPRESSED, a, sizeof a, data, a[4]);
    return 0;
}

/* ★ NOT A STUB ANY MORE (2026-09-01, king_kong_le). This returned 0 and sent
 * nothing, which is invisible right up until a title animates by patching a
 * compressed atlas in place: King Kong's intro curtain (ImageSeq_Curtains
 * Opening, two 512x512 BC3 atlases) stayed closed for the whole 30 s intro
 * while the film played behind it, and it looked exactly like a frozen video
 * - the audio ran, the clip channel handed 30 frames/s, and the picture never
 * changed. Wired through like glTexSubImage2D above; the host applies it with
 * glCompressedTexSubImage2D and journals it as an overlay on the level. */
int glCompressedTexSubImage2D(unsigned int t, int l, int x, int y, int w, int h,
                              unsigned int f, int size, const void *d)
{
    unsigned int a[7];
    (void)t;
    a[0] = (unsigned)l; a[1] = (unsigned)x; a[2] = (unsigned)y;
    a[3] = (unsigned)w; a[4] = (unsigned)h; a[5] = f;
    a[6] = (unsigned)(d && size > 0 ? size : 0);
    emit(PADGL_TEXCOMPRESSEDSUB, a, sizeof a, d, a[6]);
    return 0;
}

/* ---- buffers / vertex arrays ---- */
int glGenBuffers(int n, unsigned int *ids)
{ int i; for (i = 0; i < n; i++) { const unsigned int op_ = PADGL_GENBUF;
    ids[i] = (unsigned int)next_of(&id_buf, 4096); U(ids[i]); } return 0; }
int glDeleteBuffers(int n, const unsigned int *ids)
{ int i; for (i = 0; i < n; i++) { const unsigned int op_ = PADGL_DELBUF; U(ids[i]); } return 0; }
/* Which buffer is bound to GL_ARRAY_BUFFER, guest-side. Only glVertexAttribPointer
 * needs it, and only to tell an OFFSET from a POINTER - see below. */
static unsigned array_buffer_bound;

int glBindBuffer(unsigned int t, unsigned int id)
{ const unsigned int op_ = PADGL_BINDBUF;
  if (t == 0x8892 /* GL_ARRAY_BUFFER */) array_buffer_bound = id;
  U(t,id); return 0; }

int glBufferData(unsigned int target, long size, const void *data, unsigned int usage)
{
    unsigned int a[3];
    a[0] = target; a[1] = usage; a[2] = (unsigned)(size > 0 ? size : 0);
    emit(PADGL_BUFDATA, a, sizeof a, data, data ? a[2] : 0);
    return 0;
}

int glBufferSubData(unsigned int target, long off, long size, const void *data)
{
    unsigned int a[3];
    a[0] = target; a[1] = (unsigned)off; a[2] = (unsigned)(size > 0 ? size : 0);
    emit(PADGL_BUFSUBDATA, a, sizeof a, data, data ? a[2] : 0);
    return 0;
}

int glGenVertexArrays(int n, unsigned int *ids)
{ int i; for (i = 0; i < n; i++) { const unsigned int op_ = PADGL_GENVAO;
    ids[i] = (unsigned int)next_of(&id_vao, 1024); U(ids[i]); } return 0; }
int glDeleteVertexArrays(int n, const unsigned int *ids) { (void)n; (void)ids; return 0; }
int glBindVertexArray(unsigned int id)
{ const unsigned int op_ = PADGL_BINDVAO; U(id); return 0; }

/* CLIENT-SIDE VERTEX ARRAYS ARE NOT SUPPORTED, AND USED TO BE SILENT ABOUT IT.
 *
 * `ptr` means two different things in GLES2. With a buffer bound to
 * GL_ARRAY_BUFFER it is a byte OFFSET into that buffer, which is what the host
 * replays it as. With NO buffer bound it is a real POINTER into guest memory -
 * memory the host cannot read and would not know the length of - and replaying
 * it as an offset feeds the draw whatever happens to sit at that offset in
 * whichever buffer is bound. Arbitrary vertex attributes, arbitrary UVs.
 *
 * The whole game renders correctly, so it plainly uses buffers for everything
 * seen so far. This says so out loud the first time that stops being true,
 * because "a quad whose texture coordinates collapsed in one axis" is exactly
 * what item 6's TV inset looks like (adjacent columns differ by 0.53/255) and
 * a silent unsupported path is the worst place to go looking for it. */
int glVertexAttribPointer(unsigned int idx, int size, unsigned int type,
                          unsigned char norm, int stride, const void *ptr)
{
    const unsigned int op_ = PADGL_VERTEXATTRIB;
    if (!array_buffer_bound && ptr) {
        static int moaned;
        if (!moaned) {
            moaned = 1;
            say("[bridge] glVertexAttribPointer with NO array buffer bound - "
                "that is a CLIENT-SIDE array and this bridge cannot send it; "
                "the draw will read whatever is at that offset instead\n");
        }
    }
    U(idx, (unsigned)size, type, (unsigned)norm, (unsigned)stride, (unsigned long)ptr);
    return 0;
}
int glEnableVertexAttribArray(unsigned int i)
{ const unsigned int op_ = PADGL_ENABLEATTRIB; U(i); return 0; }
int glDisableVertexAttribArray(unsigned int i)
{ const unsigned int op_ = PADGL_DISABLEATTRIB; U(i); return 0; }

/* ---- shaders / programs ---- */
int glCreateShader(unsigned int type)
{
    const unsigned int op_ = PADGL_CREATESHADER;
    unsigned int id = (unsigned int)next_of(&id_obj, 4096);
    U(id, type);
    return (int)id;
}
int glCreateProgram(void)
{
    const unsigned int op_ = PADGL_CREATEPROGRAM;
    unsigned int id = (unsigned int)next_of(&id_obj, 4096);
    U(id);
    if (id < MAXPROG) prog_uni[id].n = 0;
    return (int)id;
}

int glShaderSource(unsigned int sh, int count, const char *const *str, const int *len)
{
    unsigned int a[2];
    int i;
    (void)len;
    if (!str) return 0;
    /* The game passes one string per shader in practice; concatenating would
     * need a scratch buffer, so send each chunk and let the host join them. */
    for (i = 0; i < count; i++) {
        unsigned int n = str[i] ? (unsigned int)strlen(str[i]) : 0;
        a[0] = sh; a[1] = n;
        emit(PADGL_SHADERSOURCE, a, sizeof a, str[i], n);
    }
    return 0;
}

int glCompileShader(unsigned int sh) { const unsigned int op_ = PADGL_COMPILESHADER; U(sh); return 0; }
int glAttachShader(unsigned int p, unsigned int s) { const unsigned int op_ = PADGL_ATTACHSHADER; U(p,s); return 0; }
int glDetachShader(unsigned int p, unsigned int s) { (void)p; (void)s; return 0; }
int glLinkProgram(unsigned int p) { const unsigned int op_ = PADGL_LINKPROGRAM; U(p); return 0; }
int glUseProgram(unsigned int p)  { const unsigned int op_ = PADGL_USEPROGRAM;  U(p); return 0; }
int glDeleteShader(unsigned int s) { (void)s; return 0; }
int glDeleteProgram(unsigned int p) { (void)p; return 0; }

int glBindAttribLocation(unsigned int p, unsigned int idx, const char *name)
{
    unsigned int a[2];
    a[0] = p; a[1] = idx;
    emit(PADGL_BINDATTRIBLOC, a, sizeof a, name, name ? (unsigned int)strlen(name) : 0);
    return 0;
}

/* Attribute locations cannot be guessed: the host's linker assigns them, and
 * guessing gave every ImGui attribute index 0, so Position, UV and Color all
 * overwrote each other. Hand back a TOKEN encoding (program, slot) and let the
 * host resolve it by name - the same trick used for uniforms, and still no
 * round trip. */
static struct { char name[40]; } prog_attr[MAXPROG][PADGL_ATTR_PER_PROG];
static int prog_attr_n[MAXPROG];

int glGetAttribLocation(unsigned int p, const char *name)
{
    int i;
    unsigned int a[2];
    if (p >= MAXPROG || !name) return -1;
    for (i = 0; i < prog_attr_n[p]; i++)
        if (!strcmp(prog_attr[p][i].name, name))
            return (int)(PADGL_ATTR_TOKEN_BASE + p * PADGL_ATTR_PER_PROG + i);
    if (prog_attr_n[p] >= PADGL_ATTR_PER_PROG) return -1;
    i = prog_attr_n[p]++;
    snprintf(prog_attr[p][i].name, 40, "%s", name);
    a[0] = p; a[1] = (unsigned)i;
    emit(PADGL_REGATTRIB, a, sizeof a, name, (unsigned int)strlen(name));
    return (int)(PADGL_ATTR_TOKEN_BASE + p * PADGL_ATTR_PER_PROG + i);
}

/* Uniform "locations" handed to the game are (program, slot) pairs allocated
 * here; the host resolves slot -> real location from the registered name. */
int glGetUniformLocation(unsigned int p, const char *name)
{
    int i;
    unsigned int a[2];
    if (p >= MAXPROG || !name) return -1;
    for (i = 0; i < prog_uni[p].n; i++)
        if (!strcmp(prog_uni[p].u[i].name, name)) return (int)(p * MAXUNI + i);
    if (prog_uni[p].n >= MAXUNI) return -1;
    i = prog_uni[p].n++;
    snprintf(prog_uni[p].u[i].name, 40, "%s", name);
    a[0] = p; a[1] = (unsigned)i;
    emit(PADGL_REGUNIFORM, a, sizeof a, name, (unsigned int)strlen(name));
    return (int)(p * MAXUNI + i);
}

static void uniform(int loc, unsigned int kind, const void *data, unsigned int bytes)
{
    unsigned int a[3];
    if (loc < 0) return;
    a[0] = (unsigned)(loc / MAXUNI); a[1] = (unsigned)(loc % MAXUNI); a[2] = kind;
    emit(PADGL_UNIFORM, a, sizeof a, data, bytes);
}

int glUniform1f(int l, float a) { uniform(l, PADGL_U1F, &a, 4); return 0; }
int glUniform1i(int l, int a)   { uniform(l, PADGL_U1I, &a, 4); return 0; }
int glUniform2f(int l, float a, float b)
{ float v[2]; v[0]=a; v[1]=b; uniform(l, PADGL_U2F, v, 8); return 0; }
int glUniform3f(int l, float a, float b, float c)
{ float v[3]; v[0]=a; v[1]=b; v[2]=c; uniform(l, PADGL_U3F, v, 12); return 0; }
int glUniform4f(int l, float a, float b, float c, float d)
{ float v[4]; v[0]=a; v[1]=b; v[2]=c; v[3]=d; uniform(l, PADGL_U4F, v, 16); return 0; }
int glUniform4fv(int l, int n, const float *v) { (void)n; uniform(l, PADGL_U4FV, v, 16); return 0; }
int glUniformMatrix4fv(int l, int n, unsigned char tr, const float *v)
{ (void)n; (void)tr; uniform(l, PADGL_UM4FV, v, 64); return 0; }

/* ---- framebuffer objects ---- */
int glGenFramebuffers(int n, unsigned int *ids)
{ int i; for (i = 0; i < n; i++) { const unsigned int op_ = PADGL_GENFBO;
    ids[i] = (unsigned int)next_of(&id_fbo, 256); U(ids[i]); } return 0; }
int glBindFramebuffer(unsigned int t, unsigned int id)
{ const unsigned int op_ = PADGL_BINDFBO; U(t,id); return 0; }
int glFramebufferTexture2D(unsigned int t, unsigned int att, unsigned int tt,
                           unsigned int tex, int level)
{ const unsigned int op_ = PADGL_FBOTEX;
  U(t,att,tt,viv_alias(tex),(unsigned)level); return 0; }   /* item 51 */
int glCheckFramebufferStatus(unsigned int t) { (void)t; return 0x8CD5; }

/* ---- draws ---- */
int glDrawArrays(unsigned int mode, int first, int count)
{ const unsigned int op_ = PADGL_DRAWARRAYS; U(mode,(unsigned)first,(unsigned)count); return 0; }

int glDrawElements(unsigned int mode, int count, unsigned int type, const void *idx)
{ const unsigned int op_ = PADGL_DRAWELEMENTS; U(mode,(unsigned)count,type,(unsigned long)idx); return 0; }

int glDrawRangeElements(unsigned int mode, unsigned int s, unsigned int e,
                        int count, unsigned int type, const void *idx)
{ (void)s; (void)e; return glDrawElements(mode, count, type, idx); }

int glDrawBuffers(int n, const unsigned int *b) { (void)n; (void)b; return 0; }

/* ---- queries, answered locally: see the header comment ---- */
int glGetError(void) { return 0; }

int glGetIntegerv(unsigned int p, int *v)
{
    if (!v) return 0;
    switch (p) {
    case 0x80CB: *v = blend_src; break;          /* GL_BLEND_SRC - per frame */
    case 0x80CA: *v = blend_dst; break;          /* GL_BLEND_DST - per frame */
    case 0x0D33: *v = 4096; break;
    case 0x8872: *v = 8;    break;
    case 0x8DFB: case 0x8DFC: *v = 256; break;
    case 0x8869: *v = 16;   break;
    default: *v = 0; break;
    }
    return 0;
}
int glGetBooleanv(unsigned int p, unsigned char *v) { (void)p; if (v) *v = 0; return 0; }
int glGetShaderiv(unsigned int s, unsigned int p, int *v) { (void)s;(void)p; if (v) *v = 1; return 0; }
int glGetProgramiv(unsigned int s, unsigned int p, int *v) { (void)s;(void)p; if (v) *v = 1; return 0; }
int glGetShaderInfoLog(unsigned int s, int m, int *l, char *b)
{ (void)s;(void)m; if (l) *l = 0; if (b) b[0] = 0; return 0; }
int glGetProgramInfoLog(unsigned int s, int m, int *l, char *b)
{ (void)s;(void)m; if (l) *l = 0; if (b) b[0] = 0; return 0; }
int glReadPixels(int x,int y,int w,int h,unsigned int f,unsigned int t,void *p)
{ (void)x;(void)y;(void)w;(void)h;(void)f;(void)t;(void)p; return 0; }

static const char *VENDOR   = "pinball-asset-decryptor";
static const char *RENDERER = "padgl bridge";
static const char *VERSION  = "OpenGL ES 3.0 padgl";
static const char *SLVER    = "OpenGL ES GLSL ES 3.00";
const char *glGetString(unsigned int n)
{
    switch (n) {
    case 0x1F00: return VENDOR;
    case 0x1F01: return RENDERER;
    case 0x1F02: return VERSION;
    case 0x8B8C: return SLVER;
    default: return "";
    }
}

/* ---------------- GL_VIV_direct_texture: THE VIDEO UPLOAD PATH ----------------
 *
 * The game never uploads a video frame with glTexImage2D. SpiVideoStreamDecoder
 * (0x5c0368) binds its own texture and calls
 *
 *     glTexDirectVIVMap(GL_TEXTURE_2D, w, h, GL_VIV_I420, &planes, &~0)
 *     glTexDirectInvalidateVIV(GL_TEXTURE_2D)
 *
 * which are Vivante extensions resolved through eglGetProcAddress. On the real
 * machine the texture unit converts YUV to RGB itself. There is nothing like it
 * on the host, so the conversion happens there and the result is a plain RGBA
 * glTexImage2D. That is why watching TEXIMAGE for a sign of video was always
 * going to read zero: this path never touches it.
 *
 * Map only records; Invalidate is what sends. That is the extension's own
 * contract - Map hands over an address, Invalidate says its contents changed -
 * and it matters here because the game calls Map every frame with a new ring
 * slot, so sending on Map would upload a frame the game has not finished with.
 *
 * ★ ITEM 43: ONE REGISTRATION PER TEXTURE, NOT ONE PER PROCESS. This used to
 * be a single global struct, which is wrong for an extension that names its
 * texture by what is bound - see the comment above glBindTexture for how that
 * one global painted video into the service menu's DMD quad for a week. Eight
 * slots is generous: this binary has four direct-texture users in total (the
 * video, the DMD scene, the presenter, and Texture::Texture's allocate path).
 */
#define VIVMAX 8
struct viv_reg {
    unsigned used, name, w, h, fmt;
    unsigned alias_of;            /* item 51: this name Maps another texture's
                                   * OWN buffer - one memory, two names       */
    const unsigned char *px;      /* what Invalidate must send                */
    unsigned char *own;           /* this texture's OWN buffer, allocate path */
    unsigned long ownsz;
};
static struct viv_reg viv_tab[VIVMAX];

/* item 51: the emitted-name translation. star_wars builds its playfield-LCD
 * scene the Vivante zero-copy way: glTexDirectVIV allocates a buffer under
 * one texture name (the FBO render target), then glTexDirectVIVMap adopts
 * THE SAME pointer under a second name (the composite's sampler). On real
 * hardware both wrap one physical buffer; on the host they were two
 * unrelated textures, so the composite sampled memory nothing ever wrote
 * and the LCD scene composed black - through every present path, since
 * forever (item 27's "32.8% black frames" flicker was bright-vs-BLACK).
 * Detection is exact: a Map whose address equals another registration's own
 * buffer. Ring-slot video addresses can never trip this - they are compared
 * against `own` allocations only. */
static unsigned viv_alias(unsigned name)
{
    int i;
    if (!name) return name;
    for (i = 0; i < VIVMAX; i++)
        if (viv_tab[i].used && viv_tab[i].name == name
            && viv_tab[i].alias_of)
            return viv_tab[i].alias_of;
    return name;
}

/* The slot for the currently bound GL_TEXTURE_2D, claiming a free one if this
 * texture has not registered before. Null only if all eight are taken, which
 * this binary cannot do. */
static struct viv_reg *viv_slot(void)
{
    unsigned name = cur_tex2d[cur_unit & 15u];
    int i, free_i = -1;
    for (i = 0; i < VIVMAX; i++) {
        if (viv_tab[i].used) {
            if (viv_tab[i].name == name) return &viv_tab[i];
        } else if (free_i < 0) {
            free_i = i;
        }
    }
    if (free_i < 0) return 0;
    viv_tab[free_i].used = 1;
    viv_tab[free_i].name = name;
    return &viv_tab[free_i];
}

/* Lookup only - Invalidate must never invent a registration. */
static struct viv_reg *viv_find(void)
{
    unsigned name = cur_tex2d[cur_unit & 15u];
    int i;
    for (i = 0; i < VIVMAX; i++)
        if (viv_tab[i].used && viv_tab[i].name == name) return &viv_tab[i];
    return 0;
}

/* Say each texture's registration ONCE, with its name, so a run can be judged
 * from the log without a screenshot: the menu's DMD texture must appear with
 * its own size and format (1024x256 GL_RGBA = 0x1908) and not the video's
 * 1360x768 0x8fc5. Before the per-texture registry there was only ever one
 * line, and it was always the video's. */
static void viv_said(const struct viv_reg *r, const char *how)
{
    static unsigned said[VIVMAX];
    static const char hx[] = "0123456789abcdef";
    char m[96];
    int i = 0, k;
    const char *p;
    unsigned slot = (unsigned)(r - viv_tab);
    if (slot >= VIVMAX || said[slot] == r->fmt + r->w) return;
    said[slot] = r->fmt + r->w;
    p = "[bridge] item43: texture ";
    while (*p) m[i++] = *p++;
    for (k = 3; k >= 0; k--) m[i++] = hx[(r->name >> (k * 4)) & 0xf];
    m[i++] = ' ';
    for (k = 3; k >= 0; k--) m[i++] = hx[(r->w >> (k * 4)) & 0xf];
    m[i++] = 'x';
    for (k = 3; k >= 0; k--) m[i++] = hx[(r->h >> (k * 4)) & 0xf];
    p = " fmt 0x";
    while (*p) m[i++] = *p++;
    for (k = 3; k >= 0; k--) m[i++] = hx[(r->fmt >> (k * 4)) & 0xf];
    m[i++] = ' ';
    while (*how) m[i++] = *how++;
    m[i++] = '\n';
    m[i] = 0;
    say(m);
}

/* gstvid.c, inside the LD_PRELOADed hwshim.so. Weak so libGLESv2 still loads
 * without it, in which case every frame takes the copying path. */
extern long pad_vid_ring_offset(const void *) __attribute__((weak));

static unsigned viv_frame_bytes(unsigned fmt, unsigned w, unsigned h)
{
    switch (fmt) {
    case PADGL_VIV_I420: case PADGL_VIV_YV12:
    case PADGL_VIV_NV12: case PADGL_VIV_NV21: return w * h * 3u / 2u;
    case PADGL_VIV_YUY2: case PADGL_VIV_UYVY: return w * h * 2u;
    /* NOT ONLY VIDEO. The Vivante direct-texture path takes plain colour
     * formats too, and Jaws LE uses it for GL_RGBA - which is how "unsupported
     * format" became a null buffer and a crash. GL_RGBA and GL_RGB are core GL
     * enums, not Vivante ones, hence the bare numbers. */
    case 0x1908u: return w * h * 4u;                 /* GL_RGBA */
    case 0x1907u: return w * h * 3u;                 /* GL_RGB  */
    default: return 0;
    }
}

void glTexDirectVIVMap(unsigned int target, int w, int h, unsigned int fmt,
                       void **logical, const unsigned int *physical)
{
    struct viv_reg *r = viv_slot();
    (void)target; (void)physical;
    if (!r) return;
    r->w = (unsigned)w; r->h = (unsigned)h; r->fmt = fmt;
    r->px = logical ? (const unsigned char *)*logical : 0;
    /* item 51: does this Map adopt a buffer glTexDirectVIV handed out under
     * another name? Then the two names are one memory - record the alias so
     * every emitted bind and attach lands on the canonical texture. */
    r->alias_of = 0;
    if (r->px) {
        int i;
        for (i = 0; i < VIVMAX; i++)
            if (viv_tab[i].used && &viv_tab[i] != r
                && viv_tab[i].own && viv_tab[i].own == (unsigned char *)r->px) {
                r->alias_of = viv_tab[i].name;
                say("[bridge] item51: Map adopts an allocated buffer - "
                    "texture aliased to its render target\n");
                break;
            }
    }
    viv_said(r, "map");
    /* Vivante's Map hands the CALLER an address to write into. This caller
     * already has its frame at the address it passed in, so *logical is left
     * exactly as it came - overwriting it would point the game at nothing. */
}

/* glTexDirectVIV ALLOCATES; glTexDirectVIVMap ADOPTS. Forwarding one to the
 * other looks harmless and is not, because the difference is which direction
 * `logical` goes:
 *
 *   Map(...,  void **logical, ...)   the app OWNS the buffer and passes it IN
 *   VIV(...,  void **logical)        the DRIVER allocates and writes it OUT
 *
 * This used to call Map, which reads *logical and never writes it. An app that
 * calls glTexDirectVIV gets back whatever was already in its pointer variable -
 * a null - and then copies a frame into it. That is precisely how Jaws LE died:
 * memmove with a null destination, from a virtual "ensure capacity" at
 * vtable+8 that returned without setting the buffer at this+32. The pointer it
 * was waiting for was this function's to provide.
 *
 * One buffer, grown as needed and reused: the extension's contract is that the
 * texture keeps the allocation until the target is respecified, and a video
 * frame arrives 30 times a second. */
void glTexDirectVIV(unsigned int target, int w, int h, unsigned int fmt,
                    void **logical)
{
    /* ★ ITEM 43, THE CO-DEFECT, and it is the same mistake as the registration:
     * this buffer used to be ONE `static` for the whole process. There is
     * exactly one call site for this function in the entire game binary -
     * 0x4da060, inside Texture::Texture - so that single buffer was serving
     * EVERY allocating texture the game builds, including the DMD's 1024x256
     * RGBA (1 MiB) and the presenter's 1360x768 RGBA (4 MiB). Whichever was
     * constructed second resized the buffer under the first, and both then
     * memmoved their pixels into the same bytes. The extension's contract is
     * that a texture keeps ITS allocation until the target is respecified, so
     * the allocation belongs in the texture's slot. */
    struct viv_reg *r = viv_slot();
    unsigned need = viv_frame_bytes(fmt, (unsigned)w, (unsigned)h);

    (void)target;
    if (logical) *logical = 0;
    if (!r) return;
    if (!need) {
        /* SAY WHICH FORMAT. "unsupported" on its own cost a whole run: Jaws
         * does call this, so the entry point was right and the only thing left
         * to learn was the four hex digits this did not print. */
        static int moaned;
        if (!moaned) {
            static const char hx[] = "0123456789abcdef";
            char m[64];
            int i = 0, k;
            const char *p = "[bridge] glTexDirectVIV: unsupported format 0x";
            moaned = 1;
            while (*p) m[i++] = *p++;
            for (k = 7; k >= 0; k--) m[i++] = hx[(fmt >> (k * 4)) & 0xf];
            p = ", no buffer given\n";
            while (*p) m[i++] = *p++;
            m[i] = 0;
            say(m);
        }
        return;
    }
    if (need > r->ownsz) {
        /* mmap rather than malloc: this file is the guest's libGLESv2 and does
         * not link an allocator of its own. Anonymous, private, and never
         * freed - there is one of these per texture size for the life of the
         * process, and a leak of one frame buffer is not a leak worth code. */
        void *p = mmap(0, need, 3 /*RW*/, 0x22 /*ANON|PRIVATE*/, -1, 0);
        if (!p || p == (void *)-1) {
            say("[bridge] glTexDirectVIV: could not allocate a frame buffer\n");
            return;
        }
        r->own = (unsigned char *)p;
        r->ownsz = need;
    }
    if (logical) *logical = r->own;
    r->w = (unsigned)w; r->h = (unsigned)h; r->fmt = fmt; r->px = r->own;
    viv_said(r, "alloc");
}

void glTexDirectInvalidateVIV(unsigned int target)
{
    /* ★ ITEM 43: send THIS texture's registration, or nothing. There is
     * deliberately no fallback to "whatever registered last" - that fallback,
     * in the shape of a single process-global, IS the bug this function spent a
     * week causing, and a silent one would put it straight back. A miss says so
     * once and sends nothing, which is this file's standing rule: anything not
     * implemented fails loudly. */
    struct viv_reg *r = viv_find();
    unsigned int a[6];
    unsigned int bytes;
    long off = -1;
    (void)target;
    if (!r) {
        static int moaned;
        if (!moaned) {
            moaned = 1;
            say("[bridge] glTexDirectInvalidateVIV on a texture that never "
                "registered - sending nothing (item 43)\n");
        }
        return;
    }
    if (!r->px || !r->w || !r->h) return;
    bytes = viv_frame_bytes(r->fmt, r->w, r->h);
    if (!bytes) {
        static int moaned;
        if (!moaned) { moaned = 1; say("[bridge] unsupported glTexDirectVIV format\n"); }
        return;
    }
    if (pad_vid_ring_offset) off = pad_vid_ring_offset(r->px);
    a[0] = r->w; a[1] = r->h; a[2] = r->fmt;
    if (off >= 0) {
        /* The pixels are already in a block the host has open. Send six words. */
        a[3] = PADGL_SRC_VIDSHM; a[4] = (unsigned)off; a[5] = bytes;
        emit(PADGL_TEXDIRECT, a, sizeof a, 0, 0);
    } else {
        a[3] = PADGL_SRC_INLINE; a[4] = 0; a[5] = bytes;
        emit(PADGL_TEXDIRECT, a, sizeof a, r->px, bytes);
    }
}

/* Name lookup for libEGL's eglGetProcAddress. The GL state lives in this
 * library, so the resolution has to happen here too. */
void *pad_gl_proc(const char *name)
{
    if (!name) return 0;
    if (!strcmp(name, "glTexDirectVIVMap"))        return (void *)glTexDirectVIVMap;
    if (!strcmp(name, "glTexDirectVIV"))           return (void *)glTexDirectVIV;
    if (!strcmp(name, "glTexDirectInvalidateVIV")) return (void *)glTexDirectInvalidateVIV;
    return 0;
}

int glLineWidth(float w) { (void)w; return 0; }
int glFenceSync(unsigned int a, unsigned int b) { (void)a; (void)b; return 1; }
int glClientWaitSync(int s, unsigned int f, unsigned long long t)
{ (void)s;(void)f;(void)t; return 0x911A; }   /* ALREADY_SIGNALED */
int glDeleteSync(int s) { (void)s; return 0; }
