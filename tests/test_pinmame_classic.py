"""Tests for the PinMAME classic-DMD plugin (Data East slice).

The games DB is auto-generated from PinMAME's ``degames.c``; these focus
on the data-driven detection contract (CI-safe, synthetic in-memory zips)
and the capture-primary capability shape.  Extraction is capture-only
(libpinmame), so the actual run is verified in the GUI, not here.
"""

import zipfile

import pytest

from pinball_decryptor.plugins.pinmame_classic.games import GAME_DB


def _make_rom_zip(out_path, game_roms, sound_roms, dmd_roms=()):
    """Minimal MAME-style zip carrying the named ROM files (zero payloads)."""
    with zipfile.ZipFile(out_path, "w") as zf:
        for name in list(game_roms) + list(sound_roms) + list(dmd_roms):
            zf.writestr(name, b"\x00" * 256)
    return out_path


@pytest.fixture(autouse=True)
def _reset_stern_era(manufacturers_by_key):
    """Stern's era is mutable instance state on a session-shared object; reset
    it after each test so a whitestar-era test can't leak into the Spike-2
    capability tests (especially under test randomisation)."""
    yield
    s = manufacturers_by_key.get("stern")
    if s is not None and hasattr(s, "set_era"):
        s.set_era("")


# ---------------------------------------------------------------------------
# Registration / catalogue
# ---------------------------------------------------------------------------

def test_data_east_registered(manufacturers_by_key):
    assert "data_east" in manufacturers_by_key
    de = manufacturers_by_key["data_east"]
    assert de.display == "Data East"
    # Only the Data-East-branded titles are exposed (not the Sega-on-DE ones).
    assert de.games, "Data East exposes no games"
    assert all(g.manufacturer_key == "data_east" for g in de.games)


def test_data_east_excludes_sega_titles(manufacturers_by_key):
    de = manufacturers_by_key["data_east"]
    de_keys = {g.key for g in de.games}
    sega_keys = {k for k, v in GAME_DB.items() if v["manufacturer"] == "Sega"}
    assert sega_keys, "fixture expects Sega-branded titles in the shared DB"
    assert not (de_keys & sega_keys)


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------

_DE_KEYS = ["lethal_weapon_3", "jurassic_park", "tales_from_the_crypt",
            "hook", "guns_n_roses", "star_trek_25th_anniversary"]


@pytest.mark.parametrize("game_key", _DE_KEYS)
def test_data_east_detect_full_romset(manufacturers_by_key, tmp_path, game_key):
    de = manufacturers_by_key["data_east"]
    info = GAME_DB[game_key]
    z = _make_rom_zip(tmp_path / f"{info['family']}.zip",
                      info["game_roms"], info["sound_roms"],
                      dmd_roms=info["dmd_roms"])
    game = de.detect(str(z))
    assert game is not None, f"detect failed for {game_key}"
    assert game.key == game_key
    assert game.manufacturer_key == "data_east"


def test_data_east_detect_by_filename_hint(manufacturers_by_key, tmp_path):
    """A revision clone whose CPU ROM we haven't catalogued is still caught
    by the family-name hint + the (stable) sound ROMs — mirrors the real
    ``btmn_106``/``wwfr_103`` zips."""
    de = manufacturers_by_key["data_east"]
    info = GAME_DB["batman"]
    # Only the sound ROMs (stable across revisions) + a made-up CPU rom,
    # in a zip named for a revision we don't catalogue.
    z = _make_rom_zip(tmp_path / f"{info['family']}_999.zip",
                      ["made_up_cpu.999"], info["sound_roms"])
    game = de.detect(str(z))
    assert game is not None and game.key == "batman"


def test_data_east_rejects_unrelated(manufacturers_by_key, tmp_path):
    de = manufacturers_by_key["data_east"]
    z = tmp_path / "random.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("unrelated.bin", b"\x00" * 64)
    assert de.detect(str(z)) is None


def test_data_east_rejects_non_zip(manufacturers_by_key, tmp_path):
    de = manufacturers_by_key["data_east"]
    p = tmp_path / "not_a_zip.bin"
    p.write_bytes(b"\x00" * 64)
    assert de.detect(str(p)) is None


# ---------------------------------------------------------------------------
# Sega (Whitestar + the Sega-on-DE-hardware titles)
# ---------------------------------------------------------------------------

_SEGA_KEYS = ["apollo_13", "goldeneye", "twister", "x_files", "godzilla",
              "star_wars_trilogy_special_edition", "south_park",
              "maverick_the_movie"]


def test_sega_registered_capture_primary(manufacturers_by_key):
    sega = manufacturers_by_key["sega"]
    assert sega.display == "Sega"
    assert sega.capabilities.capture and not sega.capabilities.extract
    assert sega.games and all(g.manufacturer_key == "sega" for g in sega.games)


def test_sega_and_data_east_are_disjoint(manufacturers_by_key):
    de_keys = {g.key for g in manufacturers_by_key["data_east"].games}
    sega_keys = {g.key for g in manufacturers_by_key["sega"].games}
    assert de_keys and sega_keys
    assert not (de_keys & sega_keys)
    # Stern-Whitestar titles are catalogued but NOT exposed by either brand.
    assert any(v["manufacturer"] == "Stern" for v in GAME_DB.values())


@pytest.mark.parametrize("game_key", _SEGA_KEYS)
def test_sega_detect_full_romset(manufacturers_by_key, tmp_path, game_key):
    sega = manufacturers_by_key["sega"]
    info = GAME_DB[game_key]
    z = _make_rom_zip(tmp_path / f"{info['family']}.zip",
                      info["game_roms"], info["sound_roms"],
                      dmd_roms=info["dmd_roms"])
    game = sega.detect(str(z))
    assert game is not None, f"detect failed for {game_key}"
    assert game.key == game_key
    assert game.manufacturer_key == "sega"


# ---------------------------------------------------------------------------
# Capture-primary shape + pipeline construction (a real run needs
# libpinmame + ROMs; verified in the GUI).
# ---------------------------------------------------------------------------

def test_data_east_is_capture_primary(manufacturers_by_key):
    de = manufacturers_by_key["data_east"]
    # Capture-only: no static-decode path (the GUI keys its capture-primary
    # treatment on capture=True + extract=False).
    assert de.capabilities.capture
    assert not de.capabilities.extract
    assert de.capture_phases


def test_data_east_capture_pipeline_constructs(manufacturers_by_key, tmp_path):
    de = manufacturers_by_key["data_east"]
    pipe = de.make_capture_pipeline(
        str(tmp_path / "lw3_208.zip"), str(tmp_path),
        lambda *a, **k: None, lambda *a: None,
        lambda *a, **k: None, lambda *a: None,
        duration_seconds=30)
    assert pipe is not None
    # Attract-mode is forced (no WPC switch maps for DE).
    assert pipe.simulate_gameplay is False


# ---------------------------------------------------------------------------
# Stern era-switching: one picker entry, two eras (Spike 2 SD-card vs
# Whitestar MAME capture).  The era reset fixture above keeps the shared
# instance's mutable era from leaking.
# ---------------------------------------------------------------------------

def _a_whitestar_key():
    return next(k for k, v in GAME_DB.items() if v["manufacturer"] == "Stern")


def test_stern_default_era_is_spike2(manufacturers_by_key):
    s = manufacturers_by_key["stern"]
    s.set_era("")                       # default
    assert s._era == "spike2"
    # Full Spike-2 surface by default — the shipped flow is unchanged.
    assert s.capabilities.extract and s.capabilities.write
    assert not s.capabilities.capture
    # Both input families are accepted.
    assert ".zip" in s.input_spec.extensions
    assert ".img" in s.input_spec.extensions


def test_stern_detects_whitestar_zip_with_era(manufacturers_by_key, tmp_path):
    s = manufacturers_by_key["stern"]
    info = GAME_DB[_a_whitestar_key()]
    z = _make_rom_zip(tmp_path / f"{info['family']}.zip",
                      info["game_roms"], info["sound_roms"],
                      dmd_roms=info["dmd_roms"])
    game = s.detect(str(z))
    assert game is not None
    assert game.manufacturer_key == "stern"
    assert game.era == "whitestar"


def test_stern_input_label_is_era_aware(manufacturers_by_key):
    # The input medium differs by era, so the field-label noun can't be a fixed
    # "Card image": Spike 2 loads an SD-card image, Whitestar a MAME ROM zip.
    s = manufacturers_by_key["stern"]
    s.set_era("spike2")
    assert s.extract_input_label == "Card image"
    s.set_era("whitestar")
    assert s.extract_input_label == "ROM zip"
    s.set_era("")  # restore default


def test_stern_era_switch_flips_capabilities(manufacturers_by_key):
    s = manufacturers_by_key["stern"]
    s.set_era("whitestar")
    # Whitestar = capture-only (no write/replace/Direct-SD on a MAME ROM).
    assert s.capabilities.capture
    assert not s.capabilities.extract and not s.capabilities.write
    assert s.extract_phases == s.capture_phases
    s.set_era("")
    assert s.capabilities.write          # back to Spike 2


def test_stern_whitestar_capture_pipeline_constructs(manufacturers_by_key,
                                                     tmp_path):
    s = manufacturers_by_key["stern"]
    pipe = s.make_capture_pipeline(
        str(tmp_path / "monopoly.zip"), str(tmp_path),
        lambda *a, **k: None, lambda *a: None,
        lambda *a, **k: None, lambda *a: None,
        duration_seconds=30)
    assert pipe is not None and pipe.simulate_gameplay is False
