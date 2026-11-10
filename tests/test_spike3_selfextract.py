"""PAD-1086 - Spike 3 OTP key self-extractor (Method A).

Covers the software-only, user-runnable key flow: parsing the key a user reads
back from the extractor card, verifying it before trusting it, writing/merging
the padkeys.json the extract pipeline consumes, and the card-build wrapper's
orchestration + enforced-board handling. No key material and no real card image
are needed (the real end-to-end build + verify is proven in-session on hardware
the owner has; nothing secret is committed).
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pinball_decryptor.plugins.stern import spike3_selfextract as SX


# --- parse_otp_key_text ----------------------------------------------------
HEX64 = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"


def test_parse_bare_64hex():
    assert SX.parse_otp_key_text(HEX64) == bytes.fromhex(HEX64)


def test_parse_otp_key_txt_with_trailing_newline():
    # what `xxd -p -c 32 /ktmp > OTP_KEY.TXT` writes
    assert SX.parse_otp_key_text(HEX64 + "\n") == bytes.fromhex(HEX64)


def test_parse_spike3_key_line():
    text = "some log\nSPIKE3_KEY=%s\nmore log\n" % HEX64.upper()
    assert SX.parse_otp_key_text(text) == bytes.fromhex(HEX64)


def test_parse_raw_32_bytes():
    raw = bytes.fromhex(HEX64)
    assert SX.parse_otp_key_text(raw) == raw


def test_parse_rejects_short_key():
    with pytest.raises(SX.Spike3SelfExtractError):
        SX.parse_otp_key_text("deadbeef")


def test_parse_rejects_garbage():
    with pytest.raises(SX.Spike3SelfExtractError):
        SX.parse_otp_key_text("no key here at all")


def test_parse_rejects_non_hex_64():
    with pytest.raises(SX.Spike3SelfExtractError):
        SX.parse_otp_key_text("z" * 64)


# --- write_padkeys ---------------------------------------------------------
def test_write_padkeys_new(tmp_path):
    out = str(tmp_path / "padkeys.json")
    SX.write_padkeys(out, bytes.fromhex(HEX64))
    doc = json.loads((tmp_path / "padkeys.json").read_text())
    assert doc["otp_keyfile"] == HEX64


def test_write_padkeys_merges_existing(tmp_path):
    out = tmp_path / "padkeys.json"
    out.write_text(json.dumps({"spk_keyfile": "ab" * 32,
                               "master_keys": {"games": "cd" * 32}}))
    SX.write_padkeys(str(out), bytes.fromhex(HEX64))
    doc = json.loads(out.read_text())
    assert doc["otp_keyfile"] == HEX64
    assert doc["spk_keyfile"] == "ab" * 32          # preserved
    assert doc["master_keys"] == {"games": "cd" * 32}  # preserved


def test_write_padkeys_survives_corrupt_existing(tmp_path):
    out = tmp_path / "padkeys.json"
    out.write_text("{ not json")
    SX.write_padkeys(str(out), bytes.fromhex(HEX64))
    assert json.loads(out.read_text())["otp_keyfile"] == HEX64


# --- ingest_otp_key (verify branch mocked; real verify proven in-session) --
def test_ingest_good_key_writes_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(SX, "verify_otp_key", lambda img, k: True)
    out = str(tmp_path / "padkeys.json")
    res = SX.ingest_otp_key(HEX64, "unused_image.raw", out_path=out)
    assert res.verified
    assert res.key_hex == HEX64
    assert os.path.exists(out)
    assert json.loads(open(out).read())["otp_keyfile"] == HEX64


def test_ingest_bad_key_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(SX, "verify_otp_key", lambda img, k: False)
    out = str(tmp_path / "padkeys.json")
    res = SX.ingest_otp_key(HEX64, "unused_image.raw", out_path=out)
    assert not res.verified
    assert not os.path.exists(out)


def test_ingest_reads_key_from_file(tmp_path, monkeypatch):
    monkeypatch.setattr(SX, "verify_otp_key", lambda img, k: True)
    keyfile = tmp_path / "OTP_KEY.TXT"
    keyfile.write_text(HEX64 + "\n")
    out = str(tmp_path / "padkeys.json")
    res = SX.ingest_otp_key(str(keyfile), "unused_image.raw", out_path=out)
    assert res.verified and os.path.exists(out)


# --- build_extractor_card wrapper (tool mocked) ---------------------------
class _FakeProc:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_build_success(tmp_path, monkeypatch):
    src = tmp_path / "in.raw"
    src.write_bytes(b"\x00")
    out_dir = tmp_path / "card"

    def fake_run(cmd, **kw):
        # the tool would write these; simulate it
        os.makedirs(out_dir, exist_ok=True)
        (out_dir / "boot.img").write_bytes(b"\x00")
        (out_dir / "boot.sig").write_text("sig")
        assert "--no-sig" not in cmd
        return _FakeProc(0, out="built ok")

    monkeypatch.setattr(SX.subprocess, "run", fake_run)
    res = SX.build_extractor_card(str(src), str(out_dir))
    assert os.path.exists(res.boot_img)
    assert res.boot_sig and os.path.exists(res.boot_sig)
    assert "OTP_KEY.TXT" in res.instructions


def test_build_missing_input_raises(tmp_path):
    with pytest.raises(SX.Spike3SelfExtractError):
        SX.build_extractor_card(str(tmp_path / "nope.raw"), str(tmp_path / "o"))


def test_build_no_sig_passes_flag_and_omits_sig(tmp_path, monkeypatch):
    src = tmp_path / "in.raw"
    src.write_bytes(b"\x00")
    out_dir = tmp_path / "card"

    def fake_run(cmd, **kw):
        assert "--no-sig" in cmd
        os.makedirs(out_dir, exist_ok=True)
        (out_dir / "boot.img").write_bytes(b"\x00")
        return _FakeProc(0)

    monkeypatch.setattr(SX.subprocess, "run", fake_run)
    res = SX.build_extractor_card(str(src), str(out_dir), no_sig=True)
    assert res.no_sig and res.boot_sig is None
    assert "DELETE boot.sig" in res.instructions


def test_build_tool_failure_raises(tmp_path, monkeypatch):
    src = tmp_path / "in.raw"
    src.write_bytes(b"\x00")
    monkeypatch.setattr(SX.subprocess, "run",
                        lambda cmd, **kw: _FakeProc(1, err="boom"))
    with pytest.raises(SX.Spike3SelfExtractError):
        SX.build_extractor_card(str(src), str(tmp_path / "o"))


def test_enforced_message_is_honest():
    m = SX.ENFORCED_BOARD_MESSAGE
    assert "secure boot" in m.lower()
    assert "dma" in m.lower()
    assert "fleet-wide" in m.lower()
