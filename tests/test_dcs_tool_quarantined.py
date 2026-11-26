"""PAD-1391: antivirus programs flag the bundled DCSExplorer.exe /
DCSEncoder.exe (Norton: "Trojan.Gen.MBT") and quarantine or block them.
PAD then has to say why DCS sound is missing instead of going quiet:
the Williams extract used to treat a DCS game as pre-DCS and write no
sounds without a word, and the Cactus Canyon repack dropped the user's
sound edits with no warning.
"""
import hashlib
import os
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.williams import dcs_decode
from pinball_decryptor.plugins.cgc import cc_dcs

VENDOR = os.path.join(os.path.dirname(dcs_decode.__file__), "vendor")

# mjrgh/DCSExplorer v1.1 release assets, as published upstream.
UPSTREAM_V1_1 = {
    "DCSExplorer.exe":
        "2a62a42fb180ce73912852f52c7de173c8644650e3858132ad0ab3f00cfc22ee",
    "DCSEncoder.exe":
        "79028d8708550fe7f8c3d33a0529b6bf2b728eb3656f33f2c61cbb3f09651af1",
}


@pytest.fixture
def fresh_state(monkeypatch):
    monkeypatch.setattr(dcs_decode, "_dcs_explorer_path", None)
    monkeypatch.setattr(dcs_decode, "_dcs_encoder_path", None)
    monkeypatch.setattr(dcs_decode, "_tool_problem", None)
    monkeypatch.setattr(dcs_decode, "_is_dcs_cache", {})


def _av_error():
    e = OSError(22, "Operation did not complete successfully because the "
                    "file contains a virus or potentially unwanted software")
    e.winerror = 225
    return e


@pytest.mark.parametrize("name", sorted(UPSTREAM_V1_1))
def test_fetched_tools_are_the_upstream_release(name):
    # What the reply to the user rests on: PAD fetches the upstream
    # v1.1 file unchanged, and no longer ships a copy (PAD-1606).
    from pinball_decryptor.core import payloads
    p = payloads.HOST_PAYLOADS[name[:-4]]
    assert p.sha256 == UPSTREAM_V1_1[name]
    assert p.url == ("https://github.com/mjrgh/DCSExplorer/releases/"
                     "download/v1.1/" + name)
    assert not os.path.exists(os.path.join(VENDOR, name))


def test_missing_message_names_the_antivirus(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    msg = dcs_decode.missing_tool_message("DCSExplorer")
    assert "DCSExplorer.exe is not on this PC" in msg
    assert "antivirus" in msg and "restart PAD" in msg
    assert dcs_decode.tool_folder() in msg


@pytest.mark.parametrize('platform, missing', [
    ('win32', 'is not on this PC'), ('linux', 'is not installed'), ('darwin', 'is not installed')])
def test_launch_error_messages(monkeypatch, platform, missing):
    monkeypatch.setattr(sys, 'platform', platform)
    assert "antivirus blocked DCSEncoder.exe" in \
        dcs_decode.launch_error_message("DCSEncoder", _av_error())
    assert missing in dcs_decode.launch_error_message(
        "DCSExplorer", FileNotFoundError(2, "gone"))
    assert "failed to launch: boom" in dcs_decode.launch_error_message(
        "DCSExplorer", OSError("boom"))


@pytest.mark.parametrize('platform, missing', [
    ('win32', 'is not on this PC'), ('linux', 'is not installed'), ('darwin', 'is not installed')])
def test_tool_problem_when_missing(fresh_state, monkeypatch, platform, missing):
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(dcs_decode, "_dcs_explorer_path", "")
    assert missing in dcs_decode.tool_problem()
    r = dcs_decode.extract_dcs("x.zip", "out")
    assert not r.is_dcs and r.message.startswith("DCS audio skipped: ")


def test_probe_blocked_records_why(fresh_state, monkeypatch, tmp_path):
    z = tmp_path / "afm.zip"
    z.write_bytes(b"PK")
    monkeypatch.setattr(dcs_decode, "_dcs_explorer_path", "DCSExplorer.exe")

    def blocked(*a, **k):
        raise _av_error()
    monkeypatch.setattr(subprocess, "run", blocked)
    assert dcs_decode.is_dcs_rom(str(z)) is False
    assert "antivirus blocked DCSExplorer.exe" in dcs_decode.tool_problem()


def test_tool_problem_none_when_present(fresh_state, monkeypatch):
    monkeypatch.setattr(dcs_decode, "_dcs_explorer_path", "DCSExplorer.exe")
    assert dcs_decode.tool_problem() is None


def _cc_tree(tmp_path):
    rom = tmp_path / "rom"
    rom.mkdir()
    for n in ("s2.rom", "s3.rom"):
        (rom / n).write_bytes(b"\0" * 16)
    streams = tmp_path / "dcs_audio"
    streams.mkdir()
    (streams / "st_00001234.wav").write_bytes(b"RIFF")
    return str(rom), str(streams)


@pytest.mark.parametrize("gone", ["DCSExplorer", "DCSEncoder"])
def test_cc_repack_refuses_out_loud_when_a_tool_is_gone(
        fresh_state, monkeypatch, tmp_path, gone):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(dcs_decode, "_dcs_explorer_path",
                        "" if gone == "DCSExplorer" else "DCSExplorer.exe")
    monkeypatch.setattr(dcs_decode, "_dcs_encoder_path",
                        "" if gone == "DCSEncoder" else "DCSEncoder.exe")
    rom, streams = _cc_tree(tmp_path)
    with pytest.raises(cc_dcs.DcsRepackError, match=f"{gone}.exe is not on this PC"):
        cc_dcs.repack(rom, streams, rom)


def test_cc_repack_nothing_to_write_stays_quiet(fresh_state, monkeypatch,
                                                tmp_path):
    monkeypatch.setattr(dcs_decode, "_dcs_explorer_path", "")
    rom = tmp_path / "rom"
    rom.mkdir()
    assert cc_dcs.repack(str(rom), str(tmp_path), str(rom)) == {
        "modified_count": 0, "total": 0}


def test_cc_run_blocked_launch_says_antivirus(monkeypatch):
    def blocked(*a, **k):
        raise _av_error()
    monkeypatch.setattr(subprocess, "run", blocked)
    with pytest.raises(cc_dcs.DcsRepackError,
                       match="antivirus blocked DCSEncoder.exe"):
        cc_dcs._run([os.path.join('PAD', 'vendor', 'DCSEncoder.exe'), "--x"], 5)
