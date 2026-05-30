"""Plugin loading + manufacturer contract tests.

These don't touch any pipelines or files — they just verify that each
plugin advertises a sane shape, so a refactor that breaks the
Manufacturer contract fails CI immediately.
"""

import pytest

from pinball_decryptor.core.registry import (Capabilities, Game, InputSpec,
                                              Manufacturer, Prerequisite)


EXPECTED_KEYS = {"ap", "pb", "spooky", "bof", "jjp", "cgc", "williams"}


def test_all_expected_manufacturers_loaded(manufacturers_by_key):
    assert set(manufacturers_by_key.keys()) == EXPECTED_KEYS


def test_manufacturers_sorted_alphabetically(all_manufacturers):
    names = [m.display for m in all_manufacturers]
    assert names == sorted(names, key=str.lower)


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_manufacturer_basic_shape(manufacturers_by_key, key):
    mfr = manufacturers_by_key[key]
    assert isinstance(mfr, Manufacturer)
    assert mfr.key == key
    assert mfr.display, f"{key} missing display name"
    assert isinstance(mfr.capabilities, Capabilities)
    assert isinstance(mfr.input_spec, InputSpec)
    assert mfr.input_spec.extensions, f"{key} has no input extensions"
    assert mfr.games, f"{key} has no games"
    assert all(isinstance(g, Game) for g in mfr.games)


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_manufacturer_phases_are_strings(manufacturers_by_key, key):
    mfr = manufacturers_by_key[key]
    assert all(isinstance(p, str) and p for p in mfr.extract_phases)
    assert all(isinstance(p, str) and p for p in mfr.write_phases)


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_manufacturer_prereqs_shape(manufacturers_by_key, key):
    mfr = manufacturers_by_key[key]
    for p in mfr.prerequisites:
        assert isinstance(p, Prerequisite)
        assert p.name and p.probe and p.reason
        assert p.where in ("host", "wsl"), \
            f"{key}.{p.name}.where = {p.where!r}"


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_games_have_manufacturer_back_reference(manufacturers_by_key, key):
    mfr = manufacturers_by_key[key]
    for g in mfr.games:
        assert g.manufacturer_key == key, \
            f"{key}: game {g.key!r} claims mfr {g.manufacturer_key!r}"


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_games_have_display_names(manufacturers_by_key, key):
    mfr = manufacturers_by_key[key]
    for g in mfr.games:
        assert g.display, f"{key}: game {g.key!r} has no display name"


def test_spooky_marks_tna_unsupported(manufacturers_by_key):
    """Total Nuclear Annihilation is encrypted with an unknown AES key."""
    spooky = manufacturers_by_key["spooky"]
    tna = next((g for g in spooky.games if g.key == "total_nuclear"), None)
    assert tna is not None
    assert not tna.supported
    assert tna.unsupported_reason


def test_only_known_unsupported_games_exist(all_manufacturers):
    """Catch-all: if a new game is marked unsupported, the test
    author has to update this list explicitly — prevents accidental
    UI regressions where every game suddenly shows as unsupported."""
    expected_unsupported = {("spooky", "total_nuclear")}
    actual_unsupported = {
        (m.key, g.key)
        for m in all_manufacturers
        for g in m.games if not g.supported}
    assert actual_unsupported == expected_unsupported


# ---------------------------------------------------------------------------
# Capability factory smoke tests — just verify make_*_pipeline doesn't
# crash on construction.  We don't run() the pipelines here; that's
# what the per-mfr E2E tests do.
# ---------------------------------------------------------------------------

def _noop_cb(*args, **kwargs):
    pass


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_make_extract_pipeline_constructs(manufacturers_by_key, key, tmp_path):
    mfr = manufacturers_by_key[key]
    if not mfr.capabilities.extract:
        pytest.skip(f"{key} has no extract capability")
    # Use any plausible path — the factory shouldn't probe the file
    fake_input = tmp_path / f"fake{mfr.input_spec.extensions[0]}"
    fake_input.write_bytes(b"\x00")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    p = mfr.make_extract_pipeline(
        str(fake_input), str(out_dir),
        _noop_cb, _noop_cb, _noop_cb, _noop_cb)
    assert p is not None


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_make_write_pipeline_constructs(manufacturers_by_key, key, tmp_path):
    mfr = manufacturers_by_key[key]
    if not mfr.capabilities.write:
        pytest.skip(f"{key} has no write capability")
    fake_original = tmp_path / f"orig{mfr.input_spec.extensions[0]}"
    fake_original.write_bytes(b"\x00")
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    output = tmp_path / f"out{mfr.input_spec.extensions[0]}"
    p = mfr.make_write_pipeline(
        str(fake_original), str(assets_dir), str(output),
        _noop_cb, _noop_cb, _noop_cb, _noop_cb)
    assert p is not None
