/* anguirus_assist.c - ANGUIRUS: a mode that STACKS with the game's own battle ON PURPOSE, for
 * Godzilla (item 152).
 *
 * Anguirus, Godzilla's oldest ally (Godzilla Raids Again, 1955; Destroy All Monsters; Final
 * Wars), joins every kaiju battle the GAME starts. It starts and ends with the game's own mode
 * and adds a layer of its own on top: charge the spikes, then roll.
 *
 *   START      By itself, when one of the game's own kaiju battles begins (the game's mode
 *              manager says a battle is active; MODE_SDK.md "The game's own modes"). Once per
 *              battle. If another of our modes is running then, Anguirus joins when it ends,
 *              if the battle is still on.
 *   CHARGE     Each SHIELD TARGET (left, center, right) charges one spike: 500,000. A spike
 *              already charged does not charge again. (A game with two shield targets, like
 *              Godzilla Pro 1.15, needs two.)
 *   ROLL       Three spikes charged: the BIG LOOP is lit for a ROLLING ATTACK: 4,000,000. Each
 *              Big loop within 6 s of the last doubles it (8,000,000, then 16,000,000, which
 *              is the most). When 6 s pass without a loop the roll is over and the spikes must
 *              be charged again.
 *   ENDS       When the game's battle ends (it asks twice a second), or the ball drains, or the
 *              ball is tilted. The game's battle is never touched: its shots, its timer and its
 *              award are its own.
 *   INSERTS    The shield inserts are the charge meter: a spike still to charge BLINKS orange, a
 *              charged one is SOLID orange. The roll lit: the BIG LOOP blinks cyan, faster as its
 *              6 s run out. They are lit from the moment it joins (the shots count at once) and
 *              handed back the moment the battle ends, the ball drains or it is tilted.
 *   DISPLAY    It YIELDS to the battle. The battle is the game's main event and its own screen
 *              (its timer, its shot progress, what to shoot) sits where our panel does, so
 *              Anguirus takes the screen only when it has something to say, holding display
 *              priority 180 for that moment and giving it back after:
 *                - its entrance (the start clip, its music, then the panel) waits until the
 *                  battle's own start screen is over: pm_display_covered() says when that
 *                  full-screen display has the glass, and the entrance comes once the screen
 *                  has been in view for a second (at most 12 s after it joined);
 *                - a spike, the roll lit and each rolling attack show the panel for 3 s;
 *                - when the battle ends, its TOTAL waits for the battle's own total screen,
 *                  then shows for 4 s (at most 12 s after the battle ended). Another of our
 *                  modes asking to start then goes first: the total gives way at once, and
 *                  that mode's next start shot starts it.
 *              A moment counts only while the panel is in view, so a display of the game's
 *              that beats 180 (a jackpot, the battle's own start or total) never eats it.
 *              Between the moments the battle's displays play as the game wants.
 *   LIGHTS     No light sweep: the port's example sweep recolours the inserts around the
 *              shots (measured, item 157), so it would make shots that pay nothing look lit.
 *   SCREEN     "SPIKES 2 OF 3" alternating with "ANGUIRUS ASSISTS"; "BIG LOOP 8,000,000"
 *              alternating with "ROLL 4" (the window's seconds).
 *
 * Emulator test triggers: /dump/anguirus_assist.start (start now, without a battle: it then
 * leaves at once unless the battle query is not available), .stop, .shot "<shot name>".
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "ANGUIRUS"
#define FOLDER             "anguirus_assist"
#define CHARGE_PAYS        500000ull
#define ROLL_SHOT          "Big loop"
#define ROLL_FIRST         4000000ull
#define ROLL_MAX           16000000ull
#define ROLL_WINDOW_MS     6000
#define TOTAL_SHOWN_MS     6000
#define SETTLE_MS          1000           /* the screen in view this long before the entrance */
#define ENTRANCE_WAIT_MS   12000          /* at most this long for the battle's own start screen */
#define ENTRANCE_SAY_MS    11500          /* the clip (8 s, from 0.5 s) and 3 s of the panel after it */
#define SAY_MS             3000           /* a spike, the roll lit, a rolling attack */
#define TOTAL_SAY_MS       4000
#define LEAVE_WAIT_MS      12000          /* at most this long for the battle's own total */

#define SCREEN_NODE "PadMode_" FOLDER "_Screen"
#define SCREEN_TEXT "PadMode_" FOLDER "_Screen.PadMode_" FOLDER "_Screen_Words"

#define N_SPIKES 3
static const char *const SPIKE_SHOT[N_SPIKES] = { "Shield target left", "Shield target center", "Shield target right" };

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t spike_mask[N_SPIKES], roll_mask;
static unsigned spike_all;                /* the spikes this game has: Pro 1.15 has no center shield */
static int battle_was;                    /* the game's battle was active at the last look */
static int battle_joined;                 /* this battle already had its Anguirus */
static int can_tell = 1;
static struct kit_db db;
static struct kit_lamps lamps;
static struct kit_screen screen = { .node_name = SCREEN_NODE, .text_name = SCREEN_TEXT, .alt_ms = 1500 };
static unsigned poll;

static struct {
    int on, rolling, entered, leaving, holding;
    unsigned player, spikes, rolls, charges;
    uint64_t roll_value, total;
    unsigned long roll_at, join_at, view_since, leave_at, last_ms, say_left;
    char why[48];                         /* why it is leaving */
} run;

/* ---- sound: the one place the mode's own clip, music and calls are played --------------------------
 * From modes/anguirus_assist/assets.json through anguirus_assist.assets (pad_mode_assets.h). No
 * stock callout fits an ally, so a cue the card does not carry is silence. */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_JOIN, CUE_ENTRANCE, CUE_CHARGE, CUE_ROLL_LIT, CUE_ROLL, CUE_ROLL_OVER, CUE_LEAVE };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_JOIN:     pa_priorities(&own); break;               /* its calls' priorities, before any call */
    case CUE_ENTRANCE: pa_start(&own); break;                    /* its music, its start clip */
    case CUE_CHARGE:   pa_call(&own, "spike"); break;            /* a spike charged */
    case CUE_ROLL:     pa_call(&own, "roll"); break;             /* a rolling attack */
    case CUE_LEAVE:                                              /* the battle is over */
        pa_call(&own, run.rolls ? "won" : "lost");
        pa_end(&own);
        break;
    default: break;                                              /* the roll lit, the roll over */
    }
}

static uint64_t pay(uint64_t points)
{
    uint64_t got = pm_score_add(run.player, points);
    run.total += got;
    return got;
}

static unsigned spikes_charged(void)
{
    unsigned i, n = 0;
    for (i = 0; i < N_SPIKES; i++) n += (run.spikes >> i) & 1u;
    return n;
}

static unsigned spikes_of_game(void)
{
    unsigned i, n = 0;
    for (i = 0; i < N_SPIKES; i++) n += (spike_all >> i) & 1u;
    return n;
}

/* the charge meter on the shield inserts, the roll on the Big loop's; only a change is sent */
static void show_lamps(void)
{
    unsigned i;
    kit_lamps_begin(&lamps);
    for (i = 0; i < N_SPIKES; i++) {
        if (!spike_mask[i]) continue;
        if (run.rolling || (run.spikes & (1u << i))) kit_lamps_shot(&lamps, spike_mask[i], KIT_ORANGE, PM_LAMP_SOLID, 0);
        else kit_lamps_shot(&lamps, spike_mask[i], KIT_ORANGE, PM_LAMP_BLINK, 400);     /* charge me */
    }
    if (run.rolling) {
        unsigned long used = pm_ms() - run.roll_at;
        unsigned long left = used >= ROLL_WINDOW_MS ? 0 : ROLL_WINDOW_MS - used;
        kit_lamps_shot(&lamps, roll_mask, KIT_CYAN, PM_LAMP_BLINK, left > 4000 ? 400 : left > 2000 ? 200 : 100);
    }
    kit_lamps_commit(&lamps);
}

static void show(void)
{
    char a[KIT_WORDS], b[KIT_WORDS], n[24];
    show_lamps();
    if (run.rolling) {
        unsigned long used = pm_ms() - run.roll_at;
        unsigned left = used >= ROLL_WINDOW_MS ? 0 : (unsigned)((ROLL_WINDOW_MS - used + 999) / 1000);
        pm_snprintf(a, sizeof a, "BIG LOOP %s", kit_num(n, sizeof n, run.roll_value));
        pm_snprintf(b, sizeof b, "ROLL %u", left);
    } else {
        pm_snprintf(a, sizeof a, "SPIKES %u OF %u", spikes_charged(), spikes_of_game());
        pm_snprintf(b, sizeof b, "ANGUIRUS ASSISTS");
    }
    kit_screen_status(&screen, a, b);
}

/* ---- the screen, in moments -------------------------------------------------------------------
 * say(): take the screen (display priority 180) and keep it `ms` of IN-VIEW time; quiet(): give it
 * back to the battle. The count stops while a display of the game's that beat 180 covers the panel. */
static void say(unsigned long ms)
{
    if (!run.holding) {
        run.holding = pm_display_priority(KIT_DISPLAY_MODE);
        if (run.holding) pm_log("display priority %d held for a moment: the panel speaks", KIT_DISPLAY_MODE);
    }
    if (!screen.up) kit_screen_show(&screen, 1);
    if (run.say_left < ms) run.say_left = ms;
}

static void quiet(void)
{
    kit_screen_show(&screen, 0);
    if (run.holding) {
        pm_display_priority(0);
        run.holding = 0;
        pm_log("display priority given back: the battle's own display again");
    }
}

/* a moment on the screen, once it has made its entrance: the panel (its status line), with a
 * message over it for `ms` when there is one */
static void moment(unsigned ms, const char *line)
{
    if (!run.entered || run.leaving) return;
    say(SAY_MS);
    if (line && line[0]) kit_screen_flash(&screen, ms, line);
}

/* ---- start and end ---------------------------------------------------------------------------- */
static int start(const char *why)
{
    unsigned p = pm_player();
    if (run.on) return 0;
    if (!pm_in_game() || p < 1 || p > 4) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (!kit_begin(MODE_NAME)) return 0;
    run.on = 1;
    run.player = p;
    run.spikes = run.rolls = run.charges = 0;
    run.rolling = run.entered = run.leaving = 0;
    run.total = 0;
    run.say_left = 0;
    run.join_at = run.last_ms = pm_ms();
    run.view_since = 0;
    battle_joined = 1;
    /* the display hold first, so pm_display_covered() can say when the battle's start screen is over */
    run.holding = pm_display_priority(KIT_DISPLAY_MODE);
    show();
    sound(CUE_JOIN);
    pm_log("START (%s): player %u joins the game's battle, score %llu - the shields are lit now; its entrance "
           "waits for the battle's own start screen%s", why, p, (unsigned long long)pm_score(p),
           run.holding ? "" : " (no display arbitration in this port: at once)");
    return 1;
}

static void entrance(const char *how)
{
    run.entered = 1;
    kit_screen_show(&screen, 1);
    show();
    kit_screen_flash(&screen, 2000, "ANGUIRUS JOINS");
    say(ENTRANCE_SAY_MS);
    sound(CUE_ENTRANCE);
    pm_log("ENTRANCE %lu ms after it joined (%s): its clip, its music, its panel", pm_ms() - run.join_at, how);
}

/* the end, now: a drain, a tilt, the game moving on, the stop trigger, or after its total */
static void end(const char *why)
{
    char a[KIT_WORDS], n[24];
    if (!run.on) return;
    run.on = 0;
    kit_lamps_off(&lamps);                         /* every insert back to the game, at once */
    if (!run.leaving) sound(CUE_LEAVE);
    run.holding = 0;
    kit_end();                                     /* gives the display priority up too */
    pm_snprintf(a, sizeof a, "TOTAL %s", kit_num(n, sizeof n, run.total));
    kit_screen_status(&screen, a, "ANGUIRUS RETREATS");
    screen.flash[0] = 0;
    if (run.leaving) {
        kit_screen_hide_in(&screen, 0);            /* its total has had its time in view */
        pm_log("the total was shown: the screen is the game's again (%s)", why);
        return;
    }
    if (screen.up || run.entered) kit_screen_show(&screen, 1);
    kit_screen_hide_in(&screen, TOTAL_SHOWN_MS);
    pm_log("END (%s): %u charge(s), %u rolling attack(s), total %llu, score %llu", why, run.charges, run.rolls,
           (unsigned long long)run.total, (unsigned long long)pm_score(run.player));
}

/* the battle ended: the shots stop counting and the lights go back at once; the TOTAL waits for the
 * battle's own total screen, then has 4 s in view, then the mode is over */
static void leave(const char *why)
{
    char a[KIT_WORDS], n[24];
    if (!run.on || run.leaving) return;
    run.leaving = 1;
    run.leave_at = pm_ms();
    kit_asked = 0;
    kit_copy(run.why, sizeof run.why, why);
    kit_lamps_off(&lamps);
    sound(CUE_LEAVE);
    pm_snprintf(a, sizeof a, "TOTAL %s", kit_num(n, sizeof n, run.total));
    kit_screen_status(&screen, a, "ANGUIRUS RETREATS");
    screen.flash[0] = 0;
    run.entered = 1;
    run.say_left = 0;
    say(TOTAL_SAY_MS);
    pm_log("END (%s): %u charge(s), %u rolling attack(s), total %llu, score %llu - its total shows once the "
           "battle's own is done", why, run.charges, run.rolls, (unsigned long long)run.total,
           (unsigned long long)pm_score(run.player));
}

/* ---- shots ------------------------------------------------------------------------------------- */
static void assist_shot(uint64_t shot)
{
    char line[KIT_WORDS], n[24];
    unsigned i;
    uint64_t got;
    if (run.rolling) {
        if (!roll_mask || !(shot & roll_mask) || !kit_fresh(&db, roll_mask)) return;
        got = pay(run.roll_value);
        run.rolls++;
        pm_log("ROLLING ATTACK %u at %s: +%llu, %lu ms after the last", run.rolls, ROLL_SHOT, (unsigned long long)got,
               pm_ms() - run.roll_at);
        pm_snprintf(line, sizeof line, "ROLLING %s", kit_num(n, sizeof n, got));
        moment(1500, line);
        sound(CUE_ROLL);
        if (run.roll_value < ROLL_MAX) run.roll_value *= 2;
        if (run.roll_value > ROLL_MAX) run.roll_value = ROLL_MAX;
        run.roll_at = pm_ms();
        show();
        return;
    }
    for (i = 0; i < N_SPIKES; i++) {
        if (!spike_mask[i] || !(shot & spike_mask[i]) || !kit_fresh(&db, spike_mask[i])) continue;
        if (run.spikes & (1u << i)) {
            pm_log("%s: that spike is already charged", SPIKE_SHOT[i]);
            continue;
        }
        run.spikes |= 1u << i;
        run.charges++;
        got = pay(CHARGE_PAYS);
        pm_log("spike charged at %s: +%llu, %u of %u", SPIKE_SHOT[i], (unsigned long long)got, spikes_charged(),
               spikes_of_game());
        sound(CUE_CHARGE);
        if (run.spikes == spike_all) {
            run.rolling = 1;
            run.roll_value = ROLL_FIRST;
            run.roll_at = pm_ms();
            pm_log("ROLL LIT: %s for %llu, %d ms to make it", ROLL_SHOT, (unsigned long long)run.roll_value, ROLL_WINDOW_MS);
            moment(1500, "ROLLING ATTACK LIT");
            sound(CUE_ROLL_LIT);
        } else {
            moment(0, 0);                          /* the panel: SPIKES 2 OF 3 */
        }
        show();
    }
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    unsigned i;
    for (i = 0; i < N_SPIKES; i++) {
        spike_mask[i] = pm_shot(SPIKE_SHOT[i]);
        if (spike_mask[i]) spike_all |= 1u << i;
        else pm_log("this port has no \"%s\": %u spikes charge the roll", SPIKE_SHOT[i], N_SPIKES - 1);
    }
    roll_mask = pm_shot(ROLL_SHOT);
    pa_load(&own);
    pm_log("ready on %s %s: joins the game's own battles; spikes 0x%llx 0x%llx 0x%llx, roll 0x%llx", pm_game(),
           pm_version(), (unsigned long long)spike_mask[0], (unsigned long long)spike_mask[1],
           (unsigned long long)spike_mask[2], (unsigned long long)roll_mask);
}

static void on_shot(uint64_t shot)
{
    if (!run.on || run.leaving || !pm_in_game() || pm_player() != run.player) return;
    assist_shot(shot);
}

static void check_triggers(void)
{
    char name[48];
    if (pm_trigger(FOLDER ".start")) start("trigger file");
    if (pm_trigger(FOLDER ".stop")) {
        if (run.leaving) end("trigger file");
        else leave("trigger file");
    }
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t m = pm_shot(name);
        pm_log("shot trigger: \"%s\" (0x%llx)", name, (unsigned long long)m);
        if (m) on_shot(m);
    }
}

/* Twice a second: is the game's own battle on? Its rising edge starts Anguirus; its fall ends it. */
static void battle_watch(void)
{
    int k;
    if (!can_tell) return;
    k = pm_stock_mode_running(PM_STOCK_BATTLE);
    if (k < 0) {
        can_tell = 0;
        pm_log("this port cannot tell when the game's battles run: Anguirus never joins by itself");
        return;
    }
    if (k > 0 && !battle_was) {
        battle_joined = 0;
        pm_log("the game's battle began (player %u)", pm_player());
    }
    if (!k && battle_was) pm_log("the game's battle is over");
    battle_was = k > 0;
    if (battle_was && !battle_joined && !run.on && pm_in_game() && !kit_running) start("the game's battle began");
    if (!battle_was && run.on) leave("the game's battle ended");
}

/* the screen: the entrance once the battle's start screen is over, the moments, the total */
static void screen_tick(void)
{
    unsigned long now = pm_ms(), d = now - run.last_ms;
    int covered = run.holding && pm_display_covered();
    run.last_ms = now;
    if (!run.entered) {
        if (covered) run.view_since = 0;
        else if (!run.view_since) run.view_since = now;
        if (!run.holding) entrance("at once");
        else if (run.view_since && now - run.view_since >= SETTLE_MS) entrance("the battle's start screen is over");
        else if (now - run.join_at >= ENTRANCE_WAIT_MS) entrance("waited the longest it waits");
        return;
    }
    if (run.say_left && !covered) run.say_left = d >= run.say_left ? 0 : run.say_left - d;
    if (run.leaving) {
        if (kit_asked) {                           /* only a total: another of our modes goes first */
            pm_log("%s asked to start: the total gives way", kit_asked);
            kit_asked = 0;
            end(run.why);
        } else if (!run.say_left || now - run.leave_at >= LEAVE_WAIT_MS) {
            end(run.why);
        }
        return;
    }
    if (!run.say_left && (run.holding || screen.up)) quiet();
}

static void on_tick(void)
{
    kit_screen_tick(&screen);
    pa_tick(&own);
    if (++poll % KIT_POLL == 0) {
        check_triggers();
        battle_watch();
    }
    if (!run.on) return;
    if (!pm_in_game() || pm_player() != run.player) {
        end("the game moved on");
        return;
    }
    screen_tick();
    if (!run.on || run.leaving) return;
    if (run.rolling && pm_ms() - run.roll_at >= ROLL_WINDOW_MS) {
        pm_log("the roll is over (%u rolling attack(s) so far): charge the spikes again", run.rolls);
        run.rolling = 0;
        run.spikes = 0;
        moment(1500, "CHARGE THE SPIKES");
        sound(CUE_ROLL_OVER);
    }
    show();
}

static void on_ball_end(void)
{
    end("ball ended");
}

static void on_event(unsigned id)
{
    if (kit_is_tilt(id)) end("tilted");           /* its lights go dark with the game's */
}

static const struct pm_mode anguirus_assist = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(anguirus_assist);
