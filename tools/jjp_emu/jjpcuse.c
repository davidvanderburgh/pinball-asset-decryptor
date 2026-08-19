/* jjpcuse.c - serve JJP's playfield I/O boards as REAL character devices.
 *
 * WHY NOT LD_PRELOAD
 * ------------------
 * The obvious approach is an LD_PRELOAD shim over open/read/write (that is
 * jjphwshim.c, and it works perfectly against an ordinary program).  Against
 * the real game it is inert, and the evidence is unambiguous:
 *
 *   - the .so IS mapped into the game (5 mappings) and LD_PRELOAD is set in
 *     its environ, so the loader did its part;
 *   - yet across a 40 s run the shim logged ZERO open() calls and ZERO
 *     fopen() calls, while the game opened thousands of asset files.
 *
 * The Sentinel envelope imports dl_iterate_phdr, dladdr, dlsym and dlvsym, and
 * resolves libc for itself rather than going through the PLT/GOT the loader
 * would have pointed at our shim.  That is deliberate anti-hooking, and no
 * LD_PRELOAD can defeat it.
 *
 * CUSE sidesteps the argument entirely: we register a REAL character device
 * with the kernel, so however the game chooses to call open() - PLT, its own
 * resolved pointer, or a raw syscall - it reaches the kernel, and the kernel
 * asks us.  WSL2 ships /dev/cuse, which is what makes this possible here.
 *
 * THE PROTOCOL
 * ------------
 * Fixed 64-byte frames both directions on every board.  read() must be
 * non-blocking and return the last cached IN frame - that is what JJP's own
 * driver does (spinlock, copy 64 bytes, return), so we owe the game nothing
 * more.  The switch matrix lives at bytes 4..19, LSB first; see swdump.py for
 * how that was derived and verified.
 *
 * State is the shared block in jjpshm.h, so the same UI drives either backend.
 *
 * One device per process: CUSE registers a single device per session, so
 * jjpcuse.sh starts one of these per board.
 *
 * Build: see build.sh.   Run: jjpcuse --name=jjpio100 --board=0
 */

#define FUSE_USE_VERSION 31

#include <cuse_lowlevel.h>
#include <fuse_opt.h>

#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include "jjpshm.h"

static struct jjp_shm *g_shm;
static int g_board;
static const char *g_devname = "jjpio100";

struct jjp_param {
    char *name;
    int board;
    int show_help;
};

#define JJP_OPT(t, p) { t, offsetof(struct jjp_param, p), 1 }

static const struct fuse_opt jjp_opts[] = {
    JJP_OPT("--name=%s", name),
    JJP_OPT("-n %s", name),
    JJP_OPT("--board=%d", board),
    JJP_OPT("-b %d", board),
    FUSE_OPT_KEY("-h", 0),
    FUSE_OPT_KEY("--help", 0),
    FUSE_OPT_END
};

static void shm_attach(void)
{
    const char *name = getenv("JJP_SHM_NAME");
    if (!name)
        name = JJP_SHM_DEFAULT_NAME;

    int fd = shm_open(name, O_RDWR | O_CREAT, 0666);
    if (fd < 0) {
        fprintf(stderr, "jjpcuse: shm_open(%s): %s\n", name, strerror(errno));
        exit(1);
    }
    if (ftruncate(fd, sizeof(struct jjp_shm)) < 0)
        perror("jjpcuse: ftruncate");
    g_shm = mmap(NULL, sizeof(struct jjp_shm), PROT_READ | PROT_WRITE,
                 MAP_SHARED, fd, 0);
    close(fd);
    if (g_shm == MAP_FAILED) {
        perror("jjpcuse: mmap");
        exit(1);
    }
    if (g_shm->magic != JJP_SHM_MAGIC) {
        memset(g_shm, 0, sizeof(*g_shm));
        g_shm->magic = JJP_SHM_MAGIC;
        g_shm->version = JJP_SHM_VERSION;
    }
    /* Make it writable by the desktop user: the daemon runs as root but the
     * matrix UI runs as the user, because it needs their WSLg session. */
    char path[256];
    snprintf(path, sizeof(path), "/dev/shm%s", name);
    chmod(path, 0666);
}

static void jjp_open(fuse_req_t req, struct fuse_file_info *fi)
{
    /* Direct I/O: no page cache between the game and us, so every read is a
     * fresh frame rather than a stale copy. */
    fi->direct_io = 1;
    fi->nonseekable = 1;
    fuse_reply_open(req, fi);
}

static void jjp_read(fuse_req_t req, size_t size, off_t off,
                     struct fuse_file_info *fi)
{
    (void)off; (void)fi;
    unsigned char frame[JJP_FRAME_LEN];
    memset(frame, 0, sizeof(frame));

    if (g_board == JJP_BOARD_IO)
        memcpy(frame + JJP_MATRIX_FIRST_BYTE, (const void *)g_shm->switches,
               JJP_MATRIX_BYTES);
    else if (g_board == JJP_BOARD_CAB)
        memcpy(frame + JJP_MATRIX_FIRST_BYTE, (const void *)g_shm->cabinet,
               sizeof(g_shm->cabinet));

    g_shm->read_count++;

    /* The real driver refuses a short read outright rather than returning a
     * partial frame; match it, so a caller that gets this wrong fails the same
     * way it would on a cabinet. */
    if (size < JJP_FRAME_LEN) {
        fuse_reply_err(req, EINVAL);
        return;
    }
    fuse_reply_buf(req, (const char *)frame, JJP_FRAME_LEN);
}

static void jjp_write(fuse_req_t req, const char *buf, size_t size, off_t off,
                      struct fuse_file_info *fi)
{
    (void)off; (void)fi;
    size_t n = size > JJP_FRAME_LEN ? JJP_FRAME_LEN : size;

    if (g_board >= 0 && g_board < JJP_BOARD_COUNT) {
        volatile unsigned char *dst = g_shm->out[g_board];
        /* Coils are PULSES.  A UI that samples a level misses a 30 ms
         * slingshot about half the time, so publish a change counter and let
         * the UI read edges. */
        for (size_t i = 0; i < n; i++) {
            if (dst[i] != (unsigned char)buf[i])
                g_shm->out_changes[g_board]++;
            dst[i] = (unsigned char)buf[i];
        }
        g_shm->write_count++;
    }
    fuse_reply_write(req, size);            /* the driver clamps, never fails */
}

static void jjp_ioctl(fuse_req_t req, int cmd, void *arg,
                      struct fuse_file_info *fi, unsigned flags,
                      const void *in_buf, size_t in_bufsz, size_t out_bufsz)
{
    (void)cmd; (void)arg; (void)fi; (void)flags;
    (void)in_buf; (void)in_bufsz; (void)out_bufsz;
    /* The lilypad / stepper / topper2 drivers take ioctls we do not model.
     * Succeed silently: board init failure is non-fatal to the game anyway,
     * and an error here would only add noise. */
    fuse_reply_ioctl(req, 0, NULL, 0);
}

static const struct cuse_lowlevel_ops jjp_clop = {
    .open = jjp_open,
    .read = jjp_read,
    .write = jjp_write,
    .ioctl = jjp_ioctl,
};

static int jjp_process_arg(void *data, const char *arg, int key,
                           struct fuse_args *outargs)
{
    (void)data; (void)arg; (void)outargs;
    if (key == 0) {
        ((struct jjp_param *)data)->show_help = 1;
        return 0;
    }
    return 1;
}

int main(int argc, char **argv)
{
    struct fuse_args args = FUSE_ARGS_INIT(argc, argv);
    struct jjp_param param = { NULL, 0, 0 };

    if (fuse_opt_parse(&args, &param, jjp_opts, jjp_process_arg) < 0)
        return 1;
    if (param.show_help) {
        printf("usage: %s --name=<devname> --board=<n> [fuse opts]\n"
               "  e.g. %s --name=jjpio100 --board=0 -f\n"
               "  boards: 0=io 1=led 2=acc 3=cab 4=top 5=top2 6=lily 7=step\n",
               argv[0], argv[0]);
        return 0;
    }
    if (param.name)
        g_devname = param.name;
    g_board = param.board;
    if (g_board < 0 || g_board >= JJP_BOARD_COUNT) {
        fprintf(stderr, "jjpcuse: board %d out of range 0..%d\n",
                g_board, JJP_BOARD_COUNT - 1);
        return 1;
    }

    shm_attach();

    char devarg[128];
    snprintf(devarg, sizeof(devarg), "DEVNAME=%s", g_devname);
    const char *devinfo[] = { devarg };
    struct cuse_info ci;
    memset(&ci, 0, sizeof(ci));
    ci.dev_info_argc = 1;
    ci.dev_info_argv = devinfo;
    ci.flags = CUSE_UNRESTRICTED_IOCTL;

    fprintf(stderr, "jjpcuse: serving /dev/%s as board %d\n", g_devname, g_board);
    return cuse_lowlevel_main(args.argc, args.argv, &ci, &jjp_clop, NULL);
}
