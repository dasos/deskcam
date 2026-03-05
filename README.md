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

## Autostart (systemd)

1. Create `/etc/systemd/system/deskcam.service`:

```ini
[Unit]
Description=DeskCam Fullscreen Viewer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/deskcam
ExecStart=/usr/bin/python3 /home/pi/deskcam/cam_display.py "http://YOUR_CAMERA/image.jpg" --interval 300 --transition 1.2
Restart=always
RestartSec=5
Environment=SDL_VIDEODRIVER=fbcon
Environment=SDL_FBDEV=/dev/fb0
Environment=SDL_NOMOUSE=1

[Install]
WantedBy=multi-user.target
```

2. Reload systemd and enable on boot:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now deskcam.service
```

3. Check status:

```bash
systemctl status deskcam.service
```

4. Follow logs:

```bash
journalctl -u deskcam.service -f
```
