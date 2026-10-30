/* stubs_dp.c - what the Dutch Pinball (The Big Lebowski) build leaves out
 * of the selector (PAD-853), the same set stubs_bof.c leaves out of the
 * Barrels of Fun build (its header below says why each).  A TBL machine is
 * an x86 Arch Linux PC with a P3-ROC; its buttons come through dpprocsw
 * (--input pipe) and its screen is the X server (fb_linux.c -DFB_X11).
 *
 * stubs_bof.c, PAD-342:
 *
 * The menu code calls the Spike 2 machine's hardware by name: the SGTL5000
 * codecs (codec.c), the node bus / cabinet SPI / bridge MCU behind
 * `--input hw` (input_hw.c), and a sound sink (audio_alsa.c).  A BOF machine
 * is an x86 Arch Linux PC with a FAST Neuron on USB serial; the BOF build is
 * ONE STATIC BINARY so it runs on whatever glibc that PC carries, and a static
 * binary cannot load the machine's libasound.  So there is no ALSA sink: the
 * menu's sound goes through audio_fifo.c into a pipe the boot hook plays with
 * the machine's own aplay (padselect_bof.sh).  `make PLATFORM=bof` links these
 * no-ops in place of codec.c, input_hw.c and audio_alsa.c, and the shared
 * sources stay one copy - no #ifdef in the menu (the JJP build's stubs_jjp.c
 * is the same idea).
 *
 * Every stub answers the way the real code answers on a box without the
 * hardware: NULL / -1 / nothing, with one log line where the menu would
 * otherwise wonder why something did nothing.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stddef.h>
#include "audio.h"
#include "input.h"
#include "codec.h"
#include "log.h"

void codec_configure(const char *mode) { (void)mode; }
void codec_snapshot(const char *when) { (void)when; }
void codec_after_reset(void) { }
int  codec_power_up(void) { return 0; }
void codec_restore(void) { }

struct input *input_hw_open(const struct input_cfg *cfg)
{
    (void)cfg;
    sel_log("input: --input hw is the Spike 2 node bus; this is the Dutch Pinball build (use --input pipe)");
    return NULL;
}

int input_hw_bridge(struct input *in, unsigned char cmd, unsigned char arg)
{
    (void)in; (void)cmd; (void)arg;
    return -1;
}

void input_hw_amp_mute(struct input *in, int mute) { (void)in; (void)mute; }

struct audio_sink *audio_alsa_open(char *err, int errlen)
{
    snprintf(err, (size_t)errlen, "no ALSA sink on Dutch Pinball (a static build cannot load libasound): "
             "the hook plays --audio fifo: through aplay");
    return NULL;
}

int audio_alsa_mixer(int v63)
{
    (void)v63;
    return -1;
}
