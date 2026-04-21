# deskcam
![Static Badge](https://img.shields.io/badge/Vibe-coded-orange) ![Static Badge](https://img.shields.io/badge/Coded_with-Codex-blue) ![Static Badge](https://img.shields.io/badge/Coded_with-Claude-orange)

Simple fullscreen webcam image viewer for Raspberry Pi framebuffer (no desktop environment required).
Uses `fbi` for display output, which works reliably from SSH + `systemd`.

## Install

```bash
sudo apt update
sudo apt install -y python3 python3-pip fbi
cd /home/pi/deskcam
python3 -m pip install -r requirements.txt
```

## Configuration

Three source backends are supported:

- `http`: fetch either a fixed image URL or the newest `.jpg`/`.jpeg` file in a WebDAV directory
- `s3`: fetch either a fixed object key or the newest `.jpg`/`.jpeg` object under a prefix
- `ftps`: fetch either a fixed file or the newest `.jpg`/`.jpeg` file in a directory (explicit TLS on port 21); single-file mode skips the download when the file has not changed

Configuration can come from CLI flags, environment variables, or an env file.

For local/manual runs, a repo-local `.env` file is fine and is already ignored by git.
For the Raspberry Pi `systemd` service, prefer a root-owned env file outside the repo such as `/etc/deskcam.env` so secrets do not live in the unit file or command line.

Copy the example file and edit it:

```bash
cp .env.example .env
nano .env
```

### Common

| Variable | Default | Description |
|---|---|---|
| `DESKCAM_SOURCE` | auto-detected | `http`, `s3`, or `ftps` |
| `DESKCAM_INTERVAL` | `300` | Poll interval in seconds (minimum 5) |
| `DESKCAM_TIMEOUT` | `10` | HTTP/S3 request timeout in seconds |

### HTTP / WebDAV

| Variable | Description |
|---|---|
| `DESKCAM_HTTP_SELECTION` | `single` (default) or `latest` |
| `DESKCAM_HTTP_URL` | Image URL when `single` |
| `DESKCAM_HTTP_DIRECTORY_URL` | WebDAV directory URL when `latest` |

### S3

| Variable | Description |
|---|---|
| `DESKCAM_S3_BUCKET` | Bucket name |
| `DESKCAM_S3_SELECTION` | `single` (default) or `latest` |
| `DESKCAM_S3_KEY` | Exact object key when `single` |
| `DESKCAM_S3_PREFIX` | Object prefix when `latest`; empty string for bucket root |
| `DESKCAM_S3_REGION` | Region (optional) |
| `DESKCAM_S3_ENDPOINT_URL` | Override endpoint for S3-compatible providers (optional) |
| `AWS_ACCESS_KEY_ID` | AWS / S3-compatible access key |
| `AWS_SECRET_ACCESS_KEY` | AWS / S3-compatible secret key |
| `AWS_SESSION_TOKEN` | Session token (optional) |

### FTPS

| Variable | Default | Description |
|---|---|---|
| `DESKCAM_FTPS_HOST` | | Server hostname |
| `DESKCAM_FTPS_PORT` | `21` | Server port |
| `DESKCAM_FTPS_USERNAME` | | Login username |
| `DESKCAM_FTPS_PASSWORD` | | Login password |
| `DESKCAM_FTPS_SELECTION` | `single` | `single` or `latest` |
| `DESKCAM_FTPS_PATH` | | Exact file path when `single` |
| `DESKCAM_FTPS_DIRECTORY` | | Directory path when `latest` |

## Run

HTTP / WebDAV single file, legacy style:

```bash
python3 cam_display.py "http://YOUR_CAMERA/image.jpg"
```

HTTP / WebDAV from env:

```bash
DESKCAM_SOURCE=http DESKCAM_HTTP_URL="http://YOUR_CAMERA/image.jpg" python3 cam_display.py
```

WebDAV newest file in a directory:

```bash
DESKCAM_SOURCE=http \
DESKCAM_HTTP_SELECTION=latest \
DESKCAM_HTTP_DIRECTORY_URL="https://webdav.example.com/camera/" \
python3 cam_display.py
```

S3 fixed object:

```bash
DESKCAM_SOURCE=s3 \
DESKCAM_S3_BUCKET=your-bucket \
DESKCAM_S3_SELECTION=single \
DESKCAM_S3_KEY=cameras/lobby/current.jpg \
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY \
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY \
python3 cam_display.py
```

S3 newest file under a prefix:

```bash
DESKCAM_SOURCE=s3 \
DESKCAM_S3_BUCKET=your-bucket \
DESKCAM_S3_SELECTION=latest \
DESKCAM_S3_PREFIX=cameras/lobby/ \
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY \
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY \
python3 cam_display.py
```

S3 newest JPG/JPEG from bucket root:

```bash
DESKCAM_SOURCE=s3 \
DESKCAM_S3_BUCKET=your-bucket \
DESKCAM_S3_SELECTION=latest \
DESKCAM_S3_PREFIX= \
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY \
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY \
python3 cam_display.py
```

FTPS fixed file:

```bash
DESKCAM_SOURCE=ftps \
DESKCAM_FTPS_HOST=ftp.example.com \
DESKCAM_FTPS_USERNAME=user \
DESKCAM_FTPS_PASSWORD=secret \
DESKCAM_FTPS_SELECTION=single \
DESKCAM_FTPS_PATH=/cameras/lobby/current.jpg \
python3 cam_display.py
```

FTPS newest file in a directory:

```bash
DESKCAM_SOURCE=ftps \
DESKCAM_FTPS_HOST=ftp.example.com \
DESKCAM_FTPS_USERNAME=user \
DESKCAM_FTPS_PASSWORD=secret \
DESKCAM_FTPS_SELECTION=latest \
DESKCAM_FTPS_DIRECTORY=/cameras/lobby/ \
python3 cam_display.py
```

## Autostart (systemd, SSH-friendly)

This repo includes a unit file template at `systemd/deskcam.service`.

1. Copy and edit the service file:

```bash
sudo cp /home/pi/deskcam/systemd/deskcam.service /etc/systemd/system/deskcam.service
sudo cp /home/pi/deskcam/.env.example /etc/deskcam.env
sudo chmod 600 /etc/deskcam.env
sudo chown root:root /etc/deskcam.env
sudo nano /etc/systemd/system/deskcam.service
sudo nano /etc/deskcam.env
```

Update these fields:

- `User`, `Group`, `WorkingDirectory`
- `/etc/deskcam.env` source settings and credentials

Example `/etc/deskcam.env` for HTTP / WebDAV single file:

```bash
DESKCAM_SOURCE=http
DESKCAM_HTTP_SELECTION=single
DESKCAM_HTTP_URL=http://192.168.1.20/snapshot.jpg
DESKCAM_INTERVAL=300
DESKCAM_TIMEOUT=10
```

Example `/etc/deskcam.env` for newest file in a WebDAV directory:

```bash
DESKCAM_SOURCE=http
DESKCAM_HTTP_SELECTION=latest
DESKCAM_HTTP_DIRECTORY_URL=https://webdav.example.com/camera/
DESKCAM_INTERVAL=300
DESKCAM_TIMEOUT=10
```

Example `/etc/deskcam.env` for S3 fixed key:

```bash
DESKCAM_SOURCE=s3
DESKCAM_S3_BUCKET=your-bucket
DESKCAM_S3_REGION=us-east-1
DESKCAM_S3_SELECTION=single
DESKCAM_S3_KEY=cameras/lobby/current.jpg
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
```

Example `/etc/deskcam.env` for newest S3 object under a prefix:

```bash
DESKCAM_SOURCE=s3
DESKCAM_S3_BUCKET=your-bucket
DESKCAM_S3_REGION=us-east-1
DESKCAM_S3_SELECTION=latest
DESKCAM_S3_PREFIX=cameras/lobby/
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
```

Example `/etc/deskcam.env` for newest S3 object from bucket root:

```bash
DESKCAM_SOURCE=s3
DESKCAM_S3_BUCKET=your-bucket
DESKCAM_S3_REGION=us-east-1
DESKCAM_S3_SELECTION=latest
DESKCAM_S3_PREFIX=
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
```

Example `/etc/deskcam.env` for FTPS fixed file:

```bash
DESKCAM_SOURCE=ftps
DESKCAM_FTPS_HOST=ftp.example.com
DESKCAM_FTPS_USERNAME=user
DESKCAM_FTPS_PASSWORD=secret
DESKCAM_FTPS_SELECTION=single
DESKCAM_FTPS_PATH=/cameras/lobby/current.jpg
DESKCAM_INTERVAL=300
```

Example `/etc/deskcam.env` for newest FTPS file in a directory:

```bash
DESKCAM_SOURCE=ftps
DESKCAM_FTPS_HOST=ftp.example.com
DESKCAM_FTPS_USERNAME=user
DESKCAM_FTPS_PASSWORD=secret
DESKCAM_FTPS_SELECTION=latest
DESKCAM_FTPS_DIRECTORY=/cameras/lobby/
DESKCAM_INTERVAL=300
```

2. Ensure the service user has required device access:

```bash
sudo usermod -aG video,render,input pi
```

3. Reload systemd and enable on boot:

```bash
sudo systemctl daemon-reload
sudo systemctl disable --now getty@tty1.service
sudo systemctl enable --now deskcam.service
```

4. Check status:

```bash
systemctl status deskcam.service
```

5. Follow logs:

```bash
journalctl -u deskcam.service -f
```

Notes:

- The unit binds to `tty1` and displays with `fbi` on `/dev/fb0`.
- `fbi` VT switching is not forced by default. If needed, set `DESKCAM_FBI_TTY=1` in the service environment.
- WebDAV latest mode uses `PROPFIND Depth: 1` and picks the newest non-directory `.jpg`/`.jpeg` by `getlastmodified`.
- S3 latest mode searches `.jpg`/`.jpeg` objects and supports bucket root with `DESKCAM_S3_PREFIX=`.
- FTPS uses explicit TLS (`STARTTLS` on port 21) via Python's stdlib `ftplib` — no extra dependencies.
- FTPS latest mode uses `MLSD` to retrieve modification times; your server must support it (most modern FTPS servers do).
- FTPS single-file mode checks `MDTM` before downloading and skips the transfer if the file has not changed.
- Credentials (S3 keys, FTPS password) should go in the env file, not in `ExecStart`.
- If video output still fails, verify KMS is enabled in `/boot/firmware/config.txt` with `dtoverlay=vc4-kms-v3d`.

## Troubleshooting (SSH-only)

If the HDMI still shows a login prompt on `tty1`:

```bash
sudo systemctl disable --now getty@tty1.service
sudo systemctl restart deskcam.service
```

If logs appear empty, check with:

```bash
journalctl -u deskcam.service -b --no-pager -n 200
systemctl status deskcam.service
```

If device permissions are wrong, verify:

```bash
id pi
ls -l /dev/dri /dev/dri/card0 /dev/dri/renderD128
ls -l /dev/fb0
```
