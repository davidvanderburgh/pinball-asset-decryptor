/* s1hwshim — CUSE device model for the Spike 1 emulation rig.
 *
 * The Spike 1 game is a *static* ARM binary, so the Spike 2 LD_PRELOAD shim
 * (hwshim.c) cannot interpose its device access.  Instead we model each board
 * peripheral as a CUSE (character device in userspace) device the game opens
 * through qemu-user: the guest's open/ioctl/read/write reach these handlers.
 *
 * One process models one device (CUSE registers one device per session); the
 * orchestrator runs an instance per device path.  Two models:
 *
 *   i2c     — the board bus.  Handles I2C_SLAVE (0x0703) to select the slave,
 *             and read/write against a per-slave register file.  Slave 0x50 is
 *             the board-identity EEPROM (content is configurable — see the
 *             --eeprom option; without the real dump we serve a benign default
 *             and watch what the firmware does with it).
 *   passive — accept every ioctl (reply 0), discard writes, read as zeros.
 *             Stand-in for the write/stream devices (dmd, i2s, amp, adc, gpio,
 *             spi) so their setup ioctls don't fail the boot.
 *
 * Build:  gcc -O2 -o s1hwshim s1hwshim.c $(pkg-config --cflags --libs fuse3)
 * Run:    s1hwshim --model i2c     --name s1i2c0 [--eeprom FILE]
 *         s1hwshim --model passive --name s1dmd
 * The device appears at /dev/<name>; the launcher bind-mounts it onto the
 * real path (e.g. /dev/i2c-0) inside the game's mount namespace.
 */
#define FUSE_USE_VERSION 31

#include <cuse_lowlevel.h>
#include <fuse_opt.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <unistd.h>

#ifndef I2C_SLAVE
#define I2C_SLAVE       0x0703
#define I2C_SLAVE_FORCE 0x0706
#define I2C_TENBIT      0x0704
#define I2C_FUNCS       0x0705
#endif

/* ---- model state ---------------------------------------------------- */
enum { MODEL_I2C, MODEL_PASSIVE };
static int g_model = MODEL_PASSIVE;

/* --waveform: make read() on this device return a synthetic AC line signal
 * instead of zeros.  /dev/adc feeds LineSenseThread (game ELF @0xc5138), which
 * reads 4096-byte blocks of u16 samples and measures the mains half-cycles by
 * counting threshold (999) crossings; from that ADC_GetLineFrequency reports
 * whether the line is present.  With zeros there are no crossings, so after 24
 * empty reads sys_line_status flags power loss and the game shows "CHECK POWER
 * DISTRIBUTION BOARD".  A square wave that swings above/below the threshold with
 * short low runs (< the 50-sample "no line" timeout) reads as a live mains line
 * and clears the alert.  See docs/architecture/spike1_emulation.md. */
static int g_waveform = 0;
/* The line-sense detector works like real mains sampling: ADC_Init(15360, 250)
 * asks for a 15360 Hz sample rate (read back via ioctl 0x4204), and the game
 * measures the frequency across a full low half-cycle — the "50 consecutive low
 * samples" branch (game ELF LineSenseThread @0xc536c) is that half-cycle marker,
 * not an error.  So the waveform must have a REALISTIC period: at 60 Hz a half-
 * cycle is 15360/120 = 128 samples.  128 high / 128 low => a 256-sample period =>
 * 15360/256 = 60.0 Hz, which sys_factory_config_exec_pdi accepts as a valid line
 * (frequencies that are not ~50/60 Hz raise "CHECK POWER DISTRIBUTION BOARD"). */
#define ADC_SAMPLE_RATE 15360   /* what ioctl 0x4204 reports (ADC_Init's arg) */
#define ADC_RATE_IOCTL  0x4204  /* LineSenseThread reads the rate from this */
#define WAVE_HIGH 3000          /* > threshold 999 (12-bit ADC, midpoint ~2048) */
#define WAVE_LOW  0
#define WAVE_HALF 128           /* samples per half-cycle => 60 Hz at 15360 sps */

/* --dmd-fps N: throttle the DMD frame-commit ioctl to N frames/second.  The
 * game's display thread (game ELF "displayExe") renders each frame as
 *   ioctl(dmd, _IOC(NONE,0x3d,0x1))  // frame begin
 *   write(spi0, 2048-byte framebuffer)
 *   ioctl(dmd, _IOC(NONE,0x3d,0x2))  // frame commit  <- exactly one per frame
 * On real hardware the commit returns only after the panel has latched the frame
 * at its fixed refresh, so that ioctl is what paces the whole loop.  Our passive
 * reply is instant, so displayExe free-runs — attract played dozens of x too fast
 * (measured ~4800 fps).  Sleeping in the commit to hold a real frame period paces
 * the game exactly as the panel would, with no game patch.  Pinball logic runs on
 * the mains tick, so 60 fps matches the 60 Hz line we report (see s1patch.py). */
#define DMD_COMMIT_TYPE 0x3d    /* _IOC type of the DMD frame ioctls */
#define DMD_COMMIT_NR   0x02    /* _IOC nr of the "commit / show frame" ioctl */
static double g_dmd_fps = 0.0;          /* 0 = no pacing (non-DMD devices) */
static struct timespec g_dmd_grid;      /* the ideal time of the next commit */
static int g_dmd_primed = 0;

/* Block until this frame's slot on the fixed refresh grid.  Monotonic so a
 * wall-clock change can't skew it; if the game falls behind (a stall, or it
 * simply runs slower than the target under qemu) we resync to now instead of
 * bursting to catch up. */
static void dmd_pace(void)
{
    long period_ns = (long)(1e9 / g_dmd_fps);
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    if (!g_dmd_primed) { g_dmd_grid = now; g_dmd_primed = 1; }
    g_dmd_grid.tv_nsec += period_ns;
    while (g_dmd_grid.tv_nsec >= 1000000000L) {
        g_dmd_grid.tv_nsec -= 1000000000L; g_dmd_grid.tv_sec += 1;
    }
    long delta_ns = (g_dmd_grid.tv_sec - now.tv_sec) * 1000000000L
                  + (g_dmd_grid.tv_nsec - now.tv_nsec);
    if (delta_ns > 0) {
        struct timespec s = { delta_ns / 1000000000L, delta_ns % 1000000000L };
        nanosleep(&s, NULL);
    } else {
        g_dmd_grid = now;   /* behind schedule: resync, don't catch up in a burst */
    }
}

/* --pcm-rate N --pcm-ch C: pace this device's WRITES at the real-time PCM
 * drain rate (N Hz x C channels x s16), the audio twin of --dmd-fps.  The
 * game's audio thread streams the mixed i2s feed to /dev/i2s and on real
 * hardware each write returns only as the DMA ring drains, so blocking here
 * for the buffer's real duration paces it exactly as the hardware would
 * (unpaced it free-runs at thousands of writes/s pumping silence).  Same
 * grid discipline as dmd_pace: monotonic, resync when behind, weighted by
 * each write's byte count instead of a fixed period. */
static double g_pcm_bps = 0.0;          /* real-time bytes/sec; 0 = no pacing */
static int g_pcm_ch = 2;
static struct timespec g_pcm_grid;
static int g_pcm_primed = 0;

static void pcm_pace(size_t nbytes)
{
    long dur_ns = (long)((double)nbytes * 1e9 / g_pcm_bps);
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    if (!g_pcm_primed) { g_pcm_grid = now; g_pcm_primed = 1; }
    g_pcm_grid.tv_nsec += dur_ns;
    while (g_pcm_grid.tv_nsec >= 1000000000L) {
        g_pcm_grid.tv_nsec -= 1000000000L; g_pcm_grid.tv_sec += 1;
    }
    long delta_ns = (g_pcm_grid.tv_sec - now.tv_sec) * 1000000000L
                  + (g_pcm_grid.tv_nsec - now.tv_nsec);
    if (delta_ns > 0) {
        struct timespec s = { delta_ns / 1000000000L, delta_ns % 1000000000L };
        nanosleep(&s, NULL);
    } else {
        g_pcm_grid = now;   /* behind schedule: resync, don't burst */
    }
}

/* --fifo PATH: tee this device's writes (the PCM stream) into a named FIFO for
 * a host player (the Spike 2 rig's playaudio.sh/padrelay.py/padplay.py chain).
 * The FIFO is the safety boundary, same contract as the Spike 2 alsastub: the
 * writes here are non-blocking and DROPPED when there is no reader or the
 * reader stalls, so nothing on the player side — slow, dead, absent — can
 * stall the emulated game.  Worst case is silence. */
static const char *g_fifo_path = NULL;
static int g_fifo_fd = -1;

static void fifo_tee(const char *buf, size_t size)
{
    if (!g_fifo_path || size == 0)
        return;
    if (g_fifo_fd < 0) {
        g_fifo_fd = open(g_fifo_path, O_WRONLY | O_NONBLOCK);
        if (g_fifo_fd < 0)
            return;                     /* no FIFO / no reader yet: drop */
    }
    ssize_t w = write(g_fifo_fd, buf, size);
    if (w < 0 && errno != EAGAIN) {     /* reader went away: reopen next time */
        close(g_fifo_fd);
        g_fifo_fd = -1;
    }                                   /* EAGAIN = reader stalled: drop */
}

/* i2c: 128 possible slaves, each a 256-byte register file + a read/write
 * offset pointer.  The firmware talks to the board EEPROM at 0x50. */
#define N_SLAVES 128
#define SLAVE_SZ 256
static uint8_t g_eeprom[N_SLAVES][SLAVE_SZ];
/* errno returned for the (unserviced) I2C_RDWR path; EREMOTEIO = "no ack".
 * Overridable via --rdwr-errno to probe how the game reacts. */
static int s1_i2c_rdwr_errno = 121 /* EREMOTEIO */;

/* optional write capture (--capture FILE): the passive stream devices (dmd,
 * spi0 = DMD frames, i2s = audio) discard writes; capturing them lets us see
 * / render / play what the game produces.  Bounded so a fast frame stream
 * doesn't fill the disk. */
static FILE *g_capfile = NULL;
/* 256 MB ~= an hour of 128x32x4bit DMD frames at ~30 fps.  The GUI's live DMD
 * preview reads the tail of this file, so the cap sets how long the preview
 * stays live before it freezes on the last frame (restart to resume). */
static long g_capmax = 256L << 20;
static long g_capped = 0;

/* --gpio-file PATH: the EARLY firmware era (the 2012 home models, PAD-101)
 * reads its cabinet switches straight off CPU-board GPIO pins with
 *     ioctl(gpio, 0x3c02, pin)   -> the pin's level
 * (node_gpio_switch_update), a scalar ioctl the qemu passthrough hands us
 * intact.  The pins idle HIGH (active-low buttons): answering 0 for every
 * pin - the passive default - reads as every button held, and the game sat
 * on its VOLUME screen at boot.  With this option the level comes from a
 * byte-per-pin file the switch window / keeper write (missing file or pin
 * -> 1, released); without it nothing changes for the DMD generation. */
#define GPIO_READ_IOCTL 0x3c02
static const char *g_gpio_file = NULL;

static int gpio_level(int pin)
{
    int lvl = 1;
    FILE *f;
    if (pin < 0 || pin > 255 || !(f = fopen(g_gpio_file, "rb")))
        return lvl;
    if (fseek(f, pin, SEEK_SET) == 0) {
        int c = fgetc(f);
        if (c != EOF) lvl = c ? 1 : 0;
    }
    fclose(f);
    return lvl;
}

struct fh {
    int  slave;     /* current I2C_SLAVE address */
    int  off;       /* register pointer within the slave */
};

static void s1_open(fuse_req_t req, struct fuse_file_info *fi)
{
    struct fh *h = calloc(1, sizeof *h);
    h->slave = 0x50;    /* default so a read before I2C_SLAVE still hits the EEPROM */
    h->off = 0;
    fi->fh = (uintptr_t)h;
    fi->nonseekable = 1;
    fuse_reply_open(req, fi);
}

static void s1_release(fuse_req_t req, struct fuse_file_info *fi)
{
    free((void *)(uintptr_t)fi->fh);
    fuse_reply_err(req, 0);
}

static void s1_read(fuse_req_t req, size_t size, off_t off,
                    struct fuse_file_info *fi)
{
    struct fh *h = (struct fh *)(uintptr_t)fi->fh;
    if (g_model == MODEL_I2C && h && h->slave >= 0 && h->slave < N_SLAVES) {
        uint8_t tmp[SLAVE_SZ];
        size_t n = size > SLAVE_SZ ? SLAVE_SZ : size;
        for (size_t i = 0; i < n; i++)
            tmp[i] = g_eeprom[h->slave][(h->off + i) & (SLAVE_SZ - 1)];
        h->off = (h->off + n) & (SLAVE_SZ - 1);
        fuse_reply_buf(req, (char *)tmp, n);
        return;
    }
    /* passive: read as zeros, at the FULL requested length — a short read
     * makes the game's stream reads (e.g. the 4096-byte ADC read) fail. */
    size_t n = size > (64u << 10) ? (64u << 10) : size;
    char *z = calloc(1, n ? n : 1);
    if (!z) { fuse_reply_err(req, ENOMEM); return; }
    if (g_waveform) {
        /* fill with a u16 square wave: WAVE_HALF samples high, WAVE_HALF low,
         * repeating.  WAVE_HALF divides the sample count so every block holds
         * whole cycles and the phase is continuous across reads.
         *
         * One-time power-up transient: the game's factory line-frequency self-
         * test (sys_factory_config_exec_pdi) only latches a valid reading after
         * the line has been ABSENT for 24 frames — it snapshots the frequency it
         * measured just before the drop (game ELF sys_line_status_exec_pdi
         * @0x6cd3c).  A real machine sees that transient as mains ramps up at
         * power-on.  So: emit 60 Hz for a moment (it measures 60), then a short
         * flat gap (present clears -> the snapshot fires -> the test passes and
         * sets its "done" flag), then a steady 60 Hz line forever after. */
        uint16_t *s = (uint16_t *)z;
        size_t ns = n / 2;
        for (size_t i = 0; i < ns; i++)
            s[i] = ((i / WAVE_HALF) & 1) ? WAVE_LOW : WAVE_HIGH;
    }
    fuse_reply_buf(req, z, n);
    free(z);
}

static void s1_write(fuse_req_t req, const char *buf, size_t size, off_t off,
                     struct fuse_file_info *fi)
{
    struct fh *h = (struct fh *)(uintptr_t)fi->fh;
    if (g_model == MODEL_I2C && h && size > 0 &&
        h->slave >= 0 && h->slave < N_SLAVES) {
        /* i2c EEPROM convention: first written byte sets the register
         * pointer; any following bytes are written sequentially. */
        h->off = (uint8_t)buf[0];
        for (size_t i = 1; i < size; i++) {
            g_eeprom[h->slave][h->off] = (uint8_t)buf[i];
            h->off = (h->off + 1) & (SLAVE_SZ - 1);
        }
    }
    if (g_model == MODEL_PASSIVE && g_capfile && g_capped < g_capmax
        && size > 0) {
        size_t n = fwrite(buf, 1, size, g_capfile);
        g_capped += (long)n;
        fflush(g_capfile);
    }
    if (g_model == MODEL_PASSIVE && size > 0) {
        fifo_tee(buf, size);          /* audio out first, then the pacing sleep */
        if (g_pcm_bps > 0.0)
            pcm_pace(size);
    }
    fuse_reply_write(req, size);      /* passive: accept + discard (+capture) */
}

static void s1_ioctl(fuse_req_t req, int cmd, void *arg,
                     struct fuse_file_info *fi, unsigned flags,
                     const void *in_buf, size_t in_bufsz, size_t out_bufsz)
{
    struct fh *h = (struct fh *)(uintptr_t)fi->fh;
    if (flags & FUSE_IOCTL_COMPAT) { fuse_reply_err(req, ENOSYS); return; }

    if (g_model == MODEL_I2C) {
        switch (cmd) {
        case I2C_SLAVE:
        case I2C_SLAVE_FORCE:
            if (h) { h->slave = (int)(intptr_t)arg; h->off = 0; }
            fuse_reply_ioctl(req, 0, NULL, 0);
            return;
        case I2C_TENBIT:
            fuse_reply_ioctl(req, 0, NULL, 0);
            return;
        case 0x0707: /* I2C_RDWR — combined transaction.  qemu can't translate
                      * its nested i2c_msg array generically, so we can't
                      * service it here; report "no ack" so the game treats the
                      * probed chip as absent rather than trusting stale data.
                      * (A real model needs qemu-side I2C_RDWR translation.) */
            fuse_reply_err(req, s1_i2c_rdwr_errno);
            return;
        case I2C_FUNCS: {
            /* report a plain I2C master (no SMBUS block quirks) */
            if (out_bufsz == 0) {
                struct iovec iov = { arg, sizeof(unsigned long) };
                fuse_reply_ioctl_retry(req, NULL, 0, &iov, 1);
                return;
            }
            unsigned long funcs = 0x00000001UL; /* I2C_FUNC_I2C */
            fuse_reply_ioctl(req, 0, &funcs, sizeof funcs);
            return;
        }
        default:
            fuse_reply_ioctl(req, 0, NULL, 0);   /* accept unknown */
            return;
        }
    }
    /* passive: accept every ioctl so device setup never fails the boot.  For the
     * ADC line-sense device, the rate query (0x4204) must report the real sample
     * rate so the game computes a valid line frequency from the waveform. */
    if (g_waveform && cmd == ADC_RATE_IOCTL) {
        fuse_reply_ioctl(req, ADC_SAMPLE_RATE, NULL, 0);
        return;
    }
    if (g_gpio_file && cmd == GPIO_READ_IOCTL) {
        fuse_reply_ioctl(req, gpio_level((int)(intptr_t)arg), NULL, 0);
        return;
    }
    /* DMD frame pacing (only the s1dmd instance sets --dmd-fps): hold the
     * frame-commit ioctl for a real refresh period so the display thread can't
     * free-run.  See dmd_pace() / --dmd-fps above. */
    if (g_dmd_fps > 0.0 && ((cmd >> 8) & 0xff) == DMD_COMMIT_TYPE
                        && (cmd & 0xff) == DMD_COMMIT_NR)
        dmd_pace();
    fuse_reply_ioctl(req, 0, NULL, 0);
}

static const struct cuse_lowlevel_ops s1_ops = {
    .open    = s1_open,
    .read    = s1_read,
    .write   = s1_write,
    .ioctl   = s1_ioctl,
    .release = s1_release,
};

/* ---- option parsing (our flags, then fuse's) ------------------------ */
int main(int argc, char **argv)
{
    const char *name = NULL, *eeprom = NULL, *model = "passive";
    int fuse_argc = 0;
    char *fuse_argv[8];
    fuse_argv[fuse_argc++] = argv[0];
    fuse_argv[fuse_argc++] = (char *)"-f";     /* foreground */
    fuse_argv[fuse_argc++] = (char *)"-s";     /* single-threaded */

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--name") && i + 1 < argc) name = argv[++i];
        else if (!strcmp(argv[i], "--model") && i + 1 < argc) model = argv[++i];
        else if (!strcmp(argv[i], "--eeprom") && i + 1 < argc) eeprom = argv[++i];
        else if (!strcmp(argv[i], "--capture") && i + 1 < argc)
            g_capfile = fopen(argv[++i], "wb");
        else if (!strcmp(argv[i], "--waveform")) g_waveform = 1;
        else if (!strcmp(argv[i], "--gpio-file") && i + 1 < argc)
            g_gpio_file = argv[++i];
        else if (!strcmp(argv[i], "--dmd-fps") && i + 1 < argc)
            g_dmd_fps = atof(argv[++i]);
        else if (!strcmp(argv[i], "--pcm-rate") && i + 1 < argc)
            g_pcm_bps = atof(argv[++i]);        /* Hz for now; scaled below */
        else if (!strcmp(argv[i], "--pcm-ch") && i + 1 < argc)
            g_pcm_ch = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--fifo") && i + 1 < argc)
            g_fifo_path = argv[++i];
        else if (!strcmp(argv[i], "-d")) fuse_argv[fuse_argc++] = (char *)"-d";
    }
    g_pcm_bps *= (double)g_pcm_ch * 2.0;        /* s16: rate x ch x 2 bytes */
    /* a FIFO reader that dies mid-write raises SIGPIPE; silence is the
     * contract, not shim death */
    signal(SIGPIPE, SIG_IGN);
    if (!name) { fprintf(stderr, "usage: %s --model i2c|passive --name DEV "
                                 "[--eeprom FILE]\n", argv[0]); return 2; }
    g_model = strcmp(model, "i2c") == 0 ? MODEL_I2C : MODEL_PASSIVE;

    /* EEPROM defaults: 0xff (erased) everywhere, then a benign board-id at
     * 0x50 (byte 0 = a nonzero "present" marker).  Overridable via --eeprom
     * (a raw dump loaded at slave 0x50) once the real content is known. */
    memset(g_eeprom, 0xff, sizeof g_eeprom);
    memset(g_eeprom[0x50], 0x00, SLAVE_SZ);
    g_eeprom[0x50][0] = 0x01;
    if (eeprom) {
        FILE *f = fopen(eeprom, "rb");
        if (f) { fread(g_eeprom[0x50], 1, SLAVE_SZ, f); fclose(f); }
        else fprintf(stderr, "s1hwshim: could not read --eeprom %s\n", eeprom);
    }

    char devname[128];
    snprintf(devname, sizeof devname, "DEVNAME=%s", name);
    const char *dev_argv[] = { devname };
    struct cuse_info ci;
    memset(&ci, 0, sizeof ci);
    ci.dev_info_argc = 1;
    ci.dev_info_argv = dev_argv;
    ci.flags = CUSE_UNRESTRICTED_IOCTL;

    fprintf(stderr, "s1hwshim: model=%s /dev/%s\n", model, name);
    return cuse_lowlevel_main(fuse_argc, fuse_argv, &ci, &s1_ops, NULL);
}
