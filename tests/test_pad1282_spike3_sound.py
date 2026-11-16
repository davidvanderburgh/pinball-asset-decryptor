"""PAD-1282: the game's callouts and sounds from a mode on a Spike 3 (64-bit ARM) game.

What the work found, held here at the desk (no card, no emulator):
- callout / callout_nth / sound_play / sound_nth / sound_active / sound_stop are plain calls into the game
  (a u16 request in w0) and were 64-bit already; the sound features around them read the engine's structs
  at Spike 2's offsets. Star Wars ELG 1.10's Spike 3 build has the same structs with 8-byte pointers:
  a request record is 32 bytes (Spike 2: 20), the same 8 tail bytes after three pointers (the bytes of
  every request match the Spike 2 build's), its sid list the third pointer; a channel is 288 bytes, its
  request at +272, voice bits +276, bus mask +277, eight 8-byte voice pointers at +144; a voice's volume
  step at +56.
- sound_lookup on Spike 3 is the bank map's find, and takes the 8-byte record key BY VALUE in x1
  (Spike 2's takes its address in r1): LOOKUP_KEY / LOOKUP_TAKE.
- the request and the variant reach the worker as w0's u16 and w2's byte: masked.
- s3port.py could not pair sound_worker / sound_resolve / sound_lookup; they are read off the program
  from the placed callout now (sound_engine), with the request table, its count and the channel table.
- Spike 3's request ids are Spike 2's + 2 on this build (two requests added early): request_shift reads
  it off the constant ids both builds' code passes to the callout.
Spike 2's mode.so stays byte-identical (tests/test_stern_mode_runtime.py holds the prebuilt).
"""
import importlib.util
import pathlib
import re
import struct

import pytest

from tests.test_spike2_mode_roster import _host_run, _lift

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORT = SDK / "ports" / "spike3" / "star_wars_elg-1.10.port"
S3RUN = ROOT / "tools" / "spike3_emu" / "s3run.sh"


def _cc_or_skip():
    from tests.test_spike2_mode_roster import _cc
    try:
        cc = _cc()
    except Exception:
        cc = None
    if not cc:
        pytest.skip("no host C compiler")
    return cc


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _layout_block(src):
    a = src.index("#define PM_PTR ")
    b = src.index("unsigned pm_callout_id(const char *role)")
    return src[a:b]


def _s3port():
    spec = importlib.util.spec_from_file_location("s3port", ROOT / "tools" / "spike3_emu" / "s3port.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    return S


# ---- the runtime ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ptr, want", [("unsigned", "4 20 16 17 19 8"),
                                       ("unsigned long long", "8 32 28 29 31 16")])
def test_request_record_layout_on_either_machine(tmp_path, ptr, want):
    _cc_or_skip()
    blk = _layout_block(_src())
    blk = blk[:blk.index("#if PM_A64")]              # the layout macros only (the key's come after)
    code = r"""
#include <stdio.h>
#define pm_addr %s
%s
int main(void)
{
    unsigned char rec[64] = {0};
    printf("%%d %%u %%u %%u %%u %%u\n", PM_PTR, REQ_SIZE, REQ_PRIO, REQ_FLAGS, REQ_CHECK,
           (unsigned)((unsigned char *)&REQ_LIST(rec) - rec));
    return 0;
}
""" % (ptr, blk)
    assert _host_run(tmp_path, code).strip() == want


def test_the_64_bit_lookup_takes_the_key_bytes_as_the_register(tmp_path):
    """Spike 3's sound_lookup is find(map, key): the key's 8 bytes, little-endian, ARE x1"""
    _cc_or_skip()
    blk = _layout_block(_src())
    a64 = blk[blk.index("#if PM_A64") + len("#if PM_A64"):blk.index("#else")]
    code = r"""
#include <stdio.h>
#include <string.h>
#define pm_reg unsigned long long
%s
int main(void)
{
    static const unsigned char ours[8] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x88 };
    pm_reg r[4] = { 0, 0x1122334455667788ull, 0, 0 };
    unsigned char k[8];
    memcpy(k, LOOKUP_KEY(r), 8);
    LOOKUP_TAKE(r, ours);
    printf("%%02x%%02x %%016llx\n", k[0], k[7], r[1]);
    return 0;
}
""" % a64
    assert _host_run(tmp_path, code, flags=("-Wno-unused-function",)).strip() == "8811 8807060504030201"


def test_every_lookup_hook_reads_and_swaps_the_key_through_the_macros():
    src = _src()
    for f in ("static void on_sound_lookup(pm_reg *r)", "static int ci_lookup(pm_reg *r)",
              "static int cpk_lookup(pm_reg *r)", "static int att_lookup(pm_reg *r)",
              "static int gms_lookup(pm_reg *r)", "static int juke_lookup(pm_reg *r)",
              "static void sndt_lookup(pm_reg *r)"):
        body = _lift(src, f)
        assert "LOOKUP_KEY(r)" in body or "on_sound_lookup" in f, f
        assert "(const unsigned char *)(unsigned long)r[1]" not in body, f
        assert not re.search(r"r\[1\] = \(unsigned\)\(unsigned long\)", body), f
    assert "LOOKUP_TAKE(r, swaps[i].ours);" in src and "LOOKUP_TAKE(r, sound_key);" in src


def test_no_sound_struct_is_read_at_a_32_bit_offset():
    src = _src()
    assert not re.search(r"table \+ (request|r) \* 20\b", src)
    assert "(rec + 8)" not in src
    assert not re.search(r"rec\[1[679]\]", src)
    assert "*(unsigned *)(c + o_vp + 4 * b)" not in src
    assert src.count("*(pm_addr *)(c + o_vp + PM_PTR * b)") == 3
    assert not re.search(r'unsigned table = data\("sound_requests"\)', src)
    assert src.count('pm_addr table = data("sound_requests")') == 5


def test_the_worker_takes_the_request_as_a_u16_on_64_bit_arm():
    src = _src()
    assert "#define WORKER_REQ(r) ((unsigned)(r)[0] & 0xffffu)" in src
    assert "#define WORKER_N(r)   ((unsigned)(r)[2] & 0xffu)" in src
    body = _lift(src, "static void on_sound_worker(pm_reg *r)")
    assert "sound_say(WORKER_REQ(r), WORKER_N(r));" in body
    assert "r[0]" not in body


def test_the_32_bit_only_sound_pieces_stay_off_on_64_bit_arm():
    src = _src()
    own = _lift(src, "static void own_on_arm(void)")
    assert own.index("#if PM_A64\n    return;") < own.index('a = fn("sound_active");')
    # PAD-1324: the music modes' descriptors stay 32-bit ARM's: on 64-bit they swap records (mswap) instead,
    # and a descriptor line is left alone, never handed the 64-bit resolver
    arm = _lift(src, "static void sndm_arm(void)")
    assert arm.index("if (n_msw) {") < arm.index("descriptor line(s) left alone") < arm.index("hook_wrap(")
    assert "the asset descriptors are 32-bit ARM's on this runtime" not in src


# ---- the port -----------------------------------------------------------------------------------------------
def _lines(kind):
    return [raw.split() for raw in PORT.read_text(encoding="utf-8").splitlines() if raw.split()[:1] == [kind]]


def test_elg_spike3_port_carries_the_callouts_and_sounds():
    sites = {t[1]: t[2:] for t in _lines("site")}
    assert sites["callout"] == sites["sound_play"] == ["0x0020dc70", "0xf0002928", "0x910c8108"]
    assert sites["callout_nth"] == sites["sound_nth"] == ["0x0020dd40", "0xf0002928", "0x910c8108"]
    assert sites["sound_active"][0] == "0x0020b070" and sites["sound_stop"][0] == "0x0020b220"
    assert sites["sound_worker"] == ["0x0020d2e0", "0x90002468", "0xf9468508"]      # the callout's call
    assert sites["sound_resolve"] == ["0x00208700", "0xaa0103e2", "0xa9bd53f3"]
    assert sites["sound_lookup"] == ["0x002084f0", "0xf9400c02", "0xb5000142"]      # the bank map's find
    data = {t[1]: t[2] for t in _lines("data")}
    assert data["sound_channels"] == "0x00733340"           # not the page + 0x220 the pairing found
    assert data["sound_requests"] == "0x006fd360" and data["sound_request_count"] == "0x005a38c8"
    values = {t[1]: int(t[2], 0) for t in _lines("value")}
    assert {k: values[k] for k in values if k.startswith("sound_")} == {
        "sound_channel_count": 8, "sound_channel_size": 288, "sound_channel_request": 272,
        "sound_channel_voices": 276, "sound_channel_bus": 277, "sound_channel_voice_ptrs": 144,
        "sound_voice_volume": 56}
    assert values["countdown_step"] == -1
    assert {t[1]: int(t[2]) for t in _lines("callout")} == {"countdown": 170}    # Spike 2's 168 + 2


# ---- the drafter ----------------------------------------------------------------------------------------------
def test_s3port_carries_the_sound_entries():
    S = _s3port()
    assert {"callout", "callout_nth", "sound_play", "sound_nth", "sound_active", "sound_stop",
            "sound_worker", "sound_resolve", "sound_lookup"} <= set(S.SITES_PROVEN)
    assert {"sound_channels", "sound_requests", "sound_request_count"} <= set(S.DATA_PROVEN)
    assert dict(S.SOUND_VALUES)["sound_channel_size"] == 288


def test_s3port_decodes_the_engine_words():
    S = _s3port()
    assert S._adrp(0x20dc70, 0xf0002928) == (8, 0x734000)          # adrp x8, 0x734000 (ELG's callout)
    assert S._add_imm(0x910c8108) == (8, 8, 0x320)                  # add x8, x8, #0x320
    assert S._bl(0x20dcc0, 0x97fffd88) == 0x20d2e0                  # bl the worker
    assert S._bl(0x20dcc0, 0x910c8108) is None


class _Fake:
    """an Elf with code words only: a64 or arm, calls from scan()'s index -> target"""
    def __init__(self, a64, words, tva=0x1000):
        self.a64, self.words, self.tva = a64, words, tva
        self.calls = {}
        for i, w in enumerate(words):
            if (w & 0xFC000000) == 0x94000000 or (not a64 and (w & 0x0F000000) == 0x0B000000):
                self.calls[i] = 0x9000


def test_request_shift_reads_the_ids_both_builds_pass_to_the_callout():
    S = _s3port()
    ids = list(range(100, 130))
    arm = []                     # mov r0, #id (ids < 256) / movw r0, #id; bl
    for i in ids:
        arm += [0xE3A00000 | i, 0xEB000000]
    arm += [0xE3000000 | (1 << 16) | 0x2C, 0xEB000000]                 # movw r0, #0x1002c
    a64 = []
    for i in ids:
        a64 += [0x52800000 | ((i + 2) << 5), 0x94000000]               # movz w0, #(id + 2); bl
    ref, tgt = _Fake(False, arm), _Fake(True, a64)
    assert set(S._const_ids(ref, 0x9000)) == set(ids) | {0x102c}
    k, hits, of = S.request_shift(ref, 0x9000, tgt, 0x9000)
    assert (k, hits, of) == (2, 30, 31)
    assert S.request_shift(ref, 0x9000, _Fake(True, a64[:8]), 0x9000)[0] is None   # too few to tell


# ---- the rig --------------------------------------------------------------------------------------------------
def test_s3run_keeps_the_pcm_muted_for_a_proof():
    s = S3RUN.read_text(encoding="utf-8")
    i = s.index('if [ "${PAD_S3_AUDIO_OUT:-0}" = 1 ] && [ -n "$PRELOAD" ]; then')
    assert 'PRELOAD="$PRELOAD PAD_S3_AUDIO_OUT=/connectivity/dump/pcm"' in s[i:i + 400]
    assert "PAD_S3_AUDIO_PLAY" not in s[i:i + 400]                   # no player: nobody hears it
