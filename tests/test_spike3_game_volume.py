"""PAD-1560: the Spike 3 game's volume reaches the speakers.

Mike, The Walking Dead Remastered in Visual Pinball: "Volume controls not
working using 8 and 9. They go up and down but volume stays high." The
Spike 3 game never scales its PCM: it sets the speaker amplifier (a
TAS5711-family part at 0x1b on the amp bus, /dev/i2c-10) - master 0x07,
channels 0x08/0x09, 0.5 dB a step, 0x30 = 0 dB, 0xff = mute. s3dev.so answered
that bus and threw the values away. Now it keeps them and s3alsa.so plays the
speakers at that gain, as Spike 2's alsastub.c does since PAD-1302; the
PAD_S3_AUDIO_OUT capture stays the game's own full-level PCM.

The harness below builds both shims for this host and drives them the way the
game does: the amp's writes through I2C_RDWR, then S16 PCM through snd_pcm_*.
"""
import os
import shutil
import struct
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S3 = os.path.join(ROOT, "tools", "spike3_emu")

HARNESS = r"""
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>
int snd_pcm_open(void **, const char *, int, int);
unsigned long snd_pcm_hw_params_sizeof(void);
int snd_pcm_hw_params_any(void *, void *);
int snd_pcm_hw_params_set_format(void *, void *, int);
int snd_pcm_hw_params_set_channels(void *, void *, unsigned);
int snd_pcm_hw_params_set_rate(void *, void *, unsigned, int);
int snd_pcm_hw_params(void *, void *);
long snd_pcm_writei(void *, const void *, unsigned long);
struct msg { uint16_t addr, flags, len, pad; uint8_t *buf; };
struct rdwr { struct msg *msgs; uint32_t nmsgs; };
static int bus;
static void amp(int reg, int v)          /* one register, as the game writes it */
{
    uint8_t b[2] = { (uint8_t)reg, (uint8_t)v };
    struct msg m = { 0x1b, 0, 2, 0, b };
    struct rdwr d = { &m, 1 };
    ioctl(bus, 0x0703, (void *)(uintptr_t)0x1b);
    if (ioctl(bus, 0x0707, &d) != 1) { perror("I2C_RDWR"); exit(3); }
}
int main(int argc, char **argv)
{
    void *pcm, *p = malloc(snd_pcm_hw_params_sizeof());
    static short s[2 * 1024];
    int i, a;
    for (i = 0; i < 2 * 1024; i++) s[i] = (i & 1) ? -10000 : 10000;
    bus = open("/dev/i2c-10", O_RDWR);
    if (bus < 0) { perror("open i2c"); return 2; }
    snd_pcm_open(&pcm, "default", 0, 0);
    snd_pcm_hw_params_any(pcm, p);
    snd_pcm_hw_params_set_format(pcm, p, 2);
    snd_pcm_hw_params_set_channels(pcm, p, 2);
    snd_pcm_hw_params_set_rate(pcm, p, 48000, 0);
    snd_pcm_hw_params(pcm, p);
    /* each argument: "reg=value,reg=value" amp writes, then one period of PCM */
    for (a = 1; a < argc; a++) {
        char *t = argv[a];
        while (*t) {
            int reg = (int)strtol(t, &t, 16), v;
            if (*t++ != '=') break;
            v = (int)strtol(t, &t, 16);
            amp(reg, v);
            if (*t == ',') t++;
        }
        snd_pcm_writei(pcm, s, 1024);
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    if not shutil.which("gcc"):
        pytest.skip("no C compiler")
    if not sys.platform.startswith("linux"):
        pytest.skip("the shims are Linux LD_PRELOAD libraries")
    d = tmp_path_factory.mktemp("s3vol")
    for name, extra in (("s3dev", ["-ldl"]), ("s3alsa", [])):
        subprocess.run(["gcc", "-std=gnu17", "-w", "-shared", "-fPIC", "-o", str(d / ("lib%s.so" % name)),
                        os.path.join(S3, name + ".c")] + extra, check=True)
    src = d / "h.c"
    src.write_text(HARNESS)
    exe = d / "h"
    # s3dev first: its open()/ioctl() answer the amp bus before libc's
    subprocess.run(["gcc", "-std=gnu17", "-w", "-o", str(exe), str(src), "-L" + str(d),
                    "-ls3dev", "-ls3alsa", "-ldl", "-Wl,-rpath," + str(d)], check=True)
    return exe


def _run(exe, tmp_path, steps, **env):
    play, out = tmp_path / "speakers.raw", tmp_path / "cap"
    play.write_bytes(b"")
    e = dict(os.environ, PAD_S3_AUDIO_PLAY=str(play), PAD_S3_AUDIO_OUT=str(out), **env)
    if "PAD_GAME_VOLUME" not in env:
        e.pop("PAD_GAME_VOLUME", None)
    r = subprocess.run([str(exe)] + steps, env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr

    def periods(p):
        b = p.read_bytes()
        s = struct.unpack("<%dh" % (len(b) // 2), b)
        return [max(s[i:i + 2048]) for i in range(0, len(s), 2048)]
    return r.stderr, periods(play), periods(tmp_path / "cap.default")


def test_the_amp_volume_scales_the_speakers_not_the_capture(harness, tmp_path):
    # boot (0 dB, nothing written), the game's level after Guided Setup (0x64
    # = -26 dB), Service Plus (0x62), mute (0xff), then back to 0x30 = 0 dB
    log, play, cap = _run(harness, tmp_path, ["", "7=30,8=64,9=64,a=64", "8=62,9=62,a=62",
                                              "8=ff,9=ff,a=ff", "8=30,9=30"])
    assert cap == [10000] * 5                         # the capture is the game's own PCM
    assert play[0] == 10000
    assert play[1] == round(10000 * 10 ** (-26 / 20))    # 501
    assert play[2] == round(10000 * 10 ** (-25 / 20))    # one dB louder
    assert play[3] == 0
    assert play[4] == 10000
    assert "game volume: amp 0x1b master 0x30 speakers 0x64 = -26.0 dB" in log
    assert "speakers 0xff = mute" in log


def test_a_boost_never_plays_above_full_level(harness, tmp_path):
    _, play, _ = _run(harness, tmp_path, ["7=20,8=20,9=20"])
    assert play == [10000]


def test_pad_game_volume_0_plays_full_level(harness, tmp_path):
    log, play, _ = _run(harness, tmp_path, ["8=64,9=64"], PAD_GAME_VOLUME="0")
    assert play == [10000]
    assert "PAD_GAME_VOLUME=0" in log


def test_s3run_hands_the_switches_to_the_game():
    text = open(os.path.join(S3, "s3run.sh"), encoding="utf-8").read()
    assert 'PRELOAD="$PRELOAD PAD_GAME_VOLUME=0"' in text
    assert 'PRELOAD="$PRELOAD PAD_S3_I2C_TRACE=1"' in text
