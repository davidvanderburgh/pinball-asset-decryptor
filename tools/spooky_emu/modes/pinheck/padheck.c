/* padheck.c - the custom-mode runtime for Spooky's pinHeck games (PAD-1422;
 * docs/plans/spooky_modes.md, tools/spooky_emu/modes/pinheck/hooks.py).
 *
 * MIPS32 (PIC32MX795) code linked into the free flash after a game's program, per build
 * (build.sh: the GAME_* symbols are that build's hook table).  The game calls pad_entry()
 * where it called its houseKeeping() once a millisecond; pad_entry runs houseKeeping and then
 * the modes.  The modes are data the build put after this code (struct pad_data at
 * PAD_DATA), the same keys as every other Spooky runtime:
 *
 *   start / start_count   the switches that start a mode and how many hits it takes
 *   shots / points        the switches that score while it runs, and what each scores
 *   seconds               how long it runs (0: until the ball ends)
 *   complete / complete_points   shots that complete it, and the bonus for that
 *   sound_start/_shot/_complete/_end   the game's own sounds (SFX/_F?/xxx.wav)
 *   panel                 middle / bottom / top / none: the mode's title, its total and its
 *                         time left on the DMD's text layer
 *
 * and (PAD-1469, JJP parity) the start rules, lamps, coils and balls:
 *
 *   start_on              ball_start, first_ball, last_ball, valid_playfield, ball_saved,
 *                         extra_ball, multiball_end: read off the game's own state every ms
 *   start_score / start_combo + combo_seconds / start_once / start_count_reset
 *   lamps / lamp_color / lamp_blink   the game's lamp table, written after its houseKeeping
 *                         filled it (that ms's value), so the lamp shows ours while the mode runs
 *   coil_start/_shot/_complete, coil_hold + coil_hold_on   the game's fireCoil; a hold is short
 *                         pulses on power of every 32 steps, and never over a coil the game drives
 *   multiball / multiball_on / add_ball / ball_save   the game's own ball queue (it loads and
 *                         launches them, and ends the ball only once every ball is home) and its
 *                         ball-save timer
 *
 * A mode ends on time, on completion, when the ball ends (drain or tilt) and when the game
 * ends; start counts reset at every new game.  What the runtime does goes to the game's own
 * serial monitor (UART1, 115200) as "[pad] ..." lines.
 *
 * No C library and no start-up code: nothing but the game's own functions, the bytes in
 * PAD_DATA, and the runtime's variables in RAM the game never writes (GAME_ram).
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

/* ------------------------------------------------------------------ the game (build.sh) */
extern void GAME_tick_target(void *self);
/* AddScore(points, flag): flag 0 is the plain award (Domino's and Rob Zombie read it: 1 takes
   another scoring path; Jetsons' ignores it) */
extern void GAME_add_score(u32 points, int flag);
extern void GAME_play_sfx(void *self, int channel, int folder, int clip0, int clip1, int priority);
#ifdef TEXT_ABI_AMH
/* AMH's text (Domino's, Rob Zombie; PAD-1423): text(this, line, s), packet 0x0F, byte 0 the
   line, up to 13 characters; no text layer to show or hide - the game's next video clears it */
extern void GAME_text_str(void *self, int line, const char *s);
#define TEXT_MAX 13
#else
extern void GAME_text_str(void *self, int zero, int column, int line, const char *s, int colour);
extern void GAME_text_show(void *self, int which, int on);
#define TEXT_MAX 32
#endif
extern void GAME_link_send(void *self, int cmd);
extern u8 GAME_this[];
extern volatile u8 GAME_data_out[16];
extern volatile u8 GAME_switch_ram[8];
extern volatile u32 GAME_millis;
extern volatile u32 GAME_score_array[5];
extern volatile u8 GAME_player, GAME_ball, GAME_ball_active, GAME_tilt, GAME_phase;
/* PAD-1469: the game's balls, coils and lamps (hooks.py) */
extern void GAME_coil_fire(void *self, int coil, int time);
extern volatile u32 GAME_coil_busy[24];     /* fireCoil's off times: non-zero while a coil is on */
extern volatile u8 GAME_lamp_ram[64];        /* 0..8 a lamp, refilled by houseKeeping every ms */
extern volatile u32 GAME_save_timer;         /* the ball save, ms left */
extern volatile u32 GAME_load_timer;         /* non-zero from a ball's load until it is in the lane */
extern volatile u16 GAME_ball_queue;         /* balls the game still has to load and launch */
extern volatile u8 GAME_extra_balls;         /* extra balls the player has waiting */
extern volatile u8 GAME_ball_limit;          /* the balls-per-game setting + 1 */

#define U1STA (*(volatile u32 *)0xBF806010)
#define U1TXREG (*(volatile u32 *)0xBF806020)

/* ------------------------------------------------------------------ the modes (the build) */
#define MAX_MODES 24
#define PANEL_NONE 0
#define PANEL_MIDDLE 1
#define PANEL_BOTTOM 2
#define PANEL_TOP 3

/* start_on bits */
#define EV_BALL_START 1
#define EV_FIRST_BALL 2
#define EV_LAST_BALL 4
#define EV_VALID_PLAYFIELD 8
#define EV_BALL_SAVED 16
#define EV_EXTRA_BALL 32
#define EV_MULTIBALL_END 64
/* pad_mode.flags */
#define F_RESET_BALL 1          /* start_count_reset = ball */
#define F_ONCE_BALL 2           /* start_once = ball */
#define F_ONCE_GAME 4           /* start_once = game */
#define HOLD_ON_SHOTS 0
#define HOLD_ON_START 1
#define HOLD_ON_SWITCHES 2
#define NO_COIL 0xFF

struct pad_mode {               /* 352 bytes, written by pinheck.py (pack_mode) */
    char title[16];             /* the panel's title, NUL-padded */
    u8 start[8], shots[8];      /* switch bitmaps, as GAME_switch_ram */
    u16 start_count, seconds, complete;
    u8 panel, flags;
    u32 points, complete_points;
    char sound[4][4];           /* start, shot, complete, end: 3 letters + NUL, "" none */
    /* PAD-1469 */
    u8 lamps[8];                /* lamp bitmap (lamp n: bit n & 7 of byte n >> 3) */
    u8 multiball_on[8], add_ball[8], hold_on[8];    /* switch bitmaps */
    u32 start_score;
    u8 start_on, lamp_level, lamp_blink, combo_n;   /* EV_ bits; 0..8; flashes a second */
    u8 combo[6];                /* start_combo's switches, in order */
    u8 combo_seconds, mb_balls; /* multiball: balls in play (0 none) */
    u8 mb_save, add_times, ball_save, hold_mode;    /* seconds; add_ball times; seconds; HOLD_ON_ */
    u8 coil[3], coil_t[3];      /* coil_start / _shot / _complete: coil (NO_COIL none), fireCoil time */
    u8 hold_coil, hold_power;   /* coil_hold: coil (NO_COIL none), on steps of 32 */
    u16 hold_ms;
    u8 pad2[2];
    /* PAD-1508: Spike 2's rules (tools/jjp_emu/MODES.md "Spike 2's rules") */
    u8 end_shots[8];            /* switch bitmap: a hit ends the mode */
    u8 rules, shot_every, start_max, cooldown;      /* RULE_ bits; every Nth shot sound; starts a game; s */
    u8 pattern, needs, sp_n, also_n;                /* PAT_; 1 + the mode of ours it needs (0 none) */
    u8 at_n, inside, pad3[2];                      /* inside: 1 + the mode of ours it runs inside (0 none) */
    struct { u8 sw[8]; u32 points; } sp[8];         /* shot_points: these switches pay these points */
    struct { u8 sw[8]; u8 count, pad[3]; } also[3]; /* start_also: these switches, this many hits */
    struct { u16 secs; char sound[4]; u8 pad[2]; } at[8];   /* sound_at: at this many seconds left */
    u8 pad4[8];
};
typedef char pad_mode_is_352[sizeof(struct pad_mode) == 352 ? 1 : -1];
#define RULE_RISING 1           /* points_ladder = rising */
#define RULE_NEEDS_BALL 2       /* start_needs ... ball (else game) */
#define PAT_AUTO 0              /* lamp_pattern: blink at lamp_blink, solid at 0 (before PAD-1508) */
#define PAT_SOLID 1
#define PAT_BLINK 2
#define PAT_PULSE 3
#define PAT_CHASE 4

struct pad_data {
    u32 magic;                  /* 'PHM2' */
    u8 count, off, lane, scale; /* the shooter lane switch; ms per fireCoil time unit */
    u8 trough[8];               /* the trough switches (and any ball locks beside them) */
    u8 coil_ok[24];             /* per coil: 1 a mode may pulse it, 2 a mode may hold it */
    u8 coil_own[24];            /* its own pulse, in fireCoil time units (an asked one is shorter) */
    u8 lamp_max, balls, pad1, pad2;     /* balls: the game's balls (0: not known) */
    char names[MAX_MODES][20];  /* the .mode file names, for the log */
    struct pad_mode mode[MAX_MODES];
};

#define DATA_MAGIC 0x334D4850u  /* "PHM3" (PAD-1508: 352-byte modes) */
extern const struct pad_data PAD_DATA;

/* ------------------------------------------------------------------ our variables */
struct run {
    u32 magic, last_ms;
    u8 prev[8];
    u8 live, active, player, ball, tilted, shown, drawn_lines;
    u32 drawn_ms, drawn_key;
    /* PAD-1469: what the game did, read every ms */
    u8 played, base, inplay, multi, prev_extra, ev_pending, valid_done, pad0;
    u32 prev_save, multi_since, our_save_until, single_since;
    /* the coils: when each fired last, its pulses this minute, and the one hold */
    u32 coil_last[24], minute_at;
    u8 coil_count[24];
    u8 hold_coil, hold_owner, hold_t, holds_this_minute;
    u32 hold_until, hold_next, hold_period, hold_ended[24];
    struct {
        u8 running, combo_i, score_done, once, mb, added, want, came;
        u16 hits, made;
        u32 total, ends_at, combo_ms, mb_until, one_since, save_until, game_save_until;
        u8 runs, at_done, got[3], pad[3];          /* PAD-1508: starts this game, sound_at, start_also */
        u32 ended_at;                               /* when it last ended (cooldown), 0: not this game */
    } m[MAX_MODES];
};

#define RUN_MAGIC 0x32444150u   /* "PAD2" */
extern struct run PAD_RUN;
#define R PAD_RUN
#define D PAD_DATA

/* ------------------------------------------------------------------ the log (UART1) */
static void out(char c)
{
    int n = 20000;
    while ((U1STA & (1u << 9)) && --n)     /* UTXBF: the transmit buffer is full */
        ;
    U1TXREG = (u8)c;
}

static void say(const char *s)
{
    while (*s)
        out(*s++);
}

static char *put_num(char *p, u32 v)
{
    char t[11];
    int n = 0;
    do {
        t[n++] = '0' + v % 10;
        v /= 10;
    } while (v);
    while (n)
        *p++ = t[--n];
    *p = 0;
    return p;
}

static char *put_str(char *p, const char *s, int max)
{
    while (*s && max--)
        *p++ = *s++;
    *p = 0;
    return p;
}

/* "[pad] <mode>: <what> <n>\r\n" */
static void log3(int i, const char *what, int has_n, u32 n, const char *tail)
{
    char b[160], *p = b;
    p = put_str(p, "[pad] ", 8);
    if (i >= 0)
        p = put_str(put_str(p, D.names[i], 20), ": ", 2);
    p = put_str(p, what, 48);
    if (has_n)
        p = put_num(p, n);
    if (tail)
        p = put_str(p, tail, 48);
    put_str(p, "\r\n", 2);
    say(b);
}

/* ------------------------------------------------------------------ the game's sound */
static void sound_named(int i, const char *key, const char *s)
{
    if (!s[0])
        return;
    GAME_play_sfx(GAME_this, 1, s[0], s[1], s[2], 255);
    log3(i, key, 0, 0, s);
}

static void sound(int i, int which)
{
    const char *s = D.mode[i].sound[which];
    static const char *const key[4] = {"sound_start ", "sound_shot ", "sound_complete ", "sound_end "};
    if (!s[0])
        return;
    GAME_play_sfx(GAME_this, 1, s[0], s[1], s[2], 255);
    log3(i, key[which], 0, 0, s);
}

/* ------------------------------------------------------------------ the panel */
static void text_line_clear(int line)
{
#ifdef TEXT_ABI_AMH
    GAME_text_str(GAME_this, line, "");
#else
    int k;
    GAME_data_out[0] = (u8)line;
    for (k = 1; k < 9; k++)
        GAME_data_out[k] = 0xFF;
    for (; k < 15; k++)
        GAME_data_out[k] = 0;
    GAME_link_send(GAME_this, 6);
#endif
}

static int len_of(const char *s, int max)
{
    int n = 0;
    while (n < max && s[n])
        n++;
    return n;
}

static void centred(int line, const char *s, int n)
{
    char b[33];
    int k;
    if (n > TEXT_MAX)
        n = TEXT_MAX;
    for (k = 0; k < n; k++)
        b[k] = s[k];
    b[n] = 0;
#ifdef TEXT_ABI_AMH
    GAME_text_str(GAME_this, line, b);          /* the Propeller centres the line */
#else
    GAME_text_str(GAME_this, 0, (32 - n) / 2, line, b, 255);
#endif
}

#ifndef TEXT_ABI_AMH
static char *put_grouped(char *p, u32 v)
{
    char t[16];
    int n = 0, k = 0;
    do {
        if (k && k % 3 == 0)
            t[n++] = ',';
        t[n++] = '0' + v % 10;
        v /= 10;
        k++;
    } while (v);
    while (n)
        *p++ = t[--n];
    *p = 0;
    return p;
}
#endif

static int first_line(int panel)
{
#ifdef TEXT_ABI_AMH
    (void)panel;
    return 0;           /* lines 0 and 1: the game's own two-line messages; 6 is its ticker */
#else
    return panel == PANEL_TOP ? 0 : panel == PANEL_BOTTOM ? 6 : 3;
#endif
}

static void undraw(void)
{
    if (!R.drawn_lines)
        return;
    text_line_clear(R.drawn_lines - 1);
    text_line_clear(R.drawn_lines);
#ifndef TEXT_ABI_AMH
    GAME_text_show(GAME_this, 3, 0);
#endif
    R.drawn_lines = 0;
}

static void draw(u32 now)
{
    int i = R.shown;
    const struct pad_mode *m;
    char b[40], *p = b;
    int line;
    if (i == 0xFF || !R.m[i].running || D.mode[i].panel == PANEL_NONE) {
        undraw();
        return;
    }
    m = &D.mode[i];
    line = first_line(m->panel);
    if (R.drawn_lines && R.drawn_lines != line + 1)
        undraw();
#ifdef TEXT_ABI_AMH
    p = put_num(p, R.m[i].total);                 /* 13 characters: "1000000 0:30" */
#else
    p = put_grouped(p, R.m[i].total);
#endif
    if (m->seconds) {
        u32 left = R.m[i].ends_at > now ? (R.m[i].ends_at - now + 999) / 1000 : 0;
#ifdef TEXT_ABI_AMH
        p = put_str(p, " ", 1);
#else
        p = put_str(p, "  ", 2);
#endif
        p = put_num(p, left / 60);
        *p++ = ':';
        *p++ = '0' + (left % 60) / 10;
        *p++ = '0' + left % 10;
        *p = 0;
    }
    {
        /* send it again only when it changed, or once a second (the game may have hidden the
           text layer for one of its own screens meanwhile) */
        u32 key = (u32)i * 2654435761u, k;
        for (k = 0; b + k < p; k++)
            key = key * 31 + (u8)b[k];
        if (R.drawn_lines == line + 1 && key == R.drawn_key && now - R.drawn_ms < 1000)
            return;
        R.drawn_key = key;
    }
#ifndef TEXT_ABI_AMH
    GAME_text_show(GAME_this, 3, 1);
#endif
    R.drawn_lines = line + 1;
#ifndef TEXT_ABI_AMH
    text_line_clear(line);              /* AMH's text replaces its line: no clear first */
#endif
    centred(line, m->title, len_of(m->title, 16));
#ifndef TEXT_ABI_AMH
    text_line_clear(line + 1);
#endif
    centred(line + 1, b, (int)(p - b));
    R.drawn_ms = now;
}

static void stop(int i, const char *why);

/* ------------------------------------------------------------------ helpers */
static int bit_of(const u8 *map, int n)
{
    return map[n >> 3] & (1 << (n & 7));
}

static int closed(int n)
{
    return GAME_switch_ram[n >> 3] & (1 << (n & 7));
}

static int any_bits(const u8 *map)
{
    int k;
    for (k = 0; k < 8; k++)
        if (map[k])
            return 1;
    return 0;
}

/* "[pad] <mode>: <what><a><tail><b>" */
static void log2n(int i, const char *what, u32 a, const char *tail, u32 b)
{
    char t[40], *p = t;
    p = put_str(p, tail, 24);
    put_num(p, b);
    log3(i, what, 1, a, t);
}

/* ------------------------------------------------------------------ coils (PAD-1469) */
static int coil_may(int c, int need)
{
    return c < 24 && (D.coil_ok[c] & need) && R.live && !GAME_tilt;
}

static void minute(u32 now)
{
    int k;
    if (now - R.minute_at < 60000)
        return;
    R.minute_at = now;
    R.holds_this_minute = 0;
    for (k = 0; k < 24; k++)
        R.coil_count[k] = 0;
}

/* coil_start / coil_shot / coil_complete: one pulse, never longer than the coil's own, 250 ms
   between two of one coil, 20 a minute; not while the game drives it */
static void pulse(int i, int which, u32 now)
{
    static const char *const key[3] = {"coil_start ", "coil_shot ", "coil_complete "};
    const struct pad_mode *m = &D.mode[i];
    int c = m->coil[which], t;
    if (c == NO_COIL)
        return;
    minute(now);
    if (!coil_may(c, 1)) {
        log3(i, key[which], 1, c, " not fired: no ball in play");
        return;
    }
    if (GAME_coil_busy[c]) {
        log3(i, key[which], 1, c, " not fired: the game is driving it");
        return;
    }
    if ((R.coil_last[c] && now - R.coil_last[c] < 250) || R.coil_count[c] >= 20) {
        log3(i, key[which], 1, c, " not fired: too soon");
        return;
    }
    t = m->coil_t[which] && m->coil_t[which] < D.coil_own[c] ? m->coil_t[which] : D.coil_own[c];
    GAME_coil_fire(GAME_this, c, t);
    R.coil_last[c] = now ? now : 1;
    R.coil_count[c]++;
    log2n(i, key[which], c, " pulsed, ms ", (u32)t * D.scale);
}

static void hold_off(const char *why)
{
    int c = R.hold_coil;
    if (c == NO_COIL)
        return;
    R.hold_ended[c] = GAME_millis ? GAME_millis : 1;
    R.hold_coil = NO_COIL;
    log3(R.hold_owner, "coil_hold off ", 1, c, why);
}

/* coil_hold: the coil on for hold_ms, on hold_power of every 32 steps, as short pulses of the
   game's fireCoil (the shortest it gives); 3 s off between two holds of one coil, 6 a minute */
static void hold_on(int i, u32 now)
{
    const struct pad_mode *m = &D.mode[i];
    int c = m->hold_coil, p = m->hold_power ? m->hold_power : 8, t;
    if (c == NO_COIL)
        return;
    minute(now);
    if (!coil_may(c, 2)) {
        log3(i, "coil_hold ", 1, c, " not held: no ball in play");
        return;
    }
    if (R.hold_coil != NO_COIL) {
        log3(i, "coil_hold ", 1, c, " not held: a hold is on");
        return;
    }
    if ((R.hold_ended[c] && now - R.hold_ended[c] < 3000) || R.holds_this_minute >= 6) {
        log3(i, "coil_hold ", 1, c, " not held: too soon");
        return;
    }
    if (p > 16)
        p = 16;
    t = D.scale > 1 ? 1 : p;                        /* fireCoil time: one unit, or p ms */
    R.hold_coil = c;
    R.hold_owner = i;
    R.hold_t = t;
    R.hold_period = (u32)t * D.scale * 32 / p;      /* on p of every 32 steps */
    R.hold_until = now + m->hold_ms;
    R.hold_next = now;
    R.holds_this_minute++;
    log2n(i, "coil_hold ", c, " on, ms ", m->hold_ms);
}

static void hold_tick(u32 now)
{
    int c = R.hold_coil;
    if (c == NO_COIL)
        return;
    if (!R.live || GAME_tilt) {
        hold_off(" (the ball ended)");
        return;
    }
    if (!R.m[R.hold_owner].running) {
        hold_off(" (the mode ended)");
        return;
    }
    if (now >= R.hold_until) {
        hold_off(" (its time)");
        return;
    }
    if (now >= R.hold_next) {
        if (!GAME_coil_busy[c])                     /* the game always wins */
            GAME_coil_fire(GAME_this, c, R.hold_t);
        R.hold_next = now + R.hold_period;
    }
}

/* ------------------------------------------------------------------ balls (PAD-1469) */
static int trough_count(void)
{
    int k, n = 0;
    for (k = 0; k < 64; k++)
        if (bit_of(D.trough, k) && closed(k))
            n++;
    return n;
}

/* balls in play: one when the ball first went in, plus every ball that left the trough after */
static void count_balls(u32 now)
{
    int t = trough_count();
    if (!R.live) {
        R.base = 0xFF;
        R.inplay = 0;
        R.multi = 0;
        R.multi_since = 0;
        return;
    }
    if (R.base == 0xFF) {
        if (GAME_phase != 3)
            return;
        R.base = (u8)t;
    }
    R.inplay = t > R.base + 1 ? 0 : (u8)(R.base + 1 - t);
    if (R.inplay >= 2) {
        if (!R.multi_since)
            R.multi_since = now ? now : 1;
        if (now - R.multi_since >= 500)
            R.multi = 1;
        R.single_since = 0;
    } else {
        R.multi_since = 0;
        if (GAME_load_timer || GAME_ball_queue)
            R.single_since = 0;                     /* a drained ball being served back */
        else if (!R.single_since)
            R.single_since = now ? now : 1;
    }
}

/* the game's ball save raised to at least ms (it counts it down, and serves back a ball that
   drains inside it) */
static void save_at_least(u32 ms)
{
    if (GAME_save_timer < ms)
        GAME_save_timer = ms;
}

/* serve balls through the game's own queue until want are in play, inside the mode's save */
static void serve_tick(int i, u32 now)
{
    if (R.m[i].mb != 2)
        return;
    if (R.inplay >= 2)
        R.m[i].came = 1;
    if (now < R.m[i].mb_until) {
        save_at_least(R.m[i].mb_until - now);
        if (R.our_save_until < R.m[i].mb_until)
            R.our_save_until = R.m[i].mb_until;
        if (R.base != 0xFF && R.inplay + GAME_ball_queue < R.m[i].want && !GAME_load_timer) {
            GAME_ball_queue = GAME_ball_queue + 1;
            log2n(i, "a ball asked for, in play ", R.inplay, ", want ", R.m[i].want);
        }
    }
    if (!D.mode[i].mb_balls)
        return;                                     /* an add_ball alone: no one-ball-left end */
    if (!R.m[i].came && now >= R.m[i].mb_until + 20000) {
        stop(i, "the balls did not come)");
        return;
    }
    if (R.m[i].came && now >= R.m[i].mb_until + 3000) {
        if (R.inplay <= 1) {
            if (!R.m[i].one_since)
                R.m[i].one_since = now ? now : 1;
            else if (now - R.m[i].one_since >= 2000)
                stop(i, "one ball left)");
        } else {
            R.m[i].one_since = 0;
        }
    }
}

static void serve(int i, u32 now)
{
    const struct pad_mode *m = &D.mode[i];
    R.m[i].mb = 2;
    R.m[i].want = D.balls && m->mb_balls > D.balls ? D.balls : m->mb_balls;
    R.m[i].mb_until = now + 1000u * m->mb_save;
    R.m[i].one_since = 0;
    R.m[i].came = 0;
    if (any_bits(m->multiball_on))
        R.m[i].ends_at = 0;                         /* the balls came: one ball left ends it */
    log2n(i, "multiball, balls ", m->mb_balls, ", ball save s ", m->mb_save);
}

static void add_ball(int i, int sw, u32 now)
{
    const struct pad_mode *m = &D.mode[i];
    if (R.m[i].added >= (m->add_times ? m->add_times : 1)) {
        log3(i, "add_ball: no more this run, switch ", 1, sw, 0);
        return;
    }
    if (D.balls && R.inplay + GAME_ball_queue >= D.balls) {
        log3(i, "add_ball: every ball of the game is in play, switch ", 1, sw, 0);
        return;
    }
    R.m[i].added++;
    if (R.m[i].mb != 2) {
        R.m[i].mb = 2;
        R.m[i].want = R.inplay ? R.inplay : 1;
        R.m[i].mb_until = now;
        R.m[i].came = 0;
    }
    R.m[i].want++;
    if (R.m[i].mb_until < now + 2000)
        R.m[i].mb_until = now + 2000;
    log2n(i, "add_ball on switch ", sw, ", balls ", R.m[i].want);
}

/* ------------------------------------------------------------------ the mode logic */
static void stop(int i, const char *why)
{
    u32 now = GAME_millis;
    if (!R.m[i].running)
        return;
    R.m[i].running = 0;
    R.m[i].ended_at = now | 1;                      /* cooldown (PAD-1508): never 0 */
    {
        int k;                                      /* a mode inside this one ends with it */
        for (k = 0; k < D.count; k++)
            if (D.mode[k].inside == i + 1 && R.m[k].running)
                stop(k, "the mode it runs inside ended)");
    }
    if (R.m[i].save_until > now && GAME_save_timer <= R.m[i].save_until - now + 20) {
        /* our ball save ends with the mode: the game's own save gets what it had left */
        u32 left = R.m[i].game_save_until > now ? R.m[i].game_save_until - now : 0;
        GAME_save_timer = left;
        R.prev_save = left;
    }
    R.m[i].save_until = 0;
    R.m[i].mb = 0;
    if (R.hold_coil != NO_COIL && R.hold_owner == i)
        hold_off(" (the mode ended)");
    if (why) {
        log3(i, "ended (", 0, 0, why);
        log3(i, "total ", 1, R.m[i].total, 0);
        sound(i, 3);
    }
    if (R.shown == i) {
        int k;
        R.shown = 0xFF;
        for (k = 0; k < D.count; k++)
            if (R.m[k].running)
                R.shown = k;
    }
}

static void stop_all(const char *why)
{
    int i;
    for (i = 0; i < D.count; i++)
        stop(i, why);
    draw(GAME_millis);
}

static u32 score_now(void)
{
    return GAME_score_array[GAME_player & 3 ? GAME_player : 1];
}

static u32 award(u32 points)
{
    u32 before = score_now();
    GAME_add_score(points, 0);
    return score_now() - before;
}

static void start(int i, u32 now)
{
    const struct pad_mode *m = &D.mode[i];
    R.m[i].running = 1;
    R.m[i].hits = 0;
    R.m[i].made = 0;
    R.m[i].total = 0;
    R.m[i].added = 0;
    R.m[i].mb = 0;
    R.m[i].combo_i = 0;
    R.m[i].once = 3;
    R.m[i].runs++;
    R.m[i].at_done = 0;
    R.m[i].got[0] = R.m[i].got[1] = R.m[i].got[2] = 0;
    R.m[i].ends_at = m->seconds ? now + 1000u * m->seconds : 0;
    log3(i, "STARTED, seconds ", 1, m->seconds, 0);
    sound(i, 0);
    pulse(i, 0, now);
    if (m->hold_mode == HOLD_ON_START)
        hold_on(i, now);
    if (m->ball_save) {
        R.m[i].save_until = now + 1000u * m->ball_save;
        R.m[i].game_save_until = now + GAME_save_timer;
        save_at_least(1000u * m->ball_save);
        log3(i, "ball save s ", 1, m->ball_save, 0);
    }
    if (m->mb_balls) {
        if (any_bits(m->multiball_on))
            R.m[i].mb = 1;                          /* waits for a multiball_on hit */
        else
            serve(i, now);
    }
    R.shown = i;
    draw(now);
}

/* why mode i may not start (or count toward a start) now, or 0: start_once, and Spike 2's
   start_max, cooldown and start_needs (PAD-1508) */
static const char *blocked(int i, u32 now)
{
    const struct pad_mode *m = &D.mode[i];
    if ((m->flags & F_ONCE_GAME) && (R.m[i].once & 2))
        return "already ran this game (start_once)";
    if ((m->flags & F_ONCE_BALL) && (R.m[i].once & 1))
        return "already ran this ball (start_once)";
    if (m->start_max && R.m[i].runs >= m->start_max)
        return "started its start_max times this game";
    if (m->cooldown && R.m[i].ended_at && now - R.m[i].ended_at < 1000u * m->cooldown)
        return "cooling down";
    if (m->needs) {
        int k = m->needs - 1;
        if (k >= D.count || !(R.m[k].once & ((m->rules & RULE_NEEDS_BALL) ? 1 : 2)))
            return "its start_needs mode has not run";
    }
    if (m->inside && (m->inside - 1 >= D.count || !R.m[m->inside - 1].running))
        return "the mode it runs inside is not running";
    return 0;
}

/* a start switch hit or a start rule fired: it counts toward start_count; a switch start also
   waits for its start_also lines */
static void count_up_as(int i, const char *why, u32 n, u32 now, int is_switch, int count)
{
    const struct pad_mode *m = &D.mode[i];
    const char *no;
    int need = m->start_count ? m->start_count : 1, k, waiting = 0;
    if (R.m[i].running)
        return;
    no = blocked(i, now);
    if (no) {
        log3(i, why, 1, n, 0);
        log3(i, "  not counted: ", 0, 0, no);
        return;
    }
    if (count && R.m[i].hits < need) {
        R.m[i].hits++;
        log3(i, why, 1, n, 0);
        log3(i, "  hits ", 1, R.m[i].hits, 0);
    }
    if (R.m[i].hits < need)
        return;
    for (k = 0; k < m->also_n; k++)
        if (R.m[i].got[k] < m->also[k].count)
            waiting++;
    if (is_switch && waiting) {
        log3(i, "start shots made - waiting for start_also lines: ", 1, (u32)waiting, 0);
        return;
    }
    start(i, now);
}

static void count_up(int i, const char *why, u32 n, u32 now)
{
    count_up_as(i, why, n, now, 0, 1);
}

/* start_also (PAD-1508): a hit of one of its lines' switches counts, in any order */
static int also_hit(int i, int sw, u32 now)
{
    const struct pad_mode *m = &D.mode[i];
    int k, hit = 0, byte = sw >> 3, bit = 1 << (sw & 7);
    for (k = 0; k < m->also_n; k++) {
        const char *no;
        if (!(m->also[k].sw[byte] & bit) || R.m[i].got[k] >= m->also[k].count)
            continue;
        no = blocked(i, now);
        if (no) {
            log3(i, "start_also not counted: ", 0, 0, no);
            return 0;
        }
        R.m[i].got[k]++;
        hit = 1;
        log2n(i, "start_also ", (u32)(k + 1), ", hits ", R.m[i].got[k]);
    }
    return hit;
}

/* what a hit of sw pays while mode i runs: the first shot_points line holding it, else points
   when it is one of the shots; *scores 0 when it does not score (PAD-1508) */
static u32 value_of(int i, int sw, int *scores)
{
    const struct pad_mode *m = &D.mode[i];
    int k, byte = sw >> 3, bit = 1 << (sw & 7);
    for (k = 0; k < m->sp_n; k++)
        if (m->sp[k].sw[byte] & bit) {
            *scores = 1;
            return m->sp[k].points;
        }
    *scores = (m->shots[byte] & bit) != 0;
    return m->points;
}

static void raise_ev(int ev, u32 now)
{
    static const char *const name[7] = {"ball_start", "first_ball", "last_ball", "valid_playfield",
                                        "ball_saved", "extra_ball", "multiball_end"};
    int i, k;
    for (k = 0; k < 6; k++)
        if (ev & (1 << k))
            break;
    log3(-1, "event ", 0, 0, name[k]);
    for (i = 0; i < D.count; i++)
        if (!R.m[i].running && (D.mode[i].start_on & ev))
            count_up(i, "start_on event ", (u32)k, now);
}

static void shot(int i, int sw, u32 now, u32 value)
{
    const struct pad_mode *m = &D.mode[i];
    u32 got = award((m->rules & RULE_RISING) ? value * (u32)(R.m[i].made + 1) : value);
    R.m[i].made++;
    R.m[i].total += got;
    log3(i, "shot on switch ", 1, sw, 0);
    log3(i, "  points scored ", 1, got, 0);
    log3(i, "  player score ", 1, score_now(), 0);
    if (!m->shot_every || R.m[i].made % m->shot_every == 0)
        sound(i, 1);
    pulse(i, 1, now);
    if (m->hold_mode == HOLD_ON_SHOTS)
        hold_on(i, now);
    R.shown = i;
    if (m->complete && R.m[i].made >= m->complete) {
        u32 bonus = m->complete_points ? award(m->complete_points) : 0;
        R.m[i].total += bonus;
        log3(i, "COMPLETED, bonus ", 1, bonus, 0);
        log3(i, "total ", 1, R.m[i].total, 0);
        sound(i, 2);
        pulse(i, 2, now);
        stop(i, 0);
    }
    draw(now);
}

static void combo(int i, int sw, u32 now)
{
    const struct pad_mode *m = &D.mode[i];
    int k = R.m[i].combo_i;
    if (k && m->combo_seconds && now - R.m[i].combo_ms > 1000u * m->combo_seconds)
        k = 0;                                      /* too slow: from the first again (0: no limit) */
    if (sw == m->combo[k]) {
        k++;
    } else if (sw == m->combo[0]) {
        k = 1;
    } else {
        R.m[i].combo_i = (u8)k;
        return;                                     /* another switch between: no matter */
    }
    R.m[i].combo_ms = now;
    if (k >= m->combo_n) {
        R.m[i].combo_i = 0;
        count_up(i, "start_combo made, last switch ", (u32)sw, now);
        return;
    }
    R.m[i].combo_i = (u8)k;
}

static void on_switch(int sw, u32 now)
{
    int i, byte = sw >> 3, bit = 1 << (sw & 7);
    if (!R.valid_done && R.base != 0xFF && sw != D.lane && !(D.trough[byte] & bit)) {
        R.valid_done = 1;                           /* the ball's first playfield switch */
        raise_ev(EV_VALID_PLAYFIELD, now);
    }
    for (i = 0; i < D.count; i++) {
        const struct pad_mode *m = &D.mode[i];
        if (R.m[i].running) {
            if (R.m[i].mb == 1 && (m->multiball_on[byte] & bit))
                serve(i, now);
            if (m->add_ball[byte] & bit)
                add_ball(i, sw, now);
            if (m->hold_mode == HOLD_ON_SWITCHES && (m->hold_on[byte] & bit))
                hold_on(i, now);
            {
                int scores;
                u32 v = value_of(i, sw, &scores);
                if (scores)
                    shot(i, sw, now, v);
            }
            if (R.m[i].running && (m->end_shots[byte] & bit)) {
                log3(i, "end shot, switch ", 1, (u32)sw, 0);
                stop(i, "end shot)");
                draw(now);
            }
        } else {
            int also;
            if (m->combo_n)
                combo(i, sw, now);
            also = also_hit(i, sw, now);
            if (!R.m[i].running && (m->start[byte] & bit))
                count_up_as(i, "start switch ", (u32)sw, now, 1, 1);
            else if (also && !R.m[i].running && R.m[i].hits >= (m->start_count ? m->start_count : 1))
                count_up_as(i, "start_also met, switch ", (u32)sw, now, 1, 0);
        }
    }
}

/* a new ball: start counts (start_count_reset = ball) and start_once ball reset; its ball events
   wait for the ball in play */
static void new_ball(void)
{
    int i;
    for (i = 0; i < D.count; i++) {
        if (D.mode[i].flags & F_RESET_BALL)
            R.m[i].hits = R.m[i].got[0] = R.m[i].got[1] = R.m[i].got[2] = 0;
        R.m[i].once &= (u8)~1;
        R.m[i].combo_i = 0;
    }
    R.valid_done = 0;
    R.base = 0xFF;
    R.ev_pending = EV_BALL_START | (GAME_ball == 1 ? EV_FIRST_BALL : 0) |
                   (GAME_ball + 1 == GAME_ball_limit && !GAME_extra_balls ? EV_LAST_BALL : 0);
}

/* what the game says now: a new game, a ball, the ball's end, tilt, the game's end */
static void track(void)
{
    int active = GAME_ball != 0, i;
    int tilted = GAME_tilt != 0;
    if (active && !R.active) {
        for (i = 0; i < D.count; i++) {
            stop(i, 0);
            R.m[i].hits = 0;
            R.m[i].once = 0;
            R.m[i].score_done = 0;
            R.m[i].runs = 0;
            R.m[i].ended_at = 0;
            R.m[i].got[0] = R.m[i].got[1] = R.m[i].got[2] = 0;
        }
        R.player = R.ball = 0xFF;
        R.prev_extra = GAME_extra_balls;
        log3(-1, "new game: start counts reset", 0, 0, 0);
    }
    if (!active && R.active) {
        R.live = 0;
        stop_all("the game ended)");
        log3(-1, "game over", 0, 0, 0);
    }
    if (active && (GAME_player != R.player || GAME_ball != R.ball)) {
        if (R.live)
            stop_all("the ball ended)");
        R.player = GAME_player;
        R.ball = GAME_ball;
        R.live = GAME_ball_active && !tilted;
        log3(-1, "ball ", 1, GAME_ball, R.live ? " started" : " (not live)");
        if (R.live)
            new_ball();
    } else if (active && !R.live && GAME_ball_active && !tilted && R.tilted == 0) {
        R.live = 1;                         /* a ball made live again (ball_active back) */
        new_ball();
    }
    if (R.live && tilted && !R.tilted) {
        R.live = 0;
        stop_all("tilt)");
    }
    if (R.live && !GAME_ball_active) {
        R.live = 0;
        stop_all("the ball ended)");
    }
    R.active = active;
    R.tilted = tilted;
}

/* the game events that are not a switch: the ball in play, a ball save, an extra ball, a
   multiball's end, a score */
static void events(u32 now)
{
    int i, was_multi = R.multi;
    u32 save = GAME_save_timer;
    u8 extra = GAME_extra_balls;
    count_balls(now);
    if (R.live && R.ev_pending && GAME_phase == 3) {
        int ev = R.ev_pending, k;
        R.ev_pending = 0;
        for (k = 0; k < 3; k++)
            if (ev & (1 << k))
                raise_ev(1 << k, now);
    }
    if (R.live && !GAME_tilt && R.prev_save >= 50 && !save && now >= R.our_save_until &&
        (GAME_load_timer || GAME_ball_queue))
        raise_ev(EV_BALL_SAVED, now);               /* the game spent its save on a drain: it cut
                                                       the save and served the ball back at once */
    R.prev_save = save;
    if (R.active && extra > R.prev_extra)
        raise_ev(EV_EXTRA_BALL, now);
    R.prev_extra = extra;
    if (was_multi && R.live && R.inplay <= 1 && R.single_since && now - R.single_since >= 500) {
        R.multi = 0;                                /* one ball, settled: the multiball is over */
        raise_ev(EV_MULTIBALL_END, now);
    }
    if (!R.live)
        return;
    for (i = 0; i < D.count; i++) {
        const struct pad_mode *m = &D.mode[i];
        int p = GAME_player & 3 ? GAME_player : 1;
        if (m->start_score && !R.m[i].running && !(R.m[i].score_done & (1 << p)) && score_now() >= m->start_score) {
            R.m[i].score_done |= (u8)(1 << p);
            count_up(i, "start_score reached ", score_now(), now);
        }
    }
}

/* the mode's lamps over the game's: after houseKeeping filled the table for this ms */
static void lamps(u32 now)
{
    int i, n;
    for (i = 0; i < D.count; i++) {
        const struct pad_mode *m = &D.mode[i];
        u8 level = m->lamp_level, pat = m->pattern;
        u32 rate = m->lamp_blink ? m->lamp_blink : 4;
        int lit = 0, on = -1, count = 0;
        if (!R.m[i].running || !any_bits(m->lamps))
            continue;
        /* PAD-1508: lamp_pattern solid / blink / pulse (the level rising and falling) / chase (one
           lamp at a time, lowest number first), lamp_blink its rate */
        if (pat == PAT_AUTO)
            pat = m->lamp_blink ? PAT_BLINK : PAT_SOLID;
        if (pat == PAT_BLINK && ((now / (500u / rate)) & 1))
            level = 0;
        if (pat == PAT_PULSE) {
            u32 per = 1000u / rate, ph = now % per;
            level = (u8)((ph < per / 2 ? ph : per - ph) * 2u * m->lamp_level / per);
        }
        if (pat == PAT_CHASE) {
            for (n = 0; n < 64; n++)
                if (bit_of(m->lamps, n))
                    count++;
            on = (int)((now / (1000u / rate)) % (u32)(count ? count : 1));
        }
        for (n = 0; n < 64; n++)
            if (bit_of(m->lamps, n)) {
                GAME_lamp_ram[n] = (on < 0 || lit == on) ? level : 0;
                lit++;
            }
    }
}

static void init(u32 now)
{
    u8 *p = (u8 *)&R;
    u32 k;
    for (k = 0; k < sizeof R; k++)
        p[k] = 0;
    R.magic = RUN_MAGIC;
    R.shown = 0xFF;
    R.player = R.ball = 0xFF;
    R.base = 0xFF;
    R.hold_coil = NO_COIL;
    R.minute_at = now;
    for (k = 0; k < 8; k++)
        R.prev[k] = GAME_switch_ram[k];
    R.last_ms = now;
    log3(-1, "PAD modes runtime: modes ", 1, D.magic == DATA_MAGIC ? D.count : 0,
         D.magic == DATA_MAGIC && D.off ? " (turned off)" : 0);
}

static void tick(void)
{
    u32 now = GAME_millis;
    int i, k;
    if (R.magic != RUN_MAGIC || now < R.last_ms)
        init(now);                          /* power-up, or the game started again */
    if (D.magic != DATA_MAGIC || D.off || !D.count)
        return;
    if (now == R.last_ms && R.drawn_ms) {
        lamps(now);                         /* houseKeeping ran again this ms: ours over it again */
        return;
    }
    R.last_ms = now;
    track();
    events(now);
    for (k = 0; k < 8; k++) {
        u8 cur = GAME_switch_ram[k], rose = cur & ~R.prev[k];
        R.prev[k] = cur;
        if (rose && R.live && !GAME_tilt)
            for (i = 0; i < 8; i++)
                if (rose & (1 << i))
                    on_switch(k * 8 + i, now);
    }
    for (i = 0; i < D.count; i++) {
        if (!R.m[i].running)
            continue;
        if (R.m[i].ends_at && now < R.m[i].ends_at) {     /* sound_at (PAD-1508): at N s left */
            const struct pad_mode *m = &D.mode[i];
            for (k = 0; k < m->at_n; k++)
                if (!(R.m[i].at_done & (1 << k)) && m->at[k].secs < m->seconds &&
                    R.m[i].ends_at - now <= 1000u * m->at[k].secs) {
                    R.m[i].at_done |= (u8)(1 << k);
                    log3(i, "seconds left ", 1, m->at[k].secs, 0);
                    sound_named(i, "sound_at ", m->at[k].sound);
                }
        }
        if (R.m[i].ends_at && now >= R.m[i].ends_at)
            stop(i, "time ran out)");
        else
            serve_tick(i, now);
    }
    hold_tick(now);
    lamps(now);
    if (R.shown != 0xFF && R.m[R.shown].running && now - R.drawn_ms >= 100)
        draw(now);                          /* the time left: sent when it changes */
    else if (R.drawn_lines && (R.shown == 0xFF || !R.m[R.shown].running))
        draw(now);
}

/* every variable fits the RAM hooks.py gives the runtime (ram: 0x800 bytes) */
typedef char pad_run_fits[sizeof(struct run) <= 0x800 ? 1 : -1];

/* the game's call: its houseKeeping, then the modes */
void pad_entry(void *self) __attribute__((section(".text.entry")));
void pad_entry(void *self)
{
    GAME_tick_target(self);
    tick();
}

/* the header the build reads: magic, version, the entry, the data's address */
struct head {
    u32 magic, version;
    void (*entry)(void *);
    const struct pad_data *data;
    struct run *run;
};
const struct head PAD_HEAD __attribute__((section(".head"), used)) = {
    0x48444150u /* "PADH" */, 1, pad_entry, &PAD_DATA, &PAD_RUN,
};
