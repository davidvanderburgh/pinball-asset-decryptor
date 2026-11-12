"""PAD-1086 - the Extract tab's Spike 3 self-extractor panel.

A locked Spike 3 card (detected Spike 3, no key yet) shows the "read the OTP
key on your own board" panel; it clears once a key is present or the input is
not a locked Spike 3 card. The build/ingest actions are wired to
spike3_selfextract (verified here with the builder/ingest mocked, and proven
for real by the spike3_selfextract unit tests + the in-app proof shot).
"""

import os
import time

from tests.webui_harness import web_app


def _res(**kw):
    base = {"era": "spike3", "game": object(), "exists": True,
            "caption": "Star Wars (LE)", "size": 123}
    base.update(kw)
    return base


def _svc(w, monkeypatch, key_present=False):
    svc = w.window.service("extract")
    # these tests drive detection/rpc directly; neutralize the async probe that
    # a real card selection would start (it would clear the panel for a junk
    # input path and race the assertions).
    monkeypatch.setattr(svc, "_start_probe", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_spike3_key_present", lambda p: key_present)
    return svc


# --- detection: when the panel shows / hides -------------------------------
def test_panel_shows_for_locked_spike3_card(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, monkeypatch, key_present=False)
        w.run(lambda: svc._refresh_spike3_unlock(_res()))
        w.drain()
        u = w.state("extract")["spike3_unlock"]
        assert u and u["caption"] == "Star Wars (LE)"
        assert u["busy"] is False and u["verified"] is False


def test_panel_hidden_when_key_present(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, monkeypatch, key_present=True)
        w.run(lambda: svc._refresh_spike3_unlock(_res()))
        w.drain()
        assert w.state("extract").get("spike3_unlock") is None


def test_panel_hidden_for_spk_package(tmp_path, monkeypatch):
    # PAD-1077: a .spk package opens with the fleet update key, not a board's
    # OTP key, so the extractor-card panel never applies to it
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, monkeypatch, key_present=False)
        w.run(lambda: svc.extract_input_var.set(
            str(tmp_path / "pokemon_le-0_87_0_spike3.spk.zip")))
        w.run(lambda: svc._refresh_spike3_unlock(_res()))
        w.drain()
        assert w.state("extract").get("spike3_unlock") is None


def test_panel_hidden_for_non_spike3(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, monkeypatch, key_present=False)
        w.run(lambda: svc._refresh_spike3_unlock(_res(era="spike2")))
        w.drain()
        assert w.state("extract").get("spike3_unlock") is None


# --- where padkeys.json is written -----------------------------------------
def test_padkeys_path_is_the_users_own_whatever_the_project(tmp_path, monkeypatch):
    """PAD-1090: the key kept in one project folder was lost to every other
    project and tab ("why don't i have the OTP key in my local?"); it is the
    user's, kept once, where every Spike 3 tab looks (webui/spike3_key.py)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("extract")
        proj = tmp_path / "proj"
        proj.mkdir()
        w.run(lambda: svc.extract_output_var.set(str(proj)))
        got = w.run(svc._spike3_padkeys_path)
        assert got == os.path.join(str(home), ".pad", "spike3_padkeys.json")


def test_padkeys_path_falls_back_outside_readonly_image_dir(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("extract")
        w.run(lambda: svc.extract_output_var.set(""))
        got = w.run(svc._spike3_padkeys_path)
        # never next to the image; a writable fallback dir
        assert got.endswith("spike3_padkeys.json")
        assert os.path.isdir(os.path.dirname(got))


# --- the two actions wire to spike3_selfextract ----------------------------
def _wait_unlock(w, pred, limit=6.0):
    end = time.time() + limit
    while time.time() < end:
        w.drain()
        u = w.state("extract").get("spike3_unlock")
        if pred(u):
            return u
        time.sleep(0.05)
    return w.state("extract").get("spike3_unlock")


def test_build_card_rpc_shows_deploy_steps(tmp_path, monkeypatch):
    import pinball_decryptor.plugins.stern.spike3_selfextract as SX

    class R:
        instructions = "DEPLOY STEPS HERE"
        log = "built"

    monkeypatch.setattr(SX, "build_extractor_card", lambda p, o, **k: R())
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, monkeypatch)
        img = tmp_path / "card.raw"
        img.write_bytes(b"\0")
        w.run(lambda: svc.extract_input_var.set(str(img)))
        w.answers = [str(tmp_path / "cardout")]       # answers ask_folder
        w.call("extract.spike3_build_card")
        u = _wait_unlock(w, lambda u: u and u.get("instructions"))
        assert u["instructions"] == "DEPLOY STEPS HERE"
        assert u["busy"] is False


def test_ingest_key_rpc_unlocks(tmp_path, monkeypatch):
    import pinball_decryptor.plugins.stern.spike3_selfextract as SX
    sidecar = str(tmp_path / "padkeys.json")

    class Res:
        verified = True
        message = "Key verified. This card is unlocked."
        sidecar = None
        key_hex = "ab" * 32

    Res.sidecar = sidecar
    monkeypatch.setattr(SX, "ingest_otp_key", lambda k, img, **kw: Res())
    monkeypatch.delenv("PAD_SPIKE3_KEYFILE", raising=False)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, monkeypatch)
        img = tmp_path / "card.raw"
        img.write_bytes(b"\0")
        keyfile = tmp_path / "OTP_KEY.TXT"
        keyfile.write_text("ab" * 32)
        w.run(lambda: svc.extract_input_var.set(str(img)))
        w.answers = [str(keyfile)]                    # answers ask_open
        w.call("extract.spike3_ingest_key")
        u = _wait_unlock(w, lambda u: u and u.get("verified"))
        assert u["verified"] is True
        assert os.environ.get("PAD_SPIKE3_KEYFILE") == sidecar
    os.environ.pop("PAD_SPIKE3_KEYFILE", None)


def test_ingest_bad_key_rpc_keeps_locked(tmp_path, monkeypatch):
    import pinball_decryptor.plugins.stern.spike3_selfextract as SX

    class Res:
        verified = False
        message = "That key did NOT unlock this card."
        sidecar = None
        key_hex = None

    monkeypatch.setattr(SX, "ingest_otp_key", lambda k, img, **kw: Res())
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, monkeypatch)
        img = tmp_path / "card.raw"
        img.write_bytes(b"\0")
        keyfile = tmp_path / "OTP_KEY.TXT"
        keyfile.write_text("00" * 32)
        w.run(lambda: svc.extract_input_var.set(str(img)))
        w.answers = [str(keyfile)]
        # wait for the worker to settle (busy back to False with a message)
        w.call("extract.spike3_ingest_key")
        u = _wait_unlock(w, lambda u: u and u.get("busy") is False
                         and "unlock" in (u.get("status") or ""))
        assert not u.get("verified")
        assert "did NOT unlock" in u["status"]
