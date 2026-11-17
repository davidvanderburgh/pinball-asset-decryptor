"""PAD-1377 proof shots: the JJP Modes tab (Wonka 03.03) with modes started by the new start
rules.
    python scripts/shot_pad1377.py <repo> <out_dir> <before|after>
Makes two modes in a scratch mode folder (one with the starter's start switch, one started
only by game events) and writes <out_dir>/<kind>_mode_list.png (the tab: the mode list beside the
open mode's Starts rows) and <kind>_help.png (the tab's help open).  David's own mode folders
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
    scratch = tempfile.mkdtemp(prefix="pad1377-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": WONKA_ISO, "write_original": WONKA_ISO,
                                             "write_output": scratch}}}, f)
    import site
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    proc, url = webui_shot.start_server(settings, scratch,
                                        extra_env={"PYTHONPATH": site.getusersitepackages(),
                                                   "PAD_JJP_MODES_DIR": os.path.join(scratch, "jjp_modes")})
    api = lambda *a: webui_shot.api(url, *a)  # noqa: E731
    try:
        api("ui.pick_manufacturer", "jjp")
        api("ui.select_tab", "modes")
        time.sleep(2)
        api("modes.jjp_pick_title", "Wonka-v03.03")
        api("modes.jjp_new", "Golden Ticket")            # the starter picks: a start switch
        api("modes.jjp_new", "Ball Start Rush")          # only a game event starts it
        api("modes.jjp_set", "start", "")
        api("modes.jjp_set", "start_on", "ball_start multiball_end")
        api("modes.jjp_set", "start_once", "ball")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1450})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            api("ui.select_tab", "modes")
            time.sleep(2)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
            # the mode list stays in view beside the Starts rows
            page.get_by_text("Starts at most once a", exact=True).first.evaluate(
                "e => e.scrollIntoView({block: 'end'})")
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, kind + "_mode_list.png"))
            page.locator(".sx-help").first.click()
            time.sleep(2)
            tips = page.get_by_text("Making a mode", exact=True)
            if tips.count():
                tips.first.evaluate("e => e.scrollIntoView({block: 'start'})")
                time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, kind + "_help.png"))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
