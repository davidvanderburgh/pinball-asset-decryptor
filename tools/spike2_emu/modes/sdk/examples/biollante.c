/* biollante.c - BIOLLANTE: a switch frenzy whose SAP JACKPOT the vine banks collect (PAD-379, for Godzilla).
 * Modelled on Lyman Sheats' switch frenzies: The Walking Dead's Blood Bath (every switch scores and piles into a
 * jackpot collected by clearing the drop targets), Metallica's FUEL, Elvira's House of Horrors' Manster, and his
 * generous clocks (a lit shot with under 15 s puts it back to 15; EHoH's Haunts pause in the bumpers).
 *
 * Godzilla vs. Biollante (1989): a rose spliced with Godzilla's cells. Her ROSE form spreads vines and acid sap;
 * cut her down and she comes back as the BEAST.
 *
 *   LIGHT IT   6 ramp shots (either ramp) in a game; the next time 8, then 10. It starts at once.
 *   THE SAP    A 40 s clock. EVERY playfield switch scores the switch value (100,000, +25,000 for each vine bank
 *              cut) and adds it to the SAP JACKPOT.
 *   THE VINES  Two banks of vines: the three SHIELD targets and the three POWERLINE targets. A target hit is
 *              a vine cut; a whole bank cut COLLECTS the SAP JACKPOT times the banks cut so far in the mode
 *              (x1, x2, x3), puts the jackpot back to 0 and grows the bank's vines back. A vine cut with under
 *              15 s on the clock puts it back to 15; each pop bumper hit gives a second back (up to 40).
 *   BEAST FORM After three collects she comes back as the BEAST: 20 s, and the BUILDING is the FINAL BLOW,
 *              worth everything the three collects paid. The switches still score.
 *   ENDS       The final blow (BIOLLANTE IS FREE); the clock (she withers: you keep what you scored); a drain;
 *              a tilt; one of the game's own modes beginning.
 *   THE GLASS  The rose rising from the lake, full screen; her vines swaying behind the score panel; PER
 *              SWITCH, SAP JACKPOT and VINES CUT at the edges, the six vines on the right edge's gauge, the
 *              clock in the badge. A vine cut plays her tendrils burning, a collect the sap spraying; the
 *              beast and the endings are full screen.
 *   INSERTS    The vines still standing green; the BEAST: the BUILDING blinking gold, faster as it runs out.
 *   DISPLAY    Priority 180.
 *
 * Emulator test triggers: /dump/biollante.start, .stop, .shot "<shot name>", .beast (the beast form now).
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "BIOLLANTE"
#define FOLDER             "biollante"
#define FINAL_SHOT         "Building"
#define RAMPS_FIRST        6
#define RAMPS_STEP         2
#define RUN_SECONDS        40
#define LIT_SHOT_FLOOR     15
#define POP_BACK_MS        1000
#define SWITCH_VALUE       100000ull
#define SWITCH_STEP        25000ull
#define COLLECTS           3
#define BEAST_SECONDS      20
#define CUT_CLIP_GAP_MS    4000
#define TOTAL_SHOWN_MS     10000

static const char *const RAMPS[2] = { "Left ramp", "Right ramp" };
#define N_BANKS 2
static const char *const BANK[N_BANKS][3] = {
    { "Shield target left", "Shield target center", "Shield target right" },
    { "Powerline left", "Powerline center", "Powerline right" },
};
static const char *const BANK_SAYS[N_BANKS] = { "THE SHIELD VINES", "THE POWERLINE VINES" };

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t ramp_mask, final_mask, pop_mask, vine_mask[N_BANKS][3];
static unsigned ramps[5], plays[5];
static int waiting[5];
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps;
static struct kit_hud hud = { .slug = FOLDER };
static struct kit_show show_fx;
static unsigned poll;

enum { PHASE_ROSE, PHASE_BEAST };
static struct {
    int on, phase, won;
    unsigned player, cut[N_BANKS], collects, switches;
    uint64_t sap, collected, total;
    unsigned long cut_clip_at;
    struct kit_timer clock;
} run;

/* ---- light shows: rose red and vine green -------------------------------------------------------- */
#define BI_ROSE        PM_RGB(255, 20, 70)
#define BI_VINE        PM_RGB(20, 200, 40)
#define BI_DEEP        PM_RGB(0, 40, 10)
#define BI_SPORE       PM_RGB(255, 230, 120)
static const struct kit_fx_step SHOW_START[] = {
    { KIT_FX_SWEEP_UP,  900, BI_VINE, BI_DEEP, KIT_AT_CENTER, 0, KIT_GI_DARK },        /* the vines climb */
    { KIT_FX_BURST,     900, BI_ROSE, BI_VINE, KIT_AT_BUILDING, 0, KIT_GI_DARK },      /* the rose opens */
    { KIT_FX_PULSE,     700, BI_ROSE, BI_DEEP, KIT_AT_CENTER, 200, KIT_GI_KEEP },
    { KIT_FX_FADE_OUT,  300, BI_VINE, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_COLLECT[] = {
    { KIT_FX_SPARKLE,   700, BI_SPORE, BI_VINE, KIT_AT_CENTER, 0, KIT_GI_FLASH },      /* the sap sprays */
    { KIT_FX_FADE_OUT,  300, BI_VINE, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_BEAST[] = {
    { KIT_FX_STROBE,    500, BI_ROSE, 0, KIT_AT_CENTER, 60, KIT_GI_FLASH },
    { KIT_FX_IMPLODE,   800, BI_ROSE, BI_DEEP, KIT_AT_BUILDING, 0, KIT_GI_DARK },      /* the jaws close */
    { KIT_FX_FIRE,      900, BI_VINE, BI_DEEP, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_WON[] = {      /* the spores rise to the stars */
    { KIT_FX_SWEEP_UP, 1200, BI_SPORE, BI_DEEP, KIT_AT_CENTER, 0, KIT_GI_DARK },
    { KIT_FX_SPARKLE,  1200, BI_SPORE, 0, KIT_AT_TOP, 0, KIT_GI_KEEP },
    { KIT_FX_FADE_OUT,  700, BI_SPORE, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_END[] = {
    { KIT_FX_SWEEP_DOWN, 900, BI_VINE, BI_DEEP, KIT_AT_TOP, 0, KIT_GI_KEEP },          /* she withers */
    { KIT_FX_FADE_OUT,  800, BI_DEEP, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
#define N_SHOW(a) (int)(sizeof (a) / sizeof (a)[0])

/* ---- sound: its own music, calls and clips (modes/biollante/assets.json) ------------------------ */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_START, CUE_CUT, CUE_COLLECT, CUE_BEAST, CUE_END };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_START:    pa_start(&own); break;                     /* her theme, the rose, the vines */
    case CUE_CUT:                                                 /* a vine cut; its clip every few seconds */
        pa_call(&own, "cut");
        if (pm_ms() - run.cut_clip_at >= CUT_CLIP_GAP_MS && pa_clip_event(&own, "cut")) run.cut_clip_at = pm_ms();
        break;
    case CUE_COLLECT:                                             /* a bank cut: the sap sprays */
        pa_call(&own, "collect");
        pa_clip_event(&own, "collect");
        break;
    case CUE_BEAST:
        pa_call(&own, "beast");
        pa_clip_full(&own, "beast");
        break;
    case CUE_END:      pa_end(&own); break;
    }
}

static unsigned ramps_needed(unsigned p) { return RAMPS_FIRST + RAMPS_STEP * plays[p]; }

static uint64_t pay(uint64_t points)
{
    uint64_t got = pm_score_add(run.player, points);
    run.total += got;
    return got;
}

static uint64_t switch_value(void) { return SWITCH_VALUE + SWITCH_STEP * run.collects; }

/* ---- the glass and the inserts ------------------------------------------------------------------------ */
static void show_lamps(void)
{
    unsigned b, i;
    uint64_t standing = 0;
    kit_lamps_begin(&lamps);
    if (run.phase == PHASE_ROSE) {
        for (b = 0; b < N_BANKS; b++)
            for (i = 0; i < 3; i++)
                if (!(run.cut[b] & (1u << i))) standing |= vine_mask[b][i];
        kit_lamps_shot(&lamps, standing, BI_VINE, PM_LAMP_SOLID, 0);
    } else {
        kit_lamps_shot(&lamps, final_mask, KIT_GOLD, PM_LAMP_BLINK,
                       kit_hurry_ms((unsigned long)kit_timer_seconds(&run.clock) * 1000u, BEAST_SECONDS * 1000u));
    }
    kit_lamps_commit(&lamps);
}

static unsigned vines_cut(void)
{
    unsigned b, i, n = 0;
    for (b = 0; b < N_BANKS; b++)
        for (i = 0; i < 3; i++) n += (run.cut[b] >> i) & 1u;
    return n;
}

static void show(void)
{
    char v[24], s[24], n[24], sub[24];
    show_lamps();
    if (run.phase == PHASE_BEAST) {
        kit_hud_title(&hud, "BIOLLANTE BEAST", "FINAL BLOW: SHOOT THE BUILDING");
        kit_hud_counter(&hud, 0, "PER SWITCH", kit_num(v, sizeof v, switch_value()), "SAP");
        kit_hud_counter(&hud, 1, "FINAL BLOW", kit_short(s, sizeof s, run.collected), "BUILDING");
        kit_hud_counter(&hud, 2, "VINES CUT", "3 OF 3", "THE BEAST");
        kit_hud_gauge(&hud, 6, "BEAST");
    } else {
        kit_hud_title(&hud, "BIOLLANTE", "SWITCHES FEED THE SAP  -  CUT A VINE BANK");
        kit_hud_counter(&hud, 0, "PER SWITCH", kit_num(v, sizeof v, switch_value()), "SAP");
        pm_snprintf(sub, sizeof sub, "X%u AT A BANK", run.collects + 1);
        kit_hud_counter(&hud, 1, "SAP JACKPOT", kit_short(s, sizeof s, run.sap), sub);
        pm_snprintf(n, sizeof n, "%u OF %d", run.collects, COLLECTS);
        kit_hud_counter(&hud, 2, "BANKS CUT", n, " ");
        kit_hud_gauge(&hud, (int)vines_cut(), "VINES");
    }
    kit_hud_timer(&hud, (int)kit_timer_seconds(&run.clock));
}

/* ---- start, collect, the beast, end ------------------------------------------------------------- */
static int start(const char *why)
{
    unsigned p = pm_player();
    if (run.on) return 0;
    if (!pm_in_game() || p < 1 || p > 4) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (kit_wait_game(MODE_NAME, why, "still lit: the next ramp after it starts it")) {
        waiting[p] = 1;
        return 0;
    }
    if (!kit_begin(MODE_NAME)) {
        waiting[p] = 1;
        return 0;
    }
    kit_display(KIT_DISPLAY_MODE);
    kit_isolate_list(own.give_way, own.block_ids, own.block_n);
    run.on = 1;
    run.player = p;
    run.phase = PHASE_ROSE;
    run.won = 0;
    run.cut[0] = run.cut[1] = 0;
    run.collects = run.switches = 0;
    run.sap = run.collected = run.total = 0;
    run.cut_clip_at = 0;
    kit_timer_set(&run.clock, RUN_SECONDS, 1);
    waiting[p] = 0;
    ramps[p] = 0;
    plays[p]++;
    kit_hud_begin(&hud, "BIOLLANTE", "");
    kit_hud_pips(&hud, 6);
    show();
    kit_hud_award(&hud, 3000, "BIOLLANTE", "EVERY SWITCH FEEDS HER SAP");
    kit_show_start(&show_fx, "biollante start", SHOW_START, N_SHOW(SHOW_START));
    sound(CUE_START);
    pm_log("START (%s): player %u, %d s, %llu a switch; next time %u ramps, score %llu", why, p, RUN_SECONDS,
           (unsigned long long)switch_value(), ramps_needed(p), (unsigned long long)pm_score(p));
    return 1;
}

static void end(const char *why)
{
    char a[24], b[KIT_HUD_WORDS];
    if (!run.on) return;
    run.on = 0;
    kit_lamps_off(&lamps);
    kit_end_after(TOTAL_SHOWN_MS);
    if (kit_natural_end(why) && !pa_call(&own, run.won ? "won" : "lost") && !(run.won))
        pm_callout(pm_callout_id("time_up"));          /* its own ending call, else the game's time-up */
    sound(CUE_END);
    pa_clip_full(&own, run.won ? "won" : "lost");
    if (run.won) kit_show_start(&show_fx, "spores", SHOW_WON, N_SHOW(SHOW_WON));
    else kit_show_start(&show_fx, "biollante end", SHOW_END, N_SHOW(SHOW_END));
    pm_snprintf(b, sizeof b, "%u SWITCHES  -  %u BANK%s CUT", run.switches, run.collects, run.collects == 1 ? "" : "S");
    kit_hud_title(&hud, run.won ? "BIOLLANTE IS FREE" : "BIOLLANTE WITHERS", b);
    kit_hud_counter(&hud, 0, 0, 0, 0);
    kit_hud_counter(&hud, 1, 0, 0, 0);
    kit_hud_counter(&hud, 2, 0, 0, 0);
    kit_hud_timer(&hud, -1);
    kit_hud_gauge(&hud, -1, 0);
    kit_hud_award(&hud, TOTAL_SHOWN_MS, kit_num(a, sizeof a, run.total), " ");
    kit_hud_hide_in(&hud, TOTAL_SHOWN_MS);
    pm_log("END (%s): %s, %u switches, %u collect(s), total %llu, score %llu", why, run.won ? "WON" : "not won",
           run.switches, run.collects, (unsigned long long)run.total, (unsigned long long)pm_score(run.player));
}

static void beast(void)
{
    run.phase = PHASE_BEAST;
    kit_timer_set(&run.clock, BEAST_SECONDS, 1);
    pm_log("BEAST FORM: the %s is the final blow for %d s: %llu", FINAL_SHOT, BEAST_SECONDS,
           (unsigned long long)run.collected);
    kit_hud_award(&hud, 3000, "BEAST FORM!", "FINAL BLOW: SHOOT THE BUILDING");
    kit_show_start(&show_fx, "beast", SHOW_BEAST, N_SHOW(SHOW_BEAST));
    sound(CUE_BEAST);
}

static void collect(unsigned bank)
{
    char a[24], s[KIT_HUD_WORDS];
    uint64_t got;
    run.collects++;
    got = pay(run.sap * run.collects);
    run.collected += got;
    pm_log("VINES CUT: %s, the SAP JACKPOT x%u: +%llu (the sap was %llu)", BANK_SAYS[bank], run.collects,
           (unsigned long long)got, (unsigned long long)run.sap);
    pm_snprintf(s, sizeof s, "SAP JACKPOT X%u", run.collects);
    kit_hud_award(&hud, 2200, s, kit_num(a, sizeof a, got));
    kit_show_start(&show_fx, "collect", SHOW_COLLECT, N_SHOW(SHOW_COLLECT));
    sound(CUE_COLLECT);
    run.sap = 0;
    run.cut[bank] = 0;
    if (run.collects >= COLLECTS) beast();
}

/* ---- shots ------------------------------------------------------------------------------------------- */
static void run_shot(uint64_t shot)
{
    unsigned b, i;
    if (shot & 1ull) {                            /* a playfield switch: the sap */
        uint64_t got = pay(switch_value());
        run.switches++;
        if (run.phase == PHASE_ROSE) run.sap += got;
    }
    if (pop_mask && (shot & pop_mask) && run.clock.ticks + POP_BACK_MS * KIT_TICKS / 1000u <=
        (run.phase == PHASE_BEAST ? BEAST_SECONDS : RUN_SECONDS) * KIT_TICKS)
        run.clock.ticks += POP_BACK_MS * KIT_TICKS / 1000u;      /* the clock stands still in the bumper */
    if (run.phase == PHASE_BEAST) {
        if (final_mask && (shot & final_mask) && kit_fresh(&db, final_mask)) {
            char a[24];
            uint64_t got = pay(run.collected);
            run.won = 1;
            pm_log("FINAL BLOW at %s: +%llu", FINAL_SHOT, (unsigned long long)got);
            kit_hud_award(&hud, 3000, "FINAL BLOW", kit_num(a, sizeof a, got));
            end("the final blow");
        }
        return;
    }
    for (b = 0; b < N_BANKS; b++)
        for (i = 0; i < 3; i++) {
            uint64_t m = vine_mask[b][i];
            if (!m || !(shot & m) || (run.cut[b] & (1u << i)) || !kit_fresh(&db, m)) continue;
            run.cut[b] |= 1u << i;
            pm_log("vine cut: %s (%s %u of 3)", BANK[b][i], BANK_SAYS[b],
                   (run.cut[b] & 1u) + ((run.cut[b] >> 1) & 1u) + ((run.cut[b] >> 2) & 1u));
            if (kit_timer_at_least(&run.clock, LIT_SHOT_FLOOR)) pm_log("the clock back up to %d s", LIT_SHOT_FLOOR);
            if (run.cut[b] == 7u) collect(b);
            else sound(CUE_CUT);
            if (run.phase != PHASE_ROSE) return;
        }
}

static void qualify_shot(uint64_t shot, unsigned p)
{
    char line[KIT_HUD_WORDS];
    unsigned need = ramps_needed(p);
    if (!ramp_mask || !(shot & ramp_mask) || !kit_fresh(&db, shot & ramp_mask)) return;
    if (waiting[p]) {
        start("a ramp, BIOLLANTE lit");
        return;
    }
    if (ramps[p] < need) ramps[p]++;
    pm_log("ramps %u of %u (player %u)", ramps[p], need, p);
    if (ramps[p] >= need) {
        start("the ramps");
    } else if (!kit_running) {
        pm_snprintf(line, sizeof line, "%u RAMP%s TO BIOLLANTE", need - ramps[p], need - ramps[p] == 1 ? "" : "S");
        kit_hud_note(&hud, 1500, line, "THE ROSE IS GROWING");
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
    if (p != run.player) return;
    run_shot(shot);
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    unsigned b, i;
    for (i = 0; i < 2; i++) ramp_mask |= pm_shot(RAMPS[i]);
    for (b = 0; b < N_BANKS; b++)
        for (i = 0; i < 3; i++) {
            vine_mask[b][i] = pm_shot(BANK[b][i]);
            if (!vine_mask[b][i]) pm_log("this port has no \"%s\"", BANK[b][i]);
        }
    final_mask = pm_shot(FINAL_SHOT);
    pop_mask = pm_shot("Pop bumper");
    pa_load(&own);
    pm_log("ready on %s %s: %d ramp shots (0x%llx) start it; the shields and the powerlines are the vines; the %s "
           "(0x%llx) the final blow", pm_game(), pm_version(), RAMPS_FIRST, (unsigned long long)ramp_mask, FINAL_SHOT,
           (unsigned long long)final_mask);
}

static void check_triggers(void)
{
    char name[48];
    if (pm_trigger(FOLDER ".start")) start("trigger file");
    if (pm_trigger(FOLDER ".stop")) end("trigger file");
    if (pm_trigger(FOLDER ".beast") && run.on && run.phase == PHASE_ROSE) beast();
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t m = pm_shot(name);
        pm_log("shot trigger: \"%s\" (0x%llx)", name, (unsigned long long)m);
        if (m) on_shot(1ull | m);
    }
}

static void on_tick(void)
{
    unsigned p;
    kit_hud_tick(&hud);
    kit_show_tick(&show_fx, &lamps);
    pa_tick(&own);
    if (++poll % KIT_POLL == 0) check_triggers();
    if (kit_new_game(&game)) {
        for (p = 0; p < 5; p++) ramps[p] = plays[p] = 0, waiting[p] = 0;
        pm_log("new game: the ramps cleared");
    }
    if (!run.on) return;
    if (!pm_in_game() || pm_player() != run.player) {
        end("the game moved on");
        return;
    }
    if (kit_game_began()) {                        /* PAD-347: isolated - the game began one of its own */
        end("the game's own mode began");
        kit_end_now();
        return;
    }
    if (kit_timer_tick(&run.clock)) {
        end(run.phase == PHASE_BEAST ? "the final blow was not made" : "time ran out");
        return;
    }
    show();
}

static void on_ball_end(void)
{
    end("ball ended");
    kit_end_now();
}

static void on_event(unsigned id)
{
    if (kit_is_tilt(id)) {
        end("tilted");
        kit_end_now();
    }
}

static const struct pm_mode biollante = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(biollante);
