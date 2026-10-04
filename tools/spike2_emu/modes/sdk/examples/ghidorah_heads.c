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
 *              no sense) or a multiball does (PAD-347: the game's, or two balls in play): the next
 *              powerline hit after it starts it.
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
 *              awards (LOOPS, POWERLINE ATTACK) are not shown over it; its jackpots, battle and
 *              multiball starts and the tilt warning still come through.
 *   THE GLASS  (hud-layers) As the game shows its own battles: Ghidorah's arrival full screen, then
 *              Ghidorah over burning Yokohama looping BEHIND the score panel (the backdrop). At the
 *              edges: the three heads' health across the top (LEFT / MIDDLE / RIGHT HEAD, the lit
 *              one marked), the GHIDORAH timer badge on the left, the heads severed on the right,
 *              KING GHIDORAH and what to shoot above the score panel. A sever and a regrowth play
 *              their clip behind the HUD with a big award line; the ending is full screen (Ghidorah
 *              falling, or blasting Godzilla), then the total.
 *   LIGHTS     Its own shows: at the start, gold lightning strikes the playfield in the dark and
 *              bursts from the Building; won, a white burst into a turning rainbow; lost, gold
 *              rising away up the playfield. No light sweep: the port's example sweep recolours
 *              the inserts around the shots (item 157).
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
#define TOTAL_SHOWN_MS     10000          /* the ending clip (5 s) full screen, then the total */


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
static struct kit_hud hud = { .slug = FOLDER };
static struct kit_show show;

/* ---- light shows (hud-layers): unique to KING GHIDORAH, gold and white -------------------------- */
#define GHID_GOLD      PM_RGB(255, 175, 0)
#define GHID_EMBER     PM_RGB(90, 30, 0)
static const struct kit_fx_step SHOW_START[] = {
    { KIT_FX_BOLTS,   1500, GHID_GOLD, 0, KIT_AT_CENTER, 190, KIT_GI_DARK },        /* gravity beams strike */
    { KIT_FX_STROBE,   500, KIT_WHITE, GHID_GOLD, KIT_AT_CENTER, 60, KIT_GI_FLASH },
    { KIT_FX_BURST,    800, GHID_GOLD, GHID_EMBER, KIT_AT_BUILDING, 0, KIT_GI_DARK },  /* from the Building */
    { KIT_FX_FADE_OUT, 400, GHID_EMBER, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_WON[] = {
    { KIT_FX_STROBE,   400, KIT_WHITE, 0, KIT_AT_CENTER, 50, KIT_GI_FLASH },
    { KIT_FX_BURST,    700, KIT_WHITE, GHID_GOLD, KIT_AT_MASER, 0, KIT_GI_DARK },      /* the final blow */
    { KIT_FX_RAINBOW, 1800, 0, 0, KIT_AT_CENTER, 60, KIT_GI_KEEP },
    { KIT_FX_FADE_OUT, 500, GHID_GOLD, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_LOST[] = {
    { KIT_FX_SWEEP_UP,   900, GHID_GOLD, GHID_EMBER, KIT_AT_CENTER, 0, KIT_GI_DARK },  /* Ghidorah flies off */
    { KIT_FX_SWEEP_UP,   900, GHID_GOLD, 0, KIT_AT_CENTER, 0, KIT_GI_DARK },
    { KIT_FX_SPARKLE,    700, GHID_GOLD, 0, KIT_AT_CENTER, 0, KIT_GI_DARK },
    { KIT_FX_FADE_OUT,   400, GHID_EMBER, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
#define N_STEPS(a) (int)(sizeof (a) / sizeof (a)[0])
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
    case CUE_START:   pa_start(&own); break;                     /* its music, its intro, then the loop */
    case CUE_SEVER:                                              /* a head severed */
        pa_call(&own, "sever");
        pa_clip_event(&own, "sever");
        break;
    case CUE_REGROW:                                             /* a wounded head grows back */
        pa_call(&own, "regrow");
        pa_clip_event(&own, "regrow");
        break;
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
    char line[KIT_HUD_WORDS];
    unsigned i;
    if (run.phase == PHASE_FINAL) {
        char n[24];
        kit_hud_title(&hud, "KING GHIDORAH", "FINAL BLOW: SHOOT THE MASER");
        pm_snprintf(line, sizeof line, "%s", kit_short(n, sizeof n, super_value()));
        kit_hud_counter(&hud, 0, 0, 0, 0);
        kit_hud_counter(&hud, 1, "SUPER JACKPOT", line, "MASER TARGET");
        kit_hud_counter(&hud, 2, 0, 0, 0);
        kit_hud_timer(&hud, (int)kit_timer_seconds(&run.final_clock));
    } else {
        pm_snprintf(line, sizeof line, "SHOOT THE %s", HEAD[run.lit].name);
        kit_hud_title(&hud, "KING GHIDORAH", line);
        for (i = 0; i < N_HEADS; i++) {
            char hp[8];
            if (run.hp[i]) pm_snprintf(hp, sizeof hp, "%u", run.hp[i]);
            else kit_copy(hp, sizeof hp, "X");
            kit_hud_counter(&hud, (int)i, HEAD[i].name, hp,
                            !run.hp[i] ? "SEVERED" : i == run.lit ? ">> LIT <<" : "HEALTH");
        }
        kit_hud_timer(&hud, (int)kit_timer_seconds(&run.clock));
    }
    kit_hud_gauge(&hud, (int)run.severed, "SEVERED");
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
    (void)what;
    if (counted && kit_wait_game(MODE_NAME, why, "the next powerline hit after it starts it")) return 0;   /* PAD-347 */
    if (!kit_begin(MODE_NAME)) return 0;          /* another of our modes: pm_begin logged it */
    kit_display(KIT_DISPLAY_MODE);                /* first: before the screen and the clip */
    kit_isolate_list(own.give_way, own.block_ids, own.block_n);   /* PAD-347/363: the game's modes wait for it */
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
    kit_hud_begin(&hud, "KING GHIDORAH", "");
    show_status();
    kit_hud_award(&hud, 3000, "GHIDORAH ATTACKS", "SEVER ALL THREE HEADS");
    show_lit();
    kit_show_start(&show, "ghidorah start", SHOW_START, N_STEPS(SHOW_START));
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
    kit_end_after(TOTAL_SHOWN_MS);      /* the ending clip and the total keep the screen */
    kit_ledger_note(KIT_GHIDORAH, run.player, won);
    sound(CUE_END);
    pa_clip_full(&own, won ? "won" : "lost");      /* the ending, full screen */
    kit_show_start(&show, won ? "ghidorah won" : "ghidorah lost", won ? SHOW_WON : SHOW_LOST,
                   won ? N_STEPS(SHOW_WON) : N_STEPS(SHOW_LOST));
    pm_snprintf(a, sizeof a, "%s", kit_num(n, sizeof n, run.total));
    kit_hud_title(&hud, won ? "GHIDORAH DEFEATED" : "GHIDORAH ESCAPES", " ");
    kit_hud_counter(&hud, 0, 0, 0, 0);
    kit_hud_counter(&hud, 1, 0, 0, 0);
    kit_hud_counter(&hud, 2, 0, 0, 0);
    kit_hud_timer(&hud, -1);
    kit_hud_gauge(&hud, -1, 0);
    kit_hud_award(&hud, TOTAL_SHOWN_MS, a, "KING GHIDORAH TOTAL");
    kit_hud_hide_in(&hud, TOTAL_SHOWN_MS);
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
        kit_hud_award(&hud, 3000, "ALL HEADS SEVERED", "FINAL BLOW: THE MASER");
        sound(CUE_FINAL);
    } else {
        kit_timer_add(&run.clock, SEVER_ADDS_SECONDS);
        run.lit = next_living(i);
        run.lit_since = pm_ms();
        {
            char n[24], sub[KIT_HUD_WORDS];
            pm_snprintf(line, sizeof line, "%s SEVERED", HEAD[i].name);
            pm_snprintf(sub, sizeof sub, "%s   +%d SECONDS", kit_num(n, sizeof n, got), SEVER_ADDS_SECONDS);
            kit_hud_award(&hud, 2500, line, sub);
        }
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
        kit_hud_award(&hud, 1200, "GLANCING BLOW", line);
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
        {
            char n[24];
            pm_snprintf(line, sizeof line, "%s -%u", HEAD[i].name, damage);
            kit_hud_award(&hud, 1300, line, kit_num(n, sizeof n, got));
        }
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
            (void)line;
            (void)n;
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
            kit_hud_note(&hud, 2000, line, "KING GHIDORAH");
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
        kit_hud_award(&hud, 1800, line, "FINISH IT BEFORE IT TURNS");
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
    kit_hud_tick(&hud);
    kit_show_tick(&show, &lamps);
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
    if (kit_game_began()) {                        /* PAD-347: isolated - the game began one of its own */
        end("the game's own mode began", 0);
        kit_end_now();
        return;
    }
    battle_tick();
}

static void on_ball_end(void)
{
    unsigned p;
    end("ball ended", 0);
    kit_end_now();
    for (p = 0; p < 5; p++) qual[p] = ran_ball[p] = 0;
}

static void on_event(unsigned id)
{
    if (kit_is_tilt(id)) {
        end("tilted", 0);                          /* its lights go dark with the game's */
        kit_end_now();
    }
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
