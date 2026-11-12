"""PAD-1209 proof shot: the Audio tab's toolbar choices come back next session.

    python scripts/shot_pad1209.py <repo> <out_dir> [--after]

Serves <repo> on the PAD-1176 scratch Stern project with a settings.json that
already holds what a previous session saved (Type Callouts, Show Unchanged,
Hide unused, Play sequentially, Play replacements), and writes
<before_|after_>audio_restored.png: the Audio tab as it opens.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import shot_pad1176 as C  # noqa: E402
import webui_shot  # noqa: E402

SAVED = {"audio_type": "Callouts", "audio_show": "Unchanged",
         "audio_hide_unused": True, "audio_play_through": True,
         "audio_play_subst": True}


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1209-")
    project = C._project(scratch)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump(dict({"disclaimer_accepted": True, "last_manufacturer": "stern",
                        "manufacturers": {"stern": {"extract_output": project,
                                                    "write_assets": project}}},
                       **SAVED), f)
    launcher = os.path.join(scratch, "launch494.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(S.LAUNCHER % repo)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_")
                       + "audio_restored.png")
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
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "audio")
            time.sleep(2)
            S._wait_scan(state)
            time.sleep(2)
            page.screenshot(path=out)
            st = state().get("audio", {})
            print("shot", out, {k: st.get(k) for k in (
                "type", "type_useful", "show", "hide_unused", "play_through",
                "play_subst")}, "rows:", len(st.get("rows") or ()), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
