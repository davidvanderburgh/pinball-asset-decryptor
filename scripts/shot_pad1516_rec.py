"""PAD-1516 proof shot: Expression lights on a Bond Pro 1.06 project, with a recording of its attract speaker lights.

    python scripts/shot_pad1516_rec.py <repo> <out.png> <recording.bin> <places.json>

The project holds the recording (cab_rec/, as Record leaves it). Before (main): the tab says Bond keeps no shows of its
own and offers nothing. After: the recording is listed under Recorded, picked, and playing on the cabinet drawing.

Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike2.
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

CARD = r"D:\Pinball\images\Stern\spike2\james_bond_pro-1_06_0.Release.16G.sdcard.raw"
NAME = "James Bond 007 Pro 1.06"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo, out, rec, places = (os.path.abspath(a) for a in sys.argv[1:5])
    scratch = tempfile.mkdtemp(prefix="pad1516r-")
    project = os.path.join(scratch, "Bond Pro 1.06")
    os.makedirs(os.path.join(project, "audio"))
    os.makedirs(os.path.join(project, "cab_rec"))
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.06.0"}, f)
    shutil.copyfile(rec, os.path.join(project, "cab_rec", NAME + ".bin"))
    with open(places, encoding="utf-8") as f:
        pl = json.load(f)
    with open(os.path.join(project, "cab_rec", NAME + ".json"), "w", encoding="utf-8") as f:
        json.dump({"source": NAME, "places": [{k: p[k] for k in ("name", "lane", "side", "u")} for p in pl]}, f)
    launcher = os.path.join(scratch, "launch1516r.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "projects": [{"folder": project, "manufacturer": "stern"}],
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project, "write_output": scratch}}}, f)
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
            for _ in range(150):                        # the card's program is read (cached after)
                time.sleep(1)
                if page.locator(".xl-cab").count() and "keeps no expression light shows" in page.inner_text("body"):
                    break
            time.sleep(2)
            row = page.locator(".xl-stock .xl-li", has_text=NAME)
            if row.count():
                row.first.click()
                time.sleep(1)
                page.locator(".xl-transport button", has_text="Play").first.click()
                time.sleep(3.2)
            page.mouse.move(5, 995)
            time.sleep(0.3)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
