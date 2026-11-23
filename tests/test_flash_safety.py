"""PAD-305: a Build + flash wrote a Godzilla image over a 30.8 GB SanDisk USB
stick that sat beside the 31.9 GB SD card it was meant for, then failed its
read-back with "Access is denied ... progress.json".

1. the card is found by WHAT IS ON IT (a Stern boot partition: zImage + a
   stern-*.dtb), not by a model name or the smallest size;
2. with more than one drive, a guess is never pre-selected for an SD card,
   and the erase question says what is on the target and warns when it is
   not a pinball card;
3. a refused rename of progress.json never stops the copy."""

import json
import os

import pytest

from pinball_decryptor.core import drives as D
from pinball_decryptor.core import elevated_flash as EF


def _drive(path, model, gb, label=""):
    return D.PhysicalDrive(device_path=path, model=model,
                           size_bytes=int(gb * 1e9), bus_type="USB",
                           mount_label=label)


@pytest.fixture
def desk(tmp_path):
    """David's desk: a SanDisk stick (smaller) with files on it, and the
    card reader holding a Spike 2 card whose boot partition is mounted."""
    stick = tmp_path / "stick"
    stick.mkdir()
    (stick / "lab.fun").write_text("x")
    card = tmp_path / "card"
    card.mkdir()
    (card / "zImage").write_bytes(b"k")
    (card / "stern-spike2.dtb").write_bytes(b"d")
    (card / "System Volume Information").mkdir()
    return (_drive(r"\\.\PHYSICALDRIVE3", "USB SanDisk 3.2Gen1", 30.78, str(stick)),
            _drive(r"\\.\PHYSICALDRIVE4", "NORELSYS 1081CS0", 0),
            _drive(r"\\.\PHYSICALDRIVE5", "NORELSYS 1081CS1", 31.91, str(card)))


def test_the_card_is_found_by_its_boot_partition_not_by_size(desk):
    stick, empty, card = desk
    assert D.holds_stern_boot(card) and not D.holds_stern_boot(stick)
    best, conf, why = D.pick_best_game_ssd(list(desk), prefer="sd_card")
    assert best is card and conf == "high"
    assert "Stern SD card" in why


def test_without_a_card_the_smallest_drive_is_only_a_low_guess(desk):
    stick, empty, _card = desk
    best, conf, _why = D.pick_best_game_ssd([stick, empty], prefer="sd_card")
    assert conf == "low"            # the dialog must not pre-select this


def test_describe_contents_says_what_would_be_erased(desk):
    stick, empty, card = desk
    assert "Stern pinball SD card" in D.describe_contents(card)
    assert D.describe_contents(stick) == "files: lab.fun"
    assert "no volume" in D.describe_contents(empty)


class _Host:
    def post(self, fn, *a):
        fn(*a)


def _dialog():
    from pinball_decryptor.webui.write_dialogs import FlashDialog
    d = FlashDialog.__new__(FlashDialog)
    d.closed = False
    d._enum_id = 1
    d.words = {"target_kind": "sd_card"}
    d.drives, d.selected, d.drive_text = [], None, ""
    d.publish = lambda: None
    return d


def test_the_dialog_preselects_only_the_card_itself(desk):
    stick, empty, card = desk
    dlg = _dialog()
    dlg._apply_drives(1, list(desk), D.pick_best_game_ssd(list(desk),
                                                          prefer="sd_card"))
    assert dlg.selected is card
    # no card: the low guess (the stick) is NOT selected; the user picks
    dlg = _dialog()
    dlg._apply_drives(1, [stick, empty], D.pick_best_game_ssd(
        [stick, empty], prefer="sd_card"))
    assert dlg.selected is None
    assert "pick the SD card yourself" in dlg.drive_text


def test_a_refused_progress_rename_never_stops_the_copy(tmp_path, monkeypatch):
    path = str(tmp_path / "progress.json")
    real = os.replace
    calls = {"n": 0}

    def refuse_always(src, dst):
        calls["n"] += 1
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(EF.os, "replace", refuse_always)
    monkeypatch.setattr(EF.time, "sleep", lambda s: None)
    # a progress tick: dropped, no exception
    assert EF._write_json_atomic(path, {"done": 1}, tries=8,
                                 required=False) is False
    assert calls["n"] == 8
    # the result: retried, then raised (the parent must not guess)
    with pytest.raises(PermissionError):
        EF._write_json_atomic(path, {"ok": True}, tries=5)

    # a rename refused twice (the parent had it open) lands on the third try
    left = {"n": 2}

    def busy_then_free(src, dst):
        if left["n"]:
            left["n"] -= 1
            raise PermissionError(5, "Access is denied")
        return real(src, dst)
    monkeypatch.setattr(EF.os, "replace", busy_then_free)
    assert EF._write_json_atomic(path, {"ok": True}) is True
    assert json.load(open(path)) == {"ok": True}


def test_the_helpers_progress_callback_swallows_a_refused_rename(tmp_path,
                                                                 monkeypatch):
    """run_helper_main's progress callback is called from inside the raw
    copy; whatever the rename does, the copy must carry on to its result."""
    ipc = tmp_path
    (ipc / "job.json").write_text(json.dumps(
        {"image": "img", "device": "dev", "verify": True}))

    def fake_flash(image, device, log, progress, cancel, verify,
                   on_verify_start):
        for i in range(5):
            progress(i, 4)               # every tick refused below
        return 1234
    monkeypatch.setattr(EF, "flash_image_to_device", fake_flash)
    real = os.replace

    def refuse_progress(src, dst):
        if dst.endswith("progress.json"):
            raise PermissionError(5, "Access is denied")
        return real(src, dst)
    monkeypatch.setattr(EF.os, "replace", refuse_progress)
    monkeypatch.setattr(EF.time, "sleep", lambda s: None)
    assert EF.run_helper_main(["--flash-helper", str(ipc)]) == 0
    assert json.load(open(ipc / "result.json")) == {"ok": True,
                                                     "written": 1234}


def test_the_windows_disk_is_never_preselected(desk, monkeypatch):
    """PAD-1514: no card in the reader, and the only drive listed is the
    PC's own disk (C:): nothing is pre-selected, the user picks."""
    from pinball_decryptor.webui import write_dialogs as wd
    monkeypatch.setattr(wd.sys, "platform", "win32")
    monkeypatch.setenv("SystemDrive", "C:")
    own = D.PhysicalDrive(device_path=r"\.\PHYSICALDRIVE2",
                          model="GIGABYTE AG514K2TB", size_bytes=int(2e12),
                          bus_type="NVMe", mount_label="C:")
    dlg = _dialog()
    dlg.words = {"target_kind": "sd_card", "noun": "SD card"}
    dlg._apply_drives(1, [own], (own, "low", "the only drive"))
    assert dlg.selected is None
    assert "Windows disk" in dlg.drive_text
    # a card beside it is still picked
    _stick, _empty, card = desk
    dlg = _dialog()
    dlg._apply_drives(1, [card], (card, "high", "a Stern SD card"))
    assert dlg.selected is card
