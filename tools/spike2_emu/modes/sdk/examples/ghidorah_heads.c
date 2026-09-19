/* ghidorah_heads.c - KING GHIDORAH: a BOSS BATTLE with health, for Godzilla (item 152).
 *
 * The three-headed monster (Ghidorah, 1964). Each head is a group of two shots and has 3
 * health. Only the LIT head takes damage, the lit head turns every 8 seconds, and a wounded
 * head that is left alone grows back. Sever all three and the Maser cannon gets one shot at
 * the body: the super jackpot.
 *
 *   START      Hit all three powerline targets (left, center, right, any order) in one ball.
 *              The third one starts the battle. Once a ball, twice a game per player. It
 *              waits while one of the game's own kaiju battles runs (two battles at once make
 *              no sense): the next powerline hit after that battle starts it.
 *   HEADS      LEFT HEAD   = Left ramp (2 damage) or Powerline left (1 damage)
 *              MIDDLE HEAD = Building (2 damage) or Powerline center (1 damage)
 *              RIGHT HEAD  = Right ramp (2 damage) or Powerline right (1 damage)
 *              Only the lit head is hurt: 1,000,000 a point of damage. Hitting a head that is
 *              not lit is a glancing blow: 250,000 and no damage. The lit head moves to the
 *              next living head every 8 s, and at once when it is severed.
 *   REGROW     A wounded head that takes no damage for 10 s grows 1 health back (and again
 *              every 10 s) - so finish a head before it turns away.
 *   SEVER      A head at 0 health is severed: 5,000,000 x heads severed so far (5M, 10M,
 *              15M) and 10 more seconds on the clock.
 *   CLOCK      50 s to sever all three (plus 10 s per severed head).
 *   FINAL BLOW All three severed: the Maser target is lit for 15 s. Hit it for the SUPER
 *              JACKPOT: 20,000,000 + 1,000,000 for every second left.
 *   ENDS       Won (the super jackpot), or GHIDORAH ESCAPES (the clock or the final blow
 *              runs out), or the ball drains, or the ball is tilted. The screen shows the total.
 *   INSERTS    The lit head's two inserts (its ramp or the Building, and its powerline) are
 *              GOLD, and their pattern is its health: solid at full health, blinking at 2,
 *              blinking fast at 1. A wounded head that is not lit PULSES GREEN: it is growing
 *              back. A full head that is not lit, and a severed one, are the game's own again.
 *              The final blow: MASER and MASER READY flash white (faster in its last 5 s).
 *              Everything is handed back the moment the mode ends, however it ends.
 *   DISPLAY    Priority 180: BATTLE IS LIT waits until it ends and the game's full-screen shot
 *              awards (LOOPS, POWERLINE ATTACK) are not shown over the panel; its jackpots, battle
 *              and multiball starts and the tilt warning still come through, and the panel is
 *              back when they end.
 *   LIGHTS     No light sweep: the port's example sweep recolours the inserts around the
 *              shots (measured, item 157), so it would make shots that pay nothing look lit.
 *   SCREEN     "HIT LEFT HEAD  41" alternating with "HEADS  L3  M1  RX" (X = severed).
 *
 * Emulator test triggers (checked twice a second):
 *   echo 1 > /dump/ghidorah_heads.start      start now (not counted against the limits)
 *   echo 1 > /dump/ghidorah_heads.stop       end now
 *   echo "Left ramp" > /dump/ghidorah_heads.shot   act as if the game dispatched that shot
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs -------------------------------------------------------------------------- */
#define MODE_NAME          "KING GHIDORAH"
#define FOLDER             "ghidorah_heads"
#define HEAD_HP            3
#define RUN_SECONDS        50
#define SEVER_ADDS_SECONDS 10
#define LIT_MOVES_MS       8000
#define REGROW_MS          10000
#define FINAL_SECONDS      15
#define DAMAGE_PAYS        1000000ull     /* a point of damage */
#define GLANCE_PAYS        250000ull      /* a head that is not lit */
#define SEVER_PAYS         5000000ull     /* x heads severed so far */
#define SUPER_BASE         20000000ull
#define SUPER_PER_SECOND   1000000ull
#define STARTS_PER_GAME    2
#define TOTAL_SHOWN_MS     6000

#define SCREEN_NODE "PadMode_" FOLDER "_Screen"
#define SCREEN_TEXT "PadMode_" FOLDER "_Screen.PadMode_" FOLDER "_Screen_Words"

#define N_HEADS 3
static const struct {
    const char *name, *tag, *big, *small;
} HEAD[N_HEADS] = {
    { "LEFT HEAD",   "L", "Left ramp",  "Powerline left" },
    { "MIDDLE HEAD", "M", "Building",   "Powerline center" },
    { "RIGHT HEAD",  "R", "Right ramp", "Powerline right" },
};
#define FINAL_SHOT "Maser target"
#define FINAL_INSERTS_TOO "MASER READY"   /* the insert beside MASER, tied to no shot by the game */
#define HURT_BLINK_MS      500            /* the lit head at 2 health */
#define DYING_BLINK_MS     180            /* ... at 1 */
#define REGROW_PULSE_MS    1200

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t big_mask[N_HEADS], small_mask[N_HEADS], final_mask;
static unsigned qual[5];              /* per player: bit i = powerline i hit this ball */
static unsigned ran_ball[5], ran_game[5];
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps;
static struct kit_screen screen = { .node_name = SCREEN_NODE, .text_name = SCREEN_TEXT, .alt_ms = 2000 };
static unsigned poll;

enum { PHASE_HEADS, PHASE_FINAL };
static struct {
    int on, phase, counted;
    unsigned player, hp[N_HEADS], lit, severed, hits;
    unsigned long last_damage[N_HEADS], lit_since;
    struct kit_timer clock, final_clock;
    uint64_t total;
} run;

/* ---- sound: the one place the mode's own clip, music and calls are played --------------------------
 * The build puts them on the card from the project's modes/ghidorah_heads/assets.json and names
 * them in ghidorah_heads.assets (pad_mode_assets.h). START plays its music and its start clip,
 * END fades its music out; each call is a cue the assets name. A cue the card does not carry
 * falls back to the game's own voice (time up) or to silence. The countdown (ten seconds, 5..1)
 * is always the game's own, through kit_timer. */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_START, CUE_DAMAGE, CUE_GLANCE, CUE_SEVER, CUE_REGROW, CUE_FINAL, CUE_SUPER, CUE_TIME_UP, CUE_END };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_START:   pa_start(&own); break;                     /* its music, its start clip */
    case CUE_SEVER:   pa_call(&own, "sever"); break;             /* a head severed */
    case CUE_REGROW:  pa_call(&own, "regrow"); break;            /* a wounded head grows back */
    case CUE_SUPER:   pa_call(&own, "won"); break;               /* the super jackpot: GHIDORAH DEFEATED */
    case CUE_TIME_UP:                                            /* GHIDORAH ESCAPES */
        if (!pa_call(&own, "lost")) pm_callout(pm_callout_id("time_up"));
        break;
    case CUE_END:     pa_end(&own); break;                       /* its music fades, the game's returns */
    default: break;                                              /* damage, glancing blow, final blow lit */
    }
}

/* ---- helpers ------------------------------------------------------------------------------------ */
static unsigned next_living(unsigned from)
{
    unsigned k, i;
    for (k = 1; k <= N_HEADS; k++) {
        i = (from + k) % N_HEADS;
        if (run.hp[i]) return i;
    }
    return from;
}

static uint64_t pay(uint64_t points)
{
    uint64_t got = pm_score_add(run.player, points);
    run.total += got;
    return got;
}

static uint64_t super_value(void)
{
    return SUPER_BASE + SUPER_PER_SECOND * kit_timer_seconds(&run.final_clock);
}

/* the inserts for the battle as it stands; every tick, only a change is sent */
static void show_lit(void)
{
    unsigned i;
    kit_lamps_begin(&lamps);
    if (run.phase == PHASE_FINAL) {
        unsigned ms = kit_timer_seconds(&run.final_clock) > 5 ? 150 : 80;
        kit_lamps_shot(&lamps, final_mask, KIT_WHITE, PM_LAMP_BLINK, ms);
        kit_lamps_name(&lamps, FINAL_INSERTS_TOO, KIT_WHITE, PM_LAMP_BLINK, ms);
    } else {
        for (i = 0; i < N_HEADS; i++) {
            uint64_t m = big_mask[i] | small_mask[i];
            if (!run.hp[i]) continue;                          /* severed: the game's own again */
            if (i == run.lit)
                kit_lamps_shot(&lamps, m, KIT_GOLD, run.hp[i] >= HEAD_HP ? PM_LAMP_SOLID : PM_LAMP_BLINK,
                               run.hp[i] >= 2 ? HURT_BLINK_MS : DYING_BLINK_MS);
            else if (run.hp[i] < HEAD_HP)
                kit_lamps_shot(&lamps, m, KIT_GREEN, PM_LAMP_PULSE, REGROW_PULSE_MS);   /* growing back */
        }
    }
    kit_lamps_commit(&lamps);
}

static void show_status(void)
{
    char a[KIT_WORDS], b[KIT_WORDS], n[24];
    unsigned i, k = 0;
    if (run.phase == PHASE_FINAL) {
        pm_snprintf(a, sizeof a, "SHOOT THE MASER %u", kit_timer_seconds(&run.final_clock));
        pm_snprintf(b, sizeof b, "SUPER %s", kit_num(n, sizeof n, super_value()));
    } else {
        pm_snprintf(a, sizeof a, "HIT %s %u", HEAD[run.lit].name, kit_timer_seconds(&run.clock));
        k = (unsigned)pm_snprintf(b, sizeof b, "HEADS");
        for (i = 0; i < N_HEADS; i++) {
            char hp[4];
            if (run.hp[i]) pm_snprintf(hp, sizeof hp, "%u", run.hp[i]);
            else kit_copy(hp, sizeof hp, "X");
            k += (unsigned)pm_snprintf(b + k, sizeof b - k, "  %s%s", HEAD[i].tag, hp);
        }
    }
    kit_screen_status(&screen, a, b);
}

/* ---- start and end ------------------------------------------------------------------------------- */
static int start(const char *why, int counted)
{
    const char *what = "";
    unsigned p = pm_player(), i;
    if (run.on) return 0;
    if (!pm_in_game() || p < 1 || p > 4) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (counted && kit_stock_busy(PM_STOCK_BATTLE, MODE_NAME, &what)) {
        pm_log("not started (%s): %s is running - it starts on the next powerline hit after it", why, what);
        return 0;
    }
    if (!kit_begin(MODE_NAME)) return 0;          /* another of our modes: pm_begin logged it */
    kit_display(KIT_DISPLAY_MODE);                /* first: before the screen and the clip */
    run.on = 1;
    run.counted = counted;
    run.player = p;
    run.phase = PHASE_HEADS;
    run.severed = run.hits = 0;
    run.total = 0;
    for (i = 0; i < N_HEADS; i++) {
        run.hp[i] = HEAD_HP;
        run.last_damage[i] = 0;
    }
    run.lit = 0;
    run.lit_since = pm_ms();
    kit_timer_set(&run.clock, RUN_SECONDS, 1);
    if (counted) {
        ran_ball[p]++;
        ran_game[p]++;
    }
    qual[p] = 0;
    kit_ledger_note(KIT_GHIDORAH, p, 0);
    kit_screen_show(&screen, 1);
    show_status();
    kit_screen_flash(&screen, 2500, "GHIDORAH ATTACKS");
    show_lit();
    sound(CUE_START);
    pm_log("START (%s): player %u, %u s, heads %u/%u/%u, lit %s, start %u this game, score %llu", why, p,
           RUN_SECONDS, run.hp[0], run.hp[1], run.hp[2], HEAD[run.lit].name, ran_game[p],
           (unsigned long long)pm_score(p));
    return 1;
}

static void end(const char *why, int won)
{
    char a[KIT_WORDS], n[24];
    if (!run.on) return;
    run.on = 0;
    kit_lamps_off(&lamps);                         /* every insert back to the game, at once */
    kit_end();
    kit_ledger_note(KIT_GHIDORAH, run.player, won);
    sound(CUE_END);
    pm_snprintf(a, sizeof a, "TOTAL %s", kit_num(n, sizeof n, run.total));
    kit_screen_status(&screen, a, won ? "GHIDORAH DEFEATED" : "GHIDORAH ESCAPES");
    screen.flash[0] = 0;
    kit_screen_hide_in(&screen, TOTAL_SHOWN_MS);
    pm_log("END (%s): %s, %u of %d heads severed, %u hits, total %llu, score %llu", why,
           won ? "WON" : "not won", run.severed, N_HEADS, run.hits, (unsigned long long)run.total,
           (unsigned long long)pm_score(run.player));
}

/* ---- the battle ------------------------------------------------------------------------------------ */
static void sever(unsigned i)
{
    char line[KIT_WORDS];
    uint64_t got;
    run.severed++;
    got = pay(SEVER_PAYS * run.severed);
    if (run.severed < N_HEADS)
        pm_log("%s SEVERED (%u of %d): +%llu, +%d s on the clock; the lit head: %s", HEAD[i].name, run.severed,
               N_HEADS, (unsigned long long)got, SEVER_ADDS_SECONDS, HEAD[next_living(i)].name);
    else
        pm_log("%s SEVERED (%u of %d): +%llu", HEAD[i].name, run.severed, N_HEADS, (unsigned long long)got);
    sound(CUE_SEVER);
    if (run.severed == N_HEADS) {
        run.phase = PHASE_FINAL;
        kit_timer_set(&run.final_clock, FINAL_SECONDS, 1);
        pm_log("FINAL BLOW: %s lit for %u s, super jackpot %llu", FINAL_SHOT, FINAL_SECONDS,
               (unsigned long long)super_value());
        kit_screen_flash(&screen, 2500, "FINAL BLOW: MASER");
        sound(CUE_FINAL);
    } else {
        kit_timer_add(&run.clock, SEVER_ADDS_SECONDS);
        run.lit = next_living(i);
        run.lit_since = pm_ms();
        pm_snprintf(line, sizeof line, "%s SEVERED", HEAD[i].name);
        kit_screen_flash(&screen, 2000, line);
    }
    show_lit();
}

static void head_hit(unsigned i, unsigned damage, const char *shot)
{
    char line[KIT_WORDS];
    uint64_t got;
    if (!run.hp[i]) {
        pm_log("%s: %s is already severed", shot, HEAD[i].name);
        return;
    }
    run.hits++;
    if (i != run.lit) {
        got = pay(GLANCE_PAYS);
        pm_log("%s: glancing blow on %s (lit: %s) +%llu", shot, HEAD[i].name, HEAD[run.lit].name,
               (unsigned long long)got);
        pm_snprintf(line, sizeof line, "HIT THE %s", HEAD[run.lit].name);
        kit_screen_flash(&screen, 1200, line);
        sound(CUE_GLANCE);
        return;
    }
    if (damage > run.hp[i]) damage = run.hp[i];
    run.hp[i] -= damage;
    run.last_damage[i] = pm_ms();
    got = pay(DAMAGE_PAYS * damage);
    pm_log("%s: %s -%u (health %u) +%llu", shot, HEAD[i].name, damage, run.hp[i], (unsigned long long)got);
    if (run.hp[i] == 0) {
        sever(i);
    } else {
        pm_snprintf(line, sizeof line, "%s -%u", HEAD[i].name, damage);
        kit_screen_flash(&screen, 1200, line);
        sound(CUE_DAMAGE);
        show_lit();                                /* its inserts blink faster, at once */
    }
}

static void battle_shot(uint64_t shot)
{
    unsigned i;
    if (run.phase == PHASE_FINAL) {
        if (final_mask && (shot & final_mask) && kit_fresh(&db, final_mask)) {
            char line[KIT_WORDS], n[24];
            uint64_t asked = super_value(), got = pay(asked);
            pm_log("SUPER JACKPOT: %s with %u s left, +%llu (asked %llu)", FINAL_SHOT,
                   kit_timer_seconds(&run.final_clock), (unsigned long long)got, (unsigned long long)asked);
            pm_snprintf(line, sizeof line, "SUPER %s", kit_num(n, sizeof n, got));
            kit_screen_flash(&screen, 2500, line);
            sound(CUE_SUPER);
            end("super jackpot", 1);
        }
        return;
    }
    for (i = 0; i < N_HEADS && run.on && run.phase == PHASE_HEADS; i++) {
        if (big_mask[i] && (shot & big_mask[i]) && kit_fresh(&db, big_mask[i])) head_hit(i, 2, HEAD[i].big);
        if (run.phase != PHASE_HEADS) break;
        if (small_mask[i] && (shot & small_mask[i]) && kit_fresh(&db, small_mask[i])) head_hit(i, 1, HEAD[i].small);
    }
}

/* ---- the callbacks ------------------------------------------------------------------------------ */
static void on_init(void)
{
    unsigned i;
    for (i = 0; i < N_HEADS; i++) {
        big_mask[i] = pm_shot(HEAD[i].big);
        small_mask[i] = pm_shot(HEAD[i].small);
        if (!big_mask[i] || !small_mask[i])
            pm_log("this port has no \"%s\" or \"%s\": the %s can only be hurt by the other", HEAD[i].big,
                   HEAD[i].small, HEAD[i].name);
    }
    final_mask = pm_shot(FINAL_SHOT);
    if (!final_mask) pm_log("this port has no \"%s\": the final blow cannot be made", FINAL_SHOT);
    pa_load(&own);
    pm_log("ready on %s %s: starts on the three powerlines in one ball; heads L 0x%llx/0x%llx M 0x%llx/0x%llx "
           "R 0x%llx/0x%llx, final 0x%llx", pm_game(), pm_version(),
           (unsigned long long)big_mask[0], (unsigned long long)small_mask[0], (unsigned long long)big_mask[1],
           (unsigned long long)small_mask[1], (unsigned long long)big_mask[2], (unsigned long long)small_mask[2],
           (unsigned long long)final_mask);
}

static void qualify_shot(uint64_t shot, unsigned p)
{
    char line[KIT_WORDS];
    unsigned i, n = 0;
    for (i = 0; i < N_HEADS; i++) {
        if (!small_mask[i] || !(shot & small_mask[i]) || !kit_fresh(&db, small_mask[i])) continue;
        if (ran_ball[p] || ran_game[p] >= STARTS_PER_GAME) {
            pm_log("%s: not counted - %s", HEAD[i].small,
                   ran_ball[p] ? "it already ran this ball" : "it already ran twice this game");
            return;
        }
        qual[p] |= 1u << i;
        for (n = 0, i = 0; i < N_HEADS; i++) n += (qual[p] >> i) & 1u;
        pm_log("powerlines %u of %d (player %u)", n, N_HEADS, p);
        if (n == N_HEADS) {
            start("three powerlines", 1);
        } else if (!kit_running) {
            pm_snprintf(line, sizeof line, "POWERLINES %u OF %d", n, N_HEADS);
            kit_screen_note(&screen, 2000, line);
        }
        return;
    }
}

static void on_shot(uint64_t shot)
{
    unsigned p = pm_player();
    if (!pm_in_game() || p < 1 || p > 4) return;
    if (!run.on) {
        qualify_shot(shot, p);
        return;
    }
    if (p == run.player) battle_shot(shot);
}

static void check_triggers(void)
{
    char name[48];
    if (pm_trigger(FOLDER ".start")) start("trigger file", 0);
    if (pm_trigger(FOLDER ".stop")) end("trigger file", 0);
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t m = pm_shot(name);
        pm_log("shot trigger: \"%s\" (0x%llx)", name, (unsigned long long)m);
        if (m) on_shot(m);
    }
}

static void battle_tick(void)
{
    unsigned long now = pm_ms();
    unsigned i;
    char line[KIT_WORDS];
    if (run.phase == PHASE_FINAL) {
        if (kit_timer_tick(&run.final_clock)) {
            sound(CUE_TIME_UP);
            end("the final blow was not made", 0);
            return;
        }
        show_status();
        show_lit();
        return;
    }
    if (kit_timer_tick(&run.clock)) {
        sound(CUE_TIME_UP);
        end("time ran out", 0);
        return;
    }
    for (i = 0; i < N_HEADS; i++) {           /* a wounded head left alone grows back */
        if (!run.hp[i] || run.hp[i] >= HEAD_HP || now - run.last_damage[i] < REGROW_MS) continue;
        run.hp[i]++;
        run.last_damage[i] = now;
        pm_log("%s REGROWS: health %u", HEAD[i].name, run.hp[i]);
        pm_snprintf(line, sizeof line, "%s REGROWS", HEAD[i].name);
        kit_screen_flash(&screen, 1500, line);
        sound(CUE_REGROW);
    }
    if (now - run.lit_since >= LIT_MOVES_MS) {  /* Ghidorah turns */
        unsigned was = run.lit;
        run.lit = next_living(run.lit);
        run.lit_since = now;
        if (run.lit != was) {
            pm_log("the lit head moves: %s -> %s", HEAD[was].name, HEAD[run.lit].name);
            show_lit();
        }
    }
    show_status();
    show_lit();
}

static void on_tick(void)
{
    unsigned p;
    kit_screen_tick(&screen);
    pa_tick(&own);
    if (++poll % KIT_POLL == 0) check_triggers();
    if (kit_new_game(&game)) {
        for (p = 0; p < 5; p++) qual[p] = ran_ball[p] = ran_game[p] = 0;
        pm_log("new game: counts cleared");
    }
    if (!run.on) return;
    if (!pm_in_game() || pm_player() != run.player) {
        end("the game moved on", 0);
        return;
    }
    battle_tick();
}

static void on_ball_end(void)
{
    unsigned p;
    end("ball ended", 0);
    for (p = 0; p < 5; p++) qual[p] = ran_ball[p] = 0;
}

static void on_event(unsigned id)
{
    if (kit_is_tilt(id)) end("tilted", 0);        /* its lights go dark with the game's */
}

static const struct pm_mode ghidorah_heads = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(ghidorah_heads);
