"""PAD-1365 proof shots: The Wizard of Oz 08.02 in the JJP Modes tab.

    python scripts/shot_pad1365.py <repo> <out_dir> <before|after>

before: Wizard of Oz picked - "can't run custom modes" (no Mode class in its older engine).
after:  Wizard of Oz picked - its starter modes open in the form (the proc engine runs them).

Writes <out_dir>/<kind>_modes_woz.png.  Needs Playwright (the user site-packages one) and the
installed Edge.  The app runs on a scratch APPDATA, so the mode folders it makes are scratch ones.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

WOZ_ISO = r"D:\Pinball\images\JJP\WizardOfOz-v08.02.iso"


def main():
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1365-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": WOZ_ISO, "write_original": WOZ_ISO,
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
            webui_shot.api(url, "modes.jjp_pick_title", "WizardOfOz-v08.02")
            time.sleep(2.5)
            page.locator(".jjpm-page .pagehead").scroll_into_view_if_needed()
            page.screenshot(path=os.path.join(out_dir, kind + "_modes_woz.png"))
            print("titles:", [(t["name"], t["can_run"]) for t in webui_shot.state(url)["modes"]["jjp"]["titles"]])
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
