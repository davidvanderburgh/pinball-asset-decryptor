"""PAD-1354 proof shots: the JJP mode editor (Modes tab, Wonka 03.03) with its Starts group.
    python scripts/shot_pad1354.py <repo> <out_dir> <before|after>
Writes <out_dir>/<kind>_mode_editor.png (the whole mode form) and, after, the start-event
picker open (<kind>_start_events.png).  A scratch settings folder: David's own mode folders
are never touched.  Needs Playwright (PAD_PWLIB / the user site) and Edge.
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
    scratch = tempfile.mkdtemp(prefix="pad1354-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": WONKA_ISO, "write_original": WONKA_ISO,
                                             "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch,
                                        extra_env={"PYTHONPATH": site.getusersitepackages(),
                                                   "PAD_JJP_MODES_DIR": os.path.join(scratch, "jjp_modes")})
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
            # the form from its last Mode rows down: before, Sounds follows; after, Starts
            page.get_by_text("When a game mode runs", exact=True).first.evaluate(
                "e => e.scrollIntoView({block: 'start'})")
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, kind + "_mode_editor.png"))
            pick = page.locator(".jjpm-pick[data-key='start_on'] .jjpm-pick-open")
            if pick.count():
                pick.first.scroll_into_view_if_needed()
                pick.first.click()
                time.sleep(1)
                page.screenshot(path=os.path.join(out_dir, kind + "_start_events.png"))
            print("start_on field:", bool(pick.count()))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
