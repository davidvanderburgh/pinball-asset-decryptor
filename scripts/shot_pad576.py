"""PAD-576 proof shots: the top bar, and Reset... in the project menu.

    python scripts/shot_pad576.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project and writes, under the same names
before and after:

- top_bar.png        the Write tab under the top bar, nothing hovered
- project_menu.png   the project menu open (after: Reset... at its bottom, hovered)

Nothing is reset: Reset... is only hovered.

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
    scratch = tempfile.mkdtemp(prefix="pad576-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "write")
            time.sleep(4)
            try:
                page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
            except Exception:                               # noqa: BLE001
                print("toasts still up", flush=True)
            page.mouse.move(5, 990)
            time.sleep(1)
            page.screenshot(path=out("top_bar.png"))
            top = page.query_selector("header.topbar button:has-text('Reset')")
            print("top bar reset:", bool(top), flush=True)
            page.click("header.topbar button[aria-label='Project menu']")
            time.sleep(1)
            rows = page.eval_on_selector_all(".menu button.mi", "bs => bs.map(b => [b.innerText.trim(), b.disabled])")
            print("project menu:", rows, flush=True)
            mi = page.query_selector(".menu button.mi:has-text('Reset')")
            if mi:
                mi.hover()
                time.sleep(1.5)
            page.screenshot(path=out("project_menu.png"))
            if mi:
                mi.click()
                time.sleep(3)
                print("reset dialog open:", bool(page.query_selector(".modal .sx-reset-list")), flush=True)
                page.click(".modal button:has-text('Cancel')")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("scratch", scratch)


if __name__ == "__main__":
    main()
