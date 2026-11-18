# pad_modes.gd - PAD's runtime for Looney Tunes (Godot 4.1, project GDToons),
# loaded beside the game as one more autoload through override.cfg next to
# main.x86_64 (PAD-1387 proof of concept):
#
#   [autoload]
#   PadModes="*/game/code/uptest/pad/pad_modes.gd"
#
# Autoloads from override.cfg come after the game's own (Logger ... Replay),
# so Modes, Game, Events and Warden exist when this runs.  It logs to
# /game/tmp/pad_modes.log (PAD_MODES_LOG overrides) and puts its modes into
# the game's own mode table (Modes.all_modes) so the game's mode manager
# starts and stops them like its own (a BALL mode: added at ball start,
# removed at ball end).
extends Node

var log_path := "/game/tmp/pad_modes.log"
var here := ""

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
	plog("loaded: %s, engine %s, game %s %s, exe %s" % [get_script().resource_path,
		Engine.get_version_info().string, Game.game_title, Game.version,
		OS.get_executable_path()])
	var autoloads := []
	for n in get_tree().root.get_children():
		autoloads.append(n.name)
	plog("root children: %s" % ", ".join(autoloads))
	plog("game modes (%d): %s" % [Modes.all_modes.size(), ", ".join(Modes.all_modes.keys())])
	# Our mode, in the game's own table: the mode manager adds every BALL
	# mode at ball start (game.gd _ball_starting -> Modes.add_by_type).
	var mode_script = load(here.path_join("pad_probe_mode.gd"))
	if mode_script == null:
		plog("could not load pad_probe_mode.gd")
	else:
		var m = mode_script.new("pad_probe", 116, GameMode.BALL)
		m.padlog = Callable(self, "plog")
		Modes.all_modes["pad_probe"] = m
		plog("pad_probe added to Modes.all_modes (BALL, priority 116)")
	# Every switch the game sees (warden.gd emits these after its own events).
	Warden.sw_active.connect(_on_sw_active)
	Game.ball_started.connect(func(_again): plog("ball_started: running modes %s" % running()))
	Game.game_started.connect(func(): plog("game_started"))
	Game.ball_ended.connect(func(): plog("ball_ended"))

func running() -> String:
	var names := []
	for m in Modes.modes:
		names.append("%s(%s)" % [m.mode_name, m.priority])
	return ", ".join(names)

func _on_sw_active(sw) -> void:
	plog("switch %s %s active (gameplay_active=%s)" % [sw, Switches.items[sw].name, Game.gameplay_active])
