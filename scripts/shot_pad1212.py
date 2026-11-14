"""PAD-1212 proof shots: the Visual Pinball tab's Tables card for a Foo Fighters
table patched before PAD-1212 (its drops pulsed, no MOD target, no playfield sounds).

    python scripts/shot_pad1212.py <out_dir> <tables_dir> [--after]

Serves THIS checkout (run main's copy for the before shot) on a scratch
settings.json holding PAD802_CODE from the environment (``tools/preview_code.py
issue --name x --feature vpx``), and on a scratch home: a copy of the kit's
~/.pad-vpx.json whose tables folder is <tables_dir>, so David's own kit file
and tables are never read for the list or written. Writes
<before_|after_>vpx_tables.png. Needs Playwright and the installed Edge.
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
    tables = os.path.abspath(sys.argv[2])
    pre = "after_" if "--after" in sys.argv else "before_"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1212-")
    home = os.path.join(scratch, "home")
    os.makedirs(home)
    real_kit = os.path.join(os.path.expanduser("~"), ".pad-vpx.json")
    kit = json.load(open(real_kit, encoding="utf-8")) if os.path.isfile(real_kit) else {}
    kit["tables"] = tables
    with open(os.path.join(home, ".pad-vpx.json"), "w", encoding="utf-8") as f:
        json.dump(kit, f, indent=1)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase,
                                                   "USERPROFILE": home, "HOME": home})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
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
            for t in st.get("tables") or []:
                if t.get("patched"):
                    print("  table:", t.get("name"), t.get("title"), "repatch:", t.get("repatch"), flush=True)
            time.sleep(1.5)
            page.locator(".vpx-tables").screenshot(path=os.path.join(out_dir, pre + "vpx_tables.png"))
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
