/* conf.c - see conf.h */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include <unistd.h>
#include "conf.h"

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

static int clamp_int(const char *val, int lo, int hi)
{
    long v = strtol(val, NULL, 10);
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    return (int)v;
}

int conf_load(struct conf *c, const char *path, char *err, int errlen)
{
    FILE *f;
    char line[1024];
    int lineno = 0;

    memset(c, 0, sizeof *c);
    c->def = -1;
    c->timeout = -1;
    c->volume = -1;
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
            /* up to six '|'-separated fields: device|title|subtitle|art|anim|music;
             * a 3-field line is the v1 form and stays valid */
            char *fld[6];
            char *p = val;
            struct conf_image *im;
            int k, nf = 0;
            if (c->n >= CONF_MAX_IMAGES) {
                snprintf(err, errlen, "%s:%d: more than %d images", path, lineno, CONF_MAX_IMAGES);
                fclose(f);
                return -1;
            }
            im = &c->img[c->n];
            for (k = 0; k < 6; k++) fld[k] = NULL;
            while (p && nf < 6) {
                char *bar = strchr(p, '|');
                if (bar) *bar++ = 0;
                fld[nf++] = trim(p);
                p = bar;
            }
            copy_field(im->device, fld[0] ? fld[0] : "");
            copy_field(im->title, fld[1] ? fld[1] : "");
            copy_field(im->subtitle, fld[2] ? fld[2] : "");
            copy_field(im->art, fld[3] ? fld[3] : "");
            copy_field(im->anim, fld[4] ? fld[4] : "");
            copy_field(im->music, fld[5] ? fld[5] : "");
            if (!*im->device) {
                snprintf(err, errlen, "%s:%d: image without a device", path, lineno);
                fclose(f);
                return -1;
            }
            if (!*im->title) copy_field(im->title, im->device);
            c->n++;
        } else if (!strcmp(key, "default")) {
            c->def = atoi(val);
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
            if (*val) c->volume = clamp_int(val, 0, 100);
        } else if (!strcmp(key, "mixer_volume")) {
            if (*val) c->mixer_volume = clamp_int(val, 0, 63);
        }
        /* unknown keys are ignored so the file can grow */
    }
    fclose(f);
    if (c->n == 0) {
        snprintf(err, errlen, "%s: no image= lines", path);
        return -1;
    }
    if (c->def >= c->n) c->def = -1;
    return 0;
}

int conf_has_art(const struct conf *c)
{
    int i;
    for (i = 0; i < c->n; i++)
        if (c->img[i].art[0] || c->img[i].anim[0]) return 1;
    return 0;
}

int conf_read_last(const char *path)
{
    FILE *f = fopen(path, "r");
    char line[64];
    int v = -1;
    if (!f) return -1;
    if (fgets(line, sizeof line, f)) {
        char *s = trim(line);
        if (*s && strspn(s, "0123456789") == strlen(s)) v = atoi(s);
    }
    fclose(f);
    return v;
}

static int write_index(const char *path, int idx, int atomic)
{
    char tmp[512];
    FILE *f;
    if (atomic) snprintf(tmp, sizeof tmp, "%s.tmp", path);
    else snprintf(tmp, sizeof tmp, "%s", path);
    f = fopen(tmp, "w");
    if (!f) return -1;
    fprintf(f, "%d\n", idx);
    if (fflush(f) != 0 || fsync(fileno(f)) != 0) { /* fsync may fail on odd fs: tolerate */ }
    if (fclose(f) != 0) return -1;
    if (atomic && rename(tmp, path) != 0) { unlink(tmp); return -1; }
    return 0;
}

int conf_write_last(const char *path, int idx)
{
    return write_index(path, idx, 1);
}

int conf_write_choice(const char *path, int idx)
{
    return write_index(path, idx, 1);
}
