r"""PAD-1289 proof shots: the Modes tab's Mode page of a Form mode for the Pokemon LE 0.82 Spike 3 card.

    python scripts/shot_pad1289.py <app tree> <out dir>

PAD1289_SHOTS="<section title>=<shot name>;..." picks the sections shot. Before, no Spike 3 port for Pokemon LE
shipped, so the card took no modes; after, its port is proven on the rig (a mode's trigger, score, clock, ball save and
multiball) and the Mode page offers them. Prints the page's lines about them and its headings.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

SHOTS = [tuple(x.split("=", 1)) for x in os.environ.get("PAD1289_SHOTS", "Other mechanisms=modes_probe").split(";")]
CARD = r"D:\Pinball\images\Stern\spike3\pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"
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
    scratch = tempfile.mkdtemp(prefix="pad1289-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "0.82.0"}, f)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    # the card's own profile when one ships (the branch): its start and scoring shots; main has none
    prof = MP.profile_for_card("pokemon_le", "0.82.0", arch="a64")
    if prof is not None:
        spec = MP.blank_spec(prof, name="BERRY RUSH")
        spec.start_shot, spec.start_count = "Berry target left", 3
        spec.scoring_shots = ["Left orbit", "Rear ramp made", "Captive ball-target"]
        slug, _ = MP.new_mode(project, spec=spec)
    else:
        slug, _ = MP.new_mode(project, "BERRY RUSH")
    launcher = os.path.join(scratch, "launch1289.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": int(os.environ.get("PAD1289_H", "1000"))})
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
            # the Mode page is the editor's first, shown when the mode is picked
            time.sleep(2.5)
            for line in page.inner_text("body").splitlines():
                low = line.lower()
                if any(w in low for w in ("ball save", "starts on", "completed", "in the place", "the game starting",
                                          "game's modes", "has not yet seen", "emulator")):
                    print("page:", line.strip()[:220], flush=True)
            heads = page.eval_on_selector_all("h1,h2,h3,h4,legend,summary,.section-title",
                                              "els => els.map(e => e.innerText.trim()).filter(t => t)")
            print("heads:", heads, flush=True)
            for title, name in SHOTS:
                sec = page.get_by_text(title, exact=True)
                if sec.count():
                    sec.first.evaluate("e => e.scrollIntoView({block: 'center'})")
                    time.sleep(1)
                else:
                    print("no section", title, flush=True)
                path = os.path.join(out, name + ".png")
                page.screenshot(path=path)
                print("shot", path, flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
