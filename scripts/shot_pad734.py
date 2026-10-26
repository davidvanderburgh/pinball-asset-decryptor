"""PAD-734 proof shots: where the machine's settings, audits and high scores live, in the Tips.

    python scripts/shot_pad734.py <repo> <out_dir> [--after]

Serves <repo> on the same scratch Godzilla Premium/LE 1.16 project as scripts/shot_pad537.py and
writes, under the same name before and after:

- <before_|after_>multiboot_tips.png   the Multi-boot tab's Tips at "Editions: no menu", the
                                       section the new "Settings, audits and high scores" follows
- <before_|after_>defaults_tips.png    the Default Settings tab's Tips at "What it's for", whose
                                       note said Stern keeps the settings on the board

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

SHOTS = (("multiboot_tips.png", "multiboot", "Editions: no menu"),
         ("defaults_tips.png", "defaults", "What it's for"))


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad734-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    tag = "after_" if after else "before_"
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
            for name, tab, heading in SHOTS:
                api("ui.select_tab", tab)
                time.sleep(4)
                page.locator("button[aria-label='Tips for this tab'], .sx-help").first.click()
                time.sleep(2)
                head = page.locator("text=%s" % heading).last
                head.evaluate("e => e.scrollIntoView({block: 'start'})")
                time.sleep(0.8)
                page.screenshot(path=os.path.join(out_dir, tag + name))
                print("shot", tag + name, flush=True)
                page.keyboard.press("Escape")
                time.sleep(1)
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
