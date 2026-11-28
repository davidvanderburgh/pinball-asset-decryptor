r"""PAD-1644 proof shot: the Modes tab of a project extracted from Stern's Spike 2 game code
download (``iron_maiden_le-1_18_0.spk.zip``), with that package in "Try it on" as the
extract leaves it.

    python scripts/shot_pad1644_modes.py <app tree> <package.spk.zip> <out png>

Before: the chip beside "Try it on" calls the package "the project's own card" (green), and
Try it later stops on "... is not a Spike 2 card image this can read (no games partition)".
After: the chip says it is game code, not an SD card image, and its tip says to download the
game's SD card image instead.  Needs Playwright (the user site-packages one) and Edge.
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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    pkg = os.path.abspath(sys.argv[2])
    out = os.path.abspath(sys.argv[3])
    scratch = tempfile.mkdtemp(prefix="pad1644-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": pkg, "input_name": os.path.basename(pkg)}, f)
    launcher = os.path.join(scratch, "launch1644.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": pkg, "write_original": pkg,
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
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(4)
            box = page.locator(".modes-tryon-path input").first
            box.fill(pkg)
            box.press("Enter")
            time.sleep(4)
            chip = page.locator(".modes-tryon .chip, .modes-tryon [class*=chip]").first
            try:
                print("chip:", chip.inner_text(timeout=3000), "| tip:",
                      chip.get_attribute("title"), flush=True)
                chip.hover()
                time.sleep(1.5)
            except Exception as e:                      # noqa: BLE001
                print("no chip:", e, flush=True)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(20)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
