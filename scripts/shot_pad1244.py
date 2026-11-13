"""PAD-1244 proof shots: a Spike 3 card's sounds named, its Requests column, Auto-transcribe offered.

    python scripts/shot_pad1244.py <repo> <out_dir> [--after] [--card <Spike 3 .raw>]

Extracts the card's sounds (Audio only) with <repo>'s own code into a scratch project, then
serves <repo> on it with the Spike 3 preview codes from David's settings.  Writes, under the
same names before (main) and after (--after, the ticket branch):

- <before_|after_>audio_tab.png      the Audio tab on the extract: bare idx names and no
                                     Requests column before; the Sound Test names and the
                                     Requests column after
- <before_|after_>extract_tab.png    the Extract tab with the card picked: the Auto-transcribe
                                     and Auto-name music options appear after

Needs Playwright (the user site-packages one), the installed Edge and the card's key.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike3\fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw"
EXTRACT = r'''
import sys, threading
sys.path.insert(0, %r)
from pinball_decryptor.plugins.stern.spike3_extract import Spike3ExtractPipeline
done = threading.Event()
def log(m, k="info"):
    print("[%%s] %%s" %% (k, m), flush=True)
def fin(ok, s):
    print("DONE", ok, s, flush=True); done.set()
p = Spike3ExtractPipeline(%r, %r, log, lambda *a: None, lambda *a: None, fin,
                          extract_categories={"audio": True, "video": False,
                                              "images": False, "scenes": False})
p.run()
done.wait()
'''


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    card = sys.argv[sys.argv.index("--card") + 1] if "--card" in sys.argv else CARD
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1244-")
    project = os.path.join(scratch, "fallout")
    script = os.path.join(scratch, "extract.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(EXTRACT % (repo, card, project))
    print("extracting", card, "with", repo, flush=True)
    r = subprocess.run([sys.executable, script], capture_output=True, text=True)
    print("\n".join(r.stdout.splitlines()[-10:]), r.stderr[-1500:], flush=True)
    real = os.path.join(os.environ["APPDATA"], "pinball_decryptor", "settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes") or []
    launcher = os.path.join(scratch, "launch.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(S.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": codes,
                   "manufacturers": {"stern": {"extract_input": card,
                                               "extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
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
            api("ui.select_tab", "audio")
            time.sleep(2)
            st = S._wait_scan(state)
            time.sleep(3)
            rows = [r for r in st.get("rows") or [] if not r.get("g")]
            print("audio rows:", len(rows), "req_cap:", st.get("req_cap"),
                  "req_note:", st.get("req_note"), flush=True)
            hdr = page.get_by_text("Requests", exact=True)
            if not after and st.get("req_note"):
                # the note is the Audio tab's own: hover what carries it
                note = page.locator("[data-tip*='No Requests column'], [title*='No Requests']")
                if note.count():
                    note.first.hover()
                    time.sleep(1.5)
            elif hdr.count():
                hdr.first.hover()
                time.sleep(1.5)
            page.screenshot(path=out("audio_tab.png"))
            print("shot", out("audio_tab.png"), flush=True)
            api("ui.select_tab", "extract")
            time.sleep(6)
            ex = state().get("extract") or {}
            print("extract opts:", {k: v for k, v in ex.items() if k.startswith("opt_")},
                  flush=True)
            page.screenshot(path=out("extract_tab.png"))
            print("shot", out("extract_tab.png"), "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
