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

3. **Run the test suite** before anything else gets touched:
   ```
   python -m pytest tests/ --ignore=tests/test_gui_smoke.py
   ```
   Abort the release if anything fails.  The `test_gui_smoke.py` Tcl error is pre-existing infrastructure noise — ignore it via the `--ignore` flag, NOT by skipping the whole run.

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

   Do NOT bump per-plugin versions (e.g. `plugins/jjp/__init__.py:__version__ = "3.7.0"`) — those are independent and track the upstream tool's version.

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
  # vX.Y.Z — <title>

  ## Highlights
  <2-4 paragraphs of WHAT'S NEW for the user>

  ## <Optional category> notable bits
  <bullets>

  ## Requires
  <any new external dependencies, e.g. libpinmame, ffmpeg, gdre_tools>
  ```
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
