"""PAD-1589 proof shot: the accessibility options on a Spike 2 Godzilla LE 1.16 project (the play options).

    python scripts/shot_pad1589.py <repo> <out.png> [--tick] [--preset red_green|blue_yellow] [--tab playopts|modes]
                                   [--lights]

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Godzilla LE 1.16 card (its
.extract_source.json names it) and shows the play options. Before (main) there is no colour-blind or spoken-score
option; after there are both, and with --tick both are ticked (--preset picks the colour-blind preset). --lights opens
the Modes tab's Light shows preview instead (the preset's colours on the playfield there).

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

CARD = os.environ.get("PAD1589_CARD") or r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
CARD_VERSION = os.environ.get("PAD1589_VERSION", "1.16.0")
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    tick = "--tick" in sys.argv[3:]
    preset = arg("--preset", "red_green")
    tab = arg("--tab", "playopts")
    scratch = tempfile.mkdtemp(prefix="pad1589-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": CARD_VERSION}, f)
    launcher = os.path.join(scratch, "launch1589.py")
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
    # the playfield window's state file (insert colours, the preview preset) is the user's: keep it out of the shot
    env = {"PYTHONPATH": site.getusersitepackages(), "USERPROFILE": scratch, "HOME": scratch}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            if tick:
                print(webui_shot.api(url, "modes.set_colour_blind", True, preset), flush=True)
                print(webui_shot.api(url, "modes.set_spoken_scores", True), flush=True)
                time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "modes" if "--lights" in sys.argv else tab)
            time.sleep(6)
            if "--lights" in sys.argv:
                page.get_by_text("Light shows").first.click()
                time.sleep(5)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
