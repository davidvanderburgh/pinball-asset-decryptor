# PAD-722: mode features made for one game, and which can go to every game

David asked (2026-10-25): "What features for modes have we added for specific games that can be ported to all
games". This is the answer as of v1.254.0, measured, not recalled: every shipped port read through
`mode_project.profiles()` (69 builds, 53 of them the newest build of a title, the library), every site/data/value line
counted across the 53 newest ports, the clip and menu routes checked on each newest card's game program, and the LE
recipe of a one-title feature run on its sibling to see if the code is there.

One gap was LE/Pro parity, and David's standing rule covers that (LE and Pro get the same support), so it is closed
in this ticket. The rest are new features for other titles, each needing its own run per title, so they are listed
below for David to choose from.

## Closed here: James Bond Pro 1.06 had less than James Bond LE 1.06

The LE got four things on PAD-428 / PAD-521 / PAD-547 that its Pro never did, though the Pro runs the same code:

| LE line | What a mode gets | Pro 1.06 |
|---|---|---|
| `site status_bar` | its name, colour and clock (or PAD-721's fill) in the game's own bar under the TV | `0x00184aec` (LE `0x1862dc`); the same 0x128-byte score display, its frame update `0x185ac4` reading the same +0x104..+0x121 fields |
| `text info_line_at 679 510` | its info line ("SUPER JACKPOT = ...") under that bar, not on it | the same HUD scene (7de1c159), the same place |
| `value backdrop_surface 1` | its loop on the TV, taken back after the game's main-play video | the Pro had the clip v2 and backdrop_idle lines already |
| `site film_complete` + six `film_*` events | Starts on / Ends on "Dr. No done" .. "Diamonds Are Forever done" | `0x001d3134`, called by the collect `0x1cf08c` (LE `0x1d0918`, identical code) |

The LE's recipe (`port_derive._draft_one` with `james_bond_le-1.06.recipe.gz` on the Pro's program) places
status_bar and film_complete strictly, and the frame update and collect were read side by side.

**Emulator proof** (2026-10-25, PAD-Runtime rig 1, the stock Pro 1.06 card, hidden, muted; kit `C:/tmp/PAD-722`):
FRWL WIZARD as blocks: it starts on `film_frwl` and has its name in the bar, an info line and its own clip on loop.
An instrument (`film_instr.c`) calls the game's collect for From Russia With Love's four parts.
- main: the four parts started nothing. Started by its trigger file, the mode logged "this port has no backdrop",
  the bar stayed empty and the info line landed on the bar's spot (the default 680,450).
- this branch: the mode started 119 ms after the fourth part (`START (a block)`), `status bar: taken for "FRWL
  WIZARD" in 2060ff, with its wipe`, the loop on the video bank's surface and taken back after MainPlayLoop_DrNo,
  the blue bar with its clock and SUPER JACKPOT = 5,000,000 under it on the glass. No abort in either run.

The other way round, the Pro's port has lines the LE's lacks (`message_*`, `frame_end/kick`, `scene_show`,
`live_records`, `clip_stop`). The LE's recipe run on LE places them all, but none changes what a mode on Bond does:
frame_end/kick only run on a build without clip v2, the scene_show backdrop also needs `backdrop_draw`, live_records
needs `mode_records_*`, and messages only serve the award screen, which Bond does not have. So nothing was added.

Every other LE/Pro difference among the newest builds is the machine itself. The Pros of Bond, Jurassic Park and
Mandalorian have no magnet, Avengers Pro and Iron Maiden Pro no scoop, John Wick Pro no diverter (`machine_absent`),
and Rush Pro's own rules use its magnet at the shot (PAD-475).

## Can go to every game: features gated to one game that other games have the route for

Coverage is out of the 53 newest builds.

| Feature (ticket) | Works on | What limits it | Route elsewhere | What porting takes |
|---|---|---|---|---|
| Random clips: a slot plays one of several clips (PAD-446) | Godzilla Pro + Premium/LE 1.16 | `clip_variants.PROVEN` only | clip hook route on **51 / 53** (45 clip v2 surface, 6 clip_play; Deadpool LE/Pro have none) | an emulator sweep (rigbatch) seeing a variant swapped on each build, then the list widened |
| Editions: EDITION in the menu picks a multi-boot image (PAD-495) | Godzilla 1.16 | `editions.PROVEN` | the menu setting's take-over reads on **31 / 53**; 22 say "the game's operator menu pages could not be read" (Aerosmith, Elvira 3, Foo Fighters, Guardians, Led Zeppelin, Mandalorian, Munsters, Rush, Sword of Rage, TMNT, Venom) | the 31: a sweep booting each edition. The 22: `menu_settings.category_table` taught their table's other shape first |
| Music modes: MUSIC MODE picks a set of sounds (PAD-494, 511, 608, 638) | Godzilla 1.16 | `sound_modes.PROVEN` + `site sound_resolve`, only in Godzilla's ports | sounds in turn / at random (PAD-565/638, `sound_lookup`) already work on **53 / 53**; the menu reads on 31 | `sound_resolve` found per title (the descriptor resolver), then a sweep |
| A mode's clip back where it would be after a game's clip (PAD-530) | Bond LE/Pro | `site surface_seek/duration/position`, only in Bond's ports | the same player code under every clip v2 surface (45) | the three sites placed per build (Bond's are at layout distances from surface_play), and a sweep |
| Backdrop on the bank's surface (PAD-521) | Bond LE/Pro (now) | `value backdrop_surface 1`: opted in per port once seen | every clip v2 build has the surface (45); `text backdrop_idle` names each game's own main-play video | each title's main-play video named, and a sweep |
| The game's own award screen for an Award block (item 154) | Godzilla 1.16 / Pro 1.15, Beatles | `award_screen_arg` + `award_*_at` values | `site award_screen` is in all **53** ports | the argument table and the three offsets read per build; elsewhere an Award shows on the mode's own screen (PAD-574) |

## Probably not worth it

- **Picture settings** (PAD-537, Godzilla 1.16): switched off on every title by PAD-575 (the GPU cost).
- **The status bar** beyond Bond: it is Bond's own HUD part (the coloured bar under the TV). Another title would
  first need such a bar in its HUD. Its info line, PAD-547, already works on every title with screens (each title
  without `info_line_at` puts it at 680,450).
- **Lights in the game's own light language** (Godzilla 1.16): the other 51 hold the inserts in the mode's colour,
  and PAD-500/503/598/601 lighting works on every title through the lamps.

## Not portable: the feature is the game's own

- Godzilla: the battle selection (PAD-589/699/706/707), shield and building (Premium/LE), Ebirah and tank rules, the
  Mechagodzilla magnet and bridge.
- James Bond: film events (no other title has films; other titles' events are the bus events every port has),
  its lock multiballs (PAD-578), its lit-shot flash calls (PAD-642), the right return post hold (PAD-621), its four
  mini-wizards claim (PAD-457).
- Each title's own mechanisms (`*_label` / `*_drive` lines): a mode holds whichever one the machine has.

## Coverage of the generic mode features (53 newest builds)

Lights, screen, clip, own sound, waiting for the game's modes and the game's own modes ("place") work on all 53.
Countdown: 48, because Aerosmith (both), Elvira 3 and John Wick (both) never say a number (PAD-479). Challenges: 46.
Dungeons & Dragons LE/Pro, Bond 60th, King Kong LE/Pro and X-Men LE/Pro still need a route. The game's light shows
and sounds in turn work on all 53. The shaker works on 50 and the game's mini-wizards on 49. The shaker is missing
only where the machine has no shaker (Bond 60th, Jurassic Park The Pin, Star Wars ELG), and the mini-wizards only
where the game has none of its own (Bond 60th, Munsters LE/Pro, Star Wars ELG: `NO_GAME_WIZARDS`). The other
gaps in the counts over all 69 ports are older builds, which the library no longer boots (David, 2026-10-20).
