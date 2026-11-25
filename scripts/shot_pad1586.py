"""PAD-1586 proof shots: Mod Pack (with Move Your Mods), Partition Explorer and Test Card on a Stern Spike 3 card.

    python scripts/shot_pad1586.py <repo> <out_dir> [--after] [--card <Spike 3 .raw>] [--project <dir>]

Serves <repo> with a Spike 3 card on the Extract tab (which sets the Spike 3 era) and writes,
under the same names before (main) and after (--after, the ticket branch):

- <before_|after_>tabs.png        the tab rail: Mod Pack, Partition Explorer and Test Card
                                  missing before, there after
- <before_|after_>modpack.png     the Mod Pack tab (Export / Import / Move Your Mods)
- <before_|after_>partitions.png  the Partition Explorer on the card, games partition open
- <before_|after_>testcard.png    the Test Card tab

Needs Playwright (the user site-packages one), the installed Edge and the card's key.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike3\fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw"


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    card = sys.argv[sys.argv.index("--card") + 1] if "--card" in sys.argv else CARD
    project = (sys.argv[sys.argv.index("--project") + 1] if "--project" in sys.argv
               else r"C:\tmp\PAD-1586\fo081")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1586-")
    real = os.path.join(os.environ["APPDATA"], "pinball_decryptor", "settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes") or []
    launcher = os.path.join(scratch, "launch.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(S.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": codes,
                   "manufacturers": {"stern": {"extract_input": card,
                                               "extract_output": project,
                                               "write_assets": project,
                                               "partition_image": card}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
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
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "extract")
            time.sleep(8)                       # card detection sets the Spike 3 era
            tabs = [t for t in (state().get("tabs") or [])]
            print("tabs:", tabs, flush=True)
            page.screenshot(path=out("tabs.png"))
            for key, name, prep in (
                    ("modpack", "modpack.png", None),
                    ("partitions", "partitions.png",
                     lambda: api("partitions.open_image", card)),
                    ("testcard", "testcard.png", None)):
                try:
                    api("ui.select_tab", key)
                except Exception as e:                      # noqa: BLE001
                    print("select", key, "failed:", e, flush=True)
                time.sleep(2)
                if prep is not None:
                    try:
                        print(key, "prep:", prep(), flush=True)
                    except Exception as e:                  # noqa: BLE001
                        print(key, "prep failed:", e, flush=True)
                    time.sleep(6)
                if key == "partitions" and after:
                    # the games partition, down to the game's logo, previewed
                    parts = state().get("partitions", {}).get("parts") or []
                    games = next((p["value"] for p in parts if "games" in p["value"]), None)
                    print("parts:", [p["value"] for p in parts], flush=True)
                    if games:
                        api("partitions.select_partition", games)
                        time.sleep(3)
                        for d in ("/fallout_le", "/fallout_le/assets", "/fallout_le/assets/lcd"):
                            api("partitions.toggle", d, True)
                            time.sleep(2)
                        api("partitions.select", "/fallout_le/assets/lcd/GameLogo.png", 520, 300)
                        time.sleep(5)
                page.screenshot(path=out(name))
                print("shot", out(name), flush=True)
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
