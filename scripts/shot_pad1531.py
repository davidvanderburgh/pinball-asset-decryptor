"""PAD-1531 proof shots: a shared image must not carry the builder's remote access.

    python scripts/shot_pad1531.py <repo> <out_dir> [--card <raw>]

Serves <repo> on scratch settings with a stock card and an empty project, where the card's remote access is a
stand-in that already lets ANOTHER person's computer in (an image someone built with remote access on and shared),
then shoots the Network tab (out_dir/network.png) and the Write tab (out_dir/write.png).  Before (main) the Network
tab copies that stranger's key into the project's key box and nothing warns; after, it names the stranger with a
Take it off button and offers Build for sharing, and the Write tab says what the card would let in.

Needs Playwright (the user site-packages one), the installed Edge and the card.
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

STRANGER = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOv0pbuHq3ZrW0yZ8cQ0KXy3d3s0E4lJbqk8mJ1yq2Wm "
            "builder@far-away")

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
import os
from pinball_decryptor.core import pad_ssh_key, ssh_card
pad_ssh_key.KEY_DIR = os.path.join(%r, "remote_access")
_real = ssh_card.inspect_image
def _inspect(path, *a, **k):
    # stand-in: the original already lets another person's computer in
    return dict(supported=True, reason="", platform="stern-spike2", enabled=True, public_keys=%r + "\n",
                partition=(2, 0x83, 0, 0))
ssh_card.inspect_image = _inspect
from pinball_decryptor.core import drives
drives.list_physical_drives = lambda: [drives.PhysicalDrive("\\.\PhysicalDrive3", "Generic SD/MMC",
                                                            7948206080, "USB")]
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    os.makedirs(out_dir, exist_ok=True)
    card = _arg("--card", r"D:\Pinball\images\Stern\spike2\deadpool_le-1_16_0.Release.8G.sdcard.raw")
    scratch = tempfile.mkdtemp(prefix="pad1531-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    open(os.path.join(project, ".checksums.md5"), "w").close()
    launcher = os.path.join(scratch, "launch1531.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % (repo, scratch, STRANGER))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "network")
            time.sleep(4)
            try:
                page.get_by_text("Hide log").first.click(timeout=3000)
            except Exception:                                            # noqa: BLE001
                pass
            # the Advanced key box open, so the shot shows what the project would save
            try:
                page.get_by_text("Advanced: let your own SSH programs in too").first.click(timeout=3000)
            except Exception:                                            # noqa: BLE001
                pass
            time.sleep(1)
            card_box = page.locator(".net-opt", has_text="Set up remote access on this card").first
            card_box.screenshot(path=os.path.join(out_dir, "network.png"))
            webui_shot.api(url, "ui.select_tab", "write")
            time.sleep(5)
            page.screenshot(path=os.path.join(out_dir, "write.png"), full_page=False)
            print("saved", out_dir, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
