"""PAD-588 proof shots: the Audio tab's Advanced Audio Options on a SAM card
(and, after, on a Spike 2 card, which keeps every lever).

    python scripts/shot_pad588.py <repo> <out_dir> [--after]

Serves <repo> on an empty scratch project and writes, under before_/after_:

- sam_advanced.png      Stern SAM: before, the whole Spike 2 dialog; after,
                        the loudness row alone
- spike2_advanced.png   Stern Spike 2: the whole dialog, both times

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad588-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1100})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            for era, name in (("sam", "sam_advanced.png"),
                              ("spike2", "spike2_advanced.png")):
                print("era", era, api("ui.set_era", era), flush=True)
                time.sleep(1)
                api("ui.select_tab", "audio")
                time.sleep(2)
                page.click("button:has-text('Advanced')")
                time.sleep(1.5)
                page.mouse.move(5, 1090)
                page.screenshot(path=out(name))
                page.click(".modal button:has-text('Cancel')")
                time.sleep(0.5)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
