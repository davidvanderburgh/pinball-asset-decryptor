"""core.lineage -- a project's revision history that follows it across machines (PAD-427).

A project used to be tied to its cards by recorded PATHS (plus name, size and
mtime), which breaks the moment the folder or a card moves to another computer,
and a card built over the last revision read as stock.  Now each card is named
by its fingerprint and the project folder carries ``.pad-lineage.json``:
stock -> rev 1 -> rev 2 ..., so a project knows "I'm rev 2 of official Turtles
Pro 1.59" wherever its files live.

The Stern fingerprint is proven on fake ext4 cards; the lineage logic runs on
plain files with a stand-in printer (a hash of the file's bytes), which is what
every card-independent rule needs.
"""
import hashlib
import json
import os
import shutil

import pytest

from pinball_decryptor.core import extract_source as es
from pinball_decryptor.core import lineage


# ---------------------------------------------------------------------------
# The Stern fingerprint
# ---------------------------------------------------------------------------

def test_stern_print_names_the_contents_not_the_file(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import stock_prints as sp
    from tests.test_stern_stock_prints import (CARD, SIDX, PIC_A, PIC_NEW,
                                               _cards, _official_files,
                                               _radium, _table)
    built = _official_files()
    built["assets/aa11/scene.radium"] = _radium(PIC_A, PIC_NEW)
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX),
                   # the official card again, renamed on another computer
                   renamed=("my stock card.raw", _official_files(), SIDX),
                   built=("Turtles mods.raw", built, SIDX))
    key, rel = _table(tmp_path, monkeypatch, cards["official"])
    off = sp.card_print(cards["official"])
    assert off["official"] is True and off["sidx"] == SIDX
    assert off["label"] == "Turtles Pro 1.59"
    # the table alone knows the official card's print: no card needed
    assert off["print"] == sp.release_print(key, rel)
    assert sp.card_print(cards["renamed"])["print"] == off["print"]
    mod = sp.card_print(cards["built"])
    assert mod["official"] is False and mod["print"] != off["print"]
    # the stock check takes the same print on its walk (deep or not)
    assert sp.check_card(cards["built"])["print"] == mod["print"]
    assert sp.check_card(cards["built"], deep=True)["print"] == mod["print"]


def test_a_resized_file_with_a_stale_record_changes_the_print():
    """A card built elsewhere can keep Stern's record for a file it
    replaced; the print takes the real size and drops the stale MD5."""
    from pinball_decryptor.plugins.stern import stock_prints as sp
    manifest = {"a/x.asset": (10, "0" * 32)}
    same = sp._print_files({"a/x.asset": {"size": 10}}, manifest, manifest)
    grown = sp._print_files({"a/x.asset": {"size": 12}}, manifest, manifest)
    assert same == {"a/x.asset": (10, "0" * 32)}
    assert grown == {"a/x.asset": (12, "-")}
    assert sp.print_of("t.sidx", same) != sp.print_of("t.sidx", grown)


# ---------------------------------------------------------------------------
# The lineage, with a stand-in printer
# ---------------------------------------------------------------------------

STOCK = b"STOCK turtles 1.59"


def _printer(path):
    with open(path, "rb") as f:
        data = f.read()
    return {"print": hashlib.sha1(data).hexdigest()[:32], "sidx": "t-1_59_0.sidx",
            "label": "Turtles Pro 1.59", "official": data == STOCK}


@pytest.fixture(autouse=True)
def _printers(tmp_path, monkeypatch):
    monkeypatch.setattr(lineage, "PRINT_CACHE", str(tmp_path / "prints.json"))
    monkeypatch.setattr(lineage, "_printers", [_printer])


def _card(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def _extract(folder, card):
    """What an Extract leaves: the sidecar, the baseline, the lineage."""
    os.makedirs(folder, exist_ok=True)
    es.write_extract_source(folder, card)
    with open(os.path.join(folder, ".checksums.md5"), "w") as f:
        f.write("audio/x.wav\td41d8cd98f00b204e9800998ecf8427e\n")
    info = lineage.card_print(card, measure=True)
    lineage.note_extract(folder, os.path.basename(card), info,
                         "official" if info["official"] else "modified")


def _build(folder, over, out, data):
    """What a Build leaves: the card, its record naming the project, a rev."""
    _card(__import__("pathlib").Path(out), data)
    with open(out + es.BUILD_RECORD_SUFFIX, "w") as f:
        json.dump({"version": 1, "building": False, "complete": True,
                   "assets": os.path.abspath(folder),
                   "stock": {"path": os.path.abspath(over),
                             "size": os.path.getsize(over)}}, f)
    return lineage.note_build(folder, os.path.basename(out),
                              lineage.card_print(out, measure=True),
                              lineage.card_print(over, measure=True), "9.9.9")


def test_revisions_chain_from_the_official_card(tmp_path):
    stock = _card(tmp_path / "cards" / "turtles.raw", STOCK)
    proj = str(tmp_path / "proj")
    _extract(proj, stock)
    lin = lineage.read_lineage(proj)
    assert lin["source"]["status"] == "official" and lin["source"]["rev"] == 0
    assert lin["stock"]["print"] == lin["source"]["print"]
    r1 = _build(proj, stock, str(tmp_path / "out" / "mods.raw"), b"rev one")
    assert (r1["rev"], r1["parent_rev"]) == (1, 0)
    # the next build goes over rev 1, onto a new file
    r2 = _build(proj, str(tmp_path / "out" / "mods.raw"),
                str(tmp_path / "out" / "mods2.raw"), b"rev two")
    assert (r2["rev"], r2["parent_rev"]) == (2, 1)
    # rebuilding with nothing changed is the same revision, not rev 3
    r2b = _build(proj, str(tmp_path / "out" / "mods.raw"),
                 str(tmp_path / "out" / "mods2.raw"), b"rev two")
    assert r2b["rev"] == 2
    line, history = lineage.describe(lineage.read_lineage(proj))
    assert line.startswith("Rev 2 of official Turtles Pro 1.59 - last built ")
    assert history[0].startswith("Rev 1: mods.raw, built ")
    assert history[0].endswith(" over stock")
    assert history[1].endswith(" over rev 1")


def test_project_and_cards_moved_to_another_computer(tmp_path):
    """Every path the project recorded is gone; the prints still match."""
    stock = _card(tmp_path / "pc1" / "turtles.raw", STOCK)
    proj = str(tmp_path / "pc1" / "proj")
    _extract(proj, stock)
    _build(proj, stock, str(tmp_path / "pc1" / "mods.raw"), b"rev one")
    # copy everything to "pc2" under other names, then the first PC is gone
    moved = str(tmp_path / "pc2" / "My Turtles")
    shutil.copytree(proj, moved)
    built2 = _card(tmp_path / "pc2" / "turtles rev1 final.raw", b"rev one")
    stock2 = _card(tmp_path / "pc2" / "stock copy.img", STOCK)
    shutil.rmtree(tmp_path / "pc1")
    rel = es.card_relation(built2, moved, measure=True)
    assert rel["kind"] == "build" and rel["rev"] == 1
    rel = es.card_relation(stock2, moved, measure=True)
    assert rel["kind"] == "source" and rel["rev"] == 0
    # building onto either is building on this project: no warning
    assert es.other_card_recorded(moved, built2) is None
    assert es.other_card_recorded(moved, stock2) is None
    other = _card(tmp_path / "pc2" / "someone else.raw", b"another build")
    lineage.card_print(other, measure=True)
    assert es.card_relation(other, moved)["kind"] == "other"
    assert es.other_card_recorded(moved, other) == "turtles.raw"


def test_pad421_built_in_place_then_copied_and_the_original_deleted(tmp_path):
    """DragonRR's shape: the project was extracted from a stock card, built
    into a custom card, then the folder was copied next to the card and the
    first one deleted.  The build record names a folder that is gone."""
    stock = _card(tmp_path / "turtles.raw", STOCK)
    first = str(tmp_path / "work" / "proj")
    _extract(first, stock)
    built = str(tmp_path / "Turtles Custom V1.96.raw")
    _build(first, stock, built, b"custom 1.96")
    beside = str(tmp_path / "Turtles Custom V1.96")
    shutil.copytree(first, beside)
    shutil.rmtree(tmp_path / "work")
    rel = es.card_relation(built, beside, measure=True)
    assert rel["kind"] == "build" and rel["rev"] == 1
    assert es.card_relation(stock, beside, measure=True)["kind"] == "source"


def test_same_name_and_size_is_not_the_source_when_the_print_differs(tmp_path):
    """The old weak rule (same file name and size) took a card rebuilt over
    the recorded source for the source itself: "treating the last version
    of revisions as stock"."""
    card = tmp_path / "turtles.raw"
    _card(card, STOCK)
    proj = str(tmp_path / "proj")
    _extract(proj, str(card))
    elsewhere = _card(tmp_path / "other" / "turtles.raw", b"STOCK turtles 1.6X")
    assert len(STOCK) == os.path.getsize(elsewhere)
    assert es._names_this_image(es.read_extract_source(proj), elsewhere)
    rel = es.card_relation(elsewhere, proj, measure=True)
    assert rel["kind"] == "other"
    assert es.other_card_recorded(proj, elsewhere) == "turtles.raw"


def test_a_project_off_a_modified_card_warns_on_stock(tmp_path):
    """PAD-176 measured against the real stock: building a project that came
    off somebody's build onto the official card drops what was baked in."""
    stock = _card(tmp_path / "turtles.raw", STOCK)
    custom = _card(tmp_path / "custom.raw", b"someone's build")
    proj = str(tmp_path / "proj")
    _extract(proj, custom)
    lin = lineage.read_lineage(proj)
    assert lin["source"]["status"] == "modified"
    assert lineage.base_words(lin) == "a modified Turtles Pro 1.59 card"
    lineage.card_print(stock, measure=True)
    assert es.card_relation(stock, proj)["kind"] == "other"
    assert es.other_card_recorded(proj, stock) == "custom.raw"


def test_built_card_source_reads_the_stock_verdict(tmp_path):
    """No build record beside the card (it was built on another computer),
    but the extract's own check said it is not the official card."""
    custom = _card(tmp_path / "custom.raw", b"someone's build")
    proj = str(tmp_path / "proj")
    os.makedirs(proj)
    es.write_extract_source(proj, custom)
    assert es.built_card_source(proj) is None
    es.amend_extract_source(proj, stock={"status": "modified"})
    assert es.built_card_source(proj) == "custom.raw"


def test_reextracting_another_card_starts_a_new_history(tmp_path):
    stock = _card(tmp_path / "turtles.raw", STOCK)
    proj = str(tmp_path / "proj")
    _extract(proj, stock)
    _build(proj, stock, str(tmp_path / "rev1.raw"), b"rev one")
    first = lineage.read_lineage(proj)["id"]
    # re-extract its own rev 1: the same project carries on
    _extract(proj, str(tmp_path / "rev1.raw"))
    lin = lineage.read_lineage(proj)
    assert lin["id"] == first and lin["source"]["rev"] == 1
    assert len(lin["revs"]) == 1
    # an unrelated card: a new project
    _extract(proj, _card(tmp_path / "x.raw", b"unrelated"))
    lin = lineage.read_lineage(proj)
    assert lin["id"] != first and lin["revs"] == []


def test_print_cache_follows_the_file_stamp(tmp_path):
    card = _card(tmp_path / "c.raw", STOCK)
    assert lineage.card_print(card) is None            # never measured
    got = lineage.card_print(card, measure=True)
    assert lineage.card_print(card)["print"] == got["print"]
    st = os.stat(card)
    _card(tmp_path / "c.raw", b"rebuilt")
    os.utime(card, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert lineage.card_print(card) is None            # stale: not trusted


def test_a_project_from_before_lineage_keeps_its_source(tmp_path):
    """No source print recorded (extracted by an older PAD): a build adds
    revisions, and the recorded source card is still its source."""
    stock = _card(tmp_path / "turtles.raw", STOCK)
    proj = str(tmp_path / "proj")
    os.makedirs(proj)
    es.write_extract_source(proj, stock)
    _build(proj, stock, str(tmp_path / "rev1.raw"), b"rev one")
    assert es.card_relation(stock, proj, measure=True)["kind"] == "source"
    assert es.card_relation(str(tmp_path / "rev1.raw"), proj,
                            measure=True)["rev"] == 1


# ---------------------------------------------------------------------------
# Mod packs carry it
# ---------------------------------------------------------------------------

def test_mod_pack_carries_the_history_and_matches_cards_by_print(tmp_path):
    import zipfile
    from pinball_decryptor.core import modpack
    from pinball_decryptor.core.checksums import generate_checksums
    stock = _card(tmp_path / "pc1" / "turtles_pro-1_59_0.Release.8G.raw", STOCK)
    proj = str(tmp_path / "pc1" / "proj")
    os.makedirs(os.path.join(proj, "audio"))
    with open(os.path.join(proj, "audio", "x.wav"), "wb") as f:
        f.write(b"stock wav")
    generate_checksums(proj)
    _extract(proj, stock)
    generate_checksums(proj)
    _build(proj, stock, str(tmp_path / "pc1" / "mods.raw"), b"rev one")
    with open(os.path.join(proj, "audio", "x.wav"), "wb") as f:
        f.write(b"my wav")
    pack = str(tmp_path / "mods.zip")
    modpack.export_mod_pack(proj, pack)
    with zipfile.ZipFile(pack) as zf:
        man = json.loads(zf.read(modpack.MANIFEST_NAME))
    assert man["lineage"]["revs"][0]["rev"] == 1
    # the receiver extracted the same official card under another name
    there = str(tmp_path / "pc2" / "theirs")
    os.makedirs(os.path.join(there, "audio"))
    with open(os.path.join(there, "audio", "x.wav"), "wb") as f:
        f.write(b"stock wav")
    _extract(there, _card(tmp_path / "pc2" / "stock.img", STOCK))
    generate_checksums(there)
    plan = modpack.inspect_mod_pack(pack, there)
    lines = modpack.mismatch_lines(plan)
    assert ("info", "This pack was made from official Turtles Pro 1.59 "
                    "(its project's rev 1).") in lines
    assert not [t for lvl, t in lines if lvl == "warning"]
    modpack.import_mod_pack(pack, there, plan=plan)
    imp = lineage.read_lineage(there)["imported"]
    assert imp[0]["rev"] == 1 and imp[0]["pack"] == "mods.zip"


def test_mod_pack_from_another_card_says_so_by_print(tmp_path):
    from pinball_decryptor.core import modpack
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    _extract(a, _card(tmp_path / "same name.raw", STOCK))
    _extract(b, _card(tmp_path / "x" / "same name.raw", b"a custom card"))
    plan = {"pack_lineage": lineage.read_lineage(a),
            "here_lineage": lineage.read_lineage(b),
            "pack_card": "same name.raw", "here_card": "same name.raw",
            "manifest": {}, "names": [], "judged": True}
    warn = [t for lvl, t in modpack.mismatch_lines(plan) if lvl == "warning"]
    assert warn and "a modified Turtles Pro 1.59 card" in warn[0]


def test_the_build_pipeline_records_the_revision_beside_the_card(tmp_path):
    from pinball_decryptor.plugins.stern import engine, pipeline
    stock = _card(tmp_path / "turtles.raw", STOCK)
    proj = str(tmp_path / "proj")
    _extract(proj, stock)
    out = _card(tmp_path / "build" / "mods.raw", b"rev one")
    record = {"version": 1, "building": False, "complete": True,
              "assets": proj}
    engine._write_build_manifest(out, record)
    logged = []
    entry = pipeline._note_build_lineage(stock, proj, out, record,
                                         lambda m, *a: logged.append(m))
    assert entry["rev"] == 1
    beside = engine.read_build_manifest(out)
    lin = lineage.read_lineage(proj)
    assert beside["lineage"] == {"id": lin["id"], "rev": 1,
                                 "print": entry["print"],
                                 "parent": lin["source"]["print"],
                                 "parent_rev": 0}
    assert beside["complete"] is True
    assert logged == ["This card is rev 1 of official Turtles Pro 1.59."]


# ---------------------------------------------------------------------------
# The extract measured against the official card, not the card it came off
# ---------------------------------------------------------------------------

def _md5(b):
    return hashlib.md5(b).hexdigest()


GZ = "godzilla_le"
VID_A, VID_B = b"stock clip A", b"stock clip B"
LOGO = b"stock logo png"
PIC_STOCK = "3ce3aba2"


def _release_table(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import stock_prints as sp
    rel = {"folder": GZ, "name": "Godzilla LE", "version": "1.16.0",
           "files": {GZ + "/assets/x/scene.assets/0.asset": [len(VID_A), _md5(VID_A)[:16]],
                     GZ + "/assets/x/scene.assets/1.asset": [len(VID_B), _md5(VID_B)[:16]],
                     GZ + "/gfx/logo.png": [len(LOGO), _md5(LOGO)[:16]],
                     GZ + "/assets/y/scene.assets/16.asset": [95632, "0" * 16]},
           "pictures": PIC_STOCK}
    path = str(tmp_path / "table.json.xz")
    sp.save_table({"godzilla_le-1_16_0.sidx": rel}, path)
    monkeypatch.setattr(sp, "TABLE_PATH", path)


def _spike2_extract(folder, name, vid_a=VID_A, logo=LOGO, tex_size=95632,
                    pic=PIC_STOCK, stamp=None):
    """The sidecars a Spike 2 extract leaves, with the baseline's MD5s."""
    os.makedirs(os.path.join(folder, "video"))
    os.makedirs(os.path.join(folder, "images", "scene_textures"))
    with open(os.path.join(folder, ".extract_source.json"), "w") as f:
        json.dump({"input_path": "X:/gone/" + name, "input_name": name,
                   "size": 1, "mtime": 1, **({"stock": stamp} if stamp else {})}, f)
    with open(os.path.join(folder, "video", "manifest.txt"), "w") as f:
        f.write("# output\tcard path\tbytes\n"
                "A.mp4\t/%s/assets/x/scene.assets/0.asset\t%d\n"
                "B.mp4\t/%s/assets/x/scene.assets/1.asset\t%d\n"
                % (GZ, len(vid_a), GZ, len(VID_B)))
    with open(os.path.join(folder, "images", "manifest.txt"), "w") as f:
        f.write("# output\tcard path\tbytes\n%s/gfx/logo.png\t/%s/gfx/logo.png\t%d\n"
                % (GZ, GZ, len(logo)))
    with open(os.path.join(folder, "images", "scene_textures", "manifest.txt"), "w") as f:
        f.write("# output\tcard path\tbytes\twidth\theight\tformat\n"
                "scene_textures/t_16.png\t/%s/assets/y/scene.assets/16.asset\t%d\t1\t1\t5\n"
                % (GZ, tex_size))
    with open(os.path.join(folder, "images", "scene_textures", "radium_images.txt"), "w") as f:
        f.write("# output\tradium card path\n"
                "scene_textures/radimg_512x512_%s.png\t/%s/assets/x/scene.radium\n"
                % (pic, GZ))
    with open(os.path.join(folder, ".checksums.md5"), "w") as f:
        f.write("video/A.mp4\t%s\nvideo/B.mp4\t%s\nimages/%s/gfx/logo.png\t%s\n"
                % (_md5(vid_a), _md5(VID_B), GZ, _md5(logo)))


def test_an_official_extract_has_nothing_off_stock(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import stock_prints as sp
    _release_table(tmp_path, monkeypatch)
    proj = str(tmp_path / "gz")
    _spike2_extract(proj, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
    got = sp.project_off_stock(proj)
    assert got == {"label": "Godzilla LE 1.16", "videos": 0, "pictures": 0,
                   "files": []}
    assert sp.off_stock_words(got) == ""


def test_a_custom_card_extract_says_what_is_not_official(tmp_path, monkeypatch):
    """A Heisei-style card: no version in its name, a clip, the loose logo,
    a scene texture and a radium picture of its own."""
    from pinball_decryptor.plugins.stern import stock_prints as sp
    import pinball_decryptor.plugins.stern.manufacturer  # noqa: F401  registers
    _release_table(tmp_path, monkeypatch)
    proj = str(tmp_path / "heisei")
    _spike2_extract(proj, "Godzilla Premium 1.16 Heisei Custom V1.5.raw",
                    vid_a=b"custom clip, longer", logo=b"custom logo",
                    tex_size=99000, pic="0badc0de")
    got = sp.project_off_stock(proj)
    assert (got["videos"], got["pictures"]) == (1, 3)
    assert got["files"] == sorted([
        "video/A.mp4", "images/%s/gfx/logo.png" % GZ,
        "images/scene_textures/t_16.png",
        "images/scene_textures/radimg_512x512_0badc0de.png"])
    words = sp.off_stock_words(got)
    assert words == ("1 video and 3 pictures differ from the official "
                     "Godzilla LE 1.16 card")
    assert lineage.off_stock(proj)[0] == words
    from pinball_decryptor.webui.extract_helpers import project_details
    assert project_details(proj)["off_stock"].startswith(
        "In the extract itself: 1 video and 3 pictures differ")


def test_another_version_by_name_is_not_measured_against_the_latest(
        tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import stock_prints as sp
    _release_table(tmp_path, monkeypatch)
    proj = str(tmp_path / "old")
    _spike2_extract(proj, "godzilla_le-1_13_0.Release.8G.sdcard.raw",
                    vid_a=b"1.13 clip")
    assert sp.project_off_stock(proj) is None


def test_mod_pack_export_names_what_the_extract_already_carried(
        tmp_path, monkeypatch):
    from pinball_decryptor.core import modpack
    import pinball_decryptor.plugins.stern.manufacturer  # noqa: F401
    _release_table(tmp_path, monkeypatch)
    proj = str(tmp_path / "heisei")
    _spike2_extract(proj, "Heisei.raw", vid_a=b"custom clip")
    with open(os.path.join(proj, "video", "A.mp4"), "wb") as f:
        f.write(b"custom clip")
    with open(os.path.join(proj, "video", "B.mp4"), "wb") as f:
        f.write(b"my own new clip")             # changed since the extract
    logged = []
    modpack.export_mod_pack(proj, str(tmp_path / "p.zip"),
                            log_cb=lambda m, lvl="": logged.append((lvl, m)))
    warn = [m for lvl, m in logged if lvl == "warning"]
    assert any(m.startswith("NOT in the pack: 1 file(s) the extract itself "
                            "holds that are not the official card's (1 video "
                            "differs from the official Godzilla LE 1.16 card)")
               for m in warn), warn


def test_the_official_extract_of_the_release_is_found(tmp_path, monkeypatch):
    """Transfer mods' stock extract, found from what the extracts recorded
    rather than asked for."""
    _release_table(tmp_path, monkeypatch)
    off = {"status": "official", "sidx": "godzilla_le-1_16_0.sidx"}
    mod = {"status": "modified", "sidx": "godzilla_le-1_16_0.sidx"}
    heisei = str(tmp_path / "work" / "heisei")
    _spike2_extract(heisei, "Heisei.raw", stamp=mod)
    # another modified extract and another release do not count
    _spike2_extract(str(tmp_path / "work" / "other custom"), "c.raw", stamp=mod)
    _spike2_extract(str(tmp_path / "work" / "pro"), "p.raw",
                    stamp={"status": "official", "sidx": "godzilla_pro-1_16_0.sidx"})
    assert lineage.find_official_extract(heisei) == ""
    stock = str(tmp_path / "elsewhere" / "Godzilla stock")
    _spike2_extract(stock, "godzilla_le-1_16_0.raw", stamp=off)
    assert lineage.find_official_extract(heisei, [stock]) == os.path.normpath(stock)
    # beside it is found without being a recent project
    beside = str(tmp_path / "work" / "stock beside")
    _spike2_extract(beside, "godzilla_le-1_16_0.raw", stamp=off)
    assert lineage.find_official_extract(heisei) == os.path.normpath(beside)
    assert es.built_card_source(heisei) == "Heisei.raw"
