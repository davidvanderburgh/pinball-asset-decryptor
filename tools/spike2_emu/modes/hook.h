/* hook.h - what padmode.c (the probe) and mode.c (our mode) share. Item 125.
 *
 * Everything here is static: each .so gets its own copy, its own trampoline page
 * and its own log. Built -nostdlib against the card rootfs's libc, so libc is
 * declared by hand (no headers from the cross toolchain's newer glibc).
 *
 * THREE RULES, each learned or checked in the emulator (MODE_API.md):
 *   1. hk_is_game_process() before touching ANY game address. A PAD_PIVOT run
 *      exports LD_PRELOAD into the game's system() children, and the first probe
 *      SEGV'd a child /bin/sh reading the tick site (run 1).
 *   2. hk_site_ok() before hooking or calling a site: the two instruction words
 *      gen_sites.py read from the ELF this was built for. It FOLLOWS a sibling
 *      .so's trampoline, so padmode.so and mode.so can hook the same function
 *      when both are preloaded: the second one relocates `ldr pc,[pc,#-4]; .word t`
 *      verbatim, which still lands in the first one's trampoline.
 *   3. Act on the game's own threads. Hooks run on whatever thread called the
 *      site; the tick (0x4ec828) is the scheduler thread, which is where a mode
 *      belongs.
 */
#ifndef PADMODE_HOOK_H
#define PADMODE_HOOK_H

#include "padmode_sites.h"

extern int   open(const char *, int, ...);
extern long  read(int, void *, unsigned long);
extern long  write(int, const void *, unsigned long);
extern int   close(int);
extern int   unlink(const char *);
extern int   snprintf(char *, unsigned long, const char *, ...);
extern int   clock_gettime(int, void *);
extern int   mprotect(void *, unsigned long, int);

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  0100
#define O_TRUNC  01000
#define O_APPEND 02000
#define CLOCK_MONOTONIC 1

/* godzilla Pro 1.15 data (MODE_API.md) */
#define GZ_MGR         0x79d954u   /* cmode_manager */
#define GZ_MGR_GUARD   0x79dbd8u   /* bit 0 = constructed */
#define GZ_CUR_PLAYER  0x708170u   /* byte, 1..4 */
#define GZ_SCORES      0x7e4968u   /* u64 x4 */
#define GZ_MODE_TABLE  0x7a1698u   /* 27 mode pointers */
#define GZ_MODE_MASK   0x7aba5au   /* u16; score_add refuses while & 0x210 */
#define GZ_MSG_COUNT   0x5ec0c8u   /* u32 */
#define GZ_MSG_REMAP   0x7b9654u   /* u16 * : id -> index */
#define GZ_MSG_PTRS    0x744c60u   /* index -> {en, de, fr, es, it, 0} */

typedef void (*hk_logger)(unsigned *regs);   /* r0..r3, ip, lr, then stack args */

#define HK_UNUSED __attribute__((unused))

/* ---- log ------------------------------------------------------------------ */
static int hk_log_fd = -1, hk_log_lines;
static struct { long s, ns; } hk_t0;

HK_UNUSED static unsigned long hk_ms(void)
{
    struct { long s, ns; } t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (unsigned long)((t.s - hk_t0.s) * 1000L + (t.ns - hk_t0.ns) / 1000000L);
}

HK_UNUSED static void hk_log_open(const char *path)
{
    clock_gettime(CLOCK_MONOTONIC, &hk_t0);
    hk_log_fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0644);
}

HK_UNUSED static void hk_logs(const char *m)
{
    char b[320];
    int n;
    if (hk_log_fd < 0 || hk_log_lines > 40000) return;
    hk_log_lines++;
    n = snprintf(b, sizeof b, "%8lu %s", hk_ms(), m);
    if (n > 0) write(hk_log_fd, b, n < (int)sizeof b ? (unsigned long)n : sizeof b - 1);
}

/* ---- rule 1: is this the game? --------------------------------------------- */
static int hk_hex(int c)
{
    return (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10 : -1;
}

HK_UNUSED static int hk_is_game_process(unsigned site)
{
    static char buf[65536];
    long n, tot = 0;
    char *s = buf, *e;
    int fd = open("/proc/self/maps", O_RDONLY);
    if (fd < 0) return 0;
    while (tot < (long)sizeof buf - 1 && (n = read(fd, buf + tot, sizeof buf - 1 - tot)) > 0)
        tot += n;
    close(fd);
    buf[tot] = 0;
    while (*s) {
        unsigned long lo = 0, hi = 0;
        char *q = s;
        int d;
        for (e = s; *e && *e != '\n'; e++) ;
        for (; (d = hk_hex(*q)) >= 0; q++) lo = lo * 16 + d;
        if (*q == '-') {
            q++;
            for (; (d = hk_hex(*q)) >= 0; q++) hi = hi * 16 + d;
            if (lo <= site && site + 8 <= hi && q[0] == ' ' && q[1] == 'r' && q[3] == 'x') {
                char *p;
                for (p = q; p + 4 <= e; p++)
                    if (p[0] == 'g' && p[1] == 'a' && p[2] == 'm' && p[3] == 'e') return 1;
                return 0;
            }
        }
        s = *e ? e + 1 : e;
    }
    return 0;
}

/* ---- rule 2: the words, through any sibling's trampoline ------------------- */
HK_UNUSED static int hk_site_ok(unsigned fn, unsigned w0, unsigned w1, const char *tag)
{
    const unsigned *p = (const unsigned *)(unsigned long)fn;
    char m[180];
    int depth;
    for (depth = 0; depth < 4; depth++) {
        if (p[0] == w0 && p[1] == w1) return 1;
        if (p[0] != 0xe51ff004u) break;                  /* not a hook jump */
        p = (const unsigned *)(unsigned long)p[1];
        if (p[0] != 0xe92d500fu) break;                  /* not our trampoline shape */
        p += 6;                                          /* what it relocated */
    }
    snprintf(m, sizeof m, "[hook] %s 0x%08x: expected %08x %08x - wrong title or build\n",
             tag, fn, w0, w1);
    hk_logs(m);
    return 0;
}

/* ---- the trampoline: hwshim.c's pad_hook, handing the logger the saved regs -- */
static unsigned hk_page[1024] __attribute__((aligned(4096)));
static int hk_used;

HK_UNUSED static int hk_install(unsigned fn, hk_logger logger)
{
    unsigned *p = (unsigned *)(unsigned long)fn, *t;
    if ((hk_used + 1) * 16 > 1024) return 0;
    t = hk_page + hk_used++ * 16;
    t[0] = 0xe92d500fu;   /* push {r0,r1,r2,r3,ip,lr} */
    t[1] = 0xe1a0000du;   /* mov r0, sp */
    t[2] = 0xe1a00000u;   /* nop */
    t[3] = 0xe59fc014u;   /* ldr ip, [pc, #20] -> t[10] */
    t[4] = 0xe12fff3cu;   /* blx ip */
    t[5] = 0xe8bd500fu;   /* pop {r0,r1,r2,r3,ip,lr} */
    t[6] = p[0];          /* original words - or a sibling's jump + literal, */
    t[7] = p[1];          /* which is position-independent as a pair */
    t[8] = 0xe59ff004u;   /* ldr pc, [pc, #4] -> t[11] */
    t[9] = 0u;
    t[10] = (unsigned)(unsigned long)logger;
    t[11] = fn + 8u;
    mprotect(hk_page, sizeof hk_page, 7);
    mprotect((void *)(unsigned long)(fn & ~0xfffu), 0x2000, 7);
    p[1] = (unsigned)(unsigned long)t;
    p[0] = 0xe51ff004u;   /* ldr pc, [pc, #-4] */
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    __builtin___clear_cache((char *)p, (char *)(p + 2));
    return 1;
}

/* ---- trigger files -------------------------------------------------------------- */
/* Reads, deletes, and parses up to four numbers (decimal or 0x hex). -1 = no file. */
HK_UNUSED static int hk_read_trigger(const char *path, unsigned long long v[4])
{
    char buf[96], *s;
    long n;
    int fd = open(path, O_RDONLY), k = 0;
    if (fd < 0) return -1;
    n = read(fd, buf, sizeof buf - 1);
    close(fd);
    unlink(path);
    buf[n > 0 ? n : 0] = 0;
    v[0] = v[1] = v[2] = v[3] = 0;
    for (s = buf; *s && k < 4; ) {
        int base = 10, got = 0;
        unsigned long long x = 0;
        while (*s == ' ' || *s == '\n') s++;
        if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { base = 16; s += 2; }
        for (;; s++) {
            int d = hk_hex(*s | 0x20);
            if (*s >= 'A' && *s <= 'F') d = *s - 'A' + 10;
            if (d < 0 || (base == 10 && d > 9)) break;
            x = x * base + d;
            got = 1;
        }
        if (!got) break;
        v[k++] = x;
    }
    return k;
}

/* ---- game reads --------------------------------------------------------------- */
HK_UNUSED static unsigned gz_player(void)
{
    return *(unsigned char *)(unsigned long)GZ_CUR_PLAYER;
}

HK_UNUSED static int gz_in_game(void)
{
    unsigned p = gz_player();
    return (*(unsigned short *)(unsigned long)GZ_MODE_MASK & 0x210) == 0 && p >= 1 && p <= 4;
}

/* English text of a message id, resolved the way 0x34a764 does; 0 if not ready */
HK_UNUSED static const char *gz_msg_en(unsigned id)
{
    unsigned count = *(unsigned *)(unsigned long)GZ_MSG_COUNT, idx;
    unsigned short *remap = *(unsigned short **)(unsigned long)GZ_MSG_REMAP;
    const char **grp;
    if (id >= count || !remap) return 0;
    idx = remap[id];
    if (idx >= count) return 0;
    grp = *(const char ***)(unsigned long)(GZ_MSG_PTRS + 4u * idx);
    return grp ? grp[0] : 0;
}

/* ---- lights: the game's own light runner (emulator-proven, run 12) -------------
 * Everything the light system makes is tagged with the CURRENT event, and from a tick
 * hook that is null - which is the one thing that separated our call from the game's.
 * With a live show event made current, tesla's own command wrote lamps 413-420 (the
 * powerline tower) 0.2 s later, the same eight the game's own award writes.
 * A group comes from a pool of 48 (0x3c1700), so ONE is kept and reused rather than
 * taken per call; nothing here has to free it. MODE_API.md has the recipe. */
#define GZ_EV_HEAD     0x7b7e80u   /* event list head; chain runs through +0x84 */
#define GZ_EV_CUR      0x7b7e84u   /* the event running now */
#define GZ_LAMP_COUNT  0x7b10b4u   /* slots per group array, 585 on Pro 1.15 */

HK_UNUSED static unsigned char *gz_live_show_event(void)
{
    unsigned char *n = *(unsigned char **)(unsigned long)GZ_EV_HEAD;
    int guard = 64;
    while (n && guard-- > 0) {
        if ((*(unsigned short *)(n + 2) & 0x20u) && *(unsigned short *)(n + 0x96)) return n;
        n = *(unsigned char **)(n + 0x84);
    }
    return 0;
}

/* Runs one blele command the way the game's own shows do. Returns the group, or 0. */
HK_UNUSED static void *gz_blele(unsigned owner, const char *cmd)
{
    static void *group;
    unsigned char *ev = gz_live_show_event(), *old = 0;
    unsigned prio = 0;
    if (ev) {
        old = *(unsigned char **)(unsigned long)GZ_EV_CUR;
        *(unsigned char **)(unsigned long)GZ_EV_CUR = ev;
        prio = ((unsigned (*)(void))(unsigned long)SITE_SHOW_PRIO)();
    }
    if (!group)
        group = ((void *(*)(unsigned, unsigned, unsigned, unsigned))
                 (unsigned long)SITE_LAMP_GROUP)(0u, prio & 0xffu, 0u, 0u);
    if (group)
        ((int (*)(unsigned, void *, const char *, unsigned))
         (unsigned long)SITE_BLELE_RUN)(owner, group, cmd, 0u);
    if (ev) *(unsigned char **)(unsigned long)GZ_EV_CUR = old;
    return group;
}

/* ---- scenes: a node of our own, found, shown, hidden and written by name (item 131) ---
 * Emulator-proven in godzilla Pro 1.15, in attract AND in a game (TODO item 131):
 *   a scene by id: resource manager [0x7db220] -> 0x443de4(mgr, &std::string id, 0) ->
 *     __dynamic_cast(0x6209c4 -> 0x673b94) -> the scene at +0x10. (0x3bac44 does this
 *     too, but logs error 0x101 when no event is current, which is every tick.)
 *   no id: the attract player singleton 0x79ac34, scene at +0x10.
 *   a node: find_node 0x578a2c(&shared_ptr, scene, &std::string "A.B.C"). It is TYPED -
 *     the generic 0x577a4c then a __dynamic_cast - so it finds our Sprite and returns
 *     null for our Text (measured). A Text is found with 0x5784c8, the finder the HUD
 *     uses for the node it hands set-text.
 *   shown:  vfn[0xa8](node, bool), the call 0x20758 makes on the SternLogo. DRAWN =
 *     keyframes AND this flag: code can hide a node but never reveal one its timeline
 *     hides, so a mode's screen is authored visible and hidden by the mode.
 *   words:  0x55c1f4(text node, &std::string), what the HUD uses for its own scores.
 * libstdc++ here is the COW ABI: a std::string is one pointer. The strings and the
 * shared_ptr are leaked on purpose (tens of bytes a call; a mode makes a few dozen). */
#define GZ_ATTRACT_PLAYER 0x79ac34u
#define GZ_RES_MGR        0x7db220u
#define TI_RESOURCE       0x6209c4u
#define TI_SCENE_PLAYER   0x673b94u

HK_UNUSED static unsigned gz_std_string(const char *s)
{
    unsigned str = 0, alloc = 0;
    ((void (*)(unsigned *, const char *, unsigned *))(unsigned long)SITE_STR_CTOR)(&str, s, &alloc);
    return str;
}

HK_UNUSED static void *gz_scene(const char *id)
{
    unsigned str;
    void *res, *player;
    if (!id || !*id) {
        player = *(void **)(unsigned long)GZ_ATTRACT_PLAYER;
        return player ? *(void **)((char *)player + 0x10) : 0;
    }
    str = gz_std_string(id);
    res = ((void *(*)(void *, unsigned *, unsigned))(unsigned long)SITE_RES_GET)
          (*(void **)(unsigned long)GZ_RES_MGR, &str, 0u);
    if (!res) return 0;
    player = ((void *(*)(void *, unsigned, unsigned, int))(unsigned long)SITE_DYNCAST)
             (res, TI_RESOURCE, TI_SCENE_PLAYER, 0);
    return player ? *(void **)((char *)player + 0x10) : 0;
}

HK_UNUSED static void *gz_find_with(unsigned finder, void *scene, const char *path)
{
    unsigned str, out[2] = { 0, 0 };
    if (!scene || !path || !*path) return 0;
    str = gz_std_string(path);
    ((void (*)(unsigned *, void *, unsigned *))(unsigned long)finder)(out, scene, &str);
    return (void *)(unsigned long)out[0];
}

HK_UNUSED static void *gz_find_node(void *scene, const char *path)
{
    return gz_find_with(SITE_FIND_NODE, scene, path);
}

HK_UNUSED static void *gz_find_text(void *scene, const char *path)
{
    return gz_find_with(SITE_FIND_TEXT, scene, path);
}

HK_UNUSED static void gz_node_visible(void *node, int on)
{
    if (node) ((void (*)(void *, unsigned))(unsigned long)(*(void ***)node)[0xa8 / 4])(node, on ? 1u : 0u);
}

HK_UNUSED static void gz_node_text(void *node, const char *s)
{
    unsigned str;
    if (!node) return;
    str = gz_std_string(s);
    ((void (*)(void *, unsigned *))(unsigned long)SITE_SET_TEXT)(node, &str);
}

/* ---- clips: a video by NAME on the in-game video surface (item 132) --------------------
 * Every in-game clip is played by one call, 0x528a4(const char *name, int loop, const char
 * *crop label). It takes the VideoSurface node of the video bank scene 60ed7e50
 * ("video.in_game_videos", 0x526b8), sets the clip by name (0x570404 looks it up in that
 * scene's Video map, name -> clip, the clip carrying its scene.assets path), plays it
 * (0x56e210) and seeks the scene to the crop label: 0 means "Normal", the others are
 * ScoreFrame, SquareCrop and LetterboxCrop. End-of-ball bonus is
 * 0x528a4("EndOfBallBonus_BackgroundLoop", 1, "SquareCrop") at 0x65c54. 0x52b04 stops the
 * surface. A clip of OUR own is one more entry in that map: scene_write's video bank. */
HK_UNUSED static void gz_clip_play(const char *name, int loop, const char *label)
{
    if (!name || !*name) return;
    ((void (*)(const char *, int, const char *))(unsigned long)SITE_PLAY_CLIP)
        (name, loop, label && *label ? label : 0);
}

HK_UNUSED static void gz_clip_stop(void)
{
    ((void (*)(void))(unsigned long)SITE_STOP_CLIP)();
}

/* Playing is not DRAWING (item 132, run 1: the clip decoded to end of stream and never
 * reached the glass). The display is immediate-mode: whoever owns a scene draws it every
 * frame, and the game's own clip loop (0x22d50) is
 *     while (state(surface) == 2) { advance(player, lap ms); draw(player, layer); yield }
 * with draw = 0x3ba964(player, 3), which takes the layer from the CURRENT EVENT and logs
 * error 0x101 when there is none - every tick of ours. So this calls what it wraps,
 * 0x4eeb08(display, player, layer 0 or 1), directly. Returns the surface state: 2 while the
 * clip is playing (and so was drawn this frame), anything else when it is not. */
#define GZ_DISPLAY_HOLDER 0x7db1a0u   /* the display manager is at +0x7c */
#define GZ_SURFACE_PLAYING 2

HK_UNUSED static int gz_clip_draw(float ms, unsigned layer)
{
    void *player, *surface, *display;
    int state;
    player = ((void *(*)(void))(unsigned long)SITE_VIDEO_PLAYER)();
    surface = ((void *(*)(void))(unsigned long)SITE_VIDEO_SURFACE)();
    display = *(void **)(unsigned long)(GZ_DISPLAY_HOLDER + 0x7c);
    if (!player || !surface || !display) return -1;
    state = ((int (*)(void *))(unsigned long)SITE_SURFACE_STATE)(surface);
    if (state != GZ_SURFACE_PLAYING) return state;
    ((void (*)(void *, float))(unsigned long)SITE_PLAYER_ADVANCE)(player, ms);
    ((void (*)(void *, void *, unsigned))(unsigned long)SITE_DISPLAY_DRAW)(display, player, layer > 1 ? 1u : layer);
    return state;
}

/* How many of a group's lamps carry the written flag, and the first one's id. The
 * proof that a command reached the lamps: group[0] + id*40, byte +36. */
HK_UNUSED static unsigned gz_group_written(void *group, unsigned *first)
{
    unsigned char *base = group ? *(unsigned char **)group : 0;
    unsigned n = *(unsigned *)(unsigned long)GZ_LAMP_COUNT, i, c = 0;
    if (first) *first = 0;
    if (!base) return 0;
    for (i = 0; i < n; i++)
        if (base[i * 40u + 36u]) {
            if (!c && first) *first = i;
            c++;
        }
    return c;
}

#endif
