# Official Stern stock fingerprints (PAD-426)

Step 1 of better revision control. Step 2 is the project-lineage ticket opened alongside this one.

## Why

"Stock" used to mean whatever card was extracted:

- `.checksums.md5` is a baseline of the extracted card. Extract a revision and that revision becomes "stock" for Changed, Transfer mods and the build warnings.
- `.pad-build.json` only recognises a card that PAD built on THIS machine. A shared custom card (Heisei) looks official.
- The version stamp comes from the update index (`/spk/index/<title>-<ver>.sidx`), and a built card keeps that index. Heisei 1.96 reads as "Godzilla LE 1.16".

PAD-421 is the case that showed this: DragonRR's Heisei project was built over an older stock extract.

## What ships

`pinball_decryptor/plugins/stern/data/stock_prints.json.xz` holds one entry per official Spike 2 release. The key is the card's own sidx name, e.g. `godzilla_le-1_16_0.sidx`. Each entry has:

- `folder`, `name`, `version`, `edition`, and `card`, the file name it was read from.
- `files`: `{path: [size, md5[:16]]}` for every file Stern's validation manifest indexes. That covers every `scene.radium` and `scene.assets/*.asset` (pictures and videos), loose pictures, `image.bin` (the sound bank), the `image-scNN.bin` music banks, the `game` program, and the node firmware.
- `pictures`: the `md5[:8]` of every picture inside the release's radiums. These are the same digits the extract puts at the end of `radimg_..._<md5[:8]>.png`.

The table is hashes only: no Stern bytes, names or pictures.

`scripts/make_stock_prints.py D:\Pinball\images\Stern\spike2` builds it. It reads the newest Release build of each title (only the latest versions are supported; `--all` reads every build). It refuses a card with a `.pad-build.json` beside it, or a card that disagrees with its own manifest:

- every file's size is checked;
- the bytes of every file up to 32 MB are re-hashed (scenes, pictures, program, about 10 s a card);
- `--full-verify` re-hashes the videos and the sound bank too (about 5 min a card on the spinning disk).

The first run proved Godzilla LE 1.16 and Aerosmith Pro 1.16 with `--full-verify`.

## How a card is checked

Every Spike 2 card carries a `.sidx`, and every PAD build rewrites the records of the files it changed (`sidx.py`). A card built elsewhere need not. DragonRR's Heisei V1.93 replaced 541 videos and kept every one's stock size and MD5 in its manifest. So the manifest is a starting point, not the answer:

1. One metadata walk, the same one the Image Info probe does.
2. Each file's real size comes from its inode, which is free because the walk already read it. A size that disagrees with the manifest's record marks the file changed. This is the quick check that Card details runs.
3. Deep check (the after-Extract stamp): every file whose size still agrees is hashed too. That catches same-size swaps; Heisei had one more video, 542 in all, in about 7 s from NVMe.
4. Diff the result against the release its sidx names. Read the changed radiums to count their pictures that are not in the stock picture set.
5. Count the manifest records that disagree with the card's files. When there are any, the app says the card's manifest still lists them as Stern's, so PAD did not build it.

The result is "official" or "modified", with counts of scenes, pictures, videos, the sound bank, music banks, the program and other files. A sidx the table does not know is "unknown", and the app says so rather than guessing.

Caveat: the sound bank is repacked by every build, so "the sound bank differs" means PAD rebuilt it, not necessarily that a sound changed. Per-sound answers still need the two extracts (the Compare tab's job).

## Where the app says it

- **Select card / Card details**, Firmware section: an "Official release" row. For example, "Official Godzilla LE 1.16 - every file matches the card Stern released (by the card's manifest and file sizes).", or "Godzilla LE 1.16, modified: differs from the official card in 27 scenes, 66 pictures, 541 videos, the sound bank, the game program. Its own manifest still lists 541 changed files as Stern's, so it was not built by PAD."
- **Extract**: when an extract finishes, the deep check runs in the background. Its verdict is logged ("Source card: ...") and stamped into the project's `.extract_source.json` as `stock`.
- **Extract / This project**: a "Stock" row. It shows the stamped verdict. An older project with no stamp is answered from its `radium_images.txt` picture names against the release named by its `card_version`. With no version, only an exact match names a release.

## Size: ship in the app

The 53 latest releases come to 1,024,164 bytes as xz (2.3 MB as gzip, 14.5 MB of JSON). That is small enough to ship in the app, so there is no fetch, no network dependency and no update channel. Regenerate it when a new Stern build lands: run the script and commit the table. Windows ships it through the installer's recursive copy. Linux and macOS have an explicit `--add-data`.

## Not done here (step 2)

- Making `.checksums.md5`, Changed and Transfer mods measure against the OFFICIAL release instead of the extracted card.
- Project lineage across machines (which revision a project came from, and what it was built over).
