/* pad_stock.h - rewrite the SHOT LOGIC of one of the game's OWN rules in C (item 161).
 *
 * Implemented in pad_mode_runtime.c ("STOCK RULES IN C") on item 160's per-rule wrap of the shot
 * handler's vtable slot. Every address, offset, slot number and id below comes from the PORT
 * (`site` / `data` / `value` lines; MODE_SDK.md, "Rewriting a stock rule's shot logic"); nothing in
 * this header is an address, and a call whose port line is missing does nothing and says so once.
 *
 * WHAT A STOCK RULE IS. The game's own modes (a battle, a multiball) are compiled C++ objects, one
 * per rule, each with a vtable (MODE_SDK.md, "The game's own modes"). Three of its virtuals matter
 * here: START (v[8]), STOP(reason) (v[11]) and the SHOT HANDLER (v[42] on Premium 1.16, v[41] on
 * Pro 1.15; the port's `stock_slot_*` values say which). The handler is called with every shot the
 * game dispatches while the rule is active: (this, _, shot lo, shot hi, [sp] factor). It reads and
 * writes the rule's own fields (its lit mask, its counters) and calls the engine (awards, shows,
 * events, the stop). Rewriting a rule's shot logic = registering a C function that runs INSTEAD
 * of that virtual, and calling the same engine pieces through the port.
 *
 * WHAT IT IS NOT. The rule's START, its timer, its display layers, its lamps and its ending are
 * still the game's own. A rewrite changes what a shot DOES; the battle still starts from the
 * select screen, still times out, and still ends with the game's own screens.
 *
 * THE RULES (pad_mode.h's still apply: no blocking, no malloc, static state):
 *   - A handler runs INSIDE the game's dispatch, on the game thread, with the rule object live.
 *     Return quickly; never start a mode of ours from it.
 *   - Reach the rule's fields only through the accessors here; every one reads its offset from
 *     the port, and returns 0 / does nothing when the port has no line for it.
 *   - `pm_stock_call_original` is the ONLY way to run the game's handler from yours; the wrap
 *     never re-enters your handler for that call, and no counts-as row is applied to it.
 *   - With no record registered for a rule, and no counts-as row, nothing is wrapped: the game
 *     runs stock (the wrap is installed only for what a card asks for).
 *
 * WHAT IS PROVEN. See MODE_SDK.md's section for the emulator runs. Item 158 proved (emulator,
 * Premium 1.16) the facts it rests on: the slot numbers, the field and counter offsets, that a
 * wrapped v[42] sees every shot with its factor, that caward_add / show_start / game_event are what
 * the handlers call, and that the final blow ends the battle with reason 1 from inside the handler.
 */
#ifndef PAD_STOCK_H
#define PAD_STOCK_H

#include "pad_mode.h"

/* ---- a stock rule, and the player it acts for -------------------------------------------- */
struct pm_stock_rule;                     /* opaque: the runtime's handle on one rule object */

/* The rule with this id, or 0 when the port cannot reach the manager (`site stock_rule_get`,
 * `data stock_mode_manager`, a `rule` line), the manager has not built it yet, or its object is not
 * the port's. Godzilla: 4 tank attack, 12 Ebirah (`value ebirah_rule`, `value tank_rule`). */
struct pm_stock_rule *pm_stock_rule(unsigned id);
unsigned pm_stock_rule_id(const struct pm_stock_rule *r);
/* The player the game's own handler would act for: the current player (1-4), as the handlers
 * read it (the same byte pm_player() reads). 0 when no game. */
unsigned pm_stock_player(void);

/* ---- registering a handler ------------------------------------------------------------------
 * Return PM_STOCK_DONE when your code handled the shot (the game's handler is NOT run for it),
 * PM_STOCK_PASS to let the game's handler run as if you were not there (after item 160's counts-as
 * rows, when the card has any). `factor` is the dispatch's stack word (1 from a switch; the
 * game's own spot helpers pass their own). `shot` is the mask as dispatched: test bits, never
 * compare the whole mask (a Big loop arrives as 0x1000000001; every switch also sends 0x1). */
#define PM_STOCK_PASS 0
#define PM_STOCK_DONE 1
typedef int (*pm_stock_shot_handler)(struct pm_stock_rule *rule, uint64_t shot, unsigned factor);

struct pm_stock_handler {
    unsigned rule_id;                                            /* the rule this replaces */
    pm_stock_shot_handler shot;                                  /* runs instead of the game's handler */
    void (*started)(struct pm_stock_rule *rule);                 /* optional: after the game's START ran */
    void (*stopped)(struct pm_stock_rule *rule, unsigned reason);/* optional: before the game's STOP runs (1 = won) */
    const char *name;                                            /* shown in the log */
    const struct pm_mode *mode;                                  /* optional: the mode the log lines and the lamp
                                                                    holds made from the callbacks belong to */
};

/* The full form, and the one-liner: PM_STOCK_HANDLER(12, my_ebirah_shot). Both put the record in
 * the `pm_stock` section the runtime walks from its tick (twice a second, until the manager has
 * built the rule), like PM_REGISTER. One record per rule; a second is refused and said. */
#define PM_STOCK_RULE(h)                                                            \
    static const struct pm_stock_handler *const pm__stock_##h                       \
        __attribute__((used, section("pm_stock"))) = &(h)
#define PM_STOCK_HANDLER(id, fn)                                                    \
    static const struct pm_stock_handler pm__stock_rec_##fn = { (id), (fn), 0, 0, #fn, 0 }; \
    PM_STOCK_RULE(pm__stock_rec_##fn)

/* The game's own handler for this rule, with these arguments, as it was before the wrap; what it
 * returns (r0:r1) is passed back. From inside a handler or a started/stopped callback of the rule. */
uint64_t pm_stock_call_original(struct pm_stock_rule *rule, uint64_t shot, unsigned factor);

/* ---- the rule's state, through the port ------------------------------------------------------
 * The lit-shot mask the rule keeps per player: u64 at obj + `value stock_field` + 8 * player.
 * What the game's own v[25] reports as lit for most rules (tank keeps its own, see below), and
 * what the game's handler gates on (Ebirah: a shot with no lit bit does nothing). */
uint64_t pm_stock_field(struct pm_stock_rule *rule, unsigned player);
int      pm_stock_field_set(struct pm_stock_rule *rule, unsigned player, uint64_t mask);
/* The rule's own answers: lit shots (v[stock_slot_lit]), active (v[stock_slot_active]; -1 unknown),
 * running for a player (the byte at obj + `value stock_running_at` + player; -1 unknown). */
uint64_t pm_stock_lit(struct pm_stock_rule *rule);
int      pm_stock_active(struct pm_stock_rule *rule);
int      pm_stock_running(struct pm_stock_rule *rule, unsigned player);
/* A word of the rule's own, at an offset the port names: `at` is the result of pm_stock_at(),
 * -1 when the port has no such line (every call below then fails with 0). A per-player word
 * is at obj + at + 4 * player (the game's counters index from 1); a plain word at obj + at. */
long pm_stock_at(const char *value_name);                    /* pm_port_value(name, -1), said once when missing */
int  pm_stock_pw_get(struct pm_stock_rule *rule, long at, unsigned player, int *out);
int  pm_stock_pw_set(struct pm_stock_rule *rule, long at, unsigned player, int value);
int  pm_stock_w_get(struct pm_stock_rule *rule, long at, int *out);
int  pm_stock_w_set(struct pm_stock_rule *rule, long at, int value);
int  pm_stock_b_get(struct pm_stock_rule *rule, long at, int *out);           /* a byte */

/* ---- the engine pieces the handlers call --------------------------------------------------
 * An AWARD, the way the stock handler pays one: caward_add(the rule's own award object at
 * obj + `value stock_award_at`, 0, value, index 0). Returns what the engine says it added.
 * pm_stock_award_to pays through ANOTHER rule's award object (Ebirah under King of the Monsters
 * pays through rule 20's). pm_stock_build is caward_build on the rule's award (tank pays half a
 * kill into it). Sites: caward_add, caward_build. */
uint64_t pm_stock_award(struct pm_stock_rule *rule, uint64_t value);
uint64_t pm_stock_award_to(unsigned rule_id, uint64_t value);
uint64_t pm_stock_build(struct pm_stock_rule *rule, uint64_t value);
/* A SHOW (a light show / display cue by id, `site show_start`): returns the show's record, which
 * the stock handlers then fill (a colour, a lamp id, a count; the offsets are the show's, not
 * the rule's), or 0. Ebirah shows 347 and 359 on a spin, 148 on a stage; tank shows 144 on the
 * destroyed tank's insert. */
void *pm_stock_show(unsigned id);
/* A GAME EVENT (`site game_event`: the rule-to-rule broadcast the handlers post; Ebirah 19 on the
 * final blow, tank 51 on a Maser hit) with the value the handlers pass (the award total). The
 * trailing arguments the handlers pass (a word, then a u64) are sent as 0. */
int  pm_stock_event(unsigned id, uint64_t value);
/* A display EVENT record (`site event_post_replacing`), what the stage screens and the stop
 * displays post; returns the record or 0. pm_stock_event_cancel removes one by id (`site event_cancel`). */
void *pm_stock_display_event(unsigned id, unsigned handler, unsigned flags);
int   pm_stock_event_cancel(unsigned id);
/* A callout or a sound: the ordinary pad_mode.h calls (pm_callout, pm_sound). */

/* STOP the rule the way its own code does: v[stock_slot_stop](reason), 1 = completed (won), 0 =
 * not. pm_stock_start runs its START (for a test; the game's own way is the select screen). Both
 * go through the vtable, so a probe's wrap of those slots logs them. */
int pm_stock_stop(struct pm_stock_rule *rule, int won);
int pm_stock_start(struct pm_stock_rule *rule);

/* ---- Godzilla: battle vs Ebirah (rule `value ebirah_rule`) -----------------------------------
 * Its own state (item 158): three per-player spin counters (`value ebirah_spin_left_at`,
 * `ebirah_spin_top_at`, `ebirah_spin_shield_at`; the ctor's defaults 15 / 40 / 15), a stage index
 * (`ebirah_stage_index_at`, which 5M / 10M / 15M award is next), a per-player stage count
 * (`ebirah_stage_count_at`), and the KOTM byte (`ebirah_kotm_at`: awards go to King of the
 * Monsters while it runs). Its handler tests RAW shot bits (`value ebirah_spin_left_bit` 0x200,
 * `ebirah_spin_top_bit` 0x2000, `ebirah_spin_shield_bit` 0x20000) and, once every counter is 0,
 * the FINAL shot (`ebirah_final_shot` 0x40, the Pop bumper, or bit 42) with the field set to
 * `ebirah_final_mask_lo/hi`. */
#define PM_EBIRAH_LEFT   0
#define PM_EBIRAH_TOP    1
#define PM_EBIRAH_SHIELD 2
int      pm_ebirah_spins(struct pm_stock_rule *rule, int which, unsigned player);      /* -1 = no line */
int      pm_ebirah_spins_set(struct pm_stock_rule *rule, int which, unsigned player, int n);
uint64_t pm_ebirah_spin_bit(int which);                                               /* 0 = no line */
/* A STAGE AWARD, exactly as the game gives one: sets that spinner's counter to 1, lights its bit,
 * and runs the game's handler with the spinner's own bit. The game then pays the last spin, gives
 * the 5M / 10M / 15M award in completion order, shows its award screen, posts its reminder
 * event, and, when every counter is 0, writes the final mask itself. Returns 1 when it ran. */
int pm_ebirah_stage_award(struct pm_stock_rule *rule, int which);
/* The FINAL BLOW, exactly as the game gives one: sets the field to the final mask and runs the
 * game's handler with the final shot. The game pays 25,000,000, the finishing bonus, shows the
 * final-blow screen, posts its events and STOPS the battle as WON (v[11](1)): the battle's own
 * ending plays. Returns 1 when it ran. Ebirah's port lines; another rule has no final blow. */
int pm_stock_final_blow(struct pm_stock_rule *rule);
/* The stage awards the game's own vector holds (`data ebirah_stage_awards`, `value
 * ebirah_stage_award_count`): 5,000,000 / 10,000,000 / 15,000,000 on Godzilla; 0 = no line. */
uint64_t pm_ebirah_stage_value(unsigned index);

/* ---- Godzilla: tank attack multiball (rule `value tank_rule`) ---------------------------------
 * Tank keeps no lit mask: its shots are TANK RECORDS (a vector at obj + `value tank_records_at`
 * of `tank_record_size`-byte records: active byte at +`tank_record_active_at`, position mask at
 * +`tank_record_pos_at`, previous position at +`tank_record_prev_at`, destination at
 * +`tank_record_dest_at`, value at +`tank_record_value_at`), walking the PATH (`data tank_path`,
 * `value tank_path_entries` 16-byte entries {u64 mask, u16 lamp, u16 id, u32}). Counters:
 * destroyed (`tank_destroyed_at`), level per player (`tank_level_at`), the tank value per
 * player (`tank_value_at`, u64), the Maser multiplier (`tank_multiplier_at`). Nothing of the
 * tank's has run under a C handler yet (desk). */
struct pm_tank_record { int active; uint64_t pos, prev, dest, value; };
int pm_tank_records(struct pm_stock_rule *rule, struct pm_tank_record *out, int max);  /* how many were filled (at most max) */
int pm_tank_destroyed(struct pm_stock_rule *rule);                                    /* -1 = no line */
int pm_tank_level(struct pm_stock_rule *rule, unsigned player);
int pm_tank_maser_phase(struct pm_stock_rule *rule);       /* the game's own test (`site tank_maser_phase`) */
/* The game's own pieces (sites tank_destroy, tank_seed_wave, tank_advance): destroy record
 * `index` with credit (the destroyed count, the value step, a respawn), seed a new wave (level +
 * 1, three tanks), advance every tank one step and spawn. Each returns 1 when the site is there
 * and it ran. pm_tank_path_index is the first path entry that ANDs the shot (from the port's
 * data), -1 when none. */
int pm_tank_destroy(struct pm_stock_rule *rule, int index, int credit);
int pm_tank_seed_wave(struct pm_stock_rule *rule);
int pm_tank_advance(struct pm_stock_rule *rule);
int pm_tank_path_index(struct pm_stock_rule *rule, uint64_t shot);
int pm_tank_path_entry(unsigned index, uint64_t *mask, unsigned *lamp);              /* from the port's data */

#endif
