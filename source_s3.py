from __future__ import annotations

from models import Config, FetchedImage, is_jpeg_path


def fetch(s3_client, cfg: Config) -> FetchedImage:
    keys = [cfg.s3_key] if cfg.s3_selection == "single" else _find_latest_keys(s3_client, cfg)
    for key in keys:
        response = s3_client.get_object(Bucket=cfg.s3_bucket, Key=key)
        body = response["Body"]
        try:
            content = body.read()
        finally:
            body.close()
        if content:
            return FetchedImage(content=content, source_label=f"s3://{cfg.s3_bucket}/{key}")
    location = cfg.s3_key if cfg.s3_selection == "single" else cfg.s3_prefix or ""
    raise RuntimeError(f"No non-empty image found in s3://{cfg.s3_bucket}/{location}")


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


def _find_latest_keys(s3_client, cfg: Config) -> list[str]:
    objects = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=cfg.s3_bucket, Prefix=cfg.s3_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/") or not is_jpeg_path(key) or obj.get("Size") == 0:
                continue
            objects.append(obj)

    objects.sort(key=lambda obj: obj["LastModified"], reverse=True)
    return [obj["Key"] for obj in objects]
