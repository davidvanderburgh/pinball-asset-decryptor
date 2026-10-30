"""PAD-848 proof shots: the Visual Pinball tab's Tables card and its folder.

    python scripts/shot_pad848.py <out_dir> [--after]

Serves THIS checkout (the repo this script sits in: run a copy from an export
of main for the before shots) on a scratch settings.json that holds one
preview code, PAD802_CODE from the environment (``tools/preview_code.py
issue --feature vpx``), and Stern Spike 2. Writes <before_|after_>:

* settings_menu.png  the gear menu: Preview features... is there only while
  the app has a preview to unlock (main has none);
* visual_pinball.png the Play group: main has only Emulate; the branch has
  the Visual Pinball tab, shown here (its state is the kit's real one on this
  PC: ~/.pad-vpx.json, Visual Pinball's tables folder, the card folder).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402


def main():
    out_dir = os.path.abspath(sys.argv[1])
    after = "--after" in sys.argv
    pre = "after_" if after else "before_"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad848-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    print("serving", os.path.dirname(HERE), flush=True)
    # pip --user packages (Crypto, PIL) live under the REAL APPDATA; the
    # server runs on a scratch one, so name their base or Stern does not load
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1500})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            if webui_shot.state(url)["shell"]["mfr"].get("era") != "spike2":
                webui_shot.api(url, "ui.set_era", "spike2")
                time.sleep(1)
            tabs = [t["label"] for t in webui_shot.state(url)["shell"]["tabs"] if t["visible"]]
            print("tabs shown:", tabs, flush=True)

            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(2)
            page.locator("button[aria-label='Settings']").first.click()
            time.sleep(1)
            items = webui_shot.state(url)["shell"].get("settings_items") or []
            print("gear menu:", [i.get("label") for i in items if i.get("label")], flush=True)
            page.screenshot(path=os.path.join(out_dir, pre + "settings_menu.png"))
            page.keyboard.press("Escape")
            time.sleep(0.5)

            if "Visual Pinball" in tabs:
                webui_shot.api(url, "ui.select_tab", "vpx")
                deadline = time.time() + 120
                while time.time() < deadline:
                    st = webui_shot.state(url).get("vpx") or {}
                    if st.get("loaded") and not st.get("busy"):
                        break
                    time.sleep(1)
                st = webui_shot.state(url).get("vpx") or {}
                print("vpx:", json.dumps({k: st.get(k) for k in (
                    "registered", "vpx", "library", "runtime_state", "patched", "layout", "message")}),
                    flush=True)
                for t in st.get("tables") or []:
                    print("  table:", t, flush=True)
                time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, pre + "tables.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
