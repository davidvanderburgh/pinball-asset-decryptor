"""PAD-1585 (David: "promote My machines ... its own button in the app header ... zero state should indicate how to
add ones (are these just remote access ones?) ... out of place on the manufacturer page"): My machines is a page of
its own, opened from the top bar, linked to the machines remote access found on the network."""
import json
import os
import re
import time
from pathlib import Path

from pinball_decryptor.core import lineage, machines, pad_ssh_key
from pinball_decryptor.webui import shellx_machines as SM

ROOT = Path(__file__).resolve().parents[1]
INFO = {"print": "p" * 32, "sidx": "godzilla_le-1_16_0.sidx", "label": "Godzilla LE 1.16", "official": True}
NETWORK = {"current": "10.0.0.7", "machines": [
    {"address": "10.0.0.7", "host_key": None, "game": "godzilla_le"},
    {"address": "10.0.0.9", "host_key": None, "game": "jaws_pro"}]}


def _until(w, ok, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if ok():
            return True
        time.sleep(0.05)
    return ok()


def _m(w):
    return w.state("shellx")["machines"]


def test_a_row_takes_the_network_address_of_the_one_machine_running_its_game():
    rows = [{"id": "a", "game": "godzilla_le", "address": ""}, {"id": "b", "game": "jaws_pro", "address": ""},
            {"id": "c", "game": "godzilla_le", "address": ""}, {"id": "d", "game": "", "address": ""}]
    net = [{"address": "10.0.0.7", "game": "godzilla_le"}, {"address": "10.0.0.9", "game": "jaws_pro"},
           {"address": "10.0.0.11", "game": "jaws_pro"}, {"address": "10.0.0.12", "game": "deadpool_pro"}]
    got, unlinked = SM.link_network(rows, net)
    by = {r["id"]: r["address"] for r in got}
    assert by["a"] == "10.0.0.7"            # the one Godzilla found
    assert by["c"] == ""                    # that one is taken: never guessed twice
    assert by["b"] == ""                    # two Jaws Pro found: none is guessed
    assert [n["address"] for n in unlinked] == ["10.0.0.9", "10.0.0.11", "10.0.0.12"]
    # a row linked by hand keeps its address, and that machine is not offered again
    got, unlinked = SM.link_network([{"id": "b", "game": "jaws_pro", "address": "10.0.0.11"}], net)
    assert got[0]["address"] == "10.0.0.11" and "10.0.0.11" not in [n["address"] for n in unlinked]


def test_set_address_links_a_machine(tmp_path):
    settings = {}
    card = tmp_path / "gz.raw"
    card.write_bytes(b"x")
    e = machines.add(settings, str(card), INFO, "Basement", "stern")
    assert machines.set_address(settings, e["id"], " 10.0.0.7 ") and machines.entries(settings)[0]["address"] == "10.0.0.7"
    assert not machines.set_address(settings, "nope", "1.2.3.4")


def test_the_page_opens_from_the_top_bar_and_offers_what_remote_access_found(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    keys = tmp_path / "remote_access"
    keys.mkdir()
    (keys / "machines.json").write_text(json.dumps(NETWORK))
    monkeypatch.setattr(pad_ssh_key, "KEY_DIR", str(keys))
    card = tmp_path / "godzilla_le-1_16_0.raw"
    card.write_bytes(b"x" * 4096)
    monkeypatch.setattr(lineage, "card_print",
                        lambda p, measure=False: dict(INFO) if os.path.samefile(p, card) else None)
    with web_app(tmp_path) as w:
        assert _until(w, lambda: len(_m(w)["network"]) == 2)
        m = _m(w)
        assert not m["open"] and m["rows"] == []
        assert [(n["address"], n["title"]) for n in m["network"]] == [("10.0.0.7", "Godzilla LE"),
                                                                     ("10.0.0.9", "Jaws Pro")]
        # its own page; Getting started and My machines are one page over the app at a time
        assert w.call("shellx.machines_open") and _m(w)["open"]
        assert w.call("shellx.getting_started_open")
        assert _until(w, lambda: not _m(w)["open"]) and w.state("shellx")["getting_started"]["open"]
        assert w.call("shellx.machines_open")
        assert _until(w, lambda: _m(w)["open"] and not w.state("shellx")["getting_started"]["open"])
        # a machine found on the network, added with the card image it runs: linked to its address
        w.answers.append(str(card))                     # the card picker
        w.answers.append("Basement Godzilla")           # its name
        mid = w.call("shellx.machines_add_network", "10.0.0.9")
        assert mid
        assert _until(w, lambda: _m(w)["rows"] and _m(w)["rows"][0]["address"] == "10.0.0.9")
        saved = json.loads((tmp_path / "cfg" / "settings.json").read_text(encoding="utf-8"))
        assert saved["machines"][0]["address"] == "10.0.0.9"
        assert [n["address"] for n in _m(w)["network"]] == ["10.0.0.7"]
        # the empty page's way to remote access: the Network tab, the page out of the way
        assert w.call("shellx.machines_go_network")
        assert _until(w, lambda: w.state("shell").get("tab") == "network")
        assert not _m(w)["open"]


def test_the_top_bar_has_the_button_and_the_picker_no_longer_carries_the_list():
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "shell.js").read_text(encoding="utf-8")
    assert re.search(r'class=\$\{cx\("btn sm sx-mach-open", machOpen && "on"\)\}', js)
    assert 'aria-label="My machines"' in js
    picker = js[js.index("function Picker("):js.index("function Picker(") + 2000]
    assert "MyMachines" not in picker
    assert "machOpen ? html`<${MyMachines} shell=${shell} />`" in js
    # the empty state names both ways to add one: a card image, and remote access
    for key in ("emptyHead", "wayCard", "wayNet", "wayNetNone"):
        assert key + ":" in js


def test_the_page_lights_the_machines_that_answer_now(tmp_path, monkeypatch):
    """David: "if the game was detected online we'd show a green light next to it": every address the page shows
    is asked when it opens (the banner only), and the answer published per address."""
    from tests.webui_harness import web_app
    from pinball_decryptor.core import machine_scan
    keys = tmp_path / "remote_access"
    keys.mkdir()
    (keys / "machines.json").write_text(json.dumps(NETWORK))
    monkeypatch.setattr(pad_ssh_key, "KEY_DIR", str(keys))
    monkeypatch.delenv("PAD_UI_CAPTURE", raising=False)
    asked = []
    monkeypatch.setattr(machine_scan, "online", lambda a, **kw: asked.append(a) or a == "10.0.0.7")
    with web_app(tmp_path) as w:
        assert _until(w, lambda: len(_m(w)["network"]) == 2)
        assert _m(w)["online"] == {}                    # nothing asked before the page opens
        assert w.call("shellx.machines_open")
        assert _until(w, lambda: _m(w)["online"] == {"10.0.0.7": True, "10.0.0.9": False})
        assert sorted(set(asked)) == ["10.0.0.7", "10.0.0.9"]


def test_online_is_the_banner_check(monkeypatch):
    from pinball_decryptor.core import machine_scan
    monkeypatch.setattr(machine_scan, "_banner", lambda h, p, t: "SSH-2.0-x" if h == "a" else None)
    assert machine_scan.online("a") is True and machine_scan.online("b") is False
