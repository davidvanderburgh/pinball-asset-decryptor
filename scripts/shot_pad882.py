"""PAD-882 proof shot: Play on the Visual Pinball tab, on a PC without
Microsoft's DirectX End-User Runtime (XINPUT1_3.dll).

    python scripts/shot_pad882.py <out_dir>

Serves THIS checkout on a scratch settings.json holding PAD802_CODE (a `vpx`
preview code from the environment), with PAD_VPX_SYSDIR naming an empty
folder as Windows' system folder, and presses Play on the Jaws table from the
kit's real tables folder. The check refuses before Visual Pinball is started,
so nothing opens on the desktop (it must never: see the vpx README). Writes
after_play_no_directx.png. The before is the reporter's own screenshot: on
the old code Play started VPinballX64.exe and Windows stopped it with a
"system error" box naming the DLL.

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

TABLE = "JAWS_50Th_Anniversary (PAD).vpx"


def main():
    out_dir = os.path.abspath(sys.argv[1])
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad882-")
    nodx = os.path.join(scratch, "system32")
    os.makedirs(nodx)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase,
                                                   "PAD_VPX_SYSDIR": nodx})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1400})
            page.add_init_script("try { localStorage.setItem('pad.log.open', '1'); } catch (e) {}")
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
            webui_shot.api(url, "vpx.play", TABLE)
            deadline = time.time() + 60
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                if not st.get("busy"):
                    break
                time.sleep(0.5)
            time.sleep(1.5)
            print("vpx message:", (webui_shot.state(url).get("vpx") or {}).get("message"), flush=True)
            page.screenshot(path=os.path.join(out_dir, "after_play_no_directx.png"))
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
