"""PAD-1277: a Spike 3 port beside a Spike 2 port of one build (Star Wars ELG 1.10 ships for both).

The Spike 3 port lives in the shipped ports' ``spike3`` folder under the same ``<game>-<version>.port``
name; that folder is what says it is for Spike 3 (mode_runtime.port_arch). Every lookup by build asks
for one machine, and a Spike 3 profile has a key, label and emulator-proof tables of its own.

The Spike 3 port here is a copy of the shipped Spike 2 Star Wars ELG 1.10 port put in a scratch
``spike3`` folder: a real, usable port file, so the profile is read exactly as a shipped one is.
"""
import os
import shutil
import struct

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_runtime as MR
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import port_derive as PD



def _elf64(vaddr, words):
    """An aarch64-shaped ELF64 with one PT_LOAD segment holding *words* at *vaddr* (as test_pad1272's)."""
    body = struct.pack("<%dI" % len(words), *words)
    phoff, off = 0x40, 0x40 + 0x38
    hdr = bytearray(b"\x7fELF\x02\x01\x01" + b"\0" * 9)
    hdr += struct.pack("<HHIQQQIHHHHHH", 3, 0xB7, 1, 0, phoff, 0, 0, 0x40, 0x38, 1, 0, 0, 0)
    ph = struct.pack("<IIQQQQQQ", 1, 5, off, vaddr, vaddr, len(body), len(body), 0x1000)
    return bytes(hdr) + ph + body

NAME = "star_wars_elg-1.10.port"
SPIKE2 = os.path.join(MP.PORTS_DIR, NAME)


@pytest.fixture
def spike3(monkeypatch, tmp_path):
    """A scratch ports/spike3 holding a Spike 3 port of Star Wars ELG 1.10."""
    if not os.path.isfile(SPIKE2):
        pytest.skip("the shipped Star Wars ELG 1.10 port is not in this tree")
    d = tmp_path / "spike3"
    d.mkdir()
    shutil.copyfile(SPIKE2, d / NAME)
    monkeypatch.setattr(MR, "spike3_ports_dir", lambda: str(d))
    MR._PORT_PATHS.clear()
    yield d
    MR._PORT_PATHS.clear()


def test_both_ports_of_one_build_are_listed_each_for_its_machine(spike3):
    got = [(v, MR.port_arch(p)) for g, v, p in MR.port_paths() if g == "star_wars_elg" and v == "1.10"]
    assert got == [("1.10", "arm"), ("1.10", "a64")]      # the shipped Spike 2 port stays first
    assert os.path.normcase(MR.port_file("star_wars_elg", "1.10.0")) == os.path.normcase(SPIKE2)
    assert MR.port_file("star_wars_elg", "1_10_0", arch="a64") == str(spike3 / NAME)
    assert ("star_wars_elg", "1.10") in MR.ports() and ("star_wars_elg", "1.10") in MR.ports("a64")
    assert ("star_wars_le", "1.31") not in MR.ports("a64")


def test_a_port_added_to_the_spike3_folder_is_seen_at_once(spike3):
    assert MR.port_file("star_wars_le", "1.31", arch="a64") is None
    shutil.copyfile(os.path.join(MP.PORTS_DIR, "star_wars_le-1.31.port"), spike3 / "star_wars_le-1.31.port")
    assert MR.port_file("star_wars_le", "1.31", arch="a64") == str(spike3 / "star_wars_le-1.31.port")


def test_each_build_has_a_profile_with_a_key_and_label_of_its_own(spike3):
    profs = {k: p for k, p in MP.profiles().items() if p.game_dir == "star_wars_elg"}
    s2, s3 = profs["star_wars_elg_1_10"], profs["star_wars_elg_1_10_spike3"]
    assert (s2.arch, s3.arch) == ("arm", "a64")
    assert s2.label == "Star Wars ELG 1.10" and s3.label == "Star Wars ELG 1.10 (Spike 3)"
    assert s3.port == "spike3/" + NAME and MP.port_path(s3) == os.path.join(str(spike3), NAME)
    assert os.path.normcase(MP.port_path(s2)) == os.path.normcase(SPIKE2)
    assert MP.profile(s3.key) is s3 or MP.profile(s3.key).key == s3.key
    assert MP.profile_for_card("star_wars_elg", "1.10.0").key == s2.key
    assert MP.profile_for_card("star_wars_elg", "1.10.0", arch="a64").key == s3.key
    assert MP.profile_for_card("star_wars_le", "1.31.0", arch="a64") is None


def test_the_spike2_builds_emulator_proofs_do_not_carry_over(spike3, monkeypatch):
    # PAD-1283: the Spike 3 build has a lamp proof of its own ("star_wars_elg-1.10/spike3"); without it, the Spike 2
    # build's proof does not light the Spike 3 profile's inserts
    monkeypatch.setattr(MP, "LAMPS_PROVEN", MP.LAMPS_PROVEN - {"star_wars_elg-1.10/spike3"})
    profs = MP.profiles()
    s2, s3 = profs["star_wars_elg_1_10"], profs["star_wars_elg_1_10_spike3"]
    assert "star_wars_elg-1.10" in MP.LAMPS_PROVEN and s2.lamps and s2.inserts
    assert not s3.lamps and s3.inserts == ()
    assert MP.table_key("star_wars_elg", "1.10", "a64") == "star_wars_elg-1.10/spike3"


def test_a_spike3_key_reads_as_its_game_and_model():
    for key in ("star_wars_elg_1_10_spike3", "godzilla_le_1_16_spike3"):
        build = key[:-len(MP.SPIKE3_KEY)]
        assert MP.family_of_key(key) == MP.family_of_key(build)
        assert MP.model_of_key(key) == MP.model_of_key(build)
    assert MP.model_of_key("godzilla_le_1_16_spike3") == "le"
    assert MP.profile_key("star_wars_elg", "1.10", "a64") == "star_wars_elg_1_10_spike3"
    assert MP.profile_key("star_wars_elg", "1.10") == "star_wars_elg_1_10"


def test_a_64_bit_program_only_tries_the_spike3_ports(spike3, monkeypatch):
    elf = _elf64(0x400000, [0xd503233f, 0xa9bf7bfd, 0x910003fd])
    s3 = MP.profiles()["star_wars_elg_1_10_spike3"]
    with pytest.raises(MW.ModeWriteError) as e:     # the copy's sites are Spike 2's: no match
        MW.find_port(s3, elf)
    assert str(e.value).count("star_wars_elg 1.10") == 1          # the Spike 3 port alone was tried
    seen = []
    monkeypatch.setattr(MW, "port_sites", lambda p: seen.append(p) or [])
    PD.ensure_port(elf, "star_wars_elg", "1.10.0")
    assert seen == [str(spike3 / NAME)]                           # never the Spike 2 port


def test_a_spike3_port_that_matches_is_the_one_taken(spike3):
    elf = _elf64(0x400000, [0xd503233f, 0xa9bf7bfd, 0x910003fd])
    (spike3 / NAME).write_text("game star_wars_elg\nversion 1.10\n"
                               "site tick 0x400000 0xd503233f 0xa9bf7bfd\n", encoding="utf-8")
    pr = PD.ensure_port(elf, "star_wars_elg", "1.10.0")
    assert pr.path == str(spike3 / NAME) and pr.origin == "shipped" and pr.proven
    prof = MP.replace(MP.GODZILLA_PRO_1_15, key="star_wars_elg_1_10_spike3", game_dir="star_wars_elg",
                      label="Star Wars ELG 1.10 (Spike 3)", version="1.10", port="spike3/" + NAME, arch="a64")
    assert MW.find_port(prof, elf) == str(spike3 / NAME)


def test_card_arch_by_partitions_or_by_name(tmp_path):
    s2 = tmp_path / "star_wars_elg-1_10_0_spike2.Release.8G.sdcard.raw"
    s2.write_bytes(b"\0" * 4096)
    assert MP.card_arch(str(s2)) == "arm"
    assert MP.card_arch("") == "arm"
    gone = r"X:\nowhere\star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw"
    assert MP.card_arch(gone) == "a64"
    assert MP.card_arch(r"X:\nowhere\pokemon_le-0_82_0.Release.64G.sdcard-secure.raw") == "a64"
    assert MP.card_arch(r"X:\nowhere\star_wars_elg-1_10_0_spike2.Release.8G.sdcard.raw") == "arm"


def test_elf_arch():
    assert MR.elf_arch(_elf64(0x400000, [1])) == "a64"
    assert MR.elf_arch(b"\x7fELF\x01\x01\x01" + b"\0" * 9) == "arm"
