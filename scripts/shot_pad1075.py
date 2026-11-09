"""PAD-1075 proof shots: the Co-op characters dialog with Godzilla's set loaded, and the pick cards of the six
abilities the set reshaped.

    python scripts/shot_pad1075.py <repo> <out_dir> <before|after> <pictures folder>...

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Godzilla LE 1.16 card, opens the
Modes tab's Co-op characters dialog, loads Godzilla's set, puts in the pictures named after its characters from each
<pictures folder> (Pictures from folder...'s way). Writes <out_dir>/<kind>_characters_dialog.png (the dialog) and
<kind>_card_<ability>.png (the pick card of the character with that ability, full size).

Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike2.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
CARDS = ("longer_save", "ally", "maser", "building", "spot", "heat_ray")
LAUNCHER = r'''
import sys
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
    folders = [os.path.abspath(f) for f in sys.argv[4:]]
    print("repo", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad1075-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1075.py")
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
        sys.path.insert(0, repo)
        from pinball_decryptor.plugins.stern import coop_play as CP
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1800})
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
            for folder in folders:
                print("pictures from", folder, CP.pictures_from_folder(project, folder), flush=True)
            webui_shot.api(url, "modes.coop_chars_show", 0)
            time.sleep(4)
            chars = CP.load_characters(project)
            print("rows", [(c["name"], c.get("sub"), c["ability"]) for c in chars["list"]], flush=True)
            page.mouse.move(5, 1790)
            time.sleep(2)
            page.screenshot(path=os.path.join(out_dir, "%s_characters_dialog.png" % kind))
            browser.close()
        chars = dict(CP.load_characters(project), pick=True)
        for ability in CARDS:
            row = next(i for i, c in enumerate(chars["list"]) if c["ability"] == ability)
            with open(os.path.join(out_dir, "%s_card_%s.png" % (kind, ability)), "wb") as f:
                f.write(CP.preview(project, chars, CP.words_for(), row))
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
