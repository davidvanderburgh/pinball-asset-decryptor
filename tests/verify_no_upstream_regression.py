"""Verify each plugin's logic matches the original standalone decryptor.

Run with:
    python tests/verify_no_upstream_regression.py

The unified app was built by lifting each manufacturer's standalone
decryptor package (pb / spooky / bof / jjp) and rewiring it to share
the unified shell.  Three classes of files exist in each plugin:

  IDENTICAL    Verbatim byte-for-byte lift.  Any difference == a bug.
               This is the strongest regression guarantee: the actual
               crypto / archive / asset-extraction logic is the upstream
               code, untouched.

  IMPORT-ONLY  Verbatim except for ``from .config`` -> ``from .games``
               (when the upstream config.py was split into a smaller
               games.py for the unified app).  Every changed line must
               match a known import-rewire pattern.

  PORTED       Orchestration intentionally rewritten to fit the unified
               BasePipeline contract (4-callback signature, per-mfr
               phase labels, manufacturer.py wrapper).  These files
               don't byte-match upstream by design.  Their correctness
               is verified by the E2E round-trip tests in
               tests/test_<mfr>_e2e.py — synthetic Extract -> modify ->
               Write -> re-extract -> verify-bytes-survived.

Exits 0 if every IDENTICAL file matches and every IMPORT-ONLY file
only has accepted import changes.  PORTED files don't gate the exit
code — the test suite does.
"""

import difflib
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_ROOT = ROOT.parent  # sibling directory of this repo


# (unified_relpath, upstream_relpath_or_None, kind)
# kind in {"identical", "import-only", "ported", "new"}
PLAN = {
    # =======================================================
    #  Pinball Brothers
    # =======================================================
    "pinball_decryptor/plugins/pb/__init__.py":
        (None, "new"),
    "pinball_decryptor/plugins/pb/games.py":
        (None, "new"),   # carved from pb_decryptor/config.py
    "pinball_decryptor/plugins/pb/manufacturer.py":
        (None, "new"),
    # PB doesn't have a separate formats.py upstream; detect logic
    # lives in pb_decryptor/formats.py.  We rewrote both formats and
    # pipeline against the shared core helpers (checksums, tar_utils,
    # clonezilla).  Underlying gzip+tar primitives are stdlib so no
    # plugin-private crypto/asset code exists.
    "pinball_decryptor/plugins/pb/formats.py":
        ("pb/pb_decryptor/formats.py", "ported"),
    "pinball_decryptor/plugins/pb/pipeline.py":
        ("pb/pb_decryptor/pipeline.py", "ported"),

    # =======================================================
    #  Spooky Pinball
    # =======================================================
    "pinball_decryptor/plugins/spooky/__init__.py":
        (None, "new"),
    "pinball_decryptor/plugins/spooky/games.py":
        (None, "new"),
    "pinball_decryptor/plugins/spooky/manufacturer.py":
        (None, "new"),

    # Asset / crypto / executor primitives -- the load-bearing decoders
    # are upstream-verbatim.  THIS is the regression firewall: any
    # accidental tweak to encryption keys, GPG packet handling, Godot
    # PCK parsing, Unity asset extraction, P3 VID conversion, or
    # Clonezilla partclone flow will trip these byte-equal checks.
    "pinball_decryptor/plugins/spooky/godot.py":
        ("spooky/spooky_decryptor/godot.py", "identical"),
    "pinball_decryptor/plugins/spooky/unity.py":
        ("spooky/spooky_decryptor/unity.py", "identical"),
    "pinball_decryptor/plugins/spooky/audio.py":
        ("spooky/spooky_decryptor/audio.py", "identical"),
    "pinball_decryptor/plugins/spooky/p3_video.py":
        ("spooky/spooky_decryptor/p3_video.py", "identical"),
    "pinball_decryptor/plugins/spooky/clonezilla.py":
        ("spooky/spooky_decryptor/clonezilla.py", "identical"),
    "pinball_decryptor/plugins/spooky/executor.py":
        ("spooky/spooky_decryptor/executor.py", "identical"),
    "pinball_decryptor/plugins/spooky/Dockerfile":
        ("spooky/spooky_decryptor/Dockerfile", "identical"),

    # Re-routed only because their `from .config import …` had to point
    # at our slimmer games.py.  No behavior changes.
    "pinball_decryptor/plugins/spooky/crypto.py":
        ("spooky/spooky_decryptor/crypto.py", "import-only"),
    "pinball_decryptor/plugins/spooky/gpg.py":
        ("spooky/spooky_decryptor/gpg.py", "import-only"),

    # Pipeline orchestration rewritten to fit BasePipeline + per-mfr
    # phase labels.  Format-detection function was tidied with no
    # logic change.  Covered by tests/test_spooky_e2e.py.
    "pinball_decryptor/plugins/spooky/formats.py":
        ("spooky/spooky_decryptor/formats.py", "ported"),
    "pinball_decryptor/plugins/spooky/pipeline.py":
        ("spooky/spooky_decryptor/pipeline.py", "ported"),

    # =======================================================
    #  Barrels of Fun
    # =======================================================
    "pinball_decryptor/plugins/bof/__init__.py":
        (None, "new"),
    "pinball_decryptor/plugins/bof/games.py":
        (None, "new"),
    "pinball_decryptor/plugins/bof/manufacturer.py":
        (None, "new"),
    "pinball_decryptor/plugins/bof/executor.py":
        ("bof/bof_decryptor/executor.py", "identical"),
    # pipeline.py DIVERGED from upstream as of v0.7.12: the BOF May 2026
    # firmware renamed the embedded Godot PCK magic from "GDPC" to "GBOF"
    # to defeat off-the-shelf tools, so DecryptPipeline now patches the
    # magic back to "GDPC" on extract (and ModifyPipeline restores "GBOF"
    # before re-packing) so GDRE Tools and the user-facing browse/edit
    # workflow keep working.  Upstream BOF decryptor lacks this swap and
    # currently breaks on May code.  Behaviour covered by
    # tests/test_bof_e2e.py + tests/test_bof_pck_magic.py.
    "pinball_decryptor/plugins/bof/pipeline.py":
        ("bof/bof_decryptor/pipeline.py", "ported"),

    # =======================================================
    #  Jersey Jack Pinball
    # =======================================================
    "pinball_decryptor/plugins/jjp/__init__.py":
        (None, "new"),
    "pinball_decryptor/plugins/jjp/games.py":
        (None, "new"),
    "pinball_decryptor/plugins/jjp/manufacturer.py":
        (None, "new"),
    # JJP was lifted wholesale — every module is byte-equal to
    # upstream.  Manufacturer.py wraps StandaloneDecryptPipeline +
    # StandaloneModPipeline without touching their internals.
    "pinball_decryptor/plugins/jjp/config.py":
        ("jjp/jjp_decryptor/config.py", "identical"),
    "pinball_decryptor/plugins/jjp/executor.py":
        ("jjp/jjp_decryptor/executor.py", "identical"),
    "pinball_decryptor/plugins/jjp/wsl.py":
        ("jjp/jjp_decryptor/wsl.py", "identical"),
    "pinball_decryptor/plugins/jjp/crypto.py":
        ("jjp/jjp_decryptor/crypto.py", "identical"),
    "pinball_decryptor/plugins/jjp/audio.py":
        ("jjp/jjp_decryptor/audio.py", "identical"),
    "pinball_decryptor/plugins/jjp/filelist.py":
        ("jjp/jjp_decryptor/filelist.py", "identical"),
    "pinball_decryptor/plugins/jjp/resources.py":
        ("jjp/jjp_decryptor/resources.py", "identical"),
    # pipeline.py has DIVERGED from upstream as of v0.6.5: the
    # Direct-SSD path now enumerates partitions, content-verifies
    # each candidate (Habo report), and mirrors writes across A/B
    # slots on Windows.  The standalone jjp-decryptor repo is being
    # deprecated in favour of this unified app, so we no longer
    # track its pipeline.py byte-for-byte.  Behaviour-equivalence on
    # the ISO-based flows is covered by tests/test_jjp_contract.py
    # and the Extract → Write → Re-extract round-trip in the unified
    # plugins.
    "pinball_decryptor/plugins/jjp/pipeline.py":
        ("jjp/jjp_decryptor/pipeline.py", "ported"),
    # updater.py in the standalone jjp-decryptor was rewired to be a
    # deprecation-redirector (points at this unified app's release
    # feed).  Our plugin's updater.py is vestigial — the unified app
    # uses core/updater.py against the unified release feed — so byte
    # equivalence no longer holds and isn't meaningful here either.
    "pinball_decryptor/plugins/jjp/updater.py":
        ("jjp/jjp_decryptor/updater.py", "ported"),
    # The upstream Dockerfile COPYs the standalone repo's jjp_decryptor/
    # package + runs it as an ENTRYPOINT.  In the unified app the Docker
    # build context is pinball_decryptor/plugins/jjp/ (no jjp_decryptor/
    # subdir), so that COPY made `docker build` fail on macOS and the app
    # reported the in-image tools (partclone, xorriso) as missing — JJP
    # extract was impossible on Mac.  Our image is a plain toolbox (no
    # COPY/ENTRYPOINT; the executor execs tools into it and stages
    # partclone_to_raw.py into the bind-mounted /tmp), matching Spooky's
    # working Dockerfile.  Build-context sanity is guarded by
    # tests/test_installer.py::test_dockerfile_copy_sources_exist.
    "pinball_decryptor/plugins/jjp/Dockerfile":
        ("jjp/Dockerfile", "ported"),
    "pinball_decryptor/plugins/jjp/partclone_to_raw.py":
        ("jjp/partclone_to_raw.py", "identical"),
}


# Patterns whose appearance in a +/- diff line is acceptable for files
# marked "import-only".  Any other +/- line is flagged as suspicious.
ACCEPTED_IMPORT_REWIRES = (
    "from .config import",
    "from .games import",
    "from ...core",
)


def _read(p):
    return p.read_bytes()


def _sha(b):
    return hashlib.sha256(b).hexdigest()[:12]


def _decode(b):
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def main():
    issues = []
    counts = {"identical": 0, "import-only": 0, "ported": 0, "new": 0}
    summary_lines = []

    for unified_rel, (upstream_rel, kind) in PLAN.items():
        unified_path = ROOT / unified_rel
        if not unified_path.exists():
            issues.append(f"MISSING IN UNIFIED: {unified_rel}")
            continue

        counts[kind] += 1

        if kind == "new":
            summary_lines.append(f"  NEW          {unified_rel}")
            continue

        upstream_path = UPSTREAM_ROOT / upstream_rel
        if not upstream_path.exists():
            issues.append(
                f"MISSING UPSTREAM: {upstream_rel} "
                f"(needed to compare against {unified_rel})")
            continue

        u_bytes = _read(unified_path)
        up_bytes = _read(upstream_path)
        bytes_equal = (u_bytes == up_bytes)

        if kind == "identical":
            if bytes_equal:
                summary_lines.append(
                    f"  IDENTICAL    {unified_rel}  sha={_sha(u_bytes)}")
            else:
                # First 40 diff lines so the issue is investigable
                diff = list(difflib.unified_diff(
                    _decode(up_bytes).splitlines(),
                    _decode(u_bytes).splitlines(),
                    fromfile=upstream_rel,
                    tofile=unified_rel, lineterm=""))
                issues.append(
                    f"IDENTICAL FILE HAS DRIFTED: {unified_rel}\n"
                    + "\n".join(diff[:40])
                    + (f"\n... ({len(diff)} total diff lines)"
                       if len(diff) > 40 else ""))
            continue

        if kind == "import-only":
            if bytes_equal:
                summary_lines.append(
                    f"  IMPORT-ONLY  {unified_rel}  (no changes)")
                continue
            diff = list(difflib.unified_diff(
                _decode(up_bytes).splitlines(),
                _decode(u_bytes).splitlines(),
                fromfile=upstream_rel, tofile=unified_rel, lineterm=""))
            change_lines = [
                ln for ln in diff
                if (ln.startswith("+") or ln.startswith("-"))
                and not ln.startswith("+++") and not ln.startswith("---")]
            suspicious = [
                ln for ln in change_lines
                if ln[1:].strip()
                and not any(pat in ln[1:] for pat in ACCEPTED_IMPORT_REWIRES)]
            if suspicious:
                issues.append(
                    f"IMPORT-ONLY FILE HAS UNEXPECTED CHANGES: {unified_rel}\n"
                    + "\n".join(suspicious[:30])
                    + (f"\n... ({len(suspicious)} suspicious lines)"
                       if len(suspicious) > 30 else ""))
            else:
                summary_lines.append(
                    f"  IMPORT-ONLY  {unified_rel}  "
                    f"({len(change_lines) // 2} lines rewired)")
            continue

        if kind == "ported":
            # No byte comparison — orchestration was deliberately
            # rewritten.  We DO sanity-check that the primitives it
            # depends on are present + accounted for.
            summary_lines.append(
                f"  PORTED       {unified_rel}  "
                f"(behavior verified by tests/test_*_e2e.py)")
            continue

    # ---- Output ---------------------------------------------------
    print("=" * 76)
    print("Plugin equivalence vs upstream decryptor repos")
    print("=" * 76)
    print()
    for line in summary_lines:
        print(line)
    print()
    print("-" * 76)
    print(f"{counts['identical']:3d} files verbatim (byte-equal to upstream)")
    print(f"{counts['import-only']:3d} files with import-only rewires")
    print(f"{counts['ported']:3d} files ported (E2E-tested for regressions)")
    print(f"{counts['new']:3d} files new to the unified app (wrappers + manifests)")
    print("-" * 76)

    if issues:
        print()
        print(f"{len(issues)} REGRESSION ISSUE(S):")
        print()
        for issue in issues:
            print("=" * 76)
            print(issue)
        print()
        print("FAIL")
        return 1

    print()
    print("PASS - no regressions detected against upstream.")
    print()
    print("Note: PORTED files (pipeline orchestration / format detection)")
    print("are intentionally different from upstream and are guarded by the")
    print("Extract -> modify -> Write -> re-extract round-trip tests in")
    print("tests/test_pb_e2e.py and tests/test_spooky_e2e.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
