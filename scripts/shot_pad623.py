"""PAD-623 proof shots: a project whose card file was moved away, in the Modes tab.

    python scripts/shot_pad623.py <out dir> [<repo>] [--modes <a project's modes folder>]

The server runs from <repo> (default: this tree) against a scratch settings folder and a scratch copy of a
project's modes (default: David's "heisei modes 1.99D"; only the small json/c/h files are copied) whose .pinproj
names a custom Godzilla card that is NOT on this computer, as his card was after he moved it. The settings'
path history names the stock Godzilla LE 1.16 card (as his does), read only. The title cache is a scratch folder,
so no picture kept from an earlier read helps. Shots:
  modes.png        the tab's head with the Blockhead blocks mode open (which game the modes are for)
  playfield.png    its Playfield tab (the game's playfield picture, or why there is none)
"""

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import webui_shot  # noqa: E402

MODES = r"C:\Users\david\OneDrive\Desktop\heisei modes 1.99D\modes"
STOCK = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
CARD_NAME = "Godzilla Premium 1.16 Heisei Custom V1.99D Kaiju Edition.raw"

HOST = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


def _project(scratch, modes):
    project = os.path.join(scratch, "heisei modes")
    for root, _dirs, files in os.walk(modes):
        rel = os.path.relpath(root, modes)
        for name in files:
            if name.lower().endswith((".json", ".c", ".h")):
                dst = os.path.join(project, "modes", rel)
                os.makedirs(dst, exist_ok=True)
                shutil.copy2(os.path.join(root, name), dst)
    gone = os.path.join(scratch, "moved away", CARD_NAME)         # never made: the card is not there
    with open(os.path.join(project, ".pinproj"), "w", encoding="utf-8") as f:
        json.dump({"kind": "pinball-asset-decryptor-project", "format": 2, "manufacturer": "stern",
                   "stock_image": gone, "paths": {"extract_input": gone, "write_original": gone}}, f)
    return project, gone


def main():
    args = sys.argv[1:]
    modes = MODES
    if "--modes" in args:
        i = args.index("--modes")
        modes = args[i + 1]
        del args[i:i + 2]
    outdir = os.path.abspath(args[0])
    repo = os.path.abspath(args[1]) if len(args) > 1 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad623-")
    project, gone = _project(scratch, modes)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project,
                                               "extract_input": gone, "write_original": gone}},
                   "path_history": {"stern": {"extract_input": [gone, STOCK],
                                              "write_original": [gone, STOCK]}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_TITLE_CACHE": os.path.join(scratch, "titles")}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print("repo", repo, "url", url, "card there:", os.path.isfile(gone), flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "modes")
        time.sleep(4)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1100})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            time.sleep(2)
            rows = page.get_by_text("Blockhead", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.get_by_text("Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            page.screenshot(path=os.path.join(outdir, "modes.png"))
            print("card words:", [t for t in page.locator("body").inner_text().splitlines()
                                  if t.startswith("Card:")][:2], flush=True)
            tab = page.get_by_role("tab", name="Playfield")
            if tab.count():
                tab.first.click()
                page.wait_for_selector(".pf-art, .pf-none", timeout=120000)
                time.sleep(1.5)
                page.screenshot(path=os.path.join(outdir, "playfield.png"))
                print("picture shown:", page.locator(".pf-art").count(), "| none:",
                      page.locator(".pf-none").all_inner_texts(), flush=True)
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
