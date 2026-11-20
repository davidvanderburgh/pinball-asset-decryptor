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
 *   padpieces recv         PAD-1465: a Send's bulk bytes over a plain TCP connection, beside the SSH one that
 *                          started this.  stdin: the Send's key, 64 hex digits (it came over SSH, so only this
 *                          computer knows it).  Prints "port N", then takes ONE connection that opens with
 *                          HMAC-SHA1(key, "pad-recv hello"); one that doesn't is dropped and the next waited for.
 *                          Then frames (big-endian): type u8, offset u64, len u32, pathlen u32, path, data, and
 *                          HMAC-SHA1(key, seq u64 + the frame).  A frame is checked BEFORE a byte of it is written,
 *                          so nothing this computer didn't send reaches a file.  Type 'W' writes data into path at
 *                          offset (created if missing, never truncated), 'E' ends: "ok BYTES\n" back on the
 *                          connection and stdout.  Anything wrong: "err WHAT\n" back, exit 1.
 *
 * Build: build.sh beside this file (static, no libraries).
 */
#define _FILE_OFFSET_BITS 64
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define VERSION "padpieces 2"

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

static void sha1_final(sha1_t *s, unsigned char *out)
{
    uint64_t bits = s->n * 8;
    unsigned char pad = 0x80, z = 0, len[8];
    int i;
    sha1_add(s, &pad, 1);
    while (s->k != 56) sha1_add(s, &z, 1);
    for (i = 0; i < 8; i++) len[i] = (unsigned char)(bits >> (56 - 8 * i));
    sha1_add(s, len, 8);
    for (i = 0; i < 20; i++)
        out[i] = (unsigned char)((s->h[i / 4] >> (24 - 8 * (i % 4))) & 0xff);
}

static void sha1_hex(sha1_t *s, char *out)
{
    unsigned char d[20];
    int i;
    sha1_final(s, d);
    for (i = 0; i < 20; i++)
        sprintf(out + 2 * i, "%02x", d[i]);
}

/* ---- HMAC-SHA1 (RFC 2104), key of at most 64 bytes */
typedef struct { sha1_t in; unsigned char okey[64]; } hmac_t;

static void hmac_init(hmac_t *h, const unsigned char *key, size_t klen)
{
    unsigned char ikey[64];
    size_t i;
    for (i = 0; i < 64; i++) {
        unsigned char k = i < klen ? key[i] : 0;
        ikey[i] = k ^ 0x36;
        h->okey[i] = k ^ 0x5c;
    }
    sha1_init(&h->in);
    sha1_add(&h->in, ikey, 64);
}

static void hmac_final(hmac_t *h, unsigned char *out)
{
    unsigned char inner[20];
    sha1_t o;
    sha1_final(&h->in, inner);
    sha1_init(&o);
    sha1_add(&o, h->okey, 64);
    sha1_add(&o, inner, 20);
    sha1_final(&o, out);
}

/* the same answer either way, in the same time: a MAC is never compared byte by byte with an early way out */
static int same20(const unsigned char *a, const unsigned char *b)
{
    unsigned char d = 0;
    int i;
    for (i = 0; i < 20; i++) d |= a[i] ^ b[i];
    return d == 0;
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

/* ---- recv (PAD-1465) */
#define RECV_MAX_DATA (4 << 20)
#define RECV_MAX_PATH 4096
#define RECV_WAIT 30            /* seconds for this computer to connect */
#define RECV_IDLE 120           /* seconds a connection may go quiet before it is given up on */

static int hexval(int c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static uint64_t be64(const unsigned char *p)
{
    uint64_t v = 0;
    int i;
    for (i = 0; i < 8; i++) v = v << 8 | p[i];
    return v;
}

static uint32_t be32(const unsigned char *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

static void say(int s, const char *fmt, const char *a, long long n)
{
    char msg[600];
    int len = snprintf(msg, sizeof msg, fmt, a, n);
    if (len > 0) {
        if (s >= 0) (void)!write(s, msg, (size_t)len);
        fputs(msg, stdout);
        fflush(stdout);
    }
}

static void mac_of(const unsigned char *key, uint64_t seq, const unsigned char *hdr, size_t hlen,
                   const unsigned char *path, size_t plen, const unsigned char *data, size_t dlen, unsigned char *out)
{
    hmac_t h;
    unsigned char sb[8];
    int i;
    for (i = 0; i < 8; i++) sb[i] = (unsigned char)(seq >> (56 - 8 * i));
    hmac_init(&h, key, 32);
    sha1_add(&h.in, sb, 8);
    sha1_add(&h.in, hdr, hlen);
    sha1_add(&h.in, path, plen);
    sha1_add(&h.in, data, dlen);
    hmac_final(&h, out);
}

static int do_recv(void)
{
    char line[200];
    unsigned char key[32], want[20], got[20], hdr[17], *data;
    char path[RECV_MAX_PATH + 1], open_path[RECV_MAX_PATH + 1] = "";
    struct sockaddr_in a;
    socklen_t al = sizeof a;
    int ls, s = -1, fd = -1, i, one = 1, big = 4 << 20;
    uint64_t seq = 0;
    long long total = 0;
    time_t until;
    struct timeval tv = { RECV_IDLE, 0 };
    hmac_t h;

    if (!fgets(line, sizeof line, stdin) || strlen(chomp(line)) != 64) { puts("err no key"); return 2; }
    for (i = 0; i < 32; i++) {
        int hi = hexval(line[2 * i]), lo = hexval(line[2 * i + 1]);
        if (hi < 0 || lo < 0) { puts("err no key"); return 2; }
        key[i] = (unsigned char)(hi << 4 | lo);
    }
    hmac_init(&h, key, 32);
    sha1_add(&h.in, (const unsigned char *)"pad-recv hello", 14);
    hmac_final(&h, want);

    data = malloc(RECV_MAX_DATA);
    ls = socket(AF_INET, SOCK_STREAM, 0);
    if (!data || ls < 0) { puts("err no socket"); return 1; }
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    setsockopt(ls, SOL_SOCKET, SO_RCVBUF, &big, sizeof big);
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    a.sin_port = 0;
    if (bind(ls, (struct sockaddr *)&a, sizeof a) < 0 || listen(ls, 4) < 0 ||
        getsockname(ls, (struct sockaddr *)&a, &al) < 0) {
        printf("err can't listen: %s\n", strerror(errno));
        return 1;
    }
    printf("port %d\n", ntohs(a.sin_port));
    fflush(stdout);

    /* the one connection that knows the key: any other is dropped, and the wait goes on */
    until = time(NULL) + RECV_WAIT;
    for (;;) {
        struct pollfd p = { ls, POLLIN, 0 };
        struct timeval hello = { 5, 0 };
        int left = (int)(until - time(NULL));
        if (left <= 0 || poll(&p, 1, left * 1000) <= 0) { puts("err nobody connected"); return 1; }
        s = accept(ls, NULL, NULL);
        if (s < 0) continue;
        setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &hello, sizeof hello);
        if (read_full(s, got, 20, -1) == 20 && same20(got, want)) break;
        close(s);
        s = -1;
    }
    close(ls);
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    setsockopt(s, SOL_SOCKET, SO_RCVBUF, &big, sizeof big);
    setsockopt(s, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);

    for (;;) {
        uint64_t off;
        uint32_t len, plen;
        if (read_full(s, hdr, sizeof hdr, -1) != (ssize_t)sizeof hdr) { say(-1, "err %s %lld\n", "cut off", total); return 1; }
        off = be64(hdr + 1);
        len = be32(hdr + 9);
        plen = be32(hdr + 13);
        if (len > RECV_MAX_DATA || plen > RECV_MAX_PATH) { say(s, "err %s %lld\n", "bad frame", total); return 1; }
        if (read_full(s, (unsigned char *)path, plen, -1) != (ssize_t)plen ||
            read_full(s, data, len, -1) != (ssize_t)len ||
            read_full(s, got, 20, -1) != 20) { say(-1, "err %s %lld\n", "cut off", total); return 1; }
        path[plen] = 0;
        mac_of(key, seq++, hdr, sizeof hdr, (unsigned char *)path, plen, data, len, want);
        if (!same20(got, want)) { say(s, "err %s %lld\n", "bad signature", total); return 1; }
        if (hdr[0] == 'E') break;
        if (hdr[0] != 'W' || !plen || strlen(path) != plen) { say(s, "err %s %lld\n", "bad frame", total); return 1; }
        if (strcmp(path, open_path)) {
            if (fd >= 0 && close(fd) < 0) { say(s, "err can't write %s %lld\n", open_path, total); return 1; }
            fd = open(path, O_WRONLY | O_CREAT, 0644);
            if (fd < 0) { open_path[0] = 0; say(s, "err can't write %s %lld\n", path, total); return 1; }
            snprintf(open_path, sizeof open_path, "%s", path);
        }
        if (write_full(fd, data, len, (off_t)off) < 0) { say(s, "err can't write %s %lld\n", path, total); return 1; }
        total += len;
    }
    if (fd >= 0 && close(fd) < 0) { say(s, "err can't write %s %lld\n", open_path, total); return 1; }
    say(s, "%sok %lld\n", "", total);
    close(s);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc >= 2 && !strcmp(argv[1], "version")) { puts(VERSION); return 0; }
    if (argc >= 2 && !strcmp(argv[1], "recv")) return do_recv();
    if (argc >= 3 && !strcmp(argv[1], "hash")) {
        long bs = atol(argv[2]);
        if (bs < 64 || bs > (16 << 20)) return 2;
        return do_hash((size_t)bs);
    }
    if (argc >= 2 && !strcmp(argv[1], "copy")) return do_copy();
    fprintf(stderr, "usage: padpieces version | hash BS | copy | recv\n");
    return 2;
}
