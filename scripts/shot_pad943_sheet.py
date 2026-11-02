"""PAD-943 proof shots: the Visual Pinball tab's "For table authors" card with
a Spike 1 title, and its checklist sheet.

    python scripts/shot_pad943_sheet.py <out_dir> [--after]

Serves THIS checkout on a scratch settings.json holding one preview code,
PAD802_CODE from the environment (``tools/preview_code.py issue --name x
--feature vpx``), and Stern Spike 2. Picks the Spike 1 title got_le on the
authors' card and opens its checklist; writes <before_|after_>vpx_authors_spike1.png:
the sheet when the title is offered (after), the authors' card alone when it
is not (before: a title the app has no device tables for is not in the list).
The tab's state is the kit's real one on this PC. Needs Playwright and the
installed Edge.
"""
import os
import json
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

WIDTH, HEIGHT = 1900, 1500
TITLE = "got_le"


def main():
    out_dir = os.path.abspath(sys.argv[1])
    pre = "after_" if "--after" in sys.argv else "before_"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad943s-")
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
            deadline = time.time() + 180
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                if st.get("loaded") and not st.get("busy") and st.get("author_titles"):
                    break
                time.sleep(1)
            st = webui_shot.state(url).get("vpx") or {}
            titles = st.get("author_titles") or []
            print("author titles: %d, %s offered: %s" % (len(titles), TITLE, TITLE in titles), flush=True)
            if TITLE in titles:
                webui_shot.api(url, "vpx.pick_author_title", TITLE)
                time.sleep(0.5)
                webui_shot.api(url, "vpx.checklist", False)
                deadline = time.time() + 120
                while time.time() < deadline:
                    st = webui_shot.state(url).get("vpx") or {}
                    if st.get("sheet") and not st.get("busy"):
                        break
                    time.sleep(1)
                sheet = (webui_shot.state(url).get("vpx") or {}).get("sheet") or {}
                print("sheet:", json.dumps(sheet.get("summary")), flush=True)
                time.sleep(1.5)
                page.screenshot(path=os.path.join(out_dir, pre + "vpx_authors_spike1.png"))
            else:
                time.sleep(1)
                page.locator(".vpx-authors").screenshot(
                    path=os.path.join(out_dir, pre + "vpx_authors_spike1.png"))
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
