from __future__ import annotations

import ftplib
import io

from models import Config, FetchedImage, is_jpeg_path

# Cached state for single-file mode — persists across poll cycles to avoid
# re-downloading when the file hasn't changed.
_last_mtime: str | None = None
_cached_image: FetchedImage | None = None


def fetch(cfg: Config) -> FetchedImage:
    if cfg.ftps_selection == "latest":
        return _fetch_latest(cfg)
    return _fetch_single(cfg)


def _connect(cfg: Config) -> ftplib.FTP_TLS:
    ftp = ftplib.FTP_TLS()
    ftp.connect(cfg.ftps_host, cfg.ftps_port)
    ftp.login(cfg.ftps_username or "", cfg.ftps_password or "")
    ftp.prot_p()  # encrypt data channel
    ftp.set_pasv(True)
    return ftp


def _quit(ftp: ftplib.FTP_TLS) -> None:
    try:
        ftp.quit()
    except Exception:
        ftp.close()


def _fetch_single(cfg: Config) -> FetchedImage:
    global _last_mtime, _cached_image

    ftp = _connect(cfg)
    try:
        resp = ftp.sendcmd(f"MDTM {cfg.ftps_path}")
        mtime = resp.split()[1]  # "213 20231015143022" -> "20231015143022"

        if mtime == _last_mtime and _cached_image is not None:
            return _cached_image

        buf = io.BytesIO()
        ftp.retrbinary(f"RETR {cfg.ftps_path}", buf.write)
    finally:
        _quit(ftp)

    image = FetchedImage(
        content=buf.getvalue(),
        source_label=f"ftps://{cfg.ftps_host}/{cfg.ftps_path.lstrip('/')}",
    )
    if not image.content:
        raise RuntimeError(f"Empty image from {image.source_label}")
    _last_mtime = mtime
    _cached_image = image
    return image


def _fetch_latest(cfg: Config) -> FetchedImage:
    directory = cfg.ftps_directory or "."

    ftp = _connect(cfg)
    try:
        entries = []

        for name, facts in ftp.mlsd(directory, facts=["type", "modify", "size"]):
            if facts.get("type") != "file" or not is_jpeg_path(name):
                continue
            size = facts.get("size", "").strip()
            if size.isdigit() and int(size) == 0:
                continue
            entries.append((facts.get("modify", ""), name))

        entries.sort(key=lambda entry: entry[0], reverse=True)
        for _, name in entries:
            path = f"{directory.rstrip('/')}/{name}"
            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {path}", buf.write)
            content = buf.getvalue()
            if content:
                return FetchedImage(
                    content=content,
                    source_label=f"ftps://{cfg.ftps_host}/{path.lstrip('/')}",
                )
        raise RuntimeError(f"No non-empty JPG/JPEG files found in FTPS directory {directory}")
    finally:
        _quit(ftp)
