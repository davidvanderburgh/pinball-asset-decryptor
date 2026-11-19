"""PAD-1448 proof shot: the Expression lights tab on a title with no cabinet lights of its own (Stranger Things LE).

    python scripts/shot_pad1448.py <repo> <out.png> [--added SPEAKERS] [--blades N] [--show]

Serves <repo> on a scratch project made from the Stranger Things LE 1.13 card (its .extract_source.json names it)
and shows the Expression lights tab. Before (main): "Nothing to light here". After: the offer to add the cabinet's
lights on a Cabinet Lights board; with --added, the lights added (the speaker rings, --blades pixels a side) on the
cabinet drawing, and with --show a show of them.

Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike2.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\stranger_things_le-1_13_0.Release.8G.sdcard.raw"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _arg(name, dflt):
    a = sys.argv[3:]
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else dflt


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    added = int(_arg("--added", "0"))
    blades = int(_arg("--blades", "0"))
    scratch = tempfile.mkdtemp(prefix="pad1448-")
    project = os.path.join(scratch, "project")
    os.makedirs(os.path.join(project, "audio"))
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.13.0"}, f)
    launcher = os.path.join(scratch, "launch1448.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "lights")
            for _ in range(90):                         # the card's program is read (cached after)
                time.sleep(1)
                if page.locator(".xl-cab").count() or page.locator(".xl-add").count() \
                        or "Nothing to light here" in page.inner_text("body"):
                    break
            if added:
                webui_shot.api(url, "lights.set_added", True, added, blades)
                for _ in range(60):
                    time.sleep(1)
                    if page.locator(".xl-cab").count():
                        break
                if "--show" in sys.argv[3:]:
                    webui_shot.api(url, "lights.new_show", "rock")
                    time.sleep(3)
            time.sleep(2)
            page.mouse.move(5, 995)
            time.sleep(1)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
