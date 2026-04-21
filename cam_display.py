#!/usr/bin/env python3
"""Fullscreen webcam image viewer for Raspberry Pi framebuffer.

- Downloads a single image URL over HTTP(S)
- Downloads an object from S3-compatible storage
- Downloads an image from an FTPS server
- Polls at a configurable interval
- Updates display only when image bytes change
- Displays via `fbi` for robust framebuffer output on SSH-only setups
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time

import requests

import source_ftps
import source_http
import source_s3
from models import Config


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def env_value_allow_empty(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip()


def env_int(name: str, default: int) -> int:
    value = env_value(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def env_float(name: str, default: float) -> float:
    value = env_value(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def load_env_file(path: str) -> None:
    if not path or not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ.setdefault(key, value)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> Config:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--env-file",
        default=os.environ.get("DESKCAM_ENV_FILE", ".env"),
        help="Optional env file to load before parsing options (default: .env if present)",
    )
    pre_args, remaining = pre_parser.parse_known_args()
    load_env_file(pre_args.env_file)

    try:
        interval_default = env_int("DESKCAM_INTERVAL", 300)
        timeout_default = env_float("DESKCAM_TIMEOUT", 10.0)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    parser = argparse.ArgumentParser(
        description="Display a webcam image fullscreen and refresh when it changes.",
        parents=[pre_parser],
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Legacy HTTP(S) webcam image URL. Prefer --http-url or DESKCAM_HTTP_URL.",
    )
    parser.add_argument(
        "--source",
        choices=("http", "s3", "ftps"),
        default=None,
        help="Image source backend (env: DESKCAM_SOURCE)",
    )
    parser.add_argument(
        "--http-url",
        default=None,
        help="HTTP(S) image URL for WebDAV-style fetches (env: DESKCAM_HTTP_URL)",
    )
    parser.add_argument(
        "--http-selection",
        choices=("single", "latest"),
        default=env_value("DESKCAM_HTTP_SELECTION") or "single",
        help="Use a fixed HTTP/WebDAV file or the newest file in a WebDAV directory (env: DESKCAM_HTTP_SELECTION)",
    )
    parser.add_argument(
        "--http-directory-url",
        default=env_value("DESKCAM_HTTP_DIRECTORY_URL"),
        help="WebDAV directory URL when --http-selection=latest (env: DESKCAM_HTTP_DIRECTORY_URL)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=interval_default,
        help="Poll interval in seconds (default: 300 = 5 minutes)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=timeout_default,
        help="HTTP request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--s3-bucket",
        default=env_value("DESKCAM_S3_BUCKET"),
        help="S3 bucket name (env: DESKCAM_S3_BUCKET)",
    )
    parser.add_argument(
        "--s3-region",
        default=env_value("DESKCAM_S3_REGION"),
        help="S3 region name (env: DESKCAM_S3_REGION)",
    )
    parser.add_argument(
        "--s3-endpoint-url",
        default=env_value("DESKCAM_S3_ENDPOINT_URL"),
        help="Optional S3-compatible endpoint URL (env: DESKCAM_S3_ENDPOINT_URL)",
    )
    parser.add_argument(
        "--s3-selection",
        choices=("single", "latest"),
        default=env_value("DESKCAM_S3_SELECTION") or "single",
        help="Use a fixed key or the newest object under a prefix (env: DESKCAM_S3_SELECTION)",
    )
    parser.add_argument(
        "--s3-key",
        default=env_value("DESKCAM_S3_KEY"),
        help="Exact S3 object key when --s3-selection=single (env: DESKCAM_S3_KEY)",
    )
    parser.add_argument(
        "--s3-prefix",
        default=env_value_allow_empty("DESKCAM_S3_PREFIX"),
        help="Object prefix when --s3-selection=latest (env: DESKCAM_S3_PREFIX)",
    )
    parser.add_argument(
        "--ftps-host",
        default=env_value("DESKCAM_FTPS_HOST"),
        help="FTPS server hostname (env: DESKCAM_FTPS_HOST)",
    )
    parser.add_argument(
        "--ftps-port",
        type=int,
        default=env_int("DESKCAM_FTPS_PORT", 21),
        help="FTPS server port (default: 21, env: DESKCAM_FTPS_PORT)",
    )
    parser.add_argument(
        "--ftps-username",
        default=env_value("DESKCAM_FTPS_USERNAME"),
        help="FTPS username (env: DESKCAM_FTPS_USERNAME)",
    )
    parser.add_argument(
        "--ftps-password",
        default=env_value("DESKCAM_FTPS_PASSWORD"),
        help="FTPS password (env: DESKCAM_FTPS_PASSWORD)",
    )
    parser.add_argument(
        "--ftps-selection",
        choices=("single", "latest"),
        default=env_value("DESKCAM_FTPS_SELECTION") or "single",
        help="Use a fixed file or the newest JPEG in a directory (env: DESKCAM_FTPS_SELECTION)",
    )
    parser.add_argument(
        "--ftps-path",
        default=env_value("DESKCAM_FTPS_PATH"),
        help="Exact file path when --ftps-selection=single (env: DESKCAM_FTPS_PATH)",
    )
    parser.add_argument(
        "--ftps-directory",
        default=env_value("DESKCAM_FTPS_DIRECTORY"),
        help="Directory path when --ftps-selection=latest (env: DESKCAM_FTPS_DIRECTORY)",
    )

    args = parser.parse_args(remaining)
    if args.interval < 5:
        parser.error("--interval must be at least 5 seconds")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")

    source_type = args.source or env_value("DESKCAM_SOURCE")
    if source_type is None:
        if args.http_url or args.url:
            source_type = "http"
        elif args.s3_bucket:
            source_type = "s3"
        elif args.ftps_host:
            source_type = "ftps"
        else:
            source_type = "http"

    http_url = args.http_url or args.url or env_value("DESKCAM_HTTP_URL")
    http_directory_url = args.http_directory_url

    if source_type == "http":
        if args.http_selection == "single" and not http_url:
            parser.error(
                "HTTP single-file mode requires a URL via the positional argument, --http-url, or DESKCAM_HTTP_URL"
            )
        if args.http_selection == "latest" and not http_directory_url:
            parser.error(
                "HTTP latest-file mode requires --http-directory-url or DESKCAM_HTTP_DIRECTORY_URL"
            )
    elif source_type == "s3":
        if args.url:
            parser.error("Positional URL cannot be used with --source s3")
        if not args.s3_bucket:
            parser.error("S3 source requires --s3-bucket or DESKCAM_S3_BUCKET")
        if args.s3_selection == "single" and not args.s3_key:
            parser.error("S3 single-object mode requires --s3-key or DESKCAM_S3_KEY")
        if args.s3_selection == "latest" and args.s3_prefix is None:
            parser.error("S3 latest-object mode requires --s3-prefix or DESKCAM_S3_PREFIX")
    elif source_type == "ftps":
        if not args.ftps_host:
            parser.error("FTPS source requires --ftps-host or DESKCAM_FTPS_HOST")
        if not args.ftps_username:
            parser.error("FTPS source requires --ftps-username or DESKCAM_FTPS_USERNAME")
        if not args.ftps_password:
            parser.error("FTPS source requires --ftps-password or DESKCAM_FTPS_PASSWORD")
        if args.ftps_selection == "single" and not args.ftps_path:
            parser.error("FTPS single-file mode requires --ftps-path or DESKCAM_FTPS_PATH")
        if args.ftps_selection == "latest" and not args.ftps_directory:
            parser.error("FTPS latest-file mode requires --ftps-directory or DESKCAM_FTPS_DIRECTORY")

    return Config(
        source_type=source_type,
        interval_seconds=args.interval,
        timeout_seconds=args.timeout,
        http_selection=args.http_selection,
        http_url=http_url,
        http_directory_url=http_directory_url,
        s3_bucket=args.s3_bucket,
        s3_region=args.s3_region,
        s3_endpoint_url=args.s3_endpoint_url,
        s3_selection=args.s3_selection,
        s3_key=args.s3_key,
        s3_prefix=args.s3_prefix,
        ftps_host=args.ftps_host,
        ftps_port=args.ftps_port,
        ftps_username=args.ftps_username,
        ftps_password=args.ftps_password,
        ftps_selection=args.ftps_selection,
        ftps_path=args.ftps_path,
        ftps_directory=args.ftps_directory,
    )


# ---------------------------------------------------------------------------
# Display (fbi)
# ---------------------------------------------------------------------------

def ensure_fbi_available() -> None:
    if shutil.which("fbi") is None:
        raise RuntimeError("fbi not found. Install with: sudo apt install -y fbi")


def write_image(path: str, raw: bytes) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "wb") as fh:
        fh.write(raw)
    os.replace(tmp_path, path)


def start_fbi(path: str) -> subprocess.Popen[str]:
    cmd = ["fbi", "-d", "/dev/fb0", "-a", "--noverbose", path]
    tty = os.environ.get("DESKCAM_FBI_TTY", "").strip()
    if tty:
        cmd[1:1] = ["-T", tty]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def stop_fbi(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(cfg: Config) -> int:
    ensure_fbi_available()

    image_dir = "/tmp/deskcam"
    image_path = os.path.join(image_dir, "current.img")
    os.makedirs(image_dir, exist_ok=True)

    session = requests.Session() if cfg.source_type == "http" else None
    s3_client = source_s3.create_client(cfg) if cfg.source_type == "s3" else None
    last_hash: str | None = None
    fbi_proc: subprocess.Popen[str] | None = None

    try:
        while True:
            try:
                if cfg.source_type == "http":
                    fetched = source_http.fetch(session, cfg)
                elif cfg.source_type == "s3":
                    fetched = source_s3.fetch(s3_client, cfg)
                else:
                    fetched = source_ftps.fetch(cfg)

                image_hash = hashlib.sha256(fetched.content).hexdigest()

                if image_hash != last_hash:
                    write_image(image_path, fetched.content)
                    stop_fbi(fbi_proc)
                    fbi_proc = start_fbi(image_path)
                    time.sleep(0.2)
                    if fbi_proc.poll() is not None:
                        err = (fbi_proc.stderr.read() if fbi_proc.stderr else "").strip()
                        raise RuntimeError(err or "fbi exited immediately")
                    if last_hash is None:
                        print(f"Initial image displayed from {fetched.source_label}")
                    else:
                        print(f"Image changed, display updated from {fetched.source_label}")
                    last_hash = image_hash
                else:
                    print(f"No image change ({fetched.source_label})")
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
        stop_fbi(fbi_proc)
        if session is not None:
            session.close()


def main() -> int:
    cfg = parse_args()
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
