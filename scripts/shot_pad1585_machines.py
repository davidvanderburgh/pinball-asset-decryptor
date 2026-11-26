"""PAD-1585 capture: My machines as its own page (header button) - empty and with machines.

    python scripts/shot_pad1585_machines.py --out <dir> --prefix before_|after_

A scratch settings folder (never David's real one), with two machines Remote access "found on the network"
(remote_access/machines.json) and the project + stub game-code page of shot_pad1585.py. Two screens:

* <prefix>machines_empty.png - no machine added yet;
* <prefix>machines_list.png  - two library cards added, the daily check on (the stub lists Godzilla LE 1.17).

A build with the header's My machines button opens its page; one without it shows the picker, where My machines
used to sit.
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
import shot_pad1585 as base  # noqa: E402

NETWORK = {"current": "192.168.1.42", "machines": [
    {"address": "192.168.1.42", "host_key": None, "game": "godzilla_le"},
    {"address": "192.168.1.57", "host_key": None, "game": "jaws_pro"}]}


def _shoot(out, prefix, name, add_cards, width, height):
    scratch = tempfile.mkdtemp(prefix="padshot1585m-")
    proj = base._project(scratch)
    settings = os.path.join(scratch, "seed.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "machine_code_watch": bool(add_cards),
                   "projects": [{"folder": proj, "manufacturer": "stern",
                                 "last_opened": "2026-10-27T10:00:00"}]}, f)
    net = os.path.join(scratch, "cfg", "pinball_decryptor", "remote_access")
    os.makedirs(net, exist_ok=True)
    with open(os.path.join(net, "machines.json"), "w", encoding="utf-8") as f:
        json.dump(NETWORK, f)
    stub = base._stub_server()
    env = {"PAD_CODE_WATCH_URL": "http://127.0.0.1:%d/support/game-code/" % stub.server_address[1],
           # the lights: the Godzilla answers, the Jaws Pro does not (a capture has no machine to ask)
           "PAD_SHOT_ONLINE": "192.168.1.42"}
    if os.environ.get("APPDATA"):
        env["PYTHONUSERBASE"] = os.path.join(os.environ["APPDATA"], "Python")
    proc, url = ws.start_server(settings, scratch, extra_env=env)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            for _ in range(240):
                if "stern" in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                    break
                time.sleep(0.5)
            if add_cards:
                for card, label in ((base.STOCK, "Basement Godzilla"), (base.CUSTOM, "Godzilla at Dave's")):
                    print("add", ws.api(url, "shellx.machines_add", card, label))
                for _ in range(60):
                    rows = (ws.state(url)["shellx"].get("machines") or {}).get("rows") or []
                    if any(r.get("newer") for r in rows):
                        break
                    time.sleep(0.5)
            btn = page.locator("button.sx-mach-open")
            if btn.count():
                btn.first.click()
                print(name, ": the header's My machines button opened its page")
            else:
                print(name, ": no My machines button in this build - the picker, where it sat")
            for _ in range(40):                         # the lights: the page checks when it opens
                if ((ws.state(url).get("shellx") or {}).get("machines") or {}).get("online"):
                    break
                time.sleep(0.25)
            time.sleep(1.5)
            st = (ws.state(url).get("shellx") or {}).get("machines") or {}
            print(json.dumps({k: st.get(k) for k in ("open", "network", "newer_count", "online")}, default=str)[:600])
            page.screenshot(path=os.path.join(out, prefix + name + ".png"))
            browser.close()
    finally:
        proc.kill()
        stub.shutdown()
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--width", type=int, default=1360)
    ap.add_argument("--height", type=int, default=900)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print("REPO", REPO)
    _shoot(a.out, a.prefix, "machines_empty", False, a.width, a.height)
    _shoot(a.out, a.prefix, "machines_list", True, a.width, a.height)
    return 0


if __name__ == "__main__":
    sys.exit(main())
