r"""tools/spike2_emu/valsite.py - where a title keeps its GAME VALIDATION ERROR
state, so the emulator can say which of the six checks behind the one red
banner is up (PAD-178).

The synthetic ELFs below carry the four shapes valsite reads, instruction for
instruction as measured on Godzilla Pro 1.15 and LE 1.16: the module's start
function (the grade restore), the alert provider, its #4 getter and the
validator's tick.  The real-card checks run when the vendor cards are on this
machine and pin the answers to the addresses hwshim already carried by hand.
"""
import os
import struct
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(REPO, "tools", "spike2_emu")
sys.path.insert(0, RIG)
import valsite  # noqa: E402

BASE = 0x8000          # vaddr of file offset 0
CODE = 0x100           # where the code starts in the file


def movw(rd, imm):
    return 0xE3000000 | ((imm >> 12) & 0xF) << 16 | rd << 12 | (imm & 0xFFF)


def movt(rd, imm):
    return 0xE3400000 | ((imm >> 12) & 0xF) << 16 | rd << 12 | (imm & 0xFFF)


def bl(at, to):
    return 0xEB000000 | (((to - (at + 8)) >> 2) & 0xFFFFFF)


def elf(mod=0x7D6C1C, restore_mod=None, aud_base=0x7F7D28, tick_off=False,
        with_provider=True):
    """A one-segment ARM ELF carrying the start function, the provider, its
    getter and the tick, in that order."""
    restore_mod = mod if restore_mod is None else restore_mod
    words = []

    def at():
        return BASE + CODE + 4 * len(words)

    # the module's start function: restore the grades from NVRAM
    words += [0xE92D41F0, movw(4, restore_mod & 0xFFFF),
              movt(4, restore_mod >> 16), 0xE3A00050, 0xE3A01F85, 0xE1A02004,
              0xE3A03080]
    words.append(bl(at(), BASE + 0x4000))
    words += [0xE3500000, 0x1A000000, 0xE8BD81F0]
    getter_at = None
    if with_provider:
        prov = [0xE92D43F0, movw(5, mod & 0xFFFF), movt(5, mod >> 16),
                0xE24DD014, 0xE59530C0, 0xE1A08000, 0xE1A09001, 0xE5D3202A,
                0xE2422002, 0xE3520001, 0x93A04000, 0xE5D3202B, 0xE2422002,
                0xE3520001, 0xE5D3302C, 0xE2433002, 0xE3530001, 0xE28D0008,
                0xE28D100C]
        words += prov
        bl_at = at()
        words.append(0)                     # patched once the getter's known
        words += [0xE59D300C, 0xE8BD83F0]
        getter_at = at()
        words += [movw(3, aud_base & 0xFFFF), movt(3, aud_base >> 16),
                  0xE5932974, 0xE5933978, 0xE5802000, 0xE5813000, 0xE12FFF1E]
        words[(bl_at - BASE - CODE) // 4] = bl(bl_at, getter_at)
    # the tick: its prologue, then the state test valtick keys on
    words += [0xE12FFF1E if tick_off else 0xE92D4010, movw(4, mod & 0xFFFF),
              movt(4, mod >> 16), 0xE5D430C5, 0xE3530008, 0xE8BD8010]
    code = struct.pack("<%dI" % len(words), *words)
    size = CODE + len(code)
    hdr = bytearray(CODE)
    hdr[:16] = b"\x7fELF\x01\x01\x01" + bytes(9)
    struct.pack_into("<HHIIIIIHHHHHH", hdr, 16, 2, 40, 1, BASE + CODE, 52, 0,
                     0x5000000, 52, 32, 1, 40, 0, 0)
    struct.pack_into("<8I", hdr, 52, 1, 0, BASE, BASE, size, size, 5, 0x1000)
    return bytes(hdr) + code


def test_both_derivations_agree_and_name_the_count():
    assert valsite.sites(elf()) == (0x7D6C1C, 0x7F7D28 + 0x978)


def test_a_disagreement_names_nothing():
    """Two ways that must agree: a shim told a wrong address reports a check
    the game is not raising, which is worse than no report."""
    assert valsite.sites(elf(restore_mod=0x7D6C20)) is None


def test_a_program_without_the_provider_names_nothing():
    assert valsite.sites(elf(with_provider=False)) is None


def test_the_tick_decides_whether_the_validator_runs():
    assert valsite.tick_state(elf()) == "live"
    assert valsite.tick_state(elf(tick_off=True)) == "off"
    assert valsite.tick_state(b"\x7fELF\x01" + bytes(200)) == "unknown"


def _run(tmp_path, *elfs):
    paths = []
    for i, data in enumerate(elfs):
        p = tmp_path / ("game%d" % i)
        p.write_bytes(data)
        paths.append(str(p))
    return subprocess.run([sys.executable, os.path.join(RIG, "valsite.py")]
                          + paths, capture_output=True, text=True)


def test_the_line_describes_the_program_the_run_uses(tmp_path):
    """The card's program places the module; the override set's copy is the
    one that runs, and that is the one whose validator is reported."""
    r = _run(tmp_path, elf(), elf(tick_off=True))
    assert r.returncode == 0
    assert r.stdout.split() == ["0x7d6c1c", "0x7f86a0", "off"]
    r = _run(tmp_path, elf())
    assert r.stdout.split() == ["0x7d6c1c", "0x7f86a0", "live"]


def test_nothing_derived_prints_nothing(tmp_path):
    r = _run(tmp_path, elf(with_provider=False))
    assert r.returncode == 1 and r.stdout == ""


def test_read_code_stops_at_the_code(tmp_path):
    data = elf() + b"\xaa" * 100000         # "data" past the code segment
    p = tmp_path / "game"
    p.write_bytes(data)
    assert valsite.read_code(str(p)) == elf()


def test_the_run_exports_them_and_forwards_the_verdict():
    with open(os.path.join(RIG, "watch.sh"), encoding="utf-8") as f:
        watch = f.read()
    assert '"$RIG/valsite.py" "$GAME_ELF"' in watch
    assert "export PAD_VAL_MOD=" in watch and "PAD_VAL_AUD=" in watch
    assert "/\\[validation\\]/" in watch
    with open(os.path.join(RIG, "hwshim.c"), encoding="utf-8") as f:
        shim = f.read()
    # armed only by the exported addresses, never by Pro 1.15's defaults
    assert 'getenv("PAD_VAL_MOD") && getenv("PAD_VAL_AUD")' in shim
    assert "val_watch();" in shim


CARDS = r"D:\Pinball\images\Stern\spike2"


@pytest.mark.parametrize("card, want", [
    ("godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw", (0x7B7B70, 0x7B9308)),
    ("godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", (0x7D6C1C, 0x7F86A0)),
])
def test_real_cards(card, want):
    """Pro 1.15's pair is the one hwshim carried by hand (PAD_VAL_MOD /
    PAD_VAL_AUD defaults); LE 1.16's is the title PAD-178 was reported on."""
    path = os.path.join(CARDS, card)
    if not os.path.isfile(path):
        pytest.skip("vendor card not on this machine")
    sys.path.insert(0, REPO)
    from pinball_decryptor.plugins.stern import engine
    with open(path, "rb") as f:
        reader, fw, _img = engine._locate(f, engine._linux_partitions(path))
        game = bytes(reader.read_file_bytes(fw))
    assert valsite.sites(game) == want
    assert valsite.tick_state(game) == "live"
