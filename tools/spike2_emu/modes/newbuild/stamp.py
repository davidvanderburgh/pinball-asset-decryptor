"""stamp.py <derived port> <check dir> -o <port> [--when YYYY-MM-DD] [--why TEXT] - a new build's derived port
(port_derive, "NOT RUN") made a shipped one once checkjob.sh passed on it (PAD-1555).

The check dir is checkjob.sh's $JOB_OUT: mode.log (the runtime's log) and check.txt (gamecheck.sh play's lines).
They are read the way the Modes tab's Check this game reads them (game_check.read), and the derived port's header
(the NOT RUN lines) is replaced with what the run proved; the program sha1 line and the body stay as derived.
Refuses a check that did not pass. Then: `port_tool.py recipe <program> ports/<port>` for its recipe."""
import argparse
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("check_dir")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--when", default="")
    ap.add_argument("--why", default="PAD-1555: Stern's November 2026 build")
    a = ap.parse_args(argv)
    sys.path.insert(0, REPO)
    from pinball_decryptor.plugins.stern import game_check as GC, mode_project as MP
    text = open(a.port, encoding="utf-8").read()
    log = open(os.path.join(a.check_dir, "mode.log"), encoding="utf-8", errors="replace").read()
    play = open(os.path.join(a.check_dir, "check.txt"), encoding="utf-8", errors="replace").read()
    prof = MP.profile_from_port(a.port)
    res = GC.read(log, play, prof.shots, prof.events)
    if not res.ok:
        sys.exit("%s: the check did not pass: %s" % (a.port, res.summary()))
    lines = text.splitlines()
    head = []
    while lines and (lines[0].startswith("#") or not lines[0].strip()):
        head.append(lines.pop(0))
    first = head[0] if head else ""
    title = first[2:].split(" - ", 1)[0] if first.startswith("# ") else "%s %s" % (prof.game, prof.version)
    sha = [h for h in head if h.startswith("# program sha1")]
    full = ("a tilted ball 2 and a ball 3%s" % (" to the game's end" if "the game ended" in play else "")
            if "ball 2 ended" in play else "one drain")
    n, total = len(res.shots_seen), len(res.shots_seen) + len(res.shots_unseen)
    when = a.when or res.when.split()[0]
    out = ["# %s - %s: derived (port_derive) from this framework generation's references, the same model's" % (title, a.why),
           "# proven port first (its values, shots, callouts, text and lamps)."]
    out += ["# Emulator-proven %s by a full build check (modes/newbuild/checkjob.sh: gamecheck.sh play full, the stock" % when,
            "# card, hidden, muted): the runtime hooked the game, %d of its %d shots came from their switches, a drain" % (n, total),
            "# ended a ball (%s), events seen firing: %s." % (full, ", ".join(res.events_seen) or "none")]
    if res.shots_unseen:
        out.append("# Shots no press made: %s." % ", ".join(res.shots_unseen))
    if res.events_unseen:
        out.append("# Events that did not fire: %s." % ", ".join(res.events_unseen))
    body = "\n".join(out + sha + [""] + lines) + "\n"
    assert MP.UNPROVEN_MARK not in "\n".join(out)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    print("%s: %d/%d shots, events %s" % (a.out, n, total, ",".join(res.events_seen)))


if __name__ == "__main__":
    main()
