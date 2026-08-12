"""Feedback batch 33 — the scan log, and reading a card back into a .raw file.

No Tk window is built: the methods under test only touch plain attributes, so
duck-typed ``self`` stubs exercise them the way the real window does (same
approach as batch 25's scan-log tests, which these extend).
"""

import os

import pytest

from pinball_decryptor.core import rawdevice
from pinball_decryptor.core.pipeline_base import ReadCardPipeline
from pinball_decryptor.core.rawdevice import (FlashCancelled, FlashError,
                                              read_device_to_image)
from pinball_decryptor.gui.main_window import MainWindow
from pinball_decryptor.gui.read_card_dialog import ReadCardDialog


# ---------------------------------------------------------------------------
# A scan superseded by a newer one used to log NOTHING: no "started" line for
# the scan that took over, and the eventual "finished in N s" timed the scan it
# replaced.  His Write tab restarted its change scan on every tab switch, so
# the log carried one lonely "started" and no finish for minutes.
# ---------------------------------------------------------------------------

class _ScanStub:
    _set_tab_scanning = MainWindow._set_tab_scanning
    _cancel_scan = MainWindow._cancel_scan
    _SCAN_LABELS = MainWindow._SCAN_LABELS

    def __init__(self):
        self.logs = []
        self._scan_reasons = {}
        self._write_preview_scan_id = 0

    def append_log(self, text, level="info"):
        self.logs.append((text, level))

    def _begin_scan_ui(self, tab_key):
        pass

    def _end_scan_ui(self, tab_key):
        pass

    def _stop_scan_spinner(self, tab_key):
        pass

    def _toggle_scan_button(self, tab_key, scanning):
        pass


def _texts(me):
    return [t for t, _lv in me.logs]


def test_superseded_scan_logs_its_replacement_and_the_new_start():
    me = _ScanStub()
    me._scan_reasons["write_preview"] = "write destination changed"
    me._set_tab_scanning("write_preview", True)
    me._scan_reasons["write_preview"] = "Refresh clicked"
    me._set_tab_scanning("write_preview", True)     # supersedes the first
    me._set_tab_scanning("write_preview", False)
    texts = _texts(me)
    assert sum("Write change scan started" in t for t in texts) == 2
    assert sum("scan replaced after" in t for t in texts) == 1
    assert sum("Write change scan finished" in t for t in texts) == 1
    # started(dest changed) → replaced → started(Refresh) → finished
    assert "write destination changed" in texts[0]
    assert "replaced after" in texts[1]
    assert "Refresh clicked" in texts[2]
    assert "finished" in texts[3]


def test_superseding_scan_is_timed_from_its_own_start():
    me = _ScanStub()
    me._set_tab_scanning("write_preview", True)
    first_t0 = me._scan_t0["write_preview"]
    me._set_tab_scanning("write_preview", True)
    assert me._scan_t0["write_preview"] >= first_t0
    me._set_tab_scanning("write_preview", False)
    assert "write_preview" not in me._scan_t0


def test_a_reason_is_never_carried_over_to_a_later_scan():
    """The suppressed start left its reason in _scan_reasons, so the NEXT
    scan's line claimed a cause that belonged to a scan it never logged."""
    me = _ScanStub()
    me._scan_reasons["write_preview"] = "write destination changed"
    me._set_tab_scanning("write_preview", True)
    me._scan_reasons["write_preview"] = "Refresh clicked"
    me._set_tab_scanning("write_preview", True)
    me._set_tab_scanning("write_preview", False)
    me._set_tab_scanning("write_preview", True)      # unrelated later scan
    assert me._scan_reasons == {}
    assert _texts(me)[-1] == "Write change scan started."


def test_first_scan_still_logs_exactly_one_pair():
    me = _ScanStub()
    me._set_tab_scanning("write_preview", True)
    me._set_tab_scanning("write_preview", False)
    texts = _texts(me)
    assert len(texts) == 2
    assert "started" in texts[0] and "finished" in texts[1]
    assert not any("replaced" in t for t in texts)


def test_a_cancel_between_scans_still_reads_as_a_cancel():
    """The Cancel button clears the stamp itself (batch 25), so a restart
    after one is a plain start, not a "replaced"."""
    me = _ScanStub()
    me._set_tab_scanning("write_preview", True)
    me._cancel_scan("write_preview")
    me._set_tab_scanning("write_preview", True)
    me._set_tab_scanning("write_preview", False)
    texts = _texts(me)
    assert sum("cancelled after" in t for t in texts) == 1
    assert not any("replaced after" in t for t in texts)
    assert sum("started" in t for t in texts) == 2


# ---------------------------------------------------------------------------
# Reading a card into a .raw image (the inverse of the flash).
# ---------------------------------------------------------------------------

def _fake_card(tmp_path, size=64 * 1024, fill=b"\xa5"):
    card = tmp_path / "card.bin"
    card.write_bytes(fill * size)
    return str(card)


def test_read_copies_every_byte_of_the_card(tmp_path):
    card = _fake_card(tmp_path)
    out = str(tmp_path / "dump" / "card.raw")
    n = read_device_to_image(card, out)
    assert n == os.path.getsize(card)
    with open(out, "rb") as f, open(card, "rb") as src:
        assert f.read() == src.read()


def test_read_reports_progress_to_the_end(tmp_path):
    card = _fake_card(tmp_path)
    seen = []
    read_device_to_image(card, str(tmp_path / "out.raw"),
                         progress=lambda d, t, m="": seen.append((d, t)))
    assert seen[-1][0] == seen[-1][1] == os.path.getsize(card)
    assert all(d <= t for d, t in seen)


def test_read_refuses_when_the_destination_has_no_room(tmp_path, monkeypatch):
    card = _fake_card(tmp_path)
    monkeypatch.setattr(
        rawdevice.shutil, "disk_usage",
        lambda _p: type("U", (), {"free": 1024, "total": 0, "used": 0})())
    with pytest.raises(FlashError) as e:
        read_device_to_image(card, str(tmp_path / "out.raw"))
    assert "free" in str(e.value)
    assert not os.path.exists(str(tmp_path / "out.raw"))


def test_read_refuses_a_card_whose_size_cannot_be_read(tmp_path, monkeypatch):
    monkeypatch.setattr(rawdevice, "device_size", lambda _p: None)
    with pytest.raises(FlashError) as e:
        read_device_to_image(_fake_card(tmp_path), str(tmp_path / "o.raw"))
    assert "size" in str(e.value)


def test_a_cancelled_read_leaves_no_image_behind(tmp_path):
    """A short .raw sitting there would look exactly like a good backup."""
    card = _fake_card(tmp_path, size=64 * 1024 * 1024)
    out = str(tmp_path / "out.raw")
    calls = {"n": 0}

    def _cancel():
        calls["n"] += 1
        return calls["n"] > 1          # let one chunk land, then stop

    with pytest.raises(FlashCancelled):
        read_device_to_image(card, out, cancel=_cancel)
    assert not os.path.exists(out)
    assert not os.path.exists(out + ".part")


def test_the_image_only_appears_once_it_is_complete(tmp_path):
    """The dump is built as <image>.part and renamed at the end."""
    card = _fake_card(tmp_path, size=32 * 1024 * 1024)
    out = str(tmp_path / "out.raw")
    seen = []

    def _progress(done, total, _msg=""):
        if done < total:
            seen.append((os.path.exists(out), os.path.exists(out + ".part")))

    read_device_to_image(card, out, progress=_progress)
    assert seen, "expected at least one mid-read progress tick"
    assert all(not final and part for final, part in seen)
    assert os.path.isfile(out) and not os.path.exists(out + ".part")


# ---------------------------------------------------------------------------
# ReadCardPipeline — the run wrapper the GUI drives.
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self):
        self.logs, self.phases, self.done = [], [], None

    def make(self, device, image):
        return ReadCardPipeline(
            device, image,
            lambda t, l="info": self.logs.append(t),
            self.phases.append,
            lambda *_a, **_k: None,
            lambda ok, msg: setattr(self, "done", (ok, msg)))


def test_pipeline_refuses_a_file_path_as_the_card(tmp_path):
    run = _Run()
    run.make(str(tmp_path / "not-a-device.raw"), str(tmp_path / "o.raw")).run()
    ok, msg = run.done
    assert ok is False
    assert "physical drive" in msg


def test_pipeline_refuses_a_folder_as_the_destination(tmp_path, monkeypatch):
    monkeypatch.setattr("pinball_decryptor.core.rawdevice.is_device_path",
                        lambda p: "PHYSICALDRIVE" in str(p))
    run = _Run()
    run.make(r"\\.\PHYSICALDRIVE9", str(tmp_path)).run()
    ok, msg = run.done
    assert ok is False
    assert "file name" in msg


def test_pipeline_reports_the_saved_size_on_success(tmp_path, monkeypatch):
    card = _fake_card(tmp_path, size=2 * 1024 * 1024)
    out = str(tmp_path / "saved.raw")
    monkeypatch.setattr("pinball_decryptor.core.rawdevice.is_device_path",
                        lambda p: "PHYSICALDRIVE" in str(p))
    monkeypatch.setattr(
        "pinball_decryptor.core.elevated_flash.read_device_with_privileges",
        lambda dev, img, **kw: read_device_to_image(card, img, **kw))
    run = _Run()
    run.make(r"\\.\PHYSICALDRIVE9", out).run()
    ok, msg = run.done
    assert ok is True, msg
    assert out in msg
    assert os.path.getsize(out) == 2 * 1024 * 1024
    assert run.phases == [0, 1, 2]


# ---------------------------------------------------------------------------
# Dialog helpers (pure functions — no Tk).
# ---------------------------------------------------------------------------

class _Drive:
    def __init__(self, model="Generic MassStorageClass", size=7864320000,
                 mount_label=""):
        self.model = model
        self.size_bytes = size
        self.mount_label = mount_label


def test_default_image_name_says_which_card_it_came_off():
    from pinball_decryptor.gui.read_card_dialog import _default_image_name
    assert _default_image_name(_Drive(), "SD card") == \
        "Generic-MassStorageClass-8GB.raw"
    assert _default_image_name(None, "SD card") == "SD-card.raw"


def test_saving_onto_the_card_being_read_is_refused(monkeypatch):
    monkeypatch.setattr("pinball_decryptor.gui.read_card_dialog.sys.platform",
                        "win32")
    drive = _Drive(mount_label="E: F:")
    assert ReadCardDialog._destination_is_on(drive, r"E:\backups")
    assert ReadCardDialog._destination_is_on(drive, r"f:\x\y")
    assert not ReadCardDialog._destination_is_on(drive, r"D:\backups")
    assert not ReadCardDialog._destination_is_on(_Drive(), r"D:\backups")
