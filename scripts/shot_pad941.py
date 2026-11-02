"""PAD-941 proof shots: the Visual Pinball tab with its card for table authors.

    python scripts/shot_pad941.py <out_dir> [--after] [--width N] [--height N]

Serves THIS checkout on a scratch settings.json holding one preview code,
PAD802_CODE from the environment (``tools/preview_code.py issue --name x
--feature vpx``), and Stern Spike 2. Writes <before_|after_>vpx_authors.png:
the whole Visual Pinball page (setup strip, the "For table authors" card,
the tables with their Coverage column), and - after - checklist_bond.png: the
checklist sheet opened from the Bond row.

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

WIDTH = int(sys.argv[sys.argv.index("--width") + 1]) if "--width" in sys.argv else 1900
HEIGHT = int(sys.argv[sys.argv.index("--height") + 1]) if "--height" in sys.argv else 1500


def wait_idle(url, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = webui_shot.state(url).get("vpx") or {}
        if st.get("loaded") and not st.get("busy"):
            return st
        time.sleep(1)
    return webui_shot.state(url).get("vpx") or {}


def main():
    out_dir = os.path.abspath(sys.argv[1])
    after = "--after" in sys.argv
    pre = "after_" if after else "before_"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad941-")
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
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
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
            st = wait_idle(url)
            print("vpx:", json.dumps({k: st.get(k) for k in ("vpx", "vpx_version", "message", "author_titles")}),
                  flush=True)
            print("coverage:", json.dumps({k: v.get("pct") for k, v in (st.get("coverage") or {}).items()}), flush=True)
            time.sleep(1.5)
            page.locator(".vpx-page").screenshot(path=os.path.join(out_dir, pre + "vpx_authors.png"))
            if after:
                bond = next((t for t in st.get("tables") or [] if t.get("title", "").startswith("james_bond")), None)
                if bond:
                    webui_shot.api(url, "vpx.row_checklist", bond["output"])
                    st = wait_idle(url)
                    print("sheet:", json.dumps((st.get("sheet") or {}).get("summary")), flush=True)
                    page.wait_for_selector(".vpx-sheet", timeout=30000)
                    time.sleep(1)
                    page.screenshot(path=os.path.join(out_dir, "after_checklist_bond.png"))
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
