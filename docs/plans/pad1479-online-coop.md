# PAD-1479: online co-op (machines in different places, one shared goal)

Captain Gordon (Discord @cokpendejo): "A peer to peer mode for spike 2 co op mode, where asynchronous gameplay
effects a shared target like a high score." Then: separate machines over the internet; teams like Splatoon /
Helldivers (Team Godzilla vs Team King Ghidorah taking over cities as they reach score targets); Godzilla first;
several PAD-built cards pinging one server that draws an image in Discord. Then Pokemon: an island that fills up as
people "rescue" Pokemon from Team Rocket, each catch sending a count to the server.

David (2026-11-21): "Yes let's build it and we need to give flexibility to the users to design their own online coop
modes (like we do on the modes tab). We should build a bare minimum baseline of online coop that works across all
titles that is vanilla."

## Design

Built on the PAD-1204 score feed (score_feed.py, pad_mode_runtime.c "the score feed"): it already posts every game's
final scores as JSON over plain HTTP to an IPv4 address on every Spike 2 port (game_over, or 30 s quiet) and on
Spike 3. No second network path.

1. **Runtime (pad_mode_runtime.c, feed):** scorefeed.cfg grows
   `online <campaign>`, `team <name>`, `machine <name>`, `key <join key>`; the JSON grows
   `"online":{"campaign","team","machine","key"}` and `"counts":{"<name>":n,...}` (only when online is set /
   counts were added). `pm_online_add(name, n)` (pad_mode.h) adds to this game's count table (ONLINE_COUNTS
   names); cleared at each new game, snapshotted into the report. Rebuild prebuilt mode.so + mode64.so.
2. **Mode file (mode_file.c):** `online start|shot|won|end <count> <n> [mask]` - like `shake`. won = end shot made,
   or the clock ran out on a mode with no end shot (roster_ended's rule).
3. **Blocks (block_modes.py):** op `online_add` {count, amount} -> `pm_online_add(...)`.
4. **Python (plugins/stern/online_coop.py):** sidecar `online_coop` = {on, campaign, team, machine, key, url,
   design: {teams:[{name,colour}], goal:"score"|"<count>", regions:[{name,target}], title}}; validation;
   cfg lines appended to scorefeed.cfg (the feed's url is the server); the campaign file the server reads
   (export). Online co-op on with the feed off turns the feed on to the server's address.
   ModeSpec.online rows -> mode-file `online` lines (validate_online, online_lines).
5. **Server (pinball_decryptor/online_coop_server.py, stdlib + Pillow):** `python -m
   pinball_decryptor.online_coop_server --campaign campaign.json --port 8090 [--webhook URL] [--state state.json]`.
   POST / takes the feed's JSON; checks campaign + key; adds the game's points to the team (goal "score": the
   team score of a co-op game = scores[0], else the sum; goal "<count>": counts[<count>]); a region is taken by the
   team that first reaches its target (regions in order, each team's running total since the last capture...
   simple rule: regions taken in order, region i goes to the first team whose total passes sum(targets[:i+1]));
   GET / status page, GET /map.png the map, GET /state.json. On each capture (and every N games) posts the map to
   the Discord webhook (multipart, urllib).
   Vanilla campaign (no design): one team "Everyone", goal score, regions "Goal 1..5" at 10M, 25M, 50M, 100M, 250M -
   the shared high score target of the first ask.
6. **UI:** Network tab: an Online co-op box beside Score feed (on, server address, campaign, team, machine, key,
   Design... dialog for teams/goal/regions, Save campaign file). Modes tab form: an "Online" row group like the
   shaker's (when, count, amount, shot). Blocks: "Add to online count" block.
7. **Proof:** emulator Godzilla LE 1.16 rig with a local server on the host's IP: a game played, the POST carries
   online + counts, the server takes it, the map is drawn. Screens: Network tab, Modes form, the map.

## Status

- [x] 1 runtime  - [x] 2 mode file  - [x] 3 blocks  - [x] 4 python (UI next)  - [x] 5 server  - [x] 6 UI  - [x] 7 proof

## Proof (2026-11-21)

Emulator, Ubuntu's rig (PAD-Runtime would not start: HCS_E_CONNECTION_TIMEOUT), stock Godzilla LE 1.16 card, rig kit
`C:	mp\PAD-1479ig` (go.sh as root in Ubuntu; slot 2 parked for its stale ballfeed.off). scorefeed.cfg made by the
app's own code (online_coop.save + mode_write.feed_into) for the server at the distro's own IP; the online co-op
server ran beside it. A plain game, ONLINETEST forced: `online start kaiju_fights 1`, `online shot cities_saved 2`,
`online won wins 1` and `online end modes_played 1` all fired; drained to game over; the report posted HTTP 200 and
the server logged "counted 3,769,950 for Team Godzilla; counts cities_saved 40, kaiju_fights 1, modes_played 1,
wins 1" and "Team Godzilla took Tokyo". Runs pass 1/1 in 4m7s twice.
