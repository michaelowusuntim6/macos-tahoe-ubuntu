from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from helpers import ROOT  # noqa: F401  (sets sys.path)
from engine import utilities as u


class GSettingsValueTests(unittest.TestCase):
    def test_string_quoting(self):
        self.assertEqual(u.to_gvariant("BOTTOM"), "'BOTTOM'")
        self.assertEqual(u.to_gvariant("it's"), "'it\\'s'")

    def test_scalars(self):
        self.assertEqual(u.to_gvariant(True), "true")
        self.assertEqual(u.to_gvariant(False), "false")
        self.assertEqual(u.to_gvariant(40), "40")
        self.assertEqual(u.to_gvariant(0.32), "0.32")

    def test_list(self):
        self.assertEqual(u.to_gvariant(["a", "b"]), "['a', 'b']")

    def test_unsupported(self):
        with self.assertRaises(u.ConfigError):
            u.to_gvariant({"a": 1})

    def test_array_parser(self):
        self.assertEqual(u.gsettings_array("['a', 'b']"), ["a", "b"])
        self.assertEqual(u.gsettings_array("@as []"), [])
        self.assertEqual(u.gsettings_array("not a list"), [])


class FileTests(unittest.TestCase):
    def test_atomic_write_and_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a" / "b.json"
            u.atomic_write_json(path, {"x": 1})
            self.assertEqual(json.loads(path.read_text()), {"x": 1})
            self.assertEqual(u.sha256_file(path), u.sha256_file(path))
            self.assertFalse(list(path.parent.glob(".b.json.*")))

    def test_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json")
            with self.assertRaises(u.ConfigError):
                u.read_json(path)

    def test_sha256_tree_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("hello")
            first = u.sha256_tree(root)
            (root / "b.txt").write_text("world")
            self.assertNotEqual(first, u.sha256_tree(root))
            self.assertEqual(u.sha256_tree(root), u.sha256_tree(root))


class ArchiveSafetyTests(unittest.TestCase):
    def test_tar_traversal_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "evil.tar"
            payload = Path(tmp) / "payload"
            payload.write_text("x")
            with tarfile.open(archive, "w") as tf:
                info = tarfile.TarInfo("../escape.txt")
                info.size = 1
                with payload.open("rb") as fh:
                    tf.addfile(info, fh)
            with self.assertRaises(u.IntegrityError):
                u.safe_extract_tar(archive, Path(tmp) / "out")
            self.assertFalse((Path(tmp).parent / "escape.txt").exists())

    def test_zip_traversal_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "evil.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../escape.txt", "x")
            with self.assertRaises(u.IntegrityError):
                u.safe_extract_zip(archive, Path(tmp) / "out")

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ok.tar.gz"
            source = Path(tmp) / "dir"
            source.mkdir()
            (source / "file.txt").write_text("data")
            with tarfile.open(archive, "w:gz") as tf:
                tf.add(source, arcname="dir")
            dest = Path(tmp) / "out"
            u.safe_extract_tar(archive, dest)
            self.assertEqual((dest / "dir/file.txt").read_text(), "data")


class ProcessTests(unittest.TestCase):
    def test_failure_raises_command_error(self):
        with self.assertRaises(u.CommandError) as ctx:
            u.run(["false"], timeout=10)
        self.assertEqual(ctx.exception.returncode, 1)

    def test_check_false_returns_result(self):
        proc = u.run(["false"], check=False, timeout=10)
        self.assertEqual(proc.returncode, 1)

    def test_missing_executable(self):
        with self.assertRaises(u.CommandError):
            u.run(["definitely-not-a-real-command-xyz"], timeout=5)

    def test_timeout(self):
        with self.assertRaises(u.CommandError):
            u.run(["sleep", "5"], timeout=0.2)


if __name__ == "__main__":
    unittest.main()
