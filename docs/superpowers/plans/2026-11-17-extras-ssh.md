# Extras SSH Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Configure key-only SSH from Replace → Extras and apply it to built cards, exposing only emulator-qualified platforms.

**Architecture:** A project-state module and platform adapter prepare a checked system-partition copy before pipeline success. A tab service uses existing RPC/state conventions. Emulator qualification controls an explicit platform allowlist.

**Tech Stack:** Python, PAD's ext filesystem reader and platform executors, debugfs/e2fsck, existing HTM/Preact UI, Dropbear, Podman/QEMU.

**Spec:** `docs/superpowers/specs/2026-11-17-extras-ssh-design.md` (approved 2026-11-17).

## Global Constraints

- No platform enablement without successful real-image emulator tests of this integration.
- Original images, live cards, cabinets, and existing emulator containers remain untouched.
- Public keys and SSH enablement stay out of shared mod exports/imports.
- SSH failures prevent success and chained flashing. Disabled configuration must work on rebuilds.
- Stern generations are distinct platforms; no manufacturer-wide support inference.

## Review Focus

- Source aliases and device paths must not permit editing an original or live disk.
- Unrecognized source SSH services must not be overwritten as if PAD owned them.
- Incremental outputs must not retain a stale authorized-key list or enabled hook.
- Imported or switched projects must not inherit another project's access settings.
- Flash-only and Direct-SD paths must refuse pending system changes rather than silently omit them.

### Task 1: Validated project state and keys

**Files:** Create `pinball_decryptor/core/card_extras.py`, `tests/test_card_extras.py`.

**Interfaces:** `load(project) -> dict | None`; `save(project, enabled, public_keys) -> dict`; `validate_keys(text) -> str`; `configuration(project) -> dict | None`; `ExtrasError`.

- [x] Write tests for real ed25519/RSA/ECDSA wire keys, private/malformed/unsupported keys, CRLF, comments, blank input, disabled retention, project isolation, malformed records, and export/import exclusion.
- [x] Run `.venv/bin/python -m pytest -q tests/test_card_extras.py`; expect missing module failures.
- [x] Implement bounded SSH-wire validation and staged state preserving unrelated sections; do not invoke host ssh-keygen in production.
- [x] Repeat tests; expect pass. Commit state module and tests.

### Task 2: Checked image preparation and payload

**Files:** Create `pinball_decryptor/core/ssh_card.py`, `pinball_decryptor/resources/ssh/`, `tests/test_ssh_card.py`.

**Interfaces:** `inspect_image(path) -> dict` (platform, supported, reason, enabled, public_keys); `validate_request(original, project) -> dict | None`; `apply_to_build(original, output, config, log=None, cancel=None) -> str`; qualification registry initially empty.

- [x] Write tests using tiny real ext filesystems for partition bounds/overlaps, source identity, ownership/modes/content, preserved bytes outside rootfs, repeated enable/key replacement/disable, missing or mismatched payload, insufficient filesystem room, cancellation and failed filesystem checks.
- [x] Run tests and confirm feature is missing.
- [x] Implement read-only identification, hash-pinned resources, scratch-rootfs mutation and read-back verification before bounded output write; reject foreign daemons and unsafe filesystem objects. Use PAD's executor for filesystem utilities. Include payload licenses and reproducible build source.
- [x] Repeat tests; expect pass. Keep adapters unavailable until Task 5 qualifies them.

### Task 3: Pipeline and write-path integration

**Files:** Modify `pinball_decryptor/plugins/stern/pipeline.py`, `pinball_decryptor/app.py`, `pinball_decryptor/webui/write_scan.py`; create `tests/test_extras_pipeline.py`.

**Interfaces:** Consume Task 1 configuration and Task 2 validation/preparation. Pipeline reports failure if extras preparation fails, before its existing successful `_done` callback.

- [x] Write tests for SSH-only build, preparation-before-success, preflight-before-engine, failed/canceled preparation, incremental rebuild configuration changes, pending preview row, and flash/direct-write refusal.
- [x] Run tests; expect missing integration failures.
- [x] Integrate Stern build pipeline and app preflight/flash/direct-write guards. Keep unrelated platforms refused unless an adapter and its pipeline are qualified.
- [x] Repeat tests plus existing Stern write/flash regressions; expect pass. Commit backend integration.

### Task 4: Extras tab

**Files:** Create `pinball_decryptor/webui/tabs/extras.py`, `pinball_decryptor/webui/static/js/tabs/extras.js`, `tests/test_webui_extras.py`; modify tab registry/window gates as necessary.

**Interfaces:** RPC `extras.configure(enabled, public_keys, project)` validates project identity; `extras` state includes project, supported, reason, enabled, public_keys, error, running.

- [x] Add web-harness tests for rail placement, supported/unsupported card behavior, project switching, saved state, invalid enabled configuration, disabled text retention, running-state lock, and inherited source SSH inspection without staging a change.
- [x] Run tests; expect missing tab failures.
- [x] Implement form in existing page style; use a labeled multiline public-key field, key-only explanation, and explicit unsupported reason. Preserve draft input while reporting validation errors, without enabling invalid state.
- [x] Repeat tests; expect pass. Validate in a real browser with the available Browser plugin or Playwright fallback; check interactions, console, and screenshot. Commit UI.

### Task 5: Emulator qualification and delivery

**Files:** Create `scripts/validate_card_ssh.py` and `docs/validation/2026-11-17-extras-ssh.md`; update packaging scripts and qualification registry. Add additional platform adapters only after their own passing tests.

- [x] Generate disposable client keys before building images with the PAD injector. Never replace the injected keys to make a test pass.
- [x] Start dedicated containers with the image-derived guest rootfs; invoke actual guest boot/service integration. Verify two authorized keys, wrong key/password rejection, SFTP round trip, persistent host identity, key replacement, and disabling.
- [x] Run the resulting card through the existing game emulator to its known attract/startup milestone; record exact image and payload hashes plus commands/results and service-vs-kernel emulation limits.
- [x] Investigate Pulp Fiction and other available cards; qualify only if their image preparation, boot integration, authentication, disable, preservation, and game tests all pass. Record unsupported candidates and reasons.
- [x] Add qualified platform ids to the registry, package the resources on macOS/Linux/Windows, and run all feature tests plus relevant existing regressions.
- [x] Perform fresh whole-branch review, resolve actionable issues with regression tests, and verify clean diff/test evidence. Commit the reviewable feature branch; do not push or merge.
