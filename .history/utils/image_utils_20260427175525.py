import base64
import logging
import uuid
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from PIL import Image

LOGGER = logging.getLogger(__name__)


class ImageDecodeError(ValueError):
    """Raised when input image data cannot be decoded into a file."""


_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
}


_FORMAT_TO_EXT = {
    "png": ".png",
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "webp": ".webp",
    "bmp": ".bmp",
    "gif": ".gif",
}


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _resolve_extension(raw_bytes: bytes, mime_hint: Optional[str] = None) -> str:
    if mime_hint:
        mime = mime_hint.split(";")[0].strip().lower()
        if mime in _MIME_TO_EXT:
            return _MIME_TO_EXT[mime]

    try:
        with Image.open(BytesIO(raw_bytes)) as image:
            image_format = (image.format or "").lower()
            if image_format in _FORMAT_TO_EXT:
                return _FORMAT_TO_EXT[image_format]
    except Exception:
        LOGGER.debug("Could not infer extension from image bytes, defaulting to .png")

    return ".png"


def decode_base64_to_file(image_b64: str, target_dir: str, prefix: str = "input") -> str:
    if not isinstance(image_b64, str) or not image_b64.strip():
        raise ImageDecodeError("Image must be a non-empty base64 string.")

    mime_hint = None
    payload = image_b64.strip()

    if payload.startswith("data:"):
        try:
            header, payload = payload.split(",", 1)
        except ValueError as exc:
            raise ImageDecodeError("Malformed data URI image payload.") from exc

        if ";base64" not in header:
            raise ImageDecodeError("Data URI must contain ';base64'.")
        mime_hint = header[5:]

    try:
        raw_bytes = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ImageDecodeError("Invalid base64 image payload.") from exc

    extension = _resolve_extension(raw_bytes, mime_hint=mime_hint)
    output_dir = Path(target_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{prefix}_{uuid.uuid4().hex}{extension}"
    output_path.write_bytes(raw_bytes)

    return str(output_path)


def download_image_to_file(image_url: str, target_dir: str, prefix: str = "input") -> str:
    if not isinstance(image_url, str) or not _is_url(image_url):
        raise ImageDecodeError("Image URL must be an absolute http or https URL.")

    try:
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ImageDecodeError(f"Failed to download image from URL: {exc}") from exc

    raw_bytes = response.content
    if not raw_bytes:
        raise ImageDecodeError("Downloaded image payload was empty.")

    extension = _resolve_extension(raw_bytes, mime_hint=response.headers.get("Content-Type"))
    output_dir = Path(target_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{prefix}_{uuid.uuid4().hex}{extension}"
    output_path.write_bytes(raw_bytes)

    return str(output_path)


def decode_image_input(image_value: str, target_dir: str, prefix: str = "input") -> str:
    if not isinstance(image_value, str) or not image_value.strip():
        raise ImageDecodeError("Image must be a non-empty string (base64 or URL).")

    value = image_value.strip()
    if _is_url(value):
        return download_image_to_file(value, target_dir=target_dir, prefix=prefix)

    return decode_base64_to_file(value, target_dir=target_dir, prefix=prefix)


def encode_image_to_base64(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    raw_bytes = path.read_bytes()
    if not raw_bytes:
        raise ValueError(f"Image file is empty: {image_path}")

    return base64.b64encode(raw_bytes).decode("ascii")
