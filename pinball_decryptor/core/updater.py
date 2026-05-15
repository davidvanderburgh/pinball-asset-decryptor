"""Auto-update checker — checks the GitHub releases API on startup."""

import json
import urllib.request

from .config import GITHUB_REPO

REQUEST_TIMEOUT = 5


def _parse_version(version_str):
    v = version_str.strip().lstrip("v")
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return ()


def check_for_update(current_version, repo=None):
    """Return (latest_version, download_url, notes) if newer, else None."""
    target_repo = repo or GITHUB_REPO
    url = f"https://api.github.com/repos/{target_repo}/releases/latest"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "Pinball-Asset-Decryptor-UpdateCheck",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())

        tag = data.get("tag_name", "")
        html_url = data.get("html_url", "")
        if not tag or not html_url:
            return None

        latest = _parse_version(tag)
        current = _parse_version(current_version)
        if latest and current and latest > current:
            return (tag.lstrip("v"), html_url, data.get("body", "") or "")
    except Exception:
        pass

    return None
