"""Feedback batch 25 — logic-level tests for the Video/Audio/Images fixes.

No window is built: the tab-service methods under test only touch plain
attributes, so duck-typed ``self`` stubs exercise them the way the real tabs
do.
"""

from types import SimpleNamespace

from pinball_decryptor.core import staged_changes
from pinball_decryptor.core.video import VideoInfo
from pinball_decryptor.core.video_slots import VideoSlot
from pinball_decryptor.webui import video_helpers as vh
from pinball_decryptor.webui.tabs.audio import AudioTab
from pinball_decryptor.webui.tabs.images import ImagesTab, compute_key_tails
from pinball_decryptor.webui.tabs.video import VideoTab


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
        _by_rel={"video/a.mov": object()}, window=SimpleNamespace(),
        log=lambda text, level="info": logs.append((text, level)))
    VideoTab._warn_dropped(me, saved, str(assets))
    assert len(logs) == 2          # the note, then the relink hint (PAD-131)
    text, level = logs[0]
    assert level == "info"
    assert '"Promos2.mov"' in text and "different extension" in text
    assert "Relink moved files" in logs[1][0]


# ---------------------------------------------------------------------------
# A .orig snapshot is proof of a staged change all by itself — the previews
# must not wait for the background change scan (minutes over a NAS) before
# treating the slot as modified.  He clicked his attract slot inside that
# window and the "Original" pane played his previous replacement.
# ---------------------------------------------------------------------------

def _changed_stub(assets, changed=()):
    return SimpleNamespace(_changed=set(changed), _scan_dir=str(assets))


def test_snapshot_counts_as_changed_before_the_scan_lands(tmp_path):
    assets = tmp_path / "assets"
    (assets / ".orig" / "video").mkdir(parents=True)
    (assets / ".orig" / "video" / "AttractMode.mov").write_bytes(b"stock")
    me = _changed_stub(assets)                    # change scan not landed yet
    assert VideoTab._slot_changed_on_disk(me, "video/AttractMode.mov")


def test_change_scan_set_still_counts(tmp_path):
    me = _changed_stub(tmp_path, changed={"video/a.mov"})
    assert VideoTab._slot_changed_on_disk(me, "video/a.mov")


def test_pristine_slot_is_not_changed(tmp_path):
    me = _changed_stub(tmp_path)
    assert not VideoTab._slot_changed_on_disk(me, "video/a.mov")


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
    me = SimpleNamespace(_group_tags={},
                         _key_tails=compute_key_tails(groups, {}))
    return me, groups


def test_shared_prefix_word_matches_no_group():
    me, groups = _search_stub()
    for g in groups.values():
        assert not ImagesTab._group_matches(me, g, "stern")
        assert not ImagesTab._group_matches(me, g, "game")


def test_scene_hash_still_finds_its_group():
    me, groups = _search_stub()
    a, b = groups["images/a.png"], groups["images/b.png"]
    assert ImagesTab._group_matches(me, a, "a1b2c3d4e5f6")
    assert not ImagesTab._group_matches(me, b, "a1b2c3d4e5f6")


def test_label_and_user_tag_still_match():
    me, groups = _search_stub()
    a = groups["images/a.png"]
    assert ImagesTab._group_matches(me, a, "logo")
    me._group_tags[_RAD_A] = "Attract logo"
    assert ImagesTab._group_matches(me, a, "attract")


def test_a_path_fragment_is_a_deliberate_full_key_search():
    me, groups = _search_stub()
    a = groups["images/a.png"]
    assert ImagesTab._group_matches(me, a, "sternpinball/game")
    assert ImagesTab._group_matches(me, a, "sternpinball\\game")


def test_lone_container_keeps_its_whole_path_searchable():
    groups = {"images/a.png": (_RAD_A, "Logo · a1b2c3d4", 0)}
    tails = compute_key_tails(groups, {})
    assert tails[_RAD_A.lower()] == \
        "/sternpinball/game/scenes/a1b2c3d4e5f6/scene.radium"


def test_tails_cut_only_at_path_components():
    groups = {"images/a.png": ("rad::/game/scene_aaa/x.radium", "A", 0),
              "images/b.png": ("rad::/game/scene_bbb/x.radium", "B", 0)}
    tails = compute_key_tails(groups, {})
    # commonprefix is ".../scene_" — the cut must fall back to the last "/",
    # never split a component.
    assert tails["rad::/game/scene_aaa/x.radium"] == "scene_aaa/x.radium"


# ---------------------------------------------------------------------------
# Cancelling a scan: the start-stamp must go WITH it, or the next Scan click
# logs nothing ("re-entrant") and the eventual "finished" reports the time
# since the cancelled scan began (his 35 s Images scan logged as 2173.4 s).
# ---------------------------------------------------------------------------

class _ScanStub:
    _set_scanning = ImagesTab._set_scanning
    cancel_scan = ImagesTab.cancel_scan

    def __init__(self):
        self.logs = []
        self._scan_id = 0
        self._scan_t0 = None

    def log(self, text, level="info"):
        self.logs.append((text, level))

    def set(self, **_kw):
        pass


def test_cancel_logs_and_clears_the_start_stamp():
    me = _ScanStub()
    me._set_scanning(True)
    me.cancel_scan()
    me._set_scanning(True)       # restart must log again
    me._set_scanning(False)
    texts = [t for t, _lv in me.logs]
    assert sum("Images scan started" in t for t in texts) == 2
    assert sum("Images scan cancelled" in t for t in texts) == 1
    assert sum("Images scan finished" in t for t in texts) == 1
    # Order: started, cancelled, started, finished.
    assert "cancelled" in texts[1] and "finished" in texts[3]


def test_cancel_bumps_the_scan_id_so_results_drop():
    me = _ScanStub()
    me._set_scanning(True)
    before = me._scan_id
    me.cancel_scan()
    assert me._scan_id == before + 1


def test_finish_measures_from_the_restart_not_the_first_start():
    me = _ScanStub()
    me._set_scanning(True)
    t_first = me._scan_t0
    me.cancel_scan()
    me._set_scanning(True)
    assert me._scan_t0 >= t_first
    me._set_scanning(False)
    assert me._scan_t0 is None


# ---------------------------------------------------------------------------
# Audio: "Play replacements" only acts while sequential play drives the list,
# so ticking it alone switches "Play sequentially" on too.
# ---------------------------------------------------------------------------

def test_play_replacements_turns_on_sequential_play():
    me = SimpleNamespace(audio_play_subst_var=_Var(False),
                         audio_play_through_var=_Var(False))
    AudioTab.set_play_subst(me, True)
    assert me.audio_play_through_var.get() is True


def test_unticking_play_replacements_leaves_sequential_alone():
    me = SimpleNamespace(audio_play_subst_var=_Var(True),
                         audio_play_through_var=_Var(True))
    AudioTab.set_play_subst(me, False)
    assert me.audio_play_through_var.get() is True


# ---------------------------------------------------------------------------
# The big callout under the video preview: wrong-format slots say so in
# words (the ⚠ glyph alone didn't stand out), and a slot with a good pick
# explains why Format/Audio keep describing the old clip until the build.
# ---------------------------------------------------------------------------

class _NoteStub:
    _update_note = VideoTab._update_note
    _conv_cached = VideoTab._conv_cached
    _conv_key = VideoTab._conv_key
    _asis_for = VideoTab._asis_for

    def __init__(self, slot, rep=None, mode=None):
        self._state = {"preview": {"note": None}}
        self._current = slot.rel_path
        self._by_rel = {slot.rel_path: slot}
        self._assign = ({slot.rel_path: rep} if rep else {})
        self._conv_cache = {}
        self.video_no_conversion_var = _Var(True)
        self.video_trim_var = _Var(False)
        self._asis = {}                   # no per-clip overrides (batch 37)
        if rep and mode is not None:
            self._conv_cache[self._conv_key(slot.rel_path, rep)] = mode

    def _mfr_key(self):
        return "stern"

    def get(self, key):
        return self._state.get(key)

    def set(self, **kw):
        self._state.update(kw)

    @property
    def note(self):
        return self._state["preview"]["note"]


def _vslot(codec="h264"):
    vi = VideoInfo(path="s.mov", vcodec=codec, width=1360, height=768,
                   fps=30.0, duration=25.0, pix_fmt="yuv420p",
                   container="mov")
    return VideoSlot(rel_path="video/AttractMode.mov",
                     abs_path="/assets/video/AttractMode.mov", ext=".mov",
                     info=vi, size=1024)


def test_note_flags_an_unplayable_slot_with_no_pick():
    me = _NoteStub(_vslot(codec="prores"))
    me._update_note()
    assert me.note is not None
    assert "WRONG FORMAT" in me.note["text"]
    assert "black picture" in me.note["text"]


def test_note_promises_the_fix_when_a_good_pick_is_assigned(tmp_path):
    rep = tmp_path / "fixed.mov"
    rep.write_bytes(b"h264 bytes")
    me = _NoteStub(_vslot(codec="prores"), rep=str(rep), mode=vh.CONV_ASIS)
    me._update_note()
    assert me.note is not None
    assert "next build" in me.note["text"] and "Format" in me.note["text"]
    assert "WRONG FORMAT" not in me.note["text"]


def test_note_hidden_for_a_healthy_slot():
    me = _NoteStub(_vslot())
    me._state["preview"] = {"note": {"kind": "err", "text": "old"}}
    me._update_note()
    assert me.note is None


def test_note_flags_a_rejected_pick_on_a_healthy_slot(tmp_path):
    rep = tmp_path / "bad.mov"
    rep.write_bytes(b"prores bytes")
    me = _NoteStub(_vslot(), rep=str(rep), mode=vh.CONV_REJECT)
    me._update_note()
    assert me.note is not None
    assert "WRONG FORMAT" in me.note["text"]
    assert "as-is" in me.note["text"].lower()
