#!/usr/bin/env python3
"""Fullscreen webcam image viewer for Raspberry Pi framebuffer.

- Downloads a single image URL over HTTP(S)
- Polls at a configurable interval
- Updates display only when image bytes change
- Uses smooth crossfade between images
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

import pygame
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
        default=1.2,
        help="Crossfade duration in seconds (default: 1.2)",
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


def configure_sdl_for_pi() -> None:
    # Use Linux framebuffer directly when no desktop/window manager exists.
    os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
    os.environ.setdefault("SDL_FBDEV", "/dev/fb0")
    os.environ.setdefault("SDL_NOMOUSE", "1")


def fetch_image_bytes(session: requests.Session, cfg: Config) -> bytes:
    response = session.get(cfg.url, timeout=cfg.timeout_seconds)
    response.raise_for_status()
    return response.content


def to_fitted_surface(raw: bytes, screen_size: tuple[int, int]) -> pygame.Surface:
    loaded = pygame.image.load(io.BytesIO(raw))
    source = loaded.convert()

    sw, sh = source.get_size()
    tw, th = screen_size

    scale = min(tw / sw, th / sh)
    nw = max(1, int(sw * scale))
    nh = max(1, int(sh * scale))

    scaled = pygame.transform.smoothscale(source, (nw, nh))

    frame = pygame.Surface((tw, th)).convert()
    frame.fill((0, 0, 0))
    x = (tw - nw) // 2
    y = (th - nh) // 2
    frame.blit(scaled, (x, y))
    return frame


def draw_fullscreen(screen: pygame.Surface, frame: pygame.Surface) -> None:
    screen.blit(frame, (0, 0))
    pygame.display.flip()


def crossfade(
    screen: pygame.Surface,
    old_frame: pygame.Surface,
    new_frame: pygame.Surface,
    seconds: float,
) -> None:
    if seconds <= 0:
        draw_fullscreen(screen, new_frame)
        return

    clock = pygame.time.Clock()
    start = time.monotonic()

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise KeyboardInterrupt
        elapsed = time.monotonic() - start
        progress = min(1.0, elapsed / seconds)

        old_alpha = int(255 * (1.0 - progress))
        new_alpha = int(255 * progress)

        old_layer = old_frame.copy()
        new_layer = new_frame.copy()
        old_layer.set_alpha(old_alpha)
        new_layer.set_alpha(new_alpha)

        screen.fill((0, 0, 0))
        screen.blit(old_layer, (0, 0))
        screen.blit(new_layer, (0, 0))
        pygame.display.flip()

        if progress >= 1.0:
            break
        clock.tick(60)


def run(cfg: Config) -> int:
    configure_sdl_for_pi()

    pygame.init()
    pygame.mouse.set_visible(False)

    try:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    except pygame.error as exc:
        print(f"Failed to open fullscreen display: {exc}", file=sys.stderr)
        return 2

    screen_size = screen.get_size()
    print(f"Display size: {screen_size[0]}x{screen_size[1]}")

    session = requests.Session()
    last_hash: Optional[str] = None
    current_frame: Optional[pygame.Surface] = None

    try:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return 0

            try:
                raw = fetch_image_bytes(session, cfg)
                image_hash = hashlib.sha256(raw).hexdigest()

                if image_hash != last_hash:
                    next_frame = to_fitted_surface(raw, screen_size)
                    if current_frame is None:
                        draw_fullscreen(screen, next_frame)
                        print("Initial image displayed")
                    else:
                        crossfade(screen, current_frame, next_frame, cfg.transition_seconds)
                        print("Image changed, display updated")
                    current_frame = next_frame
                    last_hash = image_hash
                else:
                    print("No image change")
            except Exception as exc:  # Keep the loop running on transient errors.
                print(f"Fetch/decode error: {exc}", file=sys.stderr)

            sleep_until = time.monotonic() + cfg.interval_seconds
            while True:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        return 0
                remaining = sleep_until - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.25, remaining))

    except KeyboardInterrupt:
        return 0
    finally:
        session.close()
        pygame.quit()


def main() -> int:
    cfg = parse_args()
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
