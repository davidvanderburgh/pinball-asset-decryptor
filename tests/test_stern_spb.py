"""PAD-233: Stern's .SPB settings export / the card's NVM store (plugins.stern.spb).

Synthetic bodies carry the layout read off David's TMNT, Godzilla and Batman saves;
the last test runs on the real saves when this machine has them.
"""
import glob
import hashlib
import os
import struct
import zlib

import pytest

from pinball_decryptor.plugins.stern import spb


def body(settings, audits=(), code=b"Q5", ver=(1, 59), serial=304782, tail=b"\x00" * 64):
    """settings = [(caption, default, min, max, id, value)]; audits = [(caption, value)]."""
    b = bytearray(b"MAP0" + code + b"\x00\x00")
    b += struct.pack("<I", serial) + bytes([ver[0], ver[1], 0, 4])
    b += b"\x00" * (spb.OFF_COUNTS - len(b))
    b += struct.pack("<HH", len(audits), len(settings))
    b += b"\x00" * (spb.AUDITS_AT - len(b))
    for i, (cap, v) in enumerate(audits):
        b += spb.caption_key(cap) + struct.pack("<5I", i + 1, v, 0, v, spb.audit_check(v, 0, v))
    for cap, d, mn, mx, aid, v in settings:
        b += spb.caption_key(cap) + struct.pack("<6I", d, mn, mx, aid, v, spb.adj_check(v))
    return bytes(b + tail)


def spbfile(b):
    return spb.MAGIC + struct.pack("<I", len(b)) + hashlib.sha1(b).digest() + b


ROWS = [("BALLS PER GAME", 3, 1, 10, 80, 3), ("MASTER VOLUME SETTING", 7, 0, 63, 12, 7),
        ("AUTO REPLAY START", 10000000, 10000000, 100000000, 63, 56800000)]


def test_a_body_reads_the_same_as_its_spb_and_both_write_back_byte_for_byte():
    b = body(ROWS, audits=[("TOTAL PLAYS", 179)])
    raw, box = spb.SettingsFile(b), spb.SettingsFile(spbfile(b))
    assert not raw.container and box.container and box.signature_ok and raw.signature_ok is None
    assert (box.map_code, box.serial, box.version) == ("Q5", 304782, "1.59")
    assert [s.value for s in box.settings()] == [3, 7, 56800000]
    assert all(s.check_ok for s in box.settings()) and box.audits()[0][1:] == (179, True)
    assert raw.to_bytes() == b and box.to_bytes() == spbfile(b)


def test_a_setting_is_found_by_its_caption_and_written_with_its_check():
    sf = spb.SettingsFile(spbfile(body(ROWS)))
    assert sf.find("BALLS PER GAME").value == 3
    assert sf.find("BALLS PER GAME ") is None                     # the caption, byte for byte
    old = sf.set("BALLS PER GAME", 5)
    assert old.value == 3
    s = sf.find("BALLS PER GAME")
    assert s.value == 5 and s.check_ok
    # the check is 0xFF - bytesum(value) mod 256: 3 -> 0xFC (the July hardware edit), 5 -> 0xFA
    assert struct.unpack_from("<I", sf.body, s.offset + 40)[0] == 0xFA
    sf.set("AUTO REPLAY START", 10000000)
    assert struct.unpack_from("<I", sf.body, sf.find("AUTO REPLAY START").offset + 40)[0] == 0x51
    # and the container is re-signed, so the machine's SHA1 check passes
    again = spb.SettingsFile(sf.to_bytes())
    assert again.signature_ok and again.find("BALLS PER GAME").value == 5


def test_a_write_keeps_the_check_words_upper_bytes():
    """Batman 1.13's saves carry 0x15ff on two settings: only the low byte is the check."""
    b = bytearray(body(ROWS))
    sf = spb.SettingsFile(b)
    off = sf.find("BALLS PER GAME").offset + 40
    struct.pack_into("<I", b, off, 0x1500 | spb.adj_check(3))
    sf = spb.SettingsFile(bytes(b))
    assert sf.find("BALLS PER GAME").check_ok
    sf.set("BALLS PER GAME", 4)
    assert struct.unpack_from("<I", sf.body, off)[0] == 0x1500 | 0xFB


def test_a_write_outside_the_settings_range_or_to_a_caption_it_lacks_is_refused():
    sf = spb.SettingsFile(body(ROWS))
    with pytest.raises(ValueError):
        sf.set("BALLS PER GAME", 11)
    with pytest.raises(KeyError):
        sf.set("NO SUCH SETTING", 1)
    assert sf.to_bytes() == body(ROWS)


def test_carry_moves_settings_by_caption_between_versions():
    old = spb.SettingsFile(spbfile(body([("BALLS PER GAME", 3, 1, 10, 77, 5),
                                         ("MASTER VOLUME SETTING", 7, 0, 63, 11, 99),
                                         ("MUSIC VOLUME", 7, 0, 63, 12, 3)], ver=(1, 58))))
    new = spb.SettingsFile(spbfile(body(ROWS + [("COIN DOOR", 0, 0, 1, 90, 0)])))
    rep = spb.carry(old, new)
    k = spb.caption_key
    # numbered differently on each build - the caption is the key
    assert rep["changed"] == [(k("BALLS PER GAME"), 3, 5)]
    assert rep["out_of_range"] == [(k("MASTER VOLUME SETTING"), 99, 0, 63)]
    assert rep["missing"] == [k("AUTO REPLAY START"), k("COIN DOOR")]
    assert new.find("BALLS PER GAME").value == 5 and new.find("MASTER VOLUME SETTING").value == 7
    assert spb.SettingsFile(new.to_bytes()).signature_ok


def test_what_is_not_a_settings_file_is_refused():
    for bad in (b"", b"hello" * 100, b"SPBF" + b"\x00" * 10,
                spb.MAGIC + struct.pack("<I", 999) + b"\x00" * 20 + body(ROWS)):
        with pytest.raises(ValueError):
            spb.SettingsFile(bad)
    short = bytearray(body(ROWS))
    struct.pack_into("<H", short, spb.OFF_COUNTS + 2, 500)
    with pytest.raises(ValueError):
        spb.SettingsFile(bytes(short))


def test_the_command_line_sets_and_carries(tmp_path, capsys):
    src = tmp_path / "old.SPB"
    src.write_bytes(spbfile(body([("BALLS PER GAME", 3, 1, 10, 77, 5)], ver=(1, 58))))
    dst = tmp_path / "NVM_00000015"
    dst.write_bytes(body(ROWS))
    out = tmp_path / "out"
    assert spb.main(["carry", str(src), str(dst), "--out", str(out)]) == 0
    assert "1 changed" in capsys.readouterr().out
    # a store gets its .crc32 sidecar, the plain zlib CRC32 the card keeps beside it
    assert (tmp_path / "out.crc32").read_bytes() == struct.pack("<I", zlib.crc32(out.read_bytes()))
    assert spb.main(["set", str(src), "BALLS PER GAME", "7", "--out", str(tmp_path / "s.SPB")]) == 0
    assert spb.SettingsFile((tmp_path / "s.SPB").read_bytes()).find("BALLS PER GAME").value == 7
    assert spb.main(["set", str(src), "BALLS PER GAME", "70", "--out", str(tmp_path / "x")]) == 2
    assert "outside" in capsys.readouterr().err
    assert spb.main(["show", str(src)]) == 0


def test_elf_captions_key_each_setting_by_its_caption():
    from tests.test_stern_adjustments import make_elf
    names = spb.elf_captions(make_elf([("AD_INVALID", 0, 0, 0), ("AD_FREE_PLAY", 0, 0, 1)]))
    assert all(len(k) == 20 and k == spb.caption_key(cap) for k, (_n, cap, _w) in names.items())
    assert spb.elf_captions(b"not an elf") == {}


SAVES = os.path.expanduser(r"~/OneDrive/Desktop/usb bacjkup")


@pytest.mark.skipif(not glob.glob(os.path.join(SAVES, "*.SPB")), reason="no real .SPB saves here")
def test_every_real_save_reads_checks_and_writes_back_unchanged():
    for path in glob.glob(os.path.join(SAVES, "*.SPB")):
        data = open(path, "rb").read()
        sf = spb.SettingsFile(data)
        assert sf.signature_ok and sf.to_bytes() == data, path
        assert not sf.bad_checks(), path
        assert sf.find("BALLS PER GAME") is not None, path
