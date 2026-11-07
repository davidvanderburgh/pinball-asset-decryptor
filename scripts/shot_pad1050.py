"""PAD-1050 proof shots: a file of modes opened on the Mod Pack tab.

    python scripts/shot_pad1050.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Godzilla LE 1.16 extract made here and opens the
modes file David posted (PAD1050_ZIP, default
C:\\tmp\\gz_post_stage\\daveyvandy Godzilla modes v38 (load in PAD Modes tab).zip)
with Mod Pack > Import, then points Transfer's old extract at that file
unzipped.  Writes, under the same names before and after:

- <before_|after_>import_modes_zip.png    what Import says about the file
- <before_|after_>transfer_modes_folder.png   what Transfer says about the folder
- after_import_loaded.png   (after run) Yes pressed: the Modes tab's
                            own report of the modes it loaded

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import sys
import tempfile
import threading
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

ZIP = os.environ.get("PAD1050_ZIP", r"C:\tmp\gz_post_stage\daveyvandy Godzilla modes v38 "
                                    r"(load in PAD Modes tab).zip")
CARD = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"

LAUNCHER = r'''
import os, sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import dialogs
# the Import button's file picker answers with the modes file, as a drop does
_take = dialogs.Dialogs._take_drop
def _pick(self, mode="open"):
    got = _take(self, mode)
    if got is None and mode == "open" and os.environ.get("PAD1050_PICK"):
        return [os.environ["PAD1050_PICK"]]
    return got
dialogs.Dialogs._take_drop = _pick
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _project(scratch):
    dst = os.path.join(scratch, "godzilla_le_116")
    os.makedirs(os.path.join(dst, "audio"))
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input": os.path.join(scratch, CARD), "input_name": CARD}, f)
    lines = []
    for i in range(3):
        name = "idx%04d.wav" % i
        with open(os.path.join(dst, "audio", name), "wb") as f:
            f.write(b"RIFF" + bytes(40))
        lines.append("audio/%s\t%s\n" % (name, "0" * 32))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    return dst


def _unzipped(scratch):
    """The modes file unzipped the way the reporter had it (settings only: the
    clips and sounds are not what Transfer looks at)."""
    dst = os.path.join(scratch, "Godzilla modes v38 - Premium-LE 1.16 mod pack")
    with zipfile.ZipFile(ZIP) as z:
        for n in z.namelist():
            if n.endswith((".json", ".c", ".h")):
                z.extract(n, dst)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch1050.py")
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
        extra_env={"PYTHONPATH": site.getusersitepackages(), "PAD1050_PICK": ZIP})


def _modal_text(page):
    try:
        return page.locator(".modal").last.inner_text(timeout=2000)
    except Exception:                                       # noqa: BLE001
        return ""


def _wait_modal(page, limit=60):
    deadline = time.time() + limit
    while time.time() < deadline:
        if page.locator(".modal").count():
            time.sleep(1)
            return _modal_text(page)
        time.sleep(0.5)
    return ""


def _close(page, *names):
    for name in names:
        b = page.locator(".modal").last.get_by_role("button", name=name, exact=True)
        if b.count():
            b.first.click()
            time.sleep(1)
            return name
    page.keyboard.press("Escape")
    time.sleep(1)
    return None


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1050-")
    project = _project(scratch)
    folder = _unzipped(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '1'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "modpack")
            time.sleep(2)

            threading.Thread(target=lambda: api("modpack.import_pack"), daemon=True).start()
            print("import says:\n" + _wait_modal(page), flush=True)
            page.screenshot(path=out("import_modes_zip.png"))
            print("shot", out("import_modes_zip.png"), flush=True)
            if after and _close(page, "Yes") == "Yes":
                print("loaded says:\n" + _wait_modal(page, 240), flush=True)
                page.screenshot(path=os.path.join(out_dir, "after_import_loaded.png"))
                print("shot", os.path.join(out_dir, "after_import_loaded.png"), flush=True)
                _close(page, "OK")
                print("modes now:", sorted(os.listdir(os.path.join(project, "modes")))
                      if os.path.isdir(os.path.join(project, "modes")) else None, flush=True)
            else:
                _close(page, "OK", "Cancel")

            api("ui.select_tab", "modpack")
            time.sleep(1)
            api("ui.set", "modpack", "src", folder)
            api("ui.set", "modpack", "dst", project)
            time.sleep(1)
            threading.Thread(target=lambda: api("modpack.transfer"), daemon=True).start()
            print("transfer says:\n" + _wait_modal(page, 120), flush=True)
            page.screenshot(path=out("transfer_modes_folder.png"))
            print("shot", out("transfer_modes_folder.png"), flush=True)
            _close(page, "No", "OK", "Cancel")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
