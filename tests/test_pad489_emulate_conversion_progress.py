"""PAD-489 (DragonRR): "Emulate is very slow when you have applied color filters to
everything ... I have no sign of a progress bar, no warning that there are a huge number of
files to process and it will take a long time. So we need an assessment of what is involved
from PAD, a rough time estimate, a warning ideally with a time estimate."

Staging bakes the colour profile into every game clip switched on with one encode apiece
(~1 s for a Godzilla clip on a 16-core PC), and the Emulate tab said "Applying your
replacements..." over an empty bar for the whole of it.  Now:

1. the staging counts what it will convert before it starts (a clip its cache keeps is not
   counted) and prices it (core/staging_work.py);
2. the Emulate tab logs that, and asks first when the clips alone come to a minute or more;
3. while it runs the State line says "Converting videos: 12 of 658 (about 15 minutes
   left)", the footer bar moves, and the time left is measured as it goes;
4. the override build after it shows its own steps and bar rather than a still word.

Round 2 (DragonRR: "cancel in this situation seems to run through files quickly for a few
seconds and then hangs although my PC is doing 'something'"): Cancel killed the clip being
converted, but the Start went on through every picture (no cancel there) and into the
override build, which gave up only after its own scan of the project.  Now:

5. Cancel says "Cancelling…" at once, on the State line and the button, until the work stops;
6. the pictures are not begun after a Cancel, and a Cancel ends the Start right after the
   staging: "Cancelled: the game was not started", with the videos already converted kept;
7. the override build checks for a Cancel after its scan, before reading the sound bank, and
   between clip fits."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import image_slots, staging_work, video_slots
from pinball_decryptor.core.colour_profile import Profile


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def _speed_file(tmp_path, monkeypatch):
    """Never read or write this PC's real conversion_speed.json."""
    path = str(tmp_path / "settings" / "conversion_speed.json")
    monkeypatch.setattr(staging_work, "_speed_path", lambda: path)
    return path


# --------------------------------------------------------------------------
# 1. the estimate and the words
# --------------------------------------------------------------------------

def test_the_words_never_claim_more_than_an_estimate_knows():
    assert staging_work.say_time(20) == "less than a minute"
    assert staging_work.say_time(70) == "about a minute"
    assert staging_work.say_time(17 * 60 + 10) == "about 17 minutes"
    assert staging_work.say_time(80 * 60) == "about 1 hour 20 minutes"
    assert staging_work.say_time(2 * 3600 + 60) == "about 2 hours"
    w = staging_work.Work(clips={"a": 0, "b": 0}, pictures=5813)
    assert w.says() == "2 videos and 5,813 pictures"
    assert staging_work.Work(pictures=1).says() == "1 picture"
    assert not staging_work.Work()


def test_a_whole_games_clips_are_priced_in_minutes():
    """Godzilla's 658 clips (1360x768, 30 fps, ~8 s) at the model's rate: a quarter of an
    hour or so, where this PC measured ~13 minutes."""
    px = 1360 * 768 * 30 * 8
    w = staging_work.Work(clips={str(i): px for i in range(658)})
    assert 10 * 60 < staging_work.estimate(w, factor=1.0) < 25 * 60
    # an unreadable clip is priced as an average one, not as free
    assert staging_work.clip_seconds(0) == staging_work.clip_seconds(px)
    # this PC's own speed scales the clips, not the pictures
    w = staging_work.Work(clips={"a": px}, pictures=100)
    assert staging_work.estimate(w, factor=2.0) == pytest.approx(
        2 * staging_work.clip_seconds(px) + 100 * staging_work.PICTURE_S)


def test_this_pcs_speed_is_remembered_halfway(_speed_file):
    assert staging_work.speed_factor() == 1.0
    staging_work.remember(spent=60.0, modelled=20.0)        # 3x slower than the model
    assert staging_work.speed_factor() == pytest.approx(3.0)
    staging_work.remember(spent=20.0, modelled=20.0)        # then as the model says
    assert staging_work.speed_factor() == pytest.approx(2.0)
    staging_work.remember(spent=1.0, modelled=100.0)        # too little to go by
    assert staging_work.speed_factor() == pytest.approx(2.0)


def test_the_tracker_counts_converted_clips_and_measures_the_time_left():
    clock = _Clock()
    w = staging_work.Work(clips={"v/%d.mp4" % i: 0 for i in range(10)})
    t = staging_work.Tracker(w, factor=1.0, clock=clock)
    per = staging_work.clip_seconds(0)
    text, pct = t.step("videos", 0, 12, "v/0.mp4")
    assert text == "Converting videos: 0 of 10 (less than a minute left)"
    assert pct == 0
    clock.t += 60.0                           # each takes a minute, the model said ~1.5 s
    t.step("videos", 1, 12, "v/kept.mp4")
    # a clip the cache keeps passes in no time and is not counted
    clock.t += 0.01
    t.step("videos", 2, 12, "v/1.mp4")
    for i in range(2, 4):
        clock.t += 60.0
        text, pct = t.step("videos", i + 1, 12, "v/%d.mp4" % i)
    assert 25 <= pct <= 35
    # three converted: the time left is what they really took, not the model's
    assert t.left() == pytest.approx(7 * 60.0, rel=0.01)
    assert text == "Converting videos: 3 of 10 (about 7 minutes left)"
    assert per < 2.0
    clock.t += 60.0
    text, pct = t.step("videos", 12, 12)
    assert text == "Converting videos: 4 of 10"


def test_the_tracker_moves_on_to_the_pictures_and_remembers_the_speed(_speed_file):
    clock = _Clock()
    px = 1360 * 768 * 30 * 30                  # 30 s clips: ~6.5 s each by the model
    w = staging_work.Work(clips={"a": px, "b": px, "c": px}, pictures=4)
    t = staging_work.Tracker(w, factor=1.0, clock=clock)
    for i, rel in enumerate("abc"):
        t.step("videos", i, 3, rel)
        clock.t += 4.0
    t.step("videos", 3, 3)
    text, pct = t.step("pictures", 2, 4, "images/x.png")
    assert text.startswith("Converting pictures: 2 of 4")
    assert pct >= 90
    t.finish()
    assert staging_work.speed_factor() == pytest.approx(
        12.0 / (3 * staging_work.clip_seconds(px)), rel=0.01)


# --------------------------------------------------------------------------
# 2. what the staging will convert, counted the way it converts
# --------------------------------------------------------------------------

def _clips(tmp_path, names):
    assets = tmp_path / "proj"
    (assets / "video").mkdir(parents=True)
    slots = {}
    for n in names:
        p = assets / "video" / n
        p.write_bytes(b"STOCK " + n.encode())
        rel = "video/" + n
        slots[rel] = video_slots.VideoSlot(rel_path=rel, abs_path=str(p), ext=".mp4",
                                           info=None, size=p.stat().st_size)
    return str(assets), slots


def _fake_encode(monkeypatch, done):
    def stage_replacement(slot, rep, **kw):
        with open(slot.abs_path, "wb") as f:
            f.write(b"CONVERTED %r" % (kw.get("colour") and kw["colour"].key(),))
        done.append(slot.rel_path)
        return True, "converted"
    monkeypatch.setattr(video_slots, "stage_replacement", stage_replacement)


def test_a_clip_the_staging_would_keep_is_not_counted(tmp_path, monkeypatch):
    """The count shares the staging's own recipe: after a pass nothing is due, and a new
    profile makes every clip due again."""
    assets, slots = _clips(tmp_path, ["a.mp4", "b.mp4"])
    reps = tmp_path / "reps"
    reps.mkdir()
    picks = {}
    for rel in slots:
        r = reps / os.path.basename(rel)
        r.write_bytes(b"MINE")
        picks[rel] = str(r)
    red = Profile(name="Red", gain=(1.3, 0.9, 0.9))
    monkeypatch.setattr(cp, "active", lambda d: red)
    due, coloured = video_slots.conversions_due(slots, picks, assets_dir=assets)
    assert set(due) == set(slots) and coloured == frozenset(slots)
    done = []
    _fake_encode(monkeypatch, done)
    assert video_slots.stage_replacements(slots, picks, assets_dir=assets) == (2, [])
    assert sorted(done) == sorted(slots)
    assert video_slots.conversions_due(slots, picks, assets_dir=assets) == ({}, frozenset())
    blue = Profile(name="Blue", gain=(0.9, 0.9, 1.3))
    monkeypatch.setattr(cp, "active", lambda d: blue)
    assert set(video_slots.conversions_due(slots, picks, assets_dir=assets)[0]) == set(slots)


def test_counting_writes_nothing_and_skips_an_as_is_copy(tmp_path, monkeypatch):
    assets, slots = _clips(tmp_path, ["a.mp4", "b.mp4"])
    rep = tmp_path / "mine.mp4"
    rep.write_bytes(b"MINE")
    picks = {rel: str(rep) for rel in slots}
    monkeypatch.setattr(cp, "active", lambda d: None)
    before = sorted(os.listdir(assets))
    due, coloured = video_slots.conversions_due(
        slots, picks, assets_dir=assets, asis_overrides={"video/b.mp4": True})
    assert list(due) == ["video/a.mp4"] and coloured == frozenset()
    assert sorted(os.listdir(assets)) == before          # no .orig/, no cache written


def test_the_game_pictures_switched_on_are_counted(tmp_path, monkeypatch):
    slots = {}
    for n in ("a", "b", "c"):
        rel = "images/%s.png" % n
        slots[rel] = image_slots.ImageSlot(rel_path=rel, abs_path=str(tmp_path / n),
                                           ext=".png", info=None, size=1)
    monkeypatch.setattr(cp, "active", lambda d: None)
    monkeypatch.setattr(cp, "any_asset_active", lambda d: True)
    monkeypatch.setattr(cp, "stock_image_rels",
                        lambda d, assigned=(): sorted(set(slots) - set(assigned)))
    monkeypatch.setattr(cp, "built_image_on", lambda d: [])
    assert image_slots.pictures_due(slots, {"images/a.png": "x.png"},
                                    assets_dir=str(tmp_path)) == 3
    assert image_slots.pictures_due(slots, {}, assets_dir=None) == 0


def test_cancel_stops_the_pictures_too(tmp_path, monkeypatch):
    slots = {}
    for n in ("a", "b", "c"):
        rel = "images/%s.png" % n
        slots[rel] = image_slots.ImageSlot(rel_path=rel, abs_path=str(tmp_path / n),
                                           ext=".png", info=None, size=1)
    seen = []
    monkeypatch.setattr(image_slots, "stage_replacement",
                        lambda slot, rep, **kw: (seen.append(slot.rel_path), (True, ""))[1])
    stop = lambda: len(seen) >= 1
    staged, _f = image_slots.stage_replacements(
        slots, {rel: "x.png" for rel in slots}, cancel_cb=stop)
    assert staged == 1 and len(seen) == 1


# --------------------------------------------------------------------------
# 3. the app's one call: count, ask, stage with progress
# --------------------------------------------------------------------------

class _Stub:
    """The parts of App that stage_pending_replacements calls."""

    def __init__(self, work):
        self.work = work
        self.seen = []

    def _video_staging(self, d):
        return {"assignments": {"video/a.mp4": "x"}}

    def _image_staging(self, d):
        return {"slots_by_rel": {}, "assignments": {}, "keep_size": frozenset()}

    def _staging_work(self, d, video, image):
        self.seen.append(("count", video, image))
        return self.work

    def _stage_pending_audio(self, d):
        self.seen.append("audio")
        return (0, 0, [])

    def _stage_pending_video(self, d, cancel_cb=None, progress_cb=None, staging=None):
        self.seen.append(("video", staging))
        progress_cb(0, 1, "video/a.mp4")
        progress_cb(1, 1, "")
        return (1, 1, [])

    def _stage_pending_image(self, d, cancel_cb=None, progress_cb=None, staging=None):
        self.seen.append(("image", staging))
        progress_cb(0, 1, "images/a.png")
        return (1, 1, [])


def test_a_declined_count_stages_nothing():
    from pinball_decryptor.app import App
    work = staging_work.Work(clips={"video/a.mp4": 0})
    stub = _Stub(work)
    asked = []
    got = App.stage_pending_replacements(
        stub, "D:/gz", confirm_cb=lambda w: asked.append(w) or False)
    assert got is None and asked == [work]
    assert [s for s in stub.seen if s == "audio" or s[0] != "count"] == []


def test_the_staging_reports_each_kind_with_the_staging_it_counted():
    from pinball_decryptor.app import App
    stub = _Stub(staging_work.Work(clips={"video/a.mp4": 0}))
    calls = []
    got = App.stage_pending_replacements(
        stub, "D:/gz", confirm_cb=lambda w: True,
        progress_cb=lambda *a: calls.append(a))
    assert got == (2, 2, [])
    assert calls == [("videos", 0, 1, "video/a.mp4"), ("videos", 1, 1, ""),
                     ("pictures", 0, 1, "images/a.png")]
    # the video staging gets the very arguments that were counted
    assert stub.seen[0][1] == stub.seen[2][1] == {"assignments": {"video/a.mp4": "x"}}


# --------------------------------------------------------------------------
# 4. the Emulate tab: say it, ask when it is long, show it as it goes
# --------------------------------------------------------------------------

def _tab(monkeypatch, stage):
    from pinball_decryptor.webui.tabs.emulate import EmulateTab
    logged, painted, asked = [], [], []

    class _Win:
        cb = {"on_stage_pending": stage}

        def folder_staged(self, folder):
            pass

    tab = EmulateTab.__new__(EmulateTab)
    tab.window = _Win()
    tab._stopping = tab._stopped = tab._cancel_prepare = False
    tab._preparing = tab._preparing_pct = tab._preparing_kind = None
    tab._prep_paint_due = False
    monkeypatch.setattr(tab, "_post", lambda fn, *a: None, raising=False)
    monkeypatch.setattr(tab, "_after", lambda ms, fn, *a: fn(*a), raising=False)
    monkeypatch.setattr(tab, "_log", logged.append, raising=False)
    monkeypatch.setattr(tab, "_repaint_preparing", lambda: painted.append(
        (tab._preparing, tab._preparing_pct, tab._preparing_explain())), raising=False)
    from pinball_decryptor.webui import compat
    monkeypatch.setattr(compat.messagebox, "askyesno",
                        lambda title, msg, **k: (asked.append((title, msg)), tab._answer)[1])
    tab._answer = True
    return tab, logged, painted, asked


def _game(n, px=1360 * 768 * 30 * 8, pictures=5813):
    return staging_work.Work(clips={"video/%d.mp4" % i: px for i in range(n)},
                             coloured=frozenset("video/%d.mp4" % i for i in range(n)),
                             pictures=pictures)


def test_a_long_conversion_is_asked_about_with_its_size_and_time(monkeypatch):
    work = _game(658)

    def stage(assets, cancel_cb=None, progress_cb=None, confirm_cb=None):
        if not confirm_cb(work):
            return None
        raise AssertionError("staged after a No")

    tab, logged, painted, asked = _tab(monkeypatch, stage)
    tab._answer = False
    assert tab._stage_pending("C:/proj") is False
    (title, msg), = asked
    assert title == "Before the game starts"
    assert msg.startswith("658 videos and 5,813 pictures have to be converted with your "
                          "color profile before this run can start. That takes about ")
    assert "minutes on this PC" in msg and "Cancel" in msg
    assert msg.rstrip().endswith("Convert them now?")
    assert any("658 videos and 5,813 pictures to convert before the game starts" in l
               for l in logged)
    assert any("not started" in l for l in logged)
    assert tab._preparing is None


def test_a_short_one_or_pictures_alone_are_only_said(monkeypatch):
    for work in (_game(3, pictures=0), _game(0, pictures=5813)):
        def stage(assets, cancel_cb=None, progress_cb=None, confirm_cb=None, work=work):
            assert confirm_cb(work) is True
            return (1, 1, [])
        tab, logged, painted, asked = _tab(monkeypatch, stage)
        assert tab._stage_pending("C:/proj") is True
        assert asked == []
        assert any("to convert before the game starts" in l for l in logged)


def test_the_state_line_counts_the_videos_and_the_time_left(monkeypatch):
    work = _game(658)

    def stage(assets, cancel_cb=None, progress_cb=None, confirm_cb=None):
        assert confirm_cb(work) is True
        for i in range(3):
            progress_cb("videos", i, 658, "video/%d.mp4" % i)
        progress_cb("pictures", 10, 5813, "images/x.png")
        return (658 + 5813, 658 + 5813, [])

    tab, logged, painted, asked = _tab(monkeypatch, stage)
    assert tab._stage_pending("C:/proj") is True
    assert len(asked) == 1
    texts = [p[0] for p in painted if p[0]]
    assert any(t.startswith("Converting videos: 2 of 658 (about ") and t.endswith(" left)")
               for t in texts), texts
    assert any(t.startswith("Converting pictures: 10 of 5,813") for t in texts), texts
    # the bar moves and the ⓘ says what the time goes on
    assert any(p[1] is not None for p in painted)
    assert all("converted" in p[2] for p in painted if p[0] and p[0].startswith("Convert"))
    # done: the tab is back to its own words
    assert tab._preparing is None and tab._preparing_pct is None


def test_the_override_build_shows_its_own_steps(monkeypatch, tmp_path):
    """After the staging, "Preparing your edits" carries the build's steps and bar."""
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.webui import emulate_rig as rig
    tab, logged, painted, asked = _tab(monkeypatch, None)
    tab.window.cb = {}
    assets = tmp_path / "proj"
    assets.mkdir()
    monkeypatch.setattr("pinball_decryptor.core.checksums.read_checksums", lambda d: {"x": 1})
    monkeypatch.setattr(rig, "override_base_card", lambda c, a, f: (c, ""))
    monkeypatch.setattr(rig, "overrides_dir", lambda: str(tmp_path / "set"))
    monkeypatch.setattr(rig, "assets_fingerprint", lambda a: "fp")
    monkeypatch.setattr(rig, "overrides_reason", lambda *a, **k: "first run")
    monkeypatch.setattr(E, "read_override_manifest", lambda out: None)
    monkeypatch.setattr(E, "stamp_override_manifest", lambda *a, **k: None)
    monkeypatch.setattr(tab, "_scene_edits_on", lambda: True, raising=False)
    monkeypatch.setattr(tab, "_live_ready", lambda a, o, env: env, raising=False)
    monkeypatch.setattr(tab, "_with_override_modes", lambda o, env: env, raising=False)
    monkeypatch.setattr(tab, "_paint_run_btn", lambda: None, raising=False)
    shown = []

    def write_overrides(card, assets_dir, out, progress=None, **kw):
        progress(94, 100, "Preparing video...")
        shown.append((tab._preparing, tab._preparing_pct))
        return (0, 1, 0, 0), None, None, [("/a.mp4", 10)]

    monkeypatch.setattr(E, "write_overrides", write_overrides)
    env = tab._prepare_overrides_inner("card.raw", str(assets))
    assert env and env[0].startswith("PAD_OVERRIDE_DIR=")
    assert shown == [("Preparing your edits: preparing video", 94)]


def test_one_long_video_is_asked_about_in_the_singular(monkeypatch):
    work = _game(1, px=1360 * 768 * 30 * 600, pictures=0)        # a 10-minute clip

    def stage(assets, cancel_cb=None, progress_cb=None, confirm_cb=None):
        return None if not confirm_cb(work) else (1, 1, [])

    tab, logged, painted, asked = _tab(monkeypatch, stage)
    tab._answer = False
    assert tab._stage_pending("C:/proj") is False
    (_title, msg), = asked
    assert msg.startswith("1 video has to be converted with your color profile")
    assert msg.rstrip().endswith("Convert it now?")


# --------------------------------------------------------------------------
# 5-7. round 2: a Cancel that ends the Start
# --------------------------------------------------------------------------

def test_a_cut_off_clip_is_not_counted_as_converted():
    clock = _Clock()
    t = staging_work.Tracker(staging_work.Work(clips={"a": 0, "b": 0, "c": 0}),
                             factor=1.0, clock=clock)
    t.step("videos", 0, 3, "a")
    clock.t += 2.0
    t.step("videos", 1, 3, "b")            # a done, b under way when Cancel comes
    clock.t += 0.5
    t.finish(cancelled=True)
    assert t.converted == 1


def test_cancel_says_so_at_once_and_until_the_work_stops(monkeypatch):
    tab, logged, painted, asked = _tab(monkeypatch, None)
    shown = {}
    monkeypatch.setattr(tab, "set", lambda **kw: shown.update(kw), raising=False)
    monkeypatch.setattr(tab, "log", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(tab, "_launched", lambda: False, raising=False)
    monkeypatch.setattr(tab, "_repaint_preparing", lambda: (
        painted.append(tab._preparing), tab._paint_run_btn()), raising=False)
    tab._last_up = tab._starting = False
    tab._preparing = "Converting videos: 3 of 658 (about 15 minutes left)"
    assert tab.toggle() is True
    assert tab._cancel_prepare is True
    assert painted[-1] == "Cancelling…"
    assert shown["run_btn"] == {"label": "Cancelling…", "enabled": False, "mode": "busy"}
    # what the staging says while it winds down does not take the words back
    tab._show_preparing("Converting videos: 4 of 658 (about 15 minutes left)", 1)
    assert painted[-1] == "Cancelling…"
    tab.set_preparing("Preparing your modes…")
    assert tab._preparing == "Cancelling…"
    # a second press asks nothing more
    assert tab.toggle() is True


def test_a_cancel_ends_the_start_after_the_staging(monkeypatch):
    work = _game(10, pictures=100)
    told = []

    def stage(assets, cancel_cb=None, progress_cb=None, confirm_cb=None):
        assert confirm_cb(work) is True
        for i in range(3):
            progress_cb("videos", i, 10, "video/%d.mp4" % i)
        tab._cancel_prepare = True              # Cancel, with clip 2 under way
        assert cancel_cb() is True
        progress_cb("videos", 10, 10, "")       # the staging winding down
        return (110, 2, [("video: video/2.mp4", "cancelled")])

    tab, logged, painted, asked = _tab(monkeypatch, stage)
    tab.window.folder_staged = told.append
    queued = []
    tab.window.app = type("A", (), {"msg_queue": type("Q", (), {
        "put": staticmethod(lambda m: queued.append((m.text, m.level)))})()})()
    monkeypatch.setattr(tab, "_post", lambda fn, *a: fn(*a), raising=False)
    monkeypatch.setattr(tab, "set", lambda **kw: None, raising=False)
    monkeypatch.setattr(tab, "_paint_run_btn", lambda: None, raising=False)
    assert tab._stage_pending("C:/proj") is False
    # after the staging's own lines, which go through the app's queue
    assert queued == [("[emulate] Cancelled: the game was not started. The 2 videos "
                       "converted before you cancelled are kept, so the next Start goes on "
                       "from there.", "info")]
    assert not any("Cancelled:" in l for l in logged)
    assert told == ["C:/proj"]                  # the tabs still learn what changed
    assert not any("None of the" in l for l in logged)


def test_the_pictures_are_not_begun_after_a_cancel():
    from pinball_decryptor.app import App
    stub = _Stub(staging_work.Work(clips={"video/a.mp4": 0}))
    stop = []

    def video(d, cancel_cb=None, progress_cb=None, staging=None):
        stub.seen.append(("video", staging))
        stop.append(True)                        # Cancel during the videos
        return (1, 0, [("video: video/a.mp4", "cancelled")])

    stub._stage_pending_video = video
    got = App.stage_pending_replacements(stub, "D:/gz", cancel_cb=lambda: bool(stop),
                                         confirm_cb=lambda w: True,
                                         progress_cb=lambda *a: None)
    assert got == (1, 0, [("video: video/a.mp4", "cancelled")])
    assert not any(s[0] == "image" for s in stub.seen if isinstance(s, tuple))


def test_the_build_stops_after_its_scan_when_cancelled(tmp_path, monkeypatch):
    import io
    from pinball_decryptor.plugins.stern import engine, mode_write
    assets = tmp_path / "proj"
    assets.mkdir()
    (assets / ".checksums.md5").write_text("audio/idx0000.wav\tabc\n", encoding="utf-8")
    monkeypatch.setattr(engine, "_select_changed_idx_wavs", lambda a, b: {0: "audio/idx0000.wav"})
    monkeypatch.setattr(engine, "_mode_family_on", lambda: True)

    def no(*a, **k):
        raise AssertionError("went on past the scan after a Cancel")
    monkeypatch.setattr(mode_write, "project_modes", no)
    monkeypatch.setattr(engine, "_extract_inputs_kept", no)
    out = engine._compute_patches(io.BytesIO(b""), [], str(assets),
                                  log=lambda *a, **k: None, progress=None,
                                  cancel=lambda: True)
    assert out == (None, None, None, None, None)


def test_a_cancel_between_clip_fits_stops_the_fits(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine

    class _R:
        def iter_regular_files(self, min_size=1):
            for i in range(3):
                yield "/v%d.asset" % i, i, {"size": 10}

    fitted = []
    asked = []

    def cancel():
        asked.append(1)
        return len(fitted) >= 1

    def fit(staged, size, work, log):
        fitted.append(staged)
        return b"x" * size
    monkeypatch.setattr(engine, "_fit_video_payload", fit)
    edits = [("v%d.mp4" % i, "/v%d.asset" % i, str(tmp_path / ("v%d.mp4" % i)))
             for i in range(3)]
    patches, _skipped, _jobs = engine._prepare_video_patches(
        _R(), edits, str(tmp_path), lambda *a, **k: None, cancel)
    assert len(fitted) == 1 and len(patches) == 1


def test_a_clip_cut_off_by_cancel_is_not_called_a_failure(tmp_path, monkeypatch):
    import contextlib
    from pinball_decryptor.app import App
    said = []

    class _Q:
        def put(self, m):
            said.append((m.text, m.level))

    class _S:
        msg_queue = _Q()

        def _colour_assets_scope(self):
            return contextlib.nullcontext()

    monkeypatch.setattr(video_slots, "stage_replacements",
                        lambda slots, picks, **kw: (2, [("video/c.mp4", "cancelled")]))
    staging = {"slots_by_rel": {}, "assignments": {"video/a.mp4": "x", "video/b.mp4": "x",
                                                   "video/c.mp4": "x"},
               "best_quality": False}
    App._stage_pending_video(_S(), str(tmp_path), staging=staging)
    assert said[-1] == ("Applied 2 video replacement(s).  Cancelled before the rest.", "warning")
