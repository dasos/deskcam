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
    _last_mtime = mtime
    _cached_image = image
    return image


def _fetch_latest(cfg: Config) -> FetchedImage:
    directory = cfg.ftps_directory or "."

    ftp = _connect(cfg)
    try:
        latest_name: str | None = None
        latest_mtime: str | None = None

        for name, facts in ftp.mlsd(directory, facts=["type", "modify"]):
            if facts.get("type") != "file" or not is_jpeg_path(name):
                continue
            mtime = facts.get("modify", "")
            if latest_mtime is None or mtime > latest_mtime:
                latest_mtime = mtime
                latest_name = name

        if latest_name is None:
            raise RuntimeError(f"No JPG/JPEG files found in FTPS directory {directory}")

        path = f"{directory.rstrip('/')}/{latest_name}"
        buf = io.BytesIO()
        ftp.retrbinary(f"RETR {path}", buf.write)
    finally:
        _quit(ftp)

    return FetchedImage(
        content=buf.getvalue(),
        source_label=f"ftps://{cfg.ftps_host}/{path.lstrip('/')}",
    )
