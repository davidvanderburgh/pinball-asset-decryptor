"""PAD-346 proof shots: the Color profile tab's Recommended for individual files and for
the whole screen overlay, on a project with no Machine screen of its own.

    python scripts/shot_pad346.py <repo> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is an empty scratch folder, opens
the Color profile tab and writes:

  <prefix>_color_files.png    Adjust individual files, still on its default (Recommended)
  <prefix>_color_overlay.png  Adjust whole screen overlay after picking Recommended

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
    scratch = tempfile.mkdtemp(prefix="pad346-")
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch346.py")
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

    def report(what):
        st = webui_shot.state(url).get("color") or {}
        tips = {p["key"]: p["tip"] for p in st.get("presets") or []}
        print(what, "shown:", st.get("name"), st.get("saturation"),
              st.get("ranges"), st.get("curves"), flush=True)
        print("  Recommended tip:", tips.get("recommended"), flush=True)

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 2700})
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
            api("color.set_mode", "assets")
            time.sleep(2)
            page.screenshot(path=os.path.join(out, prefix + "_color_files.png"),
                            full_page=True)
            report("files")
            api("color.set_mode", "display")
            time.sleep(1)
            api("color.preset", "recommended")
            time.sleep(2)
            page.screenshot(path=os.path.join(out, prefix + "_color_overlay.png"),
                            full_page=True)
            report("overlay")
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
