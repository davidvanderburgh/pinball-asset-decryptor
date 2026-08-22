"""PAD-79: which Spooky video is a slot, and what a repack puts in the file.

A Spooky game ships its video as loose files inside the archive, and Write
re-packs the folder as it finds it, so those round-trip.  The Replace-Video
tab used to filter them by extension (``.ogv`` only), which had it backwards:
the only ``.ogv`` in an extract is a Godot *derivative* PAD wrote itself, and
the clips a game actually ships can be anything — Halloween's 242 are
``.webm``, so its Video tab listed nothing at all.

The scan is scoped by folder now, and these tests pin both halves of that:
what surfaces as a slot, and that the repack leaves the app's own generated
folders/sidecars out of the update file it hands the machine.
"""

import os
import tarfile
import zipfile

from pinball_decryptor.core.video_slots import scan_video_slots
from pinball_decryptor.plugins.spooky import formats


def _make_extract(root):
    """A Halloween-shaped extract: loose game video + PAD's own leftovers."""
    shipped = root / "assets" / "dmd" / "animations" / "thenight"
    shipped.mkdir(parents=True)
    (shipped / "bg_school.webm").write_bytes(b"webm-shipped")
    (shipped / "bg_cemetery.webm").write_bytes(b"webm-shipped-2")
    (root / "config").mkdir()
    (root / "config" / "settings.config").write_bytes(b"cfg")

    # What Extract generated: Unity/Godot derivatives nothing writes back.
    derived = root / "_extracted_assets" / "video"
    derived.mkdir(parents=True)
    (derived / "icon.webm").write_bytes(b"webm-from-bundle")
    (derived / "cutscene.ogv").write_bytes(b"ogv-from-pck")

    # Project scratch + sidecars.
    (root / "build").mkdir()
    (root / "build" / "code_H78.pkg").write_bytes(b"previous build output")
    (root / "logs").mkdir()
    (root / "logs" / "project.log").write_bytes(b"session log")
    (root / ".checksums.md5").write_bytes(
        b"assets/dmd/animations/thenight/bg_school.webm"
        b"\td41d8cd98f00b204e9800998ecf8427e\n")
    (root / ".spooky_meta").write_bytes(b"{}")
    (root / ".hashcache.json").write_bytes(b"{}")
    return root


# ---------------------------------------------------------------------------
# Which video is a slot
# ---------------------------------------------------------------------------

def test_shipped_webm_are_slots_derivatives_are_not(manufacturers_by_key,
                                                    tmp_path):
    """The PAD-79 regression: Halloween's loose .webm list, the bundle ones
    (and the Godot .ogv the old extension filter surfaced) do not."""
    sp = manufacturers_by_key["spooky"]
    root = _make_extract(tmp_path / "Halloween")

    slots = scan_video_slots(str(root),
                             roots=sp.video_slot_dirs(str(root)),
                             exts=sp.video_slot_exts(str(root)),
                             probe=False)
    rels = sorted(s.rel_path for s in slots)
    assert rels == ["assets/dmd/animations/thenight/bg_cemetery.webm",
                    "assets/dmd/animations/thenight/bg_school.webm"]


def test_video_slot_exts_is_no_longer_narrowed(manufacturers_by_key):
    """Extension is the wrong axis here — a shipped clip and a derivative can
    share one.  Narrowing must happen by folder instead."""
    sp = manufacturers_by_key["spooky"]
    assert sp.video_slot_exts("anything") is None


def test_video_slot_dirs_scans_everything_when_nothing_generated(
        manufacturers_by_key, tmp_path):
    """A tree with no _extracted_assets/_pck_contents has nothing to scope
    out, so the whole extract is scanned (roots=None)."""
    sp = manufacturers_by_key["spooky"]
    root = tmp_path / "ed"
    (root / "game").mkdir(parents=True)
    (root / "game" / "intro.webm").write_bytes(b"webm")
    assert sp.video_slot_dirs(str(root)) is None
    slots = scan_video_slots(str(root), roots=None, exts=None, probe=False)
    assert [s.rel_path for s in slots] == ["game/intro.webm"]


def test_video_slot_dirs_tolerates_a_missing_folder(manufacturers_by_key,
                                                    tmp_path):
    sp = manufacturers_by_key["spooky"]
    assert sp.video_slot_dirs(str(tmp_path / "nope")) is None
    assert sp.video_slot_dirs("") is None


# ---------------------------------------------------------------------------
# What the repack puts in the update file
# ---------------------------------------------------------------------------

def test_tar_holds_every_file_exactly_once(tmp_path):
    """tarfile.add() recurses by default, so adding the directory entries AND
    the files wrote each file once per ancestor folder — a deep tree came out
    several times its real size."""
    src = tmp_path / "src"
    (src / "a" / "b" / "c").mkdir(parents=True)
    (src / "a" / "b" / "c" / "deep.bin").write_bytes(b"x" * 32)
    (src / "a" / "top.bin").write_bytes(b"y" * 32)

    out = tmp_path / "out.tar"
    formats.create_tar(str(src), str(out))
    with tarfile.open(out) as tf:
        names = [m.name.replace("\\", "/") for m in tf.getmembers()
                 if not m.isdir()]
    assert sorted(names) == ["a/b/c/deep.bin", "a/top.bin"]


def test_tar_still_carries_directory_entries(tmp_path):
    """The stock archives have explicit directory members; keep writing them
    (that is why the dirs are added at all) — just not recursively."""
    src = tmp_path / "src"
    (src / "a" / "b").mkdir(parents=True)
    (src / "a" / "b" / "f.bin").write_bytes(b"z")
    (src / "empty").mkdir()

    out = tmp_path / "out.tar"
    formats.create_tar(str(src), str(out))
    with tarfile.open(out) as tf:
        dirs = sorted(m.name.replace("\\", "/") for m in tf.getmembers()
                      if m.isdir())
    assert dirs == ["a", "a/b", "empty"]


def test_repack_leaves_out_the_apps_own_folders_and_sidecars(tmp_path):
    root = _make_extract(tmp_path / "Halloween")
    out = tmp_path / "out.tar.gz"
    formats.create_tar_gz(str(root), str(out))
    with tarfile.open(out) as tf:
        names = {m.name.replace("\\", "/") for m in tf.getmembers()}

    assert "assets/dmd/animations/thenight/bg_school.webm" in names
    assert "config/settings.config" in names
    for junk in ("_extracted_assets", "_extracted_assets/video/icon.webm",
                 "build", "build/code_H78.pkg", "logs", "logs/project.log",
                 ".checksums.md5", ".spooky_meta", ".hashcache.json"):
        assert junk not in names, junk


def test_zip_repack_leaves_out_the_same_things(tmp_path):
    """create_zip feeds the AES .pkg formats (R&M, Alice Cooper) and the P3
    update ZIPs — same rule."""
    root = _make_extract(tmp_path / "Halloween")
    out = tmp_path / "out.zip"
    formats.create_zip(str(root), str(out))
    with zipfile.ZipFile(out) as zf:
        names = {n.replace("\\", "/") for n in zf.namelist()}

    assert "assets/dmd/animations/thenight/bg_school.webm" in names
    for junk in ("_extracted_assets/video/icon.webm", "build/code_H78.pkg",
                 "logs/project.log", ".checksums.md5", ".spooky_meta",
                 ".hashcache.json"):
        assert junk not in names, junk


def test_a_root_dotfile_the_baseline_knows_is_the_games_and_packs(tmp_path):
    """A root dot-entry is only ours when the Extract baseline doesn't list
    it — the sidecars are written outside the baseline, so one that IS in it
    came out of the archive and has to ship."""
    src = tmp_path / "src"
    src.mkdir()
    (src / ".gameconfig").write_bytes(b"shipped by the game")
    (src / ".hashcache.json").write_bytes(b"{}")
    (src / ".checksums.md5").write_bytes(
        b".gameconfig\td41d8cd98f00b204e9800998ecf8427e\n")

    assert ".hashcache.json" in formats.generated_at_root(str(src))
    assert ".gameconfig" not in formats.generated_at_root(str(src))

    out = tmp_path / "out.tar"
    formats.create_tar(str(src), str(out))
    with tarfile.open(out) as tf:
        names = {m.name.replace("\\", "/") for m in tf.getmembers()}
    assert names == {".gameconfig"}


def test_a_generated_name_deeper_in_the_tree_still_packs(tmp_path):
    """The exclusion is anchored at the project root, so a game that ships a
    folder called "build" or "logs" inside its own tree keeps it."""
    src = tmp_path / "src"
    (src / "game" / "build").mkdir(parents=True)
    (src / "game" / "build" / "real_asset.bin").write_bytes(b"ship me")
    (src / "build").mkdir()
    (src / "build" / "ours.pkg").write_bytes(b"skip me")

    out = tmp_path / "out.tar"
    formats.create_tar(str(src), str(out))
    with tarfile.open(out) as tf:
        names = {m.name.replace("\\", "/") for m in tf.getmembers()}
    assert "game/build/real_asset.bin" in names
    assert "build/ours.pkg" not in names


def test_round_trip_keeps_a_replaced_clip_and_drops_the_scratch(
        manufacturers_by_key, tmp_path):
    """Extract -> swap a clip -> Write -> re-extract: the new bytes come back
    and none of the app's own folders rode along."""
    from tests import synthetic
    from tests._runner import run_pipeline_sync

    sp = manufacturers_by_key["spooky"]
    ed_in = synthetic.make_spooky_targz(
        tmp_path / "in.ed",
        files={"assets/dmd/animations/intro.webm": b"original clip",
               "config/settings.config": b"cfg"})
    extracted = tmp_path / "ex"
    extracted.mkdir()
    r1 = run_pipeline_sync(sp.make_extract_pipeline(
        str(ed_in), str(extracted), lambda *a, **k: None,
        lambda *a, **k: None, lambda *a, **k: None, lambda *a, **k: None))
    assert r1.success, r1.summary

    # What Replace-Video staging does, plus the scratch a session leaves.
    (extracted / "assets" / "dmd" / "animations" / "intro.webm").write_bytes(
        b"REPLACEMENT CLIP")
    (extracted / "logs").mkdir()
    (extracted / "logs" / "project.log").write_bytes(b"session log")

    ed_out = tmp_path / "out.ed"
    r2 = run_pipeline_sync(sp.make_write_pipeline(
        str(ed_in), str(extracted), str(ed_out), lambda *a, **k: None,
        lambda *a, **k: None, lambda *a, **k: None, lambda *a, **k: None))
    assert r2.success, r2.summary

    with tarfile.open(ed_out) as tf:
        names = [m.name.replace("\\", "/") for m in tf.getmembers()
                 if not m.isdir()]
    assert sorted(names) == ["assets/dmd/animations/intro.webm",
                             "config/settings.config"]

    re_ex = tmp_path / "re"
    re_ex.mkdir()
    r3 = run_pipeline_sync(sp.make_extract_pipeline(
        str(ed_out), str(re_ex), lambda *a, **k: None, lambda *a, **k: None,
        lambda *a, **k: None, lambda *a, **k: None))
    assert r3.success, r3.summary
    assert (re_ex / "assets" / "dmd" / "animations"
            / "intro.webm").read_bytes() == b"REPLACEMENT CLIP"
