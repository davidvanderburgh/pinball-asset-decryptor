"""PAD-1136 proof shot: the Visual Pinball tab in a copy of the app with NO preview code.

    python scripts/shot_pad1136.py <repo> <out_png> <project>

Serves <repo> on <project> (a scratch folder: the capture server rewrites caches inside it) with a
settings.json that holds no preview codes, picks Stern and opens the Visual Pinball tab if the rail
offers it, else the Emulate tab beside where it would be. Before: the rail has no Visual Pinball
(a preview code was needed). After: it is there and opens, with no code.
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
    repo, out, project = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                          os.path.abspath(sys.argv[3]))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1136-")
    launcher = os.path.join(scratch, "launch1136.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}},
                   "preview_codes": []}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if webui_shot.state(url)["shell"]["mfr"].get("era") != "spike2":
            webui_shot.api(url, "ui.set_era", "spike2")
        tabs = webui_shot.state(url)["shell"]["tabs"]
        shown = [t["label"] for t in tabs if t["visible"]]
        has_vpx = "Visual Pinball" in shown
        print("visible tabs:", shown, flush=True)
        webui_shot.api(url, "ui.select_tab", "vpx" if has_vpx else "emulate")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(4)
            page.screenshot(path=out)
            print("shot", out, "visual pinball tab:", has_vpx, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
