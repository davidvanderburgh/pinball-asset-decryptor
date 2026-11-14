"""PAD-1254 proof shots and end-to-end run: a follow-up goes onto the open
report, and an answer carries the app's logs.

    python scripts/shot_pad1254.py <repo> <out_dir> [<prefix>]

Runs <repo>'s own Worker (tools/donations_worker/worker.js) on this PC over a
real SQLite database (local_worker.mjs), files three reports there as the app
would and moves them along as pad-triage does: one being worked on (PAD-1225),
one released, and one asked a question.  Then serves <repo>'s app on a scratch
settings folder that remembers the three and shoots, with <prefix> (``after_``
by default) on each name:

* ``report.png``  Report a problem as it opens (after: "This is about", with
  the report waiting on an answer picked);
* ``sent.png``    the window once a report about the PAD-1225 problem went
  with a picture (after: it went onto that report, not a new one);
* ``answer.png``  Your reports' answer box, words typed (after: "Include the
  app's logs", ticked).

The answer is sent too.  Then it reads what came in as pad-triage does (GET
/v1/admin/replies) and, on a copy of the app with the follow-up, checks both
rows: the follow-up on PAD-1225's report with its words, the record (log
tails) and the picture; the answer with its words and the record.  Needs Node
22.5+, Playwright (PAD_PWLIB or the user site) and Edge.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LOCAL_WORKER = os.path.join(os.path.dirname(HERE), "tools", "donations_worker",
                            "local_worker.mjs")
APP_KEY = "pad-shelters-2026"
QUESTION = ("Could you start the Batman 66 table once more and, while the "
            "Bat Phone hurry-up is showing, send what the app logged?")
FOLLOW = ("Tried the new version: the Bat Phone still stops lighting after "
          "the second hurry-up. Picture attached.")
ANSWER = ("Started it again, the hurry-up showed for about ten seconds and "
          "the Bat Phone never lit.")

# the app's file pickers, answered from PAD1254_PICK: the page's own picker
# cannot be driven from here
WRAPPER = r'''
import os, runpy, sys
from pinball_decryptor.webui import dialogs
_file = dialogs.Dialogs.file
def file(self, mode, *a, **kw):
    pick = os.environ.get("PAD1254_PICK")
    if pick and mode == "open":
        return tuple(pick.split(os.pathsep)) if kw.get("multiple") else pick
    return _file(self, mode, *a, **kw)
dialogs.Dialogs.file = file
sys.argv = ["pinball_decryptor.webui.host"] + sys.argv[1:]
runpy.run_module("pinball_decryptor.webui.host", run_name="__main__", alter_sys=True)
'''


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _call(base, method, path, body=None, admin=False):
    h = {"content-type": "application/json", "User-Agent": "pad1254-rig"}
    if admin:
        h["X-PAD-Admin"] = "adm"
    else:
        h["X-PAD-Key"] = APP_KEY
    req = urllib.request.Request(
        base + path, method=method, headers=h,
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _report(base, title, at):
    st, out = _call(base, "POST", "/v1/report", {
        "title": title, "body": title + "\n\n(the record)", "app_version": "1.427.2",
        "platform": "win32"})
    assert st == 201, (st, out)
    rid = out["id"]
    assert _call(base, "POST", "/v1/admin/reports/%s/taken" % rid,
                 admin=True)[0] == 200
    return {"id": rid, "title": title, "at": at, "state": "received",
            "version": "", "message": "", "answered_at": 0, "seen": True,
            "stage": "received", "ticket": "", "progress": -1}


def main():
    repo, out_dir = sys.argv[1:3]
    prefix = sys.argv[3] if len(sys.argv) > 3 else "after_"
    repo = os.path.abspath(repo)
    os.makedirs(out_dir, exist_ok=True)
    print("code under test:", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad1254-")
    port = _free_port()
    wk = subprocess.Popen(
        ["node", "--no-warnings", LOCAL_WORKER, str(port), "--dir",
         os.path.join(repo, "tools", "donations_worker"),
         "--db", os.path.join(scratch, "reports.db")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert "local worker on" in wk.stdout.readline()
    base = "http://127.0.0.1:%d" % port
    proc = None
    try:
        now = time.time()
        a = _report(base, "Batman 66 VPX: the Bat Phone stops lighting",
                    now - 3 * 86400)
        b = _report(base, "Beatles in Visual Pinball: no flipper sound",
                    now - 20 * 86400)
        q = _report(base, "Batman 66 VPX: Bat Phone hurry-up never scores",
                    now - 1 * 86400)
        _call(base, "POST", "/v1/admin/reports/%s/stage" % a["id"],
              {"stage": "ready", "ticket": "PAD-1225", "progress": 100}, admin=True)
        _call(base, "POST", "/v1/admin/reports/%s/answer" % b["id"],
              {"state": "released", "version": "1.420.0",
               "message": "The flipper sounds play again."}, admin=True)
        st, out = _call(base, "POST", "/v1/admin/reports/%s/stage" % q["id"],
                        {"stage": "question", "ticket": "PAD-1240",
                         "question": QUESTION}, admin=True)
        print("question stage:", st, out, flush=True)
        time.sleep(1.2)                 # answers come after the question

        cfg_dir = os.path.join(scratch, "cfg", "pinball_decryptor")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "reports_cache.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"mine": [b, a, q], "checked_at": 0,
                       "install": "0123456789abcdef"}, f)
        settings = os.path.join(scratch, "settings.json")
        with open(settings, "w", encoding="utf-8") as f:
            json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
        pic = os.path.join(scratch, "batphone.png")
        from PIL import Image
        Image.new("RGB", (640, 400), (30, 30, 60)).save(pic)
        wrapper = os.path.join(scratch, "serve.py")
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write(WRAPPER)
        import site
        proc, url = webui_shot.start_server(
            settings, scratch, app_cmd=[sys.executable, wrapper],
            extra_env={"PYTHONPATH": os.pathsep.join(
                           [repo, site.getusersitepackages()]),
                       "PAD_REPORTS_URL": base, "PAD1254_PICK": pic})
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            for _ in range(60):          # the status ask at startup
                if webui_shot.state(url)["shellx"]["report"].get("checked_at"):
                    break
                time.sleep(0.5)
            time.sleep(1.5)
            mine = webui_shot.state(url)["shellx"]["report"]["mine"]
            print("board:", [(m["board"]["ticket"], m["state"],
                              m["board"]["stage"]) for m in mine], flush=True)

            # Report a problem, as it opens
            page.locator("button.sx-rep-btn").first.click()
            page.wait_for_selector(".sx-report textarea", timeout=20000)
            time.sleep(1.5)
            dlg = page.locator(".sx-report .modal, .sx-report").first
            about = page.locator(".sx-report .sx-rep-about select")
            has_about = about.count() > 0
            if has_about:
                print("about picked:", about.input_value(),
                      "(waiting one is", q["id"] + ")", flush=True)
                assert about.input_value() == q["id"]
                print("about options:", about.locator("option").all_inner_texts(),
                      flush=True)
            dlg.screenshot(path=os.path.join(out_dir, prefix + "report.png"))

            # a follow-up on PAD-1225's report: words and a picture
            if has_about:
                about.select_option(a["id"])
            page.locator(".sx-report textarea").first.fill(FOLLOW)
            page.locator(".sx-report button", has_text="Add a picture").click()
            page.wait_for_selector(".sx-report .chip.acc", timeout=20000)
            page.locator(".sx-report button", has_text="Send").last.click()
            page.wait_for_selector(".sx-report .note", timeout=30000)
            time.sleep(1.5)
            page.locator(".sx-report").first.screenshot(
                path=os.path.join(out_dir, prefix + "sent.png"))
            print("sent note:", page.locator(".sx-report .note").first.inner_text(),
                  flush=True)
            page.locator(".sx-report button", has_text="See your reports").click()

            # the answer box
            page.wait_for_selector(".sx-reports .sx-ask textarea", timeout=20000)
            time.sleep(1)
            page.locator(".sx-ask textarea").fill(ANSWER)
            time.sleep(0.5)
            page.locator(".sx-ask").first.screenshot(
                path=os.path.join(out_dir, prefix + "answer.png"))
            page.locator(".sx-ask button", has_text="Send").click()
            page.wait_for_selector(".sx-reports .prb-out.ok >> text=Answer sent",
                                   timeout=30000)
            time.sleep(1)
            page.locator(".sx-reports").first.screenshot(
                path=os.path.join(out_dir, prefix + "board.png"))
            browser.close()

        # pad-triage's half: collect what came in
        st, out = _call(base, "GET", "/v1/admin/replies", admin=True)
        rows = {r["id"]: r for r in out.get("rows") or []}
        for r in rows.values():
            print("reply for", r["id"], r["ticket"], "| message:", r["message"],
                  flush=True)
            for f in r["files"]:
                data = base64.b64decode(f["b64"])
                print("   file", f["name"], f["type"], len(data), "bytes;",
                      "first line:", data.split(b"\n")[0][:90], flush=True)
        if not has_about:
            print("a copy of the app with no follow-up: replies",
                  sorted(rows), flush=True)
            return
        fu = rows[a["id"]]
        assert fu["ticket"] == "PAD-1225" and fu["message"] == FOLLOW, fu
        names = [f["name"] for f in fu["files"]]
        assert names[0] == "pad-report.txt" and names[1].startswith("picture"), names
        rec = base64.b64decode(fu["files"][0]["b64"]).decode("utf-8")
        assert "Log (last" in rec and FOLLOW in rec, rec[:400]
        an = rows[q["id"]]
        assert an["message"] == ANSWER, an
        assert [f["name"] for f in an["files"]] == ["pad-report.txt"], an["files"]
        rec = base64.b64decode(an["files"][0]["b64"]).decode("utf-8")
        assert "Log (last" in rec, rec[:400]
        # nothing new was filed (the before run files a fourth report here)
        st, out = _call(base, "GET", "/v1/admin/reports", admin=True)
        waiting = len(out.get("rows") or [])
        print("new reports waiting to be filed:", waiting, flush=True)
        assert st == 200 and waiting == 0, out
        for rid in (a["id"], q["id"]):
            _call(base, "POST", "/v1/admin/reports/%s/reply-taken" % rid, admin=True)
        st, out = _call(base, "GET", "/v1/report/status?ids=%s,%s" % (a["id"], q["id"]))
        print("after: ", [(r["id"][:8], r["stage"], r["reply_at"] >= r["question_at"])
                          for r in out["rows"]], flush=True)
        print("END TO END: OK", flush=True)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(10)
            except Exception:                               # noqa: BLE001
                proc.kill()
        wk.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
