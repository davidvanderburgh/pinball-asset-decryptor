"""PAD-659 - a disk tool's backup of a card, picked where a card image goes.

Level_up mirrored a Spike 2 card with Macrium Reflect and picked the
``.mrimgx`` on Emulate: the run failed with the rig's "no MBR signature - not a
card image?" deep in the log, and Extract said only "Not recognized as Stern
Pinball".  The file is named for what it is now, and what to use instead, on
both tabs and in the Stern Detect refusals.
"""

import os

import pytest

from pinball_decryptor.core import backup_image as B
from pinball_decryptor.plugins.stern import pipeline as stern_pipeline
from pinball_decryptor.webui import emulate_rig
from tests.test_webui_emulate import _lines, _patch, _svc, _wait
from tests.test_webui_extract import _settle
from tests.webui_harness import web_app


# ---------------------------------------------------------------------------
# what a file is
# ---------------------------------------------------------------------------

_NOISE = bytes(range(7, 71))     # no container's magic; fixed, for xdist


@pytest.mark.parametrize("name,head,kind", [
    ("F44390DA22EE866C-00-00.mrimgx", _NOISE, "a Macrium Reflect backup"),
    ("card.MRIMG", _NOISE, "a Macrium Reflect backup"),
    ("card.tibx", _NOISE, "an Acronis backup"),
    ("card.img", b"vhdxfile" + bytes(56), "a VHDX virtual disk"),
    ("card.raw", b"PK\x03\x04" + bytes(60), "a zip archive"),
    ("card.img", b"7z\xbc\xaf\x27\x1c" + bytes(58), "a 7-Zip archive"),
    ("card.img.gz", b"\x1f\x8b\x08" + bytes(61), "a gzip-compressed file"),
    ("card.img.xz", b"\xfd7zXZ\x00" + bytes(58), "an xz-compressed file"),
])
def test_backup_kind_names_the_container(tmp_path, name, head, kind):
    p = tmp_path / name
    p.write_bytes(head)
    assert B.backup_kind(str(p)) == kind


def test_a_card_image_is_never_named(tmp_path):
    mbr = bytearray(4096)
    mbr[510:512] = b"\x55\xaa"
    for name, data in (("card.raw", bytes(mbr)), ("blank.img", bytes(4096)),
                       ("card.bin", os.urandom(4096))):
        p = tmp_path / name
        p.write_bytes(data)
        assert B.backup_kind(str(p)) == ""
        assert B.reason(str(p)) == ""


def test_missing_files_and_devices_are_never_named(tmp_path):
    assert B.reason(str(tmp_path / "gone.img")) == ""
    assert B.reason(r"\\.\PHYSICALDRIVE2") == ""
    assert B.reason("") == ""


def test_reason_says_what_it_is_and_what_to_use(tmp_path):
    p = tmp_path / "F44390DA22EE866C-00-00.mrimgx"
    p.write_bytes(os.urandom(64))
    why = B.reason(str(p))
    assert why.startswith("F44390DA22EE866C-00-00.mrimgx is a Macrium "
                          "Reflect backup, not a card image")
    assert "From SD card" in why and "Save card as image" in why
    z = tmp_path / "card.zip"
    z.write_bytes(b"PK\x03\x04" + bytes(60))
    assert "Unpack it first" in B.reason(str(z))


# ---------------------------------------------------------------------------
# the Stern pipelines' Detect refusal
# ---------------------------------------------------------------------------

def test_stern_detect_refusal_names_the_backup(tmp_path):
    p = tmp_path / "card.mrimgx"
    p.write_bytes(os.urandom(64))
    assert "Macrium Reflect backup" in stern_pipeline._not_a_card(str(p), "x")
    plain = tmp_path / "card.img"
    plain.write_bytes(bytes(64))
    assert stern_pipeline._not_a_card(str(plain), "x") == "x"


# ---------------------------------------------------------------------------
# Extract: the badge
# ---------------------------------------------------------------------------

def test_extract_badge_names_the_backup(tmp_path, monkeypatch):
    f = tmp_path / "F44390DA22EE866C-00-00.mrimgx"
    f.write_bytes(os.urandom(256))
    with web_app(tmp_path, mfr="stern") as w:
        for m in w.window.manufacturers:
            monkeypatch.setattr(m, "detect", lambda p: None)
        w.call("ui.set", "extract", "input", str(f))
        _settle(w)
        badge = w.state("extract")["badge"]
        assert badge["kind"] == "warn" and not badge["switch"]
        assert "is a Macrium Reflect backup, not a card image" in badge["text"]


def test_extract_badge_unchanged_for_an_unknown_file(tmp_path, monkeypatch):
    f = tmp_path / "some.img"
    f.write_bytes(bytes(256))
    with web_app(tmp_path, mfr="stern") as w:
        stern = w.window.current_mfr
        for m in w.window.manufacturers:
            monkeypatch.setattr(m, "detect", lambda p: None)
        w.call("ui.set", "extract", "input", str(f))
        _settle(w)
        assert w.state("extract")["badge"]["text"] == \
            "Not recognized as %s" % stern.display


# ---------------------------------------------------------------------------
# Emulate: said at the pick, refused at Start
# ---------------------------------------------------------------------------

@pytest.fixture
def rig_on(monkeypatch):
    monkeypatch.setattr(emulate_rig, "rig_available", lambda: True)


def test_emulate_pick_says_it_and_start_refuses(tmp_path, monkeypatch, rig_on):
    card = tmp_path / "F44390DA22EE866C-00-00.mrimgx"
    card.write_bytes(os.urandom(512))
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        _wait(w, lambda: bool(w.state("emulate").get("not_card")))
        st = w.state("emulate")
        assert "is a Macrium Reflect backup" in st["not_card"]
        assert st["game"] is None       # no title read off the file name
        assert any("Macrium Reflect backup" in ln for ln in _lines(w))
        w.call("emulate.toggle")
        w.drain()
        assert "Macrium Reflect backup" in svc.last_refusal
        assert not any("watch.sh" in " ".join(c) for c in rec.calls)
        assert svc._proc is None and not svc._starting
        # a real card picked after it clears the note
        good = tmp_path / "godzilla_le-1_16_0.Release.8G.sdcard.raw"
        good.write_bytes(bytes(512))
        w.run(lambda: w.window.emulate_card_var.set(str(good)))
        w.drain()
        assert w.state("emulate")["not_card"] == ""
        assert svc._backup == ""


def test_emulate_a_card_image_starts_as_before(tmp_path, monkeypatch, rig_on):
    card = tmp_path / "godzilla_le-1_16_0.Release.8G.sdcard.raw"
    card.write_bytes(bytes(512))
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        w.drain()
        assert w.state("emulate")["not_card"] == ""
        w.call("emulate.toggle")
        _wait(w, lambda: any("watch.sh" in " ".join(c) for c in rec.calls))
        _wait(w, lambda: svc._proc is None and not svc._starting)


# ---------------------------------------------------------------------------
# Emulate: a file that is no card image at all (PAD-659, D:\stern-spike2.dtb)
# ---------------------------------------------------------------------------

def _mbr():
    b = bytearray(4096)
    b[510:512] = b"\x55\xaa"
    return bytes(b)


def test_not_a_card_names_a_boot_partition_file(tmp_path):
    dtb = tmp_path / "stern-spike2.dtb"
    dtb.write_bytes(b"\xd0\x0d\xfe\xed" + bytes(1000))
    zimg = tmp_path / "zImage"
    zimg.write_bytes(bytes(0x24) + b"\x18\x28\x6f\x01" + bytes(1000))
    for p in (dtb, zimg):
        why = B.not_a_card(str(p))
        assert "one of the files on the card's boot partition" in why
        assert "Save card as image" in why
    # named like a card image, still not one
    odd = tmp_path / "card.raw"
    odd.write_bytes(b"\xd0\x0d\xfe\xed" + bytes(1000))
    assert "boot partition" in B.not_a_card(str(odd))


def test_not_a_card_names_a_file_without_a_partition_table(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_bytes(b"hello" * 200)
    assert "has no partition table" in B.not_a_card(str(p))


def test_not_a_card_leaves_card_images_alone(tmp_path):
    for name, data in (("card.raw", _mbr()), ("card.iso", _mbr()),
                       ("copying.raw", bytes(4096)),      # still being written
                       ("card.img", bytes(512)), ("card.bin", b"")):
        p = tmp_path / name
        p.write_bytes(data)
        assert B.not_a_card(str(p)) == "", name
    assert B.not_a_card(str(tmp_path / "gone.dtb")) == ""
    assert B.not_a_card(r"\.\PHYSICALDRIVE1") == ""


def test_not_a_card_still_names_backups(tmp_path):
    p = tmp_path / "card.mrimgx"
    p.write_bytes(_NOISE)
    assert "Macrium Reflect backup" in B.not_a_card(str(p))


def test_emulate_refuses_a_boot_partition_file(tmp_path, monkeypatch, rig_on):
    card = tmp_path / "stern-spike2.dtb"
    card.write_bytes(b"\xd0\x0d\xfe\xed" + bytes(4000))
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        _wait(w, lambda: bool(w.state("emulate").get("not_card")))
        assert "boot partition" in w.state("emulate")["not_card"]
        w.call("emulate.toggle")
        w.drain()
        assert "boot partition" in svc.last_refusal
        assert not any("watch.sh" in " ".join(c) for c in rec.calls)
