"""PAD-1053 proof shot: the Modes tab's co-op play block, ticked, with Godzilla's characters, an award changed.

    python scripts/shot_pad1053.py <repo> <out.png> [--save <file>] [--load <file>|none]

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Godzilla LE 1.16 card, shows the
Modes tab, ticks Co-op play, loads Godzilla's characters and unticks an award. Before (main) the co-op block has
Awards... and Characters... only; after it also has Save... and Load... for the co-op settings file. With --load the
settings in <file> are loaded into a second, fresh scratch project instead and the shot shows its Characters dialog
(the round trip: the file brings back the characters, their abilities and their pictures).

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
    out = os.path.abspath(sys.argv[2])
    args = sys.argv[3:]
    load = os.path.abspath(args[args.index("--load") + 1]) if "--load" in args else ""
    save = os.path.abspath(args[args.index("--save") + 1]) if "--save" in args else ""
    scratch = tempfile.mkdtemp(prefix="pad1053-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1053.py")
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
            if load:
                if os.path.isfile(load):                # the call waits on its message box: answer it here
                    import threading
                    threading.Thread(target=lambda: webui_shot.api(url, "modes.coop_settings_load", load, True),
                                     daemon=True).start()
                    page.wait_for_selector(".modal", timeout=120000)
                    time.sleep(1)
                    print("load says:", page.locator(".modal").last.inner_text(), flush=True)
                    page.screenshot(path=os.path.splitext(out)[0] + "_message.png")
                    page.locator(".modal").last.get_by_role("button", name="OK", exact=True).first.click()
                else:                                   # --load none: a fresh project, co-op ticked (before)
                    webui_shot.api(url, "modes.set_coop", True)
                time.sleep(3)
                page.get_by_role("button", name="Characters…").click()
                page.wait_for_selector(".modes-coop-ch-row" if os.path.isfile(load) else "text=Co-op characters",
                                       timeout=180000)
                page.mouse.move(5, 990)
                time.sleep(3)
                page.screenshot(path=out)
            else:
                webui_shot.api(url, "modes.set_coop", True)
                webui_shot.api(url, "modes.coop_chars_preset")
                webui_shot.api(url, "modes.coop_awards_refresh")
                if save:                                # two pictures and an award changed, then Save...
                    sys.path.insert(0, repo)
                    from PIL import Image
                    from pinball_decryptor.plugins.stern import coop_play as CP
                    for i, rgb in ((0, (40, 120, 220)), (3, (220, 90, 20))):
                        pic = os.path.join(scratch, "pic%d.png" % i)
                        Image.new("RGB", (400, 520), rgb).save(pic)
                        CP.save_picture(project, i, pic)
                    webui_shot.api(url, "modes.coop_award_set", "score", False, None)
                    print("saved", webui_shot.api(url, "modes.coop_settings_save", save), flush=True)
                time.sleep(3)
                page.mouse.move(5, 990)
                time.sleep(2)
                box = page.locator(".modes-coop").first.bounding_box()
                pad = 24
                page.screenshot(path=out, clip={"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
                                                "width": min(1500, box["width"] + 2 * pad + 300),
                                                "height": box["height"] + 2 * pad})
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
