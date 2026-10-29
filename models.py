from __future__ import annotations

import struct
import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image


@dataclass
class Config:
    source_type: str
    interval_seconds: int
    timeout_seconds: float
    # HTTP / WebDAV
    http_selection: str
    http_url: str | None
    http_directory_url: str | None
    # S3
    s3_bucket: str | None
    s3_region: str | None
    s3_endpoint_url: str | None
    s3_selection: str
    s3_key: str | None
    s3_prefix: str | None
    # FTPS
    ftps_host: str | None
    ftps_port: int
    ftps_username: str | None
    ftps_password: str | None
    ftps_selection: str
    ftps_path: str | None
    ftps_directory: str | None


@dataclass
class FetchedImage:
    content: bytes
    source_label: str


def is_jpeg_path(path: str) -> bool:
    lower = path.lower()
    return lower.endswith(".jpg") or lower.endswith(".jpeg")


def is_valid_image(content: bytes) -> bool:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            # verify() checks file structure; reopening and loading checks pixel decoding.
            with Image.open(BytesIO(content)) as image:
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image.load()
    except (
        OSError, ValueError, SyntaxError, EOFError, struct.error,
        Image.DecompressionBombError, Image.DecompressionBombWarning,
    ):
        return False
    return True
