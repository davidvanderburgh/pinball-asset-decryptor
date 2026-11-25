"""PAD-1587 proof: the app's own JJP Write, headless, on Wonka v03.03 with the minimal project."""
import sys
import time

WT = r'C:\Users\david\Documents\development\pad-triage\work\tickets\PAD-1587'
sys.path.insert(0, WT)
from pinball_decryptor.plugins.jjp.manufacturer import JJPManufacturer  # noqa: E402

ISO = r'D:\Pinball\images\JJP\Wonka-v03.03.iso'
PROJ = r'C:\tmp\PAD-1587\proj'
OUT = r'C:\tmp\PAD-1587\out\Wonka-v03.03-pad1587.iso'
result = {}
t0 = time.time()


def log(msg, level='info'):
    print('[%6.0fs %s] %s' % (time.time() - t0, level, msg), flush=True)


def phase(i):
    log('-- phase %s' % i)


def progress(*a):
    pass


def done(ok, summary):
    result['ok'] = ok
    log('DONE ok=%s %s' % (ok, summary))


p = JJPManufacturer().make_write_pipeline(ISO, PROJ, OUT, log, phase, progress, done)
p.run()
print('RESULT', result)
