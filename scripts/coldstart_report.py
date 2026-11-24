"""What a coldstart_timing.py run measured: python scripts/coldstart_report.py OUT.json"""
import json, sys, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
d = json.load(open(sys.argv[1]))
for n, t in d['marks']: print('%7.3f  %s' % (t, n))
marks = dict(d['marks'])
t_app0, t_app1 = marks['App() begin'], marks['App() end']
ui = [(t, c) for t, n, c in d['samples'] if n == 'pad-ui']
DT = 0.016
def idle(c):
    return all(x.startswith(('threading.py', 'webui/loop.py')) for x in c)
def key(c, depth):
    app = [x for x in c if not x.startswith(('threading.py', 'webui/loop.py'))]
    return ' > '.join(app[:depth])
print('--- inside App() (%.2f s): by call under App.__init__' % (t_app1 - t_app0))
agg = collections.Counter()
for t, c in ui:
    if t_app0 <= t <= t_app1:
        app = [x for x in c if not x.startswith(('threading.py', 'webui/loop.py', 'webui/host.py', 'coldstart.py'))]
        agg[' > '.join(app[1:3])] += DT
for k, v in agg.most_common(14): print('  %5.2f s  %s' % (v, k))
print('--- inside App(): innermost frame')
agg = collections.Counter()
for t, c in ui:
    if t_app0 <= t <= t_app1: agg[' < '.join(reversed(c[-3:]))] += DT
for k, v in agg.most_common(12): print('  %5.2f s  %s' % (v, k))
print('--- UI loop busy AFTER App() (jobs it queued), by job')
agg = collections.Counter(); busy = 0
for t, c in ui:
    if t > t_app1 and not idle(c):
        busy += DT; agg[key(c, 2)] += DT
print('  total busy %.2f s of %.1f s' % (busy, ui[-1][0] - t_app1))
for k, v in agg.most_common(16): print('  %5.2f s  %s' % (v, k))
print('--- busy spans of the UI loop after App() (>= 80 ms)')
span = None
for t, c in ui:
    if t <= t_app1: continue
    if not idle(c):
        if span is None: span = [t, t, collections.Counter()]
        span[1] = t; span[2][key(c, 1)] += 1
    else:
        if span and span[1] - span[0] >= 0.08:
            print('  %6.2f - %6.2f (%4.0f ms)  %s' % (span[0], span[1], (span[1]-span[0])*1000, span[2].most_common(1)[0][0]))
        span = None
lat = d.get('latency') or []
if lat:
    bad = [(t, ms) for t, ms in lat if ms >= 100]
    print('--- loop latency after the page is up: max %d ms; waits >= 100 ms:' % max(ms for t, ms in lat), bad[:20])
p = d.get('perf')
if p:
    nav = p['nav']
    print('--- page: responseEnd %.0f ms, domInteractive %.0f, DCL %.0f, load %.0f' % (nav['responseEnd'], nav['domInteractive'], nav['domContentLoadedEventEnd'], nav['loadEventEnd']))
    print('    paint', [(x['name'], round(x['startTime'])) for x in p['paint']])
    res = p['res']
    print('    %d requests, last one ends at %d ms, %.0f KB' % (len(res), max(r[1]+r[2] for r in res), sum(r[3] for r in res)/1024))
    for r in sorted(res, key=lambda r: -r[2])[:8]: print('     %5d ms (start %5d) %7d B  %s' % (r[2], r[1], r[3], r[0]))
