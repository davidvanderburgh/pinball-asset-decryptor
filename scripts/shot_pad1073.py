"""PAD-1073 proof shot: the Modes tab's co-op play block, ticked, CO-OP PLAY in the service menu, Godzilla's characters.

    python scripts/shot_pad1073.py <repo> <out.png>

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Godzilla LE 1.16 card, shows the
Modes tab, ticks Co-op play and its service menu row and loads Godzilla's characters. Before, the note under the tick
names CO-OP PLAY 0-6 (Off, three Enhanced games, the same three Classic); after, 0 Off, 1 Classic, 2 Enhanced, the game picked on the start menu.

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
    scratch = tempfile.mkdtemp(prefix="pad1073-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1073.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1800})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            webui_shot.api(url, "modes.set_coop", True)
            webui_shot.api(url, "modes.set_coop_menu", True)
            webui_shot.api(url, "modes.coop_chars_preset")
            time.sleep(4)
            page.locator(".modes-coop").first.scroll_into_view_if_needed()
            page.mouse.move(5, 1790)
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
