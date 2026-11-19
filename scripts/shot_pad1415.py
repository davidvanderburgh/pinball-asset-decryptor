r"""PAD-1415 proof shots: the Attract tab on a Spike 3 project (Pokemon LE, Fallout LE, Transformers LE or Walking Dead
Remastered LE) whose owner puts a title card of his own after the game's screen 4.

    python scripts/shot_pad1415.py <app tree> <out png> --card NAME

A scratch project made from the library card (D:\Pinball\images\Stern\spike3), served by <app tree> (main for the
before shot: the tab says the game's attract cannot take items; the ticket's branch for the after: its screens).
The Stern era is set to Spike 3 with this PC's own preview codes, as shot_pad1380.py does.
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


def _real_preview_codes():
    try:
        with open(os.path.join(os.environ["APPDATA"], "pinball_decryptor", "settings.json"), encoding="utf-8") as f:
            return list(json.load(f).get("preview_codes") or [])
    except (OSError, ValueError, KeyError):
        return []


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    card = os.path.join(LIB, _arg("--card", "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"))
    scratch = tempfile.mkdtemp(prefix="pad1415-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card)}, f)
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"attract_items": {"items": [
            {"kind": "text", "entry": 3, "where": "after", "seconds": 6, "text": "MY ARCADE\nFREE PLAY FRIDAYS"}],
            "champions": True}}, f)
    launcher = os.path.join(scratch, "launch1415.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}},
                   "preview_codes": _real_preview_codes()}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--mute-audio"])
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "extract")
            webui_shot.api(url, "extract.use_recent", "input", card)
            webui_shot.api(url, "ui.set_era", "spike3")   # Stern > Spike 3, as the reporter's app was
            webui_shot.api(url, "extract.use_recent", "input", card)   # the era switch cleared the card box
            t0 = time.time()
            era = ""
            while time.time() - t0 < 90:
                time.sleep(2)
                st = webui_shot.state(url)
                era = (st.get("shell") or {}).get("era", "")
                mfr = (st.get("shell") or {}).get("mfr") or {}
                era = era or (mfr.get("era", "") if isinstance(mfr, dict) else "")
                if era == "spike3":
                    break
            webui_shot.api(url, "ui.select_tab", "attract")
            for _ in range(240):                 # the card's program read
                time.sleep(1)
                if page.locator(".at-seq").count() or "Nothing to edit here" in page.inner_text("body"):
                    break
            time.sleep(2)
            if "--replace" in sys.argv:
                print("replace:", webui_shot.api(url, "attract.replace_all", True), flush=True)
                time.sleep(2)
            for line in page.inner_text("body").splitlines():
                low = line.lower()
                if any(w in low for w in ("attract", "hidden", "replace", "cannot", "screen")):
                    print("page:", line.strip()[:240], flush=True)
            page.screenshot(path=out, full_page=True)
            print("shot", out, "| page errors:", errors, flush=True)
            if "--kept" in sys.argv:         # the second shot: the rows from the game's screen 22 on (its high scores)
                kept = _arg("--kept", "")
                page.locator(".at-row", has_text="screen 22").first.evaluate("e => e.scrollIntoView({block: 'start'})")
                time.sleep(1.5)
                page.screenshot(path=kept)
                print("shot", kept, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
