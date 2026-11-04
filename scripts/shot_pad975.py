"""PAD-975 proof: Ctrl+V pastes a picture into Report a problem.

    python scripts/shot_pad975.py <repo> <out_dir>

Serves <repo> on a scratch settings folder, opens Report a problem from the
top bar, puts a picture on the REAL Windows clipboard (what Win+Shift+S
does), clicks into "What happened" and presses Ctrl+V.  Shoots
``report_before_paste.png`` and ``report_after_paste.png`` and prints the
report's picture as the app's state has it, and whether the paste event
carried the picture to the page (otherwise the app read the clipboard).
The clipboard's text is put back afterwards.  Needs Playwright (PAD_PWLIB
or the user site) and Edge.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402


def _ps(cmd):
    return subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", cmd],
                          capture_output=True, text=True, timeout=60)


def main():
    repo, out_dir = sys.argv[1:3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad975-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    from PIL import Image, ImageDraw
    pic = os.path.join(scratch, "clip.png")
    im = Image.new("RGB", (640, 360), (30, 60, 120))
    ImageDraw.Draw(im).rectangle((40, 40, 600, 320), outline=(255, 200, 0), width=8)
    im.save(pic)
    saved = _ps("Get-Clipboard -Raw").stdout
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
            ctx = browser.new_context(viewport={"width": 1500, "height": 950})
            page = ctx.new_page()
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            page.locator("button.sx-rep-btn").click()
            page.wait_for_selector("#sx-rep-text", timeout=20000)
            page.fill("#sx-rep-text", "The Write tab stopped at 40%, see the picture.")
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, "report_before_paste.png"))
            print("shot report_before_paste.png", flush=True)
            r = _ps("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                    "[System.Windows.Forms.Clipboard]::SetImage("
                    "[System.Drawing.Image]::FromFile('%s'))" % pic)
            print("clipboard set:", r.returncode, r.stderr.strip()[:200], flush=True)
            page.evaluate("""() => { window.__pasteSaw = null;
              document.addEventListener('paste', (e) => {
                const it = Array.from((e.clipboardData || {}).items || []);
                window.__pasteSaw = it.map((x) => x.kind + ':' + x.type);
              }, true); }""")
            page.click("#sx-rep-text")
            page.keyboard.press("Control+V")
            for _ in range(40):
                if page.locator(".sx-report .chip", has_text="pasted picture").count():
                    break
                time.sleep(0.25)
            time.sleep(0.8)
            print("paste event items:", page.evaluate("window.__pasteSaw"), flush=True)
            print("box text after paste:", repr(page.input_value("#sx-rep-text")), flush=True)
            chip = page.locator(".sx-report .chip", has_text="pasted picture")
            print("picture chip:", chip.inner_text() if chip.count() else None, flush=True)
            page.screenshot(path=os.path.join(out_dir, "report_after_paste.png"))
            print("shot report_after_paste.png", flush=True)
            # headless Edge hands the page an empty paste (the app read the
            # clipboard above); the page's own path, the paste event a
            # headed webview fires: a picture file, then plain text
            page.locator(".sx-report button", has_text="Remove").click()
            time.sleep(0.8)
            out = page.evaluate("""async () => {
              const bin = atob(%r);
              const u8 = new Uint8Array(bin.length);
              for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
              const fire = (dt) => {
                const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
                document.querySelector('#sx-rep-text').dispatchEvent(ev);
                return ev.defaultPrevented;
              };
              const a = new DataTransfer();
              a.items.add(new File([u8], 'image.png', {type: 'image/png'}));
              const picPrevented = fire(a);
              const b = new DataTransfer();
              b.setData('text/plain', 'some words');
              const textPrevented = fire(b);
              return {picPrevented, textPrevented};
            }""" % __import__("base64").b64encode(open(pic, "rb").read()).decode())
            for _ in range(40):
                if page.locator(".sx-report .chip", has_text="pasted picture").count():
                    break
                time.sleep(0.25)
            chip = page.locator(".sx-report .chip", has_text="pasted picture")
            print("page path:", out, "chip:", chip.inner_text() if chip.count() else None,
                  flush=True)
            browser.close()
    finally:
        if saved:
            subprocess.run(["powershell", "-NoProfile", "-STA", "-Command",
                            "$input | Set-Clipboard"], input=saved, text=True,
                           timeout=60)
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
