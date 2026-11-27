"""PAD-1632 capture: My machines with a machine's Remote panel open (its screen, status, logs, settings, restart).

    python scripts/shot_pad1632.py --out <dir> --prefix before_|after_ [--address 192.168.4.166]

Unlike the other captures this one reads a REAL machine: a copy of this computer's own settings and remote access
records (its key, the machines it knows) goes into a scratch settings folder, deleted afterwards, and the machine
at --address is asked for its status and one picture of its screen. Both only read; nothing on the machine or in
the real settings changes. Two screens:

* <prefix>machines.png        - the page as it opens;
* <prefix>machines_remote.png - the machine's Remote panel open, its status read and its screen captured.

A build before PAD-1632 has no Remote on the row: both screens are then the page as it was.
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


def _machines(url):
    return (ws.state(url).get("shellx") or {}).get("machines") or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--address", default="192.168.4.166")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print("REPO", REPO)
    real = os.path.join(os.environ["APPDATA"], "pinball_decryptor")
    scratch = tempfile.mkdtemp(prefix="padshot1632-")
    shutil.copytree(os.path.join(real, "remote_access"),
                    os.path.join(scratch, "cfg", "pinball_decryptor", "remote_access"))
    env = {"PAD_SHOT_ONLINE": a.address}
    if os.environ.get("APPDATA"):
        env["PYTHONUSERBASE"] = os.path.join(os.environ["APPDATA"], "Python")
    proc, url = ws.start_server(os.path.join(real, "settings.json"), scratch, extra_env=env)
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
            for _ in range(60):
                if _machines(url).get("online"):
                    break
                time.sleep(0.25)
            time.sleep(1.5)
            st = _machines(url)
            print(json.dumps({"rows": [{k: r.get(k) for k in ("name", "address", "project_name", "project_how",
                                                             "game_projects")} for r in st.get("rows") or []],
                              "online": st.get("online"), "remote": st.get("remote")}, default=str))
            page.screenshot(path=os.path.join(a.out, a.prefix + "machines.png"))
            try:
                opened = ws.api(url, "shellx.machines_remote", a.address)
            except Exception as e:                      # noqa: BLE001 - a build before PAD-1632
                opened = None
                print("no Remote panel in this build:", e)
            if opened:
                print("status", ws.api(url, "network.machine_status"))
                for _ in range(120):
                    n = ws.state(url).get("network") or {}
                    if n.get("care_status") or n.get("care_kind") == "err":
                        break
                    time.sleep(0.25)
                print("capture", ws.api(url, "network.capture_screen"))
                for _ in range(160):
                    n = ws.state(url).get("network") or {}
                    if n.get("screen_path") or n.get("screen_kind") == "err":
                        break
                    time.sleep(0.25)
                n = ws.state(url).get("network") or {}
                print(json.dumps({k: n.get(k) for k in ("address", "care_status", "care_note", "screen_note")}))
                time.sleep(1.5)
            page.screenshot(path=os.path.join(a.out, a.prefix + "machines_remote.png"), full_page=True)
            browser.close()
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
