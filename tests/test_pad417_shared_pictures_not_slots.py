"""PAD-417 (DragonRR): the pictures a loaded scene file copies into the project's
"Shared pictures" folder are the user's picks for the card's slots.  The Images tab
listed each as a slot of its own, flagged "not on this card"; no slot scanner may
list them, and the baseline never takes them in."""
import os

from PIL import Image

from pinball_decryptor.core import checksums
from pinball_decryptor.core.image_slots import scan_image_slots
from pinball_decryptor.plugins.stern import scene_share


def _png(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGBA", size, (1, 2, 3, 255)).save(path)


def test_shared_pictures_is_the_folder_scene_files_load_into():
    assert scene_share.SHARED_DIR == checksums.SHARED_PICTURES_DIR
    assert checksums.SHARED_PICTURES_DIR in checksums.NON_ASSET_DIRS


def test_image_scan_skips_shared_pictures(tmp_path):
    slot = "images/scene_textures/radimg_530x726_90dbdeb2.png"
    _png(str(tmp_path / slot), (532, 728))
    _png(str(tmp_path / scene_share.SHARED_DIR / "FOR THE SHOW V3"
             / "radimg_530x726_10a34f06.png"), (632, 828))

    rels = [s.rel_path for s in scan_image_slots(str(tmp_path), probe=False)]

    assert rels == [slot]


def test_a_card_folder_of_that_name_further_down_still_scans(tmp_path):
    # only the project's own top-level folder is ours
    deep = "images/Shared pictures/a.png"
    _png(str(tmp_path / deep), (4, 4))

    rels = [s.rel_path for s in scan_image_slots(str(tmp_path), probe=False)]

    assert rels == [deep]


def test_baseline_leaves_shared_pictures_out(tmp_path):
    _png(str(tmp_path / "images" / "a.png"), (4, 4))
    _png(str(tmp_path / scene_share.SHARED_DIR / "x" / "b.png"), (4, 4))

    checksums.generate_checksums(str(tmp_path))
    base = checksums.read_baseline_any(str(tmp_path))

    assert "images/a.png" in base
    assert not [r for r in base if r.startswith(scene_share.SHARED_DIR + "/")]
