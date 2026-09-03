/* nvm.c - see nvm.h.  One pass over one small file; every failure is a
 * reason in a string, never a crash: a store this cannot read means the
 * menu plays at the default, not that the machine does not boot. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include "nvm.h"

#define NVM_CAP (4 * 1024 * 1024)      /* a store is ~40 KB; refuse a wrong file */
#define NVM_AUDITS_AT 208
#define NVM_AUDIT_LEN 40
#define NVM_ADJ_LEN 44

static unsigned u16le(const unsigned char *p) { return p[0] | (p[1] << 8); }
static unsigned u32le(const unsigned char *p)
{
    return p[0] | (p[1] << 8) | (p[2] << 16) | ((unsigned)p[3] << 24);
}

static int hexval(int c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int nvm_parse_key(const char *hex, unsigned char key[20])
{
    int i;
    if (!hex || strlen(hex) != 40) return -1;
    for (i = 0; i < 20; i++) {
        int hi = hexval(hex[2 * i]), lo = hexval(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) return -1;
        key[i] = (unsigned char)((hi << 4) | lo);
    }
    return 0;
}

/* a generation's name: hex digits and nothing else.  The machine writes a
 * <name>.crc32 sidecar beside every generation (4 bytes), which sorts
 * AFTER its store; a name with anything but hex in it is not a store. */
static int is_generation(const char *name)
{
    const char *p = name;
    if (!*p) return 0;
    for (; *p; p++)
        if (hexval(*p) < 0) return 0;
    return 1;
}

/* the newest generation in dir: the greatest file name (they are zero-padded
 * hex, so string order is age order); "" when the dir has none */
static int newest(const char *dir, char *out, int outlen)
{
    DIR *d = opendir(dir);
    struct dirent *e;
    out[0] = 0;
    if (!d) return -1;
    while ((e = readdir(d)) != NULL) {
        if (!is_generation(e->d_name)) continue;
        if (!out[0] || strcmp(e->d_name, out) > 0)
            snprintf(out, outlen, "%s", e->d_name);
    }
    closedir(d);
    return out[0] ? 0 : -1;
}

static unsigned char *slurp(const char *path, long *len, char *why, int whylen)
{
    FILE *f = fopen(path, "rb");
    unsigned char *buf;
    long n;
    if (!f) { snprintf(why, whylen, "%s: %s", path, strerror(errno)); return NULL; }
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0 || n > NVM_CAP) {
        snprintf(why, whylen, "%s: %ld bytes", path, n);
        fclose(f);
        return NULL;
    }
    buf = malloc((size_t)n);
    if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n) {
        snprintf(why, whylen, "%s: short read", path);
        fclose(f);
        free(buf);
        return NULL;
    }
    fclose(f);
    *len = n;
    return buf;
}

int nvm_read_value(const char *dir, const unsigned char key[20], int *value,
                   char *from, int fromlen, char *why, int whylen)
{
    char name[256], path[600];
    unsigned char *d;
    long len;
    unsigned n_audits, n_adj, i;
    long off;

    why[0] = 0;
    if (from && fromlen > 0) from[0] = 0;
    if (newest(dir, name, sizeof name) < 0) {
        snprintf(why, whylen, "no store in %s", dir);
        return -1;
    }
    snprintf(path, sizeof path, "%s/%s", dir, name);
    d = slurp(path, &len, why, whylen);
    if (!d) return -1;
    if (from && fromlen > 0) snprintf(from, fromlen, "%s", path);
    if (len < 0x40 || memcmp(d, "MAP0", 4) != 0) {
        snprintf(why, whylen, "%s: not a settings store", path);
        free(d);
        return -1;
    }
    n_audits = u16le(d + 0x3c);
    n_adj = u16le(d + 0x3e);
    off = NVM_AUDITS_AT + (long)n_audits * NVM_AUDIT_LEN;
    for (i = 0; i < n_adj; i++, off += NVM_ADJ_LEN) {
        const unsigned char *rec = d + off;
        unsigned v, check;
        if (off + NVM_ADJ_LEN > len) break;
        if (memcmp(rec, key, 20) != 0) continue;
        v = u32le(rec + 36);
        check = u32le(rec + 40);
        if ((check & 0xff) != (0xffu - (v & 0xff))) {
            snprintf(why, whylen, "%s: record %u fails its check (value %u, check 0x%x)",
                     path, i, v, check);
            free(d);
            return -1;
        }
        *value = (int)v;
        free(d);
        return 0;
    }
    snprintf(why, whylen, "%s: no record with that key (%u adjustments)", path, n_adj);
    free(d);
    return -1;
}
