"""PAD-339 proof shots: the Color profile tab in Machine screen mode (colour ranges + curves).

    python scripts/shot_pad339.py <repo> <out_dir> <prefix> [--after]

Serves <repo> on a settings copy whose Stern project is an empty scratch folder with
a Machine screen stored, opens the Color profile tab in Machine screen mode and writes
<prefix>_color_screen.png (the whole tab).  With --after it also adds a blue colour
range and a curve point through the page's own controls first, so the shot shows
them in use, and writes <prefix>_color_ranges.png / <prefix>_color_curves.png (the
two new cards alone).

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
    after = "--after" in sys.argv[4:]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad339-")
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"screen_profile": {"name": "My screen", "gamma": [0.91, 0.83, 0.74],
                                      "gain": [1.0, 1.0, 1.0], "lift": [0.0, 0.0, 0.0],
                                      "saturation": 1.11}}, f)
    launcher = os.path.join(scratch, "launch339.py")
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
            page = browser.new_page(viewport={"width": 1600, "height": 2700 if after else 1900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "color")
            time.sleep(2)
            api("color.set_mode", "screen")
            time.sleep(2)
            if after:
                # a blue range through the page's own controls: Add, then type numbers
                add = page.locator(".cp-ranges button", has_text="Blues")
                add.click()
                time.sleep(0.8)
                for label, val in (("Hue shift value", "12"), ("Saturation value", "0.80"),
                                   ("Brightness value", "0.90")):
                    box = page.locator('.cp-ranges input[aria-label="%s"]' % label).first
                    box.fill(val)
                    box.press("Enter")
                    time.sleep(0.4)
                # a curve point on the master curve, typed in
                page.locator(".cp-curve-ed button", has_text="Add point").click()
                time.sleep(0.5)
                inp = page.locator('.cp-curve-ed input[aria-label="Point 2 input value"]')
                outp = page.locator('.cp-curve-ed input[aria-label="Point 2 output value"]')
                inp.fill("64")
                inp.press("Enter")
                outp.fill("48")
                outp.press("Enter")
                time.sleep(1.5)
                st = webui_shot.state(url).get("color") or {}
                print("stored ranges:", st.get("ranges"), flush=True)
                print("stored curves:", st.get("curves"), flush=True)
            page.screenshot(path=os.path.join(out, prefix + "_color_screen.png"), full_page=True)
            if after:
                page.locator(".cp-ranges").screenshot(
                    path=os.path.join(out, prefix + "_color_ranges.png"))
                page.locator(".cp-curve-ed").screenshot(
                    path=os.path.join(out, prefix + "_color_curves.png"))
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
