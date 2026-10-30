"""PAD-811 proof shots: the Emulate tab's Game display card.

    python scripts/shot_pad811.py <out_dir> [--after]

Serves THIS checkout (run a copy from an export of main for the before
shot) with Stern Spike 2 picked and writes <before_|after_>emulate.png; the
after run also shows the card in Window and in Full screen
(after_gdisp_window.png, after_gdisp_fullscreen.png). The card saves the
REAL display.conf on the rig board, so the file is put back as it was.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CONF = os.path.join(os.path.expanduser("~"), ".pad-rig", "display.conf")


def main():
    out_dir = os.path.abspath(sys.argv[1])
    after = "--after" in sys.argv
    pre = "after_" if after else "before_"
    os.makedirs(out_dir, exist_ok=True)
    saved = open(CONF, "rb").read() if os.path.exists(CONF) else None
    scratch = tempfile.mkdtemp(prefix="pad811-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark"}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            if webui_shot.state(url)["shell"]["mfr"].get("era") != "spike2":
                webui_shot.api(url, "ui.set_era", "spike2")
                time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(2.5)
            card = page.locator(".emu-gdisp")
            if card.count():
                card.first.scroll_into_view_if_needed()
                time.sleep(0.5)
            page.screenshot(path=os.path.join(out_dir, pre + "emulate.png"))
            if after and card.count():
                for mode, name in (("window", "gdisp_window"), ("fullscreen", "gdisp_fullscreen")):
                    webui_shot.api(url, "emulate.display_set", "mode", mode)
                    time.sleep(1.5)
                    print(mode, "->", json.dumps(webui_shot.state(url).get("emulate", {}).get("gdisp")),
                          flush=True)
                    card.first.screenshot(path=os.path.join(out_dir, pre + name + ".png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
        if saved is not None:
            with open(CONF, "wb") as f:
                f.write(saved)


if __name__ == "__main__":
    main()
