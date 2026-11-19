"""PAD-1417 proof shots: the Modes tab on a Spooky game (Scooby-Doo's custom modes).

    python scripts/shot_pad1417.py <repo> <out_dir> <before|after>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
before shots).  Scratch settings: Spooky, the Scooby-Doo 2025.12.01.09 update in the library
selected (only read).  The mode folders are the scratch settings folder's (seeded from the
title's starter modes).  Writes <out_dir>/<kind>_modes.png (the tab, a mode open) and
<kind>_modes_build.png (scrolled to Check, Try it and Build).  Before (main) Spooky has no Modes
tab: both shots show what the rail offers instead.  Playwright + the installed Edge.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Spooky\v2025.12.01.09.scooby"


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    print("serving", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad1417-")
    launcher = os.path.join(scratch, "launch.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(S.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "spooky",
                   "manufacturers": {"spooky": {"extract_input": CARD}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1150})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            tabs = {t["ns"]: t for t in webui_shot.state(url)["shell"]["tabs"]}
            print("modes tab visible:", tabs.get("modes", {}).get("visible"), flush=True)
            if tabs.get("modes", {}).get("visible"):
                webui_shot.api(url, "ui.select_tab", "modes")
                time.sleep(3)
                spk = webui_shot.state(url).get("modes", {}).get("spk") or {}
                print("spk:", spk.get("label"), [m["name"] for m in spk.get("modes") or []],
                      (spk.get("check") or {}).get("ok"), flush=True)
            else:
                time.sleep(2)
            out = os.path.join(out_dir, "%s_modes.png" % kind)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            card = page.locator(".jjpm-try")
            if card.count():
                card.first.evaluate("e => e.scrollIntoView({block: 'center'})")
                time.sleep(0.8)
            out = os.path.join(out_dir, "%s_modes_build.png" % kind)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
