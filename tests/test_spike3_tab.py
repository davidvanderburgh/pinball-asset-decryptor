"""Tests for the Spike 3 OTP-key helper (core.spike3) and its wiring.

Pure-function tests only - no Tk root is created (a new Tk test module fails on
CI at first contact; the panel's logic lives in core.spike3 so the tab can stay
a thin shell).  One integration test runs the real ``luks_otp.py verify``
against the in-repo LUKS2 fixture with its known key, so the whole
argv -> subprocess -> parse chain is exercised without hardware.
"""
import os
import struct
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinball_decryptor.core import spike3
from pinball_decryptor.core.registry import Capabilities

REPO = spike3.repo_root()
FIXTURE = os.path.join(str(REPO), "stern-spike-3", "tests", "fixtures",
                       "luks2_test_header.bin")
KNOWN_KEY = "3031323334353637383961626364656630313233343536373839414243444546"
EXPECTED_MASTER = "32f200324b31d7f381b91d439328b2ab569e2d5cb9d3c37eaf258fd3b8c7c2d9"


# --- key parsing -----------------------------------------------------------

def test_is_valid_key_hex():
    assert spike3.is_valid_key_hex("a" * 64)
    assert spike3.is_valid_key_hex("A" * 64)
    assert not spike3.is_valid_key_hex("a" * 63)
    assert not spike3.is_valid_key_hex("a" * 65)
    assert not spike3.is_valid_key_hex("g" * 64)
    assert not spike3.is_valid_key_hex(None)


def test_parse_key_text_plain_and_newline():
    assert spike3.parse_key_text(KNOWN_KEY) == KNOWN_KEY.lower()
    assert spike3.parse_key_text(KNOWN_KEY + "\n") == KNOWN_KEY.lower()


def test_parse_key_text_uppercases_to_lower():
    up = "AB" * 32
    assert spike3.parse_key_text(up) == up.lower()


def test_parse_key_text_wrapped_or_spaced():
    wrapped = KNOWN_KEY[:32] + "\n" + KNOWN_KEY[32:] + "\n"
    assert spike3.parse_key_text(wrapped) == KNOWN_KEY.lower()
    spaced = "  " + KNOWN_KEY + "  "
    assert spike3.parse_key_text(spaced) == KNOWN_KEY.lower()


def test_parse_key_text_embedded_in_report():
    report = "SPIKE3_KEY=%s\nsome other line\n" % KNOWN_KEY
    assert spike3.parse_key_text(report) == KNOWN_KEY.lower()


def test_parse_key_text_bytes_input():
    assert spike3.parse_key_text(KNOWN_KEY.encode()) == KNOWN_KEY.lower()


def test_parse_key_text_rejects_longer_hex_run():
    # A 128-hex blob is not a keyfile; we must not return a 64-char slice of it.
    assert spike3.parse_key_text("a" * 128) is None


def test_parse_key_text_none_when_absent():
    assert spike3.parse_key_text("no key here at all") is None
    assert spike3.parse_key_text("") is None
    assert spike3.parse_key_text(None) is None


# --- command lines ---------------------------------------------------------

def test_prepare_argv_minimal():
    argv = spike3.prepare_argv("card.raw", "out")
    assert argv[1].endswith("build_extractor_card.py")
    assert argv[2] == "card.raw"
    assert "-o" in argv and argv[argv.index("-o") + 1] == "out"
    assert "--boot-sig" not in argv


def test_prepare_argv_with_boot_sig():
    argv = spike3.prepare_argv("boot.img", "out", boot_sig="boot.sig")
    assert argv[argv.index("--boot-sig") + 1] == "boot.sig"


def test_verify_argv_shape():
    argv = spike3.verify_argv("h.bin", KNOWN_KEY, slot="1", digest="2")
    assert argv[1].endswith("luks_otp.py")
    assert argv[2] == "verify"
    assert argv[3] == "h.bin"
    assert argv[argv.index("--key-hex") + 1] == KNOWN_KEY
    assert argv[argv.index("--slot") + 1] == "1"
    assert argv[argv.index("--digest") + 1] == "2"


def test_decrypt_probe_argv_shape():
    argv = spike3.decrypt_probe_argv("img.raw", "h.bin", 51740675, KNOWN_KEY,
                                     "out.bin", sector=0, count=8)
    assert argv[2] == "decrypt"
    assert argv[argv.index("--part-base-lba") + 1] == "51740675"
    assert argv[argv.index("--count") + 1] == "8"
    assert argv[argv.index("--out") + 1] == "out.bin"


def test_python_exe_is_a_real_interpreter():
    exe = spike3.python_exe()
    assert exe
    assert "python" in os.path.basename(exe).lower() or os.path.exists(exe)


# --- reading the key back --------------------------------------------------

def test_read_key_from_file(tmp_path):
    p = tmp_path / "OTP_KEY.TXT"
    p.write_text(KNOWN_KEY + "\n")
    res = spike3.read_key(str(p))
    assert res.key_hex == KNOWN_KEY.lower()
    assert res.source == "otp_file"


def test_read_key_from_folder(tmp_path):
    (tmp_path / "otp_key.txt").write_text(KNOWN_KEY)   # case-insensitive
    res = spike3.read_key(str(tmp_path))
    assert res.key_hex == KNOWN_KEY.lower()


def test_read_key_folder_without_file(tmp_path):
    res = spike3.read_key(str(tmp_path))
    assert res.key_hex is None
    assert "OTP_KEY.TXT" in res.note


def test_read_key_missing_path():
    res = spike3.read_key(os.path.join(tempfile.gettempdir(), "nope-xyz-123"))
    assert res.key_hex is None


def test_read_key_text_without_key(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("the machine booted fine but I can't find the file")
    res = spike3.read_key(str(p))
    assert res.key_hex is None


def _synthetic_image(tmp_path, key_hex, put_key=True):
    """A tiny MBR image: one partition at LBA 1, 4 sectors, whose LAST sector
    holds the key (the /init raw fallback)."""
    total = 5 * 512
    buf = bytearray(total)
    struct.pack_into("<I", buf, 446 + 8, 1)       # partition start LBA
    struct.pack_into("<I", buf, 446 + 12, 4)      # partition sector count
    buf[510] = 0x55
    buf[511] = 0xAA
    if put_key:
        last_sector_off = 4 * 512                  # absolute LBA 4
        enc = (key_hex + "\n").encode()
        buf[last_sector_off:last_sector_off + len(enc)] = enc
    p = tmp_path / "card.raw"
    p.write_bytes(buf)
    return str(p)


def test_read_key_from_image_last_sector_fallback(tmp_path):
    img = _synthetic_image(tmp_path, KNOWN_KEY, put_key=True)
    res = spike3.read_key_from_image(img)
    assert res.key_hex == KNOWN_KEY.lower()
    assert res.source == "raw_fallback"


def test_read_key_from_image_no_key(tmp_path):
    img = _synthetic_image(tmp_path, KNOWN_KEY, put_key=False)
    res = spike3.read_key_from_image(img)
    assert res.key_hex is None


def test_read_key_from_image_not_an_image(tmp_path):
    p = tmp_path / "junk.bin"
    p.write_bytes(b"\x00" * 4096)                  # no 0x55AA MBR signature
    res = spike3.read_key_from_image(str(p))
    assert res.key_hex is None
    assert "raw SD image" in res.note


# --- LUKS2 headers ---------------------------------------------------------

def test_looks_like_luks2_on_fixture():
    assert os.path.exists(FIXTURE), "fixture header missing"
    assert spike3.looks_like_luks2(FIXTURE, 0) is True


def test_looks_like_luks2_false_on_zeroes(tmp_path):
    p = tmp_path / "z.bin"
    p.write_bytes(b"\x00" * 4096)
    assert spike3.looks_like_luks2(str(p), 0) is False


def test_carve_header_copies_bytes(tmp_path):
    out = tmp_path / "h.bin"
    n = spike3.carve_header(FIXTURE, 0, str(out), sectors=8)
    assert n == 8 * 512
    assert out.read_bytes()[:4] == b"LUKS"


def test_known_partitions_have_games_first():
    assert spike3.KNOWN_PARTITIONS[0].name == "games"
    assert all(p.lba > 0 for p in spike3.KNOWN_PARTITIONS)


# --- verify output parsing -------------------------------------------------

def test_interpret_verify_valid():
    text = "candidate key = ...\nRESULT: VALID  master_key = %s" % EXPECTED_MASTER
    info = spike3.interpret_verify_output(text, 0)
    assert info["valid"] is True
    assert info["master_key"] == EXPECTED_MASTER


def test_interpret_verify_invalid():
    info = spike3.interpret_verify_output("RESULT: INVALID", 2)
    assert info["valid"] is False
    assert info["master_key"] is None


def test_interpret_verify_falls_back_to_rc():
    assert spike3.interpret_verify_output("weird output", 0)["valid"] is True
    assert spike3.interpret_verify_output("weird output", 2)["valid"] is False


def test_secure_boot_hint_both_ways():
    assert "does NOT" in spike3.secure_boot_hint(True)
    assert "DOES enforce" in spike3.secure_boot_hint(False)


# --- capability wiring -----------------------------------------------------

def test_capability_default_off():
    assert Capabilities().spike3_key is False


def _stern():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    return SternManufacturer()


def test_spike3_is_its_own_era_not_a_spike2_tab():
    m = _stern()
    keys = [e[0] for e in m.eras]
    assert "spike3" in keys
    # The other eras must NOT expose the Spike 3 tab (it is not a Spike 2 tab).
    for era in ("spike2", "spike1", "whitestar"):
        m.set_era(era)
        assert m.capabilities.spike3_key is False


def test_spike3_era_enables_only_the_key_tab():
    m = _stern()
    m.set_era("spike3")
    caps = m.capabilities
    assert caps.spike3_key is True
    assert caps.extract is False
    assert caps.write is False
    assert getattr(caps, "emulate", False) is False


def test_spike3_era_pill_is_flagged_beta():
    m = _stern()
    entry = next(e for e in m.eras if e[0] == "spike3")
    assert len(entry) >= 3 and entry[2] == "BETA"


def test_spike3_era_requires_no_prereqs():
    m = _stern()
    m.set_era("spike3")
    assert tuple(m.prerequisites) == ()


# --- one real end-to-end verify (uses the in-repo fixture) -----------------

@pytest.mark.skipif(not os.path.exists(FIXTURE), reason="fixture missing")
def test_verify_real_header_end_to_end():
    argv = spike3.verify_argv(FIXTURE, KNOWN_KEY)
    r = subprocess.run(argv, capture_output=True, text=True)
    info = spike3.interpret_verify_output(r.stdout, r.returncode)
    assert info["valid"] is True
    assert info["master_key"] == EXPECTED_MASTER

    bad = subprocess.run(spike3.verify_argv(FIXTURE, "00" * 32),
                         capture_output=True, text=True)
    assert spike3.interpret_verify_output(bad.stdout, bad.returncode)["valid"] \
        is False
