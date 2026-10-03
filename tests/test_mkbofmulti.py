"""tools/bof_emu/mkbofmulti.py, the Barrels of Fun multi-boot builder (PAD-342).

The pure parts everywhere: the two patches to the machine's own startup scripts (anchored
on the vendor's exact lines, refused without them), the images.conf, the delta writer and
its checker.  Where gpg and tar are on the PATH (Linux CI, WSL), a whole build from two
synthetic .fun files: plan, build, inspect and a quick verify, and the archive's shape -
exactly ONE *.x86_64 (what the machine's updater requires), the scripts and the menu at the
front.  The real-file proof (Labyrinth's stock and Sarah .fun, the machine's own updater and
profile run unmodified) is tools/bof_emu/machine_sim.sh.
"""
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tarfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "bof_emu"))
import mkbofmulti as mb  # noqa: E402
from mkmulticard import Refused  # noqa: E402

# a profile with the two lines the patches anchor on - written for the test, the shape of
# Labyrinth's (the loop that starts the game, and its self-repair copy)
PROFILE = """#
# ~/.bash_profile
#
[[ -f ~/.bashrc ]] && . ~/.bashrc
SESSION_TYPE="console"
while true
do
 if [[ $ORIGINALGAMESIZE -ne $PRODGAMESIZE ]]
 then
   cp -rf /home/pinball/extracted/decrypt/GDCraze.x86_64 /home/pinball/craze/GDCraze.x86_64
 fi
 ./startgame
break;
done
"""
UPDATE_SH = """#!/bin/bash
cp -rf /home/pinball/extracted/decrypt/update/.bash_profile /home/pinball/.bash_profile
sync
sudo rm -rf /home/pinball/extracted/decrypt/update
"""


# ---------------------------------------------------------------------------- the patches
def test_profile_gets_the_hook_before_the_loop_and_rm_before_the_repair():
    out = mb.patch_profile(PROFILE)
    lines = out.splitlines()
    loop = lines.index("while true")
    hook = [i for i, ln in enumerate(lines) if mb.HOOK_MARK in ln]
    assert hook and hook[0] < loop
    assert lines[loop - 2] == "fi"           # the hook block ends just before the loop
    assert "/bin/bash %s/padselect.sh < /dev/null" % mb.PADSELECT_DIR in out
    assert ("   rm -f /home/pinball/craze/GDCraze.x86_64; cp -rf /home/pinball/extracted/decrypt/"
            "GDCraze.x86_64 /home/pinball/craze/GDCraze.x86_64") in lines
    # everything else is the vendor's, line for line: take the hook block and the rm -f
    # back out and the profile is what it was
    i = hook[0]
    unhooked = lines[:i] + lines[i + len(mb.HOOK_BLOCK) + 1:]
    assert "\n".join(unhooked).replace(mb.HEAL_RM, "") + "\n" == PROFILE


def test_profile_patch_keeps_crlf_and_refuses_what_it_does_not_know():
    crlf = mb.patch_profile(PROFILE.replace("\n", "\r\n"))
    assert "\r\n" in crlf and "\n" not in crlf.replace("\r\n", "")
    with pytest.raises(Refused, match="while true"):
        mb.patch_profile(PROFILE.replace("while true", "while :"))
    with pytest.raises(Refused, match="self-repair"):
        mb.patch_profile(PROFILE.replace("cp -rf", "cp -f"))
    with pytest.raises(Refused, match="already carries"):
        mb.patch_profile(mb.patch_profile(PROFILE))


def test_update_sh_runs_the_install_step_first():
    out = mb.patch_update_sh(UPDATE_SH).splitlines()
    assert out[0] == "#!/bin/bash"
    assert mb.INSTALL_LINE in out
    assert out.index(mb.INSTALL_LINE) < [i for i, ln in enumerate(out) if ".bash_profile" in ln][0]
    with pytest.raises(Refused, match="does not copy"):
        mb.patch_update_sh("#!/bin/bash\nsync\n")
    with pytest.raises(Refused, match="already runs"):
        mb.patch_update_sh(mb.patch_update_sh(UPDATE_SH))


# ---------------------------------------------------------------------------- the conf
def test_conf_names_the_programs_and_the_switches():
    sw = mb.TITLES["labyrinth"]["switches"]
    text = mb.render_conf(["GDCraze.x86_64", "pad_image1.bin"], ["LABYRINTH", "SARAH"], ["Stock", ""],
                          1, 10, [], None, None, None, sw, heading="PICK ONE")
    lines = text.splitlines()
    assert "image=GDCraze.x86_64|LABYRINTH|Stock" in lines and "image=pad_image1.bin|SARAH|" in lines
    for want in ("default=1", "timeout=10", "heading=PICK ONE", "switch_left=15", "switch_right=22",
                 "switch_start=14,20", "font=%s/font.ttf" % mb.PADSELECT_DIR):
        assert want in lines, want
    assert not any(ln.startswith(("sound_", "media=")) for ln in lines)
    back = mb.parse_conf(text)
    assert back["images"] == [("GDCraze.x86_64", "LABYRINTH", "Stock"), ("pad_image1.bin", "SARAH", "")]
    assert back["default"] == 1 and back["switches"]["switch_start"] == "14,20"
    with pytest.raises(Refused):
        mb.render_conf(["a", "b"], ["x|y"], [], 0, 10, [], None, None, None, sw)
    with pytest.raises(Refused):
        mb.render_conf(["a", "b"], [], [], 2, 10, [], None, None, None, sw)


def test_titles_not_read_yet_are_refused_by_name(tmp_path):
    for name, why in (("dune.fun", "Python script"), ("winchester.fun", "no startup scripts"),
                      ("bon-jovi_2026.10.01.fun", "signed disk image")):
        p = tmp_path / name
        p.write_bytes(b"x")
        with pytest.raises(Refused, match=why):
            mb.identify(str(p))


# ---------------------------------------------------------------------------- the delta
def test_delta_round_trip_and_the_check_catches_a_bad_one(tmp_path):
    rnd = random.Random(7)
    a = bytes(rnd.getrandbits(8) for _ in range(3 << 20))
    b = a[:(1 << 20)] + b"x" * 5000 + a[(1 << 20) + 5000:]
    pa, pb, pd = tmp_path / "a", tmp_path / "b", tmp_path / "d"
    pa.write_bytes(a)
    pb.write_bytes(b)
    ops = mb.delta_ops(str(pa), str(pb))
    assert sum(n for op, _o, n in ops if op == "C") == 2 << 20
    assert mb.delta_data_bytes(ops) == 1 << 20
    mb.write_delta(ops, str(pa), str(pb), str(pd))
    assert mb.apply_delta_md5(str(pa), str(pd)) == (hashlib.md5(b).hexdigest(), len(b))
    pa.write_bytes(a + b"!")
    with pytest.raises(Refused, match="was not made against"):
        mb.apply_delta_md5(str(pa), str(pd))


# ---------------------------------------------------------------------------- a whole build
HAVE_TOOLS = bool(shutil.which("gpg") and shutil.which("tar")) and sys.platform != "win32"


def _fun(path, program, data, profile=PROFILE, update=UPDATE_SH):
    """A synthetic Labyrinth update: a gpg-symmetric (funkey) gzip tarball."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, body, mode in (("update/.bash_profile", profile, 0o644), ("update/update.sh", update, 0o755),
                                 ("update/updatecode.sh", "#!/bin/bash\n", 0o755), (program, data, 0o755)):
            body = body.encode() if isinstance(body, str) else body
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(body), mode
            tf.addfile(ti, io.BytesIO(body))
    subprocess.run(["gpg", "--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase", "funkey",
                    "--symmetric", "--output", str(path)], input=buf.getvalue(), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.mark.skipif(not HAVE_TOOLS, reason="needs gpg and tar (Linux)")
def test_a_whole_build_from_two_synthetic_updates(tmp_path, capsys):
    rnd = random.Random(342)
    stock = bytes(rnd.getrandbits(8) for _ in range(2 << 20))
    mod = stock[:1 << 20] + b"MOD" * 1000 + stock[(1 << 20) + 3000:]
    (tmp_path / "stock").mkdir()
    (tmp_path / "mod").mkdir()
    f0, f1 = tmp_path / "stock" / "lab.fun", tmp_path / "mod" / "lab.fun"
    _fun(f0, "GDCraze_linux_20260130.x86_64", stock)
    _fun(f1, "GDCraze_linux_20260130.x86_64", mod)
    sel = tmp_path / "sel"
    sel.mkdir()
    for n in ("bofselect", "paddelta", "padselect.sh", "pad_install.sh", "font.ttf"):
        (sel / n).write_bytes(b"stand-in " + n.encode())
    cache, out = tmp_path / "cache", tmp_path / "multi" / "lab.fun"
    out.parent.mkdir()
    common = ["--primary", str(f0), "--extra", str(f1), "--cache-dir", str(cache)]
    assert mb.main(["plan"] + common) == 0
    plan = capsys.readouterr().out
    assert "fat32: fits" in plan and "image-size 1 pad_image1.bin" in plan and "2026.01.30" in plan
    assert mb.main(["build"] + common + ["--out", str(out), "--selector-dir", str(sel),
                                         "--titles", "STOCK;MOD", "--timeout", "7"]) == 0
    # the archive as the machine's updater sees it
    dec = subprocess.run(["gpg", "--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase", "funkey",
                          "-d", str(out)], stdout=subprocess.PIPE, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(dec), mode="r:gz") as tf:
        names = tf.getnames()
        programs = tf.extractfile("padselect/programs").read().decode()
        profile = tf.extractfile("update/.bash_profile").read().decode()
        conf = tf.extractfile("padselect/images.conf").read().decode()
    assert [n for n in names if n.endswith(".x86_64")] == ["GDCraze_linux_20260130.x86_64"]
    assert names[0].startswith("update") and names[-1] == "GDCraze_linux_20260130.x86_64"
    assert "pad_image1.delta" in names and "padselect/bofselect" in names and "padselect/build.json" in names
    assert mb.HOOK_MARK in profile and "timeout=7" in conf
    md5s = dict((ln.split()[1], ln.split()[3]) for ln in programs.splitlines())
    assert md5s == {"GDCraze.x86_64": hashlib.md5(stock).hexdigest(),
                    "pad_image1.bin": hashlib.md5(mod).hexdigest()}
    capsys.readouterr()
    assert mb.main(["inspect", "--fun", str(out), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert [i["title"] for i in rep["images"]] == ["STOCK", "MOD"] and rep["hook"] and rep["install_step"]
    assert mb.main(["verify", "--fun", str(out), "--quick"]) == 0
    # a new menu, written over the same file
    assert mb.main(["inject", "--fun", str(out), "--titles", "ONE;TWO", "--cache-dir", str(cache)]) == 0
    capsys.readouterr()
    assert mb.main(["inspect", "--fun", str(out), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert [i["title"] for i in rep["images"]] == ["ONE", "TWO"] and rep["timeout"] == 7
