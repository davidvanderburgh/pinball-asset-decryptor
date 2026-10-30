"""PAD-864 proof shots: the Color profile tab in each of its three modes
(individual files, machine screen, whole screen overlay), where the overlay
moved to a section of its own, the Machine screen preview box was added and
the "make your own profile" card (test card, AI template, load) appeared.

    python scripts/shot_pad864.py <repo> <out_dir> <prefix>

Writes <prefix>_color_files.png, <prefix>_color_machine_screen.png,
<prefix>_color_overlay.png and <prefix>_color_make_own.png (the side
column scrolled to its foot), and <prefix>_colors_bar.png (the Images
tab's Colors bar, whose tabs put the overlay last).  Serves <repo>'s app against a scratch settings
folder and an empty scratch project (Stern starts as Spike 2).
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
    repo, out_dir, prefix = sys.argv[1:4]
    scratch = tempfile.mkdtemp(prefix="pad864-")
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch864.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "theme": "dark",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    out = lambda name: os.path.join(out_dir, "%s_%s.png" % (prefix, name))
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1300})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(2.0)
            webui_shot.api(url, "ui.select_tab", "color")
            time.sleep(1.0)
            for mode, name in (("assets", "color_files"),
                               ("screen", "color_machine_screen"),
                               ("display", "color_overlay")):
                webui_shot.api(url, "color.set_mode", mode)
                time.sleep(2.5)
                page.mouse.move(5, 1250)
                page.screenshot(path=out(name))
                st = webui_shot.state(url)["color"]
                print(name, "mode", st.get("mode"), "per_file",
                      st.get("per_file"), "screen_look",
                      st.get("screen_look"), flush=True)
            # the side column's foot: Make your own profile (before: Adjust's end)
            webui_shot.api(url, "color.set_mode", "assets")
            time.sleep(2.0)
            page.evaluate("""(document.querySelector('.cp-make')
                || document.querySelector('.cp-controls'))
                .scrollIntoView({block: 'end'})""")
            time.sleep(1.0)
            page.mouse.move(5, 1250)
            page.screenshot(path=out("color_make_own"))
            # the Colors bar beside the Images tab: its tabs, overlay last
            webui_shot.api(url, "ui.select_tab", "images")
            time.sleep(2.0)
            handle = page.locator(".cpd-handle")
            if handle.count():
                handle.first.click()
                time.sleep(2.0)
                page.mouse.move(5, 1250)
                page.screenshot(path=out("colors_bar"))
            else:
                print("no Colors bar on the Images tab", flush=True)
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
