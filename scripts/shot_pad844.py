"""PAD-844 proof shot: the gear menu's "Let AI agents control PAD" (and,
with --agent, what ticking it shows: the MCP config to paste).

    python scripts/shot_pad844.py <repo> <out_png> [--agent <out2_png>]

Serves <repo>'s app against a scratch settings folder; <repo> may be an
older tree (the before shot) that has no such row.
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
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo, out_png = sys.argv[1:3]
    agent_png = sys.argv[sys.argv.index("--agent") + 1] \
        if "--agent" in sys.argv else ""
    scratch = tempfile.mkdtemp(prefix="pad844-")
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch844.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "theme": "dark",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1.5)
            page.get_by_role("button", name="Settings").first.click()
            time.sleep(1.2)
            row = page.get_by_text("Let AI agents control PAD")
            target = row.first if row.count() else page.get_by_text(
                "Files with no color profile attached").first
            target.hover()
            time.sleep(1.5)
            page.screenshot(path=out_png)
            print("row present:", bool(row.count()), flush=True)
            if agent_png and row.count():
                row.first.click()
                time.sleep(2.0)
                page.screenshot(path=agent_png)
                link = os.path.join(scratch, "cfg", "pinball_decryptor",
                                    "agent.json")
                print("link written:", os.path.isfile(link), flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
