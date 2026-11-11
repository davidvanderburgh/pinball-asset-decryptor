"""Worktree chooser logic — parsing, discovery filters, and the no-op
guarantees that keep it invisible outside a dev tree with worktrees."""

import json
import os

import pytest

from pinball_decryptor import worktree_picker as wp


SAMPLE = """\
worktree C:/Users/david/Documents/development/pinball-asset-decryptor
HEAD d085f81aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
branch refs/heads/main

worktree C:/Users/david/Documents/development/pinball-asset-decryptor-wt/item-33
HEAD 1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
branch refs/heads/item/33

worktree C:/Users/david/Documents/development/pinball-asset-decryptor/.claude/worktrees/nice-austin
HEAD 712bfa5aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
branch refs/heads/claude/nice-austin-2fa8d1

worktree C:/somewhere/detached-copy
HEAD 2222222aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
detached
"""


def test_parse_worktree_list():
    entries = wp.parse_worktree_list(SAMPLE)
    assert entries == [
        ("C:/Users/david/Documents/development/pinball-asset-decryptor",
         "main"),
        ("C:/Users/david/Documents/development/pinball-asset-decryptor-wt/item-33",
         "item/33"),
        ("C:/Users/david/Documents/development/pinball-asset-decryptor/.claude/worktrees/nice-austin",
         "claude/nice-austin-2fa8d1"),
        ("C:/somewhere/detached-copy", None),
    ]


def test_parse_worktree_list_no_trailing_blank():
    entries = wp.parse_worktree_list(
        "worktree /a/b\nHEAD 123\nbranch refs/heads/item/7")
    assert entries == [("/a/b", "item/7")]


def _make_checkout(base, name):
    p = base / name / "pinball_decryptor"
    p.mkdir(parents=True)
    (p / "__main__.py").write_text("")
    return str(base / name)


def test_discover_filters_and_sorts(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path, "repo")
    wt9 = _make_checkout(tmp_path, "wt/item-9")
    wt1b = _make_checkout(tmp_path, "wt/item-1b")
    wt33 = _make_checkout(tmp_path, "wt/item-33")
    # A worktree whose directory lost the entry point is not runnable.
    broken = str(tmp_path / "wt" / "item-4")
    os.makedirs(broken)
    # Session-internal worktrees are noise, not run targets.
    claude = _make_checkout(tmp_path, os.path.join("repo", ".claude", "worktrees", "x"))

    porcelain = ""
    for path, branch in [
            (root, "main"), (wt33, "item/33"), (broken, "item/4"),
            (claude, "claude/x"), (wt9, "item/9"), (wt1b, "item/1b")]:
        porcelain += "worktree %s\nHEAD 0\nbranch refs/heads/%s\n\n" % (
            path, branch)
    monkeypatch.setattr(wp, "_git", lambda args, cwd, timeout=10: porcelain)

    found = wp.discover_other_checkouts(root)
    assert [b for _, b in found] == ["item/1b", "item/9", "item/33"]


def test_discover_orders_by_recency(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path, "repo")
    wt9 = _make_checkout(tmp_path, "wt/item-9")
    wt33 = _make_checkout(tmp_path, "wt/item-33")

    porcelain = ""
    for path, branch in [(root, "main"), (wt9, "item/9"), (wt33, "item/33")]:
        porcelain += "worktree %s\nHEAD 0\nbranch refs/heads/%s\n\n" % (
            path, branch)
    monkeypatch.setattr(wp, "_git", lambda args, cwd, timeout=10: porcelain)
    # item/33 is the lower item number by the old sort, but item/9 was
    # touched an hour ago and item/33 last week.
    monkeypatch.setattr(wp, "touched_at",
                        {wt9: 5000.0, wt33: 1000.0}.get)

    assert [b for _, b in wp.discover_other_checkouts(root)] == [
        "item/9", "item/33"]


def test_dirty_paths():
    status = (
        " M pinball_decryptor/app.py\n"
        "?? plans/notes.md\n"
        "R  old/name.py -> new/name.py\n"
        ' M "spaced name.py"\n')
    assert wp.dirty_paths(status) == [
        "pinball_decryptor/app.py", "plans/notes.md", "new/name.py",
        "spaced name.py"]


def test_touched_at_uses_newest_of_commit_and_edits(tmp_path, monkeypatch):
    checkout = tmp_path / "wt"
    (checkout / "plans").mkdir(parents=True)
    edited = checkout / "plans" / "TODO.md"
    edited.write_text("x", encoding="utf-8")
    os.utime(edited, (9_000.0, 9_000.0))
    monkeypatch.setattr(wp, "_STATUS_CACHE", {})
    monkeypatch.setattr(wp, "_COMMIT_CACHE", {})
    answers = {("log", "-1", "--format=%ct%n%s"): "1000\nold commit\n",
               ("status", "--porcelain"): " M plans/TODO.md\n M gone.py\n"}
    monkeypatch.setattr(
        wp, "_git", lambda args, cwd, timeout=10: answers.get(tuple(args)))

    # The uncommitted edit is newer than HEAD, and a listed-but-missing
    # file is skipped rather than fatal.
    assert wp.touched_at(str(checkout)) == 9_000.0

    # With nothing dirty, HEAD's commit time stands on its own.
    monkeypatch.setattr(wp, "_STATUS_CACHE", {})
    monkeypatch.setattr(wp, "_COMMIT_CACHE", {})
    answers[("status", "--porcelain")] = ""
    assert wp.touched_at(str(checkout)) == 1000.0


def test_touched_at_no_git_is_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "_STATUS_CACHE", {})
    monkeypatch.setattr(wp, "_COMMIT_CACHE", {})
    monkeypatch.setattr(wp, "_git", lambda args, cwd, timeout=10: None)
    assert wp.touched_at(str(tmp_path)) == 0.0


def test_chooser_rows_main_sorts_by_recency(monkeypatch):
    monkeypatch.setattr(
        wp, "_git",
        lambda args, cwd, timeout=10: "main\n" if args[0] == "rev-parse"
        else None)
    monkeypatch.setattr(wp, "_describe", lambda path, branch: branch)
    others = [("/wt/item-9", "item/9"), ("/wt/item-33", "item/33")]

    # Worked in a worktree last: it leads, main falls below it.
    monkeypatch.setattr(wp, "touched_at",
                        {"/root": 100.0, "/wt/item-9": 300.0,
                         "/wt/item-33": 200.0}.get)
    rows = wp.chooser_rows("/root", others)
    assert [p for p, _ in rows] == ["/wt/item-9", "/wt/item-33", "/root"]
    assert rows[-1][1] == "main  —  this checkout"

    # Worked in main last: main leads again.
    monkeypatch.setattr(wp, "touched_at",
                        {"/root": 900.0, "/wt/item-9": 300.0,
                         "/wt/item-33": 200.0}.get)
    rows = wp.chooser_rows("/root", others)
    assert [p for p, _ in rows] == ["/root", "/wt/item-9", "/wt/item-33"]


def test_discover_git_failure_is_empty(monkeypatch):
    monkeypatch.setattr(wp, "_git", lambda args, cwd, timeout=10: None)
    assert wp.discover_other_checkouts("C:/anywhere") == []


def test_item_title():
    todo = (
        "- [ ] **33. Save-state slots need visibility.** `S2 D3`\n"
        "- [ ] **1b. LED fade decode.** `S2 D2`\n")
    assert wp.item_title(todo, "item/33") == "Save-state slots need visibility"
    assert wp.item_title(todo, "item/1b") == "LED fade decode"
    assert wp.item_title(todo, "item/99") is None
    assert wp.item_title(todo, "main") is None
    assert wp.item_title(todo, None) is None


def test_item_title_wrapped_across_lines():
    # Most real queue titles hard-wrap mid-bold — the match must cross
    # newlines and collapse the wrap indentation.
    todo = (
        "- [ ] **27. Any Spike 2 title should load, show a switch layout, "
        "and start a\n"
        "      game. Today only Godzilla does.** `S1 D3`\n")
    assert wp.item_title(todo, "item/27") == (
        "Any Spike 2 title should load, show a switch layout, and start a "
        "game. Today only Godzilla does")


def test_item_title_number_is_anchored():
    todo = "- [ ] **13. Save and load save states.** `S2 D2`\n"
    # item/1 must not match inside **13. — the dot anchors the number.
    assert wp.item_title(todo, "item/1") is None


def test_item_title_against_real_todo():
    """The regex must keep matching the REAL queue file's format."""
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(wp.__file__)))
    with open(os.path.join(root, "plans", "TODO.md"),
              encoding="utf-8") as fh:
        todo = fh.read()
    nums = re.findall(r"^- \[ \] \*\*(\w+)\.", todo, re.M)
    assert nums, "no open queue items found — format changed?"
    for num in nums:
        title = wp.item_title(todo, "item/" + num)
        assert title, "item %s title did not parse" % num
        assert "\n" not in title and "  " not in title


def test_checkout_badge(tmp_path, monkeypatch):
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "TODO.md").write_text(
        "- [ ] **27. Any Spike 2 title should load, show a switch layout, "
        "and start a\n      game. Today only Godzilla does.** `S1 D3`\n",
        encoding="utf-8")
    answers = {}
    monkeypatch.setattr(
        wp, "_git", lambda args, cwd, timeout=10: answers.get(tuple(args)))

    # Main checkout, master, detached HEAD, no git: all badge-less.
    for quiet in ("main\n", "master\n", "HEAD\n", None):
        answers[("rev-parse", "--abbrev-ref", "HEAD")] = quiet
        assert wp.checkout_badge(str(tmp_path)) is None

    # An item worktree names the branch AND the queue item.
    answers[("rev-parse", "--abbrev-ref", "HEAD")] = "item/27\n"
    badge = wp.checkout_badge(str(tmp_path))
    assert badge.startswith("item/27 — Any Spike 2 title should load")

    # A non-item branch still names itself, without a title.
    answers[("rev-parse", "--abbrev-ref", "HEAD")] = "american-pinball\n"
    assert wp.checkout_badge(str(tmp_path)) == "american-pinball"


def test_shorten():
    assert wp._shorten("short") == "short"
    long = "x" * 100
    assert len(wp._shorten(long)) == 64
    assert wp._shorten(long).endswith("…")


@pytest.fixture(autouse=True)
def _not_a_ticket_launch(monkeypatch):
    """pad-triage launches a ticket's app with PAD_TICKET set, and the
    chooser then skips itself (PAD-754); a test session may carry that
    variable too, so every test here starts without it."""
    monkeypatch.delenv("PAD_TICKET", raising=False)
    # nor may a test find the real pad-triage beside the checkout (PAD-1130)
    monkeypatch.setenv(wp.ENV_TRIAGE_DIR, os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "no-such-pad-triage"))
    monkeypatch.setattr(wp, "_TICKETS", {})


def test_pick_noop_when_launched_for_a_ticket(monkeypatch):
    """pad-triage's launch (PAD_TICKET=PAD-n, cwd the ticket's worktree):
    nothing to choose, and no 20 s of git status over every worktree."""
    monkeypatch.delenv(wp.ENV_PICKED, raising=False)
    monkeypatch.setenv("PAD_TICKET", "PAD-754")
    monkeypatch.setattr(wp, "discover_other_checkouts",
                        lambda root: (_ for _ in ()).throw(AssertionError))
    assert wp.dev_pick_checkout() is True


def test_pick_noop_when_child(monkeypatch):
    monkeypatch.setenv(wp.ENV_PICKED, "1")
    # Discovery must not even run — a child re-asking is the recursion bug.
    monkeypatch.setattr(wp, "discover_other_checkouts",
                        lambda root: (_ for _ in ()).throw(AssertionError))
    assert wp.dev_pick_checkout() is True


def test_pick_noop_when_no_worktrees(monkeypatch):
    monkeypatch.delenv(wp.ENV_PICKED, raising=False)
    monkeypatch.setattr(wp, "discover_other_checkouts", lambda root: [])
    assert wp.dev_pick_checkout() is True


def test_pick_broken_chooser_still_launches(monkeypatch):
    monkeypatch.delenv(wp.ENV_PICKED, raising=False)
    monkeypatch.setattr(wp, "discover_other_checkouts",
                        lambda root: [("/wt/item-9", "item/9")])
    def boom(root, others):
        raise RuntimeError("no display")
    monkeypatch.setattr(wp, "_ask", boom)
    assert wp.dev_pick_checkout() is True


def test_pick_worktree_launches_child(monkeypatch):
    monkeypatch.delenv(wp.ENV_PICKED, raising=False)
    monkeypatch.setattr(wp, "discover_other_checkouts",
                        lambda root: [("/wt/item-9", "item/9")])
    monkeypatch.setattr(wp, "_ask", lambda root, others: "/wt/item-9")
    launched = []
    monkeypatch.setattr(wp, "_launch", launched.append)
    assert wp.dev_pick_checkout() is False
    assert launched == ["/wt/item-9"]


def test_pick_cancel_launches_nothing(monkeypatch):
    monkeypatch.delenv(wp.ENV_PICKED, raising=False)
    monkeypatch.setattr(wp, "discover_other_checkouts",
                        lambda root: [("/wt/item-9", "item/9")])
    monkeypatch.setattr(wp, "_ask", lambda root, others: None)
    launched = []
    monkeypatch.setattr(wp, "_launch", launched.append)
    assert wp.dev_pick_checkout() is False
    assert launched == []


def test_pick_this_checkout_continues(monkeypatch):
    monkeypatch.delenv(wp.ENV_PICKED, raising=False)
    root = os.path.dirname(os.path.dirname(os.path.abspath(wp.__file__)))
    monkeypatch.setattr(wp, "discover_other_checkouts",
                        lambda r: [("/wt/item-9", "item/9")])
    monkeypatch.setattr(wp, "_ask", lambda r, others: root)
    assert wp.dev_pick_checkout() is True


# ----------------------------------------------------------------------
# the chooser window (a pywebview page in a child process)
# ----------------------------------------------------------------------
ROWS = [("/wt/main", "main  —  this checkout"),
        ("/wt/item-9", "item/9  —  Save <slots> & more")]


def _fake_rows(monkeypatch):
    monkeypatch.setattr(wp, "chooser_rows", lambda root, others: list(ROWS))


def test_ask_without_pywebview_starts_this_checkout(monkeypatch, capsys):
    _fake_rows(monkeypatch)
    monkeypatch.setattr(wp, "_chooser_python", lambda root: None)
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: (
        _ for _ in ()).throw(AssertionError("no child without pywebview")))
    assert wp._ask("/wt/main", [("/wt/item-9", "item/9")]) == "/wt/main"
    assert "pywebview" in capsys.readouterr().err


class _Done:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_ask_runs_the_window_in_a_child(monkeypatch):
    _fake_rows(monkeypatch)
    monkeypatch.setattr(wp, "_chooser_python", lambda root: "py.exe")
    seen = {}

    def run(cmd, input=None, **kw):
        seen["cmd"], seen["input"] = cmd, input
        return _Done(stdout=b'noise\n{"choice": 1}\n')
    monkeypatch.setattr(wp.subprocess, "run", run)
    assert wp._ask("/wt/main", []) == "/wt/item-9"
    assert seen["cmd"][0] == "py.exe"
    assert seen["cmd"][-1] == "--choose"
    assert os.path.samefile(seen["cmd"][1], wp.__file__)
    labels = json.loads(seen["input"].decode("utf-8"))["labels"]
    assert labels == [text for _, text in ROWS]


def test_ask_cancelled_window_is_none(monkeypatch):
    _fake_rows(monkeypatch)
    monkeypatch.setattr(wp, "_chooser_python", lambda root: "py.exe")
    monkeypatch.setattr(wp.subprocess, "run",
                        lambda *a, **k: _Done(stdout=b'{"choice": null}\n'))
    assert wp._ask("/wt/main", []) is None


def test_failed_child_starts_this_checkout(monkeypatch, capsys):
    monkeypatch.delenv(wp.ENV_PICKED, raising=False)
    monkeypatch.setattr(wp, "discover_other_checkouts",
                        lambda root: [("/wt/item-9", "item/9")])
    _fake_rows(monkeypatch)
    monkeypatch.setattr(wp, "_chooser_python", lambda root: "py.exe")
    monkeypatch.setattr(wp.subprocess, "run",
                        lambda *a, **k: _Done(returncode=1, stderr=b"boom"))
    launched = []
    monkeypatch.setattr(wp, "_launch", launched.append)
    assert wp.dev_pick_checkout() is True
    assert launched == []
    assert "chooser failed" in capsys.readouterr().err


def test_chooser_html_lists_the_rows_in_order_escaped():
    page = wp.chooser_html([text for _, text in ROWS])
    assert page.index("this checkout") < page.index("item/9")
    assert "Save &lt;slots&gt; &amp; more" in page
    assert "<slots>" not in page
    assert page.count('class="row"') == 2
    assert wp._CHOOSER_QUESTION in page
    # ten rows show before the list scrolls, and the window fits its page
    assert "max-height: %dpx" % (wp._CHOOSER_ROW_PX * 10 + 2) in page
    assert 'addEventListener("pywebviewready", fit)' in page


def test_choose_main_answers_on_stdout(monkeypatch, capsys):
    """The child: rows in on stdin, a click on the second row, the index
    out on stdout."""
    import io
    import sys
    import types
    made = {}

    class _Win:
        destroyed = False

        def destroy(self):
            self.destroyed = True

    def create_window(title, html=None, js_api=None, **kw):
        made.update(title=title, html=html, api=js_api, kw=kw, win=_Win())
        return made["win"]

    def start(*a, **k):
        made["api"].pick(1)
    fake = types.SimpleNamespace(create_window=create_window, start=start)
    monkeypatch.setitem(sys.modules, "webview", fake)
    payload = json.dumps({"labels": ["a", "b"]}).encode("utf-8")
    monkeypatch.setattr(sys, "stdin",
                        types.SimpleNamespace(buffer=io.BytesIO(payload)))
    assert wp._choose_main() == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"choice": 1}
    assert made["win"].destroyed
    assert made["kw"]["on_top"] is True


def test_choose_main_closed_window_is_null(monkeypatch, capsys):
    import io
    import sys
    import types
    fake = types.SimpleNamespace(
        create_window=lambda *a, **k: types.SimpleNamespace(
            destroy=lambda: None),
        start=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "webview", fake)
    payload = json.dumps({"labels": ["a"]}).encode("utf-8")
    monkeypatch.setattr(sys, "stdin",
                        types.SimpleNamespace(buffer=io.BytesIO(payload)))
    wp._choose_main()
    assert json.loads(capsys.readouterr().out.strip()) == {"choice": None}


# ----------------------------------------------------------------------
# pad-triage's ticket trees (PAD-1130)
# ----------------------------------------------------------------------
def _fake_triage(tmp_path, tickets):
    """A pad-triage folder: work/repo, a ticket tree per (id, status,
    title), and work/padtriage.db holding those tickets."""
    import sqlite3
    triage = tmp_path / "pad-triage"
    (triage / "work" / "repo").mkdir(parents=True)
    con = sqlite3.connect(str(triage / "work" / "padtriage.db"))
    con.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, status TEXT,"
                " title TEXT, subject TEXT)")
    trees = {}
    for tid, status, title in tickets:
        con.execute("INSERT INTO tickets VALUES (?, ?, ?, NULL)",
                    (tid, status, title))
        trees[tid] = _make_checkout(triage / "work" / "tickets",
                                    "PAD-%d" % tid)
    con.commit()
    con.close()
    return str(triage), trees


def _porcelain(entries):
    out = ""
    for path, branch in entries:
        out += "worktree %s\nHEAD 0\n" % path
        out += ("branch refs/heads/%s\n\n" % branch) if branch \
            else "detached\n\n"
    return out


def test_ticket_trees_open_ones_only(tmp_path, monkeypatch):
    """The dev checkout has no worktrees of its own; pad-triage's clone
    has a tree per ticket.  The open tickets' trees are offered, labelled
    with their titles; a closed ticket's lingering tree, the clone itself
    and its detached QA tree are not."""
    root = _make_checkout(tmp_path, "pinball-asset-decryptor")
    triage, trees = _fake_triage(tmp_path, [
        (1128, "AWAITING_USER", "Jaws VPX: plunger"),
        (1090, "NEEDS_ATTENTION", "Spike 3 emulator"),
        (586, "REJECTED", "Feasibility: JJP modes"),
        (12, "CLOSED", "old")])
    monkeypatch.delenv(wp.ENV_TRIAGE_DIR)     # found as root's sibling
    clone = os.path.join(triage, "work", "repo")
    clone_list = _porcelain(
        [(clone, "main"), (os.path.join(triage, "work", "qa"), None)]
        + [(trees[t], "ticket/PAD-%d" % t) for t in (1128, 1090, 586, 12)])

    def git(args, cwd, timeout=10):
        if args[:2] == ["worktree", "list"]:
            if os.path.normcase(cwd) == os.path.normcase(clone):
                return clone_list
            return _porcelain([(root, "main")])
        return ""
    monkeypatch.setattr(wp, "_git", git)
    monkeypatch.setattr(wp, "touched_at", {trees[1128]: 300.0,
                                           trees[1090]: 200.0}.get)

    found = wp.discover_other_checkouts(root)
    assert [b for _, b in found] == ["ticket/PAD-1128", "ticket/PAD-1090"]
    assert wp._describe(*found[0]) == \
        "PAD-1128  —  Jaws VPX: plunger  (awaiting user)"


def test_ticket_tree_launch_sets_pad_ticket(tmp_path, monkeypatch):
    """A picked ticket tree starts as pad-triage's Launch app starts it:
    PAD_TICKET=PAD-n (the rig claim keys on it), no CLAUDECODE."""
    tree = os.path.normpath(str(tmp_path / "PAD-7"))
    monkeypatch.setattr(wp, "_TICKETS",
                        {os.path.normcase(tree): ("PAD-7", "t", "WORKING")})
    monkeypatch.setenv("CLAUDECODE", "1")
    calls = []
    monkeypatch.setattr(wp.subprocess, "Popen",
                        lambda cmd, cwd, env: calls.append((cwd, env)))
    wp._launch(tree)
    cwd, env = calls[0]
    assert cwd == tree
    assert env["PAD_TICKET"] == "PAD-7" and env[wp.ENV_PICKED] == "1"
    assert "CLAUDECODE" not in env


def test_plain_worktree_launch_has_no_ticket(monkeypatch):
    calls = []
    monkeypatch.setattr(wp.subprocess, "Popen",
                        lambda cmd, cwd, env: calls.append(env))
    wp._launch("/wt/item-9")
    assert "PAD_TICKET" not in calls[0]


def test_unreadable_triage_db_shows_every_ticket_tree(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path, "pinball-asset-decryptor")
    triage = tmp_path / "pad-triage"
    (triage / "work" / "repo").mkdir(parents=True)
    tree = _make_checkout(triage / "work" / "tickets", "PAD-5")
    monkeypatch.setenv(wp.ENV_TRIAGE_DIR, str(triage))
    monkeypatch.setattr(wp, "_git", lambda args, cwd, timeout=10:
                        _porcelain([(tree, "ticket/PAD-5")]))
    assert wp.discover_ticket_checkouts(root) == \
        [(os.path.normpath(tree), "ticket/PAD-5")]
    assert wp._describe(tree, "ticket/PAD-5").startswith("PAD-5")


def test_no_pad_triage_no_ticket_trees(tmp_path):
    root = _make_checkout(tmp_path, "pinball-asset-decryptor")
    assert wp.discover_ticket_checkouts(root) == []


def test_broken_ticket_discovery_never_bricks(monkeypatch):
    monkeypatch.setattr(wp, "_git", lambda args, cwd, timeout=10: None)
    monkeypatch.setattr(wp, "discover_ticket_checkouts",
                        lambda root: 1 / 0)
    assert wp.discover_other_checkouts("C:/anywhere") == []
