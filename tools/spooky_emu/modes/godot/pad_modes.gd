# pad_modes.gd - PAD's custom mode runtime for Spooky's Godot title, Looney Tunes (Godot 4.1,
# project GDToons) (PAD-1419; the PAD-1387 probe made into the runtime).
#
# The update carries override.cfg beside main.x86_64, which adds this script as one more
# autoload, after the game's own (Logger ... Replay), so Game, Modes, Audio and Warden exist:
#
#   [autoload]
#   PadModes="*/game/code/uptest/pad/pad_modes.gd"
#
# It runs the custom modes in the folder beside it (pad/modes: title.cfg + *.mode, the JJP keys
# tools/jjp_emu/MODES.md describes; the ones this runtime takes are mkspkmodes.py's KEYS):
#
#   start / start_count   the game's switches that start it, and how many hits it takes
#   shots / points        the switches that score while it runs, and what each scores
#   seconds               how long it runs (0: until the ball ends)
#   complete / complete_points   shots that complete it, and the bonus for that
#   sound_start/_shot/_complete/_end   the game's own sounds (Audio.voice_lines: play_voice
#                                      queued; Audio.sfx: play_sfx)
#   title, panel, fonts, colors        a panel of ours over the game's screen, in its fonts
#
# Switches: Warden.sw_active (every switch the game sees, after its own events), only while a
# ball is in play (Game.gameplay_active, not tilted, not the switch test).  Points go through
# the game's own Game.score, which applies the playfield multiplier and rounds to 10, as it
# does for the game's own awards.  A mode ends on time, on completion, at the end of the ball,
# on tilt and when the game ends; start counts reset at every new game.  pad/modes/off turns
# them all off.  Mode timers stand still while the game pauses its own (Game.timers_paused).
#
# PADMODES_PORT=<file>: also write the title's port report there (switches, lights, sounds,
# the game's modes, fonts) and, at the first ball of a game, measure the points scale (one
# 1,000-point Game.score) into it.  Log: PAD_MODES_LOG (default /game/tmp/pad_modes.log).
extends Node

const VERSION := "1"
const PLACES := {"top": 0.04, "middle": 0.36, "bottom": 0.68}

var log_path := "/game/tmp/pad_modes.log"
var here := ""
var dir := ""
var all := []          # [{file, name, title, cfg, start, start_count, shots, points, ...}]
var ball_live := false
var shown = null
var panel: CanvasLayer = null
var box: Panel = null
var labels := {}
var fonts := {}
var port_path := ""
var measured := false
var voices := []       # [[key, ticks, starts needed]] our callouts the voice channel has not taken yet
var voice_starts := 0  # clips the voice channel has started (polled)
var voice_last := [null, 0.0]
# start rules (PAD-1424)
var valid_seen := false
var mb_since := 0.0
var mb_was := false
var last_running = null
var extra_seen := -1
var rules_at := 0.0
# the priority of our LED commands: above the game's shows and modes (5 .. ~400), below its system
# modes (9500+) and the service menu (9750)
const LED_PRI := 1000
const NOT_PLAYFIELD := ["trough", "shooter", "plunge", "launch", "flipper", "start", "coin", "door", "tilt",
	"slam", "outhole", "drain", "button", "service", "volume", "menu", "eject", "enter", "exit", "up", "down"]


func plog(msg: String) -> void:
	var line := "%s %s" % [Time.get_datetime_string_from_system(), msg]
	print("PADMODES: " + line)
	var f: FileAccess
	if FileAccess.file_exists(log_path):
		f = FileAccess.open(log_path, FileAccess.READ_WRITE)
		if f:
			f.seek_end()
	else:
		f = FileAccess.open(log_path, FileAccess.WRITE)
	if f:
		f.store_line(line)
		f.close()


func _ready() -> void:
	if OS.has_environment("PAD_MODES_LOG"):
		log_path = OS.get_environment("PAD_MODES_LOG")
	here = get_script().resource_path.get_base_dir()
	dir = here.path_join("modes")
	process_mode = Node.PROCESS_MODE_ALWAYS
	plog("loaded: PadModes runtime %s from %s, engine %s, game %s %s" % [VERSION,
		get_script().resource_path, Engine.get_version_info().string, Game.game_title, Game.version])
	_find_fonts()
	load_modes()
	if OS.has_environment("PADMODES_PORT"):
		port_path = OS.get_environment("PADMODES_PORT")
		write_port()
	Warden.sw_active.connect(_on_switch)
	Game.game_started.connect(_on_game_started)
	Game.ball_started.connect(_on_ball_started)
	Game.ball_ending.connect(func(): _stop_all("the ball ended"))
	Game.ball_ended.connect(func(): _stop_all("the ball ended"))
	Game.game_ended.connect(func(): _stop_all("the game ended"))
	Game.tilt_warning.connect(_on_tilt)
	# no ball-saved signal: a one-ball save plays the game's ball_save clip (trough.save_balls)
	Game.quick_clip.connect(_on_quick_clip)
	plog("PadModes joined the game: %d custom mode(s), %d game modes in Modes.all_modes" % [
		all.size(), Modes.all_modes.size()])


# ------------------------------------------------------------------ the mode files
func load_modes() -> void:
	all = []
	if not DirAccess.dir_exists_absolute(dir):
		plog("no mode folder %s: no custom modes" % dir)
		return
	if FileAccess.file_exists(dir.path_join("off")):
		plog("%s/off is there: custom modes are off" % dir)
		return
	var title := {}
	if FileAccess.file_exists(dir.path_join("title.cfg")):
		title = parse(FileAccess.get_file_as_string(dir.path_join("title.cfg")))
	var files := []
	for fn in DirAccess.get_files_at(dir):
		if fn.ends_with(".mode"):
			files.append(fn)
	files.sort()
	for fn in files:
		var cfg := title.duplicate()
		cfg.merge(parse(FileAccess.get_file_as_string(dir.path_join(fn))), true)
		var m := {
			"file": fn, "cfg": cfg,
			"name": cfg.get("name", fn.get_basename()),
			"start": switches(fn, "start", cfg.get("start", "")),
			"shots": switches(fn, "shots", cfg.get("shots", "")),
			"start_count": maxi(1, to_int(cfg.get("start_count", "1"))),
			"points": to_int(cfg.get("points", "1000000")),
			"seconds": to_int(cfg.get("seconds", "20")),
			"complete": to_int(cfg.get("complete", "0")),
			"complete_points": to_int(cfg.get("complete_points", "0")),
			"hits": 0, "running": false, "made": 0, "total": 0, "left": 0.0,
		}
		m["title"] = cfg.get("title", m["name"])
		_start_rules(fn, m, cfg)
		_lamps_coils_balls(fn, m, cfg)
		all.append(m)
		plog("mode %s \"%s\": start %s x%d, shots %s, %d points, %s, complete %d (+%d)" % [fn, m["name"],
			names(m["start"]), m["start_count"], names(m["shots"]), m["points"],
			("%d s" % m["seconds"]) if m["seconds"] > 0 else "until the ball ends",
			m["complete"], m["complete_points"]])
	plog("%d custom mode(s) from %s" % [all.size(), dir])


# PAD-1424: JJP's start rules (MODES.md "Start rules from the game's hook lists")
func _start_rules(fn: String, m: Dictionary, cfg: Dictionary) -> void:
	m["combo"] = switches(fn, "start_combo", cfg.get("start_combo", ""))
	m["combo_seconds"] = maxi(1, to_int(cfg.get("combo_seconds", "5")))
	m["start_score"] = to_int(cfg.get("start_score", "0"))
	m["start_on"] = _words(cfg.get("start_on", ""))
	m["start_after"] = _words(cfg.get("start_after", ""))
	m["once"] = cfg.get("start_once", "no")
	m["reset_ball"] = cfg.get("start_count_reset", "game") == "ball"
	m["combo_at"] = 0
	m["combo_time"] = 0.0
	m["ran_ball"] = false
	m["ran_game"] = false
	m["score_fired"] = {}
	if not m["combo"].is_empty() or not m["start_on"].is_empty() or not m["start_after"].is_empty() \
			or m["start_score"] > 0:
		plog("mode %s start rules: on %s; after %s; score %d; combo %s within %d s; once %s; count reset %s" % [
			fn, " ".join(m["start_on"]), " ".join(m["start_after"]), m["start_score"], names(m["combo"]),
			m["combo_seconds"], m["once"], "ball" if m["reset_ball"] else "game"])


# PAD-1424: the game's LEDs at a priority of ours, its coils, its balls (MODES.md "Balls and coils")
func _lamps_coils_balls(fn: String, m: Dictionary, cfg: Dictionary) -> void:
	m["lamps"] = []
	for w in _words(cfg.get("lamps", "")):
		var n := _const_of(Leds, w)
		if n < 0:
			plog("%s: lamp %s is not one of this game's LEDs (ignored)" % [fn, w])
		else:
			m["lamps"].append(n)
	var c := Color.html("#" + cfg.get("lamp_color", "ffffff").trim_prefix("#").substr(0, 6))
	m["lamp_rgb"] = [int(c.r * 255), int(c.g * 255), int(c.b * 255)]
	m["lamp_blink"] = clampi(to_int(cfg.get("lamp_blink", "4")), 0, 10)
	var mb := _words(cfg.get("multiball", ""))
	m["mb_balls"] = clampi(to_int(mb[0]), 0, 6) if mb.size() > 0 else 0
	m["mb_save"] = clampi(to_int(mb[1]), 0, 120) if mb.size() > 1 else 10
	m["mb_on"] = switches(fn, "multiball_on", cfg.get("multiball_on", ""))
	var ab := _words(cfg.get("add_ball", ""))
	m["add_times"] = 1
	if ab.size() > 1 and ab[-1].is_valid_int():
		m["add_times"] = clampi(int(ab[-1]), 1, 6)
		ab.remove_at(ab.size() - 1)
	m["add_ball"] = switches(fn, "add_ball", " ".join(ab))
	m["ball_save"] = clampi(to_int(cfg.get("ball_save", "0")), 0, 120)
	for k in ["coil_start", "coil_shot", "coil_complete"]:
		var w := _words(cfg.get(k, ""))
		m[k] = [_const_of(Coils, w[0]), to_int(w[1]) if w.size() > 1 else 0, w[0]] if w.size() > 0 else null
	var h := _words(cfg.get("coil_hold", ""))
	m["coil_hold"] = [_const_of(Coils, h[0]), clampi(to_int(h[1]), 100, 5000) if h.size() > 1 else 1000,
		clampi(to_int(h[2]), 1, 16) if h.size() > 2 else 8, h[0]] if h.size() > 0 else null
	var on: String = cfg.get("coil_hold_on", "shots")
	m["hold_on"] = on if on in ["shots", "start"] else "switches"
	m["hold_sw"] = switches(fn, "coil_hold_on", on) if m["hold_on"] == "switches" else []
	m["holds_ok"] = cfg.get("coil_holds", "off") == "on"
	m["mb_served"] = false
	m["mb_at"] = 0.0
	m["one_since"] = 0.0
	m["added"] = 0
	m["held_until"] = 0.0
	m["lamp_phase"] = -1
	m["lamp_at"] = 0.0
	m["started_at"] = 0.0


# a constant of an autoload by its name as a mode file writes it (Leds.ORBIT_INNER4, Coils.SHAKER)
static func _const_of(node: Object, w: String) -> int:
	var want := w.to_upper()
	var consts: Dictionary = node.get_script().get_script_constant_map()
	if consts.has(want) and typeof(consts[want]) == TYPE_INT:
		return consts[want]
	return -1


static func _words(v: String) -> Array:
	var out := []
	for w in v.replace(",", " ").split(" ", false):
		out.append(w.to_lower())
	return out


static func parse(text: String) -> Dictionary:
	var d := {}
	for raw in text.split("\n"):
		var s := raw.strip_edges()
		if s == "" or s[0] == "#" or s[0] == ";" or s.find("=") < 0:
			continue
		var k := s.substr(0, s.find("=")).strip_edges()
		var v := s.substr(s.find("=") + 1).strip_edges()
		if v.find(" #") >= 0:
			v = v.substr(0, v.find(" #")).strip_edges()
		d[k] = v
	return d


static func to_int(s: String) -> int:
	s = s.replace(",", "").replace("_", "").strip_edges()
	return int(s) if s.is_valid_int() else 0


func switches(fn: String, key: String, v: String) -> Array:
	var out := []
	for w in v.replace(",", " ").split(" ", false):
		var n := find_switch(w)
		if n < 0:
			plog("%s: %s %s is not one of this game's switches (ignored)" % [fn, key, w])
		elif n not in out:
			out.append(n)
	return out


func find_switch(w: String) -> int:
	if w.is_valid_int() and Switches.items.has(int(w)):
		return int(w)
	for n in Switches.items:
		if Switches.items[n].name == w:
			return n
	return -1


func names(l: Array) -> String:
	if l.is_empty():
		return "-"
	var out := []
	for n in l:
		out.append(Switches.items[n].name)
	return " ".join(out)


# ------------------------------------------------------------------ the game's signals
func _on_game_started() -> void:
	ball_live = false
	for m in all:
		_stop(m, "")
		m["hits"] = 0
		m["combo_at"] = 0
		m["ran_game"] = false
		m["score_fired"] = {}
	plog("game_started: start counts reset")


func _on_ball_started(shoot_again) -> void:
	ball_live = true
	plog("ball_started (ball %s of %s, player %d, shoot again %s)" % [Game.ball, Game.balls_per_game,
		Game.current_player_index + 1, shoot_again])
	valid_seen = false
	mb_since = 0.0
	mb_was = false
	last_running = null
	extra_seen = -1
	for m in all:
		m["ran_ball"] = false
		m["combo_at"] = 0
		if m["reset_ball"]:
			m["hits"] = 0
	_event("ball_start")
	if Game.ball == 1 and not shoot_again:
		_event("first_ball")
	if Game.ball >= Game.balls_per_game and _extra_left() <= 0:
		_event("last_ball")
	if port_path != "" and not measured:
		measured = true
		var before = _score()
		var got = Game.score(1000)
		plog("points scale: Game.score(1000) scored %s (score %s -> %s, multiplier %s)" % [
			got, before, _score(), Game.multiplier])
		write_port(got)


func _on_tilt(tilted, _times) -> void:
	if tilted:
		_stop_all("tilt")


func _stop_all(why: String) -> void:
	ball_live = false
	for m in all:
		_stop(m, why)


func playing() -> bool:
	return ball_live and Game.gameplay_active and not Game.tilted and Game.current_player != null \
		and not Warden.sw_test_active


func _on_switch(sw) -> void:
	if all.is_empty() or not playing():
		return
	var now := Time.get_ticks_msec() / 1000.0
	if not valid_seen and _is_playfield(Switches.items[sw].name):
		valid_seen = true
		_event("valid_playfield")
	for m in all:
		if m["running"]:
			_running_switch(m, sw)
			if m["running"] and sw in m["shots"]:
				_shot(m, sw)
			continue
		_combo(m, sw, now)
		if not m["running"] and sw in m["start"]:
			_fire(m, "start switch %s hit" % Switches.items[sw].name)


# ------------------------------------------------------------------ start rules (PAD-1424)
# A start rule fired for m: one more toward its start_count.
func _fire(m: Dictionary, why: String) -> void:
	if m["running"] or not playing():
		return
	if (m["once"] == "ball" and m["ran_ball"]) or (m["once"] == "game" and m["ran_game"]):
		return
	m["hits"] += 1
	plog("%s: %s (%d of %d)" % [m["name"], why, m["hits"], m["start_count"]])
	if m["hits"] >= m["start_count"]:
		_start(m)


# start_on: ball_start, first_ball, last_ball, valid_playfield, ball_saved, extra_ball, multiball_end
func _event(ev: String) -> void:
	plog("game event %s" % ev)
	for m in all:
		if ev in m["start_on"]:
			_fire(m, "start_on %s" % ev)


func _on_quick_clip(c, _how = null) -> void:
	if typeof(c) == TYPE_DICTIONARY and str(c.get("clip", "")).ends_with("/ball_save.ogv"):
		_event("ball_saved")


# The trough, the shooter lane, the buttons and the coin door are not the playfield.
static func _is_playfield(n: String) -> bool:
	var words := n.to_lower().replace(" ", "_").replace("-", "_").split("_", false)
	for w in words:
		for x in NOT_PLAYFIELD:
			if w == x or (x.length() > 3 and w.begins_with(x)):
				return false
	return not words.is_empty()


func _combo(m: Dictionary, sw, now: float) -> void:
	var c: Array = m["combo"]
	if c.size() < 2 or m["running"]:
		return
	if m["combo_at"] > 0 and now - m["combo_time"] > m["combo_seconds"]:
		m["combo_at"] = 0
	if c[m["combo_at"]] == sw:
		m["combo_at"] += 1
		m["combo_time"] = now
	elif c[0] == sw:
		m["combo_at"] = 1
		m["combo_time"] = now
	if m["combo_at"] >= c.size():
		m["combo_at"] = 0
		_fire(m, "start_combo made")


func _extra_left() -> int:
	var p = Game.current_player
	return int(p.data.get("extra_balls_pending", 0)) if p != null else 0


# extra balls earned (only ever goes up in a game), -1 with no player
func _extra_earned() -> int:
	var p = Game.current_player
	return int(p.data.get("extra_balls_earned", 0)) if p != null else -1


func _balls_in_play() -> int:
	var t = Modes.access("trough")
	return int(t.num_balls_in_play) if t != null else -1


# the game's modes running now, by their name in Modes.all_modes (the port report's game_modes)
func _running_modes() -> Array:
	var out := []
	for md in Modes.modes:
		if md == null:
			continue
		for k in Modes.all_modes:
			if Modes.all_modes[k] == md:
				out.append(str(k).to_lower())
				break
	return out


# Ten times a second in a ball: the score, extra balls, the balls in play (a multiball's end)
# and the game's running modes (start_after).
func _rules() -> void:
	var now := Time.get_ticks_msec() / 1000.0
	if not playing() or now - rules_at < 0.1:
		return
	rules_at = now
	var player: int = Game.current_player_index
	var score := _score()
	for m in all:
		if m["start_score"] > 0 and score >= m["start_score"] and not m["score_fired"].has(player):
			m["score_fired"][player] = true
			_fire(m, "start_score %d reached (%d)" % [m["start_score"], score])
	var extra := _extra_earned()
	if extra >= 0:
		if extra_seen >= 0 and extra > extra_seen:
			_event("extra_ball")
		extra_seen = extra
	var in_play := _balls_in_play()
	if in_play > 1:
		if mb_since == 0.0:
			mb_since = now
		if now - mb_since >= 0.5:
			mb_was = true
	else:
		mb_since = 0.0
		if mb_was and in_play >= 0:
			mb_was = false
			_event("multiball_end")
	var want := false
	for m in all:
		if not m["start_after"].is_empty():
			want = true
	if not want:
		return
	var running := _running_modes()
	if last_running != null:
		for ended in last_running:
			if ended in running:
				continue
			for m in all:
				if ended in m["start_after"] or "any" in m["start_after"]:
					_fire(m, "start_after %s ended" % ended)
	last_running = running


# ------------------------------------------------------------------ lamps, coils, balls (PAD-1424)
func _running_switch(m: Dictionary, sw) -> void:
	if sw in m["mb_on"] and not m["mb_served"]:
		_multiball(m)
	if sw in m["add_ball"] and m["added"] < m["add_times"]:
		m["added"] += 1
		plog("%s: add a ball on %s (%d of %d): %s" % [m["name"], Switches.items[sw].name, m["added"], m["add_times"],
			_add_balls(1)])
		_save(m, maxi(2, m["mb_save"] if m["mb_balls"] > 0 else 2))
	if m["hold_on"] == "switches" and sw in m["hold_sw"]:
		_hold(m)


func _trough():
	return Modes.access("trough")


func _add_balls(n: int) -> String:
	var t = _trough()
	if t == null:
		return "no trough"
	return "trough.add_balls(%d) added %s" % [n, t.add_balls(n, true)]


func _save(m: Dictionary, secs: int) -> void:
	var t = _trough()
	if t == null:
		return
	t.start_ball_save(secs, true)
	plog("%s: ball save %d s (trough.start_ball_save; active %s)" % [m["name"], secs, t.ball_save_active])


func _multiball(m: Dictionary) -> void:
	var have := maxi(1, _balls_in_play())
	m["mb_served"] = true
	m["mb_at"] = Time.get_ticks_msec() / 1000.0
	m["one_since"] = 0.0
	plog("%s: multiball, %d balls in play wanted, %d now%s" % [m["name"], m["mb_balls"], have,
		(": " + _add_balls(m["mb_balls"] - have)) if m["mb_balls"] > have else ""])
	if m["mb_save"] > 0:
		_save(m, m["mb_save"])


func _coil(m: Dictionary, key: String) -> void:
	var c = m[key]
	if c == null:
		return
	if c[0] < 0:
		plog("%s: %s %s is not one of this game's coils" % [m["name"], key, c[2]])
		return
	var own: int = int(Coils.items[c[0]].pulse_ms) if Coils.items.size() > c[0] else 0
	if c[1] > 0 and (own <= 0 or c[1] < own):
		Coils.pulse_ms(c[0], c[1])
	else:
		Coils.pulse(c[0])
	plog("%s: %s pulsed %s (%s ms, its own %d)" % [m["name"], key, c[2], c[1] if c[1] > 0 and c[1] < own else "its own", own])


func _hold(m: Dictionary) -> void:
	var h = m["coil_hold"]
	if h == null:
		return
	if not m["holds_ok"]:
		plog("%s: coil_hold %s refused: title.cfg has no coil_holds = on" % [m["name"], h[3]])
		return
	if h[0] < 0:
		plog("%s: coil_hold %s is not one of this game's coils" % [m["name"], h[3]])
		return
	Coils.dangerous_hold(h[0], int(h[2] * 100 / 32))
	m["held_until"] = Time.get_ticks_msec() / 1000.0 + h[1] / 1000.0
	plog("%s: holding %s for %d ms at %d of 32 (Coils.dangerous_hold %d%%, released by us)" % [m["name"], h[3], h[1], h[2],
		int(h[2] * 100 / 32)])


func _unhold(m: Dictionary) -> void:
	if m["held_until"] <= 0.0:
		return
	m["held_until"] = 0.0
	Coils.release_hold(m["coil_hold"][0])
	plog("%s: let go of %s" % [m["name"], m["coil_hold"][3]])


# Our colour on the mode's LEDs at LED_PRI, blinking lamp_blink times a second; set again four
# times a second (the game clears every command of its own at each ball start and tilt).
func _lamps_tick(m: Dictionary, now: float) -> void:
	if m["lamps"].is_empty():
		return
	var phase := int((now - m["started_at"]) * m["lamp_blink"] * 2.0) % 2 if m["lamp_blink"] > 0 else 0
	if phase == m["lamp_phase"] and now - m["lamp_at"] < 0.25:
		return
	var first: bool = m["lamp_phase"] < 0
	m["lamp_phase"] = phase
	m["lamp_at"] = now
	var rgb: Array = m["lamp_rgb"] if phase == 0 else [0, 0, 0]
	# blend false: the game's controller blends a command with the ones under it by default, and
	# black then shows them (the ball-save lamp stayed lit through our flashes)
	for n in m["lamps"]:
		Leds.enable(n, LED_PRI, Warden.OPCODE_SET_LED, rgb, 0, false)
	if first:
		plog("%s: lamps %s lit %s at priority %d%s" % [m["name"], m["lamps"], m["lamp_rgb"], LED_PRI,
			(", %d flashes a second" % m["lamp_blink"]) if m["lamp_blink"] > 0 else ""])


func _lamps_off(m: Dictionary) -> void:
	for n in m["lamps"]:
		Leds.disable(n, LED_PRI, true)
	if not m["lamps"].is_empty():
		plog("%s: lamps handed back to the game" % m["name"])


# A multiball of ours ends the mode once one ball is left for 2 s, after its ball save and 3 s more.
func _balls_tick(m: Dictionary, now: float) -> void:
	if not m["mb_served"] or now - m["mb_at"] < m["mb_save"] + 3:
		return
	if _balls_in_play() <= 1:
		if m["one_since"] == 0.0:
			m["one_since"] = now
		elif now - m["one_since"] >= 2.0:
			_stop(m, "one ball left")
	else:
		m["one_since"] = 0.0


func _start(m: Dictionary) -> void:
	m["hits"] = 0
	m["combo_at"] = 0
	m["ran_ball"] = true
	m["ran_game"] = true
	m["running"] = true
	m["made"] = 0
	m["total"] = 0
	m["left"] = float(m["seconds"])
	plog("%s: STARTED (%s)" % [m["name"], ("%d s" % m["seconds"]) if m["seconds"] > 0 else "until the ball ends"])
	_sound(m, "sound_start")
	m["started_at"] = Time.get_ticks_msec() / 1000.0
	m["mb_served"] = false
	m["one_since"] = 0.0
	m["added"] = 0
	m["lamp_phase"] = -1
	_coil(m, "coil_start")
	if m["hold_on"] == "start":
		_hold(m)
	if m["ball_save"] > 0:
		_save(m, m["ball_save"])
	if m["mb_balls"] > 0 and m["mb_on"].is_empty():
		_multiball(m)
	shown = m
	draw()


func _shot(m: Dictionary, sw) -> void:
	var got := _award(m["points"])
	m["made"] += 1
	m["total"] += got
	plog("%s: shot %d%s on %s: %d points (player score %s)" % [m["name"], m["made"],
		(" of %d" % m["complete"]) if m["complete"] > 0 else "", Switches.items[sw].name, got, _score()])
	_sound(m, "sound_shot")
	_coil(m, "coil_shot")
	if m["hold_on"] == "shots":
		_hold(m)
	shown = m
	if m["complete"] > 0 and m["made"] >= m["complete"]:
		var bonus := _award(m["complete_points"]) if m["complete_points"] > 0 else 0
		m["total"] += bonus
		plog("%s: COMPLETED, bonus %d, mode total %d" % [m["name"], bonus, m["total"]])
		_sound(m, "sound_complete")
		_coil(m, "coil_complete")
		_stop(m, "")
		return
	draw()


func _stop(m: Dictionary, why: String) -> void:
	if not m["running"]:
		return
	m["running"] = false
	if why != "":
		plog("%s: ended (%s), %d shot(s), total %d" % [m["name"], why, m["made"], m["total"]])
		_sound(m, "sound_end")
	_lamps_off(m)
	_unhold(m)
	if m["ball_save"] > 0 and m["mb_balls"] == 0 and _trough() != null and _trough().ball_save_active \
			and _trough().ball_save_timer <= m["ball_save"] + 2:
		_trough().disable_ball_save()
	if shown == m:
		shown = null
		for x in all:
			if x["running"]:
				shown = x
				break
	draw()


func _watch_voices() -> void:
	# our callouts as the game's voice channel takes them (Audio plays a queued one when the
	# one before it finishes; the game may also drop its queue)
	_voice_poll()
	while not voices.is_empty():
		var v = voices[0]
		var vp = Audio.voice_player
		# one queued behind another clip counts once the channel has started a clip since
		if Audio.active_voice_key == v[0] and vp != null and vp.playing and vp.stream != null \
				and voice_starts >= v[2]:
			plog("callout %s played on the game's voice channel (%s)" % [v[0], vp.stream.resource_path])
		elif Time.get_ticks_msec() - v[1] > 30000:
			plog("callout %s never played: the game dropped its voice queue" % v[0])
		else:
			return
		voices.pop_front()


func _voice_poll() -> void:
	# counts the clips the voice channel starts: a new stream, or the same one from its start again
	var vp = Audio.voice_player
	if vp == null or not vp.playing:
		voice_last = [null, 0.0]
		return
	var pos: float = vp.get_playback_position()
	if vp.stream != voice_last[0] or pos < voice_last[1]:
		voice_starts += 1
	voice_last = [vp.stream, pos]


func _process(delta: float) -> void:
	if not voices.is_empty():
		_watch_voices()
	if not all.is_empty():
		_rules()
	if all.is_empty() or Game.timers_paused:
		return
	var now := Time.get_ticks_msec() / 1000.0
	for m in all:
		if not m["running"]:
			continue
		if m["seconds"] > 0 and not (m["mb_served"] and not m["mb_on"].is_empty()):
			m["left"] -= delta
			if m["left"] <= 0.0:
				_stop(m, "time ran out")
				continue
		_balls_tick(m, now)
		if m["running"]:
			_lamps_tick(m, now)
			if m["held_until"] > 0.0 and now >= m["held_until"]:
				_unhold(m)
	if shown != null and shown["running"] and box != null:
		_timer(shown)


# ------------------------------------------------------------------ the game's scoring
func _score() -> int:
	return Game.current_player.data.score if Game.current_player != null else 0


func _award(points: int) -> int:
	var before := _score()
	Game.score(points)
	return _score() - before


# ------------------------------------------------------------------ the game's sounds
func _sound(m: Dictionary, key: String) -> void:
	var name: String = m["cfg"].get(key, "")
	if name == "":
		return
	if Audio.voice_lines.has(name):
		_voice_poll()
		var busy = Audio.active_voice_key if Audio.voice_player != null and Audio.voice_player.playing else null
		Audio.play_voice(name, GameMode.PLAY_QUEUED)
		plog("%s: %s %s (%s) to the game's voice channel%s" % [m["name"], key, name, Audio.voice_lines[name],
			"" if busy == null else ", queued behind %s" % busy])
		voices.append([name, Time.get_ticks_msec(), voice_starts + 1 if busy != null else 0])
		_watch_voices()
	elif Audio.sfx.has(name):
		Audio.play_sfx(name)
		plog("%s: %s %s queued as a sound effect (Audio.play_sfx)" % [m["name"], key, name])
	else:
		plog("%s: %s %s: no such sound in this game" % [m["name"], key, name])


# ------------------------------------------------------------------ the panel
func _find_fonts() -> void:
	var d := "res://assets/fonts"
	for fn in DirAccess.get_files_at(d):
		var f := fn.trim_suffix(".import").trim_suffix(".remap")
		if f.ends_with(".ttf") or f.ends_with(".otf"):
			fonts[f.get_basename()] = d.path_join(f)


func font(name: String) -> Font:
	if name == "" or not fonts.has(name):
		return null
	var f = load(fonts[name])
	return f if f is Font else null


static func colour(hex: String) -> Color:
	hex = hex.trim_prefix("#")
	if not hex.is_valid_hex_number() or (hex.length() != 6 and hex.length() != 8):
		return Color.WHITE
	return Color.html(hex)


func _make_panel() -> void:
	panel = CanvasLayer.new()
	panel.name = "PadModesPanel"
	panel.layer = 128
	get_tree().root.add_child.call_deferred(panel)
	box = Panel.new()
	box.name = "box"
	panel.add_child(box)
	for k in ["title", "value", "timer"]:
		var l := Label.new()
		l.name = k
		l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		l.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		l.clip_text = true
		box.add_child(l)
		labels[k] = l


func draw() -> void:
	if shown == null or not shown["running"] or shown["cfg"].get("panel", "middle") == "none":
		if panel != null:
			panel.visible = false
		return
	if panel == null:
		_make_panel()
	panel.visible = true
	var cfg: Dictionary = shown["cfg"]
	var view := get_viewport().get_visible_rect().size
	var w := view.x * 0.56
	var h := view.y * 0.27
	box.position = Vector2(view.x * 0.22, view.y * PLACES.get(cfg.get("panel", "middle"), 0.36))
	box.size = Vector2(w, h)
	var sb := StyleBoxFlat.new()
	sb.bg_color = colour(cfg.get("panel_color", "000000b0"))
	sb.set_corner_radius_all(int(h * 0.06))
	box.add_theme_stylebox_override("panel", sb)
	# the rows: title (top 45%), the mode's total (36%), its time left (24%)
	_style(labels["title"], cfg.get("font_title", ""), cfg.get("title_color", "ffffff"), w, h, 0.0, 0.45)
	_style(labels["value"], cfg.get("font_value", ""), cfg.get("value_color", "ffdc00"), w, h, 0.42, 0.36)
	_style(labels["timer"], cfg.get("font_timer", ""), cfg.get("timer_color", "ffffff"), w, h, 0.76, 0.24)
	labels["title"].text = shown["title"]
	labels["value"].text = commas(shown["total"])
	_fit(labels["title"])
	_fit(labels["value"])
	labels["timer"].set_meta("secs", -2)
	_timer(shown)


func _style(l: Label, fname: String, rgba: String, w: float, h: float, y0: float, frac: float) -> void:
	l.position = Vector2(w * 0.04, h * y0)
	l.size = Vector2(w * 0.92, h * frac)
	var f := font(fname)
	if f != null:
		l.add_theme_font_override("font", f)
	l.add_theme_color_override("font_color", colour(rgba))
	l.set_meta("max", int(h * frac * 0.78))
	l.add_theme_font_size_override("font_size", int(h * frac * 0.78))


func _fit(l: Label) -> void:
	# shrink the text to the row's width (Label has no auto-size in Godot 4.1)
	var f: Font = l.get_theme_font("font")
	var size: int = l.get_meta("max")
	while size > 10 and f.get_string_size(l.text, HORIZONTAL_ALIGNMENT_LEFT, -1, size).x > l.size.x:
		size -= 2
	l.add_theme_font_size_override("font_size", size)


func _timer(m: Dictionary) -> void:
	var l: Label = labels["timer"]
	var secs := int(ceil(maxf(0.0, m["left"]))) if m["seconds"] > 0 else -1
	if l.get_meta("secs", -2) == secs:
		return
	l.set_meta("secs", secs)
	l.text = "" if secs < 0 else str(secs)


static func commas(n: int) -> String:
	var s := str(absi(n))
	var out := ""
	while s.length() > 3:
		out = "," + s.substr(s.length() - 3) + out
		s = s.substr(0, s.length() - 3)
	return ("-" if n < 0 else "") + s + out


# ------------------------------------------------------------------ the port report
func write_port(scored = null) -> void:
	var sw := []
	var ids := {}
	var labs := {}
	var keys := Switches.items.keys()
	keys.sort()
	for n in keys:
		var it = Switches.items[n]
		sw.append(it.name)
		ids[it.name] = n
		labs[it.name] = it.get("display_name", it.name)
	var lamps := []
	var consts: Dictionary = Leds.get_script().get_script_constant_map()
	for k in consts:
		if typeof(consts[k]) == TYPE_INT:
			lamps.append(k)
	var voice := Audio.voice_lines.keys()
	voice.sort()
	var effects := []
	for k in Audio.sfx.keys():
		if not Audio.voice_lines.has(k):
			effects.append(k)
	effects.sort()
	var paths := {}
	for k in voice:
		paths[k] = str(Audio.voice_lines[k]).trim_prefix("res://")
	for k in effects:
		var s = Audio.sfx[k]
		paths[k] = s.resource_path.trim_prefix("res://") if s is Resource else str(s)
	var gm := []
	var gm_types := {}
	for k in Modes.all_modes:
		gm.append(k)
		gm_types[k] = [int(Modes.all_modes[k].mode_type), int(Modes.all_modes[k].priority)]
	var fl := fonts.keys()
	fl.sort()
	var p := {
		"engine": "godot", "runtime": VERSION,
		"godot": Engine.get_version_info().string, "game_title": Game.game_title, "game_version": Game.version,
		"switches": sw, "switch_ids": ids, "switch_labels": labs,
		"lamps": lamps, "sounds": voice + effects, "voice_lines": voice.size(), "sound_paths": paths,
		"game_modes": gm, "game_mode_types": gm_types, "fonts": fl,
	}
	if scored != null:
		p["points_scale_measured"] = {"asked": 1000, "scored": scored, "multiplier": Game.multiplier}
	var f := FileAccess.open(port_path, FileAccess.WRITE)
	if f == null:
		plog("port report: cannot write %s" % port_path)
		return
	f.store_string(JSON.stringify(p, " ", false))
	f.close()
	plog("port report written to %s: %d switches, %d lamps, %d sounds (%d voice), %d game modes, %d fonts" % [
		port_path, sw.size(), lamps.size(), voice.size() + effects.size(), voice.size(), gm.size(), fl.size()])
