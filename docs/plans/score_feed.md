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

## Play options tab (David's follow-ups)

- "users see the banner at the top and assume they lose IC access": the options that change no score (Handicap per
  player, Prolonged Competition, Score feed, Inactivity pauses timers) left the Modes tab for a **Play options** tab
  (Make group, after Defaults) that says Insider Connected keeps working; the Modes banner names that tab. Co-op play,
  which holds the reports back, stays on the Modes tab. The tab is a view over the Modes service's state and actions
  (`tabs/playopts.py` asks it to publish them), so the handicap Levels dialog and the options' tests are unchanged.
- "I'd like to see the sample API contract for the scores API": the Score feed card's **What your server receives**
  shows the request as sent to the typed address, the body laid out, every field with its type, and the answer the
  machine expects (`score_feed.contract()`; a test checks its keys against the runtime's `feed_json`).
