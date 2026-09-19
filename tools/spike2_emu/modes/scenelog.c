/* scenelog.c - ITEM 131 INSTRUMENT: every byte a scene.radium load reads, in order.
 *
 * WHY. Adding a copied child node to Godzilla's attract scene (394c4a03) throws
 * `vector::_M_default_append` at display time, while growing a string in the same
 * file loads fine. Guessing at the cause from outside cost four boots. This records
 * the read sequence itself, so the first read whose bytes stop matching the file map
 * names the structure the game expected there.
 *
 * WHAT IT HOOKS (godzilla Pro 1.15; addresses in gen_sites.py):
 *   cereal PortableBinaryInputArchive::loadBinary<1|2|4|8>(this, data, bytes)
 *     every raw read goes through one of these four; `this` identifies the archive
 *   the size-tag reader 0x27f4e0(wrapper, &u64*)   which caller asked for a size
 *   the child-vector resize 0x28e4a0(vec, n)       the node child count (16-B elements)
 *   the tick                                       polls /dump/scenelog.dump
 *   scene get 0x3bac44(&id, kind, 0), find node 0x578a2c(&out, parent, &"A.B.C"),
 *   set text 0x55c1f4(node, &text)                 logged once per (caller, string)
 *
 * A read's bytes are not there yet when its hook runs, so each archive's previous
 * read is captured (first 8 bytes, reads up to 64 KB only) when its next read starts,
 * and every pending one when the ring is dumped.
 *
 * DUMPS go to /dump/scenelog.<n>.bin (at most 8): the whole ring, 32-byte entries,
 * when the child resize is asked for an absurd count (the throw is next), when
 * /dump/scenelog.dump appears (a control run), or when the game first fetches a scene
 * whose id starts with the prefix in /dump/scenelog.want (read at load: boot-loaded
 * scenes). modes/scenelog_read.py decodes them.
 *
 * WHAT IT CHANGES. Nothing in the game. Build: modes/build_modes.sh.
 */
#include "hook.h"

#define RING (1u << 20)                 /* 32 MB of .bss */
#define PEND 32
#define K_SIZETAG 0x10u
#define K_RESIZE  0x20u
#define K_FILLED  0x100u

struct ent {
    unsigned arch;       /* the archive (size tags: resolved the way 0x27f4e0 does) */
    unsigned size;       /* bytes read; resize: the count asked for */
    unsigned lr;         /* the caller */
    unsigned dst;        /* where the bytes go; resize: the vector */
    unsigned kind;       /* 1/2/4/8 loadBinary width, K_SIZETAG, K_RESIZE; | K_FILLED */
    unsigned seq;        /* global order, 1-based; 0 = empty slot */
    unsigned char val[8];
};

static struct ent ring[RING];
static unsigned head, seq;
static int dumps, ticks;
static struct { unsigned arch, slot, seq; } pend[PEND];
static unsigned pend_next;

static void fill(unsigned slot, unsigned sq)
{
    struct ent *e = &ring[slot];
    unsigned i, n;
    if (e->seq != sq || (e->kind & K_FILLED)) return;   /* overwritten, or done */
    if (e->dst && e->size && e->size <= 65536u) {
        n = e->size < 8u ? e->size : 8u;
        for (i = 0; i < n; i++) e->val[i] = ((unsigned char *)(unsigned long)e->dst)[i];
    }
    e->kind |= K_FILLED;
}

static unsigned put(unsigned arch, unsigned size, unsigned lr, unsigned dst, unsigned kind)
{
    unsigned s = __sync_fetch_and_add(&head, 1u) & (RING - 1u);
    struct ent *e = &ring[s];
    e->seq = 0;                                          /* a racing fill() sees a stale seq */
    e->arch = arch; e->size = size; e->lr = lr; e->dst = dst; e->kind = kind;
    e->val[0] = e->val[1] = e->val[2] = e->val[3] = 0;
    e->val[4] = e->val[5] = e->val[6] = e->val[7] = 0;
    e->seq = __sync_add_and_fetch(&seq, 1u);
    return s;
}

static void dump(const char *why, unsigned a, unsigned b)
{
    char path[48], m[200];
    struct { char magic[4]; unsigned version, ring, head, seq, a, b; char why[16]; } hdr;
    unsigned i;
    unsigned long off = 0, total = sizeof ring;
    int fd;
    if (dumps >= 8) return;
    for (i = 0; i < PEND; i++)
        if (pend[i].arch) fill(pend[i].slot, pend[i].seq);
    snprintf(path, sizeof path, "/dump/scenelog.%d.bin", dumps++);
    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        snprintf(m, sizeof m, "[scenelog] cannot open %s (%s)\n", path, why);
        hk_logs(m);
        return;
    }
    for (i = 0; i < sizeof hdr; i++) ((char *)&hdr)[i] = 0;
    hdr.magic[0] = 'S'; hdr.magic[1] = 'C'; hdr.magic[2] = 'N'; hdr.magic[3] = 'L';
    hdr.version = 1; hdr.ring = RING; hdr.head = head; hdr.seq = seq; hdr.a = a; hdr.b = b;
    for (i = 0; why[i] && i < 15; i++) hdr.why[i] = why[i];
    write(fd, &hdr, sizeof hdr);
    while (off < total) {
        long w = write(fd, (char *)ring + off, total - off > (1ul << 20) ? (1ul << 20) : total - off);
        if (w <= 0) break;
        off += (unsigned long)w;
    }
    close(fd);
    snprintf(m, sizeof m, "[scenelog] dump %s: %s a=0x%x b=0x%x seq=%u (%lu of %lu bytes)\n",
             path, why, a, b, seq, off, total);
    hk_logs(m);
}

static void read_n(unsigned *r, unsigned width)
{
    unsigned a = r[0], i, s;
    for (i = 0; i < PEND; i++)
        if (pend[i].arch == a) break;
    if (i < PEND) fill(pend[i].slot, pend[i].seq);
    else i = pend_next++ % PEND;
    s = put(a, r[2], r[5], r[1], width);
    pend[i].slot = s;
    pend[i].seq = ring[s].seq;
    pend[i].arch = a;
}

static void on_lb1(unsigned *r) { read_n(r, 1u); }
static void on_lb2(unsigned *r) { read_n(r, 2u); }
static void on_lb4(unsigned *r) { read_n(r, 4u); }
static void on_lb8(unsigned *r) { read_n(r, 8u); }

static void on_sizetag(unsigned *r)
{
    unsigned **w = (unsigned **)(unsigned long)r[0];
    unsigned a = w[1][1];                                /* ldr [r0,#4] x4, as 0x27f4e0 does */
    a = ((unsigned *)(unsigned long)a)[1];
    a = ((unsigned *)(unsigned long)a)[1];
    put(a, 8u, r[5], *(unsigned *)(unsigned long)r[1], K_SIZETAG | K_FILLED);
}

static void on_resize(unsigned *r)
{
    put(0u, r[1], r[5], r[0], K_RESIZE | K_FILLED);
    if (r[1] > 0x100000u) dump("absurd-resize", r[1], r[5]);
}

/* ---- names: which scenes, node paths and texts the display code asks for ----------
 * Strings here are libstdc++ COW std::string, a single pointer to the characters.
 * Each (caller, text) pair is logged once, so an update loop costs one line. */
#define SEEN 8192u
static unsigned seen[SEEN];

static void name_log(const char *what, unsigned lr, unsigned obj, unsigned **sp)
{
    const char *s = sp && *sp ? (const char *)*sp : "";
    unsigned h = 2166136261u ^ lr, i, n;
    char m[200];
    for (i = 0; s[i] && i < 96; i++) h = (h ^ (unsigned char)s[i]) * 16777619u;
    if (!h) h = 1;
    for (n = 0, i = h & (SEEN - 1); n < 32; n++, i = (i + 1) & (SEEN - 1)) {
        if (seen[i] == h) return;
        if (!seen[i]) { seen[i] = h; break; }
    }
    snprintf(m, sizeof m, "[scenelog] %s lr=0x%06x obj=0x%08x \"%.96s\"\n", what, lr, obj, s);
    hk_logs(m);
}

/* /dump/scenelog.want, read once at load: a scene id prefix. The first time the game
 * fetches a scene whose id starts with it, the ring is dumped - boot-loaded scenes are
 * read long before anything else could be timed from outside. */
static char want[48];

static void on_scene_get(unsigned *r)
{
    unsigned **sp = (unsigned **)(unsigned long)r[0];
    const char *s = sp && *sp ? (const char *)*sp : "";
    unsigned i;
    name_log("scene", r[5], r[1], sp);
    if (!want[0]) return;
    for (i = 0; want[i] && s[i] == want[i]; i++) ;
    if (!want[i]) {
        want[0] = 0;                                     /* once */
        dump("scene-get", r[1], r[5]);
    }
}
static void on_find_node(unsigned *r) { name_log("node", r[5], r[1], (unsigned **)(unsigned long)r[2]); }
static void on_set_text(unsigned *r)  { name_log("text", r[5], r[0], (unsigned **)(unsigned long)r[1]); }

static void on_tick(unsigned *r)
{
    unsigned long long v[4];
    (void)r;
    if (++ticks % 30) return;
    if (hk_read_trigger("/dump/scenelog.dump", v) >= 0) dump("trigger", (unsigned)v[0], 0u);
}

__attribute__((constructor))
static void scenelog_init(void)
{
    struct { unsigned fn, w0, w1; hk_logger lg; const char *tag; } s[] = {
        { SITE_LB1, SITE_LB1_W0, SITE_LB1_W1, on_lb1, "loadBinary<1>" },
        { SITE_LB2, SITE_LB2_W0, SITE_LB2_W1, on_lb2, "loadBinary<2>" },
        { SITE_LB4, SITE_LB4_W0, SITE_LB4_W1, on_lb4, "loadBinary<4>" },
        { SITE_LB8, SITE_LB8_W0, SITE_LB8_W1, on_lb8, "loadBinary<8>" },
        { SITE_SIZETAG, SITE_SIZETAG_W0, SITE_SIZETAG_W1, on_sizetag, "size tag" },
        { SITE_CHILD_RESIZE, SITE_CHILD_RESIZE_W0, SITE_CHILD_RESIZE_W1, on_resize, "child resize" },
        { SITE_TICK, SITE_TICK_W0, SITE_TICK_W1, on_tick, "tick" },
        { SITE_SCENE_GET, SITE_SCENE_GET_W0, SITE_SCENE_GET_W1, on_scene_get, "scene get" },
        { SITE_FIND_NODE, SITE_FIND_NODE_W0, SITE_FIND_NODE_W1, on_find_node, "find node" },
        { SITE_SET_TEXT, SITE_SET_TEXT_W0, SITE_SET_TEXT_W1, on_set_text, "set text" },
    };
    unsigned i, ok = 1;
    char m[120];
    if (!hk_is_game_process(SITE_LB8)) return;
    hk_log_open("/dump/scenelog.log");
    {
        int fd = open("/dump/scenelog.want", O_RDONLY);
        if (fd >= 0) {
            long n = read(fd, want, sizeof want - 1);
            close(fd);
            want[n > 0 ? n : 0] = 0;
            for (n = 0; want[n]; n++) if (want[n] == '\n' || want[n] == ' ') { want[n] = 0; break; }
            snprintf(m, sizeof m, "[scenelog] will dump when scene \"%s...\" is fetched\n", want);
            hk_logs(m);
        }
    }
    hk_logs("[scenelog] loaded - item 131 scene read recorder, godzilla Pro 1.15\n");
    for (i = 0; i < sizeof s / sizeof s[0]; i++)
        ok &= hk_site_ok(s[i].fn, s[i].w0, s[i].w1, s[i].tag);
    if (!ok) {
        hk_logs("[scenelog] a site did not match - nothing hooked\n");
        return;
    }
    for (i = 0; i < sizeof s / sizeof s[0]; i++)
        hk_install(s[i].fn, s[i].lg);
    snprintf(m, sizeof m, "[scenelog] %d hooks installed; ring %u entries\n", hk_used, RING);
    hk_logs(m);
}
