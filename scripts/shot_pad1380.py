"""PAD-1380 proof shot: the Modes tab on a Stern Spike 3 card (Walking Dead Remastered LE), its mode's clip.

    python scripts/shot_pad1380.py <repo> <out.png> [--card <raw>]

Serves <repo> on a scratch project made from the Spike 3 card, sets the Stern era to Spike 3, opens the Modes tab
with one TARGET RUSH mode and shoots the window. Before (main) the mode's clip is refused (no clip route on this
title); after, the clip is offered.

Needs Playwright (the user site-packages one), the installed Edge and the card.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True   # the Modes tab is a preview
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def _real_preview_codes():
    try:
        with open(os.path.join(os.environ["APPDATA"], "pinball_decryptor", "settings.json"), encoding="utf-8") as f:
            return list(json.load(f).get("preview_codes") or [])
    except (OSError, ValueError, KeyError):
        return []


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    card = _arg("--card", r"D:\Pinball\images\Stern\spike3\walking_dead_remastered_le-0_92_0.Release.64G.sdcard-secure.raw")
    scratch = tempfile.mkdtemp(prefix="pad1380-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card), "card_version": "0.92.0"}, f)
    launcher = os.path.join(scratch, "launch1380.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}},
                   # the Spike 3 era sits behind a preview code (the reporter's app has one): reuse this PC's own,
                   # so the header's era badge reads Spike 3 as theirs did
                   "preview_codes": _real_preview_codes()}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "extract")
            webui_shot.api(url, "extract.use_recent", "input", card)
            webui_shot.api(url, "ui.set_era", "spike3")   # Stern > Spike 3, as the reporter's app was
            webui_shot.api(url, "extract.use_recent", "input", card)   # the era switch cleared the card box
            t0 = time.time()
            era = ""
            while time.time() - t0 < 90:
                time.sleep(2)
                st = webui_shot.state(url)
                era = (st.get("shell") or {}).get("era", "")
                mfr = (st.get("shell") or {}).get("mfr") or {}
                era = era or (mfr.get("era", "") if isinstance(mfr, dict) else "")
                if era == "spike3":
                    break
            tabs = (webui_shot.state(url).get("shell") or {}).get("tabs") or []
            print("tabs:", [t["ns"] for t in tabs if t.get("visible")], flush=True)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            page.locator("text=New mode").first.click(timeout=5000)
            time.sleep(2)
            page.mouse.click(1237, 672)   # Form's Choose in the New mode dialog (1500x1000 window)
            time.sleep(2)
            page.mouse.click(540, 550)    # Blank mode
            time.sleep(6)
            page.mouse.click(580, 292)    # the mode's Show tab: its screen and clip
            time.sleep(3)
            time.sleep(4)
            page.screenshot(path=out)
            print("saved", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
