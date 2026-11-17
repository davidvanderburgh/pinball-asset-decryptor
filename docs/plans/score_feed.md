# Score feed (PAD-1204)

C0untDeM0net (Pinside, post #482): "a high score display external from the games running on a TV ... capture the end
game scores and user info if logged in, then push them to an external server separate from IC".

## What was built

- **Play options tab > Score feed** (`webui/tabs/playopts.py`, `playopts.js`; state and `set_score_feed` on the Modes service): a tick, an address box and the API contract, kept in
  the project sidecar as `score_feed: {"on", "url"}` (`plugins/stern/score_feed.py`). The address is checked there:
  `http://`, an IPv4 address, optional port and path.
- **The build** (`engine._feed_for_build`, `mode_write.feed_plan` / `feed_into`): `scorefeed.cfg` beside the runtime
  on p2, with the address, the card's name and, when `coop_play.insider_users` finds them, the game's Insider login
  tables. A card with nothing else is a plan of its own and keeps Insider Connected.
- **The runtime** (`pad_mode_runtime.c`, "the score feed"): at each game's end, one JSON POST (players, final scores,
  each logged-in player's Insider user id). Full description: `tools/spike2_emu/modes/sdk/MODE_SDK.md`, "The score
  feed (PAD-1204)".

## Choices

- **Plain HTTP POST of JSON** to the owner's own address. The reporter wants "an external server"; a POST is what
  any small web server, Node-RED or Home Assistant webhook takes without code of ours. UDP would need a listener
  written for it; TLS has no library in the runtime.
- **An IP address, no names.** The runtime may not block or start threads (SDK rules 1-2, enforced by
  `build_mode.sh`), and a name lookup blocks. The send itself is a non-blocking state machine on the game's tick.
- **Insider user ids, not names.** The machine holds each logged-in player's 16-byte account id (PAD-1108 found the
  tables); the name shown on screen comes from Stern's servers. The id is the same every game, so the owner's server
  can map it to a name once.
- **One report per game, at its end**, not the high-score table: the owner's server keeps its own board from them.

## Proof

Emulator (rig kit `C:\tmp\PAD-1204\rig`), see MODE_SDK.md: Godzilla LE 1.16 (game_over port: post, server down
retried and dropped with the game playing on, post again; marker logins read back), Elvira 3 1.13 (a port with no
game_over). Tests: `tests/test_pad1204_score_feed.py`.

## The game's type (PAD-1344)

C0untDeM0net (Discord): "the scores for the mini games started from the game selection menu, like 'the shark is
broken' on jaws, are indistinguishable from standard games". Each report now carries `game_type` (`standard`,
`challenge`, `competition`, `tournament`, `head_to_head`, `team`, `cooperation`) and `challenge` (the challenge's
name), read by the runtime while the game runs from the flags the start menu's entries set and the port's Challenge
list (PAD-615/619: a challenge's flag, or the GamePlayModes index). `scorefeed.cfg` gains `type <flag> <name>` lines
off the card's flag names (`score_feed.type_lines`), so a port with no Challenge list still tells a challenge game
(unnamed). Jaws' menu also has Cooperation and Team Play, with flags of their own: they are types too, not standard.
Details: MODE_SDK.md "The score feed". Tests: `tests/test_pad1204_score_feed.py` (the JSON, the type rule, the type
lines). Emulator: Jaws Premium/LE 1.02 (kit `C:\tmp\PAD-1344\rig`).

## Play options tab (David's follow-ups)

- "users see the banner at the top and assume they lose IC access": the options that change no score (Handicap per
  player, Prolonged Competition, Score feed, Inactivity pauses timers) left the Modes tab for a **Play options** tab
  (Make group, after Defaults) that says Insider Connected keeps working; the Modes banner names that tab. Co-op play,
  which holds the reports back, stays on the Modes tab. The tab is a view over the Modes service's state and actions
  (`tabs/playopts.py` asks it to publish them), so the handicap Levels dialog and the options' tests are unchanged.
- "I'd like to see the sample API contract for the scores API": the Score feed card's **What your server receives**
  shows the request as sent to the typed address, the body laid out, every field with its type, and the answer the
  machine expects (`score_feed.contract()`; a test checks its keys against the runtime's `feed_json`).

## Every Spike 2 build (PAD-1389)

David: "I don't see it in the play options tab anymore for King Kong at least. we need to add it to all spike 2 games."
Every shipped port already carries what the feed needs (`score_feed.port_ok`: 76 of 78 profiles). The two that did
not were ports the app DERIVED for builds it ships none for: King Kong LE 1.00 (the newest, from Stern after 0.97)
and 0.93. King Kong LE 1.00's event bus has one more id (it ends at 208; every newest shipped reference's at 207):
from 0xb6 up every id moved by one, and the deriver dropped every numbered event of a reference whose bus differs,
`game_start` and `ball_start` with them. No `game_start`, no Score feed (and no Prolonged Competition, which starts on
the ball's start).

The fix is in the deriver, not the feed: `portgen` (REVISION 11) keeps a reference's events on a bus that differs, each
at the target's own id, read off the **event map** (`ports/recipes/eventbus-207.busmap.gz`, built by `port_tool.py
busmap <program>` from Godzilla LE 1.16): a ladder for each of the 141 handlers on that build's bus. The target's own
subscriptions say which id each located handler sits on; `fit_bus_offsets` fits the ids' moves (never going back:
ids are added or taken out, not shuffled) to those votes, so a stray ladder hit costs one vote, and an id is mapped
only where the agreeing ids below and above moved alike (KK 1.00: 0xad-0xb5, around the new id, are left out; tilt
0xc6 -> 0xc7, tilt_warning 0xc8 -> 0xc9). The end of ball's bus fallback (`via_bus`) reads its id the same way. The
derived port's key carries the map's SHA-1, so a new map re-derives.

Proof: emulator, the stock King Kong LE 1.00 card with the runtime, the re-derived port and `scorefeed.cfg`
(`C:\tmp\PAD-1389\feedjob.sh`, a stand-in server on 127.0.0.1): armed "bus 0x4d game, 0x25 ball", a game played
to its end (slingshots and an inlane hit, the saver waited out, three drains), "game 1 over (play stopped with no new
ball) - 1 player(s): 383880", posted (HTTP 200) and received. Tests: `tests/test_pad1389_event_map.py`.
