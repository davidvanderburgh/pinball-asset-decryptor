#!/usr/bin/env bash
# Attach installer assets to the GitHub release for a tag, with every upload
# BOUNDED and RETRIED.
#
# WHY THIS IS NOT A ONE-LINE `gh release upload`: on 2026-09-17 GitHub's asset
# upload endpoint (uploads.github.com) went erratic.  Some uploads took their
# usual 5-15 seconds; others sat for 16-30 minutes and then came back with an
# HTTP 500 "Error saving asset" or a 404.  `gh release upload` puts no time
# limit on a request, and its own retry (3 more tries, 200 ms apart) only
# starts once the server finally answers - so ONE bad connection parked a
# build job for half an hour: the v0.218.0 Windows job failed twice that way
# (52 minutes, no Windows asset), and v0.218.1's Linux job sat 25 minutes on
# an AppImage that uploads in 15 seconds.  Meanwhile other connections to the
# same endpoint were fine (the Intel DMG went up in 9 seconds while the
# AppImage crawled), which is exactly what a short deadline and a fresh
# connection fix.
#
# So: each attempt gets a deadline of ATTACH_ATTEMPT_SECONDS (default 60)
# plus 0.2 s per MB of the file: 74 s for the 70 MB Windows installer, 104 s
# for the 220 MB AppImage.  Healthy uploads run at 15 MB/s or better (the
# AppImage in 15 s), so that is four to five times the healthy time, and it
# still fits a slow-but-moving connection (the first live run of this
# script, on the day itself, saw its first try killed and its second land
# the AppImage in 46 s).  The per-MB part is why the Windows deadline, the
# one on the release's critical path, stays close to a minute.  A
# timed-out or failed attempt is killed, any same-named asset it left behind
# half-made (GitHub keeps those in "starter" state, and they block the name
# with a 422) is deleted, and the upload starts over on a new connection.
# Five attempts, then the step fails (~5.5 minutes): if five fresh
# connections from the runner all failed, a sixth is not the fix - an upload
# from the developer's machine is, and that is what /release does with the
# job's artifact when the Windows asset is late.  The two never fight: a
# retry here first looks for a fully uploaded asset of the same name and
# keeps it, and the fallback runs with ATTACH_KEEP_EXISTING=1, which does
# the same before its first attempt (the default, off, is for reruns of a
# green job, which should replace what they built earlier).
#
# Usage:  attach_release_asset.sh TAG FILE...
# Env:    ATTACH_ATTEMPT_SECONDS (60, plus 0.2 s per MB of the file)
#         ATTACH_MAX_ATTEMPTS (5)  ATTACH_RETRY_PAUSE (5)  ATTACH_KEEP_EXISTING (0)
#
# Runs under GitHub's `shell: bash` on all three runner OSes (Git Bash on
# Windows; bash 3.2-compatible for macOS, which is also why the deadline is
# hand-rolled: macOS ships no coreutils `timeout`) and under any local bash
# with an authenticated gh, which is how /release calls it as the fallback.
set -uo pipefail

TAG=${1:?usage: attach_release_asset.sh TAG FILE...}
shift
[ $# -ge 1 ] || { echo "::error::attach_release_asset.sh: no files to attach" >&2; exit 2; }

ATTEMPT_SECONDS=${ATTACH_ATTEMPT_SECONDS:-60}
MAX_ATTEMPTS=${ATTACH_MAX_ATTEMPTS:-5}
RETRY_PAUSE=${ATTACH_RETRY_PAUSE:-5}
KEEP_EXISTING=${ATTACH_KEEP_EXISTING:-0}

# run_with_deadline SECONDS CMD...: run CMD, kill it if it is still running
# after SECONDS.  Returns 124 on a kill, CMD's own status otherwise.
run_with_deadline() {
  local limit=$1; shift
  "$@" &
  local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$limit" ]; then
      kill "$pid" 2>/dev/null
      sleep 2
      kill -9 "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      return 124
    fi
    sleep 1
    waited=$((waited + 1))
  done
  wait "$pid"
}

# asset_uploaded NAME: true when NAME is on the release and fully uploaded.
asset_uploaded() {
  gh release view "$TAG" --json assets \
      --jq ".assets[] | select(.name == \"$1\" and .state == \"uploaded\") | .name" \
      2>/dev/null | grep -q .
}

# The release normally exists before any build finishes: /release drafts it
# right after pushing the tag.  This fallback makes a plain one so a tag
# pushed by hand still gets its assets.
gh release view "$TAG" --json id >/dev/null 2>&1 \
  || gh release create "$TAG" --verify-tag --generate-notes \
  || true

status=0
for file in "$@"; do
  name=$(basename "$file")
  attached=0
  if [ "$KEEP_EXISTING" = "1" ] && asset_uploaded "$name"; then
    echo "$name: already on the release, fully uploaded - leaving it"
    continue
  fi
  # 0.2 s per MB on top of the base: bytes / (5 * 1048576).
  deadline=$(( ATTEMPT_SECONDS + $(wc -c < "$file") / 5242880 ))
  attempt=1
  while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    t0=$SECONDS
    # --clobber: a rerun of a green job replaces its earlier asset.
    run_with_deadline "$deadline" gh release upload "$TAG" "$file" --clobber
    rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "$name: attached in $((SECONDS - t0))s (attempt $attempt)"
      attached=1
      break
    fi
    if [ "$rc" -eq 124 ]; then
      echo "::warning::$name: attempt $attempt killed after ${deadline}s"
    else
      echo "::warning::$name: attempt $attempt failed (exit $rc) after $((SECONDS - t0))s"
    fi
    if asset_uploaded "$name"; then
      echo "$name: already on the release, fully uploaded - leaving it"
      attached=1
      break
    fi
    gh release delete-asset "$TAG" "$name" --yes >/dev/null 2>&1 || true
    attempt=$((attempt + 1))
    sleep "$RETRY_PAUSE"
  done
  if [ "$attached" -ne 1 ]; then
    echo "::error::$name: not attached after $MAX_ATTEMPTS attempts"
    status=1
  fi
done
exit $status
