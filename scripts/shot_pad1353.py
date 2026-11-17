"""PAD-1353 proof shots: the Balls and Coils groups on the JJP Modes tab's form.

    python scripts/shot_pad1353.py <repo> <out_dir> <before|after>

Both: Jersey Jack picked, the Modes tab, Wonka 03.03, the mode form scrolled to its last
groups. after: the starter multiball mode (2_multiball.mode) open, its Balls and Coils
groups filled. Writes <out_dir>/<kind>_modes_form.png. Needs Playwright (the user
site-packages one) and the installed Edge; the app runs on a scratch APPDATA.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

WONKA_ISO = r"D:\Pinball\images\JJP\Wonka-v03.03.iso"


def main():
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1353-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": WONKA_ISO, "write_original": WONKA_ISO,
                                             "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch,
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            webui_shot.api(url, "modes.jjp_pick_title", "Wonka-v03.03")
            time.sleep(2)
            files = [m["file"] for m in webui_shot.state(url)["modes"]["jjp"]["modes"]]
            print("modes:", files)
            if "2_multiball.mode" in files:
                webui_shot.api(url, "modes.jjp_open", "2_multiball.mode")
                time.sleep(2)
            groups = page.locator(".jjpm-group")
            print("groups:", groups.count(), [t.strip() for t in page.locator(".jjpm-gt").all_inner_texts()])
            groups.last.scroll_into_view_if_needed()
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, kind + "_modes_form.png"))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
