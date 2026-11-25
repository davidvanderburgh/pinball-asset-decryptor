"""PAD-1587 proof, run by WSL's python: the stand-in client's own throwaway key (never this PC's real one)."""
import sys
sys.path.insert(0, '/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1587')
from pinball_decryptor.core import pad_ssh_key  # noqa: E402
pad_ssh_key.KEY_DIR = '/tmp/pad1587-client/remote_access'
_priv, line = pad_ssh_key.ensure()
open('/mnt/c/tmp/PAD-1587/client_key.pub', 'w').write(line)
print(line.strip())
