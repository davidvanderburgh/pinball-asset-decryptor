---
description: Guided release workflow — bump version, update README, commit, push, tag, publish GitHub release
---

# /release

Run a full release cycle for **pinball-asset-decryptor**.  The goal is
one command that handles every mistake-prone step in the right order
so we never again ship a tag where `__version__` lags the tag string
(see v0.3.0 vs v0.3.1).

**Async by design.**  A release carries ~12 minutes of unavoidable
waiting (local pytest ~2 min, test CI ~2.5 min, installer builds
~7-8 min) and NONE of it is watched in the foreground:
- The local test suite runs as a background task underneath the
  bump/README work and is joined just before the commit (step 6).
- Both CI waits (steps 7b and 9b) run as background `gh run watch`
  tasks; each one re-invokes this session when it finishes, and the
  tag / publish steps happen in those background-notified turns.
The attended portion ends at the push in step 7 with the interim
report — target well under a minute of foreground waiting.  Never
foreground-block on pytest or a CI run, and never poll in a sleep
loop.

## Steps (do these in order)

1. **Sanity-check the tree.**
   - `git status` — note any uncommitted changes.
   - `git log --oneline $(git describe --tags --abbrev=0)..HEAD` — see what's landed since the last tag.
   - If the tree is dirty, ask the user whether to roll those changes into this release or stash them first.

2. **Read current state.**
   - Current version from `pinball_decryptor/__init__.py` — look for `__version__ = "X.Y.Z"`.
   - Latest tag from `git tag --sort=-v:refname | head -1`.
   - The two SHOULD match the same `vX.Y.Z`.  If they don't, surface the mismatch.

3. **Start the test suite in the background** — do NOT wait for it here:
   ```
   python -m pytest tests/ --ignore=tests/test_gui_smoke.py
   ```
   Launch this as a background task NOW and keep going — it takes
   ~2 minutes and nothing in steps 4-5 depends on it.  The result is
   collected in step 6, before anything is committed.  The
   `test_gui_smoke.py` Tcl error is pre-existing infrastructure noise —
   ignore it via the `--ignore` flag, NOT by skipping the whole run.

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
   - **Screenshots:** still match the current GUI?  Stale screenshots are worse than no screenshots.  (The embedded `docs/screenshots/*.png` are regenerated at GUI-commit time — step 5c only verifies freshness, and never edits them by hand.)

   Use `git log $(git describe --tags --abbrev=0)..HEAD -- README.md` to see the last time README was touched relative to the release log.  If the README hasn't been updated but the code has changed substantially, that's a signal — propose specific README edits before committing the release.

   When in doubt, ask the user: *"The README hasn't changed since vN.N.N-1 but the code added <feature>; want me to update §X to mention it?"*

5c. **Verify the README screenshots are fresh — regeneration at release
   time is the fallback, not the norm.**  The README's "What it looks
   like" section embeds `docs/screenshots/*.png` captured from the live
   app by `scripts/take_screenshots.py`.  **Convention (since
   2026-07-21): screenshots are regenerated when the GUI change itself
   is committed** — as part of the smoke-test-before-push beat, in the
   same commit as the GUI change — NOT at release time.  A minute of
   live GUI capture doesn't belong on the release critical path.

   At release time, only check freshness.  First, did this release
   touch the GUI at all?
   ```
   git diff --stat $(git describe --tags --abbrev=0)..HEAD -- \
       pinball_decryptor/gui pinball_decryptor/app.py
   ```
   - **Diff empty** → skip entirely.  Never re-capture on non-GUI
     releases: every capture differs at the byte level (log
     timestamps), so it's pure repo bloat with zero visual change.
   - **Diff non-empty** → confirm the screenshots kept pace:
     ```
     git log -1 --format='%ct %h' -- docs/screenshots
     git log -1 --format='%ct %h' -- pinball_decryptor/gui pinball_decryptor/app.py
     ```
     If the screenshots' last commit is at or after the last
     GUI-touching commit, they're fresh — move on.

   **Fallback — GUI changed but nobody re-captured** (or step 5b
   flagged a shot as stale): regenerate now:
   ```
   python scripts/take_screenshots.py
   ```
   - The script launches the real GUI on screen for about a minute and
     captures the picker / Extract / Replace Audio / Replace Images /
     Partition Explorer screens into `docs/screenshots/`, sourcing the
     Stern card image + extract folder already saved in the app's
     settings.json.  It aborts up front (leaving the existing PNGs
     untouched) if that data isn't on this machine — if it aborts, skip
     the refresh and say so in the release summary rather than blocking
     the release.
   - **Eyeball every regenerated PNG before committing** (Read each
     file): the capture is automated and a half-rendered pane or an
     error dialog in a shot is worse than a slightly outdated one.  If
     a shot looks wrong, keep the committed version of that file
     (`git checkout -- docs/screenshots/<name>.png`) and note it.
   - Commit the refreshed PNGs as part of the release commit (step 6),
     and note the miss in the release summary so the commit-time
     convention gets re-applied next time.

5d. **Audit the in-app tab tips (the header "?" button).**  Same class
   of user-facing doc as the README (5b), and it drifts the same way.
   The tips live in `HELP_CONTENT` in
   `pinball_decryptor/gui/help_dialog.py` — a `{tab-name: [(title,
   body), ...]}` dict rendered by the "?" button for whichever notebook
   tab is showing (Extract / Audio / Video / Images / Text / Defaults /
   Write / Mod Pack / Partitions).  When a release adds, renames, moves,
   or removes a GUI control or workflow, the tip for that tab must
   follow, or the "?" text describes an app that no longer exists.

   Gate on whether the GUI actually changed:
   ```
   git diff $(git describe --tags --abbrev=0)..HEAD -- \
       pinball_decryptor/gui pinball_decryptor/app.py
   ```
   - **No GUI change** → skip.
   - **GUI changed** → for each control/label/button/flow this release
     touched, open `HELP_CONTENT` and check the matching tab's tips.
     A button renamed (e.g. "Flash image" → "Build / flash SD card"),
     a control that moved tabs, a new checkbox/mode, a consolidated or
     removed button, or a changed default all need their tip text
     updated to match.  A brand-new tab needs a new `HELP_CONTENT` key.
     Edit the tips in the SAME release commit (step 6).
   - Cross-check that no tip names a control by an old caption: grep the
     just-changed button/label strings against `help_dialog.py`.  If a
     tip still says the old name, it's stale.

   When the fix isn't obvious, ask the user: *"This release renamed
   <control>; the <Tab> tip still calls it <old name> — update it?"*

6. **Join the test suite, then stage + commit.**  Before staging
   anything, collect the result of the background pytest task from
   step 3.  If it hasn't finished yet, stop and wait for its completion
   notification — do NOT busy-poll it and do NOT commit ahead of it.
   Abort the release if anything failed.  Then commit.  Commit message
   format:
   ```
   vN.N.N - <one-line summary of what this release does>

   <2-5 sentence paragraph or bullet list of notable changes — focus
   on WHAT the user sees, not WHAT files changed.  Mention any
   feedback contributors by name (e.g. "joe_blasi feedback").>

   Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
   ```
   Use a HEREDOC for the commit body so newlines + apostrophes survive.

7. **Push to main.**
   ```
   git push origin main
   ```
   No PR — user pushes directly to main always.  (Memory: `feedback_no_prs.md`.)

7b. **Start a background watch on CI — the tag still gates on green,
    but nobody waits in the foreground.**

    Local green isn't enough — CI runners often have fewer packages installed than the dev env.  v0.4.0 shipped with a broken Williams plugin because Pillow lived in my local Python but wasn't in the CI workflow's pip-install step; `load_plugins()` swallowed the ImportError and Williams silently disappeared from the registry across all three runner OSes.  Catch this BEFORE the tag goes out — asynchronously.

    Resolve the run id in the foreground (fast):
    ```bash
    HEAD_SHA=$(git rev-parse HEAD)
    sleep 5  # let GitHub register the workflow trigger
    RUN_ID=$(gh run list --workflow=test.yml --commit "$HEAD_SHA" \
                       --json databaseId --jq '.[0].databaseId')
    ```
    - If `RUN_ID` is empty, retry the lookup once after a few more
      seconds; if still empty, either the workflow doesn't run on this
      branch or GitHub is still processing the push — ask the user
      whether to proceed without the gate.
    - Otherwise start `gh run watch "$RUN_ID" --exit-status` **as a
      background task**, print the interim report (see "What to report
      back"), and END THE TURN.  Steps 8-10 happen in the turns where
      the background watches complete — do not sit in a foreground
      wait, and do not pre-announce results the watch hasn't produced.

    When the watch completes:
    - **Green** → proceed to step 8 immediately (tag this commit).
    - **Red** → do NOT tag.  The push is on main and stays there — fix
      forward: read the failure (`gh run view $RUN_ID --log-failed`),
      make the fix, commit + push again, and start a new background
      watch.  When CI is finally green on a commit, that's the commit
      you tag.
    - **Transient GitHub 503s / watch died** → just start a fresh
      background watch on the same run id.

8. **Tag annotated.**  Tag body = a short release-note summary (different from the commit body — these end up as the GitHub release description).
   ```
   git tag -a vN.N.N -m "$(cat <<'EOF'
   vN.N.N - <title>
   <body>
   EOF
   )"
   git push origin vN.N.N
   ```

9. **Create the GitHub release as a DRAFT.**  A published release is
   visible to `releases/latest` the instant it's created, but the
   installer assets upload from the four `Build Release Installers` CI
   jobs minutes later — apps in the field saw the v0.69.5 update banner
   while the release page had zero downloads on it.  Draft-first keeps
   the release invisible to every update checker until at least one
   asset exists (step 9b flips it live as soon as the FIRST asset
   attaches, NOT after all four — David wants each platform downloadable
   the moment its own installer is ready, so Windows users aren't held
   up by the ~4x-slower Intel Mac build).  Publishing early is safe
   because the app gates per-platform client-side: `updater._release_ready`
   only surfaces an update to a given OS once THAT OS's asset is present
   (`*_Windows.exe` / `*_macOS_*.dmg` / `*.AppImage`), so a live release
   carrying only the Windows asset never prompts a Mac user with a dead
   link.  The only residual exposure is app versions that predate that
   client-side gate; that population shrinks every release, and the
   zero-asset window is still covered by drafting until the first asset.
   ```
   gh release create vN.N.N --draft --title "vN.N.N — <short title>" --notes "$(cat <<'EOF'
   <markdown release notes — can be more elaborate than the tag body;
   include screenshots / links / highlights / requirements>
   EOF
   )"
   ```
   Create the draft IMMEDIATELY after pushing the tag — the installer
   workflow's fallback (`gh release view || gh release create
   --generate-notes`) creates a NON-draft release if none exists yet,
   and `gh release view`/`upload` resolve drafts by tag name fine, so
   an early draft is what keeps that fallback from firing.

9b. **Publish at the FIRST asset, then background-watch the rest.**
    Each platform's installer job attaches its own asset independently
    (fastest first: Linux + Apple Silicon land ~2 min in, Windows ~5 min,
    Intel Mac ~6.5 min).  Flip the release live the moment the first
    asset exists so users on the ready platforms download immediately;
    the per-platform client gate (step 9) keeps the not-yet-built
    platforms silent.

    Start TWO background tasks and END THE TURN:
    1. A "publish at first asset" watcher — polls the release and flips
       it live as soon as one asset is attached, then exits:
       ```bash
       until [ "$(gh release view vN.N.N --json assets \
                    --jq '.assets | length' 2>/dev/null)" -ge 1 ]; do
         sleep 15
       done
       gh release edit vN.N.N --draft=false
       ```
    2. The installer-run watch (`gh run watch <id> --exit-status`,
       `--workflow=release.yml`) so the remaining assets finish
       attaching to the now-live release.

    When the installer-run watch completes:
    - If an upload step failed on a transient GitHub error,
      `gh run rerun <id> --failed` — builds are per-job, so only the
      failed uploads redo.  Start a fresh background watch on the rerun.
      (The release is already live with whatever assets DID build; the
      rerun just backfills the missing one — a partial-platform release
      is acceptable per the publish-early policy, but always backfill.)
    - When green, verify all four assets are attached and print the URL:
    ```
    gh release view vN.N.N --json assets --jq '.assets[].name'
    # expect: *_Windows.exe, *_macOS_AppleSilicon.dmg,
    #         *_macOS_Intel.dmg, *_Linux_x86_64.AppImage
    ```

10. **Draft a message for the tester / user.**

    After the release is published, write a SHORT, plain-text message the user can forward to whoever tests or requested the changes (e.g. monkeybug).  This is separate from the GitHub release notes — it's a casual DM, not documentation.

    Rules (this is text the USER sends onward, see `feedback_no_emdash_short_messages.md`):
    - **No em dashes.**  Keep it to a few lines.
    - Plain text, no markdown headings.
    - Lead with what's new that *they* care about and what to try next.  Name the version.
    - If a fix addressed their specific report, say so by name.

    Present it in its own copy-pasteable fenced block, clearly labelled so the user knows it's the forward-to-tester message (distinct from the release-summary in "What to report back" below).  Example shape:
    ```
    Shipped v0.50.0. New Partition Explorer tab lets you browse a card image and pull files or folders out without mounting it. And your renamed image-group names now survive re-extracting the same card. Give the explorer a try and tell me if a folder ever opens empty.
    ```

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

Because the command spans background turns, there are two reports.

**Interim report** — printed at the end of the attended turn, right
after the push in step 7b (this is where the user walks away):

- New version + previous version, and the commit count since last tag.
- Confirmation the release commit is pushed, which CI run is being
  watched in the background, and what happens next without them
  ("will tag, draft, and publish when CI is green — no action needed").

**Final report** — printed in the background-notified turn after the
release is published (step 9b), together with the forward-to-tester
message from step 10:

- New version + previous version.
- Number of commits since last tag.
- Tag SHA.
- Release URL.

So the user sees a clean final summary like:

```
Shipped v0.3.1 (was v0.3.0).
1 commit since v0.3.0.
Tag: 4245e42
Release: https://github.com/davidvanderburgh/pinball-asset-decryptor/releases/tag/v0.3.1
```
