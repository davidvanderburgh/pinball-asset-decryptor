"""The Wi-Fi networks in reach, for the test card's "Wi-Fi for the test card" (core/menu_network.py).

Simon (2026-11-26): "if the PC or machine PAD is running on has a wireless facility to scan for access points then
ideally we should let them do that ... just makes it MUCH easier to be sure for the user they have selected the
correct point ... make sure they can still manually enter tho".  Two sources, each a list of
``{"name", "signal", "band", "secure"}`` (signal 0-100, band "2.4 GHz" / "5 GHz" / "", secure True/False/None), the
strongest first, one row per network name:

* this computer: Windows ``netsh wlan``, Linux ``nmcli``; the network it is joined to now is ``current``.
* the machine, over remote access (core/remote_send.py): its own wpa_supplicant's scan - what the machine itself
  can reach, which is the better answer (Stern's adapter driver sees 2.4 GHz only).  Only while something there runs
  wpa_supplicant: the game (or the test card's own network) brings it up.

Neither reads a password: the user still types it."""

import re
import subprocess
import sys

#: what each source answers with when it cannot scan
NO_PC_WIFI = "This computer has no Wi-Fi to scan with (or it is switched off)."
NO_PC_TOOL = "This computer cannot list Wi-Fi networks here; type the network name instead."
NO_MACHINE = "The machine is not reachable: find it on the Network tab first (remote access on, the game running)."
MACHINE_OFF = "The machine's Wi-Fi is not running just now (it starts with the game); type the network name instead."


def _band(mhz):
    try:
        mhz = int(mhz)
    except (TypeError, ValueError):
        return ""
    return "2.4 GHz" if 2400 <= mhz < 2500 else "5 GHz" if 4900 <= mhz < 5900 else "6 GHz" if mhz >= 5925 else ""


def _merge(rows):
    """One row per name (its strongest), the strongest first; hidden networks (no name) left out."""
    best = {}
    for r in rows:
        name = r.get("name") or ""
        if not name:
            continue
        have = best.get(name)
        if have is None or (r.get("signal") or 0) > (have.get("signal") or 0):
            best[name] = dict(r)
        elif r.get("band") and have.get("band") and r["band"] != have["band"]:
            have["band"] = "2.4 + 5 GHz"
    return sorted(best.values(), key=lambda r: (-(r.get("signal") or 0), r["name"].lower()))


def _run(argv, timeout=15):
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000                       # CREATE_NO_WINDOW
    p = subprocess.run(argv, capture_output=True, timeout=timeout, **kw)
    return p.returncode, p.stdout.decode("utf-8", "replace") if p.stdout else ""


# ---- this computer -------------------------------------------------------------------------------------------------
def parse_netsh(networks, interfaces=""):
    """``(rows, current)`` from ``netsh wlan show networks mode=bssid`` and ``netsh wlan show interfaces``.  Windows
    words its labels in its own language: only what does not change is read - "SSID n :", a "%" signal, a channel
    number on a line of its own after the signal, and the authentication / encryption values."""
    rows, cur = [], None
    for line in networks.splitlines():
        m = re.match(r"^SSID \d+\s*:\s?(.*)$", line.strip())
        if m:
            cur = {"name": m.group(1).strip(), "signal": 0, "band": "", "secure": None}
            rows.append(cur)
            continue
        if cur is None or ":" not in line:
            continue
        value = line.split(":", 1)[1].strip()
        if re.fullmatch(r"\d{1,3}%", value):
            cur["signal"] = max(cur["signal"], int(value[:-1]))
        elif re.fullmatch(r"\d{1,3}", value) and cur.get("_chan") is None and cur["signal"]:
            ch = int(value)
            cur["_chan"] = ch
            band = "2.4 GHz" if ch <= 14 else "5 GHz"
            cur["band"] = band if not cur["band"] or cur["band"] == band else "2.4 + 5 GHz"
        elif value in ("Open", "Open System"):
            cur["secure"] = False
        elif value.startswith(("WPA", "WEP")):
            cur["secure"] = True
    for r in rows:
        r.pop("_chan", None)
    current = ""
    for line in interfaces.splitlines():
        m = re.match(r"^\s*SSID\s*:\s?(.*)$", line)
        if m:
            current = m.group(1).strip()
            break
    return rows, current


def parse_nmcli(text):
    """``(rows, current)`` from ``nmcli -t -f IN-USE,SSID,SIGNAL,FREQ,SECURITY dev wifi list``."""
    rows, current = [], ""
    for line in text.splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) < 5:
            continue
        use, ssid, sig, freq, sec = (p.replace("\\:", ":") for p in parts[:5])
        name = ssid.strip()
        rows.append({"name": name, "signal": int(sig) if sig.isdigit() else 0,
                     "band": _band(re.sub(r"\D", "", freq)), "secure": bool(sec.strip() and sec.strip() != "--")})
        if use.strip() == "*":
            current = name
    return rows, current


def scan_pc():
    """``{"ok", "why", "networks", "current"}`` for this computer."""
    try:
        if sys.platform == "win32":
            rc, nets = _run(["netsh", "wlan", "show", "networks", "mode=bssid"])
            _rc, ifs = _run(["netsh", "wlan", "show", "interfaces"])
            rows, current = parse_netsh(nets, ifs)
            if rc != 0 and not rows:
                return {"ok": False, "why": NO_PC_WIFI, "networks": [], "current": ""}
        elif sys.platform.startswith("linux"):
            rc, text = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,FREQ,SECURITY", "dev", "wifi", "list"])
            if rc != 0:
                return {"ok": False, "why": NO_PC_WIFI, "networks": [], "current": ""}
            rows, current = parse_nmcli(text)
        else:
            return {"ok": False, "why": NO_PC_TOOL, "networks": [], "current": ""}
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "why": NO_PC_TOOL, "networks": [], "current": ""}
    nets = _merge(rows)
    if not nets:
        return {"ok": False, "why": NO_PC_WIFI, "networks": [], "current": current}
    return {"ok": True, "why": "", "networks": nets, "current": current}


# ---- the machine ---------------------------------------------------------------------------------------------------
#: asks the machine's running wpa_supplicant for a fresh scan, waits, and prints its results (busybox sh); the game's
#: control folder first, then the test card's own (menu_network)
MACHINE_SCRIPT = """
for d in /var/run/wpa_supplicant /var/run/padnet_wpa; do
    [ -S $d/wlan0 ] || continue
    wpa_cli -p $d -i wlan0 scan >/dev/null 2>&1
    sleep 4
    echo PAD_WIFI_SCAN
    wpa_cli -p $d -i wlan0 scan_results
    wpa_cli -p $d -i wlan0 status | grep '^ssid='
    exit 0
done
echo PAD_WIFI_OFF
"""


def _unescape(s):
    """wpa_cli prints a name's odd bytes as \\xNN."""
    try:
        return re.sub(rb"\\x([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]),
                      s.encode("latin-1", "replace")).decode("utf-8", "replace")
    except Exception:                                       # noqa: BLE001
        return s


def parse_wpa_cli(text):
    """``(rows, current, running)`` from :data:`MACHINE_SCRIPT`'s output."""
    if "PAD_WIFI_SCAN" not in text:
        return [], "", False
    rows, current = [], ""
    for line in text.split("PAD_WIFI_SCAN", 1)[1].splitlines():
        if line.startswith("ssid="):
            current = _unescape(line[5:].strip())
            continue
        parts = line.split("\t")
        if len(parts) < 4 or not re.fullmatch(r"[0-9a-f:]{17}", parts[0]):
            continue
        try:
            dbm = int(parts[2])
        except ValueError:
            dbm = -100
        flags = parts[3]
        rows.append({"name": _unescape(parts[4]) if len(parts) > 4 else "",
                     "signal": max(0, min(100, 2 * (dbm + 100))),     # -50 dBm and up = 100
                     "band": _band(parts[1]),
                     "secure": "WPA" in flags or "WEP" in flags})
    return rows, current, True


def scan_machine(address, connect=None):
    """``{"ok", "why", "networks", "current"}`` from the machine at *address*."""
    if not address:
        return {"ok": False, "why": NO_MACHINE, "networks": [], "current": ""}
    if connect is None:
        from .remote_send import connect
    try:
        machine = connect(address)
    except Exception:                                       # noqa: BLE001 - unreachable, refused, no key
        return {"ok": False, "why": NO_MACHINE, "networks": [], "current": ""}
    try:
        _rc, text = machine.sh(MACHINE_SCRIPT, timeout=30, check=False)
    except Exception:                                       # noqa: BLE001
        return {"ok": False, "why": NO_MACHINE, "networks": [], "current": ""}
    finally:
        try:
            machine.close()
        except Exception:                                   # noqa: BLE001
            pass
    rows, current, running = parse_wpa_cli(text or "")
    if not running:
        return {"ok": False, "why": MACHINE_OFF, "networks": [], "current": ""}
    return {"ok": True, "why": "", "networks": _merge(rows), "current": current}
