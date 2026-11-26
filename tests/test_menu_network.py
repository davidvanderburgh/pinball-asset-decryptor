"""The boot menu and the test card on the network with no game running (Simon, 2026-11-26; core/menu_network.py).

Stern's game keeps the Wi-Fi name and password to itself (it hands them to wpa_supplicant with ADD_NETWORK /
SET_NETWORK and never writes them to a file), so a test card or a multi-boot card in its menu was off the network
until a game started. Simon chose "Type it into PAD": the Test card tab takes the network's name and password, PAD
keeps the name and the WPA key only, and the card gets /etc/init.d/padnet, which select.sh starts before the menu and
stops when a game is chosen."""
import hashlib
import os
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.core import menu_network as MN
from pinball_decryptor.webui import testcard_core as tc

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SELECT = os.path.join(ROOT, "tools", "spike2_emu", "codeselect", "select.sh")
CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_TESTCARD_STORE", str(tmp_path / "store" / "testcard.json"))
    tc._SHARED[:] = []
    yield
    tc._SHARED[:] = []


def test_the_key_is_wpa_supplicants_own():
    # wpa_passphrase "IEEE" "password" (the 802.11i test vector)
    assert MN.wifi_key("IEEE", "password") == "f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e"
    assert MN.wifi_key("open net", "") == ""


def test_the_wifi_is_checked_in_the_users_words():
    assert MN.check_wifi("Home", "longenough") == ""
    assert MN.check_wifi("Home", "") == ""                              # an open network
    assert "1 to 32" in MN.check_wifi("", "x" * 8) and "1 to 32" in MN.check_wifi("x" * 33, "x" * 8)
    assert "8 to 63" in MN.check_wifi("Home", "short") and "8 to 63" in MN.check_wifi("Home", "x" * 64)


def test_the_cards_wifi_file_holds_the_key_not_the_password():
    key = MN.wifi_key("My Wi-Fi", "s3cret-pass")
    text = MN.wpa_conf("My Wi-Fi", key).decode()
    assert "s3cret" not in text and "psk=%s" % key in text
    assert "ssid=%s" % "My Wi-Fi".encode().hex() in text               # any name, no quoting
    assert "ctrl_interface=/var/run/padnet_wpa" in text                # never the game's own control folder
    assert "key_mgmt=NONE" in MN.wpa_conf("Cafe", "").decode()
    with pytest.raises(Exception):
        MN.wpa_conf("Home", "not-a-key")


def test_the_start_up_script():
    s = MN.SCRIPT.decode()
    assert s.startswith("#!/bin/sh\n")
    assert "udhcpc -b -R -p $RUN/eth0.pid -i eth0 -H stern-spike2" in s           # the wired port, by DHCP
    assert "wpa_supplicant -B -P $RUN/wpa.pid -i wlan0 -c $CONF -D nl80211,wext" in s
    assert "[ -s $CONF ] || return 0" in s                                          # Wi-Fi only when given
    assert "ip addr flush dev $i" in s and "ip link set $i down" in s               # stop leaves it to the game
    bash = shutil.which("bash") or shutil.which("sh")
    if bash and os.name != "nt":                    # Windows' bash.exe is WSL's launcher: it cannot take this path
        p = os.path.join(os.environ.get("TMP", "/tmp"), "padnet_syntax.sh")
        open(p, "wb").write(MN.SCRIPT)
        assert subprocess.run([bash, "-n", p]).returncode == 0
    want = MN._wanted({"wifi_name": "Home", "wifi_key": "a" * 64})
    assert want[MN.INIT][1] == 0o755 and want[MN.WPA][1] == 0o600
    assert MN.WPA not in MN._wanted({"wifi_name": "", "wifi_key": ""})


def test_select_sh_starts_it_before_the_menu_and_stops_it_for_the_game():
    s = open(SELECT, encoding="utf-8").read()
    start = s.index('"$PADNET" start >/dev/null 2>&1 &')
    menu = s.index('"$BIN" --conf "$CONF" --out "$OUT"')
    stop = s.index('"$PADNET" stop >/dev/null 2>&1')
    assert start < menu < stop
    assert 'kill "$PADNET_PID" 2>/dev/null' in s[menu:stop + 40]
    assert s.index("PADNET=/etc/init.d/padnet") < start


def _tab():
    from pinball_decryptor.webui.tabs.testcard import TestCardTab

    class W:
        def service(self, name):
            return None
    t = TestCardTab.__new__(TestCardTab)
    t.window = W()
    t.state = {}
    t.set = lambda **kw: t.state.update(kw)
    t._lines, t._busy, t._pct, t._step, t._msg, t._cancel, t._proc = [], False, None, "", ("", ""), False, None
    t._address = lambda: ""
    return t


def test_the_tab_keeps_the_name_and_key_and_never_shows_the_key(monkeypatch):
    tab = _tab()
    assert "8 to 63" in tab.set_menu_wifi("Home", "short")
    assert tab.set_menu_wifi("Home", "a-good-password") == ""
    n = tc.shared().network
    assert n["wifi_name"] == "Home" and n["wifi_key"] == MN.wifi_key("Home", "a-good-password")
    assert "a-good-password" not in open(tc.store_path(), encoding="utf-8").read()
    assert tab.set_menu_wifi("", "") == "" and tc.shared().network["wifi_name"] == ""
    with pytest.raises(Exception):
        tab.set_network("wifi_key", "f" * 64)                          # only set_menu_wifi sets them
    src = open(os.path.join(ROOT, "pinball_decryptor", "webui", "tabs", "testcard.py"), encoding="utf-8").read()
    assert 'network={k: v for k, v in lst.network.items() if k != "wifi_key"}' in src


def test_clean_network_takes_only_a_real_key():
    good = tc.clean_network({"wifi_name": "Home", "wifi_key": "b" * 64})
    assert (good["wifi_name"], good["wifi_key"]) == ("Home", "b" * 64)
    assert tc.clean_network({"wifi_name": "Home", "wifi_key": "password"})["wifi_name"] == ""
    assert tc.clean_network({"wifi_name": "x" * 40, "wifi_key": ""})["wifi_name"] == ""


def test_the_build_adds_it_with_remote_access(tmp_path, monkeypatch):
    from pinball_decryptor.webui import multiboot_core as mbc
    from pinball_decryptor.core import card_extras, ssh_card
    seen = []

    def fake(form, out, media, cwd=None, test_specs=None, p3_mib=0):
        with open(out, "wb") as f:
            f.truncate(1 << 20)
        return [("testcard", [sys.executable, "-c", "print('built')"])]

    monkeypatch.setattr(mbc, "testcard_commands", fake)
    monkeypatch.setattr(ssh_card, "apply_to_build", lambda *a, **k: seen.append("ssh") or "ssh on")
    monkeypatch.setattr(MN, "apply_to_build", lambda o, out, cfg, **k: seen.append(("net", cfg)) or "net on")
    monkeypatch.setattr(card_extras, "with_pad_key", lambda text: "ssh-ed25519 AAAA pad")
    monkeypatch.setattr(card_extras, "validate_keys", lambda text: text)
    src = str(tmp_path / "stock.raw")
    open(src, "wb").write(b"x")
    tab = _tab()
    net = dict(tc.NETWORK_DEFAULTS, ssh=True, wifi_name="Home", wifi_key="c" * 64)
    tab._run(src, str(tmp_path / "t.raw"), [], net)
    assert tab.state["msg"][0] == "ok", tab.state["msg"]
    assert seen == ["ssh", ("net", {"wifi_name": "Home", "wifi_key": "c" * 64})]
    seen.clear()
    tab._run(src, str(tmp_path / "t2.raw"), [], dict(tc.NETWORK_DEFAULTS))
    assert seen == [], "no remote access, no menu network"


def test_it_goes_on_godzilla_116s_system_partition(tmp_path):
    """The real thing: the stock card's system partition copied out, changed with debugfs, read back."""
    if not os.path.isfile(LE116):
        pytest.skip("no Godzilla LE 1.16 card here")
    from pinball_decryptor.core import ssh_card
    from pinball_decryptor.plugins.stern.ext4 import Ext4Reader
    with open(LE116, "rb") as f:
        p2 = next(p for p in ssh_card._partitions(f) if p[0] == 2 and p[1] == 0x83)
        f.seek(p2[2])
        part = tmp_path / "p2.img"
        with open(part, "wb") as out:
            left = p2[3]
            while left:
                b = f.read(min(left, 8 << 20))
                out.write(b)
                left -= len(b)
    work = tmp_path / "work"
    work.mkdir()
    cfg = {"wifi_name": "Home", "wifi_key": MN.wifi_key("Home", "a-good-password")}
    try:
        MN.prepare_rootfs(part, work, cfg)
    except Exception as e:                                  # noqa: BLE001
        if "debugfs" in str(e) or "e2fsck" in str(e):
            pytest.skip("no debugfs/e2fsck here: %s" % e)
        raise
    with open(part, "rb") as f:
        r = Ext4Reader(f, 0, part.stat().st_size)
        assert MN._read(r, MN.INIT, 1 << 20) == MN.SCRIPT
        assert MN._read(r, MN.WPA, 4096) == MN.wpa_conf("Home", cfg["wifi_key"])
        assert ssh_card._node(r, MN.WPA)["mode"] & 0o777 == 0o600
    MN.prepare_rootfs(part, work, {"wifi_name": "", "wifi_key": ""})    # Forget: the Wi-Fi file goes
    with open(part, "rb") as f:
        r = Ext4Reader(f, 0, part.stat().st_size)
        assert ssh_card._node(r, MN.WPA) is None and MN._read(r, MN.INIT, 1 << 20) == MN.SCRIPT
    assert hashlib.md5(MN.SCRIPT).hexdigest()
