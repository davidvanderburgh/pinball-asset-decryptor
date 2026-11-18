"""PAD-1379: Spike 3 cabinet light shows - the Write carries cabshow.cfg, a show starts with its song's sound ids (a
music bank's too), the Expression lights tab draws the cabinet from the port and lists the banks' songs, and the
64-bit runtime follows the song's voice (docs/plans/spike3_modes.md "Expression light shows on Spike 3")."""
import io
import os
import re
import struct
import types

import pytest

from pinball_decryptor.plugins.stern import cab_shows as CS
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern import spike3_requests as S3R

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FALLOUT = r"D:\Pinball\images\Stern\spike3\fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw"


def _bank(plays, records):
    """A music bank in the card's layout (docs/plans/spike3_modes.md "Music modes for bank songs"): the sound-id
    pointer table from 0x68 (five equal u64 per id, 0x28 .. 0x48), the descriptors after it, the directory at 0x40
    (24-byte records: +8 the key), 0x5c the id count, 0x60 the record count, 0x20 = 0. *plays*: per sound id, the
    records it plays in order."""
    keys = [0x82600000 | (i << 2) | (0x1000 << 32) | (i << 40) for i in range(records)]
    n = len(plays)
    tstart, tend = 0x68, 0x68 + 40 * n
    descs, ptrs, at = b"", [], tend
    for recs in plays:
        d = b"\x05" + b"\x00" * 8 + b"".join(b"\x0b\x00\x01\x00" + struct.pack("<Q", keys[r]) for r in recs)
        ptrs.append(at)
        at += len(d)
        descs += d
    md = at
    head = bytearray(0x68)
    struct.pack_into("<Q", head, 0x28, tstart)
    struct.pack_into("<Q", head, 0x40, md)
    struct.pack_into("<Q", head, 0x48, tend)
    struct.pack_into("<II", head, 0x5c, n, records)
    table = b"".join(struct.pack("<Q", p) * 5 for p in ptrs)
    dirs = b"".join(struct.pack("<QQQ", 0, k, 0) for k in keys)
    return bytes(head) + table + descs + dirs


def test_a_music_bank_names_the_records_each_of_its_sound_ids_plays():
    # Fallout's bank 41 as read off the card: sid 0 plays records 1 then 2, sid 1 records 3 then 0
    bank = _bank([[1, 2], [3, 0]], 4)
    assert S3R.sound_parts(io.BytesIO(bank)) == {0: [1, 2], 1: [3, 0]}
    plays = S3R.song_plays(None, {41: io.BytesIO(bank)})
    assert plays == {41 << 16: [SMo.bank_slot_key(41, 1), SMo.bank_slot_key(41, 2)],
                     41 << 16 | 1: [SMo.bank_slot_key(41, 3), SMo.bank_slot_key(41, 0)]}
    # a show on music_cat41_0003 starts with the sound id that plays it first, and only that one
    assert CS.sids_for_slot(plays, SMo.slot_key("audio/music_cat41_0003.wav")) == [41 << 16 | 1]
    assert CS.sids_for_slot(plays, SMo.slot_key("audio/music_cat41_0002.wav")) == []
    assert S3R.sound_parts(io.BytesIO(bank[:0x60])) == {}


def test_a_show_keeps_a_music_bank_song():
    slot = SMo.bank_slot_key(1, 0)
    show = CS.norm_show({"name": "x", "slot": slot, "blades": [{"fx": "solid", "ms": 1000}]})
    assert show["slot"] == slot == -65537
    text, skipped = CS.cfg_text([show], {slot: [65536]}, only=True)
    assert not skipped and "show 65536 0 x" in text


def test_the_lights_tab_lists_a_spike3_cards_bank_songs(tmp_path):
    from pinball_decryptor.webui.tabs import lights as L
    rels = ["audio/idx0412 - music.wav", "audio/music_cat01_0000.wav", "audio/music_cat41_0001.wav"]
    slots = [types.SimpleNamespace(rel_path=r, abs_path=str(tmp_path / os.path.basename(r)), duration=90.0,
                                   info=object()) for r in rels]
    audio = types.SimpleNamespace(_slots=slots, _assign={})
    assert [s["slot"] for s in L._songs(audio)] == [412]                      # a Spike 2 card's: idx songs only
    got = [s["slot"] for s in L._songs(audio, banks=True)]
    assert got == [412, SMo.bank_slot_key(1, 0), SMo.bank_slot_key(41, 1)]


def test_the_port_draws_a_spike3_cabinet():
    prof = MP.profiles()["fallout_le_0_82_spike3"]
    lights = CS.layout_from_port(MP.read_port(MP.port_path(prof)))
    assert len(lights) == 184
    assert sum(1 for x in lights if x["lane"] == 1) == 40                     # two 20-pixel speaker rings
    assert {x["x"] for x in lights if x["lane"] == 0} == {4, 22, 278, 296}   # six 24-pixel strips, four columns
    assert all(0 < x["u"] < 1000 for x in lights)


def test_the_spike3_write_carries_the_shows(monkeypatch):
    from pinball_decryptor.plugins.stern import spike3_modes as S3M, mode_write as MW
    shows = [CS.norm_show({"name": "a", "slot": 5, "blades": [{"fx": "solid", "ms": 1000}]})]
    prof = MP.profiles()["fallout_le_0_82_spike3"]
    monkeypatch.setattr(CS, "load", lambda p: shows)
    monkeypatch.setattr(CS, "project_title", lambda p, probe=False: prof)
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    assert S3M.cabs_wanted("proj", real_card=False) == (shows, prof)
    elg = MP.profiles()["star_wars_elg_1_10_spike3"]
    monkeypatch.setattr(CS, "project_title", lambda p, probe=False: elg)
    assert S3M.cabs_wanted("proj", real_card=False) == ([], None)          # no cabinet lights: the engine said so
    assert not S3M.family_left_out_lines(["expression light shows"])


def test_the_64bit_runtime_reads_the_voice_count_at_its_own_offset():
    src = open(os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c"), encoding="utf-8").read()
    m = re.search(r'pm_port_value\("sound_voice_played", ([^)]*)\)', src)
    assert m and "PM_PTR" in m.group(1) and "12" in m.group(1)               # Spike 2's +12 kept, 64-bit's own


@pytest.mark.skipif(not os.path.isfile(FALLOUT), reason="the library's Fallout LE 0.82 card is not on this PC")
def test_fallout_shows_start_with_their_songs_sound_ids():
    """Off the real card: the main-play song (bank 1, request 65) and bank 41's two songs (requests 110 / 112)."""
    from pinball_decryptor.plugins.stern import spike3_card, spike3_modes as S3M
    from pinball_decryptor.plugins.stern.ext4 import Ext4Reader
    try:
        vol = spike3_card.open_games(FALLOUT)
    except Exception as e:                                              # noqa: BLE001 - no key on this PC
        pytest.skip("the card does not open here: %s" % e)
    rd = Ext4Reader(vol, 0, vol.size)
    _state, target = S3M.card_state(rd)
    raw = bytes(rd.read_file_bytes(S3M.game_program(rd, target)))
    shows = [CS.norm_show({"name": str(s), "slot": s, "blades": [{"fx": "solid", "ms": 1000}]})
             for s in (SMo.bank_slot_key(1, 0), SMo.bank_slot_key(41, 1), SMo.bank_slot_key(41, 3),
                       SMo.bank_slot_key(1, 1))]
    got = S3M.cab_sids(rd, os.path.dirname(target), raw, shows)
    assert got == {SMo.bank_slot_key(1, 0): [65536], SMo.bank_slot_key(41, 1): [41 << 16],
                   SMo.bank_slot_key(41, 3): [41 << 16 | 1], SMo.bank_slot_key(1, 1): []}


def test_run_in_emulator_on_a_spike3_project_goes_through_try_it(monkeypatch):
    """A plain Emulate Start runs a Spike 3 card as it is: the Expression lights and Attract tabs hand the run the
    Modes tab's Try it preparation, which builds what spike3_modes.plan carries."""
    from pinball_decryptor.webui import modes_tryit as MTI
    from pinball_decryptor.webui.tabs import lights as L
    calls = []

    class Var:
        def __init__(self, v):
            self.v = v

        def get(self):
            return self.v

        def set(self, v):
            self.v = v

    emu = types.SimpleNamespace(emulate_overrides_var=Var(True), _last_up=False, _launched=lambda: False,
                                launch_with=lambda prep: calls.append(prep) or True)
    modes = types.SimpleNamespace(tryit_prepare=object())
    window = types.SimpleNamespace(service=lambda n: {"emulate": emu, "modes": modes}[n],
                                   select_tab=lambda n: calls.append(n))
    monkeypatch.setattr(L, "project_is_spike3", lambda p: False)
    assert MTI.run_spike3_project(window, "proj") is None and not calls       # a Spike 2 card's: the tab's own Start
    monkeypatch.setattr(L, "project_is_spike3", lambda p: True)
    assert MTI.run_spike3_project(window, "proj") is True
    assert calls == ["emulate", modes.tryit_prepare] and modes._tryit_project == "proj"
    assert emu.emulate_overrides_var.get() is False                          # launch_with refuses it beside Try it
