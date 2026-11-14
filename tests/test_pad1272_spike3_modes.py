"""PAD-1272: custom modes written onto a Stern Spike 3 card's games partition.

spike3_modes puts the 64-bit runtime, the port and the mode files in /games/pad/padmode and
points /games/game at a hook that preloads the runtime into the game. These tests cover what
can be checked without a card: the card's state read off its games tree, the hook and the
install / remove steps (run in a real shell over a scratch folder where one is available),
the plan's gates, the Spike 3 Write's wiring, the 64-bit port check, and the rig's side.
The emulator run on a real card is the ticket's proof.
"""
import os
import shutil
import struct
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import spike3_modes as S3M
from tests._ext4_fake import FakeExt4Reader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Reader(FakeExt4Reader):
    def read_symlink(self, node):
        return bytes(node["i_block"][:node["size"]]).decode()


def _stock_tree(link="pokemon_le/game"):
    return {"game": ("symlink", link), "conagent": ("symlink", "pokemon_le/conagent"),
            "pokemon_le": {"game": b"\x7fELF\x02" + b"\0" * 64, "conagent": b"x"}}


# ---- the card's state ---------------------------------------------------------------------
def test_a_stock_card_names_its_game_link():
    assert S3M.card_state(_Reader(_stock_tree())) == ("stock", "pokemon_le/game")


def test_a_card_with_modes_gives_back_the_stock_link_it_kept():
    tree = _stock_tree(S3M.HOOK_LINK)
    tree["pad"] = {"padmode": {"game.target": b"pokemon_le/game\n", "mode.so": b"so",
                               "padmode.sh": S3M.HOOK_SCRIPT.encode()}}
    assert S3M.card_state(_Reader(tree)) == ("modes", "pokemon_le/game")


def test_a_multiboot_card_is_told_apart():
    assert S3M.card_state(_Reader(_stock_tree(S3M.MULTIBOOT_LINK)))[0] == "multiboot"


def test_a_card_with_no_game_link_is_unknown():
    assert S3M.card_state(_Reader({"x": b"1"})) == ("unknown", "")


def test_the_game_program_is_the_file_the_stock_link_names():
    r = _Reader(_stock_tree())
    assert S3M.game_program(r, "pokemon_le/game")["_data"].startswith(b"\x7fELF")
    assert S3M.game_program(r, "/games/pokemon_le/game") is not None
    assert S3M.game_program(r, "nope/game") is None


# ---- the hook -----------------------------------------------------------------------------
def test_the_hook_preloads_the_runtime_last_and_becomes_the_game():
    h = S3M.HOOK_SCRIPT
    assert h.startswith("#!/bin/sh\n")
    assert 'LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD:}$D/mode.so"' in h
    assert 'exec "$G" "$@"' in h            # game_monitor reads the game's own exit code
    assert "D=/games/pad/padmode" in h and "game.target" in h


def test_the_runtime_reads_its_files_where_the_install_puts_them():
    with open(os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk", "pad_mode.h")) as f:
        h = f.read()
    assert '#define PM_CARD_DIR "/games/pad/padmode/"' in h
    assert "/games/" + S3M.MODE_DIR + "/" in h


def _sh():
    """A POSIX shell that sees this machine's paths, or None. On Windows `bash` is WSL's,
    which sees C: as /mnt/c and none of this process's environment: skipped there (the
    ticket ran these under WSL)."""
    if sys.platform == "win32":
        return None
    return shutil.which("sh")


def _run_body(lines, mp):
    # chown needs root; the body's ownership is the machine's, not this test's
    script = "set -e\nMP=%s\nchown() { :; }\n%s\n" % (mp, "\n".join(lines))
    return subprocess.run([_sh(), "-c", script], capture_output=True, text=True)


@pytest.mark.skipif(_sh() is None, reason="needs a POSIX shell over this machine's paths")
def test_install_then_remove_leaves_the_games_tree_stock(tmp_path):
    mp = tmp_path / "games"
    (mp / "pokemon_le").mkdir(parents=True)
    (mp / "pokemon_le" / "game").write_bytes(b"ELF")
    os.symlink("pokemon_le/game", str(mp / "game"))
    so = tmp_path / "mode64.so"
    so.write_bytes(b"SO")
    cfg = tmp_path / "mode.cfg"
    cfg.write_text("mode")
    files = [("mode.so", str(so), 0o755), ("mode.cfg", str(cfg), 0o644)]
    out = _run_body(S3M.install_body(files, lambda p: p), str(mp))
    assert out.returncode == 0, out.stderr
    assert "PAD_MODE_OK pokemon_le/game" in out.stdout
    assert os.readlink(str(mp / "game")) == S3M.HOOK_LINK
    d = mp / "pad" / "padmode"
    assert (d / "game.target").read_text() == "pokemon_le/game\n"
    assert (d / "mode.so").read_bytes() == b"SO" and os.stat(str(d / "mode.so")).st_mode & 0o111
    assert (d / "padmode.sh").read_text() == S3M.HOOK_SCRIPT
    # a second build over it keeps the STOCK target, never the hook's own link
    out = _run_body(S3M.install_body(files[:1], lambda p: p), str(mp))
    assert out.returncode == 0, out.stderr
    assert (d / "game.target").read_text() == "pokemon_le/game\n"
    assert not (d / "mode.cfg").exists()          # the set is the new build's alone
    out = _run_body(S3M.remove_body(), str(mp))
    assert out.returncode == 0, out.stderr
    assert os.readlink(str(mp / "game")) == "pokemon_le/game"
    assert not (mp / "pad").exists()


@pytest.mark.skipif(_sh() is None, reason="needs a POSIX shell over this machine's paths")
def test_install_refuses_a_multiboot_card(tmp_path):
    mp = tmp_path / "games"
    mp.mkdir()
    os.symlink(S3M.MULTIBOOT_LINK, str(mp / "game"))
    out = _run_body(S3M.install_body([], lambda p: p), str(mp))
    assert out.returncode == 6 and "PAD_MODE_REFUSED multi-boot" in out.stderr
    assert os.readlink(str(mp / "game")) == S3M.MULTIBOOT_LINK


@pytest.mark.skipif(_sh() is None, reason="needs a POSIX shell over this machine's paths")
def test_the_hook_runs_the_game_with_the_runtime_preloaded(tmp_path):
    """The hook's text with /games swapped for a scratch tree: the game it execs sees
    LD_PRELOAD ending in the runtime, its arguments, and its exit code is the hook's."""
    g = tmp_path / "games"
    (g / "t").mkdir(parents=True)
    (g / "pad" / "padmode").mkdir(parents=True)
    game = g / "t" / "game"
    game.write_text('#!/bin/sh\necho "PRE=$LD_PRELOAD ARGS=$*"\nexit 7\n')
    game.chmod(0o755)
    (g / "pad" / "padmode" / "game.target").write_text("t/game\n")
    (g / "pad" / "padmode" / "mode.so").write_bytes(b"so")
    hook = tmp_path / "padmode.sh"
    hook.write_text(S3M.HOOK_SCRIPT.replace("/games", str(g)))
    out = subprocess.run([_sh(), str(hook), "a", "b"], capture_output=True, text=True,
                         env=dict(os.environ, LD_PRELOAD="/x/shim.so"))
    assert out.returncode == 7
    assert out.stdout.strip() == "PRE=/x/shim.so:%s/pad/padmode/mode.so ARGS=a b" % g
    # no target kept: the card's first game program runs, stock - never a dead machine
    (g / "pad" / "padmode" / "game.target").unlink()
    out = subprocess.run([_sh(), str(hook)], capture_output=True, text=True)
    assert out.returncode == 7


# ---- the plan's gates ---------------------------------------------------------------------
@pytest.fixture
def gates(monkeypatch):
    monkeypatch.setattr(MW, "preview_on", lambda: True)
    monkeypatch.setattr(MW, "project_modes", lambda p: [("m", type("S", (), {"name": "BLAST"})())])
    monkeypatch.setattr(MW, "code_mode_list", lambda p: [])
    monkeypatch.setattr(MW, "gate", lambda dest_is_device: (True, ""))
    monkeypatch.setattr(MW, "card_refusal", lambda p, real_card=False: "")


def _logged():
    said = []
    return said, (lambda m, kind="info": said.append((kind, m)))


def test_no_modes_no_plan(gates, monkeypatch, tmp_path):
    monkeypatch.setattr(MW, "project_modes", lambda p: [])
    assert S3M.plan("proj", _Reader(_stock_tree()), str(tmp_path)) is None


def test_a_build_with_no_port_leaves_the_modes_out_with_the_reason(gates, monkeypatch, tmp_path):
    monkeypatch.setattr(MW, "card_refusal", lambda p, real_card=False: "no port for this game")
    said, log = _logged()
    assert S3M.plan("proj", _Reader(_stock_tree()), str(tmp_path), log=log) is None
    assert any(k == "warning" and "left out of this build: no port for this game" in m
               for k, m in said)


def test_code_modes_are_left_out_of_a_spike3_build_and_said_so(gates, monkeypatch, tmp_path):
    monkeypatch.setattr(MW, "project_modes", lambda p: [])
    monkeypatch.setattr(MW, "code_mode_list", lambda p: [("c", object())])
    said, log = _logged()
    assert S3M.plan("proj", _Reader(_stock_tree()), str(tmp_path), log=log) is None
    assert any(S3M.CODE_MODES_WORDS in m for _k, m in said)


def test_a_multiboot_card_takes_no_modes(gates, tmp_path):
    said, log = _logged()
    assert S3M.plan("proj", _Reader(_stock_tree(S3M.MULTIBOOT_LINK)), str(tmp_path),
                    log=log) is None
    assert any(S3M.MULTIBOOT_WORDS in m for _k, m in said)


def test_a_card_whose_game_program_is_missing_stops_the_write(gates, tmp_path):
    with pytest.raises(MW.ModeWriteError, match="game program was not found"):
        S3M.plan("proj", _Reader({"game": ("symlink", "gone/game")}), str(tmp_path))


def test_the_plan_is_mode_writes_own_with_the_64_bit_runtime(gates, monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import mode_project as MP
    seen = {}
    monkeypatch.setattr(MP, "project_profile", lambda p, probe=False: (None, None))

    class _Result:
        replaced = [("pokemon_le/assets/lcd/auto_loaded/h/scene.radium", "/s/hud")]
        new = []
        lines = ["BLAST starts on 3 hits"]
        mode_names = ["BLAST"]

    def plan(project, hud, bank, elf, scratch, **kw):
        seen.update(kw, elf=elf)
        return _Result()

    def payload(result, out_dir, project=None, arch="arm"):
        seen["arch"] = arch
        return {"so": "/o/mode.so", "cfgs": ["/o/mode.cfg"], "port": "/o/game.port",
                "assets": [], "extras": [], "bundle": ""}
    monkeypatch.setattr(MW, "plan", plan)
    monkeypatch.setattr(MW, "p2_payload", payload)
    mp = S3M.plan("proj", _Reader(_stock_tree()), str(tmp_path))
    assert seen["arch"] == "a64" and seen["code_ok"] is False
    assert seen["own_sounds"] == () and seen["end_sound"] is None
    assert seen["elf"].startswith(b"\x7fELF\x02")       # the card's own 64-bit program
    assert mp.jobs == [("pokemon_le/assets/lcd/auto_loaded/h/scene.radium", "/s/hud")]
    assert [(n, m) for n, _p, m in mp.files()] == [("mode.so", 0o755), ("mode.cfg", 0o644),
                                                   ("game.port", 0o644)]


def test_try_it_plans_without_the_card_write_gate(gates, monkeypatch, tmp_path):
    monkeypatch.setattr(MW, "gate", lambda dest_is_device: (False, "no ext4 here"))
    seen = []
    monkeypatch.setattr(MW, "card_refusal",
                        lambda p, real_card=False: seen.append(real_card) or "stop here")
    S3M.plan("proj", _Reader(_stock_tree()), str(tmp_path), real_card=False)
    assert seen == [False]       # a derived port that never ran may run in the emulator


# ---- the Spike 3 Write --------------------------------------------------------------------
def test_a_card_with_modes_written_with_none_has_them_taken_off(monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import spike3_write as S3W
    monkeypatch.setattr(S3M, "plan", lambda *a, **k: None)
    tree = _stock_tree(S3M.HOOK_LINK)
    tree["pad"] = {"padmode": {"game.target": b"pokemon_le/game\n"}}
    assert S3W._plan_modes("proj", _Reader(tree), str(tmp_path), lambda *a: None) == (None, True)
    assert S3W._plan_modes("proj", _Reader(_stock_tree()), str(tmp_path),
                           lambda *a: None) == (None, False)


def test_a_mode_that_cannot_be_built_stops_the_write_before_the_copy(monkeypatch, tmp_path):
    from pinball_decryptor.core.pipeline_base import PipelineError
    from pinball_decryptor.plugins.stern import spike3_write as S3W

    def boom(*a, **k):
        raise MW.ModeWriteError("BLAST names a shot this game does not have")
    monkeypatch.setattr(S3M, "plan", boom)
    with pytest.raises(PipelineError, match="Nothing was written"):
        S3W._plan_modes("proj", _Reader(_stock_tree()), str(tmp_path), lambda *a: None)


def test_install_runs_its_steps_on_the_encrypted_volume(monkeypatch):
    from pinball_decryptor.core import ext4_grow
    got = {}

    def run(card, off, body, luks, size, timeout=900):
        got.update(card=card, off=off, luks=luks, size=size, lines=body(lambda p: "/x" + p))
        return "PAD_MODE_FILE mode.so\nPAD_MODE_FILE game.port\nPAD_MODE_OK pokemon_le/game\n"
    monkeypatch.setattr(ext4_grow, "run_on_luks", run)

    class _P:
        names = ["BLAST"]

        def files(self):
            return [("mode.so", "/so", 0o755), ("game.port", "/port", 0o644)]
    vol = {"key": b"k" * 64, "offset": 16 << 20, "sector_size": 512, "cipher": "aes-xts-plain64",
           "part_offset": 1 << 30, "part_size": 2 << 30}
    assert S3M.install("card.raw", vol, _P()) == 2
    assert got["off"] == 1 << 30 and got["size"] == 2 << 30 and got["luks"]["key"] == b"k" * 64
    text = "\n".join(got["lines"])
    assert "cp /x/so " in text and "chmod 755" in text and 'ln -sfn %s "$G"' % S3M.HOOK_LINK in text


def test_an_install_the_card_refuses_says_why(monkeypatch):
    from pinball_decryptor.core import ext4_grow

    def run(*a, **k):
        raise ext4_grow.Ext4GrowError("PAD_MODE_REFUSED multi-boot card\n")
    monkeypatch.setattr(ext4_grow, "run_on_luks", run)

    class _P:
        names = ["BLAST"]

        def files(self):
            return []
    with pytest.raises(MW.ModeWriteError, match="could not be put on the card: multi-boot card"):
        S3M.install("c", {"key": b"", "offset": 0, "sector_size": 512, "cipher": "x",
                          "part_offset": 0, "part_size": 1}, _P())


def test_the_dmcrypt_script_takes_a_body_in_place_of_the_copies():
    from pinball_decryptor.core import ext4_grow
    luks = {"key": b"\x01" * 64, "offset": 16 << 20, "sector_size": 512,
            "cipher": "aes-xts-plain64"}
    s = ext4_grow._bash_script_luks(0, (), "/c.raw", luks, 1 << 30, body=["echo BODY"])
    assert s.rstrip().endswith("echo BODY") and 'mount "$NODE" "$MP"' in s
    assert "PAD_GROW_DONE" not in s
    assert "PAD_GROW_DONE" in ext4_grow._bash_script_luks(0, (), "/c.raw", luks, 1 << 30)


# ---- the 64-bit port check ----------------------------------------------------------------
def _elf64(vaddr, words):
    """An aarch64-shaped ELF64 with one PT_LOAD segment holding *words* at *vaddr*."""
    body = struct.pack("<%dI" % len(words), *words)
    phoff, off = 0x40, 0x40 + 0x38
    hdr = bytearray(b"\x7fELF\x02\x01\x01" + b"\0" * 9)
    hdr += struct.pack("<HHIQQQIHHHHHH", 3, 0xB7, 1, 0, phoff, 0, 0, 0x40, 0x38, 1, 0, 0, 0)
    ph = struct.pack("<IIQQQQQQ", 1, 5, off, vaddr, vaddr, len(body), len(body), 0x1000)
    return bytes(hdr) + ph + body


def test_a_port_is_checked_against_a_64_bit_game_program(tmp_path):
    elf = _elf64(0x400000, [0xd503233f, 0xa9bf7bfd, 0x910003fd])
    port = tmp_path / "x.port"
    port.write_text("game x\nsite good 0x400000 0xd503233f 0xa9bf7bfd\n"
                    "site moved 0x400004 0xd503233f 0xa9bf7bfd\n")
    assert MW.site_mismatches(str(port), elf) == ["moved"]


def test_a_file_that_is_no_elf_is_refused():
    with pytest.raises(MW.ModeWriteError, match="not an ELF"):
        MW._elf_segments(b"MZ" + b"\0" * 100)


# ---- the rig -----------------------------------------------------------------------------
def _text(*rel):
    with open(os.path.join(ROOT, *rel), encoding="utf-8") as f:
        return f.read()


def test_the_launcher_passes_a_mode_build_to_the_run():
    s = _text("tools", "spike3_emu", "s3launch.sh")
    assert "--mode-so) export PAD_S3_MODE_SO=" in s and "--mode-files) export PAD_S3_MODE_FILES=" in s


def test_a_run_that_cannot_run_the_hook_does_its_steps():
    s = _text("tools", "spike3_emu", "s3run.sh")
    assert '"$(readlink "$R/games/game")" = pad/padmode/padmode.sh' in s
    assert 'PRELOAD="${PRELOAD:+$PRELOAD:}/games/pad/padmode/mode.so"' in s
