"""PAD-1575 proof shots: the Network tab's Score feed card, ticked with an address, and its API contract opened.

    python scripts/shot_pad1575.py <repo> <out_dir> [--card <raw>]

Serves <repo> on scratch settings with a project made from the Godzilla LE 1.16 card, its Score feed ticked with an
address and "Also during the game" ticked in the sidecar (main has no such tick and ignores it), and shoots the Score
feed card (score_feed.png) and the card with "What your server receives" opened (contract.png).

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
    card = _arg("--card", r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
    scratch = tempfile.mkdtemp(prefix="pad1575-")
    project = os.path.join(scratch, "godzilla project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card), "card_version": "1.16.0"}, f)
    sys.path.insert(0, repo)
    from pinball_decryptor.core import staged_changes
    staged_changes.save(project, {"score_feed": {"on": True, "url": "http://192.168.1.50:8080/scores",
                                                 "live": True}})
    launcher = os.path.join(scratch, "launch1575.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % (repo, scratch))
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
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "network")
            time.sleep(5)
            try:
                page.get_by_text("Hide log").first.click(timeout=3000)
            except Exception:                                    # noqa: BLE001
                pass
            time.sleep(1)
            cardel = page.locator(".net-opt", has_text="Your server's address").first
            cardel.scroll_into_view_if_needed()
            time.sleep(0.5)
            cardel.screenshot(path=os.path.join(out_dir, "score_feed.png"))
            page.get_by_text("What your server receives").first.click()
            time.sleep(1)
            box = cardel.bounding_box()                          # a tall card: the whole of it in the viewport
            page.set_viewport_size({"width": 1500, "height": int(box["height"]) + 400})
            time.sleep(1.5)
            cardel.screenshot(path=os.path.join(out_dir, "contract.png"))
            browser.close()
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)
    print("shots in", out_dir)


if __name__ == "__main__":
    main()
