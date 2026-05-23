"""Vestigial update-checker stub for the JJP plugin.

The unified app polls its own release feed via
:mod:`pinball_decryptor.core.updater` against
``davidvanderburgh/pinball-asset-decryptor``.  This file remains
because it was lifted verbatim from the upstream standalone
``jjp-decryptor`` and a few historical imports still reference it;
it is no longer the active updater.

If you find yourself reaching for this module to add an update
prompt, prefer the core updater — pointing at the deprecated
``jjp-decryptor`` GitHub repo would now show users a release older
than the unified app they're already running.
"""

import json
import urllib.request

# Point at the unified app's release feed so any code that does
# still call this gets sensible results instead of stale data from
# the deprecated standalone repo.
GITHUB_REPO = "davidvanderburgh/pinball-asset-decryptor"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
REQUEST_TIMEOUT = 5  # seconds


def _parse_version(version_str):
    """Parse a version string like '1.2.3' or 'v1.2.3' into a tuple of ints."""
    v = version_str.strip().lstrip("v")
    return tuple(int(x) for x in v.split("."))


def check_for_update(current_version):
    """Check GitHub for a newer release.

    Returns (latest_version, download_url) if an update is available,
    or None if already up to date or on any error.
    """
    try:
        req = urllib.request.Request(
            RELEASES_URL,
            headers={"Accept": "application/vnd.github.v3+json",
                     "User-Agent": "Pinball-Asset-Decryptor-UpdateCheck"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())

        tag = data.get("tag_name", "")
        html_url = data.get("html_url", "")

        if not tag or not html_url:
            return None

        latest = _parse_version(tag)
        current = _parse_version(current_version)

        if latest > current:
            return (tag.lstrip("v"), html_url)
    except Exception:
        pass

    return None
