"""Bounded still-photo decoding; only newly encoded pixels leave this module."""
from io import BytesIO
import warnings

from PIL import Image, ImageFile, ImageOps


MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000


class PhotoImageError(ValueError):
    """The upload is not an acceptable single, bounded JPEG still."""


def _single_jpeg(data: bytes) -> None:
    """Require one complete JPEG, not MPO, concatenated images or trailing data.

    Pillow deliberately permits trailing data. Walk JPEG marker lengths so an
    EXIF thumbnail inside an APP segment is not mistaken for another image.
    Entropy-coded scans escape FF bytes; progressive JPEGs have several scans.
    Pixel correctness is separately checked by the actual Pillow decoder.
    """
    if not data.startswith(b"\xff\xd8"):
        raise PhotoImageError("Expected a JPEG still")
    cursor, scanning, saw_scan, scan_has_data = 2, False, False, False
    while cursor < len(data):
        if scanning:
            marker_start = data.find(b"\xff", cursor)
            scan_has_data = scan_has_data or marker_start > cursor
            cursor = marker_start
            if cursor < 0:
                break
        elif data[cursor] != 0xFF:
            break
        cursor += 1
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            break
        marker = data[cursor]
        cursor += 1
        if scanning and (marker == 0 or 0xD0 <= marker <= 0xD7):
            scan_has_data = scan_has_data or marker == 0
            continue
        if scanning and not scan_has_data:
            break
        scanning = False
        if marker == 0xD9:
            if saw_scan and cursor == len(data):
                return
            break
        if marker in (0, 0xD8) or 0xD0 <= marker <= 0xD7:
            break
        if marker == 0x01:  # Standalone TEM marker has no length field.
            continue
        if cursor + 2 > len(data):
            break
        length = int.from_bytes(data[cursor:cursor + 2], "big")
        if length < 2 or cursor + length > len(data):
            break
        cursor += length
        if marker == 0xDA:
            scanning, saw_scan, scan_has_data = True, True, False
    raise PhotoImageError("Expected one complete JPEG still")


def normalize_jpeg(data: bytes, content_type: str) -> bytes:
    """Decode one JPEG, orient it, and return an RGB JPEG without source metadata.

    MIME parameters and case are accepted, but the media type must be
    image/jpeg. Input/output are each limited to 5 MiB and decoded dimensions
    to 16 million pixels. The function never changes Pillow's global limits.
    """
    if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "image/jpeg":
        raise PhotoImageError("Content-Type must be image/jpeg")
    if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE_BYTES:
        raise PhotoImageError("JPEG upload must be between 1 byte and 5 MiB")
    _single_jpeg(data)
    # A process-wide opt-in to truncated decoding must not weaken this boundary.
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise PhotoImageError("Strict JPEG decoding is unavailable")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=["JPEG"]) as source:
                if source.format != "JPEG" or getattr(source, "n_frames", 1) != 1:
                    raise PhotoImageError("Expected a single JPEG still")
                width, height = source.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise PhotoImageError("JPEG exceeds the 16 million pixel limit")
                source.load()  # verify() alone does not decode JPEG pixel data.
                with ImageOps.exif_transpose(source) as oriented:
                    with oriented.convert("RGB") as pixels:
                        # A fresh image prevents EXIF/XMP/ICC/comment propagation.
                        with Image.new("RGB", pixels.size) as clean:
                            clean.paste(pixels)
                            output = BytesIO()
                            clean.save(output, format="JPEG", quality=85,
                                       exif=b"", icc_profile=None, comment=b"")
        normalized = output.getvalue()
    except PhotoImageError:
        raise
    except (OSError, ValueError, SyntaxError, TypeError,
            Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        # Do not expose attacker-controlled metadata or decoder details upstream.
        raise PhotoImageError("Invalid JPEG still") from exc
    if len(normalized) > MAX_IMAGE_BYTES:
        raise PhotoImageError("Normalized JPEG exceeds 5 MiB")
    return normalized
