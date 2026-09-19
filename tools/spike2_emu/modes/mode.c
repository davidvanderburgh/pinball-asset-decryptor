/* mode.c - ITEM 126: A MODE IS DATA.
 *
 * Item 125 proved a mode of our own can run inside Godzilla Pro 1.15, but the mode
 * WAS this file: KAIJU RUSH's trigger, clock, shot table, awards, screens, lights and
 * callouts were C constants, so changing any of them meant an edit, a cross-compile
 * and a restart. Now they all come from a mode file (modes/kaiju_rush.mode is the
 * same mode, written as data), and this object is the interpreter.
 *
 * HOT RELOAD is the point. The file is re-read twice a second and re-parsed whenever
 * its bytes change, so an edit lands in a RUNNING game inside a second - which is what
 * makes choreographing a mode possible instead of rebuild-and-restart.
 *
 * WHY THE FILE IS NOT JSON: this object is built -nostdlib, with libc declared by hand
 * in hook.h and no allocator at all. A key-per-line format parses in a few dozen lines
 * against fixed buffers, stays hand-editable, and is trivial for the Modes tab (item
 * 127) to write. For the same reason the reload check re-reads and byte-compares
 * rather than calling stat(): hook.h declares no stat, and the file is under 4 KB.
 *
 * EVERY GAME CALL HERE IS EMULATOR-PROVEN AND MAPPED IN MODE_API.md
 *   - shots:  cmode_manager::v[7] (0xd1a9c), every shot mask before any mode sees it
 *   - clock:  the 60 Hz tick (0x4ec828); no game timer is free, all 30 are taken
 *   - score:  score_add (0x4b8cf4), so the multiplier and the event-161 veto apply
 *   - text:   the award screen (0x3ba540) over message ids we point at our own words, OR
 *             (item 131) a screen of our OWN: a node authored into a scene file, found
 *             by name, hidden until the mode runs and written with the game's own
 *             set-text - no message id is touched
 *   - clip:   (item 132) a clip of our OWN, added to the in-game video bank scene by
 *             modes/mode_clip.py, played by name (0x528a4) and drawn every tick while it
 *             plays - the display is immediate-mode, and playing alone never reaches the glass
 *   - lights: the game's own light runner, through hook.h's gz_blele
 *   - sound:  callout_play / callout_play_nth (0x187f44 / 0x18800c)
 *   - end:    the end-of-ball broadcast (0xd3dcc)
 * It is NOT registered with cmode_manager: ours is not one of the 27, and the manager
 * ignores ids above 26 anyway.
 *
 * FILES: a card carries SEVERAL modes (item 133). Slot 0 is mode.cfg, slots 1-7 are
 * mode1.cfg .. mode7.cfg; each is looked for at /usr/local/padmode/ first and /dump/
 * second, and each reloads on its own. Every mode keeps its own trigger counts and
 * its own screen, and ONE of ours runs at a time: there is one video surface and one
 * set of borrowed message slots. /dump/mode.start starts slot 0, /dump/modeK.start
 * slot K, /dump/mode.stop ends whichever is running. LOG: /dump/mode.log.
 *
 * WHY TWO PLACES, AND WHY THE LOG IS NOT ONE OF THEM (item 128, measured on a stock
 * card's p2 with debugfs). On a MACHINE /dump is a partition of its own - fstab says
 * `/dev/mmcblk0p6 /dump ext4 rw` - while the rootfs that carries this object is
 * mounted READ-ONLY (`/dev/root / auto ro,ro`; /etc/init.d/game remounts rw only when
 * it must write). So a card build puts mode.so and its mode file on p2, where a config
 * the game only ever READS is perfectly happy read-only, and the first path finds it.
 * The rig copies one to /dump/mode.cfg instead, and the second path finds that - so
 * hot reload, and every existing driver script, keep working with no change at all.
 *
 * The LOG cannot follow them. hk_log_open on a read-only p2 fails and every [mode]
 * line silently disappears, which looks exactly like the mode refusing to run - the
 * same way a root-owned /dump/mode.log made this object look mute on the rig.
 */
#include "hook.h"

/* Where a slot's file is looked for, in order; first one that opens wins. open() in a
 * loop: this object is -nostdlib with libc declared by hand in hook.h, no allocator, no
 * stat() and no readdir(), so the slots are numbered rather than discovered. */
static const char *const MODE_DIRS[] = {
    "/usr/local/padmode/",              /* a card: p2, read-only, put there by the build */
    "/dump/",                           /* the rig: writable, hot-reloaded */
};
#define MODE_DIRS_N     ((int)(sizeof MODE_DIRS / sizeof MODE_DIRS[0]))
#define MODES_MAX       8               /* mode.cfg, mode1.cfg .. mode7.cfg */
#define TICKS_PER_S     60
#define CFG_MAX         4096
#define STR_MAX         224
#define CALLOUT_AT_MAX  8
#define RELOAD_TICKS    30      /* twice a second */

/* ---- a mode, as loaded from its file ------------------------------------------- */
struct mode_cfg {
    int valid;
    char name[64];
    unsigned long long trigger_bits, shot_bits, award;
    unsigned trigger_count, seconds;
    unsigned screen_type, title_msg, total_msg, restore_after;
    char title_words[STR_MAX], total_words[STR_MAX];
    unsigned light_owner;
    char light_on[STR_MAX], light_off[STR_MAX];
    unsigned at_secs[CALLOUT_AT_MAX], at_id[CALLOUT_AT_MAX], n_at;
    unsigned callout_count, callout_end;
    /* ITEM 130: a sound of our OWN. `sound_key` is the 8-byte container key of a
     * record appended to image.bin - audio the card never shipped and no descriptor
     * names. `sound_callout` is the stock request the mode fires to carry it. */
    unsigned char sound_key[8];
    int has_sound_key;
    unsigned sound_callout;
    /* ITEM 131: a SCREEN of our own. `screen_node` is a node authored into a scene file
     * (a Sprite holding our art and a Text), `screen_scene` the 40-hex id of the scene
     * it lives in (empty = attract; in a game the glass is the HUD scenes, and 32e6ae28
     * carries the mode slide-outs), `screen_text` the Text node our words go into.
     * With a screen_node the borrowed message ids are never touched. */
    char screen_scene[48], screen_node[96], screen_text[128];
    /* ITEM 132: a CLIP of our own. `clip_start` / `clip_end` name a clip in the in-game
     * video bank (scene 60ed7e50) - one the card never shipped once scene_write's video
     * bank has added it - played on the game's own video surface when the mode starts or
     * ends. `clip_label` is the crop the surface seeks to (empty = Normal), `clip_layer`
     * the display layer the mode draws it on, 0 or 1. */
    char clip_start[96], clip_end[96], clip_label[32];
    unsigned clip_layer;
};

/* ---- ITEM 133: one slot per mode file --------------------------------------------
 * Everything that belongs to ONE mode lives here; the run (below) is shared, because
 * one of ours runs at a time. Every function that reads a mode takes the slot as its
 * parameter `M`, and `cfg` is that slot's config - a parameter, never a global, because
 * the shot dispatch and the tick are hooks on game threads and a shared "current mode"
 * pointer would be a race between them. */
struct mode {
    unsigned slot;
    char file[2][40];                   /* the slot's path under each MODE_DIRS entry */
    int said_which;                     /* which of them was last reported */
    struct mode_cfg c;
    char raw[CFG_MAX];                  /* the bytes last parsed */
    long raw_len;
    unsigned trig[5];                   /* trigger shots this ball, per player */
    const char *title_group[6], *total_group[6];
    void *own_node, *own_text;          /* item 131: its screen, once found */
    unsigned own_hide_ticks;
};
static struct mode modes[MODES_MAX];
#define cfg (M->c)

/* ---- the run, while one is running --------------------------------------------- */
static struct {
    int active;
    struct mode *mode;                  /* which one */
    unsigned player, ticks_left, secs_shown, hits;
    unsigned long long total, score_at_start;
    unsigned long started_ms;
    unsigned restore_ticks;
} run;

static int running(const struct mode *M) { return run.active && run.mode == M; }

/* ---- parsing: no allocator, no libc string functions --------------------------- */
static int is_space(int c) { return c == ' ' || c == '\t' || c == '\r'; }

/* Matches `word` at the start of a line and returns what follows it, else 0. */
static const char *key_is(const char *line, const char *word)
{
    while (*word) {
        if (*line != *word) return 0;
        line++;
        word++;
    }
    if (*line && !is_space(*line)) return 0;      /* "seconds" must not match "secondsx" */
    while (is_space(*line)) line++;
    return line;
}

/* Decimal, or 0x hex. Advances *p past the number. */
static unsigned long long num(const char **p)
{
    const char *s = *p;
    unsigned long long x = 0;
    int base = 10;
    while (is_space(*s)) s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { base = 16; s += 2; }
    for (;;) {
        int d = -1;
        if (*s >= '0' && *s <= '9') d = *s - '0';
        else if (base == 16 && *s >= 'a' && *s <= 'f') d = *s - 'a' + 10;
        else if (base == 16 && *s >= 'A' && *s <= 'F') d = *s - 'A' + 10;
        if (d < 0) break;
        x = x * (unsigned)base + (unsigned)d;
        s++;
    }
    while (is_space(*s)) s++;
    *p = s;
    return x;
}

/* The rest of the line, trailing blanks trimmed. Text values are taken verbatim:
 * a light command is full of '-' and digits and must not be tokenised. */
static void rest_of_line(char *dst, unsigned cap, const char *src)
{
    unsigned n = 0;
    while (src[n] && src[n] != '\n' && n + 1 < cap) { dst[n] = src[n]; n++; }
    while (n && is_space(dst[n - 1])) n--;
    dst[n] = 0;
}

static void cfg_line(struct mode *M, const char *line)
{
    const char *a;
    char m[120];
    if ((a = key_is(line, "name")) != 0)              { rest_of_line(cfg.name, sizeof cfg.name, a); return; }
    if ((a = key_is(line, "trigger")) != 0)           { cfg.trigger_bits = num(&a); cfg.trigger_count = (unsigned)num(&a); return; }
    if ((a = key_is(line, "seconds")) != 0)           { cfg.seconds = (unsigned)num(&a); return; }
    if ((a = key_is(line, "shots")) != 0)             { cfg.shot_bits = num(&a); return; }
    if ((a = key_is(line, "award")) != 0)             { cfg.award = num(&a); return; }
    if ((a = key_is(line, "screen_type")) != 0)       { cfg.screen_type = (unsigned)num(&a); return; }
    if ((a = key_is(line, "title_msg")) != 0)         { cfg.title_msg = (unsigned)num(&a); return; }
    if ((a = key_is(line, "total_msg")) != 0)         { cfg.total_msg = (unsigned)num(&a); return; }
    if ((a = key_is(line, "title_words")) != 0)       { rest_of_line(cfg.title_words, STR_MAX, a); return; }
    if ((a = key_is(line, "total_words")) != 0)       { rest_of_line(cfg.total_words, STR_MAX, a); return; }
    if ((a = key_is(line, "restore_after")) != 0)     { cfg.restore_after = (unsigned)num(&a); return; }
    if ((a = key_is(line, "light_owner")) != 0)       { cfg.light_owner = (unsigned)num(&a); return; }
    if ((a = key_is(line, "light_on")) != 0)          { rest_of_line(cfg.light_on, STR_MAX, a); return; }
    if ((a = key_is(line, "light_off")) != 0)         { rest_of_line(cfg.light_off, STR_MAX, a); return; }
    if ((a = key_is(line, "callout_count")) != 0)     { cfg.callout_count = (unsigned)num(&a); return; }
    if ((a = key_is(line, "callout_end")) != 0)       { cfg.callout_end = (unsigned)num(&a); return; }
    if ((a = key_is(line, "sound_callout")) != 0)     { cfg.sound_callout = (unsigned)num(&a); return; }
    if ((a = key_is(line, "screen_scene")) != 0)      { rest_of_line(cfg.screen_scene, sizeof cfg.screen_scene, a); return; }
    if ((a = key_is(line, "screen_node")) != 0)       { rest_of_line(cfg.screen_node, sizeof cfg.screen_node, a); return; }
    if ((a = key_is(line, "screen_text")) != 0)       { rest_of_line(cfg.screen_text, sizeof cfg.screen_text, a); return; }
    if ((a = key_is(line, "clip_start")) != 0)        { rest_of_line(cfg.clip_start, sizeof cfg.clip_start, a); return; }
    if ((a = key_is(line, "clip_end")) != 0)          { rest_of_line(cfg.clip_end, sizeof cfg.clip_end, a); return; }
    if ((a = key_is(line, "clip_label")) != 0)        { rest_of_line(cfg.clip_label, sizeof cfg.clip_label, a); return; }
    if ((a = key_is(line, "clip_layer")) != 0)        { cfg.clip_layer = (unsigned)num(&a); return; }
    if ((a = key_is(line, "sound_key")) != 0) {
        /* 16 hex digits, the key exactly as the derive prints it (a byte string,
         * NOT two words) - so it is copied in order and never byte-swapped. */
        unsigned n = 0;
        while (is_space(*a)) a++;
        while (n < 8) {
            int hi = hk_hex(a[2 * n] | 0x20), lo = hk_hex(a[2 * n + 1] | 0x20);
            if (hi < 0 || lo < 0) break;
            cfg.sound_key[n++] = (unsigned char)((hi << 4) | lo);
        }
        cfg.has_sound_key = (n == 8);
        if (!cfg.has_sound_key)
            hk_logs("[mode] sound_key needs 16 hex digits - ignored\n");
        return;
    }
    if ((a = key_is(line, "callout_at")) != 0) {
        if (cfg.n_at < CALLOUT_AT_MAX) {
            cfg.at_secs[cfg.n_at] = (unsigned)num(&a);
            cfg.at_id[cfg.n_at] = (unsigned)num(&a);
            cfg.n_at++;
        }
        return;
    }
    /* An unknown key is LOGGED AND SKIPPED, never fatal: a newer editor writing a
     * newer key must not break an older mode.so. */
    snprintf(m, sizeof m, "[mode] unknown key, skipped: %.80s\n", line);
    hk_logs(m);
}

static void cfg_parse(struct mode *M, const char *buf, long len)
{
    char line[STR_MAX + 64];
    long i = 0;
    unsigned k;
    char m[200];
    for (k = 0; k < sizeof cfg; k++) ((char *)&cfg)[k] = 0;
    while (i < len) {
        long j = 0;
        while (i < len && buf[i] != '\n') {
            if (j + 1 < (long)sizeof line) line[j++] = buf[i];
            i++;
        }
        i++;                                        /* past the newline */
        line[j] = 0;
        {
            char *s = line;
            while (is_space(*s)) s++;
            if (*s && *s != '#') cfg_line(M, s);
        }
    }
    /* The words a message id is pointed at: five language slots and the terminator. */
    for (k = 0; k < 5; k++) {
        M->title_group[k] = cfg.title_words;
        M->total_group[k] = cfg.total_words;
    }
    M->title_group[5] = M->total_group[5] = 0;
    cfg.valid = cfg.seconds && cfg.trigger_count;
    snprintf(m, sizeof m,
             "[mode] loaded \"%s\": trigger %08x x%u, %u s, shots %08x_%08x, award %llu%s\n",
             cfg.name, (unsigned)cfg.trigger_bits, cfg.trigger_count, cfg.seconds,
             (unsigned)(cfg.shot_bits >> 32), (unsigned)cfg.shot_bits, cfg.award,
             cfg.valid ? "" : "  - NOT VALID, it needs seconds and a trigger count");
    hk_logs(m);
}

static void own_screen_forget(struct mode *M);

/* Re-read the slot's file and byte-compare; re-parse only when it changed.
 * 1 = it changed (loaded, reloaded, or gone). */
static int cfg_reload(struct mode *M)
{
    char buf[CFG_MAX], m[160];
    long n, i;
    int fd = -1, k;
    for (k = 0; k < MODE_DIRS_N; k++) {
        fd = open(M->file[k], O_RDONLY);
        if (fd >= 0) break;
    }
    if (fd < 0) {
        /* A slot whose file went away is disarmed rather than left running on its
         * last contents: the Modes tab removes a mode by removing its file, and a
         * mode the user deleted must not keep starting. A run already under way
         * finishes on the config it started with. */
        if (M->raw_len < 0) return 0;
        M->raw_len = -1;
        M->said_which = -1;
        cfg.valid = 0;
        snprintf(m, sizeof m, "[mode] mode file gone: slot %u (\"%s\") is not armed\n",
                 M->slot, cfg.name);
        hk_logs(m);
        return 1;
    }
    /* Say WHICH file won, once, and say it again if the answer ever changes.
     * A stale /usr/local/padmode/mode.cfg inside the rig's rootfs - which IS an
     * extracted card, so that path can exist there - would silently shadow the
     * /dump file the rig copies, and hot reload would look dead with nothing in
     * the log to say why. Mute failures cost this project a night already. */
    if (M->said_which != k) {
        M->said_which = k;
        snprintf(m, sizeof m, "[mode] mode file: %s\n", M->file[k]);
        hk_logs(m);
    }
    n = read(fd, buf, sizeof buf);
    close(fd);
    if (n < 0) return 0;
    if (n == M->raw_len) {
        for (i = 0; i < n && buf[i] == M->raw[i]; i++) ;
        if (i == n) return 0;
    }
    for (i = 0; i < n; i++) M->raw[i] = buf[i];
    M->raw_len = n;
    cfg_parse(M, M->raw, n);
    own_screen_forget(M);
    return 1;
}

/* ---- the words: our strings behind a message id the screen already knows -------- */
static struct borrowed { unsigned id, idx; const char **old; int held; } borrow[2];

static void words_borrow(struct mode *M)
{
    unsigned count = *(unsigned *)(unsigned long)GZ_MSG_COUNT, i;
    unsigned short *remap = *(unsigned short **)(unsigned long)GZ_MSG_REMAP;
    for (i = 0; i < 2; i++) {
        struct borrowed *b = &borrow[i];
        const char ***slot;
        /* Still held from the LAST mode's restore window: give those back first, or
         * that mode's words would stay behind this id after the game's own came back. */
        if (b->held) {
            *(const char ***)(unsigned long)(GZ_MSG_PTRS + 4u * b->idx) = b->old;
            b->held = 0;
        }
        b->id = i == 0 ? cfg.title_msg : cfg.total_msg;
        if (!b->id || !remap || b->id >= count || remap[b->id] >= count) continue;
        b->idx = remap[b->id];
        slot = (const char ***)(unsigned long)(GZ_MSG_PTRS + 4u * b->idx);
        b->old = *slot;
        *slot = (const char **)(i == 0 ? M->title_group : M->total_group);
        b->held = 1;
    }
}

static void words_restore(void)
{
    unsigned i;
    for (i = 0; i < 2; i++) {
        struct borrowed *b = &borrow[i];
        if (!b->held) continue;
        *(const char ***)(unsigned long)(GZ_MSG_PTRS + 4u * b->idx) = b->old;
        b->held = 0;
    }
}

/* ---- the lights ---------------------------------------------------------------- */
static void *light_group;
static unsigned light_check_ticks;
static const char *light_why = "";

static void lights(struct mode *M, const char *cmd, const char *why)
{
    char m[160];
    if (!cfg.light_owner || !*cmd) return;
    light_group = gz_blele(cfg.light_owner, cmd);
    light_why = why;
    light_check_ticks = TICKS_PER_S / 2;
    snprintf(m, sizeof m, "[mode] lights %s: group %p\n", why, light_group);
    hk_logs(m);
}

/* A command writes nothing at parse time - the game's own award wrote its lamps 0.2 s
 * after the call (item 125, run 12) - so the count is read from the tick, not here. */
static void lights_check(void)
{
    char m[160];
    unsigned first = 0, n;
    if (!light_check_ticks || --light_check_ticks) return;
    n = gz_group_written(light_group, &first);
    snprintf(m, sizeof m, "[mode] lights %s landed: %u lamps written, first %u\n",
             light_why, n, first);
    hk_logs(m);
}

/* ---- ITEM 131: a screen of our own ------------------------------------------------
 * Found by name once its scene is loaded, and hidden straight away: a node is drawn
 * only while its keyframes AND this flag allow it, so the screen is authored visible
 * and it is the mode that keeps it off the glass. Emulator-proven in a game on the
 * Tokyo map (TODO item 131). */
static int own_screen(struct mode *M) { return cfg.screen_node[0] != 0; }

static void own_screen_forget(struct mode *M) { M->own_node = M->own_text = 0; }

/* EVERY mode's screen is found and hidden, not only the running one's: each is
 * authored visible, so a screen nobody hides is on the glass all game. */
static void own_screen_resolve(struct mode *M)
{
    char m[260];
    void *scene;
    if (!own_screen(M) || M->own_node) return;
    scene = gz_scene(cfg.screen_scene);
    M->own_node = gz_find_node(scene, cfg.screen_node);
    if (!M->own_node) return;
    M->own_text = gz_find_text(scene, cfg.screen_text);
    if (!running(M)) gz_node_visible(M->own_node, 0);
    snprintf(m, sizeof m, "[mode] own screen \"%.60s\" found (scene %.12s, node %p, text %p) - %s\n",
             cfg.screen_node, cfg.screen_scene[0] ? cfg.screen_scene : "attract", M->own_node,
             M->own_text, running(M) ? "left visible, the mode is running" : "hidden until the mode runs");
    hk_logs(m);
}

/* 1234567 -> "1,234,567" */
static void commas(char *out, unsigned cap, unsigned long long v)
{
    char rev[32];
    unsigned n = 0, i;
    do {
        if (n && n % 4 == 3) rev[n++] = ',';
        rev[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v && n + 2 < sizeof rev);
    for (i = 0; i < n && i + 1 < cap; i++) out[i] = rev[n - 1 - i];
    out[i] = 0;
}

static void own_words(struct mode *M, const char *before, unsigned long long value, const char *after)
{
    char num[32], s[96];
    if (!M->own_text) return;
    commas(num, sizeof num, value);
    snprintf(s, sizeof s, "%s%s%s", before, num, after);
    gz_node_text(M->own_text, s);
}

/* ---- ITEM 132: a clip of our own --------------------------------------------------
 * By name, through the call the game makes for every in-game clip (hook.h gz_clip_play).
 * The name must be in the video bank scene: a name it does not have is a clip the game
 * cannot find, so the mode file is what has to agree with the scene the build installed.
 * Playing only decodes it; the mode then DRAWS the video player every tick until the
 * surface stops playing (hook.h gz_clip_draw), the way the game's own clip loops do. */
#define CLIP_GRACE_MS 3000     /* a clip not playing this long after the call never started */

static struct {
    int on, seen_playing;
    unsigned layer, draws;
    unsigned long started_ms, last_ms;
    char name[96];
} cl;

static void clip_on_layer(struct mode *M, const char *name, unsigned layer, const char *why)
{
    char m[220];
    unsigned i;
    if (!name || !*name) return;
    gz_clip_play(name, 0, cfg.clip_label);
    for (i = 0; name[i] && i + 1 < sizeof cl.name; i++) cl.name[i] = name[i];
    cl.name[i] = 0;
    cl.on = 1;
    cl.seen_playing = 0;
    cl.layer = layer;
    cl.draws = 0;
    cl.started_ms = cl.last_ms = hk_ms();
    snprintf(m, sizeof m, "[mode] clip \"%.80s\" played (%s, crop %s, layer %u)\n",
             name, why, cfg.clip_label[0] ? cfg.clip_label : "Normal", layer);
    hk_logs(m);
}

static void clip(struct mode *M, const char *name, const char *why)
{
    clip_on_layer(M, name, cfg.clip_layer, why);
}

static void clip_tick(void)
{
    char m[200];
    unsigned long now;
    int state;
    if (!cl.on) return;
    now = hk_ms();
    state = gz_clip_draw((float)(now - cl.last_ms), cl.layer);
    cl.last_ms = now;
    if (state == GZ_SURFACE_PLAYING) {
        if (!cl.seen_playing) {
            snprintf(m, sizeof m, "[mode] clip \"%.80s\" playing after %lu ms - drawing it on layer %u\n",
                     cl.name, now - cl.started_ms, cl.layer);
            hk_logs(m);
        }
        cl.seen_playing = 1;
        cl.draws++;
        return;
    }
    if (!cl.seen_playing && now - cl.started_ms < CLIP_GRACE_MS) return;
    cl.on = 0;
    snprintf(m, sizeof m, "[mode] clip \"%.80s\" %s after %lu ms, %u frames drawn (surface state %d)\n",
             cl.name, cl.seen_playing ? "finished" : "NEVER PLAYED", now - cl.started_ms, cl.draws, state);
    hk_logs(m);
}

/* /dump/mode.clip holds a clip NAME and an optional layer, not numbers, so it is not
 * hk_read_trigger's. Read, deleted, first line only. For the rig and the Modes tab: play
 * any clip in the bank, ours or a stock one, without starting a mode. The crop and the
 * default layer are the running mode's, else slot 0's. */
static void clip_trigger(struct mode *M)
{
    char buf[120];
    long n, sp;
    unsigned layer;
    const char *p;
    int fd = open("/dump/mode.clip", O_RDONLY);
    if (fd < 0) return;
    n = read(fd, buf, sizeof buf - 1);
    close(fd);
    unlink("/dump/mode.clip");
    buf[n > 0 ? n : 0] = 0;
    for (n = 0; buf[n] && buf[n] != '\n' && buf[n] != '\r'; n++) ;
    buf[n] = 0;
    layer = cfg.clip_layer;
    for (sp = 0; buf[sp] && buf[sp] != ' '; sp++) ;
    if (buf[sp] == ' ') {
        buf[sp] = 0;
        p = buf + sp + 1;
        layer = (unsigned)num(&p);
    }
    clip_on_layer(M, buf, layer, "trigger file");
}

/* ---- the game calls ------------------------------------------------------------ */
static void screen(struct mode *M, unsigned msg, unsigned long long value)
{
    unsigned char *node;
    if (!cfg.screen_type || !msg) return;
    node = ((unsigned char *(*)(unsigned, unsigned, unsigned, unsigned))
            (unsigned long)SITE_TEXT)(cfg.screen_type, 0u, 0u, 0x6fa618u);
    if (!node) return;
    *(unsigned short *)(node + 0xa0) = (unsigned short)msg;
    *(unsigned long long *)(node + 0xa8) = value;
    *(unsigned *)(node + 0xb0) = 0u;
}

static unsigned long long score_now(unsigned p)
{
    return p >= 1 && p <= 4 ? ((unsigned long long *)(unsigned long)GZ_SCORES)[p - 1] : 0ull;
}

static unsigned long long score_add(unsigned p, unsigned long long v)
{
    return ((unsigned long long (*)(unsigned, unsigned long long))(unsigned long)SITE_SCORE_ADD)(p, v);
}

static void callout(unsigned req)
{
    if (req) ((void (*)(unsigned))(unsigned long)SITE_CALLOUT)(req);
}

/* ---- ITEM 130: a sound the game never shipped ----------------------------------
 * The play chain is request -> sid -> descriptor -> an 8-byte key -> sound_lookup
 * -> the entry the engine built from a record in image.bin. The boot-time band
 * build registers EVERY record under a key of its own, so a record we APPENDED is
 * already a live entry - it is simply one that no descriptor names.
 *
 * So the mode does not re-point anything on the card. It arms a one-shot, fires an
 * ordinary callout, and while that callout resolves, the hook points the lookup's
 * key pointer at OUR key. The game then finds our entry and plays it through its
 * own channel arbitration, priority and veto.
 *
 * TWO THREADS. The arm happens on the tick (the scheduler thread) and the lookup
 * runs on whatever thread the audio path uses, so this is a handoff and not a lock.
 * It FAILS CLOSED on purpose: if some other sound's lookup consumes the one-shot
 * first, that sound plays ours and ours plays stock - wrong audio for one callout,
 * never a bad pointer. `sound_armed` is only ever set immediately before the call
 * it is meant for, and cleared by the first lookup that sees it. */
static volatile int sound_armed;
static unsigned sound_subs, sound_misses;
/* WHICH key the one-shot carries (item 133: every mode has its own). Set before the
 * arm, never cleared, and it points into a mode slot that lives as long as this
 * object - so the lookup thread can never read a dangling key, only an earlier one. */
static const unsigned char *volatile sound_key_ptr;

static void callout_ours(struct mode *M, unsigned req)
{
    if (!req || !cfg.has_sound_key) { callout(req); return; }
    sound_key_ptr = cfg.sound_key;
    sound_armed = 1;
    callout(req);
    if (sound_armed) {                 /* nothing looked anything up: stock played */
        sound_armed = 0;
        sound_misses++;
    }
}

/* sound_lookup(map, key_ptr): repoint r1 at our key while the one-shot is armed. */
static void on_lookup(unsigned *r)
{
    if (!sound_armed || !sound_key_ptr) return;
    sound_armed = 0;
    r[1] = (unsigned)(unsigned long)sound_key_ptr;
    sound_subs++;
}

static void callout_nth(unsigned req, unsigned n)
{
    if (req) ((void (*)(unsigned, unsigned))(unsigned long)SITE_CALLOUT_NTH)(req, n);
}

/* ---- the mode ------------------------------------------------------------------ */
static void mode_start(struct mode *M, const char *why)
{
    char m[200];
    if (!cfg.valid || !gz_in_game()) return;
    if (run.active) {
        /* One of ours at a time: one video surface, one set of borrowed words. */
        if (run.mode != M) {
            snprintf(m, sizeof m, "[mode] %s not started (%s): %s is running\n",
                     cfg.name, why, run.mode->c.name);
            hk_logs(m);
        }
        return;
    }
    run.active = 1;
    run.mode = M;
    run.player = gz_player();
    run.ticks_left = cfg.seconds * TICKS_PER_S;
    run.secs_shown = cfg.seconds;
    run.hits = 0;
    run.total = 0;
    run.score_at_start = score_now(run.player);
    run.started_ms = hk_ms();
    if (run.player <= 4) M->trig[run.player] = 0;
    run.restore_ticks = 0;
    if (own_screen(M)) {
        own_screen_resolve(M);
        if (M->own_node) {
            own_words(M, "", cfg.award, " A SHOT");
            gz_node_visible(M->own_node, 1);
            M->own_hide_ticks = 0;
        } else {
            hk_logs("[mode] own screen not found - nothing shown, and no message id borrowed\n");
        }
    } else {
        words_borrow(M);
    }
    lights(M, cfg.light_on, "on");
    clip(M, cfg.clip_start, "mode start");
    if (!own_screen(M)) screen(M, cfg.title_msg, cfg.award);
    snprintf(m, sizeof m, "[mode] %s START (%s): slot %u, player %u, %u s, score %llu\n",
             cfg.name, why, M->slot, run.player, cfg.seconds, run.score_at_start);
    hk_logs(m);
}

static void mode_end(const char *why)
{
    char m[240];
    struct mode *M = run.mode;
    if (!run.active || !M) return;
    run.active = 0;
    lights(M, cfg.light_off, "off");
    clip(M, cfg.clip_end, "mode end");
    if (own_screen(M)) {
        own_words(M, "TOTAL ", run.total, "");
        M->own_hide_ticks = (cfg.restore_after ? cfg.restore_after : 4) * TICKS_PER_S;
    } else {
        screen(M, cfg.total_msg, run.total);
        run.restore_ticks = cfg.restore_after * TICKS_PER_S;
    }
    snprintf(m, sizeof m, "[mode] %s END (%s): %u shots, awarded %llu, score %llu -> %llu, %lu ms wall\n",
             cfg.name, why, run.hits, run.total, run.score_at_start,
             score_now(run.player), hk_ms() - run.started_ms);
    hk_logs(m);
    if (cfg.has_sound_key) {
        snprintf(m, sizeof m, "[mode] own sound: %u substitution(s), %u miss(es)\n",
                 sound_subs, sound_misses);
        hk_logs(m);
    }
}

/* ---- the shot dispatch: cmode_manager::v[7](mgr, _, mask64, x) ------------------ */
static void on_dispatch(unsigned *r)
{
    unsigned long long mask = ((unsigned long long)r[3] << 32) | r[2];
    unsigned p = gz_player(), k;
    char m[200];
    struct mode *M;
    if (!gz_in_game()) return;
    /* The running mode scores its shots first, so a shot that is ALSO another mode's
     * trigger still pays in the mode that is up. */
    if (run.active && (M = run.mode) != 0 && p == run.player && (mask & cfg.shot_bits)) {
        unsigned long long asked = cfg.award * ++run.hits, got = score_add(p, asked);
        run.total += got;
        if (own_screen(M)) own_words(M, "+", got, "");
        else screen(M, cfg.title_msg, got);
        snprintf(m, sizeof m, "[mode] shot %08x_%08x: +%llu (asked %llu), %u shots, %llu awarded\n",
                 (unsigned)(mask >> 32), (unsigned)mask, got, asked, run.hits, run.total);
        hk_logs(m);
    }
    if (p < 1 || p > 4) return;
    for (k = 0; k < MODES_MAX; k++) {
        M = &modes[k];
        if (!cfg.valid || running(M) || !cfg.trigger_bits || !(mask & cfg.trigger_bits)) continue;
        M->trig[p]++;
        snprintf(m, sizeof m, "[mode] %s trigger %u of %u (player %u)\n",
                 cfg.name, M->trig[p], cfg.trigger_count, p);
        hk_logs(m);
        if (M->trig[p] >= cfg.trigger_count) mode_start(M, "trigger shot");
    }
}

/* ---- the end-of-ball broadcast -------------------------------------------------- */
static void on_ballend(unsigned *r)
{
    unsigned k, p;
    (void)r;
    mode_end("ball ended");
    for (k = 0; k < MODES_MAX; k++)
        for (p = 0; p < 5; p++) modes[k].trig[p] = 0;
}

/* ---- the clock ------------------------------------------------------------------ */
static void on_tick(unsigned *r)
{
    static unsigned ticks;
    unsigned long long v[4];
    unsigned secs, i, k;
    char m[80], path[32];
    struct mode *M;
    (void)r;
    ++ticks;
    for (k = 0; k < MODES_MAX; k++) {
        M = &modes[k];
        if (ticks % RELOAD_TICKS == 0 && cfg_reload(M) && running(M))
            hk_logs("[mode] reloaded while running - the new file is live\n");
        if (ticks % 30 == 0) {
            own_screen_resolve(M);
            /* slot 0 keeps the name every script already writes */
            if (k == 0) snprintf(path, sizeof path, "/dump/mode.start");
            else snprintf(path, sizeof path, "/dump/mode%u.start", k);
            if (hk_read_trigger(path, v) >= 0) mode_start(M, "trigger file");
        }
        if (M->own_hide_ticks && --M->own_hide_ticks == 0 && !running(M) && M->own_node) {
            gz_node_visible(M->own_node, 0);
            hk_logs("[mode] own screen hidden\n");
        }
    }
    if (ticks % 30 == 0) {
        if (hk_read_trigger("/dump/mode.stop", v) >= 0) mode_end("trigger file");
        clip_trigger(run.active ? run.mode : &modes[0]);
    }
    clip_tick();
    lights_check();
    if (run.restore_ticks && --run.restore_ticks == 0 && !run.active) {
        words_restore();
        hk_logs("[mode] borrowed messages restored\n");
    }
    if (!run.active || !(M = run.mode)) return;
    if (!gz_in_game() || gz_player() != run.player) {
        mode_end("left the game, or the player changed");
        return;
    }
    if (run.ticks_left) run.ticks_left--;
    secs = (run.ticks_left + TICKS_PER_S - 1) / TICKS_PER_S;
    if (secs != run.secs_shown) {
        run.secs_shown = secs;
        for (i = 0; i < cfg.n_at; i++)
            if (secs == cfg.at_secs[i]) callout(cfg.at_id[i]);
        if (secs >= 1 && secs <= 5) callout_nth(cfg.callout_count, secs - 1);
        if (secs % 10 == 0 || secs <= 5) {
            snprintf(m, sizeof m, "[mode] %u s left\n", secs);
            hk_logs(m);
        }
    }
    if (run.ticks_left == 0) {
        /* The mode signs off in a voice of its own when the file gives it one. */
        if (cfg.has_sound_key && cfg.sound_callout)
            callout_ours(M, cfg.sound_callout);
        else
            callout(cfg.callout_end);
        mode_end("time ran out");
    }
}

__attribute__((constructor))
static void mode_init(void)
{
    char m[160];
    int ok, found = 0, d;
    unsigned k;
    if (!hk_is_game_process(SITE_TICK)) return;
    hk_log_open("/dump/mode.log");
    ok = hk_site_ok(SITE_TICK, SITE_TICK_W0, SITE_TICK_W1, "tick")
       & hk_site_ok(SITE_DISPATCH, SITE_DISPATCH_W0, SITE_DISPATCH_W1, "dispatch")
       & hk_site_ok(SITE_BALLEND, SITE_BALLEND_W0, SITE_BALLEND_W1, "ballend")
       & hk_site_ok(SITE_SCORE_ADD, SITE_SCORE_ADD_W0, SITE_SCORE_ADD_W1, "score_add")
       & hk_site_ok(SITE_CALLOUT, SITE_CALLOUT_W0, SITE_CALLOUT_W1, "callout")
       & hk_site_ok(SITE_CALLOUT_NTH, SITE_CALLOUT_NTH_W0, SITE_CALLOUT_NTH_W1, "callout_nth")
       & hk_site_ok(SITE_TEXT, SITE_TEXT_W0, SITE_TEXT_W1, "award_screen")
       & hk_site_ok(SITE_BLELE_RUN, SITE_BLELE_RUN_W0, SITE_BLELE_RUN_W1, "blele_run")
       & hk_site_ok(SITE_LAMP_GROUP, SITE_LAMP_GROUP_W0, SITE_LAMP_GROUP_W1, "lamp_group")
       & hk_site_ok(SITE_SHOW_PRIO, SITE_SHOW_PRIO_W0, SITE_SHOW_PRIO_W1, "show_prio")
       & hk_site_ok(SITE_SOUND_LOOKUP, SITE_SOUND_LOOKUP_W0, SITE_SOUND_LOOKUP_W1,
                    "sound_lookup")
       & hk_site_ok(SITE_FIND_NODE, SITE_FIND_NODE_W0, SITE_FIND_NODE_W1, "find_node")
       & hk_site_ok(SITE_FIND_TEXT, SITE_FIND_TEXT_W0, SITE_FIND_TEXT_W1, "find_text")
       & hk_site_ok(SITE_SET_TEXT, SITE_SET_TEXT_W0, SITE_SET_TEXT_W1, "set_text")
       & hk_site_ok(SITE_RES_GET, SITE_RES_GET_W0, SITE_RES_GET_W1, "resource_get")
       & hk_site_ok(SITE_STR_CTOR, SITE_STR_CTOR_W0, SITE_STR_CTOR_W1, "std_string")
       & hk_site_ok(SITE_DYNCAST, SITE_DYNCAST_W0, SITE_DYNCAST_W1, "dynamic_cast")
       & hk_site_ok(SITE_PLAY_CLIP, SITE_PLAY_CLIP_W0, SITE_PLAY_CLIP_W1, "play_clip")
       & hk_site_ok(SITE_STOP_CLIP, SITE_STOP_CLIP_W0, SITE_STOP_CLIP_W1, "stop_clip")
       & hk_site_ok(SITE_VIDEO_PLAYER, SITE_VIDEO_PLAYER_W0, SITE_VIDEO_PLAYER_W1, "video_player")
       & hk_site_ok(SITE_VIDEO_SURFACE, SITE_VIDEO_SURFACE_W0, SITE_VIDEO_SURFACE_W1, "video_surface")
       & hk_site_ok(SITE_SURFACE_STATE, SITE_SURFACE_STATE_W0, SITE_SURFACE_STATE_W1, "surface_state")
       & hk_site_ok(SITE_PLAYER_ADVANCE, SITE_PLAYER_ADVANCE_W0, SITE_PLAYER_ADVANCE_W1, "player_advance")
       & hk_site_ok(SITE_DISPLAY_DRAW, SITE_DISPLAY_DRAW_W0, SITE_DISPLAY_DRAW_W1, "display_draw");
    if (!ok) {
        hk_logs("[mode] NOT THIS BUILD - no mode is installed, the game runs stock\n");
        return;
    }
    hk_install(SITE_TICK, on_tick);
    hk_install(SITE_DISPATCH, on_dispatch);
    hk_install(SITE_BALLEND, on_ballend);
    hk_install(SITE_SOUND_LOOKUP, on_lookup);
    /* Neither line names ONE path: which directory wins for a slot is decided in
     * cfg_reload() (which says so, once, in its own line). Printing a single path
     * here would be a guess, and a log that guesses is worse than one that says what
     * it is actually doing. */
    for (k = 0; k < MODES_MAX; k++) {
        struct mode *M = &modes[k];
        M->slot = k;
        M->raw_len = -1;
        M->said_which = -1;
        for (d = 0; d < MODE_DIRS_N; d++) {
            if (k == 0) snprintf(M->file[d], sizeof M->file[d], "%smode.cfg", MODE_DIRS[d]);
            else snprintf(M->file[d], sizeof M->file[d], "%smode%u.cfg", MODE_DIRS[d], k);
        }
        found += cfg_reload(M);
    }
    if (!found) {
        snprintf(m, sizeof m, "[mode] no mode file at %s or %s yet - polling\n",
                 modes[0].file[0], modes[0].file[1]);
        hk_logs(m);
    }
    snprintf(m, sizeof m, "[mode] armed, %d mode file(s) now, reading %d slot(s) x %d path(s) twice a second\n",
             found, MODES_MAX, MODE_DIRS_N);
    hk_logs(m);
}
