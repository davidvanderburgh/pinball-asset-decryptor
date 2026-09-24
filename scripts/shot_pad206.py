"""PAD-206 proof shot: the Extract tab right after an extract finished.

    python scripts/shot_pad206.py <out.png> [card.raw]

Runs a real Text-only extract (the fast category) of a Spike 2 card into a
scratch project folder, waits for it to finish, then captures the tab with
the Extract button in view.  Nothing outside the scratch folder is written.
"""

import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0_spike2" \
       r".Release.8G.sdcard.raw"


def main():
    out = os.path.abspath(sys.argv[1])
    card = sys.argv[2] if len(sys.argv) > 2 else CARD
    scratch = tempfile.mkdtemp(prefix="pad206-")
    project = os.path.join(scratch, "Godzilla Pro 1.16")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "extract_output": project,
                       "extract_options": {"categories": {
                           "audio": False, "video": False,
                           "images": False, "text": True}}}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch,
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "extract")
        for k in ("audio", "video", "images"):
            webui_shot.api(url, "ui.set", "extract", "cat_" + k, False)
        webui_shot.api(url, "ui.set", "extract", "cat_text", True)
        time.sleep(2)
        print("before run: block_reason",
              repr(webui_shot.state(url)["extract"].get("block_reason")),
              flush=True)
        webui_shot.api(url, "extract.start")
        t0 = time.time()
        time.sleep(3)
        while webui_shot.state(url)["shell"].get("running"):
            if time.time() - t0 > 1200:
                raise SystemExit("the extract never finished")
            time.sleep(2)
        time.sleep(2)
        st = webui_shot.state(url)
        print("extract took %.0fs; status %r" % (
            time.time() - t0, st["shell"].get("status")), flush=True)
        print("after run: block_reason",
              repr(st["extract"].get("block_reason")), flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); }"
                " catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(2)
            btn = page.locator("button", has_text="Extract").last
            btn.scroll_into_view_if_needed()
            time.sleep(1)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
