"""Auto-update checker for JJP Asset Decryptor.

Checks the GitHub releases API for newer versions on startup.
Uses only the standard library (urllib, json). All errors are
silently swallowed — update checks must never interfere with
normal operation.
"""

import json
import urllib.request

GITHUB_REPO = "davidvanderburgh/jjp-decryptor"
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
                     "User-Agent": "JJP-Asset-Decryptor-UpdateCheck"},
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
