import datetime
import io
import unittest
from types import SimpleNamespace
from unittest import mock
from xml.etree import ElementTree

from PIL import Image

import cam_display
import source_ftps
import source_http
import source_s3
from models import FetchedImage, is_valid_image


def make_image(image_format):
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(output, format=image_format)
    return output.getvalue()


JPEG = make_image("JPEG")
PNG = make_image("PNG")
TRUNCATED_JPEG = JPEG[:-2]


class EmptySourceTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(source_ftps, "_last_mtime", None))
        self.enterContext(mock.patch.object(source_ftps, "_cached_image", None))

    def make_source(self, backend, entries, contents, selection="latest"):
        """Entries are (name, modification order, size); None means missing size."""
        downloads = []
        if backend == "http":
            cfg = SimpleNamespace(
                http_selection=selection,
                http_url="https://example.test/images/fixed.jpg",
                http_directory_url="https://example.test/images/",
                timeout_seconds=10,
            )
            root = ElementTree.Element("{DAV:}multistatus")
            for name, modified, size in entries:
                entry = ElementTree.SubElement(root, "{DAV:}response")
                ElementTree.SubElement(entry, "{DAV:}href").text = f"/images/{name}"
                propstat = ElementTree.SubElement(entry, "{DAV:}propstat")
                prop = ElementTree.SubElement(propstat, "{DAV:}prop")
                ElementTree.SubElement(prop, "{DAV:}resourcetype")
                ElementTree.SubElement(prop, "{DAV:}getlastmodified").text = (
                    f"Wed, {modified:02d} Jan 2025 00:00:00 GMT"
                )
                if size is not None:
                    ElementTree.SubElement(prop, "{DAV:}getcontentlength").text = str(size)
            session = mock.Mock()
            session.request.return_value.content = ElementTree.tostring(root)

            def get(url, **kwargs):
                name = url.rsplit("/", 1)[-1]
                downloads.append(name)
                response = mock.Mock()
                response.content = contents[name]
                return response

            session.get.side_effect = get
            return lambda: source_http.fetch(session, cfg), downloads

        if backend == "s3":
            cfg = SimpleNamespace(
                s3_selection=selection, s3_bucket="bucket", s3_prefix="images/",
                s3_key="images/fixed.jpg",
            )
            client = mock.Mock()
            objects = []
            for name, modified, size in entries:
                obj = {
                    "Key": f"images/{name}",
                    "LastModified": datetime.datetime(2025, 1, modified, tzinfo=datetime.timezone.utc),
                }
                if size is not None:
                    obj["Size"] = size
                objects.append(obj)
            client.get_paginator.return_value.paginate.return_value = [{"Contents": objects}]

            def get_object(Bucket, Key):
                name = Key.rsplit("/", 1)[-1]
                downloads.append(name)
                return {"Body": io.BytesIO(contents[name])}

            client.get_object.side_effect = get_object
            return lambda: source_s3.fetch(client, cfg), downloads

        cfg = SimpleNamespace(
            ftps_selection=selection, ftps_host="example.test", ftps_port=21,
            ftps_username="user", ftps_password="password", ftps_directory="/images",
            ftps_path="/images/fixed.jpg",
        )
        ftp = mock.Mock()
        listing = []
        for name, modified, size in entries:
            facts = {"type": "file", "modify": f"202501{modified:02d}000000"}
            if size is not None:
                facts["size"] = str(size)
            listing.append((name, facts))
        ftp.mlsd.return_value = listing
        ftp.sendcmd.return_value = "213 20250101000000"

        def retrbinary(command, callback):
            name = command.rsplit("/", 1)[-1]
            downloads.append(name)
            callback(contents[name])

        ftp.retrbinary.side_effect = retrbinary
        self.enterContext(mock.patch.object(source_ftps.ftplib, "FTP_TLS", return_value=ftp))
        return lambda: source_ftps.fetch(cfg), downloads

    def test_latest_skips_listed_zero_size(self):
        for backend in ("http", "s3", "ftps"):
            with self.subTest(backend=backend):
                fetch, downloads = self.make_source(
                    backend, [("old.jpg", 1, len(JPEG)), ("new.jpg", 2, 0)],
                    {"old.jpg": JPEG, "new.jpg": b""},
                )
                image = fetch()
                self.assertEqual(image.content, JPEG)
                self.assertTrue(image.source_label.endswith("/old.jpg"))
                self.assertEqual(downloads, ["old.jpg"])

    def test_latest_falls_back_from_empty_download_with_missing_size(self):
        for backend in ("http", "s3", "ftps"):
            with self.subTest(backend=backend):
                fetch, downloads = self.make_source(
                    backend, [("old.jpg", 1, None), ("new.jpg", 2, None)],
                    {"old.jpg": JPEG, "new.jpg": b""},
                )
                image = fetch()
                self.assertEqual(image.content, JPEG)
                self.assertTrue(image.source_label.endswith("/old.jpg"))
                self.assertEqual(downloads, ["new.jpg", "old.jpg"])

    def test_latest_falls_back_when_advertised_nonempty_download_is_empty(self):
        for backend in ("http", "s3", "ftps"):
            with self.subTest(backend=backend):
                fetch, downloads = self.make_source(
                    backend, [("old.jpg", 1, len(JPEG)), ("new.jpg", 2, 5)],
                    {"old.jpg": JPEG, "new.jpg": b""},
                )
                image = fetch()
                self.assertEqual(image.content, JPEG)
                self.assertTrue(image.source_label.endswith("/old.jpg"))
                self.assertEqual(downloads, ["new.jpg", "old.jpg"])

    def test_latest_all_empty_raises(self):
        for backend in ("http", "s3", "ftps"):
            for size in (0, None):
                with self.subTest(backend=backend, size=size):
                    fetch, downloads = self.make_source(
                        backend, [("old.jpg", 1, size), ("new.jpg", 2, size)],
                        {"old.jpg": b"", "new.jpg": b""},
                    )
                    with self.assertRaises(RuntimeError):
                        fetch()
                    self.assertEqual(downloads, [] if size == 0 else ["new.jpg", "old.jpg"])

    def test_latest_falls_back_from_invalid_image(self):
        for backend in ("http", "s3", "ftps"):
            for invalid in (b"not an image", TRUNCATED_JPEG):
                with self.subTest(backend=backend, invalid=invalid[:16]):
                    fetch, downloads = self.make_source(
                        backend, [("old.jpg", 1, len(JPEG)), ("new.jpg", 2, len(invalid))],
                        {"old.jpg": JPEG, "new.jpg": invalid},
                    )
                    image = fetch()
                    self.assertEqual(image.content, JPEG)
                    self.assertTrue(image.source_label.endswith("/old.jpg"))
                    self.assertEqual(downloads, ["new.jpg", "old.jpg"])

    def test_latest_all_invalid_raises(self):
        for backend in ("http", "s3", "ftps"):
            with self.subTest(backend=backend):
                fetch, downloads = self.make_source(
                    backend, [("old.jpg", 1, len(TRUNCATED_JPEG)), ("new.jpg", 2, 12)],
                    {"old.jpg": TRUNCATED_JPEG, "new.jpg": b"not an image"},
                )
                with self.assertRaises(RuntimeError):
                    fetch()
                self.assertEqual(downloads, ["new.jpg", "old.jpg"])

    def test_single_empty_raises(self):
        for backend in ("http", "s3", "ftps"):
            with self.subTest(backend=backend):
                fetch, downloads = self.make_source(
                    backend, [], {"fixed.jpg": b""}, selection="single",
                )
                with self.assertRaises(RuntimeError):
                    fetch()
                self.assertEqual(downloads, ["fixed.jpg"])

    def test_single_invalid_raises(self):
        for backend in ("http", "s3", "ftps"):
            with self.subTest(backend=backend):
                fetch, downloads = self.make_source(
                    backend, [], {"fixed.jpg": b"not an image"}, selection="single",
                )
                with self.assertRaises(RuntimeError):
                    fetch()
                self.assertEqual(downloads, ["fixed.jpg"])

    def test_single_valid_jpeg_is_returned(self):
        for backend in ("http", "s3", "ftps"):
            with self.subTest(backend=backend):
                fetch, downloads = self.make_source(
                    backend, [], {"fixed.jpg": JPEG}, selection="single",
                )
                image = fetch()
                self.assertEqual(image.content, JPEG)
                self.assertTrue(image.source_label.endswith("/fixed.jpg"))
                self.assertEqual(downloads, ["fixed.jpg"])

    def test_single_valid_png_is_returned(self):
        for backend in ("http", "s3", "ftps"):
            with self.subTest(backend=backend):
                fetch, downloads = self.make_source(
                    backend, [], {"fixed.jpg": PNG}, selection="single",
                )
                image = fetch()
                self.assertEqual(image.content, PNG)
                self.assertTrue(image.source_label.endswith("/fixed.jpg"))
                self.assertEqual(downloads, ["fixed.jpg"])

    def test_ftps_single_retries_empty_content_with_same_mdtm(self):
        contents = {"fixed.jpg": b""}
        fetch, downloads = self.make_source("ftps", [], contents, selection="single")
        with self.assertRaises(RuntimeError):
            fetch()
        contents["fixed.jpg"] = JPEG
        image = fetch()
        self.assertEqual(image.content, JPEG)
        self.assertTrue(image.source_label.endswith("/fixed.jpg"))
        self.assertEqual(downloads, ["fixed.jpg", "fixed.jpg"])
        self.assertEqual(fetch().content, JPEG)
        self.assertEqual(downloads, ["fixed.jpg", "fixed.jpg"])

    def test_ftps_single_retries_invalid_content_with_same_mdtm(self):
        contents = {"fixed.jpg": TRUNCATED_JPEG}
        fetch, downloads = self.make_source("ftps", [], contents, selection="single")
        with self.assertRaises(RuntimeError):
            fetch()
        contents["fixed.jpg"] = JPEG
        image = fetch()
        self.assertEqual(image.content, JPEG)
        self.assertTrue(image.source_label.endswith("/fixed.jpg"))
        self.assertEqual(downloads, ["fixed.jpg", "fixed.jpg"])
        self.assertEqual(fetch().content, JPEG)
        self.assertEqual(downloads, ["fixed.jpg", "fixed.jpg"])

    def test_run_rejects_empty_content_before_display(self):
        self.assert_run_rejects_content(b"")

    def test_run_rejects_invalid_content_before_display(self):
        for invalid in (b"not an image", TRUNCATED_JPEG):
            with self.subTest(invalid=invalid[:16]):
                self.assert_run_rejects_content(invalid)

    def test_decompression_bomb_is_rejected(self):
        for limit in (40, 25):
            with self.subTest(limit=limit), mock.patch.object(Image, "MAX_IMAGE_PIXELS", limit):
                self.assertFalse(is_valid_image(JPEG))

    def test_run_keeps_current_display_when_next_image_is_invalid(self):
        cfg = SimpleNamespace(source_type="http", interval_seconds=5)
        proc = mock.Mock()
        proc.poll.return_value = None
        with (
            mock.patch.object(cam_display, "ensure_fbi_available"),
            mock.patch.object(cam_display.os, "makedirs"),
            mock.patch.object(cam_display.requests, "Session"),
            mock.patch.object(source_http, "fetch", side_effect=[
                FetchedImage(JPEG, "valid.jpg"), FetchedImage(b"broken", "invalid.jpg"),
            ]),
            mock.patch.object(cam_display, "write_image") as write_image,
            mock.patch.object(cam_display, "start_fbi", return_value=proc) as start_fbi,
            mock.patch.object(cam_display, "stop_fbi") as stop_fbi,
            mock.patch.object(cam_display.time, "sleep"),
            mock.patch.object(cam_display.time, "monotonic", side_effect=[0, 5, KeyboardInterrupt]),
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(cam_display.run(cfg), 0)
        write_image.assert_called_once()
        start_fbi.assert_called_once()
        self.assertEqual(stop_fbi.call_args_list, [mock.call(None), mock.call(proc)])

    def assert_run_rejects_content(self, content):
        cfg = SimpleNamespace(source_type="http", interval_seconds=5)
        with (
            mock.patch.object(cam_display, "ensure_fbi_available"),
            mock.patch.object(cam_display.os, "makedirs"),
            mock.patch.object(cam_display.requests, "Session"),
            mock.patch.object(source_http, "fetch", return_value=FetchedImage(content, "invalid.jpg")),
            mock.patch.object(cam_display, "write_image") as write_image,
            mock.patch.object(cam_display, "start_fbi") as start_fbi,
            mock.patch.object(cam_display.time, "sleep", side_effect=KeyboardInterrupt),
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(cam_display.run(cfg), 0)
        write_image.assert_not_called()
        start_fbi.assert_not_called()
        self.assertIn("error", stderr.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
