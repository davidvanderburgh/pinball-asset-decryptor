"""PAD-1382 round 4 proof shots: the Service menu tab on projects whose card is gone, and on a dot-matrix menu game.

    python scripts/shot_pad1382_cards.py <repo> <out_dir> <before|after> <gone|aero>

gone: a Godzilla LE 1.16 project whose recorded card no longer exists (David's case: "The card image could not be
opened ... No such file or directory"), with another card of the same game known to the app's settings.
aero: an Aerosmith LE 1.16 project (the older dot-matrix Standard Adjustments menu) with four settings of its own.
Writes <out_dir>/<kind>_service_menu_<case>.png. Playwright + the installed Edge; the app on a scratch APPDATA."""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = r"D:\Pinball\images\Stern\spike2"
GZ = os.path.join(LIB, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
AERO = os.path.join(LIB, "foo_fighters_le-1_04_0.Release.16G.sdcard.raw")   # a dot-matrix menu game with handicaps


def make_project(root, case):
    project = os.path.join(root, "My project")
    os.makedirs(project, exist_ok=True)
    card = os.path.join(root, "moved away", "Godzilla Premium 1.16 Heisei Custom.raw") if case == "gone" else AERO
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card), "card_version": "1.16.0" if case == "gone" else "1.04.0",
                   "stock": {"sidx": ("godzilla_le-1_16_0.sidx" if case == "gone" else "foo_fighters_le-1_04_0.sidx"),
                             "status": "unknown", "label": "", "text": ""}}, f)
    side = {"coop_play": {"on": True, "menu": True}, "handicap": {"on": True}}
    if case == "gone":
        side["service_menu"] = {"custom": [{"name": "Dark Screens", "values": ["Off", "On"], "default": 1}]}
    else:
        side = {"handicap": {"on": True}}
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump(side, f)
    return project


def main():
    repo, out_dir, kind, case = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3], sys.argv[4]
    sys.path.insert(0, os.path.join(repo, "scripts"))
    import webui_shot  # noqa: E402
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1382c-")
    project = make_project(scratch, case)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_input": GZ, "write_original": GZ,
                                               "extract_output": project, "write_assets": project}}}, f)
    import site
    os.chdir(repo)
    proc, url = webui_shot.start_server(settings, scratch, extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "svcmenu")
            end = time.time() + 240
            while time.time() < end:
                s = webui_shot.state(url).get("svcmenu") or {}
                if s.get("menu") or s.get("why"):
                    break
                time.sleep(1)
            print("why:", s.get("why"), "source:", (s.get("menu") or {}).get("source"))
            time.sleep(2)
            if case == "aero" and kind == "after":
                rows = page.locator(".sm-hero .sm-dmd-row.ours")
                if rows.count():
                    rows.first.click()
                    time.sleep(0.5)
            page.screenshot(path=os.path.join(out_dir, "%s_service_menu_%s.png" % (kind, case)))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
