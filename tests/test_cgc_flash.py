"""CGC in-app flash: the Write tab can write a built installer .img straight
onto a card / USB drive (so users don't need Etcher / Rufus).

Reuses the generic ``core.rawdevice.flash_image_to_device`` (the same one Stern
flashes through); these tests cover the CGC wiring: the capability is on, the
manufacturer builds the pipeline, and the pipeline drives Check/Write/Flush to a
successful done with the image bytes landed on a backing 'device' file.
"""
import pinball_decryptor.plugins.cgc.pipeline as cgc_pl
from pinball_decryptor.plugins.cgc.manufacturer import CGCManufacturer
from pinball_decryptor.plugins.cgc.pipeline import FlashImagePipeline


def _pattern(n):
    return bytes((i * 37 + 11) & 0xFF for i in range(n))


def test_cgc_advertises_flash_and_builds_pipeline():
    mfr = CGCManufacturer()
    assert mfr.capabilities.flash_image is True
    assert mfr.flash_phases == ("Check card", "Write image", "Flush")
    pipe = mfr.make_flash_pipeline(
        "x.img", r"\\.\PHYSICALDRIVE9",
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None, done_cb=lambda *a, **k: None)
    assert isinstance(pipe, FlashImagePipeline)


def test_cgc_flash_pipeline_success_against_backing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cgc_pl, "is_device_path", lambda _p: True)
    img_bytes = _pattern(6000)
    img = tmp_path / "AttackFromMars.img"
    img.write_bytes(img_bytes)
    card = tmp_path / "card.dev"
    card.write_bytes(b"\xFF" * 32768)

    phases, results = [], []
    FlashImagePipeline(
        str(img), str(card),
        log_cb=lambda *a, **k: None,
        phase_cb=lambda i: phases.append(i),
        progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: results.append((ok, msg))).run()

    assert results and results[0][0] is True
    assert "Flashed" in results[0][1]
    assert phases == [0, 1, 2]                     # Check / Write / Flush
    assert card.read_bytes()[:6000] == img_bytes


def test_cgc_flash_pipeline_rejects_missing_image(monkeypatch):
    monkeypatch.setattr(cgc_pl, "is_device_path", lambda _p: True)
    errs = []
    FlashImagePipeline(
        "C:/nope.img", r"\\.\PHYSICALDRIVE9",
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: errs.append((ok, msg))).run()
    assert errs and errs[0][0] is False
    assert "not found" in errs[0][1].lower()


def test_cgc_flash_pipeline_size_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(cgc_pl, "is_device_path", lambda _p: True)
    img = tmp_path / "big.img"
    img.write_bytes(b"\x01" * 40000)
    card = tmp_path / "small.dev"
    card.write_bytes(b"\x00" * 8192)
    errs = []
    FlashImagePipeline(
        str(img), str(card),
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: errs.append((ok, msg))).run()
    assert errs and errs[0][0] is False
    assert "larger than the card" in errs[0][1]


def test_cgc_flash_pipeline_rejects_file_path_as_device():
    # Without the is_device_path patch a plain file path is refused (so we never
    # dd onto a regular file by mistake).
    errs = []
    FlashImagePipeline(
        "some.img", "some.img",
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: errs.append((ok, msg))).run()
    assert errs and errs[0][0] is False
    assert "physical drive" in errs[0][1].lower()
