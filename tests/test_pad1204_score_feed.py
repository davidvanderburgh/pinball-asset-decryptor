"""PAD-1204: the score feed - each game's final scores posted to the owner's own server (pad_mode_runtime.c "the score
feed", plugins/stern/score_feed.py).

C0untDeM0net (Pinside): "a high score display external from the games running on a TV ... capture the end game scores
and user info if logged in, then push them to an external server separate from IC". The runtime's pure parts (the
address, the JSON, the next-game witness, the answer's status) are lifted verbatim and run on the host; the rest is the
app's: the address check, the sidecar, scorefeed.cfg, the build's gate and the Modes tab's tick."""
import json
import pathlib
import re

import pytest

from tests import test_spike2_mode_roster as R

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"

MAIN = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdarg.h>
#include <string.h>
@FNS@
static void url(const char *u)
{
    char host[96], path[160];
    unsigned port = 0;
    int ok = feed_parse_url(u, host, sizeof host, &port, path, sizeof path);
    if (ok) printf("url %s -> %s %u %s\n", u, host, port, path);
    else printf("url %s -> no\n", u);
}

int main(void)
{
    unsigned char ip[4];
    struct feed_report r;
    char out[768];
    unsigned n;
    uint64_t kept[4] = { 500, 900, 0, 0 }, same[4] = { 500, 950, 0, 0 }, zeroed[4] = { 0, 900, 0, 0 };
    url("http://192.168.1.50:8080/scores");
    url("http://192.168.1.50");
    url("http://10.0.0.2/a/b?x=1");
    url("http://10.0.0.2:0/");
    url("http://10.0.0.2:70000/");
    url("https://10.0.0.2/");
    url("http://:80/");
    url("http://a b/");
    url("http://10.0.0.2/a b");
    printf("ip %d", feed_ipv4("192.168.1.50", ip));
    printf(" %u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]);
    printf(" %d %d %d %d\n", feed_ipv4("256.1.1.1", ip), feed_ipv4("1.2.3", ip), feed_ipv4("pinball.local", ip),
           feed_ipv4("1.2.3.4.5", ip));
    memset(&r, 0, sizeof r);
    r.players = 2;
    r.number = 3;
    r.scores[0] = 123456780ull;
    r.scores[1] = 98765430000ull;
    r.has_id[0] = 1;
    for (n = 0; n < 16; n++) r.ids[0][n] = (unsigned char)(0x10 + n);
    n = feed_json(out, sizeof out, &r, "Godzilla \"LE\" 1.16\\", "godzilla_le 1.16", 1794326400l);
    printf("json %u %s\n", n, out);
    n = feed_json(out, sizeof out, &r, "x", "y", 0);
    printf("json0 %u %s\n", n, out);
    r.players = 4;
    printf("small %u\n", feed_json(out, 40, &r, "x", "y", 0));
    printf("fell %d %d\n", feed_scores_fell(kept, same, 2), feed_scores_fell(kept, zeroed, 2));
    printf("status %d %d %d %d %d\n", feed_status("HTTP/1.1 200 OK\r\n", 17), feed_status("HTTP/1.0 404 Not", 16),
           feed_status("HTTP/1.1 20", 11), feed_status("SSH-2.0-OpenSSH", 15), feed_status("HTTP/1.1 2x0 OK", 15));
    return 0;
}
"""


def _struct(src, name):
    i = src.index("struct %s {" % name)
    return src[i:src.index("};", i) + 2]


def _run(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join([_struct(src, "feed_report")] + [R._lift(src, sig) for sig in (
        "static int str_starts(const char *s, const char *prefix)\n{",
        "static int feed_parse_url(const char *u, char *host, unsigned hcap, unsigned *port, char *path, unsigned pcap)",
        "static int feed_ipv4(const char *s, unsigned char out[4])",
        "static int feed_fmt(char *b, unsigned long cap, const char *f, ...)",
        "static unsigned feed_json_str(char *out, unsigned cap, const char *s)",
        "static unsigned feed_json(char *out, unsigned cap, const struct feed_report *r, const char *title,",
        "static int feed_scores_fell(const uint64_t *kept, const uint64_t *now, unsigned players)",
        "static int feed_status(const char *resp, unsigned len)")])
    return R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()


def test_the_runtime_reads_an_http_address(tmp_path):
    out = _run(tmp_path)
    assert "url http://192.168.1.50:8080/scores -> 192.168.1.50 8080 /scores" in out
    assert "url http://192.168.1.50 -> 192.168.1.50 80 /" in out
    assert "url http://10.0.0.2/a/b?x=1 -> 10.0.0.2 80 /a/b?x=1" in out
    for bad in ("http://10.0.0.2:0/", "http://10.0.0.2:70000/", "https://10.0.0.2/", "http://:80/", "http://a b/",
                "http://10.0.0.2/a b"):
        assert "url %s -> no" % bad in out, bad


def test_the_runtime_posts_to_an_ipv4_address_only(tmp_path):
    """A name lookup would hold the game up: the machine takes an IP address."""
    assert "ip 1 192.168.1.50 0 0 0 0" in _run(tmp_path)


def test_the_report_is_json_with_every_player(tmp_path):
    out = _run(tmp_path)
    line = next(l for l in out if l.startswith("json "))
    n, text = line.split(" ", 2)[1:]
    assert int(n) == len(text)
    doc = json.loads(text)
    assert doc == {"source": "PAD score feed", "game": 'Godzilla "LE" 1.16\\', "port": "godzilla_le 1.16",
                   "game_number": 3, "time": 1794326400, "players": 2, "scores": [123456780, 98765430000],
                   "insider": ["10111213-1415-1617-1819-1a1b1c1d1e1f", None]}
    doc0 = json.loads(next(l for l in out if l.startswith("json0 ")).split(" ", 2)[2])
    assert doc0["time"] is None                                       # the machine's clock was never set
    assert "small 0" in out                                           # a report that does not fit is not cut short


def test_a_lower_score_at_a_ball_start_is_the_next_game(tmp_path):
    """The game zeroes the scores for a new game; a ball of the same game only adds."""
    assert "fell 0 1" in _run(tmp_path)


def test_the_answers_status(tmp_path):
    assert "status 200 404 0 0 0" in _run(tmp_path)


def _section(src):
    return src[src.index("/* ---- PAD-1204: the score feed"):src.index("/* ---- PAD-1052: TEAM PLAY")]


def test_it_never_waits_on_the_network_inside_the_game():
    """MODE_SDK.md rules 1 and 2 (build_mode.sh refuses pthread_*, sleeping, poll and select): the send is stepped on
    the game's tick with a non-blocking socket, and a hang-up never signals the game."""
    sec = _section(RUNTIME.read_text(encoding="utf-8"))
    code = re.sub(r"/\*.*?\*/", "", sec, flags=re.S)
    for banned in ("pthread_", "sleep(", "nanosleep", "poll(", "select(", "getaddrinfo", "malloc"):
        assert banned not in code, banned
    assert "0x800" in code and "SOCK_NONBLOCK" in sec                  # the socket never blocks
    assert "0x4000 | 0x40" in code and "MSG_NOSIGNAL" in sec            # nor does a send, nor a hang-up's SIGPIPE
    tick = R._lift(sec, "static void on_feed_tick(unsigned *regs)")
    assert "feed_send_step();" in tick
    for weak in ("socket", "connect", "send", "__errno_location"):
        assert re.search(r"extern [^;]*\b%s\(.*__attribute__\(\(weak\)\);" % re.escape(weak), sec), weak


def test_it_arms_before_the_score_gate_and_alone_keeps_insider_connected():
    src = RUNTIME.read_text(encoding="utf-8")
    assert src.index("feed_arm();") < src.index("if (!insider_arm()) return;")
    assert "(cabs_only && n_cabs))\n         || feed_cfg_only())" in src
    arm = R._lift(src, "static void feed_arm(void)")
    assert 'hook(bus->addr, on_feed_dispatch)' in arm and 'hook(fn("tick"), on_feed_tick)' in arm
    assert 'event_bus_id("game_over")' in arm


def test_the_end_of_a_game(tmp_path):
    """game_over where the port names it; else play stopped for FEED_QUIET_MS with no new ball."""
    sec = _section(RUNTIME.read_text(encoding="utf-8"))
    tick = R._lift(sec, "static void on_feed_tick(unsigned *regs)")
    assert 'feed_queue(&r, "the game\'s game_over")' in tick
    assert "!feed.over_named && feed.pending && pm_ms() - feed.fall_ms >= FEED_QUIET_MS" in tick
    assert "feed_scores_fell(feed.kept.scores, now, feed.kept.players)" in tick
    assert "#define FEED_QUIET_MS   30000ul" in sec


def _port(path):
    from pinball_decryptor.plugins.stern import mode_project as MP
    return MP.read_port(str(path))


def test_every_port_but_one_can_see_a_games_end():
    from pinball_decryptor.plugins.stern import score_feed as SF
    refused = [p.name for p in sorted(PORTS.glob("*.port")) if not SF.port_ok(_port(p))]
    assert len(refused) <= 1, refused
    assert SF.port_ok(_port(PORTS / "godzilla_le-1.16.port"))
    assert SF.port_ok(_port(PORTS / "beatles-1.29.port"))             # 32-bit scores


@pytest.mark.parametrize("url,ok", [
    ("http://192.168.1.50:8080/scores", True),
    ("http://10.0.0.7", True),
    (" http://10.0.0.7/x ", True),
    ("", False),
    ("https://192.168.1.50/scores", False),
    ("ftp://192.168.1.50/", False),
    ("http://pinball.local/scores", False),
    ("http://127.0.0.1:8080/", False),
    ("http://0.0.0.0/", False),
    ("http://192.168.1.300/", False),
    ("http://192.168.1.50:99999/", False),
    ("http://192.168.1.50/a b", False),
    ("http://192.168.1.50/" + "x" * 200, False),
])
def test_the_address_check(url, ok):
    from pinball_decryptor.plugins.stern import score_feed as SF
    assert (SF.url_problem(url) == "") is ok, (url, SF.url_problem(url))


def test_the_tick_and_the_address_are_kept_in_the_project(tmp_path):
    from pinball_decryptor.plugins.stern import score_feed as SF
    p = str(tmp_path)
    assert SF.load(p) == (False, "")
    assert SF.save(p, True, "http://10.0.0.7:9000/s") == (False, "")
    assert SF.load(p) == (True, "http://10.0.0.7:9000/s") and SF.wanted(p) == "http://10.0.0.7:9000/s"
    assert SF.save(p, False) == (True, "http://10.0.0.7:9000/s")
    assert SF.load(p) == (False, "http://10.0.0.7:9000/s") and SF.wanted(p) == ""   # the address kept for next time
    SF.save(p, True, "https://x/")
    assert SF.wanted(p) == ""                                          # ticked, but nothing the machine can post to
    SF.save(p, False, "")
    from pinball_decryptor.core import staged_changes
    assert SF.STAGED_KEY not in staged_changes.load(p)


def test_scorefeed_cfg(monkeypatch):
    from pinball_decryptor.plugins.stern import coop_play as CP
    from pinball_decryptor.plugins.stern import score_feed as SF
    monkeypatch.setattr(CP, "insider_users", lambda elf: (0x7bf878, 0x160, 0x164))
    text = SF.cfg_text(" http://10.0.0.7:9000/s ", "Godzilla  Premium/LE 1.16", b"elf", only=True)
    assert text.splitlines()[1:] == ["feed http://10.0.0.7:9000/s", "title Godzilla Premium/LE 1.16",
                                     "users 0x007bf878 0x160 0x164", "only"]
    monkeypatch.setattr(CP, "insider_users", lambda elf: None)
    assert "users" not in SF.cfg_text("http://10.0.0.7/", "x", b"elf", only=False)
    assert "only" not in SF.cfg_text("http://10.0.0.7/", "x", b"elf", only=False).split()
    with pytest.raises(SF.ScoreFeedError):
        SF.cfg_text("https://10.0.0.7/", "x", b"elf", only=True)


def test_scorefeed_cfg_rides_with_the_runtime():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mode_install", ROOT / "tools" / "spike2_emu" / "mode_install.py")
    mi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mi)
    assert ("scorefeed.cfg", 0o100644) in mi.EXTRA_FILES and "scorefeed.cfg" in mi.STANDALONE_FILES
    for sh in ("cardmodes.sh", "tryit.sh"):
        assert "scorefeed.cfg" in (ROOT / "tools" / "spike2_emu" / "modes" / sh).read_text(encoding="utf-8"), sh
    src = RUNTIME.read_text(encoding="utf-8")
    assert '"/usr/local/padmode/scorefeed.cfg", "/dump/scorefeed.cfg"' in src


def test_mode_write_puts_scorefeed_cfg_beside_the_runtime(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import coop_play as CP
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(CP, "insider_users", lambda elf: (0x7bf878, 0x160, 0x164))
    prof = next(p for p in MP.profiles().values() if MP.port_path(p).endswith("godzilla_le-1.16.port"))
    plan = MW.ModePlan(project=str(tmp_path), profile=prof, port=MP.port_path(prof), build=None)
    MW.feed_into(plan, b"elf", str(tmp_path / "scratch"), "http://192.168.1.50:8080/scores", only=True)
    lines = pathlib.Path(plan.scorefeed_file).read_text(encoding="utf-8").splitlines()
    assert lines[1] == "feed http://192.168.1.50:8080/scores" and lines[-1] == "only"
    assert "users 0x007bf878 0x160 0x164" in lines and lines[2] == "title %s" % prof.label
    assert any(l.startswith("score feed: at the end of each game") for l in plan.lines)
    with pytest.raises(MW.ModeWriteError):
        MW.feed_into(plan, b"elf", str(tmp_path / "scratch2"), "http://pinball.local/", only=True)
    # the staging copies it beside the runtime
    src = (ROOT / "pinball_decryptor" / "plugins" / "stern" / "mode_write.py").read_text(encoding="utf-8")
    assert 'if getattr(result, "scorefeed_file", ""):' in src


def test_the_build_leaves_it_out_with_one_warning(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import score_feed as SF
    said = []
    log = lambda text, level="info": said.append((level, text))   # noqa: E731
    p = str(tmp_path)
    assert E._feed_for_build(p, False, log) == (None, "")
    assert said == []                                                 # not asked for: not a word
    SF.save(p, True, "https://10.0.0.7/")
    assert E._feed_for_build(p, False, log) == (None, "")
    assert said[-1][0] == "warning" and "https://" in said[-1][1]
    SF.save(p, True, "http://10.0.0.7:9000/s")
    assert E._feed_for_build(p, True, log) == (None, "")
    assert "direct-SD" in said[-1][1]
    monkeypatch.setattr(SF, "project_title", lambda project, probe=False: "PROF")
    monkeypatch.setattr(SF, "title_refusal", lambda prof: "")
    monkeypatch.setattr("pinball_decryptor.plugins.stern.mode_write.host_refusal", lambda: "")
    assert E._feed_for_build(p, False, log, ext4_available=lambda: (True, "")) == ("PROF", "http://10.0.0.7:9000/s")
    assert said[-1] == ("info", "Score feed: %s." % (SF.HOW % "http://10.0.0.7:9000/s"))


def test_the_modes_tab_tick_and_its_address(tmp_path, monkeypatch):
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.plugins.stern import score_feed as SF
    from pinball_decryptor.webui.tabs import modes as M
    svc = M.ModesTab.__new__(M.ModesTab)
    state, said = {}, []
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "project", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "_say", lambda text: said.append(text), raising=False)
    monkeypatch.setattr(SF, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(SF, "title_refusal", lambda prof: "")
    staged_changes.save(str(tmp_path), {"audio": {"x": "y"}})
    assert svc.set_score_feed(True) is True                         # ticked, no address yet: says what to type
    assert state["feed_shown"] is True and state["feed_on"] is True and state["feed_note_kind"] == "err"
    assert svc.set_score_feed(True, "http://192.168.1.50:8080/scores") is True
    assert staged_changes.load(str(tmp_path))[SF.STAGED_KEY] == {"on": True, "url": "http://192.168.1.50:8080/scores"}
    assert state["feed_url"] == "http://192.168.1.50:8080/scores" and state["feed_note"] == SF.NOTE
    assert "posting to http://192.168.1.50:8080/scores" in said[-1]
    assert svc.set_score_feed(True, "http://pinball.local/") is True
    assert state["feed_note_kind"] == "err" and "IP address" in state["feed_note"]
    assert svc.set_score_feed(False) is True and state["feed_on"] is False and state["feed_note"] == ""
    monkeypatch.setattr(SF, "title_refusal", lambda prof: "no port")
    svc._publish_feed(str(tmp_path))
    assert state["feed_shown"] is False                              # a game whose end it cannot see: hidden
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes.js").read_text(encoding="utf-8")
    assert 'call("modes.set_score_feed", v)' in js and 'call("modes.set_score_feed", true, v)' in js


def test_what_keeps_insider_connected_has_its_own_section():
    """David: "users see the banner at the top and assume they lose IC access" - the options that change no score sit
    in a section of their own that says Insider Connected stays, and the banner says only modes and co-op hold the
    reports back."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    assert MP.KEEPS_IC_HEAD == "Keeps Insider Connected"
    assert MP.KEEPS_IC_HEAD in MP.INSIDER_TAB_NOTE and "modes or co-op play" in MP.INSIDER_TAB_NOTE
    assert "keep Insider Connected" in MP.KEEPS_IC_NOTE
    for text in (MP.INSIDER_TAB_NOTE, MP.KEEPS_IC_NOTE):
        assert "—" not in text
    tab = (ROOT / "pinball_decryptor" / "webui" / "tabs" / "modes.py").read_text(encoding="utf-8")
    assert "insider_note = MP.INSIDER_TAB_NOTE" in tab
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes.js").read_text(encoding="utf-8")
    def fn(name):
        i = js.index("function %s(" % name)
        return js[i:js.index("\nfunction ", i + 1)]
    card = fn("KeepsIcCard")
    for call in ("modes.set_handicap", "modes.set_prolonged_comp", "modes.set_score_feed", "modes.set_idle_pause"):
        assert call in card, call
    assert "modes.set_coop" not in card                                  # co-op takes the reports off: not here
    lst = fn("ModeList")
    assert "modes.set_coop" in lst and "modes.set_handicap" not in lst and "modes.set_score_feed" not in lst
    assert "<${KeepsIcCard} s=${s}" in js
