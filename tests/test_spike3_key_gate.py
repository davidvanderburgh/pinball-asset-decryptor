"""PAD-1090: the user's own Spike 3 OTP key - one place, found by every
Spike 3 tab, and the tabs gated on it.

David: "our emulator page should be greyed out unless the user has the OTP
key ... that should also be on the other spike 3 pages too", and "why don't
i have the OTP key in my local?" - the Extract unlock kept it in the project
folder only, and the Emulate tab handed the store a padkeys.json beside the
cards that held only the .spk package key."""
import json
import types

import pytest

from pinball_decryptor.webui import spike3_key

#: zeros: no real key belongs in a test
ZERO = "00" * 32


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    monkeypatch.delenv("PAD_SPIKE3_KEYFILE", raising=False)
    return h


def test_a_spk_only_padkeys_beside_the_card_is_not_an_otp_key(tmp_path, home):
    """David's D:\\...\\spike3\\padkeys.json: spk_keyfile only."""
    cards = tmp_path / "cards"
    cards.mkdir()
    card = cards / "pokemon_le.raw"
    card.write_bytes(b"")
    (cards / "padkeys.json").write_text(json.dumps({"spk_keyfile": "spk.bin"}))
    assert spike3_key.find_keyfile(str(card)) is None
    user = home / ".pad" / "spike3_padkeys.json"
    user.parent.mkdir()
    user.write_text(json.dumps({"otp_keyfile": ZERO}))
    assert spike3_key.find_keyfile(str(card)) == str(user)


def test_has_otp_takes_hex_or_a_key_file_beside_it(tmp_path):
    p = tmp_path / "padkeys.json"
    p.write_text(json.dumps({"otp_keyfile": ZERO}))
    assert spike3_key.has_otp(str(p))
    (tmp_path / "otp.bin").write_bytes(b"\0" * 32)
    p.write_text(json.dumps({"otp_keyfile": "otp.bin"}))
    assert spike3_key.has_otp(str(p))
    p.write_text(json.dumps({"otp_keyfile": "missing.bin"}))
    assert not spike3_key.has_otp(str(p))
    p.write_text("not json")
    assert not spike3_key.has_otp(str(p))


def test_save_key_keeps_a_verified_key_for_every_tab(tmp_path, home, monkeypatch):
    from pinball_decryptor.plugins.stern import spike3_selfextract as SX
    seen = {}

    def ingest(key, card, out_path=None):
        seen.update(key=key, card=card, out=out_path)
        with open(out_path, "w") as f:
            json.dump({"otp_keyfile": ZERO}, f)
        return types.SimpleNamespace(verified=True, message="ok", sidecar=out_path)
    monkeypatch.setattr(SX, "ingest_otp_key", ingest)
    ok, msg, path = spike3_key.save_key("OTP_KEY.TXT", "card.raw")
    assert ok and path == spike3_key.user_keyfile() == seen["out"]
    assert spike3_key.find_keyfile() == path


def test_a_key_that_does_not_open_the_card_is_not_kept(tmp_path, home, monkeypatch):
    from pinball_decryptor.plugins.stern import spike3_selfextract as SX
    monkeypatch.setattr(SX, "ingest_otp_key", lambda k, c, out_path=None: types.SimpleNamespace(
        verified=False, message="That key did NOT unlock this card.", sidecar=None))
    ok, msg, path = spike3_key.save_key("wrong.txt", "card.raw")
    assert not ok and "did NOT" in msg and path is None
    assert spike3_key.find_keyfile() is None


def test_the_extract_tabs_discovery_finds_the_users_key(tmp_path, home):
    from pinball_decryptor.plugins.stern.spike3_keys import Spike3KeySource
    user = home / ".pad" / "spike3_padkeys.json"
    user.parent.mkdir()
    user.write_text(json.dumps({"otp_keyfile": ZERO}))
    card = tmp_path / "x.raw"
    card.write_bytes(b"")
    src = Spike3KeySource.discover(image_path=str(card))
    assert src is not None and src.has_any()


def test_spike3_tabs_need_the_key_and_spike2_ones_do_not():
    from pinball_decryptor.webui.tabs.compare import CompareTab
    from pinball_decryptor.webui.tabs.emulate import EmulateTab
    for cls in (EmulateTab, CompareTab):
        fake = types.SimpleNamespace(mfr=types.SimpleNamespace(_era="spike3"))
        fake._spike3_era = lambda f=fake: getattr(f.mfr, "_era", None) == "spike3"
        assert cls.rail_needs(fake) == "spike3key"
        fake.mfr._era = "spike2"
        assert cls.rail_needs(fake) is None
