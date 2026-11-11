"""PAD-1123 proof shots: the Co-op characters dialog with Godzilla's set loaded - after the change with GODZILLA 1954's
"When picked" panel open (a clip and a sound chosen) and the End of Ball Bonus tick on.

    python scripts/shot_pad1123.py <repo> <out_dir> <before|after> [clip file] [sound file]

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Godzilla LE 1.16 card, opens the
Modes tab's Co-op characters dialog and loads Godzilla's set. Writes <out_dir>/<kind>_characters_dialog.png.

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
    clip = sys.argv[4] if len(sys.argv) > 4 else ""
    sound = sys.argv[5] if len(sys.argv) > 5 else ""
    print("repo", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad1123-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1123.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
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
            if kind == "after":
                if clip:
                    CP.save_picked_clip(project, 0, clip)
                if sound:
                    CP.save_picked_sound(project, 0, sound)
                webui_shot.api(url, "modes.coop_chars_bonus", True)
                time.sleep(2)
                page.locator(".modes-coop-ch-row").nth(0).get_by_role("button", name="When picked").first \
                    .dispatch_event("click")
                time.sleep(2)
            page.mouse.move(5, 1290)
            time.sleep(2)
            page.screenshot(path=os.path.join(out_dir, "%s_characters_dialog.png" % kind))
            browser.close()
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
