"""PAD-776 proof shot: 'Update the loaded card in place' on a card that is read-only.

    python scripts/shot_pad776.py <repo> <out.png> <card.raw> <inspect.json>

Serves <repo> on a scratch settings folder with the Multi-boot tab holding <card.raw> (a
multi-boot card mkmulticard built, read back through <inspect.json>, its `inspect --json`),
marks the card read-only, then calls Build / flash card... > Start (the update ticked), as
the buttons do: the reporter's steps.  Before PAD-776 the tools run and the inject dies on a bare
PermissionError; after, the tab names the reason before anything runs.  The card's Read-only
mark is taken off again at the end.  Needs Playwright (PAD_PWLIB or the user site) and Edge.
"""
import json
import os
import shutil
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

HOST = r'''
import json, sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.webui import multiboot_panel as mp
from pinball_decryptor.webui import host
REPORT = json.load(open(%(inspect)r))
CARD = %(card)r
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    if not getattr(self, "_pad776_done", False):
        self._pad776_done = True
        self.load_inspect(REPORT, CARD)
    return _orig(self, *a, **k)
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''


def main():
    repo, out, card, inspect = sys.argv[1:5]
    scratch = tempfile.mkdtemp(prefix="pad776-")
    launcher = os.path.join(scratch, "launch776.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo, "inspect": inspect, "card": card})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "0"})
    os.chmod(card, stat.S_IREAD)                    # the Read-only attribute
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "multiboot")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.add_init_script("try { localStorage.setItem('pad.log.open', '1'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(4)
            if os.environ.get("PAD776_DEBUG"):
                page.screenshot(path=out + ".loaded.png")
            webui_shot.api(url, "multiboot.build_flash")
            webui_shot.api(url, "multiboot.build_tick", "write", True)
            time.sleep(2)
            if os.environ.get("PAD776_DEBUG"):
                page.screenshot(path=out + ".dialog.png")
            webui_shot.api(url, "multiboot.build_start")
            for _ in range(240):                    # the before code builds the menu first
                mb = json.dumps(webui_shot.state(url).get("multiboot") or {})
                if "failed at" in mb or "Cannot update" in mb:
                    break
                time.sleep(1)
            time.sleep(3)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        os.chmod(card, stat.S_IREAD | stat.S_IWRITE)
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
