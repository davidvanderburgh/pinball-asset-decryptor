"""PAD-1260: a Stranger Things build with new music, one video and the score feed as its only mode feature
crashed with ``'NoneType' object has no attribute 'hud_scene'`` (the profile chain left the feed's out,
fixed in PAD-1255). The pick is now one helper: every feature's profile is handed to it, and a build with
no title at all refuses in plain words instead of an AttributeError."""
import re

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import mode_write as MW

FEATURES = ("variant", "sound_modes", "picture", "attract", "coop", "idle", "hand", "cabs", "comp",
            "stime", "feed")


@pytest.mark.parametrize("i", range(len(FEATURES)))
def test_each_feature_alone_names_the_title(i):
    prof = object()
    profs = [None] * len(FEATURES)
    profs[i] = prof
    assert E._build_mode_profile([], [], "", tuple(profs)) is prof


def test_the_first_feature_on_wins():
    a, b = object(), object()
    assert E._build_mode_profile([], [], "", (None, a, None, b)) is a


def test_no_title_at_all_says_so_in_words():
    with pytest.raises(MW.ModeWriteError) as e:
        E._build_mode_profile([], [], "", (None,) * len(FEATURES))
    assert "Extract" in str(e.value)


ST_CARD = r"D:\Pinball\images\Stern\spike2\stranger_things-1_13_0.Release.8G.sdcard.raw"


def test_a_real_stranger_things_profile_reaches_scene_rels(tmp_path):
    """The crash line itself, with the profile the score feed probes from a Stranger Things 1.13 project."""
    import json
    import os
    from pinball_decryptor.plugins.stern import score_feed as SF
    if not os.path.exists(ST_CARD):
        pytest.skip("no Stranger Things 1.13 card here: %s" % ST_CARD)
    (tmp_path / ".extract_source.json").write_text(json.dumps({
        "input_path": ST_CARD, "input_name": os.path.basename(ST_CARD), "card_version": "1.13.0"}))
    prof = SF.project_title(str(tmp_path), probe=True)
    assert prof is not None and not SF.title_refusal(prof)
    got = E._build_mode_profile([], [], "", (None,) * 10 + (prof,))
    hud, bank = MW.scene_rels(got)
    assert hud.endswith("/scene.radium")


def test_every_feature_profile_of_write_image_is_handed_over():
    """A feature added later with its own ``*_prof = _x_for_build(...)`` must join the hand-over, or a build of it
    alone would fall over on a None title again."""
    src = open(E.__file__, encoding="utf-8").read()
    names = set(re.findall(r"\b(\w+_prof)\b[^=\n]*= *\(*.*_for_build\(", src))
    names |= set(re.findall(r"\b\w+, (\w+_prof)\b = .*_for_build\(", src))
    at = src.index("_mprof = _build_mode_profile(")
    call = src[at:src.index("))", at)]
    missing = sorted(n for n in names if n not in call)
    assert len(names) >= len(FEATURES) and not missing, missing
