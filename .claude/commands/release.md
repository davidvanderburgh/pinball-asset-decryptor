---
description: Guided release workflow — bump version, update README, commit, push, tag, publish GitHub release
---

# /release

Run a full release cycle for **pinball-asset-decryptor**.  The goal is
one command that handles every mistake-prone step in the right order
so we never again ship a tag where `__version__` lags the tag string
(see v0.3.0 vs v0.3.1).

## Steps (do these in order)

1. **Sanity-check the tree.**
   - `git status` — note any uncommitted changes.
   - `git log --oneline $(git describe --tags --abbrev=0)..HEAD` — see what's landed since the last tag.
   - If the tree is dirty, ask the user whether to roll those changes into this release or stash them first.

2. **Read current state.**
   - Current version from `pinball_decryptor/__init__.py` — look for `__version__ = "X.Y.Z"`.
   - Latest tag from `git tag --sort=-v:refname | head -1`.
   - The two SHOULD match the same `vX.Y.Z`.  If they don't, surface the mismatch.

3. **Run the test suite locally** before anything else gets touched:
   ```
   python -m pytest tests/ --ignore=tests/test_gui_smoke.py
   ```
   Abort the release if anything fails.  The `test_gui_smoke.py` Tcl error is pre-existing infrastructure noise — ignore it via the `--ignore` flag, NOT by skipping the whole run.

   **Local green is necessary but NOT sufficient.**  Local envs tend to have more installed than CI runners (e.g. Pillow lives in my dev env but wasn't in the CI workflow's pip-install step, which silently broke Williams plugin discovery for the entire v0.4.0 release).  See step 7b below — we don't tag until CI is green on the just-pushed commit.

4. **Decide the bump.**
   - Default to **patch** for bugfixes / small tweaks.
   - **Minor** for new user-visible features (new plugin, new pipeline mode, new GUI surface).
   - **Major** only for breaking changes to the user-facing CLI / file format.
   - Ask the user if it's not obvious from the commit log.

5. **Bump the version EVERYWHERE.**  The mistakes here are what motivated this command.  Files that may carry the version:
   - `pinball_decryptor/__init__.py` — `__version__ = "X.Y.Z"` (REQUIRED — this is what the title bar reads).
   - `README.md` — scan for hardcoded `v0.2.0`-style strings and any `vX.Y.Z` placeholder text.
   - `pyproject.toml` if present (it isn't currently, but check anyway).
   - Any `setup.py` / `setup.cfg` (none currently, but check).

   Per-plugin versions are gone as of v0.6.5 — the plugin code is no longer tracked separately from the unified app, so the only `__version__` that matters is the one at the top of `pinball_decryptor/__init__.py`.  If you spot a `__version__` constant in a `plugins/<name>/__init__.py`, that's almost certainly a regression from a fresh upstream lift and should be deleted (or, if it must stay for compatibility, NOT bumped — it represents the original lifted-from version for provenance only and is never shown to users).

5b. **Audit README content** (separate from the version-string scan above).  The README is user-facing documentation — when a release adds a new plugin, pipeline, capability, or changes a workflow, the README description of *what the app does* needs to follow.  This is NOT just find-and-replace.

   Walk through the README and ask, for each section:
   - **Title / one-liner:** still accurate?  Adding a major manufacturer often means the tagline ("decrypts X, Y, Z files") needs the new format added.
   - **Supported games / manufacturers:** new plugin since last release?  Add it to the picker / capability matrix.
   - **Quick Start / Usage:** new GUI surface (e.g. new tabs, new checkboxes, new modes)?  Update the screenshots or step-by-step.
   - **Prerequisites:** new external dep (libpinmame, ffmpeg, GDRE Tools, etc.)?  Add to the prereq list AND the install instructions.
   - **Capabilities table:** if there's a table of "what plugin X does," verify capture / write / modpack / etc. flags match the new code.
   - **Output structure:** new file types in the output dir (e.g. per-scene MP4s)?  Document.
   - **Troubleshooting / FAQ:** common questions raised in feedback since last release?  Pre-empt them.
   - **Screenshots:** still match the current GUI?  Stale screenshots are worse than no screenshots.

   Use `git log $(git describe --tags --abbrev=0)..HEAD -- README.md` to see the last time README was touched relative to the release log.  If the README hasn't been updated but the code has changed substantially, that's a signal — propose specific README edits before committing the release.

   When in doubt, ask the user: *"The README hasn't changed since vN.N.N-1 but the code added <feature>; want me to update §X to mention it?"*

6. **Stage + commit.**  Commit message format:
   ```
   vN.N.N - <one-line summary of what this release does>

   <2-5 sentence paragraph or bullet list of notable changes — focus
   on WHAT the user sees, not WHAT files changed.  Mention any
   feedback contributors by name (e.g. "joe_blasi feedback").>

   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   ```
   Use a HEREDOC for the commit body so newlines + apostrophes survive.

7. **Push to main.**
   ```
   git push origin main
   ```
   No PR — user pushes directly to main always.  (Memory: `feedback_no_prs.md`.)

7b. **Wait for CI to pass on the just-pushed commit before tagging.**

    Local green isn't enough — CI runners often have fewer packages installed than the dev env.  v0.4.0 shipped with a broken Williams plugin because Pillow lived in my local Python but wasn't in the CI workflow's pip-install step; `load_plugins()` swallowed the ImportError and Williams silently disappeared from the registry across all three runner OSes.  Catch this BEFORE the tag goes out.

    ```bash
    HEAD_SHA=$(git rev-parse HEAD)
    sleep 5  # let GitHub register the workflow trigger
    RUN_ID=$(gh run list --workflow=test.yml --commit "$HEAD_SHA" \
                       --json databaseId --jq '.[0].databaseId')
    if [ -z "$RUN_ID" ]; then
        echo "No CI run found for $HEAD_SHA — workflow may not have triggered."
        # Either the workflow doesn't run on this branch, or GitHub's
        # still processing the push.  Ask the user whether to proceed
        # without the gate.
    else
        gh run watch "$RUN_ID" --exit-status
    fi
    ```

    If CI fails:
    - **Do NOT tag.**  The push is on main and stays there — fix forward.
    - Read the failure (`gh run view $RUN_ID --log-failed`), make the fix, commit + push again, and re-poll CI.
    - When CI is finally green on a commit, that's the commit you tag.

8. **Tag annotated.**  Tag body = a short release-note summary (different from the commit body — these end up as the GitHub release description).
   ```
   git tag -a vN.N.N -m "$(cat <<'EOF'
   vN.N.N - <title>
   <body>
   EOF
   )"
   git push origin vN.N.N
   ```

9. **Publish the GitHub release.**
   ```
   gh release create vN.N.N --title "vN.N.N — <short title>" --notes "$(cat <<'EOF'
   <markdown release notes — can be more elaborate than the tag body;
   include screenshots / links / highlights / requirements>
   EOF
   )"
   ```
   Print the resulting URL.

## Conventions to match the existing release history

- **Title format:** `vX.Y.Z — <short title>` (em dash `—`, not hyphen).
- **Tag prefix:** `v`, always.  `v0.3.0` not `0.3.0`.
- **Release notes structure** (the body of `gh release create --notes`):
  ```
  ## Highlights
  <2-4 paragraphs of WHAT'S NEW for the user>

  ## <Optional category> notable bits
  <bullets>

  ## Requires
  <any new external dependencies, e.g. libpinmame, ffmpeg, gdre_tools>
  ```
  - **Do NOT** start the notes body with `# vX.Y.Z — <title>` — GitHub already renders the title above the body from `--title`, so an H1 here shows as a duplicated header on the release page.  Open with `## Highlights` directly.
  - **Do NOT hard-wrap paragraph text inside the heredoc.**  GitHub's markdown renderer preserves the hard wraps as awkward mid-sentence line breaks at full-width display.  Write each paragraph as one long line and let the renderer reflow.  Bullets and headings stay on their own lines; only running prose should be unwrapped.
- **ROMs / paid content:** Never bundle or redistribute.  If a release adds ROM-dependent features, note "User-supplied. No ROMs are bundled or redistributed."

## Non-destructive default

- **Do NOT force-push** to main.
- **Do NOT force-update tags.**  If a tag was already pushed and is wrong, ship a `+0.0.1` patch release with the fix — don't re-point the tag.  (This is exactly how v0.3.1 fixed v0.3.0's missing `__version__` bump.)
- **Do NOT skip hooks** (no `--no-verify`).
- If the previous tag was pushed within the last hour and only by us, the user can OK a force-update via explicit instruction — but never do it without that instruction.

## What to report back

At the end, print:

- New version + previous version.
- Number of commits since last tag.
- Tag SHA.
- Release URL.

So the user sees a clean summary like:

```
Shipped v0.3.1 (was v0.3.0).
1 commit since v0.3.0.
Tag: 4245e42
Release: https://github.com/davidvanderburgh/pinball-asset-decryptor/releases/tag/v0.3.1
```
