"""PAD-1350 proof shots: JJP custom modes in the Modes tab.

    python scripts/shot_pad1350.py <repo> <out_dir> <before|after> [--modes-dir DIR]

before: Jersey Jack picked, the rail as it is (no Modes tab on JJP).
after:  the Modes tab on JJP - the title list (every title that can run modes, from its
        port report), Wonka 03.03's mode open in the form editor, a name picker open on
        the sounds, the checker's answer, and the build box.

Writes <out_dir>/<kind>_modes.png (and, after, the extra screens). Needs Playwright (the
user site-packages one) and the installed Edge.  The app runs on a scratch APPDATA, so the
mode folders it makes are scratch ones.
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
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1350-")
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
            tabs = {t["ns"]: t for t in webui_shot.state(url)["shell"]["tabs"]}
            print("modes tab:", tabs.get("modes"))
            if kind == "before" or not tabs.get("modes", {}).get("visible"):
                page.screenshot(path=os.path.join(out_dir, kind + "_modes.png"))
                return 0
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            webui_shot.api(url, "modes.jjp_pick_title", "Wonka-v03.03")
            time.sleep(2)
            page.locator(".jjpm-page .pagehead").scroll_into_view_if_needed()
            page.screenshot(path=os.path.join(out_dir, kind + "_modes.png"))
            # the title list, open (a native <select> cannot be photographed open: its options as text)
            print("titles:", [(t["name"], t["can_run"]) for t in webui_shot.state(url)["modes"]["jjp"]["titles"]])
            # a name picker open on the start sound
            page.locator(".jjpm-pick[data-key='sound_start'] .jjpm-pick-open").first.scroll_into_view_if_needed()
            page.locator(".jjpm-pick[data-key='sound_start'] .jjpm-pick-open").first.click()
            time.sleep(0.5)
            page.locator(".jjpm-picker input").first.fill("jackpot")
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, kind + "_modes_picker.png"))
            page.keyboard.press("Escape")
            time.sleep(0.5)
            webui_shot.api(url, "modes.jjp_set", "start", "switch_target_typo")
            webui_shot.api(url, "modes.jjp_check")
            time.sleep(1.5)
            page.locator(".jjpm-build").scroll_into_view_if_needed()
            page.screenshot(path=os.path.join(out_dir, kind + "_modes_check.png"))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
