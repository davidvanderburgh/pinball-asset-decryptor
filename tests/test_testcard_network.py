"""Simon (2026-11-22): a PAD test card updated over the network.

"we need the same feature on the test card... even more important".  The card stays small so it writes
fast; "Allow additional space on the test card for network updates?" gives its test files partition more
room ("the user can make it whatever size they want, completely unfettered"); Remote access and Wi-Fi
start-up go on it as the Network tab puts them on a game card; Send to machine builds it and sends it with
the app's own Send.  A test card is only ever sent to a machine already running one: a full Send makes
/games the image's, so a game card's game would be deleted."""

import os
import sys
import types

import pytest

from pinball_decryptor.webui import testcard_core as tc

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu")


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_TESTCARD_STORE", str(tmp_path / "store" / "testcard.json"))
    monkeypatch.setenv("PAD_MENU_WIFI_STORE", str(tmp_path / "store" / "menu_wifi.json"))
    tc._SHARED[:] = []
    yield
    tc._SHARED[:] = []


# ---- the settings --------------------------------------------------------------------------

def test_the_network_settings_are_kept_and_cleaned(tmp_path):
    lst = tc.TestCardList()
    assert lst.network == tc.NETWORK_DEFAULTS and tc.room_mib(lst.network) == 0
    lst.network = tc.clean_network({"room": True, "room_gb": 30, "ssh": True, "wifi": "yes", "band5": True})
    lst.save()
    again = tc.TestCardList()
    assert again.network["room"] is True and again.network["room_gb"] == 30
    assert again.network["ssh"] is True and again.network["wifi"] is False, "only a real yes/no counts"
    assert tc.room_mib(again.network) == 30 * 1024, "any size: 30 GB if that is what is asked for"
    assert tc.clean_network({"room": True, "room_gb": -1})["room_gb"] == tc.ROOM_GB_DEFAULT
    assert tc.room_mib({"room": False, "room_gb": 5}) == 0


def test_the_card_builder_makes_the_test_files_partition_as_big_as_asked(tmp_path):
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard as mk
    geom = types.SimpleNamespace(part=lambda n: {1: (0x0c, 8192, 16384), 2: (0x83, 24576, 688128)}[n])
    prims, _ext, _n, _logs, total = mk.testcard_layout(geom, 2048)
    assert prims[2][2] * 512 == 2048 << 20
    small = mk.testcard_layout(geom, mk.testcard_p3_mib(0))[4]
    assert total - small == (2048 - mk.TESTCARD_P3_MIB) << 20, "only p3 grows: data and dump stay as they were"
    src = open(os.path.join(RIG, "mkmulticard.py"), encoding="utf-8").read()
    assert 'p3_mib = max(testcard_p3_mib(media["test_bytes"] if media else 0), int(p3_mib or 0))' in src
    assert 's.add_argument("--p3-mib", type=int, default=0,' in src
    assert "build_testcard(a.primary, a.out, a.selector_dir, a.media_dir,\n" \
           "                           parse_testcard_colour(a.color), a.workdir, p3_mib=a.p3_mib)" in src


def test_the_build_command_asks_for_the_room():
    from pinball_decryptor.webui import multiboot_core as mbc
    form = types.SimpleNamespace(images=[types.SimpleNamespace(path="/x/stock.raw")], volume=50,
                                 selector_dir="~/sel", tests=[], platform="stern", colour_profiles={})
    flat = lambda cmds: " ".join(str(c) for _l, c in cmds)                     # noqa: E731
    with_room = flat(mbc.testcard_commands(form, "/x/t.raw", "/x/m", test_specs=[], p3_mib=2048))
    without = flat(mbc.testcard_commands(form, "/x/t.raw", "/x/m", test_specs=[]))
    assert "--p3-mib" in with_room and "2048" in with_room
    assert "--p3-mib" not in without


# ---- the tab -------------------------------------------------------------------------------

class _Window(object):
    def __init__(self, send=None):
        self.cb = {"on_send_image": send} if send else {}
        self.current_mfr = None

    def service(self, name):
        raise KeyError(name)


def _tab(send=None, address="192.168.1.50"):
    from pinball_decryptor.webui.tabs.testcard import TestCardTab
    tab = TestCardTab.__new__(TestCardTab)
    tab.window = _Window(send)
    tab.state = {}
    tab.set = lambda **kw: tab.state.update(kw)
    tab._busy, tab._cancel, tab._proc, tab._lines = False, False, None, []
    tab._pct, tab._step, tab._msg = None, "", ("", "")
    tab._address = lambda: address
    return tab


def test_set_network_saves_and_publishes():
    tab = _tab()
    tab.set_network("room", True)
    tab.set_network("room_gb", 4)
    tab.set_network("wifi", True)
    tab.set_network("band5", True)
    tab.set_network("wifi", False)
    n = tc.shared().network
    assert n["room"] and n["room_gb"] == 4 and n["wifi"] is False and n["band5"] is False, \
        "5 GHz goes off with Wi-Fi"
    assert tab.state["network"] == dict(n, wifi_name="") and tab.state["room_mib"] == 4096   # + the saved Wi-Fi's name and tab.state["address"] == "192.168.1.50"


def test_the_build_asks_for_the_room_and_adds_remote_access(tmp_path, monkeypatch):
    from pinball_decryptor.webui import multiboot_core as mbc
    from pinball_decryptor.core import card_extras, ssh_card
    seen = {}

    def fake(form, out, media, cwd=None, test_specs=None, p3_mib=0):
        seen["p3"] = p3_mib
        with open(out, "wb") as f:
            f.truncate(1 << 20)
        return [("testcard", [sys.executable, "-c", "print('built')"])]

    def apply(original, output, config, log=None, cancel=None):
        seen["ssh"] = (original, output, config)
        assert os.path.exists(str(ssh_card.pending_marker(output))), "the image is marked unfinished meanwhile"
        return "remote access on"

    monkeypatch.setattr(mbc, "testcard_commands", fake)
    monkeypatch.setattr(ssh_card, "apply_to_build", apply)
    from pinball_decryptor.core import menu_network            # 2026-11-26: the menu network goes on with it
    monkeypatch.setattr(menu_network, "apply_to_build", lambda *a, **k: "menu network on")
    monkeypatch.setattr(card_extras, "with_pad_key", lambda text: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPAD pad")
    monkeypatch.setattr(card_extras, "validate_keys", lambda text: text)   # the key is a stand-in
    src = str(tmp_path / "stock.raw")
    open(src, "wb").write(b"x")
    out = str(tmp_path / "test.raw")
    tab = _tab()
    tab._run(src, out, [], {"room": True, "room_gb": 2, "ssh": True, "wifi": False, "band5": False})
    assert tab.state["msg"][0] == "ok", tab.state["msg"]
    assert seen["p3"] == 2048
    assert seen["ssh"][0] == src and seen["ssh"][1] == out
    assert seen["ssh"][2]["enabled"] is True and "AAAAIPAD" in seen["ssh"][2]["public_keys"]
    assert not os.path.exists(str(ssh_card.pending_marker(out))), "finished: the marker goes"


def test_a_failed_remote_access_leaves_the_card_marked_unfinished(tmp_path, monkeypatch):
    from pinball_decryptor.webui import multiboot_core as mbc
    from pinball_decryptor.core import ssh_card

    def fake(form, out, media, cwd=None, test_specs=None, p3_mib=0):
        open(out, "wb").write(b"x")
        return [("testcard", [sys.executable, "-c", "print('built')"])]

    def boom(*a, **k):
        raise ssh_card.ExtrasError("not a card remote access can go on")

    monkeypatch.setattr(mbc, "testcard_commands", fake)
    monkeypatch.setattr(ssh_card, "apply_to_build", boom)
    src = str(tmp_path / "stock.raw")
    open(src, "wb").write(b"x")
    out = str(tmp_path / "test.raw")
    tab = _tab()
    tab._run(src, out, [], {"ssh": True})
    assert tab.state["msg"][0] == "bad" and "remote access could not be added" in tab.state["msg"][1]
    assert os.path.exists(str(ssh_card.pending_marker(out))), "Send and flashing refuse it"
    # the next build, without remote access or Wi-Fi, writes the card afresh: the old marker goes with it
    monkeypatch.setattr(ssh_card, "apply_to_build", lambda *a, **k: pytest.fail("remote access is off"))
    tab = _tab()
    tab._run(src, out, [], {"ssh": False, "wifi": False})
    assert tab.state["msg"][0] == "ok", tab.state["msg"]
    assert not os.path.exists(str(ssh_card.pending_marker(out))), "a good card is not refused as unfinished"


def test_send_needs_remote_access_and_the_machine(monkeypatch):
    from pinball_decryptor.webui.rpc import RpcError
    tab = _tab(send=lambda *a: None)
    lst = tc.shared()
    lst.source = __file__
    with pytest.raises(RpcError, match="Remote access"):
        tab.send()
    lst.network = tc.clean_network({"ssh": True})
    tab._address = lambda: ""
    with pytest.raises(RpcError, match="Network tab"):
        tab.send()


def test_send_builds_then_hands_the_card_to_the_apps_send(tmp_path, monkeypatch):
    from pinball_decryptor.webui import compat
    sent = []
    from pinball_decryptor.core import remote_send as rs
    tab = _tab(send=lambda path, address: sent.append((path, address)))
    lst = tc.shared()
    lst.network = tc.clean_network({"ssh": True})
    asked = []
    monkeypatch.setattr(rs, "connect", lambda address: _Machine("PAD_TESTCARD\n"))
    monkeypatch.setattr(compat.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True)
    monkeypatch.setattr(tab, "build", lambda send_to="", out="": sent.append(("build", send_to)) or True)
    assert tab.send() is True
    assert sent == [("build", "192.168.1.50")]
    assert "The machine runs a PAD test card" in asked[0][1]
    # ...and once built, the app's own Send takes it (the Network tab's)
    sent[:] = []
    tab._send_to = "192.168.1.50"
    out = str(tmp_path / "t.raw")
    open(out, "wb").write(b"x")
    tab._finish(True, "", out)
    assert sent == [(out, "192.168.1.50")] and "Sending it to the machine" in tab.state["msg"][1]


def test_send_may_replace_a_multiboot_card_when_asked(tmp_path, monkeypatch):
    """Simon (2026-11-26): "create a card which is only a test card no multiboot (over the network)" - a machine
    running a PAD multi-boot card is asked about by name (its games are deleted), and the Send is told it may
    replace it; a one-game card is still refused before anything is built."""
    from pinball_decryptor.core import remote_send as rs
    from pinball_decryptor.webui import compat
    from pinball_decryptor.webui.rpc import RpcError
    sent = []
    tab = _tab(send=lambda path, address, **kw: sent.append((path, address, kw)))
    lst = tc.shared()
    lst.network = tc.clean_network({"ssh": True})
    asked = []
    monkeypatch.setattr(rs, "connect", lambda address: _Machine("PAD_MENU_CARD\n"))
    monkeypatch.setattr(compat.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True)
    monkeypatch.setattr(tab, "build", lambda send_to="", out="": sent.append(("build", send_to)) or True)
    assert tab.send() is True
    assert "Replace the multi-boot card" in asked[0][1] and "every game on it are deleted" in asked[0][1]
    sent[:] = []
    tab._send_to = "192.168.1.50"
    out = str(tmp_path / "t.raw")
    open(out, "wb").write(b"x")
    tab._finish(True, "", out)
    assert sent == [(out, "192.168.1.50", {"replace_menu_card": True})]
    # said no: nothing built
    asked[:], sent[:] = [], []
    monkeypatch.setattr(compat.messagebox, "askyesno", lambda *a, **k: asked.append(a) and False)
    assert tab.send() is False and sent == []
    # a one-game card: refused, nothing asked
    monkeypatch.setattr(rs, "connect", lambda address: _Machine(""))
    with pytest.raises(RpcError, match="its game would be deleted"):
        tab.send()


def test_send_takes_the_card_already_built_when_nothing_changed(tmp_path, monkeypatch):
    """Simon (2026-11-27): "if I "build" the card... it asks me to save it. If I send the card it also asks me to save
    it.. Seems that Sending doesn't check to see if it is already built?" - a card built from what the list holds now
    goes as it is (no build, no Save As); anything changed since and it is built again over the same file, still
    without asking where."""
    from pinball_decryptor.core import remote_send as rs
    from pinball_decryptor.webui import compat
    sent, asked, built = [], [], []
    tab = _tab(send=lambda path, address: sent.append((path, address)))
    lst = tc.shared()
    src = tmp_path / "stock.raw"
    src.write_bytes(b"stock")
    lst.source = str(src)
    lst.network = tc.clean_network({"ssh": True})
    out = str(tmp_path / "pad_test_card.raw")
    open(out, "wb").write(b"card")
    lst.out = out
    lst.save()
    tc.note_built(lst, out, tc.build_signature(lst))
    assert tc.built_card(lst) == out
    monkeypatch.setattr(rs, "connect", lambda address: _Machine("PAD_TESTCARD\n"))
    monkeypatch.setattr(compat.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True)
    monkeypatch.setattr(compat.filedialog, "asksaveasfilename", lambda **k: pytest.fail("no Save As on a Send"))
    monkeypatch.setattr(tab, "build", lambda send_to="", out="": built.append((send_to, out)) or True)
    assert tab.send() is True
    assert built == [] and sent == [(out, "192.168.1.50")]
    assert "goes as it is: nothing in the list has changed" in asked[0][1]
    # the network settings changed: built again, over the same file, not asked where
    sent[:], asked[:] = [], []
    lst.network = tc.clean_network({"ssh": True, "room": True})
    lst.save()
    assert tc.built_card(lst) == ""
    assert tab.send() is True
    assert built == [("192.168.1.50", out)] and sent == []
    assert "built first, as %s (replacing that file)" % out in asked[0][1]
    # the file on disk changed since (another program, a half-finished build): not taken as it is
    lst.network = tc.clean_network({"ssh": True})
    lst.save()
    assert tc.built_card(lst) == out
    open(out, "ab").write(b"more")
    assert tc.built_card(lst) == ""


def test_a_finished_build_is_remembered_for_send(tmp_path):
    tab = _tab(send=lambda *a: None)
    lst = tc.shared()
    src = tmp_path / "stock.raw"
    src.write_bytes(b"stock")
    lst.source = str(src)
    lst.save()
    out = str(tmp_path / "t.raw")
    open(out, "wb").write(b"x")
    tab._build_sig = tc.build_signature(lst)
    tab._finish(True, "", out)
    assert tc.built_card(tc.TestCardList()) == out, "kept in the list's file"
    tab._build_sig = tc.build_signature(lst)
    tab._finish(False, "boom", out)
    assert tc.TestCardList().built["out"] == out, "a failed build is not remembered"


def test_a_plain_build_does_not_send(tmp_path):
    sent = []
    tab = _tab(send=lambda *a: sent.append(a))
    out = str(tmp_path / "t.raw")
    open(out, "wb").write(b"x")
    tab._finish(True, "", out)
    assert sent == [] and tab.state["msg"][0] == "ok" and "Test card built" in tab.state["msg"][1]


# ---- the Send's guard ----------------------------------------------------------------------

def _target(conf):
    from pinball_decryptor.core import remote_send as rs
    node = {"bytes": conf}
    reader = types.SimpleNamespace(read_file_bytes=lambda n: n["bytes"])
    entries = {} if conf is None else {rs.TESTCARD_CONF: ("file", node, None)}
    return types.SimpleNamespace(trees={rs.ROOT: types.SimpleNamespace(entries=entries, reader=reader)})


class _Machine(object):
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def sh(self, script, stdin=b"", timeout=600, check=True):
        self.asked.append(script)
        return 0, self.answer

    def close(self):
        pass


def test_a_test_card_goes_only_to_a_machine_running_one():
    from pinball_decryptor.core import remote_send as rs
    card = _target(b"image=/dev/mmcblk0p3|TEST CARD|x\ndefault=0\ntestcard=on\nfont=/f.ttf\n")
    game = _target(b"image=/dev/mmcblk0p3|GODZILLA|x\nimage=/dev/mmcblk0p7|HEISEI|y\n")
    assert not rs.is_test_card(_target(None)), "a card with no boot menu is a game card"
    assert rs.is_test_card(card) and not rs.is_test_card(game)
    rs.check_test_card_target(card, _Machine("PAD_TESTCARD\n"))
    with pytest.raises(rs.SendError, match="its game would be deleted"):
        rs.check_test_card_target(card, _Machine(""))
    m = _Machine("")
    rs.check_test_card_target(game, m)
    assert m.asked == [], "a game card's Send is not asked anything new"
    # Simon (2026-11-26): a PAD multi-boot card is replaced only when the user was asked
    with pytest.raises(rs.SendError, match="asks before it replaces the multi-boot card"):
        rs.check_test_card_target(card, _Machine("PAD_MENU_CARD\n"))
    rs.check_test_card_target(card, _Machine("PAD_MENU_CARD\n"), replace_menu_card=True)
    with pytest.raises(rs.SendError, match="its game would be deleted"):
        rs.check_test_card_target(card, _Machine(""), replace_menu_card=True)
    assert rs.machine_card_kind(_Machine("PAD_TESTCARD\n")) == "testcard"
    assert rs.machine_card_kind(_Machine("PAD_MENU_CARD\n")) == "menu"
    assert rs.machine_card_kind(_Machine("")) == "game"
    src = open(rs.__file__, encoding="utf-8").read()
    assert ("check_layout(target, machine.layout())\n        check_test_card_target(target, machine, replace_menu_card)"
            in src)


def test_the_send_run_carries_the_permission(monkeypatch):
    from pinball_decryptor.core import remote_send as rs
    got = []
    m = _Machine("")
    monkeypatch.setattr(rs, "send_image", lambda image, machine, log, progress, cancel, replace_menu_card=False:
                        got.append(replace_menu_card) or "sent")
    for flag in (False, True):
        out = {}
        rs.SendPipeline("t.raw", "192.168.1.50", lambda *a: None, lambda i: None, lambda *a: None,
                        lambda ok, summary: out.update(ok=ok), connect_fn=lambda a: m,
                        replace_menu_card=flag).run()
        assert out["ok"] is True
    assert got == [False, True]
    app = open(os.path.join(os.path.dirname(HERE), "pinball_decryptor", "app.py"), encoding="utf-8").read()
    assert "backup_keep=keep, replace_menu_card=replace_menu_card)" in app


def test_the_page_offers_it():
    js = open(os.path.join(os.path.dirname(HERE), "pinball_decryptor", "webui", "static", "js", "tabs",
                           "testcard.js"), encoding="utf-8").read()
    assert "Allow additional space on the test card for network updates?" in js
    assert 'call("testcard.set_network", "ssh", v)' in js and 'call("testcard.set_network", "wifi", v)' in js
    assert 'call("testcard.send")' in js and "Send to machine…" in js


def test_the_build_log_takes_the_card_helpers_level():
    """Simon (2026-11-26): Send to machine stopped at "remote access could not be added: TestCardTab._say() takes 2
    positional arguments but 3 were given" - ssh_card, menu_network and wifi_card log (text, level)."""
    tab = _tab()
    tab._say("SSH server enabled (key-only, port 22).", "info")
    tab._say("a plain line")
    assert tab._lines[-2:] == ["SSH server enabled (key-only, port 22).", "a plain line"]
