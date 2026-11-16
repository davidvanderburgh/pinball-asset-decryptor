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
/* PAD-1325: the store's own section table - the offsets of its audits and
 * adjustments.  Spike 2 (32-bit) keeps them as u32 at 0x7c (audits at 208);
 * Spike 3 (64-bit, the same struct with 8-byte fields) as u64 at 0xa8, its
 * audits at 336 and its adjustments 8 bytes past their end (Star Wars ELG
 * 1.10: 231 audits, adjustments at 9584), so 208 + audits * 40 lands 136
 * bytes short of the first one. */
#define NVM_S2_TABLE 0x7c
#define NVM_S3_TABLE 0xa8

static unsigned u16le(const unsigned char *p) { return p[0] | (p[1] << 8); }
static unsigned u32le(const unsigned char *p)
{
    return p[0] | (p[1] << 8) | (p[2] << 16) | ((unsigned)p[3] << 24);
}

static unsigned long long u64le(const unsigned char *p)
{
    return (unsigned long long)u32le(p) | ((unsigned long long)u32le(p + 4) << 32);
}

/* where the adjustment records start in a store of len bytes with n_audits
 * audits and n_adj adjustments: the section table's word when it is one that
 * fits, else Spike 2's fixed layout */
static long adjustments_at(const unsigned char *d, long len, unsigned n_audits, unsigned n_adj)
{
    long fixed = NVM_AUDITS_AT + (long)n_audits * NVM_AUDIT_LEN;
    long need = (long)n_adj * NVM_ADJ_LEN;
    if (len >= NVM_S2_TABLE + 8 && u32le(d + NVM_S2_TABLE) == NVM_AUDITS_AT) {
        long a = (long)u32le(d + NVM_S2_TABLE + 4);
        if (a >= fixed && a + need <= len) return a;
    }
    if (len >= NVM_S3_TABLE + 16) {
        unsigned long long au = u64le(d + NVM_S3_TABLE), ad = u64le(d + NVM_S3_TABLE + 8);
        if (au >= NVM_S3_TABLE + 16 && au < (unsigned long long)len
            && ad >= au + (unsigned long long)n_audits * NVM_AUDIT_LEN
            && ad + (unsigned long long)need <= (unsigned long long)len)
            return (long)ad;
    }
    return fixed;
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
    off = adjustments_at(d, len, n_audits, n_adj);
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
