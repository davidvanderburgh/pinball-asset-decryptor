"""PAD-1520 proof shot: the Attract tab's tips, scrolled to "Attract flipper sounds" (they no longer play during
the MATCH at the end of a game).
    python scripts/shot_pad1520.py <out_dir> <before|after>
Writes <out_dir>/<kind>_attract_tips.png.  Serves the app from this checkout with a copy of David's saved
settings (PAD_UI_CAPTURE: nothing is written back).  Needs Playwright (PAD_PWLIB / the user site) and Edge.
"""
import os
import site
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402


def main():
    out_dir = os.path.abspath(sys.argv[1])
    kind = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1520-")
    settings = os.path.join(os.environ["APPDATA"], "pinball_decryptor", "settings.json")
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    proc, url = webui_shot.start_server(settings, scratch, extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda *a: webui_shot.api(url, *a)  # noqa: E731
    try:
        api("ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            api("ui.select_tab", "attract")
            time.sleep(3)
            page.locator(".sx-help").first.click()
            time.sleep(2)
            t = page.get_by_text("Attract flipper sounds", exact=True)
            if t.count():
                t.first.click()
                time.sleep(1)
            m = page.get_by_text("Time between sounds", exact=False)
            if m.count():
                m.last.evaluate("e => e.scrollIntoView({block: 'center'})")
                time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, kind + "_attract_tips.png"))
            browser.close()
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
