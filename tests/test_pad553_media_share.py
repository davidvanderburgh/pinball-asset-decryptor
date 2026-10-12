"""PAD-553: music modes and random clips as files of their own, and back out of a card.

"Can we make it so that both audio modes and video random variants can be saved as separate
items (like the scene edits)" and "when a raw file is read back by pad it will put the modes back
in correctly so the user can visually see what the modes are, and apply that same logic to the
video random variants" - a tester keeping one Godzilla project on two PCs.

The card's own record (comment lines of ``sounds.cfg`` the runtime skips), the extract's
read-back of it and of the ``__PadVar`` clips, the two files (saved, loaded into a project that
numbers its sounds otherwise, left out where nothing matches), and the tabs' More menu items."""

import json
import os
import zipfile

import pytest

from pinball_decryptor.core import checksums, staged_changes
from pinball_decryptor.plugins.stern import clip_variants as CV
from pinball_decryptor.plugins.stern import media_share as MS
from pinball_decryptor.plugins.stern import sound_modes as SMo
from tests.test_webui_audio import _wav

TUNE = "audio/idx2241 - SE GZ MX TUNE 16.wav"
SLOT = "video/EndOfBallBonus_BackgroundLoop.mov"


def _bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _card_project(root, host_wav=True):
    """An extract of a card written with one music mode file (record idx 95 holds it) and two
    random clips on SLOT."""
    root = str(root)
    _wav(os.path.join(root, *TUNE.split("/")), seconds=0.3)
    if host_wav:
        _wav(os.path.join(root, "audio", "idx0095 - music.wav"), seconds=0.6, amp=900)
    _wav(os.path.join(root, "audio", "idx0001 - Jackpot.wav"), seconds=0.2)
    _bytes(os.path.join(root, *SLOT.split("/")), b"own clip" * 10)
    _bytes(os.path.join(root, "video", "EndOfBallBonus_BackgroundLoop__PadVar2.mov"), b"two" * 10)
    _bytes(os.path.join(root, "video", "EndOfBallBonus_BackgroundLoop__PadVar3.mov"), b"three" * 10)
    _bytes(os.path.join(root, "video", "attract.mov"), b"attract" * 10)
    return root


def _cfg(db=-3):
    modes = SMo.clean({"names": ["", "Orchestral"], "slots": {TUNE: {"2": r"C:\mine\TUNE 16 orchestral.wav"}},
                       "levels": {TUNE: {"2": db}}})
    used = [{"rel": TUNE, "slot": 2241, "mode": 2, "host": 95, "db": modes.level(TUNE, 2), "lines": 4}]
    return SMo.cfg_text(0x7A4E78, 2, [(2, 2541, bytes.fromhex("0501015ddb05"))], only=True,
                        record=SMo.card_record(modes, used))


# ---- the card's record ------------------------------------------------------------------------
def test_the_card_says_which_record_holds_each_modes_file_in_lines_the_runtime_skips():
    text = _cfg()
    lines = text.splitlines()
    # what pad_mode_runtime.c sndm_line reads is as it was: everything else starts with '#'
    assert [ln for ln in lines if not ln.startswith("#")] == [
        "only", "setting\t0x007a4e78\t2", "sound\t2\t2541\t0501015ddb05"]
    assert "#mode\t2\tOrchestral" in lines
    assert "#file\t2\t2241\t95\t-3\t%s\tTUNE 16 orchestral.wav" % TUNE in lines
    assert SMo.read_card_record(text) == {
        "names": ["Standard", "Orchestral"],
        "files": [{"mode": 2, "slot": 2241, "host": 95, "db": -3, "rel": TUNE,
                   "name": "TUNE 16 orchestral.wav"}]}
    # a card written before PAD-553 says nothing
    assert SMo.read_card_record("only\nsetting\t0x1\t2\nsound\t2\t1\t05\n") is None


def test_a_file_no_sound_id_plays_is_not_in_the_record():
    modes = SMo.clean({"slots": {TUNE: {"2": "a.wav", "3": "b.wav"}}})
    used = [{"rel": TUNE, "slot": 2241, "mode": 2, "host": 95, "db": 0, "lines": 2},
            {"rel": TUNE, "slot": 2241, "mode": 3, "host": 96, "db": 0, "lines": 0}]
    rec = SMo.read_card_record("\n".join(SMo.card_record(modes, used)))
    assert [f["mode"] for f in rec["files"]] == [2]
    assert rec["names"] == ["Standard", "Custom A", "Custom B"]


def test_a_name_or_path_with_a_tab_stays_one_field():
    modes = SMo.clean({"names": ["", "Big\tBand"], "slots": {"audio/idx0002 -  two  spaces.wav": {"2": "x\ty.wav"}}})
    used = [{"rel": "audio/idx0002 -  two  spaces.wav", "slot": 2, "mode": 2, "host": 9, "db": None,
             "lines": 1}]
    rec = SMo.read_card_record("\n".join(SMo.card_record(modes, used)))
    assert rec["names"][1] == "Big Band"
    assert rec["files"][0]["rel"] == "audio/idx0002 -  two  spaces.wav"
    assert rec["files"][0]["db"] is None and rec["files"][0]["name"] == "x y.wav"


# ---- an extract of the card -------------------------------------------------------------------
def test_an_extract_of_the_card_has_its_music_modes_and_random_clips_back(tmp_path):
    proj = _card_project(tmp_path / "proj")
    said = []
    done = MS.readback("card.raw", proj, lambda m, lvl="info": said.append((lvl, m)),
                       padmode={"sounds.cfg": _cfg().encode()})
    assert done == {"music": 1, "clips": 1}
    side = staged_changes.load(proj)
    copy = os.path.join(proj, "Music mode files", "TUNE 16 orchestral.wav")
    assert side["sound_modes"] == {"names": ["Standard", "Orchestral"], "slots": {TUNE: {"2": copy}},
                                   "levels": {TUNE: {"2": -3}}}
    # the mode's file is the record that held it on the card, under the name the user gave it
    with open(copy, "rb") as a, open(os.path.join(proj, "audio", "idx0095 - music.wav"), "rb") as b:
        assert a.read() == b.read()
    assert side["video_variants"] == {SLOT: [
        os.path.join(proj, "video", "EndOfBallBonus_BackgroundLoop__PadVar2.mov"),
        os.path.join(proj, "video", "EndOfBallBonus_BackgroundLoop__PadVar3.mov")]}
    words = " ".join(m for _l, m in said)
    assert "1 sound(s) of this card have files for other music modes (1 Standard, 2 Orchestral)" in words
    assert "1 clip(s) of this card play one of several at random (EndOfBallBonus_BackgroundLoop.mov)" in words
    # the copies are the project's own, never slots of their own
    assert "Music mode files" in checksums.NON_ASSET_DIRS
    # the tabs read them as any project's
    assert SMo.load(proj).slots == {TUNE: {2: copy}}
    assert CV.load(proj) == side["video_variants"]


def test_an_extract_keeps_what_the_project_already_gives(tmp_path):
    proj = _card_project(tmp_path / "proj")
    staged_changes.save(proj, {"sound_modes": {"names": ["Mine", "Mine 2"],
                                               "slots": {TUNE: {"2": "C:/my.wav"}}, "levels": {}},
                               "video_variants": {SLOT: ["C:/my.mp4"]}})
    done = MS.readback("card.raw", proj, padmode={"sounds.cfg": _cfg().encode()})
    assert done == {"music": 0, "clips": 0}
    side = staged_changes.load(proj)
    assert side["sound_modes"]["slots"] == {TUNE: {"2": "C:/my.wav"}}
    assert side["sound_modes"]["names"] == ["Mine", "Mine 2"]
    assert side["video_variants"] == {SLOT: ["C:/my.mp4"]}


def test_a_record_the_extract_lacks_is_named(tmp_path):
    proj = _card_project(tmp_path / "proj", host_wav=False)
    said = []
    MS.readback("card.raw", proj, lambda m, lvl="info": said.append((lvl, m)),
                padmode={"sounds.cfg": _cfg().encode()})
    assert ("warning", "Music modes: idx2241 - SE GZ MX TUNE 16.wav's file for mode 2 is not back: "
                       "this extract has no sound idx 95.") in said
    assert "sound_modes" not in staged_changes.load(proj)


def test_an_older_card_gives_its_modes_back_from_the_project_it_was_built_from(tmp_path):
    proj = _card_project(tmp_path / "proj")
    built = str(tmp_path / "built")
    mine = _wav(str(tmp_path / "mine" / "orch.wav")) or str(tmp_path / "mine" / "orch.wav")
    os.makedirs(built, exist_ok=True)
    staged_changes.save(built, {"sound_modes": {"names": ["", "Orch"], "slots": {TUNE: {"2": mine}},
                                                "levels": {TUNE: {"2": 2}}}})
    card = str(tmp_path / "card.raw")
    _bytes(card, b"\0" * 16)
    with open(card + ".pad-build.json", "w", encoding="utf-8") as f:
        json.dump({"version": 1, "building": False, "complete": True, "assets": built}, f)
    old = "only\nsetting\t0x1\t2\nsound\t2\t2541\t0501\n"          # no record
    said = []
    MS.readback(card, proj, lambda m, lvl="info": said.append((lvl, m)), padmode={"sounds.cfg": old.encode()})
    side = staged_changes.load(proj)
    assert side["sound_modes"]["slots"] == {TUNE: {"2": mine}}
    assert side["sound_modes"]["levels"] == {TUNE: {"2": 2}}
    assert any("from the project it was built from" in m for _l, m in said)
    # without that project: said, and nothing made up
    os.remove(card + ".pad-build.json")
    proj2 = _card_project(tmp_path / "proj2")
    said = []
    MS.readback(card, proj2, lambda m, lvl="info": said.append((lvl, m)), padmode={"sounds.cfg": old.encode()})
    assert "sound_modes" not in staged_changes.load(proj2)
    assert any(lvl == "warning" and "written by an earlier version" in m for lvl, m in said)


def test_a_stock_card_reads_back_nothing(tmp_path):
    proj = str(tmp_path / "proj")
    _wav(os.path.join(proj, *TUNE.split("/")))
    _bytes(os.path.join(proj, *SLOT.split("/")), b"own")
    assert MS.readback("card.raw", proj, padmode={}) == {"music": 0, "clips": 0}
    assert staged_changes.load(proj) == {}


# ---- the files ----------------------------------------------------------------------------------
def _modes_project(root, rel=TUNE, sound_seconds=0.3):
    root = str(root)
    _wav(os.path.join(root, *rel.split("/")), seconds=sound_seconds)
    _wav(os.path.join(root, "audio", "idx0001 - Jackpot.wav"), seconds=0.2)
    return root


def test_music_modes_go_to_a_file_and_into_a_project_that_numbers_the_sound_otherwise(tmp_path):
    src = _modes_project(tmp_path / "src")
    mine = str(tmp_path / "mine" / "orch.wav")
    _wav(mine, seconds=0.5, amp=700)
    staged_changes.save(src, {"sound_modes": {"names": ["", "Orchestral"],
                                              "slots": {TUNE: {"2": mine, "3": mine}},
                                              "levels": {TUNE: {"3": -2}}}})
    path = str(tmp_path / "share" / "modes.zip")
    os.makedirs(os.path.dirname(path))
    got = MS.save_music_modes(src, path)
    assert got == {"slots": 1, "files": 1, "gone": []}
    with zipfile.ZipFile(path) as z:
        head = json.loads(z.read(MS.MANIFEST))
        assert head["kind"] == MS.MUSIC_KIND and head["names"] == ["", "Orchestral"]
        assert head["slots"] == {TUNE: {"2": "files/0/orch.wav", "3": "files/0/orch.wav"}}
        assert head["levels"] == {TUNE: {"3": -2}}
    # the other model: the same song is idx 2290 there
    other = "audio/idx2290 - SE GZ MX TUNE 16.wav"
    dst = _modes_project(tmp_path / "dst", rel=other)
    got = MS.load_music_modes(dst, path)
    copy = os.path.join(dst, "Music mode files", "orch.wav")
    assert got["record"] == {"names": ["", "Orchestral"], "slots": {other: {"2": copy, "3": copy}},
                             "levels": {other: {"3": -2}}}
    assert got["found"] == [(TUNE, other, "found by its sound")] and got["left"] == []
    assert MS.put_music(dst, got["record"]) == 1
    assert SMo.load(dst).slots == {other: {2: copy, 3: copy}}
    assert SMo.load(dst).name(2) == "Orchestral"
    # loading it again replaces nothing new and copies nothing twice
    assert MS.replaced_music(dst, MS.load_music_modes(dst, path)["record"]) == [(other, 2), (other, 3)]
    assert os.listdir(os.path.join(dst, "Music mode files")) == ["orch.wav"]


def test_a_sound_this_card_does_not_have_is_left_out(tmp_path):
    src = _modes_project(tmp_path / "src")
    mine = str(tmp_path / "mine" / "orch.wav")
    _wav(mine)
    staged_changes.save(src, {"sound_modes": {"slots": {TUNE: {"2": mine}}, "levels": {}}})
    path = str(tmp_path / "modes.zip")
    MS.save_music_modes(src, path)
    dst = str(tmp_path / "dst")
    _wav(os.path.join(dst, "audio", "idx0005 - other.wav"), seconds=0.9)
    got = MS.load_music_modes(dst, path)
    assert got["record"]["slots"] == {} and got["left"] == [(TUNE, "this card has no such sound")]


def test_a_file_of_the_other_kind_says_which_tab_loads_it(tmp_path):
    proj = _card_project(tmp_path / "proj")
    staged_changes.save(proj, {"video_variants": {SLOT: [os.path.join(proj, "video", "attract.mov")]}})
    path = str(tmp_path / "clips.zip")
    MS.save_random_clips(proj, path)
    with pytest.raises(MS.ShareError, match="it is a file of random clips; load it on the Video tab"):
        MS.load_music_modes(proj, path)
    with pytest.raises(MS.ShareError, match="nothing to save|no music modes to save"):
        MS.save_music_modes(proj, str(tmp_path / "m.zip"))


def test_random_clips_go_to_a_file_and_find_their_clip_by_where_the_card_keeps_it(tmp_path):
    src = str(tmp_path / "src")
    _bytes(os.path.join(src, *SLOT.split("/")), b"own clip")
    _bytes(os.path.join(src, "video", "manifest.txt"),
           b"# rel\tcard\nEndOfBallBonus_BackgroundLoop.mov\t/godzilla_le/bank/scene.assets/a.mov\n")
    one = _bytes(str(tmp_path / "mine" / "one.mp4"), b"1" * 50)
    two = _bytes(str(tmp_path / "mine" / "two.mp4"), b"2" * 50)
    staged_changes.save(src, {"video_variants": {SLOT: [one, two]}})
    path = str(tmp_path / "clips.zip")
    assert MS.save_random_clips(src, path) == {"slots": 1, "files": 2, "gone": []}
    with zipfile.ZipFile(path) as z:
        assert z.getinfo("files/0/one.mp4").compress_type == zipfile.ZIP_STORED
        head = json.loads(z.read(MS.MANIFEST))
        assert head["cards"] == {SLOT: "godzilla_le/bank/scene.assets/a.mov"}
    # a project that names the slot otherwise and holds another cut of it: where the card keeps it
    dst = str(tmp_path / "dst")
    there = "video/eob_bonus.mov"
    _bytes(os.path.join(dst, *there.split("/")), b"re-encoded clip")
    _bytes(os.path.join(dst, "video", "manifest.txt"),
           b"eob_bonus.mov\t/godzilla_le/bank/scene.assets/a.mov\n")
    got = MS.load_random_clips(dst, path)
    folder = os.path.join(dst, "Random clip files")
    assert got["variants"] == {there: [os.path.join(folder, "one.mp4"), os.path.join(folder, "two.mp4")]}
    assert got["found"] == [(SLOT, there, "found by where the card keeps it")]
    assert MS.put_clips(dst, got["variants"]) == 1
    assert CV.load(dst) == got["variants"]
    assert "Random clip files" in checksums.NON_ASSET_DIRS


def test_zip_members_that_climb_out_are_never_written(tmp_path):
    proj = _modes_project(tmp_path / "proj")
    path = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(MS.MANIFEST, json.dumps({"kind": MS.MUSIC_KIND, "slots": {
            TUNE: {"2": "../../evil.wav", "3": "files/0/../../evil.wav", "4": "files/1/ok.wav"}}}))
        z.writestr("../../evil.wav", b"x")
        z.writestr("files/1/ok.wav", b"RIFF")
    got = MS.load_music_modes(proj, path)
    assert got["record"]["slots"] == {TUNE: {"4": os.path.join(proj, "Music mode files", "ok.wav")}}
    assert not os.path.exists(str(tmp_path / "evil.wav"))


def test_a_clashing_name_with_other_bytes_gets_a_free_one(tmp_path):
    folder = str(tmp_path / "f")
    a = MS._put(folder, "x.wav", data=b"one")
    assert MS._put(folder, "x.wav", data=b"one") == a
    b = MS._put(folder, "x.wav", data=b"two")
    assert os.path.basename(b) == "x (2).wav"


# ---- the tabs -----------------------------------------------------------------------------------
def test_the_audio_tab_saves_and_loads_the_music_modes(tmp_path, monkeypatch):
    from tests.test_pad494_audio_tab import REL, _offer, _row
    from tests.test_webui_audio import _open, _project
    from tests.webui_harness import web_app
    _offer(monkeypatch)
    proj = _project(tmp_path)
    mine = str(tmp_path / "mine" / "Orchestral jackpot.wav")
    _wav(mine)
    staged_changes.save(proj, {"sound_modes": {"names": ["", "Orchestral"], "slots": {REL: {"2": mine}},
                                               "levels": {REL: {"2": 4}}}})
    path = str(tmp_path / "out" / "modes.zip")
    os.makedirs(os.path.dirname(path))
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert w.state("audio")["modes_share"] is True
        w.answers.append(path)
        assert w.call("audio.modes_save") == path
        assert w.asked[-1]["title"] == "Save the music modes to a file"
    other = tmp_path / "other"
    other.mkdir()
    dst = _project(other)
    with web_app(tmp_path / "w2", mfr="stern", era="spike2") as w:
        _open(w, dst)
        assert "md" not in _row(w, REL)
        w.answers.append(path)
        got = w.call("audio.modes_load")
        assert got == {"loaded": 1, "found": 0, "left": 0}
        assert w.asked[-1]["kind"] != "file"            # the summary
        assert _row(w, REL)["md"] == [2]
        assert "mode 2 (Orchestral): Orchestral jackpot.wav at +4 dB." in _row(w, REL)["md_tip"]
        copy = os.path.join(dst, "Music mode files", "Orchestral jackpot.wav")
        assert staged_changes.load(dst)["sound_modes"] == {
            "names": ["", "Orchestral"], "slots": {REL: {"2": copy}}, "levels": {REL: {"2": 4}}}
        # loading again asks first, and No leaves it be
        w.answers.extend([path, "no"])
        assert w.call("audio.modes_load") is None


def test_the_video_tab_saves_and_loads_the_random_clips(tmp_path, monkeypatch):
    from tests.test_webui_video import _mine, _offer, _project, _row, _scan
    from tests.webui_harness import web_app
    _offer(monkeypatch)
    proj = _project(tmp_path)
    one, two = _mine(tmp_path, "b.mp4"), _mine(tmp_path, "c.mp4")
    rel = "video/intro.mp4"
    staged_changes.save(str(proj), {"video_variants": {rel: [str(one), str(two)]}})
    path = str(tmp_path / "clips.zip")
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        assert w.state("video")["var_share"] is True
        w.answers.append(path)
        assert w.call("video.variants_save") == path
    other = tmp_path / "other"
    other.mkdir()
    dst = _project(other)
    with web_app(tmp_path / "w2", mfr="stern") as w:
        st = _scan(w, dst)
        assert _row(st, rel)["var"] == 0
        w.answers.append(path)
        assert w.call("video.variants_load") == {"loaded": 1, "found": 0, "left": 0}
        assert _row(w.state("video"), rel)["var"] == 2
        folder = os.path.join(str(dst), "Random clip files")
        assert CV.load(str(dst)) == {rel: [os.path.join(folder, "b.mp4"), os.path.join(folder, "c.mp4")]}
        # one Undo step takes it back
        assert w.state("video")["undo"]["undo"] == "Load random clips"
        w.call("video.undo")
        assert _row(w.state("video"), rel)["var"] == 0
        assert CV.load(str(dst)) == {}


# ---- mod packs carry the random clips too -------------------------------------------------------
def test_a_mod_pack_carries_the_random_clips_and_an_import_puts_them_in_the_project(tmp_path):
    from pinball_decryptor.core import modpack
    from tests.test_pad494_mod_routes import _extract, _write
    one = _write(str(tmp_path / "mine" / "one.mp4"), b"ONE" * 40) or str(tmp_path / "mine" / "one.mp4")
    two = str(tmp_path / "mine" / "two.mp4")
    _write(two, b"TWO" * 40)
    src = tmp_path / "src"
    _extract(src, {SLOT: b"OWN" * 50, "video/attract.mov": b"ATT" * 50})
    staged_changes.save(str(src), {"video_variants": {SLOT: [one, two, str(tmp_path / "gone.mp4")]}})
    logs = []
    zip_path = str(tmp_path / "pack.zip")
    # random clips alone change no file of the extract and are still a pack
    n, _ = modpack.export_mod_pack(str(src), zip_path, log_cb=lambda t, lvl="info": logs.append(t))
    assert n == 0
    assert any("NOT in the pack: 1 random clip(s)" in t for t in logs)
    assert any("random clips (2 file(s) on 1 clip(s))" in t for t in logs)
    with zipfile.ZipFile(zip_path) as zf:
        man = json.loads(zf.read(modpack.MANIFEST_NAME).decode("utf-8"))
        assert zf.getinfo(".modpack_clips/0/one.mp4").compress_type == zipfile.ZIP_STORED
    assert man["extras"]["video_variants"] == {SLOT: [".modpack_clips/0/one.mp4",
                                                      ".modpack_clips/1/two.mp4"]}
    dest = tmp_path / "dest"
    _extract(dest, {SLOT: b"OWN" * 50, "video/attract.mov": b"ATT" * 50})
    staged_changes.save(str(dest), {"video_variants": {"video/attract.mov": ["C:/keep.mp4"]}})
    plan = modpack.inspect_mod_pack(zip_path, str(dest))
    assert plan["foreign"] == []                       # the clips are not files of the card
    res = modpack.import_mod_pack(zip_path, str(dest), plan=plan)
    assert res["extras"]["video_variants"] == 1
    folder = str(dest / checksums.RANDOM_CLIP_FILES_DIR)
    assert staged_changes.load(str(dest))["video_variants"] == {
        "video/attract.mov": ["C:/keep.mp4"],
        SLOT: [os.path.join(folder, "one.mp4"), os.path.join(folder, "two.mp4")]}
    with open(os.path.join(folder, "two.mp4"), "rb") as f:
        assert f.read() == b"TWO" * 40


def test_on_the_same_title_a_sound_is_its_path_never_a_twin_elsewhere(tmp_path, monkeypatch):
    # Godzilla keeps some sounds twice: the file's slot is the one at its path, even when the
    # project here has a build's sound in it and the twin still has the game's
    monkeypatch.setattr(MS, "_about", lambda project: {"title": "godzilla_le-1.16"})
    src = _modes_project(tmp_path / "src")
    mine = str(tmp_path / "mine" / "orch.wav")
    _wav(mine)
    staged_changes.save(src, {"sound_modes": {"slots": {TUNE: {"2": mine}}, "levels": {}}})
    path = str(tmp_path / "modes.zip")
    MS.save_music_modes(src, path)
    dst = _modes_project(tmp_path / "dst", sound_seconds=0.7)        # another sound at TUNE
    twin = "audio/idx2999 - SE GZ MX TUNE 16 copy.wav"
    _wav(os.path.join(dst, *twin.split("/")), seconds=0.3)           # the game's, elsewhere
    got = MS.load_music_modes(dst, path)
    assert list(got["record"]["slots"]) == [TUNE] and got["found"] == []


def test_a_project_from_before_mode_files_had_a_loudness_saves_its_sounds(tmp_path):
    src = _modes_project(tmp_path / "src")
    mine = str(tmp_path / "mine" / "orch.wav")
    _wav(mine)
    staged_changes.save(src, {"audio_levels": {TUNE: 5},
                              "sound_modes": {"slots": {TUNE: {"2": mine}}}})   # no "levels"
    path = str(tmp_path / "modes.zip")
    MS.save_music_modes(src, path)
    with zipfile.ZipFile(path) as z:
        assert json.loads(z.read(MS.MANIFEST))["levels"] == {TUNE: {"2": 5}}
