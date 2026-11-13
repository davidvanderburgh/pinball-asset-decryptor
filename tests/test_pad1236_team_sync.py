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
