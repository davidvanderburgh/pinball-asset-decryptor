"""PAD-1479 proof shots: online co-op on the Network tab and a mode's online counts on the Modes tab's Scoring page.

    python scripts/shot_pad1479.py <repo> <out_dir> [--card <raw>] [--before]

Serves <repo> on scratch settings with a Spike 2 Godzilla card and an empty project, and shoots the Network tab
(out_dir/network.png) and a new mode's Scoring page (modes_scoring.png). After (the ticket branch) it first turns
online co-op on with the Kaiju War design and gives the mode two online counts, so both shots show them filled in.

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


def _hide_log(page):
    try:
        page.get_by_text("Hide log").first.click(timeout=3000)
    except Exception:                                            # noqa: BLE001
        pass


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    before = "--before" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    card = _arg("--card", r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
    scratch = tempfile.mkdtemp(prefix="pad1479-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:   # the card's game known
        json.dump({"input_path": card, "input_name": os.path.basename(card), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1479.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1400})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "extract")
            webui_shot.api(url, "extract.use_recent", "input", card)
            time.sleep(6)
            if not before:
                webui_shot.api(url, "network.online_example", "kaiju_war")
                webui_shot.api(url, "network.online_set", {"url": "http://203.0.113.10:8090/", "campaign": "Kaiju War",
                                                         "machine": "Dave's Godzilla LE", "key": "monster-island",
                                                         "team": "Team Godzilla"})
                webui_shot.api(url, "network.online_on", True)
            webui_shot.api(url, "ui.select_tab", "network")
            time.sleep(4)
            _hide_log(page)
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, "network.png"), full_page=True)
            if not before:                         # the Online co-op box itself, its design open
                page.get_by_text("Campaign design: teams, what counts, regions").first.click()
                time.sleep(1)
                page.get_by_text("Online co-op", exact=True).first.scroll_into_view_if_needed()
                page.evaluate("""() => { const h = [...document.querySelectorAll('.card, section, div')].find(
                    (e) => e.firstElementChild && e.firstElementChild.textContent.trim() === 'Online co-op');
                    if (h) h.scrollIntoView({block: 'start'}); }""")
                time.sleep(1)
                page.screenshot(path=os.path.join(out_dir, "network_online.png"))
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            webui_shot.api(url, "modes.new")
            time.sleep(3)
            page.get_by_role("tab", name="Scoring").first.click()
            time.sleep(2)
            if not before:
                webui_shot.api(url, "ui.set", "modes", "f:online_on_start", True)
                webui_shot.api(url, "ui.set", "modes", "f:online_count_start", "kaiju_fights")
                webui_shot.api(url, "ui.set", "modes", "f:online_on_won", True)
                webui_shot.api(url, "ui.set", "modes", "f:online_count_won", "cities_saved")
                webui_shot.api(url, "ui.set", "modes", "f:online_n_won", "1")
                time.sleep(2)
            _hide_log(page)
            page.screenshot(path=os.path.join(out_dir, "modes_scoring.png"), full_page=True)
            browser.close()
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)
    print("shots in", out_dir)


if __name__ == "__main__":
    main()
