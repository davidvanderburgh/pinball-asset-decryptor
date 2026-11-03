"""PAD-959 proof shots: the Visual Pinball tab on Jersey Jack, its "More
Jersey Jack tables" card.

    python scripts/shot_pad959.py <out_dir> <home> [--after]

shot_pad952.py's server (one preview code, PAD802_CODE from the
environment), with USERPROFILE at <home>: a scratch home whose
.pad-vpx.json names an empty scratch tables folder, so every JJP catalogue
row is on the card and nothing of the person's own folder is read. Writes
<before_|after_>vpx_jjp.png: the card alone. Needs Playwright and the
installed Edge.
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

WIDTH, HEIGHT = 1900, 2000


def main():
    out_dir, home = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    pre = "after_" if "--after" in sys.argv else "before_"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    tables = os.path.join(home, "tables")
    os.makedirs(tables, exist_ok=True)
    with open(os.path.join(home, ".pad-vpx.json"), "w", encoding="utf-8") as f:
        json.dump({"tables": tables}, f)
    scratch = tempfile.mkdtemp(prefix="pad959-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase, "USERPROFILE": home,
                                                   "PAD_VPX_PICTURES": os.path.join(scratch, "pics")})
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
            webui_shot.api(url, "ui.pick_manufacturer", "jjp")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "vpx")
            deadline = time.time() + 180
            st = {}
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                if st.get("loaded") and not st.get("busy") and (st.get("catalog") or {}).get("tables"):
                    break
                time.sleep(2)
            rows = [t.get("game") for t in (st.get("catalog") or {}).get("tables") or [] if t.get("platform") == "jjp"]
            print("jjp catalogue rows: %s" % rows, flush=True)
            time.sleep(3)
            card = page.locator(".vpx-cat").first
            card.scroll_into_view_if_needed()
            card.screenshot(path=os.path.join(out_dir, pre + "vpx_jjp.png"))
            print("page errors: %s" % errors, flush=True)
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
