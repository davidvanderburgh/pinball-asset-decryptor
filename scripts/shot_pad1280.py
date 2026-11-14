"""PAD-1280 proof shots: the Modes tab's High scores (records of your own, under the mode list).

    python scripts/shot_pad1280.py <repo> <out.png> [--dialog] [--editor]

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Godzilla LE 1.16 card (its
.extract_source.json names it) and shows the Modes tab. Before (main) there is no High scores button under the list;
after there is. --dialog adds three records through the tab's own calls and pictures the High scores dialog;
--editor pictures one record's editor (a shot-count record) instead.

Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike2.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    dialog = "--dialog" in sys.argv[3:]
    editor = "--editor" in sys.argv[3:]
    scratch = tempfile.mkdtemp(prefix="pad1280-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1280.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            if dialog or editor:
                page.get_by_role("button", name="High scores…").click()
                time.sleep(8)                       # the game's modes and audits are read off the card
                for rec in (
                        {"name": "KING OF THE MONSTERS", "description": "Most points in one King of the Monsters",
                         "mode": "game:%s" % _first_mode(url, "King"), "measure": "points", "per": "run"},
                        {"name": "BUILDING SMASHER", "description": "Buildings destroyed in one game",
                         "mode": "", "measure": "count", "per": "game",
                         "counts": _audits(url, ("BUILDING HIT", "BUILDING THRU"))},
                        {"name": "RAMP MASTER", "description": "Ramps made during Godzilla Multiball",
                         "mode": "game:%s" % _first_mode(url, "Godzilla Multiball"), "measure": "count",
                         "per": "run", "counts": _audits(url, ("LEFT RAMP", "RIGHT RAMP"))}):
                    got = webui_shot.api(url, "modes.record_save", "", rec)
                    if not got:
                        print("not saved:", rec["name"], rec.get("counts"), rec.get("mode"),
                              ((webui_shot.state(url).get("modes") or {}).get("recs") or {}).get("error"), flush=True)
                    time.sleep(1)
                time.sleep(2)
                if editor:
                    page.locator(".modes-rec-row", has_text="RAMP MASTER").get_by_role("button", name="Edit").click()
                    time.sleep(2)
                    page.locator(".modal").last.screenshot(path=out)
                else:
                    page.locator(".modal").last.screenshot(path=out)
            else:
                page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


def _state(url):
    webui_shot.api(url, "modes.records_refresh")
    return (webui_shot.state(url).get("modes") or {}).get("recs") or {}


def _first_mode(url, words):
    modes = [m for m in _state(url).get("modes") or [] if m["value"].startswith("game:")]
    for m in sorted(modes, key=lambda m: (m["label"].lower() != words.lower(), len(m["label"]))):
        if words.lower() in m["label"].lower():
            return m["value"].split(":", 1)[1]
    return ""


def _audits(url, words):
    return [a["key"] for a in _state(url).get("counts") or []
            if any(w in a["label"].upper() for w in words)][:3]


if __name__ == "__main__":
    main()
