"""PAD-942 proof shots: the Visual Pinball tab's tables with their pictures.

    python scripts/shot_pad942.py <out_dir> [--after] [--width N] [--height N]

Serves THIS checkout on a scratch settings.json holding one preview code,
PAD802_CODE from the environment (``tools/preview_code.py issue --name x
--feature vpx``), and Stern Spike 2. Writes <before_|after_>vpx_tables.png:
the whole Visual Pinball page (the tables with - after - a picture on each
patched row), and <before_|after_>vpx_table_hover.png: the page with the
pointer on a row's picture (before: on its name, where only the words show).

The tab's state is the kit's real one on this PC (~/.pad-vpx.json, Visual
Pinball's folder, the tables folder). Needs Playwright and the installed Edge.
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
        if st.get("loaded") and not st.get("busy") and not st.get("pictures_busy"):
            return st
        time.sleep(1)
    return webui_shot.state(url).get("vpx") or {}


def main():
    out_dir = os.path.abspath(sys.argv[1])
    after = "--after" in sys.argv
    pre = "after_" if after else "before_"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad942-")
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
            print("vpx:", json.dumps({k: st.get(k) for k in ("vpx", "vpx_version", "message")}), flush=True)
            pics = st.get("pictures") or {}
            print("pictures:", json.dumps({k: (v.get("source") or v.get("error")) for k, v in pics.items()}),
                  flush=True)
            time.sleep(1.5)
            page.locator(".vpx-page").screenshot(path=os.path.join(out_dir, pre + "vpx_tables.png"))
            # the pointer on Rush's row: its picture (after), its name (before)
            row = page.locator(".vpx-table", has_text="Rush").first
            target = row.locator(".vpx-pic img") if after else row.locator(".vpx-name")
            if not target.count():
                target = row.locator(".vpx-name")
            target.hover()
            page.wait_for_selector(".tip", state="visible", timeout=10000)
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, pre + "vpx_table_hover.png"))
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
