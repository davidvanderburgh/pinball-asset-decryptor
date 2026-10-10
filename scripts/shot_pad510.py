"""PAD-510 proof: the Emulate tab a few seconds after the game window is closed.

    python scripts/shot_pad510.py <repo> <out_png> [distro]

DragonRR closed the game window on a Godzilla run whose game had stopped writing
sound, and the Emulate tab went on offering only "Stop emulator": the run's
Windows sound player outlived the run, and alive.sh counts it.

<repo> is the tree whose rig is tested and whose app is served (the ticket
branch, or a ``git archive`` of main for the "before" shot).  Its rig scripts are
copied to a scratch rig beside a stand-in padplay.py that NEVER opens a sound
device; pad510_scenario.sh then starts that rig's playaudio.sh with a feed that
never delivers a byte, lets the player give up once and be restarted, and runs
the rig's own watch.sh teardown().  The stand-in models a player the relay's end
never reaches (padplay.py's half-open WSL localhost-proxy note): it leaves only by
its own no-data watchdog, ~35 s after it started, as the real one does.

Rig 3 in [distro] (default PAD-Runtime), port 46000, a scratch PAD_HOME.  The app
is an observer on rig 3: nothing is pressed, and its server is killed at the end
(never the app's quit path).  12 s after the teardown it is photographed, and what
its State, process count and one button said is printed.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = (r"D:\Pinball\images\Stern\spike2"
        r"\Godzilla Premium 1.16 Heisei Custom V1.5 Orchestral Edition.raw")
RIG_FILES = ("padpath.sh", "padslot.sh", "playaudio.sh", "padrelay.py",
             "alive.sh", "watch.sh")

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
# no background copy of the card into the rig's cache: this app only looks
from pinball_decryptor.webui.tabs import emulate
emulate.EmulateTab._precache_kick = lambda self: None
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''

STANDIN = '''"""Stand-in for the rig's padplay.py (PAD-510 proof). NEVER opens a sound device.

Named padplay.py with the port on its command line, so alive.sh (its interop
stub) and the Windows-side Stop-Process match it as they match the real player.
The relay's end never reaches it (a half-open WSL localhost-proxy connection),
so it leaves only by the no-data watchdog, 35 s after it started.
"""
import socket
import sys
import time

t0 = time.monotonic()
s = socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=30)
print("[standin] connected", flush=True)
s.settimeout(0.5)
while time.monotonic() - t0 < 35:
    try:
        if not s.recv(65536):
            print("[standin] half-open: the end of the relay never arrives", flush=True)
            while time.monotonic() - t0 < 35:
                time.sleep(0.5)
    except socket.timeout:
        pass
    except OSError:
        break
print("[standin] no data for 35 s, giving up", flush=True)
'''


def wsl_path(p):
    p = os.path.abspath(p)
    return "/mnt/%s%s" % (p[0].lower(), p[2:].replace("\\", "/"))


def build_rig(repo, rig):
    if os.path.isdir(rig):
        shutil.rmtree(rig)
    os.makedirs(rig)
    for name in RIG_FILES:
        with open(os.path.join(repo, "tools", "spike2_emu", name), "rb") as f:
            data = f.read()
        with open(os.path.join(rig, name), "wb") as f:
            f.write(data.replace(b"\r\n", b"\n"))
    with open(os.path.join(rig, "padplay.py"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write(STANDIN)


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    distro = sys.argv[3] if len(sys.argv) > 3 else "PAD-Runtime"
    tag = os.path.splitext(os.path.basename(out))[0]
    work = os.path.join(r"C:\tmp\PAD-510", "shot_" + tag)
    rig = os.path.join(work, "rig")
    build_rig(repo, rig)
    print("repo", repo, "| rig", rig, flush=True)

    scratch = tempfile.mkdtemp(prefix="pad510-")
    launcher = os.path.join(scratch, "launch510.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": CARD}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(),
           "PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "1",
           "PAD_SLOT": "3", "PAD_TICKET": "", "PAD_LABEL": "PAD-510-check",
           "CLAUDECODE": ""}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env,
                                        app_cmd=[sys.executable, launcher])
    print("server", url.split("?")[0], flush=True)

    def tab():
        st = webui_shot.state(url).get("emulate", {})
        vals = st.get("vals", {})
        return "button %r | state %r | %r" % (
            (st.get("run_btn") or {}).get("label"), vals.get("state"),
            vals.get("procs"))

    marks = {}
    scen = None
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1250})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            t0 = time.time()
            while time.time() - t0 < 60:
                if webui_shot.state(url).get("emulate", {}).get("vals", {}).get("procs"):
                    break
                time.sleep(1)
            print("idle:", tab(), flush=True)

            scen = subprocess.Popen(
                ["wsl.exe", "-d", distro, "-u", "root", "-e", "bash",
                 wsl_path(os.path.join(HERE, "pad510_scenario.sh")),
                 wsl_path(rig), tag, wsl_path(work), "50"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            def read():
                for raw in scen.stdout:
                    line = raw.decode("utf-8", "replace").rstrip()
                    print("  scenario: " + line, flush=True)
                    for key in ("BEFORE_CLOSE", "TEARDOWN_DONE", "SCENARIO_END"):
                        if key in line:
                            marks[key] = time.time()
            threading.Thread(target=read, daemon=True).start()

            while "BEFORE_CLOSE" not in marks and scen.poll() is None:
                time.sleep(0.5)
            time.sleep(3)
            print("run up, sound dead:", tab(), flush=True)
            while "TEARDOWN_DONE" not in marks and scen.poll() is None:
                time.sleep(0.2)
            done = marks.get("TEARDOWN_DONE", time.time())
            while time.time() - done < 12:
                print("  %4.1f s after the close: %s" % (time.time() - done, tab()),
                      flush=True)
                time.sleep(2)
            print("SHOT 12 s after the close:", tab(), flush=True)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            while time.time() - done < 40:
                time.sleep(4)
                print("  %4.1f s after the close: %s" % (time.time() - done, tab()),
                      flush=True)
            browser.close()
    finally:
        proc.kill()
        if scen is not None:
            try:
                scen.wait(timeout=120)
            except subprocess.TimeoutExpired:
                scen.kill()
        # the other emulator tabs' status polls this app left running (a
        # distro that does not answer keeps them waiting)
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'wsl.exe'"
             " -and $_.CommandLine -like '*%s*' } | ForEach-Object {"
             " Stop-Process -Id $_.ProcessId -Force }" % wsl_path(repo)],
            capture_output=True, timeout=60)


if __name__ == "__main__":
    main()
