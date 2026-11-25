"""scan_ret_use.py <program> <port> [--lines] - PAD-1400's per-build list of the show_start / award_screen callers
that use what they get back (pinball_decryptor/plugins/stern/ret_use.py, which a derived port runs too): the
addresses, or with --lines the port lines."""
import argparse
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def sites_of(port_text):
    out = {}
    for line in port_text.splitlines():
        f = line.split()
        if len(f) >= 3 and f[0] == "site" and f[1] in ("show_start", "award_screen"):
            out[f[1]] = int(f[2], 16)
    return out


def scan(prog, port_text):
    sys.path.insert(0, REPO)
    from pinball_decryptor.plugins.stern import portgen, ret_use
    return ret_use.scan(portgen.Elf(prog), sites_of(port_text))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("program")
    ap.add_argument("port")
    ap.add_argument("--lines", action="store_true")
    a = ap.parse_args(argv)
    addrs = scan(a.program, open(a.port, encoding="utf-8").read())
    from pinball_decryptor.plugins.stern import ret_use
    for line in (ret_use.lines(addrs) if a.lines else ["0x%08x" % x for x in addrs]):
        print(line)


if __name__ == "__main__":
    main()
