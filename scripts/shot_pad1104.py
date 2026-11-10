"""PAD-1104 proof shot: a flash whose read-back the card fails.

    python scripts/shot_pad1104.py <repo> <out.png>

Serves <repo> (the ticket branch, or a ``git archive`` of main for the
"before" shot) on a scratch settings folder and opens the Write tab's Build /
flash dialog on a scratch 1 MB image.  Its Start is swapped for a flash onto
a SCRATCH FILE standing in for the card (no real drive is ever listed or
touched), and every read-only read of that file past its first half fails
with EINVAL, the way Windows reported the reporter's card failing during the
verify.  The shot is the app with the Write Failed box up: before, a bare
'Unexpected error: [Errno 22] Invalid argument'; after, what happened and
what to do.  Needs Playwright (PAD_PWLIB or the user site) and Edge.
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
import errno, sys
sys.path.insert(0, %(repo)r)
print("PAD1104 serving", %(repo)r, flush=True)
from pinball_decryptor.core import rawdevice as rd
import pinball_decryptor.plugins.stern.pipeline as pl
from pinball_decryptor.webui import write_dialogs as wd
from pinball_decryptor.webui import host
CARD, IMAGE = %(card)r, %(image)r
pl.is_device_path = lambda _p: True
if hasattr(rd, "_READ_RETRY_PAUSE_S"):
    rd._READ_RETRY_PAUSE_S = 0.2
_real = rd.RawDeviceFile._aligned_read
def _read(self, start, length):
    if not self.writable and start + length > (1 << 19):
        raise OSError(errno.EINVAL, "Invalid argument")
    return _real(self, start, length)
rd.RawDeviceFile._aligned_read = _read
rd._VERIFY_CHUNK = 1 << 18      # so the failing read is not the first one
def _start(self):
    self._on_flash(IMAGE, CARD)
    return True
wd.FlashDialog.start = _start
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad1104-")
    project = os.path.join(scratch, "GZ 1.16 Premium Extract")
    os.makedirs(project)
    original = os.path.join(scratch, "godzilla_le-1_16_0.img")
    with open(original, "wb") as f:
        f.truncate(1 << 20)
    builds = os.path.join(scratch, "builds")
    os.makedirs(builds)
    image = os.path.join(builds, "Godzilla Premium 1.16 multi.raw")
    with open(image, "wb") as f:
        f.write(os.urandom(1 << 20))
    card = os.path.join(scratch, "stand-in card.dev")
    with open(card, "wb") as f:
        f.truncate(2 << 20)
    launcher = os.path.join(scratch, "launch1104.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"repo": repo, "card": card, "image": image})
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
            for _ in range(60):
                st = json.dumps(webui_shot.state(url))
                if "Write Failed" in st:
                    break
                time.sleep(1)
            time.sleep(2)
            page.screenshot(path=out)
            print("shot", out, os.path.getsize(out), flush=True)
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
