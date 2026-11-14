"""A team folder kept in step by Git (PAD-1236, "Git or Git LFS could be a useful setup").

A team folder that is inside a Git working copy (a clone of a repository the
team shares on GitHub, GitLab, a NAS, ...) needs no sync service: the app
carries it itself.  :func:`sync` commits the member's own subfolder, pulls the
others' commits and pushes, so each member's work arrives as one commit of
their folder.  Members only ever write their own subfolder, so a pull never
conflicts.  With Git LFS installed, the member's media go through LFS
(:data:`LFS_PATTERNS`, written to ``<team>/<me>/.gitattributes``), so the
repository holds pointers and the videos live in LFS storage.

Every call is quiet about a team folder that is not in Git (``None``), and a
failure (no network, no rights to push) comes back as words for the log: the
folder on this PC is still whole, and the next :func:`sync` tries again.
"""

import os
import shutil
import subprocess
import sys
import threading

ATTRIBUTES = ".gitattributes"

# what goes through LFS: the media and the packed edits, never the small records
LFS_PATTERNS = ("*.mp4", "*.webm", "*.mov", "*.avi", "*.mkv", "*.m4v", "*.wav", "*.ogg",
                "*.mp3", "*.flac", "*.opus", "*.m4a", "*.png", "*.jpg", "*.jpeg", "*.webp",
                "*.gif", "*.bmp", "*.tga", "*.dds", "*.zip", "*.ttf", "*.otf", "*.bin",
                "*.radium", "*.so")

TIMEOUT = 600

# one Git job at a time in this app: a Share or a Get holds it from its first file to its
# push, so the regular check never commits a share half written (and two git commands never
# meet in one working copy)
LOCK = threading.RLock()
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def git_exe():
    return shutil.which("git")


def _run(args, cwd, timeout=TIMEOUT):
    """``(returncode, output)``; 127 when Git is not there."""
    exe = git_exe()
    if not exe:
        return 127, "Git is not installed on this PC."
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="", GCM_INTERACTIVE="never")
    try:
        p = subprocess.run([exe] + list(args), cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return 124, "git %s took too long." % args[0]
    except OSError as e:
        return 126, str(e)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def repo_root(team):
    """The working copy *team* is in, or ``None`` (not in Git, or no Git here)."""
    d = os.path.abspath(team or "")
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            break
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up
    if not git_exe():
        return None
    rc, out = _run(["rev-parse", "--show-toplevel"], team, timeout=30)
    return os.path.normpath(out.splitlines()[-1]) if rc == 0 and out else None


def has_lfs(root):
    return _run(["lfs", "version"], root, timeout=30)[0] == 0


def uses_lfs(root):
    """Does any ``.gitattributes`` in the working copy send files through LFS?"""
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        if ATTRIBUTES in files:
            try:
                with open(os.path.join(d, ATTRIBUTES), encoding="utf-8") as f:
                    if "filter=lfs" in f.read():
                        return True
            except OSError:
                pass
        if d.count(os.sep) - root.count(os.sep) >= 1:
            dirs[:] = []                    # members' folders are one level down
    return False


def _remote(root):
    rc, out = _run(["remote"], root, timeout=30)
    return out.splitlines()[0].strip() if rc == 0 and out.strip() else ""


def _branch(root):
    rc, out = _run(["symbolic-ref", "--short", "HEAD"], root, timeout=30)
    return out.strip() if rc == 0 else ""


def _upstream(root):
    return _run(["rev-parse", "--abbrev-ref", "@{u}"], root, timeout=30)[0] == 0


def write_lfs_attributes(member_dir):
    """Send the member's media through LFS (their own ``.gitattributes``)."""
    os.makedirs(member_dir, exist_ok=True)
    want = "".join("%s filter=lfs diff=lfs merge=lfs -text\n" % p for p in LFS_PATTERNS)
    path = os.path.join(member_dir, ATTRIBUTES)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == want:
                return
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(want)


def status(team):
    """What the Team window says about Git: ``None`` (not in Git) or ``{"root", "remote",
    "lfs", "warnings"}``."""
    root = repo_root(team)
    if root is None:
        return None
    out = {"root": root, "remote": _remote(root), "lfs": has_lfs(root), "warnings": []}
    if not out["remote"]:
        out["warnings"].append("The team folder is in Git, but its repository has no remote "
                               "to push to, so the others won't get your shares. Clone the "
                               "team's repository instead, or add its remote.")
    if not out["lfs"] and uses_lfs(root):
        out["warnings"].append("This team keeps its videos and sounds in Git LFS, which is "
                               "not installed on this PC: install Git LFS, or the others' "
                               "files never arrive.")
    return out


def sync(team, me, message=""):
    """Commit *me*'s folder, pull the others' commits, push.  ``None`` when *team* is not
    in Git, else ``{"ok", "pulled", "pushed", "committed", "lines"}`` (*lines*: what went
    wrong, for the log)."""
    root = repo_root(team)
    if root is None:
        return None
    with LOCK:
        return _sync(root, team, me, message)


def _sync(root, team, me, message):
    res = {"ok": True, "pulled": False, "pushed": False, "committed": False, "lines": []}
    mine = os.path.join(team, me)
    lfs = has_lfs(root)
    if lfs and os.path.isdir(mine):
        if _run(["config", "--get", "filter.lfs.clean"], root, timeout=30)[0] != 0:
            _run(["lfs", "install", "--local"], root, timeout=60)
        write_lfs_attributes(mine)
    # a PC that never told Git who it is: the member's name (commits and rebases need one)
    ident = []
    if _run(["config", "user.name"], root, timeout=30)[0] != 0:
        ident += ["-c", "user.name=%s" % me]
    if _run(["config", "user.email"], root, timeout=30)[0] != 0:
        ident += ["-c", "user.email=%s@pad-team.invalid" % me.replace(" ", ".")]
    if os.path.isdir(mine):
        rel = os.path.relpath(mine, root)
        _run(["add", "-A", "--", rel], root)
        rc, _out = _run(["diff", "--cached", "--quiet", "--", rel], root, timeout=60)
        if rc == 1:
            rc, out = _run(ident + ["commit", "-q", "-m", message or ("%s's parts" % me),
                                    "--", rel], root)
            if rc == 0:
                res["committed"] = True
            else:
                res["ok"] = False
                res["lines"].append("Git couldn't commit your share: %s" % out)
                return res
    remote = _remote(root)
    if not remote:
        return res
    branch = _branch(root)
    pull = ident + ["pull", "-q", "--rebase", "--autostash"]
    if not _upstream(root):
        if not branch:
            res["ok"] = False
            res["lines"].append("The team's Git working copy is not on a branch.")
            return res
        pull += [remote, branch]
    for attempt in range(2):
        rc, out = _run(pull, root)
        if rc != 0:
            if "couldn't find remote ref" in out.lower() or "no such ref" in out.lower():
                pass                         # a new, empty repository: nothing to pull
            else:
                _run(["rebase", "--abort"], root, timeout=60)
                res["ok"] = False
                res["lines"].append("Git couldn't get the team's changes: %s" % out)
                return res
        else:
            res["pulled"] = True
        rc, out = _run(["status", "-sb", "--porcelain"], root, timeout=60)
        head = out.splitlines()[0] if rc == 0 and out else ""
        if _upstream(root) and "ahead" not in head:
            return res
        push = ["push", "-q"] + ([] if _upstream(root) else ["-u", remote, branch])
        rc, out = _run(push, root)
        if rc == 0:
            res["pushed"] = True
            return res
        if attempt == 0 and ("rejected" in out or "fetch first" in out
                             or "non-fast-forward" in out):
            continue                         # someone pushed in between: pull again
        res["ok"] = False
        res["lines"].append("Git couldn't send your share to the team: %s" % out)
        return res
    return res
