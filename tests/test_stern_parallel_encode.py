"""Orchestration tests for the parallel Write re-encode (cat-0 + music banks).

The heavy bit-exact encode itself needs a card + the firmware emulator and is
verified manually (set PAD_STERN_SERIAL_ENCODE=1 vs unset → byte-identical
output).  These cover the pure routing/aggregation around it: which sounds get
dispatched, the single-process fallback, cancellation, and the unknown-idx /
empty-edit handling — the places a regression could silently drop or duplicate a
patch."""

from pinball_decryptor.plugins.stern import engine as E


def _params(*idxs):
    return [{"idx": i, "chan": 1, "length": 100, "body_off": i * 1000}
            for i in idxs]


def _noop(*a, **k):
    return None


# ---- cat-0 dispatcher ----------------------------------------------------

def test_cat0_empty_edits_is_noop(monkeypatch):
    called = []
    monkeypatch.setattr(E, "_encode_cat0_serial",
                        lambda *a, **k: called.append("s") or ({}, [], {}))
    monkeypatch.setattr(E, "_encode_cat0_parallel",
                        lambda *a, **k: called.append("p") or ({}, [], [], {}))
    patches, skipped = E._encode_cat0_sounds(
        "g", "i", _params(1, 2), {}, None, _noop, None, lambda: False)
    assert patches == {} and skipped == []
    assert called == []  # neither path booted an emulator


def test_cat0_unknown_idx_is_dropped(monkeypatch):
    seen = {}

    def fake_serial(gr, img, byidx, edits, np, log, progress, cancel):
        seen["edits"] = edits
        return ({}, [], {})
    monkeypatch.setattr(E, "_FORCE_SERIAL_ENCODE", True)
    monkeypatch.setattr(E, "_encode_cat0_serial", fake_serial)
    # idx 99 isn't in params -> filtered out before dispatch.
    E._encode_cat0_sounds("g", "i", _params(1, 2), {1: "a.wav", 99: "b.wav"},
                          None, _noop, None, lambda: False)
    assert [idx for idx, _ in seen["edits"]] == [1]


def test_cat0_force_serial_skips_pool(monkeypatch):
    calls = []
    monkeypatch.setattr(E, "_FORCE_SERIAL_ENCODE", True)
    monkeypatch.setattr(E, "_encode_cat0_serial",
                        lambda *a, **k: calls.append("s") or ({0: b"x"}, [], {}))
    monkeypatch.setattr(E, "_encode_cat0_parallel",
                        lambda *a, **k: calls.append("p") or ({}, [], [], {}))
    E._encode_cat0_sounds("g", "i", _params(1, 2, 3),
                          {1: "a", 2: "b", 3: "c"}, None, _noop, None,
                          lambda: False)
    assert calls == ["s"]  # forced serial even with many edits


def test_cat0_parallel_failure_falls_back_to_serial(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append("p")
        raise RuntimeError("no pool")
    monkeypatch.setattr(E, "_FORCE_SERIAL_ENCODE", False)
    # Pin the core count so the parallel branch is actually attempted — on a
    # 1-2 core runner nworkers collapses to 1 and the dispatcher correctly skips
    # straight to serial (the intended low-core behaviour, but not what this
    # fallback test is exercising).
    monkeypatch.setattr(E.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(E, "_encode_cat0_parallel", boom)
    monkeypatch.setattr(E, "_encode_cat0_serial",
                        lambda *a, **k: calls.append("s") or ({0: b"x"}, [], {}))
    patches, _ = E._encode_cat0_sounds(
        "g", "i", _params(1, 2), {1: "a", 2: "b"}, None, _noop, None,
        lambda: False)
    assert calls == ["p", "s"] and patches == {0: b"x"}


def test_cat0_parallel_partial_resume_keeps_done_work(monkeypatch):
    """A pool that dies mid-run returns its finished patches + the leftovers; the
    serial pass must re-encode ONLY the leftovers (not everything), and the
    results merge.  This is the fix for the slow path that re-did all the work
    serially on a partial failure."""
    monkeypatch.setattr(E, "_FORCE_SERIAL_ENCODE", False)
    monkeypatch.setattr(E.os, "cpu_count", lambda: 8)

    # idx 1 finished in parallel; idx 2 + 3 were left over.
    def partial(gr, img, needed, edits, nworkers, np, log, progress, cancel):
        return ({1000: b"one"}, [], [(2, "b"), (3, "c")], {1: (1000, b"one")})
    seen = {}

    def fake_serial(gr, img, byidx, edits, np, log, progress, cancel):
        seen["edits"] = [idx for idx, _ in edits]
        return ({2000: b"two", 3000: b"three"}, [],
                {2: (2000, b"two"), 3: (3000, b"three")})
    monkeypatch.setattr(E, "_encode_cat0_parallel", partial)
    monkeypatch.setattr(E, "_encode_cat0_serial", fake_serial)
    patches, skipped = E._encode_cat0_sounds(
        "g", "i", _params(1, 2, 3), {1: "a", 2: "b", 3: "c"}, None, _noop,
        None, lambda: False)
    # serial only re-did the leftovers, and both sets merged.
    assert seen["edits"] == [2, 3]
    assert patches == {1000: b"one", 2000: b"two", 3000: b"three"}
    assert skipped == []


# ---- the audio encode-result cache ---------------------------------------

def _cache_rig(tmp_path):
    """(assets_dir, gr, img, wav) file scaffolding for the cache tests."""
    assets = tmp_path / "assets"
    assets.mkdir()
    wav = assets / "idx0001.wav"
    wav.write_bytes(b"RIFF-fake-wav-1")
    gr = tmp_path / "gr.bin"
    gr.write_bytes(b"G" * 64)
    img = tmp_path / "img.bin"
    img.write_bytes(b"I" * 64)
    return assets, gr, img, wav


def test_cat0_cache_replays_unchanged_sounds(monkeypatch, tmp_path):
    assets, gr, img, wav = _cache_rig(tmp_path)
    calls = []

    def fake_serial(g, i, byidx, edits, np, log, progress, cancel):
        calls.append([idx for idx, _ in edits])
        return ({1000: b"body1"}, [], {1: (1000, b"body1")})
    monkeypatch.setattr(E, "_FORCE_SERIAL_ENCODE", True)
    monkeypatch.setattr(E, "_encode_cat0_serial", fake_serial)
    args = (str(gr), str(img), _params(1), {1: str(wav)}, None, _noop, None,
            lambda: False)
    p1, _s = E._encode_cat0_sounds(*args, assets_dir=str(assets))
    p2, _s = E._encode_cat0_sounds(*args, assets_dir=str(assets))
    assert p1 == p2 == {1000: b"body1"}
    assert calls == [[1]]              # the second build never re-encoded
    # editing the WAV invalidates its entry
    wav.write_bytes(b"RIFF-fake-wav-2-edited")
    E._encode_cat0_sounds(*args, assets_dir=str(assets))
    assert calls == [[1], [1]]


def test_cat0_cache_skip_verdict_replays(monkeypatch, tmp_path):
    assets, gr, img, wav = _cache_rig(tmp_path)
    calls = []

    def fake_serial(g, i, byidx, edits, np, log, progress, cancel):
        calls.append([idx for idx, _ in edits])
        return ({}, [1], {})           # codec can't re-encode idx 1
    monkeypatch.setattr(E, "_FORCE_SERIAL_ENCODE", True)
    monkeypatch.setattr(E, "_encode_cat0_serial", fake_serial)
    args = (str(gr), str(img), _params(1), {1: str(wav)}, None, _noop, None,
            lambda: False)
    p1, s1 = E._encode_cat0_sounds(*args, assets_dir=str(assets))
    p2, s2 = E._encode_cat0_sounds(*args, assets_dir=str(assets))
    assert (p1, s1) == (p2, s2) == ({}, [1])
    assert calls == [[1]]              # the failed encode isn't re-attempted


def test_cat0_cache_env_and_kill_switch(monkeypatch, tmp_path):
    assets, gr, img, wav = _cache_rig(tmp_path)
    calls = []

    def fake_serial(g, i, byidx, edits, np, log, progress, cancel):
        calls.append(1)
        return ({1000: b"b"}, [], {1: (1000, b"b")})
    monkeypatch.setattr(E, "_FORCE_SERIAL_ENCODE", True)
    monkeypatch.setattr(E, "_encode_cat0_serial", fake_serial)
    args = (str(gr), str(img), _params(1), {1: str(wav)}, None, _noop, None,
            lambda: False)
    E._encode_cat0_sounds(*args, assets_dir=str(assets))
    # a PATH-ONLY toggle (verify skip) must NOT dump the cache...
    monkeypatch.setenv("PAD_STERN_SKIP_FINAL_VERIFY", "1")
    E._encode_cat0_sounds(*args, assets_dir=str(assets))
    assert len(calls) == 1
    # ...an encode-shaping knob MUST...
    monkeypatch.setenv("PAD_STERN_HEADROOM", "0.5")
    E._encode_cat0_sounds(*args, assets_dir=str(assets))
    assert len(calls) == 2
    # ...and the kill switch bypasses the cache entirely.
    monkeypatch.setenv("PAD_STERN_AUDIO_CACHE", "0")
    E._encode_cat0_sounds(*args, assets_dir=str(assets))
    assert len(calls) == 3


def test_cat0_cache_dir_is_never_baselined(tmp_path):
    # generate_checksums must not hash the cache into the Extract baseline —
    # else every re-extract would flag it as a modified asset.
    from pinball_decryptor.core.checksums import (generate_checksums,
                                                  read_checksums)
    assets = tmp_path / "assets"
    (assets / ".write_cache" / "audio").mkdir(parents=True)
    (assets / ".write_cache" / "audio" / "idx00001-abc.bin").write_bytes(b"x")
    (assets / "audio").mkdir()
    (assets / "audio" / "idx0001.wav").write_bytes(b"RIFF")
    generate_checksums(str(assets))
    rels = set(read_checksums(str(assets)))
    assert rels == {"audio/idx0001.wav"}


# ---- music-bank runner ---------------------------------------------------

def test_run_bank_encode_serial_aggregates(monkeypatch):
    monkeypatch.setattr(E, "_FORCE_SERIAL_ENCODE", True)

    def fake_bank(gr, img, rev, cid, sc_path, edits, np):
        return ([(cid, idx, idx * 10, b"B" + bytes([idx]))
                 for idx, _ in edits], [])
    monkeypatch.setattr(E, "_derive_encode_bank", fake_bank)
    tasks = [("g", "i", 1, 1, "sc1", [(0, "w0"), (1, "w1")]),
             ("g", "i", 1, 2, "sc2", [(0, "w0")])]
    out = E._run_bank_encode(tasks, _noop, None, lambda: False)
    assert out is not None
    allp = [p for bank_p, _ in out for p in bank_p]
    assert set(allp) == {(1, 0, 0, b"B\x00"), (1, 1, 10, b"B\x01"),
                         (2, 0, 0, b"B\x00")}


def test_run_bank_encode_cancel_returns_none(monkeypatch):
    monkeypatch.setattr(E, "_FORCE_SERIAL_ENCODE", True)
    out = E._run_bank_encode([("g", "i", 1, 1, "sc", [(0, "w")])],
                             _noop, None, lambda: True)
    assert out is None


def test_bank_encode_worker_swallows_errors(monkeypatch):
    # A bank that blows up returns ([], [(cid, idx)...]) so one bad bank never
    # crashes the whole Write — its songs are reported skipped.
    def boom(*a, **k):
        raise RuntimeError("derive failed")
    monkeypatch.setattr(E, "_derive_encode_bank", boom)
    patches, skipped = E._bank_encode_worker(
        ("g", "i", 1, 7, "sc7", [(0, "w0"), (3, "w3")]))
    assert patches == []
    assert set(skipped) == {(7, 0), (7, 3)}
