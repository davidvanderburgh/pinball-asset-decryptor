"""PAD-1519 proof shot: the same update, the old way and from the changed files alone.

    python scripts/shot_pad1519.py <repo> <out_dir> <install> <releases> <new_tree> [--after]

Serves <repo> as an INSTALLED copy - <install>, a copy of a real v1.574.0 install - whose release
feed offers v1.575.0 from a stand-in for GitHub's release downloads (<releases>/<tag>/<asset>, with
Range): the setup exe, and the file list and pack installer/make_delta.py made. Writes
<before_|after_>update_log.png: the banner and the log once the update is ready.

Before (main) the app downloads the 157 MB setup exe and installs all of it beside the running copy.
After, it copies what it has and fetches the changed files. THE SETUP EXE CANNOT RUN HERE (it needs
administrator, and the capture is not elevated), so its run is stood in for by what it does to the
folder: every file of <new_tree> (a whole v1.575.0 install) copied in and the app's package compiled;
the permission repair after it is the real one. That stand-in is quicker than the real exe, which
also has to unpack 157 MB of LZMA: David's own log has 35-56 s for the step it shows here.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import hashlib
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

VERSION = "1.575.0"
EXE = "Pinball_Asset_Decryptor_v%s_Windows.exe" % VERSION

LAUNCHER = r'''
import os, re, shutil, subprocess, sys, threading
sys.path.insert(0, %(repo)r)
INSTALL, REL, NEW_TREE, VERSION = %(install)r, %(rel)r, %(new_tree)r, %(version)r
ASSETS = %(assets)r
from pinball_decryptor.core import net, update_slots as us, updater
from pinball_decryptor.core.config import GITHUB_REPO
import pinball_decryptor.app as app_mod

us.installed_app_dir = lambda *a, **k: INSTALL


class _Resp:
    def __init__(self, f, n, status):
        self.f, self.left, self.status = f, n, status
    def read(self, n=-1):
        n = self.left if n is None or n < 0 else min(n, self.left)
        data = self.f.read(n)
        self.left -= len(data)
        return data
    def __enter__(self):
        return self
    def __exit__(self, *a):
        self.f.close()
        return False


def _open(req, timeout=None):
    m = re.match(r"https://github\.com/%%s/releases/download/([^/]+)/(.+)$"
                 %% re.escape(GITHUB_REPO), req.full_url)
    if not m:
        raise OSError("the capture has no network: " + req.full_url)
    path = os.path.join(REL, m.group(1), m.group(2))
    f = open(path, "rb")
    rng = req.get_header("Range")
    if rng:
        a, b = map(int, re.match(r"bytes=(\d+)-(\d+)", rng).groups())
        f.seek(a)
        return _Resp(f, b - a + 1, 206)
    return _Resp(f, os.path.getsize(path), 200)


net.urlopen = _open
_real_run = subprocess.run


def _run(cmd, **kw):
    if isinstance(cmd, str) and "/STAGED=2" in cmd:
        # the setup exe's work on the folder (see the module docstring)
        target = re.search(r'/DIR="([^"]+)"', cmd).group(1)
        shutil.copytree(NEW_TREE, target, ignore=shutil.ignore_patterns(
            "__pycache__", "unins*", "userpkg", "My Project"))
        _real_run([os.path.join(target, "python", "python.exe"), "-m",
                   "compileall", "-q", "-j", "0",
                   os.path.join(target, "pinball_decryptor")],
                  capture_output=True, cwd=target)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    return _real_run(cmd, **kw)


subprocess.run = _run
_init = app_mod.App.__init__


def _offer(self):
    rows = [{"name": n, "browser_download_url":
             "https://github.com/%%s/releases/download/v%%s/%%s"
             %% (GITHUB_REPO, VERSION, n), "size": s, "digest": "sha256:" + d}
            for n, s, d in ASSETS]
    installer = updater._pick_installer_asset(rows, platform="win32")
    self._offer_update(VERSION, "https://example.invalid/release", installer)


def _App(self, *a, **k):
    _init(self, *a, **k)
    def _later():
        import time
        time.sleep(6)
        self.root.after(0, _offer, self)
    threading.Thread(target=_later, daemon=True).start()


app_mod.App.__init__ = _App
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    repo, out_dir, install, rel, new_tree = (os.path.abspath(p)
                                             for p in sys.argv[1:6])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1519-")
    folder = os.path.join(rel, "v" + VERSION)
    assets = [(n, os.path.getsize(os.path.join(folder, n)),
               _sha(os.path.join(folder, n)))
              for n in sorted(os.listdir(folder))]
    assert any(n == EXE for n, _s, _d in assets), "no %s in %s" % (EXE, folder)
    launcher = os.path.join(scratch, "launch1519.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"repo": repo, "install": install, "rel": rel,
                            "new_tree": new_tree, "version": VERSION,
                            "assets": assets})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "TEMP": scratch, "TMP": scratch})
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_")
                       + "update_log.png")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 760})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '1'); "
                "localStorage.setItem('pad.log.h', '300'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            # the log pane belongs to a manufacturer's screen
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            text = ""
            deadline = time.time() + 300
            while time.time() < deadline:
                banners = {b["id"]: b for b in
                           state()["shell"].get("banners", [])}
                text = (banners.get("update") or {}).get("text", "")
                if "is ready" in text:
                    break
                time.sleep(0.5)
            back = page.locator("button:has-text('Back to Stern Pinball')")
            if back.count():                # off Getting started: no log there
                back.first.click()
            time.sleep(2.5)
            print("banner:", text, flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
