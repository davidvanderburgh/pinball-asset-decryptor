"""PAD-1606: PAD no longer ships DCSExplorer.exe / DCSEncoder.exe.

Antivirus programs flag them by mistake, so with them in the installer and
every update a user had to switch his scanner off to update PAD, even if he
never touched a DCS-era Williams game.  Now the first DCS sound job
downloads the exact upstream v1.1 file, pinned by hash, into the payload
cache, and nothing in the install carries it.
"""
import dataclasses
import hashlib
import io
import os
import re
import sys

import pytest

from pinball_decryptor.core import payloads
from pinball_decryptor.plugins.williams import dcs_decode, manufacturer
from pinball_decryptor.plugins.cgc import cc_dcs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISS = os.path.join(ROOT, "installer", "pinball_decryptor.iss")
FAKE = b"MZ pretend DCSExplorer " * 100


@pytest.fixture
def win(monkeypatch, tmp_path):
    """A Windows PC with no DCS tool anywhere, a scratch payload cache and
    a fake network serving *FAKE* as the pinned DCSExplorer.exe."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("PAD_NO_TOOL_DOWNLOAD", raising=False)
    monkeypatch.setenv("PAD_PAYLOAD_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(dcs_decode, "_dcs_explorer_path", None)
    monkeypatch.setattr(dcs_decode, "_dcs_encoder_path", None)
    monkeypatch.setattr(dcs_decode, "_tool_problem", None)
    monkeypatch.setattr(dcs_decode, "_is_dcs_cache", {})
    monkeypatch.setattr(dcs_decode.shutil, "which", lambda name: None)
    host = dict(payloads.HOST_PAYLOADS)
    host["DCSExplorer"] = dataclasses.replace(
        host["DCSExplorer"], sha256=hashlib.sha256(FAKE).hexdigest(),
        size=len(FAKE))
    monkeypatch.setattr(payloads, "HOST_PAYLOADS", host)
    calls = []

    def urlopen(req, timeout):
        calls.append(req.full_url)
        return io.BytesIO(served[0])
    served = [FAKE]
    monkeypatch.setattr(payloads.net, "urlopen", urlopen)
    return calls, served


def test_pinned_upstream_files_not_in_the_wsl_list():
    for tool, size in (("DCSExplorer", 500224), ("DCSEncoder", 3399168)):
        p = payloads.HOST_PAYLOADS[tool]
        assert p.size == size and payloads.is_published(p)
        assert payloads.asset_url(p) == p.url
        assert p.url.startswith("https://github.com/mjrgh/DCSExplorer/"
                                "releases/download/v1.1/")
        # PAYLOADS is what the emulator tabs install into WSL.
        assert tool not in payloads.PAYLOADS
        # ...but the cache prune must keep the download.
        assert p in payloads.current_payloads()


def test_install_and_update_carry_no_dcs_tool():
    vendor = os.path.join(ROOT, "pinball_decryptor", "plugins", "williams",
                          "vendor")
    assert not [n for n in os.listdir(vendor) if n.lower().endswith(".exe")]
    iss = open(ISS, encoding="utf-8").read()
    files = iss.split("[Files]", 1)[1].split("\n[", 1)[0]
    assert "DCSExplorer" not in files and "DCSEncoder" not in files
    gone = iss.split("[InstallDelete]", 1)[1].split("\n[", 1)[0]
    for tool in ("DCSExplorer", "DCSEncoder"):
        row = re.search(r'^Type: files; Name: "\{app\}\\pinball_decryptor'
                        r'\\plugins\\williams\\vendor\\%s\.exe"$' % tool,
                        gone, re.M)
        assert row, tool
    # No carry-over of the old copies into a staged update either.
    from pinball_decryptor.core import update_delta, update_slots
    for mod in (update_delta, update_slots):
        assert "DCSExplorer" not in open(mod.__file__, encoding="utf-8").read()


def test_first_dcs_job_downloads_then_reuses(win):
    calls, _ = win
    said = []
    exe = dcs_decode.find_dcs_explorer(log=said.append)
    assert exe == payloads.cache_path(payloads.HOST_PAYLOADS["DCSExplorer"])
    assert open(exe, "rb").read() == FAKE
    assert calls == [payloads.HOST_PAYLOADS["DCSExplorer"].url]
    assert "downloading the open-source DCS sound tool by mjrgh" in said[0]
    # Next process: found in the cache, no second download.
    dcs_decode._dcs_explorer_path = None
    assert dcs_decode.find_dcs_explorer() == exe and len(calls) == 1


def test_altered_download_is_refused_and_said(win):
    calls, served = win
    served[0] = b"<html>blocked by proxy</html>"
    assert dcs_decode.find_dcs_explorer() is None
    why = dcs_decode.tool_problem()
    assert why.startswith("DCSExplorer.exe could not be downloaded (")
    assert dcs_decode.tool_folder() in why and "restart PAD" in why
    assert not os.listdir(dcs_decode.tool_folder())   # no .part left
    # Negative answer is kept for the process: no retry per ROM.
    assert dcs_decode.find_dcs_explorer() is None and len(calls) == 1
    r = dcs_decode.extract_dcs("afm.zip", "out")
    assert r.message == "DCS audio skipped: " + why


def test_ui_thread_check_never_downloads(win, monkeypatch, tmp_path):
    calls, _ = win
    monkeypatch.setattr(manufacturer, "is_williams_zip", lambda p: True)
    z = tmp_path / "ft_l5.zip"
    z.write_bytes(b"PK")
    m = manufacturer.WilliamsManufacturer() if hasattr(
        manufacturer, "WilliamsManufacturer") else None
    if m is None:
        cls = next(c for c in vars(manufacturer).values()
                   if isinstance(c, type) and "audio_export_supported" in vars(c))
        m = cls.__new__(cls)
    # Not fetched yet: show the audio step, fetch nothing, cache nothing.
    assert m.audio_export_supported(str(z)) is True
    assert calls == [] and dcs_decode._dcs_explorer_path is None
    assert dcs_decode.is_dcs_rom(str(z), fetch=False) is False
    assert dcs_decode._is_dcs_cache == {}


def test_no_download_switch_and_other_platforms(win, monkeypatch):
    calls, _ = win
    monkeypatch.setenv("PAD_NO_TOOL_DOWNLOAD", "1")
    assert dcs_decode.find_dcs_explorer() is None
    monkeypatch.delenv("PAD_NO_TOOL_DOWNLOAD")
    dcs_decode._dcs_explorer_path = None
    monkeypatch.setattr(sys, "platform", "linux")
    assert dcs_decode.find_dcs_explorer() is None
    assert calls == []


def test_cc_repack_fetches_into_its_log(win, monkeypatch, tmp_path):
    calls, _ = win
    rom = tmp_path / "rom"
    rom.mkdir()
    for n in ("s2.rom", "s3.rom"):
        (rom / n).write_bytes(b"\0" * 16)
    streams = tmp_path / "dcs_audio"
    streams.mkdir()
    (streams / "st_00001234.wav").write_bytes(b"RIFF")
    said = []
    # DCSEncoder's pin is the real one, so the fake bytes are refused:
    # the repack refuses out loud with the download's reason.
    with pytest.raises(cc_dcs.DcsRepackError,
                       match="DCSEncoder.exe could not be downloaded"):
        cc_dcs.repack(str(rom), str(streams), str(rom),
                      log_cb=lambda m, level: said.append(m))
    assert len(calls) == 2 and any("DCSEncoder.exe is not on this PC yet"
                                   in m for m in said)
