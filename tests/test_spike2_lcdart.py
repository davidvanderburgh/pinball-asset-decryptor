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
    _seed(out, "54.png", "54.gif")
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
    assert rec.calls[1][-1].endswith("54.gif.tmp"), \
        "gif not atomic: %r" % rec.calls[1]
    gi = rec.calls[1]
    assert "-gifflags" in gi and \
        gi[gi.index("-gifflags") + 1] == "-offsetting-transdiff", \
        "the delta-encode trap guard is gone: %r" % gi
    assert os.path.isfile(os.path.join(out, "54.png"))
    assert os.path.isfile(os.path.join(out, "54.gif"))
    assert not [n for n in os.listdir(out) if n.endswith(".tmp")]


def test_upgrade_runs_only_the_gif_stage(rigged, monkeypatch):
    store, out = rigged
    _seed(out, "54.png")                             # pre-GIF-era cache
    with open(os.path.join(store, "54.asset"), "wb") as f:
        f.write(b"h264")
    rec = RunRecorder(rc=0, make_output=True)
    monkeypatch.setattr(lcdart.subprocess, "run", rec)
    assert lcdart.main() == 0
    assert len(rec.calls) == 1 and rec.calls[0][-1].endswith("54.gif.tmp")


def test_gif_failure_cleans_tmp_keeps_still_exits_2(rigged, monkeypatch):
    store, out = rigged
    _seed(out, "54.png")
    with open(os.path.join(store, "54.asset"), "wb") as f:
        f.write(b"h264")
    rec = RunRecorder(rc=1, make_output=True)        # dies, tmp left behind
    monkeypatch.setattr(lcdart.subprocess, "run", rec)
    assert lcdart.main() == 2, "gif failure must not report success"
    assert not os.path.isfile(os.path.join(out, "54.gif"))
    assert not [n for n in os.listdir(out) if n.endswith(".tmp")], \
        "failed encode left its .tmp behind"
    assert os.path.isfile(os.path.join(out, "54.png")), "still lost"
    with open(os.path.join(out, "lcdart.log")) as f:
        assert "gif stage failed" in f.read()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="no ffmpeg")
def test_transdiff_flag_survives_real_ffmpeg(rigged, monkeypatch):
    """Run lcdart's ACTUAL gif command and standalone-decode a late frame:
    with delta encoding (the flag deleted) the static background decodes
    TRANSPARENT and this fails - PIL-authored panel-test GIFs can never
    catch that, because PIL writes full frames."""
    Image = pytest.importorskip("PIL.Image")
    tk = pytest.importorskip("tkinter")
    store, out = rigged
    frames = []
    for i in range(8):                               # static bg, moving box
        im = Image.new("RGB", (240, 180), (0, 0, 200))
        for x in range(30 + i * 12, 50 + i * 12):
            for y in range(80, 100):
                im.putpixel((x, y), (255, 255, 255))
        frames.append(im)
    frames[0].save(os.path.join(store, "54.asset"), format="GIF",
                   save_all=True, append_images=frames[1:], loop=0,
                   duration=100)
    assert lcdart.main() == 0
    gif = os.path.join(out, "54.gif")
    assert os.path.isfile(gif)
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip("Tk unavailable: %s" % exc)
    try:
        root.attributes("-alpha", 0)
        late = tk.PhotoImage(file=gif, format="gif -index 3")
        assert not late.transparency_get(5, 5), \
            "late frame's static background is transparent: delta " \
            "encoding is back (the -gifflags guard is not working)"
    finally:
        root.destroy()
