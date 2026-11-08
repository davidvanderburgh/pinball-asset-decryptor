"""PAD-1064 proof shot: one of the game's own modes on the Modes tab, with its How it works.

    python scripts/shot_pad1064.py <repo> <out.png> [<mode id>] [<project>]

Serves <repo>, with the mode maker's preview on, on <project> (default D:\\Pinball\\pad1064_gzpro116: a video-only
Extract of the Godzilla Pro 1.16 card, with an earlier extract's decoded sounds and sound_requests.tsv beside it),
shows the Modes tab and opens the game's mode <mode id> (default 1, Godzilla Multiball). Before (main) the page has
Timers and awards only; after it has How it works above them: what starts the mode, its clips, its sounds.

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

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"
PROJECT = r"D:\Pinball\pad1064_gzpro116"
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
    mode_id = sys.argv[3] if len(sys.argv) > 3 else "1"
    project = sys.argv[4] if len(sys.argv) > 4 else PROJECT
    scratch = tempfile.mkdtemp(prefix="pad1064-")
    launcher = os.path.join(scratch, "launch1064.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            deadline = time.time() + 240             # the card's game program is read the first time
            while time.time() < deadline and not webui_shot.api(url, "modes.select", mode_id, "game"):
                time.sleep(3)
            page.wait_for_selector("text=Timers and awards", timeout=60000)
            try:                                     # after: the clips and sounds are read on a worker
                page.wait_for_selector("text=Sounds and callouts it plays", timeout=120000)
            except Exception:                        # noqa: BLE001 - before: there is no such section
                pass
            time.sleep(3)
            page.mouse.move(5, 1290)
            time.sleep(1)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
