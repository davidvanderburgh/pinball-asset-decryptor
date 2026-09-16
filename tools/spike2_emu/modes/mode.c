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
 *   - text:   the award screen (0x3ba540) over message ids we point at our own words
 *   - lights: the game's own light runner, through hook.h's gz_blele
 *   - sound:  callout_play / callout_play_nth (0x187f44 / 0x18800c)
 *   - end:    the end-of-ball broadcast (0xd3dcc)
 * It is NOT registered with cmode_manager: ours is not one of the 27, and the manager
 * ignores ids above 26 anyway.
 *
 * FILES: the mode file is /dump/mode.cfg (the rig copies one there). /dump/mode.start
 * and /dump/mode.stop still force a start or an end for testing. LOG: /dump/mode.log.
 */
#include "hook.h"

#define MODE_FILE       "/dump/mode.cfg"
#define TICKS_PER_S     60
#define CFG_MAX         4096
#define STR_MAX         224
#define CALLOUT_AT_MAX  8
#define RELOAD_TICKS    30      /* twice a second */

/* ---- the mode, as loaded from the file ---------------------------------------- */
static struct {
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
} cfg;

/* ---- the run, while it is running ---------------------------------------------- */
static struct {
    int active;
    unsigned player, ticks_left, secs_shown, hits;
    unsigned long long total, score_at_start;
    unsigned long started_ms;
    unsigned trig[5];
    unsigned restore_ticks;
} run;

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

static void cfg_line(const char *line)
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

/* The words a message id is pointed at, five language slots plus the terminator. */
static const char *title_group[6], *total_group[6];

static void cfg_parse(const char *buf, long len)
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
            if (*s && *s != '#') cfg_line(s);
        }
    }
    for (k = 0; k < 5; k++) {
        title_group[k] = cfg.title_words;
        total_group[k] = cfg.total_words;
    }
    title_group[5] = total_group[5] = 0;
    cfg.valid = cfg.seconds && cfg.trigger_count;
    snprintf(m, sizeof m,
             "[mode] loaded \"%s\": trigger %08x x%u, %u s, shots %08x_%08x, award %llu%s\n",
             cfg.name, (unsigned)cfg.trigger_bits, cfg.trigger_count, cfg.seconds,
             (unsigned)(cfg.shot_bits >> 32), (unsigned)cfg.shot_bits, cfg.award,
             cfg.valid ? "" : "  - NOT VALID, it needs seconds and a trigger count");
    hk_logs(m);
}

/* Re-read and byte-compare; re-parse only when it changed. 1 = it changed. */
static char cfg_raw[CFG_MAX];
static long cfg_raw_len = -1;

static int cfg_reload(void)
{
    char buf[CFG_MAX];
    long n, i;
    int fd = open(MODE_FILE, O_RDONLY);
    if (fd < 0) return 0;
    n = read(fd, buf, sizeof buf);
    close(fd);
    if (n < 0) return 0;
    if (n == cfg_raw_len) {
        for (i = 0; i < n && buf[i] == cfg_raw[i]; i++) ;
        if (i == n) return 0;
    }
    for (i = 0; i < n; i++) cfg_raw[i] = buf[i];
    cfg_raw_len = n;
    cfg_parse(cfg_raw, n);
    return 1;
}

/* ---- the words: our strings behind a message id the screen already knows -------- */
static struct borrowed { unsigned id, idx; const char **old; int held; } borrow[2];

static void words_borrow(void)
{
    unsigned count = *(unsigned *)(unsigned long)GZ_MSG_COUNT, i;
    unsigned short *remap = *(unsigned short **)(unsigned long)GZ_MSG_REMAP;
    borrow[0].id = cfg.title_msg;
    borrow[1].id = cfg.total_msg;
    for (i = 0; i < 2; i++) {
        struct borrowed *b = &borrow[i];
        const char ***slot;
        if (b->held || !b->id || !remap || b->id >= count || remap[b->id] >= count) continue;
        b->idx = remap[b->id];
        slot = (const char ***)(unsigned long)(GZ_MSG_PTRS + 4u * b->idx);
        b->old = *slot;
        *slot = (const char **)(i == 0 ? title_group : total_group);
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

static void lights(const char *cmd, const char *why)
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

/* ---- the game calls ------------------------------------------------------------ */
static void screen(unsigned msg, unsigned long long value)
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

static void callout_ours(unsigned req)
{
    if (!req || !cfg.has_sound_key) { callout(req); return; }
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
    if (!sound_armed) return;
    sound_armed = 0;
    r[1] = (unsigned)(unsigned long)cfg.sound_key;
    sound_subs++;
}

static void callout_nth(unsigned req, unsigned n)
{
    if (req) ((void (*)(unsigned, unsigned))(unsigned long)SITE_CALLOUT_NTH)(req, n);
}

/* ---- the mode ------------------------------------------------------------------ */
static void mode_start(const char *why)
{
    char m[200];
    if (run.active || !cfg.valid || !gz_in_game()) return;
    run.active = 1;
    run.player = gz_player();
    run.ticks_left = cfg.seconds * TICKS_PER_S;
    run.secs_shown = cfg.seconds;
    run.hits = 0;
    run.total = 0;
    run.score_at_start = score_now(run.player);
    run.started_ms = hk_ms();
    run.trig[run.player] = 0;
    run.restore_ticks = 0;
    words_borrow();
    lights(cfg.light_on, "on");
    screen(cfg.title_msg, cfg.award);
    snprintf(m, sizeof m, "[mode] %s START (%s): player %u, %u s, score %llu\n",
             cfg.name, why, run.player, cfg.seconds, run.score_at_start);
    hk_logs(m);
}

static void mode_end(const char *why)
{
    char m[240];
    if (!run.active) return;
    run.active = 0;
    lights(cfg.light_off, "off");
    screen(cfg.total_msg, run.total);
    run.restore_ticks = cfg.restore_after * TICKS_PER_S;
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
    unsigned p = gz_player();
    char m[200];
    if (!cfg.valid || !gz_in_game()) return;
    if (!run.active) {
        if (cfg.trigger_bits && (mask & cfg.trigger_bits) && p >= 1 && p <= 4) {
            run.trig[p]++;
            snprintf(m, sizeof m, "[mode] trigger %u of %u (player %u)\n",
                     run.trig[p], cfg.trigger_count, p);
            hk_logs(m);
            if (run.trig[p] >= cfg.trigger_count) mode_start("trigger shot");
        }
        return;
    }
    if (p == run.player && (mask & cfg.shot_bits)) {
        unsigned long long asked = cfg.award * ++run.hits, got = score_add(p, asked);
        run.total += got;
        screen(cfg.title_msg, got);
        snprintf(m, sizeof m, "[mode] shot %08x_%08x: +%llu (asked %llu), %u shots, %llu awarded\n",
                 (unsigned)(mask >> 32), (unsigned)mask, got, asked, run.hits, run.total);
        hk_logs(m);
    }
}

/* ---- the end-of-ball broadcast -------------------------------------------------- */
static void on_ballend(unsigned *r)
{
    (void)r;
    mode_end("ball ended");
    run.trig[1] = run.trig[2] = run.trig[3] = run.trig[4] = 0;
}

/* ---- the clock ------------------------------------------------------------------ */
static void on_tick(unsigned *r)
{
    static unsigned ticks;
    unsigned long long v[4];
    unsigned secs, i;
    char m[80];
    (void)r;
    if (++ticks % RELOAD_TICKS == 0 && cfg_reload() && run.active)
        hk_logs("[mode] reloaded while running - the new file is live\n");
    if (ticks % 30 == 0) {
        if (hk_read_trigger("/dump/mode.start", v) >= 0) mode_start("trigger file");
        if (hk_read_trigger("/dump/mode.stop", v) >= 0) mode_end("trigger file");
    }
    lights_check();
    if (run.restore_ticks && --run.restore_ticks == 0 && !run.active) {
        words_restore();
        hk_logs("[mode] borrowed messages restored\n");
    }
    if (!run.active) return;
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
            callout_ours(cfg.sound_callout);
        else
            callout(cfg.callout_end);
        mode_end("time ran out");
    }
}

__attribute__((constructor))
static void mode_init(void)
{
    char m[120];
    int ok;
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
                    "sound_lookup");
    if (!ok) {
        hk_logs("[mode] NOT THIS BUILD - no mode is installed, the game runs stock\n");
        return;
    }
    hk_install(SITE_TICK, on_tick);
    hk_install(SITE_DISPATCH, on_dispatch);
    hk_install(SITE_BALLEND, on_ballend);
    hk_install(SITE_SOUND_LOOKUP, on_lookup);
    if (!cfg_reload())
        hk_logs("[mode] no mode file at " MODE_FILE " yet - polling for one\n");
    snprintf(m, sizeof m, "[mode] armed, reading %s twice a second\n", MODE_FILE);
    hk_logs(m);
}
