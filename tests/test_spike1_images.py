"""PAD-870: Stern Spike 1 DMD pictures, font glyphs and animation frames -
read, extract, write back (in place, or into the free front page), revert.

The format is S.A.M.'s (``pinmame_classic.sam_anim``); these tests pin the
Spike 1 side: the u64 picture table the game program's hooks name, the fonts'
glyph arrays, where each record's PNG goes, and the writes.  Proven on real
cards in the Spike 1 emulator (KISS LE 1.41: edited frames and a font letter
on the DMD), see spike1_images' docstring.
"""
import glob
import hashlib
import hmac
import os
import struct

import numpy as np
import pytest
from PIL import Image

from pinball_decryptor.core import checksums
from pinball_decryptor.plugins.pinmame_classic import sam_anim
from pinball_decryptor.plugins.stern import sam_anim_assets, sidx as sidx_mod
from pinball_decryptor.plugins.stern import spike1, spike1_images as si
from pinball_decryptor.plugins.stern.formats import spike1_linux_partitions
from tests import synthetic

FRONT_END = 0x120000


def _bytes(front_page=True):
    """``(image.bin bytes, Layout, frames)``: the picture area after an
    erased 1.15 MB front page (*front_page*) or right at the start of the
    file, the way Ghostbusters lays it out."""
    base = FRONT_END if front_page else 0x40
    area, lay, frames = synthetic.make_spike1_pictures(base)
    blob = bytearray(b"\xff" * base if front_page else bytes(base)) + area
    lowest = lay["table"] if front_page else lay["fonts"]
    return bytes(blob), si.Layout(lowest=lowest, **lay), frames


def _png(path, frame):
    Image.fromarray(sam_anim_assets.to_la(frame), "LA").save(path)


def _apply(data, writes):
    out = bytearray(data)
    for off, payload in writes:
        out[off:off + len(payload)] = payload
    return bytes(out)


def _decode(data, lay):
    return sam_anim.decode_all(data, si.read_table(data, lay))


def test_read_table_fonts_and_paths():
    data, lay, frames = _bytes()
    art = si.read_table(data, lay)
    assert [r.fmt for r in art.records] == [0, 0, 0, 7, 9, 1, 12]
    assert art.fonts == [(0, 3, [(0, "A"), (1, "B")])]
    # a glyph stays where its font points; everything else may move
    assert not art.movable[0] and not art.movable[1]
    assert all(art.movable[n] for n in range(2, 7))
    rels = si.rel_paths(art)
    assert rels[0] == "images/fonts/font00 (3 px)/img0000-A.png"
    assert rels[1] == "images/fonts/font00 (3 px)/img0001-B.png"
    assert rels[2] == "images/pictures/img0002.png"
    # the keyframe a delta builds on is an animation frame, not a still
    assert [rels[n].split("/")[0] for n in (3, 4, 5, 6)] == ["animations"] * 4
    got = _decode(data, lay)
    for n, f in frames.items():
        assert np.array_equal(got[n], f), n


def test_names_take_five_digits_on_big_tables():
    assert si.png_name(42) == "img0042.png"
    assert si.png_name(42, 24195) == "img00042.png"
    assert sam_anim_assets.parse_png_stem("img00042-x2C") == 42


def test_extract_all_writes_every_record(tmp_path):
    data, lay, frames = _bytes()
    res = si.extract_all(data, lay, str(tmp_path))
    assert res == {"pictures": 1, "fonts": 1, "glyphs": 2, "frames": 4}
    art = si.read_table(data, lay)
    for n, rel in si.rel_paths(art).items():
        img = Image.open(os.path.join(str(tmp_path), *rel.split("/")))
        assert np.array_equal(sam_anim_assets.from_image(img), frames[n]), rel


def _edit(tmp_path, edits):
    changed = {}
    for n, f in edits.items():
        p = str(tmp_path / ("img%04d.png" % n))
        _png(p, f)
        changed[n] = p
    return changed


def test_plan_in_place_keeps_every_other_frame(tmp_path):
    data, lay, frames = _bytes()
    still = (15 - frames[2]).astype(np.uint8)
    glyph = np.full((3, 4), 15, np.uint8)
    writes, n, skipped = si.plan(data, lay,
                                 _edit(tmp_path, {2: still, 0: glyph}))
    assert n == 2 and not skipped
    new = _apply(data, writes)
    assert len(new) == len(data)
    got = _decode(new, lay)
    assert np.array_equal(got[2], still) and np.array_equal(got[0], glyph)
    for k in (1, 3, 4, 5, 6):
        assert np.array_equal(got[k], frames[k]), k
    # nothing moved: the table is as it was
    t = slice(lay.table, lay.table + 8 * lay.count)
    assert new[t] == data[t]
    assert new[:FRONT_END] == data[:FRONT_END]


def test_a_frame_too_big_for_its_place_moves_to_the_front_page(tmp_path):
    data, lay, frames = _bytes()
    noise = np.random.default_rng(7).integers(0, 16, (8, 16)).astype(np.uint8)
    logs = []
    writes, n, skipped = si.plan(data, lay, _edit(tmp_path, {5: noise}),
                                 log=lambda m, *a: logs.append(m))
    assert n == 1 and not skipped
    assert any("moved to free space" in m for m in logs)
    new = _apply(data, writes)
    off = struct.unpack_from("<Q", new, lay.table + 8 * 5)[0]
    assert 0x1000 <= off < FRONT_END - 0x1000
    got = _decode(new, lay)
    assert np.array_equal(got[5], noise)
    for k in (0, 1, 2, 3, 4, 6):
        assert np.array_equal(got[k], frames[k]), k

    # a second build from that card: the moved frame is held, a new one
    # goes after it, and re-editing the moved one works in its new place
    noise2 = (15 - noise).astype(np.uint8)
    still = np.random.default_rng(8).integers(0, 16, (8, 16)) \
        .astype(np.uint8)
    writes2, n2, _s = si.plan(new, lay, _edit(tmp_path, {5: noise2,
                                                         6: still}))
    assert n2 == 2
    new2 = _apply(new, writes2)
    got2 = _decode(new2, lay)
    assert np.array_equal(got2[5], noise2) and np.array_equal(got2[6], still)
    assert np.array_equal(got2[2], frames[2])


def test_without_a_free_page_a_frame_gets_fewer_shades_or_stays(tmp_path):
    data, lay, frames = _bytes(front_page=False)
    noise = np.random.default_rng(7).integers(0, 16, (8, 16)).astype(np.uint8)
    logs = []
    writes, n, skipped = si.plan(data, lay, _edit(tmp_path, {5: noise}),
                                 log=lambda m, *a: logs.append(m))
    new = _apply(data, writes)
    off = struct.unpack_from("<Q", new, lay.table + 8 * 5)[0]
    assert off >= lay.table
    got = _decode(new, lay)
    if skipped:
        assert np.array_equal(got[5], frames[5])
        assert any("keeps its original picture" in m for m in logs)
    else:
        assert any("simplified" in m for m in logs)
    for k in (0, 1, 2, 3, 4, 6):
        assert np.array_equal(got[k], frames[k]), k


def test_editing_a_keyframe_rewrites_the_delta_on_it(tmp_path):
    data, lay, frames = _bytes()
    key = frames[3].copy()
    key[0:2, :] = 5
    writes, n, _s = si.plan(data, lay, _edit(tmp_path, {3: key}))
    got = _decode(_apply(data, writes), lay)
    assert np.array_equal(got[3], key)
    # the delta still shows the frame it showed (its own pixels on the old
    # keyframe), so only the edited picture changes on the DMD
    assert np.array_equal(got[4], frames[4])


def test_a_picture_of_another_size_is_scaled_to_fit(tmp_path):
    data, lay, frames = _bytes()
    p = str(tmp_path / "big.png")
    rgb = Image.new("RGB", (64, 32), (255, 255, 255))
    rgb.paste((0, 0, 0), (0, 0, 32, 32))
    rgb.save(p)
    logs = []
    writes, n, skipped = si.plan(data, lay, {2: p},
                                 log=lambda m, *a: logs.append(m))
    assert n == 1 and not skipped
    assert any("scaled from 64x32" in m for m in logs)
    got = _decode(_apply(data, writes), lay)
    assert (got[2][:, :7] == 0).all() and (got[2][:, 9:] == 15).all()


def test_an_unreadable_png_is_skipped(tmp_path):
    data, lay, _frames = _bytes()
    p = tmp_path / "img0002.png"
    p.write_bytes(b"not a png")
    writes, n, skipped = si.plan(data, lay, {2: str(p)})
    assert (writes, n, skipped) == ([], 0, ["img0002.png"])


def test_locate_reads_the_game_programs_hooks():
    lay = dict(table=0x120100, count=7, fonts=0x120000, font_count=1)
    elf = synthetic.make_spike1_picture_elf({
        "hook_image_table_flash_offset": (lay["table"], 8),
        "hook_image_table_entry_count": (lay["count"], 4),
        "hook_font_table_flash_offset": (lay["fonts"], 8),
        "hook_font_table_entry_count": (lay["font_count"], 4),
        "hook_sound_script_table_flash_offset": (0x120080, 8),
    })
    got = si.locate(elf)
    assert got == si.Layout(lowest=0x120000, **lay)
    with pytest.raises(si.Spike1ImagesError):
        si.locate(synthetic.make_spike1_picture_elf({}))


def test_front_page_only_when_nothing_lies_in_it():
    data, lay, _f = _bytes()
    art = si.read_table(data, lay)
    assert si.FrontPage(art, len(data)).room == 0x11E000
    # a title whose sound scripts sit in the first page (Ghostbusters)
    low = si.Layout(lay.table, lay.count, lay.fonts, lay.font_count, 0xC0)
    assert si.FrontPage(si.read_table(data, low), len(data)).room == 0


# --------------------------------------------------------------------------
# on a card
# --------------------------------------------------------------------------

def _card(tmp_path):
    blob, lay, frames = synthetic.add_spike1_pictures(
        synthetic.make_spike1_image_bin()[0])
    elf = synthetic.make_spike1_picture_elf({
        "hook_image_table_flash_offset": (lay["table"], 8),
        "hook_image_table_entry_count": (lay["count"], 4),
        "hook_font_table_flash_offset": (lay["fonts"], 8),
        "hook_font_table_entry_count": (lay["font_count"], 4),
        "hook_sound_script_table_flash_offset": (0xC0, 8),
    })
    card = str(tmp_path / "synth.iso")
    synthetic.make_spike1_card(card, game_elf=elf, pictures=True)
    return card, frames


def _card_image_bin(card):
    with open(card, "rb") as f:
        reader, game_dir, node, _sp, sn = spike1.locate_assets(
            f, spike1_linux_partitions(card))
        return (game_dir, reader.read_file_bytes(node),
                reader.read_file_bytes(sn))


def test_card_extract_write_and_revert(tmp_path):
    card, frames = _card(tmp_path)
    out = str(tmp_path / "proj")
    os.makedirs(out)
    res = spike1.extract_all(card, spike1_linux_partitions(card), out)
    assert res["pictures"] == {"pictures": 1, "fonts": 1, "glyphs": 2,
                               "frames": 4}
    assert res["sounds"] == 2          # the sounds are extracted as before
    checksums.generate_checksums(out)
    rel_b = "images/fonts/font00 (3 px)/img0001-B.png"
    rel_s = "images/pictures/img0002.png"
    assert os.path.isfile(os.path.join(out, *rel_b.split("/")))

    still = (15 - frames[2]).astype(np.uint8)
    glyph = np.full((3, 4), 15, np.uint8)
    _png(os.path.join(out, *rel_s.split("/")), still)
    _png(os.path.join(out, *rel_b.split("/")), glyph)
    built = str(tmp_path / "out.iso")
    res = spike1.write_image(card, out, built)
    assert res["images"] == 2 and res["audio"] == 0 and not res["skipped"]

    game_dir, new, sdata = _card_image_bin(built)
    got = sam_anim.decode_all(new, si.read_table(new, si.Layout(
        lowest=0xC0, **synthetic.add_spike1_pictures(
            synthetic.make_spike1_image_bin()[0])[1])))
    assert np.array_equal(got[2], still) and np.array_equal(got[1], glyph)
    for k in (0, 3, 4, 5, 6):
        assert np.array_equal(got[k], frames[k]), k
    # the card's own validation record covers the patched image.bin
    recs, _crc, _fmt = sidx_mod.parse_records(sdata)
    po = recs["%s/image.bin" % game_dir]
    assert sdata[po + 21:po + 41] == hmac.new(
        sidx_mod.SIDX_KEY, new, hashlib.sha1).digest()
    assert sdata[po + 41:po + 57] == hashlib.md5(new).digest()
    # the sounds still parse on the built card
    assert len(spike1.parse_master(new)["records"]) == 2

    # Revert puts the card's original picture back over the edit
    reverted, failed = spike1.revert_assets(card, out, [rel_s, rel_b])
    assert sorted(reverted) == sorted([rel_s, rel_b]) and not failed
    img = Image.open(os.path.join(out, *rel_s.split("/")))
    assert np.array_equal(sam_anim_assets.from_image(img), frames[2])


def test_images_tab_replacement_reaches_the_card(tmp_path):
    """The Images tab's way in: a replacement of another size and colour
    assigned to a slot is staged over the slot's PNG by the Write
    (image_slots.stage_replacements), then written into the card."""
    from pinball_decryptor.core.image_slots import (scan_image_slots,
                                                    stage_replacements)
    card, frames = _card(tmp_path)
    out = str(tmp_path / "proj")
    os.makedirs(out)
    spike1.extract_all(card, spike1_linux_partitions(card), out)
    checksums.generate_checksums(out)
    rel = "animations/img0005.png"
    rep = str(tmp_path / "mine.png")
    rgb = Image.new("RGB", (64, 32), (255, 255, 255))
    rgb.paste((0, 0, 0), (0, 0, 32, 32))
    rgb.save(rep)
    slots = {s.rel_path: s for s in scan_image_slots(out)}
    assert rel in slots
    staged, failures = stage_replacements({rel: slots[rel]}, {rel: rep},
                                          assets_dir=out)
    assert staged == 1 and not failures
    built = str(tmp_path / "out.iso")
    res = spike1.write_image(card, out, built)
    assert res["images"] == 1, res
    _gd, new, _s = _card_image_bin(built)
    lay = si.Layout(lowest=0xC0, **synthetic.add_spike1_pictures(
        synthetic.make_spike1_image_bin()[0])[1])
    got = sam_anim.decode_all(new, si.read_table(new, lay))
    assert (got[5][:, :7] == 0).all() and (got[5][:, 9:] == 15).all()
    for k in (0, 1, 2, 3, 4, 6):
        assert np.array_equal(got[k], frames[k]), k


def test_card_without_picture_hooks_still_extracts_sounds(tmp_path):
    card = str(tmp_path / "plain.iso")
    synthetic.make_spike1_card(card)
    out = str(tmp_path / "proj")
    os.makedirs(out)
    logs = []
    res = spike1.extract_all(card, spike1_linux_partitions(card), out,
                             log=lambda m, *a: logs.append(m))
    assert res["sounds"] == 2 and res["pictures"] is None
    assert any("DMD pictures couldn't be read" in m for m in logs)
    assert not glob.glob(os.path.join(out, "animations", "*"))


def test_extract_without_images_category(tmp_path):
    card, _frames = _card(tmp_path)
    out = str(tmp_path / "proj")
    os.makedirs(out)
    res = spike1.extract_all(card, spike1_linux_partitions(card), out,
                             do_images=False)
    assert "pictures" not in res
    assert not os.path.isdir(os.path.join(out, "animations"))
