/* codec.h - the machine's two SGTL5000 codecs over /dev/i2c-1, the way the
 * game drives them.
 *
 * WHY THE MENU NEEDS THIS.  The card's kernel knows the codecs only as
 * `audio-routing = "Headphone Jack", "HP_OUT"` (stern-spike2.dtb, both
 * sound-main and sound-center): under ALSA it powers the headphone path
 * for a stream and never the LINE_OUT block - and LINE_OUT is what feeds
 * the amplifiers.  So a stream the kernel plays without a dropped frame
 * (David's Godzilla, 2026-09-04: `audio: alsa default ok`, 509796 frames,
 * silence) never reaches a speaker.  The game does not rely on the kernel
 * for that: its audio bring-up talks to the chips itself, over
 * /dev/i2c-1 with I2C_SLAVE_FORCE + I2C_RDWR (godzilla_pro 0x1fa724 /
 * 0x1fa7b8), and its recovery path (0x1fb38c -> 0x1fa8c0(0)) writes a
 * 50-register table that powers VAG, DAC, headphone AND line-out
 * (CHIP_ANA_POWER 0x40f9), clears every analog mute (CHIP_ANA_CTRL
 * 0x0020 / 0x0022), sets the line-out bias (CHIP_LINE_OUT_CTRL 0x0322)
 * and the reference (CHIP_REF_CTRL 0x01f0).  The same 1000-byte table
 * sits, byte for byte, in godzilla_pro, turtles_pro, stranger_things_le
 * and dungeons_and_dragons: it is the platform's codec recipe.
 *
 * WHAT THIS DOES.  After the ALSA device is open and configured (so the
 * kernel's own hw_params / DAPM writes are behind us and cannot undo it),
 * codec_power_up() applies that table to both chips - all but the
 * registers the kernel owns for the running stream (clock, I2S format,
 * the DAC and headphone volumes the mixer controls set) and the read-only
 * status word; the two power registers are ORed in, so the regulator and
 * charge-pump bits the kernel chose for this board's supplies stay.  Every
 * register it changes is remembered and codec_restore() puts it back at
 * close (power bits only ever taken away, never added), so the game boots
 * from the codec state a stock card gives it; the game resets and
 * reprograms both chips at its own start anyway.
 *
 * GATES.  Nothing is written unless /dev/i2c-1 opens and BOTH chips answer
 * CHIP_ID with the SGTL5000 part id (0xA0xx) - the emulator has no such
 * bus, and a wrong box cannot be mistaken for this one.  `--codec off`
 * leaves the codecs alone.  Every failure is a log line, never fatal: the
 * menu runs silent rather than not at all.
 */
#ifndef CODESELECT_CODEC_H
#define CODESELECT_CODEC_H

/* "auto" (default) | "off" */
void codec_configure(const char *mode);
/* log both chips' registers as they stand (two lines per chip); `when`
 * names the moment.  The first call decides whether the codecs are there. */
void codec_snapshot(const char *when);
/* the game's full-power table onto both chips; the number of registers
 * changed (0 = nothing done, for whatever reason the log says).  Records
 * the kernel's original values so codec_restore can put them back. */
int  codec_power_up(void);
/* RE-ASSERT the table, at most every KEEP_MS - call it from the menu loop.
 * The kernel's device tree routes only the headphone jack, so its DAPM
 * powers the headphone path for the running stream and pulls the LINE_OUT
 * block (the amplifiers' feed) back down after codec_power_up ran; the game
 * fights this by reprogramming the codec continuously (its health check),
 * and so does this.  Every register it finds drifted is written back and
 * logged, which is also the proof of what the kernel undoes. */
void codec_keep(long long now_ms);
/* put back what codec_power_up first found (power bits only ever removed) */
void codec_restore(void);

#endif
