"""Unit tests for BOF update-version date handling.

The game only applies a .fun whose version date (line 2 of the embedded
``updated_bash_profile`` / ``updated_updatecode``) is newer than what's
installed.  These cover the pure host-side helpers the GUI and Write
pipeline share: parsing the date and computing the next one (climbing past
the stock baseline and the per-folder ``.bof_modversion`` marker).
"""

import datetime

import pytest

from pinball_decryptor.plugins.bof.pipeline import (
    MODVERSION_FILE, parse_update_date, peek_next_update_version)


def _write_version_files(folder, bash_date="2025.06.23",
                         code_date="2025.06.20"):
    marker = "# Update check string - Godot Code looks for the date\n"
    (folder / "updated_bash_profile").write_text(
        marker + f"# {bash_date} \n# rest\n", encoding="utf-8")
    (folder / "updated_updatecode").write_text(
        marker + f"# {code_date} \nimport os\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# parse_update_date
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("# 2025.06.23 ", datetime.date(2025, 6, 23)),
    ("2026.01.15", datetime.date(2026, 1, 15)),
    ("# 2025.12.31\n", datetime.date(2025, 12, 31)),
])
def test_parse_update_date_valid(text, expected):
    assert parse_update_date(text) == expected


@pytest.mark.parametrize("text", [
    "", None, "no date here", "# 2025.13.40 ", "1999.06.23", "garbage"])
def test_parse_update_date_invalid(text):
    assert parse_update_date(text) is None


# ---------------------------------------------------------------------------
# peek_next_update_version
# ---------------------------------------------------------------------------

def test_peek_uses_highest_embedded_date(tmp_path):
    """Baseline = max across the two files; next = baseline + 1 day."""
    _write_version_files(tmp_path, bash_date="2025.06.23",
                         code_date="2025.06.20")
    baseline, next_str = peek_next_update_version(str(tmp_path))
    assert baseline == datetime.date(2025, 6, 23)
    assert next_str == "2025.06.24"


def test_peek_climbs_past_marker(tmp_path):
    """An existing .bof_modversion marker pushes the next date past it."""
    _write_version_files(tmp_path)
    (tmp_path / MODVERSION_FILE).write_text("2025.06.27\n", encoding="utf-8")
    baseline, next_str = peek_next_update_version(str(tmp_path))
    assert baseline == datetime.date(2025, 6, 23)
    assert next_str == "2025.06.28"  # one past the marker, not the baseline


def test_peek_marker_below_baseline_ignored(tmp_path):
    """A stale marker older than the baseline doesn't drag the date down."""
    _write_version_files(tmp_path, bash_date="2025.06.23")
    (tmp_path / MODVERSION_FILE).write_text("2025.01.01\n", encoding="utf-8")
    _, next_str = peek_next_update_version(str(tmp_path))
    assert next_str == "2025.06.24"


def test_peek_month_boundary(tmp_path):
    _write_version_files(tmp_path, bash_date="2025.06.30",
                         code_date="2025.06.30")
    _, next_str = peek_next_update_version(str(tmp_path))
    assert next_str == "2025.07.01"


def test_peek_returns_none_when_no_version_files(tmp_path):
    (tmp_path / "some_other_file.txt").write_text("hi", encoding="utf-8")
    assert peek_next_update_version(str(tmp_path)) == (None, None)
