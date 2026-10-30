/* x11_raw.c - a full-screen window on an X server, spoken to in the X11
 * protocol itself: the Dutch Pinball (The Big Lebowski) build's screen
 * (PAD-853, tools/dp_emu/MULTIBOOT.md).
 *
 * WHY NO libX11.  A TBL machine starts its game from ~/.xinitrc, so by the
 * time the boot menu runs an X server owns the screen and nothing drawn on
 * the console framebuffer shows.  The menu is ONE STATIC program (the
 * machine's Arch root is whatever its last system image carried) and cannot
 * load the machine's libX11.  The handful of requests a picture needs are
 * simple enough to send by hand: connect, CreateWindow (override-redirect,
 * the size of the root, so no window manager is needed - the machine has
 * none), MapWindow, CreateGC, and PutImage of the rows that changed.
 *
 * fb_linux.c draws the canvas into a memory "glass" the root's size in the
 * server's 32-bit TrueColor layout and hands the changed rows here; the
 * placement, scaling and colour code is the framebuffer build's, unchanged.
 *
 * WHERE THE SERVER IS: $DISPLAY (":N" or "unix:N"; a host name is refused),
 * the abstract socket "@/tmp/.X11-unix/XN" first and then the file - a rig's
 * Xvfb in PAD-Runtime has only the abstract one.  The cookie: the
 * MIT-MAGIC-COOKIE-1 entry for display N in $XAUTHORITY or ~/.Xauthority
 * (startx writes one); none = connect without one.
 *
 * NEVER BLOCKED BY THE SERVER.  Errors and events the server sends are read
 * (non-blocking) after every frame and logged, so its output buffer for us
 * never fills; nothing here waits for a reply after the connection setup.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include "x11_raw.h"
#include "log.h"

static struct {
    int fd;
    uint32_t root, win, gc, cursor, black;
    int w, h, depth;
    uint32_t maxreq;          /* bytes */
    long long errors;
} X = { .fd = -1 };

static int put_all(const void *buf, size_t n)
{
    const unsigned char *p = buf;
    while (n) {
        ssize_t k = write(X.fd, p, n);
        if (k < 0 && errno == EINTR) continue;
        if (k < 0 && errno == EAGAIN) {
            struct pollfd pf = { X.fd, POLLOUT, 0 };
            poll(&pf, 1, 1000);
            continue;
        }
        if (k <= 0) return -1;
        p += k;
        n -= (size_t)k;
    }
    return 0;
}

static int get_all(void *buf, size_t n, int timeout_ms)
{
    unsigned char *p = buf;
    while (n) {
        struct pollfd pf = { X.fd, POLLIN, 0 };
        ssize_t k;
        if (poll(&pf, 1, timeout_ms) <= 0) return -1;
        k = read(X.fd, p, n);
        if (k < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (k <= 0) return -1;
        p += k;
        n -= (size_t)k;
    }
    return 0;
}

static void put16(unsigned char *b, unsigned v) { b[0] = v; b[1] = v >> 8; }
static void put32(unsigned char *b, uint32_t v) { b[0] = v; b[1] = v >> 8; b[2] = v >> 16; b[3] = v >> 24; }
static unsigned get16(const unsigned char *b) { return b[0] | b[1] << 8; }
static uint32_t get32(const unsigned char *b) { return b[0] | b[1] << 8 | b[2] << 16 | (uint32_t)b[3] << 24; }
static unsigned be16(const unsigned char *b) { return b[0] << 8 | b[1]; }
static size_t pad4(size_t n) { return (4 - (n & 3)) & 3; }

/* ":0", ":0.0", "unix:0" -> 0; -1 for anything else (a TCP display) */
static int display_number(const char *d)
{
    int n = 0, any = 0;
    if (!d) return -1;
    if (!strncmp(d, "unix:", 5)) d += 4;
    if (*d != ':') return -1;
    for (d++; *d >= '0' && *d <= '9'; d++, any = 1) n = n * 10 + (*d - '0');
    return any && (!*d || *d == '.') ? n : -1;
}

static int connect_unix(int num)
{
    struct sockaddr_un a;
    int abstract;
    for (abstract = 1; abstract >= 0; abstract--) {
        int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
        socklen_t len;
        if (fd < 0) return -1;
        memset(&a, 0, sizeof a);
        a.sun_family = AF_UNIX;
        snprintf(a.sun_path + abstract, sizeof a.sun_path - 1, "/tmp/.X11-unix/X%d", num);
        len = (socklen_t)(offsetof(struct sockaddr_un, sun_path) + abstract + strlen(a.sun_path + abstract));
        if (connect(fd, (struct sockaddr *)&a, len) == 0) {
            sel_log("x11: connected to %s/tmp/.X11-unix/X%d", abstract ? "@" : "", num);
            return fd;
        }
        close(fd);
    }
    return -1;
}

/* the MIT-MAGIC-COOKIE-1 for display num, from the Xauthority file */
static int find_cookie(int num, unsigned char *cookie, int cap)
{
    char path[512];
    const char *f = getenv("XAUTHORITY");
    unsigned char *buf = NULL;
    long len = 0;
    int found = -1;
    FILE *fp;
    if (!f || !*f) {
        const char *home = getenv("HOME");
        if (!home) return -1;
        snprintf(path, sizeof path, "%s/.Xauthority", home);
        f = path;
    }
    if (!(fp = fopen(f, "rb"))) return -1;
    if (fseek(fp, 0, SEEK_END) == 0 && (len = ftell(fp)) > 0 && len < (1 << 20)
        && fseek(fp, 0, SEEK_SET) == 0 && (buf = malloc((size_t)len))
        && fread(buf, 1, (size_t)len, fp) == (size_t)len) {
        long p = 0;
        while (p + 2 <= len && found < 0) {
            const unsigned char *field[4];
            unsigned flen[4];
            int i, ok = 1;
            p += 2;                              /* family */
            for (i = 0; i < 4 && ok; i++) {
                if (p + 2 > len) { ok = 0; break; }
                flen[i] = be16(buf + p);
                p += 2;
                if (p + flen[i] > len) { ok = 0; break; }
                field[i] = buf + p;
                p += flen[i];
            }
            if (!ok) break;
            /* field: 0 address, 1 display number, 2 name, 3 data */
            if (flen[2] == 18 && !memcmp(field[2], "MIT-MAGIC-COOKIE-1", 18)
                && (int)flen[3] <= cap) {
                char nb[16];
                int k = flen[1] < sizeof nb - 1 ? (int)flen[1] : (int)sizeof nb - 1;
                memcpy(nb, field[1], (size_t)k);
                nb[k] = 0;
                if (!*nb || atoi(nb) == num) {
                    memcpy(cookie, field[3], flen[3]);
                    found = (int)flen[3];
                }
            }
        }
    }
    free(buf);
    fclose(fp);
    return found;
}

static int setup(int num)
{
    unsigned char req[12 + 20 + 16], head[8], *body;
    unsigned char cookie[64];
    int clen = find_cookie(num, cookie, sizeof cookie);
    size_t n = 12, blen;
    uint32_t id_base, id_mask;
    unsigned vlen, nfmt, i;
    const unsigned char *p, *scr;

    memset(req, 0, sizeof req);
    req[0] = 'l';                                /* little-endian */
    put16(req + 2, 11);                          /* protocol 11.0 */
    if (clen > 0) {
        put16(req + 6, 18);
        put16(req + 8, (unsigned)clen);
        memcpy(req + 12, "MIT-MAGIC-COOKIE-1", 18);
        n = 12 + 20;
        memcpy(req + n, cookie, (size_t)clen);
        n += (size_t)clen + pad4((size_t)clen);
    }
    sel_log("x11: %s", clen > 0 ? "authorising with the MIT-MAGIC-COOKIE-1 from the Xauthority file"
                                : "no cookie for this display: connecting without one");
    if (put_all(req, n) < 0 || get_all(head, 8, 5000) < 0) {
        sel_log("x11: the server did not answer the connection setup");
        return -1;
    }
    blen = (size_t)get16(head + 6) * 4;
    if (!(body = malloc(blen + 1))) return -1;
    if (get_all(body, blen, 5000) < 0) { free(body); return -1; }
    if (head[0] != 1) {
        body[blen] = 0;
        sel_log("x11: connection refused: %.*s", head[1] ? head[1] : (int)blen, (char *)body);
        free(body);
        return -1;
    }
    id_base = get32(body + 4);
    id_mask = get32(body + 8);
    vlen = get16(body + 16);
    X.maxreq = (uint32_t)get16(body + 18) * 4;
    nfmt = body[21];
    p = body + 32 + vlen + pad4(vlen);
    X.depth = 0;
    for (i = 0; i < nfmt; i++, p += 8)
        if (p[0] == 24 && p[1] != 32) {
            sel_log("x11: depth 24 is stored %d bits to a pixel, not 32: not drawn here", p[1]);
            free(body);
            return -1;
        }
    scr = p;                                    /* the first screen */
    X.root = get32(scr);
    X.black = get32(scr + 12);
    X.w = get16(scr + 20);
    X.h = get16(scr + 22);
    X.depth = scr[38];
    {
        /* the root visual's colour masks: this draws 0x00RRGGBB */
        uint32_t vis = get32(scr + 32);
        unsigned nd = scr[39], d, v;
        const unsigned char *q = scr + 40;
        uint32_t rm = 0, gm = 0, bm = 0;
        for (d = 0; d < nd; d++) {
            unsigned nv = get16(q + 2);
            q += 8;
            for (v = 0; v < nv; v++, q += 24)
                if (get32(q) == vis) { rm = get32(q + 8); gm = get32(q + 12); bm = get32(q + 16); }
        }
        if (X.depth != 24 || rm != 0xff0000u || gm != 0xff00u || bm != 0xffu) {
            sel_log("x11: the root is depth %d, masks %06x/%06x/%06x - only 24-bit 0xRRGGBB is drawn here",
                    X.depth, rm, gm, bm);
            free(body);
            return -1;
        }
    }
    /* ids: the window, its GC, the cursor, and (create_window) a pixmap and a
     * GC that live only while the cursor is made */
    if ((id_mask & 7) != 7) {
        sel_log("x11: resource id mask 0x%x leaves no room for five ids", id_mask);
        free(body);
        return -1;
    }
    X.win = id_base | 1;
    X.gc = id_base | 2;
    X.cursor = id_base | 5;
    sel_log("x11: screen %dx%d, depth %d, requests up to %u bytes", X.w, X.h, X.depth, X.maxreq);
    free(body);
    return 0;
}

static int create_window(void)
{
    static const char title[] = "PAD boot menu";
    unsigned char r[48];
    size_t tl = sizeof title - 1;
    /* AN INVISIBLE POINTER: the server draws its cursor in the middle of the
     * screen, over the menu.  A cursor made of a cleared 1x1 bitmap that
     * masks itself out: CreatePixmap (depth 1), a GC to clear it,
     * PolyFillRectangle, CreateCursor, and the pixmap and GC freed again */
    {
        unsigned char c[96];
        uint32_t pix = X.win + 2, pgc = X.win + 3;   /* ids base|3, base|4 */
        memset(c, 0, sizeof c);
        c[0] = 53; c[1] = 1; put16(c + 2, 4); put32(c + 4, pix); put32(c + 8, X.root);
        put16(c + 12, 1); put16(c + 14, 1);
        c[16] = 55; put16(c + 18, 5); put32(c + 20, pgc); put32(c + 24, pix);
        put32(c + 28, 0x4); put32(c + 32, 0);          /* foreground 0 */
        c[36] = 70; put16(c + 38, 5); put32(c + 40, pix); put32(c + 44, pgc);
        put16(c + 52, 1); put16(c + 54, 1);            /* rectangle 0,0 1x1 */
        c[56] = 93; put16(c + 58, 8); put32(c + 60, X.cursor); put32(c + 64, pix); put32(c + 68, pix);
        c[88] = 54; put16(c + 90, 2); put32(c + 92, pix);
        if (put_all(c, 96) < 0) return -1;
        memset(c, 0, 8);
        c[0] = 60; put16(c + 2, 2); put32(c + 4, pgc);
        if (put_all(c, 8) < 0) return -1;
    }
    /* CreateWindow: background-pixel (0x2) black, override-redirect (0x200),
     * cursor (0x4000) the invisible one */
    memset(r, 0, sizeof r);
    r[0] = 1; r[1] = 0;                          /* depth CopyFromParent */
    put16(r + 2, 11);
    put32(r + 4, X.win);
    put32(r + 8, X.root);
    put16(r + 16, (unsigned)X.w);
    put16(r + 18, (unsigned)X.h);
    put16(r + 22, 1);                            /* InputOutput */
    put32(r + 28, 0x2 | 0x200 | 0x4000);
    put32(r + 32, X.black);
    put32(r + 36, 1);
    put32(r + 40, X.cursor);
    if (put_all(r, 44) < 0) return -1;
    /* ChangeProperty WM_NAME (atom 39) STRING (31): rig shots name windows by it */
    {
        unsigned char c[24 + 16];
        size_t n = 24 + tl + pad4(tl);
        memset(c, 0, sizeof c);
        c[0] = 18;
        put16(c + 2, (unsigned)(n / 4));
        put32(c + 4, X.win);
        put32(c + 8, 39);
        put32(c + 12, 31);
        c[16] = 8;
        put32(c + 20, (uint32_t)tl);
        memcpy(c + 24, title, tl);
        if (put_all(c, n) < 0) return -1;
    }
    /* MapWindow, CreateGC */
    memset(r, 0, sizeof r);
    r[0] = 8; put16(r + 2, 2); put32(r + 4, X.win);
    r[8] = 55; put16(r + 10, 4); put32(r + 12, X.gc); put32(r + 16, X.win); put32(r + 20, 0);
    return put_all(r, 24);
}

/* read whatever the server sent: an error is logged (the first few) */
static void drain(void)
{
    unsigned char ev[32];
    for (;;) {
        struct pollfd pf = { X.fd, POLLIN, 0 };
        if (poll(&pf, 1, 0) <= 0) return;
        if (get_all(ev, 32, 100) < 0) return;
        if (ev[0] == 0) {
            if (X.errors++ < 5)
                sel_log("x11: error %d on request %d (value 0x%x)", ev[1], ev[10], get32(ev + 4));
        } else if (ev[0] == 1) {
            size_t extra = (size_t)get32(ev + 4) * 4;   /* a reply: skip its body */
            while (extra) {
                unsigned char sink[256];
                size_t k = extra < sizeof sink ? extra : sizeof sink;
                if (get_all(sink, k, 100) < 0) return;
                extra -= k;
            }
        }
    }
}

int x11raw_open(int *w, int *h)
{
    const char *d = getenv("DISPLAY");
    int num = display_number(d);
    if (num < 0) {
        sel_log("x11: DISPLAY=%s is not a local display (:N)", d ? d : "(unset)");
        return -1;
    }
    if ((X.fd = connect_unix(num)) < 0) {
        sel_log("x11: cannot connect to display :%d: %s", num, strerror(errno));
        return -1;
    }
    if (setup(num) < 0 || create_window() < 0) {
        x11raw_close();
        return -1;
    }
    fcntl(X.fd, F_SETFL, fcntl(X.fd, F_GETFL) | O_NONBLOCK);
    *w = X.w;
    *h = X.h;
    return 0;
}

int x11raw_put(const unsigned char *px, int stride, int y0, int rows)
{
    size_t row = (size_t)X.w * 4;
    int per = (int)((X.maxreq - 24) / row), done = 0;
    if (X.fd < 0) return -1;
    if (per < 1) per = 1;
    while (done < rows) {
        unsigned char r[24];
        int n = rows - done < per ? rows - done : per;
        size_t bytes = row * (size_t)n;
        int y;
        r[0] = 72; r[1] = 2;                     /* PutImage, ZPixmap */
        put16(r + 2, (unsigned)((24 + bytes) / 4));
        put32(r + 4, X.win);
        put32(r + 8, X.gc);
        put16(r + 12, (unsigned)X.w);
        put16(r + 14, (unsigned)n);
        put16(r + 16, 0);
        put16(r + 18, (unsigned)(y0 + done));
        r[20] = 0; r[21] = 24; r[22] = r[23] = 0;
        if (put_all(r, 24) < 0) return -1;
        for (y = 0; y < n; y++)
            if (put_all(px + (size_t)(y0 + done + y) * stride, row) < 0) return -1;
        done += n;
    }
    drain();
    return 0;
}

void x11raw_close(void)
{
    if (X.fd >= 0) {
        drain();
        if (X.errors) sel_log("x11: %lld errors from the server", X.errors);
        close(X.fd);       /* the window goes with the connection */
    }
    X.fd = -1;
}
