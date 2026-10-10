"""PAD-494: MUSIC MODES on the two routes mods take to another project.

"Can music modes be included in modpack transfer to other project?" - the tester who asked for
them. Transfer Mods pairs a sound's music mode files with the sound the way it pairs its
replacement (by the stock sound's content, so a sound that moved index takes them along); a mod
pack carries the files' BYTES (they are the user's own, anywhere on their PC) and an import puts
them in the project's "Music mode files" folder, which no Replace tab lists as slots. Both carry
the modes' names and each file's own loudness; a project saved before mode files had a loudness
of their own carries its sounds' offsets as theirs, so it builds the same anywhere."""

import json
import os
import zipfile

from pinball_decryptor.core import (audio_slots, checksums, mod_transfer, modpack,
                                    staged_changes)


def _write(path, data):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "wb") as f:
        f.write(data)


def _md5(data):
    import hashlib
    return hashlib.md5(data).hexdigest()


def _extract(root, sounds):
    for rel, data in sounds.items():
        _write(os.path.join(str(root), *rel.split("/")), data)
    (root / ".checksums.md5").write_text(
        "".join("%s\t%s\n" % (rel, _md5(data)) for rel, data in sounds.items()), encoding="utf-8")


TITLE, BOC = b"MAIN-TITLE" * 300, b"BLUE-OYSTER" * 300


# ---- the record both routes carry ------------------------------------------------------------------
def test_an_older_record_carries_its_sounds_offsets_as_its_files_own():
    data = {"audio_levels": {"audio/idx0001.wav": 3},
            "sound_modes": {"names": ["", "Orchestral"],
                            "slots": {"audio/idx0001.wav": {"2": "C:/m/a.wav", "3": ""},
                                      "audio/idx0002.wav": {"2": "C:/m/b.wav"}}}}
    assert staged_changes.sound_modes_of(data) == {
        "names": ["", "Orchestral"],
        "slots": {"audio/idx0001.wav": {"2": "C:/m/a.wav"}, "audio/idx0002.wav": {"2": "C:/m/b.wav"}},
        "levels": {"audio/idx0001.wav": {"2": 3}}}
    data["sound_modes"]["levels"] = {"audio/idx0002.wav": {"2": -2}}
    assert staged_changes.sound_modes_of(data)["levels"] == {"audio/idx0002.wav": {"2": -2}}
    assert staged_changes.sound_modes_of({"sound_modes": {"names": [], "slots": {}}}) is None


def test_a_carried_record_merges_file_by_file_and_the_projects_names_win():
    data = {"sound_modes": {"names": ["", "Heisei"], "slots": {"audio/idx0002.wav": {"2": "C:/h.wav"}},
                            "levels": {}}}
    n = staged_changes.merge_sound_modes(data, {
        "names": ["Standard", "Orchestral", "Showa"],
        "slots": {"audio/idx0001.wav": {"2": "C:/o.wav"}},
        "levels": {"audio/idx0001.wav": {"2": 4}}})
    assert n == 1
    assert data["sound_modes"] == {
        "names": ["Standard", "Heisei", "Showa"],
        "slots": {"audio/idx0002.wav": {"2": "C:/h.wav"}, "audio/idx0001.wav": {"2": "C:/o.wav"}},
        "levels": {"audio/idx0001.wav": {"2": 4}}}


# ---- Transfer Mods -------------------------------------------------------------------------------
def test_transfer_takes_a_sounds_mode_files_to_where_the_sound_went(tmp_path):
    src, tgt = tmp_path / "old", tmp_path / "new"
    _extract(src, {"audio/idx0001.wav": TITLE, "audio/idx0002.wav": BOC,
                   "audio/idx0003.wav": b"GONE" * 300})
    _extract(tgt, {"audio/idx0001.wav": BOC, "audio/idx0007.wav": TITLE})   # the title moved
    staged_changes.save(str(src), {
        "audio_levels": {"audio/idx0001.wav": 3},
        "sound_modes": {"names": ["", "Orchestral"],
                        "slots": {"audio/idx0001.wav": {"2": r"C:\m\title.wav", "4": r"C:\m\title.wav"},
                                  "audio/idx0002.wav": {"2": r"C:\m\boc.wav"},
                                  "audio/idx0003.wav": {"3": r"C:\m\gone.wav"}}}})
    plan = mod_transfer.plan_transfer(str(src), str(tgt))
    sm = plan["sound_modes"]
    assert [(e["src_rel"], e["tgt_rel"]) for e in sm["remapped"]] == [
        ("audio/idx0001.wav", "audio/idx0007.wav"), ("audio/idx0002.wav", "audio/idx0001.wav")]
    assert [e["src_rel"] for e in sm["dropped"]] == ["audio/idx0003.wav"]
    assert plan["totals"]["transfer"] == 2 and plan["totals"]["dropped"] == 1
    lines = [t for _lvl, t in mod_transfer.plan_detail_lines(plan)]
    assert any("music mode files can NOT be carried" in t for t in lines)

    res = mod_transfer.apply_transfer(str(src), str(tgt), plan)
    assert res["sound_modes"] == 2
    got = staged_changes.load(str(tgt))["sound_modes"]
    assert got == {"names": ["", "Orchestral"],
                   "slots": {"audio/idx0007.wav": {"2": r"C:\m\title.wav", "4": r"C:\m\title.wav"},
                             "audio/idx0001.wav": {"2": r"C:\m\boc.wav"}},
                   # the old record's title offset, now its files' own
                   "levels": {"audio/idx0007.wav": {"2": 3, "4": 3}}}


def test_a_second_transfer_takes_off_what_the_first_gave_and_this_one_does_not(tmp_path):
    src, tgt = tmp_path / "old", tmp_path / "new"
    _extract(src, {"audio/idx0001.wav": TITLE, "audio/idx0002.wav": BOC})
    _extract(tgt, {"audio/idx0001.wav": TITLE, "audio/idx0002.wav": BOC})
    modes = {"names": [], "slots": {"audio/idx0001.wav": {"2": "C:/a.wav"},
                                    "audio/idx0002.wav": {"2": "C:/b.wav"}}, "levels": {}}
    staged_changes.save(str(src), {"sound_modes": modes})
    mod_transfer.apply_transfer(str(src), str(tgt), mod_transfer.plan_transfer(str(src), str(tgt)))
    side = staged_changes.load(str(tgt))
    side["sound_modes"]["slots"]["audio/idx0002.wav"]["3"] = "C:/mine.wav"   # the user's own
    staged_changes.save(str(tgt), side)
    del modes["slots"]["audio/idx0002.wav"]
    staged_changes.save(str(src), {"sound_modes": modes})
    res = mod_transfer.apply_transfer(str(src), str(tgt), mod_transfer.plan_transfer(str(src), str(tgt)))
    assert res["superseded"] == 1
    assert staged_changes.load(str(tgt))["sound_modes"]["slots"] == {
        "audio/idx0001.wav": {"2": "C:/a.wav"}, "audio/idx0002.wav": {"3": "C:/mine.wav"}}


# ---- mod packs -----------------------------------------------------------------------------------
def test_a_pack_carries_the_mode_files_and_an_import_puts_them_in_the_project(tmp_path):
    mine = tmp_path / "mine"
    _write(mine / "Orchestral.wav", b"RIFF-ORCH")
    _write(mine / "Heisei.wav", b"RIFF-HEISEI")
    src = tmp_path / "src"
    _extract(src, {"audio/idx0001.wav": TITLE, "audio/idx0002.wav": BOC})
    staged_changes.save(str(src), {
        "audio_levels": {"audio/idx0002.wav": -2},
        "sound_modes": {"names": ["", "Orchestral", "Heisei"],
                        "slots": {"audio/idx0001.wav": {"2": str(mine / "Orchestral.wav"),
                                                        "3": str(mine / "Heisei.wav")},
                                  "audio/idx0002.wav": {"2": str(mine / "Orchestral.wav"),
                                                        "4": str(tmp_path / "gone.wav")}}}})
    logs = []
    zip_path = str(tmp_path / "pack.zip")
    # music modes alone change no file of the extract and are still a pack
    n, _ = modpack.export_mod_pack(str(src), zip_path, log_cb=lambda t, lvl="info": logs.append(t))
    assert n == 0
    assert any("NOT in the pack: 1 file(s) for music modes" in t for t in logs)
    with zipfile.ZipFile(zip_path) as zf:
        man = json.loads(zf.read(modpack.MANIFEST_NAME).decode("utf-8"))
        members = sorted(n for n in zf.namelist() if n.startswith(modpack.MODES_DIR + "/"))
    assert members == [".modpack_modes/0/Orchestral.wav", ".modpack_modes/1/Heisei.wav"]
    rec = man["extras"]["sound_modes"]
    assert rec["slots"]["audio/idx0002.wav"] == {"2": ".modpack_modes/0/Orchestral.wav"}
    assert rec["levels"] == {"audio/idx0002.wav": {"2": -2}}

    dest = tmp_path / "dest"
    _extract(dest, {"audio/idx0001.wav": TITLE, "audio/idx0002.wav": BOC})
    _write(dest / checksums.MUSIC_MODE_FILES_DIR / "Orchestral.wav", b"SOMETHING ELSE")
    res = modpack.import_mod_pack(zip_path, str(dest))
    assert res["extras"]["sound_modes"] == 2
    got = staged_changes.load(str(dest))["sound_modes"]
    folder = str(dest / checksums.MUSIC_MODE_FILES_DIR)
    orch = os.path.join(folder, "Orchestral (2).wav")         # the one already there is kept
    assert got == {"names": ["", "Orchestral", "Heisei"],
                   "slots": {"audio/idx0001.wav": {"2": orch, "3": os.path.join(folder, "Heisei.wav")},
                             "audio/idx0002.wav": {"2": orch}},
                   "levels": {"audio/idx0002.wav": {"2": -2}}}
    with open(orch, "rb") as f:
        assert f.read() == b"RIFF-ORCH"
    # and they are never slots of the card
    assert checksums.MUSIC_MODE_FILES_DIR in checksums.NON_ASSET_DIRS
    assert sorted(s.rel_path for s in audio_slots.scan_audio_slots(str(dest), probe=False)) == [
        "audio/idx0001.wav", "audio/idx0002.wav"]
