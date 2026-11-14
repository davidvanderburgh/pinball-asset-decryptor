"""tools/spike3_emu/mks3multi.py, the Spike 3 multi-boot card builder (PAD-1263), the
parts that need no root and no card: the games partition's new layout (laid out on a plain
folder here; the builder does it on the card's mounted games partition), the menu's
images.conf, the default titles, the refusals, and dmcrypt's read-only mapping the builder
reads source cards through.  The whole build is proven on real cards in the emulator
(tools/spike3_emu/MULTIBOOT.md); the hook's cases are
tools/spike2_emu/codeselect/test/padselect_s3_test.sh.
"""
import importlib.util
import os
import struct
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    spec = importlib.util.spec_from_file_location(
        "mks3multi_u", os.path.join(ROOT, "tools", "spike3_emu", "mks3multi.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mk = _load()


def _can_symlink(tmp_path):
    try:
        os.symlink("x", str(tmp_path / ".probe"))
        os.unlink(str(tmp_path / ".probe"))
        return True
    except (OSError, NotImplementedError):
        return False


def _stock_tree(d, title="pokemon_le"):
    """A Spike 3 card's /games as Stern ships it."""
    (d / title / "spike3" / "bin").mkdir(parents=True)
    (d / title / "data").mkdir()
    (d / title / "game").write_bytes(b"\x7fELF game")
    (d / title / "conagent").write_bytes(b"\x7fELF conagent")
    (d / "spk").mkdir()
    (d / "spk" / "index.sidx").write_bytes(b"sidx")
    (d / "lost+found").mkdir()
    for name in ("game", "conagent", "data", "spike3"):
        os.symlink("%s/%s" % (title, name), str(d / name))


def _selector(d):
    d.mkdir()
    (d / "s3select").write_bytes(b"\x7fELF menu")
    (d / "padselect.sh").write_bytes(b"#!/bin/sh\n")
    (d / "font.ttf").write_bytes(b"ttf")
    return str(d)


def test_the_games_partition_is_laid_out_for_the_menu(tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("symlinks need privileges on this Windows")
    games = tmp_path / "games"
    games.mkdir()
    _stock_tree(games)
    sel = _selector(tmp_path / "sel")
    conf = mk.render_conf(["img0", "img1"], ["A", "B"], ["a", "b"], 0, 15, [], None, None, 50,
                          footer=mk.FOOTER)
    mk._lay_out(str(games), conf, sel, None, None, {"tool": mk.TOOL})
    mk._link_top(str(games))
    pad = games / "pad"
    # image 0's tree moved WHOLE under pad/img0, its own links still pointing inside it
    assert os.readlink(str(pad / "img0" / "game")) == "pokemon_le/game"
    assert (pad / "img0" / "pokemon_le" / "game").read_bytes() == b"\x7fELF game"
    assert (pad / "img0" / "spk" / "index.sidx").exists()
    # lost+found stays where the filesystem keeps it
    assert (games / "lost+found").is_dir() and not (pad / "img0" / "lost+found").exists()
    # the top level: the hook, and links into img0 for what runs before the menu
    for name, target in mk.TOP_LINKS.items():
        assert os.readlink(str(games / name)) == target, name
    assert os.readlink(str(games / "game")) == "pad/padselect.sh"
    assert sorted(p.name for p in games.iterdir()) == sorted(
        ["lost+found", "pad"] + list(mk.TOP_LINKS))
    # the menu beside the trees
    for name in ("s3select", "padselect.sh", "font.ttf", "images.conf", "build.json"):
        assert (pad / name).is_file(), name
    if os.name == "posix":
        assert os.access(str(pad / "padselect.sh"), os.X_OK) and os.access(str(pad / "s3select"), os.X_OK)
    # and a resolved img0 game is image 0's program
    assert (games / "pad" / "img0" / "game").resolve().read_bytes() == b"\x7fELF game"


def test_a_card_already_multi_boot_is_refused(tmp_path):
    games = tmp_path / "games"
    (games / "pad").mkdir(parents=True)
    with pytest.raises(mk.Refused, match="already has a /games/pad"):
        mk._lay_out(str(games), "", _selector(tmp_path / "sel"), None, None, {})


def test_a_tree_without_a_game_is_refused(tmp_path):
    games = tmp_path / "games"
    (games / "something").mkdir(parents=True)
    with pytest.raises(mk.Refused, match="no `game` link"):
        mk._lay_out(str(games), "", _selector(tmp_path / "sel"), None, None, {})


def test_images_conf_names_the_trees_and_the_coin_door():
    conf = mk.render_conf(["img0", "img1"], ["FALLOUT LE 0.81.0", "FALLOUT LE 0.82.0"],
                          ["Stock", "Newer code"], 1, 20, [], None, None, 50, footer=mk.FOOTER)
    lines = conf.splitlines()
    assert "image=img0|FALLOUT LE 0.81.0|Stock" in lines
    assert "image=img1|FALLOUT LE 0.82.0|Newer code" in lines
    assert "default=1" in lines and "timeout=20" in lines
    assert any(ln.startswith("footer=") and "NEXT" in ln and "SELECT" in ln for ln in lines)
    # the menu's font is the one the Spike 3 build bakes in (/games/pad/font.ttf), so no font= line
    assert not any(ln.startswith("font=") for ln in lines)
    parsed = mk.parse_conf(conf)
    assert [p for p, _t, _s in parsed["images"]] == ["img0", "img1"]


def test_media_lines_point_at_the_cards_pad_folder():
    conf = mk.render_conf(["img0", "img1"], ["A", "B"], ["", ""], 0, 15,
                          [("art0.png", "", "", ""), ("", "", "", "")], None, None, 50)
    assert "media=/games/pad/media" in conf.splitlines()


def test_conf_from_the_tabs_flags_and_the_default_titles():
    cards = [SimpleNamespace(label=lambda: "FALLOUT LE 0.81.0", path="/x/fallout_le-0_81_0_spike3.Release.raw"),
             SimpleNamespace(label=lambda: "FALLOUT LE 0.82.0", path="/x/fallout_le-0_82_0_spike3.Release.raw")]
    a = SimpleNamespace(conf=None, titles=None, subtitles=None, volume=None, footer=None, footer_own=False,
                        default=0, timeout=None, theme=None, color=None, heading=None, text_size=None,
                        counter=None, countdown_word=None)
    conf = mk.conf_from_args(a, cards, None).splitlines()
    assert "image=img0|FALLOUT LE 0.81.0|Stock" in conf
    assert "image=img1|FALLOUT LE 0.82.0|fallout_le-0_82_0_spike3" in conf
    assert "timeout=15" in conf
    a.titles, a.subtitles, a.timeout = "One;Two", "x;y", 0
    conf = mk.conf_from_args(a, cards, None).splitlines()
    assert "image=img1|Two|y" in conf and "timeout=0" in conf


def test_a_card_is_read_from_its_ext4_superblock(monkeypatch, tmp_path):
    """plan's sizes: blocks and free blocks from the games volume's superblock."""
    sb = bytearray(1024)
    struct.pack_into("<I", sb, 0x04, 1000)       # blocks
    struct.pack_into("<I", sb, 0x0C, 400)        # free
    struct.pack_into("<I", sb, 0x18, 2)          # 4096-byte blocks
    struct.pack_into("<H", sb, 0x38, 0xEF53)

    class Vol:
        part_offset, segment_offset = 1 << 20, 16 << 20
        part = {"sectors": 100000}
        master_key = b"k" * 64

        def seek(self, n):
            pass

        def read(self, n):
            return bytes(sb)

        def close(self):
            pass
    img = tmp_path / "fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw"
    img.write_bytes(b"\0" * 4096)
    card_mod = SimpleNamespace(open_games=lambda path, key_source=None: Vol(),
                               image_id=lambda p: os.path.basename(p).split(".", 1)[0])
    monkeypatch.setattr(mk, "_card_mod", lambda: card_mod)
    monkeypatch.setattr(mk, "_key_source", lambda kf, p: None)
    c = mk.Card(str(img))
    assert c.block == 4096 and c.fs_bytes == 1000 * 4096 and c.used == 600 * 4096
    assert (c.title, c.version) == ("fallout_le", "0.82.0")
    assert c.label() == "FALLOUT LE 0.82.0"


def test_two_of_the_same_card_and_one_card_are_refused():
    with pytest.raises(mk.Refused, match="at least two"):
        mk._inputs(SimpleNamespace(primary="/a.raw", extra=[], keyfile=None))
    with pytest.raises(mk.Refused, match="twice"):
        mk._inputs(SimpleNamespace(primary="/a.raw", extra=["/a.raw"], keyfile=None))


def test_dmcrypt_maps_a_source_card_read_only(monkeypatch):
    from pinball_decryptor.core import dmcrypt
    calls = []

    def fake_call(nr, buf):
        calls.append((nr, struct.unpack(dmcrypt._DM_FMT, buf[:dmcrypt._DM_SIZE])[7]))
        return buf[:dmcrypt._DM_SIZE]
    monkeypatch.setattr(dmcrypt, "_call", fake_call)
    monkeypatch.setattr(dmcrypt.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(dmcrypt.os, "mknod", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(dmcrypt.os, "makedev", lambda a, b: 0, raising=False)
    monkeypatch.setattr(dmcrypt.os, "unlink", lambda *a, **k: None)
    for ro in (True, False):
        calls.clear()
        dmcrypt.open_crypt("t", "/dev/loop9", 32768, 1000, b"\0" * 64, readonly=ro)
        load = [f for nr, f in calls if nr == dmcrypt._TABLE_LOAD]
        assert load and bool(load[0] & dmcrypt._READONLY_FLAG) is ro
