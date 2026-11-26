"""PAD-1575: the score feed DURING a game - live events for a stream overlay or a second screen (pad_mode_runtime.c
"the score feed DURING a game", plugins/stern/score_feed.py, the sample overlay in the SDK's examples).

David (idea 9): "a live event feed for streaming ... score, ball and mode events over the network to an OBS overlay or
a second screen". The runtime's pure parts (an event's JSON, the queue that merges score updates and drops the oldest)
are lifted verbatim and run on the host; the rest is the app's (the tick, scorefeed.cfg's live line, the contract)
and the sample overlay server, run here against real posts."""
import json
import pathlib
import re
import threading
import urllib.request

import pytest

from tests import test_spike2_mode_roster as R

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
OVERLAY = SDK / "examples" / "score_feed_overlay"

MAIN = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdarg.h>
#include <string.h>
#define LIVE_QUEUE      24
#define LIVE_JSON_MAX   640
@FNS@
static struct live_queue q;

static void show(const char *tag)
{
    unsigned k;
    printf("%s %u..%u dropped %u:", tag, q.tail, q.head, q.dropped);
    for (k = q.tail; k != q.head; k++) printf(" %u%s", q.seq[k % LIVE_QUEUE], q.score[k % LIVE_QUEUE] ? "s" : "");
    printf("\n");
}

int main(void)
{
    struct live_event e;
    char out[LIVE_JSON_MAX], big[LIVE_JSON_MAX + 8];
    unsigned n, k;
    memset(&e, 0, sizeof e);
    e.event = "ball_start";
    e.seq = 12;
    e.number = 3;
    e.players = 2;
    e.player = 2;
    e.ball = 1;
    e.scores[0] = 123450;
    e.scores[1] = 18446744073709551615ull;
    e.ms = 81234;
    e.when = 1794326400l;
    n = live_json(out, sizeof out, &e, "Godzilla \"LE\" 1.16");
    printf("plain %u %s\n", n, out);
    e.when = 0;
    e.event = "mode_start";
    e.mode = "Ghidorah \"Battle\"";
    e.kind = "card";
    printf("mode %s\n", live_json(out, sizeof out, &e, "x") ? out : "-");
    e.players = 4;
    for (k = 0; k < 4; k++) e.scores[k] = 18446744073709551615ull;
    e.mode = "a mode name of thirty-nine characters!!";
    printf("big %u\n", live_json(out, sizeof out, &e, "Godzilla Premium/LE 1.16 with a long name of sixty-three chars"));
    printf("small %u\n", live_json(out, 60, &e, "x"));
    /* the queue: a score update merges into the one waiting last; full, the oldest goes */
    memset(&q, 0, sizeof q);
    live_q_push(&q, "{a}", 3, 1, 0, 0);
    printf("merge0 %d\n", live_q_merges(&q));
    live_q_push(&q, "{s}", 3, 2, 1, live_q_merges(&q));
    printf("merge1 %d\n", live_q_merges(&q));
    live_q_push(&q, "{s2}", 4, 2, 1, live_q_merges(&q));
    show("merged");
    printf("body %s\n", q.body[(q.head - 1) % LIVE_QUEUE]);
    live_q_push(&q, "{b}", 3, 3, 0, 0);
    live_q_push(&q, "{s3}", 4, 4, 1, live_q_merges(&q));
    show("after");
    q.tail = q.head - 1;                     /* the score waiting was taken for posting: */
    q.tail = q.head;                         /* ... and out of the queue, so the next one queues */
    printf("merge2 %d\n", live_q_merges(&q));
    memset(&q, 0, sizeof q);
    for (k = 1; k <= LIVE_QUEUE + 3; k++) live_q_push(&q, "{e}", 3, k, 0, 0);
    printf("full %u..%u dropped %u first %u last %u\n", q.tail, q.head, q.dropped, q.seq[q.tail % LIVE_QUEUE],
           q.seq[(q.head - 1) % LIVE_QUEUE]);
    memset(big, 'x', sizeof big);
    live_q_push(&q, big, LIVE_JSON_MAX, 99, 0, 0);
    live_q_push(&q, "", 0, 100, 0, 0);
    printf("toolong dropped %u last %u\n", q.dropped, q.seq[(q.head - 1) % LIVE_QUEUE]);
    return 0;
}
"""


def _struct(src, name):
    i = src.index("struct %s {" % name)
    return src[i:src.index("};", i) + 2]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join([_struct(src, "live_event"), _struct(src, "live_queue")] + [R._lift(src, sig) for sig in (
        "static int feed_fmt(char *b, unsigned long cap, const char *f, ...)",
        "static unsigned feed_json_str(char *out, unsigned cap, const char *s)",
        "static unsigned live_json(char *out, unsigned cap, const struct live_event *e, const char *title)",
        "static int live_q_merges(const struct live_queue *q)",
        "static void live_q_push(struct live_queue *q, const char *body, unsigned len, unsigned seq, int score,")])
    return R._host_run(tmp_path_factory.mktemp("live"), MAIN.replace("@FNS@", fns)).splitlines()


def _line(out, tag):
    return next(l for l in out if l.startswith(tag + " "))[len(tag) + 1:]


def test_an_event_is_json_with_the_whole_game(run):
    from pinball_decryptor.plugins.stern import score_feed as SF
    n, body = _line(run, "plain").split(" ", 1)
    doc = json.loads(body)
    assert int(n) == len(body)
    assert doc == {"source": "PAD score feed", "event": "ball_start", "seq": 12, "game": 'Godzilla "LE" 1.16',
                   "game_number": 3, "ms": 81234, "time": 1794326400, "players": 2, "player": 2, "ball": 1,
                   "scores": [123450, 18446744073709551615]}
    mode = json.loads(_line(run, "mode"))
    assert mode["time"] is None and mode["mode"] == 'Ghidorah "Battle"' and mode["kind"] == "card"
    assert list(mode) == [f[0] for f in SF.LIVE_FIELDS] == list(SF.LIVE_SAMPLE)     # the contract's own order
    assert list(doc) == [f[0] for f in SF.LIVE_FIELDS][:-2]                          # mode and kind: mode events


def test_the_biggest_event_fits_and_a_small_buffer_says_so(run):
    assert 0 < int(_line(run, "big")) < 640
    assert _line(run, "small") == "0"


def test_a_score_update_waiting_is_replaced_not_queued(run):
    """At most one score update waits: the next replaces it (same seq: no gap), behind any other event."""
    assert _line(run, "merge0") == "0" and _line(run, "merge1") == "1"
    assert _line(run, "merged") == "0..2 dropped 0: 1 2s"
    assert _line(run, "body") == "{s2}"
    assert _line(run, "after") == "0..4 dropped 0: 1 2s 3 4s"
    assert _line(run, "merge2") == "0"                     # taken for posting: the next one queues


def test_a_full_queue_drops_the_oldest(run):
    assert _line(run, "full") == "3..27 dropped 3 first 4 last 27"
    assert _line(run, "toolong") == "dropped 5 last 27"


def _section(src):
    return src[src.index("/* ---- PAD-1575: the score feed DURING a game"):src.index("static void on_feed_tick(")]


def test_it_never_waits_on_the_network_inside_the_game():
    """MODE_SDK.md rules 1 and 2: the live posts are stepped on the game's tick with a non-blocking socket, never
    tried again, and a hang-up never signals the game."""
    src = RUNTIME.read_text(encoding="utf-8")
    sec = _section(src)
    code = re.sub(r"/\*.*?\*/", "", sec, flags=re.S)
    for banned in ("pthread_", "sleep(", "nanosleep", "poll(", "select(", "getaddrinfo", "malloc"):
        assert banned not in code, banned
    step = R._lift(sec, "static void live_send_step(void)")
    assert "0x800" in step and "0x4000 | 0x40" in step
    assert step.count("live_post_done(") >= 6 and "tries" not in step           # one try an event
    assert "#define LIVE_TIMEOUT_MS 1500ul" in sec and "#define LIVE_BACKOFF_MS 5000ul" in sec
    tick = R._lift(src, "static void on_feed_tick(pm_reg *regs)")
    assert tick.index("feed_send_step();") < tick.index("live_send_step();")
    # the live events come after the report's work: a game's end goes out before the next game's start
    assert tick.rindex("feed_queue(") < tick.index("live_tick(in_game);")
    assert "if (lv.on)" in tick


def test_the_game_end_goes_out_with_the_report():
    src = RUNTIME.read_text(encoding="utf-8")
    q = R._lift(src, "static void feed_queue(const struct feed_report *r, const char *why)")
    assert q.index("feed.head++;") < q.index("live_game_end(q);")
    end = R._lift(src, "static void live_game_end(const struct feed_report *r)\n{")
    assert end.index("live_ring(1);") < end.index('live_emit_as("game_end"')    # that game's bus events first
    step = R._lift(src, "static void feed_send_step(void)")
    assert "if (!feed.tries && live_holds_report(now)) return;" in step            # the report after its game_end
    assert "#define LIVE_HOLD_MS    3000ul" in src
    assert 'live_emit_as("game_end", 0, 0, r->number' in end and "r->scores" in end


def test_the_bus_events_and_the_modes_it_follows():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = R._lift(src, "static void feed_arm(void)")
    assert 'str_starts(raw + i, "live")) lv.wanted = 1;' in arm
    for ev in ("game_start", "ball_start", "ball_end", "multiball_start", "multiball_end", "bonus_start",
               "bonus_end", "tilt"):
        assert '"%s"' % ev in arm, ev
    tick = R._lift(src, "static void live_tick(int in_game)")
    ring = R._lift(src, "static void live_ring(int to_next_game)\n{")
    for ev in ("game_start", "ball_start", "ball_end", "tilt"):
        assert 'live_emit("%s"' % ev in ring, ev
    assert 'live_emit("score"' in tick and "live_ring(0);" in tick
    assert "LIVE_SCORE_MS" in tick and "live_modes_check();" in tick
    # who was up when the bus called: a ball's end names the player whose ball it was, not the next one
    bus = R._lift(src, "static void live_bus(unsigned id)")
    assert bus.index("lv.ring_p[slot % LIVE_RING]") < bus.index("lv.ring[slot % LIVE_RING] = (unsigned char)k;")
    assert "lv.ev_p = lv.ring_p[slot];" in ring and "case LV_BALL_END: if (!lv.ended)" in ring
    modes = R._lift(src, "static void live_modes_check(void)")
    assert '"card"' in modes and '"game"' in modes and "gm_starts[id]" in modes and "gm_stops[id]" in modes
    disp = R._lift(src, "static void on_feed_dispatch(pm_reg *r)")
    assert "if (lv.on) live_bus((unsigned)r[0]);" in disp


def test_every_event_the_contract_names_is_sent():
    from pinball_decryptor.plugins.stern import score_feed as SF
    src = RUNTIME.read_text(encoding="utf-8")
    sent = set(re.findall(r'live_emit(?:_as)?\("([a-z_]+)"', _section(src)))
    assert sent == {n for n, _ in SF.LIVE_EVENTS}


def test_the_live_tick_is_kept_in_the_project(tmp_path):
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.plugins.stern import score_feed as SF
    p = str(tmp_path)
    assert SF.live_on(p) is False and SF.live_wanted(p) is False
    SF.save(p, True, "http://10.0.0.7:9000/s")
    assert SF.live_wanted(p) is False                                  # off to start with
    assert SF.save_live(p, True) is False
    assert SF.live_on(p) and SF.live_wanted(p)
    SF.save(p, True, "http://10.0.0.8/s")                              # a new address keeps the tick
    assert staged_changes.load(p)[SF.STAGED_KEY] == {"on": True, "url": "http://10.0.0.8/s", "live": True}
    SF.save(p, False)
    assert SF.live_on(p) and not SF.live_wanted(p)                     # the feed off: no live events either
    SF.save(p, True, "https://x/")
    assert not SF.live_wanted(p)


def test_online_coop_gets_the_reports_alone(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import online_coop as OC
    from pinball_decryptor.plugins.stern import score_feed as SF
    p = str(tmp_path)
    SF.save(p, True, "http://10.0.0.7/s")
    SF.save_live(p, True)
    monkeypatch.setattr(OC, "load", lambda project: {"on": True, "url": "http://10.0.0.9/coop"})
    assert SF.wanted(p) == "http://10.0.0.9/coop" and SF.live_wanted(p) is False


def test_scorefeed_cfg_live_line(monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import coop_play as CP
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern import score_feed as SF
    monkeypatch.setattr(CP, "insider_users", lambda elf: None)
    monkeypatch.setattr(SF, "players_line", lambda elf: "players 0x00713b94 0x007d116c")
    assert SF.cfg_text("http://10.0.0.7/", "x", b"elf", only=True, live=True).splitlines()[-3:] == [
        "live", "players 0x00713b94 0x007d116c", "only"]
    assert "live" not in SF.cfg_text("http://10.0.0.7/", "x", b"elf", only=True).split()
    prof = next(p for p in MP.profiles().values() if MP.port_path(p).endswith("godzilla_le-1.16.port"))
    p = str(tmp_path)
    SF.save(p, True, "http://192.168.1.50:8080/scores")
    plan = MW.ModePlan(project=p, profile=prof, port=MP.port_path(prof), build=None)
    MW.feed_into(plan, b"elf", str(tmp_path / "s1"), "http://192.168.1.50:8080/scores", only=True)
    assert "live" not in pathlib.Path(plan.scorefeed_file).read_text(encoding="utf-8").split()
    SF.save_live(p, True)
    plan = MW.ModePlan(project=p, profile=prof, port=MP.port_path(prof), build=None)
    MW.feed_into(plan, b"elf", str(tmp_path / "s2"), "http://192.168.1.50:8080/scores", only=False)
    assert "live" in pathlib.Path(plan.scorefeed_file).read_text(encoding="utf-8").splitlines()
    assert any("while a game is played" in l for l in plan.lines)


def test_the_players_line_is_the_games_own_bytes():
    """co-op's finder (portcoop.player_change) on a Spike 2 program: the player-up byte is the port's cur_player, and
    the runtime reads the ball next to it and the count of players. A program it cannot read gives no line."""
    from pinball_decryptor.plugins.stern import score_feed as SF
    assert SF.players_line(b"not an elf") == "" and SF.players_line(b"") == ""
    import os
    elf = next((os.path.join(d, n) for d in (os.environ.get("PAD_GAME_ELFS") or "").split(os.pathsep) if d
                for n in ("godzilla_le-1_16_0_spike2.elf", "godzilla_le-1.16.elf") if os.path.isfile(os.path.join(d, n))),
               None)
    if not elf:
        pytest.skip("game program not present: godzilla_le 1.16 (PAD_GAME_ELFS)")
    from pinball_decryptor.plugins.stern import mode_project as MP
    cur = MP.read_port(str(SDK / "ports" / "godzilla_le-1.16.port"))["data"]["cur_player"]
    with open(elf, "rb") as f:
        assert SF.players_line(f.read()) == "players 0x%08x 0x007d116c" % cur


def test_the_runtime_reads_the_players_bytes():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = R._lift(src, "static void feed_arm(void)")
    assert 'str_starts(raw + i, "players ")' in arm and "maps_has(lv.player_at, 2, MAP_R)" in arm
    emit = R._lift(src, "static void live_emit_as(const char *event, const char *mode, const char *kind, unsigned number,")
    assert "lv.player_at + 1" in emit and "lv.count_at" in emit
    tick = R._lift(src, "static void live_tick(int in_game)")
    assert 'pm_event(nm[k])' in tick and "event_fired[lv.site_id[k]]" in tick       # Godzilla's mball_start site
    assert "if (lv.on) events_arm();" in src


def test_the_contract_shows_the_live_events():
    from pinball_decryptor.plugins.stern import score_feed as SF
    c = SF.contract("http://10.0.0.7:9000/s")["live"]
    assert json.loads(c["body"]) == SF.LIVE_SAMPLE
    assert [f["name"] for f in c["fields"]] == list(SF.LIVE_SAMPLE)
    assert [e["name"] for e in c["events"]][0] == "game_start" and "1.5 s" in c["answer"]


def test_the_network_tab_tick_and_the_overlay_button(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import score_feed as SF
    from pinball_decryptor.webui.tabs import modes as M
    svc = M.ModesTab.__new__(M.ModesTab)
    state, said = {}, []
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "project", lambda: str(tmp_path / "proj"), raising=False)
    monkeypatch.setattr(svc, "_say", lambda text: said.append(text), raising=False)
    monkeypatch.setattr(SF, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(SF, "title_refusal", lambda prof: "")
    (tmp_path / "proj").mkdir()
    assert svc.set_score_feed(True, "http://192.168.1.50:8080/scores") is True
    assert state["feed_live"] is False and state["feed_live_note"] == "" and state["feed_live_label"] == SF.LIVE_LABEL
    assert svc.set_score_feed_live(True) is True
    assert state["feed_live"] is True and state["feed_live_note"] == SF.LIVE_NOTE and "posted too" in said[-1]
    assert svc.set_score_feed_live(False) is True and state["feed_live"] is False
    dest = tmp_path / "pick"

    class W:
        def ask_folder(self, key, title, initialdir=None):
            return str(dest)
    svc.window = W()
    assert svc.save_feed_overlay() is True
    assert sorted(x.name for x in (dest / "score_feed_overlay").iterdir()) == sorted(SF.OVERLAY_FILES)
    assert "README.md" in said[-1]
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "network.js").read_text(encoding="utf-8")
    assert 'call("modes.set_score_feed_live", v)' in js and 'call("modes.save_feed_overlay")' in js
    assert "s.feed_live_tip" in js and "LiveContract" in js


def test_the_sample_overlay_ships_in_the_sdk():
    from pinball_decryptor.plugins.stern import score_feed as SF
    assert pathlib.Path(SF.overlay_dir()) == OVERLAY
    for name in SF.OVERLAY_FILES:
        assert (OVERLAY / name).is_file(), name


def _overlay_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("overlay_server", OVERLAY / "overlay_server.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_sample_overlay_follows_a_game():
    m = _overlay_module()
    b = m.Board()
    base = {"source": "PAD score feed", "game": "Godzilla Premium/LE 1.16", "game_number": 1}
    for seq, ev, extra in ((1, "game_start", {"players": 1, "player": 1, "ball": 0, "scores": [0]}),
                           (2, "ball_start", {"players": 2, "player": 1, "ball": 1, "scores": [0, 0]}),
                           (3, "mode_start", {"players": 2, "player": 1, "ball": 1, "scores": [500, 0],
                                              "mode": "Multiball", "kind": "multiball"}),
                           (6, "score", {"players": 2, "player": 1, "ball": 1, "scores": [9000, 0]})):
        b.take(dict(base, seq=seq, event=ev, **extra))
    st = json.loads(b.json())
    assert st["in_game"] and st["players"] == 2 and st["ball"] == 1 and st["scores"] == [9000, 0]
    assert st["modes"] == [{"name": "Multiball", "kind": "multiball"}] and st["dropped"] == 2
    assert [r["what"] for r in st["recent"]] == ["mode_start: Multiball", "ball_start", "game_start"]
    b.take(dict(base, seq=7, event="mode_end", mode="Multiball", kind="multiball", players=2, player=1, ball=1,
                scores=[9000, 0]))
    b.take(dict(base, seq=8, event="game_end", players=2, player=0, ball=0, scores=[9100, 40]))
    b.take(dict(base, players=2, scores=[9100, 40], insider=[None, None], game_type="standard"))   # the report
    st = json.loads(b.json())
    assert not st["in_game"] and st["modes"] == [] and st["last_game"]["scores"] == [9100, 40]


def test_the_sample_overlay_server_takes_posts_and_serves_the_page(tmp_path):
    from http.server import ThreadingHTTPServer
    m = _overlay_module()
    m.Handler.board, m.Handler.log, m.Handler.quiet = m.Board(), str(tmp_path / "feed.jsonl"), True
    srv = ThreadingHTTPServer(("127.0.0.1", 0), m.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = "http://127.0.0.1:%d" % srv.server_address[1]
        body = json.dumps({"source": "PAD score feed", "event": "ball_start", "seq": 1, "players": 1, "player": 1,
                           "ball": 1, "scores": [10], "game": "G", "game_number": 1}).encode()
        req = urllib.request.Request(url + "/scores", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 204
        with urllib.request.urlopen(url + "/state", timeout=5) as r:
            assert json.loads(r.read())["scores"] == [10]
        with urllib.request.urlopen(url + "/", timeout=5) as r:
            page = r.read().decode()
            assert 'fetch("/state"' in page and "transparent" in page
        assert json.loads((tmp_path / "feed.jsonl").read_text().splitlines()[0])["event"] == "ball_start"
    finally:
        srv.shutdown()
        srv.server_close()
