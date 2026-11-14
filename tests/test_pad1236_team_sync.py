"""PAD-1236: several PCs working on one project (Project > Team...).

"Say user A is making videos, user B is making scenes, and user C is making
audio.  How can we effectively sync their project together so they're all
looking at the same project together?"  Each member owns parts of the project,
shares them into their own folder of a team folder a sync service carries,
and takes the others' parts from theirs.
"""

import json
import os
import time

import pytest

from pinball_decryptor.core import staged_changes, team_sync as TS
from tests.test_pad1015_replacement_export import _file, _stock_project


def _team(tmp_path, *names):
    team = str(tmp_path / "OneDrive" / "GZ team")
    out = []
    for n in names:
        project, glyph = _stock_project(tmp_path, n.lower())
        TS.join(project, team, n)
        out.append(project)
    return team, out, glyph


def test_three_people_three_parts_one_project(tmp_path):
    from pinball_decryptor.core import text_manifest
    from pinball_decryptor.plugins.stern import mode_project as MP, scene_edit
    from tests.test_gui_scene_editor import CARD
    team, (alex, bea, cy), glyph = _team(tmp_path, "Alex", "Bea", "Cy")
    TS.claim(alex, ["videos"])
    TS.claim(bea, ["scenes", "text", "modes", "fonts"])
    TS.claim(cy, ["sounds"])
    # Alex: the videos
    clip = _file(tmp_path / "alex lib" / "intro.mp4", b"alex intro")
    take2 = _file(tmp_path / "alex lib" / "intro 2.mp4", b"alex take 2")
    staged_changes.save(alex, {"video": {"video/intro.mp4": clip},
                               "video_variants": {"video/intro.mp4": [take2]},
                               "replacement_names": {"video/intro.mp4": "intro.mp4"}})
    # Bea: a scene, a line of text, a mode, a font letter
    scene_edit.save(bea, {CARD: [{"op": "move", "node": 5, "dx": 3, "dy": 4}]})
    rows = text_manifest.load(bea)
    rows[0]["replacement"] = "KAIJU"
    text_manifest.save(bea, rows)
    slug, _spec = MP.new_mode(bea, spec=MP.ModeSpec(name="TARGET RUSH",
                                                    title=MP.GODZILLA_PRO_1_15.key))
    _file(os.path.join(bea, *glyph.split("/")), b"bea's bolder A")
    # Cy: a sound, its loudness
    roar = _file(tmp_path / "cy lib" / "roar.wav", b"RIFFroar")
    staged_changes.save(cy, {"audio": {"audio/roar.wav": roar},
                             "audio_levels": {"audio/roar.wav": -3}})
    for p in (alex, bea, cy):
        TS.share(p, game="Godzilla Pro")
    # every member is told about the others' parts, and takes them
    assert {(p, w) for p, w, _s in TS.news(alex)} == {
        ("scenes", "Bea"), ("text", "Bea"), ("modes", "Bea"), ("fonts", "Bea"), ("sounds", "Cy")}
    for p in (alex, bea, cy):
        got = TS.receive(p)
        assert not got["waiting"], got
        assert TS.news(p) == []
    for p in (alex, bea, cy):
        data = staged_changes.load(p)
        intro = data["video"]["video/intro.mp4"]
        with open(intro, "rb") as f:
            assert f.read() == b"alex intro"
        if p != alex:      # a copy in the project, not the synced folder
            assert intro.startswith(os.path.join(p, TS.TEAM_FILES_DIR))
            assert data["replacement_names"] == {"video/intro.mp4": "intro.mp4"}
        assert len(data["video_variants"]["video/intro.mp4"]) == 1
        with open(data["audio"]["audio/roar.wav"], "rb") as f:
            assert f.read() == b"RIFFroar"
        assert data["audio_levels"] == {"audio/roar.wav": -3}
        assert scene_edit.ops_for(p, CARD) == [{"op": "move", "node": 5, "dx": 3, "dy": 4}]
        assert text_manifest.load(p)[0]["replacement"] == "KAIJU"
        assert [s for s, _ in MP.list_modes(p)[0]] == [slug]
        with open(os.path.join(p, *glyph.split("/")), "rb") as f:
            assert f.read() == b"bea's bolder A"
    # and the window says so: everything up to date, nothing to share
    st = TS.status(cy)
    rows = {r["key"]: r for r in st["parts"]}
    assert st["news"] == 0 and st["to_share"] == 0, st
    assert rows["videos"]["state"] == "Alex's, up to date"
    assert rows["sounds"]["state"].startswith("Yours, shared")
    assert rows["colours"]["state"] == "Nobody's"
    assert [m["name"] for m in st["members"]] == ["Alex", "Bea", "Cy"]


def test_taking_a_part_replaces_it_whole(tmp_path):
    team, (alex, bea), _g = _team(tmp_path, "Alex", "Bea")
    TS.claim(alex, ["videos"])
    a = _file(tmp_path / "lib" / "a.mp4", b"a")
    b = _file(tmp_path / "lib" / "b.mp4", b"b")
    staged_changes.save(alex, {"video": {"video/a.mp4": a, "video/b.mp4": b}})
    TS.share(alex)
    TS.receive(bea)
    assert set(staged_changes.load(bea)["video"]) == {"video/a.mp4", "video/b.mp4"}
    # Bea changes a video here although they are Alex's: the window warns her
    mine = _file(tmp_path / "bea" / "c.mp4", b"c")
    data = staged_changes.load(bea)
    data["video"]["video/c.mp4"] = mine
    data["settings"] = {"AD_BALLS_PER_GAME": 5}          # a part nobody owns: hers to keep
    staged_changes.save(bea, data)
    row = {r["key"]: r for r in TS.status(bea)["parts"]}["videos"]
    assert row["changed_here"] and row["state"] == "Alex's, up to date; changed on this PC too"
    # Alex drops b: Bea's next take is Alex's videos as they are now, b and c gone
    time.sleep(0.01)
    staged_changes.save(alex, {"video": {"video/a.mp4": a}})
    TS.share(alex)
    assert [p for p, _w, _s in TS.news(bea)] == ["videos"]
    TS.receive(bea)
    data = staged_changes.load(bea)
    assert set(data["video"]) == {"video/a.mp4"}
    assert data["settings"] == {"AD_BALLS_PER_GAME": 5}
    # b's copy left the project and Alex's folder alike
    left = [n for _d, _s, fs in os.walk(os.path.join(bea, TS.TEAM_FILES_DIR)) for n in fs]
    assert left == ["a.mp4"]
    shared = [n for _d, _s, fs in os.walk(os.path.join(team, "Alex", "Video")) for n in fs]
    assert shared == ["a.mp4"]


def test_the_last_to_take_a_part_owns_it(tmp_path):
    team, (alex, bea), _g = _team(tmp_path, "Alex", "Bea")
    TS.claim(alex, ["videos", "sounds"])
    time.sleep(0.01)
    TS.claim(bea, ["videos"])
    assert TS.owners(team) == {"videos": "Bea", "sounds": "Alex"}
    staged_changes.save(alex, {"audio": {"audio/r.wav": _file(tmp_path / "r.wav", b"RIFF")}})
    got = TS.share(alex)
    assert got["parts"] == ["sounds"]
    assert "videos" not in TS.read_member(team, "Alex")["claims"]
    TS.release(bea, ["videos"])
    assert "videos" not in TS.owners(team)
    with pytest.raises(TS.TeamError):
        TS.share(bea)                                  # owns nothing now


def test_a_share_still_arriving_is_waited_for(tmp_path):
    team, (alex, bea), _g = _team(tmp_path, "Alex", "Bea")
    TS.claim(alex, ["videos"])
    staged_changes.save(alex, {"video": {"video/a.mp4": _file(tmp_path / "a.mp4", b"abcdef")}})
    TS.share(alex)
    # the sync service has not brought the whole clip yet
    with open(os.path.join(team, "Alex", "Video", "a.mp4"), "wb") as f:
        f.write(b"abc")
    got = TS.receive(bea)
    assert got["waiting"] == [("Alex", 1)] and not got["got"]
    assert "video" not in staged_changes.load(bea)
    row = [m for m in TS.status(bea)["members"] if m["name"] == "Alex"][0]
    assert row["arriving"]
    with open(os.path.join(team, "Alex", "Video", "a.mp4"), "wb") as f:
        f.write(b"abcdef")
    assert TS.receive(bea)["got"] == [("videos", "Alex")]


def test_taking_many_parts_never_resets_your_own(tmp_path):
    """Every Reset kind at once is Reset's "everything": it must not take the part this
    member owns with it."""
    team, (alex, bea), _g = _team(tmp_path, "Alex", "Bea")
    TS.claim(alex, ["videos", "images", "sounds", "scenes", "text", "fonts", "modes",
                    "colours"])
    TS.claim(bea, ["settings"])
    staged_changes.save(alex, {"video": {"video/a.mp4": _file(tmp_path / "a.mp4", b"a")}})
    staged_changes.save(bea, {"settings": {"AD_BALLS_PER_GAME": 5},
                              "attract_items": {"items": [{"kind": "text", "text": "HI"}]}})
    TS.share(alex)
    TS.receive(bea)
    data = staged_changes.load(bea)
    assert data["settings"] == {"AD_BALLS_PER_GAME": 5} and data["attract_items"]
    assert "video/a.mp4" in data["video"]


def test_a_name_another_pc_uses_is_refused(tmp_path):
    team, (alex,), _g = _team(tmp_path, "Alex")
    card = TS.read_member(team, "Alex")
    card["pc"] = "someone@ELSEWHERE"
    with open(os.path.join(team, "Alex", TS.MEMBER_NAME), "w", encoding="utf-8") as f:
        json.dump(card, f)
    other, _g = _stock_project(tmp_path, "other")
    with pytest.raises(TS.TeamError, match="another PC"):
        TS.join(other, team, "Alex")
    with pytest.raises(TS.TeamError, match="outside the project"):
        TS.join(other, os.path.join(other, "team"), "Bo")


def test_another_cards_project_is_warned_about(tmp_path):
    team, (alex,), _g = _team(tmp_path, "Alex")
    other, _g = _stock_project(tmp_path, "other")
    with open(os.path.join(other, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_name": "jaws_le-1_01_0.raw"}, f)
    warn = TS.join(other, team, "Bo")
    assert warn and "godzilla_pro-1_15_0.raw" in warn[0]
    assert any("another card" in w for w in TS.status(other)["warnings"])


def test_team_files_are_not_card_assets():
    from pinball_decryptor.core import checksums
    assert TS.TEAM_FILES_DIR in checksums.NON_ASSET_DIRS
    assert TS.STATE_NAME in checksums.FINGERPRINT_SKIP_FILES


def test_team_window(tmp_path):
    from tests.test_pad1015_replacement_export import _until
    from tests.webui_harness import web_app
    team, (alex, bea), _g = _team(tmp_path, "Alex", "Bea")
    TS.leave(bea)                                        # Bea joins from the window
    TS.claim(alex, ["videos"])
    staged_changes.save(alex, {"video": {"video/a.mp4": _file(tmp_path / "a.mp4", b"clip")}})
    TS.share(alex, game="Godzilla Pro")
    with web_app(tmp_path / "h", mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(bea))
        assert w.call("shellx.team_open")
        assert _until(w, lambda: not w.state("shellx")["team"]["busy"])
        st = w.state("shellx")["team"]
        assert st["joined"] is False and "same card" in st["intro"]
        assert w.call("shellx.team_join", team, "Bea")
        assert _until(w, lambda: (w.state("shellx")["team"] or {}).get("parts")
                      and not w.state("shellx")["team"]["busy"])
        st = w.state("shellx")["team"]
        rows = {r["key"]: r for r in st["parts"]}
        assert rows["videos"]["news"] and rows["videos"]["state"].startswith("New from Alex")
        assert st["news"] == 1 and w.state("shellx")["team_news"] == 1
        assert w.call("shellx.team_get")
        assert _until(w, lambda: w.state("shellx")["job"] is None
                      and "video" in staged_changes.load(bea))
        assert _until(w, lambda: w.state("shellx")["team_news"] == 0)
        assert w.call("shellx.team_take", "scenes")
        assert _until(w, lambda: {r["key"]: r for r in w.state("shellx")["team"]["parts"]}
                      ["scenes"]["mine"])
        assert w.call("shellx.team_share")
        assert _until(w, lambda: w.state("shellx")["job"] is None
                      and (TS.read_member(team, "Bea").get("shared") or {}).get("parts"))
        assert TS.read_member(team, "Bea")["shared"]["parts"] == ["scenes"]
        w.call("shellx.team_close")
    with open(staged_changes.load(bea)["video"]["video/a.mp4"], "rb") as f:
        assert f.read() == b"clip"


# ---------------------------------------------------------------------------------------------
# a team folder in Git ("Git or Git LFS could be a useful setup as well")
# ---------------------------------------------------------------------------------------------
def _git(*args, cwd):
    import subprocess
    p = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout


def _git_team(tmp_path, names, seed=True):
    """A bare repository (the team's GitHub) and one clone per PC, the team folder a
    subfolder of the clone."""
    bare = str(tmp_path / "hub.git")
    _git("init", "-q", "--bare", "-b", "main", bare, cwd=str(tmp_path))
    if seed:
        seedd = str(tmp_path / "seed")
        _git("clone", "-q", bare, seedd, cwd=str(tmp_path))
        with open(os.path.join(seedd, "README.md"), "w") as f:
            f.write("GZ team\n")
        _git("add", ".", cwd=seedd)
        _git("-c", "user.name=s", "-c", "user.email=s@x", "commit", "-q", "-m", "seed", cwd=seedd)
        _git("push", "-q", "origin", "HEAD:main", cwd=seedd)
    out = []
    for n in names:
        clone = str(tmp_path / ("pc " + n) / "team repo")
        os.makedirs(os.path.dirname(clone))
        _git("clone", "-q", bare, clone, cwd=str(tmp_path))
        project, glyph = _stock_project(tmp_path, n.lower())
        assert TS.join(project, os.path.join(clone, "GZ team"), n) == []
        out.append(project)
    return bare, out


@pytest.mark.parametrize("lfs", [False, True])
@pytest.mark.parametrize("seed", [True, False])
def test_a_git_team_folder_pushes_and_pulls_itself(tmp_path, monkeypatch, lfs, seed):
    from pinball_decryptor.core import team_git
    if team_git.git_exe() is None:
        pytest.skip("no git")
    if lfs and not team_git.has_lfs(str(tmp_path)):
        pytest.skip("no git lfs")
    if not lfs:
        monkeypatch.setattr(team_git, "has_lfs", lambda root: False)
    bare, (alex, bea) = _git_team(tmp_path, ["Alex", "Bea"], seed=seed)
    TS.claim(alex, ["videos"])
    TS.claim(bea, ["sounds"])
    # a Take goes out with the next regular check, no Share needed
    assert TS.check(alex) == ([], [])
    assert TS.check(bea) == ([], [])
    assert TS.check(alex) == ([], [])          # Alex's next check brings Bea's Take
    assert TS.owners(TS.load_state(alex)["team"]) == {"videos": "Alex", "sounds": "Bea"}
    clip = _file(tmp_path / "alex lib" / "intro.mp4", b"alex intro")
    staged_changes.save(alex, {"video": {"video/intro.mp4": clip},
                               "replacement_names": {"video/intro.mp4": "intro.mp4"}})
    roar = _file(tmp_path / "bea lib" / "roar.wav", b"RIFFroar")
    staged_changes.save(bea, {"audio": {"audio/roar.wav": roar}})
    # both share before either pulls: Bea's push is turned away once, pulls, goes again
    ga = TS.share(alex)["git"]
    gb = TS.share(bea)["git"]
    assert ga["ok"] and ga["pushed"] and gb["ok"] and gb["pushed"], (ga, gb)
    news, lines = TS.check(bea)
    assert lines == [] and [(p, w) for p, w, _s in news] == [("videos", "Alex")]
    assert TS.receive(alex)["got"] == [("sounds", "Bea")]
    assert TS.receive(bea)["got"] == [("videos", "Alex")]
    with open(staged_changes.load(bea)["video"]["video/intro.mp4"], "rb") as f:
        assert f.read() == b"alex intro"
    with open(staged_changes.load(alex)["audio"]["audio/roar.wav"], "rb") as f:
        assert f.read() == b"RIFFroar"
    # one commit per share, each touching only its member's folder
    log = _git("log", "--format=%s", "--name-only", "main", cwd=bare)
    assert "Alex shared Videos" in log and "Bea shared Sounds" in log
    for block in log.split("\n\n"):
        files = [ln for ln in block.splitlines()[1:] if ln]
        assert len({f.split("/")[1] for f in files if f.startswith("GZ team/")}) <= 1, block
    clone = os.path.dirname(TS.load_state(alex)["team"])
    tracked = _git("lfs", "ls-files", "-n", cwd=clone) if lfs else ""
    assert ("GZ team/Alex/Video/intro.mp4" in tracked) == lfs
    st = TS.status(bea)
    assert st["git"] and st["git_lfs"] == lfs and st["warnings"] == []


def test_a_git_team_that_cannot_push_says_so_and_keeps_the_share(tmp_path):
    from pinball_decryptor.core import team_git
    if team_git.git_exe() is None:
        pytest.skip("no git")
    bare, (alex,) = _git_team(tmp_path, ["Alex"])
    TS.claim(alex, ["videos"])
    clip = _file(tmp_path / "alex lib" / "intro.mp4", b"alex intro")
    staged_changes.save(alex, {"video": {"video/intro.mp4": clip}})
    clone = os.path.dirname(TS.load_state(alex)["team"])
    _git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=clone)
    out = TS.share(alex)
    assert out["files"] == 1 and not out["git"]["ok"]
    assert out["git"]["lines"][0].startswith("Git couldn't get the team's changes")
    # committed here: the next check that reaches the remote sends it
    _git("remote", "set-url", "origin", bare, cwd=clone)
    assert TS.check(alex) == ([], [])
    assert "Alex shared Videos" in _git("log", "--format=%s", "main", cwd=bare)


def test_a_git_repository_without_a_remote_is_warned_about(tmp_path):
    from pinball_decryptor.core import team_git
    if team_git.git_exe() is None:
        pytest.skip("no git")
    repo = str(tmp_path / "local repo")
    _git("init", "-q", repo, cwd=str(tmp_path))
    project, _g = _stock_project(tmp_path, "alex")
    TS.join(project, os.path.join(repo, "team"), "Alex")
    st = TS.status(project)
    assert st["git"] and "no remote" in st["warnings"][0]


def test_team_window_on_a_git_team(tmp_path):
    from pinball_decryptor.core import team_git
    from tests.test_pad1015_replacement_export import _until
    from tests.webui_harness import web_app
    if team_git.git_exe() is None:
        pytest.skip("no git")
    bare, (alex, bea) = _git_team(tmp_path, ["Alex", "Bea"])
    TS.claim(alex, ["videos"])
    staged_changes.save(alex, {"video": {"video/a.mp4": _file(tmp_path / "a.mp4", b"clip")}})
    TS.share(alex, game="Godzilla Pro")          # pushed; Bea's clone has not pulled it
    with web_app(tmp_path / "h", mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(bea))
        w.run(w.window.service("shellx").team_check)   # the regular check pulls
        assert _until(w, lambda: w.state("shellx")["team_news"] == 1)
        assert w.call("shellx.team_open")
        assert _until(w, lambda: (w.state("shellx")["team"] or {}).get("parts")
                      and not w.state("shellx")["team"]["busy"])
        st = w.state("shellx")["team"]
        assert st["git"] and st["git_remote"] == "origin" and st["warnings"] == []
        assert w.call("shellx.team_get")
        assert _until(w, lambda: w.state("shellx")["job"] is None
                      and "video" in staged_changes.load(bea))
        assert w.call("shellx.team_take", "scenes")
        assert _until(w, lambda: {r["key"]: r for r in w.state("shellx")["team"]["parts"]}
                      ["scenes"]["mine"])
        assert w.call("shellx.team_share")
        assert _until(w, lambda: w.state("shellx")["job"] is None
                      and "Bea shared Scenes" in _git("log", "--format=%s", "main", cwd=bare))
        w.call("shellx.team_close")
