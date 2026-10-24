"""PAD-697 proof shots: a stock card updated on the machine reads as the game code it runs.

    python scripts/shot_pad697.py <repo> <out-dir> <prefix>

Serves <repo> on a scratch settings folder, adds two Godzilla LE cards to the Multi-boot tab
and lets the tab measure them (the same `mkmulticard.py plan` a build starts with), then
writes <out-dir>/<prefix>_multiboot.png.  The first card (PAD697_UPDATED) stands in for the
reporter's: a stock 1.16 card whose /spk/index package file still carries the 1.08 name the
card shipped with, the state an on-machine update leaves.  The second is a Heisei 1.16 build.
Before, the first row reads 1.08.0 and the tab warns the two are different game code; after,
both read 1.16.0.  Needs Playwright (PAD_PWLIB or the user site) and the installed Edge.
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
import os
from pinball_decryptor.webui import compat
_queue = os.environ["PAD697_PICKS"].split("|")
compat.filedialog.askopenfilename = lambda **k: _queue.pop(0) if _queue else ""
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''
UPDATED = os.environ.get("PAD697_UPDATED", r"C:\tmp\PAD-697\gz_le_updated_1_08_to_1_16.raw")
HEISEI = os.environ.get("PAD697_HEISEI", r"D:\Pinball\images\Stern\spike2"
                        r"\Godzilla Premium 1.16 Heisei Custom V1.5 Standard Edition.raw")


def main():
    repo, out_dir, prefix = sys.argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad697-")
    launcher = os.path.join(scratch, "launch697.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PAD697_PICKS": "|".join((UPDATED, HEISEI)),
                   "PAD_UI_NO_RIG": "0"})       # the tab must measure the card: that reads versions
    print("serving", repo, url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "multiboot")
        time.sleep(3)
        for path in (UPDATED, HEISEI):
            webui_shot.api(url, "multiboot.add_choice", "_add_image")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.add_init_script("try { localStorage.setItem('pad.log.open', '1'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            # the tab measures the card on its own; wait for both versions to be read
            mb = {}
            for _ in range(150):
                mb = webui_shot.state(url).get("multiboot") or {}
                if "1.16.0" in json.dumps(mb):
                    break
                time.sleep(2)
            time.sleep(4)
            print("multiboot state keys:", sorted(mb)[:40], flush=True)
            print("alarm =", mb.get("alarm"), flush=True)
            print("1.08.0 shown:", "1.08.0" in json.dumps(mb), "1.16.0 shown:", "1.16.0" in json.dumps(mb), flush=True)
            shot = os.path.join(out_dir, prefix + "_multiboot.png")
            page.screenshot(path=shot)
            print("shot", shot, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
