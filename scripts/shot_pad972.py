"""PAD-972 proof shots and end-to-end run: a question for an app reporter.

    python scripts/shot_pad972.py <repo> <out_dir> [<prefix>]

Runs <repo>'s own Worker (tools/donations_worker/worker.js) on this PC over a
real SQLite database (this ticket's local_worker.mjs), files three reports
there as the app would and moves them along as pad-triage does: one being
worked on, one released, and one asked a question (``stage: question``; a
Worker from before PAD-972 refuses that stage and gets ``working``, which is
pad-triage's fallback).  Then serves <repo>'s app on a scratch settings
folder that remembers the three reports and shoots, with <prefix> (``after_``
by default) on each name:

* ``notice.png``  the window as the status ask lands (the top notice);
* ``board.png``   Your reports, with the question waiting;
* ``sent.png``    Your reports once the answer (words, a log too big to send
  whole, a picture) went: the card says Answer sent.  A copy of the app
  with no answer box shoots the same board again.

After the send it reads the answer back as pad-triage does (GET
/v1/admin/replies), checks the words and both files, posts /reply-taken and
checks nothing is left.  Needs Node 22.5+, Playwright (PAD_PWLIB or the user
site) and Edge.
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
QUESTION = ("Could you send DirectOutput.log? It is in the DirectOutput "
            "folder of your Visual Pinball install (often C:\\DirectOutput). "
            "Start the table once, then close it before you attach the log.")

# the app's file picker, answered from PAD972_PICK (paths split by
# os.pathsep): the page's own picker cannot be driven from here
WRAPPER = r'''
import os, runpy, sys
from pinball_decryptor.webui import dialogs
_file = dialogs.Dialogs.file
def file(self, mode, *a, **kw):
    pick = os.environ.get("PAD972_PICK")
    if pick and kw.get("multiple"):
        return tuple(pick.split(os.pathsep))
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
    h = {"content-type": "application/json", "User-Agent": "pad972-rig"}
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
        "title": title, "body": title + "\n\n(the record)", "app_version": "1.330.2",
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
    scratch = tempfile.mkdtemp(prefix="pad972-")
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
        a = _report(base, "Godzilla: the mode clip plays twice", now - 9 * 86400)
        b = _report(base, "Write stopped at 40% on the Godzilla card", now - 20 * 86400)
        q = _report(base, "Foo Fighters in Visual Pinball: the DOF toys never fire",
                    now - 2 * 86400)
        _call(base, "POST", "/v1/admin/reports/%s/stage" % a["id"],
              {"stage": "working", "ticket": "PAD-966", "progress": 40}, admin=True)
        _call(base, "POST", "/v1/admin/reports/%s/answer" % b["id"],
              {"state": "released", "version": "1.329.0",
               "message": "The write no longer stops at 40%."}, admin=True)
        st, out = _call(base, "POST", "/v1/admin/reports/%s/stage" % q["id"],
                        {"stage": "question", "ticket": "PAD-968",
                         "question": QUESTION}, admin=True)
        print("question stage:", st, out, flush=True)
        if st == 400:                   # a Worker from before PAD-972
            st, out = _call(base, "POST", "/v1/admin/reports/%s/stage" % q["id"],
                            {"stage": "working", "ticket": "PAD-968"}, admin=True)
            print("fallback stage:", st, out, flush=True)
        # the answer must come after the question, on the Worker's clock
        time.sleep(1.2)

        cfg_dir = os.path.join(scratch, "cfg", "pinball_decryptor")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "reports_cache.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"mine": [b, a, q], "checked_at": 0,
                       "install": "0123456789abcdef"}, f)
        settings = os.path.join(scratch, "settings.json")
        with open(settings, "w", encoding="utf-8") as f:
            json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
        # what the user attaches: a log too big to go whole, and a picture
        logf = os.path.join(scratch, "DirectOutput.log")
        with open(logf, "w", encoding="utf-8") as f:
            for i in range(60000):
                f.write("2026.11.03 21:%02d:%02d.%03d Table Foo Fighters: "
                        "output 0x%02x -> %d\n" % (i // 3600 % 60, i // 60 % 60,
                                                    i % 1000, i % 64, i % 2))
        pic = os.path.join(scratch, "cabinet.png")
        from PIL import Image
        Image.new("RGB", (320, 200), (40, 90, 160)).save(pic)
        wrapper = os.path.join(scratch, "serve.py")
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write(WRAPPER)
        import site
        proc, url = webui_shot.start_server(
            settings, scratch, app_cmd=[sys.executable, wrapper],
            extra_env={"PYTHONPATH": os.pathsep.join(
                           [repo, site.getusersitepackages()]),
                       "PAD_REPORTS_URL": base,
                       "PAD972_PICK": os.pathsep.join([logf, pic])})
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            # the status ask at startup
            for _ in range(60):
                rep = webui_shot.state(url)["shellx"]["report"]
                if rep.get("checked_at"):
                    break
                time.sleep(0.5)
            time.sleep(2)
            mine = webui_shot.state(url)["shellx"]["report"]["mine"]
            print("board:", json.dumps([m["board"] for m in mine], indent=1),
                  flush=True)
            banners = webui_shot.state(url)["shell"].get("banners") or []
            print("notice:", json.dumps([x for x in banners
                                         if x.get("id") == "report_answer"]),
                  flush=True)
            page.screenshot(path=os.path.join(out_dir, prefix + "notice.png"))
            answer = page.locator(".sx-banner-report_answer button",
                                  has_text="Answer it")
            if answer.count():
                answer.first.click()
            else:
                page.locator("button.sx-rep-btn").first.click()
                page.locator(".sx-report button", has_text="Your reports").first.click()
            page.wait_for_selector(".sx-reports .prb", timeout=20000)
            time.sleep(1.5)
            box = page.locator(".sx-reports").first
            box.screenshot(path=os.path.join(out_dir, prefix + "board.png"))
            if page.locator(".sx-ask").count():
                page.locator(".sx-ask textarea").fill(
                    "Here it is. I started the table, pressed Start, then "
                    "closed it. The cabinet picture shows where the toys are.")
                page.locator(".sx-ask button", has_text="Attach files").click()
                page.wait_for_selector(".sx-ask .chip.acc >> nth=1", timeout=20000)
                time.sleep(0.8)
                print("attached:", page.locator(".sx-ask .chip.acc").all_inner_texts(),
                      flush=True)
                page.locator(".sx-ask button", has_text="Send").click()
                page.wait_for_selector(".sx-reports .prb-out.ok >> text=Answer sent",
                                       timeout=30000)
                time.sleep(1.5)
            box.screenshot(path=os.path.join(out_dir, prefix + "sent.png"))
            browser.close()

        # pad-triage's half: collect the answer, take it, nothing left
        st, out = _call(base, "GET", "/v1/admin/replies", admin=True)
        rows = out.get("rows") or []
        for r in rows:
            print("reply for", r["id"], r["ticket"], "| question:", r["question"][:40],
                  "| message:", r["message"], flush=True)
            for f in r["files"]:
                data = base64.b64decode(f["b64"])
                print("   file", f["name"], f["type"], len(data), "bytes;",
                      "first line:", data.split(b"\n")[0][:90],
                      "| last line:", data.rstrip(b"\n").split(b"\n")[-1][:80],
                      flush=True)
        if rows:
            assert [r["id"] for r in rows] == [q["id"]]
            names = [f["name"] for f in rows[0]["files"]]
            assert names == ["DirectOutput.log", "cabinet.png"], names
            assert rows[0]["message"].startswith("Here it is.")
            st, _ = _call(base, "POST", "/v1/admin/reports/%s/reply-taken"
                          % q["id"], admin=True)
            assert st == 200
            st, out = _call(base, "GET", "/v1/admin/replies", admin=True)
            assert out["rows"] == [], out
            st, out = _call(base, "GET", "/v1/report/status?ids=" + q["id"])
            row = out["rows"][0]
            print("after reply-taken: stage", row["stage"], "question_at",
                  row["question_at"], "reply_at", row["reply_at"], flush=True)
            assert row["stage"] == "working" and row["reply_at"] >= row["question_at"]
            print("END TO END: OK", flush=True)
        else:
            print("no replies (a copy of the app with no answer box)", flush=True)
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
