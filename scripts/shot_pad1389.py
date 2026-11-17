"""PAD-1389 proof shot: the Play options tab on a King Kong LE 1.00 project, Score feed offered or not.

    python scripts/shot_pad1389.py <repo> <out.png> [--card <raw>] [--version 1.00.0] [--cache <titles dir>]

Serves <repo> on a scratch project made from the card (its .extract_source.json names it), waits for the Modes service
to finish reading the card (and deriving its port, minutes on a new build), and shoots the Play options tab. The
app's title cache is pointed at ``--cache`` (PAD_TITLE_CACHE): pass a scratch COPY of the real one, so the shot sees
the ports this PC already derived and anything derived again stays out of the real cache.

Before (main) King Kong LE 1.00's derived port has no game_start / ball_start events and the Score feed is not
offered; after, the port keeps them at this build's own ids and it is.

Needs Playwright (the user site-packages one), the installed Edge and the card.
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


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    card = _arg("--card", os.path.expanduser(r"~\OneDrive\Desktop\king_kong_le-1_00_0_spike2.Release.16G.sdcard.raw"))
    version = _arg("--version", "1.00.0")
    cache = _arg("--cache", "")
    scratch = tempfile.mkdtemp(prefix="pad1389-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card), "card_version": version}, f)
    launcher = os.path.join(scratch, "launch1389.py")
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
    env = {"PYTHONPATH": site.getusersitepackages()}
    if cache:
        env["PAD_TITLE_CACHE"] = cache
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")      # the Modes service reads the card
            t0 = time.time()
            while time.time() - t0 < 480:
                time.sleep(10)
                body = page.inner_text("body")
                if "Reading which game" not in body and "Working out" not in body and time.time() - t0 > 20:
                    break
            print("read settled after %d s" % (time.time() - t0), flush=True)
            webui_shot.api(url, "ui.select_tab", "playopts")
            time.sleep(6)
            page.screenshot(path=out)
            print("shot", out, "score feed offered:", "Score feed" in page.inner_text("body"), flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
