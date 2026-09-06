"""
Tests for tools/spike3_otp_probe.sh - the read-only on-board OTP / secure-boot
probe you run on a real Spike 3 board.

No hardware needed: the script takes canned command output through its
SPIKE3_FAKE_* test hooks, so we can exercise all of its parsing here. The one
thing that actually matters - that the key the probe reports is byte-for-byte
the keyfile luks_otp expects - is cross-checked against luks_otp itself.

Skipped automatically if no POSIX `sh` is on PATH (e.g. a bare Windows host).
"""
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import luks_otp  # noqa: E402

PROBE = os.path.join(HERE, "..", "tools", "spike3_otp_probe.sh")
SH = shutil.which("sh") or shutil.which("bash")

pytestmark = pytest.mark.skipif(SH is None, reason="no POSIX sh/bash on PATH")

WORDS = ["0xdeadbeef", "0x00112233", "0x44556677", "0x8899aabb",
         "0xccddeeff", "0x01020304", "0x05060708", "0x090a0b0c"]
# a well-formed GET_CUSTOMER_OTP response: 7 header words, then W0..W7, then end.
RAW = "0x0000002c 0x80000000 0x00030021 0x00000020 0x80000028 " \
      "0x00000000 0x00000008 " + " ".join(WORDS) + " 0x00000000"


def _run(env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    p = subprocess.run([SH, PROBE], capture_output=True, text=True, env=env)
    return p


def test_reported_key_matches_luks_otp():
    """The probe's 64-hex keyfile == luks_otp.otp_words_to_keyfile (big-endian)."""
    expected = luks_otp.otp_words_to_keyfile(WORDS, "big").hex()
    out = _run({"SPIKE3_FAKE_VCMAILBOX": RAW}).stdout
    line = next(l for l in out.splitlines() if "SPIKE3_KEY=" in l)
    reported = line.split("SPIKE3_KEY=", 1)[1].strip()
    assert reported == expected
    assert len(reported) == 64


def test_secure_boot_enforced_verdict():
    out = _run({"SPIKE3_FAKE_VCMAILBOX": RAW,
                "SPIKE3_FAKE_BOOTLOADER_CONFIG": "SIGNED_BOOT=1\nBOOT_ORDER=0xf41"}).stdout
    assert "ENFORCED" in out


def test_secure_boot_not_enforced_verdict():
    out = _run({"SPIKE3_FAKE_VCMAILBOX": RAW,
                "SPIKE3_FAKE_BOOTLOADER_CONFIG": "SIGNED_BOOT=0\nBOOT_ORDER=0xf41"}).stdout
    assert "NOT enforced" in out


def test_customer_key_hash_fallback():
    """With no bootloader_config, a non-zero customer-key-hash row flags enforcement."""
    out = _run({"SPIKE3_FAKE_VCMAILBOX": RAW,
                "SPIKE3_FAKE_OTP_DUMP": "46:00000000\n47:a1b2c3d4\n48:00000000"}).stdout
    assert "customer key hash IS fused" in out
    assert "47:a1b2c3d4" in out


def test_malformed_framing_refuses():
    """Fewer than 8 words -> the probe must refuse rather than emit a short key."""
    bad = " ".join(RAW.split()[:-4])  # drop the tail so only 6 OTP words remain
    p = _run({"SPIKE3_FAKE_VCMAILBOX": bad})
    assert "WARNING" in p.stdout
    assert "SPIKE3_KEY=" not in p.stdout


def test_no_vcmailbox_exits_nonzero():
    # No fake and no vcmailbox binary (any non-Pi host) -> cannot read the key.
    p = _run({"SPIKE3_FAKE_VCMAILBOX": ""})
    assert p.returncode != 0
    assert "SPIKE3_KEY=" not in p.stdout
