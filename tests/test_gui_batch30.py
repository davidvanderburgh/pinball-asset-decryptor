"""Feedback batch 30 — the Spike 2 tester's build day.

Four things, all reproduced here:

* The build error.  "It's complaining there is no file or directory.  The
  directory does exist (see image) so it must not have the file."  It was the
  other way round: the build folder wasn't there when the write started, the
  copy that failed on it named the FILE, and the machine-render previews
  created the folder before he ever saw the error box (core.build_output).

* The misleading warning.  "I swapped out the stern_logo.png on SDA2 before
  building so it was complaining that my original was modified and I should
  re-extract.  This is a bit misleading I guess?"  Very: the Partitions tab's
  own Replace moved the image's mtime, and ``/usr/local/spike/SternLogo.png``
  is not a file any asset was extracted from (core.card_edits +
  core.extract_source).

* "There is no indicator if the file is original or has been changed.  This
  could make it more difficult for deeper and more complex changes to keep
  track of all changes."  A Changed column, filled from the per-image journal.

* "Any chance of putting in a filter? All/Changed/Unchanged" and "No preview
  for images.  Would it be possible to preview common formats such as images?
  Not sure what else might fit, maybe fonts?"

The tree/filter tests run the Partitions tab's own methods
(``webui/tabs/partitions.py``) on duck-typed stubs, with no window.  Show:
Changed listing only the replaced files under their folders, and Show:
Unchanged leaving them out, are driven end to end in test_webui_partitions.py
(test_replace_same_size_journals_and_marks).
"""

import io
import os

import pytest

from pinball_decryptor.core import (build_output, card_edits, card_paths,
                                    extract_source, image)
from pinball_decryptor.webui.tabs.partitions import PartitionsTab

LOGO = "/usr/local/spike/SternLogo.png"
CLIP = "/godzilla_pro/assets/lcd/attract.asset"


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


@pytest.fixture(autouse=True)
def _isolated_journal(tmp_path, monkeypatch):
    """Every test gets its own card_edits.json (never the real one)."""
    monkeypatch.setattr(card_edits, "CARD_EDITS_FILE",
                        str(tmp_path / "card_edits.json"))


def _image(path, data=b"\x00" * 4096):
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def _touch_later(path, seconds=120):
    """Move *path*'s mtime forward the way a real write would."""
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + seconds))


# ---------------------------------------------------------------------------
# The build error: "there is no file or directory ... the directory does exist"
# ---------------------------------------------------------------------------

def test_missing_build_folder_is_created(tmp_path):
    out = tmp_path / "project" / "build" / "card-modified.raw"
    assert not out.parent.exists()
    assert build_output.ensure_dir_for(str(out)) == ""
    assert out.parent.is_dir()


def test_existing_build_folder_is_left_alone(tmp_path):
    d = tmp_path / "build"
    d.mkdir()
    keep = d / "previous.raw"
    keep.write_bytes(b"x")
    assert build_output.ensure_dir_for(str(d / "card-modified.raw")) == ""
    assert keep.read_bytes() == b"x"


def test_build_folder_blocked_by_a_file_explains_itself(tmp_path):
    blocker = tmp_path / "build"
    blocker.write_bytes(b"not a folder")
    err = build_output.ensure_dir_for(str(blocker / "card-modified.raw"))
    # Names the FOLDER and what's wrong with it — the old failure named the
    # build file and an errno, which read as a missing card image.
    assert "build" in err and "not a folder" in err
    assert "Errno" not in err


def test_no_destination_is_reported_not_crashed():
    assert build_output.ensure_dir_for("") != ""


def test_write_image_refuses_a_bad_destination_before_doing_the_work(tmp_path,
                                                                    monkeypatch):
    """The engine checks the destination up front — the copy it used to fail on
    runs on a background thread whose error only surfaced at the join, ~90 s
    in."""
    from pinball_decryptor.plugins.stern import engine
    called = []
    monkeypatch.setattr(engine, "_linux_partitions",
                        lambda *a, **k: called.append("compute") or [])
    src = _image(tmp_path / "card.raw")
    blocker = tmp_path / "build"
    blocker.write_bytes(b"not a folder")
    with pytest.raises(OSError) as e:
        engine.write_image(src, str(tmp_path), str(blocker / "out.raw"))
    assert "not a folder" in str(e.value)
    assert not called                      # nothing was computed or copied


# ---------------------------------------------------------------------------
# The per-image journal of PAD's own card edits
# ---------------------------------------------------------------------------

def test_journal_records_a_replace_and_its_sizes(tmp_path):
    img = _image(tmp_path / "card.raw")
    card_edits.record_replace(img, 1, LOGO, 166_000, 192_498,
                              str(tmp_path / "mylogo.png"))
    assert list(card_edits.replaced(img)) == [LOGO]
    (e,) = card_edits.edits_for(img)
    assert (e["old_size"], e["new_size"], e["partition"]) == (166_000, 192_498, 1)
    assert e["source"].endswith("mylogo.png") and e["when"]
    assert LOGO in card_edits.describe(img)


def test_journal_is_per_partition_and_per_image(tmp_path):
    a = _image(tmp_path / "a.raw")
    b = _image(tmp_path / "b.raw")
    card_edits.record_replace(a, 1, LOGO, 1, 2)
    assert list(card_edits.replaced(a, partition=1)) == [LOGO]
    assert card_edits.replaced(a, partition=2) == {}
    assert card_edits.replaced(b) == {}          # another card, another journal


def test_journal_signature_tracks_the_image_it_stamped(tmp_path):
    img = _image(tmp_path / "card.raw")
    assert card_edits.signature_current(img) is False   # nothing recorded yet
    card_edits.record_replace(img, 1, LOGO, 1, 2)
    assert card_edits.signature_current(img) is True
    _touch_later(img)                    # something ELSE changed the image
    assert card_edits.signature_current(img) is False


def test_corrupt_journal_reports_nothing(tmp_path, monkeypatch):
    with open(card_edits.CARD_EDITS_FILE, "w", encoding="utf-8") as f:
        f.write("{ not json")
    img = _image(tmp_path / "card.raw")
    assert card_edits.edits_for(img) == []
    assert card_edits.signature_current(img) is False


# ---------------------------------------------------------------------------
# "it was complaining that my original was modified and I should re-extract"
# ---------------------------------------------------------------------------

def _extract_folder(tmp_path, card_path):
    """An assets folder with a video manifest, sidecar-linked to *card_path*."""
    out = tmp_path / "extract"
    (out / "video").mkdir(parents=True)
    with open(out / "video" / "manifest.txt", "w", encoding="utf-8") as f:
        f.write("# name\tcard_path\n")
        f.write("attract.asset\t%s\n" % CLIP.lstrip("/"))
    extract_source.write_extract_source(str(out), card_path)
    return str(out)


def test_partitions_replace_of_a_non_asset_stops_nagging(tmp_path):
    card = _image(tmp_path / "card.raw")
    assets = _extract_folder(tmp_path, card)
    assert extract_source.stale_source_message(assets) is None
    # The Replace writes into the image: its mtime moves, and PAD records it.
    _touch_later(card)
    card_edits.record_replace(card, 1, LOGO, 166_000, 192_498)
    # SternLogo.png on the OS partition is not where any asset came from, so
    # "re-run Extract to refresh" was wrong advice.
    assert extract_source.stale_source_message(assets) is None


def test_partitions_replace_of_an_extracted_file_still_warns(tmp_path):
    card = _image(tmp_path / "card.raw")
    assets = _extract_folder(tmp_path, card)
    _touch_later(card)
    card_edits.record_replace(card, 2, CLIP, 1_000, 2_000)
    msg = extract_source.stale_source_message(assets)
    assert msg and CLIP in msg and "re-run Extract" in msg


def test_a_sound_bank_replace_still_warns(tmp_path):
    # No manifest lists image.bin by path, but every decoded sound is in it.
    card = _image(tmp_path / "card.raw")
    assets = _extract_folder(tmp_path, card)
    _touch_later(card)
    card_edits.record_replace(card, 2, "/godzilla_pro/image.bin", 1, 2)
    msg = extract_source.stale_source_message(assets)
    assert msg and "image.bin" in msg


def test_a_change_pad_did_not_make_still_warns(tmp_path):
    card = _image(tmp_path / "card.raw")
    assets = _extract_folder(tmp_path, card)
    card_edits.record_replace(card, 1, LOGO, 166_000, 192_498)
    # Now something outside PAD moves the image on top of our own edit.
    _touch_later(card, 300)
    msg = extract_source.stale_source_message(assets)
    assert msg and "has changed on disk" in msg


def test_an_extract_with_no_manifests_still_warns(tmp_path):
    """Nothing to check the swap against — don't suppress on a guess."""
    card = _image(tmp_path / "card.raw")
    out = tmp_path / "old_extract"
    out.mkdir()
    extract_source.write_extract_source(str(out), card)
    _touch_later(card)
    card_edits.record_replace(card, 1, LOGO, 1, 2)
    assert extract_source.stale_source_message(str(out)) is not None


def test_extracted_card_paths_inverts_the_manifests(tmp_path):
    card = _image(tmp_path / "card.raw")
    assets = _extract_folder(tmp_path, card)
    assert card_paths.extracted_card_paths(assets) == {CLIP}
    assert card_paths.is_extract_source(assets, CLIP)
    assert not card_paths.is_extract_source(assets, LOGO)
    # The banks and the game ELF are extract sources no manifest names.
    for name in ("/g/image.bin", "/g/image-sc07.bin", "/g/game_real"):
        assert card_paths.is_extract_source(assets, name)


# ---------------------------------------------------------------------------
# The Changed column + the All / Changed / Unchanged filter
# ---------------------------------------------------------------------------

class _Entry:
    def __init__(self, name, path, is_dir=False, size=0, is_symlink=False):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.is_symlink = is_symlink
        self.link_target = None
        self.inode = 1


class _FakeCard:
    TREE = {
        "/usr/local/spike": [
            _Entry("spike_menu", "/usr/local/spike/spike_menu", is_dir=True),
            _Entry("SternLogo.png", LOGO, size=192_498),
            _Entry("VeraMono.ttf", "/usr/local/spike/VeraMono.ttf", size=48_100),
        ],
    }

    def list_dir(self, _part, path):
        return self.TREE[path]

    def file_size(self, _part, path):
        for entries in self.TREE.values():
            for e in entries:
                if e.path == path:
                    return e.size
        raise FileNotFoundError(path)


def _win(show="All", marks=None, image_path="C:/cards/card.raw"):
    class _Stub:
        pass

    s = _Stub()
    s._card = _FakeCard()
    s._part_index = 1
    s._image_path = image_path
    s._nodes = {}
    s._children = {}
    s._dirs = set()
    s._populated = set()
    s._open = set()
    s._marks = dict(marks or {})
    s.partition_show_var = _Var(show)
    s.log = lambda *a, **k: None
    s.set = lambda **k: None
    return s


def test_changed_column_marks_the_file_you_replaced():
    s = _win(marks={LOGO: "replaced 2026-08-07"})
    PartitionsTab._populate_dir(s, "", "/usr/local/spike")
    assert s._nodes[LOGO]["changed"] == "replaced 2026-08-07"
    # An untouched file says nothing rather than claiming to be original — PAD
    # can only vouch for the edits it made itself.
    assert s._nodes["/usr/local/spike/VeraMono.ttf"]["changed"] == ""


def test_show_changed_keeps_a_file_that_is_no_longer_on_the_card():
    gone = "/usr/local/spike/OldLogo.png"
    s = _win(show="Changed", marks={gone: "replaced 2026-08-01"})
    PartitionsTab._fill_changed_only(s)
    assert s._nodes[gone]["type"] == "not on the card now"


def test_find_drops_the_filter_so_it_can_reveal_the_hit():
    """A filtered tree doesn't hold every path and never lazy-loads into
    itself, so Find had to be able to get the whole tree back."""
    s = _win(show="Changed", marks={LOGO: "replaced 2026-08-07"})
    applied = []
    s._apply_show = lambda: applied.append(s.partition_show_var.get())
    PartitionsTab._unfilter_for_reveal(s)
    assert s.partition_show_var.get() == "All" and applied == ["All"]
    # Already unfiltered: nothing to rebuild.
    PartitionsTab._unfilter_for_reveal(s)
    assert applied == ["All"]


def test_marks_come_from_the_journal_for_this_image_and_partition(tmp_path):
    img = _image(tmp_path / "card.raw")
    card_edits.record_replace(img, 1, LOGO, 166_000, 192_498)
    card_edits.record_replace(img, 2, CLIP, 1, 2)
    s = _win(image_path=img)
    PartitionsTab._refresh_marks(s)
    assert list(s._marks) == [LOGO]
    assert s._marks[LOGO].startswith("replaced 20")


# ---------------------------------------------------------------------------
# "No preview for images ... maybe fonts?"
# ---------------------------------------------------------------------------

def test_image_bytes_off_the_card_render_without_a_file():
    PIL = pytest.importorskip("PIL")
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (400, 300), (10, 120, 200)).save(buf, "PNG")
    png = image.thumbnail_png_bytes(buf.getvalue(), 200, 200)
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"
    with PILImage.open(io.BytesIO(png)) as out:
        assert max(out.size) <= 200
    # The caption's numbers describe the file on the card, not the thumbnail.
    info = image.detect_image_info_bytes(buf.getvalue(), LOGO)
    assert (info.fmt, info.width, info.height) == ("PNG", 400, 300)


def test_non_image_bytes_do_not_raise():
    assert image.thumbnail_png_bytes(b"not an image at all", 100, 100) is None
    assert image.thumbnail_png_bytes(b"", 100, 100) is None
    assert image.font_sample_png(b"not a font", 100, 100) is None


def _system_ttf():
    """A TrueType file on this host, or None (same probe as
    test_stern_fontrender)."""
    for p in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\verdana.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/Library/Fonts/Arial.ttf"):
        if os.path.isfile(p):
            return p
    return None


@pytest.mark.skipif(_system_ttf() is None, reason="no system TTF found")
def test_a_real_font_renders_a_specimen():
    pytest.importorskip("PIL")
    from PIL import Image as PILImage
    with open(_system_ttf(), "rb") as f:
        data = f.read()
    png = image.font_sample_png(data, 300, 200)
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"
    with PILImage.open(io.BytesIO(png)) as out:
        assert out.width <= 300 and out.height <= 200
        # Glyphs actually landed: the specimen is black on the checkerboard.
        assert out.convert("RGBA").getextrema()[0][0] == 0
