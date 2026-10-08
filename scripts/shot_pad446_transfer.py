"""PAD-446 proof shot: Transfer mods carries a slot's random clips.

    python scripts/shot_pad446_transfer.py <repo> <out_dir> [--after]

Serves <repo> with two scratch projects made from videos-only extracts of the stock cards
(PAD446_PRO / PAD446_LE, default C:\\tmp\\pad446\\gzpro116 and gzle116; a few clips each, with the
manifest, baseline and extract record): a Godzilla Pro 1.16 project whose Titanosaurus intro has
a replacement and two random clips and whose end-of-ball bonus has one, and an untouched
Premium/LE 1.16 project. The Mod Pack tab's transfer runs from the Pro project onto the LE one
and the confirm dialog is photographed, under the same name before and after:

- <before_|after_>transfer_dialog.png

Before (main) the dialog counts the replacement only; the random clips are left behind without a
word. After (--after) it has a "Random clips: 2 slot(s) matched" line. The dialog is answered No.

Needs Playwright (the user site-packages one) and the installed Edge.
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
from shot_pad446 import LAUNCHER  # noqa: E402

PRO = os.environ.get("PAD446_PRO", r"C:\tmp\pad446\gzpro116")
LE = os.environ.get("PAD446_LE", r"C:\tmp\pad446\gzle116")
CLIPS = ("GodzillaVsTitanosaurus_Intro.mp4", "GodzillaVsMegalon_Intro.mp4",
         "Mecha_Multiball_Intro.mp4", "EndOfBallBonus_BackgroundLoop.mov")


def _copy(extract, dst):
    os.makedirs(os.path.join(dst, "video"))
    for name in (".extract_source.json", ".checksums.md5"):
        shutil.copy2(os.path.join(extract, name), os.path.join(dst, name))
    with open(os.path.join(extract, "video", "manifest.txt"), encoding="utf-8") as f:
        rows = [l for l in f if l.startswith("#") or l.split("\t", 1)[0] in CLIPS]
    with open(os.path.join(dst, "video", "manifest.txt"), "w", encoding="utf-8") as f:
        f.writelines(rows)
    for name in CLIPS:
        shutil.copy2(os.path.join(extract, "video", name), os.path.join(dst, "video", name))
    return dst


def _projects(scratch):
    pro = _copy(PRO, os.path.join(scratch, "GZ 1.16 Pro Custom"))
    le = _copy(LE, os.path.join(scratch, "GZ 1.16 Premium Extract"))
    mine = os.path.join(scratch, "My Godzilla clips")
    os.makedirs(mine)
    files = {}
    for name, src in (("Titanosaurus intro.mp4", "GodzillaVsTitanosaurus_Intro.mp4"),
                      ("Titanosaurus intro - take 2.mp4", "GodzillaVsMegalon_Intro.mp4"),
                      ("Titanosaurus intro - take 3.mp4", "Mecha_Multiball_Intro.mp4"),
                      ("Bonus - take 2.mov", "EndOfBallBonus_BackgroundLoop.mov")):
        shutil.copy2(os.path.join(PRO, "video", src), os.path.join(mine, name))
        files[name] = os.path.join(mine, name)
    with open(os.path.join(pro, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"video": {"video/GodzillaVsTitanosaurus_Intro.mp4": files["Titanosaurus intro.mp4"]},
                   "video_variants": {
                       "video/GodzillaVsTitanosaurus_Intro.mp4": [
                           files["Titanosaurus intro - take 2.mp4"],
                           files["Titanosaurus intro - take 3.mp4"]],
                       "video/EndOfBallBonus_BackgroundLoop.mov": [files["Bonus - take 2.mov"]]}},
                  f, indent=2)
    return pro, le


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch446t.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad446t-")
    pro, le = _projects(scratch)
    print("serving", repo, flush=True)
    proc, url = _serve(repo, scratch, le)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + "transfer_dialog.png")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "modpack")
            time.sleep(1.5)
            print("set src", api("ui.set", "modpack", "src", pro), flush=True)
            print("set dst", api("ui.set", "modpack", "dst", le), flush=True)
            time.sleep(1.5)
            # the confirm dialog is modal: the call that opens it does not return until it is
            # answered, so it is started from the page and the page is watched for the dialog
            page.evaluate("() => { window.__padRpc && 0; }")
            import threading
            threading.Thread(target=lambda: api("modpack.transfer"), daemon=True).start()
            page.wait_for_selector(".modal[aria-label='Transfer mods?']", timeout=180000)
            time.sleep(1)
            print("dialog:", page.locator(".modal[aria-label='Transfer mods?']").inner_text(), flush=True)
            page.screenshot(path=out)
            buttons = page.locator(".modal[aria-label='Transfer mods?'] button")
            for i in range(buttons.count()):
                if buttons.nth(i).inner_text().strip().lower() == "no":
                    buttons.nth(i).click()
                    break
            time.sleep(1)
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
