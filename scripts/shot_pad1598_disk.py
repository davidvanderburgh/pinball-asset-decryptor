r"""PAD-1598 proof shots: Settings > Manage disk space with the multi-boot cache folder in it.

    python scripts/shot_pad1598_disk.py <app tree> <out_dir> <prefix>

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after").  The temp
folder is a stand-in: pinball_spike2_multiboot holding what each tree left in the real run (an Alice Cooper
update planned, then planned again from a re-copy: main 2 copies, the branch 1) beside the kept Stern caches.  Nothing runs in WSL.  Writes <prefix>disk_space.png and
<prefix>disk_list.png (the list, unclipped).
"""

import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

MB = 1 << 20
LEFTOVERS = [("spike2_card_cache", 900 * MB), ("spike2_clip_cache", 120 * MB),
             ("pinball_spike2_params", 2 * MB), ("pad-scenes-a81kq2", 46 * MB), ("pad-modes-3kd9s1", 3 * MB)]
IN_USE = ("pad-scenes-live01", 12 * MB)
#: the multi-boot cache as each tree left it in the real run (C:/tmp/PAD-1598/proof.sh): Alice Cooper's update
#: planned, then planned again from a re-copy - main unpacked it twice, the branch once
GB_ = 1000 ** 3
MULTI_MAIN = [("ac-gamecode.pkg.1406216264.1790704419.zip", 1406216231),
              ("ac-gamecode.pkg.1406216264.1795657169.zip", 1406216231),
              ("ac-gamecode.pkg.9a751a60cc.1406216264.1795657169.index.json", 297063),
              ("ac-gamecode.pkg.e17288742a.1406216264.1790704419.index.json", 297063)]
MULTI_BRANCH = [("ac-gamecode.pkg.1406216264.7cce2394883c.zip", 1406216231),
                ("ac-gamecode.pkg.1406216264.7cce2394883c.index.json", 297063)]


LAUNCHER = r'''
import sys, tempfile
sys.path.insert(0, %(tree)r)
tempfile.tempdir = %(temp)r
GB = 2 ** 30
from pinball_decryptor.core import host_temp, wsl_disk
host_temp.usage = lambda: {"total": 476 * GB, "used": 431 * GB, "free": 45 * GB, "pct": 91, "drive": "C:"}
wsl_disk.available = lambda: (False, "")
wsl_disk.is_supported = lambda: False
from pinball_decryptor.webui import shellx_disk, emu_cache
shellx_disk._probes_allowed = lambda: True
emu_cache.scan_emu_cache = lambda: ([], None)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _make(temp, name, size, age_days=3):
    d = os.path.join(temp, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "data.bin"), "wb") as f:
        f.truncate(size)
    t = time.time() - age_days * 86400
    os.utime(os.path.join(d, "data.bin"), (t, t))
    os.utime(d, (t, t))
    return d


def main():
    tree, out_dir, prefix = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = os.path.join(r"C:\tmp\PAD-1598", "shot_" + prefix.strip("_"))
    shutil.rmtree(scratch, ignore_errors=True)
    temp = os.path.join(scratch, "Temp")
    os.makedirs(temp)
    for name, size in LEFTOVERS:
        _make(temp, name, size)
    live = _make(temp, IN_USE[0], IN_USE[1], age_days=2)
    mb = os.path.join(temp, "pinball_spike2_multiboot")
    os.makedirs(mb)
    with open(os.path.join(tree, "tools", "spooky_emu", "mkspkmulti.py"), encoding="utf-8") as f:
        multi = MULTI_BRANCH if "def tidy_cache" in f.read() else MULTI_MAIN
    for name, size in multi:
        with open(os.path.join(mb, name), "wb") as f:
            f.truncate(size)
    os.utime(mb, None)
    owners = os.path.join(temp, "pad_temp_owners")              # this script made it: still running
    os.makedirs(owners)
    sys.path.insert(0, tree)
    try:
        from pinball_decryptor.core import pad_temp
        started = pad_temp._started(os.getpid())
    except ImportError:
        started = None
    with open(os.path.join(owners, os.path.basename(live)), "w") as f:
        json.dump({"pid": os.getpid(), "started": started}, f)
    launcher = os.path.join(scratch, "launch1598.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree, "temp": temp})
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
            page = browser.new_page(viewport={"width": 1300, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.settings_action", "disk_space")
            for _ in range(60):
                d = (webui_shot.state(url).get("shellx") or {}).get("disk") or {}
                if d and not d.get("busy") and d.get("status"):
                    break
                time.sleep(0.5)
            time.sleep(1.5)
            shot = os.path.join(out_dir, prefix + "disk_space.png")
            page.locator(".modal").last.screenshot(path=shot)
            print("shot", shot)
            print("status", (webui_shot.state(url).get("shellx") or {}).get("disk", {}).get("status"))
            # the list with its box's height limit lifted, so every row shows (the shot only)
            page.add_style_tag(content=".modal .sx-tree, .modal .sx-tree * {max-height:none !important;"
                                       "height:auto !important; overflow:visible !important; flex:none !important}")
            time.sleep(0.5)
            shot = os.path.join(out_dir, prefix + "disk_list.png")
            page.locator(".modal .sx-tree").last.screenshot(path=shot)
            print("shot", shot)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
