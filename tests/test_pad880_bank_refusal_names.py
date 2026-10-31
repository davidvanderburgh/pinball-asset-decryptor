"""PAD-880: a card whose longer songs pass what the machine holds beside image.bin is refused
naming the user's own file, every bank that can play beside it, and how much the longer
sounds have to lose all told.

An Iron Maiden card with a dozen replaced songs was refused as "The game's idx 70 (played in
parts by sound id(s) 957, 959)"; its maker looked those sound ids up, found stock sounds, and
cut half a gig of video (card space, not the machine's memory) to make room.

Fast, no card and no firmware (the PAD-606 planner fixtures).
"""
from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
from tests.test_pad606_game_sounds_in_banks import _Reader, _image, _rec

import pytest

MB = 1_000_000


def _plan(monkeypatch, tmp_path, mapped):
    img = _image(tmp_path)
    sizes = {i: (20 - i) * MB for i in range(1, 11)}      # ten songs, 19 MB down to 10 MB
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in sizes]
    grows = {i: (100, n // 4) for i, n in sizes.items()}
    audio_edits = {i: "C:/proj/audio/idx%04d - SONG %d.wav" % (i, i) for i in grows}
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(SB, "BANK_SLICE", 5 * MB)         # every song a bank of its own
    monkeypatch.setattr(SB, "MAPPED_MAX", mapped)
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(11)), 11,
                                                    0x9000, 0))
    return E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, dict(grows), [], _Reader(), None, None,
        lambda *a: None, game_sids={i: 500 + i for i in grows})


def test_the_refusal_names_the_users_file_the_banks_beside_it_and_what_to_cut(
        monkeypatch, tmp_path):
    # room for 100 MB: 19..14 MB fit (99 MB), the 13 MB idx 7 does not beside them
    with pytest.raises(RuntimeError) as got:
        _plan(monkeypatch, tmp_path, 100 * MB)
    msg = str(got.value)
    # the user's own file by name, not "the game's idx" alone
    assert msg.startswith("Your idx0007 - SONG 7.wav for the game's sound id 507 (idx 7) is "
                          "too long for this card")
    # the banks that can play beside it, by the user's file names
    assert "beside the 6 other bank(s) that can play with it (99 MB)" in msg
    lines = msg.split("best taken from the longest of them:\n")[1].split("\n\n")[0]
    assert lines.split("\n") == ["    %d MB  idx%04d - SONG %d.wav" % (20 - i, i, i)
                                 for i in range(1, 7)] + [
        "    13 MB  idx0007 - SONG 7.wav  (this one)"]
    # how much the longer sounds have to lose all told: the eight longest (19..12 MB, 124 MB)
    # with image.bin's head past the 100 MB
    over = int(msg.split("come to about ")[1].split(" MB less")[0])
    assert 24 <= over <= 26
    assert "removing videos or other files does not change it" in msg


def test_a_card_that_fits_is_not_refused(monkeypatch, tmp_path):
    plan, _e, _g = _plan(monkeypatch, tmp_path, 200 * MB)
    assert plan is not None and len(plan.banks) == 10


def test_the_refusal_reaches_the_write_failed_dialog_as_an_answer(monkeypatch):
    """Not "Unexpected error:" and a traceback: one error line in the log, the same words in
    the dialog (as the SD card size refusal is)."""
    from tests.test_stern_space_text_notes import _pipeline
    why = "Your s1.wav for the game's sound id 501 (idx 1) is too long for this card."
    p, logged, done = _pipeline(monkeypatch, E.SoundRoomError(why))
    p.run()
    assert [t for t, lvl in logged if lvl == "error"] == [why]
    assert done == [(False, why)]
