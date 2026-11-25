"""PAD-1586: Spike 3 catch-up - Mod Pack (export / import), Move Your Mods (transfer,
one-click port, What's new) and the Partition Explorer on a Stern Spike 3 card.

The real-card proofs (Fallout LE 0.81 -> 0.82 carried and built, the card browsed) are in
the ticket's commits; these pin the pieces without a card."""

import types

import pytest

from pinball_decryptor.plugins.stern import explorer, spike3
from pinball_decryptor.plugins.stern import manufacturer as sm
from tests.test_spike3 import _build_spike3_disk
from tests.webui_harness import web_app


def test_spike3_caps_offer_the_mod_pack_transfer_and_explorer():
    caps = sm._SPIKE3_CAPS
    assert caps.modpack is True
    assert caps.mod_transfer is True
    assert caps.partition_explorer is True


@pytest.fixture
def s3_disk(tmp_path):
    p = tmp_path / "fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw"
    p.write_bytes(_build_spike3_disk().getvalue())
    return str(p)


class _Keys:
    def has_any(self):
        return True


def test_explorer_unlocks_a_spike3_cards_partitions(s3_disk, monkeypatch):
    opened = []

    def fake_open(f, part, ks, role=None):
        opened.append((part["index"], role))
        return ("reader", part["index"])
    monkeypatch.setattr(spike3, "open_partition_ext4", fake_open)
    monkeypatch.setattr("pinball_decryptor.plugins.stern.spike3_keys.Spike3KeySource.discover",
                        classmethod(lambda cls, image_path=None, image_id=None: _Keys()))
    with explorer.CardImage(s3_disk, logical=True) as card:
        assert card.spike3 and card.spike3_locked == ""
        parts = {p.index: p for p in card.partitions()}
        # 0-based slots as Spike 2's (sda1.. / logicals from sda5)
        assert parts[0].kind == "fat" and not parts[0].browsable
        assert parts[3].kind == "extended"
        assert [(i, parts[i].label) for i in (1, 2, 4, 5)] == [
            (1, "Encrypted system (ext4)"), (2, "Encrypted data (ext4)"),
            (4, "Encrypted connectivity (ext4)"), (5, "Encrypted games (ext4)")]
        assert all(parts[i].encrypted and parts[i].browsable for i in (1, 2, 4, 5))
        assert card.reader(5) == ("reader", 6)
        assert sorted(opened) == [(2, "rootfs"), (3, "data"), (5, "connectivity"), (6, "games")]
        # browsed through its decryption only: a byte patch is refused in words
        with pytest.raises(ValueError, match="encrypted"):
            card.replace_file_bytes(5, "/game", b"x")


def test_explorer_lists_a_spike3_card_locked_without_its_key(s3_disk, monkeypatch):
    monkeypatch.setattr("pinball_decryptor.plugins.stern.spike3_keys.Spike3KeySource.discover",
                        classmethod(lambda cls, image_path=None, image_id=None: None))
    monkeypatch.setattr(spike3, "open_partition_ext4",
                        lambda *a, **k: pytest.fail("opened with no key"))
    with explorer.CardImage(s3_disk) as card:
        assert card.spike3 and "no Spike 3 key" in card.spike3_locked
        enc = [p for p in card.partitions() if p.encrypted]
        assert len(enc) == 4 and not any(p.browsable for p in enc)
        assert enc[-1].label == "Encrypted games (locked)"


def test_explorer_says_when_the_key_does_not_open_a_partition(s3_disk, monkeypatch):
    monkeypatch.setattr("pinball_decryptor.plugins.stern.spike3_keys.Spike3KeySource.discover",
                        classmethod(lambda cls, image_path=None, image_id=None: _Keys()))

    def refuse(*a, **k):
        raise spike3.Spike3KeyError("the supplied key did not unlock this partition")
    monkeypatch.setattr(spike3, "open_partition_ext4", refuse)
    with explorer.CardImage(s3_disk) as card:
        assert "did not unlock" in card.spike3_locked
        assert all(not p.browsable for p in card.partitions())
        assert "(key did not open it)" in card.partitions()[1].label


def test_whats_new_answers_a_spike3_card_from_its_spike3_port(monkeypatch):
    from pinball_decryptor.plugins.stern import mode_project as MP
    monkeypatch.setattr(MP, "card_arch", lambda raw: "a64")
    monkeypatch.setattr(MP, "list_modes", lambda project: (["a", "b"], []))
    monkeypatch.setattr(MP, "probe_card_title", lambda raw: ("fallout_le", "0.82.0"))
    seen = []

    def prof(game, version, arch="arm", ports_dir=None):
        seen.append((game, version, arch))
        return object()
    monkeypatch.setattr(MP, "profile_for_card", prof)
    m = sm.SternManufacturer()
    got = m.mode_news("card.raw", project="proj")
    assert got == "This project's 2 modes run on %s." % MP.title_label("fallout_le", "0.82.0")
    assert seen == [("fallout_le", "0.82.0", "a64")]
    monkeypatch.setattr(MP, "profile_for_card", lambda *a, **k: None)
    assert "no port for that Spike 3 build" in m.mode_news("card.raw", project="proj")
    monkeypatch.setattr(MP, "probe_card_title", lambda raw: (None, None))
    assert "Spike 3 key" in m.mode_news("card.raw", project="proj")


@pytest.mark.parametrize("era,arches,refused", [
    ("spike3", ["a64", "a64"], False),
    ("spike3", ["a64", "arm"], True),
    ("spike2", ["arm"], False),
    ("spike2", ["a64"], True),
    ("spike1", ["a64"], False),          # not a Spike 2/3 session: not this check's
])
def test_port_refuses_a_card_of_the_other_generation(monkeypatch, era, arches, refused):
    from pinball_decryptor import app as A
    from pinball_decryptor.plugins.stern import mode_project as MP
    raws = ["card%d.raw" % i for i in range(len(arches))]
    monkeypatch.setattr(MP, "card_arch", lambda r: arches[raws.index(r)])
    fake = types.SimpleNamespace(_current_mfr=types.SimpleNamespace(_era=era))
    why = A.App._port_other_generation(fake, raws)
    assert bool(why) is refused
    if refused:
        odd = raws[arches.index("arm" if era == "spike3" else "a64")]
        assert "one generation" in why and odd in why


def test_spike3_session_shows_mod_pack_transfer_and_explorer_tabs(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set_era", "spike3")
        w.drain()
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["modpack"]["visible"] and tabs["partitions"]["visible"]
        mp = w.state("modpack")
        assert mp["modpack_cap"] and mp["transfer_cap"]
