r"""PAD-739 proof shot: Settings > Manage disk space right after deleting cached cards.

    python scripts/shot_pad739_disk.py <app tree> <out.png>

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after"). Nothing runs
in WSL: the scan is answered with a stand-in modelled on the reporter's Discord screenshot - his Ubuntu distro disk
(226 GB on Windows), the three cards left in ~/cardcache plus two he deleted - and Clean all "deletes" by size only.
The shot is the window after the delete, with its status line and the Reclaim section under it.
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
sys.path.insert(0, %(tree)r)
GB = 2 ** 30
from pinball_decryptor.core import host_temp, wsl_disk
host_temp.usage = lambda: {"total": 1000 * GB, "used": 820 * GB, "free": 180 * GB, "pct": 82, "drive": "C:"}
host_temp.scan = lambda: []
wsl_disk.available = lambda: (True, "")
wsl_disk.usage = lambda: {"total": 1007 * GB, "used": 196 * GB, "free": 811 * GB, "pct": 19}
wsl_disk.scan_staging = lambda: []
wsl_disk.scan_rigs = lambda: []
wsl_disk.vhdx_info = lambda: {"distro": "Ubuntu", "path": r"C:\Users\simon\AppData\Local\Packages\Ubuntu\LocalState\ext4.vhdx",
                              "size": 226 * GB, "reclaimable": 30 * GB}
from pinball_decryptor.webui import shellx_disk, emu_cache
shellx_disk._probes_allowed = lambda: True
from pinball_decryptor.core import admin
admin.is_admin = lambda: True        # the confirm only shows to an Administrator
CARDS = [("Godzilla Premium 1.16 Heisei Custom V1.96 Standard Edition", 10.66, "last booted 2026-10-17 15:59"),
         ("Godzilla Premium 1.16 Heisei Custom V1.96 TEST", 10.66, "last booted 2026-10-14 12:57"),
         ("Godzilla Premium 1.16 Heisei Custom V2 Kaiju Edition", 7.99, "last booted 2026-10-26 13:40")]
def scan():
    ents = [{"path": l, "size": int(g * GB), "manufacturer": "Stern Spike 2", "detail": l + "   " + b}
            for l, g, b in CARDS]
    return ents, {"total": 1007 * GB, "used": 196 * GB, "free": 811 * GB, "pct": 19,
                  "dir": "/home/simon/cardcache"}
emu_cache.scan_emu_cache = scan
emu_cache.drop_emu_cache = lambda labels, sizes: sum(sizes.get(l, 0) for l in labels)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    tree, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    confirm = "--reclaim-confirm" in sys.argv[3:]     # shoot Reclaim's confirm instead (answered No)
    scratch = tempfile.mkdtemp(prefix="pad739d-")
    launcher = os.path.join(scratch, "launch739d.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "",
           "PAD_SPACE_KEEPER": "0", "PAD_SPACE_STATE": os.path.join(scratch, "keeper.json")}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env, app_cmd=[sys.executable, launcher])
    print("tree", tree)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1300, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.settings_action", "disk_space")
            for _ in range(60):
                d = (webui_shot.state(url).get("shellx") or {}).get("disk") or {}
                if d and not d.get("busy") and d.get("rows"):
                    break
                time.sleep(0.5)
            import threading
            if confirm:
                threading.Thread(target=webui_shot.api, args=(url, "shellx.disk_reclaim"), daemon=True).start()
                page.get_by_role("button", name="No", exact=True).wait_for(timeout=20000)
                time.sleep(1)
                page.locator(".modal").last.screenshot(path=out)
                print("shot", out)
                page.get_by_role("button", name="No", exact=True).click()
                browser.close()
                return
            # Clean all, and answer its confirm on the page as a person would
            threading.Thread(target=webui_shot.api, args=(url, "shellx.disk_clean", None, "all"),
                             daemon=True).start()
            page.get_by_role("button", name="Yes").click(timeout=20000)
            for _ in range(60):
                d = (webui_shot.state(url).get("shellx") or {}).get("disk") or {}
                if (d.get("status") or "").startswith("Freed"):
                    break
                time.sleep(0.5)
            time.sleep(1.5)
            print("status:", d.get("status"))
            print("reclaim:", d.get("reclaim_note") or (d.get("view") or {}).get("reclaim_note"))
            page.locator(".modal").last.screenshot(path=out)
            print("shot", out)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
