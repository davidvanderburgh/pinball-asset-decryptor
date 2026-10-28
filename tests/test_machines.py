"""My machines (PAD-783): the records, the Stern release words, the daily
game-code check against a stubbed page, a project joining its machine's row
by fingerprint, and the picker's calls on the real web app.

Two real library cards (the stock Godzilla LE 1.16 and the Heisei custom
built on it) are added through the page's own call when the library is on
this computer; everything else runs anywhere.
"""

import io
import json
import os
import time

import pytest

from pinball_decryptor.core import code_watch, lineage, machines
from pinball_decryptor.plugins.stern import machine_info as mi

LIB = r"D:\Pinball\images\Stern\spike2"
STOCK = os.path.join(LIB, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
CUSTOM = os.path.join(
    LIB, "Godzilla Premium 1.16 Heisei Custom V1.5 Standard Edition.raw")

# Stern's page as it really spells its downloads: JSON-escaped links, a
# Spike 3 build of the same release, a capitalised name, a bare .spk, and
# an older build listed below a newer one.
STUB_PAGE = r"""<script>var x = {"posts":[
{"title":"Godzilla LE 1.17.0 Game Code","download_link":"https:\/\/f002.backblazeb2.com\/file\/gamecode\/godzilla_63_1.17.0_1\/godzilla_le-1_17_0_spike2.spk.zip"},
{"title":"Godzilla LE 1.16.0 Game Code","download_link":"https:\/\/f002.backblazeb2.com\/file\/gamecode\/godzilla_63_1.16.0_1\/godzilla_le-1_16_0_spike2.spk.zip"},
{"title":"Star Wars Home Edition Plus 1.11.0","download_link":"https:\/\/x\/star_wars_elg-1_11_0_spike3.spk.zip"},
{"title":"Star Wars Home Edition 1.10.0","download_link":"https:\/\/x\/star_wars_elg-1_10_0_spike2.spk.zip"},
{"title":"Ghostbusters LE 1.17.0","download_link":"https:\/\/x\/Ghostbusters_le-1_17_0.spk"},
{"title":"The Beatles Gold 1.29.0","download_link":"https:\/\/x\/beatles-1_29_0.spk"},
{"title":"Rush Pro 1.19.0","download_link":"https:\/\/x\/rush_pro-1_19_0.spk.zip"}
]};</script>"""


# ---------------------------------------------------------------- release words
def test_parse_sidx_and_short_version():
    assert mi.parse_sidx("godzilla_le-1_16_0.sidx") == ("godzilla_le", (1, 16, 0))
    assert mi.parse_sidx("spk/index/RUSH_PRO-1_19_0.sidx") == ("rush_pro", (1, 19, 0))
    assert mi.parse_sidx("readme.txt") is None
    assert mi.short_version((1, 16, 0)) == "1.16"
    assert mi.short_version((0, 97, 0)) == "0.97"
    assert mi.short_version((1, 58, 1)) == "1.58.1"


@pytest.mark.parametrize("sidx,title,edition", [
    ("godzilla_le-1_16_0.sidx", "Godzilla", "LE / Premium"),
    ("godzilla_pro-1_16_0.sidx", "Godzilla", "Pro"),
    ("aerosmith-1_16_0.sidx", "Aerosmith", "Pro"),        # bare key beside _le
    ("batman-1_14_0.sidx", "Batman", ""),
    ("dungeons_and_dragons_le-1_10_0.sidx", "Dungeons & Dragons", "LE / Premium"),
    ("turtles_pro-1_59_0.sidx", "Teenage Mutant Ninja Turtles", "Pro"),
    ("james_bond_60th_le-1_11_0.sidx", "James Bond 007 60th Anniversary", "LE / Premium"),
    ("jurassic_park_the_pin-1_05_0.sidx", "Jurassic Park", "Home Edition"),
    ("star_wars_elg-1_10_0.sidx", "Star Wars", "Home Edition"),
    ("metallica_spike-1_04_0.sidx", "Metallica Remastered", ""),
    ("beatles-1_29_0.sidx", "The Beatles", ""),
])
def test_release_info_names_every_library_title(sidx, title, edition):
    got = mi.release_info(sidx, mi.known_release_keys())
    assert (got["title"], got["edition"]) == (title, edition)


def test_every_stock_release_has_a_title():
    keys = mi.known_release_keys()
    assert len(keys) >= 50
    for k in keys:
        got = mi.release_info(k + "-1_00_0.sidx", keys)
        assert got["title"] and "_" not in got["title"], k


def test_page_parse_newest_spike2_only():
    got = mi.parse_game_code_page(STUB_PAGE)
    assert got["godzilla_le"] == (1, 17, 0)               # newest, not first
    assert got["star_wars_elg"] == (1, 10, 0)             # the Spike 3 build skipped
    assert got["ghostbusters_le"] == (1, 17, 0)           # capitals on the page
    assert got["beatles"] == (1, 29, 0)                   # .spk with no .zip
    assert got["rush_pro"] == (1, 19, 0)
    assert mi.parse_game_code_page("<html>nothing</html>") == {}


# ----------------------------------------------------------- the daily check
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def watch_cfg(tmp_path, monkeypatch):
    from pinball_decryptor.core import config
    monkeypatch.setattr(config, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.delenv(code_watch.ENV_URL, raising=False)
    import pinball_decryptor.plugins.stern.manufacturer  # noqa: F401  registers stern
    return tmp_path


def test_check_reads_once_with_the_app_user_agent(watch_cfg):
    seen = []

    def opener(req, timeout):
        seen.append((req.full_url, req.get_header("User-agent"), timeout))
        return _Resp(STUB_PAGE.encode())

    assert code_watch.due("stern", now=1000)
    st = code_watch.check("stern", opener=opener, now=1000)
    assert st["ok"] and st["latest"]["godzilla_le"] == [1, 17, 0]
    url, ua, _t = seen[0]
    assert url == mi.GAME_CODE_PAGE
    assert ua.startswith("Pinball-Asset-Decryptor/")
    assert os.path.isfile(watch_cfg / "code_watch.json")  # beside settings
    assert code_watch.newest("stern", "godzilla_le") == (1, 17, 0)
    # once a day
    assert not code_watch.due("stern", now=1000 + 23 * 3600)
    assert code_watch.due("stern", now=1000 + 24 * 3600)
    assert not code_watch.due("cgc", now=1000)            # no page for it


def test_failed_read_keeps_the_last_answer_and_retries_sooner(watch_cfg):
    code_watch.check("stern", opener=lambda r, timeout: _Resp(STUB_PAGE.encode()),
                     now=1000)

    def boom(req, timeout):
        raise OSError("offline")

    st = code_watch.check("stern", opener=boom, now=2000)
    assert not st["ok"] and "offline" in st["error"]
    assert code_watch.newest("stern", "godzilla_le") == (1, 17, 0)
    assert not code_watch.due("stern", now=2000 + 2 * 3600)
    assert code_watch.due("stern", now=2000 + 3 * 3600)
    # a page that lists nothing readable is a failure, not "no code"
    st = code_watch.check("stern", opener=lambda r, timeout: _Resp(b"<html/>"),
                          now=30000)
    assert not st["ok"] and code_watch.newest("stern", "godzilla_le") == (1, 17, 0)


def test_test_servers_never_reach_the_real_page(monkeypatch):
    monkeypatch.setenv("PAD_UI_NO_UPDATE_CHECK", "1")
    monkeypatch.delenv(code_watch.ENV_URL, raising=False)
    assert not code_watch.allowed()
    monkeypatch.setenv(code_watch.ENV_URL, "http://127.0.0.1:1/stub")
    assert code_watch.allowed()
    assert code_watch.page_url("stern") == "http://127.0.0.1:1/stub"


# ------------------------------------------------------------ the records
INFO = {"print": "p" * 32, "sidx": "godzilla_le-1_16_0.sidx",
        "label": "Godzilla LE 1.16", "official": True}


def test_add_rebind_rename_remove(tmp_path):
    card = tmp_path / "gz.raw"
    card.write_bytes(b"x" * 100)
    s = {}
    e = machines.add(s, str(card), INFO, "Basement", "stern", "t")
    assert e["size"] == 100 and e["print"] == INFO["print"] and e["official"]
    # the same card again updates that machine
    again = machines.add(s, str(card), dict(INFO, print="q" * 32), "", "stern")
    assert again["id"] == e["id"] and again["name"] == "Basement"
    assert len(machines.entries(s)) == 1
    other = tmp_path / "new.raw"
    other.write_bytes(b"y")
    machines.rebind(s, e["id"], str(other), dict(INFO, official=False))
    assert machines.get(s, e["id"])["card"] == str(other)
    assert machines.rename(s, e["id"], "Den")
    assert not machines.rename(s, e["id"], "  ")
    assert machines.get(s, e["id"])["name"] == "Den"
    assert machines.watch_on(s)
    machines.set_watch(s, False)
    assert not machines.watch_on(s)
    assert machines.remove(s, e["id"]) and machines.entries(s) == []
    assert card.exists() and other.exists()               # never touched


def _project(tmp_path, name, info, build_over=None):
    folder = tmp_path / name
    folder.mkdir()
    lineage.note_extract(str(folder), "card.raw", info,
                         "official" if info.get("official") else "modified")
    if build_over is not None:
        lineage.note_build(str(folder), "rev.raw",
                           dict(info, print=build_over, official=False), info)
    return str(folder)


def test_a_project_joins_by_fingerprint(tmp_path):
    stock = _project(tmp_path, "from_stock", INFO, build_over="r" * 32)
    other = _project(tmp_path, "unrelated",
                     dict(INFO, print="z" * 32, official=False))
    m = {"print": INFO["print"], "official": True, "label": INFO["label"]}
    found = machines.projects_for(m, [other, stock, str(tmp_path / "gone")])
    assert [f for f, _w, _l in found] == [stock]
    assert machines.card_words(m, found[0][1]) == "Stock"
    # the machine runs the revision that project built
    built = {"print": "r" * 32, "official": False, "label": INFO["label"]}
    found = machines.projects_for(built, [other, stock])
    assert found[0][1] == ("rev", 1)
    assert machines.card_words(built, found[0][1]) == "PAD build, rev 1"
    # a card none of them knows
    stray = {"print": "s" * 32, "official": False, "label": INFO["label"]}
    assert machines.projects_for(stray, [other, stock]) == []
    assert machines.card_words(stray) == "Modified card"
    assert machines.card_words(dict(stray, label="")) == "Not a known release"


def test_place_in_a_revision_built_over_the_card():
    lin = {"stock": {}, "source": {"print": "a"},
           "revs": [{"rev": 1, "print": "b", "parent": "c"},
                    {"rev": 2, "print": "d", "parent": "c"}]}
    assert machines.place_in(lin, "c") == ("over", 2)
    assert machines.place_in(lin, "a") == ("source", None)
    assert machines.place_in(lin, "x") is None


# ----------------------------------------------------- on the real web app
def _until(w, pred, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return False


def _rows(w):
    return (w.state("shellx").get("machines") or {}).get("rows") or []


def test_picker_calls_add_and_transfer(tmp_path, monkeypatch):
    """A machine added from a card whose print the printer reports (stubbed:
    no card needed), its project joining the row, the stubbed page's newer
    build on it, and Transfer Mods landing on Mod Pack with the project as
    field 1."""
    from tests.webui_harness import web_app
    from pinball_decryptor.core import project_file
    card = tmp_path / "godzilla_le-1_16_0.raw"
    card.write_bytes(b"x" * 4096)
    monkeypatch.setattr(lineage, "card_print",
                        lambda p, measure=False: dict(INFO) if os.path.samefile(p, card) else None)
    proj = _project(tmp_path, "Godzilla mods", INFO)
    project_file.save(project_file.anchor_path(proj), manufacturer_key="stern",
                      paths={"extract_input": str(card)}, extract_options={},
                      stock_image=str(card))
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                                  # noqa: N802
            body = STUB_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv(code_watch.ENV_URL, "http://127.0.0.1:%d/game-code/"
                       % srv.server_address[1])
    try:
        with web_app(tmp_path, settings={"projects": [
                {"folder": proj, "manufacturer": "stern", "last_opened": ""}]}) as w:
            # nothing to show, nothing read
            assert _rows(w) == []
            # a file that is not a card
            junk = tmp_path / "junk.raw"
            junk.write_bytes(b"0")
            w.answers.append("ok")
            assert w.call("shellx.machines_add", str(junk), "x") is None
            assert "Stern Spike 2 card image" in w.asked[-1]["message"]
            assert "Jersey Jack full-install ISO" in w.asked[-1]["message"]
            # the card: the name is asked, the release's words offered
            w.answers.append("Basement Godzilla")
            mid = w.call("shellx.machines_add", str(card))
            assert w.asked[-1]["initial"] == "Godzilla LE"
            assert _until(w, lambda: _rows(w) and _rows(w)[0]["newer"])
            r = _rows(w)[0]
            assert (r["name"], r["title"], r["edition"], r["build"], r["lineage"]) == \
                ("Basement Godzilla", "Godzilla", "LE / Premium", "1.16", "Stock")
            assert r["project"] == proj and r["newer"] == "1.17"
            saved = json.loads((tmp_path / "cfg" / "settings.json").read_text(
                encoding="utf-8"))
            assert saved["machines"][0]["id"] == mid
            # said once, wherever the owner is: a toast and a log line
            said = [t["text"] for t in w.state("shell")["toasts"]
                    if "Stern has Godzilla 1.17 out" in t["text"]]
            assert len(said) == 1 and "Basement Godzilla runs 1.16" in said[0]
            assert saved[machines.TOLD_KEY] == ["%s:1.17" % mid]
            w.call("shellx.machines_refresh")
            _until(w, lambda: False, timeout=1.0)
            assert len([t for t in w.state("shell")["toasts"]
                        if "1.17 out" in t["text"]]) == 1
            # switched off: the line says so and nothing more is read
            assert w.call("shellx.machines_set_watch", False)
            assert _until(w, lambda: "off" in w.state("shellx")["machines"]["watch_text"])
            assert not w.call("shellx.machines_check_now")
            # Transfer Mods: Stern, the project open, Mod Pack, field 1 = it
            assert w.call("shellx.machines_transfer", mid)
            assert _until(w, lambda: w.state("shell").get("tab") == "modpack")
            mp = w.state("modpack")
            assert os.path.normcase(mp["src"]) == os.path.normcase(proj)
            assert mp["dst"] == ""
            assert w.state("shell")["view"] == "mfr"
            assert os.path.normcase(w.app._project_folder()) == os.path.normcase(proj)
            # Write goes to the Write tab with it open
            assert w.call("shellx.machines_write", mid)
            assert w.state("shell").get("tab") == "write"
            # removed from the list only
            w.answers.append("yes")
            assert w.call("shellx.machines_remove", mid)
            assert _until(w, lambda: _rows(w) == [])
            assert card.exists() and os.path.isdir(proj)
    finally:
        srv.shutdown()


@pytest.mark.skipif(not (os.path.isfile(STOCK) and os.path.isfile(CUSTOM)),
                    reason="the Spike 2 card library is not on this computer")
def test_two_real_library_cards(tmp_path, monkeypatch):
    """The stock Godzilla LE 1.16 card and the Heisei custom built on it,
    added through the page's call: real fingerprints, real words."""
    from tests.webui_harness import web_app
    monkeypatch.setenv(code_watch.ENV_URL, "http://127.0.0.1:9/none")
    with web_app(tmp_path) as w:
        a = w.call("shellx.machines_add", STOCK, "Stock")
        b = w.call("shellx.machines_add", CUSTOM, "Heisei")
        assert a and b
        assert _until(w, lambda: len(_rows(w)) == 2)
        rows = {r["id"]: r for r in _rows(w)}
        for mid, words in ((a, "Stock"), (b, "Modified card")):
            r = rows[mid]
            assert (r["title"], r["edition"], r["build"]) == \
                ("Godzilla", "LE / Premium", "1.16")
            assert r["lineage"] == words and r["size"].endswith("GB")
