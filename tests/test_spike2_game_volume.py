"""PAD-1302: the game's own volume (service menu, coin-door knob) reaches the
speakers, and the older-CPU memcpy fix reaches the Barrels of Fun game too.

The Spike 2 rig's fake libasound (tools/spike2_emu/alsastub.c) used to give
the game one shared mixer element with a 0..100 range and throw every volume
away, so a run always played at full level. The harness below drives the stub
the way the game does (open the backbox card, a simple mixer on ctl backbox,
element PCM, set its volume, write PCM) and reads both what was captured and
what would have been played.
"""
import os
import shutil
import struct
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
BOF = os.path.join(ROOT, "tools", "bof_emu")


def _text(path):
    with open(path, encoding="utf8", newline="") as f:
        return f.read()


_HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
static long long raw_us = 1000000000LL;
struct t2 { long a, b; };
int clock_gettime(int clk, struct t2 *t)
{ (void)clk; t->a = raw_us / 1000000; t->b = raw_us % 1000000 * 1000; return 0; }
int gettimeofday(struct t2 *t, void *tz)
{ (void)tz; t->a = raw_us / 1000000; t->b = raw_us % 1000000; return 0; }
int usleep(unsigned us) { raw_us += us; return 0; }
void pad_say(const char *s) { fputs(s, stderr); }
#ifndef __linux__
int *__errno_location(void) { static int e; return &e; }
#endif
int snd_pcm_open(void **, const char *, int, int);
int snd_pcm_hw_params_set_rate_near(void *, void *, unsigned *, int *);
long snd_pcm_writei(void *, const void *, unsigned long);
int snd_mixer_open(void **, int);
int snd_mixer_attach(void *, const char *);
unsigned long snd_mixer_selem_id_sizeof(void);
void snd_mixer_selem_id_set_name(void *, const char *);
void *snd_mixer_find_selem(void *, const void *);
int snd_mixer_selem_get_playback_volume_range(void *, long *, long *);
int snd_mixer_selem_set_playback_volume_all(void *, long);
int snd_mixer_selem_set_playback_switch_all(void *, int);
int pad_pcm_vol_gain_q16(long);

static void *elem_on(const char *ctl, const char *name)
{
    void *m, *e;
    char id[256];
    snd_mixer_open(&m, 0);
    snd_mixer_attach(m, ctl);
    snd_mixer_selem_id_set_name(id, name);
    e = snd_mixer_find_selem(m, id);
    return e;
}

int main(int argc, char **argv)
{
    static short buf[1024 * 2];
    void *pcm, *bb, *cab, *sw;
    unsigned rate = 44100;
    long lo = -1, hi = -1;
    int i;
    for (i = 0; i < 2048; i++) buf[i] = 10000;
    if (argc > 1 && argv[1][0] == 'g') {          /* the gain table */
        long v;
        for (v = -1; v <= 193; v++) printf("%ld %d\n", v, pad_pcm_vol_gain_q16(v));
        return 0;
    }
    snd_pcm_open(&pcm, "sgtl5000main", 0, 0);
    snd_pcm_hw_params_set_rate_near(pcm, 0, &rate, 0);
    bb = elem_on("backbox", "PCM");
    cab = elem_on("cabinet", "PCM");
    sw = elem_on("backbox", "Line Out Mute");
    snd_mixer_selem_get_playback_volume_range(bb, &lo, &hi);
    printf("range %ld %ld\n", lo, hi);
    printf("same %d\n", elem_on("backbox", "PCM") == bb);
    snd_mixer_selem_set_playback_switch_all(sw, 0);     /* logged only */
    /* Godzilla's boot: the headphone amp at 48, never the speakers' gain */
    snd_mixer_selem_set_playback_volume_all(elem_on("backbox", "Headphone"), 48);
    snd_mixer_selem_set_playback_volume_all(bb, 168);   /* -12 dB */
    snd_mixer_selem_set_playback_volume_all(cab, 12);   /* the other card's */
    snd_pcm_writei(pcm, buf, 1024);
    snd_mixer_selem_set_playback_volume_all(bb, 0);     /* mute */
    snd_pcm_writei(pcm, buf, 1024);
    snd_mixer_selem_set_playback_volume_all(bb, 192);   /* full */
    snd_pcm_writei(pcm, buf, 1024);
    return 0;
}
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    if not shutil.which("gcc"):
        pytest.skip("no C compiler")
    if os.name == "nt":
        pytest.skip("the stub hard-codes Linux open() flags")
    d = tmp_path_factory.mktemp("vol")
    src = d / "harness.c"
    src.write_text(_HARNESS)
    exe = d / "harness"
    subprocess.run(["gcc", "-std=gnu17", "-w", "-o", str(exe), str(src),
                    os.path.join(RIG, "alsastub.c")], check=True)
    return exe


def _run(exe, tmp_path, **env):
    play, cap = tmp_path / "play.raw", tmp_path / "cap.raw"
    play.write_bytes(b"")          # the stub opens a FIFO, it never creates one
    e = dict(os.environ, PAD_AUDIO_PLAY=str(play), PAD_AUDIO_OUT=str(cap), **env)
    if "PAD_GAME_VOLUME" not in env:
        e.pop("PAD_GAME_VOLUME", None)
    r = subprocess.run([str(exe)], env=e, check=True, capture_output=True, text=True)
    def samples(p):
        b = p.read_bytes()
        return struct.unpack("<%dh" % (len(b) // 2), b)
    return r.stdout, r.stderr, samples(play), samples(cap)


def _periods(s):
    n = 2048
    return [set(s[i:i + n]) for i in range(0, len(s), n)]


def test_the_codec_curve_is_half_a_db_a_step(harness):
    out = subprocess.run([str(harness), "g"], check=True, capture_output=True,
                         text=True).stdout
    gain = {int(v): int(q) for v, q in (l.split() for l in out.splitlines())}
    assert gain[192] == gain[193] == 65536
    assert gain[0] == gain[-1] == 0
    for v in range(1, 192):
        want = 65536 * 10 ** (-(192 - v) * 0.5 / 20)
        assert abs(gain[v] - want) <= max(2, want * 1e-6), v
    assert gain[180] == round(65536 * 10 ** (-6 / 20))     # -6 dB: half


def test_the_game_volume_scales_the_speakers_not_the_capture(harness, tmp_path):
    out, log, play, cap = _run(harness, tmp_path)
    assert "range 0 192" in out           # the SGTL5000's own range, not 0..100
    assert "same 1" in out                # one element per (ctl, name)
    q = round(65536 * 10 ** (-12 / 20))
    assert _periods(play) == [{(10000 * q + 32768) >> 16}, {0}, {10000}]
    # The capture is the game's own PCM, whatever the volume.
    assert _periods(cap) == [{10000}] * 3
    assert 'game volume: "PCM" on card #0 = 168/192 (-12.0 dB' in log
    assert 'card #1 = 12/192 (-90.0 dB' in log and "(card not played)" in log
    assert 'game volume: "PCM" on card #0 = 0/192 (mute)' in log
    assert '"Line Out Mute" on card #0 -> off (logged only)' in log
    assert '"Headphone" on card #0 = 48/192 (not the speakers: logged only)' in log


def test_pad_game_volume_0_plays_full_level(harness, tmp_path):
    _, log, play, _ = _run(harness, tmp_path, PAD_GAME_VOLUME="0")
    assert _periods(play) == [{10000}] * 3
    assert "PAD_GAME_VOLUME=0" in log


def test_the_boot_menu_recipe_lands_in_the_range_we_report():
    """codeselect writes the game's own 192*(v/63)^0.2 into the same control;
    a stub that says 0..100 put the game's top volumes past its own max."""
    assert "192*(v/63)^0.2" in _text(os.path.join(RIG, "codeselect", "audio_alsa.c"))
    stub = _text(os.path.join(RIG, "alsastub.c"))
    assert "#define PCM_VOL_MAX 192L" in stub
    assert "*max = 100" not in stub


def _block(text, start, end="\nfi\n"):
    i = text.index(start)
    return text[i:text.index(end, text.index("\n", i)) + len(end)]


def test_the_bof_game_gets_the_vector_memcpy_on_an_old_cpu():
    """PAD-1302: the BoF game draws through the same d3d12 upload buffer as
    the Spike 2 renderer (PAD-357), but its env is scrubbed (env -i), so it
    never had the tunables: 7-8 fps in attract on an Ivy Bridge, ~20 with."""
    text = _text(os.path.join(BOF, "run_game.sh"))
    block = _block(text, "BOF_TUNABLES=${GLIBC_TUNABLES:-}")
    assert '"${PAD_MEMCPY_TUNE:-}" != 0' in block
    assert '"${PAD_MEMCPY_TUNE:-}" = 1' in block
    assert "\\bsse2\\b" in block and "! grep -q '^flags.*\\bavx2\\b'" in block
    assert "glibc.cpu.x86_rep_movsb_threshold=0x40000000" in block
    assert "glibc.cpu.x86_rep_stosb_threshold=0x40000000" in block
    launch = text[text.index('setsid -f runuser -u "$BOF_USER" -- env -i'):]
    launch = launch[:launch.index("game.log")]
    assert launch.index("env -i") < launch.index("${BOF_TUNABLES:+GLIBC_TUNABLES=$BOF_TUNABLES}") \
        < launch.index('"$BIN"')


def _tunables_for(script, env, cpuinfo, tmp_path):
    """Run just the decision block with a fake /proc/cpuinfo."""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    fake = tmp_path / "cpuinfo"
    fake.write_text(cpuinfo)
    body = script.replace("/proc/cpuinfo", "$FAKE_CPUINFO")
    sh = tmp_path / "t.sh"
    sh.write_text(body + '\necho "RESULT=${BOF_TUNABLES:-}${GL_TUNABLES:-}"\n', newline="\n")
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "FAKE_CPUINFO": str(fake), **env}
    out = subprocess.run([bash, str(sh)], env=e, capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.startswith("RESULT=")][-1][7:]


IVY = "flags\t\t: fpu sse sse2 ssse3 sse4_1 sse4_2 avx erms\n"
NEW = "flags\t\t: fpu sse sse2 ssse3 sse4_1 sse4_2 avx avx2 erms\n"
TUNE = "glibc.cpu.x86_rep_movsb_threshold=0x40000000:glibc.cpu.x86_rep_stosb_threshold=0x40000000"


@pytest.mark.parametrize("cpu,env,want", [
    (IVY, {}, TUNE),
    (NEW, {}, ""),
    (IVY, {"PAD_MEMCPY_TUNE": "0"}, ""),
    (NEW, {"PAD_MEMCPY_TUNE": "1"}, TUNE),
    (IVY, {"GLIBC_TUNABLES": "glibc.malloc.check=0"}, "glibc.malloc.check=0"),
])
def test_the_bof_decision(cpu, env, want, tmp_path):
    text = _text(os.path.join(BOF, "run_game.sh"))
    block = _block(text, "BOF_TUNABLES=${GLIBC_TUNABLES:-}")
    if os.name == "nt":
        pytest.skip("bash here is WSL; the env does not cross")
    assert _tunables_for(block, env, cpu, tmp_path) == want


@pytest.mark.parametrize("cpu,env,want", [
    (IVY, {"IS_WSL": "1"}, TUNE),
    (NEW, {"IS_WSL": "1"}, ""),
    (IVY, {"IS_WSL": "0"}, ""),
    (IVY, {"IS_WSL": "1", "PAD_MEMCPY_TUNE": "0"}, ""),
    (NEW, {"IS_WSL": "0", "PAD_MEMCPY_TUNE": "1"}, TUNE),
])
def test_the_spike2_renderer_decision(cpu, env, want, tmp_path):
    text = _text(os.path.join(RIG, "watch.sh"))
    block = _block(text, "GL_TUNABLES=${GLIBC_TUNABLES:-}")
    if os.name == "nt":
        pytest.skip("bash here is WSL; the env does not cross")
    block = 'IS_WSL=${IS_WSL:-0}\n' + block
    assert _tunables_for(block, env, cpu, tmp_path) == want
