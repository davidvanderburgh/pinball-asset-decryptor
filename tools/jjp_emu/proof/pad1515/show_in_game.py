"""PAD-1515 proof: the Modes tab's "Show it in the game", end to end, in the real app.
    python show_in_game.py <out dir>
Starts the app (scratch settings: David's own mode folders are never touched) on Wonka 03.03, picks
its stock ISO under Build, presses Show it in the game (the runtime is built for the ISO first, then
the game runs hidden and muted on the emulator), waits for it, and checks the game's attract and
in-game screens came back into the mode folder's .layout/, each with its parts named.  The census
files are copied to <out dir>.  Needs the purple JJP key attached (usbipd).
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

ISO = r"D:\Pinball\images\JJP\Wonka-v03.03.iso"


def main():
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1515show-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": ISO, "write_original": ISO, "write_output": scratch}}}, f)
    modes = os.path.join(scratch, "jjp_modes")
    import site
    proc, url = webui_shot.start_server(settings, scratch, extra_env={
        "PYTHONPATH": site.getusersitepackages(), "PAD_JJP_MODS_DIR": modes, "PAD_JJP_MODES_DIR": modes,
        "PAD_RUNTIME": os.environ.get("PAD_RUNTIME", "0")})
    rc = 1
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        webui_shot.api(url, "ui.select_tab", "modes")
        time.sleep(3)
        webui_shot.api(url, "modes.jjp_set_iso", ISO)
        webui_shot.api(url, "modes.jjp_show_in_game")
        t0, last = time.time(), ""
        while time.time() - t0 < 3600:
            time.sleep(5)
            sc = ((webui_shot.state(url).get("modes") or {}).get("jjp") or {}).get("screens") or {}
            if sc.get("msg") != last:
                last = sc.get("msg") or ""
                print("%5.0f s  %s" % (time.time() - t0, last[:160]), flush=True)
            if sc.get("done"):
                break
        j = (webui_shot.state(url).get("modes") or {}).get("jjp") or {}
        sc, game = j.get("screens") or {}, (j.get("layout") or {}).get("game") or {}
        frames = os.path.join(j.get("folder", ""), ".layout")
        got = sorted(os.listdir(frames)) if os.path.isdir(frames) else []
        print("done:", sc.get("ok"), sc.get("msg"), "in", sc.get("secs"), "s")
        print("files:", got)
        print("layout: screens", game.get("censuses"), "-", len(game.get("elements") or []), "parts,",
              sum(1 for e in game.get("elements") or [] if not e.get("fixed")), "named")
        for f in got:
            shutil.copy(os.path.join(frames, f), out)
        rc = 0 if sc.get("ok") and {"attract.json", "game.json", "attract.png", "game.png"} <= set(got) else 1
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
