"""
Tests for the Stern Spike 3 offline LUKS2 verifier/decryptor (tools/luks_otp.py).

These are self-contained and need no hardware and no Stern data:
  * luks_otp's own crypto self-test (PBKDF2 / AES-XTS / AF-split / synthetic LUKS2).
  * An end-to-end verify against a real LUKS2 header that was created by
    `cryptsetup` with Stern-identical parameters and a KNOWN key
    (fixtures/luks2_test_header.bin) -- proving the unlock pipeline recovers the
    exact master key.

Run from this folder:  pytest
(The repo's main suite uses testpaths=tests, so it does not pick these up.)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import luks_otp  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "luks2_test_header.bin")

# fixtures/luks2_test_header.bin was made with:
#   printf '0123456789abcdef0123456789ABCDEF' > known.key   # exactly 32 bytes
#   cryptsetup luksFormat --type luks2 --cipher aes-xts-plain64 --key-size 256 \
#       --pbkdf pbkdf2 --pbkdf-force-iterations 250000 --hash sha256 \
#       --sector-size 512 --batch-mode fix.img known.key
# (Stern-identical params.)  cryptsetup reported this master key:
KNOWN_KEY_HEX = "3031323334353637383961626364656630313233343536373839414243444546"
EXPECTED_MASTER_KEY = "32f200324b31d7f381b91d439328b2ab569e2d5cb9d3c37eaf258fd3b8c7c2d9"


def test_crypto_selftest():
    assert luks_otp.selftest() is True


def test_known_key_verifies_and_recovers_master_key():
    raw = open(FIXTURE, "rb").read()
    hdr = luks_otp.Luks2Header(raw)
    key = bytes.fromhex(KNOWN_KEY_HEX)
    ok, mk = luks_otp.verify_key(hdr, key, raw, "0", "0")
    assert ok is True
    assert mk.hex() == EXPECTED_MASTER_KEY


def test_wrong_key_rejected():
    raw = open(FIXTURE, "rb").read()
    hdr = luks_otp.Luks2Header(raw)
    ok, mk = luks_otp.verify_key(hdr, b"\x00" * 32, raw, "0", "0")
    assert ok is False
    assert mk is None


def test_otp_words_to_keyfile_layout():
    # The Stern keyfile is the 8 customer-OTP words, MSB-first, concatenated to
    # 32 bytes -- the exact output of busybox `xxd -r -p` on the vcmailbox slice.
    words = [0xDEADBEEF, 0x11223344, 0x55667788, 0x99AABBCC,
             0xDDEEFF00, 0x12345678, 0x9ABCDEF0, 0x0F1E2D3C]
    kf = luks_otp.otp_words_to_keyfile(words, word_endian="big")
    assert kf.hex() == "deadbeef112233445566778899aabbccddeeff00123456789abcdef00f1e2d3c"
    assert len(kf) == 32
