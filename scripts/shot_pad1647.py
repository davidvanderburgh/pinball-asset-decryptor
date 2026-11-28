"""PAD-1647 proof shots: the Plugins tab (the how-it-works guide, the newest version offered) and My machines
(what PAD put on the card, as bullets, the Bluetooth headphones plugin among them).

    python scripts/shot_pad1647.py <repo> <out dir> --store <plugin store> --status <status answer> [--prefix after]

Serves <repo> on a scratch settings folder.  The plugin store is a COPY of <plugin store> (a folder holding
``bluetooth/``), so nothing is downloaded but the author's list of versions (one request to gitlab.com).  The
machine is not a real one: ``remote_send.connect`` is replaced by a stand-in that answers the status question
from <status answer>, a file holding what a real machine answered (lines the served build does not ask for are
left out, so an older build is shown what it would have been told).

Shoots ``<prefix>_plugins.png`` (the whole tab) and ``<prefix>_machines.png``.
Needs Playwright (the user site-packages one), the installed Edge, the card and gitlab.com.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import remote_send


class StandIn:
    """Answers the status question from a file; everything else gets an empty answer."""
    host, sftp = %(address)r, None

    def sh(self, script, timeout=60, check=True):
        if 'wifi-startup' in script:
            with open(%(status)r, encoding='utf-8') as f:
                lines = f.read().splitlines()
            if 'spikebt' not in script:
                lines = [l for l in lines if not l.startswith('pad bluetooth')]
            return 0, '\n'.join(lines) + '\n'
        return 0, ''

    def close(self):
        pass


remote_send.connect = lambda address, log=None: StandIn()
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
ADDRESS = "192.168.1.42"


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def _plugin(url):
    rows = (webui_shot.state(url).get("plugins") or {}).get("plugins") or []
    return rows[0] if rows else {}


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    prefix = _arg("--prefix", "after")
    store = os.path.abspath(_arg("--store", ""))
    status = os.path.abspath(_arg("--status", ""))
    card = _arg("--card", r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1647-")
    project = os.path.join(scratch, "Godzilla Pro")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card), "card_version": "1.16.0"}, f)
    plugins = os.path.join(scratch, "plugins")
    shutil.copytree(store, plugins)
    launcher = os.path.join(scratch, "launch1647.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"repo": repo, "status": status, "address": ADDRESS})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    net = os.path.join(scratch, "cfg", "pinball_decryptor", "remote_access")
    os.makedirs(net, exist_ok=True)
    with open(os.path.join(net, "machines.json"), "w", encoding="utf-8") as f:
        json.dump({"current": ADDRESS, "machines": [
            {"address": ADDRESS, "host_key": None, "game": "godzilla_pro", "name": "Godzilla at home"}]}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_PLUGIN_DIR": plugins, "PAD_SHOT_ONLINE": ADDRESS}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
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
            webui_shot.api(url, "ui.select_tab", "plugins")
            t0 = time.time()
            while time.time() - t0 < 90 and _plugin(url).get("releases_state") in ("", "loading", None):
                time.sleep(1)
            row = _plugin(url)
            print("versions:", row.get("releases_state"), [r["tag"] for r in row.get("releases", [])][:4],
                  "pick:", row.get("pick"), "installed:", row.get("installed"), flush=True)
            time.sleep(2)
            # the whole tab, however tall: the page scrolls inside the app, so the window is made tall
            page.set_viewport_size({"width": 1500, "height": 2000})
            time.sleep(1.5)
            path = os.path.join(out, "%s_plugins.png" % prefix)
            page.screenshot(path=path)
            print("saved", path, flush=True)
            page.set_viewport_size({"width": 1500, "height": 1000})
            # My machines: its page, the machine's Remote panel, its status read from the stand-in
            btn = page.locator("button.sx-mach-open")
            if btn.count():
                btn.first.click()
            time.sleep(2)
            print("add:", webui_shot.api(url, "shellx.machines_add", card, "Godzilla at home"), flush=True)
            time.sleep(4)
            print("remote:", webui_shot.api(url, "shellx.machines_remote", ADDRESS, True), flush=True)
            time.sleep(1)
            print("status:", webui_shot.api(url, "network.machine_status"), flush=True)
            t0 = time.time()
            while time.time() - t0 < 30 and not (webui_shot.state(url).get("network") or {}).get("care_status"):
                time.sleep(0.5)
            print("rows:", (webui_shot.state(url).get("network") or {}).get("care_status"), flush=True)
            time.sleep(1.5)
            path = os.path.join(out, "%s_machines.png" % prefix)
            page.screenshot(path=path)
            print("saved", path, "page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
