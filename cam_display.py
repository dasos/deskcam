#!/usr/bin/env python3
"""Fullscreen webcam image viewer for Raspberry Pi framebuffer.

- Downloads a single image URL over HTTP(S)
- Polls at a configurable interval
- Updates display only when image bytes change
- Displays via `fbi` for robust framebuffer output on SSH-only setups
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from dataclasses import dataclass

import requests


@dataclass
class Config:
    url: str
    interval_seconds: int
    timeout_seconds: float
    transition_seconds: float


def parse_args() -> Config:
    parser = argparse.ArgumentParser(
        description="Display a webcam image fullscreen and refresh when it changes."
    )
    parser.add_argument("url", help="HTTP(S) URL of the webcam image")
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Poll interval in seconds (default: 300 = 5 minutes)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--transition",
        type=float,
        default=0.0,
        help="Unused with fbi backend; kept for CLI compatibility",
    )

    args = parser.parse_args()
    if args.interval < 5:
        parser.error("--interval must be at least 5 seconds")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.transition < 0:
        parser.error("--transition cannot be negative")

    return Config(
        url=args.url,
        interval_seconds=args.interval,
        timeout_seconds=args.timeout,
        transition_seconds=args.transition,
    )


def ensure_fbi_available() -> None:
    result = subprocess.run(["which", "fbi"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("fbi not found. Install with: sudo apt install -y fbi")


def fetch_image_bytes(session: requests.Session, cfg: Config) -> bytes:
    response = session.get(cfg.url, timeout=cfg.timeout_seconds)
    response.raise_for_status()
    return response.content


def write_image(path: str, raw: bytes) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "wb") as fh:
        fh.write(raw)
    os.replace(tmp_path, path)


def display_with_fbi(path: str) -> None:
    # Ensure only one fbi process from this service remains active.
    subprocess.run(
        ["pkill", "-x", "fbi"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    cmd = [
        "fbi",
        "-T",
        "1",
        "-d",
        "/dev/fb0",
        "-a",
        "--noverbose",
        "-1",
        "-t",
        "1",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(stderr or f"fbi exited with code {result.returncode}")


def run(cfg: Config) -> int:
    ensure_fbi_available()

    if cfg.transition_seconds > 0:
        print("Note: --transition is ignored by the fbi backend")

    image_dir = "/tmp/deskcam"
    image_path = os.path.join(image_dir, "current.img")
    os.makedirs(image_dir, exist_ok=True)

    session = requests.Session()
    last_hash: str | None = None

    try:
        while True:
            try:
                raw = fetch_image_bytes(session, cfg)
                image_hash = hashlib.sha256(raw).hexdigest()

                if image_hash != last_hash:
                    write_image(image_path, raw)
                    display_with_fbi(image_path)
                    if last_hash is None:
                        print("Initial image displayed")
                    else:
                        print("Image changed, display updated")
                    last_hash = image_hash
                else:
                    print("No image change")
            except Exception as exc:
                print(f"Fetch/display error: {exc}", file=sys.stderr)

            sleep_until = time.monotonic() + cfg.interval_seconds
            while True:
                remaining = sleep_until - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.25, remaining))
    except KeyboardInterrupt:
        return 0
    finally:
        session.close()


def main() -> int:
    cfg = parse_args()
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
