"""Tests for core.extract_source — the source-image staleness sidecar that
backs the GUI's 'source image changed' banner."""

import json
import os

from pinball_decryptor.core.extract_source import (
    BUILD_RECORD_SUFFIX, SIDE_CAR, amend_extract_source, built_card_source,
    find_extract_for, other_card_recorded, read_extract_source,
    stale_source_message, version_for_dir, version_hint_for_dir,
    version_hint_from_name, write_extract_source)


def _make_image(path, data=b"\x00" * 4096):
    with open(path, "wb") as f:
        f.write(data)


def test_no_sidecar_is_quiet(tmp_path):
    # An assets folder with no sidecar (older extract) never warns.
    assert stale_source_message(str(tmp_path)) is None


def test_unchanged_source_is_quiet(tmp_path):
    img = tmp_path / "game.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    assert os.path.isfile(out / SIDE_CAR)
    assert stale_source_message(str(out)) is None


def test_mtime_change_is_flagged(tmp_path):
    img = tmp_path / "game.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    # Simulate a revert-to-fresh-copy: same bytes, new mtime.
    st = os.stat(img)
    os.utime(img, (st.st_atime, st.st_mtime + 120))
    msg = stale_source_message(str(out))
    assert msg is not None and "game.raw" in msg


def test_size_change_is_flagged(tmp_path):
    img = tmp_path / "game.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    _make_image(str(img), b"\x01" * 8192)  # different size
    assert stale_source_message(str(out)) is not None


def test_missing_source_is_quiet(tmp_path):
    img = tmp_path / "game.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    os.remove(img)  # user relocated/deleted the image — don't nag
    assert stale_source_message(str(out)) is None


def test_nonfile_input_writes_no_sidecar(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    # A device-style path (Direct-SSD) isn't a regular file → no sidecar.
    write_extract_source(str(out), r"\\.\PHYSICALDRIVE9")
    assert not os.path.isfile(out / SIDE_CAR)
    assert stale_source_message(str(out)) is None


def test_corrupt_sidecar_is_quiet(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    with open(out / SIDE_CAR, "w", encoding="utf-8") as f:
        f.write("{ not json")
    assert stale_source_message(str(out)) is None


def test_sidecar_records_expected_fields(tmp_path):
    img = tmp_path / "the_image.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    with open(out / SIDE_CAR, encoding="utf-8") as f:
        rec = json.load(f)
    assert rec["input_name"] == "the_image.raw"
    assert rec["size"] == 4096
    assert "mtime" in rec and isinstance(rec["mtime"], int)


def test_version_hint_from_name():
    # Stern card-image naming: <game>-<maj>_<min>_<patch>.<tag>.<size>...
    assert (version_hint_from_name("turtles_pro-1_59_0.Release.8G.sdcard.raw")
            == "1.59.0 (Release)")
    assert (version_hint_from_name("turtles_pro-1_58_1.1987.8G.sdcard.raw")
            == "1.58.1 (1987)")
    # A media-size token in the channel slot is not a build tag.
    assert version_hint_from_name("acdc-2_10_0.8G.raw") == "2.10.0"
    # No version pattern / no name -> None (caller shows nothing).
    assert version_hint_from_name("some_random_backup.img") is None
    assert version_hint_from_name(None) is None


def test_read_and_version_hint_for_dir(tmp_path):
    img = tmp_path / "turtles_pro-1_59_0.Release.8G.sdcard.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    rec = read_extract_source(str(out))
    assert rec is not None and rec["input_path"] == os.path.abspath(str(img))
    assert version_hint_for_dir(str(out)) == "1.59.0 (Release)"
    # A folder with no sidecar opts out cleanly.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert read_extract_source(str(empty)) is None
    assert version_hint_for_dir(str(empty)) is None


# ---------------------------------------------------------------------------
# find_extract_for — pairing a picked card back to the folder it was
# extracted to, so the Compare report's audio diff has something to read
# ---------------------------------------------------------------------------

def _extracted(parent, name, image):
    out = parent / name
    out.mkdir(parents=True)
    write_extract_source(str(out), str(image))
    return str(out)


def test_finds_the_extract_one_level_down(tmp_path):
    """The shape Extract Both leaves behind: one parent folder the user
    picked, a sub-folder per card."""
    img_a = tmp_path / "turtles_le-1_59_0.raw"
    img_b = tmp_path / "turtles_pro-1_59_0.raw"
    _make_image(str(img_a), b"A" * 4096)
    _make_image(str(img_b), b"B" * 2048)
    parent = tmp_path / "both"
    out_a = _extracted(parent, "le", img_a)
    out_b = _extracted(parent, "pro", img_b)

    assert find_extract_for(str(img_a), [str(parent)]) == out_a
    assert find_extract_for(str(img_b), [str(parent)]) == out_b


def test_finds_an_extract_that_is_the_root_itself(tmp_path):
    """A card commonly lives inside the project extracted from it, so the
    folder holding the image is a root worth checking on its own."""
    out = tmp_path / "project"
    out.mkdir()
    img = out / "turtles_le-1_59_0.raw"
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    assert find_extract_for(str(img), [str(out)]) == str(out)


def test_a_card_with_no_extract_finds_nothing(tmp_path):
    """No guessing.  A confidently wrong audio diff is worse than the honest
    "extract both cards, then compare again"."""
    img = tmp_path / "a.raw"
    other = tmp_path / "b.raw"
    _make_image(str(img), b"A" * 4096)
    _make_image(str(other), b"B" * 4096)
    _extracted(tmp_path / "both", "other", other)
    assert find_extract_for(str(img), [str(tmp_path / "both")]) is None
    assert find_extract_for(str(img), [str(tmp_path / "nope")]) is None
    assert find_extract_for("", [str(tmp_path)]) is None
    assert find_extract_for(str(img), None) is None


def test_a_moved_card_still_pairs_up(tmp_path):
    """Cards get copied and moved far more often than they get rebuilt.  Same
    name and same byte size is enough — refusing would put the report back on
    "run an Extract" for a user who already has."""
    img = tmp_path / "orig" / "turtles_le-1_59_0.raw"
    img.parent.mkdir()
    _make_image(str(img))
    out = _extracted(tmp_path / "both", "le", img)

    moved = tmp_path / "elsewhere" / "turtles_le-1_59_0.raw"
    moved.parent.mkdir()
    _make_image(str(moved))
    assert find_extract_for(str(moved), [str(tmp_path / "both")]) == out

    # A different card of the same size does NOT pair up on size alone.
    other = tmp_path / "elsewhere" / "turtles_pro-1_59_0.raw"
    _make_image(str(other))
    assert find_extract_for(str(other), [str(tmp_path / "both")]) is None


def test_a_stale_extract_is_still_this_card_s_extract(tmp_path):
    """Staleness is stale_source_message's job.  An extract made before the
    image was touched is still the extract OF that image, and dropping it
    would silently take the sound diff away."""
    img = tmp_path / "a.raw"
    _make_image(str(img))
    out = _extracted(tmp_path / "both", "a", img)
    os.utime(str(img), (0, 0))
    assert stale_source_message(out) is not None
    assert find_extract_for(str(img), [str(tmp_path / "both")]) == out


def test_card_version_stamp_outranks_the_filename_guess(tmp_path):
    """The card's own index is the version authority (it survives renames);
    the stamped ``card_version`` shows exact, the filename parse stays a
    ~-marked hint for extracts that predate the stamp."""
    img = tmp_path / "godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"
    _make_image(str(img))
    out = tmp_path / "extract"
    out.mkdir()
    write_extract_source(str(out), str(img))

    # No stamp yet: the filename hint, marked inexact (this name's trailing
    # _spike2 also blocks the channel tag — the exact quirk resolve_version
    # documents about it).
    ver, exact = version_for_dir(str(out))
    assert exact is False and ver == "1.15.0"

    # The off-thread probe stamps what the card itself reported.
    amend_extract_source(str(out), card_version="1.15.0")
    ver, exact = version_for_dir(str(out))
    assert (ver, exact) == ("1.15.0", True)
    # ...without disturbing the staleness signature.
    assert stale_source_message(str(out)) is None


def test_amend_without_a_sidecar_is_a_noop(tmp_path):
    amend_extract_source(str(tmp_path), card_version="9.9.9")
    assert read_extract_source(str(tmp_path)) is None
    assert version_for_dir(str(tmp_path)) == (None, False)


# --------------------------------------------------------------------------
# building onto a card the folder did not come from (PAD-176)
# --------------------------------------------------------------------------
def test_building_onto_the_folder_s_own_card_is_quiet(tmp_path):
    img = tmp_path / "godzilla_pro-1_16_0.raw"
    _make_image(str(img))
    out = tmp_path / "extract"
    out.mkdir()
    write_extract_source(str(out), str(img))
    assert other_card_recorded(str(out), str(img)) is None

    # ...and so is a copy of that same card somewhere else: a card is moved
    # far more often than it is rebuilt (same rule find_extract_for uses).
    moved = tmp_path / "copy" / "godzilla_pro-1_16_0.raw"
    moved.parent.mkdir()
    _make_image(str(moved))
    assert other_card_recorded(str(out), str(moved)) is None


def test_building_onto_another_card_names_the_one_the_folder_came_from(
        tmp_path):
    """A build carries the folder's replacements, not its contents, so this
    is the case where mods baked into the recorded card vanish (PAD-176)."""
    built = tmp_path / "Godzilla Pro 1.16 Custom V1.91.raw"
    _make_image(str(built))
    out = tmp_path / "V1.92"
    out.mkdir()
    write_extract_source(str(out), str(built))

    stock = tmp_path / "godzilla_pro-1_16_0.raw"
    _make_image(str(stock), b"\x01" * 4096)
    assert (other_card_recorded(str(out), str(stock))
            == "Godzilla Pro 1.16 Custom V1.91.raw")


def test_a_folder_with_no_sidecar_or_no_card_is_quiet(tmp_path):
    img = tmp_path / "game.raw"
    _make_image(str(img))
    # older extract: no sidecar at all
    assert other_card_recorded(str(tmp_path), str(img)) is None
    out = tmp_path / "extract"
    out.mkdir()
    write_extract_source(str(out), str(img))
    assert other_card_recorded(str(out), "") is None
    assert other_card_recorded("", str(img)) is None


def test_the_build_asks_before_dropping_the_baked_mods(tmp_path):
    """The message names both cards, says what a build actually carries, and
    points at the route that does carry baked mods; _start_write asks it."""
    import inspect

    from pinball_decryptor import app as app_mod

    msg = app_mod.other_card_message(
        str(tmp_path), "Godzilla Pro 1.16 Custom V1.91.raw",
        r"D:\cards\godzilla_pro-1_16_0.raw")
    assert "Godzilla Pro 1.16 Custom V1.91.raw" in msg
    assert "godzilla_pro-1_16_0.raw" in msg
    assert "will NOT be on this card" in msg
    assert "Transfer mods" in msg
    assert msg.rstrip().endswith("Build anyway?")

    src = inspect.getsource(app_mod.App._start_write)
    assert "other_card_recorded(assets_dir, original)" in src
    assert "other_card_message(assets_dir, other, original)" in src
    # and the same thing lands in the log, for a log posted days later
    assert src.index("other_card_recorded") < src.index("log_cb(")


def test_a_folder_extracted_from_a_built_card_is_named(tmp_path):
    """A build record beside the card is what says "this folder's content
    already carries mods" — the transfer's pending route leaves those
    behind, so it has to be able to tell (PAD-176)."""
    built = tmp_path / "Godzilla Pro 1.16 Custom V1.91.raw"
    _make_image(str(built))
    out = tmp_path / "V1.92"
    out.mkdir()
    write_extract_source(str(out), str(built))
    # no record beside it yet: a stock card, nothing to say
    assert built_card_source(str(out)) is None

    (tmp_path / ("Godzilla Pro 1.16 Custom V1.91.raw"
                 + BUILD_RECORD_SUFFIX)).write_text("{}", encoding="utf-8")
    assert built_card_source(str(out)) == "Godzilla Pro 1.16 Custom V1.91.raw"
    assert built_card_source(str(tmp_path)) is None      # no sidecar at all


def test_the_build_record_suffix_matches_the_engine_s():
    """Duplicated to keep this module plugin-free; pinned so it can't drift."""
    from pinball_decryptor.plugins.stern import engine
    assert BUILD_RECORD_SUFFIX == engine.BUILD_MANIFEST_SUFFIX


def test_the_transfer_says_baked_mods_are_not_coming(tmp_path):
    """The pending route carries this folder's replacements only; when the
    folder came off a built card, say so before it runs."""
    import inspect

    from pinball_decryptor import app as app_mod

    src = inspect.getsource(app_mod.App._transfer_plan_ready)
    assert "built_card_source(source_dir)" in src
    assert "NOT included" in src
    assert "intro=intro" in src
    # and it says it in the log too, not only in a dialog that is dismissed
    assert 'append_log(intro' in src
