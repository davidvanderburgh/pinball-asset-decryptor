# pad_probe_mode.gd - a PAD mode written the way the game writes its own
# (modes/*.gd extend GameMode): sw_<switch name>_active / evt_<event>
# methods are found by GameMode._init and registered with the game's Events
# dispatcher when the mode manager adds the mode (PAD-1387 proof of concept).
extends GameMode

var padlog: Callable
var hits := 0

func _init(_name, _priority, _mode_type):
	super._init(_name, _priority, _mode_type)

func say(msg: String) -> void:
	if padlog.is_valid():
		padlog.call("pad_probe: " + msg)

func _ready():
	super._ready()
	say("started by the mode manager; running modes: %s" % _running())
	Delays.add(id, "pad_tick", 2.0, _tick)

func _tick():
	say("2 s timer (Delays) fired, ball %s, score %s" % [Game.ball, Game.current_player.data.score])

func mode_stopped():
	say("stopped by the mode manager")
	super.mode_stopped()

func evt_ball_started(_kwargs) -> bool:
	say("evt_ball_started (shoot again %s)" % _kwargs)
	return CONTINUE

# The spinner: warden.gd -> Events.call_event("sw_spinner_active", ...).
func sw_spinner_active(_sw) -> bool:
	hits += 1
	var before = Game.current_player.data.score
	var got = Game.score(12340)
	say("sw_spinner_active #%d: Game.score(12340) -> %s, score %s -> %s" % [hits, got, before, Game.current_player.data.score])
	led_blink(Leds.BUGS_ARROW, YELLOW, Warden.MEDIUM)
	return CONTINUE

func _running() -> String:
	var names := []
	for m in Modes.modes:
		names.append(m.mode_name)
	return ", ".join(names)
