"""PAD-1079 proof shots: the Co-op characters dialog with Godzilla's set loaded and its pick card, before and after the
pick screen's look (colours, title, background) became the owner's to choose.

    python scripts/shot_pad1079.py <repo> <out_dir> <before|after> <pictures folder> [<background picture>]

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Godzilla LE 1.16 card, opens the
Modes tab's Co-op characters dialog, loads Godzilla's set and the pictures named after its characters. After: opens
the dialog's Look section and gives the pick a look of its own (a red frame, gold names, green words, its own title,
a background picture, one character's own colour). Writes <out_dir>/<kind>_characters_dialog.png and
<kind>_pick_card.png (the machine's still of the first character's pick screen).

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
LOOK = {"title": "PICK YOUR KAIJU", "accent": "#e0201c", "accent2": "#ffd400", "name": "#ffd400",
        "does": "#a8ffb0", "help": "#ffd400", "dim": 60}
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
    folder = os.path.abspath(sys.argv[4])
    backdrop = os.path.abspath(sys.argv[5]) if len(sys.argv) > 5 else ""
    print("repo", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad1079-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1079.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1900})
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
            print("pictures from", folder, CP.pictures_from_folder(project, folder), flush=True)
            if kind == "after":
                for key, value in LOOK.items():
                    webui_shot.api(url, "modes.coop_chars_look", key, value)
                if backdrop:
                    CP.save_backdrop(project, backdrop)
                webui_shot.api(url, "modes.coop_char_colour", 1, "#7a3cff")
                page.get_by_role("button", name="Look…").dispatch_event("click")
                time.sleep(1)
            webui_shot.api(url, "modes.coop_chars_show", 0)
            time.sleep(5)
            chars = CP.load_characters(project)
            print("theme", chars.get("theme"), "first", chars["list"][0], flush=True)
            page.mouse.move(5, 1890)
            time.sleep(2)
            page.screenshot(path=os.path.join(out_dir, "%s_characters_dialog.png" % kind))
            browser.close()
        chars = dict(CP.load_characters(project), pick=True)
        with open(os.path.join(out_dir, "%s_pick_card.png" % kind), "wb") as f:
            f.write(CP.preview(project, chars, CP.words_for(), 0))
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
