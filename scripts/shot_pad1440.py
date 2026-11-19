"""PAD-1440 proof shot: Stern's era switcher, with and without a preview code.

    python scripts/shot_pad1440.py <repo> <out_png> <project> [--codes]

Serves <repo> on <project> (a scratch folder: the capture server rewrites caches in it), picks
Stern and opens Extract. With no ``--codes`` the settings hold no preview code (every user's
copy); with ``--codes`` they hold this PC's own (David's). Before (main): no code = no SPIKE 3
pill at all; a code = SPIKE 3 with a BETA badge. After: SPIKE 3 is there for everyone, no badge.
Opens the header's era menu and writes <out_png> (the window) and <out_png minus .png>_header.png
(that menu, cropped).
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


def _real_preview_codes():
    try:
        with open(os.path.join(os.environ["APPDATA"], "pinball_decryptor", "settings.json"),
                  encoding="utf-8") as f:
            return list(json.load(f).get("preview_codes") or [])
    except (OSError, ValueError, KeyError):
        return []


def main():
    repo, out, project = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                          os.path.abspath(sys.argv[3]))
    codes = _real_preview_codes() if "--codes" in sys.argv[4:] else []
    os.makedirs(os.path.dirname(out), exist_ok=True)
    os.makedirs(project, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1440-")
    launcher = os.path.join(scratch, "launch1440.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}},
                   "preview_codes": codes}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.set_era", "spike2")
        webui_shot.api(url, "ui.select_tab", "extract")
        eras = webui_shot.state(url)["shell"]["mfr"].get("eras")
        print("codes:", len(codes), "eras:", eras, flush=True)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(4)
            page.get_by_text("Stern Pinball").first.click()     # the era + manufacturer menu
            time.sleep(1)
            page.screenshot(path=out)
            page.screenshot(path=out[:-4] + "_header.png",
                            clip={"x": 0, "y": 0, "width": 700, "height": 520})
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
