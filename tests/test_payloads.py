"""The pinned payloads: binaries we build in CI instead of on a user's machine.

Background: the Spike 1 emulator compiled itself on first Start, and that build
broke in the field twice in eight days on distro changes that had nothing to do
with the app (glibc 2.41's sched_attr, then a Python 3.14 with no ensurepip).
core/payloads.py replaces the build with a download of the exact bytes we
tested, identified by SHA-256.

So the thing these tests are really guarding is the promise "what runs on their
machine is what we verified on ours": a payload that installs without matching
its hash, a cached file that is trusted because it exists, or a hash the app
believes but nothing builds, would each break it quietly.
"""
import hashlib
import io
import os
import pathlib
import re

import pytest

from pinball_decryptor.core import payloads

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "payloads.yml"
PREREQS = REPO / "tools" / "spike1_emu" / "prereqs.sh"

BODY = b"the exact bytes we built" * 100
SHA = hashlib.sha256(BODY).hexdigest()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A cache dir of this test's own — never the user's real one."""
    monkeypatch.setenv("PAD_PAYLOAD_DIR", str(tmp_path / "cache"))
    return tmp_path


@pytest.fixture
def sample(tmp_path):
    return payloads.Payload(
        key="test-thing", filename="thing", release_tag="payloads-9",
        sha256=SHA, size=len(BODY), version="thing 1.0",
        what="a thing", dest=str(tmp_path / "installed" / "thing"),
        source_sha256="ab" * 32)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _opener(body=BODY, fail=None):
    def open_(req, timeout=None):
        if fail:
            raise fail
        return _FakeResponse(body)
    return open_


# ------------------------------------------------------------- the address --

def test_the_asset_url_never_goes_through_the_api(sample):
    """Unauthenticated api.github.com allows 60 requests an hour per IP, which
    a shared office address can exhaust without this user doing anything - the
    app has already met that 403 once.  A release asset URL built from the tag
    has no such limit and no JSON to parse."""
    url = payloads.asset_url(sample, repo="owner/repo")
    assert url == ("https://github.com/owner/repo/releases/download/"
                   "payloads-9/thing")
    assert "api.github.com" not in url


def test_a_payload_is_cached_under_its_hash(sample, cache):
    """A re-cut payload lands BESIDE the old one, never on top of it, so a
    stale file cannot pass itself off as the new build and rolling back is
    deleting a file rather than fetching the previous one again."""
    path = payloads.cache_path(sample)
    assert SHA[:12] in os.path.basename(path)
    other = payloads.cache_path(payloads.Payload(
        key="k", filename="thing", release_tag="payloads-9",
        sha256="f" * 64, size=1, version="v", what="w", dest="~/x"))
    assert path != other


# ------------------------------------------------------------ verification --

def test_verify_answers_why_not(sample, cache, tmp_path):
    f = tmp_path / "thing"
    assert payloads.verify(str(f), sample) == (False, "not downloaded yet")

    f.write_bytes(b"<html>403 Forbidden</html>")
    ok, why = payloads.verify(str(f), sample)
    assert not ok and "wrong size" in why

    f.write_bytes(b"x" * len(BODY))
    ok, why = payloads.verify(str(f), sample)
    assert not ok and "checksum" in why

    f.write_bytes(BODY)
    assert payloads.verify(str(f), sample) == (True, "")


# --------------------------------------------------------------- the fetch --

def test_a_download_that_verifies_is_kept(sample, cache):
    path = payloads.download(sample, opener=_opener())
    assert pathlib.Path(path).read_bytes() == BODY
    assert not os.path.exists(path + ".part")


def test_a_download_that_does_not_verify_leaves_nothing(sample, cache):
    """The antivirus / captive-portal / truncated-transfer case.  Half a
    binary that is never renamed cannot be mistaken for the real one by the
    next run - which is the entire reason for the .part file."""
    with pytest.raises(RuntimeError) as exc:
        payloads.download(sample, opener=_opener(body=b"not what we built"))
    assert "Install from file" in str(exc.value)
    assert not os.path.exists(payloads.cache_path(sample))
    assert not os.path.exists(payloads.cache_path(sample) + ".part")


def test_a_blocked_download_names_the_hosts_to_allow(sample, cache):
    """A corporate proxy that allows github.com and blocks the asset host is
    the common shape, so the message names both rather than saying "failed"."""
    with pytest.raises(RuntimeError) as exc:
        payloads.download(sample, opener=_opener(fail=OSError("refused")))
    msg = str(exc.value)
    assert "github.com" in msg and "objects.githubusercontent.com" in msg
    assert "Install from file" in msg


def test_a_corrupt_cache_is_replaced_rather_than_trusted(sample, cache):
    """Self-healing: a machine that slept mid-download costs one retry, not a
    support thread."""
    path = payloads.cache_path(sample)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(BODY[:10])
    logged = []
    got = payloads.ensure_cached(sample, log=logged.append, opener=_opener())
    assert pathlib.Path(got).read_bytes() == BODY
    assert any("not what we built" in m for m in logged)


def test_a_good_cache_is_not_downloaded_again(sample, cache):
    payloads.download(sample, opener=_opener())
    payloads.ensure_cached(sample, opener=_opener(fail=AssertionError("fetched")))


# ------------------------------------------------------------ the install --

def test_install_refuses_anything_that_is_not_what_we_built(sample, cache):
    path = payloads.cache_path(sample)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"tampered")
    with pytest.raises(RuntimeError) as exc:
        payloads.install(sample, installer=lambda p, s: None)
    assert "refusing to install" in str(exc.value)


def test_install_from_file_holds_a_hand_delivered_file_to_the_same_hash(
        sample, cache, tmp_path):
    """The air-gapped path is a different DELIVERY, not a lower standard."""
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.write_bytes(BODY)
    bad.write_bytes(b"something else entirely")
    seen = []
    payloads.install_from_file(sample, str(good),
                               installer=lambda p, s: seen.append(s))
    assert seen
    with pytest.raises(RuntimeError):
        payloads.install_from_file(sample, str(bad),
                                   installer=lambda p, s: None)


def test_installing_locally_writes_the_binary_and_its_stamp(sample, cache):
    payloads.download(sample, opener=_opener())
    payloads.install(sample, installer=payloads._install_locally)
    dest = pathlib.Path(sample.dest)
    assert dest.read_bytes() == BODY
    stamp = dest.with_name(dest.name + payloads.STAMP_SUFFIX)
    assert "source_sha256=%s" % sample.source_sha256 in stamp.read_text()


def test_only_missing_and_published_payloads_are_installed(sample, cache,
                                                           monkeypatch):
    """An unpinned payload (no hash yet) is not ours to supply, and a payload
    already on the machine is not fetched again - so `ensure` on a healthy
    machine is silent and free."""
    unpinned = payloads.Payload(
        key="not-cut-yet", filename="x", release_tag="payloads-9",
        sha256="", size=0, version="v", what="w", dest="~/x")
    monkeypatch.setattr(payloads, "PAYLOADS",
                        {"test-thing": sample, "not-cut-yet": unpinned})
    assert [p.key for p in payloads.missing(prober=lambda p: False)] \
        == ["test-thing"]
    assert payloads.missing(prober=lambda p: True) == []

    installed = payloads.ensure(prober=lambda p: False,
                                installer=lambda p, s: None,
                                opener=_opener())
    assert installed == ["test-thing"]


# ------------------------------------------------- the registry and the CI --

def test_every_pinned_payload_is_one_the_workflow_actually_builds():
    """A hash in the app that nothing in CI produces is a payload no user can
    ever install; a file CI publishes that the app does not know is dead
    weight.  Held together here because they are edited in different files
    weeks apart."""
    wf = WORKFLOW.read_text(encoding="utf-8")
    published = set(re.findall(r"out/([A-Za-z0-9._-]+)", wf))
    for p in payloads.PAYLOADS.values():
        assert p.filename in published, (
            "%s is pinned in the app but payloads.yml never uploads it"
            % p.filename)


def test_the_registry_is_internally_consistent():
    keys = list(payloads.PAYLOADS)
    assert len(keys) == len(set(keys))
    for key, p in payloads.PAYLOADS.items():
        assert p.key == key
        assert p.dest.startswith("~/") or p.dest.startswith("/"), p.dest
        assert p.what and p.version
        # A hash without a size, or a size without a hash, is half a pin.
        assert bool(p.sha256) == bool(p.size), p.key


def test_the_app_and_the_rig_spell_the_stamp_the_same_way():
    """The app writes the stamp and the rig reads it (s1_build_groups), which
    is exactly the shape this rig's oldest rule is about: never let two
    scripts define the same fact."""
    src = PREREQS.read_text(encoding="utf-8")
    m = re.search(r'S1_PAYLOAD_STAMP_SUFFIX="([^"]+)"', src)
    assert m, "the rig no longer names the stamp suffix"
    assert m.group(1) == payloads.STAMP_SUFFIX
    assert "source_sha256=" in src, (
        "the rig reads a field the app no longer writes")
