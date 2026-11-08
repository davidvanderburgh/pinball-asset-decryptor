"""PAD-1060: Replace Audio renames that change only the case of a name.

A tester renamed "idx2268 - ONE" to "idx2268 - One" in Audio Properties and
was told "A file named ... already exists in that folder": on Windows (and a
default macOS volume) the new name IS the file, so the clash check found the
slot itself.  Rename from callouts.csv refused every such row the same way.
They also cleared a name while changing its Type and saw the file keep it.

Driven through the web UI's Replace Audio service (webui/tabs/audio.py).
"""
import json
import os

import pytest

from pinball_decryptor.core import audio_categories as AC
from pinball_decryptor.core import audio_slots
from pinball_decryptor.core import checksums
from pinball_decryptor.core import name_memory as NM
from pinball_decryptor.core.transcribe import CalloutsFile
from pinball_decryptor.webui import compat
from tests.test_gui_audio_rename import _load, _rows, _wait, _wav
from tests.webui_harness import web_app

REL = "audio/idx0001 - ONE.wav"


@pytest.fixture
def boxes(monkeypatch, tmp_path):
    monkeypatch.setattr(NM, "AUDIO_NAMES_FILE", str(tmp_path / "audio_names.json"))
    said = []
    monkeypatch.setattr(compat.messagebox, "showinfo", lambda t, m: said.append(m))
    monkeypatch.setattr(compat.messagebox, "showerror", lambda t, m: said.append(m))
    monkeypatch.setattr(compat.messagebox, "askyesno",
                        lambda t, m: said.append(m) or True)
    return said


def _folder(tmp_path, *rels):
    assets = str(tmp_path / "proj")
    for i, rel in enumerate(rels or (REL,)):
        _wav(os.path.join(assets, *rel.split("/")), amp=1000 + 100 * i)
    checksums.generate_checksums(assets)
    return assets


def _names(assets):
    return sorted(os.listdir(os.path.join(assets, "audio")))


def test_properties_rename_that_only_changes_case(tmp_path, boxes):
    assets = _folder(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        assert w.call("audio.rename", REL, "One", "callout") is True
        assert _rows(w) == ["audio/idx0001 - One.wav"]
        assert "audio/idx0001 - One.wav" in svc._by_rel
    assert boxes == []
    assert _names(assets) == ["idx0001 - One.wav"]   # the case on disk too
    assert checksums.changed_rels(assets, ["audio/idx0001 - One.wav"]) == set()
    with open(NM.AUDIO_NAMES_FILE, encoding="utf-8") as f:
        assert [v["label"] for v in json.load(f).values()] == ["One"]


def test_a_real_clash_is_still_refused(tmp_path, boxes):
    other = "audio/idx0001 - One.wav"
    assets = str(tmp_path / "proj")
    _wav(os.path.join(assets, "audio", "idx0001 - ONE.wav"))
    _wav(os.path.join(assets, "audio", "idx0001.wav"), amp=1500)
    checksums.generate_checksums(assets)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        # a different file already holds the bare-prefix name
        assert w.call("audio.rename", REL, "", "callout") is False
    assert "already exists" in boxes[-1]
    assert _names(assets) == ["idx0001 - ONE.wav", "idx0001.wav"]
    assert other not in _names(assets)


def _rescan(w):
    w.call("audio.scan")
    assert _wait(w, lambda: not w.state("audio")["scanning"]
                 and w.state("audio")["rows"])


def test_clearing_the_name_while_changing_the_type_keeps_the_type(tmp_path,
                                                                   boxes):
    """The Discord half: Callouts -> Sound FX with the name cleared.  The
    file goes bare, and the new Type survives a rescan (a blank name used to
    forget the slot, Type and all, so it came back as the derived Type)."""
    assets = _folder(tmp_path)
    bare = "audio/idx0001.wav"
    derived = AC.derived(assets, bare)
    new_cat = "sfx" if derived != "sfx" else "music"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        assert w.call("audio.rename", REL, "", new_cat) is True
        assert _rows(w) == [bare]
        assert svc._cats.get(bare) == new_cat
        _rescan(w)
        assert _rows(w) == [bare]
        assert svc._cats.get(bare) == new_cat
    assert boxes == []
    assert _names(assets) == ["idx0001.wav"]
    # nothing to put back as a name on the next extract, only the Type
    assert NM.load() == {}
    assert list(NM.load_categories().values()) == [new_cat]


def test_clearing_the_name_on_its_own_still_forgets_it(tmp_path, boxes):
    assets = _folder(tmp_path)
    bare = "audio/idx0001.wav"
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        same = AC.derived(assets, bare)       # the Type is never changed
        assert w.call("audio.rename", REL, "Uno", same) is True
        assert w.call("audio.rename", "audio/idx0001 - Uno.wav", "",
                      same) is True
    assert _names(assets) == ["idx0001.wav"]
    assert NM.load() == {} and NM.load_categories() == {}


def test_a_remembered_case_only_name_applies_on_the_next_extract(tmp_path,
                                                                 boxes):
    assets = _folder(tmp_path)
    md5 = NM.baseline_md5(assets, REL)
    NM.remember(md5, "One", category="callouts")
    assert NM.apply_saved_names(assets) == 1
    assert _names(assets) == ["idx0001 - One.wav"]
    assert checksums.changed_rels(assets, ["audio/idx0001 - One.wav"]) == set()


def test_retry_fallback_never_deletes_a_case_only_rename(tmp_path,
                                                         monkeypatch):
    """os.replace keeps failing (a lock): the copy-then-delete fallback must
    not run when the target is the same file, or it deletes the sound."""
    src = tmp_path / "idx0001 - ONE.wav"
    src.write_bytes(b"RIFF data")
    dst = tmp_path / "idx0001 - One.wav"

    def locked(a, b):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(audio_slots.os, "replace", locked)
    if not os.path.exists(dst):
        pytest.skip("case-sensitive disk: the names are two files here")
    with pytest.raises(PermissionError):
        audio_slots.replace_with_retry(str(src), str(dst), base_delay=0)
    assert os.listdir(tmp_path) == ["idx0001 - ONE.wav"]
    assert src.read_bytes() == b"RIFF data"


def test_rename_from_callouts_changes_only_the_case(tmp_path, boxes):
    assets = _folder(tmp_path, REL, "audio/idx0002 - million plus pops.wav")
    with open(os.path.join(assets, "callouts.csv"), "w", encoding="utf-8",
              newline="") as f:
        f.write("folder,file,seconds,classification,text\n"
                "audio,idx0001 - ONE.wav,0.2,speech,One\n"
                "audio,idx0002 - million plus pops.wav,0.2,speech,"
                "Million plus pops\n")
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.rename_from_callouts") is True
        assert sorted(_rows(w)) == ["audio/idx0001 - One.wav",
                                    "audio/idx0002 - Million plus pops.wav"]
    assert "Renamed 2 sound(s)." in boxes[-1]
    assert _names(assets) == ["idx0001 - One.wav",
                              "idx0002 - Million plus pops.wav"]


# The tester's reply on v1.372.0: a callout moved to Sound FX with its name
# cleared kept "speech,Okay." in callouts.csv, so Rename from callouts.csv
# named it "Okay" again.

OKAY = "audio/00m00s798 - idx0891 - Okay.wav"
BARE = "audio/00m00s798 - idx0891.wav"


def _csv(assets, rows):
    with open(os.path.join(assets, "callouts.csv"), "w", encoding="utf-8",
              newline="") as f:
        f.write("folder,file,seconds,classification,text\n")
        for fname, kind, text in rows:
            f.write("audio,%s,0.798,%s,%s\n" % (fname, kind, text))


def _csv_rows(assets):
    cf = CalloutsFile(os.path.join(assets, "callouts.csv"))
    return [(cf.get(r, "file"), cf.get(r, "classification"), cf.get(r, "text"))
            for r in cf.rows]


def test_cleared_name_and_sound_fx_reach_callouts_csv(tmp_path, boxes):
    assets = _folder(tmp_path, OKAY)
    _csv(assets, [("00m00s798 - idx0891 - Okay.wav", "speech", "Okay.")])
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        assert svc._cats.get(OKAY) == "callouts"
        assert w.call("audio.rename", OKAY, "", "sfx") is True
        assert _csv_rows(assets) == [
            ("00m00s798 - idx0891.wav", "non-speech", "")]
        # nothing for Rename from callouts.csv to put back
        assert w.call("audio.rename_from_callouts") is True
        assert "already has the name" in boxes[-1]
        _rescan(w)
        assert _rows(w) == [BARE]
        assert svc._cats.get(BARE) == "sfx"
    assert _names(assets) == ["00m00s798 - idx0891.wav"]


def test_a_type_change_alone_reaches_callouts_csv(tmp_path, boxes):
    """Name kept, Callouts -> Sound FX: the row stops being speech and keeps
    its words (they still make the file's name)."""
    assets = _folder(tmp_path, OKAY)
    _csv(assets, [("00m00s798 - idx0891 - Okay.wav", "speech", "Okay.")])
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        assert w.call("audio.rename", OKAY, "Okay", "sfx") is True
        assert _csv_rows(assets) == [
            ("00m00s798 - idx0891 - Okay.wav", "non-speech", "Okay.")]
        _rescan(w)
        assert svc._cats.get(OKAY) == "sfx"
        # and back to Callouts: speech again
        assert w.call("audio.rename", OKAY, "Okay", "callouts") is True
        assert _csv_rows(assets)[0][1] == "speech"


def test_update_callouts_mends_a_row_an_earlier_save_left(tmp_path, boxes):
    """The tester's row as v1.372.0 left it: the file bare, Sound FX
    remembered, the row still "speech,Okay.".  Update callouts.csv from the
    names puts it in step; a bare callout's words are left alone."""
    other = "audio/00m00s799 - idx0892.wav"
    assets = _folder(tmp_path, BARE, other)
    _csv(assets, [("00m00s798 - idx0891.wav", "speech", "Okay."),
                  ("00m00s799 - idx0892.wav", "speech", "Hey.")])
    NM.remember_category(NM.baseline_md5(assets, BARE), "sfx")
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.update_callouts") is True
        assert _csv_rows(assets) == [
            ("00m00s798 - idx0891.wav", "non-speech", ""),
            ("00m00s799 - idx0892.wav", "speech", "Hey.")]
