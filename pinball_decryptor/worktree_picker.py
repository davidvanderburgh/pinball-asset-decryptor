"""Dev-only checkout chooser: pick which git worktree the app runs from.

The desktop icon always points at the MAIN checkout, but /next item work
happens in sibling worktrees (../pinball-asset-decryptor-wt/item-<N>), and
testing an item means running THAT checkout's code.  So when other
worktrees exist at launch, a small chooser appears first; picking one
relaunches this same interpreter with the worktree as cwd (`-m` puts cwd
on sys.path, so the worktree's package is the one imported).  With no
worktrees — every installed copy, and a dev tree with nothing in
progress — the chooser never appears and startup is unchanged.

Rows are ordered most-recently-touched first (main included) and the top
row is pre-selected, so the usual launch — Enter on the checkout you were
just working in — needs no aiming.

The chooser is a small pywebview window run in a child process
(:func:`_ask`); without pywebview it is skipped and this checkout starts.

The chooser must never be able to brick a launch: any git failure, parse
failure, or window failure falls through to "just run this checkout".
"""

import html
import json
import os
import re
import subprocess
import sys

# Set in the child's environment when a worktree is picked, so the child
# (whose checkout ALSO sees every worktree — `git worktree list` output is
# shared) doesn't ask again.
ENV_PICKED = "PAD_WORKTREE_PICKED"

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# `git status` is the slowest thing the chooser does on a big checkout,
# and both the recency sort and the row label want it, so each checkout
# is asked once per launch.
_STATUS_CACHE = {}
_COMMIT_CACHE = {}

# Dirty files are stat'd for their mtime; a checkout mid-rebuild can have
# thousands, and the newest is nearly always in the first handful.
_DIRTY_STAT_LIMIT = 200


def _git(args, cwd, timeout=10):
    """stdout of `git <args>` run quietly in cwd, or None on any failure."""
    try:
        proc = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def parse_worktree_list(porcelain):
    """`git worktree list --porcelain` -> [(path, branch_or_None)].

    Blocks are blank-line separated; a detached worktree has no branch
    line and a bare entry has no path we care about.
    """
    entries = []
    path = branch = None
    for line in porcelain.splitlines() + [""]:
        if line.startswith("worktree "):
            path, branch = line[len("worktree "):], None
        elif line.startswith("branch refs/heads/"):
            branch = line[len("branch refs/heads/"):]
        elif not line.strip():
            if path:
                entries.append((path, branch))
            path = branch = None
    return entries


def _status(path):
    """`git status --porcelain` for a checkout ("" if git can't answer)."""
    if path not in _STATUS_CACHE:
        _STATUS_CACHE[path] = _git(["status", "--porcelain"], cwd=path) or ""
    return _STATUS_CACHE[path]


def _last_commit(path):
    """(commit epoch seconds, subject) of HEAD — (0.0, None) if unknown."""
    if path not in _COMMIT_CACHE:
        out = _git(["log", "-1", "--format=%ct%n%s"], cwd=path) or ""
        stamp, _, subject = out.partition("\n")
        stamp = stamp.strip()
        _COMMIT_CACHE[path] = (float(stamp) if stamp.isdigit() else 0.0,
                               subject.strip() or None)
    return _COMMIT_CACHE[path]


def dirty_paths(status):
    """Repo-relative paths named by `git status --porcelain` output.

    Lines are `XY <path>`; a rename reads `old -> new` (the new name is
    the one on disk) and a path with odd characters comes back quoted.
    """
    paths = []
    for line in status.splitlines():
        rel = line[3:].strip()
        if " -> " in rel:
            rel = rel.split(" -> ")[-1]
        rel = rel.strip('"')
        if rel:
            paths.append(rel)
    return paths


def touched_at(path):
    """When a checkout was last worked in, as epoch seconds (0.0 = never).

    HEAD's commit time is the floor, but a worktree with edits in it was
    touched more recently than its last commit — and that is exactly the
    one to offer first — so the dirty files git just listed are stat'd
    too.
    """
    stamps = [_last_commit(path)[0]]
    for rel in dirty_paths(_status(path))[:_DIRTY_STAT_LIMIT]:
        try:
            stamps.append(os.path.getmtime(os.path.join(path, rel)))
        except OSError:
            pass  # deleted, or a quoted path we didn't unescape
    return max(stamps)


def _sort_key(entry):
    """item/<N> worktrees first in numeric order, then everything else.

    Item numbers aren't purely numeric (1b, 1d are real items), so the
    numeric part ranks and the suffix breaks ties.  This only settles
    checkouts that look equally recent (a fresh `git worktree add` before
    any work lands in it) — recency comes first.
    """
    _path, branch = entry
    m = re.fullmatch(r"item/(\d+)([a-z]?)", branch or "")
    if m:
        return (0, int(m.group(1)), m.group(2))
    return (1, 0, branch or _path)


def _recency_key(entry):
    """Most recently touched first, item order as the tiebreak."""
    return (-touched_at(entry[0]),) + _sort_key(entry)


def discover_other_checkouts(root):
    """Worktrees of root's repo that are runnable copies of the app.

    Excludes root itself, session-internal worktrees under a `.claude`
    directory, and any worktree missing the package entry point.
    """
    out = _git(["worktree", "list", "--porcelain"], cwd=root)
    if not out:
        return []
    root_key = os.path.normcase(os.path.normpath(root))
    found = []
    for path, branch in parse_worktree_list(out):
        p = os.path.normpath(path)
        if os.path.normcase(p) == root_key:
            continue
        if (os.sep + ".claude" + os.sep) in p:
            continue
        if not os.path.isfile(
                os.path.join(p, "pinball_decryptor", "__main__.py")):
            continue
        found.append((p, branch))
    return sorted(found, key=_recency_key)


def item_title(todo_text, branch):
    """The queue item's title for an item/<N> branch, from plans/TODO.md.

    Queue lines look like `- [ ] **33. Save-state slots need visibility.**
    `S2 D3`` — the number is the anchor, the bold run is the title.  Long
    titles WRAP across hard-wrapped lines (most real items do), so the
    match must cross newlines and the result is whitespace-collapsed."""
    m = re.fullmatch(r"item/(\w+)", branch or "")
    if not m:
        return None
    hit = re.search(
        r"\*\*" + re.escape(m.group(1)) + r"\.\s*(.+?)\*\*", todo_text, re.S)
    if not hit:
        return None
    return " ".join(hit.group(1).split()).rstrip(".")


def _shorten(text, limit=64):
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _describe(path, branch):
    """One chooser row: branch, item title if findable, dirty marker."""
    label = branch or os.path.basename(path)
    title = None
    try:
        with open(os.path.join(path, "plans", "TODO.md"),
                  encoding="utf-8", errors="replace") as fh:
            title = item_title(fh.read(), branch)
    except OSError:
        pass
    if not title:
        # Never leave a bare branch number — the last commit subject is
        # the next best reminder of what the worktree is about.
        title = _last_commit(path)[1]
    if title:
        label += "  —  " + _shorten(title)
    if _status(path).strip():
        label += "   ● uncommitted"
    return label


def chooser_rows(root, others):
    """[(path, label)] for the chooser, most recently touched first.

    `others` already arrives recency-ordered from discovery, so only the
    root row needs placing among them; sorting is stable, so checkouts
    that look equally recent keep that order.
    """
    branch = (_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
              or "main").strip()
    rows = [(root, branch + "  —  this checkout")]
    rows += [(p, _describe(p, b)) for p, b in others]
    return sorted(rows, key=lambda row: -touched_at(row[0]))


def checkout_badge(root=None):
    """`item/27 — <queue title>` for the checkout this package runs from.

    None on main/master, detached HEAD, or anywhere git can't answer
    (every installed copy) — the places where a marker would be noise.
    The App shows it in the title bar so a window running a picked
    worktree is identifiable at a glance next to a main-checkout window.
    """
    if root is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    branch = branch.strip() if branch else ""
    if not branch or branch in ("main", "master", "HEAD"):
        return None
    title = None
    try:
        with open(os.path.join(root, "plans", "TODO.md"),
                  encoding="utf-8", errors="replace") as fh:
            title = item_title(fh.read(), branch)
    except OSError:
        pass
    if title:
        return branch + " — " + _shorten(title, 48)
    return branch


def _launch(path):
    """Start the chosen checkout's app with this same interpreter."""
    env = dict(os.environ)
    env[ENV_PICKED] = "1"
    subprocess.Popen([sys.executable, "-m", "pinball_decryptor"],
                     cwd=path, env=env)


#: The chooser window's title and question.
_CHOOSER_TITLE = "Pinball Asset Decryptor — dev"
_CHOOSER_QUESTION = "Item worktrees exist. Run the app from which checkout?"


def _has_webview(python):
    """True when *python* can import pywebview (the chooser's window)."""
    try:
        proc = subprocess.run(
            [python, "-c", "import webview"], capture_output=True,
            timeout=30, creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _chooser_python(root):
    """An interpreter that can show the chooser: this one when it has
    pywebview, else the checkout's own .venv's (the desktop icon may start
    an interpreter without it).  None when neither has it."""
    try:
        import importlib.util
        if importlib.util.find_spec("webview") is not None:
            return sys.executable
    except (ImportError, ValueError):
        pass
    venv = os.path.join(root, ".venv")
    for exe in (os.path.join(venv, "Scripts", "python.exe"),
                os.path.join(venv, "bin", "python")):
        if os.path.isfile(exe) and _has_webview(exe):
            return exe
    return None


def _ask(root, others):
    """Show the chooser.  Returns the chosen checkout path, or None for
    cancel.

    The window (a small pywebview page, :func:`_choose_main`) runs in a
    child process, so this process never starts a GUI loop of its own and
    the app it goes on to start is untouched by it.  Without pywebview
    this checkout is started, and stderr says why."""
    rows = chooser_rows(root, others)
    python = _chooser_python(root)
    if python is None:
        print("worktree chooser: pywebview is not installed, so there is no "
              "window to choose in; starting this checkout (%s)." % root,
              file=sys.stderr)
        return root
    proc = subprocess.run(
        [python, os.path.abspath(__file__), "--choose"],
        input=json.dumps({"labels": [text for _, text in rows]}).encode(
            "utf-8"),
        capture_output=True, creationflags=_CREATE_NO_WINDOW)
    out = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    if proc.returncode != 0 or not out:
        raise RuntimeError("the chooser exited with %s: %s" % (
            proc.returncode,
            proc.stderr.decode("utf-8", "replace").strip()[-400:]))
    choice = json.loads(out[-1]).get("choice")
    if choice is None:
        return None
    return rows[int(choice)][0]


def chooser_html(labels):
    """The chooser page: the rows, most recently touched first, the top one
    selected so Enter launches it; arrows move, a double click launches,
    Esc cancels."""
    items = "\n".join(
        '<div class="row" tabindex="-1">%s</div>' % html.escape(text)
        for text in labels)
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>%(title)s</title>
<style>
:root { color-scheme: light dark; --bg: #f4f5f7; --fg: #1d2127;
        --line: #c9ced6; --sel: #2f6fd6; --self: #ffffff; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #1b1e23; --fg: #e6e8eb; --line: #3a3f47; --sel: #3b7de6;
          --self: #23272d; } }
body { margin: 0; padding: 12px; background: var(--bg); color: var(--fg);
       font: 13px "Segoe UI", system-ui, sans-serif; user-select: none; }
p { margin: 0 0 8px; }
#rows { border: 1px solid var(--line); background: var(--self);
        max-height: calc(100vh - 100px); overflow-y: auto; }
.row { padding: 5px 8px; white-space: nowrap; cursor: default;
       overflow: hidden; text-overflow: ellipsis; outline: none; }
.row.sel { background: var(--sel); color: #fff; }
.buttons { display: flex; justify-content: flex-end; gap: 8px;
           margin-top: 10px; }
button { min-width: 84px; padding: 4px 10px; font: inherit; }
</style></head>
<body>
<p>%(question)s</p>
<div id="rows">
%(items)s
</div>
<div class="buttons">
<button id="cancel">Cancel</button>
<button id="launch" autofocus>Launch</button>
</div>
<script>
var rows = Array.prototype.slice.call(document.querySelectorAll(".row"));
var sel = 0;
function show() {
  rows.forEach(function (r, i) { r.classList.toggle("sel", i === sel); });
  rows[sel].scrollIntoView({block: "nearest"});
}
function api() { return window.pywebview && window.pywebview.api; }
function go() { if (api()) { api().pick(sel); } }
function cancel() { if (api()) { api().cancel(); } }
rows.forEach(function (r, i) {
  r.addEventListener("click", function () { sel = i; show(); });
  r.addEventListener("dblclick", function () { sel = i; show(); go(); });
});
document.getElementById("launch").addEventListener("click", go);
document.getElementById("cancel").addEventListener("click", cancel);
document.addEventListener("keydown", function (e) {
  if (e.key === "ArrowDown") { sel = Math.min(rows.length - 1, sel + 1); }
  else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); }
  else if (e.key === "Home") { sel = 0; }
  else if (e.key === "End") { sel = rows.length - 1; }
  else if (e.key === "Enter") { e.preventDefault(); go(); return; }
  else if (e.key === "Escape") { e.preventDefault(); cancel(); return; }
  else { return; }
  e.preventDefault();
  show();
});
show();
</script>
</body></html>
""" % {"title": html.escape(_CHOOSER_TITLE),
       "question": html.escape(_CHOOSER_QUESTION), "items": items}


def _choose_main():
    """The chooser window, in the child process ``_ask`` starts: the row
    labels arrive as JSON on stdin, the answer leaves as one JSON line on
    stdout (``{"choice": <row index or null>}``)."""
    labels = json.loads(sys.stdin.buffer.read().decode("utf-8"))["labels"]
    import webview

    chosen = []
    holder = []

    class _Api:
        def pick(self, index):
            chosen[:] = [int(index)]
            holder[0].destroy()

        def cancel(self):
            holder[0].destroy()

    longest = max([len(text) for text in labels] + [len(_CHOOSER_QUESTION)])
    width = max(440, min(1100, 7 * longest + 60))
    height = max(200, min(720, 118 + 27 * len(labels)))
    holder.append(webview.create_window(
        _CHOOSER_TITLE, html=chooser_html(labels), js_api=_Api(),
        width=width, height=height, resizable=False, on_top=True))
    webview.start()
    sys.stdout.write(json.dumps(
        {"choice": chosen[0] if chosen else None}) + "\n")
    sys.stdout.flush()
    return 0


def dev_pick_checkout():
    """Entry-point hook.  True = continue into the app in THIS checkout;
    False = the caller should exit (a worktree's app was launched instead,
    or the chooser was cancelled)."""
    if os.environ.get(ENV_PICKED):
        return True
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    others = discover_other_checkouts(root)
    if not others:
        return True
    try:
        choice = _ask(root, others)
    except Exception as e:
        # a broken chooser must never block the app
        print("worktree chooser failed (%s); starting this checkout." % e,
              file=sys.stderr)
        return True
    if choice is None:
        return False
    if os.path.normcase(os.path.normpath(choice)) == \
            os.path.normcase(os.path.normpath(root)):
        return True
    _launch(choice)
    return False


if __name__ == "__main__" and sys.argv[1:] == ["--choose"]:
    sys.exit(_choose_main())
