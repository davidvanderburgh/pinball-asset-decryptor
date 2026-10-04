"""PAD-360 proof shot: the Color profile tab's Adjust card after a saved profile is loaded.

    python scripts/shot_pad360.py <repo> <out_png> [--after] [--bw]

Serves <repo> on shot_pad312's scratch Godzilla project with two profile files saved in
the folder Save a copy / Load last used ("Godzilla LE.txt" saved without a name of its
own, so it says "My profile" inside, and "Black playfield.txt").  Before (main): the
overlay gets Godzilla LE's numbers as Load leaves them.  After (--after): the Saved
profiles list loads it.  With --bw the overlay is the Black and white starting point
instead.  Snaps the page.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

GODZILLA = """name = My profile
gamma = 1.12 1.25 1.40
gain = 1.00 0.98 0.95
lift = 0.02 0.02 0.02
saturation = 0.92
brightness = 1.00
contrast = 1.05
"""
DARK = """name = My profile
gamma = 1.30 1.30 1.30
gain = 1.00 1.00 1.00
lift = 0.00 0.00 0.00
saturation = 1.10
brightness = 0.95
contrast = 1.00
"""


def _serve(repo, scratch, project, folder):
    launcher = os.path.join(scratch, "launch360.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(base.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "browse_dirs": {"colour_profile": folder},
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def main():
    repo, out = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad360-")
    project = base._project(scratch)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    for name, text in (("Godzilla LE.txt", GODZILLA), ("Black playfield.txt", DARK)):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)
    proc, url = _serve(repo, scratch, project, folder)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1300})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "color")
            time.sleep(1.5)
            api("color.set_mode", "display")
            time.sleep(0.5)
            if "--bw" in sys.argv:
                api("color.preset", "bw")
            elif after:
                print("use_saved:", api("color.use_saved",
                                        os.path.join(folder, "Godzilla LE.txt")), flush=True)
            else:
                # what Load... leaves on main: the file's numbers, named "My profile"
                api("color.set_params", {"name": "My profile", "gamma": [1.12, 1.25, 1.40],
                                         "gain": [1.0, 0.98, 0.95], "lift": 0.02,
                                         "saturation": 0.92, "brightness": 1.0,
                                         "contrast": 1.05})
            time.sleep(2)
            st = webui_shot.state(url).get("color") or {}
            print("name:", st.get("name"), "preset_on:", st.get("preset_on"),
                  "saved_on:", st.get("saved_on"), flush=True)
            page.mouse.move(5, 1290)
            time.sleep(0.3)
            page.screenshot(path=out)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
