# deskcam

Simple fullscreen webcam image viewer for Raspberry Pi framebuffer (no desktop environment required).

## Install

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-pygame
cd /home/pi/deskcam
python3 -m pip install -r requirements.txt
```

## Run

```bash
python3 cam_display.py "http://YOUR_CAMERA/image.jpg"
```

Useful options:

- `--interval 300` poll every 5 minutes (default)
- `--transition 1.2` crossfade duration in seconds
- `--timeout 10` HTTP timeout in seconds

Example:

```bash
python3 cam_display.py "http://192.168.1.20/snapshot.jpg" --interval 300 --transition 1.5
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

- The unit uses `SDL_VIDEODRIVER=kmsdrm` and binds to `tty1`, which is more reliable than starting from an SSH shell.
- If video initialization still fails, verify KMS is enabled in `/boot/firmware/config.txt` with `dtoverlay=vc4-kms-v3d`.
