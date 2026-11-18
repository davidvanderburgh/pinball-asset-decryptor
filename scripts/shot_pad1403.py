"""PAD-1403 proof shot: the Modes tab's Mode page for an Uncanny X-Men LE 0.98 mode, its "Shots that score while it
runs" grid: on the ticket branch it lists the cabinet buttons' shots (Action, flippers, Start: presses, releases,
holds, combos) after the playfield's.

    python scripts/shot_pad1403.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). Writes
<out_dir>/<prefix>_modes_shots.png. The settings copy carries only the preview code from David's real settings.
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


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad1403-")
    project = os.path.join(scratch, "X-Men LE Extract")
    os.makedirs(project)
    card = "uncanny_xmen_le-0_98_0.Release.16G.sdcard.raw"
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card, "card_version": "0.98.0"}, f)
    prof = MP.profile_from_port(os.path.join(repo, "tools", "spike2_emu", "modes", "sdk", "ports",
                                             "uncanny_xmen_le-0.98.port"))
    MP.PROFILES[prof.key] = prof
    spec = MP.ModeSpec(name="CYCLOPS VISOR", title=prof.key, seconds=30)
    slug, _ = MP.new_mode(project, spec=spec)
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes", [])
    launcher = os.path.join(scratch, "launch1403.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": codes,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
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
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            st = webui_shot.state(url).get("modes", {})
            print("title:", (st.get("profile") or {}).get("label"), "shots:", len((st.get("profile") or {}).get("shots") or []),
                  flush=True)
            page.get_by_text("Shots that score while it runs", exact=True).first.evaluate(
                "e => e.scrollIntoView({block: 'start'})")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_modes_shots.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, os.path.getsize(out), flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
