"""PAD-929 proof shot: Report a problem with "Leave file paths ... out" ticked.

    python scripts/shot_pad929.py <repo> <out_dir>

Serves <repo> on a scratch settings folder with Stern picked and a card and a
project under the account's home folder (so their paths carry the account
name), opens Report a problem from the top bar and shoots ``report.png``: the
facts table under the form, with the box ticked as it opens.  Before PAD-929
the Card and Project rows showed the full paths whatever the box said.
Needs Playwright (PAD_PWLIB or the user site) and Edge.
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


def main():
    repo, out_dir = sys.argv[1:3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad929-")
    # a card and a project under %TEMP%, which is under the account's home
    project = os.path.join(scratch, "HEISEI v1.99D + daveyvandy modes")
    os.makedirs(os.path.join(project, "build"), exist_ok=True)
    card = os.path.join(project, "build", "Godzilla Premium 1.16 Heisei.raw")
    with open(card, "wb") as f:
        f.write(b"\0" * 4096)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "extract_output": project,
                       "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch,
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PAD_REPORTS_URL": "http://127.0.0.1:9"})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            page.locator("button.sx-rep-btn").first.click()
            page.wait_for_selector("table.sx-rep-tab", timeout=20000)
            time.sleep(1.5)
            rows = page.locator("table.sx-rep-tab tr").all_inner_texts()
            print("ticked:", json.dumps(rows, indent=1), flush=True)
            page.locator(".sx-report").first.screenshot(
                path=os.path.join(out_dir, "report.png"))
            print("shot report.png", flush=True)
            # untick it: the full paths come back, as the record has them
            page.locator(".sx-report label", has_text="Leave file paths").first.click()
            time.sleep(1)
            rows = page.locator("table.sx-rep-tab tr").all_inner_texts()
            print("unticked:", json.dumps(rows, indent=1), flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
