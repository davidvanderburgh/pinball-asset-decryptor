"""PAD-1587 proof shots: remote access on a Jersey Jack Pinball project (the Network and Write tabs).

    python scripts/shot_pad1587.py <repo> <out_dir> [--iso <iso>] [--project <dir>]

Serves <repo> on scratch settings with JJP picked, a JJP install ISO as the original and a copy of --project (else
an empty one), and shoots the Network tab (out_dir/network.png) and the Write tab (out_dir/write.png).

Needs Playwright (the user site-packages one), the installed Edge and the ISO.
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
import os, sys
sys.path.insert(0, %r)
from pinball_decryptor.core import pad_ssh_key
pad_ssh_key.KEY_DIR = os.path.join(%r, "remote_access")
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
    iso = _arg("--iso", r"D:\Pinball\images\JJP\Wonka-v03.03.iso")
    src_project = _arg("--project", "")
    scratch = tempfile.mkdtemp(prefix="pad1587-")
    project = os.path.join(scratch, "project")
    if src_project:
        shutil.copytree(src_project, project)
    else:
        os.makedirs(project)
    launcher = os.path.join(scratch, "launch1587.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % (repo, scratch))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {
                       "extract_input": iso, "write_original": iso,
                       "extract_output": project, "write_assets": project,
                       "write_output": os.path.join(scratch, "Wonka-v03.03-mod.iso")}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            try:
                page.get_by_text("Hide log").first.click(timeout=3000)
            except Exception:                                            # noqa: BLE001
                pass
            for tab, name in (("network", "network.png"), ("write", "write.png")):
                try:
                    webui_shot.api(url, "ui.select_tab", tab)
                except Exception as e:                                   # noqa: BLE001 - the tab may not exist
                    print("no %s tab: %s" % (tab, e))
                time.sleep(4)
                page.screenshot(path=os.path.join(out_dir, name), full_page=True)
                print("shot", name)
            browser.close()
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
