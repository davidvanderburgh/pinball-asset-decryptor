/* padpieces - PAD-1435: the machine's side of Send to machine's piece reuse.
 *
 * Runs on the machine (Spike 2: armv7, Spike 3: aarch64), uploaded to its /run tmpfs for one Send and removed
 * after.  busybox alone needs a dd and a sha1sum process for every piece; this does a card's worth of pieces in
 * one process.
 *
 *   padpieces version
 *   padpieces hash BS      paths on stdin, one per line; for each: "= SIZE PATH" then the sha1 of each BS piece
 *                          (the last may be short), one per line; "! PATH" when it can't be read
 *   padpieces copy         lines "SRC\tSOFF\tDST\tDOFF\tLEN" on stdin, done IN ORDER: LEN bytes of SRC at SOFF
 *                          written into DST at DOFF (created if missing, never truncated); "ok BYTES" at the end
 *
 * Build: build.sh beside this file (static, no libraries).
 */
#define _FILE_OFFSET_BITS 64
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define VERSION "padpieces 1"

/* ---- SHA-1 (FIPS 180-4) */
typedef struct { uint32_t h[5]; uint64_t n; unsigned char b[64]; size_t k; } sha1_t;

#define ROL(x, s) (((x) << (s)) | ((x) >> (32 - (s))))

static void sha1_block(uint32_t *h, const unsigned char *p)
{
    uint32_t w[80], a, b, c, d, e, t;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (; i < 80; i++)
        w[i] = ROL(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    a = h[0]; b = h[1]; c = h[2]; d = h[3]; e = h[4];
    for (i = 0; i < 80; i++) {
        if (i < 20)      t = ((b & c) | (~b & d)) + 0x5A827999;
        else if (i < 40) t = (b ^ c ^ d) + 0x6ED9EBA1;
        else if (i < 60) t = ((b & c) | (b & d) | (c & d)) + 0x8F1BBCDC;
        else             t = (b ^ c ^ d) + 0xCA62C1D6;
        t += ROL(a, 5) + e + w[i];
        e = d; d = c; c = ROL(b, 30); b = a; a = t;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e;
}

static void sha1_init(sha1_t *s)
{
    s->h[0] = 0x67452301; s->h[1] = 0xEFCDAB89; s->h[2] = 0x98BADCFE; s->h[3] = 0x10325476; s->h[4] = 0xC3D2E1F0;
    s->n = 0; s->k = 0;
}

static void sha1_add(sha1_t *s, const unsigned char *p, size_t len)
{
    s->n += len;
    if (s->k) {
        while (len && s->k < 64) { s->b[s->k++] = *p++; len--; }
        if (s->k < 64) return;
        sha1_block(s->h, s->b);
        s->k = 0;
    }
    while (len >= 64) { sha1_block(s->h, p); p += 64; len -= 64; }
    memcpy(s->b, p, len);
    s->k = len;
}

static void sha1_hex(sha1_t *s, char *out)
{
    uint64_t bits = s->n * 8;
    unsigned char pad = 0x80, z = 0, len[8];
    int i;
    sha1_add(s, &pad, 1);
    while (s->k != 56) sha1_add(s, &z, 1);
    for (i = 0; i < 8; i++) len[i] = (unsigned char)(bits >> (56 - 8 * i));
    sha1_add(s, len, 8);
    for (i = 0; i < 20; i++)
        sprintf(out + 2 * i, "%02x", (s->h[i / 4] >> (24 - 8 * (i % 4))) & 0xff);
}

/* ---- io */
static ssize_t read_full(int fd, unsigned char *buf, size_t n, off_t off)
{
    size_t got = 0;
    while (got < n) {
        ssize_t r = off < 0 ? read(fd, buf + got, n - got) : pread(fd, buf + got, n - got, off + (off_t)got);
        if (r < 0) { if (errno == EINTR) continue; return -1; }
        if (r == 0) break;
        got += (size_t)r;
    }
    return (ssize_t)got;
}

static int write_full(int fd, const unsigned char *buf, size_t n, off_t off)
{
    size_t put = 0;
    while (put < n) {
        ssize_t w = pwrite(fd, buf + put, n - put, off + (off_t)put);
        if (w < 0) { if (errno == EINTR) continue; return -1; }
        put += (size_t)w;
    }
    return 0;
}

static char *chomp(char *s)
{
    size_t n = strlen(s);
    while (n && (s[n - 1] == '\n' || s[n - 1] == '\r')) s[--n] = 0;
    return s;
}

static int do_hash(size_t bs)
{
    unsigned char *buf = malloc(bs);
    char line[8192], hex[41];
    if (!buf) return 2;
    while (fgets(line, sizeof line, stdin)) {
        char *path = chomp(line);
        struct stat st;
        int fd;
        if (!*path) continue;
        fd = open(path, O_RDONLY);
        if (fd < 0 || fstat(fd, &st) < 0) { printf("! %s\n", path); if (fd >= 0) close(fd); continue; }
#ifdef POSIX_FADV_SEQUENTIAL
        posix_fadvise(fd, 0, 0, POSIX_FADV_SEQUENTIAL);
#endif
        printf("= %lld %s\n", (long long)st.st_size, path);
        for (;;) {
            ssize_t r = read_full(fd, buf, bs, -1);
            sha1_t s;
            if (r < 0) { printf("! %s\n", path); break; }
            if (r == 0) break;
            sha1_init(&s);
            sha1_add(&s, buf, (size_t)r);
            sha1_hex(&s, hex);
            puts(hex);
            if ((size_t)r < bs) break;
        }
        close(fd);
        fflush(stdout);
    }
    free(buf);
    return 0;
}

/* the last file opened each side stays open: a run of copies between the same two files opens each once */
static int do_copy(void)
{
    static unsigned char buf[1 << 20];
    char line[17000], src_open[8192] = "", dst_open[8192] = "";
    int sfd = -1, dfd = -1;
    long long total = 0;
    while (fgets(line, sizeof line, stdin)) {
        char *f[5], *p = chomp(line);
        long long soff, doff, len;
        int i;
        if (!*p) continue;
        for (i = 0; i < 5; i++) {
            f[i] = p;
            p = strchr(p, '\t');
            if (i < 4) { if (!p) { fprintf(stderr, "bad line\n"); return 2; } *p++ = 0; }
        }
        soff = atoll(f[1]); doff = atoll(f[3]); len = atoll(f[4]);
        if (strcmp(f[0], src_open)) {
            if (sfd >= 0) close(sfd);
            sfd = open(f[0], O_RDONLY);
            if (sfd < 0) { fprintf(stderr, "can't read %s: %s\n", f[0], strerror(errno)); return 1; }
            snprintf(src_open, sizeof src_open, "%s", f[0]);
        }
        if (strcmp(f[2], dst_open)) {
            if (dfd >= 0 && close(dfd) < 0) { fprintf(stderr, "can't write %s: %s\n", dst_open, strerror(errno)); return 1; }
            dfd = open(f[2], O_WRONLY | O_CREAT, 0644);
            if (dfd < 0) { fprintf(stderr, "can't write %s: %s\n", f[2], strerror(errno)); return 1; }
            snprintf(dst_open, sizeof dst_open, "%s", f[2]);
        }
        while (len > 0) {
            size_t n = len > (long long)sizeof buf ? sizeof buf : (size_t)len;
            ssize_t r = read_full(sfd, buf, n, (off_t)soff);
            if (r != (ssize_t)n) { fprintf(stderr, "short read %s at %lld\n", f[0], soff); return 1; }
            if (write_full(dfd, buf, n, (off_t)doff) < 0) {
                fprintf(stderr, "can't write %s: %s\n", f[2], strerror(errno));
                return 1;
            }
            soff += (long long)n; doff += (long long)n; len -= (long long)n; total += (long long)n;
        }
    }
    if (sfd >= 0) close(sfd);
    if (dfd >= 0 && close(dfd) < 0) { fprintf(stderr, "can't write %s: %s\n", dst_open, strerror(errno)); return 1; }
    printf("ok %lld\n", total);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc >= 2 && !strcmp(argv[1], "version")) { puts(VERSION); return 0; }
    if (argc >= 3 && !strcmp(argv[1], "hash")) {
        long bs = atol(argv[2]);
        if (bs < 64 || bs > (16 << 20)) return 2;
        return do_hash((size_t)bs);
    }
    if (argc >= 2 && !strcmp(argv[1], "copy")) return do_copy();
    fprintf(stderr, "usage: padpieces version | hash BS | copy\n");
    return 2;
}
