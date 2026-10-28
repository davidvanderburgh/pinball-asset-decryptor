"""PAD-606 proof shot: Advanced Audio Options, the "Allow replacements longer or shorter than the original" text (2 GB no longer trims: past it the longer sounds go into extra sound banks).

    python scripts/shot_pad523.py <repo> <out_dir> <prefix>

shot_pad312's scratch Godzilla project, Audio tab, "Advanced…" opened and its
longer-replacements section scrolled into view; the dialog is shot as
<prefix>_audio_advanced.png.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402


def main():
    repo, out, prefix = sys.argv[1:4]
    print("repo:", repo, flush=True)
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad606-")
    project = base._project(scratch)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            base._wait_scan(state, "audio")
            page.get_by_role("button", name="Advanced").first.click()
            page.wait_for_selector(".aud-adv", timeout=20000)
            time.sleep(1)
            blip = page.get_by_text("Allow replacements longer or shorter than the original", exact=False).first
            blip.scroll_into_view_if_needed()
            page.evaluate("document.querySelector('.aud-adv').closest('.bd')"
                          ".scrollTop -= 40")
            time.sleep(1)
            page.locator(".modal").last.screenshot(
                path=os.path.join(out, prefix + "_audio_advanced.png"))
            print("adv:", api("audio.advanced_get"), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
