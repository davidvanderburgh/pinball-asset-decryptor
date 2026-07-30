"""Feedback batch 25 — logic-level tests for the Video/Audio/Images fixes.

No Tk window is built: the methods under test only touch plain attributes,
so duck-typed ``self`` stubs exercise them the way the real window does.
"""

from types import SimpleNamespace

from pinball_decryptor.core import staged_changes
from pinball_decryptor.core.video import VideoInfo
from pinball_decryptor.core.video_slots import VideoSlot
from pinball_decryptor.gui.main_window import MainWindow


class _Var:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


# ---------------------------------------------------------------------------
# "The file is no longer in its folder" — but a same-name file with another
# extension IS (he re-exported .mp4 picks as .mov and deleted the originals,
# then read the note as a false alarm).  The sibling is named in the note.
# ---------------------------------------------------------------------------

def test_same_stem_sibling_found_across_extensions(tmp_path):
    (tmp_path / "Promos2.mov").write_bytes(b"clip")
    assert staged_changes.same_stem_sibling(
        str(tmp_path / "Promos2.mp4")) == "Promos2.mov"


def test_same_stem_sibling_is_case_insensitive(tmp_path):
    (tmp_path / "PROMOS2.MOV").write_bytes(b"clip")
    assert staged_changes.same_stem_sibling(
        str(tmp_path / "promos2.mp4")) == "PROMOS2.MOV"


def test_same_stem_sibling_ignores_other_stems_and_dirs(tmp_path):
    (tmp_path / "Promos3.mov").write_bytes(b"other clip")
    (tmp_path / "Promos2.mov").mkdir()          # a folder is not a clip
    assert staged_changes.same_stem_sibling(
        str(tmp_path / "Promos2.mp4")) is None


def test_same_stem_sibling_none_when_folder_unreachable(tmp_path):
    assert staged_changes.same_stem_sibling(
        str(tmp_path / "no_such_dir" / "Promos2.mp4")) is None


def test_dropped_warning_names_the_renamed_sibling(tmp_path):
    assets = tmp_path / "assets"
    (assets / "video").mkdir(parents=True)
    (assets / ".orig" / "video").mkdir(parents=True)
    (assets / "video" / "a.mov").write_bytes(b"replacement bytes")
    (assets / ".orig" / "video" / "a.mov").write_bytes(b"original bytes")
    (tmp_path / "Promos2.mov").write_bytes(b"re-exported clip")

    saved = {"video/a.mov": str(tmp_path / "Promos2.mp4")}
    logs = []
    me = SimpleNamespace(
        append_log=lambda text, level="info": logs.append((text, level)))
    MainWindow._warn_dropped_assignments(me, "video", saved,
                                         {"video/a.mov": object()},
                                         str(assets))
    assert len(logs) == 1
    text, level = logs[0]
    assert level == "info"
    assert '"Promos2.mov"' in text and "different extension" in text


# ---------------------------------------------------------------------------
# A .orig snapshot is proof of a staged change all by itself — the previews
# must not wait for the background change scan (minutes over a NAS) before
# treating the slot as modified.  He clicked his attract slot inside that
# window and the "Original" pane played his previous replacement.
# ---------------------------------------------------------------------------

def _changed_stub(assets, changed=()):
    return SimpleNamespace(_video_changed_on_disk=set(changed),
                           _video_scan_dir=str(assets))


def test_snapshot_counts_as_changed_before_the_scan_lands(tmp_path):
    assets = tmp_path / "assets"
    (assets / ".orig" / "video").mkdir(parents=True)
    (assets / ".orig" / "video" / "AttractMode.mov").write_bytes(b"stock")
    me = _changed_stub(assets)                    # change scan not landed yet
    assert MainWindow._slot_changed_on_disk(me, "video",
                                            "video/AttractMode.mov")


def test_change_scan_set_still_counts(tmp_path):
    me = _changed_stub(tmp_path, changed={"video/a.mov"})
    assert MainWindow._slot_changed_on_disk(me, "video", "video/a.mov")


def test_pristine_slot_is_not_changed(tmp_path):
    me = _changed_stub(tmp_path)
    assert not MainWindow._slot_changed_on_disk(me, "video", "video/a.mov")


# ---------------------------------------------------------------------------
# Images search: a word sitting in the card-path prefix EVERY container
# shares ("stern" in the mount root) matched ~5000 rows while naming none of
# them.  Only the distinguishing tail of a group key is searched now; scene
# hashes (a tester) and explicit path fragments still work.
# ---------------------------------------------------------------------------

_RAD_A = "rad::/sternpinball/game/scenes/a1b2c3d4e5f6/scene.radium"
_RAD_B = "rad::/sternpinball/game/scenes/f6e5d4c3b2a1/scene.radium"


def _search_stub():
    groups = {"images/a.png": (_RAD_A, "Logo · a1b2c3d4", 0),
              "images/b.png": (_RAD_B, "Drums · f6e5d4c3", 0)}
    me = SimpleNamespace(
        _image_group_tags={},
        _image_group_key_tails=MainWindow._compute_image_key_tails(
            groups, {}))
    return me, groups


def test_shared_prefix_word_matches_no_group():
    me, groups = _search_stub()
    for g in groups.values():
        assert not MainWindow._image_group_matches(me, g, "stern")
        assert not MainWindow._image_group_matches(me, g, "game")


def test_scene_hash_still_finds_its_group():
    me, groups = _search_stub()
    a, b = groups["images/a.png"], groups["images/b.png"]
    assert MainWindow._image_group_matches(me, a, "a1b2c3d4e5f6")
    assert not MainWindow._image_group_matches(me, b, "a1b2c3d4e5f6")


def test_label_and_user_tag_still_match():
    me, groups = _search_stub()
    a = groups["images/a.png"]
    assert MainWindow._image_group_matches(me, a, "logo")
    me._image_group_tags[_RAD_A] = "Attract logo"
    assert MainWindow._image_group_matches(me, a, "attract")


def test_a_path_fragment_is_a_deliberate_full_key_search():
    me, groups = _search_stub()
    a = groups["images/a.png"]
    assert MainWindow._image_group_matches(me, a, "sternpinball/game")
    assert MainWindow._image_group_matches(me, a, "sternpinball\\game")


def test_lone_container_keeps_its_whole_path_searchable():
    groups = {"images/a.png": (_RAD_A, "Logo · a1b2c3d4", 0)}
    tails = MainWindow._compute_image_key_tails(groups, {})
    assert tails[_RAD_A.lower()] == \
        "/sternpinball/game/scenes/a1b2c3d4e5f6/scene.radium"


def test_tails_cut_only_at_path_components():
    groups = {"images/a.png": ("rad::/game/scene_aaa/x.radium", "A", 0),
              "images/b.png": ("rad::/game/scene_bbb/x.radium", "B", 0)}
    tails = MainWindow._compute_image_key_tails(groups, {})
    # commonprefix is ".../scene_" — the cut must fall back to the last "/",
    # never split a component.
    assert tails["rad::/game/scene_aaa/x.radium"] == "scene_aaa/x.radium"


# ---------------------------------------------------------------------------
# Cancelling a scan: the start-stamp must go WITH it, or the next Scan click
# logs nothing ("re-entrant") and the eventual "finished" reports the time
# since the cancelled scan began (his 35 s Images scan logged as 2173.4 s).
# ---------------------------------------------------------------------------

class _ScanStub:
    _set_tab_scanning = MainWindow._set_tab_scanning
    _cancel_scan = MainWindow._cancel_scan
    _SCAN_LABELS = MainWindow._SCAN_LABELS

    def __init__(self):
        self.logs = []
        self._scan_reasons = {}
        self._image_scan_id = 0

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


def test_cancel_logs_and_clears_the_start_stamp():
    me = _ScanStub()
    me._set_tab_scanning("image", True)
    me._cancel_scan("image")
    me._set_tab_scanning("image", True)       # restart must log again
    me._set_tab_scanning("image", False)
    texts = [t for t, _lv in me.logs]
    assert sum("Images scan started" in t for t in texts) == 2
    assert sum("Images scan cancelled" in t for t in texts) == 1
    assert sum("Images scan finished" in t for t in texts) == 1
    # Order: started, cancelled, started, finished.
    assert "cancelled" in texts[1] and "finished" in texts[3]


def test_cancel_bumps_the_scan_id_so_results_drop():
    me = _ScanStub()
    me._set_tab_scanning("image", True)
    before = me._image_scan_id
    me._cancel_scan("image")
    assert me._image_scan_id == before + 1


def test_finish_measures_from_the_restart_not_the_first_start():
    me = _ScanStub()
    me._set_tab_scanning("image", True)
    t_first = me._scan_t0["image"]
    me._cancel_scan("image")
    me._set_tab_scanning("image", True)
    assert me._scan_t0["image"] >= t_first
    me._set_tab_scanning("image", False)
    assert "image" not in me._scan_t0


# ---------------------------------------------------------------------------
# Audio: "Play replacements" only acts while sequential play drives the list,
# so ticking it alone switches "Play sequentially" on too.
# ---------------------------------------------------------------------------

def test_play_replacements_turns_on_sequential_play():
    me = SimpleNamespace(audio_play_subst_var=_Var(True),
                         audio_play_through_var=_Var(False))
    MainWindow._audio_on_play_subst_toggle(me)
    assert me.audio_play_through_var.get() is True


def test_unticking_play_replacements_leaves_sequential_alone():
    me = SimpleNamespace(audio_play_subst_var=_Var(False),
                         audio_play_through_var=_Var(True))
    MainWindow._audio_on_play_subst_toggle(me)
    assert me.audio_play_through_var.get() is True


# ---------------------------------------------------------------------------
# The big callout under the video preview: wrong-format slots say so in
# words (the ⚠ glyph alone didn't stand out), and a slot with a good pick
# explains why Format/Audio keep describing the old clip until the build.
# ---------------------------------------------------------------------------

class _FakeLabel:
    def __init__(self):
        self.text = ""
        self.fg = None
        self._mgr = ""

    def configure(self, **kw):
        self.text = kw.get("text", self.text)
        self.fg = kw.get("foreground", self.fg)

    def pack(self, **kw):
        self._mgr = "pack"

    def pack_forget(self):
        self._mgr = ""

    def winfo_manager(self):
        return self._mgr


class _NoteStub:
    _video_update_preview_note = MainWindow._video_update_preview_note
    _slot_unplayable = MainWindow._slot_unplayable
    _video_conv_cached = MainWindow._video_conv_cached
    _video_conv_key = MainWindow._video_conv_key
    _VIDEO_CONV_GOOD = MainWindow._VIDEO_CONV_GOOD
    _VIDEO_CONV_REJECT = MainWindow._VIDEO_CONV_REJECT
    _VIDEO_CONV_ASIS_NOISY = MainWindow._VIDEO_CONV_ASIS_NOISY

    def __init__(self, slot, rep=None, mode=None):
        self._video_preview_note = _FakeLabel()
        self._video_current_rel = slot.rel_path
        self._video_slots_by_rel = {slot.rel_path: slot}
        self._video_assignments = ({slot.rel_path: rep} if rep else {})
        self._video_conv_cache = {}
        self._current_mfr = SimpleNamespace(key="stern")
        self._current_theme = "dark"
        self.video_no_conversion_var = _Var(True)
        self.video_trim_var = _Var(False)
        if rep and mode is not None:
            self._video_conv_cache[
                self._video_conv_key(slot.rel_path, rep)] = mode

    def _video_noconv_conflict(self, rel, path, deep=True):
        return None


def _vslot(codec="h264"):
    vi = VideoInfo(path="s.mov", vcodec=codec, width=1360, height=768,
                   fps=30.0, duration=25.0, pix_fmt="yuv420p",
                   container="mov")
    return VideoSlot(rel_path="video/AttractMode.mov",
                     abs_path="/assets/video/AttractMode.mov", ext=".mov",
                     info=vi, size=1024)


def test_note_flags_an_unplayable_slot_with_no_pick():
    me = _NoteStub(_vslot(codec="prores"))
    me._video_update_preview_note()
    lbl = me._video_preview_note
    assert lbl.winfo_manager() == "pack"
    assert "WRONG FORMAT" in lbl.text and "black picture" in lbl.text


def test_note_promises_the_fix_when_a_good_pick_is_assigned(tmp_path):
    rep = tmp_path / "fixed.mov"
    rep.write_bytes(b"h264 bytes")
    me = _NoteStub(_vslot(codec="prores"), rep=str(rep),
                   mode=MainWindow._VIDEO_CONV_ASIS)
    me._video_update_preview_note()
    lbl = me._video_preview_note
    assert lbl.winfo_manager() == "pack"
    assert "next build" in lbl.text and "Format" in lbl.text
    assert "WRONG FORMAT" not in lbl.text


def test_note_hidden_for_a_healthy_slot():
    me = _NoteStub(_vslot())
    me._video_preview_note.pack()             # pretend it was showing
    me._video_update_preview_note()
    assert me._video_preview_note.winfo_manager() == ""


def test_note_flags_a_rejected_pick_on_a_healthy_slot(tmp_path):
    rep = tmp_path / "bad.mov"
    rep.write_bytes(b"prores bytes")
    me = _NoteStub(_vslot(), rep=str(rep),
                   mode=MainWindow._VIDEO_CONV_REJECT)
    me._video_update_preview_note()
    lbl = me._video_preview_note
    assert lbl.winfo_manager() == "pack"
    assert "WRONG FORMAT" in lbl.text and "as-is" in lbl.text.lower()
