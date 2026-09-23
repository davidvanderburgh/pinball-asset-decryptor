"""Feedback batch 26 — logic-level tests for the Images-search and Audio-stop
fixes.

No window is built: the Images tab's grouping and search helpers only touch
plain attributes, so duck-typed ``self`` stubs exercise them the way the real
tab does.  (The Audio-stop half of this batch lives in the page's players
now; the queued-step cancel it relied on is covered in test_gui_batch28.)
"""

from types import SimpleNamespace

from pinball_decryptor.webui.tabs.images import (ImagesTab,
                                                 compute_key_tails,
                                                 scan_image_groups)


# ---------------------------------------------------------------------------
# Images search on a pre-slicer extract: the font-atlas skip (v0.100.2) keyed
# off the glyphs/<stem>/ dirs, which an extract made before the slicer
# (v0.45) doesn't have — so scenes still wore their font's name and "stern"
# phantom-matched ~44% of a card's rows through invisible labels (a tester's
# older Led Zeppelin project).  With no glyph record at all, no member may
# supply a label hint; the slicer's manifest also names atlases, covering a
# project whose glyphs folder was pruned.
# ---------------------------------------------------------------------------

_ATLAS = "radimg_Stern_FooFont_512x512_deadbeef.png"
_NAMED = "radimg_Char_Select_8x8_00000001.png"
_PLAIN = "radimg_8x8_00000002.png"
_CARD_A = "/game/scenes/aaaaaaaa1111/scene.radium"
_CARD_B = "/game/scenes/bbbbbbbb2222/scene.radium"


def _seed_two_scenes(tmp_path):
    """Scene A: font atlas first, real named element later.  Scene B: the
    font is the only named member."""
    st = tmp_path / "images" / "scene_textures"
    st.mkdir(parents=True)
    for fn in (_ATLAS, _NAMED, _PLAIN):
        (st / fn).write_bytes(b"\x89PNG-fake")
    with open(st / "radium_images.txt", "w", encoding="utf-8") as f:
        f.write("# output\tradium card path\tdata offset\tlength"
                "\tpad_w\tpad_h\tfmt\n")
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (_ATLAS, _CARD_A))
        f.write("scene_textures/%s\t%s\t200\t16\t8\t8\t5\n" % (_NAMED, _CARD_A))
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (_ATLAS, _CARD_B))
        f.write("scene_textures/%s\t%s\t200\t16\t8\t8\t5\n" % (_PLAIN, _CARD_B))
    return st


def test_glyph_manifest_vets_atlases_without_the_glyphs_dir(tmp_path):
    st = _seed_two_scenes(tmp_path)
    with open(st / "glyph_images.txt", "w", encoding="utf-8") as f:
        f.write("# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\n")
        f.write("scene_textures/glyphs/%s/U+0041_A.png\tscene_textures/%s"
                "\t0x0041\t1\t1\t8\t8\tStern_FooFont\n"
                % (_ATLAS[:-4], _ATLAS))
    groups, _occ, _where = scan_image_groups(str(tmp_path))
    assert groups["images/scene_textures/" + _NAMED][1] == \
        "Char_Select · aaaaaaaa"
    assert groups["images/scene_textures/" + _PLAIN][1] == "bbbbbbbb"


def test_pre_slicer_extract_trusts_no_hint_at_all(tmp_path):
    _seed_two_scenes(tmp_path)          # no glyphs dir, no glyph manifest
    groups, _occ, where = scan_image_groups(str(tmp_path))
    for rel in ("images/scene_textures/" + _ATLAS,
                "images/scene_textures/" + _NAMED,
                "images/scene_textures/" + _PLAIN):
        assert " · " not in groups[rel][1]
    assert groups["images/scene_textures/" + _NAMED][1] == "aaaaaaaa"
    assert groups["images/scene_textures/" + _PLAIN][1] == "bbbbbbbb"
    # And the search consequence: "stern" no longer matches any GROUP; a
    # scene hash still finds its scene.
    me = SimpleNamespace(
        _group_tags={},
        _key_tails=compute_key_tails(groups, where))
    for g in groups.values():
        assert not ImagesTab._group_matches(me, g, "stern")
    named_group = groups["images/scene_textures/" + _NAMED]
    assert ImagesTab._group_matches(me, named_group, "aaaaaaaa1111")


def test_modern_extract_keeps_its_hint_labels(tmp_path):
    st = _seed_two_scenes(tmp_path)
    (st / "glyphs" / _ATLAS[:-4]).mkdir(parents=True)
    groups, _occ, _where = scan_image_groups(str(tmp_path))
    assert groups["images/scene_textures/" + _NAMED][1] == \
        "Char_Select · aaaaaaaa"
