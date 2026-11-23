# Delta updates on Windows (PAD-1519)

David: "Update installer takes a while. Can we do automatic delta updates? so
instead of replacing all the files, we just do the new ones? I know we have AB
installs, but we need to speed them up somehow."

## What was slow

The blue-green update (PAD-1024, `core/update_slots.py`) already made Restart to
update quick: two folder renames, about 7 s to the new window. What it did not
change is how the new version gets ready beside the running one: the whole
setup exe is downloaded and run with `/STAGED=2`.

| | measured |
|---|---|
| setup exe | 157 MB |
| installed app | 710 MB, 8,300 files (python 553 MB, app package 90 MB, tools 68 MB) |
| "Installing in the background" on David's PC (his session log, 8 updates) | 35-56 s |
| download on his line | 3 s; minutes on a slow one |
| files a typical release changes | a dozen source files |

## What it does now

Each Windows release publishes two more assets beside the setup exe
(`installer/make_delta.py`):

- `<installer>.delta.json.gz`, the **file list**: every file the installer
  installs, with size and SHA-256, and where its bytes are: which release's
  pack, at what offset.
- `<installer>.delta.pack`, the **pack**: the files of this release that no
  earlier release's pack holds, each compressed on its own, end to end.

An installed copy offered a release with a file list
(`core/update_delta.py`, called from `App._stage_update_from_changes`):

1. downloads the file list (0.5 MB) and checks it against the SHA-256 GitHub
   publishes for it;
2. builds `<app>.next`: a file whose installed copy has the listed hash is
   copied from the running install (read once, hashed and written from the
   same bytes); any other file is fetched from its pack with an HTTP range
   request, unpacked, and checked against its hash before it gets its name;
3. compiles what changed (the installer's own `compileall` line; unchanged
   modules keep their `.pyc`), carries over what the user's install has that a
   fresh one lacks, writes the staged marker.

From there it is the same swap as before. The setup exe is never downloaded.

Measured on a copy of David's real v1.574.0 install, to a v1.575.0 with seven
changed files (`C:\tmp\PAD-1519\scripts\e2e.py`): **ready in 4.7 s, 0.14 MB
downloaded in one request**, the result identical to the release's file list,
the swapped-in copy's own Python importing the new version.

## Decisions worth knowing

- **The pack holds only what is new.** David ships about ten releases a day; a
  whole pack each time would be another 270 MB upload on the release's
  critical path and 3 GB a day of release storage. The file list names earlier
  releases' packs for unchanged files (by tag and asset name, never a URL).
  The first release, or one whose predecessors have no file list, packs
  everything once. A pack that is gone (a yanked release) is noticed at build
  time and its files are packed again; an app that meets a missing pack falls
  back to the setup exe.
- **The file list is the installer's own.** `make_delta.iss_files` reads the
  `[Files]` section of `pinball_decryptor.iss` with Inno's rules for
  wildcards, `recursesubdirs` and `Excludes`. Checked against David's real
  install of the same version: 2,196 files outside `python\`, the same set,
  the same bytes. A flag or parameter it does not model stops it (no delta
  assets for that build; the setup exe is unaffected). The release workflow's
  `check-delta` job then installs the real setup exe and compares
  (`make_delta.py --verify`), and takes the delta assets off the release if
  they disagree.
- **`.pyc` files are not in the list.** pip compiles the bundled packages at
  build time with the build's timestamps inside, so they differ on every
  build and would be 2,500 "changed" files per release. Unchanged sources keep
  the `.pyc` the install has (the copy keeps the source's timestamp, so it
  stays valid); changed ones are compiled.
- **Permissions without the walk.** The installer's `icacls /reset /T` and
  `/grant /T` over the finished Python tree were 9 of the first run's 13 s.
  A delta writes every file itself, so the grant goes on the empty `python`
  folder first and every file inherits it: the same ACLs, no walk.
- **Before the setup exe.** The app offers a release the moment its setup exe
  is up, so the delta assets are attached first (pack, then file list). Their
  step is `continue-on-error` with two upload attempts: a release without
  them just updates the old way.
- **Any failure is the installer's turn.** No file list, no published digest
  for it, a hash mismatch, a missing pack, a server that ignores ranges, more
  to fetch than the setup exe: the log says why and the setup exe is
  downloaded and staged as before. A swap that fails with no setup exe on
  disk brings the old version back up and notes the version, and the next try
  fetches the installer.

## Not done

- macOS and Linux update as before (a disk image and an AppImage: one file
  each, nothing to diff file by file without a different mechanism).
- With "Download and install updates in the background" switched off, Install
  update still downloads and runs the setup exe.
- The first update after this ships is still a full one: the delta code has to
  be in the running copy.
