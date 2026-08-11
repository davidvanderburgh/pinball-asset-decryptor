"""Dev-only checkout chooser: pick which git worktree the GUI runs from.

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

The chooser must never be able to brick a launch: any git failure, parse
failure, or Tk failure falls through to "just run this checkout".
"""

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


def _ask(root, others):
    """Tk chooser.  Returns the chosen checkout path, or None for cancel."""
    import tkinter as tk

    rows = chooser_rows(root, others)

    win = tk.Tk()
    win.title("Pinball Asset Decryptor — dev")
    win.resizable(False, False)
    win.attributes("-topmost", True)

    tk.Label(win, text="Item worktrees exist. Run the app from which checkout?",
             anchor="w", padx=12, pady=8).pack(fill="x")
    lb = tk.Listbox(win, height=len(rows), activestyle="dotbox",
                    width=max(28, max(len(t) for _, t in rows) + 2))
    for _, text in rows:
        lb.insert("end", text)
    # Top row = most recently touched: selected, active (the dotbox that
    # arrow keys move from), and in view, so Enter launches it.
    lb.selection_set(0)
    lb.activate(0)
    lb.see(0)
    lb.pack(fill="both", expand=True, padx=12)

    chosen = []

    def go(_event=None):
        sel = lb.curselection()
        if sel:
            chosen.append(rows[sel[0]][0])
            win.destroy()

    def cancel(_event=None):
        win.destroy()

    btns = tk.Frame(win, padx=12, pady=10)
    btns.pack(fill="x")
    tk.Button(btns, text="Launch", width=10, default="active",
              command=go).pack(side="right")
    tk.Button(btns, text="Cancel", width=10,
              command=cancel).pack(side="right", padx=(0, 8))

    lb.bind("<Double-Button-1>", go)
    win.bind("<Return>", go)
    win.bind("<Escape>", cancel)
    win.protocol("WM_DELETE_WINDOW", cancel)

    win.update_idletasks()
    x = (win.winfo_screenwidth() - win.winfo_reqwidth()) // 2
    y = (win.winfo_screenheight() - win.winfo_reqheight()) // 3
    win.geometry("+%d+%d" % (x, y))
    lb.focus_set()
    win.mainloop()
    return chosen[0] if chosen else None


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
    except Exception:
        return True  # a broken chooser must never block the app
    if choice is None:
        return False
    if os.path.normcase(os.path.normpath(choice)) == \
            os.path.normcase(os.path.normpath(root)):
        return True
    _launch(choice)
    return False
