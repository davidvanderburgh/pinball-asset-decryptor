"""PAD-85 — the Compare tab's audio half, after a tester's Extract Both.

"Compare tab doesn't work as it should on audio part.  I've clicked on
'Extract both'.  When finished, I clicked on 'Compare', and PAD tells me
this" — the same sentence he had just acted on.  The report told him to
extract both cards, he used the tab's own button to do exactly that, and the
Sounds section came back word for word identical, because nothing in the
Compare path ever looked at an extract folder.

These tests cover the wiring that closes that loop: the tab works out where
the two cards' extracts are and hands them to the plugin.  The diff itself is
tested in test_audio_compare.py, the report rows in test_stern_compare.py.
"""

import os

import pytest

from pinball_decryptor.core.extract_source import write_extract_source
from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

# Every test here builds a full Tk App() — same tagging as test_gui_smoke, so
# a fast logic-only run deselects them and a headless box skips them.
pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]


def _stern(app, manufacturers_by_key):
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    return app.window


def _card(path, data=b"\x00" * 4096):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def _extract_of(folder, card):
    folder.mkdir(parents=True, exist_ok=True)
    write_extract_source(str(folder), card)
    return str(folder)


def _pump(app, done, limit=10.0):
    """Let the tab's worker + its after()-poll actually run.

    A bare ``update()`` loop spins far too fast for a 120 ms timer to ever
    come due, so the poll that renders the report would never fire."""
    import time
    end = time.time() + limit
    while time.time() < end and not done():
        app.root.update()
        time.sleep(0.02)
    assert done(), "the Compare worker never finished"


def test_extract_both_output_is_where_compare_looks(app, manufacturers_by_key,
                                                    tmp_path):
    """THE TESTER'S EXACT SEQUENCE.  Extract Both drops one sub-folder per
    card into the parent he picked and remembers that parent; Compare has to
    find both of them there, or the Sounds section can only repeat itself."""
    win = _stern(app, manufacturers_by_key)
    a = _card(tmp_path / "cards" / "led_zeppelin_le-1_21_0.raw", b"A" * 4096)
    b = _card(tmp_path / "cards" / "led_zeppelin_le-1_22_0.raw", b"B" * 2048)
    parent = tmp_path / "both"
    out_a = _extract_of(parent / "led_zeppelin_le-1_21_0", a)
    out_b = _extract_of(parent / "led_zeppelin_le-1_22_0", b)
    win.remember_browse_dir("extract_both", str(parent))

    from pinball_decryptor.core import extract_source
    roots = win._compare_extract_roots(a, b)
    assert extract_source.find_extract_for(a, roots) == out_a
    assert extract_source.find_extract_for(b, roots) == out_b


def test_the_extract_tab_and_the_card_s_own_folder_count_too(
        app, manufacturers_by_key, tmp_path):
    """Two extracts run by hand off the Extract tab, and the very common
    "the card lives inside the project extracted from it" layout."""
    win = _stern(app, manufacturers_by_key)
    project = tmp_path / "tmnt-1987-le"
    a = _card(project / "turtles_le-1_59_0.raw", b"A" * 4096)
    out_a = _extract_of(project, a)

    b = _card(tmp_path / "elsewhere" / "turtles_pro-1_59_0.raw", b"B" * 4096)
    out_b = _extract_of(tmp_path / "runs" / "pro", b)
    win.extract_output_var.set(str(tmp_path / "runs" / "pro"))

    from pinball_decryptor.core import extract_source
    roots = win._compare_extract_roots(a, b)
    assert extract_source.find_extract_for(a, roots) == out_a
    assert extract_source.find_extract_for(b, roots) == out_b


def test_no_extract_anywhere_resolves_to_nothing(app, manufacturers_by_key,
                                                 tmp_path):
    """Nothing is guessed at.  A report confidently listing the wrong card's
    sounds would be worse than the honest "extract both, then compare"."""
    win = _stern(app, manufacturers_by_key)
    a = _card(tmp_path / "a.raw", b"A" * 4096)
    b = _card(tmp_path / "b.raw", b"B" * 4096)
    from pinball_decryptor.core import extract_source
    roots = win._compare_extract_roots(a, b)
    assert extract_source.find_extract_for(a, roots) is None
    assert extract_source.find_extract_for(b, roots) is None


def test_compare_hands_the_extracts_to_the_plugin(app, manufacturers_by_key,
                                                  tmp_path, monkeypatch):
    """End to end through the real button handler: whatever the tab resolved
    has to actually reach compare_images, or none of the above matters."""
    win = _stern(app, manufacturers_by_key)
    a = _card(tmp_path / "a.raw", b"A" * 4096)
    b = _card(tmp_path / "b.raw", b"B" * 2048)
    parent = tmp_path / "both"
    out_a = _extract_of(parent / "a", a)
    out_b = _extract_of(parent / "b", b)
    win.remember_browse_dir("extract_both", str(parent))
    win.compare_a_var.set(a)
    win.compare_b_var.set(b)

    seen = {}

    def _fake(path_a, path_b, assets_a=None, assets_b=None):
        seen.update(a=path_a, b=path_b, xa=assets_a, xb=assets_b)
        return [("Sounds", [("Decoded sounds", "549 (unchanged)")])]

    monkeypatch.setattr(win._current_mfr, "compare_images", _fake)
    win._compare_run()
    _pump(app, lambda: win._compare_sections)
    assert seen == {"a": a, "b": b, "xa": out_a, "xb": out_b}
    assert win._compare_sections == [
        ("Sounds", [("Decoded sounds", "549 (unchanged)")])]


def test_a_listed_sound_opens_out_of_the_extract_folder(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """A Sounds row points at a WAV that is ALREADY on disk, so the
    double-click plays it rather than decoding it a second time."""
    win = _stern(app, manufacturers_by_key)
    a = _card(tmp_path / "a.raw", b"A" * 4096)
    b = _card(tmp_path / "b.raw", b"B" * 2048)
    win.compare_a_var.set(a)
    win.compare_b_var.set(b)
    wav = tmp_path / "xb" / "audio" / "idx0107 - Kashmir.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"RIFF....WAVE")

    from pinball_decryptor.plugins.stern.compare import disk_ref
    ref = disk_ref("B", str(wav))
    win._compare_render([("Sounds", [("Changed", "1:"),
                                     ("", "idx0107 - Kashmir.wav", ref)])])

    iid = next(iter(win._compare_refs))
    side, image, back = win._compare_open_target(iid)
    assert (side, image) == ("B", b) and back is ref

    # Played straight out of the extract — no temp copy of a decoded sound.
    # (The read half and the open half are exercised separately: the tab runs
    # the read on a worker thread, which a test driving Tk cannot join.)
    out = tmp_path / "temp-copy"
    out.mkdir()
    assert win._current_mfr.extract_report_file(image, ref, str(out)) == \
        str(wav)
    assert os.listdir(out) == []

    from pinball_decryptor.core import desktop
    opened = []
    monkeypatch.setattr(desktop, "open_path",
                        lambda p, env=None: (opened.append(p), (True, ""))[1])
    win._compare_open_busy = True
    win._compare_open_finished(ref["name"], "B", str(wav), None)
    assert opened == [str(wav)]
    assert os.path.isfile(wav)
