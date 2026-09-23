"""PAD-176 — "not enough free space" now says how much and what.

A modder's build replaced 542 videos and grew the sound bank for about seven
minutes of longer music.  It ran for twenty-odd minutes and then died on the
card's data partition with nothing but "Not enough free space ... They keep
their stock content on the card", which left him guessing whether he was over
by a megabyte or a gigabyte, and which of his 542 clips to blame.

The grow scripts had computed the shortfall all along and thrown it away.  Now
the numbers and the biggest files come back with the failure, because the
partition is a fixed size and the only possible answer is to take something
out.
"""

from pinball_decryptor.core import ext4_grow


def test_the_message_says_how_far_over_the_build_is():
    msg = ext4_grow.no_space_message(
        need=1_500_000_000, avail=300_000_000,
        items=[(400_000_000, "godzilla_pro/data/image.bin"),
               (3_000_000, "godzilla_pro/video/attract.mov")])
    assert "1200 MB over" in msg
    assert "grows files by 1500 MB" in msg
    assert "300 MB free" in msg
    # the biggest offenders, largest first
    assert "godzilla_pro/data/image.bin (+400 MB)" in msg
    assert msg.index("image.bin") < msg.index("attract.mov")


def test_only_the_five_biggest_are_named():
    items = [(n * 1_000_000, "video/clip%02d.mov" % n) for n in range(1, 21)]
    msg = ext4_grow.no_space_message(need=1, avail=0, items=items)
    assert msg.count("video/clip") == 5
    assert "clip20.mov (+20 MB)" in msg
    assert "clip15.mov" not in msg


def test_without_numbers_it_says_what_it_always_said():
    """A failure before the accounting ran, or an older script: no invented
    figures, just the plain sentence."""
    msg = ext4_grow.no_space_message()
    assert msg.startswith("Not enough free space on the card's data partition")
    assert "over" not in msg


def test_the_numbers_are_read_back_out_of_the_script_output():
    """Shaped like the real thing: per-file lines on stdout during the
    accounting pass, then the refusal on stderr."""
    text = (
        "PAD_GROW_ITEM 412000000 godzilla_pro/data/image.bin\n"
        "PAD_GROW_ITEM 2500000 godzilla_pro/video/ATTRACT_LOOP1.mov\n"
        "PAD_GROW_ITEM 1900000 godzilla_pro/video/magnagrab.mp4\n"
        "PAD_GROW_ENOSPC need=1500000000 avail=300000000\n")
    need, avail, items = ext4_grow.parse_space_report(text)
    assert (need, avail) == (1500000000, 300000000)
    assert len(items) == 3
    assert (412000000, "godzilla_pro/data/image.bin") in items

    msg = ext4_grow.no_space_message(need, avail, items)
    assert "1200 MB over" in msg
    assert "godzilla_pro/data/image.bin (+412 MB)" in msg


def test_output_with_no_markers_reports_nothing():
    for text in ("", None, "cp: cannot stat 'x': No such file or directory"):
        assert ext4_grow.parse_space_report(text) == (None, None, [])


def test_both_scripts_emit_the_per_file_line():
    """The accounting pass is where the per-file growth is known, and both
    routes onto a card run one."""
    wsl = ext4_grow._bash_script(
        1048576, [("godzilla_pro/video/a.mov", "/tmp/a.mov")], "/tmp/card.raw")
    assert 'echo "PAD_GROW_ITEM $d' in wsl
    assert wsl.index("PAD_GROW_ITEM") < wsl.index("PAD_GROW_ENOSPC")

    pinned = ext4_grow._pinned_script(
        1048576, [("godzilla_pro/video/a.mov", "/tmp/a.mov")], "/tmp/card.raw",
        epoch=1700000000)
    assert 'echo "PAD_GROW_ITEM $d' in pinned
    assert "godzilla_pro/video/a.mov" in pinned
    assert "@REL@" not in pinned, "the placeholder must be filled in"
