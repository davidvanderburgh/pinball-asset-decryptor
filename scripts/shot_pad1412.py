"""PAD-1412 proof shot: the JJP Modes tab takes its game from the selected card (no game drop-down).

    python scripts/shot_pad1412.py <out_dir> <before|after> [card]

Jersey Jack picked with CHAKA's LOTLJ (a Guns N' Roses LE 3.03 mod) as the selected card, the
Modes tab, top of the page. Writes <kind>_modes_card.png. Needs Playwright (the user
site-packages one) and the installed Edge; the app runs on a scratch APPDATA.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\JJP\custom\CHAKAs_LOTLJ_V1.0_GNR_LE_3.03.iso"


def main():
    out_dir = os.path.abspath(sys.argv[1])
    kind = sys.argv[2]
    card = sys.argv[3] if len(sys.argv) > 3 else CARD
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1412-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": card, "write_original": card,
                                             "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch,
                                        extra_env={"PYTHONPATH": site.getusersitepackages(),
                                                   "PAD_JJP_MODES_DIR": os.path.join(scratch, "jjp_modes")})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 820})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(4)
            print("HEAD", page.locator(".jjpm-page .pagehead").inner_text())
            print("SELECTS", page.locator(".jjpm-page .pagehead select").count())
            page.screenshot(path=os.path.join(out_dir, kind + "_modes_card.png"))
            browser.close()
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
