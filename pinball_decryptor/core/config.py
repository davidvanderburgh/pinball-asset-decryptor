"""Core configuration shared across all manufacturer plugins."""

import os
import sys

# Pipeline phase names — uniform across plugins for v1.  Plugins emit
# different log messages within these phases but share the 4-step shape.
EXTRACT_PHASES = ["Detect", "Extract", "Checksums", "Cleanup"]
WRITE_PHASES = ["Detect", "Scan", "Repack", "Cleanup"]

# GitHub repo for the unified app's auto-update check.
GITHUB_REPO = "davidvanderburgh/pinball-asset-decryptor"

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
