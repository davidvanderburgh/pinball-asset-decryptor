"""PAD-611: draw one blocks mode in each of the visual alternatives to the blocks, as pages styled like the app.

    python tools/mode_views/render_views.py <out dir> [<blocks.json>]

Writes <out dir>/<view>.html for every view (and <view>.png when Playwright and Edge are there: the mockups David
reviews). With no blocks.json it draws showcase.program(), RAMP FRENZY on Godzilla Pro's shots. Every view is made
FROM the program - nothing is drawn by hand - so what a view shows is what that view would show for a real mode.
The views (docs/plans/pad611_mode_making_alternatives.md):

  story      the mode's life as a state diagram: waiting -> running -> over, its rules in the state they work in
  playfield  the rules pinned to the shots on a playfield, lit shots in their colours
  timeline   the clock as a track, what happens at each moment; the shots' reactions beside it
  table      a grid: every shot, what it does while the mode waits and while it runs
  graph      a node graph: triggers wired to actions, variables wired to what reads and writes them
  cards      the rules as When / Then cards in plain words
  script     the same program as typed text (mode_script.py), beside the C the card runs
"""
import html
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import describe as D  # noqa: E402
import mode_script as MS  # noqa: E402
import showcase  # noqa: E402
from pinball_decryptor.plugins.stern import block_modes as BM  # noqa: E402

E = html.escape
VIEWS = ("story", "playfield", "timeline", "table", "graph", "cards", "script")
TITLES = {"story": "Story: the mode's life as a diagram", "playfield": "Playfield: rules pinned to the shots",
          "timeline": "Timeline: the clock as a track", "table": "Shot table: every shot, waiting and running",
          "graph": "Node graph: triggers wired to actions", "cards": "Rule cards: When ... Then, in words",
          "script": "Script: the same mode as text, beside its C"}

CSS = """
:root{--bg:#15171a;--bg-2:#1b1e22;--panel:#22262b;--panel-2:#2a2f35;--panel-3:#323841;--line:#333940;--line-2:#414951;
--ink:#e9eae7;--ink-2:#b7bbb9;--ink-3:#8b9196;--accent:#e8a33d;--ok:#6fc07a;--info:#7fb0e6;--err:#f0705f;
--mono:"Cascadia Mono",Consolas,monospace;--sans:"Segoe UI",system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.4 var(--sans)}
.top{display:flex;align-items:center;gap:14px;padding:10px 18px;background:var(--bg-2);border-bottom:1px solid var(--line)}
.top .mode{font-weight:700;font-size:16px;letter-spacing:.04em}
.top .meta{color:var(--ink-3);font-size:12.5px}
.tabs{display:flex;gap:4px;margin-left:auto}
.tabs span{padding:5px 11px;border-radius:7px;color:var(--ink-2);font-size:12.5px;border:1px solid transparent}
.tabs span.on{background:var(--panel-2);color:var(--ink);border-color:var(--line-2)}
.mock{text-align:right;padding:4px 14px 10px;color:var(--ink-3);font-size:11.5px}
.wrap{padding:16px 18px}
h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin:0 0 8px;font-weight:600}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;color:#fff;margin:1px 2px;white-space:nowrap}
.row{display:flex;align-items:flex-start;gap:6px;margin:3px 0;font-size:13px}
.dot{width:9px;height:9px;border-radius:3px;flex:none;margin-top:5px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.hat{font-weight:600;color:#ffd77a;margin-bottom:4px;font-size:13px}
.muted{color:var(--ink-3)}
"""


def page(view, prog, body, extra_css=""):
    tabs = "".join('<span class="%s">%s</span>' % ("on" if v == view else "", v.title()) for v in ("blocks",) + VIEWS)
    meta = "%s s clock%s · %d rules · %d variables · %d timer" % (
        prog["seconds"], ", ends on a drain" if prog["ends_on_drain"] else "", len(prog["scripts"]),
        len(prog["vars"]), len(prog["timers"]))
    return ("<!doctype html><html><head><meta charset='utf-8'><style>%s%s</style></head><body>"
            "<div class='top'><span class='mode'>%s</span><span class='meta'>%s</span><div class='tabs'>%s</div></div>"
            "<div class='wrap'>%s</div><div class='mock'>PAD-611 mockup · %s · drawn from the mode's blocks.json"
            "</div></body></html>") % (CSS, extra_css, E(prog["name"]), E(meta), tabs, body, E(TITLES[view]))


def rule_rows(stack, max_rows=99):
    out = []
    for depth, fam, words in D.lines(stack)[:max_rows]:
        out.append("<div class='row' style='margin-left:%dpx'><span class='dot' style='background:%s'></span>"
                   "<span>%s</span></div>" % (depth * 16, D.FAMILY_COLOUR.get(fam, "#888"), E(words)))
    return "".join(out)


# ---- classifying the scripts --------------------------------------------------------------------------------------
def state_of(h):
    """Which part of the mode's life a hat works in: waiting, running, both, in (on the way in), out, drain."""
    k, w = h.get("kind"), h.get("when", "any")
    if k == "mode_start":
        return "in"
    if k == "mode_end":
        return "out"
    if k == "ball_end":
        return "drain"
    if k in ("every", "seconds_left", "timer_done"):
        return "running"
    if k in ("challenge", "battle", "game_mode", "completed"):   # PAD-706: a battle is picked, like a challenge, before the mode runs; PAD-710: a game mode started; PAD-747: the game's modes completed
        return "waiting"
    return {"idle": "waiting", "running": "running"}.get(w, "both")


def walk(stack, path=()):
    """Every block with the conditions it sits under."""
    for b in stack or []:
        if not isinstance(b, dict):
            continue
        if b.get("op") == "if":
            yield from walk(b.get("then"), path + (D.cond(b.get("cond")),))
            yield from walk(b.get("else"), path + ("not (%s)" % D.cond(b.get("cond")),))
        else:
            yield b, path


def trigger_words(h, path):
    s = D.hat(h).replace("When ", "").replace(" (not running)", "").replace(" (running)", "")
    return s + ("<br><span class='muted'>if %s</span>" % E(" and ".join(path)) if path else "")


# ---- story -------------------------------------------------------------------------------------------------------
def story(prog):
    cols = {"waiting": [], "running": [], "both": [], "in": [], "out": [], "drain": []}
    starts, ends = [], []
    for s in prog["scripts"]:
        st = state_of(s["hat"])
        cols[st].append(s)
        for b, path in walk(s["do"]):
            if b.get("op") == "start_mode":
                starts.append(trigger_words(s["hat"], path))
            if b.get("op") == "end_mode":
                ends.append(trigger_words(s["hat"], path))
    if prog["seconds"]:
        adds = sum(1 for s in prog["scripts"] for b, _p in walk(s["do"]) if b.get("op") == "add_time")
        ends.insert(0, "the clock runs out (%d s%s)" % (prog["seconds"], ", jackpots add time" if adds else ""))
    if prog["ends_on_drain"]:
        ends.append("the ball drains")

    def state(title, sub, scripts, cls):
        cards = "".join("<div class='card r'><div class='hat'>%s</div>%s</div>" % (E(D.hat(s["hat"])), rule_rows(s["do"]))
                        for s in scripts) or "<div class='muted'>nothing happens here</div>"
        return "<div class='state %s'><div class='sh'><b>%s</b><span>%s</span></div>%s</div>" % (cls, title, sub, cards)

    def arrow(label, items, inside):
        trig = "".join("<div class='trig'>%s</div>" % t for t in items) or "<div class='muted'>never</div>"
        on_way = ("<div class='way'><div class='wayh'>%s</div>%s</div>" % (label, "".join(
            rule_rows(s["do"]) for s in inside))) if inside else ""
        return "<div class='arrow'><div class='trigs'>%s</div><div class='shaft'></div>%s</div>" % (trig, on_way)

    vars_ = "".join("<span class='chip' style='background:#c8553a'>%s · reset each %s</span>" % (
        E(v["name"]), E(v.get("reset", "ball"))) for v in prog["vars"])
    timers = "".join("<span class='chip' style='background:#b0457e'>timer %s</span>" % E(t["name"]) for t in prog["timers"])
    body = ("<div class='flow'>%s%s%s%s%s</div>"
            "<div class='foot'>%s<div class='card'><div class='hat'>Any time (waiting or running)</div>%s</div>"
            "<div class='card'><div class='hat'>When the ball drains</div>%s</div><div class='card'><h2>It keeps</h2>%s %s</div></div>") % (
        state("WAITING", "until it starts", cols["waiting"], "w"),
        arrow("on the way in", starts, cols["in"]),
        state("RUNNING", "%d s on the clock" % prog["seconds"] if prog["seconds"] else "until a block ends it",
              cols["running"], "run"),
        arrow("on the way out", ends, cols["out"]),
        "<div class='state over'><div class='sh'><b>OVER</b><span>back to waiting</span></div>"
        "<div class='loop'>↻ next time it starts again</div></div>",
        "", "".join(rule_rows(s["do"]) for s in cols["both"]) or "<div class='muted'>none</div>",
        "".join(rule_rows(s["do"]) for s in cols["drain"]) or "<div class='muted'>none</div>", vars_, timers)
    css = """
.flow{display:grid;grid-template-columns:1fr 210px 1.25fr 210px .55fr;gap:0;align-items:stretch}
.state{border:2px solid var(--line-2);border-radius:16px;padding:10px;background:var(--bg-2);display:flex;flex-direction:column;gap:8px}
.state.w{border-color:#6b7480}.state.run{border-color:#e8a33d;box-shadow:0 0 0 4px rgba(232,163,61,.12)}.state.over{border-style:dashed}
.sh{display:flex;align-items:baseline;gap:8px}.sh b{font-size:15px;letter-spacing:.08em}.sh span{color:var(--ink-3);font-size:12px}
.arrow{display:flex;flex-direction:column;justify-content:center;padding:0 8px;gap:8px}
.shaft{height:4px;background:var(--accent);position:relative;margin:2px 4px}
.shaft:after{content:"";position:absolute;right:-4px;top:-7px;border:9px solid transparent;border-left:12px solid var(--accent);border-right:0}
.trig{background:var(--panel-2);border:1px solid var(--accent);border-radius:8px;padding:5px 8px;font-size:12.5px;margin:3px 0}
.way{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 8px}
.wayh{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3);margin-bottom:2px}
.loop{color:var(--ink-3);font-size:13px;margin-top:20px;text-align:center}
.r .row{font-size:12.5px}
.foot{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:14px}
"""
    return page("story", prog, body, css)


# ---- playfield ---------------------------------------------------------------------------------------------------
#: where a shot sits on the schematic playfield (x 0-100 across, y 0-100 down), by the words in its name
SPOTS = [("left ramp", 22, 30), ("right ramp", 74, 28), ("big loop", 88, 46), ("building", 50, 22),
         ("godzilla", 40, 42), ("maser", 60, 42), ("powerline left", 34, 58), ("powerline center", 50, 60),
         ("powerline right", 66, 58), ("left spinner", 14, 48), ("top spinner", 50, 10), ("right spinner", 84, 62),
         ("left orbit", 10, 30), ("right orbit", 90, 30), ("scoop", 30, 46)]


def spot(name, i):
    n = name.lower()
    for key, x, y in SPOTS:
        if key in n:
            return x, y
    a = i * 2.4
    return 50 + 30 * math.cos(a), 40 + 22 * math.sin(a)


def playfield(prog):
    shots = {}
    other = []
    lit = {}
    for s in prog["scripts"]:
        h = s["hat"]
        if h.get("kind") == "shot":
            shots.setdefault(h["shot"], []).append(s)
        else:
            other.append(s)
        for b, _p in walk(s["do"]):
            if b.get("op") == "light_shot" and b.get("shot"):
                lit.setdefault(b["shot"], b.get("color"))
    for name in list(lit):
        shots.setdefault(name, [])
    pins, cards = [], []
    for i, (name, ss) in enumerate(sorted(shots.items())):
        x, y = spot(name, i)
        c = lit.get(name, "#8b9196")
        pins.append("<div class='pin' style='left:%.1f%%;top:%.1f%%;--c:%s'><i></i><b>%s</b></div>" % (x, y, c, E(name)))
        rows = "".join("<div class='when'>%s</div>%s" % (
            {"idle": "waiting", "running": "running"}.get(s["hat"].get("when"), "any time"), rule_rows(s["do"])) for s in ss)
        lights = "".join("<div class='row'><span class='dot' style='background:%s'></span>lit by: %s</div>" % (
            c, E(D.hat(s["hat"]))) for s in prog["scripts"] for b, _p in walk(s["do"])
            if b.get("op") == "light_shot" and b.get("shot") == name)
        cards.append("<div class='card sc'><div class='hat' style='color:%s'>◉ %s</div>%s%s</div>" % (
            c, E(name), rows, lights))
    others = "".join("<div class='card sc'><div class='hat'>%s</div>%s</div>" % (E(D.hat(s["hat"])), rule_rows(s["do"]))
                     for s in other)
    body = ("<div class='pf'><div class='table'><div class='glass'></div>%s"
            "<div class='flip l'></div><div class='flip r'></div><div class='sling l'></div><div class='sling r'></div></div>"
            "<div class='side'><h2>Shots · click one on the playfield to add what it does</h2>%s"
            "<h2 style='margin-top:12px'>Not tied to a shot</h2><div class='others'>%s</div></div></div>") % (
        "".join(pins), "".join(cards), others)
    css = """
.pf{display:grid;grid-template-columns:430px 1fr;gap:18px}
.table{position:relative;height:820px;border-radius:200px 200px 22px 22px;background:linear-gradient(#1d2a3a,#16202c);
border:3px solid #3c4a5c;overflow:hidden}
.glass{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 30%,rgba(127,176,230,.10),transparent 60%)}
.pin{position:absolute;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;gap:3px}
.pin i{width:22px;height:22px;border-radius:50%;background:var(--c);box-shadow:0 0 14px var(--c),0 0 3px #000;border:2px solid #0008}
.pin b{font-size:11.5px;background:#000a;padding:1px 6px;border-radius:5px;white-space:nowrap}
.flip{position:absolute;bottom:60px;width:90px;height:16px;background:#ddd;border-radius:9px}
.flip.l{left:105px;transform:rotate(24deg)}.flip.r{right:105px;transform:rotate(-24deg)}
.sling{position:absolute;bottom:120px;width:0;height:0;border:28px solid transparent}
.sling.l{left:60px;border-left:22px solid #445}.sling.r{right:60px;border-right:22px solid #445}
.side{display:grid;grid-template-columns:1fr 1fr;gap:10px;align-content:start}
.side h2{grid-column:1/-1}.others{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
.when{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3);margin-top:4px}
.sc .row{font-size:12.5px}
"""
    return page("playfield", prog, body, css)


# ---- timeline ----------------------------------------------------------------------------------------------------
TRACKS = [("Clock", ("mode",)), ("Lights", ("show_light",)), ("Light shows", ("show",)),
          ("Sound", ("sound",)), ("Screen and HUD", ("hud",)), ("Score and variables", ("score", "var", "timer"))]


def track_of(b):
    op = b.get("op")
    if op in ("light_shot", "lights_off", "light_mode", "unlight_mode"):
        return "Lights"
    if op in ("show", "game_show"):
        return "Light shows"
    if op in ("callout", "sound", "music"):
        return "Sound"
    if op in ("words", "hud_text", "hud_counter", "hud_gauge", "hud_award", "hud_progress", "roster_progress", "clip"):
        return "Screen and HUD"
    if op in ("start_mode", "end_mode", "add_time", "set_time", "multiball", "ball_save", "drain_to_one"):
        return "Clock"
    return "Score and variables"


def timeline(prog):
    secs = prog["seconds"] or 30
    moments = []                        # (second, label, script)
    for s in prog["scripts"]:
        h = s["hat"]
        if h["kind"] == "mode_start":
            moments.append((0, "start", s))
        elif h["kind"] == "seconds_left":
            moments.append((secs - h["seconds"], "%d s left" % h["seconds"], s))
        elif h["kind"] == "every":
            for t in range(h["seconds"], secs, h["seconds"]):
                moments.append((t, "every %d s" % h["seconds"], s))
        elif h["kind"] == "mode_end":
            moments.append((secs, "end", s))
    ticks = "".join("<div class='tick' style='left:%.2f%%'><span>%d</span></div>" % (t * 100.0 / secs, t)
                    for t in range(0, secs + 1, 5))
    lanes = []
    for name, _fam in TRACKS:
        items = []
        for t, label, s in moments:
            for b, path in walk(s["do"]):
                if track_of(b) != name:
                    continue
                fam = D.FAMILY.get(b.get("op"), "show")
                at = t * 100.0 / secs
                where = "left:%.2f%%" % at if at < 60 else "right:%.2f%%" % (100 - at)
                items.append("<div class='it' style='%s;background:%s'>%s%s</div>" % (
                    where, D.FAMILY_COLOUR[fam], E(D.say(b)),
                    " <i>if %s</i>" % E(" and ".join(path)) if path else ""))
        if name == "Clock":
            items.insert(0, "<div class='clk'>%d s on the clock%s</div>" % (
                secs, "".join(" · +%s s %s" % (D.val(b.get("seconds")), E(D.hat(s["hat"]).replace("When ", "when ")))
                              for s in prog["scripts"] for b, _p in walk(s["do"]) if b.get("op") == "add_time")))
        lanes.append("<div class='lane'><div class='ln'>%s</div><div class='lt'>%s</div></div>" % (
            name, "".join(items)))
    marks = "".join("<div class='mk' style='left:%.2f%%'><b>%s</b></div>" % (t * 100.0 / secs, E(label))
                    for t, label in sorted({(t, l) for t, l, _s in moments}))
    react = "".join("<div class='card rc'><div class='hat'>%s</div>%s</div>" % (E(D.hat(s["hat"])), rule_rows(s["do"]))
                    for s in prog["scripts"] if s["hat"]["kind"] in ("shot", "any_shot", "event", "timer_done", "ball_end"))
    body = ("<h2>The mode's %d seconds · drag a block onto a moment</h2><div class='tl'><div class='axis'>%s%s</div>%s</div>"
            "<h2 style='margin-top:16px'>Whenever it happens (not at a fixed time)</h2><div class='reacts'>%s</div>") % (
        secs, ticks, marks, "".join(lanes), react)
    css = """
.tl{background:var(--bg-2);border:1px solid var(--line);border-radius:10px;padding:10px 12px 12px 150px;position:relative}
.axis{position:relative;height:46px;border-bottom:1px solid var(--line-2);margin-bottom:6px}
.tick{position:absolute;bottom:0;height:8px;border-left:1px solid var(--line-2)}
.tick span{position:absolute;top:12px;left:-6px;font-size:11px;color:var(--ink-3)}
.mk{position:absolute;top:0;transform:translateX(-50%)}.mk b{background:var(--accent);color:#111;font-size:11.5px;padding:1px 7px;border-radius:5px;white-space:nowrap}
.lane{position:relative;height:50px;border-bottom:1px dashed var(--line)}
.ln{position:absolute;left:-140px;top:15px;width:130px;color:var(--ink-2);font-size:12.5px}
.lt{position:relative;height:100%}
.it{position:absolute;top:8px;padding:5px 9px;border-radius:7px;color:#fff;font-size:12px;white-space:nowrap;max-width:300px;
overflow:hidden;text-overflow:ellipsis;box-shadow:0 2px 6px #0007}
.it i{opacity:.8}
.clk{position:absolute;left:0;right:0;top:14px;height:22px;border-radius:11px;background:linear-gradient(90deg,#8b5bd6,#8b5bd655);color:#fff;font-size:12px;padding:3px 12px}
.it:nth-child(2n){top:26px}
.reacts{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.rc .row{font-size:12.5px}
"""
    return page("timeline", prog, body, css)


# ---- table -------------------------------------------------------------------------------------------------------
def table(prog):
    rows = {}
    for s in prog["scripts"]:
        h = s["hat"]
        if h["kind"] in ("shot", "any_shot"):
            key = h.get("shot") if h["kind"] == "shot" else "Any shot"
            col = {"idle": 0, "running": 1}.get(h.get("when"), 2)
            rows.setdefault(key, [[], [], []])[col].append(s)
    order = [n for n in showcase.SHOTS if n in rows] + [n for n in rows if n not in showcase.SHOTS]
    for n in showcase.SHOTS[:8]:
        if n not in rows:
            rows[n] = [[], [], []]
            order.append(n)
    trs = []
    for n in order:
        cells = "".join("<td>%s</td>" % ("".join(rule_rows(s["do"]) for s in ss) or "<span class='add'>+</span>")
                        for ss in rows[n])
        trs.append("<tr><th>%s</th>%s</tr>" % (E(n), cells))
    other = "".join("<tr><th>%s</th><td colspan=3>%s</td></tr>" % (E(D.hat(s["hat"])), rule_rows(s["do"]))
                    for s in prog["scripts"] if s["hat"]["kind"] not in ("shot", "any_shot"))
    body = ("<table class='g'><thead><tr><th>Shot</th><th>While it waits</th><th>While it runs</th><th>Any time</th></tr>"
            "</thead><tbody>%s</tbody></table><h2 style='margin-top:14px'>Moments and other triggers</h2>"
            "<table class='g'><tbody>%s</tbody></table>") % ("".join(trs), other)
    css = """
table.g{width:100%;border-collapse:collapse;background:var(--bg-2);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.g th,.g td{border:1px solid var(--line);padding:6px 9px;vertical-align:top;text-align:left;font-size:13px}
.g thead th{background:var(--panel-2);color:var(--ink-2);font-weight:600}
.g tbody th{width:220px;color:#ffd77a;font-weight:600}
.g td .row{font-size:12.5px}.add{color:var(--ink-3);font-size:18px}
"""
    return page("table", prog, body, css)


# ---- graph -------------------------------------------------------------------------------------------------------
def graph(prog):
    W, NODE_W, NODE_H, GAP, ROW = 1400, 160, 40, 12, 52
    svg, wires, y = [], [], 16
    var_y = {}
    links = []
    var_x = W - 130
    X0 = 16 + NODE_W + 24
    for i, v in enumerate(prog["vars"] + [{"name": t["name"], "timer": True} for t in prog["timers"]]):
        var_y[v["name"]] = 60 + i * 80

    def node(x, y, fam, text, hat=False):
        c = D.FAMILY_COLOUR[fam]
        t = text if len(text) <= 25 else text[:24] + "…"
        r = 14 if hat else 7
        svg.append("<rect x='%d' y='%d' width='%d' height='%d' rx='%d' fill='%s' stroke='#0006'/>" % (x, y, NODE_W, NODE_H, r, c))
        svg.append("<text x='%d' y='%d' class='nt'>%s</text>" % (x + 10, y + 25, E(t)))
        svg.append("<circle cx='%d' cy='%d' r='4' class='port'/>" % (x + NODE_W, y + NODE_H // 2))
        if not hat:
            svg.append("<circle cx='%d' cy='%d' r='4' class='port'/>" % (x, y + NODE_H // 2))

    def wire(x1, y1, x2, y2, cls="w"):
        mx = (x1 + x2) / 2
        wires.append("<path d='M%d %d C%d %d %d %d %d %d' class='%s'/>" % (x1, y1, mx, y1, mx, y2, x2, y2, cls))

    def chain(stack, x, y, fromx, fromy):
        """Lay a stack out left to right from (x, y); returns the next free row's y."""
        lowest = y
        for b in stack or []:
            if x + NODE_W > var_x - 40:
                x, y = X0, lowest + ROW
                lowest = y
            if b.get("op") == "if":
                node(x, y, "flow", "If " + D.cond(b.get("cond")))
                wire(fromx, fromy, x, y + NODE_H // 2)
                for name in _reads(b.get("cond")):
                    links.append((x + NODE_W // 2, y, name))
                svg.append("<text x='%d' y='%d' class='yn'>yes</text>" % (x + NODE_W + 8, y + 14))
                end_yes = chain(b.get("then"), x + NODE_W + GAP + 20, y, x + NODE_W, y + NODE_H // 2)
                ny = end_yes + ROW
                if b.get("else") is not None:
                    svg.append("<text x='%d' y='%d' class='yn'>no</text>" % (x + NODE_W + 8, ny + 14))
                    end_no = chain(b.get("else"), x + NODE_W + GAP + 20, ny, x + NODE_W, y + NODE_H // 2)
                    ny = end_no + ROW
                return max(lowest, ny - ROW)
            node(x, y, D.FAMILY.get(b.get("op"), "show"), D.say(b))
            wire(fromx, fromy, x, y + NODE_H // 2)
            v = b.get("var") or b.get("timer")
            if v in var_y:
                links.append((x + NODE_W // 2, y + NODE_H, v, "set"))
            for f in ("points", "value", "by", "ms", "seconds"):
                for name in _reads(b.get(f)):
                    links.append((x + NODE_W // 2, y, name))
            fromx, fromy = x + NODE_W, y + NODE_H // 2
            x += NODE_W + GAP
        return lowest

    for s in prog["scripts"]:
        node(16, y, "hat", D.hat(s["hat"]), hat=True)
        y = chain(s["do"], X0, y, 16 + NODE_W, y + NODE_H // 2) + ROW + 6
    for name, vy in var_y.items():
        svg.append("<rect x='%d' y='%d' width='130' height='44' rx='22' class='var'/>" % (var_x, vy))
        svg.append("<text x='%d' y='%d' class='vt'>%s</text>" % (var_x + 65, vy + 27, E(name)))
    for link in links:
        x, yy, name = link[0], link[1], link[2]
        if name in var_y:
            wire(var_x, var_y[name] + 22, x, yy, "dw set" if len(link) > 3 else "dw")
    h = y + 10
    body = ("<h2>Each trigger wired to what it does · dashed wires: the variables each block reads and writes</h2>"
            "<svg width='%d' height='%d' class='gsv'>%s</svg>") % (W, h, "".join(wires + svg))
    css = """
.gsv{background:var(--bg-2);border:1px solid var(--line);border-radius:10px;
background-image:radial-gradient(#ffffff12 1px,transparent 1px);background-size:18px 18px}
.nt{fill:#fff;font:12px var(--sans)}.port{fill:#fff;stroke:#0008}
.w{fill:none;stroke:#e9eae7aa;stroke-width:2}.dw{fill:none;stroke:#c8553a88;stroke-width:1.5;stroke-dasharray:5 4}
.dw.set{stroke:#c8553acc}.var{fill:#c8553a33;stroke:#c8553a}.vt{fill:#ffb19f;font:600 13px var(--sans);text-anchor:middle}
.yn{fill:var(--ink-3);font:11px var(--sans)}
"""
    return page("graph", prog, body, css)


def _reads(e):
    if not isinstance(e, dict):
        return []
    out = []
    if e.get("k") == "var":
        out.append(e.get("name"))
    if e.get("k") == "timer_left":
        out.append(e.get("timer"))
    for key in ("a", "b"):
        out += _reads(e.get(key))
    return out


# ---- cards -------------------------------------------------------------------------------------------------------
def cards(prog):
    out = []
    for s in prog["scripts"]:
        thens = []
        for depth, fam, words in D.lines(s["do"]):
            thens.append("<div class='then' style='margin-left:%dpx;border-color:%s'>%s</div>" % (
                depth * 22, D.FAMILY_COLOUR.get(fam, "#888"), E(words)))
        out.append("<div class='rule'><div class='when'><span>WHEN</span>%s</div><div class='thens'><span>THEN</span>%s"
                   "<div class='addc'>+ add what happens</div></div></div>" % (E(D.hat(s["hat"])), "".join(thens)))
    body = ("<h2>Every rule of the mode, as a sentence · click any underlined word to change it</h2>"
            "<div class='rules'>%s<div class='rule newr'>+ New rule: When …</div></div>") % "".join(out)
    css = """
.rules{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.rule{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.when{background:#c28a1233;border-bottom:1px solid #c28a1277;padding:9px 12px;font-weight:600;font-size:14px}
.when span,.thens>span{display:block;font-size:10.5px;letter-spacing:.12em;color:var(--ink-3);font-weight:600}
.thens{padding:8px 12px}.then{border-left:4px solid;padding:3px 8px;margin:4px 0;background:var(--panel-2);border-radius:0 6px 6px 0;
font-size:13px;text-decoration:underline dotted #fff5}
.addc{color:var(--ink-3);font-size:12px;margin-top:6px}.newr{display:flex;align-items:center;justify-content:center;
color:var(--ink-3);border-style:dashed;min-height:90px}
"""
    return page("cards", prog, body, css)


# ---- script ------------------------------------------------------------------------------------------------------
KW = ("with", "if", "else", "and", "or", "not", "pass", "None", "True", "False")


def highlight(src):
    import re
    out = []
    for line in src.splitlines():
        s = E(line)
        s = re.sub(r"(&quot;.*?&quot;)", r"<span class='s'>\1</span>", s)
        s = re.sub(r"\b(on\.\w+)\b", r"<span class='h'>\1</span>", s)
        s = re.sub(r"\b(%s)\b" % "|".join(KW), r"<span class='k'>\1</span>", s)
        s = re.sub(r"\b(\d[\d_]*)\b", r"<span class='n'>\1</span>", s)
        s = re.sub(r"^(\s*)(\w+)\(", r"\1<span class='f'>\2</span>(", s)
        out.append(s)
    return "\n".join(out)


def c_excerpt(prog):
    c = BM.to_c(prog, "ramp_frenzy")
    i = c.find("static void on_shot(")
    j = c.find("\n}\n", i)
    return c[i:j + 2], len(c.splitlines())


def script(prog):
    text = MS.to_script(prog, defaults=BM.normalize({}))
    c, n = c_excerpt(prog)
    body = ("<div class='two'><div><h2>The mode as script · type it, or switch to blocks: the same program</h2>"
            "<pre class='code'>%s</pre></div><div><h2>The C it makes (%d lines; the shots part shown)</h2>"
            "<pre class='code c'>%s</pre></div></div>") % (highlight(text), n, E(c))
    css = """
.two{display:grid;grid-template-columns:1.05fr 1fr;gap:14px}
.code{margin:0;background:#111316;border:1px solid var(--line);border-radius:10px;padding:12px 14px;font:12px/1.5 var(--mono);
color:#c9cdcb;white-space:pre;overflow:hidden}
.code .s{color:#a5d6a7}.code .k{color:#e8a33d;font-weight:600}.code .n{color:#7fb0e6}.code .h{color:#ffd77a;font-weight:600}
.code .f{color:#d18cff}.c{color:#9aa3a8;font-size:11px}
"""
    return page("script", prog, body, css)


RENDER = {"story": story, "playfield": playfield, "timeline": timeline, "table": table, "graph": graph,
          "cards": cards, "script": script}


def shoot(paths, height=1000):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
            from playwright.sync_api import sync_playwright
        else:
            print("no Playwright: html only")
            return
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        pg = browser.new_page(viewport={"width": 1440, "height": height})
        for path in paths:
            pg.goto("file:///" + path.replace("\\", "/"))
            pg.wait_for_timeout(300)
            pg.screenshot(path=path[:-5] + ".png", full_page=True)
        browser.close()


def main():
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    if len(sys.argv) > 2:
        with open(sys.argv[2], encoding="utf-8") as f:
            prog = BM.normalize(json.load(f))
    else:
        prog = showcase.program()
    paths = []
    for v in VIEWS:
        path = os.path.join(out, v + ".html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(RENDER[v](prog))
        paths.append(path)
    shoot(paths)
    print("views in", out)


if __name__ == "__main__":
    main()
