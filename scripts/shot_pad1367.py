"""PAD-1367 proof shots: the Co-op characters dialog with Godzilla's set loaded and MIREGOJI's (character 9, ACTION
BUTTON BALL SAVE) powers open, plus its pick card as the app draws it. Before: the save is a fixed 10 seconds; after:
a seconds box beside each timed power, set here through the app to 5 seconds, and the card says 5.

    python scripts/shot_pad1367.py <repo> <out_dir> <before|after>

Writes <out_dir>/<kind>_characters_miregoji.png and <kind>_card_miregoji.png. Needs Playwright (the user site-packages
one), the installed Edge and the Godzilla LE 1.16 card in D:/Pinball/images/Stern/spike2.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD_PNG = r'''
import sys
sys.path.insert(0, sys.argv[1])
from PIL import Image
from pinball_decryptor.plugins.stern import coop_play as CP
chars = CP.load_characters(sys.argv[2])
Image.fromarray(CP.pick_card(sys.argv[2], chars, 8, scale=1)).save(sys.argv[3])
'''
CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
LAUNCHER = r'''
import os, sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    scratch = tempfile.mkdtemp(prefix="pad1367-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1367.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            webui_shot.api(url, "modes.set_coop", True)
            time.sleep(3)
            page.get_by_role("button", name="Characters…").dispatch_event("click")
            page.wait_for_selector("text=Co-op characters", timeout=180000)
            webui_shot.api(url, "modes.coop_chars_preset")
            page.wait_for_selector(".modes-coop-ch-row", timeout=180000)
            time.sleep(3)
            if kind == "after":
                webui_shot.api(url, "modes.coop_char_time", 8, "action_save", 5)
                time.sleep(3)
            row = page.locator(".modes-coop-ch-row").nth(8)                 # MIREGOJI, character 9
            row.locator("button", has_text="Powers").first.dispatch_event("click")
            time.sleep(2)
            grp = page.locator(".modes-coop-ch-grp", has_text="Action button").first      # the timed powers
            grp.evaluate("e => e.scrollIntoView({block: 'start'})")
            time.sleep(1)
            page.mouse.move(5, 990)
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, "%s_characters_miregoji.png" % kind))
            browser.close()
        cp = os.path.join(scratch, "card.py")
        with open(cp, "w", encoding="utf-8") as f:
            f.write(CARD_PNG)
        subprocess.check_call([sys.executable, cp, repo, project, os.path.join(out_dir, "%s_card_miregoji.png" % kind)])
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
