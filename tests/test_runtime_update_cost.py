"""What a software update costs the user, in downloads.

The runtime image is 414 MB.  David's requirement, in his words: a user should
be able to do a normal software update and get the latest runtime installed as
necessary, and if the runtime has NOT changed a newer app version must not
re-download it.  Only a changed runtime costs a download.

That promise rests on two independent mechanisms, and these pin both:

* the app decides whether the INSTALLED distro is current by reading a version
  stamp inside it, so an app update that did not move that number leaves the
  distro completely alone; and
* the cached image is named after its own checksum, so an unchanged image is a
  cache HIT (no network at all) while a re-cut one lands beside it rather than
  on top of it.

The second half is what makes a rollback cheap too: the previous image is still
on disk under its own name, so going back is not another 414 MB.
"""
import json
import os
import pathlib
import subprocess
from dataclasses import replace

import pytest

from pinball_decryptor.core import payloads, runtime

MANIFEST = {"runtime_version": runtime.RUNTIME_VERSION, "variant": "base",
            "snapshot": "20260801T000000Z", "built": "2026-09-08T00:00:00Z"}


def _sha(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _proc(stdout=b"", rc=0):
    return subprocess.CompletedProcess([], rc, stdout, b"")


def _runner(listed=(runtime.DISTRO,), version=None):
    """A fake wsl.exe whose installed runtime reports *version*."""
    body = dict(MANIFEST)
    if version is not None:
        body["runtime_version"] = version

    def run(args, timeout=None, stdin=None):
        if args[:3] == ["wsl.exe", "-l", "-q"]:
            return _proc("\n".join(listed).encode("utf-8"))
        if "cat" in args:
            return _proc(json.dumps(body).encode("utf-8"))
        return _proc()
    return run


@pytest.fixture(autouse=True)
def _windows(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    runtime.invalidate()
    yield
    runtime.invalidate()


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(payloads, "cache_root", lambda: str(tmp_path))
    return tmp_path


# ---- the app update that costs nothing ------------------------------------

def test_an_app_update_that_does_not_move_the_runtime_leaves_it_alone():
    """The common case, and the one that must never cost 414 MB."""
    state, _why = runtime.status(runner=_runner(version=runtime.RUNTIME_VERSION),
                                 refresh=True)
    assert state == "ready"


def test_a_ready_runtime_is_never_re_downloaded(cache, monkeypatch):
    """`ensure_cached` is the only thing that can fetch, and a verified cache
    short-circuits it.  The opener raises: reaching the network is the failure."""
    body = b"a pretend runtime image"
    image = replace(runtime.IMAGE, sha256=_sha(body), size=len(body))
    path = payloads.cache_path(image)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pathlib.Path(path).write_bytes(body)

    def explode(*a, **k):
        raise AssertionError("an unchanged runtime must not be downloaded")

    assert payloads.ensure_cached(image, opener=explode) == path


# ---- the app update that does cost, once ----------------------------------

def test_an_older_installed_runtime_is_reported_stale_not_ready():
    """"Install it as necessary" needs the app to KNOW it is out of date."""
    state, why = runtime.status(runner=_runner(version=runtime.RUNTIME_VERSION - 1),
                                refresh=True)
    assert state == "stale"
    assert str(runtime.RUNTIME_VERSION) in why


def test_a_newer_image_does_not_collide_with_the_cached_old_one(cache):
    """A re-cut image lands BESIDE the old one, so a stale 414 MB file can
    never masquerade as the new one - and rolling back is free."""
    old = replace(runtime.IMAGE, sha256="aa" * 32)
    new = replace(runtime.IMAGE, sha256="bb" * 32)
    assert payloads.cache_path(old) != payloads.cache_path(new)
    assert os.path.dirname(payloads.cache_path(old)) == \
        os.path.dirname(payloads.cache_path(new))


def test_a_changed_image_is_a_cache_miss_and_is_fetched(cache):
    """The other side of the promise: when it HAS changed, the user gets it."""
    old_body = b"the previous runtime"
    old = replace(runtime.IMAGE, sha256=_sha(old_body), size=len(old_body))
    p = payloads.cache_path(old)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    pathlib.Path(p).write_bytes(old_body)

    new_body = b"the new runtime"
    new = replace(runtime.IMAGE, sha256=_sha(new_body), size=len(new_body))
    fetched = []

    class _Resp:
        headers = {"Content-Length": str(len(new_body))}

        def read(self, n=-1):
            b, self._done = (new_body if not getattr(self, "_done", False)
                             else b""), True
            return b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(url, timeout=None):
        fetched.append(url)
        return _Resp()

    got = payloads.ensure_cached(new, opener=opener)
    assert fetched, "a changed image must be downloaded"
    assert pathlib.Path(got).read_bytes() == new_body
    assert pathlib.Path(p).exists(), "the old image is kept, not clobbered"


# ---- the destructive edge, which is the one to be careful about -----------

def test_replacing_a_registered_runtime_needs_consent():
    """A runtime version bump means unregister-then-import, which DELETES that
    distro's filesystem - save states included.  The app must refuse to do that
    on its own, so an update can never silently eat something a person made."""
    with pytest.raises(runtime.RuntimeNeedsReplacing):
        runtime.install(runner=_runner(listed=(runtime.DISTRO,)),
                        source=None, replace=False)


def test_the_work_disk_is_not_inside_the_distro():
    """So replacing the runtime cannot take the cards and caches with it."""
    from pinball_decryptor.core import rigdata
    inside = os.path.normcase(runtime.install_dir())
    disk = os.path.normcase(rigdata.disk_path())
    assert not disk.startswith(inside)
