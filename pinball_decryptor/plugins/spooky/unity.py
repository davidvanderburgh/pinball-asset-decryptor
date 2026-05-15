"""Unity asset extraction for Beetlejuice (and future Unity-based Spooky games).

Beetlejuice game assets (video, audio, textures) are embedded inside
Unity asset bundles. This module uses UnityPy to extract them into
loose files organized by type.

Required files in the same directory:
- resources.assets (asset index/metadata)
- resources.resource (audio + video binary data, ~1.3GB)
- resources.assets.resS (texture binary data, ~1.9GB)
- sharedassets0.assets + sharedassets0.assets.resS (more textures/sprites)
"""

import os
import traceback

try:
    import UnityPy
    HAS_UNITYPY = True
except ImportError:
    HAS_UNITYPY = False


def _setup_fsb5():
    """Set up fsb5 with pyogg's native DLLs for Vorbis decoding.

    Monkey-patches fsb5.utils.load_lib to find libvorbis/libogg from pyogg's
    package directory, since ctypes.util.find_library doesn't find them on Windows.

    Returns True if fsb5 is ready for Vorbis decoding, False otherwise.
    """
    try:
        import fsb5.utils
    except ImportError:
        return False

    # Find pyogg's DLL directory
    pyogg_dir = None
    try:
        import pyogg
        pyogg_dir = os.path.dirname(pyogg.__file__)
    except ImportError:
        pass

    # Monkey-patch load_lib to check pyogg's directory
    if pyogg_dir:
        import ctypes
        _original_load_lib = fsb5.utils.load_lib

        def _patched_load_lib(*names):
            for name in names:
                dll_path = os.path.join(pyogg_dir, f"lib{name}.dll")
                if os.path.isfile(dll_path):
                    try:
                        return ctypes.CDLL(dll_path)
                    except OSError:
                        pass
            return _original_load_lib(*names)

        fsb5.utils.load_lib = _patched_load_lib

    # Verify Vorbis support actually works
    try:
        from fsb5 import vorbis  # noqa: F401
        return True
    except Exception:
        return False


def _decode_fsb5_audio(raw_data, name, log=None):
    """Decode FSB5 audio data using the fsb5 library.

    Args:
        raw_data: Raw FSB5 binary data.
        name: Clip name for logging.
        log: Optional log function.

    Returns:
        Tuple of (audio_bytes, extension) or (None, None) on failure.
    """
    try:
        import fsb5
        fsb = fsb5.load(raw_data)
    except Exception as e:
        if log:
            log(f"  fsb5 parse error for {name}: {e}", "warning")
        return None, None

    if not fsb.samples:
        return None, None

    sample = fsb.samples[0]
    ext = fsb.get_sample_extension()

    try:
        rebuilt = fsb.rebuild_sample(sample)
        return rebuilt, ext
    except Exception as e:
        if log:
            if not getattr(_decode_fsb5_audio, '_logged_rebuild_err', False):
                _decode_fsb5_audio._logged_rebuild_err = True
                log(f"  fsb5 rebuild error for {name}: {type(e).__name__}: {e}", "warning")
                for line in traceback.format_exc().splitlines()[-4:]:
                    log(f"    {line}", "warning")
        return None, None


def check_unitypy():
    """Check if UnityPy is available."""
    return HAS_UNITYPY


def extract_unity_assets(data_dir, output_dir, progress_cb=None, log_cb=None):
    """Extract video, audio, and texture assets from Unity data files.

    Args:
        data_dir: Directory containing Unity .assets and companion files.
        output_dir: Directory to write extracted assets into subfolders
                    (video/, audio/, textures/).
        progress_cb: Optional callback(files_done, total_files, current_name).
        log_cb: Optional callback(text, level) for logging.

    Returns:
        List of extracted file paths (relative to output_dir).
    """
    if not HAS_UNITYPY:
        raise ImportError(
            "UnityPy is required for Beetlejuice asset extraction. "
            "Install it with: pip install UnityPy")

    def log(text, level="info"):
        if log_cb:
            log_cb(text, level)

    # Set up fsb5 + pyogg for audio decoding
    has_fsb5 = _setup_fsb5()
    if has_fsb5:
        log("Using fsb5 library for audio decoding")
    else:
        log("fsb5 not available - audio will use UnityPy (may need FMOD)", "warning")

    # Find all .assets files
    assets_files = []
    for f in os.listdir(data_dir):
        if f.endswith(".assets") and not f.endswith(".resS"):
            assets_files.append(os.path.join(data_dir, f))

    if not assets_files:
        raise FileNotFoundError(f"No Unity .assets files found in {data_dir}")

    log(f"Found {len(assets_files)} asset files")

    # Create output subdirectories
    video_dir = os.path.join(output_dir, "video")
    audio_dir = os.path.join(output_dir, "audio")
    texture_dir = os.path.join(output_dir, "textures")
    os.makedirs(video_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(texture_dir, exist_ok=True)

    # First pass: count extractable objects
    total_objects = 0
    for asset_file in assets_files:
        env = UnityPy.load(asset_file)
        for obj in env.objects:
            if obj.type.name in ("VideoClip", "AudioClip", "Texture2D"):
                total_objects += 1

    log(f"Found {total_objects} extractable assets (video/audio/texture)")

    # Second pass: extract
    extracted = []
    count = 0
    audio_ok = 0
    audio_fail = 0

    for asset_file in assets_files:
        env = UnityPy.load(asset_file)
        asset_basename = os.path.basename(asset_file)
        log(f"Processing {asset_basename}...")

        for obj in env.objects:
            if obj.type.name == "VideoClip":
                try:
                    data = obj.read()
                    name = data.m_Name
                    ext_res = data.m_ExternalResources

                    if ext_res and ext_res.m_Size > 0:
                        # Read video data from companion resource file
                        res_path = os.path.join(data_dir, ext_res.m_Source)
                        if not os.path.isfile(res_path):
                            log(f"  Skip {name}: missing {ext_res.m_Source}", "warning")
                            continue

                        with open(res_path, "rb") as f:
                            f.seek(ext_res.m_Offset)
                            vdata = f.read(ext_res.m_Size)

                        # Use original extension or .webm
                        orig_ext = os.path.splitext(
                            data.m_OriginalPath)[1] if data.m_OriginalPath else ".webm"

                        # Preserve subdirectory from original path
                        rel_path = _make_video_path(data.m_OriginalPath, name, orig_ext)
                        out_path = os.path.join(video_dir, rel_path)
                        os.makedirs(os.path.dirname(out_path), exist_ok=True)

                        with open(out_path, "wb") as f:
                            f.write(vdata)

                        rel = os.path.relpath(out_path, output_dir)
                        extracted.append(rel)
                        count += 1
                        if progress_cb:
                            progress_cb(count, total_objects, f"video/{rel_path}")
                except Exception as e:
                    log(f"  Error extracting video {getattr(data, 'm_Name', '?')}: {e}", "warning")

            elif obj.type.name == "AudioClip":
                try:
                    data = obj.read()
                    name = data.m_Name
                    wrote = False

                    # Strategy 1: Use fsb5 to decode raw FSB5 data directly
                    if has_fsb5 and not wrote:
                        res = data.m_Resource
                        if res and res.m_Size > 0 and res.m_Source:
                            res_path = os.path.join(data_dir, res.m_Source)
                            if os.path.isfile(res_path):
                                with open(res_path, "rb") as rf:
                                    rf.seek(res.m_Offset)
                                    raw = rf.read(res.m_Size)
                                audio_bytes, ext = _decode_fsb5_audio(raw, name, log)
                                if audio_bytes:
                                    out_path = os.path.join(audio_dir, f"{name}.{ext}")
                                    with open(out_path, "wb") as wf:
                                        wf.write(audio_bytes)
                                    rel = os.path.relpath(out_path, output_dir)
                                    extracted.append(rel)
                                    wrote = True
                                    audio_ok += 1

                    # Strategy 2: Try UnityPy's data.samples (needs FMOD)
                    if not wrote:
                        try:
                            samples = data.samples
                            if samples:
                                for sample_name, sample_data in samples.items():
                                    _, dot_ext = os.path.splitext(sample_name)
                                    ext = dot_ext.lstrip(".") if dot_ext else "wav"
                                    out_path = os.path.join(audio_dir, f"{name}.{ext}")
                                    with open(out_path, "wb") as f:
                                        f.write(sample_data)
                                    rel = os.path.relpath(out_path, output_dir)
                                    extracted.append(rel)
                                    wrote = True
                                    audio_ok += 1
                                    break
                        except Exception:
                            pass

                    # Strategy 3: Save raw FSB5 data
                    if not wrote:
                        res = data.m_Resource
                        if res and res.m_Size > 0 and res.m_Source:
                            res_path = os.path.join(data_dir, res.m_Source)
                            if os.path.isfile(res_path):
                                with open(res_path, "rb") as rf:
                                    rf.seek(res.m_Offset)
                                    raw = rf.read(res.m_Size)
                                out_path = os.path.join(audio_dir, f"{name}.fsb")
                                with open(out_path, "wb") as wf:
                                    wf.write(raw)
                                rel = os.path.relpath(out_path, output_dir)
                                extracted.append(rel)
                                wrote = True
                                audio_fail += 1

                    if not wrote:
                        audio_fail += 1

                    count += 1
                    if progress_cb:
                        progress_cb(count, total_objects, f"audio/{name}")
                except Exception as e:
                    clip_name = getattr(data, 'm_Name', '?') if 'data' in dir() else '?'
                    log(f"  Error extracting audio {clip_name}: {type(e).__name__}: {e}", "warning")
                    count += 1
                    audio_fail += 1

            elif obj.type.name == "Texture2D":
                try:
                    data = obj.read()
                    name = data.m_Name
                    if data.m_Width > 0 and data.m_Height > 0:
                        img = data.image
                        out_path = os.path.join(texture_dir, f"{name}.png")
                        img.save(out_path)

                        rel = os.path.relpath(out_path, output_dir)
                        extracted.append(rel)
                    count += 1
                    if progress_cb:
                        progress_cb(count, total_objects, f"textures/{name}")
                except Exception as e:
                    count += 1

    if audio_ok > 0 or audio_fail > 0:
        log(f"Audio: {audio_ok} decoded, {audio_fail} saved as raw FSB5", "success" if audio_fail == 0 else "warning")
    log(f"Extracted {len(extracted)} assets total", "success")

    # Clean up empty subdirectories (and parent) if nothing was extracted
    for d in (video_dir, audio_dir, texture_dir):
        try:
            os.rmdir(d)  # only removes if empty
        except OSError:
            pass
    try:
        os.rmdir(output_dir)  # only removes if empty
    except OSError:
        pass

    return extracted


def _make_video_path(original_path, name, ext):
    """Create a relative path for video files preserving original subdirs."""
    if original_path:
        # Original path like "Assets/Resources/video/ghosts/feet_0_intro.webm"
        # Extract the subpath after "video/"
        parts = original_path.replace("\\", "/").split("/")
        try:
            vid_idx = parts.index("video")
            subpath = "/".join(parts[vid_idx + 1:])
            return subpath
        except ValueError:
            pass
        # Try after "Resources/"
        try:
            res_idx = parts.index("Resources")
            subpath = "/".join(parts[res_idx + 1:])
            return subpath
        except ValueError:
            pass
    return f"{name}{ext}"
