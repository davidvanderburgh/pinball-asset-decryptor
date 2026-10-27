"""Core configuration shared across all manufacturer plugins."""

import os
import sys

# Pipeline phase names — uniform across plugins for v1.  Plugins emit
# different log messages within these phases but share the 4-step shape.
EXTRACT_PHASES = ["Detect", "Extract", "Checksums", "Cleanup"]
WRITE_PHASES = ["Detect", "Scan", "Repack", "Cleanup"]

# GitHub repo for the unified app's auto-update check.
GITHUB_REPO = "davidvanderburgh/pinball-asset-decryptor"

# The animal shelter donations total (PAD-754, core/donations.py): the
# Cloudflare Worker in tools/donations_worker.  PAD_DONATIONS_URL points the
# app elsewhere (tests, a staging copy); empty disables the network side and
# the paw chip shows no total.  The key ships in the app and only keeps
# casual scripts out (the Worker's rate limit does the real work).
DONATIONS_URL = os.environ.get(
    "PAD_DONATIONS_URL",
    "https://pad-donations.davidvanderburgh.workers.dev")
DONATIONS_APP_KEY = "pad-shelters-2026"

# Application name used for settings directory + window title.
APP_NAME = "Pinball Asset Decryptor"
_SETTINGS_NAMESPACE = "pinball_decryptor"


def _settings_root():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get(
            "XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, _SETTINGS_NAMESPACE)


SETTINGS_FILE = os.path.join(_settings_root(), "settings.json")
