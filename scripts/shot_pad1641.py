"""PAD-1641 proof shots: the Extract tab with Stern's own Spike 2 download
(``iron_maiden_le-1_18_0.spk.zip``) as the input.

    python scripts/shot_pad1641.py <repo> <package.spk.zip> <out_dir> <before|after>

Serves <repo> on scratch settings whose Stern extract input is the package and
whose project folder is a fresh scratch folder, and writes:

* ``<kind>_extract_detect.png``: the tab once the input is detected (before:
  "Spike 3 .spk package"; after: a Spike 2 update package).
* ``<kind>_extract_start.png``: ~25 s after Extract is pressed, log open
  (before: "No Spike 3 .spk key available"; after: the package unpacking and
  the extract running).  The extract is cancelled after the shot.

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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    pkg = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])
    kind = sys.argv[4]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1641-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch1641.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": pkg, "extract_output": project,
                       "write_assets": project, "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "extract")
            time.sleep(8)
            page.screenshot(path=os.path.join(out_dir, kind + "_extract_detect.png"))
            try:
                webui_shot.api(url, "extract.start")
            except Exception as e:                      # noqa: BLE001
                print("start:", e)
            time.sleep(4)
            for label in ("Show log", "Log"):
                try:
                    page.get_by_role("button", name=label).first.click(timeout=2000)
                    break
                except Exception:                       # noqa: BLE001
                    pass
            time.sleep(21)
            page.screenshot(path=os.path.join(out_dir, kind + "_extract_start.png"))
            try:
                webui_shot.api(url, "extract.cancel")
            except Exception:                           # noqa: BLE001
                pass
            time.sleep(5)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(20)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
