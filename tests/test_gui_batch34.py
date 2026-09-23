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

No window is built: the web tabs' methods under test only touch plain
attributes, so duck-typed ``self`` stubs exercise them the way the real tab
services do.  Covered elsewhere: the metadata pass keeping the changed-on-disk
mark and an untouched slot saying Choose (test_webui_images.py
test_changed_on_disk_and_revert_fanouts and
test_scan_lists_every_slot_with_metadata), the default interval being on the
menu (test_webui_shellx.py test_menu_choices), and a dismissed update banner
staying shut until a newer version (test_webui_shellx.py
test_update_banner_dismiss_and_newer).
"""

import os

import pytest

from pinball_decryptor.core import checksums, staged_changes, tag_library
from pinball_decryptor.core.extract_source import write_extract_source
from pinball_decryptor.webui import text_rules as R
from pinball_decryptor.webui.tabs.images import ImagesTab
from pinball_decryptor.webui.tabs.text import TextTab, _seed_names_from_library
from pinball_decryptor.webui.tabs.video import VideoTab
from pinball_decryptor.webui.update_interval import (UPDATE_INTERVAL_CHOICES,
                                                     UPDATE_INTERVAL_DEFAULT,
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


class _Loop:
    """Collects posted callbacks instead of running them, so a test can
    interleave two scans exactly the way the UI loop does."""

    def __init__(self):
        self.queued = []

    def post(self, fn, *args):
        self.queued.append(lambda: fn(*args))

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

class _TabStub:
    def __init__(self, assets_dir, loop, logs, refreshed):
        self._assets = assets_dir
        self.ctx = type("Ctx", (), {"loop": loop})()
        self._logs = logs
        self._refreshed = refreshed
        self._foreign_notes = {}
        self._change_running = False
        self._store = {}

    def log(self, text, level="info"):
        self._logs.append((level, text))

    def get(self, key, default=None):
        return self._store.get(key, default)

    def set(self, **kw):
        self._store.update(kw)


class _VideoScan(_TabStub):
    _start_change_scan = VideoTab._start_change_scan
    _mark_change_scan = VideoTab._mark_change_scan
    _note_foreign = VideoTab._note_foreign

    def __init__(self, assets_dir, loop, logs, refreshed, slots=None):
        super().__init__(assets_dir, loop, logs, refreshed)
        self._slots = (slots if slots is not None
                       else [_Slot("video/attract.mov")])
        self._change_id = 0
        self._changed = set()
        self._foreign = set()
        self._twins = {}
        self._current = None

    def _assets_path(self):
        return self._assets

    def _refresh_list(self):
        self._refreshed.append("video")


class _ImageScan(_TabStub):
    _start_change_scan = ImagesTab._start_change_scan
    _mark_change_scan = ImagesTab._mark_change_scan
    _note_foreign_slots = ImagesTab._note_foreign_slots

    def __init__(self, assets_dir, loop, logs, refreshed, slots=None):
        super().__init__(assets_dir, loop, logs, refreshed)
        self._slots = (slots if slots is not None
                       else [_Slot("images/logo.png")])
        self._change_scan_id = 0
        self._changed_on_disk = set()
        self._foreign_rels = set()
        self._foreign_twins = {}
        self._current_rel = None
        self.image_status_var = _Var("")

    def _assets_dir(self):
        return self._assets

    def _refresh_image_list(self):
        self._refreshed.append("image")


class _ScanStub:
    """The Video and Images tabs on one folder and one loop."""

    def __init__(self, assets_dir, image_slots=None):
        self.loop = _Loop()
        self.logs = []
        self.refreshed = []
        self.video = _VideoScan(assets_dir, self.loop, self.logs,
                                self.refreshed)
        self.image = _ImageScan(assets_dir, self.loop, self.logs,
                                self.refreshed, slots=image_slots)


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
    me.video._start_change_scan()
    me.image._start_change_scan()     # starts while video is still in flight
    me.loop.drain()
    assert me.video._changed == {"video/attract.mov"}
    assert me.image._changed_on_disk == {"images/logo.png"}
    assert sorted(me.refreshed) == ["image", "video"]


def test_rescanning_one_kind_still_supersedes_its_own_earlier_scan(
        tmp_path, _sync_threads):
    # The guard itself has to keep working: two scans of the SAME kind must
    # leave only the newer one's answer.
    me = _ScanStub(_extract(tmp_path))
    me.video._start_change_scan()
    me.video._start_change_scan()
    me.loop.drain()
    assert me.video._changed == {"video/attract.mov"}
    assert me.refreshed == ["video"]       # the superseded one never refreshed


def test_change_scan_ids_are_per_kind(tmp_path, _sync_threads):
    me = _ScanStub(_extract(tmp_path))
    me.video._start_change_scan()
    me.image._start_change_scan()
    assert (me.video._change_id, me.image._change_scan_id) == (1, 1)


def test_scan_names_files_that_are_not_part_of_this_extract(tmp_path,
                                                            _sync_threads):
    """A pack built from another card left files this extract never produced;
    they list as slots no build can use (a tester's Pro folder showed 201 of
    them).  The scan has to say so — once, not on every rescan."""
    assets = _extract(tmp_path)
    stray = os.path.join(assets, "images", "other_card_logo.png")
    with open(stray, "wb") as f:
        f.write(b"not from this card")

    me = _ScanStub(assets, image_slots=[_Slot("images/logo.png"),
                                        _Slot("images/other_card_logo.png")])
    me.image._start_change_scan()
    me.loop.drain()
    notes = [t for lvl, t in me.logs if lvl == "warning"]
    assert len(notes) == 1
    assert "1 file(s) in this folder aren't part of this extract" in notes[0]
    assert "images/other_card_logo.png" in notes[0]

    me.image._start_change_scan()             # same folder, same strays
    me.loop.drain()
    assert len([t for lvl, t in me.logs if lvl == "warning"]) == 1


# ---------------------------------------------------------------------------
# 2. The Images metadata pass must keep the changed-on-disk mark
# ---------------------------------------------------------------------------

class _ImageMetaStub:
    _apply_image_meta = ImagesTab._apply_image_meta
    _row = ImagesTab._row
    _slot_not_on_card = ImagesTab._slot_not_on_card
    _changed_on_disk_cell = ImagesTab._changed_on_disk_cell
    _remembered_rep_name = ImagesTab._remembered_rep_name
    _keep_state = ImagesTab._keep_state

    def __init__(self, rel, changed=(), assigned=None, foreign=()):
        self._scan_id = 7
        self._slot = _Slot(rel)
        self._by_rel = {rel: self._slot}
        self._idx = {rel: 0}
        self._keep_size = set()
        self._assignments = dict(assigned or {})
        self._changed_on_disk = set(changed)
        self._foreign_rels = set(foreign)
        self._scan_dir = ""
        self._rep_names = {}

    def _can_keep_size(self, _rel):
        return False


REL = "images/led_zeppelin_le/assets/lcd/GameLogo.png"


def _rep_cell(me):
    return me._row(me._slot)["p"]


def test_image_meta_prefers_the_pending_assignment():
    me = _ImageMetaStub(REL, changed={REL},
                        assigned={REL: os.path.join("W:", "art", "redux.png")})
    assert me._apply_image_meta(7, REL, object()) == 0
    assert _rep_cell(me) == "redux.png"


def test_image_meta_from_a_stale_scan_is_ignored():
    me = _ImageMetaStub(REL, changed={REL})
    assert me._apply_image_meta(6, REL, object()) is None
    assert me._slot.info is None and not me._slot.probed


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


def test_seed_names_fills_from_library_and_writes_the_sidecar(tmp_path):
    old = _carded(tmp_path, "redux3")
    tag_library.remember(old, {"rad::a/scene.radium": "Song Select"},
                         {"rad::a/scene.radium"})
    new = _carded(tmp_path, "redux4")
    tags = {}
    assert _seed_names_from_library(
        new, {"rad::a/scene.radium"}, tags) is True
    assert tags == {"rad::a/scene.radium": "Song Select"}
    # Persisted, so the tab that scans this folder next reads it straight off.
    assert staged_changes.load(new)["image_group_tags"] == tags


def test_seed_names_never_overrides_this_folders_own_name(tmp_path):
    old = _carded(tmp_path, "redux3")
    tag_library.remember(old, {"rad::x": "Library Name"}, {"rad::x"})
    new = _carded(tmp_path, "redux4")
    tags = {"rad::x": "Typed Here"}
    assert _seed_names_from_library(new, {"rad::x"}, tags) is False
    assert tags == {"rad::x": "Typed Here"}


def test_seed_names_keeps_names_the_other_tab_already_saved(tmp_path):
    # The Images tab may have written its own group names before the Text tab
    # seeds a scene (or the other way round) — one store, so neither may drop
    # the other's entries when it saves.
    old = _carded(tmp_path, "redux3")
    tag_library.remember(old, {"rad::scene": "Song Select"}, {"rad::scene"})
    new = _carded(tmp_path, "redux4")
    staged_changes.save(new, {"image_group_tags": {"dir::art": "Backglass"}})
    _seed_names_from_library(new, {"rad::scene"}, {})
    assert staged_changes.load(new)["image_group_tags"] == {
        "dir::art": "Backglass", "rad::scene": "Song Select"}


class _TextNameStub:
    _set_scene_name = TextTab._set_scene_name

    def __init__(self, scan_dir):
        self._text_scan_dir = scan_dir
        self._scene_names = {}
        self._text_rows = [{"path": "a/scene.radium", "original": "PLAY",
                            "replacement": ""}]
        self._scene_displays = {}
        self._suspend = 0
        self.text_scene_filter_var = _Var("All scenes")

    def _scene_selection(self):
        return None

    def _images_follow(self, _scan_dir, _tags):
        pass

    def _rebuild_scene_menu(self):
        pass

    def _refresh_list(self, rebuild_rows=False):
        pass


def test_naming_a_scene_on_the_text_tab_reaches_the_library(tmp_path):
    # Naming on the Images tab was remembered card-wide; naming on the Text tab
    # only ever reached this folder's sidecar, so a fresh extract of the same
    # card came back with bare hashes.
    old = _carded(tmp_path, "redux3")
    me = _TextNameStub(old)
    key = R.scene_key("a/scene.radium")
    me._set_scene_name(key, "Song Select")
    assert staged_changes.load(old)["image_group_tags"] == {key: "Song Select"}
    new = _carded(tmp_path, "redux4")
    assert tag_library.seed_tags(new, {key}) == {key: "Song Select"}


def test_clearing_a_scene_name_clears_it_card_wide(tmp_path):
    old = _carded(tmp_path, "redux3")
    me = _TextNameStub(old)
    key = R.scene_key("a/scene.radium")
    me._set_scene_name(key, "Song Select")
    me._set_scene_name(key, "")
    assert tag_library.seed_tags(old, {key}) == {}


# ---------------------------------------------------------------------------
# 4. Automatic re-checks for updates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stored", [None, "", "6h", 5, -1, {}])
def test_update_interval_falls_back_to_the_default(stored):
    assert normalize_update_interval(stored) == UPDATE_INTERVAL_DEFAULT


@pytest.mark.parametrize("hours", [h for h, _ in UPDATE_INTERVAL_CHOICES])
def test_update_interval_keeps_a_real_choice(hours):
    # 0 ("only at startup") is a choice, not a missing value.
    assert normalize_update_interval(hours) == hours
    assert normalize_update_interval(str(hours)) == hours
