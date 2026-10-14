"""PAD-575 proof shots: what the Write tab and its Tips say about Picture settings in the service menu.

    python scripts/shot_pad575.py <repo> <out_dir> [--after]

Serves <repo> on the same scratch Godzilla Premium/LE 1.16 project as scripts/shot_pad537.py (its
sidecar asks for the picture settings). Writes, under the same name before and after:

- <before_|after_>write_tab.png   the Write tab where the tick sits (PAD-575 round 2: after, not
                                  offered, so no tick)
- <before_|after_>write_tip.png   the Write tab with "Picture settings in the service menu"'s tip
                                  open: after, a change shows from the game's next start and at 5
                                  the game draws as it does without them
- <before_|after_>tips.png        the Write tab's Tips window at its "Picture settings in the
                                  service menu" section

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad537 as base  # noqa: E402
import webui_shot  # noqa: E402

LABEL = "Picture settings in the service menu"


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad575-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    tag = "after_" if after else "before_"
    out = lambda n: os.path.join(out_dir, tag + n)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "write")
            time.sleep(6)
            ed = page.locator(".wr-editions, button:has-text('Name the editions')").first
            if ed.count():
                ed.scroll_into_view_if_needed()
                time.sleep(0.5)
            page.screenshot(path=out("write_tab.png"))
            row = page.locator("label:has-text('%s')" % LABEL).first
            if not row.count():                             # PAD-575 round 2: not offered
                print("no picture settings tick on the Write tab", flush=True)
                browser.close()
                return
            row.scroll_into_view_if_needed()
            time.sleep(0.5)
            row.hover()
            time.sleep(1.5)
            page.screenshot(path=out("write_tip.png"))
            page.mouse.move(5, 5)
            time.sleep(0.5)
            page.locator("button[aria-label='Tips for this tab'], .sx-help").first.click()
            time.sleep(2)
            head = page.locator("text=%s" % LABEL).last
            head.scroll_into_view_if_needed()
            head.evaluate("e => e.scrollIntoView({block: 'start'})")
            time.sleep(0.8)
            page.screenshot(path=out("tips.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
