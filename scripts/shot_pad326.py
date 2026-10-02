"""PAD-326 capture: the Emulate PB tab running Alien, ABBA or Queen (the I/O-board
rig, tools/pbio_emu) through the app itself - its Start button - plus the
playfield window on that rig's board and the game's own screen.

    set PAD_SLOT=1 & set PAD_LABEL=PAD-326   (a rig of your own: riglock.sh)
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad315.py --out <dir>
        --file <clonezilla-live-alien40.iso | pbap145.upd> --name emulate
        [--prefix after_] [--tab-only]

--tab-only: just the page with that file picked, nothing started (the
"before" from a main export, where the tab refuses these files).

The server runs on a scratch settings folder with the rig ON; started from a
Claude Code session it runs every game hidden and muted (rigslot.hidden).
Writes <prefix><name>.png (the page, the game in attract after a coin and
Start), and unless --tab-only <prefix><name>_switches.png (the playfield
window, served headless as pbpf.py --rig pbio serves it) and
<prefix><name>_game.png (tools/pbio_emu/shot.sh).  Stops the game at the end.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import webui_shot as ws  # noqa: E402

DISTRO = "PAD-Runtime"


def ws_path(p):
    p = p.replace("\\", "/")
    return "/mnt/" + p[0].lower() + p[2:] if len(p) > 1 and p[1] == ":" else p


def pbio(slot, *args):
    """A tools/pbio_emu script in the app's Linux, as root, on *slot*."""
    script = args[0]
    cmd = (["python3"] if script.endswith(".py") else ["bash"])
    return subprocess.run(
        ["wsl.exe", "-d", DISTRO, "-u", "root", "--", "env", "PAD_SLOT=%s" % slot,
         "PAD_LABEL=PAD-326"] + cmd
        + ["%s/tools/pbio_emu/%s" % (ws_path(REPO), script)] + list(args[1:]),
        capture_output=True, text=True, timeout=180)


def wait_for(url, test, secs):
    end = time.time() + secs
    st = {}
    while time.time() < end:
        st = ws.state(url).get("emulate_pb") or {}
        if test(st):
            return st
        time.sleep(1)
    return st


def tab_shot(args):
    scratch = tempfile.mkdtemp(prefix="padshot326-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "pb_emulate_file": args.file}, f)
    proc, url = ws.start_server(settings, scratch, extra_env={"PAD_UI_NO_RIG": "0"})
    from playwright.sync_api import sync_playwright
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": args.width, "height": args.height})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            for _ in range(120):
                if "pb" in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                    break
                time.sleep(0.5)
            ws.api(url, "ui.pick_manufacturer", "pb")
            time.sleep(2)
            ws.api(url, "ui.select_tab", "emulate_pb")
            time.sleep(4)
            if not args.tab_only:
                ws.api(url, "emulate_pb.toggle")
                st = wait_for(url, lambda s: s.get("ready"), 600)
                print("after Start:", st.get("state_label"), st.get("state_hint"))
                if st.get("ready"):
                    # a credit (the game debounces presses closer than ~1 s),
                    # then Start: the game serves a ball to the shooter lane
                    for _ in range(4):
                        print("coin:", pbio(args.slot, "sw.py", "coin").stdout.strip())
                        time.sleep(1.3)
                    print("start:", pbio(args.slot, "sw.py", "start").stdout.strip())
                    time.sleep(8)
                    st = wait_for(url, lambda s: any(
                        c["label"] == "Balls" and "lane 1" in c["value"]
                        for c in s.get("cells", [])), 30)
            time.sleep(2)
            page.screenshot(path=os.path.join(args.out, args.prefix + args.name + ".png"))
            st = ws.state(url).get("emulate_pb") or {}
            print("state:", st.get("state_label"), "|", st.get("state_hint"))
            print("cells:", {c["label"]: c["value"] for c in st.get("cells", [])})
            print("title note:", st.get("title_note") or "none")
            print("supported:", st.get("supported"), "pending:", st.get("pending"))
            if not args.tab_only and st.get("up"):
                errors += switch_shot(args, browser)
                r = pbio(args.slot, "shot.sh", "%s/%s%s_game.png" % (
                    ws_path(args.out), args.prefix, args.name))
                print("game shot:", r.stdout.strip()[-200:], r.stderr.strip()[-200:])
                ws.api(url, "emulate_pb.toggle")             # Stop
                st = wait_for(url, lambda s: not s.get("up") and not s.get("busy"), 120)
                print("after Stop:", st.get("state_label"))
            browser.close()
    finally:
        proc.terminate()
        for line in (proc.stdout.read() if proc.stdout else "").splitlines():
            if "PB:" in line:
                print("log:", line.strip()[:240])
    return errors


def switch_shot(args, b):
    sys.path.insert(0, os.path.join(REPO, "tools", "pb_emu"))
    import pbpf  # noqa: E402
    unc = "\\\\wsl.localhost\\%s\\var\\tmp\\pad_pbio\\rig%s\\switches.json" % (
        DISTRO, args.slot)
    with open(unc, encoding="utf-8") as f:
        table = json.load(f)
    app, rig, host = pbpf.serve(table, DISTRO, args.slot, rig_name="pbio")
    errors = []
    page = b.new_page(viewport={"width": 1000, "height": 980})  # the tab's browser
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(host.url())
    time.sleep(4)
    print("window balls:", app._balls()[3])
    page.keyboard.press("KeyF")                 # plunge (Queen: both flippers)
    time.sleep(3)
    print("after Launch:", app._balls()[3])
    for key in "ASZXQWGE":                      # playfield switches by letter
        page.keyboard.down("Key" + key)
        time.sleep(0.15)
        page.keyboard.up("Key" + key)
        time.sleep(0.35)
    page.keyboard.down("KeyO")                  # one held while captured
    time.sleep(1.5)
    page.screenshot(path=os.path.join(args.out, args.prefix + args.name + "_switches.png"))
    page.keyboard.up("KeyO")
    page.keyboard.press("F9")                   # Pause freezes the game
    time.sleep(1.5)
    print("paused:", app.paused)
    page.keyboard.press("F9")
    time.sleep(1.5)
    print("resumed:", not app.paused, "| notes:", app.note)
    page.close()
    app.stopping = True
    rig.close()
    host.stop()
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--name", default="emulate")
    ap.add_argument("--prefix", default="after_")
    ap.add_argument("--tab-only", action="store_true")
    ap.add_argument("--slot", default=os.environ.get("PAD_SLOT", "1"))
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    errors = tab_shot(args)
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
