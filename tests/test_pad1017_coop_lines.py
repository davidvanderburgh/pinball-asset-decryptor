"""PAD-1017: the co-op port lines (portcoop.py) - the framework's player change, its player / ball / players bytes and
its add-a-player function, read off the shapes every Spike 2 build shares."""
import glob
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import adjustments
from pinball_decryptor.plugins.stern import portcoop
from pinball_decryptor.plugins.stern.coop_play import OWN_COOP

BASE = 0x10000
PLAYER, PLAYERS, XB_COUNT = 0x713B94, 0x7D116C, 0x7CA5C8
MAX_PLAYERS_ID = 81


def _movw(r, v):
    return 0xE3000000 | (v >> 12 & 0xF) << 16 | r << 12 | v & 0xFFF


def _movt(r, v):
    return 0xE3400000 | (v >> 28 & 0xF) << 16 | r << 12 | v >> 16 & 0xFFF


def _bl(at, to):
    return 0xEB000000 | ((to - at - 8) >> 2) & 0xFFFFFF


def _ldrb(rt, rb, off=0):
    return 0xE5D00000 | rb << 16 | rt << 12 | off


def _program(store_count=True):
    """The words of Godzilla LE 1.16's framework player code, cut down to what the finder reads."""
    w = []
    at = lambda: BASE + 4 * len(w)
    # the extra-ball test
    xb = at()
    w += [_movw(3, XB_COUNT & 0xFFFF), _movt(3, XB_COUNT), _ldrb(2, 3), 0xE2920000, 0x13A00001, 0xE3500000,
          0x12422001, 0x15C32000, 0xE12FFF1E]
    # the "can a player be added" test: the same opening, no store
    w += [0xE92D4008, 0xE3A00000 | MAX_PLAYERS_ID]
    w.append(_bl(at(), 0x8000))
    w += [_movw(3, PLAYERS & 0xFFFF), _movt(3, PLAYERS), _ldrb(3, 3), 0xE6EF0070, 0xE1530000, 0xE8BD8008]
    # add a player
    add = at()
    w += [0xE92D4038, 0xE3A00000 | MAX_PLAYERS_ID]
    w.append(_bl(at(), 0x8000))
    w += [_movw(4, PLAYERS & 0xFFFF), _movt(4, PLAYERS), _ldrb(3, 4), 0xE6EF0070, 0xE1530000, 0x23A05000,
          0xE3A01000, 0x13A05001, 0x10833005]
    w += [0x15C43000 if store_count else 0xE1A00000, 0xE1A00005, 0xE8BD8038]
    # the player change
    pc = at()
    w += [0xE92D41F0, 0xE24DD008, 0xE3A00090, 0xE1A00000, 0xE3500000, 0x1A000008]
    w.append(_bl(at(), xb))
    w += [0xE2508000, 0x1A00002A, _movw(6, PLAYER & 0xFFFF), 0xE3A00009, _movt(6, PLAYER), 0xE1A00000,
          _ldrb(7, 6), _movw(3, PLAYERS & 0xFFFF), _movt(3, PLAYERS), 0xE2875001, _ldrb(3, 3), 0xE6EF5075,
          0xE1530005, 0x3A00000A, 0xE1A00007, 0xE1A00000, _ldrb(3, 6, 1), 0xE1500003, 0xE8BD81F0]
    return w, xb, add, pc


def _elf(words):
    """A 32-bit little-endian ELF holding the words in one executable PT_LOAD at BASE."""
    code = struct.pack("<%dI" % len(words), *words)
    hdr = bytearray(0x54)
    hdr[0:4] = b"\x7fELF"
    hdr[4], hdr[5] = 1, 1
    struct.pack_into("<I", hdr, 0x1C, 0x34)
    struct.pack_into("<HH", hdr, 0x2A, 32, 1)
    struct.pack_into("<8I", hdr, 0x34, 1, 0x54, BASE, BASE, len(code), len(code), 5, 4)
    return bytes(hdr) + code


class _Adj:
    def __init__(self, _data):
        self.by_name = {"AD_MAX_PLAYERS_PER_GAME": MAX_PLAYERS_ID}


def test_lines_name_the_player_change_bytes_and_add_player(monkeypatch):
    monkeypatch.setattr(adjustments, "AdjustmentTable", _Adj)
    words, _xb, add, pc = _program()
    lines, notes = portcoop.lines(_elf(words))
    assert notes == []
    assert [l.split()[:3] for l in lines] == [
        ["site", "coop_player_change", "0x%08x" % pc],
        ["site", "coop_add_player", "0x%08x" % add],
        ["data", "coop_player", "0x%08x" % PLAYER],
        ["data", "coop_players", "0x%08x" % PLAYERS]]
    # a site line carries the function's first two words, as the runtime checks them
    assert lines[0].split()[3:] == ["0x%08x" % words[(pc - BASE) // 4], "0x%08x" % words[(pc - BASE) // 4 + 1]]


def test_the_can_add_test_is_not_the_add(monkeypatch):
    """Without the count's store there is no add-a-player function: no lines, rather than the wrong one."""
    monkeypatch.setattr(adjustments, "AdjustmentTable", _Adj)
    words, *_ = _program(store_count=False)
    lines, notes = portcoop.lines(_elf(words))
    assert lines == [] and notes == ["no add-a-player function of the known shape"]


def test_no_player_change_no_lines(monkeypatch):
    monkeypatch.setattr(adjustments, "AdjustmentTable", _Adj)
    words, *_ = _program()
    words[words.index(0xE2508000)] = 0xE1A00000          # the call's result is not tested: not the player change
    assert portcoop.lines(_elf(words)) == ([], ["no player change of the known shape"])


ELFS = sorted(p for d in os.environ.get("PAD_GAME_ELFS", "C:/tmp/PAD-1010/elfs;C:/tmp/PAD-1017/elfs_old").split(";")
              for p in glob.glob(os.path.join(d, "*.elf")))


@pytest.mark.skipif(not ELFS, reason="no shipped game programs here (PAD_GAME_ELFS)")
def test_every_shipped_build_has_the_lines():
    found = {os.path.basename(p): portcoop.lines(p)[0] for p in ELFS}
    assert [k for k, v in found.items() if len(v) < 4 or not v[0].startswith("site  coop_player_change")] == []
    # and the end-of-game high scores' lines, for the team's own boards (X-Men has no challenge list to bring them)
    assert all(any(line.startswith("site  challenge_scores ") for line in v) for v in found.values())
    gz = found.get("godzilla_le-1_16_0_spike2.elf")
    if gz:
        assert [l.split()[2] for l in gz[:4]] == ["0x00338950", "0x00338790", "0x00713b94", "0x007d116c"]
    old = found.get("aerosmith_le-1_15_0.elf")   # the older shape: the count at +0x50 in a struct
    if old:
        assert [l.split()[2] for l in old[:4]] == ["0x001a51c4", "0x001a4fb8", "0x005a02f4", "0x00608e80"]


def _latest_ports():
    """The newest shipped port of each title (David, 2026-11-05: co-op on the latest versions only)."""
    best = {}
    for p in glob.glob(os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu", "modes", "sdk", "ports",
                                    "*.port")):
        title, ver = os.path.basename(p)[:-5].rsplit("-", 1)
        v = tuple(int(x) for x in ver.split("."))
        if title not in best or v > best[title][0]:
            best[title] = (v, p)
    return sorted(p for _v, p in best.values())


def test_every_latest_port_carries_the_lines():
    ports = _latest_ports()
    assert len(ports) == 53
    for p in ports:
        text = open(p, encoding="utf-8").read()
        for key in ("site  coop_player_change", "site  coop_add_player", "data  coop_player ", "data  coop_players"):
            assert key in text, (os.path.basename(p), key)
        # where co-op is offered: the "BALL %d" line that says whose turn it is, and the end-of-game high scores
        if not os.path.basename(p).startswith(OWN_COOP):
            for key in ("value coop_ball_msg", "message_table", "challenge_scores "):
                assert key in text, (os.path.basename(p), key)
