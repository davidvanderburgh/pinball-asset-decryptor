#!/usr/bin/env bash
# Build and attach a Windows release's delta-update assets (PAD-1519): the
# file list (<installer>.delta.json.gz) and the pack of this release's new
# files (<installer>.delta.pack).  See installer/make_delta.py for what they
# are and pinball_decryptor/core/update_delta.py for what the app does with
# them.
#
# RUNS BEFORE THE SETUP EXE IS ATTACHED, and that order is the point: the
# app offers a release the moment its setup exe is up, and a copy that looks
# then - David's own, minutes after every release - must find the file list
# already there, or it downloads the whole installer after all.  The pack
# goes up before the file list for the same reason: the file list is what
# the app acts on.
#
# NEVER IN THE WAY OF THE RELEASE.  The workflow step is continue-on-error
# with a short timeout, and the uploads here get two attempts, not five: a
# release without delta assets just updates the old way (the app falls back
# to the setup exe by itself), while a late setup exe is a late release.
#
# The pack only holds files that no earlier release's pack has, so this
# looks back through the last releases for the newest one with a file list
# and hands it to make_delta.py as --previous.  None found (the first
# release with this script, or a run of releases whose delta step failed)
# packs every file: ~270 MB, once.
#
# Usage:  build_delta_assets.sh TAG          (from the repo root, after
#         installer/build.ps1; needs GH_TOKEN and GITHUB_REPOSITORY)
set -uo pipefail

TAG=${1:?usage: build_delta_assets.sh TAG}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is not set}
LOOK_BACK=${DELTA_LOOK_BACK:-20}

exe=$(ls installer/Output/*_Windows.exe 2>/dev/null | head -n 1)
[ -n "$exe" ] || { echo "::warning::no setup exe in installer/Output - no delta assets" >&2; exit 1; }

prev_dir=$(mktemp -d)
prev=""
tags=$(gh api "repos/$REPO/releases?per_page=$LOOK_BACK" \
         --jq '.[] | select(.draft | not) | select(.prerelease | not) | .tag_name' 2>/dev/null || true)
for t in $tags; do
  [ "$t" = "$TAG" ] && continue
  case "$t" in v[0-9]*) ;; *) continue ;; esac
  if gh release download "$t" --repo "$REPO" --pattern '*_Windows.delta.json.gz' \
       --dir "$prev_dir" >/dev/null 2>&1; then
    prev=$(ls "$prev_dir"/*.delta.json.gz 2>/dev/null | head -n 1)
    [ -n "$prev" ] && { echo "previous file list: $t"; break; }
  fi
done
[ -n "$prev" ] || echo "no earlier release has a file list - packing every file"

if [ -n "$prev" ]; then
  python installer/make_delta.py --installer "$exe" --previous "$prev" --repo "$REPO" || exit 1
else
  python installer/make_delta.py --installer "$exe" || exit 1
fi

pack=$(ls installer/Output/*.delta.pack | head -n 1)
list=$(ls installer/Output/*.delta.json.gz | head -n 1)
ATTACH_MAX_ATTEMPTS=${ATTACH_MAX_ATTEMPTS:-2} \
  bash "$HERE/attach_release_asset.sh" "$TAG" "$pack" || exit 1
ATTACH_MAX_ATTEMPTS=${ATTACH_MAX_ATTEMPTS:-2} \
  bash "$HERE/attach_release_asset.sh" "$TAG" "$list" || exit 1
echo "delta assets attached to $TAG"
