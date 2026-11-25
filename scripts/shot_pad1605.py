"""PAD-1605 proof shots: Try it on the Modes tab of a JJP game.

    python scripts/shot_pad1605.py <repo> <out_dir> <before|after>

Opens Wonka 03.03 (JJP) in the Modes tab and photographs the cards under the mode editor: before,
Check is followed by the USB stick card; after, a Try it card sits between them (these modes in
the Emulate tab, on the stock ISO).  Writes <out_dir>/<kind>_jjp_try.png.  Needs Playwright (the
user site-packages one) and the installed Edge.  The app runs on a scratch APPDATA, so the mode
folder it reads is a scratch copy of the starters.
"""
import json
import os
import site
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

ISO = r"D:\Pinball\images\JJP\Wonka-v03.03.iso"


def main():
    repo, out_dir, kind = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    print("repo", repo)
    scratch = tempfile.mkdtemp(prefix="pad1605-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": ISO, "write_original": ISO,
                                             "write_output": scratch}}}, f)
    proc, url = webui_shot.start_server(settings, scratch, extra_env={
        "PYTHONPATH": site.getusersitepackages(),
        "PYTHONUSERBASE": os.path.join(os.environ["APPDATA"], "Python")})
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
            st = webui_shot.state(url)["modes"]["jjp"]
            webui_shot.api(url, "modes.jjp_open", st["modes"][0]["file"])
            webui_shot.api(url, "modes.jjp_check")
            time.sleep(2)
            print(kind, "try card:", page.locator(".jjpm-try").count(),
                  "iso:", (webui_shot.state(url)["modes"]["jjp"].get("build") or {}).get("iso"))
            page.locator(".jjpm-check").scroll_into_view_if_needed()
            page.evaluate("document.querySelector('.jjpm-check').scrollIntoView({block: 'start'})")
            time.sleep(0.8)
            page.screenshot(path=os.path.join(out_dir, "%s_jjp_try.png" % kind))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
