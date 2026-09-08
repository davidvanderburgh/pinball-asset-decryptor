"""Which GitHub release the update check compares against (PAD-116).

A tester on v0.191.0 was never offered v0.192.0.  Nothing was wrong with
either release: the app asked GitHub for ``/releases/latest``, which
answers "the most recently PUBLISHED release" — and the most recent one
was ``runtime-1``, the Linux image the emulator rigs run on.  Its tag
parses to no version at all, so the "is it newer?" comparison could never
fire and every installed copy silently concluded it was up to date.

Two halves, both pinned here:

  * the app reads the release LIST and picks the newest release whose tag
    is a version, so an asset holder in the top slot is simply skipped;
  * the workflows that publish those asset holders mark them prerelease,
    which is what keeps them out of ``/releases/latest`` — the copies of
    the app already in the field will never have the fix above and are
    still asking the old question.
"""

import io
import json
from pathlib import Path

import pytest

from pinball_decryptor.core import net, updater

REPO = Path(__file__).resolve().parent.parent

# The real asset names CI uploads — _release_ready gates on them, so a
# fixture release without them is withheld for a different reason.
ASSETS = [
    {"name": "Pinball_Asset_Decryptor_v0.192.0_macOS_AppleSilicon.dmg",
     "browser_download_url": "https://example.com/mac_arm.dmg"},
    {"name": "Pinball_Asset_Decryptor_v0.192.0_macOS_Intel.dmg",
     "browser_download_url": "https://example.com/mac_intel.dmg"},
    {"name": "Pinball_Asset_Decryptor_v0.192.0_Windows.exe",
     "browser_download_url": "https://example.com/win.exe"},
    {"name": "Pinball_Asset_Decryptor_v0.192.0_Linux_x86_64.AppImage",
     "browser_download_url": "https://example.com/linux"},
]


def _release(tag, **kw):
    data = {"tag_name": tag,
            "html_url": "https://example.com/%s" % tag,
            "body": "notes",
            "assets": list(ASSETS)}
    data.update(kw)
    return data


#: The repo as it actually stood the day the ticket came in: the runtime
#: image published after the app release it shadowed.  Newest first, which
#: is the order the API returns.
FEED_AS_IT_WAS = [
    _release("runtime-1", body="The Linux the emulator rigs run on.",
             assets=[{"name": "pad-runtime-base.tar.gz",
                      "browser_download_url": "https://example.com/rt"}]),
    _release("v0.192.0"),
    _release("payloads-1", body="Binaries the app installs.",
             assets=[{"name": "qemu-arm",
                      "browser_download_url": "https://example.com/q"}]),
    _release("v0.191.0"),
]


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _feed(monkeypatch, releases):
    """Serve *releases* as the /releases page; return the URLs asked for."""
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        return _FakeResp(json.dumps(releases).encode())

    monkeypatch.setattr(net, "urlopen", fake_urlopen)
    return calls


# --------------------------------------------------------------- the app --

def test_an_image_release_in_the_top_slot_does_not_hide_the_app(monkeypatch):
    """Sam's report, exactly: v0.191.0 with v0.192.0 released and runtime-1
    published on top of it."""
    calls = _feed(monkeypatch, FEED_AS_IT_WAS)
    result = updater.check_for_update("0.191.0")
    assert result, "the released v0.192.0 must still be found"
    version, url, _notes, _installer = result
    assert version == "0.192.0"
    assert url == "https://example.com/v0.192.0"
    # And it must be asking for the feed, not for the one release GitHub
    # calls latest — that question cannot be answered correctly.
    assert calls and "/releases?" in calls[0]
    assert "/releases/latest" not in calls[0]


def test_the_newest_version_wins_whatever_order_the_feed_is_in(monkeypatch):
    """Ordering is created-at (the TAG's commit date), so it is not a
    reliable stand-in for "newest version" — the version is."""
    _feed(monkeypatch, [_release("v0.190.0"), _release("v0.192.0"),
                        _release("v0.191.0")])
    assert updater.check_for_update("0.191.0")[0] == "0.192.0"


def test_a_page_with_no_app_release_is_simply_no_update(monkeypatch):
    _feed(monkeypatch, [_release("runtime-1"), _release("payloads-1")])
    assert updater.check_for_update("0.191.0") is None


def test_drafts_and_prereleases_are_not_offered(monkeypatch):
    """/releases lists both; /releases/latest did not, and users should not
    start seeing banners for releases that were never announced."""
    _feed(monkeypatch, [_release("v0.193.0", draft=True),
                        _release("v0.194.0", prerelease=True),
                        _release("v0.192.0")])
    assert updater.check_for_update("0.191.0")[0] == "0.192.0"


def test_the_readiness_gate_still_applies_to_the_release_it_picks(
        monkeypatch):
    """A version whose installers are still uploading is withheld, and named
    to the caller, exactly as before — the gate now runs against the release
    the feed search chose."""
    withheld = []
    _feed(monkeypatch, [_release("runtime-1"),
                        _release("v0.192.0", assets=[])])
    assert updater.check_for_update(
        "0.191.0", not_ready_cb=withheld.append) is None
    assert withheld == ["0.192.0"]


def test_a_body_that_is_not_the_feed_is_an_error_not_up_to_date(monkeypatch):
    """"Couldn't check" is true; "no update" would be the same false
    reassurance this ticket is about, so the caller must get the raise."""
    _feed(monkeypatch, {"message": "API rate limit exceeded"})
    with pytest.raises(ValueError):
        updater.check_for_update("0.191.0")


def test_the_running_version_is_still_the_floor(monkeypatch):
    _feed(monkeypatch, FEED_AS_IT_WAS)
    assert updater.check_for_update("0.192.0") is None
    assert updater.check_for_update("1.0.0") is None


# ---------------------------------------------------------- the workflows --

@pytest.mark.parametrize("workflow", ["runtime.yml", "payloads.yml"])
def test_asset_holder_releases_are_marked_prerelease(workflow):
    """The half of the fix that reaches copies of the app that will never
    get the other half: every v0.192.0-and-older install in the field is
    still asking GitHub for "the latest release", and these two workflows
    are the only things that put a non-app release in that slot.

    It has to be ``--prerelease``.  ``--latest=false`` reads like the right
    flag and is not: it only un-pins the release, and GitHub then recomputes
    its latest one by creation date and lands straight back on the release
    you just un-pinned — checked against the live API on runtime-1, which
    stayed "Latest" through both `gh release edit --latest=false` and a raw
    `PATCH make_latest=false`.  ``/releases/latest`` is documented as the
    most recent NON-PRERELEASE, non-draft release, so that is the flag that
    actually excludes one.
    """
    wf = (REPO / ".github" / "workflows" / workflow).read_text(
        encoding="utf-8")
    publish = wf.split("- name: Publish", 1)[1]
    assert "gh release create" in publish
    for line in publish.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "gh release create" in line:
            assert "--prerelease" in line, (
                "%s creates its release without --prerelease" % workflow)
        assert "--latest=false" not in line, (
            "%s uses --latest=false, which does not demote anything"
            % workflow)
    # ...and a tag created before we knew this gets corrected on a re-run.
    assert "gh release edit" in publish and "--prerelease" in publish
