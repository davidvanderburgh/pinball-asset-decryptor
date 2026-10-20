# PAD-645 - attract flipper sounds on every Spike 2 game and version

Follow-up to PAD-641 (the Audio tab's **Attract flipper sounds**, built and emulator-proven on the three
James Bond 007 builds). David: make it work on all the other games, every version, older and locally
derived builds included.

## What was short, and what changed

| Gap (PAD-641) | Change |
|---|---|
| Shipped ports with a shot dispatch never had the framework's switch drain written into them | `portswitch.drain_source`: the drain's own lines (sites, tables, values) with no `switch` lines; appended to the 19 shipped ports that lacked it (The Beatles 1.30, also on the list, has no card or port) (`site switch_edge` / `switch_drain`, `data switch_records` / `switch_count`, the `switch_*` values; `mode_mask` checked equal to each port's own). Recipes rebuilt (and Bond LE/Pro 1.06's, already stale on main). |
| TMNT Pro 1.58's port had no `site sound_play` | Placed at 0x2ae830: TMNT Pro 1.59 and LE 1.59 (strict) and The Beatles 1.29 (loose) agree. |
| Ports derived on the user's machine (older builds) | `port_derive.framework_core` writes the drain, and this build's own drain values, on every derived port, shots or not (portgen REVISION 5, so cached derived ports re-derive). Fixed on the way: with the references now carrying `site switch_edge`, a derive must still read the build's own switch shots and values (Elvira 1.11, Foo Fighters LE 1.03, Bond 60th 1.10, Jaws LE 1.01, JP LE 1.15 derive again). |
| Older and derived builds had no carrier (`mode_sounds` TITLES) | `mode_sounds.own_calls`: calls read off the build's own play tables (one sid, one record no other sid names and no other request plays, mono, longest first). The engine uses them where no carrier was measured. Batman 66 1.13 picks request 715 (13.24 s), exactly Batman 1.14's measured 720 shifted by 5. |
| A card of attract sounds alone was gated as a card of sounds in turn | `mode_write.sound_modes_plan` gates on what `sounds.cfg` carries: attract alone takes `attract_refusal`. |
| The drain hooked for the attract sounds would also count switch shots | Runtime `edge_shots`: the drain's edges are the port's shots only where `switches_arm` made them so. A drain added for the attract sounds says `value switch_edge_shots 0` (the 19 ports above, and derived ports whose shots come from a dispatch), so The Beatles 1.29 keeps its switch_hit sites; every other port keeps the drain's edges as its shots, switch_hit sites or not, as on main (Godzilla Pro 1.16, James Bond: an earlier draft of this rule moved them to switch_hit). Profiles (`mode_project`) follow the same rule. |
| The game's own sound at an attract press could play with ours (PAD-641 let both) | Decided: ours replaces it. The build adds a short silent record (pseudo file 17, `aquiet` in sounds.cfg); a request the sound worker takes within 500 ms of either edge of a flipper button in attract (not the carrier) has its record lookups for 60 ms take the silence. |
| TMNT Pro 1.58's sound bank derived 7 of its 2053 sounds (since 6c5c0c15, v0.49.3) | `emulator.plt_branches`: the validated build's own PLT handlers are not branched through the GOT a second time (operator new ran twice). Its audio extract is whole again. |

## The attract bit

The edge log (`value switch_edge_log`) prints the game's mode mask at every flipper button edge. On every
build swept: 0x0010 in attract, 0x0000 in a game, generations A and B alike. `mode_mask_attract` stays 0x10.

## The game's own sound at a press (census)

The sweep's sound log (`/dump/soundlog.on`, now armed on a card of attract sounds alone too) lists the
requests the sound worker takes within 0.6 s of a press (`C:/tmp/PAD-645/census.py`). Most games hand
one of their own to the worker at a press (Deadpool 179 at the release, Batman 58/63, Godzilla LE 1.16
64 now and then), and most of those never look a record up while ours plays. The Beatles 1.29's 403
did, at the first press, and played the silence; the capture held only our tones.

## Carrier lengths

Each flipper sound plays for at most its carrier's record: 2.25 s (Bond 60th LE 1.11) and 2.37 s
(Star Wars) are the shortest, most are 3-15 s, Jaws 45.7 s. A stock attract callout is shorter than
the shortest, so no sound-bank route for longer files.

## Proof

`C:/tmp/PAD-645`: `build645.py` (one build: derive its port into a scratch PAD_TITLE_CACHE, a one-sound
scratch project, three tones 500/1000/2000 Hz as flipper sounds, `engine.write_overrides`),
`build_all.py` (every card in the library), `run645.sh` (rigbatch job: six presses in attract 3 s
apart, then a game and three presses in it; VERDICT pass = files 1 2 3 1 2 3 in press order, each
looked up, nothing in the game), `census.py`, `/c/tmp/PAD-608/rig/freqruns.py` (tones in order in the
capture). Results: see the ticket's report.

## Left out

- TMNT Pro 1.58 and TMNT LE 1.58 (the 1987 card): the app cannot read each sound record's play key on
  them (Pro: the codec's validated path never reads one; LE: its bank does not derive, on main too),
  so nothing can say which record a request plays. Refused up front (`ATTRACT_NO_KEYS`).
- Venom LE 1.06: an older framework (event bus bound 201, every other B build 207) whose switch drain
  matches neither signature; its derived port has no drain, so it is refused.
- The Beatles 1.30: no card in the library (a hand-made copy of 1.29's port sat in the old cache).
