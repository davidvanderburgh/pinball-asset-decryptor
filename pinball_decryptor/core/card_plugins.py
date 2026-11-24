"""Plugins: optional add-ons made by other people, pulled from their own repository (PAD-1554).

David, on putting mattlqx's Bluetooth headphones on a card: "would you be cool if I integrated your bluetooth
feature into PAD?"  The author: "do you think you could have it pull the repo and use it from there rather than
pulling all the code into the PAD repo?  maybe select a version tag or something.  installation integration would
be great."  And David on the screen: "maybe a new Plugins tab, where the user can choose optional plugins to
install.  they need to persist between PAD updates too."

So a plugin is **not in this repository and not in the app's download**.  It is a release its author published,
at a version tag the user picked, fetched from the author's project when the user installs it:

* **Where it is kept.**  ``<settings folder>/plugins/<key>/`` (``%APPDATA%\\pinball_decryptor`` on Windows): beside
  the app's settings, outside the app's own folder, so an app update neither removes nor replaces it.  One release
  at a time: its archives as downloaded, the release's ``SHA256SUMS``, and ``installed.json`` (the tag and each
  file's hash and size).
* **What "the right file" means.**  A tag this version of the app was tested with has its archive hashes written
  here (:attr:`Plugin.pinned`), and nothing else is accepted for it.  A newer tag is taken on the release's own
  ``SHA256SUMS`` over HTTPS and is said to be untested, by the screen as well.  Either way each archive must be a
  flat tar of plain files whose own ``SHA256SUMS`` member matches every other member.
* **Nothing runs here.**  Installing is a download and a check.  The files only ever run on a machine, after a
  card build puts them there (for Bluetooth headphones: core/bluetooth_card.py).
"""
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Tuple

from . import config, net

TIMEOUT = 60
MAX_ARCHIVE = 64 << 20                  # a release archive: the Bluetooth ones are 4 MB
MAX_MEMBER = 32 << 20                   # one file of one, unpacked
MAX_TEXT = 1 << 20                      # SHA256SUMS, the releases list
TAG = re.compile(r'^v\d{1,4}(\.\d{1,4}){1,3}$')
SUMS = 'SHA256SUMS'
RECORD = 'installed.json'
_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


class PluginError(ValueError):
    """A plugin could not be listed, fetched, checked or read: the sentence is for the user."""


@dataclass(frozen=True)
class Plugin:
    """One optional add-on and where its author publishes it.

    Attributes:
        key: the folder it is kept under and the name the screen and the tests use (``"bluetooth"``).
        name / what: the title and one plain sentence for the Plugins tab.
        author: who made it, as the tab credits them.
        project: the GitLab project page (``https://gitlab.com/<namespace>/<name>``).
        license: its licence, named on the tab.
        archives: ``{arch: file name}``, the release asset for each kind of machine.
        needs: ``{arch: (member, ...)}``, the files an archive must hold to be this plugin at all.
        tested: the tag this version of the app was proven with; the one Install offers first.
        pinned: ``{tag: {file name: sha256}}`` for every tag the app has been tested with.
    """
    key: str
    name: str
    what: str
    author: str
    project: str
    license: str
    archives: Dict[str, str]
    needs: Dict[str, Tuple[str, ...]]
    tested: str
    pinned: Dict[str, Dict[str, str]] = field(default_factory=dict)


PLUGINS: Dict[str, Plugin] = {}


def register(plugin):
    PLUGINS[plugin.key] = plugin
    return plugin


# ------------------------------------------------------------------ where things are
def store_root():
    """The folder installed plugins are kept in.  ``PAD_PLUGIN_DIR`` moves it (the tests, a portable set-up)."""
    return os.environ.get('PAD_PLUGIN_DIR') or os.path.join(config._settings_root(), 'plugins')


def plugin_dir(plugin):
    return os.path.join(store_root(), plugin.key)


def asset_url(plugin, tag, name):
    """A release asset's permanent address: GitLab redirects it to wherever the author uploaded the file."""
    return '%s/-/releases/%s/downloads/%s' % (plugin.project, _tag(tag), name)


def releases_url(plugin):
    path = urllib.parse.urlparse(plugin.project).path.strip('/')
    return 'https://gitlab.com/api/v4/projects/%s/releases?per_page=30' % urllib.parse.quote(path, safe='')


def _tag(tag):
    if not isinstance(tag, str) or not TAG.match(tag):
        raise PluginError('%r is not a release version this app can use (it expects one like v0.3.0).' % (tag,))
    return tag


def tag_key(tag):
    return tuple(int(n) for n in tag[1:].split('.'))


# ------------------------------------------------------------------ the network
def _get(url, limit, opener=None, progress=None):
    do_open = opener or net.urlopen
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'pad-plugins'})
        out, done = io.BytesIO(), 0
        with do_open(req, timeout=TIMEOUT) as resp:
            while True:
                block = resp.read(1 << 16)
                if not block:
                    break
                done += len(block)
                if done > limit:
                    raise PluginError('The file at %s is larger than a plugin file can be.' % url)
                out.write(block)
                if progress:
                    progress(done)
        return out.getvalue()
    except PluginError:
        raise
    except Exception as exc:                                           # noqa: BLE001
        raise PluginError('Could not download %s: %s\nPlugins come from gitlab.com, which this computer has to '
                          'be able to reach; or download the files on another computer and use "Install from '
                          'files".' % (url, exc)) from exc


def releases(plugin, opener=None):
    """The author's published releases, newest first: ``[dict(tag, title, date, tested)]``.  Only tags of the
    ``v1.2.3`` shape that carry every archive this plugin needs are offered."""
    answer = _get(releases_url(plugin), MAX_TEXT, opener)
    try:
        rows = json.loads(answer.decode('utf-8'))
    except ValueError:
        raise PluginError('gitlab.com answered the list of %s releases in a form this app does not read.'
                          % plugin.name) from None
    out = []
    for row in rows if isinstance(rows, list) else []:
        tag = row.get('tag_name') if isinstance(row, dict) else None
        if not isinstance(tag, str) or not TAG.match(tag):
            continue
        links = ((row.get('assets') or {}).get('links') or []) if isinstance(row.get('assets'), dict) else []
        have = {l.get('name') for l in links if isinstance(l, dict)}
        if not set(plugin.archives.values()) | {SUMS} <= have:
            continue
        out.append({'tag': tag, 'title': str(row.get('name') or tag)[:120],
                    'date': str(row.get('released_at') or '')[:10], 'tested': tag in plugin.pinned})
    out.sort(key=lambda r: tag_key(r['tag']), reverse=True)
    return out


# ------------------------------------------------------------------ checking a release
def parse_sums(text):
    """``{file name: sha256}`` from a ``sha256sum`` listing; lines that are not one are refused."""
    out = {}
    for line in (text.decode('utf-8', 'replace') if isinstance(text, bytes) else text).splitlines():
        if not line.strip():
            continue
        m = re.match(r'^([0-9a-f]{64}) [ *](\S+)$', line.strip())
        if not m or not _NAME.match(m.group(2)):
            raise PluginError('The release checksum list has a line this app does not read.')
        out[m.group(2)] = m.group(1)
    return out


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def unpack(plugin, arch, data):
    """``{member name: (bytes, mode)}`` of the release archive *data* for *arch*, or PluginError.

    The archive must be what the author's packaging makes: a gzip tar of plain files at its top level (no folders,
    links or devices), holding a ``SHA256SUMS`` that names every other member with its hash, and every file this
    plugin needs.  Mode is 0o755 for a member the archive marks executable, 0o644 for the rest."""
    members = {}
    try:
        raw = gzip.GzipFile(fileobj=io.BytesIO(data)).read(MAX_ARCHIVE * 4 + 1)
        if len(raw) > MAX_ARCHIVE * 4:
            raise PluginError('The %s archive unpacks to more than a plugin can be.' % plugin.name)
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as tar:
            for info in tar:
                if not info.isreg() or not _NAME.match(info.name) or info.size > MAX_MEMBER or info.name in members:
                    raise PluginError('The %s archive holds %r, which is not a plain file at its top level.'
                                      % (plugin.name, info.name[:80]))
                members[info.name] = (tar.extractfile(info).read(), 0o755 if info.mode & 0o100 else 0o644)
    except PluginError:
        raise
    except (OSError, EOFError, tarfile.TarError, ValueError):
        raise PluginError('The %s archive is not a readable .tar.gz.' % plugin.name) from None
    if SUMS not in members:
        raise PluginError('The %s archive has no SHA256SUMS of its own.' % plugin.name)
    sums = parse_sums(members[SUMS][0])
    names = set(members) - {SUMS}
    if set(sums) != names or any(sha256(members[n][0]) != sums[n] for n in names):
        raise PluginError('The files in the %s archive do not match its own SHA256SUMS.' % plugin.name)
    missing = [n for n in plugin.needs.get(arch, ()) if n not in members]
    if missing:
        raise PluginError('The %s archive for %s has no %s: this version of the app cannot use that release.'
                          % (plugin.name, arch, ', '.join(missing)))
    return members


def _check_release(plugin, tag, sums_text, blobs):
    """Refuse unless every archive in *blobs* (``{file name: bytes}``) is the one release *tag* published."""
    listed = parse_sums(sums_text)
    pinned = plugin.pinned.get(tag)
    for arch, name in plugin.archives.items():
        got = sha256(blobs[name])
        want = (pinned or listed).get(name)
        if want is None:
            raise PluginError("The release's checksum list does not name %s." % name)
        if got != want or (pinned and listed.get(name) not in (None, want)):
            raise PluginError('%s is not the file release %s published (its checksum is %s..., the release says '
                              '%s...). Nothing was installed.' % (name, tag, got[:12], want[:12]))
        unpack(plugin, arch, blobs[name])


# ------------------------------------------------------------------ the store
def installed(plugin):
    """``dict(tag, tested, files={name: dict(sha256, size)})`` for the release that is installed, or None.
    Never raises: a store that is not whole (a file gone, changed, a record that is not one) reads as nothing
    installed, and Install puts it right."""
    folder = plugin_dir(plugin)
    try:
        with open(os.path.join(folder, RECORD), encoding='utf-8') as f:
            rec = json.load(f)
        tag, files = _tag(rec['tag']), rec['files']
        for name in list(plugin.archives.values()) + [SUMS]:
            entry = files[name]
            if os.path.getsize(os.path.join(folder, name)) != entry['size'] or not re.match(
                    r'^[0-9a-f]{64}$', entry['sha256']):
                return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {'tag': tag, 'tested': tag in plugin.pinned,
            'files': {n: dict(files[n]) for n in list(plugin.archives.values()) + [SUMS]}}


def _store(plugin, tag, sums_text, blobs):
    _check_release(plugin, tag, sums_text, blobs)
    folder = plugin_dir(plugin)
    fresh = folder + '.new'
    shutil.rmtree(fresh, ignore_errors=True)
    try:
        os.makedirs(fresh)
        files = dict(blobs)
        files[SUMS] = sums_text if isinstance(sums_text, bytes) else sums_text.encode('utf-8')
        for name, data in files.items():
            with open(os.path.join(fresh, name), 'wb') as f:
                f.write(data)
        with open(os.path.join(fresh, RECORD), 'w', encoding='utf-8') as f:
            json.dump({'tag': tag, 'project': plugin.project,
                       'files': {n: {'sha256': sha256(d), 'size': len(d)} for n, d in files.items()}}, f, indent=1)
        # the whole folder changes hands at once: a reader sees the old release or the new one, never a mix
        old = folder + '.old'
        shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(folder):
            os.replace(folder, old)
        os.replace(fresh, folder)
        shutil.rmtree(old, ignore_errors=True)
    except OSError as exc:
        shutil.rmtree(fresh, ignore_errors=True)
        raise PluginError('The %s plugin could not be saved to %s: %s' % (plugin.name, folder, exc)) from None
    return installed(plugin)


def install(plugin, tag=None, log=None, opener=None, progress=None):
    """Fetch release *tag* (the tested one when None) from the author's project, check it, and keep it."""
    tag = _tag(tag or plugin.tested)
    if log:
        log('Downloading %s %s from %s…' % (plugin.name, tag, plugin.project))
    sums_text = _get(asset_url(plugin, tag, SUMS), MAX_TEXT, opener)
    blobs = {}
    for name in plugin.archives.values():
        blobs[name] = _get(asset_url(plugin, tag, name), MAX_ARCHIVE, opener,
                           (lambda done, name=name: progress(name, done)) if progress else None)
    rec = _store(plugin, tag, sums_text, blobs)
    if log:
        log('%s %s installed%s.' % (plugin.name, tag, '' if rec['tested'] else
                                    ' (newer than this version of the app was tested with)'))
    return rec


def install_from_files(plugin, paths, log=None):
    """The same, for a computer that cannot reach gitlab.com: *paths* are the release's archives and its
    ``SHA256SUMS`` as downloaded elsewhere.  Only a release this app was tested with is taken this way, because
    its checksums are the app's own and a file handed over by hand has no other witness."""
    by_name = {os.path.basename(p): p for p in paths}
    want = list(plugin.archives.values())
    missing = [n for n in want + [SUMS] if n not in by_name]
    if missing:
        raise PluginError('Choose %s from the release as well.' % ' and '.join(missing))
    blobs = {}
    try:
        for name in want + [SUMS]:
            if os.path.getsize(by_name[name]) > MAX_ARCHIVE:
                raise PluginError('%s is larger than a plugin file can be.' % name)
            with open(by_name[name], 'rb') as f:
                blobs[name] = f.read()
    except OSError as exc:
        raise PluginError('Could not read the chosen files: %s' % exc) from None
    sums_text = blobs.pop(SUMS)
    hashes = {n: sha256(blobs[n]) for n in want}
    tag = next((t for t, pin in plugin.pinned.items() if all(pin.get(n) == hashes[n] for n in want)), None)
    if tag is None:
        raise PluginError('Those files are not a %s release this version of the app knows (it knows %s).'
                          % (plugin.name, ', '.join(sorted(plugin.pinned, key=tag_key))))
    rec = _store(plugin, tag, sums_text, blobs)
    if log:
        log('%s %s installed from files.' % (plugin.name, tag))
    return rec


def remove(plugin):
    """Take the installed release off this computer.  Cards already written keep what was put on them."""
    folder = plugin_dir(plugin)
    try:
        if os.path.isdir(folder):
            shutil.rmtree(folder)
    except OSError as exc:
        raise PluginError('The %s plugin could not be removed from %s: %s' % (plugin.name, folder, exc)) from None


def files(plugin, arch):
    """``(tag, {member name: (bytes, mode)})``: the installed release's files for *arch*, checked again against
    the record made when it was installed.  PluginError when the plugin is not installed or its store changed."""
    rec = installed(plugin)
    if rec is None:
        raise PluginError('The %s plugin is not installed. Install it on the Plugins tab first.' % plugin.name)
    name = plugin.archives.get(arch)
    if name is None:
        raise PluginError('The %s plugin has nothing for this kind of machine.' % plugin.name)
    try:
        with open(os.path.join(plugin_dir(plugin), name), 'rb') as f:
            data = f.read(MAX_ARCHIVE + 1)
    except OSError as exc:
        raise PluginError('The installed %s plugin could not be read: %s' % (plugin.name, exc)) from None
    if sha256(data) != rec['files'][name]['sha256'] or (
            rec['tested'] and sha256(data) != plugin.pinned[rec['tag']].get(name)):
        raise PluginError('The installed %s plugin has changed on disk since it was installed. Install it again '
                          'on the Plugins tab.' % plugin.name)
    return rec['tag'], unpack(plugin, arch, data)
