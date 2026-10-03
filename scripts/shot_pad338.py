"""PAD-338 proof shots: the Color profile tab sliders (full ranges, middle shades brighter to the right).

    python scripts/shot_pad338.py <repo> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is an empty scratch folder with
the Recommended whole screen profile staged, and writes <prefix>_color.png (the whole
tab) and <prefix>_color_adjust.png (the Adjust card alone).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo, out, prefix = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad338-")
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"color_profile": {"name": "Recommended", "gamma": [1.1, 1.2, 1.35],
                                     "gain": [1.0, 1.0, 1.0], "lift": [0.0, 0.0, 0.0],
                                     "saturation": 0.9}}, f)
    launcher = os.path.join(scratch, "launch338.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    print("serving", repo, flush=True)
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "color")
            time.sleep(3)
            page.screenshot(path=os.path.join(out, prefix + "_color.png"), full_page=True)
            card = page.locator(".cp-controls")
            card.screenshot(path=os.path.join(out, prefix + "_color_adjust.png"))
            print("number boxes:", page.locator(".cp-controls input[type=number]").count(),
                  flush=True)
            box = page.locator('.cp-controls input[aria-label="Contrast value"]')
            if box.count():
                box.fill("1.25")
                box.press("Enter")
                time.sleep(1.5)
                st = webui_shot.state(url).get("color") or {}
                print("typed contrast ->", st.get("contrast"), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
