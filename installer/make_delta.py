#!/usr/bin/env python3
"""Build a Windows release's delta-update assets (PAD-1519).

David: "Can we do automatic delta updates?  so instead of replacing all the
files, we just do the new ones?"  Every in-app update downloaded the whole
setup exe (157 MB) and unpacked all of it (710 MB, 8,300 files) into the
blue-green sibling folder: 35-56 s of installing on his PC for a release
that changed a dozen source files.

So each Windows release also publishes, beside the setup exe:

``<installer>.delta.json.gz``  the MANIFEST
    Every file the setup exe installs: its path, size and SHA-256, and where
    its bytes can be fetched - which release's pack, at what offset.
``<installer>.delta.pack``  the PACK
    The files of this release that no earlier release's pack holds, each
    compressed on its own and laid end to end, so the app can fetch any one
    of them with an HTTP range request.

The app (``pinball_decryptor/core/update_delta.py``) builds the new version
from the files already installed and fetches only the ones whose hash
differs.  The pack holds only what is NEW since the previous release - a
release's own pack is a few hundred KB, not another 300 MB upload on the
release's critical path - and the manifest points at the earlier packs for
everything else.  A pack that is no longer downloadable (its release was
yanked) is noticed here, and its files go into this release's pack again.

THE FILE LIST IS THE INSTALLER'S OWN.  ``iss_files`` reads the ``[Files]``
section of pinball_decryptor.iss and applies Inno Setup's rules for
``Source`` wildcards, ``recursesubdirs`` and ``Excludes``, so the manifest
cannot drift from the setup exe by somebody forgetting a second list.  A
flag or parameter this reader does not know stops it (no delta assets for
that build; the setup exe is unaffected) rather than guessing, and the
release workflow installs the real setup exe afterwards and compares
(``--verify``), deleting the delta assets if they disagree.

``.pyc`` files beside their source are left out: pip compiles them at build
time with the build's timestamps inside, so they differ on every build.  The
app keeps the ones it has for unchanged sources and compiles the rest.

Usage:
  make_delta.py --version 1.575.0 --python-dir build/python [--previous
      prev.delta.json.gz] [--repo owner/name] [--out installer/Output]
  make_delta.py --verify <installed folder> --manifest <x.delta.json.gz>
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import stat
import sys
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor

FORMAT = 1
MANIFEST_SUFFIX = ".delta.json.gz"
PACK_SUFFIX = ".delta.pack"
STORED, DEFLATED = 0, 1

_HERE = os.path.dirname(os.path.abspath(__file__))
ISS = os.path.join(_HERE, "pinball_decryptor.iss")

#: [Files] parameters and flags whose meaning this reader implements (or
#: that do not change which file lands where).  Anything else is refused.
_KNOWN_PARAMS = {"source", "destdir", "flags", "excludes", "afterinstall",
                 "check"}
_KNOWN_FLAGS = {"recursesubdirs", "ignoreversion", "onlyifdoesntexist"}
#: the only Check functions modelled (PAD-1606): KeptAsInstalled skips a
#: file only when the running install already has it, so the version's
#: file list still holds it.  ``onlyifdoesntexist`` likewise: a fresh
#: install has the file.  Any other Check could leave a file out.
_KNOWN_CHECKS = {"keptasinstalled"}


class IssError(ValueError):
    """The [Files] section says something this reader does not model."""


def _iss_params(line):
    """``Key: "value"; Key2: value2`` -> {key: value} (keys lowercased)."""
    out = {}
    for m in re.finditer(r'\s*(\w+)\s*:\s*("(?:[^"]|"")*"|[^;]*)\s*(?:;|$)',
                         line):
        val = m.group(2).strip()
        if val.startswith('"'):
            val = val[1:-1].replace('""', '"')
        out[m.group(1).lower()] = val
    return out


def _files_section(iss_text):
    """The [Files] entries as whole lines: comments dropped, ``\\``
    continuations joined."""
    lines, cur, inside = [], "", False
    for raw in iss_text.splitlines():
        s = raw.strip()
        if s.startswith("[") and s.endswith("]"):
            inside = s.lower() == "[files]"
            continue
        if not inside or not s or s.startswith(";"):
            continue
        if s.startswith("#"):
            raise IssError("preprocessor line inside [Files]: %s" % s)
        if s.endswith("\\"):
            cur += s[:-1].rstrip() + " "
            continue
        lines.append(cur + s)
        cur = ""
    if cur:
        raise IssError("[Files] ends in a continuation line")
    return lines


def _wild(pattern):
    """An Inno wildcard (``*`` ``?``) for ONE path component, as a regex."""
    return re.compile("".join(
        ".*" if c == "*" else "." if c == "?" else re.escape(c)
        for c in pattern.lower()) + r"\Z", re.S)


class _Excludes:
    """Inno's ``Excludes``: a pattern is matched against the END of the
    path (as many components as the pattern has), or against its START
    when it begins with a backslash.  Directories are tested too, and an
    excluded directory is not entered."""

    def __init__(self, text):
        self.pats = []
        for p in (text or "").split(","):
            p = p.strip()
            if not p:
                continue
            anchored = p.startswith("\\")
            self.pats.append((anchored, [_wild(c) for c in
                                         p.strip("\\").split("\\")]))

    def match(self, rel):
        comps = rel.lower().split("\\")
        for anchored, pats in self.pats:
            if len(pats) > len(comps):
                continue
            part = comps[:len(pats)] if anchored else comps[-len(pats):]
            if anchored and len(pats) != len(comps):
                continue
            if all(p.match(c) for p, c in zip(pats, part)):
                return True
        return False


def _hidden(entry):
    """Inno leaves hidden files out unless the entry says ``hidden``."""
    try:
        attrs = entry.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN)


def iss_files(iss_path=ISS, defines=None):
    """What the setup exe installs: ``{dest (app-relative, "/"): source
    path}``.  *defines* fills ``{#Name}`` (ProjectDir, PythonDir)."""
    defines = {k.lower(): v for k, v in (defines or {}).items()}
    base = os.path.dirname(os.path.abspath(iss_path))
    with open(iss_path, encoding="utf-8-sig") as f:
        text = f.read()

    def _expand(s):
        def _one(m):
            try:
                return defines[m.group(1).lower()]
            except KeyError:
                raise IssError("no value for {#%s}" % m.group(1)) from None
        return re.sub(r"\{#(\w+)\}", _one, s)

    out = {}
    for line in _files_section(text):
        p = _iss_params(line)
        unknown = set(p) - _KNOWN_PARAMS
        if unknown:
            raise IssError("unknown [Files] parameter %s in: %s"
                           % (sorted(unknown), line))
        flags = set(p.get("flags", "").lower().split())
        if flags - _KNOWN_FLAGS:
            raise IssError("unknown [Files] flag %s in: %s"
                           % (sorted(flags - _KNOWN_FLAGS), line))
        check = p.get("check", "").split("(")[0].strip().lower()
        if check and check not in _KNOWN_CHECKS:
            raise IssError("unknown [Files] Check %s in: %s"
                           % (p["check"], line))
        if "source" not in p or "destdir" not in p:
            raise IssError("no Source/DestDir in: %s" % line)
        dest = p["destdir"]
        if not dest.lower().startswith("{app}"):
            raise IssError("DestDir outside {app}: %s" % line)
        dest = dest[len("{app}"):].strip("\\")
        if "{" in dest:
            raise IssError("constant in DestDir: %s" % line)
        source = _expand(p["source"])
        if os.sep != "\\":
            # read on a host that is not Windows (the tests): the script's
            # backslashes are its path separators
            source = source.replace("\\", os.sep)
        src = os.path.normpath(os.path.join(base, source))
        src_dir, mask = os.path.split(src)
        if "*" in src_dir or "?" in src_dir:
            raise IssError("wildcard in a Source folder: %s" % line)
        mask_re = _wild(mask)
        excl = _Excludes(p.get("excludes"))
        recurse = "recursesubdirs" in flags
        found = False
        stack = [""]
        while stack:
            sub = stack.pop()
            try:
                entries = sorted(os.scandir(os.path.join(src_dir, sub)),
                                 key=lambda e: e.name.lower())
            except OSError as e:
                raise IssError("cannot read %s: %s"
                               % (os.path.join(src_dir, sub), e)) from None
            for e in entries:
                here = os.path.join(sub, e.name) if sub else e.name
                rel = here.replace("/", "\\")     # as Inno names it
                if excl.match(rel) or _hidden(e):
                    continue
                if e.is_dir():
                    if recurse:
                        stack.append(here)
                    continue
                if not mask_re.match(e.name.lower()):
                    continue
                found = True
                key = "/".join(x for x in (dest.replace("\\", "/"),
                                           rel.replace("\\", "/")) if x)
                out[key] = e.path
        if not found:
            raise IssError("Source matches no file: %s" % line)
    return out


def source_of_pyc(path):
    """``a/__pycache__/x.cpython-312.pyc`` -> ``a/x.py``; None for any
    other path."""
    parts = path.split("/")
    if (len(parts) < 2 or parts[-2] != "__pycache__"
            or not parts[-1].lower().endswith(".pyc")):
        return None
    return "/".join(parts[:-2] + [parts[-1].split(".")[0] + ".py"])


def drop_compiled(files):
    """*files* without the ``.pyc`` whose source is also in it (see the
    module docstring)."""
    lower = {k.lower() for k in files}
    return {k: v for k, v in files.items()
            if (source_of_pyc(k) or "").lower() not in lower}


def _sha_file(path):
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def read_manifest(path):
    with gzip.open(path, "rb") as f:
        data = json.loads(f.read().decode("utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError("manifest format %r" % data.get("format"))
    return data


def pack_url(repo, tag, name):
    return "https://github.com/%s/releases/download/%s/%s" % (repo, tag, name)


def _reachable(url, opener=None):
    """True when one byte of *url* can be fetched (a yanked release's pack
    answers 404)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Pinball-Asset-Decryptor-Build", "Range": "bytes=0-0"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=30) as r:
            return r.status in (200, 206)
    except Exception:                                       # noqa: BLE001
        return False


def reusable_blobs(previous, repo, reachable=_reachable):
    """``{sha256: (pack {"tag","name"}, offset, clen, method)}`` for every
    file of the *previous* manifest whose pack can still be downloaded."""
    packs = previous.get("packs") or []
    with ThreadPoolExecutor(8) as ex:
        alive = list(ex.map(
            lambda p: bool(reachable(pack_url(repo, p["tag"], p["name"]))),
            packs))
    out = {}
    for _path, _size, sha, pi, off, clen, method in previous["files"]:
        if 0 <= pi < len(packs) and alive[pi]:
            out.setdefault(sha, (packs[pi], off, clen, method))
    return out, [p for p, ok in zip(packs, alive) if not ok]


def _compress(path):
    with open(path, "rb") as f:
        raw = f.read()
    packed = zlib.compress(raw, 9)
    return (DEFLATED, packed) if len(packed) < len(raw) else (STORED, raw)


def build(files, version, out_dir, base_name, previous=None, repo=None,
          reachable=_reachable, log=print):
    """Write the manifest and pack for *files* (``{dest: source path}``)
    into *out_dir*.  Returns ``(manifest path, pack path, stats)``."""
    files = drop_compiled(files)
    names = sorted(files)
    with ThreadPoolExecutor(8) as ex:
        hashed = list(ex.map(lambda n: _sha_file(files[n]), names))
    reuse, lost = ({}, [])
    if previous is not None:
        reuse, lost = reusable_blobs(previous, repo, reachable)
        for p in lost:
            log("  pack %s of %s is gone - its files are packed again"
                % (p["name"], p["tag"]))
    own = {"tag": "v" + version, "name": base_name + PACK_SUFFIX}
    packs = [own]
    pack_index = {(own["tag"], own["name"]): 0}
    fresh = {}                      # sha -> source path, first seen
    for name, (sha, _size) in zip(names, hashed):
        if sha not in reuse:
            fresh.setdefault(sha, files[name])
    os.makedirs(out_dir, exist_ok=True)
    pack_path = os.path.join(out_dir, own["name"])
    placed = {}                     # sha -> (offset, clen, method)
    offset = 0
    order = sorted(fresh)
    with open(pack_path, "wb") as pack, ThreadPoolExecutor(
            max(2, (os.cpu_count() or 4) - 1)) as ex:
        for sha, (method, blob) in zip(order, ex.map(
                lambda s: _compress(fresh[s]), order)):
            pack.write(blob)
            placed[sha] = (offset, len(blob), method)
            offset += len(blob)
    rows = []
    for name, (sha, size) in zip(names, hashed):
        if sha in placed:
            pi, (off, clen, method) = 0, placed[sha]
        else:
            p, off, clen, method = reuse[sha]
            key = (p["tag"], p["name"])
            if key not in pack_index:
                pack_index[key] = len(packs)
                packs.append({"tag": p["tag"], "name": p["name"]})
            pi = pack_index[key]
        rows.append([name, size, sha, pi, off, clen, method])
    manifest = {"format": FORMAT, "version": version, "packs": packs,
                "files": rows}
    manifest_path = os.path.join(out_dir, base_name + MANIFEST_SUFFIX)
    with open(manifest_path, "wb") as raw:
        # mtime=0: the same tree gives the same manifest bytes
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(json.dumps(manifest, separators=(",", ":"))
                     .encode("utf-8"))
    stats = {"files": len(rows), "bytes": sum(r[1] for r in rows),
             "new_files": sum(1 for r in rows if r[3] == 0),
             "pack_bytes": offset, "packs": len(packs),
             "manifest_bytes": os.path.getsize(manifest_path)}
    return manifest_path, pack_path, stats


def verify(folder, manifest):
    """Compare an installed *folder* (the real setup exe's work) with
    *manifest*.  Returns a list of differences, empty when they agree.
    Compiled ``.pyc`` beside a source, the uninstaller and the staging
    marker are not the manifest's business."""
    want = {r[0].lower(): (r[1], r[2]) for r in manifest["files"]}
    have = {}
    for root, _dirs, names in os.walk(folder):
        for n in names:
            full = os.path.join(root, n)
            rel = os.path.relpath(full, folder).replace("\\", "/")
            have[rel] = full
    have = drop_compiled(have)
    problems = []
    seen = set()
    for rel, full in sorted(have.items()):
        low = rel.lower()
        if "/" not in rel and (low.startswith("unins")
                               or low == ".pad_staged.json"):
            continue
        if "__pycache__" in low.split("/") and low not in want:
            continue            # compiled at install time (compileall)
        seen.add(low)
        if low not in want:
            problems.append("installed but not in the manifest: %s" % rel)
            continue
        sha, size = _sha_file(full)
        if (size, sha) != want[low]:
            problems.append("differs from the manifest: %s" % rel)
    for low in sorted(set(want) - seen):
        problems.append("in the manifest but not installed: %s" % low)
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", help="default: the project's __version__")
    ap.add_argument("--installer", help="the setup exe these assets go "
                    "beside: they take its name")
    ap.add_argument("--python-dir", default=os.path.join(_HERE, "build",
                                                         "python"))
    ap.add_argument("--project-dir", default=os.path.dirname(_HERE))
    ap.add_argument("--iss", default=ISS)
    ap.add_argument("--out", default=os.path.join(_HERE, "Output"))
    ap.add_argument("--previous", help="the previous release's manifest; "
                    "without it every file goes into this release's pack")
    ap.add_argument("--repo", help="owner/name, to check the earlier packs "
                    "are still downloadable")
    ap.add_argument("--verify", metavar="FOLDER",
                    help="compare an installed folder with --manifest")
    ap.add_argument("--manifest")
    a = ap.parse_args(argv)
    if a.verify:
        problems = verify(a.verify, read_manifest(a.manifest))
        for p in problems[:40]:
            print("  " + p)
        print("manifest %s the installed folder (%d difference(s))"
              % ("MATCHES" if not problems else "DOES NOT MATCH",
                 len(problems)))
        return 1 if problems else 0
    if not a.version:
        with open(os.path.join(a.project_dir, "pinball_decryptor",
                               "__init__.py"), encoding="utf-8") as f:
            m = re.search(r'^__version__\s*=\s*["\']([^"\']+)', f.read(),
                          re.M)
        if not m:
            ap.error("no __version__ in the project; pass --version")
        a.version = m.group(1)
    files = iss_files(a.iss, {"ProjectDir": os.path.abspath(a.project_dir),
                              "PythonDir": os.path.abspath(a.python_dir),
                              "AppVersion": a.version})
    previous = None
    if a.previous and os.path.isfile(a.previous):
        if not a.repo:
            ap.error("--previous needs --repo")
        try:
            previous = read_manifest(a.previous)
        except (OSError, ValueError) as e:
            print("  previous manifest unreadable (%s) - packing every file"
                  % e)
    base = "Pinball_Asset_Decryptor_v%s_Windows" % a.version
    if a.installer:
        base = os.path.splitext(os.path.basename(a.installer))[0]
        if ("v%s_" % a.version) not in base:
            print("  %s is not v%s's installer" % (a.installer, a.version))
            return 2
    mpath, ppath, st = build(files, a.version, a.out, base, previous, a.repo)
    print("delta assets for v%s: %d files (%.0f MB); %d new in this pack "
          "(%.1f MB); %d pack(s) referenced; manifest %.0f KB"
          % (a.version, st["files"], st["bytes"] / 1e6, st["new_files"],
             st["pack_bytes"] / 1e6, st["packs"],
             st["manifest_bytes"] / 1e3))
    print("  " + mpath)
    print("  " + ppath)
    return 0


if __name__ == "__main__":
    sys.exit(main())
