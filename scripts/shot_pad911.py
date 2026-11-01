"""PAD-911 proof shot: the Multi-boot tab on a Mac building the Linux
toolbox image for the first time (the first Build after an update that
changes it).

    python scripts/shot_pad911.py <repo> <out_png> [seconds]

<repo> is the source tree to serve (the ticket branch, or a ``git archive``
of main for the "before" shot).  Nothing runs Docker: the launcher stands
the Mac in (``multiboot_docker.enabled``), has no image on the machine, and
makes ``docker build`` a stand-in that prints the reporter's own apt lines,
one a second, for two minutes.  A writing run is started as the tab is
shown, and the page is photographed *seconds* (default 45) later.  Before:
the build ran on the app's main thread, so the page is frozen where it was.
After: the tab is busy, Cancel is live and the Log says the build is going.
"""

import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import os
import sys
import time
os.environ["PAD_UI_NO_RIG"] = "0"
sys.path.insert(0, %r)
from pinball_decryptor.webui import multiboot_docker as D
from pinball_decryptor.webui import multiboot_core as mt
D.enabled = lambda: True
D.unavailable_reason = lambda: ""
D._image_field = lambda field: ""          # no toolbox image yet
APT = ["#5 %%.2f Get:%%d http://deb.debian.org/debian bookworm/main amd64 "
       "%%s" %% (1.7 * i, i, pkg) for i, pkg in enumerate(
           ["gnupg all 2.2.40-1.1+deb12u2 [846 kB]",
            "libburn4 amd64 1.5.4-1 [166 kB]",
            "libc-dev-bin amd64 2.36-9+deb12u14 [48.1 kB]",
            "libcrypt-dev amd64 1:4.4.33-2 [118 kB]",
            "libisofs6 amd64 1.5.4-1 [209 kB]",
            "partclone amd64 0.3.23+repack-1 [699 kB]",
            "qemu-user-static amd64 1:7.2+dfsg-7+deb12u18+b3 [62.6 MB]",
            "libavfilter8 amd64 7:5.1.9-0+deb12u1 [3720 kB]"] * 15, 200)]


class R:
    returncode, stdout, stderr = 1, "", "stand-in: not a real docker"


def docker(args, timeout=30):
    if list(args)[:1] == ["build"]:
        for _ in APT:
            time.sleep(1)                # silent: run() captures it all
    return R()


def docker_build(args, on_line, timeout):
    for line in APT:
        time.sleep(1)
        on_line(line)
    return 1, "stand-in: not a real docker"


D._docker = docker
D._docker_build = docker_build
_shown = mt.MultibootPanel.on_shown


def on_shown(self, *a, _shown=_shown, mt=mt, **k):
    try:
        r = _shown(self, *a, **k)
        if not getattr(mt, "_pad911_started", False):
            mt._pad911_started = True
            self._run_commands([("build", ["true"])])
    except Exception:
        import traceback
        with open(%r, "w") as fh:
            traceback.print_exc(file=fh)
        raise
    return r


mt.MultibootPanel.on_shown = on_shown
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    wait = float(sys.argv[3]) if len(sys.argv) > 3 else 45
    scratch = tempfile.mkdtemp(prefix="pad911-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch911.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % (repo, out + ".err"))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {
                       "extract_output": project, "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            # on main the build holds this call (and the app) until it ends
            threading.Thread(target=lambda: webui_shot.api(
                url, "ui.select_tab", "multiboot"), daemon=True).start()
            time.sleep(wait)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
