"""PAD-495 proof shots: one card, several editions of the game, EDITION in the operator menu picks one.

    python scripts/shot_pad495.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Godzilla Premium/LE 1.16 project (PAD495_EXTRACT, default the Desktop's
gzho: its extract record and two of its sounds) whose sidecar names two editions, "Standard" and
"70th Anniversary". Writes, under the same names before and after:

- <before_|after_>write_tab.png       the Write tab: after, the Editions row with the names and
                                      "Name the editions..."
- <before_|after_>multiboot_menu.png  the Multi-boot tab's Menu settings: after, the "No menu: boot
                                      the edition the game's EDITION setting names" tick, ticked

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import hashlib
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
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
EXTRACT = os.environ.get("PAD495_EXTRACT", r"C:\Users\david\OneDrive\Desktop\gzho")
CARD = os.environ.get("PAD495_CARD",
                      r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
SOUNDS = ("idx0004 - music.wav", "idx0066 - music.wav")


def _project(scratch):
    dst = os.path.join(scratch, "GZ 1.16 Premium 70th Anniversary")
    os.makedirs(os.path.join(dst, "audio"))
    shutil.copy2(os.path.join(EXTRACT, ".extract_source.json"), dst)
    lines = []
    for name in SOUNDS:
        shutil.copy2(os.path.join(EXTRACT, "audio", name), os.path.join(dst, "audio", name))
        with open(os.path.join(dst, "audio", name), "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"editions": {"names": ["Standard", "70th Anniversary"]}}, f, indent=2)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch495.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project,
                                               "extract_input": CARD, "write_update": CARD}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad495-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tag = "after_" if after else "before_"
    out = lambda n: os.path.join(out_dir, tag + n)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "write")
            time.sleep(6)
            st = state().get("write") or {}
            print("write editions:", st.get("editions_cap"), st.get("editions_text"),
                  st.get("editions_note"), flush=True)
            ed = page.locator(".wr-editions").first
            if ed.count():
                ed.scroll_into_view_if_needed()
                time.sleep(0.5)
            page.screenshot(path=out("write_tab.png"))
            api("ui.select_tab", "multiboot")
            time.sleep(3)
            api("multiboot.menu_settings")
            time.sleep(2)
            box = page.locator(".mb-dlg-menu label:has-text('No menu')").first
            if box.count():
                box.click()
                time.sleep(1)
                box.scroll_into_view_if_needed()
                time.sleep(0.5)
            else:
                look = page.locator(".mb-dlg-menu legend:has-text('Look')").first
                if look.count():
                    look.scroll_into_view_if_needed()
                    time.sleep(0.5)
            print("menu summary:", (state().get("multiboot") or {}).get("menu_summary"), flush=True)
            page.screenshot(path=out("multiboot_menu.png"))
            api("multiboot.menu_cancel")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
