"""Worktree chooser logic — parsing, discovery filters, and the no-op
guarantees that keep it invisible outside a dev tree with worktrees."""

import os

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
