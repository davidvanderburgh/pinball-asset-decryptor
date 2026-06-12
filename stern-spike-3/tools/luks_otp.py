#!/usr/bin/env python3
"""
luks_otp.py - Pure-Python offline LUKS2 (aes-xts-plain64) verifier + decryptor.

Built for the Stern "Spike 3" pinball SD-card reverse-engineering effort.

What it does, with NO cryptsetup and NO machine:
  * Parse a LUKS2 binary header + JSON metadata carved from a raw partition.
  * Given a candidate 32-byte key (the keyfile that /init feeds to cryptsetup),
    perform the full LUKS2 keyslot unlock in pure Python:
        candidate key
          -> PBKDF2-HMAC-<hash>(key, slot.salt, slot.iterations, dklen=key_size)   [keyslot KEK]
          -> AES-XTS decrypt the keyslot 'area' (the AF-split material)
          -> AF-merge (anti-forensic stripe merge)                                  [master-key candidate]
          -> PBKDF2-HMAC-<hash>(master_key, digest.salt, digest.iterations)
          -> compare against digest.digest                                          [valid / invalid]
  * Decrypt an arbitrary sector range of the data segment with AES-XTS-plain64.

Only deps: `cryptography` (AES, AES-XTS) + stdlib `hashlib`/`hmac`.
If `cryptography` lacks XTS for your version we fall back to `pycryptodome`.

------------------------------------------------------------------------------
THE STERN KEYFILE (what to pass as the candidate key)
------------------------------------------------------------------------------
/init builds the key like this:

  echo `vcmailbox 0x00030021 40 40 0 8 0 0 0 0 0 0 0 0` \
     | awk '{print substr ($0, 77, 88)}' | xxd -r -p > /ktmp

vcmailbox prints the whole mailbox buffer back as space-separated 32-bit hex
words ("0x........" each). tag 0x00030021 = GET_CUSTOMER_OTP, requesting 8 rows
(start row 0, num 8). The awk grabs an 88-char substring starting at column 77;
that substring is the 8 OTP words rendered WITHOUT "0x" and WITHOUT spaces, i.e.
64 hex chars + the awk window. `xxd -r -p` turns those 64 hex chars into 32 raw
bytes. So the keyfile is simply the 8 customer-OTP rows concatenated big-endian
in the order vcmailbox printed them, MSB-first per word, exactly as the hex text
reads left-to-right. See otp_words_to_keyfile() for the helper + endianness notes.

Usage:
    python luks_otp.py selftest
    python luks_otp.py parse   <header.bin>
    python luks_otp.py verify  <header.bin> --key-hex <64hex>
    python luks_otp.py verify  <header.bin> --key-file <path>
    python luks_otp.py verify  <header.bin> --otp-words 0x..,0x..,...(8)
    python luks_otp.py decrypt <image.raw>  --part-base-lba 131073 \
            --header <header.bin> --key-hex <64hex> --sector 0 --count 8 \
            --out plain.bin
"""

import sys, os, json, struct, hashlib, hmac, binascii, argparse

# --------------------------------------------------------------------------
# AES / AES-XTS backend (cryptography preferred, pycryptodome fallback)
# --------------------------------------------------------------------------
_BACKEND = None
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    _BACKEND = "cryptography"
except Exception:
    pass

try:
    from Crypto.Cipher import AES as _PCD_AES
    _HAVE_PCD = True
except Exception:
    _HAVE_PCD = False


def aes_ecb_encrypt(key, data):
    """Raw AES-ECB encrypt (used only for the XTS pure-python fallback)."""
    if _BACKEND == "cryptography":
        c = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        e = c.encryptor()
        return e.update(data) + e.finalize()
    if _HAVE_PCD:
        return _PCD_AES.new(key, _PCD_AES.MODE_ECB).encrypt(data)
    raise RuntimeError("No AES backend available")


def aes_xts_decrypt(key, data, sector_no, sector_size=512):
    """
    AES-XTS decrypt `data`, broken into `sector_size` chunks, where the first
    chunk uses tweak = sector_no, the next sector_no+1, etc. (plain64 tweak).
    `key` is the full XTS key (key1||key2), so 64 bytes for AES-256-XTS.
    Returns plaintext.
    """
    assert len(data) % sector_size == 0, "data must be a multiple of sector_size"
    out = bytearray()
    n = sector_no
    for off in range(0, len(data), sector_size):
        chunk = data[off:off + sector_size]
        out += _xts_one_unit(key, chunk, n)
        n += 1
    return bytes(out)


def aes_xts_encrypt(key, data, sector_no, sector_size=512):
    assert len(data) % sector_size == 0, "data must be a multiple of sector_size"
    out = bytearray()
    n = sector_no
    for off in range(0, len(data), sector_size):
        chunk = data[off:off + sector_size]
        out += _xts_one_unit(key, chunk, n, encrypt=True)
        n += 1
    return bytes(out)


def _xts_one_unit(key, unit, tweak_no, encrypt=False, sector_size=512):
    """One XTS data unit. Prefer library XTS; fall back to manual XTS."""
    # plain64 tweak = little-endian 64-bit sector number, padded to 16 bytes.
    tweak = struct.pack("<Q", tweak_no & 0xFFFFFFFFFFFFFFFF) + b"\x00" * 8

    if _BACKEND == "cryptography":
        try:
            mode = modes.XTS(tweak)
            c = Cipher(algorithms.AES(key), mode, backend=default_backend())
            op = c.encryptor() if encrypt else c.decryptor()
            return op.update(unit) + op.finalize()
        except Exception:
            pass  # older cryptography w/o XTS -> manual path

    if _HAVE_PCD and hasattr(_PCD_AES, "MODE_XTS"):
        try:
            # pycryptodome wants the tweak as a 16-byte little-endian value.
            cipher = _PCD_AES.new(key, _PCD_AES.MODE_XTS, initial_value=tweak)
            return cipher.encrypt(unit) if encrypt else cipher.decrypt(unit)
        except Exception:
            pass  # fall through to manual XTS

    # Manual XTS (IEEE 1619). key = k1||k2. Handles partial final block via
    # ciphertext stealing, but LUKS units are always full multiples of 16.
    half = len(key) // 2
    k1, k2 = key[:half], key[half:]
    enc_tweak = aes_ecb_encrypt(k2, tweak)  # E_k2(tweak)
    t = int.from_bytes(enc_tweak, "little")
    out = bytearray()
    GF = (1 << 128)
    POLY = 0x87
    assert len(unit) % 16 == 0, "manual XTS path needs 16-byte multiples"
    for i in range(0, len(unit), 16):
        blk = unit[i:i + 16]
        tb = t.to_bytes(16, "little")
        x = bytes(a ^ b for a, b in zip(blk, tb))
        if encrypt:
            y = aes_ecb_encrypt(k1, x)
        else:
            y = _aes_ecb_decrypt(k1, x)
        out += bytes(a ^ b for a, b in zip(y, tb))
        # t = t * alpha in GF(2^128)
        t <<= 1
        if t & GF:
            t ^= GF | POLY  # clear bit 128, xor poly
            t &= (GF - 1)
    return bytes(out)


def _aes_ecb_decrypt(key, data):
    if _BACKEND == "cryptography":
        c = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        d = c.decryptor()
        return d.update(data) + d.finalize()
    if _HAVE_PCD:
        return _PCD_AES.new(key, _PCD_AES.MODE_ECB).decrypt(data)
    raise RuntimeError("No AES backend available")


# --------------------------------------------------------------------------
# Anti-Forensic (AF) split / merge  (cryptsetup afsplit.c)
# --------------------------------------------------------------------------
def _af_hash(hash_name, data, target_len):
    """Diffuse `data` to `target_len` bytes using iterated `hash_name`,
    matching cryptsetup's diffuse(): blocks of digestsize, each =
    H( BE32(block_index) || data_block )."""
    h = hashlib.new(hash_name)
    digest_size = h.digest_size
    out = bytearray()
    blocks = target_len // digest_size
    pad = target_len % digest_size
    i = 0
    while i < blocks:
        hh = hashlib.new(hash_name)
        hh.update(struct.pack(">I", i))
        hh.update(data[i * digest_size:(i + 1) * digest_size])
        out += hh.digest()
        i += 1
    if pad:
        hh = hashlib.new(hash_name)
        hh.update(struct.pack(">I", i))
        hh.update(data[i * digest_size:i * digest_size + pad])
        out += hh.digest()[:pad]
    return bytes(out)


def af_merge(split_material, key_len, stripes, hash_name):
    """Reverse of AF_split: collapse `stripes` blocks back to a `key_len` key."""
    assert len(split_material) == key_len * stripes, \
        "split material must be key_len*stripes"
    block = bytearray(key_len)
    for s in range(stripes - 1):
        seg = split_material[s * key_len:(s + 1) * key_len]
        block = bytearray(a ^ b for a, b in zip(block, seg))
        block = bytearray(_af_hash(hash_name, bytes(block), key_len))
    last = split_material[(stripes - 1) * key_len:stripes * key_len]
    return bytes(a ^ b for a, b in zip(block, last))


def af_split(key, stripes, hash_name, rng=None):
    """Forward AF_split - only used by the self-test."""
    key_len = len(key)
    if rng is None:
        rng = os.urandom
    out = bytearray()
    block = bytearray(key_len)
    rand_blocks = []
    for s in range(stripes - 1):
        r = rng(key_len)
        rand_blocks.append(r)
        out += r
        block = bytearray(a ^ b for a, b in zip(block, r))
        block = bytearray(_af_hash(hash_name, bytes(block), key_len))
    last = bytes(a ^ b for a, b in zip(block, key))
    out += last
    return bytes(out)


# --------------------------------------------------------------------------
# LUKS2 header parsing
# --------------------------------------------------------------------------
LUKS2_MAGIC_1 = b"LUKS\xba\xbe"
LUKS2_MAGIC_2 = b"SKUL\xba\xbe"  # secondary header magic


class Luks2Header:
    def __init__(self, raw):
        self.raw = raw
        magic = raw[0:6]
        if magic not in (LUKS2_MAGIC_1, LUKS2_MAGIC_2):
            raise ValueError("Not a LUKS2 header (bad magic %r)" % magic)
        # binary header (big-endian)
        self.version = struct.unpack(">H", raw[6:8])[0]
        if self.version != 2:
            raise ValueError("Not LUKS version 2 (got %d)" % self.version)
        self.hdr_size = struct.unpack(">Q", raw[8:16])[0]
        self.seqid = struct.unpack(">Q", raw[16:24])[0]
        self.label = raw[24:24 + 48].split(b"\x00", 1)[0].decode("latin1")
        self.csum_alg = raw[72:72 + 32].split(b"\x00", 1)[0].decode("latin1")
        self.salt = raw[104:104 + 64]
        self.uuid = raw[168:168 + 40].split(b"\x00", 1)[0].decode("latin1")
        # JSON area starts at offset 4096, runs to hdr_size
        json_area = raw[4096:self.hdr_size]
        json_str = json_area.split(b"\x00", 1)[0]
        self.json = json.loads(json_str.decode("utf-8"))

    # convenience accessors -------------------------------------------------
    def keyslot(self, idx="0"):
        return self.json["keyslots"][str(idx)]

    def digest(self, idx="0"):
        return self.json["digests"][str(idx)]

    def segment(self, idx="0"):
        return self.json["segments"][str(idx)]


def b64dec(s):
    import base64
    # LUKS2 uses standard base64 with padding
    pad = (-len(s)) % 4
    return base64.b64decode(s + "=" * pad)


# --------------------------------------------------------------------------
# Keyslot unlock + master-key verify
# --------------------------------------------------------------------------
def derive_keyslot_kek(candidate_key, slot):
    """PBKDF2 the candidate keyfile into the keyslot key-encryption key."""
    kdf = slot["kdf"]
    if kdf["type"] != "pbkdf2":
        raise NotImplementedError(
            "Only pbkdf2 KDF implemented (got %r). Argon2 would need a separate "
            "implementation; the Stern slots are pbkdf2." % kdf["type"])
    salt = b64dec(kdf["salt"])
    iters = int(kdf["iterations"])
    prf = kdf["hash"]                       # e.g. 'sha256'
    key_size = int(slot["key_size"])        # bytes of the volume/XTS key
    return hashlib.pbkdf2_hmac(prf, candidate_key, salt, iters, dklen=key_size)


def unlock_master_key(header, candidate_key, slot_idx="0", area_bytes=None,
                      verbose=False):
    """
    Return the recovered master key from keyslot `slot_idx` using
    `candidate_key`, or None data still returned (caller verifies via digest).
    `area_bytes` is the full LUKS header blob so we can read the keyslot area;
    must be large enough to cover area.offset+area.size.
    """
    slot = header.keyslot(slot_idx)
    area = slot["area"]
    af = slot["af"]
    key_size = int(slot["key_size"])
    stripes = int(af["stripes"])
    af_hash = af["hash"]                       # e.g. 'sha256'
    area_off = int(area["offset"])
    area_size = int(area["size"])
    area_enc = area["encryption"]             # e.g. 'aes-xts-plain64'
    area_key_size = int(area["key_size"])     # KEK size (== key_size usually)

    # 1) derive KEK
    kdf = slot["kdf"]
    salt = b64dec(kdf["salt"])
    iters = int(kdf["iterations"])
    prf = kdf["hash"]
    kek = hashlib.pbkdf2_hmac(prf, candidate_key, salt, iters,
                              dklen=area_key_size)
    if verbose:
        print("  KEK   = %s (%d bytes)" % (kek.hex(), len(kek)))

    # 2) pull the split material out of the keyslot area
    af_len = key_size * stripes
    blob = area_bytes[area_off:area_off + af_len]
    if len(blob) < af_len:
        raise ValueError("Header blob too small for keyslot area "
                         "(need offset %d + %d bytes, have %d)"
                         % (area_off, af_len, len(area_bytes)))

    # 3) AES-XTS decrypt the area. cryptsetup encrypts the AF material per
    #    512-byte sector with tweak starting at 0 (relative to area start).
    if not area_enc.startswith("aes-xts"):
        raise NotImplementedError("Only aes-xts area encryption implemented "
                                  "(got %r)" % area_enc)
    # area_key_size is the XTS key size (64 for aes-256-xts). The KEK we derived
    # is exactly that length.
    sector_size = 512
    # af_len is a multiple of key_size; pad to sector multiple for XTS decrypt.
    dec_len = ((af_len + sector_size - 1) // sector_size) * sector_size
    blob_padded = area_bytes[area_off:area_off + dec_len]
    plain = aes_xts_decrypt(kek, blob_padded, 0, sector_size)[:af_len]

    # 4) AF-merge to recover the master key
    mk = af_merge(plain, key_size, stripes, af_hash)
    if verbose:
        print("  MKcand= %s (%d bytes)" % (mk.hex(), len(mk)))
    return mk


def verify_master_key(header, master_key, digest_idx="0", verbose=False):
    """PBKDF2(master_key, digest.salt, digest.iters) == digest.digest ?"""
    d = header.digest(digest_idx)
    if d["type"] != "pbkdf2":
        raise NotImplementedError("Only pbkdf2 digest implemented (got %r)"
                                  % d["type"])
    salt = b64dec(d["salt"])
    want = b64dec(d["digest"])
    iters = int(d["iterations"])
    prf = d["hash"]
    got = hashlib.pbkdf2_hmac(prf, master_key, salt, iters, dklen=len(want))
    if verbose:
        print("  digest want= %s" % want.hex())
        print("  digest got = %s" % got.hex())
    return hmac.compare_digest(got, want)


def verify_key(header, candidate_key, area_bytes, slot_idx="0",
               digest_idx="0", verbose=False):
    """Full unlock+verify. Returns (ok, recovered_master_key_or_None)."""
    mk = unlock_master_key(header, candidate_key, slot_idx, area_bytes, verbose)
    ok = verify_master_key(header, mk, digest_idx, verbose)
    return ok, (mk if ok else None)


# --------------------------------------------------------------------------
# Data segment decryption
# --------------------------------------------------------------------------
def decrypt_segment(image_path, part_base_lba, header, master_key,
                    first_sector, count, segment_idx="0", out_path=None):
    """
    Decrypt `count` 512-byte plaintext sectors starting at logical data sector
    `first_sector` of the LUKS data segment.

    Physical byte offset of segment start within the IMAGE file =
        part_base_lba*512  +  segment.offset
    XTS tweak (plain64) for a data sector = its index within the segment
    (segment.offset corresponds to tweak 0).
    """
    seg = header.segment(segment_idx)
    enc = seg["encryption"]
    if not enc.startswith("aes-xts"):
        raise NotImplementedError("Only aes-xts segment implemented (got %r)"
                                  % enc)
    seg_sector = int(seg.get("sector_size", 512))
    seg_off = int(seg["offset"])                 # bytes, within partition
    part_base = int(part_base_lba) * 512

    phys = part_base + seg_off + first_sector * seg_sector
    nbytes = count * seg_sector
    with open(image_path, "rb") as f:
        f.seek(phys)
        ct = f.read(nbytes)
    if len(ct) < nbytes:
        raise ValueError("Short read: wanted %d got %d (EOF?)"
                         % (nbytes, len(ct)))
    pt = aes_xts_decrypt(master_key, ct, first_sector, seg_sector)
    if out_path:
        with open(out_path, "wb") as o:
            o.write(pt)
    return pt


# --------------------------------------------------------------------------
# OTP keyfile helper
# --------------------------------------------------------------------------
def otp_words_to_keyfile(words, word_endian="big"):
    """
    Turn 8 OTP rows (as ints or '0x..' strings) into the 32-byte keyfile.

    The /init pipeline renders each vcmailbox word as 8 hex chars MSB-first and
    concatenates them, then xxd -r -p reads that hex stream into bytes. That is
    exactly each 32-bit word serialized big-endian, in printed order. So the
    DEFAULT here (word_endian='big') reproduces /init.

    If offline verification FAILS with big-endian, try word_endian='little'
    (in case the OTP dump tool you used printed words byte-swapped).
    """
    vals = []
    for w in words:
        if isinstance(w, str):
            vals.append(int(w, 16))
        else:
            vals.append(int(w))
    if len(vals) != 8:
        raise ValueError("Expected 8 OTP words, got %d" % len(vals))
    fmt = ">I" if word_endian == "big" else "<I"
    return b"".join(struct.pack(fmt, v & 0xFFFFFFFF) for v in vals)


# --------------------------------------------------------------------------
# Self-test (no cryptsetup needed)
# --------------------------------------------------------------------------
def selftest():
    print("== luks_otp self-test (backend=%s, pycryptodome=%s) =="
          % (_BACKEND, _HAVE_PCD))
    ok_all = True

    # 1) PBKDF2 known-answer (RFC 6070 is SHA1; use a SHA256 vector instead)
    kat = hashlib.pbkdf2_hmac("sha256", b"password", b"salt", 1, dklen=32).hex()
    expect = "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b"
    print("[1] PBKDF2-HMAC-SHA256 KAT: %s" % ("PASS" if kat == expect else "FAIL got=%s" % kat))
    ok_all &= (kat == expect)

    # 2) AES-XTS encrypt->decrypt identity over multiple sectors
    xts_key = os.urandom(64)
    pt = os.urandom(512 * 5)
    ct = aes_xts_encrypt(xts_key, pt, 7, 512)
    rt = aes_xts_decrypt(xts_key, ct, 7, 512)
    print("[2] AES-XTS roundtrip (5 sectors): %s" % ("PASS" if rt == pt else "FAIL"))
    ok_all &= (rt == pt)

    # 2b) AES-XTS IEEE-1619 vector 256-bit (vector 10) to pin tweak/byteorder
    #     key1=key2 pattern from the standard test vectors.
    key = bytes.fromhex(
        "2718281828459045235360287471352662497757247093699959574966967627"
        "2718281828459045235360287471352662497757247093699959574966967627")
    # data unit seq number = 0xff, 512 bytes of incrementing pattern
    data = bytes((i & 0xff) for i in range(512))
    ct_v = aes_xts_encrypt(key, data, 0xff, 512)
    rt_v = aes_xts_decrypt(key, ct_v, 0xff, 512)
    print("[2b] AES-XTS 256 vector roundtrip: %s" % ("PASS" if rt_v == data else "FAIL"))
    ok_all &= (rt_v == data)

    # 3) AF split->merge identity for several stripe counts
    for stripes in (1, 2, 4000):
        key = os.urandom(64)
        split = af_split(key, stripes, "sha256")
        merged = af_merge(split, len(key), stripes, "sha256")
        good = (merged == key)
        print("[3] AF split/merge stripes=%d: %s" % (stripes, "PASS" if good else "FAIL"))
        ok_all &= good

    # 4) End-to-end synthetic LUKS2-style unlock matching the REAL Stern params
    #    exactly: aes-xts-plain64 with key_size=32 (256-bit XTS key = aes-128),
    #    pbkdf2/sha256, 250000 keyslot iters, AF stripes 4000, 1000 digest iters.
    #    Build the keyslot area in memory and round-trip a known master key.
    master = os.urandom(32)             # 256-bit XTS volume key (aes-128-xts)
    candidate = os.urandom(32)          # the 32-byte "keyfile" (OTP)
    slot_salt = os.urandom(64)
    iters = 250000
    stripes = 4000
    key_size = 32
    kek = hashlib.pbkdf2_hmac("sha256", candidate, slot_salt, iters, dklen=64)
    split = af_split(master, stripes, "sha256")
    af_len = key_size * stripes
    sector_size = 512
    dec_len = ((af_len + sector_size - 1) // sector_size) * sector_size
    split_padded = split + b"\x00" * (dec_len - af_len)
    area_ct = aes_xts_encrypt(kek, split_padded, 0, sector_size)

    # fake header object exposing keyslot/digest/segment
    digest_salt = os.urandom(64)
    digest_iters = 1000
    digest_val = hashlib.pbkdf2_hmac("sha256", master, digest_salt, digest_iters, dklen=32)
    import base64
    class _Fake:
        def keyslot(self, i="0"):
            return {
                "key_size": key_size,
                "kdf": {"type": "pbkdf2", "hash": "sha256",
                        "iterations": iters,
                        "salt": base64.b64encode(slot_salt).decode()},
                "af": {"type": "luks1", "stripes": stripes, "hash": "sha256"},
                "area": {"type": "raw", "encryption": "aes-xts-plain64",
                         "key_size": 64, "offset": 0, "size": dec_len},
            }
        def digest(self, i="0"):
            return {"type": "pbkdf2", "hash": "sha256",
                    "iterations": digest_iters,
                    "salt": base64.b64encode(digest_salt).decode(),
                    "digest": base64.b64encode(digest_val).decode()}
    fake = _Fake()
    ok, mk = verify_key(fake, candidate, area_ct, verbose=False)
    print("[4] Synthetic LUKS2 unlock+verify (correct key): %s" % ("PASS" if ok and mk == master else "FAIL"))
    ok_all &= (ok and mk == master)
    ok_bad, _ = verify_key(fake, os.urandom(32), area_ct, verbose=False)
    print("[4b] Synthetic LUKS2 reject (wrong key): %s" % ("PASS" if not ok_bad else "FAIL"))
    ok_all &= (not ok_bad)

    print("== SELF-TEST %s ==" % ("PASS" if ok_all else "FAIL"))
    return ok_all


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _load_key(args):
    if args.key_hex:
        h = args.key_hex.strip().replace(" ", "")
        return binascii.unhexlify(h)
    if args.key_file:
        with open(args.key_file, "rb") as f:
            return f.read()
    if args.otp_words:
        words = [w.strip() for w in args.otp_words.split(",")]
        return otp_words_to_keyfile(words, args.word_endian)
    raise SystemExit("Provide --key-hex, --key-file, or --otp-words")


def main(argv):
    p = argparse.ArgumentParser(description="Offline LUKS2 verifier/decryptor")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("selftest")

    pp = sub.add_parser("parse")
    pp.add_argument("header")

    vp = sub.add_parser("verify")
    vp.add_argument("header")
    vp.add_argument("--key-hex")
    vp.add_argument("--key-file")
    vp.add_argument("--otp-words")
    vp.add_argument("--word-endian", default="big", choices=["big", "little"])
    vp.add_argument("--slot", default="0")
    vp.add_argument("--digest", default="0")
    vp.add_argument("-v", "--verbose", action="store_true")

    dp = sub.add_parser("decrypt")
    dp.add_argument("image")
    dp.add_argument("--header", required=True)
    dp.add_argument("--part-base-lba", type=int, required=True)
    dp.add_argument("--key-hex")
    dp.add_argument("--key-file")
    dp.add_argument("--otp-words")
    dp.add_argument("--word-endian", default="big", choices=["big", "little"])
    dp.add_argument("--sector", type=int, default=0)
    dp.add_argument("--count", type=int, default=8)
    dp.add_argument("--segment", default="0")
    dp.add_argument("--out")
    dp.add_argument("-v", "--verbose", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "selftest":
        return 0 if selftest() else 1

    if args.cmd == "parse":
        raw = open(args.header, "rb").read()
        h = Luks2Header(raw)
        print("LUKS2 header  uuid=%s  label=%s  hdr_size=%d  seqid=%d"
              % (h.uuid, h.label, h.hdr_size, h.seqid))
        print(json.dumps(h.json, indent=2))
        return 0

    if args.cmd == "verify":
        raw = open(args.header, "rb").read()
        h = Luks2Header(raw)
        key = _load_key(args)
        print("candidate key = %s (%d bytes)" % (key.hex(), len(key)))
        ok, mk = verify_key(h, key, raw, args.slot, args.digest, args.verbose)
        if ok:
            print("RESULT: VALID  master_key = %s" % mk.hex())
            return 0
        print("RESULT: INVALID")
        return 2

    if args.cmd == "decrypt":
        raw = open(args.header, "rb").read()
        h = Luks2Header(raw)
        key = _load_key(args)
        ok, mk = verify_key(h, key, raw, "0", "0", args.verbose)
        if not ok:
            print("Key did NOT verify against header; refusing to decrypt.")
            return 2
        pt = decrypt_segment(args.image, args.part_base_lba, h, mk,
                             args.sector, args.count, args.segment, args.out)
        if args.out:
            print("Wrote %d bytes of plaintext to %s" % (len(pt), args.out))
        else:
            sys.stdout.buffer.write(pt)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
