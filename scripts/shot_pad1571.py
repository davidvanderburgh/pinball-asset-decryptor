"""PAD-1571 proof shots: the Visual Pinball tab's Cabinet row, whose cabinet
light strips (blades, else speaker lights) can now be sent to DOF.

    python scripts/shot_pad1571.py <out_dir> [--after]

Serves THIS checkout on a scratch settings.json (Stern Spike 2) and writes
<before_|after_>vpx_cabinet.png. Before: the kit's real state, read only.
After: a scratch home holding a COPY of the kit with the strips set (E200, 4
parts a side), so the row shows them, and after_vpx_strip_lines.png, the DOF
lines window; the real ~/.pad-vpx.json is never written.
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
    scratch = tempfile.mkdtemp(prefix="pad1571-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    # the kit's own record names an installed app's rig (~/.pad-vpx.json
    # `rig`); the cache check must ask THIS checkout's cardmount.sh
    rig = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu")
    env = {"PYTHONUSERBASE": userbase, "PAD_VPX_RIG": rig}
    after = "--after" in sys.argv
    if after:
        home = os.path.join(scratch, "home")
        os.makedirs(home)
        real = os.path.join(os.path.expanduser("~"), ".pad-vpx.json")
        kit = json.load(open(real, encoding="utf-8")) if os.path.isfile(real) else {}
        cab = kit.setdefault("cabinet", {})
        cab.update(dof_strips=200, strip_parts=4)
        with open(os.path.join(home, ".pad-vpx.json"), "w", encoding="utf-8") as f:
            json.dump(kit, f)
        env.update(USERPROFILE=home, HOME=home)
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"), extra_env=env)
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
            print("vpx:", json.dumps({k: st.get(k) for k in (
                "library", "message", "card_cache", "space", "space_busy")}, default=str)[:1500], flush=True)
            for t in (st.get("tables") or [])[:8]:
                print("  table:", t.get("name"), t.get("title"), t.get("card"), flush=True)
            time.sleep(1.5)
            print("lcd_on_top:", st.get("lcd_on_top"), "layout:", st.get("layout"), flush=True)
            page.locator(".vpx-top").scroll_into_view_if_needed()
            time.sleep(0.5)
            page.locator(".vpx-top").screenshot(path=os.path.join(out_dir, pre + "vpx_cabinet.png"))
            if after:
                page.get_by_text("DOF lines…").click()
                time.sleep(1.0)
                page.screenshot(path=os.path.join(out_dir, "after_vpx_strip_lines.png"))
            st = webui_shot.state(url).get("vpx") or {}
            print("cabinet:", json.dumps({k: v for k, v in (st.get("cabinet") or {}).items() if k != "screens"}, default=str)[:600], flush=True)
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
