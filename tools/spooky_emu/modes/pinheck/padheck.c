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
extern void GAME_add_score(u32 points);
extern void GAME_play_sfx(void *self, int channel, int folder, int clip0, int clip1, int priority);
extern void GAME_text_str(void *self, int zero, int column, int line, const char *s, int colour);
extern void GAME_text_show(void *self, int which, int on);
extern void GAME_link_send(void *self, int cmd);
extern u8 GAME_this[];
extern volatile u8 GAME_data_out[16];
extern volatile u8 GAME_switch_ram[8];
extern volatile u32 GAME_millis;
extern volatile u32 GAME_score_array[5];
extern volatile u8 GAME_player, GAME_ball, GAME_ball_active, GAME_tilt;

#define U1STA (*(volatile u32 *)0xBF806010)
#define U1TXREG (*(volatile u32 *)0xBF806020)

/* ------------------------------------------------------------------ the modes (the build) */
#define MAX_MODES 24
#define PANEL_NONE 0
#define PANEL_MIDDLE 1
#define PANEL_BOTTOM 2
#define PANEL_TOP 3

struct pad_mode {               /* 64 bytes, written by mkspkmodes.py (pinheck_data) */
    char title[16];             /* the panel's title, NUL-padded */
    u8 start[8], shots[8];      /* switch bitmaps, as GAME_switch_ram */
    u16 start_count, seconds, complete;
    u8 panel, flags;
    u32 points, complete_points;
    char sound[4][4];           /* start, shot, complete, end: 3 letters + NUL, "" none */
};

struct pad_data {
    u32 magic;                  /* 'PHM1' */
    u8 count, off, pad0, pad1;
    char names[MAX_MODES][20];  /* the .mode file names, for the log */
    struct pad_mode mode[MAX_MODES];
};

#define DATA_MAGIC 0x314D4850u  /* "PHM1" */
extern const struct pad_data PAD_DATA;

/* ------------------------------------------------------------------ our variables */
struct run {
    u32 magic, last_ms;
    u8 prev[8];
    u8 live, active, player, ball, tilted, shown, drawn_lines;
    u32 drawn_ms, drawn_key;
    struct {
        u8 running;
        u16 hits, made;
        u32 total, ends_at;
    } m[MAX_MODES];
};

#define RUN_MAGIC 0x50414453u   /* "PADS" */
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
    char b[96], *p = b;
    p = put_str(p, "[pad] ", 8);
    if (i >= 0)
        p = put_str(put_str(p, D.names[i], 20), ": ", 2);
    p = put_str(p, what, 48);
    if (has_n)
        p = put_num(p, n);
    if (tail)
        p = put_str(p, tail, 24);
    put_str(p, "\r\n", 2);
    say(b);
}

/* ------------------------------------------------------------------ the game's sound */
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
    int k;
    GAME_data_out[0] = (u8)line;
    for (k = 1; k < 9; k++)
        GAME_data_out[k] = 0xFF;
    for (; k < 15; k++)
        GAME_data_out[k] = 0;
    GAME_link_send(GAME_this, 6);
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
    if (n > 32)
        n = 32;
    for (k = 0; k < n; k++)
        b[k] = s[k];
    b[n] = 0;
    GAME_text_str(GAME_this, 0, (32 - n) / 2, line, b, 255);
}

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

static int first_line(int panel)
{
    return panel == PANEL_TOP ? 0 : panel == PANEL_BOTTOM ? 6 : 3;
}

static void undraw(void)
{
    if (!R.drawn_lines)
        return;
    text_line_clear(R.drawn_lines - 1);
    text_line_clear(R.drawn_lines);
    GAME_text_show(GAME_this, 3, 0);
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
    p = put_grouped(p, R.m[i].total);
    if (m->seconds) {
        u32 left = R.m[i].ends_at > now ? (R.m[i].ends_at - now + 999) / 1000 : 0;
        p = put_str(p, "  ", 2);
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
    GAME_text_show(GAME_this, 3, 1);
    R.drawn_lines = line + 1;
    text_line_clear(line);
    centred(line, m->title, len_of(m->title, 16));
    text_line_clear(line + 1);
    centred(line + 1, b, (int)(p - b));
    R.drawn_ms = now;
}

/* ------------------------------------------------------------------ the mode logic */
static void stop(int i, const char *why)
{
    if (!R.m[i].running)
        return;
    R.m[i].running = 0;
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
    GAME_add_score(points);
    return score_now() - before;
}

static void start(int i, u32 now)
{
    R.m[i].running = 1;
    R.m[i].hits = 0;
    R.m[i].made = 0;
    R.m[i].total = 0;
    R.m[i].ends_at = D.mode[i].seconds ? now + 1000u * D.mode[i].seconds : 0;
    log3(i, "STARTED, seconds ", 1, D.mode[i].seconds, 0);
    sound(i, 0);
    R.shown = i;
    draw(now);
}

static void shot(int i, int sw, u32 now)
{
    const struct pad_mode *m = &D.mode[i];
    u32 got = award(m->points);
    R.m[i].made++;
    R.m[i].total += got;
    log3(i, "shot on switch ", 1, sw, 0);
    log3(i, "  points scored ", 1, got, 0);
    log3(i, "  player score ", 1, score_now(), 0);
    sound(i, 1);
    R.shown = i;
    if (m->complete && R.m[i].made >= m->complete) {
        u32 bonus = m->complete_points ? award(m->complete_points) : 0;
        R.m[i].total += bonus;
        log3(i, "COMPLETED, bonus ", 1, bonus, 0);
        log3(i, "total ", 1, R.m[i].total, 0);
        sound(i, 2);
        stop(i, 0);
    }
    draw(now);
}

static void on_switch(int sw, u32 now)
{
    int i, byte = sw >> 3, bit = 1 << (sw & 7);
    for (i = 0; i < D.count; i++) {
        const struct pad_mode *m = &D.mode[i];
        if (R.m[i].running) {
            if (m->shots[byte] & bit)
                shot(i, sw, now);
        } else if (m->start[byte] & bit) {
            R.m[i].hits++;
            log3(i, "start switch ", 1, sw, 0);
            log3(i, "  hits ", 1, R.m[i].hits, 0);
            if (R.m[i].hits >= (m->start_count ? m->start_count : 1))
                start(i, now);
        }
    }
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
        }
        R.player = R.ball = 0xFF;
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
    } else if (active && !R.live && GAME_ball_active && !tilted && R.tilted == 0) {
        R.live = 1;                         /* a ball made live again (ball_active back) */
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

static void init(u32 now)
{
    u8 *p = (u8 *)&R;
    u32 k;
    for (k = 0; k < sizeof R; k++)
        p[k] = 0;
    R.magic = RUN_MAGIC;
    R.shown = 0xFF;
    R.player = R.ball = 0xFF;
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
    if (now == R.last_ms && R.drawn_ms)
        return;                             /* once a millisecond */
    R.last_ms = now;
    if (D.magic != DATA_MAGIC || D.off || !D.count)
        return;
    track();
    for (k = 0; k < 8; k++) {
        u8 cur = GAME_switch_ram[k], rose = cur & ~R.prev[k];
        R.prev[k] = cur;
        if (rose && R.live && !GAME_tilt)
            for (i = 0; i < 8; i++)
                if (rose & (1 << i))
                    on_switch(k * 8 + i, now);
    }
    for (i = 0; i < D.count; i++)
        if (R.m[i].running && R.m[i].ends_at && now >= R.m[i].ends_at)
            stop(i, "time ran out)");
    if (R.shown != 0xFF && R.m[R.shown].running && now - R.drawn_ms >= 100)
        draw(now);                          /* the time left: sent when it changes */
    else if (R.drawn_lines && (R.shown == 0xFF || !R.m[R.shown].running))
        draw(now);
}

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
