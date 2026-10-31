"""PAD-887 proof shots: the Visual Pinball tab (Setup and Tables cards).

    python scripts/shot_pad887.py <out_dir> [--after]

Serves THIS checkout on a scratch settings.json holding one preview code,
PAD802_CODE from the environment (``tools/preview_code.py issue --name x
--feature vpx``), and Stern Spike 2. Writes <before_|after_>:

* vpx_setup.png   the Setup card: the Visual Pinball line, where the
                  minimum version now shows;
* vpx_tables.png  the Tables card: the Jurassic Park table the kit knows.

The tab's state is the kit's real one on this PC (~/.pad-vpx.json, Visual
Pinball's folder, the card folder). Needs Playwright and the installed Edge.
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
    pre = "after_" if "--after" in sys.argv else "before_"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad887-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 2200})
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
            webui_shot.api(url, "ui.select_tab", "vpx")
            deadline = time.time() + 120
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                if st.get("loaded") and not st.get("busy"):
                    break
                time.sleep(1)
            st = webui_shot.state(url).get("vpx") or {}
            print("vpx:", json.dumps({k: st.get(k) for k in (
                "vpx", "vpx_version", "vpx_min", "vpx_old", "message")}), flush=True)
            for t in st.get("tables") or []:
                print("  table:", t.get("name"), t.get("titles"), t.get("patched"), flush=True)
            time.sleep(1.5)
            cards = page.locator(".vpx-page .card")
            for i in range(cards.count()):
                c = cards.nth(i)
                txt = c.inner_text()
                if txt.startswith("Setup"):
                    c.screenshot(path=os.path.join(out_dir, pre + "vpx_setup.png"))
                elif txt.startswith("Tables"):
                    c.screenshot(path=os.path.join(out_dir, pre + "vpx_tables.png"))
            page.screenshot(path=os.path.join(out_dir, pre + "vpx_page.png"), full_page=True)
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
