r"""PAD-1596 proof shots: Settings > Manage disk space listing every temp folder the app makes.

    python scripts/shot_pad1596_disk.py <app tree> <out_dir> <prefix>

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after").  The temp
folder is a stand-in (the same leftovers each time): an old Stern build, a Spike 1 flat image, Scenes / Modes / Audio
tab scratch, a Find originals clip, a sound self-test, and one Scenes folder whose maker is still running (this
script), so the branch shows it "(in use)".  Nothing runs in WSL.  Writes <prefix>disk_space.png and <prefix>disk_list.png (the list, unclipped).
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

MB = 1 << 20
LEFTOVERS = [("spike2_King_Kong_Pro_4c1d9e2a", 420 * MB), ("spike1_q8w2x1", 310 * MB),
             ("pad_srcfind_k2j3", 64 * MB), ("pad-scenes-a81kq2", 46 * MB), ("pad-scenes-z0p3m1", 38 * MB),
             ("pad-audio-7hh2qq", 9 * MB), ("pad-modes-3kd9s1", 3 * MB), ("pad-modes-u2n8c4", 3 * MB),
             ("image_sound_selftest_w9", 2 * MB)]
IN_USE = ("pad-scenes-live01", 12 * MB)

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
    scratch = os.path.join(r"C:\tmp\PAD-1596", "shot_" + prefix.strip("_"))
    shutil.rmtree(scratch, ignore_errors=True)
    temp = os.path.join(scratch, "Temp")
    os.makedirs(temp)
    for name, size in LEFTOVERS:
        _make(temp, name, size)
    live = _make(temp, IN_USE[0], IN_USE[1], age_days=2)
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
    launcher = os.path.join(scratch, "launch1596.py")
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
