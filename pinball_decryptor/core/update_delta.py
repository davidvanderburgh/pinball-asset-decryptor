"""Delta updates on Windows: build the new version from the files already
installed and download only the ones that changed (PAD-1519).

David: "Can we do automatic delta updates?  so instead of replacing all the
files, we just do the new ones?  I know we have AB installs, but we need to
speed them up somehow."  The blue-green update (core/update_slots.py) made
Restart to update quick, but getting the new version ready still meant the
whole setup exe: 157 MB downloaded and 710 MB / 8,300 files unpacked, 35-56 s
of "Installing in the background" on David's PC for a release that changed a
dozen files - and several minutes of download on a slow line.

Each Windows release publishes a MANIFEST beside its setup exe
(installer/make_delta.py): every file the installer installs, with its size
and SHA-256 and where its bytes sit in a PACK - a release asset holding the
files, each compressed on its own, so one file is one HTTP range request.
:func:`build_tree` then makes ``<app>.next``:

* a file whose installed copy has the manifest's hash is copied from the
  running install (read once: hashed and written from the same bytes);
* any other file is fetched from its pack, unpacked and checked against the
  manifest's hash before it gets its name;
* ``.pyc`` files are not in the manifest (they differ on every build): the
  ones the install has for unchanged sources are copied, and the caller
  compiles the changed sources (:func:`compile_args`), as the installer does.

What comes out is file for file what the setup exe would have installed -
the release workflow installs the real exe and compares - so the same swap
takes it from there.

TRUST.  The manifest is only used when GitHub publishes its SHA-256 (the
asset ``digest``), and it is checked; every file is then checked against the
manifest.  Packs are only ever fetched from this project's own release
downloads: the manifest names a tag and an asset, never a URL.  Paths are
refused unless they are plain relative ones.

ANY FAILURE IS THE INSTALLER'S TURN.  A release without a manifest, a pack
that is gone, a hash that does not match, more to download than the setup
exe itself: :class:`DeltaUnavailable`, and the caller downloads and runs the
setup exe as before.
"""

import gzip
import hashlib
import json
import os
import re
import shutil
import threading
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor

from . import net
from .config import GITHUB_REPO

FORMAT = 1
MANIFEST_SUFFIX = ".delta.json.gz"
PACK_SUFFIX = ".delta.pack"
STORED, DEFLATED = 0, 1

#: a manifest bigger than this is not ours (a real one is ~0.5 MB)
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
#: blobs of one pack closer together than this are fetched in one request
#: (a request costs ~0.4 s of redirects; 256 KB costs less on any line)
MERGE_GAP = 256 * 1024
#: ...up to this much per request, so a retry never repeats much
MAX_SPAN = 32 * 1024 * 1024
FETCH_THREADS = 4
COPY_THREADS = 8
FETCH_TRIES = 3
TIMEOUT = 60
_CHUNK = 256 * 1024
_UA = "Pinball-Asset-Decryptor-UpdateCheck"

_TAG_RE = re.compile(r"^v\d+(\.\d+){1,3}$")
_ASSET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
#: Windows names that are never a file of ours, whatever the extension
_RESERVED = {"con", "prn", "aux", "nul"} | {
    "%s%d" % (p, i) for p in ("com", "lpt") for i in range(1, 10)}


class DeltaUnavailable(Exception):
    """This update cannot (or should not) be made from changed files; the
    message says why.  The caller uses the setup exe."""


def pick_manifest_asset(assets, installer_name):
    """The delta manifest published for the setup exe *installer_name*, as
    ``{"name", "url", "size", "sha256"}``, or None.  None too when GitHub
    gives no digest for it: an unverifiable manifest is not used."""
    want = (os.path.splitext(installer_name or "")[0]
            + MANIFEST_SUFFIX).lower()
    for a in assets or []:
        if (a.get("name") or "").lower() != want:
            continue
        digest = a.get("digest") or ""
        if (not a.get("browser_download_url")
                or not digest.startswith("sha256:")
                or not _SHA_RE.match(digest[7:])):
            return None
        return {"name": a["name"], "url": a["browser_download_url"],
                "size": a.get("size") or 0, "sha256": digest[7:]}
    return None


def _safe_path(path):
    """True for a plain relative path with ``/`` separators that stays
    inside the folder it is joined to, on Windows too."""
    if not isinstance(path, str) or not path or len(path) > 400:
        return False
    if "\\" in path or ":" in path or path.startswith("/"):
        return False
    for part in path.split("/"):
        if (not part or part in (".", "..") or part != part.strip()
                or part.endswith(".")
                or any(ord(c) < 32 or c in '<>"|?*' for c in part)
                or part.split(".")[0].lower() in _RESERVED):
            return False
    return True


def parse_manifest(raw, version):
    """The manifest in *raw* (the gzip asset's bytes), validated: for
    *version*, well-formed, every path safe.  Raises DeltaUnavailable."""
    try:
        text = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        if len(text) > 8 * MAX_MANIFEST_BYTES:
            raise ValueError("too big")
        data = json.loads(text.decode("utf-8"))
    except (OSError, ValueError, EOFError, zlib.error) as e:
        raise DeltaUnavailable("the file list is unreadable (%s)" % e)
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise DeltaUnavailable("the file list is in a format this version "
                               "does not know")
    if data.get("version") != version:
        raise DeltaUnavailable("the file list is for v%s, not v%s"
                               % (data.get("version"), version))
    packs, files = data.get("packs"), data.get("files")
    if not isinstance(packs, list) or not isinstance(files, list) or not files:
        raise DeltaUnavailable("the file list is empty")
    for p in packs:
        if (not isinstance(p, dict) or not _TAG_RE.match(str(p.get("tag")))
                or not _ASSET_RE.match(str(p.get("name")))
                or not str(p.get("name")).endswith(PACK_SUFFIX)):
            raise DeltaUnavailable("the file list names a pack that is not "
                                   "a release download")
    seen = set()
    for row in files:
        ok = (isinstance(row, list) and len(row) == 7
              and _safe_path(row[0])
              and all(isinstance(v, int) and not isinstance(v, bool)
                      and v >= 0 for v in (row[1], row[3], row[4], row[5]))
              and isinstance(row[2], str) and _SHA_RE.match(row[2])
              and row[3] < len(packs) and row[6] in (STORED, DEFLATED))
        if not ok:
            raise DeltaUnavailable("the file list has a bad entry")
        low = row[0].lower()
        if low in seen:
            raise DeltaUnavailable("the file list names %s twice" % row[0])
        seen.add(low)
    return data


def pack_url(pack, repo=GITHUB_REPO):
    return "https://github.com/%s/releases/download/%s/%s" % (
        repo, pack["tag"], pack["name"])


def fetch_manifest(asset, version, opener=None):
    """Download and check the manifest *asset* (from
    :func:`pick_manifest_asset`).  Raises DeltaUnavailable."""
    do_open = opener or net.urlopen
    req = urllib.request.Request(asset["url"], headers={"User-Agent": _UA})
    try:
        with do_open(req, timeout=TIMEOUT) as resp:
            raw = resp.read(MAX_MANIFEST_BYTES + 1)
    except Exception as e:                                  # noqa: BLE001
        raise DeltaUnavailable("the file list could not be downloaded "
                               "(%s: %s)" % (type(e).__name__, e))
    if len(raw) > MAX_MANIFEST_BYTES:
        raise DeltaUnavailable("the file list is too big")
    if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
        raise DeltaUnavailable("the file list failed its integrity check")
    return parse_manifest(raw, version)


# ----------------------------------------------------------------------
# building the new folder
# ----------------------------------------------------------------------

def _take_local(src, dst, size, sha):
    """Copy *src* to *dst* if it is the manifest's file (same size, same
    SHA-256), keeping its timestamps - a ``.pyc`` beside it stays valid.
    The bytes written are the bytes hashed.  True when taken."""
    try:
        st = os.stat(src)
        if st.st_size != size:
            return False
        with open(src, "rb") as f:
            data = f.read()
    except OSError:
        return False
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f:
        f.write(data)
    os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
    return True


def _carry_pyc(app_dir, target, path):
    """Copy the running install's compiled files for the unchanged source
    *path* (``a/x.py`` -> ``a/__pycache__/x.*.pyc``)."""
    if not path.lower().endswith(".py"):
        return
    folder, name = os.path.split(path)
    cache = os.path.join(app_dir, folder, "__pycache__")
    stem = name[:-3] + "."
    try:
        names = [n for n in os.listdir(cache)
                 if n.startswith(stem) and n.lower().endswith(".pyc")]
    except OSError:
        return
    for n in names:
        dst = os.path.join(target, folder, "__pycache__", n)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(cache, n), dst)
        except OSError:
            pass                    # compiled again on first import


def plan_spans(blobs):
    """Group *blobs* (``(offset, clen, ...)`` of ONE pack) into the byte
    ranges to request: neighbours closer than MERGE_GAP share a request,
    up to MAX_SPAN each.  Returns ``[[blob, ...], ...]`` in offset order."""
    spans = []
    for b in sorted(blobs, key=lambda b: b[0]):
        if spans:
            first, last = spans[-1][0], spans[-1][-1]
            end = last[0] + last[1]
            if (b[0] - end <= MERGE_GAP and b[0] >= end
                    and b[0] + b[1] - first[0] <= MAX_SPAN):
                spans[-1].append(b)
                continue
        spans.append([b])
    return spans


def _read_exact(resp, n, cancel_cb, sink=None, count=None):
    """Read *n* bytes of *resp*, feeding them to *sink*; short is an
    error."""
    left = n
    while left:
        if cancel_cb and cancel_cb():
            raise InterruptedError("update canceled")
        chunk = resp.read(min(_CHUNK, left))
        if not chunk:
            raise EOFError("the download ended early")
        left -= len(chunk)
        if sink:
            sink(chunk)
        if count:
            count(len(chunk))


def _fetch_span(url, span, target, opener, cancel_cb, count):
    """One range request: every blob of *span* (``(offset, clen, method,
    size, sha, path)``) unpacked to ``target/path``, each checked against
    its hash before it gets its name."""
    start = span[0][0]
    end = span[-1][0] + span[-1][1] - 1
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Range": "bytes=%d-%d" % (start, end)})
    with opener(req, timeout=TIMEOUT) as resp:
        status = getattr(resp, "status", None)
        if status != 206:
            # 200 would be the whole pack from byte 0: not what the
            # offsets below assume
            raise DeltaUnavailable("the download server ignored the range "
                                   "request (HTTP %s)" % status)
        pos = start
        for off, clen, method, size, sha, path in span:
            if off > pos:
                _read_exact(resp, off - pos, cancel_cb)
            dst = os.path.join(target, path.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            part = dst + ".part"
            digest = hashlib.sha256()
            unz = zlib.decompressobj() if method == DEFLATED else None
            written = [0]
            try:
                with open(part, "wb") as out:
                    def _sink(chunk):
                        data = unz.decompress(chunk) if unz else chunk
                        written[0] += len(data)
                        if written[0] > size:
                            raise ValueError("%s unpacks bigger than the "
                                             "file list says" % path)
                        digest.update(data)
                        out.write(data)
                    _read_exact(resp, clen, cancel_cb, _sink, count)
                    if unz:
                        tail = unz.flush()
                        written[0] += len(tail)
                        digest.update(tail)
                        out.write(tail)
                if written[0] != size or digest.hexdigest() != sha:
                    raise ValueError("%s failed its integrity check" % path)
                os.replace(part, dst)
            except BaseException:
                try:
                    os.unlink(part)
                except OSError:
                    pass
                raise
            pos = off + clen


def build_tree(manifest, app_dir, target, *, opener=None, cancel_cb=None,
               progress_cb=None, max_download=None, repo=GITHUB_REPO):
    """Make *target* the manifest's version, from *app_dir*'s files and the
    packs.  *target* must not exist yet; the caller removes it on any
    exception.  ``progress_cb(stage, done, total)`` with stage ``"copy"``
    (files) then ``"download"`` (bytes).  *max_download*: more packed bytes
    to fetch than this raises DeltaUnavailable before any is fetched.

    Returns ``{"copied", "fetched", "fetched_bytes", "changed": [paths]}``.
    """
    opener = opener or net.urlopen
    rows = manifest["files"]
    os.makedirs(target)
    missing = []
    done = [0]
    lock = threading.Lock()

    def _local(row):
        if cancel_cb and cancel_cb():
            raise InterruptedError("update canceled")
        path, size, sha = row[0], row[1], row[2]
        rel = path.replace("/", os.sep)
        took = _take_local(os.path.join(app_dir, rel),
                           os.path.join(target, rel), size, sha)
        if took:
            _carry_pyc(app_dir, target, rel)
        with lock:
            done[0] += 1
            if not took:
                missing.append(row)
            if progress_cb and (done[0] % 200 == 0 or done[0] == len(rows)):
                progress_cb("copy", done[0], len(rows))

    with ThreadPoolExecutor(COPY_THREADS) as ex:
        list(ex.map(_local, rows))

    # one download per distinct content; the other paths are copies of it
    first = {}
    twins = []
    for row in sorted(missing, key=lambda r: r[0]):
        if row[2] in first:
            twins.append(row)
        else:
            first[row[2]] = row
    need = sum(r[5] for r in first.values())
    if max_download is not None and need > max_download:
        raise DeltaUnavailable(
            "%.0f MB of files changed - no smaller than the installer"
            % (need / 1e6))
    by_pack = {}
    for path, size, sha, pi, off, clen, method in first.values():
        by_pack.setdefault(pi, []).append((off, clen, method, size, sha,
                                           path))
    jobs = [(pack_url(manifest["packs"][pi], repo), span)
            for pi, blobs in sorted(by_pack.items())
            for span in plan_spans(blobs)]
    got = [0]

    def _count(n):
        with lock:
            got[0] += n
            if progress_cb:
                progress_cb("download", got[0], need)

    def _job(job):
        url, span = job
        last = None
        for _ in range(FETCH_TRIES):
            mine = [0]

            def _mine(n):
                mine[0] += n
                _count(n)
            try:
                _fetch_span(url, span, target, opener, cancel_cb, _mine)
                return
            except (InterruptedError, DeltaUnavailable):
                raise
            except Exception as e:                          # noqa: BLE001
                last = e
                _count(-mine[0])    # the retry fetches these again
        raise DeltaUnavailable("a changed file could not be downloaded "
                               "(%s: %s)" % (type(last).__name__, last))

    if jobs:
        if progress_cb:
            progress_cb("download", 0, need)
        with ThreadPoolExecutor(FETCH_THREADS) as ex:
            list(ex.map(_job, jobs))
    for row in twins:
        src = os.path.join(target, first[row[2]][0].replace("/", os.sep))
        dst = os.path.join(target, row[0].replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    return {"copied": len(rows) - len(missing), "fetched": len(missing),
            "fetched_bytes": need,
            "changed": sorted(r[0] for r in missing)}


def compile_args(target, changed, list_path):
    """The bundled Python's command line that compiles what the installer
    would have: the app's package (as pinball_decryptor.iss [Run] does -
    unchanged modules already have their ``.pyc`` and are skipped) and the
    changed sources of the bundled Python's own packages, which the build
    ships compiled.  Writes the latter to *list_path* (compileall ``-i``)."""
    extra = [os.path.join(target, p.replace("/", os.sep)) for p in changed
             if p.lower().startswith("python/") and p.lower().endswith(".py")]
    args = [os.path.join(target, "python", "python.exe"), "-m", "compileall",
            "-q", "-j", "0"]
    if extra:
        with open(list_path, "w", encoding="utf-8") as f:
            f.write("\n".join(extra) + "\n")
        args += ["-i", list_path]
    return args + [os.path.join(target, "pinball_decryptor")]
