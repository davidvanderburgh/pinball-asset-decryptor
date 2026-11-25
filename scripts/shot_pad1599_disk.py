r"""PAD-1599 proof shots: Settings > Manage disk space with what the app left in the PC's previous Linux.

    python scripts/shot_pad1599_disk.py <app tree> <out_dir> <prefix> [--press]

The PAD-819 stand-in (shot_pad819_disk.py: the app's own Linux and Windows temp faked, nothing to clean there) with
the REAL previous-Linux section: PAD_OLD_DISTRO names a throwaway distro (made by
tools/old_distro_proof.py, never the user's own) holding what an older version of the app left behind.  Writes
<prefix>disk_space_old.png (the window's top, where the section is).  --press also presses "Remove and give the
space back…", answers Yes, waits for the removal and the disk file's compact, and writes
<prefix>disk_space_old_done.png.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad819_disk as base  # noqa: E402
import webui_shot  # noqa: E402


def _old(url):
    return ((webui_shot.state(url).get("shellx") or {}).get("disk") or {}).get("old")


def main():
    tree, out_dir, prefix = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    press = "--press" in sys.argv[4:]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1599-")
    launcher = os.path.join(scratch, "launch1599.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(base.LAUNCHER % {"tree": tree})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "",
           "PAD_SPACE_KEEPER": "0", "PAD_SPACE_STATE": os.path.join(scratch, "keeper.json"),
           "PAD_DISK_GIVEBACK": "0",
           "PAD_OLD_DISTRO": os.environ.get("PAD_OLD_DISTRO", "PAD1599-Old")}
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
            for i in range(240):        # the previous Linux has to start for its scan
                d = (webui_shot.state(url).get("shellx") or {}).get("disk") or {}
                o = d.get("old")
                if d and not d.get("busy") and d.get("old_checked") and not (o and o.get("busy")):
                    break
                if d and not d.get("busy") and "old_checked" not in d and i > 20:
                    break               # a tree without the section
                time.sleep(0.5)
            time.sleep(1)
            print("old:", json.dumps(_old(url)))
            shot = os.path.join(out_dir, prefix + "disk_space_old.png")
            page.locator(".modal").last.screenshot(path=shot)
            print("shot", shot)
            if press and _old(url):
                page.get_by_role("button", name="Remove and give the space back…").click()
                page.get_by_role("button", name="Yes", exact=True).wait_for(timeout=20000)
                time.sleep(0.8)
                shot = os.path.join(out_dir, prefix + "disk_space_old_confirm.png")
                page.locator(".modal").last.screenshot(path=shot)
                print("shot", shot)
                page.get_by_role("button", name="Yes", exact=True).click()
                time.sleep(2)
                for _ in range(1200):
                    o = _old(url) or {}
                    if not o.get("busy"):
                        break
                    time.sleep(0.5)
                time.sleep(1)
                print("old after:", json.dumps(_old(url)))
                ok = page.get_by_role("button", name="OK", exact=True)
                if ok.count():
                    shot = os.path.join(out_dir, prefix + "disk_space_old_info.png")
                    page.locator(".modal").last.screenshot(path=shot)
                    ok.click()
                    time.sleep(0.8)
                shot = os.path.join(out_dir, prefix + "disk_space_old_done.png")
                page.locator(".modal").last.screenshot(path=shot)
                print("shot", shot)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
