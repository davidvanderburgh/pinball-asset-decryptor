"""PAD-1479: the online co-op server - every machine's games per team, the regions raced for, the map, Discord."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from pinball_decryptor import online_coop_server as S
from pinball_decryptor.plugins.stern import online_coop as OC


def _camp(example="kaiju_war", key="monster-island", **kw):
    c = dict(OC.EXAMPLES[example])
    c.update(campaign="Kaiju War", key=key, **kw)
    return c


def _report(team="Team Godzilla", machine="Dave", scores=(1000,), n=1, game_type="standard", key="monster-island",
            counts=None, campaign="Kaiju War"):
    r = {"source": "PAD score feed", "game": "Godzilla Premium/LE 1.16", "port": "godzilla_le 1.16", "game_number": n,
         "game_type": game_type, "challenge": None, "time": 1794510000 + n, "players": len(scores),
         "scores": list(scores), "insider": [None] * len(scores), "campaign": campaign, "team": team,
         "machine": machine, "key": key, "counts": counts or {}}
    return r


def test_teams_race_for_one_region_at_a_time():
    c = _camp(regions=[{"name": "Tokyo", "target": 1000}, {"name": "Osaka", "target": 2000}])
    camp = S.Campaign(c)
    assert camp.take(_report(scores=(600,), n=1))[0] == 200
    assert camp.take(_report(team="Team King Ghidorah", machine="Ann", scores=(900,), n=1))[2] == []
    st, words, news = camp.take(_report(scores=(700,), n=2))          # Godzilla 1300 >= 1000: Tokyo
    assert st == 200 and news == ["Team Godzilla took Tokyo (1,000 from Dave)"]
    s = camp.snapshot()
    assert s["regions"][0]["owner"] == "Team Godzilla"
    assert s["teams"]["Team Godzilla"]["progress"] == 300               # past the target carries over
    assert s["teams"]["Team King Ghidorah"]["progress"] == 0            # everyone else starts again
    assert s["teams"]["Team King Ghidorah"]["total"] == 900
    news = camp.take(_report(team="Team King Ghidorah", machine="Ann", scores=(2500,), n=2))[2]
    assert news[0].startswith("Team King Ghidorah took Osaka")
    assert news[1] == "The campaign is over: Team King Ghidorah holds 1 of 2"   # 1 each: more points wins
    assert camp.snapshot()["won_by"] == "Team King Ghidorah"
    assert camp.take(_report(scores=(5,), n=3))[0] == 200               # games still count after it is over


def test_the_vanilla_campaign_is_one_shared_goal_after_another():
    c = dict(OC.vanilla_design(), campaign="Shared", key="")
    camp = S.Campaign(c)
    r = _report(team="Everyone", scores=(10 ** 7 + 5,), key="", campaign="Shared")
    assert camp.take(r)[2] == ["Everyone took Goal 1 (10,000,000 from Dave)"]
    assert camp.snapshot()["teams"]["Everyone"]["progress"] == 5


def test_a_coop_game_counts_its_team_score_once_and_others_every_player():
    assert S.game_points({"scores": [500, 500, 500], "game_type": "cooperation"}, {"kind": "score"}) == 500
    assert S.game_points({"scores": [100, 200], "game_type": "standard"}, {"kind": "score"}) == 300
    assert S.game_points({"scores": [10 ** 14]}, {"kind": "score"}) == 0             # not believed
    goal = {"kind": "count", "count": "rescued"}
    assert S.game_points({"scores": [9], "counts": {"rescued": 3}}, goal) == 3
    assert S.game_points({"scores": [9], "counts": {"caught": 3}}, goal) == 0
    assert S.game_points({"counts": {"rescued": True}}, goal) == 0


def test_a_count_campaign_fills_its_island():
    c = dict(OC.EXAMPLES["rescue_island"], campaign="Rescue", key="")
    camp = S.Campaign(c)
    for i in range(12):
        camp.take(_report(team="Rescuers", n=i, key="", campaign="Rescue", counts={"rescued": 2}))
    s = camp.snapshot()
    assert s["teams"]["Rescuers"]["total"] == 24 and s["regions"][0]["owner"] is None   # 24 of 25: not yet
    camp.take(_report(team="Rescuers", n=99, key="", campaign="Rescue", counts={"rescued": 1}))
    assert camp.snapshot()["regions"][0]["owner"] == "Rescuers"


def test_a_resend_is_counted_once():
    camp = S.Campaign(_camp())
    r = _report(scores=(400,))
    assert camp.take(r)[0] == 200
    assert camp.take(dict(r))[:2] == (202, "game already counted (a resend)")
    assert camp.snapshot()["teams"]["Team Godzilla"]["total"] == 400


def test_reports_the_campaign_does_not_take():
    camp = S.Campaign(_camp())
    assert camp.take({"source": "x"})[0] == 400
    assert camp.take(_report(campaign="Other"))[0] == 403
    assert camp.take(_report(key="guess"))[:2] == (403, "the campaign's join key is wrong")
    assert camp.take(_report(team="Team Mothra"))[0] == 403
    r = _report()
    r.pop("campaign")
    assert camp.take(r)[:2] == (403, "the machine plays in no online co-op campaign")
    assert camp.snapshot()["games"] == 0


def test_the_totals_outlive_a_restart_and_a_changed_design(tmp_path):
    p = str(tmp_path / "state.json")
    camp = S.Campaign(_camp(), p)
    camp.take(_report(scores=(1234,)))
    again = S.Campaign(_camp(), p)
    assert again.snapshot()["teams"]["Team Godzilla"]["total"] == 1234
    c = _camp()
    c["teams"] = c["teams"] + [{"name": "Team Mothra", "colour": "#8e4ec6"}]
    grown = S.Campaign(c, p)
    assert grown.snapshot()["teams"]["Team Mothra"]["total"] == 0
    assert grown.snapshot()["teams"]["Team Godzilla"]["total"] == 1234


def test_the_campaign_file_is_checked(tmp_path):
    good = tmp_path / "c.json"
    good.write_text(json.dumps(_camp()), encoding="utf-8")
    assert S.load_campaign(str(good))["campaign"] == "Kaiju War"
    bad = tmp_path / "b.json"
    bad.write_text(json.dumps(dict(_camp(), regions=[])), encoding="utf-8")
    with pytest.raises(S.CampaignError):
        S.load_campaign(str(bad))


def test_the_map_is_drawn():
    pytest.importorskip("PIL")
    camp = S.Campaign(_camp())
    camp.take(_report(scores=(10 ** 9 + 1,)))
    png = S.draw_map(camp.c, camp.snapshot())
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(png))
    assert im.size[0] == 1200 and im.size[1] > 300
    # Tokyo is Team Godzilla's colour now
    assert im.getpixel((24 + 40, 84 + 75))[:3] == (0x30, 0xa4, 0x6c)


def test_the_server_over_http(tmp_path):
    cf = tmp_path / "c.json"
    cf.write_text(json.dumps(_camp()), encoding="utf-8")
    httpd, camp = S.serve(str(cf), 0, str(tmp_path / "s.json"), host="127.0.0.1")
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        def post(doc):
            body = json.dumps(doc).encode()
            req = urllib.request.Request("http://127.0.0.1:%d/scores" % port, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code
        assert post(_report(scores=(777,))) == 200
        assert post(_report(key="nope")) == 403
        with urllib.request.urlopen("http://127.0.0.1:%d/state.json" % port, timeout=5) as r:
            s = json.loads(r.read())
        assert s["teams"]["Team Godzilla"]["total"] == 777 and "seen" not in s["machines"]["Dave"]
        with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=5) as r:
            page = r.read().decode()
        assert "Kaiju War" in page and "Dave (Team Godzilla): 1 game(s), 777" in page
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_discord_gets_the_map_on_news():
    camp = S.Campaign(_camp(regions=[{"name": "Tokyo", "target": 10}, {"name": "Osaka", "target": 10 ** 6}]))
    sent = []
    n = S.Notifier(camp, "https://discord.example/api/webhooks/1/x", every=0,
                   post=lambda url, text, png: sent.append((url, text, png)) or (True, "ok"))
    assert n([]) is None                                    # nothing new: no post
    news = camp.take(_report(scores=(50,)))[2]
    n(news).join(5)
    assert sent and sent[0][1].startswith("Team Godzilla took Tokyo") and "Now racing for Osaka" in sent[0][1]


def test_the_discord_upload_is_multipart_with_the_map():
    got = {}

    class R:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        got["req"] = req
        return R()
    ok, why = S.discord_post("https://discord.example/api/webhooks/1/x", "hello", b"\x89PNGdata", opener=opener)
    assert ok and why == "HTTP 204"
    body = got["req"].data
    assert b'name="payload_json"' in body and b'"content": "hello"' in body
    assert b'name="files[0]"; filename="map.png"' in body and b"\x89PNGdata" in body
