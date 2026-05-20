"""Per-manufacturer detect() tests using synthetic fixtures."""

import pytest

from tests import synthetic
from tests.conftest import HAS_GPG


# ---------------------------------------------------------------------------
# PB - detects from filename prefix AND from internal tar layout.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("game_key", ["abba", "alien", "queen", "predator"])
def test_pb_detect_upd(manufacturers_by_key, tmp_path, game_key):
    pb = manufacturers_by_key["pb"]
    upd = synthetic.make_pb_upd(tmp_path / f"{game_key}.upd",
                                game_key=game_key)
    game = pb.detect(str(upd))
    assert game is not None, f"PB.detect failed on {game_key}.upd"
    assert game.key == game_key


def test_pb_detect_iso_filename(manufacturers_by_key, tmp_path):
    """Clonezilla .iso detection is filename-based (Alien/Queen)."""
    pb = manufacturers_by_key["pb"]
    fake_iso = tmp_path / "alien40_clonezilla.iso"
    fake_iso.write_bytes(b"\x00" * 16)  # ISO file content not inspected here
    game = pb.detect(str(fake_iso))
    assert game is not None and game.key == "alien"


def test_pb_detect_rejects_unrelated(manufacturers_by_key, tmp_path):
    pb = manufacturers_by_key["pb"]
    unrelated = tmp_path / "random.bin"
    unrelated.write_bytes(b"\x00\x01\x02")
    assert pb.detect(str(unrelated)) is None


# ---------------------------------------------------------------------------
# Spooky - per-format detect via filename + magic bytes.
# ---------------------------------------------------------------------------

def test_spooky_detect_ed(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    ed = synthetic.make_spooky_targz(tmp_path / "2025.12.19.ed")
    game = sp.detect(str(ed))
    assert game is not None and game.key == "evil_dead"


def test_spooky_detect_scooby(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    scooby = synthetic.make_spooky_targz(tmp_path / "v2025.12.01.scooby")
    game = sp.detect(str(scooby))
    assert game is not None and game.key == "scooby_doo"


def test_spooky_detect_looney(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    looney = synthetic.make_spooky_plain_tar(tmp_path / "v2025.10.looney")
    game = sp.detect(str(looney))
    assert game is not None and game.key == "legends_of_tera"


def test_spooky_detect_p3_zip(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    # Filename pattern 'Jetsons' triggers detection
    z = synthetic.make_spooky_p3_zip(tmp_path / "Jetsons_Code.zip")
    game = sp.detect(str(z))
    assert game is not None and game.key == "jetsons"


def test_spooky_detect_rm_pkg(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    pkg = synthetic.make_spooky_aes_pkg(
        tmp_path / "rm-gamecode-test.pkg", key_name="rm_pkg")
    game = sp.detect(str(pkg))
    assert game is not None and game.key == "rick_and_morty"


def test_spooky_detect_ac_pkg(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    pkg = synthetic.make_spooky_aes_pkg(
        tmp_path / "ac-gamecode-test.pkg", key_name="ac_pkg")
    game = sp.detect(str(pkg))
    assert game is not None and game.key == "alice_cooper"


def test_spooky_detect_clonezilla_iso_filename(manufacturers_by_key, tmp_path):
    """Clonezilla .iso detection is filename-pattern-based."""
    sp = manufacturers_by_key["spooky"]
    iso = tmp_path / "bj_production_base_image.iso"
    iso.write_bytes(b"\x00" * 16)
    game = sp.detect(str(iso))
    assert game is not None
    assert game.key == "beetlejuice"


# ---------------------------------------------------------------------------
# BOF - detects .fun by filename only (the inner gpg-encrypted bytes
# aren't probed for detect; we don't need gpg available for this test).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected_key", [
    ("lab.fun", "labyrinth"),
    ("dune.fun", "dune"),
    ("winchester.fun", "winchester"),
])
def test_bof_detect_filename(manufacturers_by_key, tmp_path,
                              filename, expected_key):
    bof = manufacturers_by_key["bof"]
    f = tmp_path / filename
    f.write_bytes(b"\x00")
    game = bof.detect(str(f))
    assert game is not None and game.key == expected_key


def test_bof_detect_rejects_unknown_fun(manufacturers_by_key, tmp_path):
    bof = manufacturers_by_key["bof"]
    f = tmp_path / "mystery.fun"
    f.write_bytes(b"\x00")
    assert bof.detect(str(f)) is None


# ---------------------------------------------------------------------------
# JJP - detects .iso by filename prefix.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected_key", [
    ("Wonka-v03.03.iso", "wonka"),
    ("GunsNRoses-v03.03.iso", "guns_n_roses"),
    ("Hobbit-v04.02.iso", "the_hobbit"),
    ("WizardOfOz-v08.02.iso", "wizard_of_oz"),
    ("HarryPotter-v00.76P.iso", "harry_potter"),
])
def test_jjp_detect_iso_filename(manufacturers_by_key, tmp_path,
                                  filename, expected_key):
    jjp = manufacturers_by_key["jjp"]
    iso = tmp_path / filename
    iso.write_bytes(b"\x00")
    game = jjp.detect(str(iso))
    assert game is not None and game.key == expected_key


def test_jjp_detect_rejects_non_iso(manufacturers_by_key, tmp_path):
    jjp = manufacturers_by_key["jjp"]
    other = tmp_path / "Wonka.zip"
    other.write_bytes(b"\x00")
    assert jjp.detect(str(other)) is None


# ---------------------------------------------------------------------------
# CGC - detects .img by filename hint, requires a valid MBR signature.
# ---------------------------------------------------------------------------

def _make_fake_cgc_img(path):
    """Tiny MBR-signed file -- enough for detect() to accept the
    .img as plausibly a disk image without us shipping a real one."""
    blob = bytearray(512)
    blob[510:512] = b"\x55\xaa"
    path.write_bytes(bytes(blob))


@pytest.mark.parametrize("filename,expected_key", [
    ("MedievalMadness300Installer.img", "mm_remake"),
    ("AttackFromMars100Installer.img", "afm_remake"),
    ("MonsterBash103Installer.img", "mb_remake"),
    ("PulpFiction102Installer.img", "pulp_fiction"),
    # Lowercased / spaced variants the hints accept.
    ("medievalmadness_2.5.img", "mm_remake"),
    ("AFM_remake_v1.0.0.img", "afm_remake"),
])
def test_cgc_detect_filename(manufacturers_by_key, tmp_path,
                              filename, expected_key):
    cgc = manufacturers_by_key["cgc"]
    f = tmp_path / filename
    _make_fake_cgc_img(f)
    game = cgc.detect(str(f))
    assert game is not None and game.key == expected_key


def test_cgc_detect_requires_mbr_signature(manufacturers_by_key, tmp_path):
    cgc = manufacturers_by_key["cgc"]
    f = tmp_path / "MedievalMadness300Installer.img"
    # Garbage without the 0x55 0xAA boot signature should not detect.
    f.write_bytes(b"\x00" * 16)
    assert cgc.detect(str(f)) is None


def test_cgc_detect_rejects_unknown_img(manufacturers_by_key, tmp_path):
    cgc = manufacturers_by_key["cgc"]
    f = tmp_path / "SomeRandomGame.img"
    _make_fake_cgc_img(f)
    assert cgc.detect(str(f)) is None


def test_cgc_detect_rejects_non_img_extension(manufacturers_by_key, tmp_path):
    cgc = manufacturers_by_key["cgc"]
    f = tmp_path / "MedievalMadness300Installer.iso"
    _make_fake_cgc_img(f)
    assert cgc.detect(str(f)) is None
