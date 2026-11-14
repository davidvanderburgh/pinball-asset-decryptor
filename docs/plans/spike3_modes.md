# Custom modes on a Stern Spike 3 card (PAD-1272)

PAD-1269 built the mode runtime for Spike 3's 64-bit ARM games (`prebuilt/mode64.so`), gave
s3run.sh a preload hook (`PAD_S3_MODE_SO`) and made the Modes tab name a Spike 3 card. This is
the plumbing that puts a project's modes ON a Spike 3 card and runs them in Try it. A title's
port (PAD-1271 for Star Wars ELG) is the only thing a Spike 3 build still needs.

## Where the modes go

A Spike 2 card carries them on the system partition (`/usr/local/padmode`, game_monitor
hooked: `tools/spike2_emu/modehook.py`). A Spike 3 card's rootfs is LUKS2 like every partition
but it is the signed image's, and a Write changes only the games partition (p6), so:

| on p6 | what |
|---|---|
| `pad/padmode/mode.so` | mode64.so, 0755 root |
| `pad/padmode/game.port`, `mode.cfg`, `mode1.cfg` ..., `stock.cfg`, `pad_modes.zip` | as on Spike 2, 0644 root |
| `pad/padmode/padmode.sh` | the hook, 0755 |
| `pad/padmode/game.target` | where `/games/game` pointed on the stock card |
| `game` | `-> pad/padmode/padmode.sh` |

`/etc/init.d/S95game` -> `game_monitor` runs `/games/game` in a restart loop and reads its
exit code. The hook appends the runtime to `LD_PRELOAD` and `exec`s the program `game.target`
names, so game_monitor reads the game's own code and conagent (its own monitor) never sees the
runtime - Spike 3 multi-boot's road from the same link (`tools/spike3_emu/MULTIBOOT.md`). A hook
with no target runs the card's first game program stock: never a dead machine. A multi-boot
card takes no modes (each image is a whole games tree; modes are made for one build).

The runtime's sources name `/usr/local/padmode/<file>` everywhere; the 64-bit build alone wraps
`open()` so those paths open `/games/pad/padmode/<file>` (pad_mode_runtime.c, `pm_card_open`).
The Spike 2 mode.so is byte-identical.

## Write (spike3_write -> spike3_modes)

1. `spike3_modes.plan` - the preview switch, code modes (left out: compiled for Spike 2's
   32-bit ARM), `card_refusal` (no port / no Insider gate), a multi-boot card, then
   `mode_write.plan` against the card's own 64-bit program (`/games/game`'s target; the port
   check reads ELF64), with no own sounds or end sound (carriers in Spike 2's sound bank).
   `p2_payload(arch="a64")` stages mode64.so as `mode.so`.
2. A mode that cannot be built stops the Write before the 62 GB copy; a refusal leaves the
   modes out with the reason and writes the rest, as on Spike 2.
3. The scenes the modes' screens and clips rewrite go on whole with the grown files (their
   `.sidx` records refreshed by the existing loop).
4. After the copies, `spike3_modes.install` runs over the volume through dm-crypt
   (`ext4_grow.run_on_luks`: the grow script's mount with a body of its own).
5. A card an earlier build put modes on, written now with none, has them taken off
   (`/games/game` back to `game.target`, `pad/padmode` gone).

The engine (`_compute_patches`) no longer builds the Spike 2 mode family onto a Spike 3 volume:
modes are spike3_write's; random clips, music modes, editions, picture settings, attract
items, co-op, idle, handicaps, light shows, Prolonged Competition, the score feed and screen
times are left out with one sentence (they ride Spike 2's delivery).

## The Modes tab and Try it

- The tab's card read (`title_reader`) opens a Spike 3 card's games partition with the user's
  key and reads `/games/game`'s program. `port_derive.ensure_port` takes, for a 64-bit program,
  the listed port of its game whose every site is the program's own (never one derived here).
  **Star Wars ELG 1.10 has a Spike 2 build of the same game folder and version** whose shipped
  port is passed over by that test - but `mode_runtime.port_paths` keeps ONE port per
  (game, version), so a Spike 3 port of that build must not share the Spike 2 port's file name
  and header (PAD-1271's to settle).
- Try it on a Spike 3 card: the Modes tab builds the same set from the card
  (`_tryit_prepare_s3`), and the Emulate tab's Spike 3 start now runs the prepare (it skipped
  it) and hands `--mode-so` / `--mode-files` to s3launch.sh -> `PAD_S3_MODE_SO` /
  `PAD_S3_MODE_FILES`. Screens and clips are not shown in Try it on Spike 3 (no override set
  on that rig); a Write puts them on the card.
- s3run.sh on a card with modes: a plain run (binfmt) runs the card's own hook; a
  checkpointable run or the explicit qemu runs programs only, so s3run does the hook's two
  steps (the target program, the card's mode.so preloaded); with `PAD_S3_MODE_SO` (Try it) the
  card's is not loaded too. Its host-side readers (switch list, bridge, playfield) read the
  program the hook names.

## Proof (2026-11-14)

Star Wars ELG 1.10 from the library + a copy of PAD-1271's draft port (process-only):
`write_card` copied the card (595 s), planned PAD TEST against the card's 64-bit program and
installed 4 files; read back through the card's own encryption: `/games/game -> pad/padmode/
padmode.sh`, `game.target = star_wars_elg/game`, root-owned 0755/0644, mode.so = mode64.so.
Booted on rig slot 72 (muted, hidden): plain run - the card's hook started the game and the
runtime logged `port /games/pad/padmode/game.port`; checkpointable run - s3run started
`/games/star_wars_elg/game` with the card's mode.so; with a port naming only `tick` the game ran
to the cap (61 frames, 6 node boards, its Game Setup screen) with the runtime inside it ("Nothing
is hooked; the game runs stock"). Try it: the tab's prepare built the set from the card and the
stock card ran it with the runtime reading `/dump/game.port` (7 sites). The draft port's own
crash 0.8 s in (seen in PAD-1271's runs too) is the port's, not the delivery's.

## The first Spike 3 port (PAD-1271)

`ports/spike3/star_wars_elg-1.10.port`, drafted by `tools/spike3_emu/s3port.py` from the
proven Spike 2 port of the same build (`s3port.py <S2 game> <S2 port> <S3 game> -o <port>`):
functions paired by vtable slot, unique strings and call-graph growth (both programs are
stripped), globals by what the paired functions load through the GOT, switches renumbered by
name from the program's own device table (Spike 3's ids are one lower), scores 64-bit. It
carries only what the 64-bit runtime has been run with: the tick, event dispatch (ball end is
bus event 0x34), score_add, the two switch_hit sites, the Insider gate, and cur_player /
scores / score_mult / mode_mask. Every other placed site is written as a comment with its
address: the runtime features that use them still read the game's structs at 32-bit offsets,
and arming them stopped the game (the "crash 0.8 s in" above was the full draft). Each is
carried when its feature is made 64-bit and proven. The runtime fixes it needed are in
hook_a64.h (hidden template labels, a branch as a hooked first instruction, a veto read from w0)
and pad_mode_runtime.c (a 64-bit achievement-query scan, the switch id masked to 16 bits).

Proof: a TRENCH RUN mode (3 trigger shots, 30 s, 5 award shots) on the Spike 3 emulator, slot
41, muted and hidden, with `prebuilt/mode64.so` and this port: it started on the third trigger,
scored 1M..5M on five shots (score 26,630 -> 15,080,990) and ended when its time ran out, the
game running on to the cap. Tests: tests/test_pad1271_spike3_port.py.
