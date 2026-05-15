"""GPG operations for Spooky Pinball game files.

Beetlejuice files are GPG-signed (NOT encrypted) tar.gz archives.
The GPG packet structure is:
  [Compressed Data tag=8][OnePass Sig][Literal Data ~2GB][Signature]

Since they're only signed (not encrypted), we can extract the literal
data without any private key. We just need to strip the GPG framing.

Halloween/Ultraman .pkg files are GPG symmetric (password-encrypted).
The machine decrypts with: gpg --yes --batch --passphrase=<PASS> <file>
Passphrases found in Assembly-CSharp.dll (Unity C#) on Clonezilla images.

Strategy: Use gpg binary if available, otherwise parse GPG packets
manually to extract the literal data payload.
"""

import os
import shutil
import struct
import subprocess
import tempfile

from .games import GPG_PASSPHRASES


def _find_gpg():
    """Find gpg binary on system."""
    gpg = shutil.which("gpg")
    if gpg:
        return gpg
    # Check common Windows locations
    for path in [
        r"C:\Program Files (x86)\GnuPG\bin\gpg.exe",
        r"C:\Program Files\GnuPG\bin\gpg.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\GnuPG\bin\gpg.exe"),
    ]:
        if os.path.isfile(path):
            return path
    return None


def strip_gpg_signature(in_path, out_path, progress_cb=None):
    """Extract the literal data from a GPG-signed file.

    The .beetlejuice file is GPG-signed tar.gz. We extract the tar.gz
    payload by either:
    1. Using gpg -d (if gpg is installed)
    2. Manually parsing GPG packets to extract literal data

    Args:
        in_path: Path to .beetlejuice file.
        out_path: Path to write extracted tar.gz.
        progress_cb: Optional callback(bytes_done, total_bytes).
    """
    gpg = _find_gpg()
    if gpg:
        return _strip_with_gpg(gpg, in_path, out_path, progress_cb)
    else:
        return _strip_manual(in_path, out_path, progress_cb)


def _strip_with_gpg(gpg_path, in_path, out_path, progress_cb):
    """Use gpg binary to extract signed data."""
    file_size = os.path.getsize(in_path)

    # Create a temporary GPG home to avoid polluting user's keyring
    with tempfile.TemporaryDirectory(prefix="spooky_gpg_") as gpg_home:
        cmd = [
            gpg_path,
            "--homedir", gpg_home,
            "--batch",
            "--yes",
            "--no-default-keyring",
            "--output", out_path,
            "--decrypt",
            in_path,
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # GPG doesn't provide progress, so we monitor output file size
        if progress_cb:
            import time
            while proc.poll() is None:
                try:
                    current = os.path.getsize(out_path)
                except OSError:
                    current = 0
                progress_cb(current, file_size)
                time.sleep(0.5)

        _, stderr = proc.communicate()

        # GPG will warn about untrusted signature - that's fine
        # It should still extract the data
        if proc.returncode != 0 and not os.path.isfile(out_path):
            raise RuntimeError(
                f"gpg failed (exit {proc.returncode}): {stderr.decode(errors='replace')}")

    if progress_cb:
        progress_cb(file_size, file_size)


def _strip_manual(in_path, out_path, progress_cb):
    """Manually parse GPG packets to extract the literal data payload.

    GPG packet format for signed files:
    - Compressed Data packet (tag 8) wrapping:
      - One-Pass Signature packet (tag 4)
      - Literal Data packet (tag 11) containing actual file data
      - Signature packet (tag 2)

    The compressed data uses algorithm 1 (ZIP/DEFLATE).
    We decompress the compressed packet body, then find the literal
    data packet and extract its body.
    """
    import zlib

    file_size = os.path.getsize(in_path)
    bytes_done = 0

    with open(in_path, "rb") as infile:
        # Read first byte - should be 0xA3 (old format, tag 8, indeterminate length)
        ctb = infile.read(1)[0]
        bytes_done += 1
        if (ctb & 0x80) == 0:
            raise ValueError("Not a valid GPG file (missing bit 7)")

        old_format = (ctb & 0x40) == 0
        if old_format:
            tag = (ctb & 0x3C) >> 2
            length_type = ctb & 0x03
        else:
            tag = ctb & 0x3F
            length_type = None

        if tag != 8:
            raise ValueError(f"Expected Compressed Data packet (tag 8), got tag {tag}")

        # For old format with length_type=3, rest of file is the body
        if old_format and length_type == 3:
            # Read compression algorithm byte
            algo = infile.read(1)[0]
            bytes_done += 1
            if algo != 1:
                raise ValueError(f"Unsupported compression algorithm: {algo} (expected 1=ZIP)")

            # Rest of file is zlib/deflate compressed data
            # Use raw deflate (wbits=-15) since GPG uses raw DEFLATE for algo 1
            decompressor = zlib.decompressobj(-15)

            with open(out_path, "wb") as outfile:
                # We need to decompress and parse the inner packets
                # The decompressed stream contains: OnePassSig + LiteralData + Signature
                # We need to skip the OnePassSig header, extract LiteralData body,
                # and stop before the trailing Signature
                inner_buf = b""
                literal_started = False
                literal_remaining = 0
                skip_header = True
                chunk_size = 64 * 1024

                while True:
                    chunk = infile.read(chunk_size)
                    if not chunk:
                        break
                    bytes_done += len(chunk)

                    try:
                        decompressed = decompressor.decompress(chunk)
                    except zlib.error:
                        break

                    if not decompressed:
                        continue

                    if not literal_started:
                        inner_buf += decompressed
                        # Try to parse inner packets
                        pos = 0
                        while pos < len(inner_buf) and not literal_started:
                            if pos >= len(inner_buf):
                                break
                            inner_ctb = inner_buf[pos]
                            pos += 1
                            if (inner_ctb & 0x80) == 0:
                                break
                            inner_old = (inner_ctb & 0x40) == 0
                            if inner_old:
                                inner_tag = (inner_ctb & 0x3C) >> 2
                                inner_lt = inner_ctb & 0x03
                            else:
                                inner_tag = inner_ctb & 0x3F
                                inner_lt = None

                            # Parse packet length
                            if inner_old:
                                if inner_lt == 0:
                                    if pos >= len(inner_buf):
                                        break
                                    plen = inner_buf[pos]
                                    pos += 1
                                elif inner_lt == 1:
                                    if pos + 1 >= len(inner_buf):
                                        break
                                    plen = struct.unpack(">H", inner_buf[pos:pos+2])[0]
                                    pos += 2
                                elif inner_lt == 2:
                                    if pos + 3 >= len(inner_buf):
                                        break
                                    plen = struct.unpack(">I", inner_buf[pos:pos+4])[0]
                                    pos += 4
                                elif inner_lt == 3:
                                    plen = None  # indeterminate
                            else:
                                if pos >= len(inner_buf):
                                    break
                                first = inner_buf[pos]
                                pos += 1
                                if first < 192:
                                    plen = first
                                elif first < 224:
                                    if pos >= len(inner_buf):
                                        break
                                    second = inner_buf[pos]
                                    pos += 1
                                    plen = ((first - 192) << 8) + second + 192
                                elif first == 255:
                                    if pos + 3 >= len(inner_buf):
                                        break
                                    plen = struct.unpack(">I", inner_buf[pos:pos+4])[0]
                                    pos += 4
                                else:
                                    plen = 1 << (first & 0x1F)  # partial body

                            if inner_tag == 4:
                                # One-Pass Signature - skip it
                                if plen is not None:
                                    pos += plen
                                continue
                            elif inner_tag == 11:
                                # Literal Data packet!
                                # Header: mode(1) + name_len(1) + name(n) + date(4)
                                if pos >= len(inner_buf):
                                    break
                                mode = inner_buf[pos]
                                pos += 1
                                name_len = inner_buf[pos]
                                pos += 1
                                pos += name_len  # skip filename
                                pos += 4  # skip date

                                literal_started = True
                                literal_remaining = plen
                                if literal_remaining is not None:
                                    # Subtract header we just parsed
                                    header_size = 1 + 1 + name_len + 4
                                    literal_remaining -= header_size

                                # Write remaining buffer as file data
                                remaining_data = inner_buf[pos:]
                                if literal_remaining is not None:
                                    write_size = min(len(remaining_data), literal_remaining)
                                    outfile.write(remaining_data[:write_size])
                                    literal_remaining -= write_size
                                else:
                                    outfile.write(remaining_data)
                                break
                            else:
                                # Unknown inner packet, skip
                                if plen is not None:
                                    pos += plen
                    else:
                        # Already in literal data, write directly
                        if literal_remaining is not None:
                            write_size = min(len(decompressed), literal_remaining)
                            outfile.write(decompressed[:write_size])
                            literal_remaining -= write_size
                            if literal_remaining <= 0:
                                break
                        else:
                            outfile.write(decompressed)

                    if progress_cb:
                        progress_cb(bytes_done, file_size)

        else:
            raise ValueError(f"Unsupported GPG packet length type: {length_type}")

    if progress_cb:
        progress_cb(file_size, file_size)


def sign_beetlejuice(in_path, out_path, progress_cb=None):
    """Wrap a tar.gz in a GPG signed message to create a .beetlejuice file.

    The BJ machine uses `gpg -d <file>.gpg > <output>; echo $?` to extract
    updates. When the signature doesn't match Spooky's key, the machine
    shows "GPG SIGNATURE VERIFICATION FAILED" but allows the operator to
    proceed via an AGREE dialog. The `gpg -d` command still extracts the
    data regardless of signature validity.

    We sign with a temporary throwaway GPG key so the file is a valid GPG
    signed message that `gpg -d` can extract. If GPG is not available, we
    build the GPG packet structure manually.
    """
    gpg = _find_gpg()
    if gpg:
        try:
            return _sign_with_gpg(gpg, in_path, out_path, progress_cb)
        except Exception:
            # GPG key generation may fail (e.g. Git-bundled GPG on Windows)
            pass
    return _sign_manual(in_path, out_path, progress_cb)


def _sign_with_gpg(gpg_path, in_path, out_path, progress_cb):
    """Use gpg binary to create a signed .beetlejuice file."""
    file_size = os.path.getsize(in_path)

    with tempfile.TemporaryDirectory(prefix="spooky_gpg_sign_") as gpg_home:
        # Generate a throwaway signing key
        key_params = os.path.join(gpg_home, "key_params")
        with open(key_params, "w") as f:
            f.write(
                "Key-Type: RSA\n"
                "Key-Length: 2048\n"
                "Name-Real: Spooky Mod\n"
                "Name-Email: mod@localhost\n"
                "%no-protection\n"
                "%commit\n"
            )

        subprocess.run(
            [gpg_path, "--homedir", gpg_home, "--batch",
             "--gen-key", key_params],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        # Sign the tar.gz
        cmd = [
            gpg_path,
            "--homedir", gpg_home,
            "--batch",
            "--yes",
            "--sign",
            "--output", out_path,
            in_path,
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if progress_cb:
            import time
            while proc.poll() is None:
                try:
                    current = os.path.getsize(out_path)
                except OSError:
                    current = 0
                progress_cb(current, file_size)
                time.sleep(0.5)

        _, stderr = proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(
                f"gpg sign failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace')}")

    if progress_cb:
        progress_cb(file_size, file_size)


def _sign_manual(in_path, out_path, progress_cb):
    """Build a minimal GPG signed message without the gpg binary.

    Creates the same packet structure as `gpg --sign`:
      Compressed Data (tag 8, algo 1=ZIP) containing:
        One-Pass Signature (tag 4)
        Literal Data (tag 11) with the tar.gz payload
        Signature (tag 2)

    The signature is a valid RSA structure but won't verify against
    any real key. This is sufficient for `gpg -d` to extract the data.
    """
    import hashlib
    import zlib

    file_size = os.path.getsize(in_path)
    bytes_done = 0

    # Build the inner (uncompressed) packet stream
    # 1. One-Pass Signature packet (tag 4, old format)
    # Version 3, SHA-256 (algo 8), RSA (algo 1), 8-byte keyid, nested=0
    # version=3, sigtype=0(binary), hash=SHA256, pubkey=RSA, keyid=0, nested=1
    onepass_body = b"\x03\x00\x08\x01" + b"\x00" * 8 + b"\x01"
    onepass_packet = bytes([0xC4, len(onepass_body)]) + onepass_body

    # 2. Literal Data packet (tag 11, new format with 5-byte length)
    # Header: mode='b', filename_len=0, date=0
    literal_header = b"b\x00\x00\x00\x00\x00"
    literal_body_len = len(literal_header) + file_size

    # New format tag 11 with 5-byte length
    literal_tag = bytes([0xCB, 0xFF]) + struct.pack(">I", literal_body_len)

    # 3. Signature packet (tag 2, minimal valid structure)
    # Version 4, type 0 (binary), RSA, SHA-256
    # v4, sigtype=0(binary), pubkey=RSA, hash=SHA256,
    # hashed_subpkt_len=0, unhashed_subpkt_len=0, hash_prefix=0,
    # MPI: 16-bit dummy value
    sig_body = (b"\x04\x00\x01\x08\x00\x00\x00\x00\x00\x00"
                b"\x00\x10\xDE\xAD")
    sig_packet = bytes([0xC2, len(sig_body)]) + sig_body

    # Compress the inner stream with raw DEFLATE (GPG compression algo 1)
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)

    with open(out_path, "wb") as outfile:
        # Outer: Compressed Data packet (tag 8, old format, indeterminate length)
        outfile.write(b"\xa3")  # old format, tag 8, indeterminate length
        outfile.write(b"\x01")  # compression algo 1 (ZIP)

        # Compress and write one-pass signature
        outfile.write(compressor.compress(onepass_packet))

        # Compress and write literal data header
        outfile.write(compressor.compress(literal_tag + literal_header))

        # Stream the file data through the compressor
        chunk_size = 64 * 1024
        with open(in_path, "rb") as infile:
            while True:
                chunk = infile.read(chunk_size)
                if not chunk:
                    break
                bytes_done += len(chunk)
                compressed = compressor.compress(chunk)
                if compressed:
                    outfile.write(compressed)
                if progress_cb:
                    progress_cb(bytes_done, file_size)

        # Compress and write signature packet, then finalize
        outfile.write(compressor.compress(sig_packet))
        outfile.write(compressor.flush())

    if progress_cb:
        progress_cb(file_size, file_size)


def decrypt_gpg_symmetric(in_path, out_path, passphrase, progress_cb=None):
    """Decrypt a GPG symmetric (password-encrypted) .pkg file.

    The UM/H78 .pkg files are encrypted with:
        gpg --yes --batch --passphrase=<PASS> <file>
    which produces a decrypted tar.gz.

    Args:
        in_path: Path to .pkg file.
        out_path: Path to write decrypted tar.gz.
        passphrase: GPG symmetric passphrase.
        progress_cb: Optional callback(bytes_done, total_bytes).
    """
    gpg = _find_gpg()
    if not gpg:
        raise RuntimeError(
            "GPG (GnuPG) is required to decrypt this file but was not found. "
            "Install GPG: https://gnupg.org/download/ or via your package manager.")

    file_size = os.path.getsize(in_path)

    with tempfile.TemporaryDirectory(prefix="spooky_gpg_dec_") as gpg_home:
        cmd = [
            gpg,
            "--homedir", gpg_home,
            "--batch",
            "--yes",
            "--passphrase", passphrase,
            "--output", out_path,
            "--decrypt",
            in_path,
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if progress_cb:
            import time
            while proc.poll() is None:
                try:
                    current = os.path.getsize(out_path)
                except OSError:
                    current = 0
                progress_cb(current, file_size)
                time.sleep(0.5)

        _, stderr = proc.communicate()

        if proc.returncode != 0:
            if os.path.isfile(out_path):
                os.remove(out_path)
            raise RuntimeError(
                f"GPG decryption failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace')}")

    # Validate tar.gz magic
    with open(out_path, "rb") as f:
        magic = f.read(2)
    if magic != b"\x1f\x8b":
        raise ValueError(
            f"Decryption produced invalid tar.gz (magic: {magic.hex()}). "
            "Wrong passphrase or corrupt input.")

    if progress_cb:
        progress_cb(file_size, file_size)


def encrypt_gpg_symmetric(in_path, out_path, passphrase, progress_cb=None):
    """Encrypt a tar.gz into a GPG symmetric .pkg file.

    Reproduces what the machine expects:
        gpg --yes --batch --passphrase=<PASS> -c <file>

    Args:
        in_path: Path to tar.gz file.
        out_path: Path to write .pkg file.
        passphrase: GPG symmetric passphrase.
        progress_cb: Optional callback(bytes_done, total_bytes).
    """
    gpg = _find_gpg()
    if not gpg:
        raise RuntimeError(
            "GPG (GnuPG) is required to encrypt this file but was not found. "
            "Install GPG: https://gnupg.org/download/ or via your package manager.")

    file_size = os.path.getsize(in_path)

    with tempfile.TemporaryDirectory(prefix="spooky_gpg_enc_") as gpg_home:
        cmd = [
            gpg,
            "--homedir", gpg_home,
            "--batch",
            "--yes",
            "--passphrase", passphrase,
            "--symmetric",
            "--cipher-algo", "AES256",
            "--s2k-digest-algo", "SHA256",
            "--s2k-mode", "3",
            "--output", out_path,
            in_path,
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if progress_cb:
            import time
            while proc.poll() is None:
                try:
                    current = os.path.getsize(out_path)
                except OSError:
                    current = 0
                progress_cb(current, file_size)
                time.sleep(0.5)

        _, stderr = proc.communicate()

        if proc.returncode != 0:
            if os.path.isfile(out_path):
                os.remove(out_path)
            raise RuntimeError(
                f"GPG encryption failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace')}")

    if progress_cb:
        progress_cb(file_size, file_size)
