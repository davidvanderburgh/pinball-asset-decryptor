#!/usr/bin/env python3
"""spkmarkmod.py - a "mod" for the multi-boot proof (machine_sim.sh, PAD-980): the same
Spooky update with one file added, uptest/PAD_MULTIBOOT_MARK (flat titles: at the archive's
root), saying which build it is, packed as the original was.

    spkmarkmod.py <update> <out dir> [<mark text>]

The output keeps the update's own name, in <out dir>.  Prints the path it wrote.
"""
import io
import os
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkspkmulti as mk  # noqa: E402


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    src, out_dir = os.path.abspath(argv[0]), os.path.abspath(argv[1])
    mark = (argv[2] if len(argv) > 2 else "PAD-980 mark build").encode() + b"\n"
    u = mk.SpkUpdate(src)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, os.path.basename(src))
    if os.path.abspath(out) == src:
        print("spkmarkmod: the out dir is the update's own folder", file=sys.stderr)
        return 2
    work = tempfile.mkdtemp(prefix="spkmark.", dir=out_dir)
    try:
        if u.title["proc"]:
            # a P-ROC package: an AES zip whose root is the game's folder
            import zipfile
            import mkspkproc as sp
            tmp = os.path.join(work, "mod.zip")
            with zipfile.ZipFile(u.tar_path(work)) as zin, \
                    zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=1) as zout:
                for zi in zin.infolist():
                    with zin.open(zi) as s, zout.open(zi, "w", force_zip64=True) as d:
                        while True:
                            b = s.read(1 << 20)
                            if not b:
                                break
                            d.write(b)
                zout.writestr("PAD_MULTIBOOT_MARK", mark)
            sp.aes_encrypt(tmp, out + ".part", u.fmt)
            os.replace(out + ".part", out)
            print(out)
            return 0
        gz = u.fmt != "plain_tar"
        tmp = os.path.join(work, "mod.tar" + (".gz" if gz else ""))
        name = "PAD_MULTIBOOT_MARK" if u.title["flat"] else "uptest/PAD_MULTIBOOT_MARK"
        with tarfile.open(u.tar_path(work), "r|*") as tin, \
                (tarfile.open(tmp, "w:gz", compresslevel=1) if gz else tarfile.open(tmp, "w")) as tout:
            for ti in tin:
                tout.addfile(ti, tin.extractfile(ti) if ti.isfile() else None)
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(mark), 0o644
            tout.addfile(ti, io.BytesIO(mark))
        mk._pack(u, tmp, out + ".part")
        os.replace(out + ".part", out)
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
