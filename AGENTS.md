# AGENTS.md

## Project Snapshot
- Project: `deskcam`
- Goal: display a periodically refreshed webcam image fullscreen on Raspberry Pi HDMI output.
- Current display backend: `fbi` (not `pygame`/SDL), because SDL/KMS rendered black on target setup.

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
4. Edit service for correct user/path/url.
5. `sudo systemctl daemon-reload`
6. `sudo systemctl disable --now getty@tty1.service`
7. `sudo systemctl enable --now deskcam.service`
8. Verify logs: `journalctl -u deskcam.service -f`

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
