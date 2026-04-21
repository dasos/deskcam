from __future__ import annotations

from models import Config, FetchedImage, is_jpeg_path


def fetch(s3_client, cfg: Config) -> FetchedImage:
    key = cfg.s3_key if cfg.s3_selection == "single" else _find_latest_key(s3_client, cfg)
    response = s3_client.get_object(Bucket=cfg.s3_bucket, Key=key)
    body = response["Body"]
    try:
        return FetchedImage(
            content=body.read(),
            source_label=f"s3://{cfg.s3_bucket}/{key}",
        )
    finally:
        body.close()


def create_client(cfg: Config):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is not installed. Install dependencies with: python3 -m pip install -r requirements.txt"
        ) from exc

    kwargs = {}
    if cfg.s3_region:
        kwargs["region_name"] = cfg.s3_region
    if cfg.s3_endpoint_url:
        kwargs["endpoint_url"] = cfg.s3_endpoint_url
    return boto3.client("s3", **kwargs)


def _find_latest_key(s3_client, cfg: Config) -> str:
    latest_obj = None
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=cfg.s3_bucket, Prefix=cfg.s3_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/") or not is_jpeg_path(key):
                continue
            if latest_obj is None or obj["LastModified"] > latest_obj["LastModified"]:
                latest_obj = obj

    if latest_obj is None:
        raise RuntimeError(
            f"No JPG/JPEG objects found in s3://{cfg.s3_bucket}/{cfg.s3_prefix or ''}"
        )
    return latest_obj["Key"]
