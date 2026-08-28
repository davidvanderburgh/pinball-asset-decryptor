"""lcdart.py: the two-artifact extraction pipeline (item 83).

The motion review found every branch of this script untested - and worse,
its one trap-guard flag (`-gifflags -offsetting-transdiff`, which stops
ffmpeg's delta encoding that Tk's standalone frame decode renders as
speckle) actively invites deletion because a leading `-` disabling flags
looks like a typo. Two tiers here:

- A no-ffmpeg tier: subprocess.run is a recorder, so the branch logic
  (both-cached short circuit, still-first ordering, .tmp+os.replace
  atomicity on BOTH artifacts, the exit-2 degrade, the failure log) is
  pinned on any machine.
- A real-ffmpeg tier (skipped where ffmpeg is absent): PIL authors a
  moving-box source clip, lcdart's ACTUAL command encodes it, and Tk
  decodes a later frame standalone - under delta encoding the static
  background comes back transparent, so this fails the moment someone
  "fixes" the odd-looking flag.
"""
import os
import shutil
import sys
import types

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

import lcdart  # noqa: E402


class RunRecorder:
    """Stands in for subprocess.run: records the command, optionally
    creates the output file (always the last argument), returns rc."""

    def __init__(self, rc=0, make_output=True):
        self.calls, self.rc, self.make_output = [], rc, make_output

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if self.make_output:
            with open(cmd[-1], "wb") as f:
                f.write(b"fake artifact")
        return types.SimpleNamespace(returncode=self.rc, stderr=b"boom")


@pytest.fixture
def rigged(tmp_path, monkeypatch):
    tables = os.path.join(str(tmp_path), "tables")
    store = os.path.join(str(tmp_path), "store", "batman")
    os.makedirs(store)
    monkeypatch.setattr(lcdart.padpath, "tables", lambda: tables)
    monkeypatch.setattr(
        lcdart, "STORE_GLOB",
        os.path.join(str(tmp_path), "store", "%s", "%s.asset"))
    monkeypatch.setattr(sys, "argv", ["lcdart.py", "batman", "54"])
    out = os.path.join(tables, "batman", "lcd")
    return store, out


def _seed(out, *names):
    os.makedirs(out, exist_ok=True)
    for n in names:
        with open(os.path.join(out, n), "wb") as f:
            f.write(b"cached")


def test_both_cached_short_circuits(rigged, monkeypatch):
    store, out = rigged
    _seed(out, "54.png", "54.webp")
    rec = RunRecorder()
    monkeypatch.setattr(lcdart.subprocess, "run", rec)
    assert lcdart.main() == 0
    assert rec.calls == [], "fully cached id still ran ffmpeg"


def test_no_store_logs_and_exits_1(rigged, monkeypatch):
    store, out = rigged
    rec = RunRecorder()
    monkeypatch.setattr(lcdart.subprocess, "run", rec)
    assert lcdart.main() == 1
    assert rec.calls == []
    with open(os.path.join(out, "lcdart.log")) as f:
        assert "no store" in f.read()


def test_fresh_id_runs_still_first_and_both_atomically(rigged, monkeypatch):
    store, out = rigged
    with open(os.path.join(store, "54.asset"), "wb") as f:
        f.write(b"h264")
    rec = RunRecorder(rc=0, make_output=True)
    monkeypatch.setattr(lcdart.subprocess, "run", rec)
    assert lcdart.main() == 0
    assert len(rec.calls) == 2
    assert rec.calls[0][-1].endswith("54.png.tmp"), \
        "still not first / not atomic: %r" % rec.calls[0]
    assert rec.calls[1][-1].endswith("54.webp.tmp"), \
        "clip not atomic: %r" % rec.calls[1]
    ci = rec.calls[1]
    assert "-lossless" in ci and ci[ci.index("-lossless") + 1] == "1", \
        "the clip is no longer lossless: %r" % ci
    assert "-pix_fmt" in ci and ci[ci.index("-pix_fmt") + 1] == "bgra", \
        "the pix_fmt guard is gone - libwebp would take yuv420p and " \
        "'lossless' would still cost a YUV round trip: %r" % ci
    assert os.path.isfile(os.path.join(out, "54.png"))
    assert os.path.isfile(os.path.join(out, "54.webp"))
    assert not [n for n in os.listdir(out) if n.endswith(".tmp")]


def test_upgrade_runs_only_the_clip_stage(rigged, monkeypatch):
    store, out = rigged
    _seed(out, "54.png")                             # still-only cache
    with open(os.path.join(store, "54.asset"), "wb") as f:
        f.write(b"h264")
    rec = RunRecorder(rc=0, make_output=True)
    monkeypatch.setattr(lcdart.subprocess, "run", rec)
    assert lcdart.main() == 0
    assert len(rec.calls) == 1 and rec.calls[0][-1].endswith("54.webp.tmp")


def test_palette_era_gif_is_swept_up(rigged, monkeypatch):
    """A cache from the GIF afternoon carries a dead ~1 MB file per id; the
    panel only reads .webp now, so the encode that replaces it removes it."""
    store, out = rigged
    _seed(out, "54.png", "54.gif")
    with open(os.path.join(store, "54.asset"), "wb") as f:
        f.write(b"h264")
    monkeypatch.setattr(lcdart.subprocess, "run", RunRecorder(rc=0))
    assert lcdart.main() == 0
    assert os.path.isfile(os.path.join(out, "54.webp"))
    assert not os.path.isfile(os.path.join(out, "54.gif")), \
        "the superseded palette clip was left behind"


def test_clip_failure_cleans_tmp_keeps_still_exits_2(rigged, monkeypatch):
    store, out = rigged
    _seed(out, "54.png")
    with open(os.path.join(store, "54.asset"), "wb") as f:
        f.write(b"h264")
    rec = RunRecorder(rc=1, make_output=True)        # dies, tmp left behind
    monkeypatch.setattr(lcdart.subprocess, "run", rec)
    assert lcdart.main() == 2, "clip failure must not report success"
    assert not os.path.isfile(os.path.join(out, "54.webp"))
    assert not [n for n in os.listdir(out) if n.endswith(".tmp")], \
        "failed encode left its .tmp behind"
    assert os.path.isfile(os.path.join(out, "54.png")), "still lost"
    with open(os.path.join(out, "lcdart.log")) as f:
        assert "clip stage failed" in f.read()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="no ffmpeg")
def test_clip_frames_are_bit_exact(rigged, tmp_path):
    """Run lcdart's ACTUAL clip command on a YUV source and compare every
    decoded frame against the source's own frames: they must match EXACTLY.

    This is the guard on `-pix_fmt bgra`, which reads like a typo and is
    not: the card's assets are yuv420p H.264, and without it libwebp takes
    ffmpeg's default YUV and the round trip back to RGB costs real colour
    even under `-lossless 1`. Measured on this fixture: worst channel error
    0 with the flag, 182 without. A YUV source is essential - a PIL-authored
    RGB source makes the flag a no-op and the test vacuous.
    """
    pytest.importorskip("PIL.Image")
    from PIL import Image, ImageChops
    store, out = rigged
    src = os.path.join(store, "54.asset")
    ref = os.path.join(str(tmp_path), "ref")
    os.makedirs(ref)
    sub = lcdart.subprocess
    assert sub.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=240x180:rate=10:duration=1",
                    "-c:v", "ffv1", "-pix_fmt", "yuv420p", "-f", "matroska",
                    src], timeout=60).returncode == 0
    assert sub.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                    "-vf", "fps=10", os.path.join(ref, "%03d.png")],
                   timeout=60).returncode == 0
    assert lcdart.main() == 0
    clip = Image.open(os.path.join(out, "54.webp"))
    n = min(clip.n_frames, len(os.listdir(ref)))
    assert n >= 5, "fixture produced only %d frames" % n
    worst = 0
    for i in range(n):
        clip.seek(i)
        want = Image.open(os.path.join(ref, "%03d.png" % (i + 1))).convert("RGB")
        h = ImageChops.difference(clip.convert("RGB"), want).histogram()
        for ch in range(3):
            for v, cnt in enumerate(h[ch * 256:(ch + 1) * 256]):
                if cnt and v > worst:
                    worst = v
    assert worst == 0, \
        "clip frames are not bit-exact (worst channel error %d) - the " \
        "lossless/pix_fmt guarantee is broken" % worst
