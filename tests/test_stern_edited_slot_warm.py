"""PAD-331: a sound being re-encoded never picks its own codec entry.

On a generic Spike 2 build the emulator chooses a ``(scale, chan)``'s codec
sub-slot by decoding the first sound it is asked about and scoring the audio
(:meth:`Spike2Emu._resolve_entry`).  On a card PAD already built, the sound a
Write re-encodes holds the last build's replacement, and loud dense audio there
reads as the wrong codec: the key settled on the noise entry, the bit-exact
self-test failed, and the sound was skipped on every build - the old
replacement stayed whatever the user picked or reverted to, and a project
changing only that sound got "Nothing could be written" (Godzilla LE 1.16,
measured).  The key is now settled from another sound of the card first.
"""
import pytest

from pinball_decryptor.plugins.stern.spike2.emulator import Spike2Emu


class _Emu:
    """Just the slot cache and resolver of a booted emulator."""

    warm_slots_for_grown = Spike2Emu.warm_slots_for_grown

    def __init__(self):
        self._slot_cache = {}
        self.resolved = []

    def _resolve_entry(self, p):
        self.resolved.append(p["idx"])
        self._slot_cache[(p["scale"], p["chan"])] = 0x1000 + p["idx"]
        return self._slot_cache[(p["scale"], p["chan"])]


def _p(idx, scale=20, chan=1, length=40000, **kw):
    return dict(idx=idx, scale=scale, chan=chan, length=length, **kw)


def test_an_edited_sound_settles_its_key_from_another_sound():
    params = [_p(2), _p(3), _p(4, scale=21)]
    emu = _Emu()
    emu.warm_slots_for_grown(params, edited=[2])
    assert emu.resolved == [3]
    assert emu._slot_cache == {(20, 1): 0x1003}


def test_every_edited_key_is_settled_and_no_edited_sound_seeds_one():
    params = [_p(1), _p(2), _p(3), _p(5, chan=2), _p(6, chan=2),
              _p(7, scale=30)]
    emu = _Emu()
    emu.warm_slots_for_grown(params, edited=[1, 2, 5])
    assert sorted(emu.resolved) == [3, 6]
    assert (30, 1) not in emu._slot_cache    # nothing edited there


def test_short_and_grown_sounds_never_seed_a_key():
    params = [_p(2), _p(3, length=4000), _p(4, grown=True), _p(5)]
    emu = _Emu()
    emu.warm_slots_for_grown(params, edited=[2])
    assert emu.resolved == [5]


def test_a_key_with_only_edited_sounds_is_left_to_resolve_itself():
    params = [_p(2), _p(3, scale=21)]
    emu = _Emu()
    emu.warm_slots_for_grown(params, edited=[2])
    assert emu.resolved == [] and emu._slot_cache == {}


def test_a_key_already_settled_is_not_resolved_again():
    params = [_p(2), _p(3)]
    emu = _Emu()
    emu._slot_cache[(20, 1)] = 0xBEEF
    emu.warm_slots_for_grown(params, edited=[2])
    assert emu.resolved == [] and emu._slot_cache == {(20, 1): 0xBEEF}


def test_without_edits_only_grown_sounds_are_warmed_as_before():
    params = [_p(2), _p(3, grown=True), _p(4)]
    emu = _Emu()
    emu.warm_slots_for_grown(params)
    assert emu.resolved == [2]


class _Stop(Exception):
    pass


def _recording_emu(seen):
    class FakeEmu:
        def __init__(self, gr_path, img_path):
            pass

        def boot(self):
            pass

        def warm_slots_for_grown(self, params, edited=()):
            seen.append(sorted(edited))
            raise _Stop()           # all this test needs

        def close(self):
            pass
    return FakeEmu


def test_the_single_process_encoder_warms_the_sounds_it_encodes(monkeypatch):
    from pinball_decryptor.plugins.stern import engine
    from pinball_decryptor.plugins.stern.spike2 import emulator

    seen = []
    monkeypatch.setattr(emulator, "Spike2Emu", _recording_emu(seen))
    byidx = {i: _p(i, body_off=0x1000 * i) for i in (2, 3, 4)}
    with pytest.raises(_Stop):
        engine._encode_cat0_serial("gr", "img", byidx,
                                   [(4, "a.wav"), (2, "b.wav")], None,
                                   lambda *a, **k: None, None, lambda: False)
    assert seen == [[2, 4]]


def test_an_encode_worker_warms_the_sounds_it_is_handed(monkeypatch):
    from pinball_decryptor.plugins.stern.spike2 import emulator, parallel

    seen = []
    monkeypatch.setattr(emulator, "Spike2Emu", _recording_emu(seen))
    params = [_p(i, body_off=0x1000 * i) for i in (2, 3)]
    with pytest.raises(_Stop):
        parallel.init_encode_worker("gr", "img", params, {}, [3])
    assert seen == [[3]]
