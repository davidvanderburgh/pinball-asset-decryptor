"""PAD-343 proof shots: colour ranges and curves on the whole screen overlay and on
individual files, not only on the Machine screen.

    python scripts/shot_pad343.py <repo> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is an empty scratch folder, opens
the Color profile tab and, in each of "Adjust whole screen overlay" and "Adjust
individual files", sends the same sea range and curves the Machine screen takes, then
writes <prefix>_color_overlay.png and <prefix>_color_files.png.  Before the change the
page has no Color ranges or Curves card in those modes and the numbers are dropped.

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
    scratch = tempfile.mkdtemp(prefix="pad343-")
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch343.py")
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
            extras = {"ranges": [[205, 50, 30, 15, 0.8, 0.85, 0.15]],
                      "curves": {"rgb": [[0, 0], [64, 48], [255, 255]],
                                 "b": [[0, 0], [255, 230]]}}
            for mode, name in (("display", "overlay"), ("assets", "files")):
                api("color.set_mode", mode)
                time.sleep(2)
                api("color.preset", "recommended")
                time.sleep(1)
                api("color.set_params", extras)
                time.sleep(2)
                page.screenshot(path=os.path.join(out, "%s_color_%s.png" % (prefix, name)),
                                full_page=True)
                st = webui_shot.state(url).get("color") or {}
                print(mode, "shown:", st.get("name"), st.get("ranges"), st.get("curves"),
                      flush=True)
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
