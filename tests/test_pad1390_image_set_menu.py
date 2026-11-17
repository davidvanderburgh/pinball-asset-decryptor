"""PAD-1390: IMAGE SET (Simon's image sets, :mod:`.scene_variants`) is one of the app's service-menu settings: a row of its
own where the game has a spare one, else one more setting on the MORE SETTINGS rows (PAD-1382). Its runtime reads the
value through setting_addr like every other setting's, and the build points scenes.cfg's ``setting`` line at the
address the menu gave it. Emulator proof: artifacts/PAD-1390/emulator."""
import os
import re

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern import scene_variants as SV
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable

from tests.test_pad1382_more_settings import LE116, PRO116, RUNTIME, _program, _wanted

SCENE = "godzilla_le/auto_loaded/cac32730af42" + "0" * 28 + "/scene.radium"
NAMES = ["Standard", "Dark", "Light"]


def _image_row():
    from pinball_decryptor.plugins.stern import engine as E
    return E._ImageSetMenu(NAMES, lambda *a, **k: None).wanted()


def test_the_menu_job_offers_one_value_a_set_by_name():
    key, values, names = _image_row()[:3]
    assert key == MS.IMAGE_SET == "image_set"
    assert values == 3 and list(names) == NAMES
    assert MS.SETTINGS[MS.IMAGE_SET][1] == "IMAGE SET" and MS.IMAGE_SET not in MS.NOT_SHARED


def test_no_more_sets_than_a_menu_setting_has_values():
    raw = {"names": ["S%d" % k for k in range(1, 13)],
           "scenes": {SCENE: {str(k): {"card": True} for k in range(2, 13)}}}
    got = SV.normalise(raw)
    assert SV.MAX_SETS == MS.MAX_VALUES
    assert len(got["names"]) == MS.MAX_VALUES and max(got["scenes"][SCENE]) == MS.MAX_VALUES


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_image_set_alone_has_a_row_of_its_own(card):
    t = AdjustmentTable(_program(card))
    settings, _w, _c, refused = MS.plan_many(t, [_image_row()])
    assert refused == {}
    (s,) = settings
    assert s.key == MS.IMAGE_SET and not MS.is_shared(s) and s.values == 3 and s.low == 1
    assert "Standard" in s.help and "Dark" in s.help


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_image_set_shares_the_more_settings_rows_when_none_is_spare(card):
    # Simon's card: music modes, co-op and handicaps took all three spare rows; the picture settings and IMAGE SET too
    t = AdjustmentTable(_program(card))
    settings, _w, _c, refused = MS.plan_many(t, _wanted(music=True) + [_image_row()])
    assert refused == {}
    by = {s.key: s for s in settings}
    img = by[MS.IMAGE_SET]
    assert MS.is_shared(img)
    k = img.shared[0]
    assert img.live == MS.SHARED_BASE + 4 * k and img.where.endswith("MORE SETTINGS %d" % k)
    assert (img.low, img.values) == (1, 3)
    assert by[MS.MORE_SELECT].values == 7                       # music, 3 pictures, co-op, handicap, image set
    text = MS.shared_cfg_text(settings)
    assert re.search(r"^option\t%d\timage_set\t1\t3\t1\t" % k, text, re.M), text


def test_scenes_cfg_reads_the_value_where_the_menu_put_it():
    slots = {"fopen64": 0x1000, "eglSwapBuffers": 0x2000}
    text = SV.cfg_text(slots, MS.SHARED_BASE + 4 * 7, 3, [(SCENE, 2, SV.file_name(SCENE, 2))])
    assert "setting\t0xfade001c\t3\n" in text


def test_the_runtime_takes_image_sets_address_through_setting_addr():
    src = open(RUNTIME, encoding="utf-8").read()
    assert "scnv_live = (unsigned)setting_addr(scnv_live);" in src
    # read after the shared rows are loaded: mset_arm comes before scnv_arm, and scnv_arm after pic_arm
    assert src.index("    mset_arm();") < src.index("    pic_arm();") < src.index("    scnv_arm();")


def test_the_service_menu_wants_image_set_for_a_project_with_sets(tmp_path):
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.plugins.stern import service_menu as SM
    project = str(tmp_path)
    assert all(w[0] != MS.IMAGE_SET for w in SM.wanted(project))
    staged_changes.save(project, {SV.STAGED_KEY: {"names": NAMES, "scenes": {SCENE: {"2": {"card": True},
                                                                                     "3": {"card": True}}}}})
    assert all(w[0] != MS.IMAGE_SET for w in SM.wanted(project))       # PAD-1393 round 3: not until ticked
    SM.save(project, {"on": ["image_set"]})
    rows = [w for w in SM.wanted(project) if w[0] == MS.IMAGE_SET]
    assert rows and rows[0][1] == 3 and list(rows[0][2]) == NAMES


def test_the_service_menu_tab_lists_image_set():
    from pinball_decryptor.webui.tabs import svcmenu
    assert any(k == MS.IMAGE_SET for k, _n, _w in svcmenu.SETTINGS)


def test_spike3_builds_say_image_sets_are_left_out():
    from pinball_decryptor.plugins.stern import spike3_modes as S3M
    (line,) = S3M.family_left_out_lines(["image sets"])
    assert line.startswith("Image sets: left out of this build:")
