"""PAD-1469 proof shots: the Modes tab's start rules, coils and lamps on Domino's (pinHeck).

    python scripts/shot_pad1469.py <repo> <out_dir> <before|after>

scripts/shot_pad1417.py's scratch server with Domino's stock update in the library selected (only
read); writes <out_dir>/<kind>_modes_starts.png (the Starts and Sounds groups),
<kind>_modes_coil_picker.png and <kind>_modes_lamp_picker.png (the coils and lamps a mode may use,
the picker open).  Before: main + PAD-1423, whose pinHeck form offered keys its runtime ignored.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Spooky\DOM_v6.zip"
#: (shot, the form group to scroll to, the button in it to open first)
SHOTS = (("modes_starts", "Starts", None), ("modes_coil_picker", "Coils", "Pick"),
         ("modes_lamp_picker", "Lamps", "Add"))


def main():
    repo, out_dir, kind = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1469-")
    launcher = os.path.join(scratch, "launch.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(S.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "spooky",
                   "manufacturers": {"spooky": {"extract_input": CARD}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1150})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            spk = webui_shot.state(url).get("modes", {}).get("spk") or {}
            print("spk:", spk.get("label"), [g["title"] for g in spk.get("groups") or []], flush=True)
            for name, title, button in SHOTS:
                g = page.locator(".jjpm-group", has=page.locator(".jjpm-gt", has_text=title))
                if g.count():
                    g.first.evaluate("e => e.scrollIntoView({block: 'start'})")
                    page.evaluate("window.scrollBy(0, -60)")
                    time.sleep(0.8)
                    if button:
                        b = g.first.get_by_role("button", name=button)
                        if b.count():
                            b.first.click()
                            time.sleep(1.0)
                out = os.path.join(out_dir, "%s_%s.png" % (kind, name))
                page.screenshot(path=out)
                print("shot", out, flush=True)
                if button:
                    page.keyboard.press("Escape")
                    time.sleep(0.5)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
