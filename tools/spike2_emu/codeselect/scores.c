/* scores.c - see scores.h.  Small files, plain stdio; every failure is a
 * reason in msg and the store as the game left it. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include "scores.h"

#define LK_CAP (1024 * 1024)       /* LKRAM is 7-20 KB; refuse a wrong file */
#define LK_KEEP 3                  /* the game's ring keeps three generations */
#define MAXGEN 64

static unsigned u32le(const unsigned char *p)
{
    return p[0] | (p[1] << 8) | (p[2] << 16) | ((unsigned)p[3] << 24);
}

static void put32le(unsigned char *p, unsigned v)
{
    p[0] = v & 0xff; p[1] = (v >> 8) & 0xff; p[2] = (v >> 16) & 0xff; p[3] = (v >> 24) & 0xff;
}

static unsigned crc32_buf(const unsigned char *p, long n)
{
    static unsigned t[256];
    static int ready;
    unsigned c;
    long i;
    if (!ready) {
        unsigned k, j;
        for (k = 0; k < 256; k++) {
            c = k;
            for (j = 0; j < 8; j++) c = (c & 1) ? 0xedb88320u ^ (c >> 1) : c >> 1;
            t[k] = c;
        }
        ready = 1;
    }
    c = 0xffffffffu;
    for (i = 0; i < n; i++) c = t[(c ^ p[i]) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

/* a generation's name: the game writes them "%s/%08d", so digits only;
 * <name>.crc32 and anything else in the directory is not one */
static int is_gen_name(const char *s)
{
    if (!*s) return 0;
    for (; *s; s++)
        if (*s < '0' || *s > '9') return 0;
    return 1;
}

static int cmp_name(const void *a, const void *b)
{
    return strcmp(*(char *const *)b, *(char *const *)a);    /* newest first */
}

/* the generations in dir, newest first; the count, -1 when dir cannot be read */
static int generations(const char *dir, char **names, int max)
{
    DIR *d = opendir(dir);
    struct dirent *e;
    int n = 0;
    if (!d) return -1;
    while ((e = readdir(d)) != NULL && n < max)
        if (is_gen_name(e->d_name)) names[n++] = strdup(e->d_name);
    closedir(d);
    qsort(names, n, sizeof *names, cmp_name);
    return n;
}

static void free_names(char **names, int n)
{
    while (n > 0) free(names[--n]);
}

static unsigned char *slurp(const char *path, long *len)
{
    FILE *f = fopen(path, "rb");
    unsigned char *buf;
    long n;
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END) < 0 || (n = ftell(f)) <= 0 || n > LK_CAP || fseek(f, 0, SEEK_SET) < 0) {
        fclose(f);
        return NULL;
    }
    buf = malloc(n);
    if (buf && fread(buf, 1, n, f) != (size_t)n) { free(buf); buf = NULL; }
    fclose(f);
    *len = n;
    return buf;
}

/* the NSEC section's offset in an LKRAM file whose sidecar and section CRC
 * both hold, else -1 */
static long good_lkram(const unsigned char *b, long n, const char *path)
{
    char side[600];
    unsigned char c[4];
    FILE *f;
    long s = 44;
    if (n < s + 20 || memcmp(b, "NFI2", 4) || memcmp(b + s, "NSEC", 4)) return -1;
    if (s + 8 + (long)u32le(b + s + 4) != n) return -1;
    if (u32le(b + s + 12) != crc32_buf(b + s + 20, n - s - 20)) return -1;
    snprintf(side, sizeof side, "%s.crc32", path);
    f = fopen(side, "rb");
    if (!f) return -1;
    if (fread(c, 1, 4, f) != 4) { fclose(f); return -1; }
    fclose(f);
    return u32le(c) == crc32_buf(b, n) ? s : -1;
}

/* the score block's offset (at its tag) inside the section, -1 when none */
static long find_block(const unsigned char *b, long n, long s)
{
    long o = s + 20;
    while (o + 20 <= n) {
        unsigned len = u32le(b + o + 4);
        if (memcmp(b + o, "NDAT", 4) && memcmp(b + o, "NMEM", 4)) return -1;
        if (len < 12 || o + 8 + (long)len > n) return -1;
        if (!memcmp(b + o, "NMEM", 4) && u32le(b + o + 8) == SCORES_BLOCK_ID) return o;
        o += 8 + len;
    }
    return -1;
}

/* the newest good generation of <store>/LKRAM: its bytes, length, path and
 * the score block in it.  0 ok; 1 with why when there is none that reads. */
struct lk {
    unsigned char *b;
    long n, sec, blk;
    char path[600], newest[64];
    int width;
};

static int read_newest(const char *store, struct lk *lk, char *why, int whylen)
{
    char dir[560], *names[MAXGEN];
    int n, i;
    memset(lk, 0, sizeof *lk);
    snprintf(dir, sizeof dir, "%s/LKRAM", store);
    n = generations(dir, names, MAXGEN);
    if (n <= 0) {
        snprintf(why, whylen, "%s has no generation yet", dir);
        if (n > 0) free_names(names, n);
        return 1;
    }
    snprintf(lk->newest, sizeof lk->newest, "%s", names[0]);
    lk->width = (int)strlen(names[0]);
    for (i = 0; i < n; i++) {
        snprintf(lk->path, sizeof lk->path, "%s/%s", dir, names[i]);
        lk->b = slurp(lk->path, &lk->n);
        if (!lk->b) continue;
        lk->sec = good_lkram(lk->b, lk->n, lk->path);
        if (lk->sec >= 0 && (lk->blk = find_block(lk->b, lk->n, lk->sec)) >= 0) {
            free_names(names, n);
            return 0;
        }
        free(lk->b);
        lk->b = NULL;
    }
    snprintf(why, whylen, "no generation in %s reads as a score table (%d there)", dir, n);
    free_names(names, n);
    return 1;
}

static int write_all(const char *path, const unsigned char *b, long n, const struct stat *like)
{
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    long off = 0;
    if (fd < 0) return -1;
    while (off < n) {
        ssize_t w = write(fd, b + off, n - off);
        if (w <= 0) { close(fd); unlink(path); return -1; }
        off += w;
    }
    if (like) {
        if (fchown(fd, like->st_uid, like->st_gid) < 0) { /* not root: the owner is ours */ }
        fchmod(fd, like->st_mode & 07777);
    }
    fsync(fd);
    return close(fd);
}

int scores_save(const char *store, const char *to, char *msg, int msglen)
{
    struct lk lk;
    char why[700], part[600];
    long len;
    if (read_newest(store, &lk, why, sizeof why)) {
        snprintf(msg, msglen, "scores: nothing to save: %s", why);
        return 1;
    }
    len = 8 + (long)u32le(lk.b + lk.blk + 4);
    snprintf(part, sizeof part, "%s.part", to);
    if (write_all(part, lk.b + lk.blk, len, NULL) < 0 || rename(part, to) < 0) {
        snprintf(msg, msglen, "scores: cannot write %s: %s", to, strerror(errno));
        unlink(part);
        free(lk.b);
        return 2;
    }
    snprintf(msg, msglen, "scores: saved the high scores of %s (%ld bytes) to %s", lk.path, len, to);
    free(lk.b);
    return 0;
}

int scores_load(const char *from, const char *store, char *msg, int msglen)
{
    struct lk lk;
    struct stat st, stc;
    unsigned char *blk, *out, c[4];
    long blen, have;
    char why[700], dir[560], path[640], side[660], *names[MAXGEN];
    unsigned long gen;
    int n, i, rc = 2;

    blk = slurp(from, &blen);
    if (!blk) {
        snprintf(msg, msglen, "scores: no saved table at %s: the store keeps its own", from);
        return 1;
    }
    if (blen < 20 || memcmp(blk, "NMEM", 4) || 8 + (long)u32le(blk + 4) != blen
            || u32le(blk + 8) != SCORES_BLOCK_ID) {
        snprintf(msg, msglen, "scores: %s is not a saved score table: the store keeps its own", from);
        free(blk);
        return 2;
    }
    if (read_newest(store, &lk, why, sizeof why)) {
        snprintf(msg, msglen, "scores: nothing to load into: %s", why);
        free(blk);
        return 1;
    }
    have = 8 + (long)u32le(lk.b + lk.blk + 4);
    if (have != blen || memcmp(lk.b + lk.blk + 12, blk + 12, 8)) {
        snprintf(msg, msglen, "scores: refused: the shared table has %ld bytes of %u-byte rows, this game's %ld"
                 " of %u-byte rows (another game version?): it keeps its own", blen, u32le(blk + 12), have,
                 u32le(lk.b + lk.blk + 12));
        goto out;
    }
    if (!memcmp(lk.b + lk.blk, blk, blen)) {
        snprintf(msg, msglen, "scores: %s already holds the shared table", lk.path);
        rc = 1;
        goto out;
    }
    out = lk.b;
    memcpy(out + lk.blk, blk, blen);
    put32le(out + lk.sec + 12, crc32_buf(out + lk.sec + 20, lk.n - lk.sec - 20));
    gen = strtoul(lk.newest, NULL, 10) + 1;   /* the game names them %08d */
    snprintf(dir, sizeof dir, "%s/LKRAM", store);
    snprintf(path, sizeof path, "%s/%0*lu", dir, lk.width, gen);
    snprintf(side, sizeof side, "%s.crc32", path);
    if (stat(lk.path, &st) < 0) memset(&st, 0, sizeof st);
    {
        char ls[640];
        snprintf(ls, sizeof ls, "%s.crc32", lk.path);
        if (stat(ls, &stc) < 0) stc = st;
    }
    /* the generation, then its sidecar: a power cut between the two leaves a
     * generation whose CRC does not hold, which the game passes over for the
     * one before it - the store as it was */
    put32le(c, crc32_buf(out, lk.n));
    if (write_all(path, out, lk.n, st.st_mode ? &st : NULL) < 0
            || write_all(side, c, 4, stc.st_mode ? &stc : NULL) < 0) {
        snprintf(msg, msglen, "scores: cannot write %s: %s: it keeps its own", path, strerror(errno));
        unlink(path);
        unlink(side);
        goto out;
    }
    /* the ring: the game keeps three; so does a store this wrote to */
    n = generations(dir, names, MAXGEN);
    for (i = LK_KEEP; i < n; i++) {
        char p[640];
        snprintf(p, sizeof p, "%s/%s", dir, names[i]);
        unlink(p);
        snprintf(p, sizeof p, "%s/%s.crc32", dir, names[i]);
        unlink(p);
    }
    if (n > 0) free_names(names, n);
    snprintf(msg, msglen, "scores: the shared high scores (%s) written into %s", from, path);
    rc = 0;
out:
    free(blk);
    free(lk.b);
    return rc;
}
