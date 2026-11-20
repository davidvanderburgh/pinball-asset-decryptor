"""The whole-project saves carry the themes and the Service menu rows (Simon, 2026-11-20).

Simon: "can you also check saving and loading works for the new service menu mode (a scene save shouldn't touch that)
and in other areas where you can save the entire project". Project > Export replacement files (its replacements.json),
the mod pack and the Images tab's Save / load settings each lost the themes (names, each theme's own pictures, Keep
size ticks); the first two lost the Service menu rows too, without which a Write drops the themes (IMAGE SET unticked).
"""
import hashlib
import json
import os
import zipfile

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import modpack, replacement_export as rx, staged_changes, tab_settings as TS
from pinball_decryptor.plugins.stern import scene_share, scene_variants as SV, service_menu
from tests.test_pad502_save_game_picture_profiles import BACK, ELSE, HERO, SEPIA, _project
from tests.test_scene_save_themes import _themed

pytest.importorskip("PIL.Image")

ROWS = {"on": ["IMAGE_SET"], "order": ["IMAGE_SET"]}


def _baseline(folder):
    """A .checksums.md5 of the extract's pictures as they are, so a mod pack has a baseline."""
    lines = []
    for top, _dirs, files in os.walk(os.path.join(folder, "images")):
        for f in files:
            full = os.path.join(top, f)
            with open(full, "rb") as g:
                lines.append("%s\t%s\n" % (os.path.relpath(full, folder).replace("\\", "/"),
                                           hashlib.md5(g.read()).hexdigest()))
    with open(os.path.join(folder, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)


def _with_rows(folder):
    side = staged_changes.load(folder)
    side[service_menu.STAGED_KEY] = dict(ROWS)
    staged_changes.save(folder, side)
    return folder


def test_the_export_record_carries_the_themes_and_the_service_menu(tmp_path):
    src = _with_rows(_themed(tmp_path))
    staged = staged_changes.load(src)
    dest = tmp_path / "export"
    out = rx.export(staged, rx.plan(staged, str(dest), src))
    rest = {"defaults": rx.defaults_of(src)}
    path = rx.write_record(str(dest), rx.make_record(staged, out["mapping"], str(dest), rest=rest))
    rec = json.loads(open(path, encoding="utf-8").read())
    themes = rec["records"][SV.STAGED_KEY]
    assert themes["names"] == ["Standard", "DARK", "LIGHT"]
    assert themes["images"]["2"]["images/" + HERO].startswith("Images/")        # named inside the export
    assert rec["defaults"][service_menu.STAGED_KEY] == ROWS
    # the folder moves, and a fresh extract with a theme of its own takes it in
    moved = tmp_path / "elsewhere"
    os.rename(dest, moved)
    _rec, records, missing = rx.read_record(str(moved / rx.RECORD_NAME))
    assert missing == []
    fresh = _project(tmp_path, "fresh")
    SV.set_themes_on(fresh, True)
    SV.add_set(fresh, "OLD")
    data, _n = rx.import_record(staged_changes.load(fresh), records)
    staged_changes.save(fresh, data)
    modpack.apply_extras(fresh, _rec["defaults"])
    assert SV.set_names(fresh) == ["Standard", "DARK", "LIGHT"]                  # the record's, whole
    hero = SV.set_pictures(fresh, 2)["images/" + HERO]
    assert os.path.dirname(hero) == str(moved / "Images") and os.path.isfile(hero)
    assert SV.keeps_size(fresh, 2, "images/" + HERO) is True
    side = staged_changes.load(fresh)
    assert side[cp.FILE_PROFILES_KEY["images"]][SV.theme_key(3, "images/" + BACK)] == SEPIA
    assert side[service_menu.STAGED_KEY] == ROWS


def test_a_mod_pack_carries_the_themes_and_the_service_menu(tmp_path):
    src = _with_rows(_themed(tmp_path))
    _baseline(src)
    logs = []
    zip_path = str(tmp_path / "pack.zip")
    # themes alone change no file of the extract and are still a pack
    n, _ = modpack.export_mod_pack(src, zip_path, log_cb=lambda t, lvl="info": logs.append(t))
    assert n == 0
    assert any("themes (2: 3 theme picture(s) or color(s))" in t and "the Service menu rows" in t for t in logs)
    with zipfile.ZipFile(zip_path) as zf:
        man = json.loads(zf.read(modpack.MANIFEST_NAME).decode("utf-8"))
        names = zf.namelist()
    rec = man["extras"]["themes"]
    member = rec["pictures"]["images/" + HERO]["themes"]["2"]["file"]
    assert member.startswith(modpack.THEMES_DIR + "/") and member in names
    assert man["extras"][service_menu.STAGED_KEY] == ROWS

    dest = _project(tmp_path, "dest")
    _baseline(dest)
    plan = modpack.inspect_mod_pack(zip_path, dest)
    assert plan["foreign"] == []                       # the theme pictures are not files of the card
    res = modpack.import_mod_pack(zip_path, dest, plan=plan, log_cb=lambda t, lvl="info": logs.append(t))
    assert res["extras"]["themes"] == 3 and res["extras"][service_menu.STAGED_KEY] == 1
    assert SV.themes_on(dest) and SV.set_names(dest) == ["Standard", "DARK", "LIGHT"]
    hero = SV.set_pictures(dest, 2)["images/" + HERO]
    assert hero.startswith(os.path.join(dest, scene_share.SHARED_DIR))
    with open(hero, "rb") as f, open(str(tmp_path / "dark hero.png"), "rb") as g:
        assert f.read() == g.read()
    assert SV.keeps_size(dest, 2, "images/" + HERO) is True
    assert "images/" + ELSE in SV.set_pictures(dest, 2)
    side = staged_changes.load(dest)
    assert side[cp.FILE_PROFILES_KEY["images"]][SV.theme_key(3, "images/" + BACK)] == SEPIA
    assert side[service_menu.STAGED_KEY] == ROWS
    assert any("Restored from the pack: 3 theme picture(s) or color(s)" in t for t in logs)


def test_a_mod_pack_without_themes_carries_none(tmp_path):
    p = _project(tmp_path, "plain")
    assert modpack.pack_themes(p) == (None, [])
    assert service_menu.STAGED_KEY not in modpack.project_extras(p)


def test_the_images_settings_file_carries_the_themes(tmp_path):
    src = _themed(tmp_path)
    path = str(tmp_path / "images settings.json")
    TS.export_media(staged_changes.load(src), "images", path)
    doc = TS.read(path, "images")
    assert doc["sections"][SV.STAGED_KEY]["names"] == ["Standard", "DARK", "LIGHT"]
    dest = _project(tmp_path, "dest")
    slots = {"images/" + r for r in (HERO, BACK)}                 # this card lacks ELSE
    res = TS.merge_media(staged_changes.load(dest), doc, "images", slots)
    assert res.themes == 2
    staged_changes.save(dest, res.data)
    assert SV.set_names(dest) == ["Standard", "DARK", "LIGHT"] and SV.themes_on(dest)
    assert set(SV.set_pictures(dest, 2)) == {"images/" + HERO}
    assert "images/" + ELSE in res.missing
    assert SV.keeps_size(dest, 2, "images/" + HERO) is True
    # a theme's own color is its picture's: kept, where before it was counted as a slot this card lacks
    key = SV.theme_key(3, "images/" + BACK)
    assert res.data[cp.FILE_PROFILES_KEY["images"]][key] == SEPIA
    assert res.data[cp.IMAGE_SLOTS_KEY][key] is True
    assert key not in res.missing and "images/" + BACK in res.slots
