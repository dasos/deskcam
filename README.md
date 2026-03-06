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

## Run

```bash
python3 cam_display.py "http://YOUR_CAMERA/image.jpg"
```

Useful options:

- `--interval 300` poll every 5 minutes (default)
- `--timeout 10` HTTP timeout in seconds

Example:

```bash
python3 cam_display.py "http://192.168.1.20/snapshot.jpg" --interval 300
```

## Autostart (systemd, SSH-friendly)

This repo includes a unit file template at `systemd/deskcam.service`.

1. Copy and edit the service file:

```bash
sudo cp /home/pi/deskcam/systemd/deskcam.service /etc/systemd/system/deskcam.service
sudo nano /etc/systemd/system/deskcam.service
```

Update these fields:

- `User`, `Group`, `WorkingDirectory`
- `ExecStart` camera URL and options

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
