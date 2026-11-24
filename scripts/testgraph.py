"""Which test files can reach a source file - a static import graph.

PAD-1536: testpick ran the FULL suite for any change under core/ (37 of
the 54 full runs in the last 220 commits, 25 of them for that alone), for
app.py, and for every file without a zone (tools/spike3_emu/ sent PAD-1533
full).  Two tickets running full suites at once filled David's CPU.

This answers the narrower question "which tests could run this file" from
the source alone, and errs WIDE on purpose:

  * every import counts, at any depth - module level, inside functions,
    inside try blocks - and importing a.b.c counts a and a.b too;
  * a string that names a module counts as an import ("pinball_decryptor.
    plugins.jjp" in the plugin registry's list, tab names beside the tabs
    package, `-m pinball_decryptor.mcp`), and a package named that way
    counts its __main__;
  * a string naming a .py file (subprocess runs, spec_from_file_location)
    counts every file of that name, and so does one naming any other
    tracked file ("build_linux.sh", "pinball_decryptor.iss"); a string naming a tools/ rig folder
    ("spike3_emu") counts every file in it;
  * a test helper module in tests/ (webui_harness, synthetic...) is
    see-through: going through one costs no hop.

The closure is NOT followed all the way: this repo is so cross-linked by
imports inside functions (core -> the Stern engine -> the web tabs -> the
app) that 1019 of 1065 test files reach every core file, a rig script
and app.py alike - transitive reach is just the full suite again.
testpick takes the tests within DEPTH (2) imports: the tests of the file
and the tests of the modules that use it.  Measured on all 117 core
files: a median of 60 test files (mean 120), never none; at depth 3 it
is ~400.  The release gate still runs everything.

testpick still runs EVERYTHING when a conftest.py imports the file
itself (its fixtures run for every test), when no test reaches a core/
file at all (a reach this graph cannot see is likelier than none), or
when most of the suite is reached anyway.  Edges are cached per file by
size + mtime, so a second run takes well under a second.
"""

import ast
import collections
import json
import os
import subprocess
import tempfile
import warnings
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_VERSION = 1
DEPTH = 2          # imports from a test to the changed file (see above)


def repo_files(repo=REPO):
    out = subprocess.check_output(
        ["git", "-C", repo, "ls-files", "--cached", "--others",
         "--exclude-standard", "--", "*.py", "*.pyw"], text=True)
    return sorted({p.strip() for p in out.splitlines()
                   if p.strip() and os.path.isfile(os.path.join(repo, p))})


def tracked_files(repo=REPO):
    out = subprocess.check_output(
        ["git", "-C", repo, "ls-files", "--cached", "--others",
         "--exclude-standard"], text=True)
    return sorted({p.strip() for p in out.splitlines() if p.strip()})


def module_names(path, repo=REPO):
    """Dotted names *path* can be imported as."""
    parts = path[:-4 if path.endswith(".pyw") else -3].split("/")
    is_pkg = parts[-1] == "__init__"
    if is_pkg:
        parts = parts[:-1]
    # climb while the folder is a package: the name starts at the first
    # folder that is NOT one (the repo root for pinball_decryptor/ + tests/)
    start = len(parts) - (0 if is_pkg else 1)
    while start > 0 and os.path.isfile(
            os.path.join(repo, *parts[:start], "__init__.py")):
        start -= 1
    if is_pkg:
        start = max(start, 0)
    names = set()
    if parts[start:]:
        names.add(".".join(parts[start:]))
    names.add(".".join(parts))                 # from the repo root
    if not is_pkg and not path.startswith("pinball_decryptor/"):
        names.add(parts[-1])                   # sys.path.insert(dir) + import
    return {n for n in names if n}


def _package_of(path, names):
    """The dotted package a file's relative imports resolve against."""
    best = max(names, key=lambda n: n.count("."))
    if path.endswith("__init__.py"):
        return best
    return best.rpartition(".")[0]


def file_refs(path, repo=REPO):
    """-> {'imports': [dotted], 'rel': [(level, module, [names])],
           'strings': [str]}  or None when it does not parse."""
    try:
        with open(os.path.join(repo, path), "rb") as f:
            src = f.read()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")    # old files' bad escapes
            tree = ast.parse(src, filename=path)
    except (SyntaxError, ValueError, OSError):
        return None
    imports, rel, strings = [], [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            rel.append((node.level or 0, node.module or "",
                        [a.name for a in node.names]))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value.strip()
            if 0 < len(s) < 200 and not any(c.isspace() for c in s):
                strings.add(s)
    return {"imports": imports, "rel": rel, "strings": sorted(strings)}


def _load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("v") == CACHE_VERSION:
            return data["files"]
    except (OSError, ValueError, KeyError):
        pass
    return {}


class Graph:
    def __init__(self, repo=REPO, cache=True):
        self.repo = repo
        self.files = repo_files(repo)
        self.names = {}                        # file -> names
        self.by_name = {}                      # name -> {files}
        self.by_base = {}                      # basename -> {files}
        self.by_dir = {}                       # folder -> {files}
        self.by_stem = {}                      # (folder, stem) -> file
        for p in self.files:
            ns = module_names(p, repo)
            self.names[p] = ns
            for n in ns:
                self.by_name.setdefault(n, set()).add(p)
            self.by_base.setdefault(os.path.basename(p), set()).add(p)
            self.by_dir.setdefault(os.path.dirname(p), set()).add(p)
            if p.endswith(".py"):
                self.by_stem[(os.path.dirname(p),
                              os.path.basename(p)[:-3])] = p
        # any other tracked file a string can name ("build_linux.sh",
        # "pinball_decryptor.iss"): a node with no edges of its own
        self.data_by_base = {}
        pyset = set(self.files)
        for p in tracked_files(repo):
            if p not in pyset and "." in os.path.basename(p):
                self.data_by_base.setdefault(os.path.basename(p),
                                             set()).add(p)
        self.rig_dirs = {}                     # "spike3_emu" -> {files}
        for d, fs in self.by_dir.items():
            bits = d.split("/")
            if len(bits) >= 2 and bits[0] == "tools":
                self.rig_dirs.setdefault(bits[1], set()).update(fs)
        cpath = os.path.join(tempfile.gettempdir(),
                             "pad-testgraph-%08x.json"
                             % zlib.crc32(os.path.abspath(repo).encode()))
        old = _load_cache(cpath) if cache else {}
        fresh, self.unparsed = {}, set()
        self.edges = {}
        for p in self.files:
            st = os.stat(os.path.join(repo, p))
            key = "%d:%d" % (st.st_size, st.st_mtime_ns)
            ent = old.get(p)
            refs = ent["refs"] if ent and ent.get("key") == key else \
                file_refs(p, repo)
            fresh[p] = {"key": key, "refs": refs}
            if refs is None:
                self.unparsed.add(p)
                self.edges[p] = set()
            else:
                self.edges[p] = self._resolve(p, refs)
        if cache:
            try:
                tmp = cpath + ".%d.tmp" % os.getpid()
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"v": CACHE_VERSION, "files": fresh}, f)
                os.replace(tmp, cpath)
            except OSError:
                pass
        self.rev = {}
        for p, outs in self.edges.items():
            for q in outs:
                self.rev.setdefault(q, set()).add(p)

    def _mod(self, dotted, out, with_main=False):
        bits = dotted.split(".")
        for i in range(1, len(bits) + 1):
            out.update(self.by_name.get(".".join(bits[:i]), ()))
        if with_main:
            out.update(self.by_name.get(dotted + ".__main__", ()))

    def _resolve(self, p, refs):
        out = set()
        for m in refs["imports"]:
            self._mod(m, out)
        pkg = _package_of(p, self.names[p])
        for level, mod, names in refs["rel"]:
            if level:
                base = pkg.split(".") if pkg else []
                base = base[:len(base) - (level - 1)] if level > 1 else base
                full = ".".join([b for b in base if b] + ([mod] if mod else []))
            else:
                full = mod
            if full:
                self._mod(full, out)
            for n in names:
                if n != "*":
                    self._mod((full + "." + n) if full else n, out)
        here = os.path.dirname(p)
        for s in refs["strings"]:
            base = s.replace("\\", "/").rsplit("/", 1)[-1]
            if base in self.data_by_base:
                out.update(self.data_by_base[base])
            if s.endswith((".py", ".pyw")):
                out.update(self.by_base.get(base, ()))
            elif "." in s and s in self.by_name:
                self._mod(s, out, with_main=True)
            elif s in self.rig_dirs:
                out.update(self.rig_dirs[s])
            elif s.isidentifier():
                # a bare name only counts beside the file (a package's own
                # list of its modules: the tabs loader, sam_audio's parts)
                q = self.by_stem.get((here, s))
                if q:
                    out.add(q)
                init = (here + "/" if here else "") + s + "/__init__.py"
                if init in self.names:
                    out.add(init)
        out.discard(p)
        return out

    def reachers(self, target, depth=None):
        """Files whose imports reach *target* within *depth* hops (None: any
        depth).  A test helper module (tests/ but not test_*) costs no hop:
        a test that drives the app through webui_harness is as close as one
        importing the module itself."""
        best = {target: 0}
        todo = collections.deque([target])
        while todo:
            q = todo.popleft()
            for r in self.rev.get(q, ()):
                free = r.startswith("tests/") and not os.path.basename(
                    r).startswith("test_")
                d = best[q] + (0 if free else 1)
                if depth is not None and d > depth:
                    continue
                if d < best.get(r, 1 << 30):
                    best[r] = d
                    (todo.appendleft if free else todo.append)(r)
        best.pop(target)
        return set(best)

    def test_files(self):
        return [p for p in self.files if p.startswith("tests/")
                and os.path.basename(p).startswith("test_")
                and p.endswith(".py")]

    def known(self, path):
        return path in self.names or any(
            path in fs for fs in self.data_by_base.values())

    def tests_reaching(self, target, depth=None):
        """-> (tests, conftest_direct): the test files that reach *target*
        (within *depth* imports), and whether a conftest.py imports it
        outright."""
        reach = self.reachers(target, depth) | {target}
        tests = {p for p in reach if p.startswith("tests/")
                 and os.path.basename(p).startswith("test_")}
        conf = any(target in self.edges.get(c, ())
                   for c in self.files if os.path.basename(c) == "conftest.py")
        return tests, conf
