# deskcam
![Static Badge](https://img.shields.io/badge/Vibe-coded-orange) ![Static Badge](https://img.shields.io/badge/Coded_with-Codex-blue)

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

The app now supports two source backends:

- `http`: fetch either a fixed image URL or the newest `.jpg`/`.jpeg` file in a WebDAV directory
- `s3`: fetch either a fixed object key or the newest `.jpg`/`.jpeg` object under a prefix

Configuration can come from CLI flags, environment variables, or an env file.

For local/manual runs, a repo-local `.env` file is fine and is already ignored by git.
For the Raspberry Pi `systemd` service, prefer a root-owned env file outside the repo such as `/etc/deskcam.env` so secrets do not live in the unit file or command line.

Copy the example file and edit it:

```bash
cp .env.example .env
nano .env
```

Important environment variables:

- `DESKCAM_SOURCE=http|s3`
- `DESKCAM_INTERVAL=300`
- `DESKCAM_TIMEOUT=10`
- `DESKCAM_HTTP_SELECTION=single|latest`
- `DESKCAM_HTTP_URL=...` when `single`
- `DESKCAM_HTTP_DIRECTORY_URL=...` when `latest`
- `DESKCAM_S3_BUCKET=...`
- `DESKCAM_S3_SELECTION=single|latest`
- `DESKCAM_S3_KEY=...` when `single`
- `DESKCAM_S3_PREFIX=...` when `latest`; set it to an empty value for bucket root
- `AWS_ACCESS_KEY_ID=...`
- `AWS_SECRET_ACCESS_KEY=...`
- `AWS_SESSION_TOKEN=...` optional
- `DESKCAM_S3_REGION=...` optional but usually useful
- `DESKCAM_S3_ENDPOINT_URL=...` optional for S3-compatible providers

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

Example `/etc/deskcam.env` for HTTP / WebDAV:

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

Example `/etc/deskcam.env` for newest object under a prefix:

```bash
DESKCAM_SOURCE=s3
DESKCAM_S3_BUCKET=your-bucket
DESKCAM_S3_REGION=us-east-1
DESKCAM_S3_SELECTION=latest
DESKCAM_S3_PREFIX=cameras/lobby/
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
```

Example `/etc/deskcam.env` for newest JPG/JPEG object from bucket root:

```bash
DESKCAM_SOURCE=s3
DESKCAM_S3_BUCKET=your-bucket
DESKCAM_S3_REGION=us-east-1
DESKCAM_S3_SELECTION=latest
DESKCAM_S3_PREFIX=
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
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
- WebDAV latest-directory mode uses `PROPFIND Depth: 1` and picks the newest non-directory `.jpg` or `.jpeg` item by `getlastmodified`.
- S3 latest mode only considers `.jpg` and `.jpeg` objects and can search bucket root with `DESKCAM_S3_PREFIX=`.
- S3 bucket name, key, prefix, and credentials should go in the env file, not in `ExecStart`.
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
