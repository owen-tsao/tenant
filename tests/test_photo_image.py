"""Real JPEG decoding/normalization checks; no camera, device or network IO."""
from io import BytesIO
import random
import unittest
from unittest.mock import patch

from PIL import Image, ImageFile

from brain.core.photo_image import MAX_IMAGE_BYTES, PhotoImageError, normalize_jpeg


def jpeg(mode="RGB", size=(48, 32), **options):
    color = 120 if mode == "L" else (180, 20, 30) if mode == "RGB" else (0, 200, 50, 0)
    with Image.new(mode, size, color) as image:
        output = BytesIO()
        image.save(output, "JPEG", **options)
        return output.getvalue()


def with_dimensions(data, width, height):
    """Patch the SOF dimensions, without allocating a gigantic decoded fixture."""
    marker = data.index(b"\xff\xc0")
    return (data[:marker + 5] + height.to_bytes(2, "big") +
            width.to_bytes(2, "big") + data[marker + 9:])


class PhotoImageTests(unittest.TestCase):
    def test_real_baseline_and_progressive_jpeg_decode_as_rgb(self):
        for mode in ("RGB", "L", "CMYK"):
            for progressive in (False, True):
                with self.subTest(mode=mode, progressive=progressive):
                    result = normalize_jpeg(jpeg(mode, progressive=progressive), " IMAGE/JPEG ; anything=value")
                    with Image.open(BytesIO(result)) as image:
                        image.load()
                        self.assertEqual((image.format, image.mode, image.size), ("JPEG", "RGB", (48, 32)))
                    self.assertLessEqual(len(result), MAX_IMAGE_BYTES)

    def test_declared_mime_cannot_enable_other_formats(self):
        for content_type in (None, "image/png", "image/jpg", "", "text/plain"):
            with self.subTest(content_type=content_type), self.assertRaises(PhotoImageError):
                normalize_jpeg(jpeg(), content_type)
        output = BytesIO()
        Image.new("RGB", (4, 4)).save(output, "PNG")
        with self.assertRaises(PhotoImageError):
            normalize_jpeg(output.getvalue(), "image/jpeg")

    def test_empty_nonbytes_and_oversize_upload_rejected(self):
        for data in (b"", bytearray(jpeg()), None, b"x" * (MAX_IMAGE_BYTES + 1)):
            with self.subTest(kind=type(data)), self.assertRaises(PhotoImageError):
                normalize_jpeg(data, "image/jpeg")

    def test_invalid_truncated_and_corrupt_lengths_rejected(self):
        data = jpeg()
        for bad in (b"not a picture", b"\xff\xd8\xff\xd9", data[:-2], data[:100],
                    data[:4] + b"\xff\xff" + data[6:]):
            with self.subTest(length=len(bad)), self.assertRaises(PhotoImageError):
                normalize_jpeg(bad, "image/jpeg")
        # A scan with no entropy is invalid even if the decoder repairs it.
        sos = data.index(b"\xff\xda")
        scan = sos + 2 + int.from_bytes(data[sos + 2:sos + 4], "big")
        with self.assertRaises(PhotoImageError):
            normalize_jpeg(data[:scan] + b"\xff\xd9", "image/jpeg")

    def test_valid_marker_envelope_still_requires_real_pixel_decode(self):
        data = jpeg()
        table = data.index(b"\xff\xc4")
        # Segment lengths remain intact, but the Huffman table ID is invalid.
        bad = data[:table + 4] + b"\xff" + data[table + 5:]
        with self.assertRaises(PhotoImageError) as caught:
            normalize_jpeg(bad, "image/jpeg")
        self.assertIsInstance(caught.exception.__cause__, OSError)

    def test_concatenated_images_and_trailing_data_rejected(self):
        data = jpeg()
        for bad in (data + data, data + b"\n", data + b"private trailing metadata"):
            with self.subTest(length=len(bad)), self.assertRaises(PhotoImageError):
                normalize_jpeg(bad, "image/jpeg")

    def test_mpo_multiframe_rejected(self):
        output = BytesIO()
        with Image.new("RGB", (4, 4), "red") as first, Image.new("RGB", (4, 4), "blue") as second:
            first.save(output, "MPO", save_all=True, append_images=[second])
        with self.assertRaises(PhotoImageError):
            normalize_jpeg(output.getvalue(), "image/jpeg")

    def test_exif_orientation_applied_and_all_source_metadata_dropped(self):
        exif = Image.Exif()
        exif[274] = 6  # Clockwise 90 degrees.
        exif[315] = "private author"
        exif[270] = "private description"
        data = jpeg(exif=exif, icc_profile=b"private ICC", comment=b"private comment",
                    xmp=b"<xmp>private XMP</xmp>")
        result = normalize_jpeg(data, "image/jpeg")
        with Image.open(BytesIO(result)) as image:
            image.load()
            self.assertEqual(image.size, (32, 48))
            self.assertEqual(dict(image.getexif()), {})
            for key in ("exif", "icc_profile", "comment", "xmp"):
                self.assertNotIn(key, image.info)
        for secret in (b"private author", b"private description", b"private ICC", b"private comment", b"private XMP"):
            self.assertNotIn(secret, result)

    def test_embedded_thumbnail_marker_is_not_an_extra_image(self):
        data = jpeg()
        # Legal opaque APP2 payload containing a complete thumbnail JPEG.
        payload = b"thumbnail\0" + jpeg(size=(2, 2))
        segment = b"\xff\xe2" + (len(payload) + 2).to_bytes(2, "big") + payload
        result = normalize_jpeg(data[:2] + segment + data[2:], "image/jpeg")
        self.assertNotIn(b"thumbnail", result)

    def test_orientation_rotates_pixels_in_correct_direction(self):
        with Image.new("RGB", (64, 32), "red") as image:
            image.paste("blue", (32, 0, 64, 32))
            exif = Image.Exif()
            exif[274] = 6
            output = BytesIO()
            image.save(output, "JPEG", exif=exif)
        result = normalize_jpeg(output.getvalue(), "image/jpeg")
        with Image.open(BytesIO(result)) as image:
            top = image.getpixel((16, 8))
            bottom = image.getpixel((16, 56))
            self.assertGreater(top[0], 200)
            self.assertLess(top[2], 30)
            self.assertGreater(bottom[2], 200)
            self.assertLess(bottom[0], 30)

    def test_pixel_limit_and_zero_dimensions_rejected_before_decode(self):
        for width, height in ((4001, 4000), (65535, 65535), (0, 32), (48, 0)):
            with self.subTest(width=width, height=height), self.assertRaises(PhotoImageError):
                normalize_jpeg(with_dimensions(jpeg(), width, height), "image/jpeg")

    def test_exact_pixel_limit_is_allowed(self):
        result = normalize_jpeg(jpeg(size=(4000, 4000)), "image/jpeg")
        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.size, (4000, 4000))

    def test_pillow_bomb_warning_is_error_without_global_limit_mutation(self):
        with patch.object(Image, "MAX_IMAGE_PIXELS", 1000):
            with self.assertRaises(PhotoImageError):
                normalize_jpeg(jpeg(), "image/jpeg")
            self.assertEqual(Image.MAX_IMAGE_PIXELS, 1000)

    def test_permissive_global_truncated_decoder_fails_closed(self):
        with patch.object(ImageFile, "LOAD_TRUNCATED_IMAGES", True):
            with self.assertRaises(PhotoImageError):
                normalize_jpeg(jpeg(), "image/jpeg")
            self.assertTrue(ImageFile.LOAD_TRUNCATED_IMAGES)

    def test_reencoded_output_limit_enforced(self):
        rng = random.Random(7)
        with Image.frombytes("RGB", (128, 128), rng.randbytes(128 * 128 * 3)) as image:
            output = BytesIO()
            image.save(output, "JPEG", quality=5)
        data = output.getvalue()
        # Lossy re-encoding can exceed a small source, so check the result too.
        with patch("brain.core.photo_image.MAX_IMAGE_BYTES", len(data) + 1):
            with self.assertRaisesRegex(PhotoImageError, "Normalized JPEG"):
                normalize_jpeg(data, "image/jpeg")


if __name__ == "__main__":
    unittest.main()
