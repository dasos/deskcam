#!/usr/bin/env python3
"""Fullscreen webcam image viewer for Raspberry Pi HDMI output.

- Downloads a single image URL over HTTP(S)
- Polls at a configurable interval
- Updates display only when image bytes change
- Supports display backends:
  - `fbi` (robust fallback, cut updates only)
  - `fb` direct framebuffer rendering (supports fade transitions)
"""

from __future__ import annotations

import argparse
import io
import hashlib
import mmap
import os
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from ctypes import Structure, c_char, c_uint16, c_uint32, c_ulong
from dataclasses import dataclass
from fcntl import ioctl

import requests
from PIL import Image


@dataclass
class Config:
    url: str
    interval_seconds: int
    timeout_seconds: float
    backend: str
    transition: str
    transition_ms: int
    transition_fps: int


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
        "--backend",
        choices=("auto", "fbi", "fb"),
        default="auto",
        help="Display backend: auto, fbi, fb (default: auto)",
    )
    parser.add_argument(
        "--transition",
        choices=("none", "fade"),
        default="none",
        help="Transition effect between changed frames (default: none)",
    )
    parser.add_argument(
        "--transition-ms",
        type=int,
        default=500,
        help="Transition duration in milliseconds (default: 500)",
    )
    parser.add_argument(
        "--transition-fps",
        type=int,
        default=20,
        help="Transition FPS for direct framebuffer backend (default: 20)",
    )

    args = parser.parse_args()
    if args.interval < 5:
        parser.error("--interval must be at least 5 seconds")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.transition_ms < 0:
        parser.error("--transition-ms must be 0 or greater")
    if args.transition_fps < 1:
        parser.error("--transition-fps must be at least 1")

    return Config(
        url=args.url,
        interval_seconds=args.interval,
        timeout_seconds=args.timeout,
        backend=args.backend,
        transition=args.transition,
        transition_ms=args.transition_ms,
        transition_fps=args.transition_fps,
    )


def ensure_fbi_available() -> None:
    if shutil.which("fbi") is None:
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


def decode_image(raw: bytes) -> Image.Image:
    with Image.open(io.BytesIO(raw)) as img:
        return img.convert("RGB")


def fit_image(img: Image.Image, width: int, height: int) -> Image.Image:
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("invalid source or target dimensions")
    scale = min(width / src_w, height / src_h)
    dst_w = max(1, int(src_w * scale))
    dst_h = max(1, int(src_h * scale))
    resized = img.resize((dst_w, dst_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    off_x = (width - dst_w) // 2
    off_y = (height - dst_h) // 2
    canvas.paste(resized, (off_x, off_y))
    return canvas


def start_fbi(path: str) -> subprocess.Popen[str]:
    cmd = [
        "fbi",
        "-d",
        "/dev/fb0",
        "-a",
        "--noverbose",
        path,
    ]
    # Optional VT selection: set DESKCAM_FBI_TTY=1 if explicit VT switching is needed.
    tty = os.environ.get("DESKCAM_FBI_TTY", "").strip()
    if tty:
        cmd[1:1] = ["-T", tty]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def stop_fbi(proc: subprocess.Popen[str] | None) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


class DisplayBackend(ABC):
    @abstractmethod
    def show(self, raw: bytes, cfg: Config) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class FbiBackend(DisplayBackend):
    def __init__(self) -> None:
        ensure_fbi_available()
        self.image_dir = "/tmp/deskcam"
        self.image_path = os.path.join(self.image_dir, "current.img")
        os.makedirs(self.image_dir, exist_ok=True)
        self._proc: subprocess.Popen[str] | None = None

    def show(self, raw: bytes, cfg: Config) -> None:
        write_image(self.image_path, raw)
        stop_fbi(self._proc)
        self._proc = start_fbi(self.image_path)
        time.sleep(0.2)
        if self._proc.poll() is not None:
            err = (self._proc.stderr.read() if self._proc.stderr else "").strip()
            raise RuntimeError(err or "fbi exited immediately")

    def close(self) -> None:
        stop_fbi(self._proc)


# ioctl constants from linux/fb.h
FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602


class FbBitfield(Structure):
    _fields_ = [
        ("offset", c_uint32),
        ("length", c_uint32),
        ("msb_right", c_uint32),
    ]


class FbVarScreeninfo(Structure):
    _fields_ = [
        ("xres", c_uint32),
        ("yres", c_uint32),
        ("xres_virtual", c_uint32),
        ("yres_virtual", c_uint32),
        ("xoffset", c_uint32),
        ("yoffset", c_uint32),
        ("bits_per_pixel", c_uint32),
        ("grayscale", c_uint32),
        ("red", FbBitfield),
        ("green", FbBitfield),
        ("blue", FbBitfield),
        ("transp", FbBitfield),
        ("nonstd", c_uint32),
        ("activate", c_uint32),
        ("height", c_uint32),
        ("width", c_uint32),
        ("accel_flags", c_uint32),
        ("pixclock", c_uint32),
        ("left_margin", c_uint32),
        ("right_margin", c_uint32),
        ("upper_margin", c_uint32),
        ("lower_margin", c_uint32),
        ("hsync_len", c_uint32),
        ("vsync_len", c_uint32),
        ("sync", c_uint32),
        ("vmode", c_uint32),
        ("rotate", c_uint32),
        ("colorspace", c_uint32),
        ("reserved", c_uint32 * 4),
    ]


class FbFixScreeninfo(Structure):
    _fields_ = [
        ("id", c_char * 16),
        ("smem_start", c_ulong),
        ("smem_len", c_uint32),
        ("type", c_uint32),
        ("type_aux", c_uint32),
        ("visual", c_uint32),
        ("xpanstep", c_uint16),
        ("ypanstep", c_uint16),
        ("ywrapstep", c_uint16),
        ("line_length", c_uint32),
        ("mmio_start", c_ulong),
        ("mmio_len", c_uint32),
        ("accel", c_uint32),
        ("capabilities", c_uint16),
        ("reserved", c_uint16 * 2),
    ]


class FbBackend(DisplayBackend):
    def __init__(self, device: str = "/dev/fb0") -> None:
        self.device = device
        self._fh = None
        self._mm = None
        self._prev_frame: Image.Image | None = None
        try:
            self._fh = open(device, "r+b", buffering=0)

            var = FbVarScreeninfo()
            fix = FbFixScreeninfo()
            ioctl(self._fh.fileno(), FBIOGET_VSCREENINFO, var)
            ioctl(self._fh.fileno(), FBIOGET_FSCREENINFO, fix)

            self.width = int(var.xres)
            self.height = int(var.yres)
            self.bits_per_pixel = int(var.bits_per_pixel)
            self.bytes_per_pixel = self.bits_per_pixel // 8
            self.line_length = int(fix.line_length)
            self.frame_size = self.line_length * self.height
            self._mm = mmap.mmap(
                self._fh.fileno(), self.frame_size, mmap.MAP_SHARED, mmap.PROT_WRITE
            )

            if self.bits_per_pixel not in (16, 24, 32):
                raise RuntimeError(f"Unsupported framebuffer format: {self.bits_per_pixel} bpp")
            print(
                f"Framebuffer initialized: {self.width}x{self.height} "
                f"{self.bits_per_pixel}bpp stride={self.line_length}"
            )
        except Exception:
            self.close()
            raise

    def _to_fb_bytes(self, frame_rgb: Image.Image) -> bytes:
        if self.bits_per_pixel == 16:
            return frame_rgb.tobytes("raw", "BGR;16")
        if self.bits_per_pixel == 24:
            return frame_rgb.tobytes("raw", "BGR")
        return frame_rgb.tobytes("raw", "BGRX")

    def _blit(self, frame_rgb: Image.Image) -> None:
        buf = self._to_fb_bytes(frame_rgb)
        expected_packed = self.width * self.height * self.bytes_per_pixel
        if len(buf) != expected_packed:
            raise RuntimeError("Unexpected packed framebuffer byte length")

        packed_stride = self.width * self.bytes_per_pixel
        if packed_stride == self.line_length:
            self._mm.seek(0)
            self._mm.write(buf)
            self._mm.flush()
            return

        self._mm.seek(0)
        for row in range(self.height):
            start = row * packed_stride
            end = start + packed_stride
            self._mm.write(buf[start:end])
            if self.line_length > packed_stride:
                self._mm.write(b"\x00" * (self.line_length - packed_stride))
        self._mm.flush()

    def show(self, raw: bytes, cfg: Config) -> None:
        next_frame = fit_image(decode_image(raw), self.width, self.height)
        if (
            cfg.transition == "fade"
            and self._prev_frame is not None
            and cfg.transition_ms > 0
            and cfg.transition_fps > 0
        ):
            steps = max(1, int((cfg.transition_ms / 1000.0) * cfg.transition_fps))
            step_sleep = (cfg.transition_ms / 1000.0) / steps
            for step in range(1, steps + 1):
                alpha = step / steps
                blended = Image.blend(self._prev_frame, next_frame, alpha=alpha)
                self._blit(blended)
                if step < steps:
                    time.sleep(step_sleep)
        else:
            self._blit(next_frame)
        self._prev_frame = next_frame

    def close(self) -> None:
        if self._mm is not None:
            self._mm.close()
            self._mm = None
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def build_backend(cfg: Config) -> DisplayBackend:
    if cfg.backend == "fbi":
        print("Display backend selected: fbi")
        return FbiBackend()
    if cfg.backend == "fb":
        print("Display backend selected: fb")
        return FbBackend()

    if cfg.transition != "none":
        try:
            backend = FbBackend()
            print("Display backend selected: fb (auto)")
            return backend
        except Exception as exc:
            print(f"fb backend unavailable ({exc}), falling back to fbi")
    print("Display backend selected: fbi (auto)")
    return FbiBackend()


def run(cfg: Config) -> int:
    session = requests.Session()
    last_hash: str | None = None
    display = build_backend(cfg)

    try:
        while True:
            try:
                raw = fetch_image_bytes(session, cfg)
                image_hash = hashlib.sha256(raw).hexdigest()

                if image_hash != last_hash:
                    display.show(raw, cfg)
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
        display.close()
        session.close()


def main() -> int:
    cfg = parse_args()
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
