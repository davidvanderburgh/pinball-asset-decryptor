/* theme.c - see theme.h */
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include "theme.h"
#define THEME_DEFINE_TABLE
#include "theme_table.h"        /* the data, after struct theme is declared */

int theme_role(const char *key)
{
    int i;
    for (i = 0; i < TH_N; i++)
        if (!strcmp(key, theme_role_names[i])) return i;
    return -1;
}

const char *theme_role_name(int role)
{
    return role >= 0 && role < TH_N ? theme_role_names[role] : "?";
}

int theme_parse_rgb(const char *val, unsigned *rgb)
{
    unsigned v = 0;
    int i;
    if (*val == '#') val++;
    if (strlen(val) != 6) return -1;
    for (i = 0; i < 6; i++) {
        int ch = (unsigned char)val[i], d;
        if (ch >= '0' && ch <= '9') d = ch - '0';
        else if (ch >= 'a' && ch <= 'f') d = ch - 'a' + 10;
        else if (ch >= 'A' && ch <= 'F') d = ch - 'A' + 10;
        else return -1;
        v = (v << 4) | (unsigned)d;
    }
    *rgb = v;
    return 0;
}

int theme_count(void)
{
    return THEME_COUNT;
}

const char *theme_name_at(int i)
{
    return i >= 0 && i < THEME_COUNT ? theme_table[i].name : "";
}

int theme_builtin(const char *name, struct theme *out)
{
    int i;
    for (i = 0; i < THEME_COUNT; i++) {
        if (!strcmp(name, theme_table[i].name)) {
            if (out) *out = theme_table[i];
            return 1;
        }
    }
    return 0;
}

int theme_resolve(struct theme *out, const char *name, const unsigned *rgb,
                  const unsigned char *set, int *known)
{
    int i, n = 0;
    *known = 1;
    if (!name || !*name) {
        theme_builtin(THEME_DEFAULT, out);
    } else if (!strcmp(name, "custom")) {
        theme_builtin(THEME_DEFAULT, out);
        snprintf(out->name, sizeof out->name, "custom");
    } else if (!theme_builtin(name, out)) {
        theme_builtin(THEME_DEFAULT, out);
        *known = 0;
    }
    for (i = 0; i < TH_N; i++) {
        if (set && set[i]) {
            out->rgb[i] = rgb[i];
            n++;
        }
    }
    return n;
}
