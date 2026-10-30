"""PAD-844 proof shots: the gear menu (grouped, no top-level checks, the AI
agents submenu) and the Color profile tab's Machine screen mode, where the
"Files with no color profile attached skip the Machine screen" box moved.

    python scripts/shot_pad844.py <repo> <out_dir> <prefix> [<project>]

Writes <prefix>_gear_menu.png, <prefix>_ai_agents.png (when <repo> has the
submenu) and, with a Spike 2 <project>, <prefix>_color_machine_screen.png.
Serves <repo>'s app against a scratch settings folder; <repo> may be an
older tree (the before shots).
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
    project = sys.argv[4] if len(sys.argv) > 4 else ""
    scratch = tempfile.mkdtemp(prefix="pad844-")
    if not project:
        project = os.path.join(scratch, "proj")
        os.makedirs(project)
    launcher = os.path.join(scratch, "launch844.py")
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
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(2.0)
            page.get_by_role("button", name="Settings").first.click()
            time.sleep(1.2)
            page.mouse.move(700, 600)
            time.sleep(0.6)
            page.screenshot(path=out("gear_menu"))
            sub = page.locator(".menu button.mi", has_text="AI agents")
            if sub.count():
                sub.first.hover()
                time.sleep(1.2)
                page.screenshot(path=out("ai_agents"))
            page.keyboard.press("Escape")
            time.sleep(0.5)
            st = webui_shot.state(url)
            if st.get("color", {}).get("per_file") is not None:
                webui_shot.api(url, "ui.select_tab", "color")
                time.sleep(1.0)
                webui_shot.api(url, "color.set_mode", "screen")
                time.sleep(2.5)
                page.mouse.move(5, 450)
                page.screenshot(path=out("color_machine_screen"))
                print("color per_file:",
                      webui_shot.state(url)["color"].get("per_file"),
                      flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
