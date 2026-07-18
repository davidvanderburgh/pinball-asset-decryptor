"""Size+mtime-keyed MD5 cache for change scans.

The Write tab's change scan and the mod-pack export both MD5 every baseline
file to find the changed ones — minutes of re-hashing on big or networked
folders even when almost nothing changed since the last walk (monkeybug
batch 14).  This sidecar remembers each file's ``(size, mtime_ns, md5)``;
a later walk re-hashes only files whose size or mtime moved, rsync-style.

Advisory only: deleting the sidecar just costs one full re-hash pass, and a
corrupt one is ignored.  An edit that preserves BOTH size and mtime_ns is
invisible to it — that doesn't happen through this app or normal tooling.
"""

import json
import os

from .checksums import md5_file

CACHE_FILE = ".hashcache.json"


def load(assets_dir):
    """``{rel: [size, mtime_ns, md5]}`` from the sidecar; ``{}`` when absent
    or unreadable."""
    try:
        with open(os.path.join(assets_dir, CACHE_FILE),
                  "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {k: v for k, v in data.items()
                    if isinstance(v, list) and len(v) == 3}
    except (OSError, ValueError):
        pass
    return {}


def save(assets_dir, cache):
    """Best-effort persist (the cache is advisory)."""
    try:
        with open(os.path.join(assets_dir, CACHE_FILE),
                  "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError:
        pass


def md5_for(abs_path, rel, cache):
    """MD5 of *abs_path*, from *cache* when its size+mtime still match, else
    freshly hashed (updating *cache* in place).  ``None`` on read failure."""
    try:
        st = os.stat(abs_path)
    except OSError:
        return None
    ent = cache.get(rel)
    if ent and ent[0] == st.st_size and ent[1] == st.st_mtime_ns:
        return ent[2]
    try:
        digest = md5_file(abs_path)
    except OSError:
        return None
    cache[rel] = [st.st_size, st.st_mtime_ns, digest]
    return digest
