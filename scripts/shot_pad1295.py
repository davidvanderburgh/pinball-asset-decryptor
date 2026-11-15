r"""PAD-1295 proof shot: Try it of a CODE mode on a Stern Spike 3 card, in the Modes tab.

    python scripts/shot_pad1295.py <app tree> <out png> <code mode .c>

Serves <app tree> (main for "before", the ticket branch for "after"), with the mode maker's preview
on, on a scratch project made from the Star Wars ELG 1.10 Spike 3 card holding one code mode (the
.c given), opens the Modes tab, puts that card in "Try it on" and presses Try it. The Spike 3 start
itself is stubbed in the served app (a sleeping process in place of s3launch.sh, whose game window
would land on the desktop); the build and its note are the app's own. Before: Try it refuses, the
code mode left out. After: the code mode compiled for the card's 64-bit ARM, named in the note.

Needs Playwright (the user site-packages one), the installed Edge and the card in
D:\Pinball\images\Stern\spike3.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike3\star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import emulate_core
_real = emulate_core._s3_argv
emulate_core._s3_argv = lambda *a: (_real(*a) if any(str(x).startswith("--") and str(x) not in ("--mode-so", "--mode-files") for x in a[:1])
                                    else [sys.executable, "-c", "import time; time.sleep(90)"])
from pinball_decryptor.webui import modes_tryit
modes_tryit.TryItMixin.run_ended = lambda self, serial: None   # the stub never comes up: keep the build's note
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad1295-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "1.10.0"}, f)
    mode = os.path.join(project, "modes", "bounty_hunt")
    os.makedirs(mode)
    import shutil
    shutil.copyfile(sys.argv[3], os.path.join(mode, "bounty_hunt.c"))
    launcher = os.path.join(scratch, "launch1295.py")
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
            browser = p.chromium.launch(channel="msedge", args=["--mute-audio"])
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            box = page.locator(".modes-tryon-path input").first
            box.fill(CARD)
            box.press("Enter")
            time.sleep(4)
            btn = page.get_by_role("button", name="Try it").first
            print("button:", btn.count(), flush=True)
            btn.click()
            for _ in range(1200):                # the build: the compile is ~15 s, a first kit unpack more
                time.sleep(0.2)
                line = page.locator(".modes-tryline-text")
                txt = line.first.inner_text() if line.count() else ""
                if "ready" in txt:                # the build's note; the stubbed start is not waited for
                    break
                if txt and page.get_by_role("button", name="Cancel").count() == 0:
                    time.sleep(2)
                    break
            print("note:", page.locator(".modes-tryline-text").first.inner_text(), flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
