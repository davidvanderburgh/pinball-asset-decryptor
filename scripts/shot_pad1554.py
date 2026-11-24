"""PAD-1554 proof shots: the Plugins tab and the Bluetooth headphones plugin on a Stern Spike 2 card.

    python scripts/shot_pad1554.py <repo> <out dir> [--card <raw>] [--prefix after]

Serves <repo> on a scratch project made from the card and a scratch settings folder (so the plugin store starts
empty) and shoots, as <prefix>_<screen>.png:

* ``plugins``: the Plugins tab as a user first meets it (nothing installed, the author's versions listed).  On a
  repo without the tab (main, the before shot) the Network tab is shot instead: the rail has no Plugins.
* ``plugins_installed``: after Install (a real download from the author's GitLab project) and the project's tick.
* ``plugins_details``: the same with "Exactly what it changes on the card" open.

Needs Playwright (the user site-packages one), the installed Edge, the card, and gitlab.com for the after shots.
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


def _plugin(url):
    rows = (webui_shot.state(url).get("plugins") or {}).get("plugins") or []
    return rows[0] if rows else {}


def _wait(url, done, what, seconds=120):
    t0 = time.time()
    while time.time() - t0 < seconds:
        row = _plugin(url)
        if done(row):
            return row
        time.sleep(1)
    raise SystemExit("timed out waiting for " + what + ": " + json.dumps(_plugin(url))[:600])


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    prefix = _arg("--prefix", "after")
    card = _arg("--card", r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0.Release.16G.sdcard.raw")
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1554-")
    project = os.path.join(scratch, "Godzilla Pro")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1554.py")
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
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)

    def shot(page, name):
        path = os.path.join(out, "%s_%s.png" % (prefix, name))
        page.screenshot(path=path)
        print("saved", path, flush=True)

    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            tabs = (webui_shot.state(url).get("shell") or {}).get("tabs") or []
            make = [t["label"] for t in tabs if t.get("visible") and t.get("group") == "Make"]
            print("Make group:", make, flush=True)
            if not any(t["ns"] == "plugins" and t.get("visible") for t in tabs):
                webui_shot.api(url, "ui.select_tab", "network")
                time.sleep(5)
                for name in ("plugins", "plugins_installed", "plugins_details"):
                    shot(page, name)
                browser.close()
                return
            webui_shot.api(url, "ui.select_tab", "plugins")
            row = _wait(url, lambda r: r.get("releases_state") not in ("", "loading", None), "the versions list")
            print("versions:", [(r["tag"], r["tested"]) for r in row["releases"]], "state:", row["releases_state"],
                  "supported:", row["supported"], row["reason"], "now:", row["now"], flush=True)
            time.sleep(1)
            shot(page, "plugins")
            webui_shot.api(url, "plugins.install", "bluetooth", row["tested"])
            row = _wait(url, lambda r: not r.get("busy") and (r.get("installed") or r.get("kind") == "err"),
                        "the install")
            print("installed:", row["installed"], row["kind"], row["note"], flush=True)
            webui_shot.api(url, "plugins.configure", "bluetooth", True, project)
            row = _wait(url, lambda r: r.get("enabled"), "the tick")
            print("ticked:", row["enabled"], "hint:", row["hint"], flush=True)
            time.sleep(1)
            shot(page, "plugins_installed")
            page.get_by_text("Exactly what it changes on the card").click()
            time.sleep(1)
            page.screenshot(path=os.path.join(out, "%s_plugins_details.png" % prefix), full_page=True)
            print("saved details; page errors:", errors, flush=True)
            store = (webui_shot.state(url).get("plugins") or {}).get("store")
            print("store:", store, sorted(os.listdir(os.path.join(store, "bluetooth"))), flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
