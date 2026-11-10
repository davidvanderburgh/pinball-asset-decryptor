"""PAD-1114 proof shots: the Modes tab's co-op row on a Godzilla LE 1.16 project with co-op on and Godzilla's
characters loaded, before and after co-op and team games got an intro video of the owner's (Intro video...).

    python scripts/shot_pad1114.py <repo> <out_dir> <before|after> <pictures folder> [<intro video>]

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Godzilla LE 1.16 card, opens the
Modes tab, ticks Co-op play (switched in the service menu), loads Godzilla's set and the pictures named after its
characters. After: gives co-op and team games <intro video> as their intro. Writes <out_dir>/<kind>_coop_row.png (the
co-op part of the Modes tab's list footer).

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
    folder = os.path.abspath(sys.argv[4])
    video = os.path.abspath(sys.argv[5]) if len(sys.argv) > 5 else ""
    scratch = tempfile.mkdtemp(prefix="pad1114-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1114.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            webui_shot.api(url, "modes.set_coop", True)
            webui_shot.api(url, "modes.set_coop_menu", True)
            time.sleep(2)
            webui_shot.api(url, "modes.coop_chars_preset")
            print("pictures from", folder, CP.pictures_from_folder(project, folder), flush=True)
            if kind == "after" and video:
                CP.save_intro(project, video)
            webui_shot.api(url, "modes.coop_chars_refresh")
            # the row republishes on the next project read: reselect the tab
            webui_shot.api(url, "ui.select_tab", "audio")
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(5)
            page.mouse.move(5, 1090)
            time.sleep(1)
            row = page.locator(".modes-coop").first
            row.scroll_into_view_if_needed()
            time.sleep(1)
            box = row.bounding_box()
            pad = 12
            page.screenshot(path=os.path.join(out_dir, "%s_coop_row.png" % kind),
                            clip={"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
                                  "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad})
            page.screenshot(path=os.path.join(out_dir, "%s_modes_tab.png" % kind))
            browser.close()
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
