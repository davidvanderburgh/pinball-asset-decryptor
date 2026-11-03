"""PAD-943 proof shots: the Visual Pinball tab the moment it opens.

    python scripts/shot_pad943_load.py <out_dir> [--after] [--name vpx_load]

Serves THIS checkout on a scratch settings.json holding one preview code,
PAD802_CODE from the environment, and Stern Spike 2; selects the tab and
shoots it 0.4 s later, before the kit has answered: <before_|after_><name>.png.
PAD943_PICS names the pictures' cache folder the server runs with (the last
state seen is kept beside it): a folder with no state shows the skeleton, one
a previous run wrote shows the tables at once. The tab's state is the kit's
real one on this PC. Needs Playwright and the installed Edge.
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

WIDTH, HEIGHT = 1900, 1100


def main():
    out_dir = os.path.abspath(sys.argv[1])
    pre = "after_" if "--after" in sys.argv else "before_"
    name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else "vpx_load"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad943l-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    pics = os.environ.get("PAD943_PICS") or os.path.join(scratch, "pictures")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase, "PAD_VPX_PICTURES": pics})
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
            t0 = time.time()
            webui_shot.api(url, "ui.select_tab", "vpx")
            time.sleep(0.4)
            page.screenshot(path=os.path.join(out_dir, pre + name + ".png"))
            st = webui_shot.state(url).get("vpx") or {}
            print("at %.1f s: loaded=%s stale=%s tables=%d authors_busy=%s coverage_busy=%s" % (
                time.time() - t0, st.get("loaded"), st.get("stale"), len(st.get("tables") or []),
                st.get("authors_busy"), st.get("coverage_busy")), flush=True)
            deadline = time.time() + 180
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                if st.get("loaded") and not st.get("busy") and not st.get("authors_busy") \
                        and not st.get("coverage_busy"):
                    break
                time.sleep(0.2)
            print("all in at %.1f s" % (time.time() - t0), flush=True)
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
