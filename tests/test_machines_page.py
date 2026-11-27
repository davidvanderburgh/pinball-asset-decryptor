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
        assert [(n["address"], n["title"]) for n in m["network"]] == [("10.0.0.7", "Godzilla LE / Premium"),
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


KEY = ["ssh-ed25519", "AAAAgodzilla"]
MOVED = {"current": "10.0.0.7", "machines": [
    {"address": "10.0.0.50", "host_key": None, "game": ""},                 # typed in, never answered
    {"address": "10.0.0.7", "host_key": KEY, "game": "godzilla_le"}]}


def _keys(tmp_path, monkeypatch, data):
    keys = tmp_path / "remote_access"
    keys.mkdir()
    (keys / "machines.json").write_text(json.dumps(data))
    monkeypatch.setattr(pad_ssh_key, "KEY_DIR", str(keys))
    return keys


def test_find_my_machines_follows_a_machine_to_its_new_address(tmp_path, monkeypatch):
    """PAD-1627 (David: "I don't see my godzilla that is turned on right now"): the router gave the machine a new
    address; the page looks over the network by itself when a known machine doesn't answer, finds it by its
    identity, and the row linked to the old address follows it."""
    from tests.webui_harness import web_app
    from pinball_decryptor.core import machine_scan
    _keys(tmp_path, monkeypatch, MOVED)
    monkeypatch.delenv("PAD_UI_CAPTURE", raising=False)
    card = tmp_path / "godzilla_le-1_16_0.raw"
    card.write_bytes(b"x" * 4096)
    monkeypatch.setattr(lineage, "card_print",
                        lambda p, measure=False: dict(INFO) if os.path.samefile(p, card) else None)
    monkeypatch.setattr(machine_scan, "online", lambda a, **kw: a == "10.0.0.12")
    scans = []

    def scan(*a, **kw):
        scans.append(kw)
        return [dict(address="10.0.0.12", banner="SSH-2.0-dropbear", lets_in=True, game="godzilla_le",
                     host_key=tuple(KEY), note="")]
    monkeypatch.setattr(machine_scan, "scan", scan)
    with web_app(tmp_path) as w:
        assert _until(w, lambda: len(_m(w)["network"]) == 2)
        w.answers.append(str(card))
        w.answers.append("Basement Godzilla")
        mid = w.call("shellx.machines_add_network", "10.0.0.7")
        assert mid and not scans
        assert w.call("shellx.machines_open")           # the old address doesn't answer: it looks by itself
        assert _until(w, lambda: _m(w)["rows"] and _m(w)["rows"][0]["address"] == "10.0.0.12")
        assert _until(w, lambda: _m(w)["online"].get("10.0.0.12") is True)
        m = _m(w)
        assert len(scans) == 1 and not m["finding"] and m["find_kind"] == "ok"
        assert m["find_note"] == "Godzilla LE / Premium is on at 10.0.0.12 (it was at 10.0.0.7)."
        assert [n["address"] for n in m["network"]] == ["10.0.0.50"]
        saved = json.loads((tmp_path / "cfg" / "settings.json").read_text(encoding="utf-8"))
        assert saved["machines"][0]["address"] == "10.0.0.12"
        assert pad_ssh_key.last_address() == "10.0.0.12"
        # asked for again from the page, whenever
        assert w.call("shellx.machines_find")
        assert _until(w, lambda: len(scans) == 2 and not _m(w)["finding"])
        assert _m(w)["find_note"] == "Godzilla LE / Premium is on at 10.0.0.12."


def test_a_found_machine_is_named_and_an_address_nothing_answered_at_is_said_and_forgotten(tmp_path, monkeypatch):
    """PAD-1627 (David: "I should be able to name it. I don't have a godzilla LE, it's a premium" and "'A stern
    machine' I have no idea what that is")."""
    from tests.webui_harness import web_app
    _keys(tmp_path, monkeypatch, MOVED)
    with web_app(tmp_path) as w:
        assert _until(w, lambda: len(_m(w)["network"]) == 2)
        typed, god = _m(w)["network"]
        assert (typed["known"], typed["title"], typed["name"]) == (False, "", "")
        assert (god["known"], god["title"], god["name"]) == (True, "Godzilla LE / Premium", "")
        w.answers.append("Godzilla Premium")
        assert w.call("shellx.machines_name_network", "10.0.0.7")
        assert _until(w, lambda: _m(w)["network"][1]["name"] == "Godzilla Premium")
        assert pad_ssh_key.machines()[1]["name"] == "Godzilla Premium"
        # the name stays with the machine when it is found at another address
        pad_ssh_key.remember_machine("10.0.0.12", tuple(KEY), "godzilla_le", make_current=False)
        assert [(x["address"], x["name"]) for x in pad_ssh_key.machines()][-1] == ("10.0.0.12", "Godzilla Premium")
        w.answers.append("yes")
        assert w.call("shellx.machines_forget_network", "10.0.0.50")
        assert _until(w, lambda: [n["address"] for n in _m(w)["network"]] == ["10.0.0.12"])
        assert not w.call("shellx.machines_forget_network", "10.0.0.50")


def test_the_page_has_find_names_and_forget():
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "shell.js").read_text(encoding="utf-8")
    for needle in ('call("shellx.machines_find")', 'call("shellx.machines_name_network", n.address)',
                   'call("shellx.machines_forget_network", n.address)', "Find my machines", "MACH.unknownText(n)"):
        assert needle in js


def test_a_machine_on_a_new_card_and_a_new_address_takes_its_old_place(tmp_path, monkeypatch):
    """PAD-1627, on David's network: his Godzilla was at a new address AND on a card written since (a new
    identity), so it came back as a second Godzilla.  One machine of a game gone, one new of that game found:
    the same machine, its name kept.  Two of a game: none is guessed."""
    from pinball_decryptor.core import machine_scan
    _keys(tmp_path, monkeypatch, MOVED)
    pad_ssh_key.name_machine("10.0.0.7", "Godzilla Premium")
    new = dict(address="10.0.0.12", banner="SSH-2.0-dropbear", lets_in=True, game="godzilla_le",
               host_key=("ssh-ed25519", "AAAAnewcard"), note="")
    ours, moved = machine_scan.remember([new])
    assert moved == {"10.0.0.7": "10.0.0.12"} and len(ours) == 1
    assert [(m["address"], m["name"], m["host_key"][1] if m["host_key"] else None)
            for m in pad_ssh_key.machines()] == [("10.0.0.50", "", None),
                                                 ("10.0.0.12", "Godzilla Premium", "AAAAnewcard")]
    assert pad_ssh_key.last_address() == "10.0.0.12"
    assert SM._find_careful([new]) is False            # accounted for: the slow pass is not needed
    # a second Godzilla turns up while the first still answers: it is another machine
    other = dict(new, address="10.0.0.13", host_key=("ssh-ed25519", "AAAAother"))
    _ours, moved = machine_scan.remember([new, other])
    assert moved == {} and [m["address"] for m in pad_ssh_key.machines()] == ["10.0.0.50", "10.0.0.12", "10.0.0.13"]


# ---- PAD-1627: a machine that says where it is (core/machine_announce.py, resources/ssh/sshd) ----
def _labels(name):
    return b"".join(bytes([len(x)]) + x.encode() for x in name.split(".")) + b"\0"


def _answer(game="godzilla_le", key="ssh-ed25519 AAAAgodzilla", service="_pad-machine._tcp.local"):
    """An answer the way avahi sends it: the question echoed, then PTR, SRV, TXT and A, names compressed."""
    import struct
    head = struct.pack(">HHHHHH", 0, 0x8400, 1, 1, 0, 3)
    q = _labels(service) + struct.pack(">HH", 12, 1)
    svc = b"\xc0\x0c"                                    # a pointer to the question's name
    inst = b"\x10PAD stern-spike2" + svc
    ptr = svc + struct.pack(">HHIH", 12, 1, 4500, len(inst)) + inst
    at = len(head) + len(q) + len(ptr) - len(inst)       # where the instance name sits
    iname = struct.pack(">H", 0xC000 | at)
    target = _labels("stern-spike2.local")
    srv = iname + struct.pack(">HHIH", 33, 0x8001, 120, 6 + len(target)) + struct.pack(">HHH", 0, 0, 22) + target
    txts = b"".join(bytes([len(t)]) + t for t in (b"v=1", ("game=" + game).encode(), ("key=" + key).encode()))
    txt = iname + struct.pack(">HHIH", 16, 0x8001, 4500, len(txts)) + txts
    a = _labels("stern-spike2.local") + struct.pack(">HHIH", 1, 0x8001, 120, 4) + bytes([10, 0, 0, 12])
    return head + q + ptr + srv + txt + a


def test_an_announce_answer_is_read_and_anything_else_is_not():
    from pinball_decryptor.core import machine_announce as MA
    q = MA.question()
    assert q[:12] == b"\0\0\0\0\0\1\0\0\0\0\0\0" and q.endswith(b"\x05local\x00\x00\x0c\x80\x01")
    assert MA.parse(_answer()) == {"game": "godzilla_le", "host_key": ("ssh-ed25519", "AAAAgodzilla"),
                                   "port": 22, "name": "PAD stern-spike2"}
    assert MA.parse(_answer(key="rubbish"))["host_key"] is None
    assert MA.parse(q) is None                          # a question, not an answer
    assert MA.parse(_answer(service="_ssh._tcp.local")) is None
    for bad in (b"", b"\x00" * 5, _answer()[:40], b"\xff" * 64):
        assert MA.parse(bad) is None
    assert MA.ask(wait=0.05, addresses=[]) == []


def test_the_start_script_announces_only_where_the_card_has_the_service():
    from pinball_decryptor.core import ssh_card, ssh_jjp
    for text in (ssh_card.payload_bytes("sshd", {}, ssh_card.layout("stern-spike2")), ssh_jjp.start_script()):
        text = text.decode("ascii")
        assert "\r" not in text
        assert 'if [ -x "$AVAHI" ] && [ -d /etc/avahi/services ]; then' in text
        assert "<type>_pad-machine._tcp</type>" in text and "enable-dbus=no" in text
        # never in the way of the login, and everything it makes is in RAM
        assert "( announce ) </dev/null >/dev/null 2>&1 || true" in text
        assert "ANNOUNCE=/var/run/pad-announce" in text and "announce)" in text
        assert text.index('"$DAEMON" -P "$PIDFILE"') < text.index("( announce )")
        # PAD-1631: JJP runs its own avahi: it is told to read its services again, never a second one started
        # beside it, and never stopped by ours
        body = text[text.index("announce() {"):text.index("announcing() {")]
        assert body.index('if "$AVAHI" -c; then') < body.index('"$AVAHI" -r') < body.index("elif system_avahi")
        stop = text[text.index("  stop)"):text.index("  restart)")]
        assert '"$AVAHI" -k' in stop and stop.index('if [ -f "$ANNOUNCE/own" ]') < stop.index('"$AVAHI" -k')
        assert "-k -f" not in stop
        # PAD-1631: a Spike 3 card has no avahi but python3: the answerer runs from RAM, one at a time
        assert "py=$(command -v python3 2>/dev/null) || return 0" in body
        assert body.index('kill "$(cat "$ANNOUNCE/answer.pid")"') < body.index('cat > "$ANNOUNCE/answer.py"')


def _answerer():
    from pinball_decryptor.core import ssh_card
    text = ssh_card.payload_bytes("sshd", {}, ssh_card.layout("stern-spike2")).decode("ascii")
    return text.split("<<'PAD_ANSWER'\n", 1)[1].split("\nPAD_ANSWER\n", 1)[0]


def test_the_answerer_of_a_card_with_no_avahi_answers_the_apps_question(tmp_path):
    """PAD-1631: the answerer the start script runs on a Spike 3 card, run for real: the app's own question,
    sent straight to it, gets the game, the SSH identity and the port back; any other question gets nothing."""
    import os
    import socket
    import subprocess
    import sys
    import time
    from pinball_decryptor.core import machine_announce as MA
    script = tmp_path / "answer.py"
    script.write_text(_answerer(), encoding="utf-8")
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    env = dict(os.environ, PAD_ANSWER_PORT=str(port))
    p = subprocess.Popen([sys.executable, "-I", str(script), "fallout_le", "ssh-ed25519 AAAAfallout"], env=env)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.3)
    try:
        got = None
        end = time.monotonic() + 20
        while got is None and time.monotonic() < end:
            s.sendto(MA.question(), ("127.0.0.1", port))
            try:
                data, _src = s.recvfrom(9000)
            except (socket.timeout, ConnectionResetError):   # not listening yet (Windows says so)
                assert p.poll() is None, "the answerer stopped"
                continue
            got = MA.parse(data)
        assert got is not None
        assert got["game"] == "fallout_le" and got["host_key"] == ("ssh-ed25519", "AAAAfallout")
        assert got["port"] == 22 and got["name"].startswith("PAD ")
        # an A record with the address it was asked on
        assert socket.inet_aton("127.0.0.1") in data
        s.sendto(MA.question("_ssh._tcp.local"), ("127.0.0.1", port))
        try:
            s.recvfrom(9000)
            raise AssertionError("answered a question that was not for it")
        except socket.timeout:
            pass
        assert p.poll() is None
    finally:
        s.close()
        p.kill()
        p.wait(10)


def test_only_a_machine_not_where_it_is_remembered_is_news(tmp_path, monkeypatch):
    from pinball_decryptor.core import machine_scan
    _keys(tmp_path, monkeypatch, MOVED)
    said = {"address": "10.0.0.7", "game": "godzilla_le", "host_key": tuple(KEY), "port": 22, "name": "PAD x"}
    probed = []

    def probe(host, port=22, timeout=8):
        probed.append(host)
        return dict(lets_in=host != "10.0.0.99", game="godzilla_le", host_key=("ssh-ed25519", "AAAAnewcard"),
                    note="")
    monkeypatch.setattr(machine_scan, "probe", probe)
    monkeypatch.setattr(machine_scan, "_refused", {})
    assert machine_scan.news([said]) == [] and not probed           # where it was, the identity it had
    assert machine_scan.news([dict(said, host_key=("ssh-rsa", "AAAAother"))]) == []     # another kind of key
    moved = dict(said, address="10.0.0.12", host_key=("ssh-ed25519", "AAAAnewcard"))
    recs = machine_scan.news([moved])
    assert [(r["address"], r["lets_in"], r["announces"]) for r in recs] == [("10.0.0.12", True, True)]
    ours, went = machine_scan.remember(recs)
    assert went == {"10.0.0.7": "10.0.0.12"} and pad_ssh_key.machines()[-1]["announces"] is True
    assert machine_scan.news([moved]) == []                        # known there now
    assert SM._find_careful([]) is False                           # it is asked, never swept for
    # one that doesn't let this computer in is not tried again every half minute
    other = dict(said, address="10.0.0.99", host_key=("ssh-ed25519", "AAAAstranger"))
    assert len(machine_scan.news([other], now=1000.0)) == 1
    assert machine_scan.news([other], now=1100.0) == [] and len(machine_scan.news([other], now=1700.0)) == 1
    # found again by its identity at once
    monkeypatch.setattr(machine_scan, "ANNOUNCE", True)
    from pinball_decryptor.core import machine_announce
    asked = []
    monkeypatch.setattr(machine_announce, "ask", lambda also=(): asked.append(list(also)) or [
        dict(moved, address="10.0.0.33")])
    monkeypatch.setattr(machine_scan, "scan", lambda *a, **k: (_ for _ in ()).throw(AssertionError("swept")))
    assert machine_scan.find_moved(("ssh-ed25519", "AAAAnewcard")) == "10.0.0.33"
    assert asked == [["10.0.0.12"]]                     # the address it was last at is asked directly too


def test_the_page_follows_a_machine_that_says_where_it_is_with_no_sweep(tmp_path, monkeypatch):
    """David: "the IP address is pretty much going to change every time the machine boots on. we need the machine
    to reach out to the app": the page's own check asks the network, and the row goes to the new address."""
    from tests.webui_harness import web_app
    from pinball_decryptor.core import machine_scan
    _keys(tmp_path, monkeypatch, MOVED)
    monkeypatch.delenv("PAD_UI_CAPTURE", raising=False)
    monkeypatch.setattr(machine_scan, "online", lambda a, **kw: a == "10.0.0.12")
    monkeypatch.setattr(machine_scan, "announced", lambda: [
        {"address": "10.0.0.12", "game": "godzilla_le", "host_key": tuple(KEY), "port": 22, "name": "PAD x"}])
    monkeypatch.setattr(machine_scan, "probe", lambda host, port=22, timeout=8: dict(
        lets_in=True, game="godzilla_le", host_key=tuple(KEY), note=""))
    monkeypatch.setattr(machine_scan, "_refused", {})
    monkeypatch.setattr(machine_scan, "scan", lambda *a, **k: (_ for _ in ()).throw(AssertionError("swept")))
    with web_app(tmp_path) as w:
        assert _until(w, lambda: len(_m(w)["network"]) == 2)
        assert w.call("shellx.machines_open")
        assert _until(w, lambda: [n["address"] for n in _m(w)["network"]] == ["10.0.0.50", "10.0.0.12"])
        assert _until(w, lambda: _m(w)["online"].get("10.0.0.12") is True)
        m = _m(w)
        assert m["network"][1]["announces"] is True and not m["finding"]
        assert m["find_note"] == "Godzilla LE / Premium is on at 10.0.0.12 (it was at 10.0.0.7)."


class _Machine:
    """A machine over remote access, as core/network_apply talks to one."""
    def __init__(self, files, avahi=True):
        self.files, self.avahi, self.ran, self.sftp, self.corrupt = dict(files), avahi, [], self, False

    def open(self, path, mode):
        import io as _io
        m = self
        if "r" in mode:
            if path not in m.files:
                raise IOError(path)
            return _io.BytesIO(m.files[path])

        class F(_io.BytesIO):
            def __exit__(s, *a):
                m.files[path] = s.getvalue()[:-1] + b"!" if m.corrupt else s.getvalue()
        return F()

    def sh(self, script, timeout=60, check=True):
        import hashlib
        self.ran.append(script)
        words = script.replace("'", "").split()
        if "PAD_HAS" in script:
            # PAD-1631: avahi, or python3 for the script's own answerer (a Spike 3 card)
            assert "avahi-daemon" in script and "command -v python3" in script
            return 0, "PAD_HAS\n" if self.avahi else ""
        if "remount,rw" in script:
            return 0, "PAD_RW\n"
        if words[0] == "sha1sum":
            return 0, "%s %s\n" % (hashlib.sha1(self.files[words[1]]).hexdigest(), words[1])
        if "PAD_PUT" in script:
            self.files[words[words.index("mv") + 3]] = self.files.pop(words[words.index("mv") + 2])
            return 0, "PAD_PUT\n"
        if words[0] == "rm":
            self.files.pop(words[2], None)
        if words[-1] == "announce":
            return 0, "PAD_ANNOUNCING\n"
        return 0, ""


def test_a_machine_set_up_before_is_made_to_say_where_it_is():
    import pytest
    from pinball_decryptor.core import network_apply as A, ssh_card
    from pinball_decryptor.core.card_extras import ExtrasError
    new = ssh_card.payload_bytes("sshd", {}, ssh_card.layout("stern-spike2"))
    m = _Machine({"/etc/init.d/sshd": b"#!/bin/sh\n# the script of before\n"})
    assert A.announce_to_machine(m) == "on"
    assert m.files == {"/etc/init.d/sshd": new}
    assert any("remount,rw" in r for r in m.ran) and "remount,ro" in m.ran[-2]
    assert m.ran[-1] == "'/etc/init.d/sshd' announce" and not any("reboot" in r for r in m.ran)
    m.ran.clear()
    assert A.announce_to_machine(m) == "already" and not any("remount" in r for r in m.ran)
    # a system with neither avahi nor python3 to answer with: the card is left as it was
    old = _Machine({"/etc/init.d/sshd": b"old"}, avahi=False)
    assert A.announce_to_machine(old) == "none" and old.files == {"/etc/init.d/sshd": b"old"}
    # a file that did not arrive as sent changes nothing
    bad = _Machine({"/etc/init.d/sshd": b"old"})
    bad.corrupt = True
    with pytest.raises(ExtrasError, match="did not arrive"):
        A.announce_to_machine(bad)
    assert bad.files == {"/etc/init.d/sshd": b"old"} and "remount,ro" in bad.ran[-1]
    with pytest.raises(ExtrasError, match="no remote access start script"):
        A.announce_to_machine(_Machine({}))
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "shell.js").read_text(encoding="utf-8")
    assert 'call("shellx.machines_announce_on", n.address)' in js and "MACH.says" in js
