r"""PAD-1458 proof shots: Settings > Manage disk space after the app has given space back to Windows at a close.

    python scripts/shot_pad1458_disk.py <app tree> <out_dir> <prefix>

The PAD-819 stand-in (shot_pad819_disk.py: nothing runs in WSL, a user's C: nearly full) with the space keeper's
record written beforehand: a clean-up an hour ago, and a give-back to Windows two days ago (23.4 GiB, from the app's
Linux 88.9 -> 65.5 GB). A tree that knows the give-back says so in the automatic clean-up line; one that does not
shows the clean-up alone. Writes <prefix>disk_space_auto.png (the top: the automatic clean-up) and
<prefix>disk_space_reclaim.png (the foot: Reclaim).
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

GB = 2 ** 30


def main():
    tree, out_dir, prefix = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1458-")
    launcher = os.path.join(scratch, "launch1458.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(base.LAUNCHER % {"tree": tree})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    now = time.time()
    keeper = os.path.join(scratch, "keeper.json")
    with open(keeper, "w", encoding="utf-8") as f:
        json.dump({"checked": now - 3600, "auto": True,
                   "last": {"at": now - 3600, "freed": int(6.2 * GB), "count": 3, "room": 40 * GB, "wsl": True,
                            "removed": []},
                   "freed_total": int(6.2 * GB),
                   "giveback": {"at": now - 2 * 86400, "freed": int(23.4 * GB),
                                "disks": [{"name": "PAD-Runtime", "before": int(88.9 * GB),
                                           "after": int(65.5 * GB)}]},
                   "giveback_checked": now - 2 * 86400, "giveback_total": int(23.4 * GB)}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "",
           "PAD_SPACE_KEEPER": "0", "PAD_SPACE_STATE": keeper, "PAD_DISK_GIVEBACK": "0"}
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
                if d and not d.get("busy") and str(d.get("status", "")).startswith("No leftover"):
                    break
                time.sleep(0.5)
            time.sleep(1)
            print("auto_summary:", d.get("auto_summary"))
            shot = os.path.join(out_dir, prefix + "disk_space_auto.png")
            page.locator(".modal").last.screenshot(path=shot)
            print("shot", shot)
            page.evaluate("""() => { for (const el of document.querySelectorAll('.modal *')) {
                if (el.scrollHeight > el.clientHeight + 4) el.scrollTop = el.scrollHeight; } }""")
            time.sleep(0.5)
            shot = os.path.join(out_dir, prefix + "disk_space_reclaim.png")
            page.locator(".modal").last.screenshot(path=shot)
            print("shot", shot)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
