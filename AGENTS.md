# AGENTS.md

## Project Snapshot
- Project: `deskcam`
- Goal: display a periodically refreshed webcam image fullscreen on Raspberry Pi HDMI output.
- Current display backend: `fbi` (not `pygame`/SDL), because SDL/KMS rendered black on target setup.

## File Structure
- `cam_display.py` — entry point; env/arg parsing, fbi display logic, main poll loop
- `models.py` — shared `Config` and `FetchedImage` dataclasses, `is_jpeg_path` helper
- `source_http.py` — HTTP / WebDAV fetch backend; exposes `fetch(session, cfg)`
- `source_s3.py` — S3 fetch backend; exposes `fetch(s3_client, cfg)` and `create_client(cfg)`
- `source_ftps.py` — FTPS fetch backend; exposes `fetch(cfg)` (manages its own connection per poll)

## What Works (Confirmed)
- Running as a `systemd` service bound to `tty1`.
- Fetch + hash + update loop in `cam_display.py`.
- Display via `fbi` on `/dev/fb0`.
- Keeping `fbi` process alive between polls (do not run one-shot `fbi -1 -t 1` if persistent display is desired).

## Known Pitfalls
- `pygame`/SDL path was removed due to repeated black-screen behavior despite successful decode/render logs.
- Forcing `fbi -T 1` can fail in service context with:
  - `ioctl VT_ACTIVATE: Operation not permitted`
- Black screen with flashing cursor usually means display process exited and tty fallback happened.

## Source Backend Notes
- **HTTP**: uses a persistent `requests.Session` created once at startup.
- **S3**: uses a persistent boto3 client created once at startup; `boto3` is imported lazily inside `create_client()` so it is not loaded when using other backends.
- **FTPS**: opens a fresh `ftplib.FTP_TLS` connection each poll cycle to avoid timeout issues with long intervals. Single-file mode caches the last `MDTM` timestamp and skips the download when unchanged. Requires explicit TLS (STARTTLS, port 21); uses `MLSD` for directory listings.

## Service Guidance
- Use the template at `systemd/deskcam.service`.
- Typical required settings:
  - `Conflicts=getty@tty1.service`
  - `TTYPath=/dev/tty1`
  - `StandardInput=tty-force`
  - `User`/`Group`/`WorkingDirectory` must match real deployment user/path.
- Service user should be in at least: `video`, `render`, `input`.

## Runtime Notes
- `DESKCAM_FBI_TTY` environment variable is optional.
  - Default behavior does not force VT switching.
  - Set only when explicit `fbi -T <n>` behavior is required and permitted.
- `--transition` support was intentionally removed because the `fbi` backend does not provide clean frame-transition primitives.

## Deployment Checklist
1. `sudo apt install -y python3 python3-pip fbi`
2. `python3 -m pip install -r requirements.txt`
3. Copy service: `sudo cp systemd/deskcam.service /etc/systemd/system/deskcam.service`
4. Edit service for correct user/path.
5. Copy and edit env file: `sudo cp .env.example /etc/deskcam.env && sudo chmod 600 /etc/deskcam.env`
6. `sudo systemctl daemon-reload`
7. `sudo systemctl disable --now getty@tty1.service`
8. `sudo systemctl enable --now deskcam.service`
9. Verify logs: `journalctl -u deskcam.service -f`

## Useful Diagnostics
- Active VT: `cat /sys/class/tty/tty0/active`
- Device access:
  - `id <user>`
  - `ls -l /dev/fb0 /dev/dri/card0 /dev/dri/renderD128`
- Service inspection:
  - `systemctl cat deskcam.service`
  - `journalctl -u deskcam.service -b --no-pager -n 200`

## Editing Policy For Future Agents
- Keep implementation simple and operationally robust for headless SSH + systemd environments.
- Prefer incremental, verifiable changes with clear journald logs.
- Avoid reintroducing SDL/pygame display code unless there is a verified hardware-specific need and test evidence.
- Each source backend lives in its own `source_*.py` file and exposes a `fetch()` entry point. Add new backends by creating a new `source_*.py` and wiring it into `parse_args()` and the dispatch in `run()` in `cam_display.py`.
