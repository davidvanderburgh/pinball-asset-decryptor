"""PAD-995: a sound played once from a sound bank kept its channel - because its descriptor was
copied cut at the 80 bytes the resolver's callers read.  The game reads a script in place to its
end op, and a call's runs to 94 bytes on Godzilla (1661 of Godzilla Pro 1.16's 2599): past the cut
the bank held zeros, which de-whiten to keystream noise, and the game read a WAIT of some two
billion ticks there.  Bank descriptors are copied whole now, in slots with room for one."""
import struct

from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern.spike2 import sfx_names as SN
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB

#: Godzilla Pro 1.16's sound id 0x612 (request 1900, idx 2034), read whole through the game's
#: resolver: duck the buses, play, WAIT, put the buses back (the second 0x09 op runs from byte
#: 0x4b to 0x5a, past the 80-byte window), wait for the voice (0x11), end (0x00).
CALL = bytes.fromhex(
    "0502014b730000020001090028000000140000001400010000000902200000001900000019000100"
    "00000b00000005057f76b992e3df100a6d000009003c00000014000000ecffffff00000902180000"
    "0019000000e7ffffff0000110100")
#: 108 bytes, as long as the game's own run on Godzilla Pro 1.16 (three of them)
LONG = CALL[:-1] + bytes(15)
#: a master directory record for plan_bank (its body offset and length word are read)
MD_RECORD = (struct.pack("<I", 0x100) + bytes(range(4, 16)) + struct.pack("<I", 0x10 ^ 0xDEADBEEF)
             + bytes(range(20, 24)))


def test_the_call_runs_past_the_window_the_resolver_s_callers_read():
    assert len(CALL) == 94 and CALL[-1] == 0 and SN.DESC_WINDOW == 0x50 and len(LONG) == 108
    assert CALL[0x4b:0x4d] == b"\x09\x02" and CALL[0x5b:0x5d] == b"\x11\x01"
    # every bank descriptor gets room for a whole script, as far as one is ever read
    assert SB.DESC_SLOT >= E._WIDE_DESC and SB.DESC_SLOT_MAX >= SB.DESC_SLOT


def test_a_bank_copy_of_the_call_keeps_its_whole_script():
    key = struct.pack("<II", 0x5bf98007, 0xd73e0000 | 1 << 13)
    d = BB.compose_descriptor(CALL, key, 0x8000, False)
    assert len(d) == len(CALL) and d[0x50:] == CALL[0x50:]
    assert E._op11_payloads(d)[0][1] == key
    assert struct.unpack_from("<I", d, E._DESC_DUR_OFF)[0] == 0x8000


def test_write_tables_whitens_a_whole_script_in_a_default_slot(tmp_path):
    import random
    rnd = random.Random(995)
    vf2 = bytes(rnd.getrandbits(8) for _ in range(SB.VF2_WINDOW + SB.DESC_SLOT))
    _d, places = SB.plan_bank([SB.BankEdit(2034, MD_RECORD, 0x10, 0x30, 1000),
                               SB.BankEdit(2035, MD_RECORD, 0x10, 0x30, 1000)])
    assert places[1].desc_off - places[0].desc_off == SB.DESC_SLOT
    path = tmp_path / "image-sc01.bin"
    path.write_bytes(bytes(places[1].desc_off + SB.DESC_SLOT + 0x100))
    descs = {0: CALL, 1: LONG}
    ks = SB.write_tables(str(path), places, descs, vf2, lambda off: off & 0x2a6, stride=5)
    data = path.read_bytes()
    for pl in places:
        plain = descs[pl.new_idx]
        raw = data[pl.desc_off:pl.desc_off + len(plain)]
        assert bytes(a ^ b for a, b in zip(raw, vf2[ks[pl.new_idx]:])) == plain


def test_write_bank_tables_copies_the_carrier_s_descriptor_whole(monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM

    class FakeEmu(object):
        VF2_VA = 0

        def __init__(self, *a):
            self.mu = self

        def boot(self):
            pass

        def close(self):
            pass

        def mem_read(self, addr, n):
            return bytes(n)
    monkeypatch.setattr(EM, "Spike2Emu", FakeEmu)
    monkeypatch.setattr(SN, "_find_resolver", lambda emu: (0x1000, 0x2000))
    monkeypatch.setattr(BB, "resolver_rule", lambda *a, **k: (0x2a6, 0))
    # (what the resolver's callers read: the first 80 bytes)
    monkeypatch.setattr(SN, "resolve_descriptor",
                        lambda *a, **k: (0x100, bytes(SN.DESC_WINDOW), CALL[:SN.DESC_WINDOW]))
    monkeypatch.setattr(E, "_whole_descriptors_once",
                        lambda gr, img: [(0x611, 0x40, CALL[:40]), (0x612, 0x100, CALL)])
    got = {}

    def write_tables(path, places, descs, vf2, ks_of, stride, desc_slot):
        got.update(descs)
        return {pl.new_idx: 0 for pl in places}
    monkeypatch.setattr(SB, "write_tables", write_tables)
    _d, places = SB.plan_bank([SB.BankEdit(2034, MD_RECORD, 0x10, 0x30, 1000)])
    key = struct.pack("<II", 0x5bf98007, 0xd73e2000)
    rows = [{"idx": 0, "findkey": key, "host": 2034}]
    BB.write_bank_tables("game", "image.bin", str(tmp_path / "image-sc01.bin"), 1, places, rows,
                         {2034: 0x612}, {2034: 0x8000}, set(), lambda *a: None, stride=5)
    assert len(got[0]) == len(CALL) and got[0][0x50:] == CALL[0x50:]


def test_the_runtime_s_mode_descriptors_are_whole_up_to_what_it_holds(monkeypatch):
    found = [(0x612, 0x100, CALL), (0x613, 0x15e, LONG)]
    monkeypatch.setattr(E, "_whole_descriptors_once", lambda gr, img: found)
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a, **k: 0)
    seen = {}

    def table(found_, params, mask, used, log, ends=None):
        seen["ends"] = ends
        return [(2, sid, d) for sid, _o, d in found_]
    monkeypatch.setattr(E, "_mode_descriptor_table", table)
    out = E._sound_mode_descriptors("game", "image.bin", [], [], [{}], lambda *a: None)
    assert seen["ends"] == {0x612: 94, 0x613: 108}
    assert out == [(2, 0x612, CALL), (2, 0x613, LONG[:SMo.RUNTIME_DESC])]


def test_wide_descriptors_are_the_whole_ones(monkeypatch):
    monkeypatch.setattr(E, "_whole_descriptors_once", lambda gr, img: [(0x612, 0x100, CALL)])
    params = [{"idx": 2034, "findkey": E._play_key(E._op11_payloads(CALL)[0][1], 0x612, 0)}]
    assert E._wide_descriptors("game", "image.bin", params, 0) == {0x612: (CALL, [2034])}
