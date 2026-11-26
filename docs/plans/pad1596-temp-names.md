# PAD-1596: the space keeper knows every temp folder the app makes

## What was wrong
`core/host_temp.py` held ten prefixes; the app made about sixty more names in
`%TEMP%` (plus fixed folders and files). A crash or cancel left those for good
and neither Manage disk space nor the space keeper saw them. Found on David's
PC: 2,565 PAD entries, of which main's window listed 543.

## What changed
- `core/pad_temp.py` is the one list (`NAMES`: name, maker, what it is, and
  its rule). `host_temp` and `space_keeper` read it.
- `pad_temp.mkdtemp` notes the process that made a folder
  (`%TEMP%\pad_temp_owners\<name>`, pid + process start time). Every app site
  uses it, as does Stern's `_work_dir`. The keeper never takes a folder whose
  maker still runs, and takes one whose maker died after an hour instead of a
  day. The window marks such a folder "(in use)" and its Clean skips it.
- Caches marked `kept` are never removed whole. Their entries age out
  (`child_days`): Stern card copies, clips, compiled objects and build
  params after 30 days unused; card menu previews after 7. A half-written
  `<key>.tmp<pid>` whose writer is gone goes after an hour.
- Empty leftovers are removed too. They used to be skipped for ever.
- The card-menu preview cache prunes itself (7 days) and touches the folder
  it shows.
- "Load modes from a folder" removes the zip it makes.
- Unnamed temp files got names (`pad_diskpart_`, `pad_bof_`, `pad_scbin_`).
  Two generic tool names moved under `mkmulticard.`.
- Tests run with a private temp folder (`tests/conftest.py`), so test builds
  stop leaving `spike2_grow_*` / `pad-swap-*` in the real `%TEMP%`.
- `tests/test_pad_temp.py` parses the tree and fails on any temp name that
  is not registered (mkdtemp/mkstemp/TemporaryDirectory/NamedTemporaryFile
  and `os.path.join(gettempdir(), ...)`), or any app `tempfile.mkdtemp`
  that bypasses the wrapper.

## Proof
- Stand-in temp folder: a keeper run went from 10 folders / 907 MB to 1 / 12 MB,
  keeping the one held by a live process.
- David's real `%TEMP%`, dry run: main would remove 13 entries; the branch
  would remove 2,286 (18.3 GB), nearly all names main never knew.
