r"""PAD-1597 proof shots: Settings > Manage disk space with the restores' and JJP builders' leftovers in the app's Linux.

    python scripts/shot_pad1597_disk.py <app tree> <out_dir> <prefix>

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after").  The app's real
Linux is scanned: the script plants the same leftovers there each time (a Spooky Clonezilla raw image and its partclone
image, a Clonezilla restore's raw partition, a killed JJP multi-boot build's work folder) and removes them after.
Writes <prefix>disk_list.png (the list, unclipped).
"""

import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

PLANT = r"""
set -e
fallocate -l 1800M /tmp/spooky_raw_pad1597.img
fallocate -l 700M /tmp/spooky_partclone_pad1597
fallocate -l 2600M /tmp/pad_raw_pad1597.img
mkdir -p /var/tmp/pad_jjpmulti_work/chunks /var/tmp/pad_jjpmulti_work/iso0
fallocate -l 1200M /var/tmp/pad_jjpmulti_work/chunks/root.part
fallocate -l 900M /var/tmp/pad_jjpmulti_work/iso0/sys.img
"""
CLEAN = r"""rm -rf /tmp/spooky_raw_pad1597.img /tmp/spooky_partclone_pad1597 /tmp/pad_raw_pad1597.img /var/tmp/pad_jjpmulti_work; true"""

LAUNCHER = r'''
import sys
sys.path.insert(0, %(tree)r)
from pinball_decryptor.core import runtime
runtime.wsl_distro = lambda runner=None: %(distro)r    # where the leftovers were planted (scratch APPDATA hides the runtime)
from pinball_decryptor.core import host_temp
host_temp.scan = lambda *a, **k: []          # the Windows temp folder is not what this shot is about
from pinball_decryptor.webui import shellx_disk, emu_cache
shellx_disk._probes_allowed = lambda: True
emu_cache.scan_emu_cache = lambda: ([], None)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    tree, out_dir, prefix = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = os.path.join(r"C:\tmp\PAD-1597", "shot_" + prefix.strip("_"))
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch)
    sys.path.insert(0, tree)
    from pinball_decryptor.core import wsl_disk
    wsl_disk._wsl_script(CLEAN + "\n" + PLANT, timeout=300)
    launcher = os.path.join(scratch, "launch1597.py")
    with open(launcher, "w", encoding="utf-8") as f:
        from pinball_decryptor.core import runtime
        f.write(LAUNCHER % {"tree": tree, "distro": runtime.wsl_distro()})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "spooky"}, f)
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
            for _ in range(240):
                d = (webui_shot.state(url).get("shellx") or {}).get("disk") or {}
                if d and not d.get("busy") and d.get("status"):
                    break
                time.sleep(0.5)
            time.sleep(1.5)
            disk = (webui_shot.state(url).get("shellx") or {}).get("disk", {})
            print("status", disk.get("status"))
            for line in json.dumps(disk.get("rows"), indent=0).splitlines():
                if "pad1597" in line or "work" in line.lower() or "Clonezilla" in line:
                    print("  row", line.strip()[:150])
            page.add_style_tag(content=".modal .sx-tree, .modal .sx-tree * {max-height:none !important;"
                                       "height:auto !important; overflow:visible !important; flex:none !important}")
            time.sleep(0.5)
            shot = os.path.join(out_dir, prefix + "disk_list.png")
            page.locator(".modal .sx-tree").last.screenshot(path=shot)
            print("shot", shot)
            browser.close()
    finally:
        proc.terminate()
        wsl_disk._wsl_script(CLEAN, timeout=300)


if __name__ == "__main__":
    main()
