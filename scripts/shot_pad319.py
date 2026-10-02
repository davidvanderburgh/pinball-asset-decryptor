"""PAD-319 capture: the Emulate Spooky tab running a P-ROC game (Rick and
Morty, Alice Cooper's Nightmare Castle) from its game-code .pkg, and the
virtual playfield it opens, against the live rig.

    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad319.py --out <dir>
        --file D:\\Pinball\\images\\Spooky\\rm-gamecode-20220902.pkg [--slot 1]

shot_pad316.py's server (scratch settings, rig ON, hidden and muted on rig
slot --slot, this checkout's tools/spooky_emu): shoots <prefix>emulate_spooky
idle, sets the file, presses Start, waits and shoots
<prefix>emulate_spooky_<name>; then serves the playfield page (spkpf.py, as
the window does) on the run's switches.json, presses a coin, Start, Launch
and a few playfield letters, shoots <prefix>playfield_<name>, and Stops.
"""
import argparse
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "spooky_emu"))
import webui_shot as ws  # noqa: E402

NS = "emulate_spooky"


def state(url):
    return ws.state(url).get(NS) or {}


def playfield(args, slot, browser):
    import spkpf
    path = r"\\wsl.localhost\%s\var\tmp\pad_spkproc\rig%s\switches.json" % (
        args.distro, slot)
    with open(path, encoding="utf-8") as f:
        table = json.load(f)
    app, rig, host = spkpf.serve(table, args.distro, slot)
    errors = []
    try:
        if True:
            page = browser.new_page(viewport={"width": 1000, "height": 980})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(host.url())
            time.sleep(4)
            print("at rest:", app._balls()[3])
            page.keyboard.press("Digit5")           # a coin
            time.sleep(1)
            page.keyboard.press("Digit1")           # Start
            time.sleep(5)
            print("after Start:", app._balls()[3])
            page.keyboard.down("Space")             # the Launch button
            time.sleep(0.25)
            page.keyboard.up("Space")
            time.sleep(3)
            print("after Launch:", app._balls()[3])
            for key in "ASZXQW":                    # playfield switches
                page.keyboard.down("Key" + key)
                time.sleep(0.15)
                page.keyboard.up("Key" + key)
                time.sleep(0.4)
            time.sleep(2)
            page.screenshot(path=os.path.join(
                args.out, "%splayfield_%s.png" % (args.prefix, args.name)))
            print("notes:", app.note)
            page.close()
    finally:
        app.stopping = True
        rig.close()
        host.stop()
    return errors


def shoot(args):
    scratch = tempfile.mkdtemp(prefix="padshot319-")
    env = {"PAD_UI_NO_RIG": "0", "PAD_SLOT": str(args.slot),
           "PAD_LABEL": "PAD-319", "PAD_HIDDEN": "1",
           "PAD_SPOOKY_EMU_DIR": os.path.join(REPO, "tools", "spooky_emu")}
    if os.environ.get("APPDATA"):
        env["PYTHONUSERBASE"] = os.path.join(os.environ["APPDATA"], "Python")
    proc, url = ws.start_server("", scratch, extra_env=env)
    from playwright.sync_api import sync_playwright
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": args.width,
                                              "height": args.height})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            for _ in range(480):
                if "spooky" in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                    break
                time.sleep(0.5)
            ws.api(url, "ui.pick_manufacturer", "spooky")
            ws.api(url, "ui.select_tab", NS)
            for _ in range(60):
                if state(url).get("state_label") not in (None, "Checking…"):
                    break
                time.sleep(1)
            time.sleep(2)
            page.screenshot(path=os.path.join(args.out,
                                              args.prefix + "emulate_spooky.png"))
            if args.file:
                ws.api(url, "ui.set", NS, "file", args.file)
                time.sleep(1)
                ws.api(url, NS + ".toggle")
                t0 = time.time()
                time.sleep(3)
                while time.time() - t0 < 1500:
                    st = state(url)
                    if not st.get("busy") and not st.get("starting"):
                        break
                    time.sleep(2)
                time.sleep(4)
                st = state(url)
                print("->", st.get("state_label"), st.get("state_hint"),
                      [c["value"] for c in st.get("cells", [])],
                      round(time.time() - t0), "s")
                page.screenshot(path=os.path.join(
                    args.out, "%semulate_spooky_%s.png" % (args.prefix, args.name)))
                if st.get("up"):
                    errors += playfield(args, args.slot, browser)
                    ws.api(url, NS + ".toggle")      # Stop
                    for _ in range(60):
                        st = state(url)
                        if not st.get("busy") and not st.get("up"):
                            break
                        time.sleep(2)
                    print("stopped:", not st.get("up"))
            browser.close()
    finally:
        proc.terminate()
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="after_")
    ap.add_argument("--file", default="")
    ap.add_argument("--name", default="rick_and_morty")
    ap.add_argument("--slot", default="1")
    ap.add_argument("--distro", default="PAD-Runtime")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    errors = shoot(args)
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
