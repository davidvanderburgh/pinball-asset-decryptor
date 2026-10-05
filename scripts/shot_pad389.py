"""PAD-389 proof: the Emulate tab's colour ticks under "Apply my replaced assets on top".

    python scripts/shot_pad389.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of the commit
before it for the "before" shot). Writes <out_dir>/<prefix>_emulate.png: the Emulate tab of
a scratch Godzilla project whose replaced files carry the Recommended individual files
profile (no whole screen overlay), the opt-in ticked. No game is started.
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
CARD = (r"C:\Users\david\Documents\development\pinball-asset-decryptor\images\Stern\spike2"
        r"\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad389-")
    project = os.path.join(scratch, "Godzilla Extract")
    os.makedirs(os.path.join(project, "images"))
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "1.16"}, f)
    # the replaced pictures' switches on, the files profile left on Recommended
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"color_all_images": True}, f)
    launcher = os.path.join(scratch, "launch389.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": CARD, "emulate_overrides": True,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": ""}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    print("server", url.split("?")[0], "scratch", scratch, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1100})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(4)
            st = webui_shot.state(url).get("emulate", {})
            print("overrides", st.get("overrides"), "assets", st.get("assets"),
                  "machine_screen", st.get("machine_screen"), flush=True)
            box = page.locator(".emu-ovr").first
            try:
                box.scroll_into_view_if_needed(timeout=5000)
            except Exception as e:                    # noqa: BLE001
                print("no .emu-ovr:", e, flush=True)
            time.sleep(1)
            out = os.path.join(out_dir, "%s_emulate.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
