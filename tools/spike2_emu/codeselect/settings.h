/* settings.h - the SETTINGS tile's screens (PAD-307).
 *
 * The last card of the menu, when the card has something to set, is SETTINGS.
 * START on it opens a list of settings - today one, Color correction, and a
 * way back - and Color correction is where an operator changes, ON THE
 * MACHINE, the colour profile each image's game draws through (PAD-305): the
 * middle shades and colour level per channel, the colour strength and the lift
 * of the darkest shades, the same controls the Color profile tab has, with a
 * test card on the screen corrected live as the numbers move.
 *
 * TEST PICTURES (PAD-1279) is the second entry: the built-in patterns
 * (testpics.h) and then the card's own test= pictures, animations and sounds,
 * one at a time, FULL SCREEN and pixel for pixel, drawn through the colour
 * correction of the game START picks (the numbers as the Color correction
 * screen has them now, saved or not) or through none.  A caption along the
 * bottom says what is up and hides itself after TEST_CAPTION_MS, so the
 * picture can be photographed whole; any key brings it back.
 *
 *   LEFT / RIGHT flipper (or Service - / +)   previous / next
 *   START / ACTION (or Service Select)        the next game's correction / none
 *                                             (on a sound: play it again;
 *                                             on BACK TO SETTINGS: back)
 *
 *   LEFT / RIGHT flipper (or Service - / +)   move between rows
 *   START / ACTION (or Service Select)        change the row / do it
 *   ...while changing a value: LEFT / RIGHT   less / more (held = repeats)
 *                              START          done
 *
 * EACH IMAGE KEEPS ITS OWN NUMBERS (David, 2026-10-01: "each game image can
 * have its own color profile"), starting from the ones it was built with
 * (images.conf color_profile=); "Save for every game" puts one set on all of
 * them.  Saved numbers go to the values file (colour.h) and reach a game the
 * next time it starts: the boot hook binds a copy of its program with the
 * numbers rewritten.  Nothing here boots anything, and no countdown runs while
 * a settings screen is up; SETTINGS_IDLE_MS without a key leaves without
 * saving, so a machine left in here still ends up playing.
 */
#ifndef CODESELECT_SETTINGS_H
#define CODESELECT_SETTINGS_H

#include <signal.h>
#include "conf.h"
#include "gfx.h"
#include "input.h"
#include "audio.h"
#include "theme.h"

#define SETTINGS_IDLE_MS 120000
/* ...and inside Test pictures, where looking without pressing is the point */
#define TEST_IDLE_MS 600000
#define TEST_CAPTION_MS 5000

struct settings_env {
    struct gfx *g;
    struct gfx_font *font;
    const struct theme *th;
    const struct conf *c;
    struct input *in;                    /* NULL: nothing to read (a snapshot) */
    struct audio *au;
    const struct audio_clip *move;       /* the menu's move sound, or NULL */
    const char *colour_file;             /* the values file (DEF_COLOUR_FILE) */
    const char *media_dir;               /* where test= files are (PAD-1279), or NULL */
    int testcard;                        /* a TEST CARD (conf testcard=on): no way back to
                                            a menu, no idle exit, TEST CARD as the heading */
    int first_image;                     /* the image Color correction opens on, or -1 */
    void (*present)(void *ctx);          /* upload what is dirty and swap */
    void *ctx;
    volatile sig_atomic_t *stop;
};

/* The settings screens, from the list, until the operator leaves them (or
 * *stop, or SETTINGS_IDLE_MS of nothing).  The caller repaints its menu after. */
void settings_run(struct settings_env *e);

/* --snapshot --screen: draw one screen once, as it comes up - `screen` is
 * "settings", "color" or "test"; `row` the highlighted row (-1 = the first),
 * or for "test" the item (the built-in patterns first); `editing` whether that
 * row is being changed, or for "test" that the caption is hidden.  0 ok, -1 an
 * unknown screen (in why). */
int settings_snapshot(struct settings_env *e, const char *screen, int row, int editing,
                      char *why, int whylen);

#endif
