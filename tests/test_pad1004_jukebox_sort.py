"""PAD-1004: the Jukebox (and Sounds on shots) list sorts by a column title, and the titles stay in view.

The behaviour itself is proven in a browser by scripts/shot_pad1004.py (click Song, then How often:
most often first; again: rarest first; again: the jukebox's own order; scroll: the titles stay at the
top of the list); these keep the wiring from going missing.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "pinball_decryptor", "webui", "static")


def _read(*parts):
    with open(os.path.join(STATIC, *parts), encoding="utf-8") as f:
        return f.read()


def test_both_audio_windows_sort_by_their_column_titles():
    js = _read("js", "tabs", "audio.js")
    assert "function useColSort(rows, cols)" in js
    assert "useColSort(songs, JUKE_COLS)" in js and "useColSort(rows, SHOT_COLS)" in js
    for k in ("k", "audio", "video", "weight"):
        assert '<${Th} k="%s">' % k in js, k
    for k in ("k", "mode", "shot", "sound"):
        assert '<${Th} k="%s">' % k in js, k
    assert "${shown.map((g) =>" in js and "${shown.map((r) =>" in js
    assert re.search(r"weight: \{ val: \(g\) => Number\(g\.weight\), desc: true \}", js)   # most often first
    # a third click gives the list its own order back
    assert ": c.desc === !!cols[k].desc ? { key: k, desc: !c.desc } : null" in js


def test_moving_a_song_waits_for_the_lists_own_order():
    js = _read("js", "tabs", "audio.js")
    assert "disabled: d.running || sorted || (g.n ?? g.k) === 1" in js            # PAD-1007: its pool's first
    assert "disabled: d.running || sorted || (g.n ?? g.k) === songs.length" in js


def test_the_column_titles_stay_at_the_top_of_the_list():
    css = _read("css", "tabs", "audio.css")
    assert ".aud-juke thead th { position: sticky; top: 0;" in css
