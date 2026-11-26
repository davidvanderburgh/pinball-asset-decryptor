"""The Scan… button beside "Wi-Fi for the test card" (core/wifi_scan.py). Simon (2026-11-26): "if the PC or machine PAD
is running on has a wireless facility to scan for access points then ideally we should let them do that ... make sure
they can still manually enter tho". Readers of each tool's output, with made-up networks."""
import os

from pinball_decryptor.core import wifi_scan as WS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NETSH = """
Interface name : WiFi
There are 3 networks currently visible.

SSID 1 : Home Net
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : aa:bb:cc:dd:ee:01
         Signal             : 60%
         Radio type         : 802.11n
         Band               : 2.4 GHz
         Channel            : 6
    BSSID 2                 : aa:bb:cc:dd:ee:02
         Signal             : 88%
         Radio type         : 802.11ac
         Band               : 5 GHz
         Channel            : 44

SSID 2 : Cafe
    Network type            : Infrastructure
    Authentication          : Open
    Encryption              : None
    BSSID 1                 : aa:bb:cc:dd:ee:03
         Signal             : 30%
         Channel            : 11

SSID 3 :
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    BSSID 1                 : aa:bb:cc:dd:ee:04
         Signal             : 99%
         Channel            : 1
"""
# the same, as a German Windows words it: only the labels change
NETSH_DE = NETSH.replace("Signal             :", "Signal             :").replace("Channel", "Kanal").replace(
    "Authentication", "Authentifizierung")
IFACES = """
    Name                   : WiFi
    State                  : connected
    SSID                   : Home Net
    BSSID                  : aa:bb:cc:dd:ee:02
"""


def test_windows_netsh():
    rows, current = WS.parse_netsh(NETSH, IFACES)
    nets = WS._merge(rows)
    assert [n["name"] for n in nets] == ["Home Net", "Cafe"], "the strongest first; a hidden network left out"
    home = nets[0]
    assert home["signal"] == 88 and home["band"] in ("2.4 + 5 GHz", "2.4 GHz") and home["secure"] is True
    assert nets[1]["secure"] is False and nets[1]["band"] == "2.4 GHz"
    assert current == "Home Net"
    assert [n["name"] for n in WS._merge(WS.parse_netsh(NETSH_DE)[0])] == ["Home Net", "Cafe"], \
        "Windows in another language still reads"


def test_linux_nmcli():
    text = ("*:Home Net:88:5180 MHz:WPA2\n"
            " :Home Net:60:2437 MHz:WPA2\n"
            " :Cafe:30:2462 MHz:\n"
            " :Odd\\:Name:20:2412 MHz:WPA1 WPA2\n")
    rows, current = WS.parse_nmcli(text)
    nets = WS._merge(rows)
    assert current == "Home Net" and nets[0]["name"] == "Home Net" and nets[0]["band"] == "2.4 + 5 GHz"
    assert {n["name"] for n in nets} == {"Home Net", "Cafe", "Odd:Name"}
    assert next(n for n in nets if n["name"] == "Cafe")["secure"] is False


def test_the_machines_wpa_cli():
    text = ("PAD_WIFI_SCAN\n"
            "bssid / frequency / signal level / flags / ssid\n"
            "aa:bb:cc:dd:ee:01\t2437\t-52\t[WPA2-PSK-CCMP][ESS]\tHome Net\n"
            "aa:bb:cc:dd:ee:03\t2462\t-80\t[ESS]\tCafe\n"
            "aa:bb:cc:dd:ee:05\t2412\t-70\t[WPA2-PSK-CCMP][ESS]\tCaf\\xc3\\xa9 2\n"
            "ssid=Home Net\n")
    rows, current, running = WS.parse_wpa_cli(text)
    nets = WS._merge(rows)
    assert running and current == "Home Net"
    assert [n["name"] for n in nets] == ["Home Net", "Café 2", "Cafe"]
    assert nets[0]["signal"] == 96 and nets[0]["band"] == "2.4 GHz" and nets[0]["secure"] is True
    assert nets[2]["secure"] is False
    assert WS.parse_wpa_cli("PAD_WIFI_OFF\n") == ([], "", False)


def test_scan_machine_says_why_not():
    class M:
        def __init__(self, out):
            self.out = out

        def sh(self, script, timeout=600, check=True):
            assert "wpa_cli -p $d -i wlan0 scan_results" in script
            return 0, self.out

        def close(self):
            pass
    assert WS.scan_machine("")["why"] == WS.NO_MACHINE

    def refuse(address):
        raise OSError("no route")
    assert WS.scan_machine("192.168.1.9", connect=refuse)["why"] == WS.NO_MACHINE
    assert WS.scan_machine("192.168.1.9", connect=lambda a: M("PAD_WIFI_OFF\n"))["why"] == WS.MACHINE_OFF
    got = WS.scan_machine("192.168.1.9", connect=lambda a: M(
        "PAD_WIFI_SCAN\naa:bb:cc:dd:ee:01\t2437\t-60\t[WPA2-PSK-CCMP][ESS]\tHome Net\n"))
    assert got["ok"] and got["networks"][0]["name"] == "Home Net"


def test_the_tab_offers_both_and_still_takes_a_typed_name():
    src = open(os.path.join(ROOT, "pinball_decryptor", "webui", "tabs", "testcard.py"), encoding="utf-8").read()
    assert "@rpc(loop=False)\n    def scan_wifi(self, where):" in src
    js = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "core", "menu_wifi.js"),
              encoding="utf-8").read()
    assert 'label: "From this computer", onClick: () => doScan("pc")' in js
    assert 'label: "From the machine", onClick: () => doScan("machine")' in js
    assert 'placeholder="network name"' in js and "onChange=${setName}" in js        # typing still works
    assert "onPick=${(v) => { setName(v); setScan(null); }}" in js
