"""Run the tests a change actually touches, instead of all 3450.

David, 2026-09-01: "when I'm making spike two emulator changes, there's no
reason for any JJP tests to run."  This maps changed files to test ZONES and
runs only the union - falling back to the FULL suite the moment anything
shared is in the diff, because a wrong "unaffected" verdict is a silently
thinner gate and this repo yanks releases over exactly that.

Usage:
    python scripts/testpick.py                  # zones from git diff vs HEAD
                                                # (working tree + staged)
    python scripts/testpick.py --since v0.176.0 # zones from REF..working tree
    python scripts/testpick.py spike2 jjp       # named zones, git not asked
    python scripts/testpick.py --list           # show every zone's tests
    python scripts/testpick.py --dry            # print the verdict, run nothing
    python scripts/testpick.py spike2 -- -k coil  # after --, args go to pytest

The RELEASE GATE still runs everything, on purpose - this is a dev-loop
tool.  Selection here is path-based and conservative, not coverage-based:
a zone owns whole test files, sources are matched by prefix, and any
changed file no rule recognises promotes the run to FULL and says so.
pytest itself still applies pytest.ini, so zone runs are parallel too.
"""

import argparse
import glob
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# The zone table.  ORDER MATTERS: the first zone whose source prefix matches
# a changed file claims it, so specific rows (a single gui file, a plugin
# subdir) sit above general ones (the whole gui/ or plugins/stern/ tree).
#
# tests are glob patterns under tests/.  A source that maps to NO zone
# promotes the whole run to FULL - that is the safety net, not an error.
# ---------------------------------------------------------------------------

ZONES = [
    # -- Spike 2 rig: the emulator, its tab, its playfield tooling ---------
    ("spike2", ["tools/spike2_emu/",
                "pinball_decryptor/plugins/stern/spike2/",
                "pinball_decryptor/gui/emulate_tab.py"],
     ["test_spike2_*.py", "test_emulate_tab.py", "test_emulate_poll_storm.py",
      "test_emulate_setup_check.py"]),
    # -- Spike 1 rig -------------------------------------------------------
    ("spike1", ["tools/spike1_emu/",
                "pinball_decryptor/plugins/stern/spike1",   # spike1*.py
                "pinball_decryptor/gui/spike1_emulate_tab.py",
                "pinball_decryptor/gui/spike1_windows.py"],
     ["test_spike1_*.py"]),
    # -- Stern plugin core: formats, engine, radium, sidx, compare... ------
    # Both rigs sit on it, so its zone pulls their tests in too.
    ("stern", ["pinball_decryptor/plugins/stern/"],
     ["test_stern_*.py", "test_spike1_*.py", "test_spike2_*.py",
      "test_emulate_*.py", "test_scene_*.py", "test_plugins.py"]),
    # -- JJP: plugin, rig, tab --------------------------------------------
    ("jjp", ["pinball_decryptor/plugins/jjp/", "tools/jjp_emu/",
             "pinball_decryptor/gui/jjp_emulate_tab.py"],
     ["test_jjp_*.py", "test_plugins.py"]),
    # -- The small plugins -------------------------------------------------
    ("bof",     ["pinball_decryptor/plugins/bof/"],
     ["test_bof_*.py", "test_plugins.py"]),
    ("cgc",     ["pinball_decryptor/plugins/cgc/"],
     ["test_cgc_*.py", "test_plugins.py"]),
    ("spooky",  ["pinball_decryptor/plugins/spooky/"],
     ["test_spooky_*.py", "test_plugins.py"]),
    ("williams", ["pinball_decryptor/plugins/williams/"],
     ["test_williams_*.py", "test_plugins.py"]),
    ("dp",      ["pinball_decryptor/plugins/dp/"],
     ["test_dp_*.py", "test_plugins.py"]),
    ("ap",      ["pinball_decryptor/plugins/ap/"],
     ["test_ap_*.py", "test_plugins.py"]),
    ("pb",      ["pinball_decryptor/plugins/pb/"],
     ["test_pb_*.py", "test_plugins.py"]),
    ("pinmame", ["pinball_decryptor/plugins/pinmame_classic/"],
     ["test_pinmame_*.py", "test_plugins.py"]),
    # -- Shared GUI: widgets, theme, picker, dialogs... --------------------
    # Every tab imports these, so the zone is honestly wide: the whole Tk
    # lane.  Still far short of FULL (no plugin/pipeline/core tests).
    ("gui", ["pinball_decryptor/gui/", "pinball_decryptor/worktree_picker.py"],
     ["test_gui_*.py", "test_emulate_*.py", "test_jjp_emulate_tab.py",
      "test_jjp_matrix_ui.py", "test_spike1_emulate_tab.py",
      "test_spike1_windows.py", "test_log_pane_freeze.py",
      "test_worktree_*.py", "test_desktop_*.py", "test_placement*.py",
      "test_installer.py"]),
]
# (No `updater` zone: pinball_decryptor/core/ is a FULL trigger and the
# updater lives inside it - core changes run everything, on purpose.)

# A changed file matching any of these promotes the run to FULL outright.
FULL_TRIGGERS = [
    "pinball_decryptor/core/",       # shared by everything
    "pinball_decryptor/app.py",
    "pinball_decryptor/__init__.py",
    "pinball_decryptor/__main__.py",
    "tests/conftest.py",
    "tests/test_gui_smoke.py",       # the shared `app` fixture lives here
    "pytest.ini",
    "requirements",
    ".github/",
]

# Changes here run NOTHING (docs and planning never execute).
NO_TEST_SUFFIXES = (".md", ".png", ".txt", ".json.example")
NO_TEST_PREFIXES = ("docs/", "plans/", "images/", "scripts/take_screenshots",
                    "scripts/testpick")


def changed_files(since):
    """Working tree + staged changes; with --since, everything after REF."""
    base = ["git", "-C", REPO, "diff", "--name-only"]
    names = set()
    if since:
        names |= set(subprocess.check_output(
            base + [since], text=True).splitlines())
    else:
        names |= set(subprocess.check_output(base + ["HEAD"],
                                             text=True).splitlines())
        names |= set(subprocess.check_output(
            base + ["--cached"], text=True).splitlines())
    return sorted(n.strip().replace("\\", "/") for n in names if n.strip())


def classify(path):
    """-> ('zone', name) | ('full', why) | ('none', None) | ('self', path)"""
    # FULL triggers come FIRST: tests/test_gui_smoke.py is a test file, but
    # it is also the shared `app` fixture - editing it must run everything,
    # not "itself" (which the suite ignores by name anyway).
    for trig in FULL_TRIGGERS:
        if path.startswith(trig):
            return ("full", trig)
    if path.startswith("tests/") and os.path.basename(path).startswith("test_"):
        return ("self", path)
    if path.endswith(NO_TEST_SUFFIXES) or path.startswith(NO_TEST_PREFIXES):
        return ("none", None)
    for name, sources, _tests in ZONES:
        if any(path.startswith(s) for s in sources):
            return ("zone", name)
    return ("full", "no zone rule for %s" % path)


def zone_tests(names):
    out = []
    for zname, _sources, patterns in ZONES:
        if zname not in names:
            continue
        for pat in patterns:
            out.extend(sorted(glob.glob(os.path.join(REPO, "tests", pat))))
    return sorted(set(out))


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("zones", nargs="*", help="zone names; empty = from git diff")
    ap.add_argument("--since", help="diff against this ref instead of HEAD")
    ap.add_argument("--dry", action="store_true", help="print, do not run")
    ap.add_argument("--list", action="store_true", help="show the zone table")
    if "--" in argv:
        cut = argv.index("--")
        argv, extra = argv[:cut], argv[cut + 1:]
    else:
        extra = []
    args = ap.parse_args(argv)

    if args.list:
        for name, sources, patterns in ZONES:
            files = zone_tests({name})
            print("%-9s %3d test files   sources: %s"
                  % (name, len(files), ", ".join(sources)))
        return 0

    known = {z[0] for z in ZONES}
    if args.zones:
        bad = [z for z in args.zones if z not in known]
        if bad:
            print("unknown zone(s): %s   (known: %s)"
                  % (", ".join(bad), ", ".join(sorted(known))))
            return 2
        picked, full_why, self_tests = set(args.zones), None, []
    else:
        picked, self_tests, full_why = set(), [], None
        changes = changed_files(args.since)
        if not changes:
            print("no changes found - nothing to test.")
            return 0
        for path in changes:
            kind, val = classify(path)
            if kind == "full" and full_why is None:
                full_why = "%s (matched %s)" % (path, val)
            elif kind == "zone":
                picked.add(val)
            elif kind == "self":
                self_tests.append(os.path.join(REPO, val))
        print("changed: %d file(s)" % len(changes))

    if full_why:
        print("FULL suite: %s" % full_why)
        cmd = [sys.executable, "-m", "pytest", "tests/",
               "--ignore=tests/test_gui_smoke.py"] + extra
    else:
        files = zone_tests(picked) + sorted(set(self_tests))
        files = [f for f in files
                 if os.path.basename(f) != "test_gui_smoke.py"]
        if not files:
            print("zones: %s -> no tests to run." % (sorted(picked) or "none"))
            return 0
        print("zones: %s -> %d test file(s)"
              % (", ".join(sorted(picked)) or "(changed tests only)",
                 len(files)))
        cmd = [sys.executable, "-m", "pytest"] + files + extra
    print(" ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    if args.dry:
        return 0
    return subprocess.call(cmd, cwd=REPO)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
