"""PAD-103: running the user's edits without rebuilding the card image.

Three layers, and each is tested where it can be tested honestly:

  * ``stern.engine.write_overrides`` — the bytes.  A fake ext4 reader
    (``tests/_ext4_fake``) stands in for the card, exactly as the Partition
    Explorer tests use it, and the patch computation is stubbed: what is under
    test here is the mapping from the flat disk-write list BACK to the files
    those writes live in, which is the one piece this feature adds to a write
    path that is otherwise the Write tab's own.
  * the Emulate tab's policy — where a set is kept and when the staged one may
    be reused.  Pure functions, no Tk.
  * the tab itself — that ticking the box puts ``PAD_OVERRIDE_DIR`` in front of
    ``watch.sh`` and that a refusal never launches anything.

The rig's own half (``overrides.sh`` staging, ``run_game.sh``'s bind loop) is
Linux and is checked here only as script TEXT — the behaviour was exercised in
a real mount namespace under WSL, which no test on a Windows CI runner can do.
"""

import os
import pathlib

import pytest

from tests._ext4_fake import FakeExt4Reader, materialize_files

from pinball_decryptor.gui import emulate_tab
from pinball_decryptor.plugins.stern import engine

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu"

# One title's worth of card: the sound bank, a video asset, the firmware, and
# the .sidx manifest that lives BESIDE the title rather than inside it.
CARD_TREE = {
    "turtles_pro": {
        "image.bin": b"STOCK-SOUND-BANK-" + b"." * 64,
        "game": b"\x7fELF" + b"F" * 32,
        "data": {"boot_display_cmd": b"-invert"},
        "assets": {"lcd": {"1.asset": b"STOCK-VIDEO-" + b"v" * 32}},
    },
    "spk": {"index": {"turtles_pro.sidx": b"FINF" + b"s" * 40}},
}


class _Reader(FakeExt4Reader):
    """The fake, plus the two attributes the override path reads."""
    base = 0

    def node(self, path):
        for p, _ino, n in self.iter_regular_files(min_size=1):
            if p == path:
                return n
        raise KeyError(path)


@pytest.fixture()
def card(monkeypatch, tmp_path):
    """A stubbed card: the fake reader, and a patch computation we control.

    ``_compute_patches`` is the Write tab's own machinery (numpy, the codec
    oracle, a real card) and is deliberately NOT re-tested here; the fixture
    hands ``write_overrides`` a write list and a grow plan directly, which is
    the contract between them.
    """
    reader = _Reader(CARD_TREE)
    img = tmp_path / "turtles_pro-1_59_0.Release.8G.sdcard.raw"
    img.write_bytes(bytes(4096))
    # The card's OWN bytes, at the offsets this reader maps the files to.
    # Patching a set in place reads them back out of the image to undo what
    # the previous build wrote, so the stub image the first tests got away
    # with is not enough any more.
    materialize_files(str(img), CARD_TREE)

    state = {"writes": [], "grow": None,
             "counts": (1, 0, 0, 0), "audio": None, "val": None}

    def fake_compute(disk_f, parts, assets_dir, log, progress, cancel,
                     phase=None, label=None, dest_is_device=False):
        return (state["writes"], state["counts"], state["grow"],
                state["audio"], state["val"])

    monkeypatch.setattr(engine, "_compute_patches", fake_compute)
    monkeypatch.setattr(engine, "_locate", lambda f, p: (reader, None, None))
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [(0, 1 << 30)])
    return type("Card", (), {"reader": reader, "img": img, "state": state})


def _disk(reader, path, off):
    return reader.disk_ranges(reader.node(path), off, 1)[0][0]


def _no_extracts(card, monkeypatch):
    """Count calls to the reader's extract_file, which is the whole file.

    The number that says whether a build patched the set it found or laid a
    new one down: extracting is what costs 1.4 GB of I/O for a changed
    callout, and not extracting is the point of the second build.
    """
    calls = []
    real = card.reader.extract_file

    def counted(node, dest, progress=None):
        calls.append(dest)
        return real(node, dest)

    monkeypatch.setattr(card.reader, "extract_file", counted)
    return calls


def _delta(out):
    """The staging list as ``[(kind, rest), ...]``, header lines included."""
    raw = (out / engine.OVERRIDE_DELTA).read_bytes()
    assert b"\r" not in raw          # a shell in WSL reads this
    lines = raw.decode("utf-8").splitlines()
    return [tuple(ln.split(" ", 1)) for ln in lines if not ln.startswith("#")]


# --------------------------------------------------------------------------
# The bytes
# --------------------------------------------------------------------------

def test_a_write_lands_in_the_file_it_came_from(card, tmp_path):
    """The set is the touched files, patched — and nothing else."""
    r = card.reader
    card.state["writes"] = [
        (_disk(r, "/turtles_pro/image.bin", 6), b"MINE!"),
        (_disk(r, "/spk/index/turtles_pro.sidx", 4), b"XXXX"),
    ]
    out = tmp_path / "ovr"
    counts, _mode, _val, files = engine.write_overrides(
        str(card.img), str(tmp_path / "assets"), str(out))

    assert counts == (1, 0, 0, 0)
    assert sorted(p for p, _n in files) == ["/spk/index/turtles_pro.sidx",
                                            "/turtles_pro/image.bin"]
    # Laid out as the games partition is, so the rig can bind each one at
    # games/<the same relative path>.
    bank = out / "turtles_pro" / "image.bin"
    assert bank.read_bytes() == b"STOCK-MINE!-BANK-" + b"." * 64
    assert (out / "spk" / "index" / "turtles_pro.sidx").read_bytes() \
        == b"FINFXXXX" + b"s" * 36
    # The files the edit did not touch are NOT in the set: that is the whole
    # saving, and a stray one would be bound over the card for no reason.
    assert not (out / "turtles_pro" / "game").exists()
    assert not (out / "turtles_pro" / "assets").exists()


def test_a_write_split_across_two_extents_is_reassembled(card, tmp_path,
                                                         monkeypatch):
    """A patch that straddles an extent boundary still lands as one file.

    The producers split their writes on the extent map on the way out, so each
    normally lies inside one run — but nothing in the write list SAYS so, and
    a mapper that assumed it would silently drop the tail of any that did not.
    """
    r = card.reader
    node = r.node("/turtles_pro/image.bin")
    real = r.disk_ranges

    def two_runs(inode, file_off, length):
        if inode is not node or length < 2:
            return real(inode, file_off, length)
        # Same bytes, same places — just described as two runs.
        first = real(inode, file_off, length // 2)
        second = real(inode, file_off + length // 2, length - length // 2)
        return first + second

    monkeypatch.setattr(r, "disk_ranges", two_runs)
    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 0),
                             b"ABCDEFGH")]
    out = tmp_path / "ovr"
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    assert (out / "turtles_pro" / "image.bin").read_bytes()[:8] == b"ABCDEFGH"


def test_an_untraceable_write_refuses_the_whole_set(card, tmp_path):
    """A partial set is worse than none: it would run as if it were whole."""
    card.state["writes"] = [(1 << 40, b"nowhere")]
    with pytest.raises(RuntimeError) as exc:
        engine.write_overrides(str(card.img), str(tmp_path / "a"),
                               str(tmp_path / "ovr"))
    assert "could not be traced back" in str(exc.value)
    assert not (tmp_path / "ovr" / engine.OVERRIDE_MANIFEST).exists()


def test_a_second_build_patches_the_set_it_finds(card, tmp_path, monkeypatch):
    """The whole point: changing an edit must not re-extract the sound bank.

    A card file is 1.4 GB on a real Spike 2 card, and re-extracting it is
    both halves of the cost this feature exists to avoid - the write here,
    and the copy the rig would then have to make across 9p.
    """
    r = card.reader
    out = tmp_path / "ovr"
    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 6), b"MINE!")]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    first = engine.read_override_manifest(str(out))

    calls = _no_extracts(card, monkeypatch)
    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 6), b"OTHR!")]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))

    assert calls == []
    assert (out / "turtles_pro" / "image.bin").read_bytes() \
        == b"STOCK-OTHR!-BANK-" + b"." * 64
    second = engine.read_override_manifest(str(out))
    assert second["parent"] == first["generation"]
    assert second["generation"] != first["generation"]


def test_an_edit_taken_back_gets_the_card_bytes_back(card, tmp_path,
                                                     monkeypatch):
    """Patching in place has to be able to UNDO, or a set only ever grows.

    The file is not rewritten from the card, so the bytes of an edit the user
    has since dropped would otherwise stay in it for ever - and be bound over
    the card on every run after that.
    """
    r = card.reader
    out = tmp_path / "ovr"
    card.state["writes"] = [
        (_disk(r, "/turtles_pro/image.bin", 0), b"XX"),
        (_disk(r, "/turtles_pro/image.bin", 6), b"MINE!"),
    ]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    assert (out / "turtles_pro" / "image.bin").read_bytes()[:2] == b"XX"

    calls = _no_extracts(card, monkeypatch)
    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 6), b"MINE!")]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))

    assert calls == []
    # Stock at the front again, the surviving edit still applied.
    assert (out / "turtles_pro" / "image.bin").read_bytes() \
        == b"STOCK-MINE!-BANK-" + b"." * 64


def test_a_file_that_leaves_the_set_is_deleted_and_written_down(card, tmp_path,
                                                                monkeypatch):
    """The rig has to be told, since it is not re-copying the set either."""
    r = card.reader
    out = tmp_path / "ovr"
    card.state["writes"] = [
        (_disk(r, "/turtles_pro/image.bin", 0), b"S"),
        (_disk(r, "/spk/index/turtles_pro.sidx", 0), b"F"),
    ]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))

    calls = _no_extracts(card, monkeypatch)
    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 0), b"S")]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))

    assert calls == []
    assert not (out / "spk").exists()          # and the folder with it
    data = engine.read_override_manifest(str(out))
    assert data["removed"] == ["/spk/index/turtles_pro.sidx"]
    assert ("remove", "spk/index/turtles_pro.sidx") in _delta(out)


def test_the_delta_names_only_the_bytes_that_moved(card, tmp_path):
    """What the rig copies, and what it must not have to copy."""
    r = card.reader
    out = tmp_path / "ovr"
    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 6), b"MINE!")]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    # Built from scratch, so there is nothing to patch it onto: whole files.
    assert ("parent", "-") in _delta(out)
    assert ("whole", "turtles_pro/image.bin") in _delta(out)

    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 6), b"OTHR!")]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    kinds = _delta(out)
    assert ("whole", "turtles_pro/image.bin") not in kinds
    # One range, covering the five bytes this build and the last one wrote,
    # and the path LAST so a card path with a space in it still parses.
    ranges = [rest for kind, rest in kinds if kind == "range"]
    assert len(ranges) == 1
    off, length, rel = ranges[0].split(" ", 2)
    assert rel == "turtles_pro/image.bin"
    assert int(off) == 6 and int(length) == 5


def test_a_set_touched_behind_our_back_is_built_again(card, tmp_path,
                                                      monkeypatch):
    """Patching assumes the set is what the manifest says it is.

    If it is not - a half-copied file, a temp cleaner part way through, the
    user poking at it - then nothing in the manifest describes what is in
    the folder, and the only honest answer is to build it again.
    """
    r = card.reader
    out = tmp_path / "ovr"
    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 0), b"S")]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    with open(out / "turtles_pro" / "image.bin", "ab") as f:
        f.write(b"?")                          # now the wrong size

    calls = _no_extracts(card, monkeypatch)
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    assert len(calls) == 1
    assert (out / "turtles_pro" / "image.bin").read_bytes() \
        == b"STOCK" + b"-SOUND-BANK-" + b"." * 64


def test_another_card_is_never_patched_into_this_set(card, tmp_path,
                                                     monkeypatch):
    """A set is only patchable because the bytes under it are the same card."""
    r = card.reader
    out = tmp_path / "ovr"
    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 0), b"S")]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))

    os.utime(card.img, (0, 0))                 # a different card image
    calls = _no_extracts(card, monkeypatch)
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    assert len(calls) == 1
    assert engine.read_override_manifest(str(out))["parent"] == ""


def test_a_grown_file_is_copied_in_whole(card, tmp_path):
    """An oversized video needs the ext4 driver on a card; here it is a file."""
    src = tmp_path / "big.asset"
    src.write_bytes(b"A-MUCH-BIGGER-CLIP" * 8)
    card.state["writes"] = []
    card.state["grow"] = {"offset": 0, "n_video": 1, "cleanup": None,
                          "jobs": [("turtles_pro/assets/lcd/1.asset",
                                    str(src))]}
    card.state["counts"] = (0, 1, 0, 0)
    out = tmp_path / "ovr"
    _c, _m, _v, files = engine.write_overrides(
        str(card.img), str(tmp_path / "a"), str(out))
    assert [p for p, _n in files] == ["/turtles_pro/assets/lcd/1.asset"]
    assert (out / "turtles_pro" / "assets" / "lcd" / "1.asset").read_bytes() \
        == src.read_bytes()
    # Always staged whole, too: a grow job is built into a scratch dir on
    # every run, so there is no older version of it to patch and no mtime
    # worth believing about the one there is.
    assert ("whole", "turtles_pro/assets/lcd/1.asset") in _delta(out)


def test_the_set_is_rewritten_whole_not_merged(card, tmp_path):
    """A file that stopped being edited must stop being applied."""
    r = card.reader
    out = tmp_path / "ovr"
    card.state["writes"] = [
        (_disk(r, "/turtles_pro/image.bin", 0), b"S"),
        (_disk(r, "/spk/index/turtles_pro.sidx", 0), b"F"),
    ]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    assert (out / "spk" / "index" / "turtles_pro.sidx").exists()

    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 0), b"S")]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    assert not (out / "spk").exists()


def test_a_folder_that_is_not_a_set_is_never_cleared(card, tmp_path):
    """The set folder is emptied on every build, so it has to be ours."""
    out = tmp_path / "documents"
    out.mkdir()
    (out / "tax return.pdf").write_bytes(b"%PDF")
    with pytest.raises(OSError) as exc:
        engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    assert "not put there by this app" in str(exc.value)
    assert (out / "tax return.pdf").exists()


def test_a_build_that_dies_half_way_leaves_nothing_behind(card, tmp_path,
                                                          monkeypatch):
    """A half-written set must not survive, and must not poison the next Start.

    The rig binds whatever is in the folder, so a set that stopped half way
    would run some of the edits and none of the rest — and the guard above,
    which refuses to clear a folder this app did not build, would then have to
    refuse this one for ever.
    """
    r = card.reader
    out = tmp_path / "ovr"
    card.state["writes"] = [
        (_disk(r, "/turtles_pro/image.bin", 0), b"S"),
        (_disk(r, "/spk/index/turtles_pro.sidx", 0), b"F"),
    ]
    real = r.extract_file
    seen = []

    def die(node, dest):
        seen.append(dest)
        if len(seen) > 1:
            raise OSError(28, "No space left on device")
        return real(node, dest)

    monkeypatch.setattr(r, "extract_file", die)
    with pytest.raises(OSError):
        engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    assert len(seen) == 2                      # it really did get part way in
    assert not out.exists()

    monkeypatch.setattr(r, "extract_file", real)
    _c, _m, _v, files = engine.write_overrides(
        str(card.img), str(tmp_path / "a"), str(out))
    assert len(files) == 2


def test_a_folder_a_killed_build_left_is_still_ours(card, tmp_path):
    """The stub manifest goes down BEFORE any bytes, so a build that is killed
    outright (no exception to clean up after) still leaves a folder this app
    recognises — and one that can never be mistaken for a set to run."""
    out = tmp_path / "ovr"
    (out / "turtles_pro").mkdir(parents=True)
    (out / engine.OVERRIDE_MANIFEST).write_text(
        '{"version": 1, "building": true}', encoding="utf-8")
    (out / "turtles_pro" / "image.bin").write_bytes(b"half")

    # It names no card, so the reuse test sends the tab back to building one.
    assert emulate_tab.overrides_reason(
        engine.read_override_manifest(str(out)), str(card.img),
        str(tmp_path / "a"), "1 2.0")

    r = card.reader
    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 0), b"S")]
    engine.write_overrides(str(card.img), str(tmp_path / "a"), str(out))
    assert (out / "turtles_pro" / "image.bin").read_bytes()         == b"STOCK-SOUND-BANK-" + b"." * 64


def test_the_manifest_names_the_card_it_was_built_from(card, tmp_path):
    r = card.reader
    out = tmp_path / "ovr"
    card.state["writes"] = [(_disk(r, "/turtles_pro/image.bin", 0), b"S")]
    engine.write_overrides(str(card.img), str(tmp_path / "assets"), str(out))
    data = engine.read_override_manifest(str(out))
    st = os.stat(card.img)
    assert data["card"]["size"] == st.st_size
    assert int(data["card"]["mtime"]) == int(st.st_mtime)
    assert os.path.normcase(data["assets"]) \
        == os.path.normcase(str(tmp_path / "assets"))
    assert [f["path"] for f in data["files"]] == ["/turtles_pro/image.bin"]
    # And a caller can add to it afterwards without rewriting it themselves.
    engine.stamp_override_manifest(str(out), assets_fingerprint="7 1.0")
    assert engine.read_override_manifest(str(out))["assets_fingerprint"] \
        == "7 1.0"
    assert engine.read_override_manifest(str(out))["card"]["size"] == st.st_size


def test_no_manifest_reads_as_no_set(tmp_path):
    assert engine.read_override_manifest(str(tmp_path)) == {}
    (tmp_path / engine.OVERRIDE_MANIFEST).write_text("{ truncated")
    assert engine.read_override_manifest(str(tmp_path)) == {}
    assert engine.stamp_override_manifest(str(tmp_path), x=1) == {}


# --------------------------------------------------------------------------
# When the staged set may be reused
# --------------------------------------------------------------------------

def _manifest(card_path, assets, fp="1 2.0"):
    st = os.stat(card_path)
    return {"card": {"path": os.path.abspath(str(card_path)),
                     "size": st.st_size, "mtime": int(st.st_mtime)},
            "assets": os.path.abspath(str(assets)),
            "assets_fingerprint": fp}


def test_a_current_set_is_reused(tmp_path):
    img = tmp_path / "card.raw"
    img.write_bytes(b"x" * 32)
    assets = tmp_path / "gz"
    assets.mkdir()
    assert emulate_tab.overrides_reason(
        _manifest(img, assets), str(img), str(assets), "1 2.0") == ""


@pytest.mark.parametrize("what", ["card", "assets", "edits", "nothing"])
def test_a_stale_set_says_why(tmp_path, what):
    img = tmp_path / "card.raw"
    img.write_bytes(b"x" * 32)
    assets = tmp_path / "gz"
    assets.mkdir()
    man = _manifest(img, assets)
    if what == "card":
        man["card"]["size"] += 1
        expect = "different card image"
    elif what == "assets":
        man["assets"] = str(tmp_path / "elsewhere")
        expect = "different assets folder"
    elif what == "edits":
        man["assets_fingerprint"] = "9 9.0"
        expect = "has changed"
    else:
        man = {}
        expect = "no set staged"
    why = emulate_tab.overrides_reason(man, str(img), str(assets), "1 2.0")
    assert expect in why


def test_the_fingerprint_moves_for_any_edit(tmp_path):
    """Equality, not "is anything newer" — a restored older file counts too."""
    assets = tmp_path / "gz"
    (assets / "audio").mkdir(parents=True)
    wav = assets / "audio" / "idx0001.wav"
    wav.write_bytes(b"RIFF")
    first = emulate_tab.assets_fingerprint(str(assets))
    assert emulate_tab.assets_fingerprint(str(assets)) == first   # stable
    os.utime(wav, (1_000_000, 1_000_000))                         # backdated
    assert emulate_tab.assets_fingerprint(str(assets)) != first
    (assets / "audio" / "idx0002.wav").write_bytes(b"RIFF")
    assert emulate_tab.assets_fingerprint(str(assets)) != first


def test_the_set_is_staged_where_the_app_already_cleans_up():
    """core.host_temp knows the spike2_ prefix, so the set is listed there."""
    from pinball_decryptor.core import host_temp
    d = emulate_tab.overrides_dir()
    assert os.path.dirname(d) == host_temp.temp_dir()
    assert os.path.basename(d).startswith("spike2_")


# --------------------------------------------------------------------------
# The tab
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_real_setup_probe(monkeypatch):
    """Building a panel must not shell out to WSL to probe this machine."""
    monkeypatch.setattr(emulate_tab, "setup_state", lambda: None)


def _panel(**kw):
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip("Tk unavailable: %s" % exc)
    root.attributes("-alpha", 0)
    root.geometry("+10000+10000")
    frame = tk.Frame(root)
    frame.pack()
    panel = emulate_tab.EmulatePanel(
        frame, assets_var=tk.StringVar(value=kw.get("assets", "")),
        overrides_var=tk.BooleanVar(value=kw.get("on", False)))
    panel.build(frame)
    root.update()
    return root, panel


def test_the_box_is_off_and_says_nothing_is_changed(tmp_path):
    root, panel = _panel(assets=str(tmp_path))
    try:
        assert panel._overrides_wanted() is None
        assert "runs exactly as it is" in panel._ovr_hint.cget("text")
    finally:
        root.destroy()


def test_ticked_with_no_assets_folder_says_so():
    root, panel = _panel(on=True, assets="")
    try:
        assert panel._overrides_wanted() is None
        assert "no assets folder" in panel._ovr_hint.cget("text")
    finally:
        root.destroy()


def test_ticked_with_a_folder_explains_the_wait(tmp_path):
    root, panel = _panel(on=True, assets=str(tmp_path))
    try:
        panel._src_path.set("D:/cards/turtles.raw")
        assert panel._overrides_wanted() == ("D:/cards/turtles.raw",
                                             str(tmp_path))
        assert "Start prepares them first" in panel._ovr_hint.cget("text")
    finally:
        root.destroy()


def test_an_extract_with_no_baseline_is_refused(tmp_path, monkeypatch):
    """Without .checksums.md5 every sound reads as edited — hours of encode."""
    assets = tmp_path / "gz"
    assets.mkdir()
    img = tmp_path / "card.raw"
    img.write_bytes(bytes(16))
    root, panel = _panel(on=True, assets=str(assets))
    try:
        panel._src_path.set(str(img))
        assert panel._prepare_overrides(str(img), str(assets)) is None
        # The refusal is handed to the main loop (the caller is the start
        # worker and Tk is not thread safe), so the reason only reaches the
        # label once the loop has run - and it goes in the OPT-IN's label,
        # which the 2 s status poll does not blank.
        root.update()
        assert "baseline" in panel._ovr_hint.cget("text")
        assert panel._ovr_hint.cget("foreground") != "#888"
    finally:
        root.destroy()


def test_a_prepared_set_reaches_watch_sh(tmp_path, monkeypatch):
    """The whole point: PAD_OVERRIDE_DIR in front of watch.sh."""
    out = tmp_path / "ovr"
    out.mkdir()
    monkeypatch.setattr(emulate_tab, "overrides_dir", lambda: str(out))
    monkeypatch.setattr(engine, "read_override_manifest",
                        lambda d: {"reuse": True})
    monkeypatch.setattr(emulate_tab, "overrides_reason",
                        lambda *a, **k: "")          # already current
    assets = tmp_path / "gz"
    assets.mkdir()
    # Stern's baseline flavour is "<rel>\t<md5>" (core.checksums.read_checksums).
    (assets / ".checksums.md5").write_text(
        "audio/idx0001.wav\td41d8cd98f00b204e9800998ecf8427e\n")
    img = tmp_path / "card.raw"
    img.write_bytes(bytes(16))
    root, panel = _panel(on=True, assets=str(assets))
    try:
        panel._src_path.set(str(img))
        extra = panel._prepare_overrides(str(img), str(assets))
        assert extra and extra[0].startswith("PAD_OVERRIDE_DIR=")
        assert "\\" not in extra[0]          # a Windows path would not mount
        cmd = emulate_tab.watch_cmd(120, ["PAD_CARD=/mnt/c/x.raw"] + extra,
                                    savestates=False)
        assert any(a.startswith("PAD_OVERRIDE_DIR=") for a in cmd)
        assert cmd.index(extra[0]) < cmd.index("120")
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# The rig's half, as text
# --------------------------------------------------------------------------

def test_run_game_binds_the_set_over_the_card():
    body = (RIG / "run_game.sh").read_text(encoding="utf-8", errors="replace")
    assert "PAD_OVERRIDE_DIR" in body
    assert "overrides.sh" in body
    # Over games/<rel>, not games/<title>/<rel>: the .sidx sits beside the
    # title, so the set mirrors the whole partition.
    assert 'mount --bind "$OVERRIDE_SRC/$rel" "$R/games/$rel"' in body
    # ...and after the -invert mask, which replaces the whole of data/.
    assert body.index("boot_display_cmd") < body.index("$OVERRIDE_SRC/$rel")


def test_watch_hands_the_variable_to_run_game():
    body = (RIG / "watch.sh").read_text(encoding="utf-8", errors="replace")
    assert 'PAD_OVERRIDE_DIR="${PAD_OVERRIDE_DIR:-}"' in body


def test_overrides_sh_refuses_anything_that_is_not_a_set():
    body = (RIG / "overrides.sh").read_text(encoding="utf-8", errors="replace")
    assert "not an override set" in body
    # The stamp must live BESIDE the stage: run_game.sh binds every file it
    # finds inside it, and one with no card path to land on fails the run.
    assert "STAMP=$PAD_HOME/override.src" in body
    assert "STAGE=$PAD_HOME/override" in body
    assert "GENF=$PAD_HOME/override.gen" in body


def test_overrides_sh_stages_a_delta_rather_than_the_set():
    body = (RIG / "overrides.sh").read_text(encoding="utf-8", errors="replace")
    # Only onto the generation the set was patched out of...
    assert 'sed -n \'s/^parent //p\'' in body
    assert '[ "$held" = "$par" ] || return 1' in body
    # ...and in bytes, not blocks: these are offsets into a multi-GB file.
    assert "iflag=skip_bytes,count_bytes oflag=seek_bytes" in body
    assert "conv=notrunc" in body
    # A full copy still has to leave a generation behind, or every build
    # after one would be a full copy too.
    assert body.index("cp -rL") < body.rindex('> "$GENF"')


def test_run_game_never_binds_the_two_bookkeeping_files():
    """Neither has a card path to land on, so binding one fails the run."""
    body = (RIG / "run_game.sh").read_text(encoding="utf-8", errors="replace")
    assert "! -name overrides.json" in body
    assert "! -name overrides.delta" in body
