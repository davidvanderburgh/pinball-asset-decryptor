"""PAD-1325 proof shots: editions on a Stern Spike 3 project and Multi-boot card, before and after.

    python scripts/shot_pad1325.py <repo> <out_png> <project> write|multiboot

Serves <repo> on <project> (a Spike 3 extract whose .extract_source.json names the card, with two
editions named in its .staged_changes.json), switches Stern to the Spike 3 era, then

- ``write``      the Write tab: before, no Editions row on a Spike 3 project; after, the row with
                 the editions and where EDITION lands in the operator menu
- ``multiboot``  the Multi-boot tab's Menu settings dialog: before, no editions tick on Spike 3;
                 after, the tick

Needs Playwright (the user site-packages one) and the installed Edge.
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
    repo, out_png, project, mode = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                                    os.path.abspath(sys.argv[3]), sys.argv[4])
    with open(os.path.join(project, ".extract_source.json"), encoding="utf-8") as f:
        card = json.load(f)["input_path"]
    scratch = tempfile.mkdtemp(prefix="pad1325-")
    launcher = os.path.join(scratch, "launch1325.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    # Spike 3 is a preview feature: the user's own codes switch it on in the scratch copy
    codes = []
    real = os.path.join(os.environ.get("APPDATA", ""), "pinball_decryptor", "settings.json")
    if os.path.isfile(real):
        with open(real, encoding="utf-8") as f:
            codes = json.load(f).get("preview_codes") or []
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "preview_codes": codes,
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": os.path.join(scratch, "out.raw")}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        print("era:", webui_shot.api(url, "ui.set_era", "spike3"), flush=True)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            # the page's own load may put the era back: set it again (False = it already was)
            print("era after load:", webui_shot.api(url, "ui.set_era", "spike3"), flush=True)
            page.reload()
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            print("pill:", page.locator("text=/SPIKE [23]/").all_inner_texts()[:2], flush=True)
            if mode == "write":
                webui_shot.api(url, "ui.select_tab", "write")
                time.sleep(6)
                row = page.locator(".wr-editions")
                print("editions row:", row.count(), row.all_inner_texts(), flush=True)
                if row.count():
                    row.first.scroll_into_view_if_needed()
                    time.sleep(1)
            else:
                webui_shot.api(url, "ui.select_tab", "multiboot")
                time.sleep(4)
                for key in ("multiboot.set_platform",):
                    try:
                        print(key, webui_shot.api(url, key, "s3"), flush=True)
                    except Exception as e:                   # noqa: BLE001
                        print(key, "not callable:", e, flush=True)
                time.sleep(2)
                webui_shot.api(url, "multiboot.menu_settings")
                time.sleep(3)
                tick = page.locator("text=Editions").first
                print("editions tick:", page.locator("text=EDITION").count(), flush=True)
                if tick.count():
                    tick.scroll_into_view_if_needed()
                    time.sleep(1)
            page.screenshot(path=out_png)
            print("page errors:", errors, flush=True)
            browser.close()
        print("shot", out_png, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
