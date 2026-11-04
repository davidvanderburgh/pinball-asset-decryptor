"""tools/spooky_emu/mkspkmulti.py for the P-ROC titles (mkspkproc.py, PAD-980): Rick and Morty
and Alice Cooper's Nightmare Castle.

Synthetic AES packages of each (the stock build and a mod): the package's layout the machine's
codeupdate needs (the stock build at the root as it came, PAD_MULTIBOOT/ beside it with the
launcher, the menu, the reader and the other builds' files, the marker), each title's hook
(Rick and Morty's run-on-update.sh running Spooky's own first; Alice Cooper's one-time stub
with the real player beside it and the launcher's xinitrc), the AES layer round trip, verify,
inspect, inject.  The machine-side proof is tools/spooky_emu/proc's rig (MULTIBOOT.md).
"""
import io
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "spooky_emu"))
sys.path.insert(0, REPO)
import mkspkmulti as mk  # noqa: E402
import mkspkproc as sp  # noqa: E402

pytest.importorskip("Crypto.Cipher.AES")      # the app's own requirement; the rig uses openssl

LAUNCHER = os.path.join(REPO, "tools", "spike2_emu", "codeselect", "padselect_proc.sh")
AC_XINITRC = """#!/bin/sh
userresources=$HOME/.Xresources
#cd /game/code
#python2 ACGame.py >> /game/log.txt 2>&1

chmod +x /game/code/uptest/main.x86_64
cd /game/code/uptest
./main.x86_64 . &

cd /game/code
find /game/log.txt -size +100M -delete
python2 ACGame.py >> /game/log.txt 2>&1
"""


def _pkg(path, files, fmt):
    raw = str(path) + ".zip"
    with zipfile.ZipFile(raw, "w") as z:
        for rel, data in files.items():
            zi = zipfile.ZipInfo(rel)
            zi.create_system = 3
            zi.external_attr = (0o100755 if rel.endswith((".sh", "main.x86_64")) else 0o100644) << 16
            z.writestr(zi, data)
    sp.aes_encrypt(raw, str(path), fmt)
    os.unlink(raw)
    return str(path)


def _members(path, tmp):
    u = mk.SpkUpdate(path)
    with zipfile.ZipFile(u.tar_path(str(tmp))) as z:
        return {i.filename: (i, z.read(i)) for i in z.infolist() if not i.filename.endswith("/")}


@pytest.fixture
def sel(tmp_path):
    d = tmp_path / "sel"
    d.mkdir()
    (d / "spkselect").write_bytes(b"\x7fELF menu")
    (d / "dpprocsw").write_bytes(b"\x7fELF buttons")
    (d / "spksw").write_bytes(b"\x7fELF warden")
    (d / "padselect.sh").write_bytes(b"#!/bin/bash\n# the Linux launcher\n")
    (d / "padselect_proc.sh").write_bytes(open(LAUNCHER, "rb").read())
    (d / "font.ttf").write_bytes(b"font")
    return str(d)


def _rm(tmp_path):
    base = {"RMGame.pyc": b"stock code", "config/game_user_data.yaml": b"scores",
            "assets/dmd/a.png": b"A" * 100, "run-on-update.sh": b"#!/bin/bash\necho spooky's own\n",
            "payload/libpinproc.so.2.0": b"lib", "only_stock.txt": b"x"}
    (tmp_path / "s").mkdir()
    (tmp_path / "m").mkdir()
    stock = _pkg(tmp_path / "s" / "rm-gamecode-20220902.pkg", base, "rm_pkg")
    mod = dict(base, **{"assets/dmd/a.png": b"MINE"})
    mod.pop("only_stock.txt")
    return stock, _pkg(tmp_path / "m" / "rm-gamecode-20220902.pkg", mod, "rm_pkg")


def _build(stock, mod, out, sel):
    os.makedirs(out, exist_ok=True)
    assert mk.main(["build", "--primary", stock, "--extra", mod, "--out", out, "--selector-dir", sel,
                    "--timeout", "9", "--titles", "STOCK;MINE"]) == 0
    return os.path.join(out, os.path.basename(stock))


def test_aes_round_trip(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("x", b"y" * 1001)
    sp.aes_encrypt(str(z), str(tmp_path / "a.pkg"), "rm_pkg")
    sp.aes_decrypt(str(tmp_path / "a.pkg"), str(tmp_path / "b.zip"), "rm_pkg")
    assert open(z, "rb").read() == open(tmp_path / "b.zip", "rb").read()


def test_rick_and_morty_package(tmp_path, sel):
    stock, mod = _rm(tmp_path)
    path = _build(stock, mod, str(tmp_path / "multi"), sel)
    assert os.path.basename(path) == "rm-gamecode-20220902.pkg"
    m = _members(path, tmp_path)
    # the stock build at the root, as codeupdate unzips it into /game/RickAndMorty
    assert m["RMGame.pyc"][1] == b"stock code" and m["only_stock.txt"][1] == b"x"
    assert m["assets/dmd/a.png"][1] == b"A" * 100
    # the hook: ours, running Spooky's own first
    hook = m["run-on-update.sh"][1].decode()
    assert "PAD multi-boot" in hook and "run-on-update.stock.sh" in hook and "rmstart.sh" in hook
    assert m["PAD_MULTIBOOT/run-on-update.stock.sh"][1] == b"#!/bin/bash\necho spooky's own\n"
    assert b"exec bash \"$L\"" in m["PAD_MULTIBOOT/rmstart.sh"][1]
    # the menu, the launcher, the reader, the other build's files
    assert b"multi-boot launcher" in m["PAD_MULTIBOOT/padselect.sh"][1]
    for f in ("spkselect", "dpprocsw", "font.ttf", "images.conf", "builds.txt"):
        assert "PAD_MULTIBOOT/" + f in m
    assert "PAD_MULTIBOOT/spksw" not in m
    d1 = {n for n in m if n.startswith("PAD_MULTIBOOT/d1/")}
    assert d1 == {"PAD_MULTIBOOT/d1/assets/dmd/a.png"}
    assert m["PAD_MULTIBOOT/d1.removed"][1] == b"only_stock.txt\n"
    pc = m["PAD_MULTIBOOT/proc.conf"][1].decode()
    for want in ("game=/game/RickAndMorty", "lib=/usr/local/lib", "L=SD14", "R=SD8", "S=SD15",
                 "start=python RMGame.pyc 2>> /tmp/runlog", "keep=config/game_user_data.yaml"):
        assert want in pc
    assert m["PAD_MULTIBOOT_LIVE"][1].startswith(b"b0 ")
    assert mk.main(["verify", "--update", path]) == 0
    rep = mk.inspect_update(path)
    assert rep["game"] == "Rick and Morty" and [i["device"] for i in rep["images"]] == ["b0", "b1"]


def test_alice_cooper_package(tmp_path, sel):
    base = {"ACGame.py": b"game", "xinitrc": AC_XINITRC.encode(), "uptest/main.x86_64": b"\x7fELF unity",
            "config/alice.yaml": b"yaml", "assets/dmd/a.png": b"A"}
    for d in ("s", "m"):
        (tmp_path / d).mkdir()
    stock = _pkg(tmp_path / "s" / "ac-gamecode.pkg", base, "ac_pkg")
    mod = _pkg(tmp_path / "m" / "ac-gamecode.pkg", dict(base, **{"assets/dmd/a.png": b"MINE"}), "ac_pkg")
    path = _build(stock, mod, str(tmp_path / "multi"), sel)
    assert os.path.basename(path) == "ac-gamecode.pkg"
    m = _members(path, tmp_path)
    # the stub in the player's place, the real one beside it
    assert b"PAD multi-boot" in m["uptest/main.x86_64"][1]
    assert m["uptest/main.x86_64"][0].external_attr >> 16 & 0o111
    assert m["uptest/main.x86_64.real"][1] == b"\x7fELF unity"
    # the stock xinitrc untouched (the game's self-heal reads it); the launcher's beside the menu
    assert m["xinitrc"][1] == AC_XINITRC.encode()
    x = m["PAD_MULTIBOOT/xinitrc"][1].decode()
    assert "bash /game/code/.pad/padselect.sh" in x and "uptest" in x and "delete" in x
    assert [ln for ln in x.splitlines() if ln.startswith("python2 ACGame.py")] == ["python2 ACGame.py >> /game/log.txt 2>&1"]
    assert "#python2 ACGame.py" in x
    assert "run-on-update.sh" not in m
    pc = m["PAD_MULTIBOOT/proc.conf"][1].decode()
    assert "game=/game/code" in pc and "lib=/usr/lib" in pc and "R=SD10" in pc and "python2 ACGame.py" in pc
    assert mk.main(["verify", "--update", path]) == 0


def test_inject_keeps_the_builds_and_the_stamp(tmp_path, sel):
    stock, mod = _rm(tmp_path)
    path = _build(stock, mod, str(tmp_path / "multi"), sel)
    stamp = _members(path, tmp_path)["PAD_MULTIBOOT_LIVE"][1]
    assert mk.main(["inject", "--update", path, "--titles", "NEW;NAMES", "--timeout", "4"]) == 0
    m = _members(path, tmp_path / "again")
    conf = m["PAD_MULTIBOOT/images.conf"][1].decode()
    assert "image=b0|NEW|" in conf and "timeout=4" in conf
    assert m["PAD_MULTIBOOT_LIVE"][1] == stamp, "a new stamp would make the machine throw its builds away"
    assert m["PAD_MULTIBOOT/d1/assets/dmd/a.png"][1] == b"MINE" and m["RMGame.pyc"][1] == b"stock code"
    assert m["PAD_MULTIBOOT/run-on-update.stock.sh"][1] == b"#!/bin/bash\necho spooky's own\n"
    assert mk.main(["verify", "--update", path]) == 0


def test_refusals(tmp_path, sel):
    stock, _mod = _rm(tmp_path)
    (tmp_path / "a").mkdir()
    ac = _pkg(tmp_path / "a" / "ac-gamecode.pkg", {"ACGame.py": b"g", "xinitrc": b"x"}, "ac_pkg")
    assert mk.main(["build", "--primary", stock, "--extra", ac, "--out", str(tmp_path / "o"),
                    "--selector-dir", sel]) == 2
    # an Alice Cooper update whose xinitrc this builder cannot place the menu in
    (tmp_path / "b").mkdir()
    bad = _pkg(tmp_path / "b" / "ac-gamecode.pkg", {"ACGame.py": b"g2", "xinitrc": b"#!/bin/sh\n"}, "ac_pkg")
    os.makedirs(tmp_path / "o2")
    assert mk.main(["build", "--primary", ac, "--extra", bad, "--out", str(tmp_path / "o2"),
                    "--selector-dir", sel]) == 2
    with pytest.raises(sp.Refused):
        sp.ac_xinitrc("#!/bin/sh\nstartx\n")
    assert io  # (imported for symmetry with the Linux tests)


def test_the_openssl_path_matches(tmp_path, monkeypatch):
    """PAD-Runtime's python has no AES module: the rig and the tab's Linux use openssl"""
    import shutil
    if not shutil.which("openssl"):
        pytest.skip("no openssl here")
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("x", b"y" * 5000)
    sp.aes_encrypt(str(z), str(tmp_path / "crypto.pkg"), "ac_pkg")             # pycryptodome
    monkeypatch.setattr(sp, "_have_crypto", lambda: False)
    sp.aes_decrypt(str(tmp_path / "crypto.pkg"), str(tmp_path / "b.zip"), "ac_pkg")   # openssl
    assert open(z, "rb").read() == open(tmp_path / "b.zip", "rb").read()
    sp.aes_encrypt(str(z), str(tmp_path / "ossl.pkg"), "ac_pkg")                 # openssl
    monkeypatch.setattr(sp, "_have_crypto", lambda: True)
    sp.aes_decrypt(str(tmp_path / "ossl.pkg"), str(tmp_path / "c.zip"), "ac_pkg")     # pycryptodome
    assert open(z, "rb").read() == open(tmp_path / "c.zip", "rb").read()
