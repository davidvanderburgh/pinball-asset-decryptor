/* conf.c - see conf.h */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include <unistd.h>
#include "conf.h"
#include "nvm.h"

static char *trim(char *s)
{
    char *e;
    while (*s && isspace((unsigned char)*s)) s++;
    e = s + strlen(s);
    while (e > s && isspace((unsigned char)e[-1])) *--e = 0;
    return s;
}

/* bounded copy, truncating at CONF_STR-1. memmove rather than snprintf: dst
 * and src can both sit inside one struct conf (title <- device), and GCC 13's
 * -Wrestrict flags snprintf's restrict-qualified dst for that even though the
 * fields never overlap - this keeps the build warning-free. */
static void copy_field(char *dst, const char *src)
{
    size_t n = strlen(src);
    if (n >= CONF_STR) n = CONF_STR - 1;
    memmove(dst, src, n);
    dst[n] = 0;
}

/* something the file got wrong that must NOT stop the machine booting: kept
 * for the caller to log.  The count keeps climbing after the text runs out,
 * so a conf with forty bad members says forty and shows the first sixteen. */
static void conf_warn(struct conf *c, const char *fmt, ...)
{
    va_list ap;
    if (c->nwarn < CONF_MAX_WARN) {
        va_start(ap, fmt);
        vsnprintf(c->warn[c->nwarn], CONF_WARN_STR, fmt, ap);
        va_end(ap);
    }
    c->nwarn++;
}

/* split a '|'-separated line into up to seven trimmed fields; missing ones
 * come back NULL.  Shared by image= and group=, which carry the same seven. */
static void split_fields(char *val, char *fld[7])
{
    char *p = val;
    int k, nf = 0;
    for (k = 0; k < 7; k++) fld[k] = NULL;
    while (p && nf < 7) {
        char *bar = strchr(p, '|');
        if (bar) *bar++ = 0;
        fld[nf++] = trim(p);
        p = bar;
    }
}

/* the display half of an image= or group= line: fields 1..6 */
static void copy_card_fields(struct conf_image *im, char *fld[7])
{
    copy_field(im->title, fld[1] ? fld[1] : "");
    copy_field(im->subtitle, fld[2] ? fld[2] : "");
    copy_field(im->art, fld[3] ? fld[3] : "");
    copy_field(im->anim, fld[4] ? fld[4] : "");
    copy_field(im->music, fld[5] ? fld[5] : "");
    copy_field(im->confirm, fld[6] ? fld[6] : "");
}

/* '3-5', '3,5,7-9' -> image indexes, in the order written.  Range ends are
 * inclusive.  A token that is not a number or a range is dropped with a
 * warning rather than refusing the file; so is a range written backwards.
 * Bounds are NOT checked here - the image lines may not all be read yet - so
 * resolve_groups does that once the file is done. */
static const char *const ROLL_NAMES[] = { "not-last", "any", "shuffle" };

const char *conf_roll_name(int roll)
{
    if (roll < 0 || roll >= (int)(sizeof ROLL_NAMES / sizeof ROLL_NAMES[0]))
        return ROLL_NAMES[CONF_ROLL_NOT_LAST];
    return ROLL_NAMES[roll];
}

int conf_roll_from_name(const char *word)
{
    int k;
    if (!word) return -1;
    for (k = 0; k < (int)(sizeof ROLL_NAMES / sizeof ROLL_NAMES[0]); k++)
        if (!strcmp(word, ROLL_NAMES[k])) return k;
    return -1;
}

int conf_card_roll(const struct conf *c, int k)
{
    int g = conf_card_group(c, k);
    return g >= 0 ? c->grp[g].roll : CONF_ROLL_NOT_LAST;
}

static void parse_members(struct conf *c, struct conf_group *g, const char *spec,
                          const char *path, int lineno)
{
    char buf[CONF_STR], *p;
    snprintf(buf, sizeof buf, "%s", spec);
    p = buf;
    while (*p) {
        char *comma = strchr(p, ',');
        char *tok, *dash, *end;
        long a, b, v;
        if (comma) *comma++ = 0;
        tok = trim(p);
        p = comma ? comma : p + strlen(p);
        if (!*tok) continue;
        dash = strchr(tok + 1, '-');   /* +1: a leading '-' is a bad token, not a range */
        if (dash) *dash++ = 0;
        a = strtol(tok, &end, 10);
        if (end == tok || *end) {
            conf_warn(c, "%s:%d: group member '%s' is not a number: dropped", path, lineno, tok);
            continue;
        }
        b = a;
        if (dash) {
            b = strtol(dash, &end, 10);
            if (end == dash || *end) {
                conf_warn(c, "%s:%d: group range end '%s' is not a number: dropped", path, lineno, dash);
                continue;
            }
            if (b < a) {
                conf_warn(c, "%s:%d: group range %ld-%ld runs backwards: dropped", path, lineno, a, b);
                continue;
            }
        }
        for (v = a; v <= b; v++) {
            if (g->nmember >= CONF_MAX_IMAGES) {
                conf_warn(c, "%s:%d: group names more than %d members: the rest are dropped",
                          path, lineno, CONF_MAX_IMAGES);
                return;
            }
            g->member[g->nmember++] = (int)v;
        }
    }
}

static int clamp_int(const char *val, int lo, int hi)
{
    long v = strtol(val, NULL, 10);
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    return (int)v;
}

/* append one card and record which images it owns.  The ONLY thing in the
 * group machinery that can refuse a file: too many cards is the same class of
 * mistake as too many image lines, and is refused the same way. */
static int add_card(struct conf *c, int image, int group, const char *path, char *err, int errlen)
{
    struct conf_card *cd;
    if (c->ncards >= CONF_MAX_CARDS) {
        snprintf(err, errlen, "%s: more than %d cards (%d images, %d group(s))",
                 path, CONF_MAX_CARDS, c->n, c->ngroups);
        return -1;
    }
    cd = &c->cards[c->ncards];
    cd->image = image;
    cd->group = group;
    if (image >= 0) {
        /* AN IMAGE'S OWN CARD ALWAYS WINS the highlight.  A kept member has two
         * cards, and the one a player means when they pick that build is its
         * own - so this overwrites the group's claim, and it runs later because
         * the group line sits before its members. */
        c->card_of[image] = (short)c->ncards;
    } else {
        int k;
        for (k = 0; k < c->grp[group].nmember; k++)
            if (c->card_of[c->grp[group].member[k]] < 0)
                c->card_of[c->grp[group].member[k]] = (short)c->ncards;
    }
    c->ncards++;
    return 0;
}

/* ONCE THE WHOLE FILE IS READ: bound-check every member, hand each image to
 * the first group that claims it, drop whatever is left empty, and lay the
 * cards out in line order.  Everything here except the card limit is a
 * warning, because a mistyped group must never stop a machine booting. */
static int resolve_groups(struct conf *c, const int *gpos, const int *gline,
                          const char *path, char *err, int errlen)
{
    int owner[CONF_MAX_IMAGES];
    int dropped[CONF_MAX_GROUPS], placed[CONF_MAX_GROUPS];
    int i, gi, k, nkeep;

    for (i = 0; i < CONF_MAX_IMAGES; i++) { owner[i] = -1; c->card_of[i] = -1; }
    for (gi = 0; gi < CONF_MAX_GROUPS; gi++) { dropped[gi] = 0; placed[gi] = 0; }

    for (gi = 0; gi < c->ngroups; gi++) {
        struct conf_group *g = &c->grp[gi];
        nkeep = 0;
        for (k = 0; k < g->nmember; k++) {
            int m = g->member[k];
            if (m < 0 || m >= c->n) {
                conf_warn(c, "%s:%d: group member %d names no image line: dropped",
                          path, gline[gi], m);
                continue;
            }
            if (m == 0 && !g->keep) {
                /* a CONSUMING group would take the primary's own card away, and
                 * the primary is what the machine boots when the menu is not
                 * honoured.  A KEEPING group leaves that card where it is. */
                conf_warn(c, "%s:%d: image 0 is the primary and cannot be a member of a "
                          "consuming group: dropped", path, gline[gi]);
                continue;
            }
            if (owner[m] >= 0) {
                conf_warn(c, "%s:%d: image %d is already in the group on line %d: dropped",
                          path, gline[gi], m, gline[owner[m]]);
                continue;
            }
            owner[m] = gi;
            g->member[nkeep++] = m;
        }
        g->nmember = nkeep;
        if (nkeep == 0) {
            conf_warn(c, "%s:%d: group '%s' has no usable member: dropped",
                      path, gline[gi], g->card.title);
            dropped[gi] = 1;
            continue;
        }
        if (nkeep == 1)
            conf_warn(c, "%s:%d: group '%s' has one member: it behaves as a plain card",
                      path, gline[gi], g->card.title);
        if (!*g->card.title) copy_field(g->card.title, c->img[g->member[0]].title);
    }

    /* line order: a group card sits where its group= line sat, and the images
     * it owns do not get cards of their own */
    for (i = 0; i < c->n; i++) {
        for (gi = 0; gi < c->ngroups; gi++) {
            if (dropped[gi] || placed[gi] || gpos[gi] != i) continue;
            if (add_card(c, -1, gi, path, err, errlen) < 0) return -1;
            placed[gi] = 1;
        }
        /* a member of a CONSUMING group has no card of its own; a member of a
         * KEEPING group has both, and its own is the one the highlight prefers
         * (see conf_card_of_image) */
        if (owner[i] >= 0 && !c->grp[owner[i]].keep) continue;
        if (add_card(c, i, -1, path, err, errlen) < 0) return -1;
    }
    /* a group= line written past the last image line still gets its card */
    for (gi = 0; gi < c->ngroups; gi++) {
        if (dropped[gi] || placed[gi]) continue;
        if (add_card(c, -1, gi, path, err, errlen) < 0) return -1;
        placed[gi] = 1;
    }
    return 0;
}

int conf_load(struct conf *c, const char *path, char *err, int errlen)
{
    FILE *f;
    char line[1024];
    int lineno = 0;
    int gpos[CONF_MAX_GROUPS];    /* the image index each group= line sits before */
    int gline[CONF_MAX_GROUPS];   /* and the line it was on, for the warnings */

    memset(c, 0, sizeof *c);
    memset(gpos, 0, sizeof gpos);
    memset(gline, 0, sizeof gline);
    c->def = -1;
    c->def_card = -1;
    c->timeout = -1;
    c->volume = -1;
    c->volume_machine = 0;
    c->mv_store[0] = 0;
    c->mv_key_set = 0;
    c->mv_default = -1;
    c->mixer_volume = -1;
    f = fopen(path, "r");
    if (!f) {
        snprintf(err, errlen, "cannot open %s: %s", path, strerror(errno));
        return -1;
    }
    while (fgets(line, sizeof line, f)) {
        char *s, *eq, *key, *val;
        lineno++;
        s = trim(line);
        if (!*s || *s == '#') continue;
        eq = strchr(s, '=');
        if (!eq) continue;                      /* not key=value: ignore */
        *eq = 0;
        key = trim(s);
        val = trim(eq + 1);
        if (!strcmp(key, "image")) {
            /* up to seven '|'-separated fields:
             * device|title|subtitle|art|anim|music|confirm. A 3-field line is
             * the v1 form and a 6-field line the first v2 form; both stay
             * valid, and anything past the seventh field is ignored. */
            char *fld[7];
            struct conf_image *im;
            if (c->n >= CONF_MAX_IMAGES) {
                snprintf(err, errlen, "%s:%d: more than %d images", path, lineno, CONF_MAX_IMAGES);
                fclose(f);
                return -1;
            }
            im = &c->img[c->n];
            split_fields(val, fld);
            copy_field(im->device, fld[0] ? fld[0] : "");
            copy_card_fields(im, fld);
            if (!*im->device) {
                snprintf(err, errlen, "%s:%d: image without a device", path, lineno);
                fclose(f);
                return -1;
            }
            if (!*im->title) copy_field(im->title, im->device);
            c->n++;
        } else if (!strcmp(key, "group")) {
            /* <members>|<title>|<subtitle>[|art|anim|music[|confirm]] - the
             * same seven fields an image line carries, with the member list
             * where the device would be.  The card sits where this line sits,
             * which mkmulticard writes immediately before the first member,
             * so remember the image index the line arrived at. */
            char *fld[7];
            struct conf_group *g;
            if (c->ngroups >= CONF_MAX_GROUPS) {
                snprintf(err, errlen, "%s:%d: more than %d groups", path, lineno, CONF_MAX_GROUPS);
                fclose(f);
                return -1;
            }
            g = &c->grp[c->ngroups];
            split_fields(val, fld);
            copy_card_fields(&g->card, fld);
            {
                /* a leading '+' means the members KEEP their own cards as well
                 * as appearing behind this one */
                const char *spec = fld[0] ? fld[0] : "";
                const char *colon;
                if (*spec == '+') { g->keep = 1; spec++; }
                /* ...and an optional HOW IT PICKS, before the range: a word
                 * and a colon.  An unknown word is dropped out loud and the
                 * card still works, the way a bad member is. */
                colon = strchr(spec, ':');
                if (colon) {
                    char word[32];
                    int n = (int)(colon - spec), roll;
                    if (n < 0 || n >= (int)sizeof word) n = (int)sizeof word - 1;
                    memcpy(word, spec, (size_t)n);
                    word[n] = 0;
                    roll = conf_roll_from_name(word);
                    if (roll < 0)
                        conf_warn(c, "%s:%d: group picks '%s', which is not any / "
                                  "not-last / shuffle: %s is used", path, lineno,
                                  word, conf_roll_name(g->roll));
                    else
                        g->roll = roll;
                    spec = colon + 1;
                }
                parse_members(c, g, spec, path, lineno);
            }
            gpos[c->ngroups] = c->n;
            gline[c->ngroups] = lineno;
            c->ngroups++;
        } else if (!strcmp(key, "default")) {
            c->def = atoi(val);
        } else if (!strcmp(key, "default_card")) {
            c->def_card = atoi(val);
        } else if (!strcmp(key, "timeout")) {
            c->timeout = atoi(val);
        } else if (!strcmp(key, "font")) {
            copy_field(c->font, val);
        } else if (!strcmp(key, "media")) {
            copy_field(c->media, val);
        } else if (!strcmp(key, "sound_move")) {
            copy_field(c->sound_move, val);
        } else if (!strcmp(key, "sound_confirm")) {
            copy_field(c->sound_confirm, val);
        } else if (!strcmp(key, "volume")) {
            if (!strcmp(val, "machine")) c->volume_machine = 1;
            else if (*val) c->volume = clamp_int(val, 0, 100);
        } else if (!strcmp(key, "machine_volume")) {
            /* <store>|<sha1 hex>|<default> - a field this cannot read is
             * dropped, never fatal: the worst case is the plain volume */
            char tmp[CONF_STR * 3], *p = tmp, *q;
            snprintf(tmp, sizeof tmp, "%s", val);
            q = strchr(p, '|');
            if (q) *q++ = 0;
            copy_field(c->mv_store, p);
            if (q) {
                p = q;
                q = strchr(p, '|');
                if (q) *q++ = 0;
                c->mv_key_set = nvm_parse_key(p, c->mv_key) == 0;
                if (q && *q) c->mv_default = clamp_int(q, 0, 63);
            }
        } else if (!strcmp(key, "mixer_volume")) {
            if (*val) c->mixer_volume = clamp_int(val, 0, 63);
        } else if (!strcmp(key, "theme")) {
            copy_field(c->theme, val);
        } else if (!strncmp(key, "color_", 6)) {
            /* one colour on top of the theme.  An unknown role or a value
             * that is not RRGGBB is counted and ignored (main logs the
             * count): a typo in a colour must never stop a machine booting */
            int r = theme_role(key + 6);
            unsigned rgb;
            if (r < 0 || theme_parse_rgb(val, &rgb) < 0) {
                c->bad_colors++;
            } else {
                c->color[r] = rgb;
                c->color_set[r] = 1;
            }
        }
        /* unknown keys are ignored so the file can grow */
    }
    fclose(f);
    if (c->n == 0) {
        snprintf(err, errlen, "%s: no image= lines", path);
        return -1;
    }
    if (resolve_groups(c, gpos, gline, path, err, errlen) < 0) return -1;
    if (c->def >= c->n) c->def = -1;
    if (c->def_card >= c->ncards) c->def_card = -1;
    return 0;
}

int conf_has_art(const struct conf *c)
{
    int i;
    for (i = 0; i < c->ncards; i++) {
        const struct conf_image *im = conf_card_face(c, i);
        if (im->art[0] || im->anim[0]) return 1;
    }
    return 0;
}

const struct conf_image *conf_card_face(const struct conf *c, int k)
{
    if (k < 0 || k >= c->ncards) return &c->img[0];
    if (c->cards[k].group >= 0) return &c->grp[c->cards[k].group].card;
    return &c->img[c->cards[k].image];
}

int conf_card_of_image(const struct conf *c, int i)
{
    if (i < 0 || i >= c->n) return -1;
    return c->card_of[i];
}

int conf_card_boots(const struct conf *c, int k)
{
    if (k < 0 || k >= c->ncards) return -1;
    return c->cards[k].image;
}

int conf_card_group(const struct conf *c, int k)
{
    if (k < 0 || k >= c->ncards) return -1;
    return c->cards[k].group;
}

int conf_card_nmembers(const struct conf *c, int k)
{
    if (k < 0 || k >= c->ncards) return 0;
    if (c->cards[k].group >= 0) return c->grp[c->cards[k].group].nmember;
    return 1;
}

int conf_card_member(const struct conf *c, int k, int m)
{
    if (k < 0 || k >= c->ncards || m < 0 || m >= conf_card_nmembers(c, k)) return -1;
    if (c->cards[k].group >= 0) return c->grp[c->cards[k].group].member[m];
    return c->cards[k].image;
}

int conf_read_last(const char *path, int *card, struct conf_bags *bags)
{
    FILE *f = fopen(path, "r");
    char line[CONF_STR];
    int v = -1;
    if (card) *card = -1;
    if (bags) memset(bags, 0, sizeof *bags);
    if (!f) return -1;
    if (fgets(line, sizeof line, f)) {
        /* "<image>" from every selector up to 3.0, "<image> <card>" from this
         * one. A file with one number still reads, which is what a card
         * carried over from an older build has in it. */
        char *s = trim(line), *sp = strchr(s, ' ');
        if (sp) {
            *sp++ = 0;
            sp = trim(sp);
        }
        if (*s && strspn(s, "0123456789") == strlen(s)) v = atoi(s);
        if (v >= 0 && card && sp && *sp && strspn(sp, "0123456789") == strlen(sp))
            *card = atoi(sp);
    }
    /* ...and what each SHUFFLE has already dealt, one line per group:
     * `bag<G>=<i>,<j>,...`.  A file from an older selector has none, which
     * reads as a fresh deck - the right answer either way. */
    while (bags && fgets(line, sizeof line, f)) {
        char *eq, *tok, *s2 = trim(line);
        long g;
        if (strncmp(s2, "bag", 3)) continue;
        eq = strchr(s2, '=');
        if (!eq) continue;
        *eq++ = 0;
        g = strtol(s2 + 3, NULL, 10);
        if (g < 0 || g >= CONF_MAX_GROUPS) continue;
        for (tok = strtok(eq, ","); tok; tok = strtok(NULL, ",")) {
            char *e2;
            long v2 = strtol(trim(tok), &e2, 10);
            if (e2 == tok || v2 < 0 || v2 >= CONF_MAX_IMAGES) continue;
            if (bags->n[g] < CONF_MAX_IMAGES) bags->m[g][bags->n[g]++] = (int)v2;
        }
    }
    fclose(f);
    return v;
}

static int write_index(const char *path, int idx, int atomic, int card,
                       const struct conf_bags *bags)
{
    char tmp[512];
    FILE *f;
    if (atomic) snprintf(tmp, sizeof tmp, "%s.tmp", path);
    else snprintf(tmp, sizeof tmp, "%s", path);
    f = fopen(tmp, "w");
    if (!f) return -1;
    if (card >= 0) fprintf(f, "%d %d\n", idx, card);
    else fprintf(f, "%d\n", idx);
    if (bags) {
        int g, k;
        for (g = 0; g < CONF_MAX_GROUPS; g++) {
            if (bags->n[g] <= 0) continue;
            fprintf(f, "bag%d=", g);
            for (k = 0; k < bags->n[g]; k++)
                fprintf(f, "%s%d", k ? "," : "", bags->m[g][k]);
            fprintf(f, "\n");
        }
    }
    if (fflush(f) != 0 || fsync(fileno(f)) != 0) { /* fsync may fail on odd fs: tolerate */ }
    if (fclose(f) != 0) return -1;
    if (atomic && rename(tmp, path) != 0) { unlink(tmp); return -1; }
    return 0;
}

int conf_write_last(const char *path, int idx, int card,
                    const struct conf_bags *bags)
{
    return write_index(path, idx, 1, card, bags);
}

int conf_write_choice(const char *path, int idx)
{
    /* THE CHOICE FILE IS ONE NUMBER, FOR EVER: select.sh's awk and
     * run_game.sh both read it as an image index and neither has any idea
     * groups exist. The card goes in the last-choice file, which only this
     * program reads. */
    return write_index(path, idx, 1, -1, NULL);
}
