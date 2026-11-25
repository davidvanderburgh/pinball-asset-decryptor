r"""PAD-1599 proof: a THROWAWAY distro standing in for a user's previous Linux, holding what an older version of the
app left there.  Never the user's own distro.

    python scripts/pad1599_old_distro_proof.py make  <rootfs.tar.gz> [name] [--fresh] [--checkout]
    python scripts/pad1599_old_distro_proof.py run   [name]     # check -> remove -> compact, through core/old_distro
    python scripts/pad1599_old_distro_proof.py drop  [name]

make: imports the tarball as <name> (default PAD1599-Old) under C:\tmp\PAD-1599\<name>, and writes (random bytes, so
the disk file really grows): /home/u/cardcache (2 GiB), /var/tmp/pad_ap/cache/tmnt (768 MiB), /var/tmp/pad_ap/rig0
(64 MiB), /var/tmp/pad_ap/nv0 + /home/u/padslots (kept: settings / save states), /var/tmp/jjp_wonka/iso (512 MiB),
/tmp/cgc_stage_x_1 (128 MiB), and /home/u/cardcache_mine (the user's, a name the app never makes).  All dated 60 days
ago unless --fresh; --checkout also puts a PAD checkout in /home/u/src.
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

FILL = r"""
set -e
mk() { mkdir -p "$(dirname "$1")"; head -c $2 /dev/urandom > "$1"; }
M=1048576
mk /home/u/cardcache/spike2_tmnt_le.raw $((2048*M))
mk /var/tmp/pad_ap/cache/tmnt/game.img $((768*M))
mk /var/tmp/pad_ap/rig0/run.log $((64*M))
mk /var/tmp/pad_ap/nv0/nvram.bin $((2*M))
mk /home/u/padslots/slot1.state $((4*M))
mk /var/tmp/jjp_wonka/iso/wonka.iso $((512*M))
mk /tmp/cgc_stage_x_1/stage.bin $((128*M))
mk /home/u/cardcache_mine/keep.bin $((8*M))
@CHECKOUT@
if [ "@AGE@" = 1 ]; then
  find /home /var/tmp/pad_ap /var/tmp/jjp_wonka /tmp/cgc_stage_x_1 -exec touch -h -d '60 days ago' {} +
fi
sync
du -sh /home/u/cardcache /var/tmp/pad_ap/* /var/tmp/pad_ap/cache/* /var/tmp/jjp_wonka /tmp/cgc_stage_x_1 /home/u/padslots /home/u/cardcache_mine
"""


def wsl(*args, **kw):
    return subprocess.run(["wsl.exe", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL, **kw)


def main():
    cmd = sys.argv[1]
    rest = [a for a in sys.argv[2:] if not a.startswith("--")]
    if cmd == "make":
        tar = rest[0]
        name = rest[1] if len(rest) > 1 else "PAD1599-Old"
        where = os.path.join(r"C:\tmp\PAD-1599", name)
        os.makedirs(where, exist_ok=True)
        r = wsl("--import", name, where, tar, "--version", "2")
        print("import", r.returncode, (r.stdout + r.stderr).replace("\x00", "").strip())
        checkout = ("mkdir -p /home/u/src/pinball_decryptor && touch /home/u/src/pinball_decryptor/__main__.py"
                    if "--checkout" in sys.argv else "")
        script = FILL.replace("@AGE@", "0" if "--fresh" in sys.argv else "1").replace("@CHECKOUT@", checkout)
        import base64
        b64 = base64.b64encode(script.encode()).decode()
        r = wsl("-d", name, "-u", "root", "--", "bash", "-c", "echo %s | base64 -d | bash" % b64, timeout=900)
        print(r.stdout, r.stderr)
        wsl("--terminate", name)
        time.sleep(3)
        print("vhdx", os.path.getsize(os.path.join(where, "ext4.vhdx")) / 2 ** 30, "GiB")
    elif cmd == "run":
        name = rest[0] if rest else "PAD1599-Old"
        os.environ["PAD_OLD_DISTRO"] = name
        from pinball_decryptor.core import old_distro, runtime
        print("runtime:", runtime.status(refresh=True))
        t = time.time()
        v = old_distro.check()
        print("check (%.1f s):" % (time.time() - t), json.dumps(v, indent=1, default=str))
        if not v:
            return
        t = time.time()
        print("remove:", old_distro.remove(v["name"], v["items"]), "%.1f s" % (time.time() - t))
        t = time.time()
        b, a = old_distro.compact(v, progress=print)
        print("compact: %.2f GiB -> %.2f GiB (%.1f s)" % (b / 2 ** 30, a / 2 ** 30, time.time() - t))
        r = wsl("-d", name, "-u", "root", "--", "bash", "-c",
                "ls -la /home/u /var/tmp/pad_ap /var/tmp/pad_ap/cache /var/tmp /tmp; du -sh /home/u/*")
        print(r.stdout, r.stderr)
        wsl("--terminate", name)
        print("check again:", old_distro.check())
    elif cmd == "compact-when-idle":
        # The press's compact, waited for: the same fail-closed checks, except that on THIS PC a third distro
        # (David's Ubuntu, where the ticket rigs run) is running - it passes only when nobody is in it and the
        # give-back's own busy scan finds nothing running in it either.
        name = rest[0] if rest else "PAD1599-Old"
        hours = float(rest[1]) if len(rest) > 1 else 3
        os.environ["PAD_OLD_DISTRO"] = name
        from pinball_decryptor.core import disk_giveback, old_distro, runtime
        print("runtime:", runtime.status(refresh=True), flush=True)
        prev = old_distro.previous()
        end = time.time() + hours * 3600
        n = 0
        while time.time() < end:
            n += 1
            why = old_distro.busy_reasons(name, distros=lambda: [
                d for d in disk_giveback.running_distros() if d != "Ubuntu"])
            if not why and "Ubuntu" in disk_giveback.running_distros():
                users = old_distro._run("Ubuntu", old_distro._IN_USE, 60).strip()
                inner = disk_giveback.parse_scan(old_distro._run("Ubuntu", disk_giveback.scan_script([]), 600))[1]
                why = ([users] if users else []) + inner
            if why:
                if n % 10 == 1:
                    print(time.strftime("%H:%M:%S"), "busy:", "; ".join(why)[:300], flush=True)
                time.sleep(30)
                continue
            print(time.strftime("%H:%M:%S"), "idle - compacting", prev, flush=True)
            b, a = old_distro.compact(prev, progress=lambda m: print(m, flush=True), busy=lambda: [])
            print("COMPACT: %.2f GiB -> %.2f GiB" % (b / 2 ** 30, a / 2 ** 30), flush=True)
            print("record:", json.dumps(old_distro._record(name)), flush=True)
            print("check again:", old_distro.check(), flush=True)
            return
        print("no idle moment in %.1f h" % hours, flush=True)
    elif cmd == "drop":
        name = rest[0] if rest else "PAD1599-Old"
        r = wsl("--unregister", name)
        print("unregister", r.returncode)


if __name__ == "__main__":
    main()
