r"""PAD-1129 proof: the playfield window as a Mac's emulator box starts it.

    python scripts/shot_pad1129_box_playfield.py <tree> <out png>

<tree> is the source tree (a ``git archive`` of main for "before", the ticket
branch for "after"). The window is scripts/playfield_demo.py with no emulator,
given the environment that tree's docker/padbox.sh gives the window inside
the box: main gives it no PAD_AUDIO_CTL; the branch gives it the box's own
copy, kept level with the app's folder by padbox.sh's ctl_sync.

For a tree with ctl_sync, the REAL ctl_sync and docker/boxctl.py run in WSL
(`docker` a shell function that runs boxctl.py on a folder standing in for
the box's /tmp/pad_ctl), and the script then works the window's own buttons -
Mute, Volume, Restart game - and says what reached the app's folder. The app
side is first set to 40 %, so the shot shows the window following the tab.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time


def wsl_path(p):
    p = os.path.abspath(p).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:])


def functions(box_sh, names):
    body = open(box_sh, encoding="utf-8").read()
    out = [re.search(r"^box_up\(\) \{.*\}\n", body, re.M).group(0)]
    for n in names:
        out.append(re.search(r"^%s\(\) \{\n.*?^\}\n" % n, body, re.S | re.M).group(0))
    return "\n".join(out)


def start_sync(tree, scratch, mac, box):
    script = os.path.join(scratch, "sync.sh")
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write("""set -u
NAME=pad-box BOX_CTL_DIR=/tmp/pad_ctl
PAD_AUDIO_CTL=%(mac)s/audio_ctl.json
docker() {
  case "$1" in ps) echo pad-box; return 0 ;; exec) ;; *) return 0 ;; esac
  echo "[shot] docker exec ${*:2}" >&2
  exec python3 %(boxctl)s %(box)s
}
%(funcs)s
( sleep 150; kill $$ ) &
ctl_sync
""" % {"mac": wsl_path(mac), "box": wsl_path(box),
       "boxctl": wsl_path(os.path.join(tree, "tools", "spike2_emu", "docker", "boxctl.py")),
       "funcs": functions(os.path.join(tree, "tools", "spike2_emu", "docker", "padbox.sh"),
                          ("ctl_feed", "ctl_apply", "ctl_sync"))})
    return subprocess.Popen(["wsl.exe", "-e", "bash", wsl_path(script)],
                            stdout=open(os.path.join(scratch, "sync.log"), "w"),
                            stderr=subprocess.STDOUT)


def wait_for(cond, s=15):
    end = time.time() + s
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def read(p):
    try:
        return open(p, encoding="utf-8").read().strip()
    except OSError:
        return None


def main():
    tree, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    box_sh = open(os.path.join(tree, "tools", "spike2_emu", "docker", "padbox.sh"),
                  encoding="utf-8").read()
    hands_ctl = 'RUN_ARGS+=(-e "PAD_AUDIO_CTL=$BOX_CTL")' in box_sh
    scratch = tempfile.mkdtemp(prefix="pad1129pf-", dir=r"C:\tmp")
    mac, box = os.path.join(scratch, "mac"), os.path.join(scratch, "box")
    os.makedirs(mac)
    mac_ctl = os.path.join(mac, "audio_ctl.json")
    with open(mac_ctl, "w", encoding="utf-8") as f:
        f.write('{"gain": 0.4, "muted": false}\n')
    env = dict(os.environ, PAD_LABEL="PAD-1129")
    env.pop("PAD_AUDIO_CTL", None)
    env.pop("PAD_SLOT", None)
    sync = None
    if hands_ctl:
        print("this padbox.sh hands the box's window PAD_AUDIO_CTL=/tmp/pad_ctl/audio_ctl.json")
        sync = start_sync(tree, scratch, mac, box)
        if not wait_for(lambda: read(os.path.join(box, "audio_ctl.json")), 30):
            sys.exit("ctl_sync never put the app's volume file into the box:\n"
                     + (read(os.path.join(scratch, "sync.log")) or ""))
        print("box copy after ctl_sync:", read(os.path.join(box, "audio_ctl.json")))
        env["PAD_AUDIO_CTL"] = os.path.join(box, "audio_ctl.json")
    else:
        print("this padbox.sh gives the box's window no PAD_AUDIO_CTL")
    log = os.path.join(scratch, "pf.log")
    demo = subprocess.Popen(
        [sys.executable, os.path.join(tree, "scripts", "playfield_demo.py"), "field",
         "--window", "none", "--seconds", "140"],
        stdout=open(log, "w", encoding="utf-8"), stderr=subprocess.STDOUT, env=env)
    try:
        url = None
        for _ in range(120):
            txt = open(log, encoding="utf-8", errors="replace").read()
            urls = [ln.split()[1] for ln in txt.splitlines() if ln.startswith("URL ")]
            if urls:
                url = urls[0]
                break
            time.sleep(0.5)
        if not url:
            sys.exit("the demo never printed its URL:\n" + txt)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge")
            pg = b.new_page(viewport={"width": 1180, "height": 900})
            pg.goto(url)
            pg.wait_for_timeout(3000)
            bar = ("Array.from(document.querySelectorAll('.pf-run .btn, .pf-run .lab,"
                   " .pf-run .pct, .pf-run .mute'))"
                   ".map(e => e.textContent.trim()).filter(Boolean)")
            print("status bar:", pg.evaluate(bar))
            pg.screenshot(path=out)
            print("shot", out)
            if hands_ctl:
                pg.locator(".pf-run .mute input").click()
                ok = wait_for(lambda: '"muted": true' in (read(mac_ctl) or ""))
                print("Mute clicked in the window -> app's file:", read(mac_ctl),
                      "" if ok else "(DID NOT ARRIVE)")
                pg.locator(".pf-run input.vol").fill("75")
                ok = wait_for(lambda: '"gain": 0.75' in (read(mac_ctl) or ""))
                print("Volume set to 75 in the window -> app's file:", read(mac_ctl),
                      "" if ok else "(DID NOT ARRIVE)")
                with open(mac_ctl + ".t", "w", encoding="utf-8") as f:
                    f.write('{"gain": 0.2, "muted": false}\n')
                os.replace(mac_ctl + ".t", mac_ctl)
                ok = wait_for(lambda: pg.evaluate(
                    "document.querySelector('.pf-run .pct').textContent") == "20%")
                print("app's slider set to 20 % unmuted -> window shows:",
                      pg.evaluate("document.querySelector('.pf-run .pct').textContent"),
                      "muted" if pg.locator(".pf-run .mute input").is_checked() else "unmuted",
                      "" if ok else "(DID NOT FOLLOW)")
                pg.get_by_role("button", name="Restart game").click()
                req = os.path.join(mac, "restart_game_0.req")
                ok = wait_for(lambda: os.path.isfile(req))
                print("Restart game clicked -> app's request file:",
                      req if ok else "NOT WRITTEN",
                      "| box's request taken:",
                      not os.path.exists(os.path.join(box, "restart_game_0.req")))
            b.close()
    finally:
        demo.kill()
        if sync is not None:
            sync.kill()
            subprocess.run(["wsl.exe", "-e", "pkill", "-f", wsl_path(scratch)],
                           capture_output=True)
        print("sync log:\n" + (read(os.path.join(scratch, "sync.log")) or ""))


if __name__ == "__main__":
    main()
