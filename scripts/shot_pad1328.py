r"""PAD-1328 proof shots: the Attract and Expression lights tabs on a Spike 3 card's project.

    python scripts/shot_pad1328.py <app tree> <out png> --tab attract|lights [--card NAME]

A scratch project made from a library Spike 3 card (--card, a file name in D:\Pinball\images\Stern\spike3; Star Wars
ELG 1.10 for the Attract tab, Fallout LE 0.82 for Expression lights), served by <app tree> (main for the before shot,
the ticket's branch for the after). Prints the tab's lines that say whether the game can take items / shows.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LIB = r"D:\Pinball\images\Stern\spike3"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    tab = _arg("--tab", "attract")
    card = os.path.join(LIB, _arg("--card", "star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw"))
    scratch = tempfile.mkdtemp(prefix="pad1328-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card)}, f)
    launcher = os.path.join(scratch, "launch1328.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
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
            webui_shot.api(url, "ui.select_tab", tab)
            time.sleep(25)                       # the card's program read (a Spike 3 card: its encrypted volume)
            for line in page.inner_text("body").splitlines():
                low = line.lower()
                if any(w in low for w in ("attract", "expression", "cabinet", "cannot", "spike 3")):
                    print("page:", line.strip()[:240], flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
