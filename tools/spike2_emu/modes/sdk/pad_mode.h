/* pad_mode.h - write a game mode of your own for a Stern Spike 2 pinball machine, in C.
 *
 * Read MODE_SDK.md first, then template_mode.c, which uses almost every call below.
 *
 * WHAT A MODE IS. A few functions the game calls: once at boot, 60 times a second, on
 * every shot, and when the ball drains. Your mode decides when it starts, what scores
 * while it runs, and what the display, speakers and lights do - using the GAME'S OWN
 * scoring, sound, light and display code through the calls in this header, so it
 * behaves like a mode the game shipped with.
 *
 * HOW IT GETS INTO THE GAME. Your .c files are compiled together with
 * pad_mode_runtime.c into one shared object (build_mode.sh), which the machine preloads
 * into the game. At boot the runtime reads the PORT for the game on the card
 * (ports/<game>-<version>.port): where each game function is in THIS build, plus that
 * build's shot names, scenes and callouts. Nothing in this header is an address, so the
 * same mode source runs on any game and version that has a port.
 *
 * THE SAFETY GATE. Before hooking anything the runtime checks, for every function the
 * port names, the first two machine instructions against what the port says they
 * should be. If the core ones do not match - a port for another game or version - it
 * hooks NOTHING, calls none of your code, logs why, and the game runs stock.
 *
 * THE RULES THAT KEEP A GAME RUNNING (MODE_SDK.md explains each):
 *   1. Never block. Every callback runs on a game thread; return quickly.
 *   2. No malloc, no files beyond pm_trigger/pm_log, no libc beyond pm_snprintf.
 *      The object is built -nostdlib: there is no allocator inside it.
 *   3. Keep state in static variables. Stack is fine for small buffers.
 *   4. One of our modes runs at a time: call pm_begin() before you start, pm_end()
 *      when you finish, and do not start if pm_begin() says no.
 *   5. A call that returns failure (0 / NULL) means this game's port lacks that
 *      capability, or the thing asked for is not there. Carry on without it.
 */
#ifndef PAD_MODE_H
#define PAD_MODE_H

#include <stdarg.h>
#include <stdint.h>

/* ---- a mode: define one of these and register it ----------------------------------
 * Every callback is optional (leave it 0). All of them run on the game's own threads -
 * which ones is logged at every boot (MODE_SDK.md, "What is measured").
 *
 *   static const struct pm_mode my_mode = {
 *       .name = "RAMP FRENZY", .init = on_init, .tick = on_tick,
 *       .shot = on_shot, .ball_end = on_ball_end,
 *   };
 *   PM_REGISTER(my_mode);
 */
struct pm_mode {
    const char *name;                 /* shown in the log; keep it short */
    void (*init)(void);               /* once, on the game's first tick (the game is up; its
                                         scenes may still be loading - see pm_node) */
    void (*tick)(void);               /* 60 times a second, on the game's scheduler thread */
    void (*shot)(uint64_t shot);      /* every shot the game dispatches - see pm_shot() */
    void (*ball_end)(void);           /* the ball in play drained */
    void (*event)(unsigned id);       /* one of the game's EVENTS fired (ball start, multiball
                                         start...): see pm_event(). Called from the tick, within
                                         a tick of the game's own broadcast. */
};

#define PM_REGISTER(m)                                                                 \
    static const struct pm_mode *const pm__register_##m                               \
        __attribute__((used, section("pm_modes"))) = &(m)

/* ---- what this game can do ----------------------------------------------------------
 * A port lists only what was found and checked for its build. Ask before relying on a
 * capability, or just call - a missing one fails safely. */
#define PM_CAN_CALLOUT      0x0001u   /* pm_callout, pm_callout_nth */
#define PM_CAN_LIGHTS       0x0002u   /* pm_lights */
#define PM_CAN_SCREENS      0x0004u   /* pm_node, pm_text, pm_show, pm_set_text */
#define PM_CAN_CLIPS        0x0008u   /* pm_clip */
#define PM_CAN_OWN_SOUND    0x0010u   /* pm_callout_own_sound */
#define PM_CAN_MESSAGES     0x0020u   /* pm_message_set / pm_message_restore */
#define PM_CAN_AWARD_SCREEN 0x0040u   /* pm_award_screen */
#define PM_CAN_EVENTS       0x0080u   /* .event callbacks, pm_event */

int pm_can(unsigned what);            /* 1 if EVERY bit in `what` is available */
const char *pm_game(void);            /* the port's game, e.g. "godzilla_pro" */
const char *pm_version(void);         /* the port's version, e.g. "1.15" */

/* ---- the game, right now ----------------------------------------------------------- */
int pm_in_game(void);                 /* a game is being played (not attract, not a menu) */
unsigned pm_player(void);             /* the player up, 1-4; 0 when no game */
uint64_t pm_score(unsigned player);   /* that player's score */

/* ---- shots --------------------------------------------------------------------------
 * A SHOT is a 64-bit mask the game hands every mode when a playfield switch means
 * something: one bit per shot (a ramp, a target...). A single switch can dispatch twice -
 * first 0x1 ("a playfield switch was hit"), then its own shot bit - so test bits, never
 * compare the whole mask. The port names this game's shots: */
uint64_t pm_shot(const char *name);   /* the named shot's mask, or 0 if this game has none */
const char *pm_shot_name(uint64_t shot);          /* the first named shot in `shot`, or 0 */
int pm_shot_count(void);                          /* how many named shots the port has */
const char *pm_shot_at(int i, uint64_t *mask);    /* the i-th named shot (0-based), or 0 */

/* ---- one mode at a time ------------------------------------------------------------ */
int pm_begin(void);        /* 1 = your mode is now the one running; 0 = another one is */
void pm_end(void);         /* your mode stopped running */
int pm_running(void);      /* your mode is the one running */

/* ---- scoring ------------------------------------------------------------------------
 * Through the game's own scoring, so its playfield multiplier and its rules about when a
 * score may be added apply. Returns what was actually added (can be 0). */
uint64_t pm_score_add(unsigned player, uint64_t points);

/* ---- sound --------------------------------------------------------------------------
 * A callout is one of the game's own speech/sound requests, by id. The port names the
 * useful ones by role: pm_callout_id("ten_seconds"), "countdown", "time_up". */
unsigned pm_callout_id(const char *role);        /* 0 if the port has no such role */
void pm_callout(unsigned id);
void pm_callout_nth(unsigned id, unsigned n);    /* a numbered variant (a countdown's "3") */
/* A sound the card never shipped: carried by the game's callout `carrier`, with the
 * sound container key the build gave your appended sound (Modes tab / Write).
 * Countdown variants n = 0..4 are proven; others are not measured. */
int pm_callout_own_sound(unsigned carrier, const unsigned char key[8]);
/* A sound REQUEST by id, straight to the game's sound code: no city variant is swapped in.
 * A sound of your own is a request whose record the build re-pointed (Modes tab / Write,
 * MODE_SDK.md "Sounds of your own"). Each returns 0 when the port lacks the call. */
int pm_sound(unsigned request);          /* start it; 1 if the port has the call */
int pm_sound_active(unsigned request);   /* 1 while a channel plays it */
int pm_sound_stop(unsigned request);     /* stop every channel playing it; 1 if one was */
/* How a request competes for its sound bus (music, voice and each effect bus hold ONE sound
 * at a time): a new request takes a bus from a playing one of LOWER priority, or of EQUAL
 * priority when the playing one's steal flag (bit 0) is set; otherwise it is not played.
 * Sets the request's priority and flags (-1 leaves one as it is) and returns the old pair as
 * priority << 8 | flags, or -1 when the port has no request table (data sound_requests) or
 * the record does not look like one. Only for a request the game never plays itself, such
 * as the carrier of a sound of your own. */
int pm_sound_priority(unsigned request, int priority, int flags);
/* Item 150 follow-up (MODE_SDK.md "A music bed of your own"):
 * pm_sound_sid points `request` at ONE sound id until it is called again with sid 0, which puts
 * the request's own list back. The one music carrier plays a different bed for every mode this
 * way: each bed is a sound id the build bound to an appended record and no request names.
 * 1 = done; 0 when the port has no request table or the record does not look like one.
 * pm_sound_fade fades every channel playing `request` down to silence over `ms`, then stops it
 * (a stop at full level is a click); 1 if one was playing. Without the port's channel and voice
 * offsets it stops at once. pm_sound() on a request still fading ends that fade first.
 * pm_sound_playing fills up to `max` requests (and their bus bits: 0x01 music, 0x02 voice) of
 * the channels playing now; returns how many play, or -1 when the port has no channel table. */
int pm_sound_sid(unsigned request, unsigned sid);
int pm_sound_fade(unsigned request, unsigned ms);
int pm_sound_playing(unsigned *requests, unsigned *buses, int max);

/* ---- lights -------------------------------------------------------------------------
 * One command in the game's own light language, e.g.
 *   "blele --sweep 0 --lts 224 --red 0 --green 255 --blue 0 --freq 10 --use_alpha 1 --alpha 255"
 * The port supplies the owner id. Returns 1 only if it ran under a live show - without
 * one the game takes the command and lights nothing. MODE_SDK.md, "Lights". */
int pm_lights(const char *command);
int pm_lights_as(unsigned owner, const char *command);    /* a specific owner id */

/* ---- named inserts: the playfield's lamps, one by one (MODE_SDK.md "Lights: named inserts")
 * The port's `lamp` lines name every insert on the playfield (the game's own names: "LEFT RAMP",
 * "MASER", "POWERLINE LEFT"...) and the shots the game itself ties to each. A mode HOLDS an insert
 * with a colour and a pattern; while it holds it, that is what the insert shows, on top of the
 * game's own light shows, and every insert it does not hold keeps doing what the game wants (its
 * modes, battles, multiballs, attract). Releasing hands the insert back to the game at once.
 *
 * It rides the game's own layering: the game lights through LAYERS (lamp groups), each with a
 * priority, composited bottom to top every frame; a layer covers only the lights it holds. The
 * runtime gives the mode a layer of its own at priority 255 (the top) unless the mode asks for a
 * lower one, so a game show of a higher priority covers it there.
 *
 *   pm_lamp_shot(pm_shot("Left ramp"), PM_RGB(255, 0, 0), PM_LAMP_BLINK, 0);
 *   pm_lamp_set("TANK 2,ADV TRAIN,TANK 3", PM_RGB(255, 200, 0), PM_LAMP_CHASE, 150);
 *   ...
 *   pm_lamp_release_all();                    at the mode's end: the game has them back
 *
 * `names` is one insert or several separated by commas (case does not matter); a CHASE runs
 * across them in the order given, one lit at a time. `period_ms` 0 takes the pattern's own
 * (blink 500, pulse 1600, chase 150 a step). Each returns how many inserts it held or released;
 * 0 when none of the names is in the port, or the port has no lamp lines (pm_can(PM_CAN_LAMPS)). */
#define PM_CAN_LAMPS        0x2000u   /* pm_lamp_*: the port names inserts and the game's lamp layers */
#define PM_LAMP_SOLID       0
#define PM_LAMP_BLINK       1         /* on half the period, off half */
#define PM_LAMP_PULSE       2         /* breathes between dim and full */
#define PM_LAMP_CHASE       3         /* one insert of the set at a time, stepping every period */
#define PM_RGB(r, g, b)     ((((unsigned)(r) & 255u) << 16) | (((unsigned)(g) & 255u) << 8) | ((unsigned)(b) & 255u))
int pm_lamp_count(void);                                   /* how many inserts the port names */
const char *pm_lamp_at(int i, uint64_t *shots);            /* the i-th insert's name, and its shots */
int pm_lamp_find(const char *name);                        /* its index, or -1 */
int pm_lamp_set(const char *names, unsigned rgb, int pattern, unsigned period_ms);
int pm_lamp_shot(uint64_t shots, unsigned rgb, int pattern, unsigned period_ms);   /* a shot's inserts */
int pm_lamp_release(const char *names);
int pm_lamp_release_shot(uint64_t shots);
int pm_lamp_release_all(void);                             /* every insert THIS mode holds */
/* This mode's layer priority, 1-255 (255 when never called): a game show above it covers its
 * inserts. The inserts it holds move to the new layer. Returns the priority now in force. */
int pm_lamp_priority(unsigned priority);
/* The game's lamp layers right now, bottom to top: each one's priority, with 0x100 added for a
 * layer of ours. Returns how many there are (up to max), or -1 without the port's layer list. */
int pm_lamp_layers(unsigned *priorities, int max);

/* ---- the display --------------------------------------------------------------------
 * A SCREEN of your own is a node the build added to the game's "hud" scene (the Modes
 * tab does this). For a mode in the card project's folder modes/<folder>/ its names are
 * "PadMode_<folder>_Screen" and "PadMode_<folder>_Screen.PadMode_<folder>_Screen_Words"
 * (MODE_SDK.md, "Screens"). `scene` is a role the port names
 * ("hud") or a 40-hex scene id. A node is drawn only while its timeline AND this flag
 * allow it, and a built screen is VISIBLE by default - so find it and hide it. A scene
 * can load after your init runs: pm_node returns 0 until it has, so keep trying from
 * your tick (twice a second is plenty) until it is found. */
const char *pm_scene_id(const char *role);                /* the port's scene for a role */
void *pm_node(const char *scene, const char *path);       /* a picture/group node, or 0 */
void *pm_text(const char *scene, const char *path);       /* a text node, or 0 */
void pm_show(void *node, int on);
void pm_set_text(void *text, const char *words);

/* ---- clips --------------------------------------------------------------------------
 * A full-screen video from the game's in-game video bank, by name - a stock clip, or one
 * the build added. The runtime keeps drawing it every frame until it ends. */
int pm_clip(const char *name);        /* 1 if the game started it */
int pm_clip_playing(void);
void pm_clip_stop(void);

/* ---- the game's own message screens (optional, title specific) --------------------- */
int pm_message_set(unsigned id, const char *words);   /* show `words` wherever id is shown */
void pm_message_restore(unsigned id);
int pm_award_screen(unsigned type, unsigned message_id, uint64_t value);

/* ---- anything else a port carries ---------------------------------------------------- */
const char *pm_port_text(const char *name);           /* a `text` line, or 0 */
long pm_port_value(const char *name, long fallback);  /* a `value` line, or fallback */

/* ---- helpers --------------------------------------------------------------------------- */
void pm_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));  /* /dump/mode.log */
unsigned long pm_ms(void);            /* milliseconds since boot */
int pm_trigger(const char *name);     /* 1, once, when the file /dump/<name> appears */
long pm_read_file(const char *path, char *buf, unsigned long cap);  /* bytes read, or -1 */
int pm_trigger_text(const char *name, char *out, unsigned cap);  /* ...and its first line */
void pm_commas(char *out, unsigned cap, uint64_t value);          /* 1234567 -> "1,234,567" */
int pm_snprintf(char *out, unsigned long cap, const char *fmt, ...)
    __attribute__((format(printf, 3, 4)));

/* ---- the game's own modes ------------------------------------------------------------
 * Is one of the GAME'S modes going on (a battle, a multiball)? Asked through the game's
 * own mode manager, with the queries the game itself uses (MODE_SDK.md, "The game's own
 * modes"). "Running" means ACTIVE to the game: the mode is started for the player up, or
 * its timer or start sequence is still live. A mode that should not stack on the game's
 * own asks before it starts. */
#define PM_STOCK_ANY        0x1u      /* any of the game's modes */
#define PM_STOCK_MULTIBALL  0x2u      /* a multiball */
#define PM_STOCK_BATTLE     0x4u      /* a battle (Godzilla's kaiju battles) */
/* Of the kinds asked for, the first one active (checked BATTLE, then MULTIBALL, then ANY);
 * 0 = none of them; -1 = this port cannot tell (no stock queries for a kind asked) */
int pm_stock_mode_running(unsigned kinds);
const char *pm_stock_mode_what(unsigned kind);   /* "a battle", "a multiball", "a stock mode" */

/* ---- events -------------------------------------------------------------------------------
 * The game's rules talk through numbered EVENTS (a ball started, a multiball started, the
 * skill shot was made). The port names the ones measured for its build (`event` lines,
 * MODE_SDK.md "Events"); a mode's .event callback gets each named one as it fires:
 *
 *   static void on_event(unsigned id) { if ((int)id == pm_event("ball_start")) ... }
 *
 * Only events the port names are delivered, once per firing, on the tick thread. */
int pm_event(const char *name);       /* the named event's id, or -1 if this port has none */
const char *pm_event_name(unsigned id);                  /* the port's name for an id, or 0 */

/* ---- the battle roster (item 146; title specific: Godzilla) ---------------------------
 * Godzilla's battles are picked on its BATTLE SELECTION screen from a roster of seven
 * slots (0 Ebirah, 1 Titanosaurus, 2 Gigan, 3 Megalon, 4 King Ghidorah, 5 Megalon & Gigan,
 * 6 King Ghidorah & Gigan). A mode can CLAIM one slot: when the player picks it, the
 * game's battle for that slot does not start and `on_pick(slot)` runs instead, on the
 * game's thread, at the moment the battle would have started. on_pick returns 1 when it
 * took the pick (the battle is skipped) and 0 to let the game's own battle run.
 * The roster is a fixed-size table in the game's code: a mode takes a slot's place, it
 * cannot add an eighth. The slot's name and art on the selection screen are the card
 * build's job (MODE_SDK.md, "A monster in the roster"). */
#define PM_CAN_ROSTER       0x0100u   /* pm_roster_claim (0x0080 is item 147's PM_CAN_EVENTS) */
int pm_roster_slots(void);                                        /* 0 when the port has no roster */
int pm_roster_claim(unsigned slot, int (*on_pick)(unsigned slot)); /* 1 = claimed */
void pm_roster_release(unsigned slot);
/* When a mode started by a pick ends, call this: the battle rule then does what it does when one
 * of the game's battles stops (the ramps light again, so another battle can be qualified). Until
 * then the ramps stay dark and the scoop opens nothing, as during a battle of the game's own.
 * It acts only on a pick a mode took and has not given back yet, and only for the player who picked:
 * called while another player is up it waits until that player is up again, and after the game has
 * ended it does nothing (a new game lights every player's ramps). A mode that never calls it gets it
 * called at the end of the ball its pick was taken in. */
void pm_roster_done(void);
/* The slot's spoken name. When the cursor lands on a slot the selection screen plays that slot's
 * callout (Godzilla: slot 0 says "Ebirah!"). A claimed slot is SILENT, so the old monster's name is
 * never heard over the new art; this sets a sound request id of the mode's own for the slot it holds
 * (0 = silent), and releasing the slot puts the game's back. 1 = written; 0 when the caller does not
 * hold the slot or the port has no `data roster_screen_table`. */
int pm_roster_callout(unsigned slot, unsigned id);

/* ---- display priority (item 154 display; MODE_SDK.md "Display priority") ------------------
 * The game decides what is on its screen with PRIORITIES, on two levels: its DISPLAY EFFECTS
 * (152 on Godzilla, each with a priority 1-255: BATTLE IS LIT 177, a multiball's jackpot 184,
 * the tilt warning 241), one at a time, a higher one taking over and a lower one waiting; and,
 * inside its layered-display effect (priority 1), its LAYERED displays (the shot awards: LOOPS,
 * the Maser and powerline clips; the mode starts and totals), ranked the same way among
 * themselves. pm_display_priority makes your RUNNING mode, to that arbitration, a display of
 * `priority` (1-255, the display-effect scale): until you call it with 0, or your mode ends,
 *   - a display effect of the game's comes through only when its own priority beats `priority`
 *     (the battle select screen 196, the tilt warning 241); a lower one waits (BATTLE IS LIT
 *     177), or is refused, as it would be behind one of the game's own effects;
 *   - a layered display the game flags as a MODE START or TOTAL counts as one of the game's mode
 *     displays (priority 184): it comes through when that beats yours;
 *   - any other FULL-SCREEN layered display (LOOPS, combos, bonus) waits;
 *   - a FRAMED layered display (the Maser, powerline, building clips, drawn inside the score
 *     frame, under your screen) plays as the game layers it, except while your own clip plays.
 * A display that comes through covers your screen for its length; your screen is in view again
 * when it ends (nothing to call). Your clip stops being drawn the moment the game plays another
 * clip. 1 = held; 0 = the port has no display arbitration (PM_CAN_DISPLAY_PRIORITY), or your
 * mode is not the one running. */
#define PM_CAN_DISPLAY_PRIORITY 0x4000u   /* pm_display_priority (0x0100 is the roster's) */
int pm_display_priority(unsigned priority);
/* 1 while a display of the game's that beat your priority has the screen (your screen is
 * under it); 0 otherwise, and with no priority held. */
int pm_display_covered(void);

#endif
