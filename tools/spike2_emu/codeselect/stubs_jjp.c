/* stubs_jjp.c - what the JJP build leaves out of the Stern selector.
 *
 * The menu code (codeselect.c, audio_alsa.c) calls the Spike 2 machine's
 * hardware by name: the SGTL5000 codecs over /dev/i2c-1 (codec.c), and the
 * node bus / cabinet SPI / bridge MCU behind `--input hw` (input_hw.c).  A
 * JJP machine is an x86 PC with a USB I/O board and PulseAudio; none of
 * that exists there, and a PC does have an /dev/i2c-1 of its own (SMBus),
 * which the codec code must never be let near.  So make PLATFORM=jjp links
 * these no-ops in place of codec.c and input_hw.c, and the shared sources
 * stay one copy - no #ifdef in the menu.
 *
 * Every stub answers the way the real code answers on a box without the
 * hardware: NULL / -1 / nothing, with one log line where the menu would
 * otherwise wonder why a --input hw did nothing.
 */
#define _GNU_SOURCE
#include <stddef.h>
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
    sel_log("input: --input hw is the Spike 2 node bus; this is the JJP build (use --input jjpio)");
    return NULL;
}

int input_hw_bridge(struct input *in, unsigned char cmd, unsigned char arg)
{
    (void)in; (void)cmd; (void)arg;
    return -1;
}

void input_hw_amp_mute(struct input *in, int mute) { (void)in; (void)mute; }
