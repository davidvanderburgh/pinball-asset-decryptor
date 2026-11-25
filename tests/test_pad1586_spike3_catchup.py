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


# ---- the Spike 3 Test card (run 2) ---------------------------------------------------------------
import importlib.util                                                   # noqa: E402
import os                                                               # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mks3():
    spec = importlib.util.spec_from_file_location(
        "mks3multi_1586", os.path.join(ROOT, "tools", "spike3_emu", "mks3multi.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_spike3_test_card_conf_is_the_test_card_menu():
    mk = _mks3()
    media = {"rows": [], "volume": 50, "test_files": {"test0.png": "x"},
             "tests": [("test0.png", "LOGO", "image", None), ("test1.padv", "CLIP", "video", None)]}
    text = mk.testcard_conf(media, None)
    lines = text.splitlines()
    assert "image=img0|TEST CARD|color profile and test pictures" in lines
    assert "testcard=on" in lines and "timeout=0" in lines
    assert "test_dir=/games/pad/testcard" in lines
    assert any(l.startswith("color_profile=0|") and l.endswith("|No change") for l in lines)
    # the test lines are the ones mkmulticard writes for a Spike 2 test card (one menu reads both)
    mkc = mk.mkc
    for l in mkc.conf_test_lines(media["tests"]):
        assert l in lines
    # no test files: no test_dir, still the test card menu
    bare = mk.testcard_conf(None, None).splitlines()
    assert "testcard=on" in bare and not any(l.startswith("test_dir=") for l in bare)


def test_spike3_test_card_refuses_sounds(monkeypatch, tmp_path):
    mk = _mks3()
    monkeypatch.setattr(mk, "_need_root", lambda: None)
    monkeypatch.setattr(mk.mkc, "PNG_MAX", mk.mkc.PNG_MAX)      # the build raises it in its process
    monkeypatch.setattr(mk, "Card", lambda path, keyfile=None: types.SimpleNamespace(path=path))
    monkeypatch.setattr(mk.mkc, "plan_media", lambda d, n, tests_apart=False: {
        "tests": [("t.wav", "TONE", "sound", None)], "files": {}, "rows": [], "volume": 50})
    a = types.SimpleNamespace(primary="c.raw", keyfile=None, media_dir=str(tmp_path), color=None,
                              selector_dir=str(tmp_path), out=str(tmp_path / "o.raw"), force=False,
                              workdir=None)
    with pytest.raises(mk.Refused, match="plays no sound"):
        mk.testcard_card(a)


def test_spike3_build_work_dir_falls_back_to_the_card_store_disk(monkeypatch, tmp_path):
    mk = _mks3()
    small, big = tmp_path / "var" / "pad_s3multi", tmp_path / "cards" / "pad_s3multi"
    (tmp_path / "var").mkdir()
    (tmp_path / "cards").mkdir()
    monkeypatch.setattr(mk, "WORKDIRS", (str(small), str(big)))
    free = {str(small): 38 << 30, str(big): 120 << 30}
    monkeypatch.setattr(mk.shutil, "disk_usage",
                        lambda d: types.SimpleNamespace(free=free[os.path.abspath(d)]))
    assert mk._work_dir(None, 62 << 30) == str(big)
    assert mk._work_dir(None, 10 << 30) == str(small)
    with pytest.raises(mk.Refused, match="no Linux folder has room"):
        mk._work_dir(None, 200 << 30)
    # --workdir is the one asked for, or a refusal: never another
    with pytest.raises(mk.Refused):
        mk._work_dir(str(small), 62 << 30)


def test_test_card_commands_take_the_spike3_route(monkeypatch):
    from pinball_decryptor.webui import multiboot_core as mbc
    from pinball_decryptor.webui import spike3_key
    monkeypatch.setattr(spike3_key, "find_keyfile", lambda *a, **k: r"C:\Users\x\.pad\spike3_padkeys.json")
    form = types.SimpleNamespace(images=[types.SimpleNamespace(path=r"D:\cards\fallout_le-0_82_0_spike3.raw")],
                                 volume=50, selector_dir=mbc.backend_for("s3").selector_default, tests=[],
                                 platform="s3", colour_profiles={})
    cmds = mbc.testcard_commands(form, r"C:\tmp\tc.raw", r"C:\tmp\media",
                                 test_specs=["--test", "image:/mnt/c/a.png|A"])
    labels = [l for l, _a in cmds]
    assert labels == ["selector", "prepare", mbc.TESTCARD_LABEL]
    prep = [a for l, a in cmds if l == "prepare"][0]
    prep_text = " ".join(map(str, prep)) if isinstance(prep, (list, tuple)) else repr(prep)
    assert "--test" in prep_text and "image:/mnt/c/a.png|A" in prep_text
    # a Spike 2 form keeps mkmulticard's test card
    form2 = types.SimpleNamespace(**dict(vars(form), platform="stern", selector_dir=mbc.DEFAULT_SELECTOR_DIR))
    cmds2 = mbc.testcard_commands(form2, r"C:\tmp\tc.raw", r"C:\tmp\media", test_specs=[])
    assert "mkmulticard.py" in repr(dict(cmds2)[mbc.TESTCARD_LABEL])


def test_s3_testcard_builder_argv(monkeypatch):
    from pinball_decryptor.webui import multiboot_core as mbc
    from pinball_decryptor.webui import spike3_key
    monkeypatch.setattr(spike3_key, "find_keyfile", lambda *a, **k: r"C:\Users\x\.pad\spike3_padkeys.json")
    seen = []
    monkeypatch.setattr(mbc, "root_command", lambda args, cwd=None, exe="python3": seen.append(list(args)) or args)
    form = types.SimpleNamespace(images=[types.SimpleNamespace(path=r"D:\cards\fallout.raw")], volume=50,
                                 selector_dir="", tests=[], platform="s3", colour_profiles={})
    mbc.testcard_commands(form, r"C:\tmp\tc.raw", r"C:\tmp\media", test_specs=[])
    argv = seen[-1]
    assert argv[:2] == [mbc.backend_for("s3").tool, "testcard"]
    assert argv[argv.index("--primary") + 1] == mbc.wsl(r"D:\cards\fallout.raw")
    assert argv[argv.index("--selector-dir") + 1] == "/var/tmp/s3select"
    assert argv[argv.index("--keyfile") + 1] == mbc.wsl(r"C:\Users\x\.pad\spike3_padkeys.json")


def test_test_card_source_spike3_detection(s3_disk, tmp_path):
    from pinball_decryptor.webui import testcard_core as tc
    assert tc.is_spike3_source(s3_disk) is True
    other = tmp_path / "spike2.raw"
    other.write_bytes(b"\0" * 4096)
    assert tc.is_spike3_source(str(other)) is False
    assert tc.is_spike3_source(str(tmp_path / "missing.raw")) is False


def test_spike3_test_pictures_are_fitted_to_its_1920x1080_screen(monkeypatch):
    from pinball_decryptor.webui import multiboot_core as mbc
    from pinball_decryptor.webui import spike3_key
    monkeypatch.setattr(spike3_key, "find_keyfile", lambda *a, **k: None)
    form = types.SimpleNamespace(images=[types.SimpleNamespace(path=r"D:\cards\fallout.raw")], volume=50,
                                 selector_dir="", tests=[], platform="s3", colour_profiles={})
    prep = repr(dict(mbc.testcard_commands(form, r"C:\tmp\tc.raw", r"C:\tmp\media", test_specs=[]))["prepare"])
    assert "--screen" in prep and "1920x1080" in prep
    form2 = types.SimpleNamespace(**dict(vars(form), platform="stern", selector_dir=mbc.DEFAULT_SELECTOR_DIR))
    prep2 = repr(dict(mbc.testcard_commands(form2, r"C:\tmp\tc.raw", r"C:\tmp\media", test_specs=[]))["prepare"])
    assert "--screen" not in prep2                       # Spike 2: the 1360x768 LCD, as before
    mk = _mks3()
    assert mk.SCREEN == (1920, 1080)


def test_selectmedia_screen_raises_the_test_picture_cap(tmp_path, monkeypatch):
    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, "tools", "spike2_emu"))
    import selectmedia as sm_
    monkeypatch.setattr(sm_, "TEST_PNG_MAX", (1360, 768))
    seen = {}

    def stop(a):
        seen["cap"] = sm_.TEST_PNG_MAX
        raise SystemExit(0)
    # cmd_prepare sets the cap first thing; stop it right after
    monkeypatch.setattr(sm_, "parse_size", lambda s: tuple(int(v) for v in s.split("x")))
    a = types.SimpleNamespace(screen="1920x1080")
    try:
        monkeypatch.setattr(sm_, "read_media_manifest", stop, raising=False)
        sm_.cmd_prepare(a)
    except (SystemExit, AttributeError, TypeError, KeyError):
        pass
    assert sm_.TEST_PNG_MAX == (1920, 1080)
