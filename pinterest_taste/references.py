"""Bounded decoding for images sent to the local reference endpoint."""
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 25_000_000
IMAGE_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def decode_reference(data, content_type):
    if content_type not in IMAGE_TYPES:
        raise ValueError("Choose a JPG, PNG or WebP photo.")
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Choose a photo smaller than 10 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                if original.format != IMAGE_TYPES[content_type]:
                    raise ValueError("The file contents do not match its image type.")
                if original.width * original.height > MAX_PIXELS:
                    raise ValueError("Choose a photo with at most 25 megapixels.")
                if getattr(original, "is_animated", False):
                    raise ValueError("Choose a still photo, not an animation.")
                image = ImageOps.exif_transpose(original).convert("RGB")
                image.thumbnail((1024, 1024))
                image.info.clear()
                return image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("This photo could not be read. Try a smaller JPG, PNG or WebP file.") from exc
