"""One-click port: a modded project + stock card image(s) → built modded
card image(s).

The manual route a modder walks today for every model or version of a title —
extract the stock card, transfer the mods onto the extract, stage, build —
is four tabs of steps repeated per target (a Pro + Premium pair in two
soundtrack flavors is that walk FOUR times, on cards that take minutes to
extract and minutes to write).  This module is the sequencing for doing the
whole chain from one button: give it the project folder that holds the mods
and any number of stock card images, and each target gets extracted (once —
an existing extract is reused), transferred onto, staged, and built, in
order, unattended.

The heavy lifting stays where it already lives (the manufacturer's extract /
write pipelines, :mod:`.mod_transfer`, the app's staging), injected as
callables so this sequencing is testable without a card:

* ``extract(raw, workspace)`` — full stock extract of *raw* into *workspace*
  (including the checksum baseline).  Only called when the workspace has no
  baseline yet.
* ``transfer(workspace)`` — plan + apply the project's mods onto the
  extracted target; returns a one-line summary for the report.  Raises
  :class:`PortSkip` when nothing can transfer (the build would be an
  unmodified copy — skipped loudly instead).
* ``stage(workspace)`` — materialize the transferred Replace assignments
  into the workspace's files (the same staging a Write does).
* ``write(raw, workspace, output)`` — build *output* from *raw* + the
  staged workspace.

Each callable raises on failure; a failed target is reported and the run
CONTINUES with the next target — four ports shouldn't die at one bad card.
"""

import os

from .checksums import CHECKSUMS_FILE

#: Suffix of the per-target extract folder created beside the built images.
EXTRACT_SUFFIX = " extract"


class PortSkip(Exception):
    """Raised by ``transfer`` when none of the project's mods can land on a
    target — the port is skipped (never a silently-unmodified build)."""


def plan_ports(project_dir, target_raws, out_dir):
    """``[{"raw", "workspace", "output"}]`` for porting *project_dir* onto
    each of *target_raws*, everything landing under *out_dir*.

    The output keeps the stock image's name plus the project's, so four
    ports of one project stay tellable apart at a glance — and re-porting
    the same pair overwrites its own previous build, never a stranger's."""
    proj = os.path.basename(os.path.normpath(project_dir)) or "mods"
    jobs = []
    for raw in target_raws:
        stem, ext = os.path.splitext(os.path.basename(raw))
        jobs.append({
            "raw": raw,
            "workspace": os.path.join(out_dir, stem + EXTRACT_SUFFIX),
            "output": os.path.join(out_dir,
                                   "%s - %s%s" % (stem, proj, ext or ".raw")),
        })
    return jobs


def has_baseline(workspace):
    """Whether *workspace* already holds a finished extract.  The checksum
    baseline is written LAST by the extract, so its presence means the whole
    extract completed — a half-done folder re-extracts."""
    return os.path.isfile(os.path.join(workspace, CHECKSUMS_FILE))


def run_ports(jobs, extract, transfer, stage, write, log, cancel):
    """Run the chain for every job from :func:`plan_ports`, sequentially.

    Returns ``[(job, status, detail)]`` with status ``"ok"`` / ``"skipped"``
    (a :class:`PortSkip` — nothing transferred) / ``"failed"`` /
    ``"cancelled"``.  Cancellation stops between steps; the target being
    cancelled and every target after it report ``"cancelled"``."""
    results = []
    for i, job in enumerate(jobs):
        name = os.path.basename(job["raw"])
        if cancel():
            results.extend((j, "cancelled", "") for j in jobs[i:])
            break
        log("=== Port %d of %d: %s ===" % (i + 1, len(jobs), name), "info")
        try:
            if has_baseline(job["workspace"]):
                log("Reusing the finished extract at %s (delete that folder "
                    "to force a fresh one)." % job["workspace"], "info")
            else:
                extract(job["raw"], job["workspace"])
            if cancel():
                results.extend((j, "cancelled", "") for j in jobs[i:])
                break
            detail = transfer(job["workspace"])
            stage(job["workspace"])
            if cancel():
                results.extend((j, "cancelled", "") for j in jobs[i:])
                break
            write(job["raw"], job["workspace"], job["output"])
            results.append((job, "ok", detail or ""))
        except PortSkip as e:
            log("Port of %s skipped: %s" % (name, e), "warning")
            results.append((job, "skipped", str(e)))
        except Exception as e:
            if cancel():
                # A step interrupted BY the cancel is a cancellation, not
                # this target's failure.
                results.extend((j, "cancelled", "") for j in jobs[i:])
                break
            log("Port of %s FAILED: %s" % (name, e), "error")
            results.append((job, "failed", str(e)))
    return results


def summarize(results):
    """Human summary of a :func:`run_ports` result set, one line per target,
    ready for the completion dialog and the log."""
    lines = []
    for job, status, detail in results:
        name = os.path.basename(job["raw"])
        if status == "ok":
            lines.append("%s -> %s\n    (%s)"
                         % (name, job["output"], detail or "built"))
        elif status == "skipped":
            lines.append("%s: skipped - %s" % (name, detail))
        elif status == "cancelled":
            lines.append("%s: cancelled" % name)
        else:
            lines.append("%s: FAILED - %s" % (name, detail))
    n_ok = sum(1 for _j, s, _d in results if s == "ok")
    head = "Ported the project onto %d of %d card image(s)." % (
        n_ok, len(results))
    return head + "\n\n" + "\n".join(lines)
