"""The Spike 1 live switch-map walk (tools/spike1_emu/s1swmap.py).

The walk itself needs a booted guest; what is pinned here are the pure pieces
that decide WHERE it reads and WHAT it will believe:

  * :func:`find_registry` — the registry is not always at the anchor's literal
    (GOT LE's sits 0xC past it, which used to read as "count 0" and made the
    tool refuse the title);
  * :func:`plausible_name` — a name is reached through two pointer hops and a
    hop onto live data reads as a short printable string, which would then be
    shown as a switch's name and matched by the ball keeper;
  * :func:`_owns` — both rigs name their guest ``game`` (PAD-98), and walking
    the Spike 2 one with Spike 1 symbols would produce confident nonsense.

A fake guest stands in for /proc/<pid>/mem: an address -> u32 dict.
"""

import os
import struct
import sys

import pytest

_RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "spike1_emu")
if _RIG not in sys.path:
    sys.path.insert(0, _RIG)

import s1swmap  # noqa: E402


class _FakeGuest:
    """Guest memory as {address: u32}; anything unset reads back as 0."""

    def __init__(self, words=None):
        self.words = dict(words or {})

    def u32(self, addr):
        return self.words.get(addr, 0)

    def u8(self, addr):
        return self.u32(addr & ~3) >> ((addr & 3) * 8) & 0xFF


def _registry_at(base, nodes=(1, 8), rec=0x480000):
    """The words a populated registry of len(nodes) makes at *base*."""
    words = {base + 0x100: len(nodes)}
    for i, _node in enumerate(nodes):
        words[base + i * 8] = rec + i * 0x40     # record pointer
        words[base + i * 8 + 4] = 0              # empty device chain
    return words


# ------------------------------------------------------- finding the base --

def test_registry_is_found_at_the_literal_itself():
    base = 0x482000
    g = _FakeGuest(_registry_at(base))
    assert s1swmap.find_registry(g, base) == (base, 2)


def test_registry_is_found_past_the_literal():
    # GOT LE: the anchor loads an enclosing struct and the registry sits 0xC in.
    lit = 0x482e24
    g = _FakeGuest(_registry_at(lit + 0xC, nodes=(1, 8, 9, 10, 11, 12, 0)))
    base, count = s1swmap.find_registry(g, lit)
    assert (base, count) == (lit + 0xC, 7)


def test_a_bare_count_without_pointers_is_not_a_registry():
    # .data is full of small integers; the entries have to look like pointers.
    g = _FakeGuest({0x482000 + 0x100: 7})
    with pytest.raises(s1swmap.NotReady):
        s1swmap.find_registry(g, 0x482000)


def test_an_unpopulated_registry_says_not_ready():
    # count 0 = the game has not registered its switches yet, so --wait waits
    g = _FakeGuest({})
    with pytest.raises(s1swmap.NotReady):
        s1swmap.find_registry(g, 0x482000)


def test_the_scan_window_is_bounded():
    far = 0x482000 + s1swmap._REGISTRY_SCAN
    g = _FakeGuest(_registry_at(far))
    with pytest.raises(s1swmap.NotReady):
        s1swmap.find_registry(g, 0x482000)


# ------------------------------------------------------------ switch names --

@pytest.mark.parametrize("name", [
    "START BUTTON", "TROUGH #6 (L)", "L. FLIPPER BUTTON",
    "3-BANK DROP TGT TOP", "UP LEFT LOOP", "10 POINTS",
])
def test_real_switch_names_are_kept(name):
    assert s1swmap.plausible_name(name) is True


@pytest.mark.parametrize("name", [
    None, "", "AB", "X{'", "\x01\x02\x03\x04", "1234", "<?xml",
])
def test_pointer_garbage_is_refused(name):
    assert s1swmap.plausible_name(name) is False


# ---------------------------------------------------------- which guest is --

def test_only_this_rigs_guest_is_walked(tmp_path, monkeypatch):
    """comm=game is not unique on this machine — the Spike 2 rig uses it too."""
    proc = tmp_path / "proc"
    for pid, mounts in ((11, "/home/u/spike2root/rootfs /\n"),
                        (12, "/home/u/s1emu/cache/WN-1_55/rootfs /\n")):
        d = proc / str(pid)
        d.mkdir(parents=True)
        (d / "mountinfo").write_text(mounts, encoding="utf-8")
    monkeypatch.setattr(s1swmap, "PROC", str(proc))

    class _Run:
        stdout = b"  PID COMMAND %CPU\n   11 game 90.0\n   12 game 20.0\n"

    monkeypatch.setattr(s1swmap.subprocess, "run", lambda *a, **k: _Run())
    # 11 is busier, and is the OTHER rig's: the walk must take 12
    assert s1swmap.game_pid("/home/u/s1emu") == 12


def test_an_unreadable_mountinfo_stays_claimable(tmp_path, monkeypatch):
    """A pid whose mountinfo cannot be read is ambiguous, and claiming it is
    the pre-PAD-101 behaviour — never worse."""
    monkeypatch.setattr(s1swmap, "PROC", str(tmp_path))
    assert s1swmap._owns(4242, "/home/u/s1emu") is True


def test_no_guest_of_ours_is_not_ready(monkeypatch):
    class _Run:
        stdout = b"  PID COMMAND %CPU\n    9 bash 1.0\n"

    monkeypatch.setattr(s1swmap.subprocess, "run", lambda *a, **k: _Run())
    with pytest.raises(s1swmap.NotReady):
        s1swmap.game_pid("/home/u/s1emu")


# ------------------------------------------------------------- the output --

def test_written_map_is_sorted_and_atomic(tmp_path):
    out = tmp_path / "s1switches.json"
    s1swmap.write_map({"9,1": "SHOOTER LANE", "1,11": "START BUTTON",
                       "1,2": "TOP PLAYER BUTTON"}, str(out))
    text = out.read_text(encoding="utf-8")
    assert text.index('"1,2"') < text.index('"1,11"') < text.index('"9,1"')
    assert not list(tmp_path.glob("*.tmp"))     # the window polls this file


def test_the_reader_needs_no_binutils():
    """s1swmap reads the ELF itself: `nm` is not something a WSL distro has to
    have (PAD-100's lesson about the rig's bare python3)."""
    src = open(os.path.join(_RIG, "s1swmap.py"), encoding="utf-8").read()
    assert '"nm"' not in src and "'nm'" not in src


def test_elf_symbols_reads_a_game_elf(tmp_path):
    """A tiny hand-built ELF32-LE with one symbol, to prove the reader path."""
    sym = struct.pack("<IIIBBH", 1, 0x8000, 0, 0x12, 0, 1)
    strtab = b"\x00" + s1swmap.ANCHOR.encode() + b"\x00"
    shoff = 0x100
    data = bytearray(0x400)
    data[0:20] = (b"\x7fELF\x01\x01\x01" + b"\x00" * 9 +
                  struct.pack("<HH", 2, 40))
    struct.pack_into("<16sHHIIIIIHHHHHH", data, 0,
                     b"\x7fELF\x01\x01\x01" + b"\x00" * 9, 2, 40, 1, 0, 0,
                     shoff, 0, 52, 32, 0, 40, 3, 0)
    # section 0 null, 1 symtab (link -> 2), 2 strtab
    struct.pack_into("<10I", data, shoff, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into("<10I", data, shoff + 40, 0, 2, 0, 0, 0x200,
                     len(sym), 2, 0, 4, 16)
    struct.pack_into("<10I", data, shoff + 80, 0, 3, 0, 0, 0x300,
                     len(strtab), 0, 0, 1, 0)
    data[0x200:0x200 + len(sym)] = sym
    data[0x300:0x300 + len(strtab)] = strtab
    p = tmp_path / "game"
    p.write_bytes(bytes(data))
    elf, syms = s1swmap.elf_symbols(str(p))
    assert syms[s1swmap.ANCHOR] == 0x8000
    assert s1swmap.find_anchor(syms) == 0x8000
