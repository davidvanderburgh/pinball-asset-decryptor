"""PAD-1086 proof shots: the Extract tab's Spike 3 OTP self-extractor panel.

    python scripts/shot_pad1086.py <repo> <out_dir> [--before] [--card PATH]

Serves <repo> with the Spike 3 preview on, picks Stern, opens Extract, and
selects a real locked Spike 3 card. On this branch a "needs its board's OTP
key" panel appears with Build extractor card... / I have the key... . The
script then drives both (answering the pickers through agent.use_files):
Build writes the card files and shows the deploy steps; I-have-the-key reads
the real OTP keyfile, verifies it against the card, and the panel flips to
unlocked. On main there is no panel (the before shot).

Writes, under the same names before/after:
  <before_|after_>extract.png    the Extract tab with the locked card selected
  after_build.png                the deploy steps after Build extractor card
  after_verified.png             the panel unlocked after the key verifies

The real OTP key value is never shown; the padkeys.json it writes goes to the
scratch dir and is removed with it. Needs Playwright (user site-packages) and
the installed Edge.
"""
import os
import site
import sys
import tempfile
import time
import shutil

sys.path.insert(0, site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

# a short-lived Spike 3 preview code minted for this shot (public code; the key
# value it unlocks is never in the repo).
SPIKE3_CODE = ("PAD-PREVIEW-PMRGKIR2EIZDAMRWFUYTCLJRGMRCYITGEI5FWITTOBUWWZJTEJOSYITJ"
               "EI5CEMRQGI3C2MJRFUYTAIRMEJUWIIR2EIZWKNTDGQYSELBCNYRDUISQIFCC2MJQHA3C"
               "A43IN52CELBCOYRDUML5DYMUURFWN4YDLVELUWO6LYPQYKQYY5FCSALYVH5JQWFBPEIS"
               "ETKRXHS4LQZNVCTN54D3A5AE6KAW42DEW2Y3AXIQ4DAQRFNYEIFPOAA")
DEFAULT_CARD = r"D:\Pinball\images\Stern\spike3\star_wars_2025_le-0_96_0.Release.64G.sdcard-secure.raw"
OTP_KEYFILE = r"C:\Users\david\OneDrive\Documents\Spike3-Research\otp_sd_keyfile.bin"

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _serve(repo, scratch):
    import json
    launcher = os.path.join(scratch, "launch1086.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": [SPIKE3_CODE]}, f)
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def _wait(state_fn, pred, limit=60):
    end = time.time() + limit
    while time.time() < end:
        try:
            if pred(state_fn()):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    before = "--before" in sys.argv
    card = DEFAULT_CARD
    if "--card" in sys.argv:
        card = sys.argv[sys.argv.index("--card") + 1]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1086-")
    pfx = "before_" if before else "after_"
    print("serving", repo, flush=True)
    proc, url = _serve(repo, scratch)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "extract")
            time.sleep(1)
            # point the output at the scratch dir so a written padkeys.json
            # lands there (never beside the read-only card) and is cleaned up
            api("extract.use_recent", "output", scratch)
            api("extract.use_recent", "input", card)
            ok = _wait(state, lambda s: (s.get("extract") or {}).get("detected"), 90)
            print("detected:", (state().get("extract") or {}).get("detected"), flush=True)
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, pfx + "extract.png"))
            has_panel = bool((state().get("extract") or {}).get("spike3_unlock"))
            print("panel present:", has_panel, flush=True)
            if has_panel and not before:
                try:
                    # Build extractor card... -> answer the folder picker with a scratch dir
                    carddir = os.path.join(scratch, "extractor_card")
                    api("agent.use_files", [carddir])
                    api("extract.spike3_build_card")
                    _wait(state, lambda s: (s["extract"].get("spike3_unlock") or {}).get("instructions"), 90)
                    time.sleep(1)
                    page.screenshot(path=os.path.join(out_dir, "after_build.png"))
                    print("built:", (state()["extract"]["spike3_unlock"] or {}).get("status"), flush=True)
                except Exception as e:
                    print("build drive error:", e, flush=True)
                try:
                    # I have the key... -> answer with the real OTP keyfile, verify
                    api("agent.use_files", [OTP_KEYFILE])
                    api("extract.spike3_ingest_key")
                    _wait(state, lambda s: (s["extract"].get("spike3_unlock") or {}).get("verified"), 90)
                    time.sleep(1)
                    page.screenshot(path=os.path.join(out_dir, "after_verified.png"))
                    u = state()["extract"].get("spike3_unlock") or {}
                    print("verified:", u.get("verified"), "| status:", u.get("status"), flush=True)
                except Exception as e:
                    print("ingest drive error:", e, flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
