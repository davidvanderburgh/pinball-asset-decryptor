"""PAD-1610 proof shot: a table row's checklist sheet now lists every DOF
event the patched table sends and what it is.

    python scripts/shot_pad1610.py <out_dir> [--after]

Serves THIS checkout on a scratch settings.json (Stern Spike 2), opens the
first Deadpool row's checklist and writes <before_|after_>vpx_dof_events.png
(the sheet scrolled to its Lights/DOF part). Reads the kit's real state;
changes nothing.
Needs Playwright and the installed Edge.
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
    scratch = tempfile.mkdtemp(prefix="pad1610-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    # the kit's own record names an installed app's rig (~/.pad-vpx.json
    # `rig`); the cache check must ask THIS checkout's cardmount.sh
    rig = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase, "PAD_VPX_RIG": rig,
                                                   "PAD1610_TABLE": os.environ.get("PAD1610_TABLE", "")},
                                        app_cmd=([sys.executable, os.environ["PAD1610_WRAP"]]
                                                 if os.environ.get("PAD1610_WRAP") else None))
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1250})
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
            # the page, then its slow parts (the authors' titles, the cache
            # check over WSL): up to two minutes
            deadline = time.time() + 180
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                if st.get("loaded") and not st.get("busy") and not st.get("authors_busy") \
                        and not st.get("space_busy"):
                    break
                time.sleep(1)
            st = webui_shot.state(url).get("vpx") or {}
            row = next((t for t in st.get("tables") or [] if "deadpool" in (t.get("output") or "").lower()), None)
            print("row:", row and row.get("output"), flush=True)
            if os.environ.get("PAD1610_TABLE"):
                # the tab's own route: Check a table, the dialog answered by the wrapper
                print("pick:", webui_shot.api(url, "vpx.pick_author_title", "deadpool_pro"), flush=True)
                webui_shot.api(url, "vpx.checklist", True)
            else:
                webui_shot.api(url, "vpx.row_checklist", row["output"])
            deadline = time.time() + 300
            while time.time() < deadline and not (webui_shot.state(url).get("vpx") or {}).get("sheet"):
                time.sleep(1)
            sheet = (webui_shot.state(url).get("vpx") or {}).get("sheet") or {}
            print("sheet:", sheet.get("map"), sheet.get("dof_rom"), len(sheet.get("dof") or []), flush=True)
            time.sleep(1.5)
            h = page.locator(".vpx-sheet h3", has_text="DOF events")
            if h.count():
                h.first.scroll_into_view_if_needed()
                page.evaluate("document.querySelectorAll('.vpx-sheet h3').forEach(e => { if (/DOF events/.test(e.textContent)) e.scrollIntoView({block: 'start'}); })")
            time.sleep(0.8)
            page.screenshot(path=os.path.join(out_dir, pre + "vpx_dof_events.png"))
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
