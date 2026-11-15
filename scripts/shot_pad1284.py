r"""PAD-1284 proof shot: the Modes tab's screen page of a Form mode for the Star Wars ELG 1.10 Spike 3 card.

    python scripts/shot_pad1284.py <app tree> <out png> [page label]

shot_pad1283.py's project on the Spike 3 card with one Form mode, on the page that holds its screen, words and clip:
before, the Spike 3 port carried none of the scene, text and video-surface sites (the 64-bit runtime's screen and
clip features read 32-bit strings and structs), so the page said the mode's screen and clip are not on this game;
after, they are carried and the page offers them. Prints the page's navigation and its screen / clip lines.
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
    scratch = tempfile.mkdtemp(prefix="pad1284-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "1.10.0"}, f)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    slug, _ = MP.new_mode(project, "TRENCH RUN")
    launcher = os.path.join(scratch, "launch1284.py")
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
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            want = sys.argv[3] if len(sys.argv) > 3 else "Screen"
            for line in page.inner_text("body").splitlines()[:400]:
                if 0 < len(line.strip()) < 40:
                    print("nav?:", line.strip(), flush=True)
            hit = page.get_by_text(want, exact=True)
            print("page label %r found %d" % (want, hit.count()), flush=True)
            if hit.count():
                hit.first.click()
                time.sleep(2.5)
            for line in page.inner_text("body").splitlines():
                low = line.lower()
                if any(w in low for w in ("screen", "clip", "video", "words", "picture", "not on this game")):
                    print("page:", line.strip()[:240], flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
