"""PAD-1619 proof shots: the Plugins and Network tabs with a card whose game_monitor, game and fstab are links into
Stern's /spk/packages (the layout Stern's own updater leaves).

    python scripts/shot_pad1619.py <repo> <out dir> --card <raw> [--prefix before|after]

Serves <repo> on a scratch project made from the card and a scratch settings folder, and shoots
<prefix>_plugins.png and <prefix>_network.png.  Nothing is installed or downloaded beyond the versions list the
Plugins tab asks for itself.
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
    card = os.path.abspath(_arg("--card", ""))
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1619-")
    project = os.path.join(scratch, "Stranger Things LE")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card), "card_version": "1.13.0"}, f)
    launcher = os.path.join(scratch, "launch1619.py")
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
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_PLUGIN_DIR": os.path.join(scratch, "plugins")}
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
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            webui_shot.api(url, "ui.select_tab", "plugins")
            row = _wait(url, lambda r: r.get("releases_state") not in ("", "loading", None), "the versions list")
            print("plugins: supported", row.get("supported"), "reason:", row.get("reason"), flush=True)
            time.sleep(2)
            shot(page, "plugins")
            webui_shot.api(url, "ui.select_tab", "network")
            time.sleep(6)
            net = webui_shot.state(url).get("network") or {}
            print("network:", json.dumps(net)[:400], flush=True)
            shot(page, "network")
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
