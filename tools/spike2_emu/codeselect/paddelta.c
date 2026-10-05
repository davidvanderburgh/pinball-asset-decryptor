/* paddelta.c - rebuild a game program from another one and a delta, on a
 * Barrels of Fun machine (PAD-342).
 *
 *     paddelta SOURCE DELTA OUT
 *
 * WHY A DELTA.  A multi-boot update has to carry every game program it
 * offers, and a BOF update is one file on a FAT32 stick, which cannot hold a
 * file of 4 GiB or more.  Labyrinth's program is 4.3 GB (2.9 GB packed), so
 * two of them do not fit in one update.  But a mod of a title is that title's
 * program with some of its packed files changed: the Sarah build of Labyrinth
 * shares its first 1.5 GB (the engine) and 8,411 of its 8,512 packed files
 * byte for byte with stock, and differs in 311 MB.  So the update carries the
 * first program whole and every other one as a DELTA against it, and the
 * install step rebuilds them here.  The builder (tools/bof_emu/mkbofmulti.py)
 * makes the delta from the programs' own Godot pack directories, runs THIS
 * program on it before it ships anything, and writes each rebuilt program's
 * md5 into the update; the install step checks that md5 with md5sum.
 *
 * THE FORMAT, little-endian throughout:
 *
 *     "PADDLT01"                     8 bytes
 *     u64 source size, u64 target size
 *     ops, until 'E':
 *       'C' u64 offset u64 length    copy that range of SOURCE
 *       'D' u64 length, length bytes the bytes themselves
 *       'E'                          end; the output is then exactly target size
 *
 * OUT is written as OUT.part and renamed over OUT only when every op is done,
 * the size is right and the data is on the disk (fsync), so a power cut or a
 * full disk leaves no half program under the real name.  Exit 0 = OUT is the
 * target; 2 = usage; 3 = a read / write / space failure; 4 = the delta does
 * not describe a program from this SOURCE.  One line on stderr says which.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/stat.h>

#define BUF (4u << 20)

static const char *g_out_part;

static int fail(int code, const char *fmt, const char *a, const char *b)
{
    fprintf(stderr, "paddelta: ");
    fprintf(stderr, fmt, a, b);
    fprintf(stderr, "\n");
    if (g_out_part) unlink(g_out_part);
    return code;
}

static int read_full(int fd, void *p, size_t n)
{
    size_t got = 0;
    while (got < n) {
        ssize_t r = read(fd, (char *)p + got, n - got);
        if (r < 0) { if (errno == EINTR) continue; return -1; }
        if (r == 0) return -1;
        got += (size_t)r;
    }
    return 0;
}

static int write_full(int fd, const void *p, size_t n)
{
    size_t put = 0;
    while (put < n) {
        ssize_t w = write(fd, (const char *)p + put, n - put);
        if (w < 0) { if (errno == EINTR) continue; return -1; }
        put += (size_t)w;
    }
    return 0;
}

static int u64(int fd, uint64_t *v)
{
    unsigned char b[8];
    int i;
    if (read_full(fd, b, 8) < 0) return -1;
    *v = 0;
    for (i = 7; i >= 0; i--) *v = (*v << 8) | b[i];
    return 0;
}

int main(int argc, char **argv)
{
    static char part[4096];
    unsigned char *buf;
    char magic[8];
    uint64_t src_size, dst_size, done = 0;
    struct stat st;
    int src, dlt, out;

    if (argc != 4) {
        fprintf(stderr, "usage: paddelta SOURCE DELTA OUT\n");
        return 2;
    }
    if (snprintf(part, sizeof part, "%s.part", argv[3]) >= (int)sizeof part)
        return fail(2, "%s%s: the output path is too long", argv[3], "");
    src = open(argv[1], O_RDONLY | O_CLOEXEC);
    if (src < 0) return fail(3, "%s: %s", argv[1], strerror(errno));
    dlt = open(argv[2], O_RDONLY | O_CLOEXEC);
    if (dlt < 0) return fail(3, "%s: %s", argv[2], strerror(errno));
    if (read_full(dlt, magic, 8) < 0 || memcmp(magic, "PADDLT01", 8))
        return fail(4, "%s%s: not a PAD delta (no PADDLT01 header)", argv[2], "");
    if (u64(dlt, &src_size) < 0 || u64(dlt, &dst_size) < 0)
        return fail(4, "%s%s: the header is cut short", argv[2], "");
    if (fstat(src, &st) < 0) return fail(3, "%s: %s", argv[1], strerror(errno));
    if ((uint64_t)st.st_size != src_size)
        return fail(4, "%s%s: is not the program this delta was made against (the size differs)", argv[1], "");
    buf = malloc(BUF);
    if (!buf) return fail(3, "%s%s: out of memory", "", "");
    unlink(part);
    out = open(part, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0755);
    if (out < 0) return fail(3, "%s: %s", part, strerror(errno));
    g_out_part = part;
    for (;;) {
        unsigned char op;
        uint64_t off = 0, len = 0;
        if (read_full(dlt, &op, 1) < 0) return fail(4, "%s%s: ends without its end mark", argv[2], "");
        if (op == 'E') break;
        if (op == 'C') {
            if (u64(dlt, &off) < 0 || u64(dlt, &len) < 0) return fail(4, "%s%s: a copy is cut short", argv[2], "");
            if (off > src_size || len > src_size - off)
                return fail(4, "%s%s: a copy reaches past the end of the source", argv[2], "");
            while (len) {
                size_t n = len < BUF ? (size_t)len : BUF;
                ssize_t r = pread(src, buf, n, (off_t)off);
                if (r <= 0) return fail(3, "%s: read failed: %s", argv[1], r < 0 ? strerror(errno) : "end of file");
                if (write_full(out, buf, (size_t)r) < 0) return fail(3, "%s: %s", part, strerror(errno));
                off += (uint64_t)r;
                len -= (uint64_t)r;
                done += (uint64_t)r;
            }
        } else if (op == 'D') {
            if (u64(dlt, &len) < 0) return fail(4, "%s%s: a data block is cut short", argv[2], "");
            while (len) {
                size_t n = len < BUF ? (size_t)len : BUF;
                if (read_full(dlt, buf, n) < 0) return fail(4, "%s%s: a data block is cut short", argv[2], "");
                if (write_full(out, buf, n) < 0) return fail(3, "%s: %s", part, strerror(errno));
                len -= n;
                done += n;
            }
        } else {
            return fail(4, "%s%s: an unknown op", argv[2], "");
        }
        if (done > dst_size) return fail(4, "%s%s: writes more than the target size", argv[2], "");
    }
    if (done != dst_size) return fail(4, "%s%s: ends short of the target size", argv[2], "");
    if (fsync(out) < 0) return fail(3, "%s: %s", part, strerror(errno));
    if (close(out) < 0) return fail(3, "%s: %s", part, strerror(errno));
    if (rename(part, argv[3]) < 0) return fail(3, "%s: %s", argv[3], strerror(errno));
    g_out_part = NULL;
    free(buf);
    close(src);
    close(dlt);
    return 0;
}
