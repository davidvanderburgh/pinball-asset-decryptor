/* stubs_s3.c - the Stern Spike 3 build of the selector (PAD-1263): its
 * buttons, and what it leaves out.
 *
 * BUTTONS: `--input hw` on Spike 3 is the CPU board's cabinet-input chain,
 * /dev/spidev4.0: SPI mode 3, 100 kHz, 8 bytes out / 8 bytes in, ACTIVE LOW
 * (0xff = nothing pressed). The game polls it ~3000 times a second and its
 * first transfers send eight zero bytes, which is what the menu sends. Byte 0
 * carries the coin door's service buttons, measured in Guided Setup
 * (docs/plans/spike3_emulation.md, stage 4c):
 *
 *   bit 0 SELECT     -> EV_SELECT  (boots the highlighted image)
 *   bit 1 NEXT       -> EV_PLUS    (moves the highlight on)
 *   bit 2 PREVIOUS   -> EV_MINUS   (moves it back)
 *   bit 3 BACK       -> EV_BACK
 *
 * The flippers and START sit on the node bus behind the bridge board, which
 * the game brings up itself; the menu does not, so it promises only the
 * coin-door buttons (input_has) and the countdown boots the highlighted image
 * when nobody presses anything. PADSELECT_SPI overrides the device.
 *
 * LEFT OUT: the Spike 2 codecs (codec.c), the Spike 2 node bus and bridge MCU
 * (input_hw.c) and an ALSA sink. A Spike 3 cabinet's amplifier is a TAS57xx
 * that only the game's own I2C sequence starts, so the menu is silent on the
 * machine: its sound sink is none.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include "audio.h"
#include "input.h"
#include "codec.h"
#include "log.h"

/* linux/spi/spidev.h, by hand */
struct spi_xfer {
    uint64_t tx_buf, rx_buf;
    uint32_t len, speed_hz;
    uint16_t delay_usecs;
    uint8_t bits_per_word, cs_change, tx_nbits, rx_nbits, word_delay_usecs, pad;
};
#define SPI_IOC_MAGIC 'k'
#define SPI_IOC_MESSAGE_1    _IOW(SPI_IOC_MAGIC, 0, char[sizeof(struct spi_xfer)])
#define SPI_IOC_WR_MODE      _IOW(SPI_IOC_MAGIC, 1, uint8_t)
#define SPI_IOC_WR_MAX_SPEED _IOW(SPI_IOC_MAGIC, 4, uint32_t)

#define S3_SPI_DEFAULT "/dev/spidev4.0"

struct s3spi {
    struct input base;
    int fd;
    long long xfers, fails, changes;
    unsigned char last0;
};

static const struct { int bit, ev; } S3_KEYS[] = {
    { 0, EV_SELECT }, { 1, EV_PLUS }, { 2, EV_MINUS }, { 3, EV_BACK },
};
#define NKEYS ((int)(sizeof S3_KEYS / sizeof *S3_KEYS))

static void s3spi_poll(struct input *in, long long now_ms)
{
    struct s3spi *s = (struct s3spi *)in;
    unsigned char tx[8] = { 0 }, rx[8];
    struct spi_xfer x;
    int k;
    (void)now_ms;
    if (s->fd < 0) return;
    memset(rx, 0xff, sizeof rx);
    memset(&x, 0, sizeof x);
    x.tx_buf = (uint64_t)(uintptr_t)tx;
    x.rx_buf = (uint64_t)(uintptr_t)rx;
    x.len = sizeof tx;
    if (ioctl(s->fd, SPI_IOC_MESSAGE_1, &x) < 0) {
        if (s->fails++ < 3) sel_log("input: spi transfer failed (%s)", strerror(errno));
        return;
    }
    s->xfers++;
    if (rx[0] != s->last0) { s->changes++; s->last0 = rx[0]; }
    for (k = 0; k < NKEYS; k++)
        input_sample(&s->base, KEY_OF(S3_KEYS[k].ev), !(rx[0] & (1u << S3_KEYS[k].bit)));
}

static void s3spi_close(struct input *in)
{
    struct s3spi *s = (struct s3spi *)in;
    sel_log("input: spi %lld transfers, %lld failed, %lld changes of the service byte",
            s->xfers, s->fails, s->changes);
    if (s->fd >= 0) close(s->fd);
    pthread_mutex_destroy(&s->base.lock);
    free(s);
}

static const struct input_ops s3spi_ops = { s3spi_poll, s3spi_close };

struct input *input_hw_open(const struct input_cfg *cfg)
{
    struct s3spi *s = calloc(1, sizeof *s);
    const char *dev = getenv("PADSELECT_SPI");
    uint8_t mode = 3;
    uint32_t hz = 100000;
    int k;
    if (!s) return NULL;
    /* the Spike 2 default (/dev/spidev1.0) means "the machine's": Spike 3's is spidev4.0 */
    if (!dev || !*dev)
        dev = (cfg && cfg->spi && *cfg->spi && strcmp(cfg->spi, "/dev/spidev1.0")) ? cfg->spi : S3_SPI_DEFAULT;
    input_base_init(&s->base, &s3spi_ops);
    for (k = 0; k < KEY_COUNT; k++) s->base.present[k] = 0;
    for (k = 0; k < NKEYS; k++) s->base.present[KEY_OF(S3_KEYS[k].ev)] = 1;
    s->last0 = 0xff;
    s->fd = strcmp(dev, "none") ? open(dev, O_RDWR | O_CLOEXEC) : -1;
    if (s->fd < 0) {
        sel_log("input: cannot open %s (%s): no buttons, the countdown boots the highlight",
                dev, strerror(errno));
    } else {
        if (ioctl(s->fd, SPI_IOC_WR_MAX_SPEED, &hz) < 0 || ioctl(s->fd, SPI_IOC_WR_MODE, &mode) < 0)
            sel_log("input: %s: setting mode 3 / 100 kHz failed (%s), reading anyway", dev, strerror(errno));
        sel_log("input: Spike 3 coin door on %s (SELECT boots, NEXT / PREVIOUS move)", dev);
    }
    return &s->base;
}

int input_hw_bridge(struct input *in, unsigned char cmd, unsigned char arg)
{
    (void)in; (void)cmd; (void)arg;
    return -1;
}

void input_hw_amp_mute(struct input *in, int mute) { (void)in; (void)mute; }

void codec_configure(const char *mode) { (void)mode; }
void codec_snapshot(const char *when) { (void)when; }
void codec_after_reset(void) { }
int  codec_power_up(void) { return 0; }
void codec_restore(void) { }

struct audio_sink *audio_alsa_open(char *err, int errlen)
{
    snprintf(err, (size_t)errlen, "no sound on Spike 3: the cabinet amplifier is started by the game");
    return NULL;
}

int audio_alsa_mixer(int v63)
{
    (void)v63;
    return -1;
}
