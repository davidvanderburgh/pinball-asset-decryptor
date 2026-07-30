"""Feedback batch 26 — logic-level tests for the Images-search and Audio-stop
fixes.

No Tk window is built: the methods under test only touch plain attributes,
so duck-typed ``self`` stubs exercise them the way the real window does.
"""

from types import SimpleNamespace

from pinball_decryptor.gui.main_window import (_AudioPreviewPane,
                                               _VideoPreviewPane, MainWindow)


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
    groups, _occ, _where = MainWindow._scan_image_groups(str(tmp_path))
    assert groups["images/scene_textures/" + _NAMED][1] == \
        "Char_Select · aaaaaaaa"
    assert groups["images/scene_textures/" + _PLAIN][1] == "bbbbbbbb"


def test_pre_slicer_extract_trusts_no_hint_at_all(tmp_path):
    _seed_two_scenes(tmp_path)          # no glyphs dir, no glyph manifest
    groups, _occ, where = MainWindow._scan_image_groups(str(tmp_path))
    for rel in ("images/scene_textures/" + _ATLAS,
                "images/scene_textures/" + _NAMED,
                "images/scene_textures/" + _PLAIN):
        assert " · " not in groups[rel][1]
    assert groups["images/scene_textures/" + _NAMED][1] == "aaaaaaaa"
    assert groups["images/scene_textures/" + _PLAIN][1] == "bbbbbbbb"
    # And the search consequence: "stern" no longer matches any GROUP; a
    # scene hash still finds its scene.
    me = SimpleNamespace(
        _image_group_tags={},
        _image_group_key_tails=MainWindow._compute_image_key_tails(
            groups, where))
    for g in groups.values():
        assert not MainWindow._image_group_matches(me, g, "stern")
    named_group = groups["images/scene_textures/" + _NAMED]
    assert MainWindow._image_group_matches(me, named_group, "aaaaaaaa1111")


def test_modern_extract_keeps_its_hint_labels(tmp_path):
    st = _seed_two_scenes(tmp_path)
    (st / "glyphs" / _ATLAS[:-4]).mkdir(parents=True)
    groups, _occ, _where = MainWindow._scan_image_groups(str(tmp_path))
    assert groups["images/scene_textures/" + _NAMED][1] == \
        "Char_Select · aaaaaaaa"


# ---------------------------------------------------------------------------
# Audio ■: sequential play moves the sound between the Original and
# Replacement panes, so stop on the pane in front of you must silence BOTH
# ("tie the stop buttons together (like slings!)" — a tester).  Only the
# stopped pane rewinds; the sibling keeps its playhead.
# ---------------------------------------------------------------------------

class _PaneStub:
    stop_to_start = _AudioPreviewPane.stop_to_start

    def __init__(self, pos=3.3):
        self.pos = pos
        self.sibling = None
        self.stops = 0

    def stop_playback(self):
        self.stops += 1

    def _draw_playhead(self):
        pass


def test_stop_button_silences_both_audio_panes():
    a, b = _PaneStub(pos=3.3), _PaneStub(pos=7.7)
    a.sibling, b.sibling = b, a
    a.stop_to_start()
    assert a.stops == 1 and b.stops == 1
    assert a.pos == 0.0
    assert b.pos == 7.7                  # sibling keeps its playhead


def test_stop_button_safe_before_the_sibling_is_wired():
    a = _PaneStub()
    a.stop_to_start()
    assert a.stops == 1 and a.pos == 0.0


class _VideoPaneStub(_PaneStub):
    stop_to_start = _VideoPreviewPane.stop_to_start

    def __init__(self, pos=3.3):
        super().__init__(pos)
        self.path = None                 # no poster re-render in the stub


def test_video_stop_button_matches_the_audio_rule():
    a, b = _VideoPaneStub(pos=1.1), _VideoPaneStub(pos=2.2)
    a.sibling, b.sibling = b, a
    a.stop_to_start()
    assert a.stops == 1 and b.stops == 1
    assert a.pos == 0.0 and b.pos == 2.2
