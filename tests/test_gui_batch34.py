"""Feedback batch 34 — importing a mod pack into a fresh extract.

A tester exported a mod pack from his old project, extracted the same card into
a new folder and imported the pack there.  Audio came back correct; the Images,
Video and Text tabs all claimed nothing had changed, and stayed that way until
he restarted the app.  Three separate faults, one per symptom:

* every Replace tab shared ONE change-scan bump-counter, so the three scans an
  import kicks off cancelled each other and only the last to start survived;
* the Images tab's background metadata pass rewrote each row's Replacement cell
  without the changed-on-disk mark, wiping the ✓ off rows that had it;
* scene names lived in the per-card library until the (slow) Images scan seeded
  them into the new folder's sidecar, and the Text tab only ever read that
  sidecar — so its Scene dropdown was bare hashes.

Plus the wish-list item that came with them: re-check for updates on a timer,
not only at startup.

No Tk window is built — the methods under test only touch plain attributes, so
duck-typed ``self`` stubs exercise them the way the real window does (the same
approach as batches 25 and 33).
"""

import os

import pytest

from pinball_decryptor.core import checksums, staged_changes, tag_library
from pinball_decryptor.core.extract_source import write_extract_source
from pinball_decryptor.gui.main_window import (UPDATE_INTERVAL_CHOICES,
                                               UPDATE_INTERVAL_DEFAULT,
                                               MainWindow,
                                               normalize_update_interval)


# ---------------------------------------------------------------------------
# Shared doubles
# ---------------------------------------------------------------------------

class _Var:
    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class _Root:
    """Collects ``after`` callbacks instead of running them, so a test can
    interleave two scans exactly the way the event loop does."""

    def __init__(self):
        self.queued = []

    def after(self, _delay, fn=None, *args):
        if fn is not None:
            self.queued.append(lambda: fn(*args))
        return "id"

    def drain(self):
        """Run queued callbacks (including any they queue) to completion."""
        while self.queued:
            self.queued.pop(0)()


class _Slot:
    def __init__(self, rel):
        self.rel_path = rel
        self.info = None
        self.probed = False

    def resolution_str(self):
        return "24×24"

    def format_summary(self):
        return "PNG alpha"


class _SyncThread:
    """threading.Thread stand-in that runs the target inline on start()."""

    def __init__(self, target=None, daemon=None, **_kw):
        self._target = target

    def start(self):
        self._target()


def _extract(tmp_path, name="lz"):
    """A project folder with a two-file baseline; both files are then edited,
    so a change scan must flag exactly both."""
    out = tmp_path / name
    (out / "video").mkdir(parents=True)
    (out / "images").mkdir(parents=True)
    (out / "video" / "attract.mov").write_bytes(b"stock clip")
    (out / "images" / "logo.png").write_bytes(b"stock art")
    checksums.generate_checksums(str(out))
    (out / "video" / "attract.mov").write_bytes(b"my clip")
    (out / "images" / "logo.png").write_bytes(b"my art")
    return str(out)


# ---------------------------------------------------------------------------
# 1. The three Replace tabs' change scans must not cancel each other
# ---------------------------------------------------------------------------

class _ScanStub:
    _start_change_scan = MainWindow._start_change_scan

    def __init__(self, assets_dir):
        self.root = _Root()
        self.write_assets_var = _Var(assets_dir)
        self._change_scan_ids = {}
        self._video_slots = [_Slot("video/attract.mov")]
        self._image_slots = [_Slot("images/logo.png")]
        self._audio_slots = []
        self._video_changed_on_disk = set()
        self._image_changed_on_disk = set()
        self._audio_changed_on_disk = set()
        self.refreshed = []

    def _refresh_video_list(self):
        self.refreshed.append("video")

    def _refresh_image_list(self):
        self.refreshed.append("image")

    def _refresh_audio_list(self):
        self.refreshed.append("audio")


@pytest.fixture
def _sync_threads(monkeypatch):
    import threading
    monkeypatch.setattr(threading, "Thread", _SyncThread)


def test_concurrent_change_scans_all_land(tmp_path, _sync_threads):
    # A mod-pack import re-scans every tab, so each finished slot scan starts
    # its own change scan while the others are still hashing.  With one shared
    # counter the video result was discarded the moment the image scan started
    # and the tab sat at "0 slots changed" until the app was restarted.
    me = _ScanStub(_extract(tmp_path))
    me._start_change_scan("video")
    me._start_change_scan("image")     # starts while video is still in flight
    me.root.drain()
    assert me._video_changed_on_disk == {"video/attract.mov"}
    assert me._image_changed_on_disk == {"images/logo.png"}
    assert sorted(me.refreshed) == ["image", "video"]


def test_rescanning_one_kind_still_supersedes_its_own_earlier_scan(
        tmp_path, _sync_threads):
    # The guard itself has to keep working: two scans of the SAME kind must
    # leave only the newer one's answer.
    me = _ScanStub(_extract(tmp_path))
    me._start_change_scan("video")
    me._start_change_scan("video")
    me.root.drain()
    assert me._video_changed_on_disk == {"video/attract.mov"}
    assert me.refreshed == ["video"]       # the superseded one never refreshed


def test_change_scan_ids_are_per_kind(tmp_path, _sync_threads):
    me = _ScanStub(_extract(tmp_path))
    me._start_change_scan("video")
    me._start_change_scan("image")
    assert me._change_scan_ids == {"video": 1, "image": 1}


# ---------------------------------------------------------------------------
# 2. The Images metadata pass must keep the changed-on-disk mark
# ---------------------------------------------------------------------------

class _Tree:
    def __init__(self, rows):
        self.values = {r: None for r in rows}

    def exists(self, iid):
        return iid in self.values

    def item(self, iid, values=None, **_kw):
        if values is not None:
            self.values[iid] = tuple(values)


class _ImageMetaStub:
    _apply_image_meta = MainWindow._apply_image_meta

    def __init__(self, rel, changed=(), assigned=None):
        self._image_scan_id = 7
        slot = _Slot(rel)
        self._image_slots_by_rel = {rel: slot}
        self._image_assignments = dict(assigned or {})
        self._image_changed_on_disk = set(changed)
        self._image_tree = _Tree([rel])

    def _image_source_label(self, _rel):
        return "File"


REL = "images/led_zeppelin_le/assets/lcd/GameLogo.png"


def _rep_cell(me, rel=REL):
    return me._image_tree.values[rel][-1]


def test_image_meta_keeps_changed_on_disk_mark():
    # The pass runs over every image in the folder (11 819 of them for the
    # tester), so it wiped the mark off the whole list behind him: the tab said
    # "Choose…" — i.e. nothing changed — for the image he had just imported.
    me = _ImageMetaStub(REL, changed={REL})
    me._apply_image_meta(7, REL, object())
    assert _rep_cell(me) == "✓ changed on disk"


def test_image_meta_prefers_the_pending_assignment():
    me = _ImageMetaStub(REL, changed={REL},
                        assigned={REL: os.path.join("W:", "art", "redux.png")})
    me._apply_image_meta(7, REL, object())
    assert _rep_cell(me) == "redux.png"


def test_image_meta_untouched_slot_still_says_choose():
    me = _ImageMetaStub(REL)
    me._apply_image_meta(7, REL, object())
    assert _rep_cell(me) == "Choose…"


def test_image_meta_from_a_stale_scan_is_ignored():
    me = _ImageMetaStub(REL, changed={REL})
    me._apply_image_meta(6, REL, object())
    assert me._image_tree.values[REL] is None


# ---------------------------------------------------------------------------
# 3. Scene names: the library, and the Text tab's own seeding
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_library(tmp_path, monkeypatch):
    """Never touch the real group_tags.json."""
    monkeypatch.setattr(tag_library, "LIBRARY_FILE",
                        str(tmp_path / "settings" / "group_tags.json"))


def _carded(tmp_path, sub, card="led_zeppelin_le-1_22_0.Release.8G.sdcard.raw"):
    """A project folder that knows which card it came from (tag_library scopes
    its entries by that name)."""
    img = tmp_path / card
    if not img.exists():
        img.write_bytes(b"\x00" * 16)
    out = tmp_path / sub
    out.mkdir()
    write_extract_source(str(out), str(img))
    return str(out)


class _SeedStub:
    _seed_names_from_library = MainWindow._seed_names_from_library


def test_seed_names_fills_from_library_and_writes_the_sidecar(tmp_path):
    old = _carded(tmp_path, "redux3")
    tag_library.remember(old, {"rad::a/scene.radium": "Song Select"},
                         {"rad::a/scene.radium"})
    new = _carded(tmp_path, "redux4")
    tags = {}
    assert _SeedStub()._seed_names_from_library(
        new, {"rad::a/scene.radium"}, tags) is True
    assert tags == {"rad::a/scene.radium": "Song Select"}
    # Persisted, so the tab that scans this folder next reads it straight off.
    assert staged_changes.load(new)["image_group_tags"] == tags


def test_seed_names_never_overrides_this_folders_own_name(tmp_path):
    old = _carded(tmp_path, "redux3")
    tag_library.remember(old, {"rad::x": "Library Name"}, {"rad::x"})
    new = _carded(tmp_path, "redux4")
    tags = {"rad::x": "Typed Here"}
    assert _SeedStub()._seed_names_from_library(new, {"rad::x"}, tags) is False
    assert tags == {"rad::x": "Typed Here"}


def test_seed_names_keeps_names_the_other_tab_already_saved(tmp_path):
    # The Images tab may have written its own group names before the Text tab
    # seeds a scene (or the other way round) — one store, so neither may drop
    # the other's entries when it saves.
    old = _carded(tmp_path, "redux3")
    tag_library.remember(old, {"rad::scene": "Song Select"}, {"rad::scene"})
    new = _carded(tmp_path, "redux4")
    staged_changes.save(new, {"image_group_tags": {"dir::art": "Backglass"}})
    _SeedStub()._seed_names_from_library(new, {"rad::scene"}, {})
    assert staged_changes.load(new)["image_group_tags"] == {
        "dir::art": "Backglass", "rad::scene": "Song Select"}


class _TextNameStub:
    _text_set_scene_name = MainWindow._text_set_scene_name
    # staticmethod() around it: MainWindow._text_scene_key hands back the bare
    # function, which would rebind as an instance method on this stub.
    _text_scene_key = staticmethod(MainWindow._text_scene_key)

    def __init__(self, scan_dir):
        self._text_scan_dir = scan_dir
        self._text_scene_names = {}
        self._text_rows = [{"path": "a/scene.radium", "original": "PLAY",
                            "replacement": ""}]
        self._text_scene_displays = {}
        self._image_scan_dir = ""
        self.text_scene_filter_var = _Var("All scenes")

    def _text_scene_selection(self):
        return None

    def _same_folder(self, _a, _b):
        return False

    def _text_rebuild_scene_menu(self):
        pass

    def _refresh_text_list(self):
        pass

    def _text_reselect(self, _iid):
        pass


def test_naming_a_scene_on_the_text_tab_reaches_the_library(tmp_path):
    # Naming on the Images tab was remembered card-wide; naming on the Text tab
    # only ever reached this folder's sidecar, so a fresh extract of the same
    # card came back with bare hashes.
    old = _carded(tmp_path, "redux3")
    me = _TextNameStub(old)
    key = MainWindow._text_scene_key("a/scene.radium")
    me._text_set_scene_name(key, "Song Select")
    assert staged_changes.load(old)["image_group_tags"] == {key: "Song Select"}
    new = _carded(tmp_path, "redux4")
    assert tag_library.seed_tags(new, {key}) == {key: "Song Select"}


def test_clearing_a_scene_name_clears_it_card_wide(tmp_path):
    old = _carded(tmp_path, "redux3")
    me = _TextNameStub(old)
    key = MainWindow._text_scene_key("a/scene.radium")
    me._text_set_scene_name(key, "Song Select")
    me._text_set_scene_name(key, "")
    assert tag_library.seed_tags(old, {key}) == {}


# ---------------------------------------------------------------------------
# 4. Automatic re-checks for updates
# ---------------------------------------------------------------------------

def test_update_interval_default_is_on_the_menu():
    assert UPDATE_INTERVAL_DEFAULT in {h for h, _ in UPDATE_INTERVAL_CHOICES}


@pytest.mark.parametrize("stored", [None, "", "6h", 5, -1, {}])
def test_update_interval_falls_back_to_the_default(stored):
    assert normalize_update_interval(stored) == UPDATE_INTERVAL_DEFAULT


@pytest.mark.parametrize("hours", [h for h, _ in UPDATE_INTERVAL_CHOICES])
def test_update_interval_keeps_a_real_choice(hours):
    # 0 ("only at startup") is a choice, not a missing value.
    assert normalize_update_interval(hours) == hours
    assert normalize_update_interval(str(hours)) == hours


class _BannerStub:
    show_update_banner = MainWindow.show_update_banner
    _dismiss_update_banner = MainWindow._dismiss_update_banner

    class _Widget:
        def __init__(self):
            self.mapped = False
            self.text = ""

        def winfo_ismapped(self):
            return self.mapped

        def pack(self, **_kw):
            self.mapped = True

        def pack_forget(self):
            self.mapped = False

        def configure(self, text=None, **_kw):
            if text is not None:
                self.text = text

    def __init__(self):
        self._update_banner = self._Widget()
        self._update_banner_text = self._Widget()
        self._update_install_btn = self._Widget()
        self._update_download_btn = self._Widget()
        self._top_bar = None
        self._update_available = None
        self._update_banner_url = None
        self._update_banner_dismissed = None
        self._on_install_update = None
        self.badges = 0

    def _refresh_gear_badge(self):
        self.badges += 1


def test_dismissed_banner_stays_shut_when_the_timer_re_checks():
    me = _BannerStub()
    me.show_update_banner("0.132.0", "http://example/rel")
    assert me._update_banner.mapped
    me._dismiss_update_banner()
    me.show_update_banner("0.132.0", "http://example/rel")   # timer fired
    assert not me._update_banner.mapped
    # The news itself is not lost — the gear keeps carrying it.
    assert me._update_available[0] == "0.132.0"


def test_a_newer_version_banners_again_after_a_dismissal():
    me = _BannerStub()
    me.show_update_banner("0.132.0", "http://example/rel")
    me._dismiss_update_banner()
    me.show_update_banner("0.133.0", "http://example/rel2")
    assert me._update_banner.mapped
    assert "0.133.0" in me._update_banner_text.text
