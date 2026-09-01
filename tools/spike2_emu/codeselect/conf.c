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

static void copy_field(char *dst, const char *src)
{
    snprintf(dst, CONF_STR, "%s", src);
}

int conf_load(struct conf *c, const char *path, char *err, int errlen)
{
    FILE *f;
    char line[1024];
    int lineno = 0;

    memset(c, 0, sizeof *c);
    c->def = -1;
    c->timeout = -1;
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
            char *a, *b, *p;
            struct conf_image *im;
            if (c->n >= CONF_MAX_IMAGES) {
                snprintf(err, errlen, "%s:%d: more than %d images", path, lineno, CONF_MAX_IMAGES);
                fclose(f);
                return -1;
            }
            im = &c->img[c->n];
            p = val;
            a = strchr(p, '|');
            if (a) { *a++ = 0; b = strchr(a, '|'); if (b) *b++ = 0; } else b = NULL;
            copy_field(im->device, trim(p));
            copy_field(im->title, a ? trim(a) : "");
            copy_field(im->subtitle, b ? trim(b) : "");
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
