"""PAD-1479: online co-op - machines in different places playing toward one shared goal, on the score feed.

Captain Gordon: "A peer to peer mode for spike 2 co op mode, where asynchronous gameplay effects a shared target like
a high score"; David: "give flexibility to the users to design their own online coop modes ... a bare minimum baseline
of online coop that works across all titles that is vanilla." (docs/plans/pad1479-online-coop.md)"""
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"


def _godzilla():
    from pinball_decryptor.plugins.stern import mode_project as MP
    return next(p for p in MP.profiles().values() if MP.port_path(p).endswith("godzilla_le-1.16.port"))


def test_the_vanilla_campaign_needs_nothing_designed():
    from pinball_decryptor.plugins.stern import online_coop as OC
    d = OC.vanilla_design()
    assert OC.design_problems(d) == []
    assert [t["name"] for t in d["teams"]] == ["Everyone"] and d["goal"] == {"kind": "score"}
    targets = [r["target"] for r in d["regions"]]
    assert targets == sorted(targets) and len(targets) == 5
    for name, ex in OC.EXAMPLES.items():
        assert OC.design_problems(ex) == [], name


def test_a_design_the_server_cannot_run_is_refused():
    from pinball_decryptor.plugins.stern import online_coop as OC
    bad = {"title": "X", "teams": [{"name": "A", "colour": "#112233"}, {"name": "a", "colour": "red"}],
           "goal": {"kind": "count", "count": "two words"}, "regions": [{"name": "R", "target": 0}]}
    why = " ".join(OC.design_problems(bad))
    assert "Two teams are called a" in why and "#rrggbb" in why and "count's name" in why and "whole number" in why
    assert OC.design_problems({"title": "X", "teams": [], "goal": {"kind": "score"}, "regions": []})
    assert OC.count_problem("pokemon_rescued") == "" and OC.count_problem("a" * 24)


def test_the_settings_are_kept_in_the_project(tmp_path):
    from pinball_decryptor.plugins.stern import online_coop as OC
    p = str(tmp_path)
    s = OC.load(p)
    assert s["on"] is False and s["design"] == OC.vanilla_design()
    with pytest.raises(OC.OnlineCoopError):          # on, with no server, no campaign, no machine name
        OC.save(p, on=True)
    assert OC.load(p)["on"] is False
    s = OC.save(p, url="http://203.0.113.10:8090/", campaign="Shared  score", machine="Dave's LE")
    assert s["team"] == "Everyone"                   # one team: the machine is on it
    s = OC.save(p, on=True)
    assert s["on"] and OC.wanted(p)["campaign"] == "Shared score"
    s = OC.save(p, design=OC.EXAMPLES["kaiju_war"])
    assert s["team"] == "" and OC.wanted(p) is None  # a team the new design does not have: pick one
    with pytest.raises(OC.OnlineCoopError):
        OC.save(p, team="Team Mothra")
    s = OC.save(p, team="Team Godzilla", key="monster-island")
    assert OC.wanted(p)["team"] == "Team Godzilla"
    assert OC.cfg_lines(s)[1:] == ["online Shared score", "team Team Godzilla", "machine Dave's LE",
                                   "key monster-island"]
    with pytest.raises(OC.OnlineCoopError):
        OC.save(p, url="https://203.0.113.10/")


def test_online_coop_turns_the_feed_on_to_the_campaigns_server(tmp_path):
    from pinball_decryptor.plugins.stern import online_coop as OC
    from pinball_decryptor.plugins.stern import score_feed as SF
    p = str(tmp_path)
    SF.save(p, True, "http://192.168.1.50:8080/scores")
    OC.save(p, url="http://203.0.113.10:8090/", campaign="C", machine="M", on=True)
    assert SF.load(p) == (True, "http://203.0.113.10:8090/") and SF.wanted(p) == "http://203.0.113.10:8090/"
    assert SF.own(p) == (True, "http://192.168.1.50:8080/scores")      # the owner's own feed kept for later
    OC.save(p, on=False)
    assert SF.load(p) == (True, "http://192.168.1.50:8080/scores")


def test_the_cards_scorefeed_cfg_names_the_campaign(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import coop_play as CP
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern import online_coop as OC
    monkeypatch.setattr(CP, "insider_users", lambda elf: None)
    p = str(tmp_path)
    OC.save(p, url="http://203.0.113.10:8090/", campaign="Kaiju War", machine="Dave", design=OC.EXAMPLES["kaiju_war"])
    OC.save(p, team="Team King Ghidorah", on=True)
    prof = _godzilla()
    plan = MW.ModePlan(project=p, profile=prof, port=MP.port_path(prof), build=None)
    MW.feed_into(plan, b"elf", str(tmp_path / "scratch"), "http://203.0.113.10:8090/", only=True)
    lines = pathlib.Path(plan.scorefeed_file).read_text(encoding="utf-8").splitlines()
    assert lines[1] == "feed http://203.0.113.10:8090/"
    assert ["online Kaiju War", "team Team King Ghidorah", "machine Dave"] == [
        l for l in lines if l.split(" ")[0] in ("online", "team", "machine", "key")]
    assert any(l.startswith("online co-op: each game's report names campaign \"Kaiju War\"") for l in plan.lines)
    OC.save(p, on=False)                              # off: the owner's own feed carries no campaign
    plan = MW.ModePlan(project=p, profile=prof, port=MP.port_path(prof), build=None)
    MW.feed_into(plan, b"elf", str(tmp_path / "scratch2"), "http://192.168.1.50/", only=True)
    assert "online " not in pathlib.Path(plan.scorefeed_file).read_text(encoding="utf-8")


def test_the_runtime_reads_the_online_lines():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    arm = src[src.index("static void feed_arm(void)"):]
    for k in ('"online "', '"team "', '"machine "', '"key "'):
        assert "str_starts(raw + i, %s)" % k in arm, k
    assert "int pm_online_add(const char *name, long long n)" in src
    h = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    assert "int pm_online_add(const char *name, long long n);" in h and "long long pm_online_count" in h


def test_a_modes_online_counts_go_into_its_file():
    from pinball_decryptor.plugins.stern import mode_project as MP
    prof = _godzilla()
    spec = MP.blank_spec(prof)
    shot = prof.shots[0][0]
    spec.online = [["start", "kaiju_fights", 1, ""], ["shot", "cities_saved", 2, shot], ["won", "wins", 1, ""]]
    assert MP.validate_online(spec, prof) == []
    lines = MP.online_lines(spec, prof)
    assert lines[0].split() == ["online", "start", "kaiju_fights", "1"]
    assert lines[1].split() == ["online", "shot", "cities_saved", "2", "0x%08x" % prof.mask([shot])]
    assert lines[2].split() == ["online", "won", "wins", "1"]
    spec.online = [["later", "x y", 0, ""], ["shot", "ok", 1, "No such shot"]]
    why = " ".join(MP.validate_online(spec, prof))
    assert "as the mode starts" in why and "count's name" in why and "1 to" in why and "No such shot" in why
    spec.online = [["start", "a", 1, ""]] * 5
    assert any("up to 4" in w for w in MP.validate_online(spec, prof))


def test_a_spec_with_online_counts_round_trips():
    from pinball_decryptor.plugins.stern import mode_project as MP
    prof = _godzilla()
    spec = MP.blank_spec(prof)
    spec.online = [["end", "games_played", 1, ""]]
    back = MP.ModeSpec.from_json(json.loads(json.dumps(spec.to_json())))
    assert back.online == [["end", "games_played", 1, ""]]


def test_the_mode_file_reads_its_online_lines():
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    assert "if (online_line(M, line)) return;" in src
    for w in ('key_is(a, "start")', 'key_is(a, "shot")', 'key_is(a, "won")', 'key_is(a, "end")'):
        assert w in src[src.index("static int online_line("):src.index("static void online_at(struct slot *M, unsigned when, uint64_t mask)\n{")], w
    assert "online_at(M, ONLINE_AT_START, 0);" in src and "online_at(M, ONLINE_AT_SHOT, mask);" in src
    assert "online_at(M, ONLINE_AT_WON, 0);" in src and "online_at(M, ONLINE_AT_END, 0);" in src


def test_the_counts_a_projects_modes_add_to(tmp_path):
    from pinball_decryptor.plugins.stern import online_coop as OC
    m = tmp_path / "modes" / "rescue"
    m.mkdir(parents=True)
    (m / "mode.json").write_text(json.dumps({"online": [["won", "rescued", 1, ""]]}), encoding="utf-8")
    b = tmp_path / "modes" / "blocky"
    b.mkdir()
    (b / "blocks.json").write_text(json.dumps({"rules": [{"do": [{"op": "online_add", "count": "caught",
                                                                  "amount": 1}]}]}), encoding="utf-8")
    assert OC.counts_in_modes(str(tmp_path)) == ["caught", "rescued"]


def test_the_campaign_file_is_what_the_server_runs(tmp_path):
    from pinball_decryptor.plugins.stern import online_coop as OC
    s = OC.save(str(tmp_path), url="http://203.0.113.10:8090/", campaign="Rescue", machine="M", key="k1",
                design=OC.EXAMPLES["rescue_island"])
    c = OC.campaign_file(s)
    assert c["campaign"] == "Rescue" and c["key"] == "k1" and c["goal"] == {"kind": "count", "count": "rescued"}
    assert OC.design_problems(c) == []


def test_a_blocks_mode_adds_to_an_online_count():
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import blocks_sim as BS
    n = lambda v: {"k": "num", "v": v}
    prog = {"name": "RESCUE", "seconds": 30, "vars": [], "game_modes": "stack", "scripts": [
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"}, "do": [
            {"op": "online_add", "count": "rescued", "by": n(2)}]}]}
    assert BM.problems(prog) == []
    src = BM.to_c(prog, "rescue")
    assert 'pm_online_add("rescued", (2LL));' in src
    bad = json.loads(json.dumps(prog))
    bad["scripts"][1]["do"][0]["count"] = "two words"
    assert any("online count" in w for w in BM.problems(bad))
    sim = BS.Sim(prog) if hasattr(BS, "Sim") else None
    if sim is not None and hasattr(sim, "shot"):
        sim.shot("Left ramp")
        sim.shot("Right ramp")
        assert sim.online.get("rescued") == 2
