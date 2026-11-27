"""PAD-1627 capture: My machines with what remote access found on the network - a machine the owner named, and
an address typed in that nothing ever answered at.

    python scripts/shot_pad1627.py --out <dir> --prefix before_|after_

A scratch settings folder (never David's real one).  remote_access/machines.json holds an address only typed in
(no identity, no game) and a Godzilla that let this computer in, named "Godzilla Premium" by its owner; the
Godzilla answers (PAD_SHOT_ONLINE: a capture has no machine to ask).  One screen:

* <prefix>machines_network.png - no machine added yet, the two found on the network.

A build before PAD-1627 ignores the name, calls the typed address "A Stern machine" and has no Find my machines.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import webui_shot as ws  # noqa: E402

NETWORK = {"current": "192.168.1.64", "machines": [
    {"address": "192.168.1.50", "host_key": None, "game": ""},
    {"address": "192.168.1.64", "host_key": ["ssh-ed25519", "AAAAshot"], "game": "godzilla_le",
     "name": "Godzilla Premium", "announces": True}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--width", type=int, default=1360)
    ap.add_argument("--height", type=int, default=700)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print("REPO", REPO)
    scratch = tempfile.mkdtemp(prefix="padshot1627-")
    settings = os.path.join(scratch, "seed.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True}, f)
    net = os.path.join(scratch, "cfg", "pinball_decryptor", "remote_access")
    os.makedirs(net, exist_ok=True)
    with open(os.path.join(net, "machines.json"), "w", encoding="utf-8") as f:
        json.dump(NETWORK, f)
    env = {"PAD_SHOT_ONLINE": "192.168.1.64"}
    if os.environ.get("APPDATA"):
        env["PYTHONUSERBASE"] = os.path.join(os.environ["APPDATA"], "Python")
    proc, url = ws.start_server(settings, scratch, extra_env=env)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": a.width, "height": a.height})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            for _ in range(240):
                if "stern" in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                    break
                time.sleep(0.5)
            page.locator("button.sx-mach-open").first.click()
            for _ in range(40):                         # the lights: the page checks when it opens
                if ((ws.state(url).get("shellx") or {}).get("machines") or {}).get("online"):
                    break
                time.sleep(0.25)
            time.sleep(1.5)
            st = (ws.state(url).get("shellx") or {}).get("machines") or {}
            print(json.dumps({k: st.get(k) for k in ("network", "online", "find_note")}, default=str))
            page.screenshot(path=os.path.join(a.out, a.prefix + "machines_network.png"))
            browser.close()
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
