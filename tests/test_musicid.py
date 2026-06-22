"""AcoustID online music identification (core/musicid.py).

Network + the AcoustID key are mocked, so these run offline; the live lookup
is validated separately once a key is available.
"""
import io
import json

from pinball_decryptor.core import musicid as M


_SAMPLE = {
    "status": "ok",
    "results": [
        {"score": 0.93, "recordings": [
            {"title": "Communication Breakdown",
             "artists": [{"name": "Led Zeppelin"}]}]},
        {"score": 0.31, "recordings": [
            {"title": "Other", "artists": [{"name": "Nobody"}]}]},
    ],
}


def test_best_match_picks_top_score():
    assert M.best_match(_SAMPLE) == (
        "Communication Breakdown", "Led Zeppelin", 0.93)


def test_best_match_handles_empty_and_error():
    assert M.best_match({"status": "ok", "results": []}) == (None, None, 0.0)
    assert M.best_match({"status": "error"}) == (None, None, 0.0)
    assert M.best_match({"status": "ok", "results": [
        {"score": 0.9, "recordings": []}]}) == (None, None, 0.0)


def test_lookup_builds_gzip_request(monkeypatch):
    captured = {}

    class FakeResp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_opener(req, timeout=20):
        import gzip
        captured["url"] = req.full_url
        captured["enc"] = dict(req.header_items()).get("Content-encoding")
        captured["body"] = gzip.decompress(req.data).decode()
        return FakeResp(json.dumps(_SAMPLE).encode())

    data = M.lookup("FPDATA", 140, "KEY123", _opener=fake_opener)
    assert data["status"] == "ok"
    assert captured["url"] == M.ACOUSTID_LOOKUP_URL
    assert captured["enc"] == "gzip"
    for token in ("client=KEY123", "fingerprint=FPDATA",
                  "duration=140", "meta=recordings"):
        assert token in captured["body"], captured["body"]


def test_resolve_client_key_precedence(monkeypatch):
    monkeypatch.setenv("ACOUSTID_API_KEY", "envkey")
    assert M.resolve_client_key("explicit") == "explicit"
    assert M.resolve_client_key(None) == "envkey"
    monkeypatch.delenv("ACOUSTID_API_KEY")
    assert M.resolve_client_key(None) == (M.DEFAULT_CLIENT_KEY or "")


def test_pipeline_identifies_and_renames(tmp_path, monkeypatch):
    import wave
    import numpy as np
    assets = tmp_path / "assets"
    assets.mkdir()
    # a >=20s WAV so it passes the music gate
    sr = 22050
    pcm = (0.1 * np.sin(np.arange(sr * 22) * 0.05)).astype("<f4")
    pcm16 = (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()
    w = wave.open(str(assets / "idx0139.wav"), "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes(pcm16); w.close()

    monkeypatch.setattr(M, "fingerprint_file", lambda p: ("FP", 22))
    monkeypatch.setattr(M, "lookup", lambda fp, d, k, **kw: _SAMPLE)

    done = {}
    p = M.MusicIdPipeline(
        str(assets),
        log_cb=lambda t, l: None, phase_cb=lambda i: None,
        progress_cb=lambda a, b, d: None,
        done_cb=lambda ok, msg: done.update(ok=ok, msg=msg),
        client_key="KEY", min_music_seconds=8.0, min_score=0.5,
        rename_after=True)
    p.run()

    assert done.get("ok") is True, done
    names = sorted(p_ for p_ in __import__("os").listdir(assets))
    assert "idx0139 - Led Zeppelin - Communication Breakdown.wav" in names, names
    assert M.MUSIC_IDS_CSV in names


def test_pipeline_errors_without_key(tmp_path, monkeypatch):
    # Force no key: empty the bundled default + env so resolve_client_key("")
    # really yields "".
    monkeypatch.setattr(M, "DEFAULT_CLIENT_KEY", "")
    monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
    assets = tmp_path / "assets"; assets.mkdir()
    done = {}
    p = M.MusicIdPipeline(
        str(assets),
        log_cb=lambda t, l: None, phase_cb=lambda i: None,
        progress_cb=lambda a, b, d: None,
        done_cb=lambda ok, msg: done.update(ok=ok, msg=msg),
        client_key="")
    p.run()
    assert done.get("ok") is False
    assert "AcoustID" in done.get("msg", "")
