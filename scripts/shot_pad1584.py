"""PAD-1584 proof shots: rewriting a card sends only the chunks that changed.

    python scripts/shot_pad1584.py <repo> <out_dir>

Serves <repo> (the ticket branch, or a ``git archive`` of main for the
"before" shots) on a scratch settings folder and opens the Write tab's Build /
flash dialog on a scratch 64 MB image.  Its Start first writes an EARLIER
build (the same image with three 1 MB chunks different) onto a SCRATCH FILE
standing in for the card, the way the last edit, write, test round left it,
then writes the image through the app's own flash as usual.  No real drive
is ever listed or touched.  Each chunk the card is handed is slowed a little
so the write can be seen running.

``<out_dir>/<prefix>_writing.png`` is the dialog mid-write and
``<prefix>_done.png`` the log once it finished (``PAD_SHOT_PREFIX``, default
``shot``).  Needs Playwright (PAD_PWLIB or the user site) and Edge.
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
import os, sys, time
sys.path.insert(0, %(repo)r)
os.environ["PAD_CARD_RECORD"] = %(record)r
from pinball_decryptor.core import rawdevice as rd
import pinball_decryptor.plugins.stern.pipeline as pl
from pinball_decryptor.webui import write_dialogs as wd
from pinball_decryptor.webui import host
CARD, IMAGE, EARLIER = %(card)r, %(image)r, %(earlier)r
pl.is_device_path = lambda _p: True
rd._FLASH_CHUNK = 1 << 20
_real_write = rd._FdIO.write
def _slow(self, data):
    if os.path.abspath(self.path) == os.path.abspath(CARD) and _SLOW[0]:
        time.sleep(0.25)
    return _real_write(self, data)
rd._FdIO.write = _slow
_real_read = rd.RawDeviceFile._aligned_read
def _slow_read(self, start, length):
    if self.writable and _SLOW[0] and length >= (1 << 20):
        time.sleep(0.06)
    return _real_read(self, start, length)
rd.RawDeviceFile._aligned_read = _slow_read
_SLOW = [False]
def _start(self):
    # the card as the last round left it
    rd.flash_image_to_device(EARLIER, CARD, eject=False, skip_free=False)
    _SLOW[0] = True
    self._on_flash(IMAGE, CARD)
    return True
wd.FlashDialog.start = _start
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = os.environ.get("PAD_SHOT_PREFIX", "shot")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1584-")
    project = os.path.join(scratch, "GZ 1.16 Premium Extract")
    os.makedirs(project)
    original = os.path.join(scratch, "godzilla_le-1_16_0.img")
    with open(original, "wb") as f:
        f.truncate(1 << 20)
    builds = os.path.join(scratch, "builds")
    os.makedirs(builds)
    image = os.path.join(builds, "Godzilla Premium 1.16 multi.raw")
    data = bytearray(os.urandom(64 << 20))
    with open(image, "wb") as f:
        f.write(data)
    for chunk in (5, 23, 41):
        data[chunk << 20:(chunk << 20) + 4096] = os.urandom(4096)
    earlier = os.path.join(scratch, "earlier build.raw")
    with open(earlier, "wb") as f:
        f.write(data)
    card = os.path.join(scratch, "stand-in card.dev")
    with open(card, "wb") as f:
        f.truncate(80 << 20)
    launcher = os.path.join(scratch, "launch1584.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"repo": repo, "card": card, "image": image,
                            "earlier": earlier,
                            "record": os.path.join(scratch, "cards.json")})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": project,
                       "write_original": original,
                       "write_assets": project,
                       "write_output": builds}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1360, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            webui_shot.api(url, "ui.select_tab", "write")
            time.sleep(1)
            webui_shot.api(url, "write.primary")
            time.sleep(3)
            webui_shot.api(url, "write.flash_set", "build", False)
            webui_shot.api(url, "write.flash_set", "image_path", image)
            time.sleep(1)
            webui_shot.api(url, "write.flash_start")
            shot = False
            for _ in range(240):
                st = json.dumps(webui_shot.state(url))
                if not shot and "Writing image to SD card" in st:
                    time.sleep(1.5)
                    page.keyboard.press("Escape")   # the dialog, not the write
                    time.sleep(1)
                    page.screenshot(path=os.path.join(
                        out_dir, prefix + "_writing.png"))
                    shot = True
                if "(verified)" in st:
                    break
                time.sleep(0.25)
            time.sleep(2)
            for name in ("OK", "Close"):            # Write Complete, donations
                try:
                    page.get_by_role("button", name=name, exact=True).last                         .click(timeout=3000)
                    time.sleep(1)
                except Exception:                           # noqa: BLE001
                    pass
            page.screenshot(path=os.path.join(out_dir, prefix + "_done.png"))
            print("shots in", out_dir, flush=True)
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
