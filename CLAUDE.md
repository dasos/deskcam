# deskcam — Claude context

Fullscreen webcam image viewer for Raspberry Pi, running headless via SSH + systemd. Displays via `fbi` on `/dev/fb0`.

## File structure

- `cam_display.py` — entry point: env/arg parsing, fbi display, main poll loop
- `models.py` — `Config`, `FetchedImage` dataclasses, `is_jpeg_path` helper
- `source_http.py` — HTTP / WebDAV backend; entry point: `fetch(session, cfg)`
- `source_s3.py` — S3 backend; entry points: `fetch(s3_client, cfg)`, `create_client(cfg)`
- `source_ftps.py` — FTPS backend; entry point: `fetch(cfg)`

## Adding a new source backend

1. Create `source_<name>.py` with a `fetch(cfg) -> FetchedImage` entry point
2. Add fields to `Config` in `models.py`
3. Add args + validation to `parse_args()` in `cam_display.py`
4. Wire into the dispatch in `run()` in `cam_display.py`

## Key design decisions (don't reverse without good reason)

- **fbi, not SDL/pygame** — SDL rendered black on the target hardware; fbi is reliable from SSH with no display environment
- **fbi stays alive between polls** — do not switch to one-shot `fbi -1 -t 1`; the process must persist for a stable display
- **boto3 imported lazily** inside `source_s3.create_client()` — not at module level, so it isn't loaded when using http or ftps
- **FTPS opens a fresh connection each poll** — keeps it simple and avoids timeout issues at long intervals
- **FTPS single-file mode caches `MDTM`** at module level to skip unnecessary downloads between polls
- **`fbi -T` (VT switching) is off by default** — forcing it fails with `ioctl VT_ACTIVATE: Operation not permitted` in the systemd service context; only enable via `DESKCAM_FBI_TTY` if explicitly needed

## Deployment context

- Target: Raspberry Pi, SSH-only, no desktop
- Service: `systemd/deskcam.service`, bound to `tty1`, env from `/etc/deskcam.env` (chmod 600)
- Service user needs groups: `video`, `render`, `input`
- KMS overlay required in `/boot/firmware/config.txt`: `dtoverlay=vc4-kms-v3d`
