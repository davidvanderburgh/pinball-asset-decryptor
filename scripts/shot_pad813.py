"""PAD-813 proof shots: what a brand-new user sees, and the top bar.

    python scripts/shot_pad813.py <repo> <out_dir> [--after]

Serves <repo> (this checkout, or an export of main for the before shots) on
a scratch settings file that has never picked a manufacturer, the way a
first launch looks, and writes <before_|after_>first_launch.png. Then picks
Stern Spike 2 and writes <before_|after_>top_bar.png. With --after it also
opens Getting started from the top bar on a second tab and writes
after_reopened.png.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
if __name__ == "__main__":       # spawned workers import this file too
    from pinball_decryptor.webui import host
    sys.argv = ["host"] + sys.argv[1:]
    sys.exit(host.main())
'''


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad813-")
    launcher = os.path.join(scratch, "launch813.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "theme": "dark"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, os.path.join(scratch, "srv"), app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)   # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2.5)
            page.screenshot(path=out("first_launch.png"))
            if after:
                page.get_by_role("button", name="Choose a manufacturer").first.click()
                time.sleep(1)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1.5)
            api("ui.set_era", "spike2")
            time.sleep(1.5)
            page.screenshot(path=out("top_bar.png"))
            if after:
                page.locator(".sx-gs-open").first.click()
                time.sleep(1.5)
                page.screenshot(path=out("reopened.png"))
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
