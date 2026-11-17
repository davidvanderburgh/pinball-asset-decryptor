"""PAD-1375 proof shots: Write to USB stick on the JJP Modes tab.

    python scripts/shot_pad1375.py <repo> <out_dir> <before|after>

Wonka 03.03 picked in the Modes tab, scrolled to the bottom of the page: before, the Build
card is the only way out; after, the Write to USB stick card above it, a scratch folder as the
stick, an install stick written (the runtime built from the stock ISO in the app's Linux), the
status line and the steps at the machine.  Writes <out_dir>/<kind>_modes_usb.png.  Needs
Playwright (the user site-packages one) and the installed Edge; the app runs on a scratch
APPDATA (scripts/webui_shot.py).
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

WONKA_ISO = r"D:\Pinball\images\JJP\Wonka-v03.03.iso"


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1375-")
    stick = os.path.join(scratch, "USB stick")
    os.makedirs(stick)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "jjp_modes": {"label": "Wonka-v03.03", "iso": {"Wonka-v03.03": WONKA_ISO}},
                   "manufacturers": {"jjp": {"extract_input": WONKA_ISO, "write_original": WONKA_ISO,
                                             "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch,
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            webui_shot.api(url, "modes.jjp_pick_title", "Wonka-v03.03")
            webui_shot.api(url, "modes.jjp_set_iso", WONKA_ISO)
            time.sleep(1)
            if kind == "after":
                webui_shot.api(url, "modes.jjp_set_stick", stick)
                webui_shot.api(url, "modes.jjp_write_stick")
                end = time.time() + 1500
                while time.time() < end:
                    k = webui_shot.state(url)["modes"]["jjp"].get("stick") or {}
                    if k.get("done"):
                        break
                    time.sleep(1)
                print("stick:", k.get("ok"), k.get("msg"))
                print("on the stick:", sorted(os.path.relpath(os.path.join(d, f), stick)
                                              for d, _s, fs in os.walk(stick) for f in fs))
            time.sleep(1.5)
            page.evaluate("() => { const m = document.querySelector('.jjpm-build');"
                          " m && m.scrollIntoView({block: 'end'}); }")
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, kind + "_modes_usb.png"))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
