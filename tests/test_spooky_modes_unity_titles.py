"""Custom modes on the other five Spooky Unity titles (PAD-1418): Beetlejuice, Texas Chainsaw
Massacre, Evil Dead, Halloween and Ultraman.  Their updates carry no launch line, so the runtime
comes in through the update's own Mono config (dllmap); their ports, the update build in their
containers and layouts, and the app's half (which update and extract is which title).  The
runtime itself is proven on the Spooky rig (docs/plans/spooky_modes.md, ticket 2).
"""
import io
import json
import os
import re
import tarfile

import pytest

from pinball_decryptor.plugins.spooky import custom_modes as SM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNITY = os.path.join(ROOT, "tools", "spooky_emu", "modes", "unity")
TITLES = {
    "beetlejuice-2026.09.15.11": ("Beetlejuice", "gpg_signed", "v2026.09.15.11.beetlejuice", "beetlejuice"),
    "texas_chainsaw-1.00": ("Texas Chainsaw Massacre", "tar.gz", "tcm-1_00.pkg", "texas_chainsaw"),
    "evil_dead-2026.07.15": ("Evil Dead", "tar.gz", "2026.07.15.ed", "evil_dead"),
    "halloween_78-1.18.1": ("Halloween", "gpg_symmetric", "code_H78.pkg", "halloween_78"),
    "ultraman-1.18": ("Ultraman", "gpg_symmetric", "code_UM.pkg", "ultraman"),
}
MONO = ('<configuration>\n\t<dllmap dll="libc" target="libc.so.6" os="!windows"/>\n'
        '\t<dllmap dll="MonoPosixHelper" target="libMonoPosixHelper.so" os="!windows" />\n'
        '\t<dllmap dll="libmono-btls-shared" target="libmono-btls-shared.so" os="!windows" />\n</configuration>\n')
PLACEHOLDER = re.compile(r"(?i)^(switch_\d+|_no_switch_\d+|unused.*)$")


@pytest.fixture
def mk():
    return SM.mk()


@pytest.fixture
def modes_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_SPOOKY_MODES_DIR", str(tmp_path / "modes"))
    return tmp_path / "modes"


def _tar(path, members):
    with tarfile.open(path, "w:gz") as t:
        for name, data in members:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o755
            t.addfile(ti, io.BytesIO(data))


def _read(path):
    out = {}
    with tarfile.open(path, "r:gz") as t:
        for ti in t:
            out[ti.name] = t.extractfile(ti).read() if ti.isfile() else None
    return out


# ------------------------------------------------------------------ the ports
@pytest.mark.parametrize("label", sorted(TITLES))
def test_each_title_has_its_port_and_runtime(label, mk):
    port = SM.load_port(label)
    title, container, update, game = TITLES[label]
    assert port["title"] == title and port["game"] == game and port["engine"] == "unity"
    assert port["load"] == "dllmap" and port["update_container"] == container
    assert port["update_name"] == update
    # read by the runtime in the running game, the empty slots left out
    assert port["switches"] and not [s for s in port["switches"] if PLACEHOLDER.match(s)]
    assert set(port["switch_ids"]) == set(port["switches"]) == set(port["switch_labels"])
    assert len(port["sounds"]) > 400 and set(port["sound_paths"]) == set(port["sounds"])
    assert port["lamps"] and port["game_modes"] and port["fonts"]
    # measured in the game: the runtime's award is what the mode says, unrounded
    assert port["points_scale"] == 1 and port["points_round"] == 0
    d = port["defaults"]
    assert set(d["start"].split() + d["shots"].split()) <= set(port["switches"])
    assert {d[k] for k in ("sound_start", "sound_shot", "sound_complete", "sound_end")} <= set(port["sounds"])
    assert {d["font_title"], d["font_value"]} <= set(port["fonts"])
    so, dll = mk.runtime_files(port)
    assert os.path.basename(so) == "padunity_dllmap.so" and os.path.isfile(so) and os.path.isfile(dll)
    if container == "gpg_symmetric":
        assert port["gpg_format"] in ("h78_pkg", "um_pkg")
    t = {x["label"]: x for x in SM.titles()}[label]
    assert t["can_run"], t["why"]


@pytest.mark.parametrize("label", sorted(TITLES))
def test_each_titles_starter_modes_pass_the_check(label, modes_dir, mk):
    d = SM.title_dir(label)
    modes, problems = mk.check_modes(d, SM.load_port(label))
    assert problems == [] and len(modes) == 2
    v = SM.read_mode(label, SM.new_mode(label, "Fresh"))
    assert v["start"] == SM.load_port(label)["defaults"]["start"]


def test_every_glue_gives_the_core_what_it_calls():
    """The core (PadModes.cs) calls Glue.X and Hook on every title: each framework's glue file
    must define them all (build.sh compiles core + one glue)."""
    with open(os.path.join(UNITY, "PadModes.cs"), encoding="utf-8") as f:
        core = f.read()
    called = set(re.findall(r"\bGlue\.([A-Za-z]+)\b", core))
    assert {"Ready", "Ensure", "Poll", "Switches", "Award", "Voice", "VoiceChannel"} <= called
    with open(os.path.join(UNITY, "build.sh"), encoding="utf-8") as f:
        build = f.read()
    glues = sorted(set(re.findall(r"GLUE=(glue_[a-z]+\.cs)", build)))
    assert glues == ["glue_bj.cs", "glue_ed.cs", "glue_pc.cs", "glue_scooby.cs"]
    for g in glues:
        with open(os.path.join(UNITY, g), encoding="utf-8") as f:
            src = f.read()
        assert "public class Hook : Mode" in src and "public static class Glue" in src, g
        for name in called:
            assert re.search(r"public (?:const string|static [\w<>, \[\]]+) %s\b" % name, src), (g, name)


def test_every_title_has_its_prebuilt_runtime(mk):
    for label in list(TITLES) + ["scooby_doo-2025.12.01.09"]:
        so, dll = mk.runtime_files(SM.load_port(label))
        with open(dll, "rb") as f:
            assert f.read(2) == b"MZ", label
        with open(so, "rb") as f:
            assert f.read(4) == b"\x7fELF", label


# ------------------------------------------------------------------ the way in
def test_the_mono_config_maps_the_serial_library_to_the_runtime(mk):
    text, n = mk.patch_mono_config(MONO)
    assert n == 1
    assert '<dllmap dll="MonoPosixHelper" target="/game/code/uptest/pad/padunity.so" os="!windows" />' in text
    assert '<dllmap dll="libc" target="libc.so.6"' in text and 'target="libmono-btls-shared.so"' in text
    again, n2 = mk.patch_mono_config(text)
    assert again == text and n2 == 1                       # a modes update built again: once
    assert mk.patch_mono_config("<configuration/>")[1] == 0


def test_only_the_titles_own_way_in_is_patched(mk):
    dll, pre = SM.load_port("evil_dead-2026.07.15"), SM.load_port("scooby_doo-2025.12.01.09")
    cfg = "uptest/main_Data/MonoBleedingEdge/etc/mono/config"
    assert mk.patch_file(cfg, MONO.encode(), dll)[1] == 1
    assert mk.patch_file("./" + cfg, MONO.encode(), dll)[1] == 1
    assert mk.patch_file("main_Data/MonoBleedingEdge/etc/mono/config", MONO.encode(), dll)[1] == 1   # Beetlejuice's layout
    assert mk.patch_file("uptest/config/config", MONO.encode(), dll)[1] == 0      # another file called config
    assert mk.patch_file(cfg, MONO.encode(), pre)[1] == 0                          # Scooby-Doo: its launch line
    sway = b"exec --no-startup-id /game/code/uptest/main.x86_64\n"
    assert mk.patch_file("sway_config", sway, dll)[1] == 0 and mk.patch_file("sway_config", sway, pre)[1] == 1
    assert mk.pad_dir_for(["./assets/x", "./uptest/main.x86_64"]) == "uptest/pad"
    assert mk.pad_dir_for(["./main.x86_64"]) == "pad"


# ------------------------------------------------------------------ the build
def _uptest_update(path, config=MONO):
    members = [("./uptest/main.x86_64", b"ELF"), ("./uptest/UnityPlayer.so", b"ELF"),
               ("./assets/sound/voice/x.wav", b"RIFF"), ("./config/lightconfig.json", b"{}"),
               ("./uptest/pad/old.mode", b"from an older build")]
    if config is not None:
        members.append(("./uptest/main_Data/MonoBleedingEdge/etc/mono/config", config.encode()))
    _tar(path, members)


def test_build_puts_the_runtime_beside_the_game_and_maps_it_in(tmp_path, modes_dir, mk):
    label = "evil_dead-2026.07.15"
    port = SM.load_port(label)
    stock = tmp_path / "stock" / "2026.07.15.ed"
    stock.parent.mkdir()
    _uptest_update(str(stock))
    out = tmp_path / "new" / "2026.07.15.ed"
    out.parent.mkdir()
    logs = []
    mk.build(str(stock), SM.title_dir(label), str(out), port, log=logs.append)
    got = _read(str(out))
    assert b'target="/game/code/uptest/pad/padunity.so"' in got["./uptest/main_Data/MonoBleedingEdge/etc/mono/config"]
    so, dll = mk.runtime_files(port)
    assert got["uptest/pad/padunity.so"] == open(so, "rb").read()          # the dllmap loader
    assert got["uptest/pad/PadModes.dll"] == open(dll, "rb").read()
    assert b"points_scale = 1" in got["uptest/pad/modes/title.cfg"]
    assert "uptest/pad/modes/1_groovy.mode" in got and "./uptest/pad/old.mode" not in got
    assert got["./assets/sound/voice/x.wav"] == b"RIFF" and got["./uptest/main.x86_64"] == b"ELF"
    assert any("MonoPosixHelper is now" in s for s in logs)
    assert not [p for p in os.listdir(out.parent) if p.endswith(".partial")]
    bare = tmp_path / "bare.ed"
    _uptest_update(str(bare), config=None)
    with pytest.raises(mk.Refused, match="no MonoPosixHelper dllmap"):
        mk.build(str(bare), SM.title_dir(label), str(tmp_path / "x.ed"), port, log=lambda s: None)
    assert not [p for p in os.listdir(tmp_path) if p.endswith(".partial")]


def test_build_unwraps_and_wraps_the_titles_container(tmp_path, modes_dir, mk, monkeypatch):
    """Halloween's update is encrypted with the game's passphrase, Beetlejuice's signed: the build
    takes the tar.gz out with the plugin's own GPG code and puts the new one back the same way."""
    gpg, games = mk._spooky_gpg()
    calls = []

    def fake_decrypt(src, dst, passphrase, progress_cb=None):
        calls.append(("decrypt", passphrase))
        with open(src, "rb") as f, open(dst, "wb") as g:
            g.write(f.read()[4:])

    def fake_encrypt(src, dst, passphrase, progress_cb=None):
        calls.append(("encrypt", passphrase))
        with open(src, "rb") as f, open(dst, "wb") as g:
            g.write(b"GPG!" + f.read())
    monkeypatch.setattr(gpg, "decrypt_gpg_symmetric", fake_decrypt)
    monkeypatch.setattr(gpg, "encrypt_gpg_symmetric", fake_encrypt)
    label = "halloween_78-1.18.1"
    port = SM.load_port(label)
    inner = tmp_path / "inner.tar.gz"
    _uptest_update(str(inner))
    stock = tmp_path / "code_H78.pkg"
    stock.write_bytes(b"GPG!" + inner.read_bytes())
    out = tmp_path / "PAD modes" / "code_H78.pkg"
    out.parent.mkdir()
    mk.build(str(stock), SM.title_dir(label), str(out), port, log=lambda s: None)
    pw = games.GPG_PASSPHRASES["h78_pkg"]
    assert calls == [("decrypt", pw), ("encrypt", pw)]
    data = out.read_bytes()
    assert data[:4] == b"GPG!"
    plain = tmp_path / "plain.tar.gz"
    plain.write_bytes(data[4:])
    got = _read(str(plain))
    assert "uptest/pad/modes/1_trick_or_treat.mode" in got
    assert sorted(os.listdir(tmp_path)) == sorted(["PAD modes", "code_H78.pkg", "inner.tar.gz", "modes", "plain.tar.gz"])

    signed = []
    monkeypatch.setattr(gpg, "strip_gpg_signature", lambda s, d, progress_cb=None: (
        signed.append("strip"), open(d, "wb").write(open(s, "rb").read()[4:])))
    monkeypatch.setattr(gpg, "sign_beetlejuice", lambda s, d, progress_cb=None: (
        signed.append("sign"), open(d, "wb").write(b"SIG!" + open(s, "rb").read())))
    bj = SM.load_port("beetlejuice-2026.09.15.11")
    inner2 = tmp_path / "bj.tar.gz"
    _tar(str(inner2), [("./main.x86_64", b"ELF"), ("./_profile", b"sway\n"),
                       ("./main_Data/MonoBleedingEdge/etc/mono/config", MONO.encode())])
    stock2 = tmp_path / "v2026.09.15.11.beetlejuice"
    stock2.write_bytes(b"SIG!" + inner2.read_bytes())
    out2 = tmp_path / "PAD modes" / stock2.name
    mk.build(str(stock2), SM.title_dir("beetlejuice-2026.09.15.11"), str(out2), bj, log=lambda s: None)
    assert signed == ["strip", "sign"]
    plain2 = tmp_path / "plain2.tar.gz"
    plain2.write_bytes(out2.read_bytes()[4:])
    got2 = _read(str(plain2))
    assert "pad/padunity.so" in got2 and b"pad/padunity.so" in got2["./main_Data/MonoBleedingEdge/etc/mono/config"]
    assert got2["./_profile"] == b"sway\n"                 # the launcher is not how it gets in


# ------------------------------------------------------------------ the app's half
@pytest.mark.parametrize("label", sorted(TITLES))
def test_the_card_is_the_title_even_with_no_date_in_its_name(label, tmp_path):
    name = TITLES[label][2]
    f = tmp_path / name
    f.write_bytes(b"\x1f\x8b" + b"\0" * 30)
    assert SM.label_for_card(str(f)) == label


def test_the_stock_update_is_found_by_its_name_and_size(tmp_path):
    label = "halloween_78-1.18.1"
    size = SM.load_port(label)["update_size"]
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "code_H78.pkg").write_bytes(b"x" * 10)            # another build under the same name
    assert SM.find_stock(label, [str(lib)]) == ""
    with open(lib / "code_H78.pkg", "wb") as f:
        f.truncate(size)
    assert SM.find_stock(label, [str(lib)]) == str(lib / "code_H78.pkg")
    (lib / "2026.07.15.ed").write_bytes(b"x")
    assert SM.find_stock("evil_dead-2026.07.15", [str(lib)]) == str(lib / "2026.07.15.ed")


@pytest.mark.parametrize("game,files,label", [
    ("Halloween", {"uptest/version_118.txt": "", "uptest/main.x86_64": "ELF"}, "halloween_78-1.18.1"),
    ("Ultraman", {"uptest/version_1_18.txt": "", "uptest/main.x86_64": "ELF"}, "ultraman-1.18"),
    ("Texas Chainsaw Massacre", {"version.txt": "TCM V1.00\n", "uptest/main.x86_64": "ELF"}, "texas_chainsaw-1.00"),
    ("Evil Dead", {"version.txt": "2026.07.15.ed \n", "uptest/main.x86_64": "ELF"}, "evil_dead-2026.07.15"),
    ("Beetlejuice", {"version.txt": "v2026.09.15.11\n", "main.x86_64": "ELF"}, "beetlejuice-2026.09.15.11"),
    ("Halloween", {"uptest/version_119.txt": "", "uptest/main.x86_64": "ELF"}, ""),
])
def test_the_extract_is_the_title(tmp_path, game, files, label):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    assert SM.label_for_extract(str(tmp_path), {"game": game}) == label


def test_the_write_tab_carries_the_modes_beside_an_uptest_game(tmp_path, modes_dir):
    from pinball_decryptor.plugins.spooky import formats
    label = "ultraman-1.18"
    SM.title_dir(label)
    ex = tmp_path / "extract"
    cfg = ex / "uptest" / "main_Data" / "MonoBleedingEdge" / "etc" / "mono" / "config"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(MONO)
    (ex / "uptest" / "main.x86_64").write_bytes(b"ELF")
    (ex / "uptest" / "version_1_18.txt").write_text("")
    (ex / "config").mkdir()
    (ex / "config" / "config").write_text("not mono's")
    (ex / "uptest" / "pad").mkdir()
    (ex / "uptest" / "pad" / "stale.txt").write_text("old")
    assert SM.label_for_extract(str(ex), {"game": "Ultraman"}) == label
    pm = SM.write_pad_modes(label, str(ex))
    assert pm[2] == "uptest/pad"
    out = tmp_path / "code_UM.tar.gz"
    formats.create_tar_gz(str(ex), str(out), pad_modes=pm)
    got = {k.replace("\\", "/"): v for k, v in _read(str(out)).items()}
    assert b'target="/game/code/uptest/pad/padunity.so"' in got["uptest/main_Data/MonoBleedingEdge/etc/mono/config"]
    assert got["config/config"] == b"not mono's"
    assert "uptest/pad/modes/1_kaiju_strike.mode" in got and "uptest/pad/padunity.so" in got
    assert "uptest/pad/stale.txt" not in got and "pad/padunity.so" not in got


def test_write_takes_modes_for_every_container_the_titles_come_in(tmp_path, monkeypatch):
    """The Write pipeline hands the modes to the signed (Beetlejuice) and encrypted (Halloween,
    Ultraman) builds as well as the plain tar.gz."""
    from pinball_decryptor.plugins.spooky import pipeline
    seen = []
    monkeypatch.setattr(pipeline, "create_tar_gz", lambda src, out, progress_cb=None, pad_modes=None: (
        seen.append(pad_modes), open(out, "wb").close()))
    monkeypatch.setattr(pipeline, "encrypt_gpg_symmetric", lambda *a, **k: open(a[1], "wb").close())
    monkeypatch.setattr(pipeline, "sign_beetlejuice", lambda *a, **k: open(a[1], "wb").close())
    wp = pipeline.WritePipeline.__new__(pipeline.WritePipeline)
    import threading
    wp.assets_dir, wp.output_path, wp._cancelled = str(tmp_path), str(tmp_path / "out.pkg"), threading.Event()
    wp.pad_modes = ("files", "rewrite", "uptest/pad")
    wp.log = lambda *a, **k: None
    wp.progress = lambda *a, **k: None
    assert wp._build_gpg_symmetric_pkg("h78_pkg")
    assert wp._build_gpg_tar_gz()
    assert seen == [wp.pad_modes, wp.pad_modes]
