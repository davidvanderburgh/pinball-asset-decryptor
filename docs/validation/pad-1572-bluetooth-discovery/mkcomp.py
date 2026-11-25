"""PAD-1572: comp.cfg (Prolonged Competition, the app's own text) for the game ELF given: mkcomp.py <game elf> <out>."""
import sys
sys.path.insert(0, '/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1572')
from pinball_decryptor.plugins.stern import prolonged_comp
open(sys.argv[2], 'w').write(prolonged_comp.cfg_text(sys.argv[1], True))
print(open(sys.argv[2]).read())
