r"""PAD-1407 proof shots: the Attract tab on an Uncanny X-Men LE 0.98 project whose owner puts a title card of his own
("UNCANNY X-MEN 2.0 / PRESS START") in front of the game's attract.

    python scripts/shot_pad1407.py <app tree> <out png> [--replace] [--card NAME]

A scratch project made from the library card, its record seeded with the text card before the game's first screen,
served by <app tree> (main for the before shot, the ticket's branch for the after). --replace also presses the page's
"Replace the game's attract" button (after shot only: the button is new), so the shot shows the game's own screens
taken off and its high score and champion screens kept.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LIB = r"D:\Pinball\images\Stern\spike2"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    card = os.path.join(LIB, _arg("--card", "uncanny_xmen_le-0_98_0.Release.16G.sdcard.raw"))
    scratch = tempfile.mkdtemp(prefix="pad1407-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card)}, f)
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"attract_items": {"items": [
            {"kind": "text", "entry": 0, "where": "before", "seconds": 6, "text": "UNCANNY X-MEN 2.0\nPRESS START"}],
            "champions": True}}, f)
    launcher = os.path.join(scratch, "launch1407.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--mute-audio"])
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "attract")
            for _ in range(120):                 # the card's program read
                time.sleep(1)
                if page.locator(".at-seq").count() or "Nothing to edit here" in page.inner_text("body"):
                    break
            time.sleep(2)
            if "--replace" in sys.argv:
                print("replace:", webui_shot.api(url, "attract.replace_all", True), flush=True)
                time.sleep(2)
            for line in page.inner_text("body").splitlines():
                low = line.lower()
                if any(w in low for w in ("attract", "hidden", "replace", "cannot", "screen")):
                    print("page:", line.strip()[:240], flush=True)
            page.screenshot(path=out, full_page=True)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
