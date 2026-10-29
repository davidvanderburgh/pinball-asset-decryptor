"""The Emulate video's last shot: a real frame of the game running (PAD-813).

    python scripts/getting_started/game_frame.py <slot> <out.png>

Starts the card through the app's Emulate tab on the rig slot you took
(``riglock.sh take --any PAD-813 ...``), muted, waits for attract mode,
reads the guest's own framebuffer with glshot.sh and stops the run.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import make_getting_started_videos as M  # noqa: E402

RIG = "/mnt/c" + M.REPO[2:].replace("\\", "/") + "/tools/spike2_emu"


def main():
    slot, out = sys.argv[1], os.path.abspath(sys.argv[2])
    from playwright.sync_api import sync_playwright
    os.environ.update({"PAD_SLOT": slot, "PAD_TICKET": "", "PAD_LABEL": "PAD-813-film",
                       "PAD_AUDIO": "0"})
    with sync_playwright() as pw:
        app = M.App(pw, M.REPO, {"last_manufacturer": "stern"}, rig=True)
        try:
            M.to_spike2(app)
            app.api("ui.select_tab", "emulate")
            time.sleep(3)
            app.api("ui.set", "emulate", "card", M.CARDS["deadpool"])
            time.sleep(3)
            print("run button:", app.state("emulate").get("run_btn"), flush=True)
            app.api("emulate.toggle")
            ok = app.wait(lambda: app.state("emulate").get("up"), timeout=900, step=3)
            print("up:", ok, flush=True)
            time.sleep(75)                      # boot checks, then attract
            wsl_out = "/mnt/c" + out[2:].replace("\\", "/")
            r = subprocess.run(["wsl", "-e", "bash", "-c",
                                "PAD_SLOT=%s bash %s/glshot.sh '%s'" % (slot, RIG, wsl_out)],
                               capture_output=True, text=True, timeout=120,
                               env=dict(os.environ, MSYS_NO_PATHCONV="1"))
            print(r.stdout[-800:], r.stderr[-800:], flush=True)
        finally:
            try:
                if (app.state("emulate").get("run_btn") or {}).get("mode") != "start":
                    app.api("emulate.toggle")             # Stop
                    app.wait(lambda: not app.state("emulate").get("up"), timeout=120, step=2)
            finally:
                app.close()


if __name__ == "__main__":
    main()
