"""PAD-849 proof shots: Start on the Emulate tab with a card WSL could not see.

    python scripts/shot_pad849.py <out_dir> <before|after> [repo]

Serves *repo* (default: this checkout; give an export of main for the before
shot) with Stern Spike 2 picked, sets the Emulate card to Foo Fighters LE 1.04
reached through ``subst Q: D:\\Pinball\\images\\Stern\\spike2`` (a drive WSL
does not mount, like a network drive), presses Start on rig 3 - never David's
rig - and photographs the tab with its log open 60 s later, then stops the
run.  Writes <before|after>_emulate_start.png.

Needs Playwright (the user site-packages one), the installed Edge, and the
Foo Fighters LE card under D:\\Pinball\\images\\Stern\\spike2.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD_DIR = r"D:\Pinball\images\Stern\spike2"
CARD = r"Q:\foo_fighters_le-1_04_0.Release.16G.sdcard.raw"


def main():
    out_dir = os.path.abspath(sys.argv[1])
    pre = sys.argv[2] + "_"
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else None
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(["subst", "Q:", "/d"], capture_output=True)
    subprocess.run(["subst", "Q:", CARD_DIR], check=True)
    scratch = tempfile.mkdtemp(prefix="pad849-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "theme": "dark"}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    env = {"PYTHONUSERBASE": userbase, "PAD_SLOT": "3", "PAD_TICKET": "",
           "PAD_LABEL": "PAD-849-check"}
    env["PAD_UI_NO_RIG"] = ""           # the rig is the point of this shot
    app_cmd = [sys.executable, "-c",
               "import sys, runpy; sys.path.insert(0, %r); "
               "runpy.run_module('pinball_decryptor.webui.host', "
               "run_name='__main__')" % (repo or os.path.dirname(HERE))]
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env=env, app_cmd=app_cmd)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '1'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            if webui_shot.state(url)["shell"]["mfr"].get("era") != "spike2":
                webui_shot.api(url, "ui.set_era", "spike2")
                time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(2)
            webui_shot.api(url, "ui.set", "emulate", "card", CARD)
            time.sleep(2)
            webui_shot.api(url, "emulate.toggle")
            time.sleep(60)
            page.screenshot(path=os.path.join(out_dir, pre + "emulate_start.png"))
            if pre == "after_":                 # running: Stop it
                webui_shot.api(url, "emulate.toggle")
                time.sleep(15)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
        subprocess.run(["subst", "Q:", "/d"], capture_output=True)


if __name__ == "__main__":
    main()
