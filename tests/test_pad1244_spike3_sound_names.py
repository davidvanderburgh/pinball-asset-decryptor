"""PAD-1244: a Spike 3 extract names its sounds and maps the game's sound requests.

Built on a synthetic 64-bit game program and ``image.bin`` laid out as the real cards are
(Fallout LE 0.81/0.82, Star Wars 2025 LE/Pro, Star Wars ELG 1.10, Pokemon LE 0.82 all read
this way: docs in :mod:`pinball_decryptor.plugins.stern.spike3_requests`).
"""

import os
import struct

import pytest

from pinball_decryptor.plugins.stern import clip_sounds as CS
from pinball_decryptor.plugins.stern import spike3_requests as R
from pinball_decryptor.plugins.stern import spike3_sound as S

FRAGMENTS = 10
#: request -> its sound ids (sid 0 would end a list, as on the cards)
LISTS = [[1], [1], [2], [3, 5], [4], [6, 7], [8, 9], [2]]
#: sid -> the records its descriptor plays (sid 3 plays two parts; 6..9 play none)
SID_RECORDS = {0: [0], 1: [0], 2: [1], 3: [2, 3], 4: [4], 5: [1]}
RECORDS = 5
#: (name, node id) of the Sound Test, in menu order
MENU = [("SE FX ALPHA", 1), ("SE VO BRAVO", 4), ("INVALID", 6), ("SE FX ECHO", 99)]


def _key(i):
    return 0x40 + i, 0x1000 * i + 2                     # flags_lo (mono), param


# --------------------------------------------------------------------------- image.bin
def build_image(path):
    frames = 441
    hdr = bytearray(0x100)
    tstart = 0x100
    tend = tstart + 8 * R._PTRS_PER_SID * FRAGMENTS
    body0 = tend
    bodies = b"".join(struct.pack("<h", 1000 * (i + 1)) * frames for i in range(RECORDS))
    desc_at, block = {}, bytearray()
    dbase = body0 + len(bodies)
    for sid in range(FRAGMENTS):
        desc_at[sid] = dbase + len(block)
        d = bytearray(b"\x05\x1c\x01" + struct.pack("<I", 40)[:3] + b"\x00" * 4)
        for i in SID_RECORDS.get(sid, ()):
            fl, pa = _key(i)
            d += b"\x0b\x00\x00\x00" + struct.pack("<II", fl, pa) + b"\x00" * 4
        block += d
    md = dbase + len(block)
    table = b"".join(struct.pack("<Q", desc_at[s]) * R._PTRS_PER_SID for s in range(FRAGMENTS))
    dirb = bytearray()
    for i in range(RECORDS):
        fl, pa = _key(i)
        dirb += struct.pack("<QIIII", body0 + 2 * frames * i, fl, pa, frames, 0xabc0 + i)
    dirb += b"\x00" * (-len(dirb) % 16) + b"\x00" * 8
    struct.pack_into("<Q", hdr, 0, 0x100)
    struct.pack_into("<Q", hdr, R._DESC_TABLE_END, tend)
    struct.pack_into("<Q", hdr, 0x40, md)
    struct.pack_into("<III", hdr, 0x58, 0, FRAGMENTS, RECORDS)
    with open(path, "wb") as f:
        f.write(bytes(hdr) + table + bodies + bytes(block) + bytes(dirb))
    return path


# --------------------------------------------------------------------------- game program
def build_game(lists=LISTS, menu=MENU, self_pointing=True):
    """A minimal aarch64-shaped PIE: one PT_LOAD at VA 0, every pointer a RELATIVE reloc."""
    buf = bytearray(0x200)
    rel = []

    def put(data, align=8):
        buf.extend(b"\x00" * (-len(buf) % align))
        at = len(buf)
        buf.extend(data)
        return at

    def ptr(slot, value):
        rel.append((slot, value))

    names = {n: put(n.encode() + b"\x00") for n, _ in menu}
    groups = []
    for n, _nid in menu:
        g = put(b"\x00" * 48)
        for k in range(R._GROUP_PTRS):
            ptr(g + 8 * k, names[n])
        groups.append(g)
    arr = put(b"\x00" * (16 * len(menu)))
    for k, (g, (_n, nid)) in enumerate(zip(groups, menu)):
        ptr(arr + 16 * k, g)
        struct.pack_into("<Q", buf, arr + 16 * k + 8, nid)
    count = len(lists)
    table = put(b"\x00" * (32 * count))
    end = len(buf)
    # the last record's list first, right at the table's end (as on the cards)
    for r in reversed(range(count)):
        at = put(b"".join(struct.pack("<I", s) for s in lists[r]) + b"\x00\x00\x00\x00", 4)
        if r == count - 1 and not self_pointing:
            at += 4
        ptr(table + 32 * r + 16, at)
    assert self_pointing is False or dict(rel)[table + 32 * (count - 1) + 16] == end
    reg = put(b"\x00" * 24)
    ptr(reg, table)
    struct.pack_into("<QQ", buf, reg + 8, count, 32)
    rela = put(b"".join(struct.pack("<QQq", s, R._R_RELATIVE, v) for s, v in rel))
    shoff = put(b"\x00" * 64 + struct.pack("<IIQQQQIIQQ", 0, 4, 0, rela, rela, 24 * len(rel),
                                          0, 0, 8, 24))
    struct.pack_into("<4sBB", buf, 0, b"\x7fELF", 2, 1)
    struct.pack_into("<Q", buf, 0x20, 0x40)                      # e_phoff
    struct.pack_into("<Q", buf, 0x28, shoff)                     # e_shoff
    struct.pack_into("<HH", buf, 0x36, 56, 1)                    # e_phentsize, e_phnum
    struct.pack_into("<HHH", buf, 0x3a, 64, 2, 0)                # e_shentsize, e_shnum, e_shstrndx
    struct.pack_into("<IIQQQQQQ", buf, 0x40, 1, 5, 0, 0, 0, len(buf), len(buf), 0x1000)
    return bytes(buf)


@pytest.fixture
def card(tmp_path):
    img = build_image(str(tmp_path / "image.bin"))
    proj = tmp_path / "proj"
    S.decode_container(img, str(proj / "audio"))
    return img, str(proj)


def test_request_table_found_through_its_registry():
    prog = R.Program(build_game())
    assert R.request_table(prog, FRAGMENTS) == LISTS


def test_a_table_that_does_not_point_at_its_own_end_is_not_taken():
    prog = R.Program(build_game(self_pointing=False))
    assert R.request_table(prog, FRAGMENTS) == []


def test_a_table_reaching_too_few_sound_ids_is_not_taken():
    # the same table on a card with ten times the sound ids: not this card's requests
    prog = R.Program(build_game())
    assert R.request_table(prog, FRAGMENTS * 10) == []


def test_a_32_bit_program_is_refused():
    with pytest.raises(ValueError):
        R.Program(b"\x7fELF\x01\x01" + b"\x00" * 64)


def test_sound_ids_resolve_through_plaintext_descriptors(card):
    img, _proj = card
    assert R.sound_parts(img) == SID_RECORDS


def test_menu_names_keep_sounds_with_a_request():
    prog = R.Program(build_game())
    # INVALID is no sound; node 99 is no request
    assert R.menu_entries(prog, LISTS) == [(1, "SE FX ALPHA"), (4, "SE VO BRAVO")]


def test_requests_resolve_first_parts_and_later_parts(card):
    img, _proj = card
    idx_of, also = R.resolve(LISTS, R.sound_parts(img))
    assert idx_of[3] == [2, 1]            # sid 3's first part, then sid 5's
    assert also == {3: [3]}               # sid 3's second part
    assert 5 not in idx_of                # sids 6..9 play no recording


def test_map_sounds_names_files_and_gives_the_audio_tab_its_requests_column(card):
    img, proj = card
    logs = []
    got = R.map_sounds(build_game(), img, proj, audio_dir=os.path.join(proj, "audio"),
                       log=lambda m, k: logs.append(m))
    assert got == (6, 2)
    files = sorted(os.listdir(os.path.join(proj, "audio")))
    assert "idx0000 - SE FX ALPHA.wav" in files
    assert "idx0004 - SE VO BRAVO.wav" in files
    assert "idx0001.wav" in files                         # unnamed: left for Auto-transcribe
    req = CS.read_requests(proj)
    assert req[1]["name"] == "SE FX ALPHA" and req[3]["also"] == [3]
    uses = CS.sound_uses(proj)
    assert uses is not None and 3 in uses                # a later part counts as played
    assert CS.sound_uses_why(proj) == ""
    assert any("Mapped 6 of the game's 8" in m for m in logs)


def test_no_map_dir_names_only(card, tmp_path):
    img, proj = card
    assert R.map_sounds(build_game(), img, None, audio_dir=os.path.join(proj, "audio")) == (0, 2)
    assert not os.path.exists(os.path.join(proj, CS.REQUESTS_TSV))


def test_switches_turn_either_half_off(card, monkeypatch):
    img, proj = card
    monkeypatch.setenv("PINBALL_SFX_NAMES", "0")
    assert R.map_sounds(build_game(), img, proj, audio_dir=os.path.join(proj, "audio")) == (6, 0)
    monkeypatch.setenv("PINBALL_SOUND_REQUESTS", "0")
    os.remove(os.path.join(proj, CS.REQUESTS_TSV))
    assert R.map_sounds(build_game(), img, proj, audio_dir=os.path.join(proj, "audio")) == (0, 0)
    assert not os.path.exists(os.path.join(proj, CS.REQUESTS_TSV))


def test_a_program_without_a_request_table_leaves_the_files_alone(card):
    img, proj = card
    logs = []
    got = R.map_sounds(build_game(lists=[[1]] * 3), img, proj,
                       audio_dir=os.path.join(proj, "audio"), log=lambda m, k: logs.append(m))
    assert got == (0, 0)
    assert all(" - " not in f for f in os.listdir(os.path.join(proj, "audio")))
    assert CS.sound_uses_why(proj) == CS.WHY_EXTRACT_AGAIN
    assert any("request table wasn't found" in m for m in logs)


def test_spk_decode_names_the_sounds_beside_their_game(tmp_path):
    from pinball_decryptor.plugins.stern import spike3_extract as SE
    img = build_image(str(tmp_path / "src.bin"))
    game = build_game()

    class Pipe:
        output_dir = str(tmp_path / "out")
        logs = []

        def _check_cancel(self):
            pass

        def _progress(self, *a):
            pass

        def _log(self, m, k="info"):
            self.logs.append(m)

    def write(rel, out):
        with open(img, "rb") as s, open(out, "wb") as d:
            d.write(s.read())

    seen = []

    def game_of(d):
        seen.append(d)
        return game if d == "fallout_le" else None

    SE.decode_sound_containers(Pipe(), ["fallout_le/image.bin", "spike_menu/image.bin"],
                               lambda r: r, write, game_of=game_of)
    assert seen == ["fallout_le", "spike_menu"]
    named = os.listdir(tmp_path / "out" / "sound" / "fallout_le" / "audio")
    assert "idx0000 - SE FX ALPHA.wav" in named
    assert all(" - " not in f for f in
               os.listdir(tmp_path / "out" / "sound" / "spike_menu" / "audio"))


def test_spike3_offers_auto_transcribe_and_music_naming():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    m = SternManufacturer()
    m._era = "spike3"
    caps = m.capabilities
    assert caps.transcribe and caps.music_id
    assert [p.name for p in m.prerequisites] == ["faster-whisper"]
    assert "Spike 3" in m.extract_input_help()
