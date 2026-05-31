"""Dutch Pinball (TBL + AAIW) plugin tests.

Covers detection, the ``.cdmd`` colour-video decoder, the pure-Python
partclone v2 reader, and a TBL extract round-trip on synthetic fixtures.
No real game data is used.
"""

import os

import pytest

from tests import synthetic


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_dp_detect_tbl_full_zip(manufacturers_by_key, tmp_path):
    dp = manufacturers_by_key["dp"]
    z = synthetic.make_tbl_zip(tmp_path / "TBL-v1.00.zip", version="1.00")
    game = dp.detect(str(z))
    assert game is not None and game.key == "tbl"


def test_dp_detect_tbl_delta_zip(manufacturers_by_key, tmp_path):
    dp = manufacturers_by_key["dp"]
    z = synthetic.make_tbl_zip(tmp_path / "TBL-v1.15.zip", version="1.15",
                               delta_bases=["1.01", "1.10"])
    game = dp.detect(str(z))
    assert game is not None and game.key == "tbl"


def test_dp_detect_aaiw_img(manufacturers_by_key, tmp_path):
    dp = manufacturers_by_key["dp"]
    img = synthetic.make_aaiw_img(tmp_path / "AAIW_1.05_full_image.img")
    game = dp.detect(str(img))
    assert game is not None and game.key == "aaiw"


def test_dp_rejects_unrelated(manufacturers_by_key, tmp_path):
    dp = manufacturers_by_key["dp"]
    junk = tmp_path / "random.zip"
    import zipfile
    with zipfile.ZipFile(junk, "w") as zf:
        zf.writestr("hello.txt", b"not a pinball update")
    assert dp.detect(str(junk)) is None


# ---------------------------------------------------------------------------
# cdmd decoder
# ---------------------------------------------------------------------------

def test_cdmd_parse_header():
    from pinball_decryptor.plugins.dp import cdmd
    data = synthetic.make_cdmd(nframes=3, w=4, h=5)
    assert cdmd.is_cdmd(data)
    nframes, w, h = cdmd.parse_header(data)
    assert (nframes, w, h) == (3, 4, 5)


def test_cdmd_iter_frames_count_and_size():
    from pinball_decryptor.plugins.dp import cdmd
    data = synthetic.make_cdmd(nframes=4, w=6, h=3)
    frames = list(cdmd.iter_frames(data))
    assert len(frames) == 4
    assert all(f.size == (6, 3) and f.mode == "RGBA" for f in frames)


def test_cdmd_argb_byte_order():
    """First pixel of frame 0 is A=ff R=0 G=0x40 B=0x80 (synthetic colour)."""
    from pinball_decryptor.plugins.dp import cdmd
    data = synthetic.make_cdmd(nframes=1, w=1, h=1)
    img = next(cdmd.iter_frames(data))
    assert img.getpixel((0, 0)) == (0, 0x40, 0x80, 0xff)


def test_cdmd_single_frame_to_png(tmp_path):
    from pinball_decryptor.plugins.dp import cdmd
    from PIL import Image
    src = tmp_path / "icon.cdmd"
    src.write_bytes(synthetic.make_cdmd(nframes=1, w=3, h=3))

    # Raw (no dot-matrix) keeps native resolution.
    raw = tmp_path / "raw.png"
    assert cdmd.cdmd_to_png(str(src), str(raw), dmd=False) == 1
    assert Image.open(raw).size == (4, 4)  # padded to even for consistency

    # Dot-matrix render upscales by the cell pitch plus the bezel border.
    dmd = tmp_path / "dmd.png"
    cdmd.cdmd_to_png(str(src), str(dmd), dmd=True, cell=8)
    assert Image.open(dmd).size == (3 * 8 + 2 * cdmd.DMD_BORDER,
                                    3 * 8 + 2 * cdmd.DMD_BORDER)


def test_cdmd_rejects_non_video_magic(tmp_path):
    """Font .cdmd files (magic 'dmd\\0') are not treated as video."""
    from pinball_decryptor.plugins.dp import cdmd
    src = tmp_path / "font.cdmd"
    src.write_bytes(b"dmd\x00rest-of-font-data")
    assert not cdmd.is_cdmd(str(src))


def test_cdmd_convert_all_skips_non_video(tmp_path):
    from pinball_decryptor.plugins.dp import cdmd
    (tmp_path / "v.cdmd").write_bytes(synthetic.make_cdmd(1, 2, 2))
    (tmp_path / "font.cdmd").write_bytes(b"dmd\x00not-video")
    out = tmp_path / "decoded"
    ok, fail = cdmd.convert_all_cdmd(str(tmp_path), str(out))
    # The single-frame video decodes to PNG (no ffmpeg needed); the font is
    # skipped, not counted as a failure.
    assert ok == 1 and fail == 0


# ---------------------------------------------------------------------------
# partclone v2 reader
# ---------------------------------------------------------------------------

def test_partclone_header_parse(tmp_path):
    from pinball_decryptor.core import partclone
    path, _expected = synthetic.make_partclone_v2(
        tmp_path / "p.img", used_blocks=(0, 2), totalblock=4, block_size=512)
    with open(path, "rb") as f:
        img = partclone.PartcloneImage.from_stream(f)
    assert img.fs == "EXTFS"
    assert img.totalblock == 4 and img.block_size == 512
    assert img.usedblocks == 2 and img.blocks_per_checksum == 2


def test_partclone_restore_roundtrip(tmp_path):
    from pinball_decryptor.core import partclone
    path, expected = synthetic.make_partclone_v2(
        tmp_path / "p.img", used_blocks=(0, 2, 3), totalblock=5,
        block_size=512, blocks_per_checksum=2)
    out = tmp_path / "raw.img"
    with open(path, "rb") as f:
        img = partclone.PartcloneImage.from_stream(f)
        with open(out, "wb") as o:
            written = img.restore(f, o)
    assert written == 3
    assert out.read_bytes() == expected


def test_partclone_rejects_non_v2(tmp_path):
    from pinball_decryptor.core import partclone
    bad = tmp_path / "bad.img"
    bad.write_bytes(b"partclone-image\x00" + b"\x00" * 200)
    with pytest.raises(partclone.PartcloneError):
        with open(bad, "rb") as f:
            partclone.PartcloneImage.from_stream(f)


# ---------------------------------------------------------------------------
# TBL extract round-trip (no ffmpeg dependency required)
# ---------------------------------------------------------------------------

def test_tbl_extract_pipeline(manufacturers_by_key, tmp_path):
    dp = manufacturers_by_key["dp"]
    z = synthetic.make_tbl_zip(tmp_path / "TBL-v1.00.zip", version="1.00")
    out = tmp_path / "out"

    done = {}
    pipe = dp.make_extract_pipeline(
        str(z), str(out),
        lambda *a, **k: None, lambda *a, **k: None, lambda *a, **k: None,
        lambda ok, msg: done.update(ok=ok, msg=msg))
    pipe.run()

    assert done.get("ok") is True, done.get("msg")
    # Raw assets extracted, version prefix preserved.
    assert (out / "1.00" / "assets" / "sound" / "beep.wav").is_file()
    assert (out / "1.00" / "assets" / "sequences" / "clip" / "clip.cdmd").is_file()
    # Baseline checksums written, decoded-videos folder kept out of them.
    assert (out / ".checksums.md5").is_file()
    from pinball_decryptor.core.checksums import read_checksums
    baseline = read_checksums(str(out))
    assert not any(k.startswith("_DECODED VIDEOS") for k in baseline)


def test_dp_dmd_toggle_wires_through(manufacturers_by_key, tmp_path):
    """The GUI 'decode_dmd' checkbox toggles the dot-matrix shader on TBL."""
    dp = manufacturers_by_key["dp"]
    assert dp.capabilities.decode_dmd is True
    assert "dot-matrix" in dp.decode_dmd_label.lower()

    z = synthetic.make_tbl_zip(tmp_path / "TBL.zip", version="1.00")
    cbs = (lambda *a, **k: None,) * 4
    off = dp.make_extract_pipeline(str(z), str(tmp_path / "o1"), *cbs)
    on = dp.make_extract_pipeline(str(z), str(tmp_path / "o2"), *cbs,
                                  decode_dmd=True)
    assert off.dmd is False and on.dmd is True


def test_dp_game_aware_controls(manufacturers_by_key):
    """The video toggle shows for both games (with game-specific labels);
    delta-merge is TBL-only."""
    dp = manufacturers_by_key["dp"]
    # Both games get the optional video-processing toggle...
    assert dp.decode_dmd_applies("TBL-v1.00.zip") is True
    assert dp.decode_dmd_applies("AAIW_1.05_full_image.img") is True
    # ...but with different labels (dot-matrix vs ProRes convert).
    assert "dot-matrix" in dp.decode_dmd_label_for("TBL-v1.00.zip").lower()
    assert "prores" in dp.decode_dmd_label_for("AAIW_x.img").lower()
    # Delta-merging is TBL-only (AAIW ships a full SSD image).
    assert dp.chain_deltas_applies("TBL-v1.00.zip") is True
    assert dp.chain_deltas_applies("AAIW_1.05_full_image.img") is False


def test_tbl_build_bumps_version_and_remaps(manufacturers_by_key, tmp_path):
    """Build labels the output one version newer than the merged version,
    remaps the tree onto it, and writes a fresh delta marker."""
    dp = manufacturers_by_key["dp"]
    full = synthetic.make_tbl_zip(tmp_path / "TBL-v1.01.zip", version="1.01",
                                  delta_bases=["1.00"])
    delta = synthetic.make_tbl_zip(
        tmp_path / "TBL-v1.15.zip", version="1.15", delta_bases=["1.01", "1.10"],
        extra_files={"assets/sound/new_in_115.wav": b"RIFFnew115",
                     "assets/sound/beep.wav": b"RIFFchanged-in-115"})
    out = tmp_path / "out"
    dp.make_extract_pipeline(
        str(full), str(out),
        lambda *a, **k: None, lambda *a, **k: None, lambda *a, **k: None,
        lambda ok, msg: None, deltas=[str(delta)]).run()

    built = tmp_path / "built.zip"
    done = {}
    dp.make_write_pipeline(
        str(full), str(out), str(built),
        lambda *a, **k: None, lambda *a, **k: None, lambda *a, **k: None,
        lambda ok, msg: done.update(ok=ok, msg=msg)).run()
    assert done.get("ok") is True, done.get("msg")

    import zipfile
    with zipfile.ZipFile(built) as zf:
        names = zf.namelist()
        # Merged version was 1.15 -> built update is labeled 1.16.
        assert any(n.startswith("1.16/") for n in names)
        assert not any(n.startswith("1.01/") for n in names)
        # Fresh delta marker lists the versions it installs onto (incl 1.15).
        assert "1.16/delta" in names
        compat = zf.read("1.16/delta").decode()
        assert "1.15" in compat
        # Merged + changed content carried through under the new version.
        assert zf.read("1.16/assets/sound/new_in_115.wav") == b"RIFFnew115"
        assert zf.read("1.16/assets/sound/beep.wav") == b"RIFFchanged-in-115"


def test_aaiw_ignores_dmd_toggle(manufacturers_by_key, tmp_path):
    """The dot-matrix toggle never touches the AAIW path."""
    dp = manufacturers_by_key["dp"]
    img = synthetic.make_aaiw_img(tmp_path / "AAIW.img")
    cbs = (lambda *a, **k: None,) * 4
    pipe = dp.make_extract_pipeline(str(img), str(tmp_path / "o"), *cbs,
                                    decode_dmd=True)
    assert type(pipe).__name__ == "AaiwExtractPipeline"
    assert not hasattr(pipe, "dmd")


def test_dp_delta_info_and_version_sort():
    from pinball_decryptor.plugins.dp import formats
    full = formats  # noqa
    assert formats.version_key("1.10") > formats.version_key("1.9")
    assert formats.top_version(["1.01/a", "1.01/b/c"]) == "1.01"
    assert formats.top_version(["1.01/a", "1.15/b"]) is None


def test_tbl_chain_deltas_during_extract(manufacturers_by_key, tmp_path):
    """Full image + delta(s) supplied to Extract are auto-merged, remapped
    onto the base version folder (no sibling delta-version folder)."""
    dp = manufacturers_by_key["dp"]
    full = synthetic.make_tbl_zip(tmp_path / "TBL-v1.01.zip", version="1.01")
    delta = synthetic.make_tbl_zip(
        tmp_path / "TBL-v1.15.zip", version="1.15", delta_bases=["1.01", "1.10"],
        extra_files={"assets/sound/new_in_115.wav": b"RIFFnew115",
                     "assets/sound/beep.wav": b"RIFFchanged-in-115"})
    out = tmp_path / "out"

    done = {}
    pipe = dp.make_extract_pipeline(
        str(full), str(out),
        lambda *a, **k: None, lambda *a, **k: None, lambda *a, **k: None,
        lambda ok, msg: done.update(ok=ok, msg=msg),
        deltas=[str(delta)])
    pipe.run()
    assert done.get("ok") is True, done.get("msg")

    # Everything merged under the base (1.01) folder; no sibling 1.15/.
    assert not (out / "1.15").exists()
    assert (out / "1.01" / "assets" / "sound" / "new_in_115.wav").read_bytes() \
        == b"RIFFnew115"
    assert (out / "1.01" / "assets" / "sound" / "beep.wav").read_bytes() \
        == b"RIFFchanged-in-115"
    # The delta marker is metadata — it must not leak into the tree.
    assert not (out / "1.01" / "delta").exists()


def test_tbl_chain_deltas_rejects_incompatible(manufacturers_by_key, tmp_path):
    """A delta whose compat list excludes the base version is rejected."""
    dp = manufacturers_by_key["dp"]
    full = synthetic.make_tbl_zip(tmp_path / "TBL-v1.00.zip", version="1.00")
    delta = synthetic.make_tbl_zip(
        tmp_path / "TBL-v1.15.zip", version="1.15", delta_bases=["1.01", "1.10"])
    out = tmp_path / "out"

    done = {}
    dp.make_extract_pipeline(
        str(full), str(out),
        lambda *a, **k: None, lambda *a, **k: None, lambda *a, **k: None,
        lambda ok, msg: done.update(ok=ok, msg=msg),
        deltas=[str(delta)]).run()
    assert done.get("ok") is False
    assert "1.00" in done["msg"] and "1.15" in done["msg"]


def test_dp_direct_ssd_wiring(manufacturers_by_key):
    """Dutch Pinball advertises direct-SSD and builds the SSD pipelines."""
    dp = manufacturers_by_key["dp"]
    assert dp.capabilities.direct_ssd is True
    assert all(isinstance(p, str) for p in dp.direct_ssd_extract_phases)
    assert all(isinstance(p, str) for p in dp.direct_ssd_write_phases)
    cbs = (lambda *a, **k: None,) * 4
    ex = dp.make_direct_ssd_extract_pipeline(r"\\.\PHYSICALDRIVE3", "out", *cbs)
    wr = dp.make_direct_ssd_write_pipeline(r"\\.\PHYSICALDRIVE3", "assets",
                                           *cbs, partition_override=2)
    assert type(ex).__name__ == "DpDirectSsdExtractPipeline"
    assert type(wr).__name__ == "DpDirectSsdWritePipeline"
    assert wr.partition_override == 2


def test_dp_ssd_subtree_detection():
    """find_game_subtree spots AAIW's fixed path and TBL's assets dir."""
    from pinball_decryptor.plugins.dp import ssd
    from pinball_decryptor.core.executor import CommandError

    class FakeExec:
        def __init__(self, game):
            self.game = game

        def run(self, cmd, timeout=None):
            if "test -d" in cmd and "/opt/assets/alice" in cmd:
                if self.game == "aaiw":
                    return ""
                raise CommandError(cmd, 1, "")
            if cmd.lstrip().startswith("find "):
                if self.game == "tbl":
                    return "/mnt/x/home/lebowski/assets/sequences\n"
                return ""
            if "ls " in cmd and ".cdmd" in cmd:
                if self.game == "tbl":
                    return ""
                raise CommandError(cmd, 1, "")
            raise CommandError(cmd, 1, "")

    assert ssd.find_game_subtree(FakeExec("aaiw"), "/mnt/x") == "/opt/assets/alice"
    assert ssd.find_game_subtree(FakeExec("tbl"), "/mnt/x") == "/home/lebowski/assets"
    assert ssd.find_game_subtree(FakeExec("none"), "/mnt/x") is None


def test_tbl_apply_delta(manufacturers_by_key, tmp_path):
    dp = manufacturers_by_key["dp"]
    # Extract a base, then overlay a delta that changes one file + adds one.
    base_zip = synthetic.make_tbl_zip(tmp_path / "base.zip", version="1.00")
    out = tmp_path / "out"
    dp.make_extract_pipeline(
        str(base_zip), str(out),
        lambda *a, **k: None, lambda *a, **k: None, lambda *a, **k: None,
        lambda ok, msg: None).run()

    import zipfile
    delta = tmp_path / "delta.zip"
    with zipfile.ZipFile(delta, "w") as zf:
        zf.writestr("1.00/assets/sound/beep.wav", b"RIFFchanged")
        zf.writestr("1.00/assets/sound/new.wav", b"RIFFbrand-new")
    overwritten, added, total = dp.apply_delta(str(out), str(delta))
    assert overwritten == 1 and added == 1
    assert (out / "1.00" / "assets" / "sound" / "new.wav").read_bytes() \
        == b"RIFFbrand-new"
