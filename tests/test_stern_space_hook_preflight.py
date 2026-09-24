"""PAD-176 at a Build's first step: the Stern ``write_preflight`` hook runs
BEFORE the Replace tabs stage anything (re-encoding every assigned video can
take an hour), and refuses a build whose assigned videos can't fit the card's
games partition even at the fewest bytes each one can take there, in the
engine pre-flight's own words.

Each clip counts only what is sure: a file "use my files as-is" copies
through at its own size, an MP4/QuickTime the slot plays as it is at its own
size, one the Video tab has already converted at the smaller of the two, and
anything else (a file that is always converted) at nothing.  The hook never
starts WSL to learn whether this computer copies files whole: it takes the
prerequisite strip's answer, or the SD card size check's, and refuses nothing
when neither is in.  It skips a port and a direct SD write.

The card is the small real ext2 filesystem test_stern_space_preflight.py
places where a Spike 2 card keeps its games partition."""

import os
import queue
import sys
import time
from types import SimpleNamespace

import pytest

from pinball_decryptor.core import ext4_grow
from pinball_decryptor.core import staged_changes
from pinball_decryptor.core import staged_originals
from pinball_decryptor.core import video
from pinball_decryptor.core.messages import DoneMsg, LogMsg
from pinball_decryptor.core.registry import (Manufacturer, get_manufacturer,
                                             load_plugins)
from pinball_decryptor.plugins.stern import card_size as cs
from pinball_decryptor.plugins.stern import engine
from pinball_decryptor.plugins.stern import manufacturer as stern_mfr
from tests.test_stern_space_preflight import (V1, V2, _budget, _locate_tiny,
                                              _parts, _stern_card, _tiny_fs)

# Windows and Linux: the prerequisite strip's ext4 row decides, not macOS's
# e2fsprogs
pytestmark = pytest.mark.usefixtures("not_macos")

#: the start of an MP4: a file the machine may play as it is
_MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
#: the ext4 driver's row on the prerequisite strip, as the tests name it
ROW = "ext4 row"
KNOWN = {ROW: True}


@pytest.fixture()
def hook(monkeypatch, tmp_path):
    """The Stern plugin in its Spike 2 era, on the tiny card, with ffprobe
    stubbed (``probe.info`` is what every probe answers; ``probe.seen`` the
    files it was asked about), no SD card size and no port."""
    load_plugins()
    mfr = get_manufacturer("stern")
    era = mfr.current_era
    mfr.set_era("spike2")
    monkeypatch.setattr(engine, "_locate", _locate_tiny)
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: _parts())
    monkeypatch.setattr(stern_mfr, "_EXT4_GROW_PREREQS",
                        (SimpleNamespace(name=ROW),))
    # macOS asks its e2fsprogs instead of the strip
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "ok"))
    monkeypatch.delenv(cs.ENV, raising=False)
    monkeypatch.delenv(cs.FIXED_ENV, raising=False)
    probe = SimpleNamespace(info=None, seen=[])

    def _detect(path):
        probe.seen.append(os.path.basename(str(path)))
        return probe.info
    monkeypatch.setattr(video, "detect_video_info", _detect)
    card = _stern_card(tmp_path / "orig.raw", _tiny_fs(free=200))
    yield SimpleNamespace(mfr=mfr, card=str(card), tmp=tmp_path, probe=probe)
    mfr.set_era(era)


def _project(tmp, videos, **toggles):
    """A project whose Video tab assigned *videos*: ``{card path: (your
    file's name, its bytes)}``, nothing staged yet (each slot still holds its
    3 KB stock clip).  A name ending .mp4 or .mov is an MP4/QuickTime file,
    anything else is not.  *toggles* go into the sidecar as the tab saves
    them."""
    proj = tmp / "project"
    (proj / "video").mkdir(parents=True, exist_ok=True)
    mine = tmp / "mine"
    mine.mkdir(exist_ok=True)
    rows, assigned = [], {}
    for i, (card_path, (name, n)) in enumerate(sorted(videos.items())):
        fname = "%d.mp4" % i
        rows.append("%s\t/%s" % (fname, card_path))
        (proj / "video" / fname).write_bytes(b"S" * 3000)
        head = _MP4 if name.endswith((".mp4", ".mov")) else b""
        (mine / name).write_bytes(head + b"M" * (n - len(head)))
        assigned["video/" + fname] = str(mine / name)
    (proj / "video" / "manifest.txt").write_text("\n".join(rows) + "\n")
    staged_changes.save(str(proj), dict({"video": assigned}, **toggles))
    return proj


def _ask(hook, proj, prereqs=KNOWN, **kw):
    t = time.perf_counter()
    why = hook.mfr.write_preflight(hook.card, assets_dir=str(proj),
                                   prereqs=prereqs, **kw)
    return why, time.perf_counter() - t


def _engine_refusal(hook, proj):
    """The engine pre-flight's own refusal for *proj*, once each clip is
    staged as a copy of the user's file (what "as-is" does)."""
    for fname, src in _assigned(proj):
        with open(src, "rb") as f:
            (proj / "video" / fname).write_bytes(f.read())
    with open(hook.card, "rb") as disk_f, \
            engine._SpaceScope(_budget(hook.card)), \
            pytest.raises(cs.WontFit) as ei:
        engine._compute_patches(disk_f, _parts(), str(proj),
                                lambda *a, **k: None, None, lambda: False)
    return str(ei.value)


def _assigned(proj):
    return [(rel[len("video/"):], src) for rel, src
            in sorted(staged_changes.load(str(proj))["video"].items())]


# ---- what refuses --------------------------------------------------------------

def test_videos_that_cannot_fit_as_they_are_refuse_in_the_engines_words(
        hook, monkeypatch):
    # two MP4s of 150 KB over 3 KB slots: 290 blocks more, 190 usable
    proj = _project(hook.tmp, {V1: ("a.mp4", 150_000), V2: ("b.mp4", 150_000)})
    why, took = _ask(hook, proj)
    assert why is not None and took < 1.0
    assert why.startswith("This build needs at least 297 KB on the card's "
                          "games partition, which has 195 KB free, so the "
                          "build was stopped before anything was converted or "
                          "written.")
    assert "Build it for a 16 GB SD card if the SD card in the machine" in why
    # the build's own pre-flight gives the same figures and size, and says
    # where it stopped: after the Build converted what it had to
    for step in ("_prepare_video_patches", "_extract_inputs"):
        monkeypatch.setattr(engine, step, lambda *a, **k: pytest.fail(step))
    late = _engine_refusal(hook, proj)
    assert late.startswith("This build needs 297 KB on the card's games "
                           "partition, which has 195 KB free, so the build was "
                           "stopped before anything was written to the card "
                           "image.")
    assert why.split(" written.", 1)[1] == late.split(
        " kept in the project.", 1)[1]


def test_use_my_files_as_is_counts_each_file_at_its_own_size(hook):
    # copied through as they are: nothing to probe
    proj = _project(hook.tmp, {V1: ("a.mp4", 150_000), V2: ("b.mp4", 150_000)},
                    video_no_conversion=True)
    assert _ask(hook, proj)[0].startswith("This build needs at least 297 KB ")
    assert hook.probe.seen == []            # nothing to probe
    # ... one clip's own "as-is" answer, the other converted: only the first
    proj = _project(hook.tmp, {V1: ("a.mkv", 250_000), V2: ("b.mkv", 250_000)},
                    video_asis_slots={"video/0.mp4": True})
    staged_changes.save(str(proj), dict(staged_changes.load(str(proj)),
                                        video_no_conversion=False))
    # the file "as-is" must be the slot's own container, or staging refuses
    assert _ask(hook, proj)[0] is None
    os.replace(hook.tmp / "mine" / "a.mkv", hook.tmp / "mine" / "a.mp4")
    saved = staged_changes.load(str(proj))
    saved["video"]["video/0.mp4"] = str(hook.tmp / "mine" / "a.mp4")
    staged_changes.save(str(proj), saved)
    why = _ask(hook, proj)[0]
    assert why.startswith("This build needs at least 249 KB ")
    assert "0.mp4 (+" in why and "1.mp4" not in why


def test_a_converted_copy_already_made_counts_the_smaller_of_the_two(hook):
    """The machine can't play the file as it is (HEVC), so the converted copy
    goes on; one the Video tab already made, over a slot staged before and
    since the file was assigned, counts at the smaller size."""
    hook.probe.info = SimpleNamespace(vcodec="hevc", pix_fmt="yuv420p",
                                      width=0, height=0, fps=0.0, profile="")
    proj = _project(hook.tmp, {V1: ("a.mp4", 400_000)},
                    video_no_conversion=False)
    # nothing converted yet: its size isn't known, so nothing is refused
    assert _ask(hook, proj)[0] is None
    staged = proj / "video" / "0.mp4"
    assert staged_originals.snapshot(str(proj), "video/0.mp4", None)
    staged.write_bytes(b"C" * 250_000)
    later = time.time() + 5
    os.utime(staged, (later, later))
    why = _ask(hook, proj)[0]
    assert why.startswith("This build needs at least 249 KB ")
    # the file that goes on may be the 400 KB one: no size is named as enough
    assert ("It may need more: 1 replaced video(s) can't be sized until the "
            "build converts them. Only a 16 GB SD card or bigger could hold "
            "it") in why
    # a copy older than the assignment is from another file: not counted
    early = time.time() - 3600
    os.utime(staged, (early, early))
    assert _ask(hook, proj)[0] is None


# ---- what counts nothing -----------------------------------------------------------

def test_a_refusal_that_left_clips_out_names_no_size_as_enough(
        hook, monkeypatch):
    """An MP4 of 300 KB goes on as it is, and an .mkv that converts to
    200 KB counts nothing before it is converted.  The hook's need is a
    floor: 16 GB holds the floor, but the build needs 32 GB once the .mkv is
    converted, so the hook names 16 GB only as the smallest that could hold
    it, and says a clip wasn't counted."""
    import collections
    rooms = collections.OrderedDict(
        [("8G", 195 * 1024), ("16G", 350 * 1024), ("32G", 10 << 20)])
    real = cs.room_by_class

    def fake(layout, space, classes, route=cs.ROUTE_MOUNT):
        got = real(layout, space, classes, route)
        return collections.OrderedDict((c, rooms[c]) for c in got)
    monkeypatch.setattr(cs, "room_by_class", fake)
    monkeypatch.setattr(cs, "offered", lambda p: ["16G", "32G"])
    proj = _project(hook.tmp, {V1: ("a.mp4", 300_000), V2: ("b.mkv", 3000)})
    why, _t = _ask(hook, proj)
    assert why.startswith("This build needs at least 298 KB on the card's "
                          "games partition, which has 195 KB free, so the "
                          "build was stopped before anything was converted "
                          "or written. It may need more: 1 replaced video(s) "
                          "can't be sized until the build converts them. "
                          "Only a 16 GB SD card or bigger could hold it: if "
                          "the SD card in the machine is that big, pick it "
                          "under SD card size on the Write tab.")
    assert "Build it for" not in why
    # every clip sized: the size that fits is named as enough
    proj = _project(hook.tmp / "b", {V1: ("a.mp4", 300_000)})
    why, _t = _ask(hook, proj)
    assert "may need more" not in why
    assert "Build it for a 16 GB SD card if the SD card in the machine" in why


def test_a_file_that_is_always_converted_counts_nothing(hook):
    proj = _project(hook.tmp, {V1: ("a.mkv", 900_000), V2: ("b.avi", 900_000)},
                    video_no_conversion=False)
    assert _ask(hook, proj)[0] is None
    assert hook.probe.seen == []


def test_a_file_the_machine_cant_play_as_it_is_counts_nothing(hook):
    hook.probe.info = SimpleNamespace(vcodec="hevc", pix_fmt="yuv420p",
                                      width=0, height=0, fps=0.0, profile="")
    proj = _project(hook.tmp, {V1: ("a.mp4", 900_000)},
                    video_no_conversion=False)
    assert _ask(hook, proj)[0] is None


def test_a_build_that_fits_at_full_size_probes_nothing(hook):
    proj = _project(hook.tmp, {V1: ("a.mp4", 100_000)})
    assert _ask(hook, proj)[0] is None
    assert hook.probe.seen == []


def test_an_update_that_fits_the_build_already_there_is_not_refused(
        hook, monkeypatch):
    """The build at the output has room this one doesn't have from the
    original; write_image updates it, so nothing is refused."""
    out = _stern_card(hook.tmp / "out.raw", _tiny_fs(free=400))
    monkeypatch.setattr(engine, "read_build_manifest",
                        lambda p: {"version": 1} if p == str(out) else {})
    proj = _project(hook.tmp, {V2: ("b.mp4", 250_000)})
    assert _ask(hook, proj, output_path=str(out))[0] is None
    # asked to build whole, it is measured from the original and refused
    why = _ask(hook, proj, output_path=str(out), update=False)[0]
    assert why.startswith("This build needs at least 249 KB ")


# ---- when it doesn't ask ----------------------------------------------------------

@pytest.mark.skipif(sys.platform == "darwin",
                    reason="macOS asks its e2fsprogs, not the strip")
@pytest.mark.parametrize("prereqs", [None, {}, {ROW: False}, {"ffmpeg": True}],
                         ids=["no-strip", "still-checking", "no-ext4", "other"])
def test_not_knowing_whether_files_are_copied_whole_refuses_nothing(
        hook, monkeypatch, prereqs):
    def _no_wsl():
        pytest.fail("the hook must not start WSL to find out")
    monkeypatch.setattr(ext4_grow, "available", _no_wsl)
    proj = _project(hook.tmp, {V1: ("a.mp4", 900_000)})
    assert _ask(hook, proj, prereqs=prereqs)[0] is None


def test_a_port_refuses_nothing(hook, monkeypatch):
    monkeypatch.setenv(cs.FIXED_ENV, "1")
    proj = _project(hook.tmp, {V1: ("a.mp4", 900_000)})
    assert _ask(hook, proj)[0] is None


def test_without_the_project_folder_nothing_is_measured(hook):
    assert hook.mfr.write_preflight(hook.card, prereqs=KNOWN) is None


def test_a_grow_proves_whole_copies_and_is_measured_at_its_size(
        hook, monkeypatch):
    """A bigger SD card size: its tools check has just shown this computer
    copies files whole (no strip answer needed), and the room is the grown
    partition's."""
    monkeypatch.setattr(cs, "supported", lambda: True)
    monkeypatch.setattr(cs, "_E2fs", lambda: None)
    monkeypatch.setenv(cs.ENV, "16G")
    seen = []
    real = engine.space_floor

    def _floor(orig, grow_to=None, *a, **k):
        seen.append(grow_to)
        return real(orig, grow_to, *a, **k)
    monkeypatch.setattr(engine, "space_floor", _floor)
    proj = _project(hook.tmp, {V1: ("a.mp4", 150_000), V2: ("b.mp4", 150_000)})
    assert _ask(hook, proj, prereqs=None)[0] is None
    assert seen == ["16G"]


# ---- the Build's worker thread ----------------------------------------------------

class _Recorder(Manufacturer):
    key = "recorder"
    display = "Recorder"

    def __init__(self, why=None):
        self.why = why
        self.asked = []

    def detect(self, path):
        return None

    def write_preflight(self, original_path, **kw):
        self.asked.append((original_path, kw))
        return self.why


def _app(mfr, rows):
    from pinball_decryptor import app as appmod
    a = appmod.App.__new__(appmod.App)
    a.msg_queue = queue.Queue()
    a._staging_failures = []
    a._cancel_requested = False
    a._current_mfr = mfr
    a.ctx = SimpleNamespace(store=SimpleNamespace(
        get=lambda ns, key: rows if (ns, key) == ("shell", "prereqs")
        else None))
    a.pipeline = SimpleNamespace(
        output_path="OUT.raw", update=True,
        run=lambda: pytest.fail("the build must not run"))
    return a


def test_the_build_hands_the_hook_what_it_knows_and_logs_a_refusal(
        monkeypatch):
    mfr = _Recorder(why="This build needs 1.61 GB more.")
    a = _app(mfr, [{"name": "WSL2", "state": "ok"},
                   {"name": "ffmpeg", "state": "missing"},
                   {"name": "unicorn", "state": "checking"}])
    staged = []
    for name in ("_stage_pending_audio", "_stage_pending_image"):
        monkeypatch.setattr(a, name, lambda d: staged.append(1) or (0, 0, []))
    monkeypatch.setattr(a, "_stage_pending_video",
                        lambda d, cancel_cb=None: staged.append(1)
                        or (0, 0, []))
    a._run_pipeline_with_audio("ASSETS", original="orig.raw")
    assert mfr.asked == [("orig.raw", {
        "assets_dir": "ASSETS", "output_path": "OUT.raw", "update": True,
        "prereqs": {"WSL2": True, "ffmpeg": False}})]
    assert staged == []
    msgs = []
    while not a.msg_queue.empty():
        msgs.append(a.msg_queue.get_nowait())
    assert [(m.text, m.level) for m in msgs if isinstance(m, LogMsg)] == [
        ("Not building: This build needs 1.61 GB more.", "error")]
    [done] = [m for m in msgs if isinstance(m, DoneMsg)]
    assert (done.success, done.summary) == (False,
                                            "This build needs 1.61 GB more.")


def test_a_direct_sd_write_never_asks_the_hook(monkeypatch):
    mfr = _Recorder(why="never")
    a = _app(mfr, [])
    ran = []
    a.pipeline = SimpleNamespace(run=lambda: ran.append(1))
    for name in ("_stage_pending_audio", "_stage_pending_image"):
        monkeypatch.setattr(a, name, lambda d: (0, 0, []))
    monkeypatch.setattr(a, "_stage_pending_video",
                        lambda d, cancel_cb=None: (0, 0, []))
    a._run_pipeline_with_audio("ASSETS")         # no original: a direct write
    assert mfr.asked == [] and ran == [1]
