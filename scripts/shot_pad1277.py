r"""PAD-1277 proof shot: the Modes tab's "Try it on" note for the Star Wars ELG 1.10 Spike 3 card.

    python scripts/shot_pad1277.py <app tree> <out png>

shot_pad1272.py on the card whose game folder and build Spike 2 also has (Star Wars ELG 1.10):
before, the Spike 2 build's port answered for the Spike 3 card, so the tab offered modes a Write
then refused; after, a Spike 3 card is answered by a Spike 3 port only (ports/spike3), and with
none shipped yet the tab says its build has no port. Prints the note and its tip.
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
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad1277-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "1.10.0"}, f)
    launcher = os.path.join(scratch, "launch1277.py")
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
            chip = page.locator(".modes-tryon .chip, .modes-tryon [class*=chip]").last
            if chip.count():
                print("note:", chip.inner_text(), flush=True)
                print("tip:", chip.get_attribute("title") or chip.get_attribute("data-tip"),
                      flush=True)
                chip.hover()
                time.sleep(1.5)
            else:
                print("note: none", flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
