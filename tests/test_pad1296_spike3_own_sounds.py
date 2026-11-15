"""PAD-1296: a mode's own sounds and end sound on a Stern Spike 3 card.

Each sound is a record APPENDED to the card's image.bin, keyed beside a carrier's record (a request
the game never plays), and the mode swaps the carrier's key for it while it plays (``swap <request>
<stock key> <our key>``, the item 163 route; the 64-bit runtime's lookup hook takes the key the
bank map's find is handed). The record key is the directory's +0x08/+0x0c words (flags_lo, param):
Star Wars ELG 1.10's lookups logged 46000220 02002060 etc., each exactly one record's.

Emulator proof (2026-11-14, Spike 3 rig slot 96, hidden and muted, the PCM kept): a grown image.bin
with four records and a mode on carriers 135 / 201 / 70 / 202 - the start call (1500 Hz, 3.5 s on a
2.4 s carrier: whole), the shot call (1000 Hz), the music (700 Hz, the whole 26 s mode, looping past
its 20 s) and the end call (2500 Hz) each heard in the game's output after ``[pad] sound swap:
request N looked up <stock>, took <ours>``; the game played none of the carriers itself.
"""
import os
import struct
import wave
import zlib

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_sounds as MS
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import spike3_modes as S3M
from pinball_decryptor.plugins.stern import spike3_requests as Q
from pinball_decryptor.plugins.stern import spike3_sound as SND
from pinball_decryptor.plugins.stern import spike3_write as W


class _Node(dict):
    pass


class _Reader:
    """An Ext4Reader stand-in over in-memory files {path: bytes} (test_spike3_write's)."""

    def __init__(self, files, main):
        self.files = files
        self.main = main
        self.nodes = {p: _Node(size=len(b), path=p) for p, b in files.items()}

    def find_spike_assets(self):
        return hash(self.main), None

    def iter_regular_files(self, min_size=1, max_depth=12, root_ino=2):
        for p, n in self.nodes.items():
            yield p, hash(p), n

    def read_range(self, node, off, n):
        return self.files[node["path"]][off:off + n]

    def read_file_chunks(self, node, chunk=64):
        b = self.files[node["path"]]
        for i in range(0, len(b), chunk):
            yield i, b[i:i + chunk]

    def read_file_bytes(self, node):
        return self.files[node["path"]]


def _container(tmp_path):
    """The synthetic two-record container with keys set and the header's tail word (0x38) as a card's."""
    p = str(tmp_path / "c.bin")
    SND._synth_container(p)              # idx0 mono 100 frames, idx1 stereo 50
    b = bytearray(open(p, "rb").read())
    img = SND.ImageSound(p)
    for i, (fl, pa, p2) in enumerate(((0x00000482, 0x20000082, 11), (0x20020446, 0x60200002, 22))):
        at = img.md_off + 24 * i
        struct.pack_into("<IIII", b, at + 8, fl, pa, struct.unpack_from("<I", b, at + 16)[0], p2)
    dlen = SND._align16(48)
    struct.pack_into("<I", b, img.md_off + dlen, zlib.crc32(bytes(b[img.md_off:img.md_off + dlen])))
    struct.pack_into("<Q", b, 0x38, len(b) - 4)
    return bytes(b)


def _wav(path, frames, ch, value=1000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(struct.pack("<h", value) * frames * ch)


def test_records_are_appended_with_their_keys_and_the_container_reads_back(tmp_path):
    cont = _container(tmp_path)
    r = _Reader({"/g/image.bin": cont}, "/g/image.bin")
    _wav(tmp_path / "call.wav", 300, 2, 2500)        # a stereo file for a mono carrier: made mono
    _wav(tmp_path / "music.wav", 70, 2, 3000)
    a = W.NewRecord(str(tmp_path / "call.wav"), 1, 0x00000482, 0x20100082, 0x1234)
    b = W.NewRecord(str(tmp_path / "music.wav"), 2, 0x20020446, 0x60300002, 0x5678)
    p, = W.plan_sounds(r, str(tmp_path), {}, str(tmp_path), lambda *a, **k: None,
                       adds={"/g/image.bin": [a, b]})
    assert p.appended == [2, 3] and p.grown == [] and p.staged
    old = SND.ImageSound.from_parts(cont[:0x80], cont[struct.unpack_from("<Q", cont, 0x40)[0]:], len(cont))
    new = SND.ImageSound(p.staged)
    new.validate()
    assert new.count == 4                            # the header's count with them
    assert new.md_off == old.md_off + 300 * 2 + 70 * 4
    got = [(x.offset, x.channels, x.frames, x.flags_lo, x.param, x.param2) for x in new.records]
    assert got[:2] == [(x.offset, x.channels, x.frames, x.flags_lo, x.param, x.param2) for x in old.records]
    assert got[2] == (old.md_off, 1, 300, 0x00000482, 0x20100082, 0x1234)
    assert got[3] == (old.md_off + 600, 2, 70, 0x20020446, 0x60300002, 0x5678)
    assert max(struct.unpack("<300h", new.read_body(new.records[2]))) > 2000
    data = open(p.staged, "rb").read()
    dlen = SND._align16(24 * 4)
    assert len(data) == new.md_off + dlen + 8
    assert struct.unpack_from("<I", data, len(data) - 8)[0] == zlib.crc32(data[new.md_off:new.md_off + dlen])
    assert struct.unpack_from("<Q", data, 0x38)[0] == len(data) - 4     # the tail word moved with it
    # the bodies before are the card's bytes
    assert data[0x80:old.md_off] == cont[0x80:old.md_off]


def test_a_replaced_sound_and_the_modes_records_go_in_one_container(tmp_path):
    cont = _container(tmp_path)
    r = _Reader({"/g/image.bin": cont}, "/g/image.bin")
    proj = tmp_path / "proj"
    (proj / "audio").mkdir(parents=True)
    _wav(proj / "audio" / "idx0001.wav", 80, 2, 3000)       # 50 -> 80 frames: grown
    _wav(tmp_path / "m.wav", 10, 1)
    a = W.NewRecord(str(tmp_path / "m.wav"), 1, 0x00000482, 0x20100082, 0x99)
    p, = W.plan_sounds(r, str(proj), {}, str(tmp_path), lambda *a, **k: None,
                       adds={"/g/image.bin": [a]})
    new = SND.ImageSound(p.staged)
    new.validate()
    assert p.grown == [1] and p.appended == [2] and new.count == 3
    assert new.records[1].frames == 80 and new.records[2].frames == 10
    assert new.records[2].offset == new.records[1].offset + 80 * 4


def test_a_new_key_is_the_carriers_flags_and_a_free_param_beside_its_own():
    recs = [SND.SoundRecord(i, 0, 1, 1, fl, pa, i) for i, (fl, pa) in enumerate(
        ((0x482, 0x20000082), (0x482, 0x20100082), (0x446, 0x60200002), (0x482, 0x00000002)))]
    fl, pa = W.free_key(recs, 0x482, 0x20000082)
    assert fl == 0x482 and (fl, pa) not in {(r.flags_lo, r.param) for r in recs}
    assert pa & 0x3 == 0x20000082 & 0x3                         # bits 0-1 stay the carrier's
    assert bin(pa ^ 0x20000082).count("1") == 1                  # one varied bit away
    fl2, pa2 = W.free_key(recs, 0x482, 0x20000082, taken=[(fl, pa)])
    assert (fl2, pa2) != (fl, pa)
    p2 = W.free_param2(recs, b"seed", taken=[5])
    assert p2 not in {r.param2 for r in recs} | {5, 0}
    k = W.NewRecord("x.wav", 1, 0x20000082, 0x60200002, 1).key
    assert k == bytes.fromhex("8200002002002060")                # flags_lo then param, little-endian


def test_sound_parts_reads_an_open_file_like_a_path(tmp_path):
    p = tmp_path / "c.bin"
    p.write_bytes(_container(tmp_path))
    with open(p, "rb") as f:
        f.read(0x100)                                            # anywhere: it seeks
        assert Q.sound_parts(f) == Q.sound_parts(str(p))


def test_spike3_carriers_are_their_own_table():
    a64 = MS.profile_carriers("star_wars_elg_1_10_spike3")
    arm = MS.profile_carriers("star_wars_elg_1_10")
    assert a64 is MS.TITLES_A64[("star_wars_elg", "1.10")] and a64.swap
    assert arm is MS.TITLES[("star_wars_elg", "1.10")]
    # the Spike 2 build's census carriers two request ids on (calls 133 200 199 72 236), 344 = 343's record
    assert a64.calls == (135, 202, 201, 74, 238) and a64.music == (70, 345, 73, 78)
    assert MS.profile_carriers("pokemon_le_0_82_spike3") is None
    assert MS.carriers("star_wars_elg", "1.10", "a64") is a64


def test_a_spike3_build_offers_a_modes_own_sounds_where_carriers_are_known():
    assert MP.end_sound_carried("star_wars_elg", "1.10", "a64")
    assert not MP.end_sound_carried("pokemon_le", "0.82", "a64")
    p = MP.profile_for_card("star_wars_elg", "1.10.0", arch="a64")
    if p is None:
        pytest.skip("no Spike 3 port of Star Wars ELG 1.10 in this tree")
    assert p.why_not("own_sound") == ""


class _Prof:
    key = "star_wars_elg_1_10_spike3"
    label = "Star Wars ELG 1.10 (Spike 3)"
    arch = "a64"
    callout_time_up = 0


def test_a_spike3_build_carries_the_end_sound_on_a_carrier():
    assert MW.end_on_carrier(_Prof())
    assert "sound_end" in MW.carried_keys(_Prof())


def test_own_sounds_key_each_sound_beside_its_carriers_record(tmp_path, monkeypatch):
    cont = _container(tmp_path)
    r = _Reader({"/g/image.bin": cont}, "/g/image.bin")
    for n in ("s.wav", "e.wav"):
        _wav(tmp_path / n, 4410, 1)
    wanted = [{"slug": "m", "name": "M", "key": "sound_start", "request": 5, "candidates": [5, 6],
               "wav": str(tmp_path / "s.wav"), "music": False, "swap": True},
              {"slug": "m", "name": "M", "key": "sound_end", "request": 5, "candidates": [5, 6],
               "wav": str(tmp_path / "e.wav"), "music": False, "swap": True}]
    monkeypatch.setattr(MW, "choose_own_sounds", lambda *a, **k: [dict(e) for e in wanted])
    monkeypatch.setattr(Q, "Program", lambda raw: object())
    monkeypatch.setattr(Q, "request_table", lambda prog, frag: [[], [], [], [], [], [7], [8]])
    monkeypatch.setattr(Q, "sound_parts", lambda f: {7: [0], 8: [1]})
    monkeypatch.setattr("pinball_decryptor.plugins.stern.info.container_counts", lambda head: (9, 2))
    used, adds = S3M.own_sounds("proj", [("m", object())], r, b"", _Prof())
    assert [u["request"] for u in used] == [5, 6]                # distinct within one mode
    assert used[0]["stock_key"] == struct.pack("<II", 0x00000482, 0x20000082).hex()
    assert used[1]["stock_key"] == struct.pack("<II", 0x20020446, 0x60200002).hex()
    news = adds["/g/image.bin"]
    assert [n.channels for n in news] == [1, 2] and [u["our_key"] for u in used] == [n.key.hex() for n in news]
    assert used[0]["ms"] == 100
    # the mode file names each carrier's swap
    req, ms = MW.own_cfg_args("proj", "m", object(), [dict(u, stock_key=u["stock_key"], our_key=u["our_key"])
                                                       for u in used])
    assert req["sound_start"] == 5 and req["sound_end"] == 6
    assert [(r_, s) for r_, s, _o in req["swaps"]] == [(5, used[0]["stock_key"]), (6, used[1]["stock_key"])]
    assert ms == {"sound_start": 100, "sound_end": 100}


def test_try_its_patch_builds_the_same_file_the_write_stages(tmp_path):
    cont = _container(tmp_path)
    r = _Reader({"/g/image.bin": cont}, "/g/image.bin")
    _wav(tmp_path / "a.wav", 300, 1, 2500)
    _wav(tmp_path / "b.wav", 70, 2, 3000)
    adds = [W.NewRecord(str(tmp_path / "a.wav"), 1, 0x482, 0x20100082, 7),
            W.NewRecord(str(tmp_path / "b.wav"), 2, 0x20020446, 0x60300002, 8)]
    whole, = W.plan_sounds(r, str(tmp_path), {}, str(tmp_path), lambda *a, **k: None,
                           adds={"/g/image.bin": adds})
    cut, head, tail = W.stage_tail(r, r.nodes["/g/image.bin"], adds, str(tmp_path / "p"), "c0")
    built = bytearray(cont[:cut] + open(tail, "rb").read())     # s3run.sh: cp, truncate, cat
    built[:0x80] = open(head, "rb").read()                      # dd conv=notrunc
    assert bytes(built) == open(whole.staged, "rb").read()


def test_try_it_lists_each_patched_container_for_s3run(tmp_path):
    cont = _container(tmp_path)
    r = _Reader({"/g/image.bin": cont}, "/g/image.bin")
    _wav(tmp_path / "a.wav", 30, 1)

    class _Plan:
        sound_adds = {"/g/image.bin": [W.NewRecord(str(tmp_path / "a.wav"), 1, 0x482, 0x20100082, 7)]}
    files = tmp_path / "files"
    assert S3M.stage_try_it_sounds(r, _Plan(), str(files)) == 1
    line = (files / S3M.GAMES_PATCH / "patches").read_text().strip()
    rel, cut, head, tail = line.split("|")
    assert rel == "g/image.bin" and int(cut) == struct.unpack_from("<Q", cont, 0x40)[0]
    assert (files / S3M.GAMES_PATCH / head).stat().st_size == 0x80
    assert (files / S3M.GAMES_PATCH / tail).is_file()

    class _None:
        sound_adds = {}
    assert S3M.stage_try_it_sounds(r, _None(), str(tmp_path / "none")) == 0


def test_s3run_builds_try_its_patch_in_the_slot_and_takes_it_away_after():
    s = open(os.path.join(os.path.dirname(__file__), "..", "tools", "spike3_emu", "s3run.sh"),
             encoding="utf-8").read()
    assert 'GPATCH=${PAD_S3_MODE_FILES:+$PAD_S3_MODE_FILES/games.patch}' in s
    assert 'truncate -s "$cut" "$dst" && cat "$GPATCH/$tail" >> "$dst"' in s
    assert 'dd if="$GPATCH/$head" of="$dst" conv=notrunc' in s
    assert s.index('rm -f "$SD/games.up/$f"') < s.index('GPATCH=')     # the last run's first
    # the patch folder is not copied into /dump with the mode files
    assert 'find "$PAD_S3_MODE_FILES" -maxdepth 1 -type f' in s
