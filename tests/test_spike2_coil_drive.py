"""hwshim.c's coil drive decoder: what a coil command asks for, and until when (PAD-381).

coil_publish() counts a coil being addressed; coil_drive_note() reads the whole
14-byte cmd 40 - pulse power, pulse time, HOLD POWER (the byte 7 that was
"undecoded" for months), hold time - plus the cmd 4d OFF and the short 40, and
publishes when each coil's drive runs out in padled version 5. Every field is
named from the game's own serialiser (godzilla Pro 1.16 0x5a995c, called from
the coil service at 0x403f88); hwshim.c's comment has the addresses.

This compiles the REAL functions out of hwshim.c (the coil motor test's
extractor - the text is never copied here) with the clock, the log and the
mapping stubbed. What is worth failing on:

  * BYTE 7 IS THE HOLD POWER and both times are TICKS, converted at the tick
    rate the rig's boards claim. A magnet held at 50/255 for 5500 ms must read
    exactly that, and the C decoder and coildecode.decode() must agree on it.
  * A HOLD IS BOUNDED: the drive ends at pulse + hold, not "until told".
  * OFF (cmd 4d) ENDS IT AT ONCE, and says how much of the hold it cut short.
  * A FRAME WITH A BAD CHECKSUM CHANGES NOTHING. A stray frame must never turn
    a coil on in the published state.
  * THE LAYOUT IS APPEND-ONLY: version 5's offsets are the ones padled.h
    documents, in both structs, and every version-4 offset is unmoved.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMU = os.path.join(ROOT, "tools", "spike2_emu")
SHIM = os.path.join(EMU, "hwshim.c")
PADLED = os.path.join(EMU, "padled.h")

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

pytestmark = [
    pytest.mark.skipif(not os.path.isfile(SHIM), reason="rig not present"),
]


def _ck(hexs):
    """Append the checksum and a zero reply length to a frame body."""
    b = bytes.fromhex(hexs)
    return (b + bytes([(-sum(b)) & 0xFF, 0])).hex()


#: godzilla Pro 1.15's ball search, captured 2026-08-04 while the rig claimed a
#: tick rate of 1 - which is why every time in them is 0
SLING_L = "880b4003ff0000ff000000002c00"
SCOOP = "880b4008ff000000000000002600"
PLUNGER = "880b400496000000000000009300"
#: what ControlCoil::v[56] sends for a magnet grab at the rig's 100 ticks/s:
#: pulse 255 for 30 ms (3 ticks), hold 50 for 5500 ms (550 ticks = 0x226)
MAGNET = _ck("880b4005ff0300322602" "0000")
OFF = _ck("88034d05")
RULE = "890340003400"                      # jaws_le's short 40 (PAD-256)
#: MPF's own test fixture for a pulse, same frame shape (agreement, not evidence)
MPF_PULSE = _ck("810b4000ff8000ff00000000")


def test_frames_are_well_formed():
    sys.path.insert(0, EMU)
    import coildecode
    for f in (SLING_L, SCOOP, PLUNGER, MAGNET, OFF, RULE, MPF_PULSE):
        assert coildecode.checksum_ok(bytes.fromhex(f)), f


def test_python_names_byte_7_the_hold_power():
    sys.path.insert(0, EMU)
    import coildecode
    d = coildecode.decode(bytes.fromhex(MAGNET))
    assert d == {"node": 8, "index": 5, "kind": "fire", "pulse_pwr": 255, "pulse_t": 3,
                 "hold_pwr": 50, "hold_t": 550, "x": 0, "pulse_ms": 30, "hold_ms": 5500}
    assert coildecode.decode(bytes.fromhex(SLING_L))["hold_pwr"] == 0xFF
    assert coildecode.decode(bytes.fromhex(SCOOP))["hold_pwr"] == 0
    assert coildecode.decode(bytes.fromhex(PLUNGER))["pulse_pwr"] == 0x96
    assert coildecode.decode(bytes.fromhex(OFF))["kind"] == "off"
    assert coildecode.decode(bytes.fromhex(RULE))["kind"] == "rule"
    assert coildecode.decode(bytes.fromhex(MPF_PULSE))["pulse_t"] == 0x80
    bad = bytearray(bytes.fromhex(MAGNET))
    bad[7] ^= 1
    assert coildecode.decode(bytes(bad)) is None


HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

static unsigned long now_ms, pad_ms_base = 5000;
static unsigned long pad_ms(void) { return now_ms; }
static void logmsg(const char *s) { fputs(s, stdout); }
static int coil_probe_on(void) { return 1; }
static unsigned nb_env_hex(const char *n, unsigned d)
{
    const char *e = getenv(n);
    return e ? (unsigned)strtoul(e, 0, 16) : d;
}

%s

static struct padled_shm shm;
static struct padled_shm *led_shm = &shm;
static unsigned led_shm_len = 8192;
static void led_map(void) { }

%s

int main(int argc, char **argv)
{
    int a;
    for (a = 1; a < argc; a++) {
        const char *s = argv[a];
        if (s[0] == 't') {
            now_ms = strtoul(s + 1, 0, 10);
        } else if (s[0] == 'q') {               /* q<node>:<idx> - the state */
            char *e;
            unsigned node = (unsigned)strtoul(s + 1, &e, 10);
            unsigned idx = (unsigned)strtoul(e + 1, 0, 10);
            printf("S until=%%u pulse=%%u/%%u hold=%%u/%%u fires=%%u offs=%%u rules=%%u t0=%%u tps=%%u\n",
                   shm.drive_until[node][idx], shm.drive_pulse_pwr[node][idx],
                   shm.drive_pulse_t[node][idx], shm.drive_hold_pwr[node][idx],
                   shm.drive_hold_t[node][idx], shm.drive_fires, shm.drive_offs,
                   shm.drive_rule_fires, shm.drive_t0, shm.drive_tps);
        } else if (s[0] == 'o') {               /* the struct's offsets */
            printf("O %%u %%u %%u %%u %%u %%u %%u %%u %%u %%u %%u\n",
                   (unsigned)offsetof(struct padled_shm, wide_skipped),
                   (unsigned)offsetof(struct padled_shm, drive_t0),
                   (unsigned)offsetof(struct padled_shm, drive_tps),
                   (unsigned)offsetof(struct padled_shm, drive_until),
                   (unsigned)offsetof(struct padled_shm, drive_pulse_t),
                   (unsigned)offsetof(struct padled_shm, drive_hold_t),
                   (unsigned)offsetof(struct padled_shm, drive_pulse_pwr),
                   (unsigned)offsetof(struct padled_shm, drive_hold_pwr),
                   (unsigned)offsetof(struct padled_shm, drive_fires),
                   (unsigned)offsetof(struct padled_shm, drive_offs),
                   (unsigned)offsetof(struct padled_shm, drive_rule_fires));
        } else {                                /* f<hex> - a frame */
            unsigned char f[64];
            int n = 0;
            s++;
            while (s[0] && s[1] && n < 64) {
                char t[3]; t[0] = s[0]; t[1] = s[1]; t[2] = 0;
                f[n++] = (unsigned char)strtoul(t, 0, 16);
                s += 2;
            }
            coil_drive_note(f, n);
        }
    }
    return 0;
}
"""

#: padled.h's documented version-5 offsets, and version 4's last field
OFFSETS = [4772, 4776, 4780, 4784, 5808, 6320, 6832, 7088, 7344, 7348, 7352]


def _src():
    return open(SHIM, encoding="utf-8", errors="replace").read()


def _extract(name):
    """One static function's DEFINITION, brace-counted out of hwshim.c (the
    coil motor test's reading; a prototype is skipped)."""
    src = _src()
    m = None
    for c in re.finditer(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M):
        brace, semi = src.find("{", c.start()), src.find(";", c.start())
        if brace >= 0 and (semi < 0 or brace < semi):
            m = c
            break
    assert m, "%s not found in hwshim.c - did it get renamed?" % name
    depth, j = 0, src.index("{", m.start())
    while j < len(src):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading %s" % name)


def _block(pattern, text=None):
    m = re.search(pattern, text if text is not None else _src(), re.M | re.S)
    assert m, "a declaration this test reads moved: %s" % pattern
    return m.group(0)


def _compile(tmp_path_factory, struct_src):
    d = tmp_path_factory.mktemp("coildrive")
    decls = "\n".join([
        _block(r"^#define NB_HWID_DEFAULT .*?$"),
        struct_src,
        "#define PADLED_MAGIC 0x44454c50u",
    ])
    body = "\n".join([
        _block(r"^#define COIL_DRIVE_FIRE .*?^struct coil_drive \{.*?^\};"),
        _extract("coil_drive_decode"), _extract("coil_drive_tps"),
        _extract("coil_ticks_ms"), _extract("coil_drive_note"),
    ])
    src = d / "coildrive.c"
    src.write_text(HARNESS % (decls, body), encoding="utf-8")
    exe = d / ("coildrive.exe" if os.name == "nt" else "coildrive")
    r = subprocess.run([CC, "-O1", "-Wall", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's coil drive did not compile:\n" + r.stderr
    return str(exe)


@pytest.fixture(scope="module")
def cbin(tmp_path_factory):
    if not CC:
        pytest.skip("no C compiler on this host")
    return _compile(tmp_path_factory,
                    _block(r"^struct padled_shm \{.*?^\};"))


@pytest.fixture(scope="module")
def hbin(tmp_path_factory):
    """The same harness over padled.h's struct, the one readers are told to
    trust - so the two structs are held to the same offsets."""
    if not CC:
        pytest.skip("no C compiler on this host")
    hdr = open(PADLED, encoding="utf-8").read()
    return _compile(tmp_path_factory, "\n".join([
        _block(r"^#define PADLED_NODES .*?$", hdr),
        _block(r"^#define PADLED_IDX .*?$", hdr),
        _block(r"^#define PADLED_COILS .*?$", hdr),
        _block(r"^struct padled_shm \{.*?^\};", hdr)]))


def _run(exe, steps, **env):
    e = dict(os.environ)
    e.pop("PAD_NB_HWID", None)
    e.update(env)
    r = subprocess.run([exe] + [s if s[0] in "tqo" else "f" + s for s in steps],
                       capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def _state(lines):
    return [dict(kv.split("=") for kv in l.split()[1:]) for l in lines if l.startswith("S ")]


def test_magnet_hold_reads_power_and_time(cbin):
    out = _run(cbin, ["t1000", MAGNET, "q8:5"])
    assert ("[coildrive] 1000 ms node 8 coil 5: pulse 255/255 for 30 ms, hold 50/255 "
            "for 5500 ms (3+550 ticks at 100/s)") in out
    s = _state(out)[0]
    assert s["until"] == str(1000 + 30 + 5500)
    assert (s["pulse"], s["hold"]) == ("255/3", "50/550")
    assert (s["t0"], s["tps"], s["fires"]) == ("5000", "100", "1")


def test_off_ends_the_drive_and_says_what_it_cut(cbin):
    out = _run(cbin, ["t1000", MAGNET, "t3000", OFF, "q8:5"])
    assert "[coildrive] 3000 ms node 8 coil 5: OFF (cmd 4d), 3530 ms of its last command left" in out
    s = _state(out)[0]
    assert (s["until"], s["offs"]) == ("0", "1")


def test_the_rule_fire_leaves_the_drive_alone(cbin):
    out = _run(cbin, ["t1000", MAGNET, RULE, "q8:5"])
    assert "[coildrive] 1000 ms node 9 coil 0: fired by its rule (short cmd 40)" in out
    s = _state(out)[0]
    assert (s["until"], s["rules"]) == ("6530", "1")


def test_a_bad_checksum_changes_nothing(cbin):
    bad = bytearray(bytes.fromhex(MAGNET))
    bad[7] ^= 1
    out = _run(cbin, ["t1000", bad.hex(), "q8:5"])
    assert not any(l.startswith("[coildrive]") for l in out)
    assert _state(out)[0]["until"] == "0"


def test_the_tick_rate_the_boards_claim_scales_the_times(cbin):
    """At MPF's fixture rate (0x500 = 1280/s) the same 550 ticks are 429 ms."""
    out = _run(cbin, ["t0", MAGNET, "q8:5"], PAD_NB_HWID="500")
    assert any("hold 50/255 for 429 ms (3+550 ticks at 1280/s)" in l for l in out)


def test_old_captures_are_slings_with_a_full_hold_and_no_time(cbin):
    out = _run(cbin, ["t10", SLING_L, SCOOP, "q8:3", "q8:8"])
    sl, sc = _state(out)
    assert (sl["pulse"], sl["hold"], sl["until"]) == ("255/0", "255/0", "10")
    assert (sc["pulse"], sc["hold"]) == ("255/0", "0/0")


@pytest.mark.parametrize("which", ["cbin", "hbin"])
def test_version_5_is_appended_where_padled_h_says(which, request):
    exe = request.getfixturevalue(which)
    line = [l for l in _run(exe, ["o"]) if l.startswith("O ")][0]
    assert [int(x) for x in line.split()[1:]] == OFFSETS
    assert OFFSETS[-1] + 4 <= 8192


def test_padled_h_documents_those_offsets():
    hdr = open(PADLED, encoding="utf-8").read()
    for name, off in zip(["drive_t0", "drive_tps", "drive_until", "drive_pulse_t",
                          "drive_hold_t", "drive_pulse_pwr", "drive_hold_pwr",
                          "drive_fires", "drive_offs", "drive_rule_fires"], OFFSETS[1:]):
        assert re.search(r"\b%s %d\b" % (name, off), hdr), name
    assert "#define PADLED_VERSION 5" in hdr
