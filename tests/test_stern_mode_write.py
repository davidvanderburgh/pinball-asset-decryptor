"""Item 149: Write ships the project's modes - the planning half (plugins/stern/mode_write).

Desk only, no card and no emulator: the gates, the port check against a game program, which
record the end sound rides on, the manifest with the modes in it, the p2 payload and the
command that installs it, and what the log and change scan say. The asset build itself is
mode_assets' (tested there); here it is stubbed so the mapping of its outputs to card paths
is what is tested.
"""
import os
import struct

import pytest

# The mode maker ships dark behind a preview switch (core/preview.py); these tests are
# about what it does when it is ON (tests/test_preview_switch.py covers it OFF).
pytestmark = pytest.mark.usefixtures("preview_modes_on")

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_runtime as MR
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import sidx, sidx_append

GZ = MP.GODZILLA_PRO_1_15


# ---- gates ---------------------------------------------------------------------------------
def test_modes_are_on_unless_the_kill_switch_is_set(monkeypatch):
    # platform: a host that can carry modes, whatever runs the test (the macos-latest CI leg
    # is a Mac, where host_refusal says no - test_a_mac_cannot_carry_modes_and_says_why)
    ok = lambda: (True, "")                      # noqa: E731
    monkeypatch.delenv(MW.GATE_ENV, raising=False)
    assert MW.gate(False, ok, platform="linux") == (True, "")
    monkeypatch.setenv(MW.GATE_ENV, "0")
    closed, why = MW.gate(False, ok, platform="linux")
    assert not closed and "PAD_STERN_MODES=0" in why


def test_a_direct_sd_write_or_a_host_without_ext4_cannot_carry_modes(monkeypatch):
    monkeypatch.delenv(MW.GATE_ENV, raising=False)
    ok, why = MW.gate(True, lambda: (True, ""), platform="linux")
    assert not ok and "direct-SD" in why
    ok, why = MW.gate(False, lambda: (False, "no WSL"), platform="win32")
    assert not ok and "no WSL" in why


def test_the_host_gate_follows_the_running_platform(monkeypatch):
    """With no *platform* the gate reads ``sys.platform`` - a Mac refuses, anything else asks
    the ext4 driver. Pinned both ways, so the test means the same on every CI leg."""
    import types
    monkeypatch.delenv(MW.GATE_ENV, raising=False)
    for host, want in (("darwin", (False, MW.MAC_REFUSAL)), ("linux", (True, ""))):
        monkeypatch.setattr(MW, "sys", types.SimpleNamespace(platform=host))
        assert MW.host_refusal() == ("" if want[0] else MW.MAC_REFUSAL)
        assert MW.gate(False, lambda: (True, "")) == want


def test_a_mac_cannot_carry_modes_and_says_why(monkeypatch):
    """On macOS ext4_grow.available() says yes once Homebrew's e2fsprogs is installed, but a mode
    build's delivery (grow_files_pinned and mode_install.py through the Mac executor) finds no
    debugfs on its PATH and runs GNU ``stat -c%s``: no whole file lands while the in-place
    firmware writes do, and the dialog said "Wrote". The gate refuses modes there first, with a
    sentence, and never asks the ext4 driver."""
    monkeypatch.delenv(MW.GATE_ENV, raising=False)

    def never():
        raise AssertionError("the ext4 check is not asked on a Mac")
    ok, why = MW.gate(False, never, platform="darwin")
    assert not ok and why == MW.MAC_REFUSAL
    assert "Mac" in why and "Windows or Linux" in why
    assert MW.host_refusal("darwin") == MW.MAC_REFUSAL
    for host in ("win32", "linux"):
        assert MW.host_refusal(host) == ""
        assert MW.gate(False, lambda: (True, ""), platform=host) == (True, "")
    # the kill switch and a device write keep their own reasons on a Mac too
    assert "direct-SD" in MW.gate(True, never, platform="darwin")[1]
    monkeypatch.setenv(MW.GATE_ENV, "0")
    assert "PAD_STERN_MODES=0" in MW.gate(False, never, platform="darwin")[1]


def test_the_own_end_sound_ships_by_default(monkeypatch):
    monkeypatch.delenv(MW.SOUND_ENV, raising=False)
    assert MW.sound_gate() == (True, "")
    monkeypatch.setenv(MW.SOUND_ENV, "0")
    assert MW.sound_gate()[0] is False


def test_a_project_without_modes_has_none_and_a_broken_one_is_named(tmp_path):
    assert MW.project_modes(str(tmp_path)) == []
    MP.new_mode(str(tmp_path), "KAIJU RUSH")
    bad = tmp_path / "modes" / "broken"
    bad.mkdir()
    (bad / "mode.json").write_text("{not json")
    with pytest.raises(MW.ModeWriteError, match="broken"):
        MW.project_modes(str(tmp_path))


# ---- the port check --------------------------------------------------------------------------
def _elf(words_at, base=0x10000, size=0x2000):
    """A 32-bit ELF with one executable PT_LOAD holding *words_at* {va: (w0, w1)}."""
    body = bytearray(size)
    for va, (w0, w1) in words_at.items():
        struct.pack_into("<II", body, va - base, w0, w1)
    hdr = bytearray(0x34 + 32)
    hdr[:4] = b"\x7fELF"
    hdr[4] = 1
    struct.pack_into("<I", hdr, 0x1C, 0x34)
    struct.pack_into("<HH", hdr, 0x2A, 32, 1)
    struct.pack_into("<8I", hdr, 0x34, 1, len(hdr), base, base, size, size, 5, 0x1000)
    return bytes(hdr) + bytes(body)


def _port(path, sites):
    with open(path, "w") as f:
        f.write("game godzilla_pro\nversion 1.15\n")
        for name, va, w0, w1 in sites:
            f.write("site %-12s 0x%08x 0x%08x 0x%08x\n" % (name, va, w0, w1))


def test_a_port_matches_only_the_program_it_was_measured_on(tmp_path, monkeypatch):
    sites = [("tick", 0x10100, 0xe92d4038, 0xe3a00037), ("callout", 0x10200, 1, 2)]
    good = tmp_path / "godzilla_pro-1.15.port"
    _port(good, sites)
    elf = _elf({0x10100: (0xe92d4038, 0xe3a00037), 0x10200: (1, 2)})
    assert MW.site_mismatches(str(good), elf) == []
    assert MW.site_mismatches(str(good), _elf({0x10100: (0xe92d4038, 0xe3a00037)})) == ["callout"]
    monkeypatch.setattr(MR, "ports", lambda: [("godzilla_pro", "1.15"), ("turtles_pro", "1.58")])
    monkeypatch.setattr(MR, "port_file", lambda g, v: str(good) if g == "godzilla_pro" else None)
    assert MW.find_port(GZ, elf) == str(good)
    with pytest.raises(MW.ModeWriteError, match="1 of 2 functions differ"):
        MW.find_port(GZ, _elf({0x10100: (0xe92d4038, 0xe3a00037)}))


def test_the_shipped_godzilla_port_is_parsed_whole():
    path = MR.port_file("godzilla_pro", "1.15")
    names = [s[0] for s in MW.port_sites(path)]
    assert "tick" in names and "sound_lookup" in names and len(names) >= 20


# ---- which record the end sound rides on -------------------------------------------------------
def _site(sid, payload):
    from pinball_decryptor.plugins.stern import engine
    return engine._DescSite(sid, 0x1000 + sid, b"\x00" * 8, payload, 0x0ff9 + sid, b"\x00" * 4, 100)


def test_the_time_up_request_resolves_to_one_record_under_the_builds_mask(monkeypatch):
    mask = 0xFC0003FF
    key = struct.pack("<II", 0xb9c44a28, 0x980001af)
    payload = struct.pack("<II", 0xb9c44a28, 0x980001af | 0x00ff0000)   # bits the mask drops
    params = [{"idx": 1560, "findkey": key}, {"idx": 7, "findkey": struct.pack("<II", 1, 2)}]
    monkeypatch.setattr(MW, "request_sids", lambda elf, head, req: [1998] if req == 1295 else [])
    assert MW.request_record(b"", b"", params, [_site(1998, payload)], 1295, mask) == 1560
    with pytest.raises(MW.ModeWriteError, match="no sound for request 1291"):
        MW.request_record(b"", b"", params, [_site(1998, payload)], 1291, mask)
    stranger = struct.pack("<II", 0x12345678, 0x980001af)
    with pytest.raises(MW.ModeWriteError, match="not one sound record"):
        MW.request_record(b"", b"", params, [_site(1998, stranger)], 1295, mask)


def test_a_params_cache_with_only_the_first_key_word_still_resolves(monkeypatch):
    """Measured on the first real build: the cached Godzilla Pro 1.15 params carry
    ``key0`` and no whole ``findkey``, and the chain found no record. The first word is
    what the grow path's own named-by-a-descriptor check matches on."""
    payload = struct.pack("<II", 0xb9c44a28, 0x980001af)
    params = [{"idx": 1560, "key0": 0xb9c44a28}, {"idx": 7, "key0": 0x11}]
    monkeypatch.setattr(MW, "request_sids", lambda elf, head, req: [1998])
    assert MW.request_record(b"", b"", params, [_site(1998, payload)], 1295, 0xE0001FFF) == 1560
    params.append({"idx": 8, "key0": 0xb9c44a28})
    with pytest.raises(MW.ModeWriteError, match="not one sound record"):
        MW.request_record(b"", b"", params, [_site(1998, payload)], 1295, 0xE0001FFF)


# ---- the plan ----------------------------------------------------------------------------------------
def _project(tmp_path, sound_for=()):
    project = str(tmp_path / "project")
    for name, spec in MP.example_specs()[:2]:
        slug, _s = MP.new_mode(project, spec=spec)
        if name in sound_for:
            folder = MP.mode_folder(project, slug)
            with open(os.path.join(folder, "end.wav"), "wb") as f:
                f.write(b"RIFF")
            spec = MP.load(os.path.join(folder, MP.MODE_FILE))
            spec.end_sound = "end.wav"
            MP.save(project, slug, spec)
    return project


def _stub_build(monkeypatch):
    from pinball_decryptor.plugins.stern import mode_assets as MA

    def build(project, hud, bank, out_dir, ffmpeg=None, only=None, **_code):
        res = MA.ModeBuild(out_dir=out_dir)
        hud_rel = "%s/%s/scene.radium" % (MA.LCD, GZ.hud_scene)
        bank_rel = "%s/%s/scene.radium" % (MA.LCD, GZ.bank_scene)
        clips = ["%s/%s/scene.assets/2.asset/%d.asset" % (MA.LCD, GZ.bank_scene, n) for n in (598, 599)]
        for rel, data in [(hud_rel, hud + b"+screens"), (bank_rel, bank + b"+clips")] + \
                [(c, b"clip") for c in clips]:
            p = os.path.join(out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
            res.files.append(rel)
        res.new_files += clips
        for slot, (slug, spec) in enumerate(MP.list_modes(project)[0]):
            name = MA.mode_file_name(slot)
            p = os.path.join(out_dir, "padmode", name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(MP.runtime_cfg(spec, slug))
            res.mode_files.append(name)
            res.slots.append((slot, slug, spec.name))
        return res
    monkeypatch.setattr(MA, "build", build)


def test_the_plan_maps_the_build_to_card_paths_and_names_the_port(tmp_path, monkeypatch):
    project = _project(tmp_path, sound_for=("KAIJU RUSH",))
    _stub_build(monkeypatch)
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: "/ports/godzilla_pro-1.15.port")
    plan = MW.plan(project, b"HUD", b"BANK", b"ELF", str(tmp_path / "scratch"), ffmpeg="ffmpeg")
    auto = "godzilla_pro/assets/lcd/auto_loaded/"
    assert [r for r, _s in plan.replaced] == [auto + GZ.hud_scene + "/scene.radium",
                                              auto + GZ.bank_scene + "/scene.radium"]
    assert [r for r, _s in plan.new] == [auto + GZ.bank_scene + "/scene.assets/2.asset/598.asset",
                                         auto + GZ.bank_scene + "/scene.assets/2.asset/599.asset"]
    assert open(plan.replaced[0][1], "rb").read() == b"HUD+screens"
    assert [n for n, _p in plan.mode_files] == ["mode.cfg", "mode1.cfg"]
    assert plan.port.endswith("godzilla_pro-1.15.port")
    assert plan.end_sound["name"] == "KAIJU RUSH" and plan.end_sound["request"] == 1295
    assert plan.end_sound["wav"].endswith("end.wav")
    assert plan.jobs == plan.replaced + plan.new
    assert plan.lines[0].startswith("ATOMIC BREATH: its own screen") or \
        plan.lines[0].startswith("KAIJU RUSH")
    text = " | ".join(plan.lines)
    assert "its own end sound end.wav" in text and "mode file mode1.cfg" in text


def test_a_project_without_modes_plans_nothing(tmp_path):
    assert MW.plan(str(tmp_path), b"", b"", b"", str(tmp_path / "s")) is None


def test_one_end_sound_per_card_and_the_gate_closes_it(tmp_path):
    project = _project(tmp_path, sound_for=("KAIJU RUSH", "ATOMIC BREATH"))
    modes = MW.project_modes(project)
    said = []
    got = MW.choose_end_sound(project, modes, (True, ""), lambda m, lvl="info": said.append(m))
    assert got["name"] == modes[0][1].name
    assert any("a card carries one" in m for m in said)
    said.clear()
    assert MW.choose_end_sound(project, modes, (False, "PAD_STERN_MODE_SOUND=0"),
                               lambda m, lvl="info": said.append(m)) is None
    assert "PAD_STERN_MODE_SOUND=0" in said[0]


def test_the_change_scan_promises_only_the_end_sound_a_card_carries(tmp_path, monkeypatch):
    """ONE own end sound per card, none with the sound gate closed - the scan's wording follows
    the build's decision, and a mode without a sound of its own says whose it ends on."""
    monkeypatch.delenv(MW.SOUND_ENV, raising=False)
    both = _project(tmp_path / "a", sound_for=("KAIJU RUSH", "ATOMIC BREATH"))
    lines = dict(line.split(": ", 1) for line in MW.pending_lines(both))
    first, second = [spec.name for _s, spec in MW.project_modes(both)]
    assert "its own end sound end.wav" in lines[first]
    assert "time-up call now plays too" in lines[first]
    assert "its own end sound" not in lines[second]
    assert "another mode's end sound (a card carries one): %s's" % first in lines[second]

    one = _project(tmp_path / "b", sound_for=("KAIJU RUSH",))
    lines = dict(line.split(": ", 1) for line in MW.pending_lines(one))
    assert "its own end sound end.wav" in lines["KAIJU RUSH"]
    assert "KAIJU RUSH's end sound when it ends" in lines["ATOMIC BREATH"]

    monkeypatch.setenv(MW.SOUND_ENV, "0")
    lines = dict(line.split(": ", 1) for line in MW.pending_lines(one))
    assert "its own end sound end.wav" not in lines["KAIJU RUSH"]
    assert "the game's own time-up call (its own end sound is not on this card)" in lines["KAIJU RUSH"]
    assert "end sound" not in lines["ATOMIC BREATH"]
    assert MW.pending_lines(str(tmp_path / "empty")) == []


def test_conflicts_name_the_scene_and_the_sound(tmp_path, monkeypatch):
    project = _project(tmp_path)
    _stub_build(monkeypatch)
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: "/p")
    plan = MW.plan(project, b"H", b"B", b"E", str(tmp_path / "s"), ffmpeg="ffmpeg")
    hud, bank = MW.scene_rels(GZ)
    assert MW.conflicts(plan) == []
    got = MW.conflicts(plan, touched_rels=["/" + hud], audio_idx=[1560, 3], sound_idx=1560)
    assert len(got) == 2 and "HUD scene" in got[0] and "sound idx 1560" in got[1]


# ---- the manifest ---------------------------------------------------------------------------------
def _manifest(paths_and_sizes, fmt="FI64"):
    from tests.test_stern_sidx_append import _build
    return _build(paths_and_sizes, fmt=fmt)


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_compose_manifest_refreshes_folds_and_appends(tmp_path, fmt):
    stock = _manifest([("g/game", 100), ("g/image.bin", 1000), ("g/hud/scene.radium", 50)], fmt)
    hud = tmp_path / "hud"
    hud.write_bytes(b"h" * 80)
    clip = tmp_path / "clip"
    clip.write_bytes(b"c" * 30)
    recs, _c, _f = sidx.parse_records(stock)
    # another edit's in-place refresh of image.bin, grown to 1200, at stock offsets
    hm, md = sidx.digests(b"x")
    inplace = sidx.record_field_writes(recs["g/image.bin"], hm, md, fmt, size=1200)
    out = MW.compose_manifest(stock, inplace=inplace, refreshed=[("g/hud/scene.radium", str(hud))],
                              new=[("g/bank/598.asset", str(clip))], expect_paths=["g/game"])
    assert sidx_append.verify(out, expect_paths=["g/bank/598.asset"]) == []
    assert sidx_append.size_total(out) == 100 + 1200 + 80 + 30
    files = sidx.manifest_files(out)
    assert files["g/image.bin"][0] == 1200 and files["g/hud/scene.radium"][0] == 80
    assert files["g/bank/598.asset"] == (30, sidx.digests(b"c" * 30)[1].hex())
    assert list(files)[-1] == "g/bank/598.asset"


def test_compose_manifest_refuses_a_record_it_does_not_have(tmp_path):
    stock = _manifest([("g/game", 100)])
    f = tmp_path / "f"
    f.write_bytes(b"1")
    with pytest.raises(MW.ModeWriteError, match="no record for g/nope"):
        MW.compose_manifest(stock, refreshed=[("g/nope", str(f))])
    with pytest.raises(MW.ModeWriteError, match="already has a record"):
        MW.compose_manifest(stock, new=[("g/game", str(f))])


# ---- the system partition ------------------------------------------------------------------------------
def test_the_p2_payload_is_the_pinned_object_the_mode_files_and_the_port(tmp_path, monkeypatch):
    project = _project(tmp_path)
    _stub_build(monkeypatch)
    port = tmp_path / "godzilla_pro-1.15.port"
    port.write_text("game godzilla_pro\n")
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: str(port))
    plan = MW.plan(project, b"H", b"B", b"E", str(tmp_path / "s"), ffmpeg="ffmpeg")
    pay = MW.p2_payload(plan, str(tmp_path / "p2"))
    assert open(pay["so"], "rb").read() == open(MR.prebuilt_object(), "rb").read()
    assert [os.path.basename(c) for c in pay["cfgs"]] == ["mode.cfg", "mode1.cfg"]
    assert open(pay["cfgs"][1]).read() == open(plan.mode_files[1][1]).read()
    assert open(pay["port"]).read() == "game godzilla_pro\n"


class _Ex:
    def __init__(self):
        self.ran = []

    def to_exec_path(self, p):
        return "/x/" + os.path.basename(p)

    def run(self, cmd, timeout=0):
        self.ran.append(cmd)
        return "[mode] installed game.port, mode.cfg, mode.so, mode1.cfg into /usr/local/padmode\n"


def test_the_install_runs_mode_install_with_the_clock_pinned():
    ex = _Ex()
    pay = {"so": "a/mode.so", "cfgs": ["a/mode.cfg", "a/mode1.cfg"], "port": "a/game.port"}
    said = []
    line = MW.install_p2("C:/b/card.raw", pay, 1662343945, lambda m, lvl="info": said.append(m), executor=ex)
    cmd = ex.ran[0]
    assert "E2FSPROGS_FAKE_TIME=1662343945 python3 mode_install.py install /x/card.raw" in cmd
    assert "--cfg /x/mode.cfg --cfg /x/mode1.cfg --port /x/game.port" in cmd
    assert line.startswith("[mode] installed") and said
    assert os.path.isfile(os.path.join(MW.tools_dir(), "mode_install.py"))


def test_a_code_mode_is_named_as_not_reaching_the_card(tmp_path):
    """Item 127's New code mode (modes/<slug>/<slug>.c, no mode file) runs in Try it only: Write
    ships the pinned runtime, so the build and the change scan say the code mode is left out."""
    project = _project(tmp_path)
    folder = os.path.join(MP.modes_dir(project), "blitz")
    os.makedirs(folder)
    with open(os.path.join(folder, "blitz.c"), "w") as f:
        f.write("/* a mode */\n")
    assert MW.code_modes(project) == ["blitz"]
    assert [s for s, _m in MW.project_modes(project)] == ["atomic_breath", "kaiju_rush"]
    assert "code mode(s) blitz are not put on the card" in MW.code_modes_note(["blitz"])
    assert MW.code_modes(str(tmp_path / "none")) == []


# ---- item 150's own sounds on a card (start, shot, music) -----------------------------------
def _sounds_project(tmp_path, sounds):
    """The two example modes, each given the own sounds in *sounds* {mode name: {field: wav}}."""
    project = str(tmp_path / "project")
    for name, spec in MP.example_specs()[:2]:
        slug, _s = MP.new_mode(project, spec=spec)
        folder = MP.mode_folder(project, slug)
        spec = MP.load(os.path.join(folder, MP.MODE_FILE))
        for field_name, wav in sounds.get(name, {}).items():
            with open(os.path.join(folder, wav), "wb") as f:
                f.write(b"RIFF")
            setattr(spec, field_name, wav)
        MP.save(project, slug, spec)
    return project


def test_own_sounds_ride_on_distinct_carriers_and_the_end_sound_keeps_its_request(tmp_path):
    project = _sounds_project(tmp_path, {
        "ATOMIC BREATH": {"sound_start": "go.wav", "music": "theme.wav"},
        "KAIJU RUSH": {"sound_shot": "hit.wav", "music": "roar.wav", "end_sound": "end.wav"}})
    modes = MW.project_modes(project)
    said = []
    log = lambda m, lvl="info": said.append(m)         # noqa: E731
    end = MW.choose_end_sound(project, modes, (True, ""), log)
    assert end["name"] == "KAIJU RUSH" and end["request"] == 1295
    own = MW.choose_own_sounds(project, modes, (True, ""), end_sound=end, log=log)
    calls = MS_calls("godzilla_pro", "1.15")
    beds = MS_beds("godzilla_pro", "1.15")
    assert [(o["name"], o["key"], o["request"], o.get("sid")) for o in own] == [
        ("ATOMIC BREATH", "sound_start", calls[0], None), ("ATOMIC BREATH", "music", 125, beds[0]),
        ("KAIJU RUSH", "sound_shot", calls[1], None), ("KAIJU RUSH", "music", 125, beds[1])]
    assert own[0]["wav"].endswith("go.wav") and own[1]["music"] and not own[0]["music"]
    # no call carrier twice; the music carrier holds no sound itself, each music has its own bed
    calls_used = [o["request"] for o in own if not o["music"]]
    assert len(set(calls_used) | {1295}) == len(calls_used) + 1
    assert len({o["sid"] for o in own if o["music"]}) == 2
    assert not any("music is not put on this card" in m for m in said), said
    # a carrier already chosen (here as if the end sound rode on the first call) is skipped
    moved = MW.choose_own_sounds(project, modes, (True, ""), end_sound={"request": calls[0]})
    assert moved[0]["request"] == calls[1]
    # the sound gate closes them all, and says so
    said.clear()
    assert MW.choose_own_sounds(project, modes, (False, "PAD_STERN_MODE_SOUND=0"), log=log) == []
    assert "PAD_STERN_MODE_SOUND=0" in said[0] and "not put on the card" in said[0]
    # no own sound of that kind: nothing chosen, nothing said
    bare = _sounds_project(tmp_path / "bare", {})
    said.clear()
    assert MW.choose_own_sounds(bare, MW.project_modes(bare), (True, ""), log=log) == [] and not said


def MS_calls(game, version):
    from pinball_decryptor.plugins.stern import mode_sounds as MS
    return list(MS.TITLES[(game, version)].calls)


def MS_beds(game, version):
    from pinball_decryptor.plugins.stern import mode_sounds as MS
    return list(MS.TITLES[(game, version)].beds)


def test_a_title_without_measured_carriers_leaves_the_own_sounds_out(tmp_path):
    project = str(tmp_path / "project")
    tmnt = MP.profile("turtles_pro_1_59")
    slug, _s = MP.new_mode(project, "LOUD", MP.ModeSpec(
        name="LOUD", title=tmnt.key, start_shot=tmnt.example_start_shot,
        scoring_shots=[n for n, _m in tmnt.shots][:1], screen=False, clip="none"))
    folder = MP.mode_folder(project, slug)
    with open(os.path.join(folder, "go.wav"), "wb") as f:
        f.write(b"RIFF")
    spec = MP.load(os.path.join(folder, MP.MODE_FILE))
    spec.sound_start = "go.wav"
    MP.save(project, slug, spec)
    said = []
    assert MW.choose_own_sounds(project, MW.project_modes(project), (True, ""),
                                log=lambda m, lvl="info": said.append(m)) == []
    assert "no stock requests to carry them have been measured for TMNT Pro 1.59" in said[0]


def test_the_scan_and_the_plan_name_each_carried_sound_or_say_it_is_left_out(tmp_path, monkeypatch):
    monkeypatch.delenv(MW.SOUND_ENV, raising=False)
    project = _sounds_project(tmp_path, {
        "ATOMIC BREATH": {"sound_start": "go.wav", "music": "theme.wav"},
        "KAIJU RUSH": {"music": "roar.wav"}})
    lines = dict(line.split(": ", 1) for line in MW.pending_lines(project))
    calls = MS_calls("godzilla_pro", "1.15")
    assert "its own start sound go.wav (request %d)" % calls[0] in lines["ATOMIC BREATH"]
    beds = MS_beds("godzilla_pro", "1.15")
    assert "its own music theme.wav (request 125, its own bed: sound id %d)" % beds[0] in lines["ATOMIC BREATH"]
    # item 150 follow-up: a second mode's music has a bed of its own too
    assert "its own music roar.wav (request 125, its own bed: sound id %d)" % beds[1] in lines["KAIJU RUSH"]
    # the plan: the carried sounds' modes name their carriers in their mode files
    _stub_build(monkeypatch)
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: "/ports/godzilla_pro-1.15.port")
    used = [{"slug": "atomic_breath", "name": "ATOMIC BREATH", "key": "sound_start",
             "request": calls[0], "idx": 7, "ms": 480},
            {"slug": "atomic_breath", "name": "ATOMIC BREATH", "key": "music", "request": 125,
             "idx": 9, "ms": None}]
    plan = MW.plan(project, b"HUD", b"BANK", b"ELF", str(tmp_path / "scratch"), ffmpeg="ffmpeg",
                   end_sound=None, own_sounds=used)
    cfg = dict((n, open(p, encoding="utf-8").read()) for n, p in plan.mode_files)
    assert "sound_start    %d 480" % calls[0] in cfg["mode.cfg"]
    assert "music          125" in cfg["mode.cfg"]
    assert "sound_start" not in cfg["mode1.cfg"] and "music " not in cfg["mode1.cfg"]
    text = " | ".join(plan.lines)
    assert "its own start sound go.wav (request %d)" % calls[0] in text
    assert "KAIJU RUSH: " in text and "not its own music" in text
    assert MW.own_cfg_args(project, "atomic_breath", None, used) == (
        {"sound_start": calls[0], "music": 125}, {"sound_start": 480})
    assert MW.own_cfg_args(project, "kaiju_rush", None, used) == (None, None)
    # what Try it's tab reads back from a set's record
    assert MW.own_sounds_by_slug(used) == {"atomic_breath": {
        "requests": {"sound_start": calls[0], "music": 125}, "ms": {"sound_start": 480}}}


def test_the_log_and_the_scan_never_promise_a_screen_or_a_clip_the_title_cannot_add(
        tmp_path, monkeypatch):
    """Item 149's loose end: a mode SAVED on Godzilla, with a screen and a 4 s title clip,
    put in a TMNT Pro 1.59 project gets neither - TMNT's port has no screen or clip
    functions, so ``mode_assets.build`` skips both - and neither the build log nor the Write
    change scan may say it adds them. The scan reads the card's title from the project's own
    record, so it is right while mode.json still says Godzilla; the log reads the retargeted
    mode :func:`card_modes` hands it. Jaws LE 1.02 can add a clip but no screen."""
    import json
    monkeypatch.delenv(MW.SOUND_ENV, raising=False)
    tmnt = MP.profile("turtles_pro_1_59")
    project = str(tmp_path / "proj")
    os.makedirs(project)
    card = "turtles_pro-1_59_0.Release.8G.sdcard.raw"
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": "D:\\cards\\" + card, "input_name": card,
                   "size": 1, "mtime": 1, "card_version": "1.59.0"}, f)
    _name, spec = MP.example_specs()[0]
    assert (spec.title, spec.screen, spec.clip) == (GZ.key, True, "title")
    MP.new_mode(project, spec=spec)
    screen, clip = "its own screen in the game's HUD scene", "title-card clip"
    left_out = ("not its own screen (TMNT Pro 1.59 cannot add one)",
                "not its own clip (TMNT Pro 1.59 cannot add one)")

    line = MW.pending_lines(project)[0]                  # the Write change scan
    assert screen not in line and clip not in line, line
    assert all(w in line for w in left_out), line

    moved, _dropped = MP.retarget(spec, tmnt)            # the build log, after card_modes
    line = MW.describe([("m", moved)])[0]
    assert screen not in line and clip not in line, line
    assert all(w in line for w in left_out), line

    # the lines follow the title, not one blanket refusal: Jaws takes the clip and not the
    # screen, and on the mode's own Godzilla both are still promised
    line = MW.describe([("m", spec)], prof=MP.profile("jaws_le_1_02"))[0]
    assert screen not in line and clip in line, line
    assert "not its own screen (Jaws LE 1.02 cannot add one)" in line, line
    line = MW.describe([("m", spec)])[0]
    assert screen in line and clip in line and "not its own" not in line, line
