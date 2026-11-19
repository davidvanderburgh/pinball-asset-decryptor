"""PAD-1418 proof shots: the Modes tab on the other Spooky Unity titles (Halloween, Beetlejuice).

    python scripts/shot_pad1418.py <repo> <out_dir> <before|after>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of the base for the
before shots).  For each title: scratch settings with Spooky and that title's stock update in the
library selected (only read); the mode folders are the scratch settings folder's (seeded from the
title's starter modes).  Writes <out_dir>/<kind>_modes_<title>.png (the tab) and
<kind>_modes_<title>_build.png (scrolled to Check, Try it and Build).  Playwright + the installed
Edge (PAD_PWLIB: where Playwright is, if not installed).
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

CARDS = [("halloween", r"D:\Pinball\images\Spooky\code_H78.pkg"),
         ("beetlejuice", r"D:\Pinball\images\Spooky\v2026.09.15.11.beetlejuice")]


def shoot(repo, out_dir, kind, title, card):
    scratch = tempfile.mkdtemp(prefix="pad1418-")
    launcher = os.path.join(scratch, "launch.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(S.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "spooky",
                   "manufacturers": {"spooky": {"extract_input": card}}}, f)
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
            print(title, "modes tab visible:", tabs.get("modes", {}).get("visible"), flush=True)
            if tabs.get("modes", {}).get("visible"):
                webui_shot.api(url, "ui.select_tab", "modes")
                time.sleep(3)
                spk = webui_shot.state(url).get("modes", {}).get("spk") or {}
                print(" spk:", spk.get("label"), [m["name"] for m in spk.get("modes") or []],
                      (spk.get("check") or {}).get("ok"), (spk.get("build") or {}).get("note"), flush=True)
            else:
                time.sleep(2)
            out = os.path.join(out_dir, "%s_modes_%s.png" % (kind, title))
            page.screenshot(path=out)
            print(" shot", out, flush=True)
            card_el = page.locator(".jjpm-try")
            if card_el.count():
                card_el.first.evaluate("e => e.scrollIntoView({block: 'center'})")
                time.sleep(0.8)
            out = os.path.join(out_dir, "%s_modes_%s_build.png" % (kind, title))
            page.screenshot(path=out)
            print(" shot", out, flush=True)
            browser.close()
            if errors:
                print(" PAGE ERRORS:", errors, flush=True)
    finally:
        proc.terminate()


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    print("serving", repo, flush=True)
    for title, card in CARDS:
        shoot(repo, out_dir, kind, title, card)


if __name__ == "__main__":
    main()
