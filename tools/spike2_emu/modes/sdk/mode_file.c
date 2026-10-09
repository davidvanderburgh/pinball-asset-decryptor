/* mode_file.c - modes written as FILES, run by a mode written in C (items 126, 133, 134).
 *
 * The Modes tab does not write C: it writes key-per-line mode files (mode.cfg,
 * mode1.cfg, mode2.cfg ...), and this mode interprets them. It is an ordinary mode on
 * pad_mode.h - no address in it - so it runs on any game with a port, beside any modes
 * written in C, and pm_begin() keeps all of them to one at a time.
 *
 * It is items 126-133's mode.c, moved onto the SDK with its behaviour kept:
 *   - slot 0 is mode.cfg, slot K modeK.cfg, each looked for in /usr/local/padmode/
 *     (a card) then /dump/ (the rig), each re-read twice a second and re-parsed when its
 *     bytes change, a vanished file disarming its slot. The app numbers the files with no
 *     gaps, so after the first sweep only the slots up to one past the last file are
 *     re-read (poll_n): 64 slots cost what the files there are, not 64 x 2 open()s;
 *   - every slot keeps its own trigger counts and its own screen, and every screen is
 *     found and hidden;
 *   - /dump/mode.start starts slot 0, /dump/modeK.start slot K, /dump/mode.stop ends
 *     whichever is running, /dump/mode.clip "<name>" plays any clip.
 * Its log lines are `[mode] ...`, as before, because the SDK prefixes them with this
 * mode's name - "mode".
 *
 * Not carried over: the "lights landed: N lamps written" diagnostic (it read a lamp
 * table the SDK does not expose), and clip_label / clip_layer (the SDK plays clips on
 * the port's layer with the Normal crop; layer 1 was measured to show nothing anyway).
 */
#include "pad_mode.h"

static const char *const MODE_DIRS[] = { "/usr/local/padmode/", "/dump/" };
#define MODE_DIRS_N     2
#define MODES_MAX       64          /* high enough never to be the limit a person meets */
#define TICKS_PER_S     60
#define CFG_MAX         4096
#define STR_MAX         224
#define CALLOUT_AT_MAX  8
#define POLL_TICKS      30          /* files and triggers, twice a second */
#define SHOT_AWARD_MAX  16          /* shot_award lines a file may carry (item 141) */
#define BLOCK_LIST_MAX  128         /* PAD-363: the game's mode ids a `block_modes` line may list */

#define ALSO_MAX 3                  /* PAD-227: trigger_also lines a mode may have */
#define SEQ_MAX 8                   /* PAD-314: trigger_seq lines a mode may have (shots in order) */

struct mode_cfg {
    int valid;
    char name[64];
    uint64_t trigger_bits, shot_bits, award;
    unsigned trigger_count, seconds;
    unsigned screen_type, title_msg, total_msg, restore_after;
    char title_words[STR_MAX], total_words[STR_MAX];
    unsigned light_owner;
    char light_on[STR_MAX], light_off[STR_MAX];
    unsigned at_secs[CALLOUT_AT_MAX], at_id[CALLOUT_AT_MAX], n_at;
    unsigned callout_count, callout_end;
    unsigned char sound_key[8];
    int has_sound_key;
    unsigned sound_callout;
    char screen_scene[96], screen_node[96], screen_text[128];   /* a nested scene id: 40 hex, /, 40 hex */
    char clip_start[96], clip_end[96];
    unsigned starts_game, starts_ball, cooldown_s;   /* item 139: 0 = no limit */
    int stack_no;                   /* item 140: `stack no` - never beside the game's battle or multiball */
    int aside_keep;                 /* PAD-347: `aside keep` - its screen stays up beside a game mode */
    int game_modes;                 /* PAD-363: GM_STACK, GM_GIVE_WAY or GM_BLOCK (PAD-398: the default) */
    unsigned char block_ids[BLOCK_LIST_MAX];   /* PAD-363: `block_modes` - the game's mode ids it holds off */
    int block_n;                    /* ... how many (0 = every one the port names) */
    unsigned char keep_rules[32];   /* PAD-398: `keep_rules` - the game's rules that go on counting while it blocks */
    int keep_n;
    /* item 141: what each shot pays, a shot that ends the mode, and the award ladder */
    uint64_t sa_bits[SHOT_AWARD_MAX], sa_points[SHOT_AWARD_MAX];
    unsigned n_sa;
    uint64_t pen_bits[SHOT_AWARD_MAX], pen_points[SHOT_AWARD_MAX];   /* PAD-314: `shot_penalty` lines */
    unsigned n_pen;
    uint64_t end_shot_bits;
    unsigned award_fixed;           /* 0 = rising (the default: the Nth shot pays N x) */
    unsigned params_set;            /* one of the item 141 keys was in the file */
    /* item 147: starts_on / ends_on (their own functions below) */
    int start_on_event, start_event, end_on, end_event;
    unsigned start_event_count;
    char start_event_name[40], end_event_name[40];
    unsigned roster_slot_1;           /* item 146: `roster_slot <n>` + 1; 0 = no roster slot */
    unsigned roster_callout_1;        /* item 146: `roster_callout <id>` + 1; 0 = not given (the slot is silent) */
    unsigned display_priority;        /* item 154 display: `priority <n>`, 0 = none (the display as before) */
    /* item 167: `multiball <balls> [ball save s]` - the mode is a multiball of its own; `seconds 0` is then no
     * clock (it ends when one ball is left). `add_ball <mask> [times]`: a shot that adds a ball */
    unsigned mball_balls, mball_save_s, add_ball_max;
    uint64_t add_ball_bits;
    unsigned ball_save_s;             /* `ball_save <s>`: a ball save when it starts, no multiball; 0 = none */
    uint64_t mball_on_bits;           /* PAD-228 `multiball_on <mask>`: the balls come on that shot, not at the start */
    unsigned magnet_ms;               /* PAD-381 `magnet <ms> [mask]`: a grab on each hit of that shot; 0 = none */
    uint64_t magnet_bits;
    unsigned scoop_ms;                /* PAD-381 `scoop_hold <ms>`: a ball landing in the scoop is held; 0 = none */
    int shield;                       /* PAD-392 `shield toward`: the shield targets face the player while it runs */
    char show_start[40], show_end[40];   /* PAD-418 `show_start <name>` / `show_end <name>`: the game's own light
                                       * show (the port's `text show_name_<n>`) at its start / its end; "" = none */
    char wizard[40];                  /* PAD-436 `game_wizard light|start <name>`: when it starts, the game's own
                                       * mini-wizard (the port's `text wizard_name_<n>`) instead; "" = none */
    int wizard_start;                 /* ... started at once (1), or lit for the game's start shot (0) */
    char coil_name[4][16];            /* PAD-381 `coil_hold <name> <ms> [mask]`: a held coil of the port's */
    unsigned coil_ms[4];
    uint64_t coil_bits[4];            /* ... on each hit of these shots; 0 = once, when the mode starts */
    unsigned n_coil;
    /* PAD-414 `shake start|shot|end ...`: the cabinet's shaker, as it starts, on a shot, as it ends */
    unsigned char shake_when[4];      /* SHAKE_AT_* */
    unsigned shake_ms[4], shake_strength[4];
    char shake_name[4][24];           /* one of the game's own shakes; "" = shake_ms at shake_strength */
    uint64_t shake_bits[4];           /* SHAKE_AT_SHOT: on each hit of these shots */
    unsigned n_shake;
    /* PAD-227: more than one thing to meet before it starts (their own functions below) */
    uint64_t also_bits[ALSO_MAX];
    unsigned also_count[ALSO_MAX], n_also;
    char after_name[64];              /* `after ball|game <name>`: "" = no other mode first */
    int after_ball;                   /* 1 = this ball, 0 = this game */
    /* PAD-314: `starts_on sequence` - the `trigger_seq` shots made in that order, in one ball */
    int start_on_seq;
    uint64_t seq_bits[SEQ_MAX], seq_reset_bits;
    unsigned n_seq;
};

struct slot {
    unsigned index;
    char file[2][40];
    int said_which;
    struct mode_cfg c;
    char raw[CFG_MAX];
    long raw_len;
    unsigned trig[5];
    void *node, *text;
    unsigned hide_ticks;
    unsigned ended_begun;                 /* PAD-413: pm_begun() at its end, while its total shows */
    int aside;                            /* PAD-347: its screen is stepped aside for a game mode */
    char said[96];                        /* PAD-390: the screen's last words, written again on a fresh copy */
    unsigned ev_trig[5], ev_pending;      /* item 147: event start counts; a start waiting for pm_in_game */
    unsigned also[ALSO_MAX][5];           /* PAD-227: each trigger_also line's count, per player */
    int after_said;                       /* PAD-227: its `after` mode is missing, said once */
    unsigned seq_at[5], seq_done[5];      /* PAD-314: how far along the sequence each player is; it is complete */
};
static struct slot slots[MODES_MAX];
static unsigned poll_n = 1;         /* slots re-read each poll: up to one past the last file */
#define cfg (M->c)

static struct {
    int active;
    struct slot *slot;
    unsigned player, ticks_left, secs_shown, hits;
    uint64_t total, score_at_start;
    uint64_t lost;                    /* PAD-314: what the penalty shots took this run */
    unsigned long started_ms;
    unsigned restore_ticks;
    /* item 167: a multiball of the mode's own */
    int no_clock;                     /* `seconds 0`: the clock never runs it out */
    int mball_on, mball_seen2;        /* the game is serving; two or more balls were seen in play */
    int saving;                       /* `ball_save`: the game took the ball save at the start */
    int mball_last;                   /* the count last logged */
    unsigned mball_grace_ticks;       /* the ball save and the serving: one ball in play does not end it yet */
    unsigned mball_one_ticks;         /* ticks with one ball (or none) in play since */
    unsigned add_balls_left;
    int mball_wait;                   /* PAD-228: `multiball_on` - the balls are not served until its shot */
    unsigned long shield_due;         /* PAD-392: when the shield platform turns (0 = turned, or not asked) */
} run;

static int running(const struct slot *M) { return run.active && run.slot == M; }

/* ---- parsing: key per line, no allocator -------------------------------------------- */
static int is_space(int c) { return c == ' ' || c == '\t' || c == '\r'; }

static const char *key_is(const char *line, const char *word)
{
    while (*word) {
        if (*line != *word) return 0;
        line++;
        word++;
    }
    if (*line && !is_space(*line)) return 0;
    while (is_space(*line)) line++;
    return line;
}

static int hexval(int c)
{
    return (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10
         : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : -1;
}

static uint64_t num(const char **p)
{
    const char *s = *p;
    uint64_t x = 0;
    int base = 10;
    while (is_space(*s)) s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { base = 16; s += 2; }
    for (;;) {
        int d = hexval(*s);
        if (d < 0 || (base == 10 && d > 9)) break;
        x = x * (unsigned)base + (unsigned)d;
        s++;
    }
    while (is_space(*s)) s++;
    *p = s;
    return x;
}

static void rest_of_line(char *dst, unsigned cap, const char *src)
{
    unsigned n = 0;
    while (src[n] && src[n] != '\n' && n + 1 < cap) { dst[n] = src[n]; n++; }
    while (n && is_space(dst[n - 1])) n--;
    dst[n] = 0;
}

/* `stack yes|no` (item 140): may this mode start while the game's own battle or multiball is
 * active? `yes` (and no key at all) is how every mode behaved before the key existed. */
/* item 167: a multiball of the mode's own (MODE_SDK.md "A multiball of your own")
 *   multiball <balls> [ball save s]    when it starts the game serves balls until <balls> (2-6) are in
 *                                      play, with a ball save of that many seconds (10 when absent);
 *                                      the mode ends when one ball is left, and `seconds 0` is no clock
 *   add_ball <mask> [times]            a shot that puts one more ball in play, up to <times> (1) a run
 *   multiball_on <mask>                PAD-228: the balls are served on the first hit of that shot while
 *                                      the mode runs, not when it starts ("press the Action button now for
 *                                      a multiball"). Until then the mode's clock is the window: time up
 *                                      ends it with no multiball. Once served, the clock stops and one
 *                                      ball left ends it, as with `seconds 0` */
#define MBALL_GRACE_S    3           /* after the ball save: the serving, and a saved ball coming back */
#define MBALL_ONE_S      2           /* one ball in play this long, after the grace, ends the mode */
#define MBALL_SAVE_DEFAULT_S 10
static int multiball_line(struct slot *M, const char *line)
{
    const char *a;
    if ((a = key_is(line, "multiball")) != 0) {
        cfg.mball_balls = (unsigned)num(&a);
        cfg.mball_save_s = MBALL_SAVE_DEFAULT_S;
        while (is_space(*a)) a++;
        if (*a >= '0' && *a <= '9') cfg.mball_save_s = (unsigned)num(&a);
        if (cfg.mball_balls < 2) cfg.mball_balls = 2;
        if (cfg.mball_balls > 6) cfg.mball_balls = 6;
        if (cfg.mball_save_s > 120) cfg.mball_save_s = 120;
        return 1;
    }
    if ((a = key_is(line, "add_ball")) != 0) {
        cfg.add_ball_bits = num(&a);
        cfg.add_ball_max = 1;
        while (is_space(*a)) a++;
        if (*a >= '0' && *a <= '9') cfg.add_ball_max = (unsigned)num(&a);
        if (cfg.add_ball_max > 6) cfg.add_ball_max = 6;
        return 1;
    }
    if ((a = key_is(line, "multiball_on")) != 0) {
        cfg.mball_on_bits = num(&a);
        return 1;
    }
    return 0;
}

/* PAD-225: a ball save of the mode's own (MODE_SDK.md "A ball save of your own")
 *   ball_save <s>    no multiball: when it starts, a drained ball is served back for <s> seconds (1-120),
 *                    the game's own one-ball save (pm_ball_save); a `multiball` line's own ball save is
 *                    used instead when both are there. 0 = none. */
static int ball_save_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "ball_save");
    if (!a) return 0;
    cfg.ball_save_s = (unsigned)num(&a);
    if (cfg.ball_save_s > 120) cfg.ball_save_s = 120;
    return 1;
}

/* PAD-381: the playfield magnet (MODE_SDK.md "The magnet")
 *   magnet <ms> [mask]    while the mode runs, every hit of the shot the magnet sits at - the port's
 *                         `value magnet_shot` (Godzilla: the Godzilla target), or <mask> - holds the
 *                         ball on the magnet for <ms>, the hit that starts the mode included. The time
 *                         is only asked for: pm_magnet_grab clamps it to 100-5000 ms, picks the powers
 *                         from the operator's magnet settings and refuses inside its own limits (a
 *                         refused hit is logged and the mode carries on). 0 = none. */
static int magnet_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "magnet");
    if (!a) return 0;
    cfg.magnet_ms = (unsigned)num(&a);
    cfg.magnet_bits = (*a >= '0' && *a <= '9') ? num(&a) : (uint64_t)(unsigned long)pm_port_value("magnet_shot", 0);
    return 1;
}

/* PAD-381: the scoop (MODE_SDK.md "The scoop")
 *   scoop_hold <ms>       while the mode runs, a ball that settles in the scoop is held there <ms> more
 *                         (100-10000; pm_scoop_hold) once the game is done with it, then the game kicks it
 *                         out as it always does. 0 = none. */
static int scoop_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "scoop_hold");
    if (!a) return 0;
    cfg.scoop_ms = (unsigned)num(&a);
    return 1;
}

/* PAD-392: the shield platform (MODE_SDK.md "The shield platform")
 *   shield toward       while the mode runs, the shield targets face the player: the platform turns SHIELD_DELAY_MS
 *                       after it starts (the ball that started it clear of the platform first, as the examples'
 *                       kit does) and the runtime keeps it there (pm_shield_keep, with all of its limits), then
 *                       turns it back when the mode ends. Kept only while the game's own shield feature sees no
 *                       shots: `game_modes block` (the default) without it in `keep_rules`. */
#define SHIELD_DELAY_MS 1500
static int shield_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "shield");
    if (!a) return 0;
    if (key_is(a, "toward")) cfg.shield = PM_SHIELD_TOWARD;
    else pm_log("shield takes toward - \"%.40s\" ignored", a);
    return 1;
}

/* PAD-381: held coils (MODE_SDK.md "Held coils")
 *   coil_hold <name> <ms> [mask]   the port's held coil <name> (magnet, mg_magnet, bridge on a Godzilla
 *                                  Premium) held <ms> through pm_coil_hold, with all of its limits: on every
 *                                  hit of <mask> while the mode runs (the starting hit included), or once when
 *                                  the mode starts when there is no mask. Up to 4 lines. */
static int coil_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "coil_hold");
    unsigned k = 0, n;
    if (!a) return 0;
    if (cfg.n_coil >= 4) return 1;
    n = cfg.n_coil;
    while (*a && !is_space(*a) && k + 1 < sizeof cfg.coil_name[n]) cfg.coil_name[n][k++] = *a++;
    cfg.coil_name[n][k] = 0;
    while (*a && !is_space(*a)) a++;
    cfg.coil_ms[n] = (unsigned)num(&a);
    cfg.coil_bits[n] = (*a >= '0' && *a <= '9') ? num(&a) : 0;
    if (k && cfg.coil_ms[n]) cfg.n_coil++;
    return 1;
}

static void coils_at(struct slot *M, uint64_t mask)   /* mask 0: the mode's start */
{
    unsigned i;
    for (i = 0; i < cfg.n_coil; i++) {
        if (mask ? !(mask & cfg.coil_bits[i]) : cfg.coil_bits[i] != 0) continue;
        pm_log("%s: %s %u ms %s - %s", cfg.name, cfg.coil_name[i], cfg.coil_ms[i], mask ? "on its shot" : "as it starts",
               pm_coil_hold(cfg.coil_name[i], cfg.coil_ms[i]) ? "holding" : "no hold (the runtime's line says why)");
    }
}

#define SHAKE_AT_START 0
#define SHAKE_AT_SHOT  1
#define SHAKE_AT_END   2
static int shakes_at(struct slot *M, unsigned when, uint64_t mask);   /* PAD-414: the shaker, below */

/* A shot of the running mode's: the magnet, when it is the magnet's shot */
static void magnet_shot(struct slot *M, uint64_t mask)
{
    coils_at(M, mask);                       /* PAD-381: the held coils on their shots, too */
    shakes_at(M, SHAKE_AT_SHOT, mask);       /* PAD-414: the shaker on its shots */
    if (!cfg.magnet_ms || !(mask & cfg.magnet_bits)) return;
    pm_log("%s: magnet shot %08x_%08x - %s", cfg.name, (unsigned)(mask >> 32), (unsigned)mask,
           pm_magnet_grab(cfg.magnet_ms) ? "holding the ball" : "no grab (the runtime's line says why)");
}

/* PAD-414: the shaker (MODE_SDK.md "The shaker"; PAD-474: every latest title with one)
 *   shake start <ms> <strength>        as the mode starts: the cabinet shakes <ms> at <strength> (0 hardest .. 3
 *   shake start game <name>            softest), or plays the game's own shake <name> (Godzilla's hit, jackpot...,
 *   shake shot <ms> <strength> <mask>  another's tap, short...: the port's `text shake_<name>`); `shot` on every
 *   shake shot game <name> <mask>      hit of <mask> while it runs (the starting hit included); `end` as it ends,
 *   shake end <ms> <strength>          left to run out after the end (pm_shake_outlast). Every limit is
 *   shake end game <name>              pm_shake's: the operator's setting, its length per strength, 20 shakes and
 *                                      15 s a minute. Up to 4 lines. */
static int shake_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "shake"), *b;
    unsigned n = cfg.n_shake, k = 0;
    if (!a) return 0;
    if (n >= 4) return 1;
    if ((b = key_is(a, "start"))) cfg.shake_when[n] = SHAKE_AT_START;
    else if ((b = key_is(a, "shot"))) cfg.shake_when[n] = SHAKE_AT_SHOT;
    else if ((b = key_is(a, "end"))) cfg.shake_when[n] = SHAKE_AT_END;
    else {
        pm_log("shake takes start, shot or end - \"%.40s\" ignored", a);
        return 1;
    }
    cfg.shake_name[n][0] = 0;
    cfg.shake_ms[n] = cfg.shake_strength[n] = 0;
    if ((a = key_is(b, "game"))) {
        while (*a && !is_space(*a) && k + 1 < sizeof cfg.shake_name[n]) cfg.shake_name[n][k++] = *a++;
        cfg.shake_name[n][k] = 0;
        while (*a && !is_space(*a)) a++;
        while (is_space(*a)) a++;
    } else {
        a = b;
        cfg.shake_ms[n] = (unsigned)num(&a);
        cfg.shake_strength[n] = (unsigned)num(&a);
    }
    cfg.shake_bits[n] = (*a >= '0' && *a <= '9') ? num(&a) : 0;
    if (!k && !cfg.shake_ms[n]) {
        pm_log("shake needs a time or `game <name>` - \"%.60s\" ignored", line);
        return 1;
    }
    if (cfg.shake_when[n] == SHAKE_AT_SHOT && !cfg.shake_bits[n]) {
        pm_log("shake shot needs a shot mask - \"%.60s\" ignored", line);
        return 1;
    }
    cfg.n_shake++;
    return 1;
}

/* The shakes of `when` (SHAKE_AT_SHOT: those whose mask the hit has); 1 = one of them shook */
static int shakes_at(struct slot *M, unsigned when, uint64_t mask)
{
    unsigned i;
    int r, any = 0;
    for (i = 0; i < cfg.n_shake; i++) {
        if (cfg.shake_when[i] != when || (when == SHAKE_AT_SHOT && !(mask & cfg.shake_bits[i]))) continue;
        r = cfg.shake_name[i][0] ? pm_shake_game(cfg.shake_name[i]) : pm_shake(cfg.shake_ms[i], cfg.shake_strength[i]);
        if (cfg.shake_name[i][0])
            pm_log("%s: the game's %s shake %s - %s", cfg.name, cfg.shake_name[i],
                   when == SHAKE_AT_START ? "as it starts" : when == SHAKE_AT_SHOT ? "on its shot" : "as it ends",
                   r ? "shaking" : "no shake (the runtime's line says why)");
        else
            pm_log("%s: shake %u ms at %u %s - %s", cfg.name, cfg.shake_ms[i], cfg.shake_strength[i],
                   when == SHAKE_AT_START ? "as it starts" : when == SHAKE_AT_SHOT ? "on its shot" : "as it ends",
                   r ? "shaking" : "no shake (the runtime's line says why)");
        if (r) { any = 1; break; }           /* one at a time: the runtime refuses the next while it runs */
    }
    return any;
}

static int stack_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "stack");
    if (!a) return 0;
    if (a[0] == 'n' || a[0] == 'N' || a[0] == '0') cfg.stack_no = 1;
    else if (a[0] == 'y' || a[0] == 'Y' || a[0] == '1') cfg.stack_no = 0;
    else pm_log("stack needs yes or no - \"%.40s\" read as yes", a);
    return 1;
}

/* PAD-363: `game_modes stack` (it runs beside the game's modes, its screen stepping aside), `game_modes
 * give_way` (it starts only while none of the game's modes runs, the trigger count kept, and one of them
 * beginning ends it) or `game_modes block` (as give_way, and while it runs the game's modes in `block_modes <id>
 * ...` - or every one the port names - cannot start: pm_block_game_modes, and every rule of the game's the port
 * names sees no shot but the ones in `keep_rules <n> ...`: pm_block_rules_keep). PAD-398 (David, 2026-10-05:
 * "when our custom modes start, we should ONLY be in those modes unless explicitly noted"): `block` is the
 * default, for a file with no game_modes line. */
#define GM_STACK    0
#define GM_GIVE_WAY 1
#define GM_BLOCK    2
/* 1 when the line's value is exactly `w` (any case), followed by nothing but spaces or a comment */
static int value_is(const char *a, const char *w)
{
    for (; *w; a++, w++)
        if ((*a | 0x20) != (*w | 0x20)) return 0;
    while (*a == ' ' || *a == '\t') a++;
    return !*a || *a == '#';
}

static int game_modes_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "game_modes");
    if (!a) return 0;
    if (value_is(a, "block")) cfg.game_modes = GM_BLOCK;
    else if (value_is(a, "give_way")) cfg.game_modes = GM_GIVE_WAY;
    else if (value_is(a, "stack")) cfg.game_modes = GM_STACK;
    else {
        cfg.game_modes = GM_BLOCK;           /* PAD-398: what a file that says nothing does */
        pm_log("game_modes needs stack, give_way or block - \"%.40s\" read as block", a);
    }
    return 1;
}

static int keep_rules_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "keep_rules");
    unsigned v;
    if (!a) return 0;
    cfg.keep_n = 0;
    while (*a) {
        while (*a == ' ' || *a == '\t' || *a == ',') a++;
        if (!*a || *a == '#') break;
        if (*a < '0' || *a > '9') { pm_log("keep_rules takes the port's rule numbers, 0-31 - \"%.40s\" ignored", a); break; }
        for (v = 0; *a >= '0' && *a <= '9' && v < 100000; a++) v = v * 10 + (unsigned)(*a - '0');
        if (v > 31) pm_log("keep_rules: %u is not a rule number the runtime knows (0-31)", v);
        else if (cfg.keep_n < 32) cfg.keep_rules[cfg.keep_n++] = (unsigned char)v;
    }
    return 1;
}

static int block_modes_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "block_modes");
    unsigned v;
    if (!a) return 0;
    cfg.block_n = 0;
    while (*a) {
        while (*a == ' ' || *a == '\t' || *a == ',') a++;
        if (!*a) break;
        if (*a < '0' || *a > '9') { pm_log("block_modes takes the game's mode ids, 0-127 - \"%.40s\" ignored", a); break; }
        for (v = 0; *a >= '0' && *a <= '9' && v < 100000; a++) v = v * 10 + (unsigned)(*a - '0');
        if (v > 127) pm_log("block_modes: %u is not a mode id the runtime can hold off (0-127)", v);
        else if (cfg.block_n < BLOCK_LIST_MAX) cfg.block_ids[cfg.block_n++] = (unsigned char)v;
    }
    return 1;
}

/* PAD-347: `aside hide` (the default) / `aside keep` - while one of the game's own modes runs, the middle
 * of the screen is the game's (pm_aside) and the mode's screen is hidden, back when the game's mode ends;
 * `keep` leaves it up (a screen laid out clear of the game's words). */
static int aside_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "aside");
    if (!a) return 0;
    if (a[0] == 'k' || a[0] == 'K') cfg.aside_keep = 1;
    else if (a[0] == 'h' || a[0] == 'H') cfg.aside_keep = 0;
    else pm_log("aside needs keep or hide - \"%.40s\" read as hide", a);
    return 1;
}

/* item 146: `roster_slot <n>` - the mode takes the place of roster slot n's battle (Godzilla's
 * BATTLE SELECTION screen, slots 0-6). Parsed here; claimed in roster_sync() after a (re)load. */
static int roster_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "roster_slot");
    uint64_t n;
    if (!a && (a = key_is(line, "roster_callout")) != 0) {
        /* `roster_callout <id>`: the sound request the selection screen plays when the cursor lands on the
         * slot (0 = silent, which a claimed slot is without this line) - never the old monster's name */
        n = (a[0] >= '0' && a[0] <= '9') ? num(&a) : 0x10000;
        if (n > 0xffff) {
            pm_log("roster_callout needs a sound request id 0-65535 - \"%.40s\" ignored (the slot stays silent)", key_is(line, "roster_callout"));
            cfg.roster_callout_1 = 0;
        } else {
            cfg.roster_callout_1 = (unsigned)n + 1;
        }
        return 1;
    }
    if (!a) return 0;
    if (a[0] < '0' || a[0] > '9') {                  /* `-1`, a word: num() would read 0 and claim slot 0 */
        pm_log("roster_slot needs a slot number 0-6 - \"%.40s\" ignored", a);
        cfg.roster_slot_1 = 0;
        return 1;
    }
    n = num(&a);
    if (n > 15) {                                    /* never truncated into range (3000000000 + 1 ...) */
        pm_log("roster_slot %llu is not a slot number 0-6 - ignored", (unsigned long long)n);
        cfg.roster_slot_1 = 0;
        return 1;
    }
    cfg.roster_slot_1 = (unsigned)n + 1;
    return 1;
}
static void roster_sync(struct slot *M);
static void roster_ended(void);

/* item 154 display: `priority <n>` (1-255, the game's display-effect scale; MODE_SDK.md "Display
 * priority"): while the mode runs, the game's displays that do not beat n wait, so its clip plays
 * through and its screen stays readable. No line, or 0: the display as before the key existed. */
static int display_line(struct slot *M, const char *line)
{
    const char *a = key_is(line, "priority");
    uint64_t n;
    if (!a) return 0;
    if (a[0] < '0' || a[0] > '9') {
        pm_log("priority needs a number 0-255 - \"%.40s\" ignored (no display priority)", a);
        cfg.display_priority = 0;
        return 1;
    }
    n = num(&a);
    if (n > 255) {
        pm_log("priority %llu is above 255 - 255 is used", (unsigned long long)n);
        n = 255;
    }
    cfg.display_priority = (unsigned)n;
    return 1;
}

static void display_start(struct slot *M)
{
    if (!cfg.display_priority) return;
    if (!pm_display_priority(cfg.display_priority))
        pm_log("%s: priority %u not held - this game's port has no display arbitration", cfg.name, cfg.display_priority);
}

#define TEXT(k, f)  if ((a = key_is(line, k)) != 0) { rest_of_line(cfg.f, sizeof cfg.f, a); return; }
#define NUM(k, f)    if ((a = key_is(line, k)) != 0) { cfg.f = (unsigned)num(&a); return; }
#define NUM64(k, f)  if ((a = key_is(line, k)) != 0) { cfg.f = num(&a); return; }

/* ---- a mode's own sounds (item 150) ---------------------------------------------------
 *   sound_start <request> [ms]          played when the mode starts
 *   sound_shot  <request> [every] [ms]  played on every scored shot, or every Nth one
 *   sound_end   <request> [ms]          played when time runs out, INSTEAD of callout_end
 *   music       <request> [sid]         started with the mode, started again whenever no
 *                                       channel plays it (so it loops), faded out at every end;
 *                                       with a sid, the mode's OWN bed (item 150 follow-up): the
 *                                       request is pointed at that sound id while the mode runs
 * Each is a request whose record the build re-pointed at a sound of the mode's own. They
 * are called with pm_sound (no city variant), so a port without sound_play plays nothing,
 * and an older mode.so logs these keys as unknown and plays the stock callouts.
 * [ms] is the call's OWN length. An appended record is never shorter than the carrier's stock
 * one, so a shorter sound is followed by silence that would hold the voice bus (and drop the
 * next call); the carrier is stopped once [ms] (+1/8 +120 ms of slack) has passed. An older
 * mode.so reads only the request and lets the record play out, and reads `music <request>`
 * only (it plays the carrier's own record).
 *   swap <request> <stock key> <our key>    (item 163; keys 16 hex digits) the build appended the
 * sound as a record NO descriptor names: while it plays on <request>, every lookup of the
 * carrier's own record key takes ours (pm_sound_swap), so no stock sound id changes at all. A call
 * swaps for that play only; the music for as long as the mode runs. A swap that cannot be armed
 * (no sound_lookup site) is not played.
 *
 * Item 150 follow-up, NO CLICKS (David's run of the film pack, 2026-09-18): nothing of ours is
 * ever cut while it sounds, and nothing of the game's is cut by ours - every such cut was a
 * click in the capture. So: a call never takes the voice bus from a sound of equal priority
 * (steal flag cleared) and a shot call whose previous call is still sounding is skipped; a call
 * that would cut the game's lower-priority speech fades it first (60 ms) and plays 70 ms later,
 * one held off by the game's equal or higher priority speech waits (up to 1.5 s for a start or
 * end call, 0.8 s for a shot call); the game's music is faded out (250 ms) before the mode's
 * music starts, any music of the game's that gets under it is faded out too (the mode's music
 * is the only music), and at the end the mode's music is FADED (400 ms) and the game's music
 * that was playing at the start is started again - so the end is never followed by silence. */
struct own_sounds {
    unsigned start, shot, shot_every, end, music, music_restarts, start_ms, shot_ms, end_ms;
    unsigned music_sid;                 /* item 150 follow-up: the mode's own bed, 0 = none */
    struct { unsigned request; unsigned char keys[16]; } swap[4];   /* item 163: stock, ours */
    unsigned n_swap;
    unsigned long shot_until;           /* the previous shot call still sounds until then */
};

#define OWN_STOPS_MAX 8
static struct { unsigned request; unsigned long due; } own_stops[OWN_STOPS_MAX];

/* stop <request> once its own <ms> have played; a new play of the same request moves the time */
static void own_sounds_stop_after(unsigned request, unsigned ms)
{
    unsigned long due;
    int i, free_i = -1;
    if (!request || !ms) return;
    due = pm_ms() + ms + ms / 8 + 120;
    for (i = 0; i < OWN_STOPS_MAX; i++) {
        if (own_stops[i].request == request) { own_stops[i].due = due; return; }
        if (!own_stops[i].request && free_i < 0) free_i = i;
    }
    if (free_i >= 0) { own_stops[free_i].request = request; own_stops[free_i].due = due; }
}

/* ---- calls wait for a clean voice bus (item 150 follow-up) ----------------------------- */
#define BUS_MUSIC 0x01u                 /* the channel bus bits measured on Godzilla (item 150) */
#define BUS_VOICE 0x02u
#define OWN_CALLS_MAX 6
static struct { unsigned request, prio, ms; const unsigned char *swap; unsigned long due, deadline; const char *what; } own_calls[OWN_CALLS_MAX];

static int request_prio(unsigned request)
{
    int pair = pm_sound_priority(request, -1, -1);
    return pair < 0 ? -1 : pair >> 8;
}

/* 1 = played now; 0 = not yet (a lower-priority sound of the game's is being faded, or the bus
 * is held by one ours cannot take); -1 = never (its own record cannot be swapped in) */
static int own_call_try(unsigned request, const unsigned char *swap, unsigned prio, unsigned ms, const char *what)
{
    unsigned reqs[8], buses[8];
    int n = pm_sound_playing(reqs, buses, 8), i, faded = 0;
    for (i = 0; i < n && i < 8; i++) {
        int p;
        if (!(buses[i] & BUS_VOICE) || reqs[i] == request) continue;
        p = request_prio(reqs[i]);
        if (p < 0 || p >= (int)prio) return 0;   /* ours would not take it (or unknown): wait */
        pm_sound_fade(reqs[i], 60);
        pm_log("own sound: %s %u waits 70 ms - %u (priority %d) on the voice bus is faded out first",
               what, request, reqs[i], p);
        faded = 1;
    }
    if (faded) return 0;
    if (swap && !pm_sound_swap(request, swap, swap + 8, (int)prio, ms)) {
        pm_log("own sound: %s %u NOT played - its own record could not be swapped in (no sound_lookup site)",
               what, request);
        return -1;
    }
    return pm_sound(request);
}

static void own_call(unsigned request, const unsigned char *swap, unsigned ms, unsigned prio,
                     unsigned long wait_ms, const char *what)
{
    int i, free_i = -1, got;
    if (!request) return;
    got = own_call_try(request, swap, prio, ms, what);
    if (got < 0) return;
    if (got) {
        if (swap) pm_log("own sound: %s %u played (its own record, swapped in)", what, request);
        else pm_log("own sound: %s %u played", what, request);
        own_sounds_stop_after(request, ms);
        return;
    }
    for (i = 0; i < OWN_CALLS_MAX; i++) {
        if (own_calls[i].request == request) { free_i = i; break; }
        if (!own_calls[i].request && free_i < 0) free_i = i;
    }
    if (free_i < 0) {
        pm_log("own sound: %s %u NOT played (too many calls waiting)", what, request);
        return;
    }
    own_calls[free_i].request = request;
    own_calls[free_i].swap = swap;
    own_calls[free_i].prio = prio;
    own_calls[free_i].ms = ms;
    own_calls[free_i].what = what;
    own_calls[free_i].due = pm_ms() + 70;
    own_calls[free_i].deadline = pm_ms() + wait_ms;
}

static void own_calls_tick(void)
{
    unsigned long now = pm_ms();
    int i, got;
    for (i = 0; i < OWN_CALLS_MAX; i++) {
        if (!own_calls[i].request || now < own_calls[i].due) continue;
        got = own_call_try(own_calls[i].request, own_calls[i].swap, own_calls[i].prio, own_calls[i].ms,
                           own_calls[i].what);
        if (got > 0) {
            pm_log("own sound: %s %u played (after waiting for the voice bus)", own_calls[i].what, own_calls[i].request);
            own_sounds_stop_after(own_calls[i].request, own_calls[i].ms);
            own_calls[i].request = 0;
        } else if (got < 0) {
            own_calls[i].request = 0;
        } else if (now >= own_calls[i].deadline) {
            pm_log("own sound: %s %u NOT played - the game's own speech held the voice bus", own_calls[i].what,
                   own_calls[i].request);
            own_calls[i].request = 0;
        } else {
            own_calls[i].due = now + 70;
        }
    }
}

/* ---- the music: the mode's own, the only one, and the game's back after it -------------- */
#define MUSIC_FADE_IN_WAIT_MS 260       /* the game's music fades 250 ms before ours starts */
#define MUSIC_FADE_OUT_MS     400
static struct {
    unsigned request, sid;              /* ours, while it runs */
    const unsigned char *swap;          /* item 163: its stock and our key, 0 = none */
    unsigned long start_due;            /* ours starts then (after the game's has faded); 0 = started */
    unsigned game;                      /* the game's music playing at the start, played again at the end */
    unsigned after_request, after_game; /* after an end: once ours has faded, */
    unsigned long after_due;            /*   put the carrier's list back and the game's music on */
    unsigned silenced[4];               /* the game's music requests faded under ours (logged once) */
} music;

static void own_music_after_tick(void)
{
    if (!music.after_request || pm_ms() < music.after_due) return;
    if (pm_sound_active(music.after_request)) { music.after_due = pm_ms() + 50; return; }
    pm_sound_sid(music.after_request, 0);
    if (music.after_game && pm_in_game()) {
        pm_log("own sound: music %u faded out; the game's music %u %s", music.after_request, music.after_game,
               pm_sound(music.after_game) ? "is playing again" : "could NOT be started again");
    } else {
        pm_log("own sound: music %u faded out%s", music.after_request,
               music.after_game ? " (no game in play, the game's music is left to the game)" : "");
    }
    music.after_request = music.after_game = 0;
}

/* every tick, mode running or not (an end call outlives its mode) */
static void own_sounds_stops_tick(void)
{
    unsigned long now = pm_ms();
    int i;
    for (i = 0; i < OWN_STOPS_MAX; i++) {
        if (!own_stops[i].request || now < own_stops[i].due) continue;
        /* faded (40 ms) to silence, not cut: a voice's end is never heard (item 150 follow-up) */
        if (pm_sound_fade(own_stops[i].request, 40))
            pm_log("own sound: call %u stopped - its own sound is over, the rest of the record is silence", own_stops[i].request);
        own_stops[i].request = 0;
    }
    own_calls_tick();
    own_music_after_tick();
}
static struct own_sounds own_sounds[MODES_MAX];

static int own_sounds_key(struct slot *M, const char *line)
{
    struct own_sounds *S = &own_sounds[M->index];
    const char *a;
    if ((a = key_is(line, "sound_start")) != 0) { S->start = (unsigned)num(&a); S->start_ms = (unsigned)num(&a); return 1; }
    if ((a = key_is(line, "sound_shot")) != 0) {
        S->shot = (unsigned)num(&a);
        S->shot_every = (unsigned)num(&a);
        S->shot_ms = (unsigned)num(&a);
        return 1;
    }
    if ((a = key_is(line, "sound_end")) != 0) { S->end = (unsigned)num(&a); S->end_ms = (unsigned)num(&a); return 1; }
    if ((a = key_is(line, "music")) != 0) { S->music = (unsigned)num(&a); S->music_sid = (unsigned)num(&a); return 1; }
    if ((a = key_is(line, "swap")) != 0) {
        unsigned r = (unsigned)num(&a), n = 0;
        unsigned char k[16];
        while (n < 16) {
            int hi, lo;
            while (is_space(*a)) a++;
            hi = hexval(a[0]);
            lo = hi < 0 ? -1 : hexval(a[1]);
            if (hi < 0 || lo < 0) break;
            k[n++] = (unsigned char)((hi << 4) | lo);
            a += 2;
        }
        if (!r || n != 16 || S->n_swap >= 4) {
            pm_log("swap needs <request> <stock key> <our key>, 16 hex digits each - ignored");
        } else {
            S->swap[S->n_swap].request = r;
            for (n = 0; n < 16; n++) S->swap[S->n_swap].keys[n] = k[n];
            S->n_swap++;
        }
        return 1;
    }
    return 0;
}

/* item 163: the stock and our key for <request> in this mode, or 0 */
static const unsigned char *own_swap_of(struct own_sounds *S, unsigned request)
{
    unsigned i;
    for (i = 0; request && i < S->n_swap; i++)
        if (S->swap[i].request == request) return S->swap[i].keys;
    return 0;
}

static void own_sounds_clear(struct slot *M)
{
    struct own_sounds *S = &own_sounds[M->index];
    S->start = S->shot = S->shot_every = S->end = S->music = S->music_restarts = 0;
    S->start_ms = S->shot_ms = S->end_ms = 0;
    S->music_sid = 0;
    S->n_swap = 0;
    S->shot_until = 0;
}

/* Each sound bus (music, voice, each effect bus) plays one sound at a time, and a request
 * takes a bus only from a lower priority, or an equal one whose steal flag is set
 * (pm_sound_priority; measured 2026-09-17, MODE_API.md "Sound BUSES and priority"). The
 * game asks for its music again as soon as another takes the bus, so with the stock flag it
 * took the music bus back from ours 11 times in a 25 s mode; and a call at the carriers'
 * stock priority 2 is not played while any other speech plays. So before playing: the music
 * keeps its priority and loses the steal flag (the game's own music cannot take the bus back),
 * and the calls go to priority 3 (shot) and 4 (start, end), also WITHOUT the steal flag (item
 * 150 follow-up: with it, the game's equal-priority speech and the mode's own next call cut a
 * call mid-sound, a click each time). Only a handful of the game's requests sit at 4 or above.
 * Carriers are requests the game never plays, so this changes nothing the game plays itself.
 * A call swapped in (item 163) takes its priority for each play only (pm_sound_swap).
 * A port without the request table leaves every carrier as it is. */
static const unsigned own_prio[3] = { 4, 3, 4 };      /* start, shot, end */

static void own_sounds_priorities(struct own_sounds *S)
{
    unsigned calls[3];
    int i, old;
    calls[0] = S->start; calls[1] = S->shot; calls[2] = S->end;
    for (i = 0; i < 3; i++) {
        if (!calls[i] || (i == 1 && calls[1] == calls[0]) || (i == 2 && (calls[2] == calls[0] || calls[2] == calls[1])))
            continue;
        if (own_swap_of(S, calls[i])) continue;   /* item 163: a swap's carrier takes it per play only */
        old = pm_sound_priority(calls[i], (int)own_prio[i], 0);
        if (old < 0)
            pm_log("own sound: call %u keeps its priority (no request table in the port)", calls[i]);
        else if (old != (int)(own_prio[i] << 8))
            pm_log("own sound: call %u takes the voice bus at priority %u (was %d, flags %d)", calls[i], own_prio[i], old >> 8, old & 0xff);
    }
    if (S->music) {
        old = pm_sound_priority(S->music, -1, 0);
        if (old < 0)
            pm_log("own sound: music %u keeps its steal flag (no request table in the port)", S->music);
        else if (old & 1)
            pm_log("own sound: music %u holds its bus (priority %d, steal flag cleared)", S->music, old >> 8);
    }
}

static void own_music_start_now(void)
{
    music.start_due = 0;
    if (music.swap && !pm_sound_swap(music.request, music.swap, music.swap + 8, -1, 0)) {
        pm_log("own sound: music %u NOT started - its own record could not be swapped in (no sound_lookup site)",
               music.request);
        return;
    }
    pm_log("own sound: music %u%s %s", music.request, music.sid ? " (its own bed)" : "",
           pm_sound(music.request) ? "started" : "NOT started (no sound_play in the port)");
}

static void own_sounds_start(struct slot *M)
{
    struct own_sounds *S = &own_sounds[M->index];
    unsigned reqs[8], buses[8], carry;
    int n, i;
    S->music_restarts = 0;
    S->shot_until = 0;
    own_sounds_priorities(S);
    if (S->start) own_call(S->start, own_swap_of(S, S->start), S->start_ms, own_prio[0], 1500, "start call");
    if (!S->music) return;
    carry = music.after_game;           /* the last mode's music still fading: the game's music */
    music.after_request = music.after_game = 0;         /* a new start: nothing to put back yet */
    music.request = S->music;
    music.sid = S->music_sid;
    music.swap = own_swap_of(S, S->music);
    music.game = 0;
    for (i = 0; i < 4; i++) music.silenced[i] = 0;
    if (S->music_sid)
        pm_log("own sound: music %u plays its own bed, sound id %u%s", S->music, S->music_sid,
               pm_sound_sid(S->music, S->music_sid) ? "" : " - NOT pointed (no request table in the port), the carrier's own record plays");
    n = pm_sound_playing(reqs, buses, 8);
    for (i = 0; i < n && i < 8; i++)
        if ((buses[i] & BUS_MUSIC) && reqs[i] != S->music) {
            music.game = reqs[i];
            break;
        }
    if (music.game) {
        pm_sound_fade(music.game, 250);
        music.start_due = pm_ms() + MUSIC_FADE_IN_WAIT_MS;
        pm_log("own sound: the game's music %u fades out (250 ms) before music %u starts", music.game, S->music);
    } else {
        music.game = carry;
        own_music_start_now();
    }
}

static void own_sounds_shot(struct slot *M, unsigned hits)
{
    struct own_sounds *S = &own_sounds[M->index];
    unsigned every = S->shot_every ? S->shot_every : 1;
    if (!S->shot || hits % every != 0) return;
    if (S->shot_ms && pm_ms() < S->shot_until) {
        pm_log("own sound: shot call %u (shot %u) skipped - its previous call still sounds", S->shot, hits);
        return;
    }
    S->shot_until = pm_ms() + S->shot_ms;
    own_call(S->shot, own_swap_of(S, S->shot), S->shot_ms, own_prio[1], 800, "shot call");
}

/* 1 if the mode has its own end call (callout_end is then not played) */
static int own_sounds_time_up(struct slot *M)
{
    struct own_sounds *S = &own_sounds[M->index];
    if (!S->end) return 0;
    if (S->shot && S->shot != S->end && pm_sound_active(S->shot)) pm_sound_fade(S->shot, 60);
    own_call(S->end, own_swap_of(S, S->end), S->end_ms, own_prio[2], 1500, "end call");
    return 1;
}

/* PAD-306: one of the mode's own calls - its countdown, its time-up call, a callout_at. On
 * Metallica Remastered they are in the game's music class (priority 1), and the music rule
 * below faded the mode's own countdown out under its own music. */
static int mode_call(struct slot *M, unsigned request)
{
    unsigned i;
    if (!request) return 0;
    if (request == cfg.callout_count || request == cfg.callout_end) return 1;
    for (i = 0; i < cfg.n_at; i++)
        if (request == cfg.at_id[i]) return 1;
    return 0;
}

static void own_sounds_tick(struct slot *M, unsigned ticks)
{
    struct own_sounds *S = &own_sounds[M->index];
    unsigned reqs[8], buses[8];
    int n, i, k;
    if (!S->music) return;
    if (music.start_due) {
        if (pm_ms() >= music.start_due) own_music_start_now();
        return;
    }
    if (ticks % POLL_TICKS != 0) return;
    if (music.swap) pm_sound_swap(S->music, music.swap, music.swap + 8, -1, 0);   /* held while the mode runs */
    /* the mode's music is the only music: any request of the game's music class (priority 1)
     * playing on any channel under it is faded out - but never the mode's own calls */
    n = pm_sound_playing(reqs, buses, 8);
    for (i = 0; i < n && i < 8; i++) {
        if (reqs[i] == S->music || mode_call(M, reqs[i]) || request_prio(reqs[i]) != 1) continue;
        pm_sound_fade(reqs[i], 250);
        for (k = 0; k < 4 && music.silenced[k] && music.silenced[k] != reqs[i]; k++) ;
        if (k < 4 && !music.silenced[k]) {
            music.silenced[k] = reqs[i];
            pm_log("own sound: the game's music %u (bus %02x) faded out under music %u", reqs[i], buses[i], S->music);
        }
    }
    if (pm_sound_active(S->music)) return;
    if (pm_sound(S->music) && (++S->music_restarts <= 3 || S->music_restarts % 20 == 0))
        pm_log("own sound: music %u had stopped - started again (%u)", S->music, S->music_restarts);
}

static void own_sounds_end(struct slot *M)
{
    struct own_sounds *S = &own_sounds[M->index];
    int playing;
    if (!S->music) return;
    if (music.start_due) {                       /* ended before ours even started */
        music.start_due = 0;
        playing = 0;
    } else {
        playing = pm_sound_fade(S->music, MUSIC_FADE_OUT_MS);
    }
    pm_log("own sound: music %u fades out at the end (%s, %u restart(s))", S->music,
           playing ? "was playing" : "was not playing", S->music_restarts);
    music.after_request = S->music;
    music.after_game = music.game;
    music.after_due = pm_ms() + MUSIC_FADE_OUT_MS + 20;
    if (music.swap)                              /* item 163: the swap lasts out the fade only */
        pm_sound_swap(S->music, music.swap, music.swap + 8, -1, MUSIC_FADE_OUT_MS);
    music.swap = 0;
    music.request = 0;
}

/* ---- how often a mode can start (item 139) ---------------------------------------------
 *   starts   once_per_game | once_per_ball | unlimited | N     (N = up to N times a game)
 *   cooldown <seconds>                                         (after it ends; 0 = none)
 * Kept PER PLAYER, per slot. A start is counted when the mode STARTS; a ball's counts are
 * cleared at every end of ball; a game's counts and the cooldowns are cleared when a new
 * game begins (starts_watch_game says what marks one). The cooldown is wall-clock time
 * from the mode's END, so it runs through an end of ball. A trigger shot hit while the
 * mode is refused still counts toward its trigger, as it does while another mode runs.
 * A trigger FILE (/dump/modeK.start) is a test path: it starts the mode whatever these
 * say, and that run is neither counted nor starts a cooldown.
 * An older mode.so logs `unknown key, skipped` for both keys and starts as often as ever. */
#define STARTS_PLAYERS 5            /* players 1..4 */
static struct {
    unsigned game[STARTS_PLAYERS], ball[STARTS_PLAYERS], ended[STARTS_PLAYERS];
    unsigned long ended_ms[STARTS_PLAYERS];
} starts_n[MODES_MAX];
static int starts_uncounted;        /* the running mode was started by a trigger file */

static int starts_policy(const struct slot *M)
{
    return cfg.starts_game || cfg.starts_ball || cfg.cooldown_s;
}

static int starts_is_file(const char *why)
{
    const char *w = "trigger file";
    while (*w && *why == *w) { w++; why++; }
    return *w == 0 && *why == 0;
}

/* a `starts` or `cooldown` line: 1 = it was one */
static int starts_line(struct slot *M, const char *line)
{
    const char *a;
    if ((a = key_is(line, "starts")) != 0) {
        cfg.starts_game = cfg.starts_ball = 0;
        if (key_is(a, "once_per_game")) cfg.starts_game = 1;
        else if (key_is(a, "once_per_ball")) cfg.starts_ball = 1;
        else if (*a >= '1' && *a <= '9') cfg.starts_game = (unsigned)num(&a);
        else if (!key_is(a, "unlimited"))
            pm_log("starts \"%.40s\" is not once_per_game, once_per_ball, unlimited or a number - unlimited", a);
        return 1;
    }
    if ((a = key_is(line, "cooldown")) != 0) {
        cfg.cooldown_s = (unsigned)num(&a);
        return 1;
    }
    return 0;
}

/* 1 = the policy lets this mode start now; 0 = refused, and the log says why */
static int starts_allowed(struct slot *M, const char *why)
{
    unsigned p = pm_player(), k = M->index;
    unsigned long since, wait;
    if (!starts_policy(M)) return 1;
    if (starts_is_file(why)) {
        pm_log("%s: a trigger file starts it whatever starts/cooldown say, and this run is not counted", cfg.name);
        return 1;
    }
    if (p < 1 || p >= STARTS_PLAYERS) return 1;
    if (cfg.starts_ball && starts_n[k].ball[p] >= cfg.starts_ball) {
        pm_log("%s not started (%s): already ran this ball", cfg.name, why);
        return 0;
    }
    if (cfg.starts_game && starts_n[k].game[p] >= cfg.starts_game) {
        if (cfg.starts_game == 1) pm_log("%s not started (%s): already ran this game", cfg.name, why);
        else pm_log("%s not started (%s): already ran %u times this game", cfg.name, why, starts_n[k].game[p]);
        return 0;
    }
    if (cfg.cooldown_s && starts_n[k].ended[p]) {
        since = pm_ms() - starts_n[k].ended_ms[p];
        wait = (unsigned long)cfg.cooldown_s * 1000UL;
        if (since < wait) {
            pm_log("%s not started (%s): cooling down, %lu s left", cfg.name, why, (wait - since + 999UL) / 1000UL);
            return 0;
        }
    }
    return 1;
}

/* the mode started: count it (called by mode_start just before its START line) */
static void starts_count(struct slot *M, const char *why)
{
    unsigned p = run.player, k = M->index;
    starts_uncounted = starts_is_file(why);
    if (starts_uncounted || p < 1 || p >= STARTS_PLAYERS) return;
    starts_n[k].game[p]++;
    starts_n[k].ball[p]++;
    if (starts_policy(M))
        pm_log("%s: start %u this game, %u this ball (player %u)", cfg.name, starts_n[k].game[p],
               starts_n[k].ball[p], p);
}

/* the mode ended: its cooldown runs from now */
static void starts_ended(struct slot *M)
{
    unsigned p = run.player, k = M->index;
    if (starts_uncounted || p < 1 || p >= STARTS_PLAYERS) return;
    starts_n[k].ended[p] = 1;
    starts_n[k].ended_ms[p] = pm_ms();
    if (cfg.cooldown_s) pm_log("%s: cooldown of %u s from now (player %u)", cfg.name, cfg.cooldown_s, p);
}

static void starts_ball_end(void)
{
    unsigned k, p, any = 0, policy = 0;
    for (k = 0; k < MODES_MAX; k++) {
        policy |= (unsigned)(slots[k].c.valid && starts_policy(&slots[k]));
        for (p = 0; p < STARTS_PLAYERS; p++) {
            any |= starts_n[k].ball[p];
            starts_n[k].ball[p] = 0;
        }
    }
    if (policy) pm_log("end of ball: this ball's start counts cleared%s", any ? "" : " (none had started)");
}

static void starts_clear_game(const char *witness)
{
    unsigned k, p, any = 0;
    for (k = 0; k < MODES_MAX; k++)
        for (p = 0; p < STARTS_PLAYERS; p++) {
            any |= starts_n[k].game[p] | starts_n[k].ball[p] | starts_n[k].ended[p];
            starts_n[k].game[p] = starts_n[k].ball[p] = starts_n[k].ended[p] = 0;
            starts_n[k].ended_ms[p] = 0;
        }
    pm_log("new game (%s): how-often counts cleared%s", witness, any ? "" : " (there were none)");
}

/* ---- PAD-227: more than one thing to meet before a mode starts --------------------------
 *   trigger_also <shots> <count>      another shot to hit <count> times in one ball as well
 *                                     (up to ALSO_MAX lines): the mode starts once the trigger
 *                                     line AND every trigger_also line are met, in any order
 *   after ball|game <mode name>       it can start only once that mode (another of this card's
 *                                     modes, by its name) has started for this player this ball,
 *                                     or this game; until then its own shots and events do not
 *                                     count toward starting it
 * The counts are per player and cleared at every end of ball and when the mode starts, as the
 * trigger line's are. Only one of a card's modes runs at a time, so `after` is never "while it
 * runs": a mode whose shots are met while its `after` mode still runs starts on its next shot
 * once that one has ended. An event start (`starts_on event`) is held to both as well: the event
 * starts it only when the trigger_also shots are met by then. A trigger file starts the mode
 * whatever these say. An older mode.so logs both keys `unknown key, skipped` and starts the mode
 * on its trigger line (or event) alone. */
static int more_line(struct slot *M, const char *line)
{
    const char *a;
    if ((a = key_is(line, "trigger_also")) != 0) {
        uint64_t bits = num(&a);
        unsigned count = (unsigned)num(&a);
        if (cfg.n_also >= ALSO_MAX) pm_log("trigger_also: a mode has up to %d - skipped", ALSO_MAX);
        else if (bits) {
            cfg.also_bits[cfg.n_also] = bits;
            cfg.also_count[cfg.n_also] = count ? count : 1;
            cfg.n_also++;
        }
        return 1;
    }
    if ((a = key_is(line, "after")) != 0) {
        const char *b;
        if ((b = key_is(a, "ball")) != 0) cfg.after_ball = 1;
        else if ((b = key_is(a, "game")) != 0) cfg.after_ball = 0;
        else {
            pm_log("after \"%.40s\" is not after ball <name> or after game <name> - skipped", a);
            return 1;
        }
        rest_of_line(cfg.after_name, sizeof cfg.after_name, b);
        return 1;
    }
    return 0;
}

static int name_is(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == 0 && *b == 0;
}

/* 1 = its `after` mode has started for player p (this ball or this game), or it has none */
static int after_met(struct slot *M, unsigned p)
{
    unsigned k;
    if (!cfg.after_name[0] || p < 1 || p >= STARTS_PLAYERS) return 1;
    for (k = 0; k < MODES_MAX; k++) {
        struct slot *O = &slots[k];
        if (O == M || !O->c.valid || !name_is(O->c.name, cfg.after_name)) continue;
        M->after_said = 0;
        return cfg.after_ball ? starts_n[k].ball[p] > 0 : starts_n[k].game[p] > 0;
    }
    if (!M->after_said)
        pm_log("%s: after %s - no mode of that name on this card, so it never starts", cfg.name, cfg.after_name);
    M->after_said = 1;
    return 0;
}

/* the OR of its trigger_also shots */
static uint64_t also_bits(const struct slot *M)
{
    uint64_t out = 0;
    unsigned i;
    for (i = 0; i < M->c.n_also; i++) out |= M->c.also_bits[i];
    return out;
}

/* count the trigger_also shots in `mask` for player p; 1 = one of them was hit */
static int also_shot(struct slot *M, uint64_t mask, unsigned p)
{
    unsigned i, hit = 0;
    for (i = 0; i < cfg.n_also; i++) {
        if (!(mask & cfg.also_bits[i])) continue;
        M->also[i][p]++;
        hit = 1;
        pm_log("%s: also %08x_%08x %u of %u (player %u)", cfg.name, (unsigned)(cfg.also_bits[i] >> 32),
               (unsigned)cfg.also_bits[i], M->also[i][p], cfg.also_count[i], p);
    }
    return hit;
}

/* 1 = every trigger_also line is met for player p */
static int also_met(struct slot *M, unsigned p)
{
    unsigned i;
    for (i = 0; i < cfg.n_also; i++)
        if (p > 4 || M->also[i][p] < cfg.also_count[i]) return 0;
    return 1;
}

static void also_clear(struct slot *M, unsigned p)
{
    unsigned i;
    for (i = 0; i < ALSO_MAX; i++) {
        if (p <= 4) M->also[i][p] = 0;
    }
}

static void more_loaded(struct slot *M)
{
    unsigned i;
    for (i = 0; i < cfg.n_also; i++)
        pm_log("\"%s\": also needs %08x_%08x x%u", cfg.name, (unsigned)(cfg.also_bits[i] >> 32),
               (unsigned)cfg.also_bits[i], cfg.also_count[i]);
    if (cfg.after_name[0])
        pm_log("\"%s\": starts only after %s has run this %s", cfg.name, cfg.after_name, cfg.after_ball ? "ball" : "game");
    M->after_said = 0;
}

/* ---- PAD-314: a mode started by shots made in ORDER -------------------------------------
 *   starts_on sequence                the mode starts when one player makes the trigger_seq
 *                                     shots in that order, in one ball (no `trigger` line)
 *   trigger_seq <shots>               one line per step, up to SEQ_MAX, in the order to make them
 *   trigger_seq_reset <shots>         a shot in these, made when it is not the step wanted, sends
 *                                     the player back to the start (the tab writes every shot of
 *                                     the game that is not in the sequence: "any other shot")
 * A step is met by a shot in its mask. A shot of the sequence made out of turn always starts the
 * player over (it counts as step 1 if it is step 1's shot); a shot in neither mask is ignored.
 * The progress is per player, cleared at the mode's start and at every end of ball, as the
 * trigger line's count is. Once the last step is made the sequence is MET: with trigger_also
 * shots still to make, it stays met until they are (as a met trigger count does), and `after`
 * gates it as it gates the trigger line. The tab writes no `trigger` line with it, so a mode.so
 * older than this logs the file NOT VALID instead of starting it on some other rule. A trigger
 * file starts the mode whatever the sequence says. */
static int sequence_line(struct slot *M, const char *line)
{
    const char *a;
    if ((a = key_is(line, "trigger_seq_reset")) != 0) {
        cfg.seq_reset_bits = num(&a);
        return 1;
    }
    if ((a = key_is(line, "trigger_seq")) != 0) {
        uint64_t bits = num(&a);
        if (cfg.n_seq >= SEQ_MAX) pm_log("trigger_seq: a mode has up to %d shots in order - skipped", SEQ_MAX);
        else if (bits) cfg.seq_bits[cfg.n_seq++] = bits;
        return 1;
    }
    return 0;
}

/* the OR of the sequence's shots */
static uint64_t seq_all_bits(const struct slot *M)
{
    uint64_t out = 0;
    unsigned i;
    for (i = 0; i < M->c.n_seq; i++) out |= M->c.seq_bits[i];
    return out;
}

static void seq_clear(struct slot *M, unsigned p)
{
    if (p <= 4) M->seq_at[p] = M->seq_done[p] = 0;
}

/* a shot in the sequence's or the reset shots, for player p: step forward, or start over */
static void sequence_shot(struct slot *M, uint64_t mask, unsigned p)
{
    unsigned at = M->seq_at[p], back;
    if (M->seq_done[p]) return;              /* met already: waiting for its other shots, or refused */
    if (mask & cfg.seq_bits[at]) {
        at++;
        pm_log("%s sequence %u of %u (player %u)", cfg.name, at, cfg.n_seq, p);
        if (at >= cfg.n_seq) {
            M->seq_done[p] = 1;
            at = 0;
        }
    } else if (mask & (seq_all_bits(M) | cfg.seq_reset_bits)) {
        back = (mask & cfg.seq_bits[0]) ? 1 : 0;
        if (at || back)
            pm_log("%s sequence: %08x_%08x is not shot %u of %u - back to %s (player %u)", cfg.name,
                   (unsigned)(mask >> 32), (unsigned)mask, at + 1, cfg.n_seq, back ? "1 of the sequence, this shot" : "the start", p);
        at = back;
    }
    M->seq_at[p] = at;
}

static void seq_loaded(struct slot *M)
{
    unsigned i;
    for (i = 0; i < cfg.n_seq; i++)
        pm_log("\"%s\": in order, shot %u is %08x_%08x", cfg.name, i + 1, (unsigned)(cfg.seq_bits[i] >> 32),
               (unsigned)cfg.seq_bits[i]);
    if (cfg.seq_reset_bits)
        pm_log("\"%s\": a shot in %08x_%08x out of turn starts the sequence over", cfg.name,
               (unsigned)(cfg.seq_reset_bits >> 32), (unsigned)cfg.seq_reset_bits);
}

/* Every tick, first: log each change of pm_in_game(), pm_player() and whether player 1's
 * score is 0, and clear the game's counts once per new game. A new game is player 1's
 * score falling to 0, or pm_in_game() rising while it is 0; it is recognised once, then
 * not again until player 1 has scored or pm_in_game() has fallen. Measured on Godzilla
 * Pro 1.15 (item 139): at game over the mode mask goes 0x0005 -> 0x0098 -> 0x0010 and
 * pm_in_game() falls, while the player byte stays 1 and every score stays on; a new game
 * clears the mask, raises pm_in_game() and zeroes player 1's score in the SAME tick; Start
 * held 3 s mid-game restarts it with pm_in_game() staying 1, so only the score shows it;
 * an end of ball sets mask bits 0x0004/0x0001, which are not busy bits, so pm_in_game()
 * never flickers there. MODE_SDK.md has the log lines. */
static void starts_watch_game(void)
{
    static int seen, was_in, was_zero, armed;
    static unsigned was_player, lines;
    int in = pm_in_game(), zero = pm_score(1) == 0;
    unsigned p = pm_player();
    const char *witness = 0;
    if (!seen) {
        seen = armed = 1;
        was_in = in;
        was_player = p;
        was_zero = zero;
        pm_log("game: in_game %d, player %u, player 1 score %s (first look)", in, p, zero ? "0" : "not 0");
        return;
    }
    if (in == was_in && p == was_player && zero == was_zero) return;
    if (lines < 2000) {
        lines++;
        pm_log("game: in_game %d -> %d, player %u -> %u, player 1 score %s -> %s", was_in, in,
               was_player, p, was_zero ? "0" : "not 0", zero ? "0" : "not 0");
    }
    if (!zero || (was_in && !in)) armed = 1;     /* player 1 scored, or the game ended */
    if (zero && armed && !was_zero) witness = "player 1's score went back to 0";
    else if (zero && armed && in && !was_in) witness = "a game began with player 1's score at 0";
    if (witness) {
        armed = 0;
        starts_clear_game(witness);
    }
    was_in = in;
    was_player = p;
    was_zero = zero;
}

/* ---- item 141: per-shot awards, an ending shot, the award ladder ----------------------
 *   shot_award   <bits> <points>   the shots in <bits> pay <points> instead of `award`, and
 *                                  score even when they are not in `shots` (repeatable, 16)
 *   end_shot     <bits>            a shot in <bits> ends the mode: it scores first if it is a
 *                                  scoring shot, and the mode ends on the next tick
 *   award_ladder fixed|rising      rising (the default, and what a file without the key
 *                                  gets): the Nth scoring shot pays N x its value; fixed: x 1
 *   shot_penalty <bits> <points>   PAD-314: a shot in <bits> TAKES <points> away while the mode
 *                                  runs (pm_score_sub: flat, never below 0; repeatable, 16). A
 *                                  shot that also scores pays and takes nothing
 * An older mode.so logs "unknown key, skipped" for each and pays as before. */
static struct slot *end_pending;    /* the slot whose end shot was hit, until the next tick */
static uint64_t scoring_bits(struct slot *M);   /* below; PAD-314's load-time note needs it */

static int params_line(struct slot *M, const char *line)
{
    const char *a;
    if ((a = key_is(line, "shot_award")) != 0) {
        uint64_t bits = num(&a), points = num(&a);
        cfg.params_set = 1;
        if (!bits) pm_log("shot_award needs shot bits - ignored");
        else if (cfg.n_sa >= SHOT_AWARD_MAX) pm_log("more than %d shot_award lines - ignored", SHOT_AWARD_MAX);
        else {
            cfg.sa_bits[cfg.n_sa] = bits;
            cfg.sa_points[cfg.n_sa] = points;
            cfg.n_sa++;
        }
        return 1;
    }
    if ((a = key_is(line, "end_shot")) != 0) {
        cfg.end_shot_bits = num(&a);
        cfg.params_set = 1;
        return 1;
    }
    if ((a = key_is(line, "shot_penalty")) != 0) {      /* PAD-314 */
        uint64_t bits = num(&a), points = num(&a);
        cfg.params_set = 1;
        if (!bits || !points) pm_log("shot_penalty needs shot bits and points - ignored");
        else if (cfg.n_pen >= SHOT_AWARD_MAX) pm_log("more than %d shot_penalty lines - ignored", SHOT_AWARD_MAX);
        else {
            cfg.pen_bits[cfg.n_pen] = bits;
            cfg.pen_points[cfg.n_pen] = points;
            cfg.n_pen++;
        }
        return 1;
    }
    if ((a = key_is(line, "award_ladder")) != 0) {
        cfg.params_set = 1;
        if (key_is(a, "fixed")) cfg.award_fixed = 1;
        else {
            cfg.award_fixed = 0;
            if (!key_is(a, "rising")) pm_log("award_ladder %.20s is not fixed or rising - rising", a);
        }
        return 1;
    }
    return 0;
}

static void params_loaded(struct slot *M)
{
    unsigned i;
    if (!cfg.params_set) return;
    pm_log("params: award ladder %s, %u shot award(s), end shot %08x_%08x", cfg.award_fixed ? "fixed" : "rising",
           cfg.n_sa, (unsigned)(cfg.end_shot_bits >> 32), (unsigned)cfg.end_shot_bits);
    for (i = 0; i < cfg.n_sa; i++)
        pm_log("params: shot %08x_%08x pays %llu", (unsigned)(cfg.sa_bits[i] >> 32), (unsigned)cfg.sa_bits[i],
               (unsigned long long)cfg.sa_points[i]);
    for (i = 0; i < cfg.n_pen; i++)                     /* PAD-314 */
        pm_log("params: shot %08x_%08x takes %llu away%s", (unsigned)(cfg.pen_bits[i] >> 32), (unsigned)cfg.pen_bits[i],
               (unsigned long long)cfg.pen_points[i],
               (cfg.pen_bits[i] & scoring_bits(M)) ? " - but it scores, so it takes nothing" : "");
}

/* PAD-314: every bit that costs: each shot_penalty's bits, less the ones that score */
static uint64_t penalty_bits(struct slot *M)
{
    uint64_t bits = 0;
    unsigned i;
    for (i = 0; i < cfg.n_pen; i++) bits |= cfg.pen_bits[i];
    return bits & ~scoring_bits(M);
}

/* what a penalty shot takes: the first shot_penalty it matches (flat, no ladder) */
static uint64_t penalty_value(struct slot *M, uint64_t mask)
{
    unsigned i;
    for (i = 0; i < cfg.n_pen; i++)
        if (mask & cfg.pen_bits[i]) return cfg.pen_points[i];
    return 0;
}

/* every bit that scores: `shots`, and each shot_award's bits */
static uint64_t scoring_bits(struct slot *M)
{
    uint64_t bits = cfg.shot_bits;
    unsigned i;
    for (i = 0; i < cfg.n_sa; i++) bits |= cfg.sa_bits[i];
    return bits;
}

/* what the Nth scoring shot asks for: the first shot_award it matches, or `award` */
static uint64_t shot_value(struct slot *M, uint64_t mask, unsigned n)
{
    uint64_t base = cfg.award;
    unsigned i;
    for (i = 0; i < cfg.n_sa; i++)
        if (mask & cfg.sa_bits[i]) {
            base = cfg.sa_points[i];
            break;
        }
    return cfg.award_fixed ? base : base * n;
}

/* ---- item mode-leds: the mode's own inserts on the playfield ---------------------------------
 *   light          <shots> <colour> [pattern] [ms]     the inserts the port ties to these shot bits
 *   light_insert   <colour> <pattern> <ms> <name>[,<name>...]   inserts by the game's own name
 *   light_shots    <colour> [pattern] [ms]             every shot that scores in this mode (`shots`
 *                                                      and every `shot_award`, and PAD-228 the
 *                                                      `multiball_on` shot), lit while it runs
 *   light_all      <colour> [pattern] [ms]             every insert the port names (item 164: a mode's
 *                                                      Lights on a title without the light language)
 *   light_priority <1-255>                             the layer's priority (255, the top, when absent)
 * colour: rrggbb hex (a # before it is fine) or red, green, blue, yellow, orange, purple, cyan,
 * white, pink. pattern: solid (the default), blink, pulse, chase (across the line's inserts).
 * ms: the pattern's period, 0 or absent = its own. Held from the mode's START (pm_lamp_*), handed
 * back to the game at its END, whatever ends it. An older mode.so logs each line as an unknown
 * key and lights nothing. */
#define LIGHT_LINES_MAX 8
#define LIGHT_NAMES_MAX 160
#define LIGHT_SHOTS     1
#define LIGHT_INSERT    2
#define LIGHT_SCORING   3
#define LIGHT_ALL       4
static struct {
    unsigned n, prio;
    struct { int kind, pattern; uint64_t bits; unsigned rgb, ms; char names[LIGHT_NAMES_MAX]; } l[LIGHT_LINES_MAX];
} own_lights[MODES_MAX];

static void own_lights_clear(struct slot *M)
{
    own_lights[M->index].n = 0;
    own_lights[M->index].prio = 0;
}

static int light_same(const char *a, const char *b, unsigned n)
{
    unsigned i;
    for (i = 0; i < n; i++)
        if (a[i] != b[i]) return 0;
    return b[n] == 0;
}

/* a colour word or rrggbb at *p: 1 and the colour, 0 if it is neither (the log says so) */
static int light_colour(const char **p, unsigned *rgb)
{
    static const struct { const char *name; unsigned rgb; } names[] = {
        { "red", 0xff0000 }, { "green", 0x00ff00 }, { "blue", 0x0000ff }, { "yellow", 0xffc800 },
        { "orange", 0xff6000 }, { "purple", 0xa000ff }, { "cyan", 0x00ffff }, { "white", 0xffffff },
        { "pink", 0xff40a0 },
    };
    const char *s = *p;
    unsigned n = 0, i, v = 0;
    while (is_space(*s)) s++;
    if (*s == '#') s++;
    while (s[n] && !is_space(s[n])) n++;
    for (i = 0; i < sizeof names / sizeof names[0]; i++)
        if (light_same(s, names[i].name, n)) { *rgb = names[i].rgb; *p = s + n; return 1; }
    if (n != 6) return 0;
    for (i = 0; i < 6; i++) {
        int d = hexval(s[i]);
        if (d < 0) return 0;
        v = v * 16 + (unsigned)d;
    }
    *rgb = v;
    *p = s + n;
    return 1;
}

/* a pattern word at *p: solid when absent; -1 for a word that is not one */
static int light_pattern(const char **p)
{
    static const char *const names[] = { "solid", "blink", "pulse", "chase" };
    const char *s = *p;
    unsigned n = 0, i;
    while (is_space(*s)) s++;
    while (s[n] && !is_space(s[n])) n++;
    if (!n || (s[0] >= '0' && s[0] <= '9')) { *p = s; return PM_LAMP_SOLID; }
    for (i = 0; i < 4; i++)
        if (light_same(s, names[i], n)) { *p = s + n; return (int)i; }
    return -1;
}

static int own_lights_key(struct slot *M, const char *line)
{
    const char *a;
    int kind = 0, pat;
    unsigned rgb = 0;
    uint64_t bits = 0;
    if ((a = key_is(line, "light_priority")) != 0) {
        own_lights[M->index].prio = (unsigned)num(&a);
        if (own_lights[M->index].prio < 1 || own_lights[M->index].prio > 255) {
            pm_log("light_priority needs 1-255 - 255");
            own_lights[M->index].prio = 255;
        }
        return 1;
    }
    if ((a = key_is(line, "light")) != 0) { kind = LIGHT_SHOTS; bits = num(&a); }
    else if ((a = key_is(line, "light_insert")) != 0) kind = LIGHT_INSERT;
    else if ((a = key_is(line, "light_shots")) != 0) kind = LIGHT_SCORING;
    else if ((a = key_is(line, "light_all")) != 0) kind = LIGHT_ALL;
    if (!kind) return 0;
    if (kind == LIGHT_SHOTS && !bits) { pm_log("light needs shot bits - ignored: %.60s", line); return 1; }
    if (!light_colour(&a, &rgb)) { pm_log("light: no colour (rrggbb or a colour's name) - ignored: %.60s", line); return 1; }
    pat = light_pattern(&a);
    if (pat < 0) { pm_log("light: not solid, blink, pulse or chase - ignored: %.60s", line); return 1; }
    if (own_lights[M->index].n >= LIGHT_LINES_MAX) { pm_log("more than %d light lines - ignored", LIGHT_LINES_MAX); return 1; }
    {
        unsigned k = own_lights[M->index].n++;
        own_lights[M->index].l[k].kind = kind;
        own_lights[M->index].l[k].bits = bits;
        own_lights[M->index].l[k].rgb = rgb;
        own_lights[M->index].l[k].pattern = pat;
        own_lights[M->index].l[k].ms = (unsigned)num(&a);
        own_lights[M->index].l[k].names[0] = 0;
        if (kind == LIGHT_INSERT) {
            rest_of_line(own_lights[M->index].l[k].names, LIGHT_NAMES_MAX, a);
            if (!own_lights[M->index].l[k].names[0]) {
                pm_log("light_insert names no insert - ignored");
                own_lights[M->index].n--;
            }
        }
    }
    return 1;
}

static void own_lights_start(struct slot *M)
{
    unsigned k;
    int held = 0;
    if (!own_lights[M->index].n) return;
    if (!pm_can(PM_CAN_LAMPS)) {
        pm_log("lights: this game's port names no inserts - the light lines light nothing");
        return;
    }
    pm_lamp_priority(own_lights[M->index].prio ? own_lights[M->index].prio : 255);
    for (k = 0; k < own_lights[M->index].n; k++) {
        const typeof(own_lights[0].l[0]) *L = &own_lights[M->index].l[k];
        if (L->kind == LIGHT_SHOTS) held += pm_lamp_shot(L->bits, L->rgb, L->pattern, L->ms);
        else if (L->kind == LIGHT_SCORING)  /* PAD-228: and the shot a `multiball_on` waits for (the Action button) */
            held += pm_lamp_shot(scoring_bits(M) | (cfg.mball_balls ? cfg.mball_on_bits : 0), L->rgb, L->pattern, L->ms);
        else if (L->kind == LIGHT_ALL) held += pm_lamp_all(L->rgb, L->pattern, L->ms);
        else held += pm_lamp_set(L->names, L->rgb, L->pattern, L->ms);
    }
    pm_log("lights: %d insert(s) held while it runs (layer %u)", held,
           own_lights[M->index].prio ? own_lights[M->index].prio : 255);
}

static void own_lights_end(struct slot *M)
{
    int n;
    if (!own_lights[M->index].n || !pm_can(PM_CAN_LAMPS)) return;
    n = pm_lamp_release_all();
    pm_log("lights: %d insert(s) handed back to the game", n);
}

/* A clip a SHOT starts - the trigger shot's clip_start, the end shot's clip_end - waits
 * CLIP_AFTER_SHOT_TICKS and then plays from the tick. Measured in item 141 run 1 on Godzilla
 * Pro 1.15: PARAM TEST's clip_start, played inside the Maser trigger shot, never showed (the
 * shot's own reaction took the one video surface; MODE_SDK.md "Clips race the game's own"),
 * while every clip played from the tick did. A start or end by any other cause plays at once.
 * ONE clip waits at a time, and the newest clip wins the one surface: a clip still waiting when
 * another is asked for (the last mode's end clip when the next mode starts, a start clip when its
 * mode ends) is dropped, with a log line, and never plays over the newer one. */
#define CLIP_AFTER_SHOT_TICKS 30    /* half a second */
static struct { char name[96]; const char *when; unsigned ticks, watch; char watching[96]; } clip_later;
static int ending_clip;                 /* PAD-413: the last end played (or waits to play) its clip */
static unsigned ending_clip_begun;      /* pm_begun() then */

static void clip_copy(char *dst, unsigned cap, const char *src)
{
    unsigned i;
    for (i = 0; src[i] && i + 1 < cap; i++) dst[i] = src[i];
    dst[i] = 0;
}

static void clip_later_drop(const char *because)
{
    if (!clip_later.ticks) return;
    clip_later.ticks = 0;
    pm_log("clip \"%.80s\" (%s) dropped before it played: %s", clip_later.name, clip_later.when, because);
}

/* a clip that plays at once - the log line is the one every mode file has always written */
static void clip_now(const char *name, const char *when)
{
    clip_later_drop("a newer clip played at once");
    pm_log("clip \"%.80s\" %s (%s)", name, pm_clip(name) ? "played" : "NOT played", when);
}

/* PAD-413: the last mode's ENDING gives way once another of our modes began - a mode file's, or one in C (David's
 * Premium, 2026-10-06: BIOLLANTE began 4.8 s into KIRYU's 10 s ending and their words shared the glass). Its own
 * screen's TOTAL is hidden at once, an end clip still waiting never plays, and - when it is one of ours that began
 * (`starting`) - an end clip still playing stops (the runtime stops it itself when a mode in C began). */
static void ending_gives_way(int starting)
{
    unsigned k, now = pm_begun();
    struct slot *M;
    if (ending_clip && now != ending_clip_begun) {
        ending_clip = 0;
        clip_later_drop("another mode began");
        if (starting && pm_clip_playing()) {
            pm_clip_stop();
            pm_log("the last mode's ending clip stopped - another mode began");
        }
    }
    for (k = 0; k < MODES_MAX; k++) {
        M = &slots[k];
        if (!M->hide_ticks || running(M) || M->ended_begun == now) continue;
        M->hide_ticks = 0;
        M->aside = 0;
        if (M->node && !(run.active && run.slot && run.slot->node == M->node)) pm_show(M->node, 0);
        pm_log("%s: its total gives way - another mode began", cfg.name);
    }
}

static int clip_after_shot(const char *name, const char *when, const char *why)
{
    const char *shot = "trigger shot", *end = "end shot", *w;
    for (w = why; *w && *w == *shot; w++, shot++) ;
    if (*w || *shot) {
        for (w = why; *w && *w == *end; w++, end++) ;
        if (*w || *end) return 0;
    }
    clip_later_drop("a newer clip waits instead");
    clip_copy(clip_later.name, sizeof clip_later.name, name);
    clip_later.when = when;
    clip_later.ticks = CLIP_AFTER_SHOT_TICKS;
    pm_log("clip \"%.80s\" waits %u ms after the %s (%s)", name, CLIP_AFTER_SHOT_TICKS * 1000 / TICKS_PER_S, why, when);
    return 1;
}

static void clip_later_tick(void)
{
    if (clip_later.watch && --clip_later.watch == 0)
        pm_log("clip \"%.80s\" %s 1 s after it started", clip_later.watching,
               pm_clip_playing() ? "still drawing" : "NOT drawing");
    if (!clip_later.ticks || --clip_later.ticks) return;
    pm_log("clip \"%.80s\" %s (%s, from the tick)", clip_later.name, pm_clip(clip_later.name) ? "played" : "NOT played",
           clip_later.when);
    clip_copy(clip_later.watching, sizeof clip_later.watching, clip_later.name);
    clip_later.watch = TICKS_PER_S;
}

static void end_shot_seen(uint64_t mask, unsigned player)
{
    struct slot *M = run.slot;
    if (!run.active || !M || player != run.player || !(mask & cfg.end_shot_bits) || end_pending) return;
    end_pending = M;
    pm_log("end shot %08x_%08x: the mode ends on the next tick", (unsigned)(mask >> 32), (unsigned)mask);
}

/* ---- item 147: what starts a mode, and what ends it ------------------------------------
 *   starts_on shot                    the `trigger` line's shots (the default)
 *   starts_on event <name> [N]        the N-th firing of a port event (N = 1 if absent), counted
 *                                     per player across a game (reset by the port's game_start)
 *   starts_on sequence                the `trigger_seq` shots made in order (PAD-314, above)
 *   ends_on drain                     its clock, or the ball ending (the default)
 *   ends_on clock                     its clock only: it runs on through the end of a ball
 *   ends_on event <name>              that event, its clock, or the ball ending
 * An event start needs no `trigger` line, and the Modes tab writes none, so a mode.so older
 * than this item logs such a file NOT VALID instead of starting it on a shot. */
#define END_DRAIN 0
#define END_CLOCK 1
#define END_EVENT 2

static void word_copy(char *dst, unsigned cap, const char **src)
{
    unsigned n = 0;
    const char *s = *src;
    while (is_space(*s)) s++;
    while (*s && *s != '\n' && !is_space(*s)) {
        if (n + 1 < cap) dst[n++] = *s;
        s++;
    }
    dst[n] = 0;
    while (is_space(*s)) s++;
    *src = s;
}

static int trigger_on_line(struct slot *M, const char *line)
{
    const char *a;
    char how[16];
    if ((a = key_is(line, "starts_on")) != 0) {
        word_copy(how, sizeof how, &a);
        if (key_is(how, "event")) {
            word_copy(cfg.start_event_name, sizeof cfg.start_event_name, &a);
            cfg.start_event_count = (unsigned)num(&a);
            if (!cfg.start_event_count) cfg.start_event_count = 1;
            cfg.start_on_event = 1;
        } else if (key_is(how, "sequence")) {
            cfg.start_on_seq = 1;                /* PAD-314: the trigger_seq shots, in order */
        } else if (!key_is(how, "shot")) {
            pm_log("starts_on \"%.40s\" is not shot, sequence or event - the mode starts on its shots", how);
        }
        return 1;
    }
    if ((a = key_is(line, "ends_on")) != 0) {
        word_copy(how, sizeof how, &a);
        if (key_is(how, "clock")) cfg.end_on = END_CLOCK;
        else if (key_is(how, "event")) {
            word_copy(cfg.end_event_name, sizeof cfg.end_event_name, &a);
            cfg.end_on = END_EVENT;
        } else {
            if (!key_is(how, "drain")) pm_log("ends_on \"%.40s\" is not drain, clock or event - drain", how);
            cfg.end_on = END_DRAIN;
        }
        return 1;
    }
    return 0;
}

/* After a file is parsed: resolve the event names through the port, and let an event start
 * stand in for the trigger count. */
/* it has something to run: a clock, a multiball (which may have no clock), or the game's mini-wizard (PAD-436) */
static int runs(const struct slot *M)
{
    return cfg.seconds || cfg.mball_balls || cfg.wizard[0];
}

static void trigger_on_validate(struct slot *M)
{
    cfg.start_event = cfg.end_event = -1;
    if (cfg.end_on == END_EVENT) {
        cfg.end_event = pm_event(cfg.end_event_name);
        if (cfg.end_event < 0) {
            pm_log("ends_on event %s: this game's port has no such event - it ends on the drain", cfg.end_event_name);
            cfg.end_on = END_DRAIN;
        }
    }
    if (cfg.start_on_seq) {                  /* PAD-314: the shots in order stand in for the trigger count */
        if (cfg.start_on_event) {
            pm_log("starts_on sequence: an event start is ignored");
            cfg.start_on_event = 0;
        }
        if (cfg.trigger_bits) {
            pm_log("starts_on sequence: the trigger shots are ignored");
            cfg.trigger_bits = 0;
        }
        cfg.valid = runs(M) && cfg.n_seq > 0;
        pm_log("starts on %u shots in order%s", cfg.n_seq, cfg.valid ? "" : "  - NOT VALID, it needs seconds and a trigger_seq line");
        seq_loaded(M);
        return;
    }
    if (!cfg.start_on_event) return;
    cfg.start_event = pm_event(cfg.start_event_name);
    if (cfg.trigger_bits) {
        pm_log("starts_on event: the trigger shots are ignored");
        cfg.trigger_bits = 0;
    }
    cfg.valid = runs(M) && cfg.start_event >= 0;
    pm_log("starts on event %s (id %d) x%u, ends on %s%s%s", cfg.start_event_name, cfg.start_event,
           cfg.start_event_count, cfg.end_on == END_CLOCK ? "its clock" : cfg.end_on == END_EVENT ? "event " : "the drain",
           cfg.end_on == END_EVENT ? cfg.end_event_name : "",
           cfg.start_event < 0 ? "  - NOT VALID, this game's port has no such event" : "");
}

static void cfg_line(struct slot *M, const char *line)
{
    const char *a;
    TEXT("name", name)
    if ((a = key_is(line, "trigger")) != 0) { cfg.trigger_bits = num(&a); cfg.trigger_count = (unsigned)num(&a); return; }
    NUM("seconds", seconds)
    NUM64("shots", shot_bits)
    NUM64("award", award)
    NUM("screen_type", screen_type)
    NUM("title_msg", title_msg)
    NUM("total_msg", total_msg)
    TEXT("title_words", title_words)
    TEXT("total_words", total_words)
    NUM("restore_after", restore_after)
    NUM("light_owner", light_owner)
    TEXT("light_on", light_on)
    TEXT("light_off", light_off)
    NUM("callout_count", callout_count)
    NUM("callout_end", callout_end)
    NUM("sound_callout", sound_callout)
    TEXT("screen_scene", screen_scene)
    TEXT("screen_node", screen_node)
    TEXT("screen_text", screen_text)
    TEXT("clip_start", clip_start)
    TEXT("clip_end", clip_end)
    TEXT("show_start", show_start)          /* PAD-418 */
    TEXT("show_end", show_end)              /* PAD-418 */
    if ((a = key_is(line, "game_wizard")) != 0) {   /* PAD-436 */
        const char *b;
        if ((b = key_is(a, "start")) != 0) cfg.wizard_start = 1;
        else if ((b = key_is(a, "light")) != 0) cfg.wizard_start = 0;
        else {
            pm_log("game_wizard \"%.40s\" is not light or start - skipped", a);
            return;
        }
        rest_of_line(cfg.wizard, sizeof cfg.wizard, b);
        return;
    }
    if (key_is(line, "clip_label") || key_is(line, "clip_layer")) return;   /* see the top */
    if ((a = key_is(line, "sound_key")) != 0) {
        unsigned n = 0;
        while (is_space(*a)) a++;
        while (n < 8) {
            int hi = hexval(a[2 * n]), lo = hexval(a[2 * n + 1]);
            if (hi < 0 || lo < 0) break;
            cfg.sound_key[n++] = (unsigned char)((hi << 4) | lo);
        }
        cfg.has_sound_key = (n == 8);
        if (!cfg.has_sound_key) pm_log("sound_key needs 16 hex digits - ignored");
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
    if (own_sounds_key(M, line)) return;
    if (starts_line(M, line)) return;
    if (stack_line(M, line)) return;
    if (aside_line(M, line)) return;         /* PAD-347 */
    if (game_modes_line(M, line)) return;    /* PAD-363 */
    if (block_modes_line(M, line)) return;   /* PAD-363 */
    if (keep_rules_line(M, line)) return;    /* PAD-398 */
    if (multiball_line(M, line)) return;     /* item 167 */
    if (ball_save_line(M, line)) return;     /* PAD-225 */
    if (magnet_line(M, line)) return;        /* PAD-381 */
    if (scoop_line(M, line)) return;         /* PAD-381 */
    if (coil_line(M, line)) return;          /* PAD-381 */
    if (shield_line(M, line)) return;        /* PAD-392 */
    if (shake_line(M, line)) return;         /* PAD-414 */
    if (params_line(M, line)) return;
    if (trigger_on_line(M, line)) return;
    if (roster_line(M, line)) return;
    if (own_lights_key(M, line)) return;     /* item mode-leds */
    if (display_line(M, line)) return;
    if (more_line(M, line)) return;          /* PAD-227 */
    if (sequence_line(M, line)) return;      /* PAD-314 */
    pm_log("unknown key, skipped: %.80s", line);
}

static void cfg_parse(struct slot *M, const char *buf, long len)
{
    char line[STR_MAX + 64];
    long i = 0;
    unsigned k;
    for (k = 0; k < sizeof cfg; k++) ((char *)&cfg)[k] = 0;
    cfg.game_modes = GM_BLOCK;               /* PAD-398: a file that says nothing runs alone */
    own_sounds_clear(M);
    own_lights_clear(M);                     /* item mode-leds */
    while (i < len) {
        long j = 0;
        while (i < len && buf[i] != '\n') {
            if (j + 1 < (long)sizeof line) line[j++] = buf[i];
            i++;
        }
        i++;
        line[j] = 0;
        {
            char *s = line;
            while (is_space(*s)) s++;
            if (*s && *s != '#') cfg_line(M, s);
        }
    }
    cfg.valid = runs(M) && cfg.trigger_count;   /* a multiball may have no clock */
    trigger_on_validate(M);
    pm_log("loaded \"%s\": trigger %08x_%08x x%u, %u s, shots %08x_%08x, award %llu%s",
           cfg.name, (unsigned)(cfg.trigger_bits >> 32), (unsigned)cfg.trigger_bits, cfg.trigger_count, cfg.seconds,
           (unsigned)(cfg.shot_bits >> 32), (unsigned)cfg.shot_bits, (unsigned long long)cfg.award,
           cfg.valid ? "" : "  - NOT VALID, it needs seconds and a trigger count");
    if (cfg.stack_no) pm_log("\"%s\": stack no - waits while the game's own battle or multiball runs", cfg.name);
    if (cfg.mball_balls)
        pm_log("\"%s\": a multiball of its own - %u balls, ball save %u s, %s%s", cfg.name, cfg.mball_balls,
               cfg.mball_save_s, cfg.seconds ? "its clock or one ball left ends it" : "one ball left ends it (no clock)",
               pm_can(PM_CAN_MULTIBALL) ? "" : "  - this game's port cannot serve balls: it will not start");
    if (cfg.ball_save_s && !cfg.mball_balls)
        pm_log("\"%s\": a ball save of %u s when it starts%s", cfg.name, cfg.ball_save_s,
               pm_can(PM_CAN_MULTIBALL) ? "" : "  - this game's port cannot save a ball: it starts without one");
    if (cfg.add_ball_bits)
        pm_log("\"%s\": add a ball on %08x_%08x, up to %u time(s)", cfg.name, (unsigned)(cfg.add_ball_bits >> 32),
               (unsigned)cfg.add_ball_bits, cfg.add_ball_max);
    if (cfg.mball_on_bits)
        pm_log("\"%s\": the multiball comes on %08x_%08x%s", cfg.name, (unsigned)(cfg.mball_on_bits >> 32),
               (unsigned)cfg.mball_on_bits, cfg.mball_balls ? "" : " - but there is no multiball line: ignored");
    if (cfg.magnet_ms)                       /* PAD-381 */
        pm_log("\"%s\": the magnet holds the ball %u ms on %08x_%08x%s", cfg.name, cfg.magnet_ms,
               (unsigned)(cfg.magnet_bits >> 32), (unsigned)cfg.magnet_bits,
               !cfg.magnet_bits ? " - but no shot is the magnet's (the port has no magnet_shot): ignored"
               : pm_can(PM_CAN_COILS) ? "" : " - this game's port cannot drive the magnet: no grab");
    if (cfg.n_coil)                          /* PAD-381 */
        pm_log("\"%s\": %u held coil line(s), the first %s %u ms%s", cfg.name, cfg.n_coil, cfg.coil_name[0],
               cfg.coil_ms[0], pm_can(PM_CAN_COILS) ? "" : " - this game's port names no held coils: no hold");
    if (cfg.scoop_ms)                        /* PAD-381 */
        pm_log("\"%s\": a ball in the scoop is held %u ms%s", cfg.name, cfg.scoop_ms,
               pm_can(PM_CAN_SCOOP) ? "" : " - this game's port cannot hold the scoop: no hold");
    if (cfg.shield)                          /* PAD-392 */
        pm_log("\"%s\": the shield targets face the player while it runs%s", cfg.name,
               pm_can(PM_CAN_SHIELD) ? "" : " - this game has no shield platform: nothing turns");
    if (cfg.n_shake)                         /* PAD-414 */
        pm_log("\"%s\": %u shake line(s)%s", cfg.name, cfg.n_shake,
               pm_can(PM_CAN_SHAKER) ? "" : " - this game's port has no shaker: no shake");
    if (cfg.wizard[0]) {                     /* PAD-436 */
        pm_log("\"%s\": when it starts, the game's mini-wizard \"%s\" is %s instead - nothing of its own runs%s", cfg.name,
               cfg.wizard, cfg.wizard_start ? "started" : "lit for its start shot",
               pm_can(PM_CAN_GAME_WIZARDS) ? "" : " - this game's port names no mini-wizards: nothing happens");
        pm_game_wizard_claim_named(cfg.wizard);   /* PAD-457: the game's own lighting leaves it to this mode */
    }
    if (cfg.show_start[0] || cfg.show_end[0])   /* PAD-418 */
        pm_log("\"%s\": the game's light show \"%s\" at its start, \"%s\" at its end%s", cfg.name, cfg.show_start,
               cfg.show_end, pm_can(PM_CAN_GAME_SHOWS) ? "" : " - this game's port names no light shows: none plays");
    params_loaded(M);
    more_loaded(M);                          /* PAD-227 */
}

/* Re-read and byte-compare; 1 = it changed (loaded, reloaded, or gone). */
static int cfg_reload(struct slot *M)
{
    char buf[CFG_MAX];
    long n = -1, i;
    int k;
    for (k = 0; k < MODE_DIRS_N; k++) {
        n = pm_read_file(M->file[k], buf, sizeof buf);
        if (n >= 0) break;
    }
    if (n < 0) {
        if (M->raw_len < 0) return 0;
        M->raw_len = -1;
        M->said_which = -1;
        cfg.valid = 0;
        pm_log("mode file gone: slot %u (\"%s\") is not armed", M->index, cfg.name);
        roster_sync(M);
        return 1;
    }
    if (M->said_which != k) {
        M->said_which = k;
        pm_log("mode file: %s", M->file[k]);
    }
    if (n == M->raw_len) {
        for (i = 0; i < n && buf[i] == M->raw[i]; i++) ;
        if (i == n) return 0;
    }
    for (i = 0; i < n; i++) M->raw[i] = buf[i];
    M->raw_len = n;
    cfg_parse(M, M->raw, n);
    roster_sync(M);
    M->node = M->text = 0;
    M->said[0] = 0;                          /* PAD-390: a new file's screen has said nothing yet */
    return 1;
}

/* ---- screens: every slot's is found and hidden --------------------------------------- */
static int own_screen(struct slot *M) { return cfg.screen_node[0] != 0; }

static void screen_resolve(struct slot *M)
{
    const char *where;
    if (!own_screen(M) || M->node) return;
    where = cfg.screen_scene[0] ? cfg.screen_scene : "hud";
    M->node = pm_node(where, cfg.screen_node);
    if (!M->node) return;
    M->text = pm_text(where, cfg.screen_text);
    if (!running(M)) pm_show(M->node, 0);
    pm_log("own screen \"%.60s\" found (text %s) - %s", cfg.screen_node, M->text ? "found" : "missing",
           running(M) ? "left visible, the mode is running" : "hidden until the mode runs");
}

static void words(struct slot *M, const char *before, uint64_t value, const char *after)
{
    char number[32], s[96];
    if (!M->text) return;
    pm_commas(number, sizeof number, value);
    pm_snprintf(s, sizeof s, "%s%s%s", before, number, after);
    pm_set_text(M->text, s);
    pm_snprintf(M->said, sizeof M->said, "%s", s);
}

/* PAD-390: a screen is authored VISIBLE and was hidden once, when it was found. If the game has the scene back in
 * its authored state - a fresh copy of it, or its nodes shown again - nothing hid it, and every mode's screen is
 * on the glass with the words the card build gave it (David's Godzilla Premium, 2026-10-05: every example's HUD
 * at once, word on word). So every 2 s the screen is looked at again: a different node (a fresh copy, or none)
 * is found afresh and given its last words, and the old copy is never touched again; the same node is shown or
 * hidden again as it should be (up while the mode runs or its total shows, unless it stepped aside). */
static void screen_recheck(struct slot *M)
{
    const char *where;
    void *n;
    if (!own_screen(M) || !M->node) return;
    where = cfg.screen_scene[0] ? cfg.screen_scene : "hud";
    n = pm_node(where, cfg.screen_node);
    if (n != M->node) {
        pm_log("%s: the game made its screen's scene again - %s", cfg.name, n ? "found afresh" : "gone for now");
        M->node = M->text = 0;              /* the old copy's: never shown, hidden or written again */
        screen_resolve(M);
        if (!M->node) return;
        if (M->said[0] && M->text) pm_set_text(M->text, M->said);
    }
    pm_show(M->node, (running(M) || M->hide_ticks) && !M->aside);
}

/* ---- the mode ------------------------------------------------------------------------ */
static int lights(struct slot *M, const char *command)
{
    /* the file's owner when it names one, the port's otherwise */
    return cfg.light_owner ? pm_lights_as(cfg.light_owner, command) : pm_lights(command);
}

/* `stack no` (item 140): 1 = it may start. A refusal leaves the slot's trigger count where it
 * is, so the first trigger after the game's mode ends starts it. A port that cannot tell says so
 * once, and the mode starts as `stack yes` would. */
static int stack_allows(struct slot *M, const char *why)
{
    static int said_cannot;
    int kind;
    if (!cfg.stack_no) return 1;
    kind = pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL);
    if (kind < 0) {
        if (!said_cannot) pm_log("stack no: this game's port cannot tell when its own modes run - starting as stack yes");
        said_cannot = 1;
        return 1;
    }
    if (kind == 0) return 1;
    pm_log("%s not started (%s): %s is running", cfg.name, why, pm_stock_mode_what((unsigned)kind));
    return 0;
}

/* item 167: the game took the multiball's balls: watch the count from now (PAD-228: also on a `multiball_on` shot) */
static void multiball_served(struct slot *M)
{
    run.mball_on = 1;
    run.mball_seen2 = 0;
    run.mball_last = -1;
    run.mball_one_ticks = 0;
    run.mball_grace_ticks = (cfg.mball_save_s + MBALL_GRACE_S) * TICKS_PER_S;
    run.add_balls_left = cfg.add_ball_bits ? cfg.add_ball_max : 0;
}

/* PAD-418: the game's own light show by the port's name (MODE_SDK.md "The game's own light shows"): at the start,
 * and in the first 2 s of the end (pm_end keeps that open). Never as the ball ends - the game stops every show of
 * its own then; the runtime refuses those too, and logs every refusal. */
static void game_show(struct slot *M, const char *name, const char *when)
{
    if (!name[0]) return;
    pm_log("%s: the game's light show \"%s\" at %s - %s", cfg.name, name, when,
           pm_game_show_named(name) ? "playing" : "not played (the runtime's line says why)");
}

/* PAD-436: a mode that is the game's own mini-wizard. When it would start, the player is handed the game's mode
 * (lit for its start shot, or started) and nothing of this mode's own runs: no clock, screen, lights or sounds. How
 * often it can start still holds, and the start counts as a run that ended at once (its cooldown runs from now).
 * Another of this card's modes running does not stop it; while that one holds the game's modes off, the runtime
 * lights a `start` instead (and starts it once that one ends, that ball - as when one of the game's own modes is
 * in the way, PAD-457). Refused by the runtime (no game, not this game's), it keeps its trigger count. */
static void hand_off(struct slot *M, const char *why)
{
    unsigned p = pm_player(), k = M->index;
    int how = cfg.wizard_start ? PM_WIZARD_START : PM_WIZARD_LIGHT, r;
    if (!starts_allowed(M, why)) return;
    r = pm_game_wizard_named(cfg.wizard, how);
    if (!r) {
        pm_log("%s not started (%s): the game's mini-wizard \"%s\" was not handed over%s", cfg.name, why, cfg.wizard,
               pm_can(PM_CAN_GAME_WIZARDS) ? " (the runtime's line says why)" : " - this game's port names none");
        return;
    }
    if (!starts_is_file(why) && p >= 1 && p < STARTS_PLAYERS) {
        starts_n[k].game[p]++;
        starts_n[k].ball[p]++;
        starts_n[k].ended[p] = 1;
        starts_n[k].ended_ms[p] = pm_ms();
    }
    if (p <= 4) M->trig[p] = 0;
    also_clear(M, p);
    seq_clear(M, p);
    pm_log("%s START (%s): the game's %s, %s for player %u", cfg.name, why, cfg.wizard,
           r == PM_WIZARD_STARTED ? "started" : "lit for its start shot", p);
}

static void mode_start(struct slot *M, const char *why)
{
    if (!cfg.valid || !pm_in_game()) return;
    if (cfg.wizard[0]) {                     /* PAD-436: the game's mini-wizard instead */
        hand_off(M, why);
        return;
    }
    if (run.active) {
        if (run.slot != M) pm_log("%s not started (%s): %s is running", cfg.name, why, run.slot->c.name);
        return;
    }
    if (!starts_allowed(M, why)) return;     /* item 139: how often it can start */
    if (!stack_allows(M, why)) return;       /* item 140: the game's own modes */
    if (cfg.game_modes != GM_STACK && pm_stock_mode_running(PM_STOCK_ANY) > 0) {   /* PAD-363 */
        pm_log("%s not started (%s): one of the game's modes is running - its trigger count is kept", cfg.name, why);
        return;
    }
    if (!pm_begin()) return;                 /* a mode written in C is running */
    pm_running_name(cfg.name);               /* PAD-363: the runtime's lines say this mode, not "mode" */
    ending_gives_way(1);                     /* PAD-413: before its own screen and clip */
    if (cfg.game_modes == GM_BLOCK) {        /* PAD-363: the listed game's modes cannot start while it runs */
        pm_block_list(cfg.block_ids, cfg.block_n);
        pm_block_rules_keep(cfg.keep_rules, cfg.keep_n);   /* PAD-398 */
        if (!pm_block_game_modes(1)) pm_log("%s: this game's port cannot hold its modes off - it gives way to them", cfg.name);
    }
    run.mball_on = run.mball_wait = 0;
    if (cfg.mball_balls && cfg.mball_on_bits) {
        run.mball_wait = 1;                  /* PAD-228: served on its shot, while the mode runs */
    } else if (cfg.mball_balls) {            /* item 167: the game serves the balls, or the mode does not start */
        if (!pm_multiball_start(cfg.mball_balls, cfg.mball_save_s)) {
            pm_log("%s not started (%s): the game did not serve its balls%s", cfg.name, why,
                   pm_can(PM_CAN_MULTIBALL) ? "" : " - this game's port cannot serve balls");
            pm_end();
            return;
        }
        multiball_served(M);
    }
    run.saving = !cfg.mball_balls && cfg.ball_save_s && pm_ball_save(cfg.ball_save_s);   /* no refusal stops the mode */
    if (cfg.scoop_ms) pm_scoop_hold(cfg.scoop_ms);       /* PAD-381: the runtime lets it go when the mode ends */
    coils_at(M, 0);                                      /* PAD-381: held coils with no shot hold as it starts */
    shakes_at(M, SHAKE_AT_START, 0);                     /* PAD-414 */
    run.shield_due = cfg.shield ? (pm_ms() + SHIELD_DELAY_MS) | 1ul : 0;   /* PAD-392 */
    run.no_clock = cfg.seconds == 0;
    run.active = 1;
    run.slot = M;
    run.player = pm_player();
    run.ticks_left = cfg.seconds * TICKS_PER_S;
    run.secs_shown = cfg.seconds;
    run.hits = 0;
    run.total = 0;
    run.lost = 0;                            /* PAD-314 */
    run.score_at_start = pm_score(run.player);
    run.started_ms = pm_ms();
    if (run.player <= 4) M->trig[run.player] = 0;
    also_clear(M, run.player);               /* PAD-227 */
    seq_clear(M, run.player);                /* PAD-314 */
    run.restore_ticks = 0;
    display_start(M);                        /* item 154 display: before the screen and the clip */
    if (own_screen(M)) {
        screen_resolve(M);
        if (M->node) {
            words(M, "", cfg.award, " A SHOT");
            pm_show(M->node, 1);
            M->aside = 0;                    /* PAD-347: on_tick steps it aside if a game mode runs */
            M->hide_ticks = 0;
        } else {
            pm_log("own screen not found - nothing shown, and no message id borrowed");
        }
    } else {
        if (cfg.title_msg) pm_message_set(cfg.title_msg, cfg.title_words);
        if (cfg.total_msg) pm_message_set(cfg.total_msg, cfg.total_words);
    }
    if (cfg.light_on[0]) pm_log("lights on: %s", lights(M, cfg.light_on) ? "ran under a live show" : "did not run (no live show, or no lights on this game)");
    if (cfg.clip_start[0] && !clip_after_shot(cfg.clip_start, "mode start", why)) clip_now(cfg.clip_start, "mode start");
    game_show(M, cfg.show_start, "its start");          /* PAD-418 */
    if (!own_screen(M) && cfg.title_msg) pm_award_screen(cfg.screen_type, cfg.title_msg, cfg.award);
    starts_count(M, why);
    pm_log("%s START (%s): slot %u, player %u, %u s, score %llu", cfg.name, why, M->index,
           run.player, cfg.seconds, (unsigned long long)run.score_at_start);
    if (!cfg.mball_balls && cfg.ball_save_s)
        pm_log("%s BALL SAVE: %u s%s", cfg.name, cfg.ball_save_s, run.saving ? "" : " - the game refused, so none");
    if (run.mball_on)
        pm_log("%s MULTIBALL: %u balls asked for, ball save %u s, %d in play now%s", cfg.name, cfg.mball_balls,
               cfg.mball_save_s, pm_balls_in_play(), run.add_balls_left ? ", add a ball armed" : "");
    if (run.mball_wait)
        pm_log("%s: the multiball waits for %08x_%08x (%u s to hit it)", cfg.name, (unsigned)(cfg.mball_on_bits >> 32),
               (unsigned)cfg.mball_on_bits, cfg.seconds);
    own_sounds_start(M);
    own_lights_start(M);                     /* item mode-leds: its inserts, while it runs */
}

static void mode_end(const char *why)
{
    struct slot *M = run.slot;
    uint64_t net;
    if (!run.active || !M) return;
    run.active = 0;
    pm_block_game_modes(0);                  /* PAD-363: the game's modes may start again */
    starts_ended(M);
    end_pending = 0;
    clip_later_drop("the mode ended");       /* a start clip still waiting never plays after the end */
    if (cfg.display_priority) pm_display_priority(0);   /* item 154 display: the game's display order again */
    if (shakes_at(M, SHAKE_AT_END, 0)) pm_shake_outlast();   /* PAD-414: before pm_end, which then leaves it to run */
    pm_end();
    roster_ended();
    own_sounds_end(M);
    own_lights_end(M);                       /* item mode-leds: the game has its inserts back */
    if (cfg.light_off[0]) lights(M, cfg.light_off);
    if (cfg.clip_end[0] && !clip_after_shot(cfg.clip_end, "mode end", why)) clip_now(cfg.clip_end, "mode end");
    if (!name_is(why, "ball ended")) game_show(M, cfg.show_end, "its end");   /* PAD-418: none as the ball ends */
    if (cfg.clip_end[0]) {                   /* PAD-413: an ending, until another mode begins */
        ending_clip = 1;
        ending_clip_begun = pm_begun();
    }
    /* PAD-314 (Ales): the total is NET of the penalty shots - "TOTAL -500,000" when they took more */
    net = run.total >= run.lost ? run.total - run.lost : run.lost - run.total;
    if (own_screen(M)) {
        words(M, run.total >= run.lost ? "TOTAL " : "TOTAL -", net, "");
        M->hide_ticks = (cfg.restore_after ? cfg.restore_after : 4) * TICKS_PER_S;
        M->ended_begun = pm_begun();         /* PAD-413: hidden at once if another mode begins */
    } else {
        if (cfg.total_msg) pm_award_screen(cfg.screen_type, cfg.total_msg, run.total >= run.lost ? net : 0);
        run.restore_ticks = cfg.restore_after * TICKS_PER_S;
    }
    pm_log("%s END (%s): %u shots, awarded %llu, lost %llu, total %s%llu, score %llu -> %llu, %lu ms wall", cfg.name,
           why, run.hits, (unsigned long long)run.total, (unsigned long long)run.lost,
           run.total >= run.lost ? "" : "-", (unsigned long long)net, (unsigned long long)run.score_at_start,
           (unsigned long long)pm_score(run.player), pm_ms() - run.started_ms);
}

/* ---- item 146: a mode in Godzilla's battle roster --------------------------------------- */
static unsigned roster_held[MODES_MAX];     /* roster slot + 1 each mode file holds; 0 = none */
static int roster_run;                      /* the running mode holds a roster pick: its END gives it back */
static unsigned roster_wait;                /* mode file slot + 1 picked but not started yet; 0 = none */
static unsigned roster_wait_player;
static unsigned long roster_wait_ms;        /* not before this pm_ms() */

static void roster_ended(void)
{
    if (!roster_run) return;
    roster_run = 0;
    pm_roster_done();
}

/* A taken pick starts its mode HERE: at once when nothing else runs and the port has no
 * `value roster_start_after_ms`; otherwise on the tick after that many ms (the selection screen's
 * closing animation covers a start screen shown at the pick), and not while another mode runs (it
 * starts when that one ends). A pick the mode cannot start (item 139's starts/cooldown, item 140's
 * stack no, a mode in C running, the player changed) is GIVEN BACK: pm_roster_done() lights the
 * ramps again. The game's battle for the slot never runs - the slot shows our name and art. */
static void roster_tick(void)
{
    struct slot *M;
    if (!roster_wait || run.active || pm_ms() < roster_wait_ms) return;
    M = &slots[roster_wait - 1];
    roster_wait = 0;
    if (!pm_in_game() || pm_player() != roster_wait_player) {
        pm_log("%s: the roster pick lapsed - the player changed or the game ended", cfg.name);
        pm_roster_done();                    /* the runtime gives it back to that player, or drops it at game over */
        return;
    }
    mode_start(M, "roster pick");
    if (running(M)) { roster_run = 1; return; }
    pm_log("%s: picked but not started - the pick is given back (the ramps light again)", cfg.name);
    pm_roster_done();
}

/* the ball ended before a taken pick started: give it back, as the end of a picked mode does */
static void roster_ball_end(void)
{
    if (!roster_wait) return;
    pm_log("%s: the ball ended before the roster pick started - the pick is given back", slots[roster_wait - 1].c.name);
    roster_wait = 0;
    pm_roster_done();
}

static int roster_pick(unsigned roster)
{
    unsigned k;
    long after = pm_port_value("roster_start_after_ms", 0);
    for (k = 0; k < MODES_MAX; k++) {
        struct slot *M = &slots[k];
        if (roster_held[k] != roster + 1) continue;
        if (running(M)) {
            roster_run = 1;           /* started by its trigger: its END must give the pick back too */
            pm_log("%s: roster slot %u picked while it runs - the pick is taken, nothing restarts", cfg.name, roster);
            return 1;
        }
        roster_wait = k + 1;
        roster_wait_player = pm_player();
        roster_wait_ms = pm_ms() + (after > 0 ? (unsigned long)after : 0UL);
        if (run.active)
            pm_log("%s: roster slot %u picked while %s runs - it starts when that one ends", cfg.name, roster,
                   run.slot->c.name);
        else if (after > 0)
            pm_log("%s: roster slot %u picked - it starts in %ld ms, once the selection screen has closed", cfg.name,
                   roster, after);
        roster_tick();
        return 1;
    }
    return 0;
}

/* item 146 fix-1: the held slot's callout follows the file's `roster_callout` (no line = silent). The runtime
 * silences a slot when it is claimed and puts the game's callout back when it is released. */
static unsigned roster_callout_now[MODES_MAX];   /* id + 1 last written for the slot each file holds; 0 = none */

static void roster_callout_sync(struct slot *M)
{
    unsigned id = cfg.roster_callout_1 ? cfg.roster_callout_1 - 1 : 0;
    if (!roster_held[M->index] || roster_callout_now[M->index] == id + 1) return;
    roster_callout_now[M->index] = id + 1;           /* said once either way */
    if (pm_roster_callout(roster_held[M->index] - 1, id))
        pm_log("%s: roster slot %u's callout is %u%s", cfg.name, roster_held[M->index] - 1, id, id ? "" : " (silent)");
    else
        pm_log("%s: roster slot %u's callout NOT set (this game's port has no selection screen table)", cfg.name,
               roster_held[M->index] - 1);
}

static void roster_sync(struct slot *M)
{
    unsigned want, k;
    if (M->raw_len >= 0 && cfg.roster_slot_1 && cfg.seconds && !cfg.valid && cfg.trigger_bits && !cfg.trigger_count) {
        /* `trigger <shots> 0` never starts a mode (without roster_slot the file is NOT VALID): keep that meaning */
        pm_log("%s: trigger %08x_%08x with a count of 0 starts nothing - only a pick of roster slot %u starts it", cfg.name,
               (unsigned)(cfg.trigger_bits >> 32), (unsigned)cfg.trigger_bits, cfg.roster_slot_1 - 1);
        cfg.trigger_bits = 0;
    }
    if (M->raw_len >= 0 && cfg.roster_slot_1 && cfg.seconds && !cfg.valid) {
        cfg.valid = 1;
        pm_log("%s: valid without a trigger (the NOT VALID above is the trigger modes' rule) - picking roster slot %u starts it",
               cfg.name, cfg.roster_slot_1 - 1);
    }
    want = cfg.valid ? cfg.roster_slot_1 : 0;
    if (roster_held[M->index] == want) { roster_callout_sync(M); return; }
    if (roster_held[M->index]) {
        pm_roster_release(roster_held[M->index] - 1);
        pm_log("roster slot %u released (mode file slot %u)", roster_held[M->index] - 1, M->index);
        roster_held[M->index] = 0;
        roster_callout_now[M->index] = 0;
    }
    if (!want) return;
    for (k = 0; k < MODES_MAX; k++)
        if (k != M->index && roster_held[k] == want) {
            pm_log("%s: roster slot %u NOT claimed - %s holds it", cfg.name, want - 1, slots[k].c.name);
            return;
        }
    if (pm_roster_claim(want - 1, roster_pick)) {
        roster_held[M->index] = want;
        roster_callout_now[M->index] = 1;    /* the runtime made the claimed slot silent */
        pm_log("%s claims roster slot %u", cfg.name, want - 1);
        roster_callout_sync(M);
    } else {
        pm_log("%s: roster slot %u NOT claimed (%s)", cfg.name, want - 1,
               pm_can(PM_CAN_ROSTER) ? "out of range" : "this game's port has no roster");
    }
}

/* ---- item 167: the multiball, while it runs ------------------------------------------------
 * The game's own end of ball comes only when the LAST ball drains, so the mode watches the
 * framework's count: two or more balls means the multiball is on; one (or none) for MBALL_ONE_S,
 * once the ball save and the serving are over (MBALL_GRACE_S after the save), ends it. A ball the
 * game could not serve (the rig with no coils, a machine with a stuck ball) ends it the same way. */
static void multiball_tick(struct slot *M)
{
    int n = pm_balls_in_play();
    if (n != run.mball_last) {
        pm_log("%s: %d ball(s) in play", cfg.name, n);
        run.mball_last = n;
    }
    if (n >= 2) {
        run.mball_seen2 = 1;
        run.mball_one_ticks = 0;
    }
    if (run.mball_grace_ticks) {
        run.mball_grace_ticks--;
        return;
    }
    if (n >= 2) return;
    if (++run.mball_one_ticks >= MBALL_ONE_S * TICKS_PER_S)
        mode_end(run.mball_seen2 ? "one ball left" : "no second ball was served");
}

/* PAD-228: a `multiball_on` mode's shot, while it waits: the game serves the balls now, the clock stops */
static void multiball_on_shot(struct slot *M, uint64_t mask)
{
    if (!(mask & cfg.mball_on_bits)) return;
    if (!pm_multiball_start(cfg.mball_balls, cfg.mball_save_s)) {
        pm_log("%s: multiball on %08x_%08x - the game did not serve its balls%s", cfg.name, (unsigned)(mask >> 32),
               (unsigned)mask, pm_can(PM_CAN_MULTIBALL) ? "" : " (this game's port cannot serve balls)");
        return;
    }
    run.mball_wait = 0;
    multiball_served(M);
    run.no_clock = 1;
    pm_log("%s MULTIBALL on %08x_%08x with %u s left: %u balls asked for, ball save %u s, %d in play now%s", cfg.name,
           (unsigned)(mask >> 32), (unsigned)mask, run.secs_shown, cfg.mball_balls, cfg.mball_save_s,
           pm_balls_in_play(), run.add_balls_left ? ", add a ball armed" : "");
}

static void multiball_shot(struct slot *M, uint64_t mask)
{
    if (!run.add_balls_left || !(mask & cfg.add_ball_bits)) return;
    if (!pm_multiball_add(1, cfg.mball_save_s)) {
        pm_log("%s: add a ball - the game refused", cfg.name);
        return;
    }
    run.add_balls_left--;
    run.mball_grace_ticks = (cfg.mball_save_s + MBALL_GRACE_S) * TICKS_PER_S;
    pm_log("%s: add a ball on %08x_%08x - %d in play, %u more add(s) left", cfg.name, (unsigned)(mask >> 32),
           (unsigned)mask, pm_balls_in_play(), run.add_balls_left);
}

/* ---- the game check (the Modes tab's Check this game) -------------------------------------
 * With /dump/gamecheck.on there at the first tick (tryit.sh install puts it there), every shot,
 * event and end of ball is logged as a `check` line, and so is each switch mark gamecheck.sh
 * writes to /dump/census.mark before it presses a switch: the app reads which of the port's
 * shots, events and end of ball this game really sends. Off, nothing here runs. */
static int check_on;

static void on_shot(uint64_t mask)
{
    unsigned p = pm_player(), k;
    struct slot *M;
    if (check_on)
        pm_log("check shot 0x%llx in_game %d", (unsigned long long)mask, pm_in_game());
    if (!pm_in_game()) return;
    if (run.active && (M = run.slot) != 0 && p == run.player && (mask & scoring_bits(M))
        && end_pending != M) {                   /* item 141: nothing pays once its end shot was hit */
        uint64_t asked = shot_value(M, mask, ++run.hits), got = pm_score_add(p, asked);
        run.total += got;
        if (own_screen(M)) words(M, "+", got, "");
        else if (cfg.title_msg) pm_award_screen(cfg.screen_type, cfg.title_msg, got);
        pm_log("shot %08x_%08x: +%llu (asked %llu), %u shots, %llu awarded",
               (unsigned)(mask >> 32), (unsigned)mask, (unsigned long long)got,
               (unsigned long long)asked, run.hits, (unsigned long long)run.total);
        own_sounds_shot(M, run.hits);
        /* PAD-415: the hit answers at once - while one of ours runs the game's rules see no shots, so none of the
         * game's own sounds or insert flashes play for it: the shot's inserts strobe white, and the game's own hit
         * sounds climb a step a hit */
        pm_lamp_flash(mask & scoring_bits(M), PM_RGB(255, 255, 255), 480);
        if (pm_hit_sounds()) pm_hit_sound((int)((run.hits - 1) % (unsigned)pm_hit_sounds()) + 1);
    }
    if (run.active && (M = run.slot) != 0 && p == run.player && (mask & penalty_bits(M)) && end_pending != M) {
        uint64_t asked = penalty_value(M, mask), lost = pm_score_sub(p, asked);   /* PAD-314 */
        run.lost += lost;
        if (own_screen(M)) words(M, "-", lost, "");
        pm_log("penalty shot %08x_%08x: -%llu (asked %llu), %llu lost, score %llu",
               (unsigned)(mask >> 32), (unsigned)mask, (unsigned long long)lost,
               (unsigned long long)asked, (unsigned long long)run.lost, (unsigned long long)pm_score(p));
    }
    if (run.active && (M = run.slot) != 0 && p == run.player && run.mball_on) multiball_shot(M, mask);
    else if (run.active && (M = run.slot) != 0 && p == run.player && run.mball_wait && end_pending != M)
        multiball_on_shot(M, mask);          /* PAD-228 */
    if (run.active && (M = run.slot) != 0 && p == run.player && end_pending != M)
        magnet_shot(M, mask);                /* PAD-381 */
    end_shot_seen(mask, p);
    if (p < 1 || p > 4) return;
    for (k = 0; k < MODES_MAX; k++) {
        int hit;
        uint64_t want;
        M = &slots[k];
        if (!cfg.valid || running(M)) continue;
        /* PAD-314: a sequence mode listens to its shots in order and to the shots that start it over */
        want = cfg.start_on_seq ? (seq_all_bits(M) | cfg.seq_reset_bits) : cfg.trigger_bits;
        if (!(mask & (want | also_bits(M)))) continue;
        if (!after_met(M, p)) {                  /* PAD-227: nothing counts before its `after` mode */
            pm_log("%s: shot not counted - %s has not run this %s (player %u)", cfg.name, cfg.after_name,
                   cfg.after_ball ? "ball" : "game", p);
            continue;
        }
        hit = also_shot(M, mask, p);
        if (cfg.start_on_seq) {
            if (mask & want) {
                sequence_shot(M, mask, p);
                hit = 1;
            }
            if (!hit || !M->seq_done[p]) continue;
            if (also_met(M, p)) mode_start(M, "shot sequence");
            else pm_log("%s: its sequence is met - waiting for its other shots (player %u)", cfg.name, p);
            if (running(M)) magnet_shot(M, mask);   /* PAD-381: the hit that starts it counts */
            continue;
        }
        if (mask & cfg.trigger_bits) {
            M->trig[p]++;
            pm_log("%s trigger %u of %u (player %u)", cfg.name, M->trig[p], cfg.trigger_count, p);
            hit = 1;
        }
        if (!hit || !cfg.trigger_bits || M->trig[p] < cfg.trigger_count) continue;
        if (also_met(M, p)) mode_start(M, "trigger shot");
        else pm_log("%s: its trigger is met - waiting for its other shots (player %u)", cfg.name, p);
        if (running(M)) magnet_shot(M, mask);       /* PAD-381: the hit that starts it counts */
    }
}

/* ---- item 147: starting and ending on the game's events ---------------------------------- */
#define EVENT_RETRY_TICKS (3 * TICKS_PER_S)

static void event_start(struct slot *M)
{
    char why[64];
    pm_snprintf(why, sizeof why, "event %s", cfg.start_event_name);
    if (pm_in_game()) {
        M->ev_pending = 0;
        mode_start(M, why);
        return;
    }
    if (!M->ev_pending)
        pm_log("%s: %s fired with no game in play yet (player %u) - retrying for 3 s", cfg.name, why, pm_player());
    M->ev_pending = EVENT_RETRY_TICKS;
}

static void on_event(unsigned id)
{
    unsigned k, p = pm_player();
    struct slot *M;
    if (check_on) {
        const char *name = pm_event_name(id);
        pm_log("check event %s (0x%02x) in_game %d", name ? name : "?", id, pm_in_game());
    }
    if (run.active && (M = run.slot) != 0 && cfg.end_on == END_EVENT && (int)id == cfg.end_event) {
        char why[64];
        pm_snprintf(why, sizeof why, "event %s", cfg.end_event_name);
        mode_end(why);
    }
    if (p > 4) p = 0;
    if ((int)id == pm_event("game_start"))
        for (k = 0; k < MODES_MAX; k++) {
            unsigned q;
            for (q = 0; q < 5; q++) slots[k].ev_trig[q] = 0;
        }
    for (k = 0; k < MODES_MAX; k++) {
        M = &slots[k];
        if (!cfg.valid || !cfg.start_on_event || (int)id != cfg.start_event || running(M)) continue;
        if (!after_met(M, p)) {                  /* PAD-227 */
            pm_log("%s: event %s not counted - %s has not run this %s (player %u)", cfg.name, cfg.start_event_name,
                   cfg.after_name, cfg.after_ball ? "ball" : "game", p);
            continue;
        }
        if (++M->ev_trig[p] < cfg.start_event_count) {
            pm_log("%s: event %s %u of %u (player %u)", cfg.name, cfg.start_event_name, M->ev_trig[p],
                   cfg.start_event_count, p);
            continue;
        }
        if (!also_met(M, p)) {                   /* PAD-227: its shots are not all hit yet */
            pm_log("%s: event %s - waiting for its other shots (player %u)", cfg.name, cfg.start_event_name, p);
            M->ev_trig[p] = 0;
            continue;
        }
        M->ev_trig[p] = 0;
        event_start(M);
    }
}

/* every tick: a start that fired before the game counted as in play gets 3 s to become one */
static void events_tick(void)
{
    unsigned k;
    for (k = 0; k < MODES_MAX; k++) {
        struct slot *M = &slots[k];
        if (!M->ev_pending) continue;
        if (!cfg.valid || running(M)) { M->ev_pending = 0; continue; }
        if (pm_in_game()) {
            char why[64];
            pm_snprintf(why, sizeof why, "event %s, %u ms late", cfg.start_event_name,
                        (EVENT_RETRY_TICKS - M->ev_pending) * 1000u / TICKS_PER_S);
            M->ev_pending = 0;
            mode_start(M, why);
        } else if (--M->ev_pending == 0) {
            pm_log("%s: event %s start dropped - still no game in play after 3 s", cfg.name, cfg.start_event_name);
        }
    }
}

/* `ends_on clock`: the running mode goes on through the end of a ball. 1 = keep it running. */
static int keeps_through_ball_end(void)
{
    if (!run.active || !run.slot || run.slot->c.end_on != END_CLOCK) return 0;
    if (roster_run) {                        /* item 146: a picked mode running on would get its pick given back */
        pm_log("%s: the ball ended - a roster pick ends with its ball, as the game's battles do (ends_on clock ignored)",
               run.slot->c.name);
        return 0;
    }
    pm_log("%s: the ball ended - running on (ends_on clock)", run.slot->c.name);
    return 1;
}

static void on_ball_end(void)
{
    unsigned k, p;
    if (check_on) pm_log("check ball end");
    if (!keeps_through_ball_end()) mode_end("ball ended");
    for (k = 0; k < MODES_MAX; k++)
        for (p = 0; p < 5; p++) {
            slots[k].trig[p] = 0;
            also_clear(&slots[k], p);            /* PAD-227 */
            seq_clear(&slots[k], p);             /* PAD-314 */
        }
    starts_ball_end();
    roster_ball_end();                       /* item 146: a pick not started yet is given back */
}

/* The files are numbered with no gaps (the app writes slot order), so a new one appears at
 * the slot after the last: re-read every slot up to that one. The first sweep (on_init)
 * reads them all, so a file past a gap that was there at boot is still found. */
static void poll_bound(void)
{
    unsigned k, n = 0;
    for (k = 0; k < MODES_MAX; k++)
        if (slots[k].raw_len >= 0) n = k + 1;
    poll_n = n < MODES_MAX ? n + 1 : MODES_MAX;
}

/* PAD-347: while its screen is up (the mode running, or its total showing) and one of the game's own modes
 * runs, the screen steps aside: hidden, and shown again when the game's mode ends (`aside keep`: never). */
static void screen_aside_tick(struct slot *M)
{
    int a;
    if (!own_screen(M) || !M->node || cfg.aside_keep) return;
    if (!running(M) && !M->hide_ticks) {     /* down anyway: nothing to put back */
        M->aside = 0;
        return;
    }
    a = pm_aside();
    if (!a == !M->aside) return;
    M->aside = a != 0;
    pm_show(M->node, !M->aside);
    if (M->aside) pm_log("%s: its screen steps aside - %s has the middle of the screen", cfg.name, pm_stock_mode_what((unsigned)a));
    else pm_log("%s: its screen is back - the game's mode is over", cfg.name);
}

static void on_tick(void)
{
    static unsigned ticks;
    unsigned secs, i, k;
    char name[24], clip[100];
    struct slot *M;
    if (check_on && pm_trigger_text("census.mark", name, sizeof name))
        pm_log("check mark %s", name);
    starts_watch_game();                     /* item 139: what marks a new game */
    ending_gives_way(0);                     /* PAD-413: a mode in C began during the last one's ending */
    clip_later_tick();                       /* item 141: a clip a shot started */
    ++ticks;
    events_tick();
    roster_tick();                           /* item 146: a taken roster pick starts when it may */
    for (k = 0; k < MODES_MAX; k++) {
        M = &slots[k];
        if (ticks % POLL_TICKS == 0 && k < poll_n) {
            if (cfg_reload(M) && running(M)) pm_log("reloaded while running - the new file is live");
            screen_resolve(M);
            if (ticks % (4 * POLL_TICKS) == 0) screen_recheck(M);   /* PAD-390: every 2 s */
            if (k == 0) pm_snprintf(name, sizeof name, "mode.start");
            else pm_snprintf(name, sizeof name, "mode%u.start", k);
            if (pm_trigger(name)) mode_start(M, "trigger file");
        }
        if (M->hide_ticks && --M->hide_ticks == 0 && !running(M) && M->node) {
            pm_show(M->node, 0);
            M->aside = 0;
            pm_log("own screen hidden");
        }
        screen_aside_tick(M);                /* PAD-347 */
    }
    if (ticks % POLL_TICKS == 0) {
        poll_bound();
        if (pm_trigger("mode.stop")) mode_end("trigger file");
        if (pm_trigger_text("mode.clip", clip, sizeof clip) && clip[0]) {
            for (i = 0; clip[i] && clip[i] != ' '; i++) ;
            clip[i] = 0;                               /* a layer after the name is ignored */
            pm_log("clip \"%.80s\" %s (trigger file)", clip, pm_clip(clip) ? "played" : "NOT played");
        }
    }
    if (run.restore_ticks && --run.restore_ticks == 0 && !run.active) {
        struct slot *last = run.slot;
        if (last) {
            pm_message_restore(last->c.title_msg);
            pm_message_restore(last->c.total_msg);
        }
        pm_log("borrowed messages restored");
    }
    own_sounds_stops_tick();                 /* item 150: a call's own length */
    if (!run.active || !(M = run.slot)) return;
    if (!pm_in_game() || pm_player() != run.player) {
        mode_end("left the game, or the player changed");
        return;
    }
    if (cfg.game_modes != GM_STACK && pm_aside()) {   /* PAD-363: one of the game's modes began anyway */
        mode_end("the game's own mode began");
        return;
    }
    if (end_pending == M) {                        /* item 141: its end shot was hit */
        mode_end("end shot");
        return;
    }
    own_sounds_tick(M, ticks);
    if (run.shield_due && pm_ms() >= run.shield_due) {      /* PAD-392: the runtime keeps it and turns it back */
        run.shield_due = 0;
        pm_log("%s: the shield targets turn toward the player - %s", cfg.name,
               pm_shield_keep(cfg.shield) ? "kept there while it runs" : "no platform on this machine");
    }
    if (run.mball_on) {
        multiball_tick(M);
        if (!run.active) return;
    }
    if (run.no_clock) return;                /* item 167: a multiball with no clock */
    if (run.ticks_left) run.ticks_left--;
    secs = (run.ticks_left + TICKS_PER_S - 1) / TICKS_PER_S;
    if (secs != run.secs_shown) {
        run.secs_shown = secs;
        for (i = 0; i < cfg.n_at; i++)
            if (secs == cfg.at_secs[i]) {
                pm_callout(cfg.at_id[i]);
                pm_log("callout %u at %u s left", cfg.at_id[i], secs);
            }
        if (secs >= 1 && secs <= 5) pm_callout_nth(cfg.callout_count, secs - 1);
        if (secs % 10 == 0 || secs <= 5) pm_log("%u s left", secs);
    }
    if (run.ticks_left == 0) {
        if (cfg.has_sound_key && cfg.sound_callout)
            pm_log("own sound %s", pm_callout_own_sound(cfg.sound_callout, cfg.sound_key) ? "substituted" : "missed");
        else if (!own_sounds_time_up(M))
            pm_callout(cfg.callout_end);
        mode_end("time ran out");
    }
}

static void on_init(void)
{
    unsigned k;
    int d, found = 0;
    for (k = 0; k < MODES_MAX; k++) {
        struct slot *M = &slots[k];
        M->index = k;
        M->raw_len = -1;
        M->said_which = -1;
        for (d = 0; d < MODE_DIRS_N; d++) {
            if (k == 0) pm_snprintf(M->file[d], sizeof M->file[d], "%smode.cfg", MODE_DIRS[d]);
            else pm_snprintf(M->file[d], sizeof M->file[d], "%smode%u.cfg", MODE_DIRS[d], k);
        }
        found += cfg_reload(M);
    }
    poll_bound();
    pm_log("armed, %d mode file(s) now, reading %u slot(s) x %d path(s) twice a second",
           found, poll_n, MODE_DIRS_N);
    check_on = pm_trigger("gamecheck.on");
    if (check_on) pm_log("check ready on %s %s", pm_game(), pm_version());
}

static const struct pm_mode mode_files = {
    .name = "mode",
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(mode_files);
