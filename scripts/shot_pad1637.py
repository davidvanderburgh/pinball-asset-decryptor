"""PAD-1637 proof shots: the Modes tab's Co-op characters dialog with Godzilla's set loaded, the pick on, select and
awards music set, before and after the co-op sounds could change with the MUSIC MODE (By music mode... under the music
rows, its grid open in the after shot with files of their own in modes 2 and 3).

    python scripts/shot_pad1637.py <repo> <out_dir> <before|after> <ceremony video> <music> <music 2> <music 3>

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Godzilla LE 1.16 card, opens the
dialog, loads Godzilla's set, sets the ceremony video, the select and awards music, and turns the pick on. After: the
intro's sound and the select music get a file of their own in music mode 2, the awards music in mode 3 and the first
character's sound once picked in mode 2, and the By music mode grid is opened. Writes <out_dir>/<kind>_characters_dialog.png
and <kind>_music_rows.png (the dialog's music rows, cropped).

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
    video = os.path.abspath(sys.argv[4])
    music = os.path.abspath(sys.argv[5])
    music2 = os.path.abspath(sys.argv[6])
    music3 = os.path.abspath(sys.argv[7])
    os.makedirs(out_dir, exist_ok=True)
    print("repo", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad1637-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1637.py")
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
            CP.save_ceremony(project, video)
            CP.save_intro(project, video)
            CP.save_ceremony_sound(project, music)
            CP.save_select_sound(project, music)
            if kind == "after":
                CP.save_mode_sound(project, "intro", 2, music2)
                CP.save_mode_sound(project, "select", 2, music2)
                CP.save_mode_sound(project, "ceremony", 3, music3)
                CP.save_picked_mode_sound(project, 0, 2, music3)
            webui_shot.api(url, "modes.coop_chars_pick", True)          # republishes the dialog, pick on
            time.sleep(1)
            webui_shot.api(url, "modes.coop_chars_show", 0)
            time.sleep(5)
            print("characters", {k: v for k, v in CP.load_characters(project).items() if k != "list"}, flush=True)
            if kind == "after":
                page.get_by_role("button", name="By music mode").dispatch_event("click")
                time.sleep(2)
            page.mouse.move(5, 1890)
            time.sleep(2)
            page.screenshot(path=os.path.join(out_dir, "%s_characters_dialog.png" % kind))
            rows = page.locator("button", has_text="Select music").first
            box = rows.bounding_box()
            if box:
                y = max(0, box["y"] - 20)
                page.screenshot(path=os.path.join(out_dir, "%s_music_rows.png" % kind),
                                clip={"x": max(0, box["x"] - 20), "y": y, "width": 1000,
                                      "height": 620 if kind == "after" else 260})
            browser.close()
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
