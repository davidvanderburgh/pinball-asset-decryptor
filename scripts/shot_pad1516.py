"""PAD-1516 proof shot: Expression lights, New show's menu on an Iron Maiden project, with a Bond Pro project and a
Led Zeppelin project (each with shows of its own) known to the app.

    python scripts/shot_pad1516.py <repo> <out.png>

Before (main): the menu has the ready-made shows only. After: From another project lists the other projects' shows
to copy in (Led Zeppelin's show of the game's own frames greyed: it stays on its game).

Needs Playwright (the user site-packages one), the installed Edge and the cards in D:\\Pinball\\images\\Stern\\spike2.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

D = r"D:\Pinball\images\Stern\spike2"
CARDS = {"Iron Maiden LE": ("iron_maiden_le-1_18_0.Release.8G.sdcard.raw", "1.18.0"),
         "Bond Pro 1.06": ("james_bond_pro-1_06_0.Release.16G.sdcard.raw", "1.06.0"),
         "Led Zeppelin LE": ("led_zeppelin_le-1_22_0.Release.8G.sdcard.raw", "1.22.0")}
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _step(fx, ms, a, b="#000000", rate=0):
    return {"fx": fx, "ms": ms, "a": a, "b": b, "rate": rate, "blend": 0}


SHOWS = {
    "Bond Pro 1.06": [
        {"name": "Gold sweep", "slot": None, "loop": True, "blades": [],
         "speakers": [_step("sweep_up", 1500, "#ffb000"), _step("pulse", 2000, "#ffffff", "#ffb000", 500)]},
        {"name": "Red alert", "slot": None, "loop": True, "blades": [],
         "speakers": [_step("strobe", 1000, "#ff0000", "#000000", 120)]}],
    "Led Zeppelin LE": [
        {"name": "Kashmir (original)", "slot": 156, "loop": False,
         "blades": [{"fx": "game", "ms": 30000, "req": 66, "set": "original", "from": 0}],
         "speakers": [{"fx": "game", "ms": 30000, "req": 66, "set": "original", "from": 0}]},
        {"name": "Blue chase", "slot": 156, "loop": True,
         "blades": [_step("sweep_up", 1200, "#0060ff")], "speakers": [_step("sweep_up", 1200, "#0060ff")]}],
}


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad1516-")
    folders = {}
    for name, (card, ver) in CARDS.items():
        p = os.path.join(scratch, name)
        os.makedirs(os.path.join(p, "audio"))
        with open(os.path.join(p, ".extract_source.json"), "w", encoding="utf-8") as f:
            json.dump({"input_path": os.path.join(D, card), "input_name": card, "card_version": ver}, f)
        staged = {}
        if name in SHOWS:
            staged["cab_shows"] = {"shows": SHOWS[name]}
        else:
            staged["cab_shows"] = {"shows": [], "added": {"on": True, "speakers": 23, "blades": 0}}
        with open(os.path.join(p, ".staged_changes.json"), "w", encoding="utf-8") as f:
            json.dump(staged, f)
        folders[name] = p
    im = folders["Iron Maiden LE"]
    card = os.path.join(D, CARDS["Iron Maiden LE"][0])
    launcher = os.path.join(scratch, "launch1516.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "projects": [{"folder": folders[n], "manufacturer": "stern"} for n in
                                ("Iron Maiden LE", "Bond Pro 1.06", "Led Zeppelin LE")],
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": im, "write_assets": im, "write_output": scratch}}}, f)
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
            webui_shot.api(url, "ui.select_tab", "lights")
            for _ in range(120):                        # the card's program is read (cached after)
                time.sleep(1)
                if page.locator(".xl-cab").count():
                    break
            time.sleep(2)
            page.locator(".xl-list-acts button", has_text="New show").click()
            time.sleep(1.5)
            sub = page.locator(".menu .mi", has_text="From another project")
            if sub.count():
                sub.first.hover()
                time.sleep(1)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
