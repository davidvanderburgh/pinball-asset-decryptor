"""compcfg.py <game program> <out comp.cfg> - the card's comp.cfg for a Prolonged Competition proof (compjob.sh), as the
Modes tab writes it (plugins/stern/prolonged_comp.cfg_text, with `only`: nothing else on the card). PAD-1555."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))
from pinball_decryptor.plugins.stern import prolonged_comp as P  # noqa: E402

if __name__ == "__main__":
    text = P.cfg_text(sys.argv[1], True)
    pathlib.Path(sys.argv[2]).write_text(text, encoding="utf-8", newline="\n")
    print(sys.argv[2], " ".join(text.split()))
