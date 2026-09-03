/* theme.h - the boot menu's colours.
 *
 * A theme is one colour per ROLE (the background, the heading, a card's face
 * and frame plain and highlighted, its title / subtitle / label plain and
 * highlighted, the footer line, the countdown line).  The built-in themes and
 * the role names live in themes.json - one file, shared with the tools that
 * write a card - and reach this program through theme_table.h, generated at
 * build time by gen_themes.py.  images.conf picks a theme with theme=<name>
 * and may override any role with color_<role>=RRGGBB; theme=custom is the
 * default theme with the conf's overrides on top.  An unknown name is not an
 * error: the menu comes up in the default theme and says so in its log - a
 * broken theme must never stop a pinball machine from booting.
 */
#ifndef CODESELECT_THEME_H
#define CODESELECT_THEME_H

#include "theme_table.h"        /* TH_N, enum theme_role, THEME_DEFAULT, THEME_COUNT */

struct theme {
    char name[32];
    unsigned rgb[TH_N];         /* 0xRRGGBB per role */
};

/* the role a 'color_<role>' key names ("background", "card_hl", ...), or -1 */
int theme_role(const char *key);
const char *theme_role_name(int role);

/* 'RRGGBB' or '#RRGGBB' -> 0 ok, -1 not a colour */
int theme_parse_rgb(const char *val, unsigned *rgb);

/* the built-in of that name: 1 and *out filled (when given), or 0 */
int theme_builtin(const char *name, struct theme *out);
int theme_count(void);
const char *theme_name_at(int i);

/* The theme a conf asks for: *name* ("" = the default, "custom" = the default
 * as a base, a built-in's name, or an unknown name -> the default and *known
 * = 0), then every role whose *set* flag is on replaced by *rgb*.  Returns
 * how many roles the conf set. */
int theme_resolve(struct theme *out, const char *name, const unsigned *rgb,
                  const unsigned char *set, int *known);

#endif
