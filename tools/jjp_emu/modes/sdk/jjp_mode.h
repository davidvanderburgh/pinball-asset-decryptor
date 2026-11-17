/* jjp_mode.h - the C++ API of a JJP custom mode (PAD-1384).
 *
 * A mode is a <name>.mode file (its settings: name, start, scoring shots,
 * seconds, sounds, lamps, screen - the Modes tab's form) and, for a mode with
 * rules of its own, `code = <name>`: <name>.cpp, built to <name>.so beside it
 * (build_code.sh), which the runtime (jjpmodes.so, already inside the game)
 * loads and calls at the moments below.  The Blocks editor writes this same
 * C++ from its blocks.
 *
 *   #include "jjp_mode.h"
 *   static int jackpots;
 *   static void start() { jackpots = 0; jm_title("SUPER JACKPOTS"); }
 *   static int shot(const char *sw) {
 *       if (jm_is(sw, "switch_target_tv")) { jm_score(5000000); jackpots++; return JM_TAKEN; }
 *       return JM_GO_ON;
 *   }
 *   JM_REGISTER({ .api = JM_API, .start = start, .shot = shot });
 *
 * Rules (the game's own proc thread runs every call):
 *   - never block, never sleep, no threads: a call returns at once;
 *   - no C++ standard library (no new/delete, std::, exceptions, RTTI): the
 *     game's machine has its own, and a mode carries none of it.  Classes,
 *     templates, lambdas, constexpr and statics are all fine; keep state in
 *     statics;
 *   - names (switches, lamps, sounds, coils) are the game's own, as in the
 *     form, written as string literals ("switch_target_tv"): the runtime
 *     finds the switches and coils a mode's code uses by its literals, and the
 *     Modes tab's Check reads them against the game.
 *
 * Every jm_* call acts on the mode whose callback is running; called at any
 * other time it does nothing (logged).  Everything is logged to
 * /jjpe/temp/jjpmodes.log with the mode's name.
 */
#ifndef JJP_MODE_H
#define JJP_MODE_H

#include <stdio.h>     /* snprintf - plain C library calls a mode may make (build_code.sh lists them) */
#include <string.h>

#define JM_API 1
#define JM_GO_ON 0      /* shot(): the form's own handling goes on (points, sounds, completion) */
#define JM_TAKEN 1      /* shot(): this hit is the code's alone - the form scores nothing for it */

#ifdef __cplusplus
extern "C" {
#endif

/* The moments a mode is called at.  Leave out any it does not need (C++20
 * designated initializers, in this order). */
struct jm_mode {
    int api;                              /* JM_API */
    void (*start)(void);                  /* it has just started (its form's start sound, multiball... done) */
    int (*shot)(const char *sw);          /* any switch hit while it runs: JM_TAKEN or JM_GO_ON */
    void (*scored)(const char *sw);       /* after the form scored one of its scoring shots */
    void (*tick)(void);                   /* ten times a second while it runs (not while paused) */
    void (*end)(const char *why);         /* it is over: "time", "completion", "its code", "ball end"... */
    void (*idle)(const char *sw);         /* any switch hit in a game while it is NOT running: jm_start() starts it */
};

/* -- points and time -------------------------------------------------------- */
void jm_score(long long points);        /* through the game's own scoring; adds to the mode total */
long long jm_total(void);               /* the mode total of this run */
int jm_hits(void);                      /* the form's scoring shots made this run */
int jm_switch_hits(const char *sw);     /* hits of one switch this run (taken or not) */
int jm_seconds_left(void);
void jm_set_seconds(int seconds);       /* the clock to this (1 or more) */
void jm_add_seconds(int seconds);       /* more time (negative: less, never under 1) */
long jm_ms(void);                       /* ms since it started */
/* -- the mode ---------------------------------------------------------------- */
void jm_end(void);                      /* end it now ("its code") */
void jm_start(void);                    /* from idle(): start it at the next free moment, as a start rule does */
int jm_running(void);
void jm_title(const char *text);        /* the panel's title this run (empty: the form's title) */
/* -- the game's things, by its own names ------------------------------------- */
int jm_sound(const char *name);         /* a game sound (se_...); 0 = no such sound */
int jm_lamp(const char *name, unsigned rgb, int flashes_a_second);   /* lp_/ls_ in the mode's own lamp layer */
void jm_lamp_off(const char *name);     /* back to the game */
int jm_coil(const char *name, int ms);  /* pulse a coil the form may fire (0 ms = its own pulse) */
int jm_multiball(int balls, int ball_save_seconds);
int jm_ball_save(int seconds);
void jm_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
/* sw is the game's name for a switch: jm_is(sw, "switch_target_tv") */
static inline int jm_is(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

#ifdef __cplusplus
}
#define JM_C_BEGIN extern "C" {
#define JM_C_END }
#else
#define JM_C_BEGIN
#define JM_C_END
#endif
/* A mode library links no C runtime start files; a static object with a
 * destructor still names this (and then __cxa_atexit, which the check refuses). */
JM_C_BEGIN __attribute__((weak, visibility("hidden"))) void *__dso_handle = &__dso_handle; JM_C_END
/* JM_REGISTER({ .api = JM_API, .start = ..., ... }); once per mode */
#define JM_REGISTER(...) static const struct jm_mode jm_mode_this_ = __VA_ARGS__; \
    JM_C_BEGIN __attribute__((visibility("default"), used)) const struct jm_mode *jm_mode_def = &jm_mode_this_; JM_C_END \
    static_assert(1, "")
#endif
