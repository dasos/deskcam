from __future__ import annotations

from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import requests

from models import Config, FetchedImage, is_jpeg_path


def fetch(session: requests.Session, cfg: Config) -> FetchedImage:
    if cfg.http_selection == "latest":
        return _fetch_latest(session, cfg)
    return _fetch_single(session, cfg)


def _fetch_single(session: requests.Session, cfg: Config) -> FetchedImage:
    response = session.get(cfg.http_url, timeout=cfg.timeout_seconds)
    response.raise_for_status()
    if not response.content:
        raise RuntimeError(f"Empty image from {cfg.http_url}")
    return FetchedImage(content=response.content, source_label=cfg.http_url)


def _fetch_latest(session: requests.Session, cfg: Config) -> FetchedImage:
    for url in _find_latest_urls(session, cfg):
        response = session.get(url, timeout=cfg.timeout_seconds)
        response.raise_for_status()
        if response.content:
            return FetchedImage(content=response.content, source_label=url)
    raise RuntimeError(
        f"No non-empty JPG/JPEG files found in WebDAV directory {cfg.http_directory_url}"
    )


def _normalize_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return f"{parts.scheme}://{parts.netloc}{path}"


def _find_latest_urls(session: requests.Session, cfg: Config) -> list[str]:
    body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:getlastmodified />
    <d:getcontentlength />
    <d:resourcetype />
  </d:prop>
</d:propfind>
"""
    response = session.request(
        "PROPFIND",
        cfg.http_directory_url,
        data=body,
        headers={"Depth": "1", "Content-Type": "application/xml"},
        timeout=cfg.timeout_seconds,
    )
    response.raise_for_status()

    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        raise RuntimeError(
            f"Failed to parse WebDAV directory listing from {cfg.http_directory_url}"
        ) from exc

    namespace = {"d": "DAV:"}
    directory_url = _normalize_url(cfg.http_directory_url)
    entries = []

    for entry in root.findall("d:response", namespace):
        href = entry.findtext("d:href", namespaces=namespace)
        if not href:
            continue

        file_url = urljoin(cfg.http_directory_url, href)
        if _normalize_url(file_url) == directory_url:
            continue
        if not is_jpeg_path(file_url):
            continue

        prop = entry.find("d:propstat/d:prop", namespace)
        if prop is None:
            continue

        resource_type = prop.find("d:resourcetype", namespace)
        if resource_type is not None and resource_type.find("d:collection", namespace) is not None:
            continue

        size = prop.findtext("d:getcontentlength", namespaces=namespace)
        if size and size.strip().isdigit() and int(size) == 0:
            continue

        last_modified = prop.findtext("d:getlastmodified", namespaces=namespace)
        if not last_modified:
            continue

        try:
            modified_at = parsedate_to_datetime(last_modified)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid getlastmodified value for {file_url}: {last_modified}"
            ) from exc

        entries.append((modified_at, file_url))

    entries.sort(key=lambda entry: entry[0], reverse=True)
    return [url for _, url in entries]
