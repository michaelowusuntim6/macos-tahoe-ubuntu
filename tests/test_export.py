from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT
from engine import exporter


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tahoe-export-test-"))
        cls.result = exporter.export(ROOT, cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_archive_and_checksum(self):
        archive = self.result["archive"]
        self.assertTrue(archive.exists())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(digest, self.result["digest"])
        checksum_text = self.result["sha256"].read_text()
        self.assertIn(digest, checksum_text)

    def test_manifest_is_valid(self):
        manifest = json.loads(self.result["manifest"].read_text())
        self.assertEqual(manifest["version"], exporter.VERSION)
        self.assertEqual(manifest["sha256"], self.result["digest"])
        self.assertTrue(manifest["contents"])
        self.assertIn("restore_instructions", manifest)

    def test_no_machine_specific_data(self):
        with tarfile.open(self.result["archive"]) as tf:
            names = tf.getnames()
        forbidden = ("/backups/", "/state/", "/logs/", "/runtime/", "/.git/")
        for name in names:
            for part in forbidden:
                self.assertNotIn(part, name, f"{name} leaks machine data")
        self.assertFalse(any("/backups" in n or "/logs" in n for n in names))

    def test_required_files_present(self):
        with tarfile.open(self.result["archive"]) as tf:
            names = set(tf.getnames())
        prefix = "macos-tahoe-ubuntu-v1.1.1"
        for required in ("install.sh", "uninstall.sh", "verify.sh", "repair.sh",
                         "export.sh", "engine/main.py", "engine/exporter.py",
                         "config/desktop.json", "manifests/components.lock.json",
                         "extensions/tpct-mac-shell@tpct/metadata.json",
                         "assets/wallpapers/tahoe-dark.png",
                         "assets/cache/apt/SHA256SUMS",
                         "assets/cache/extensions/user-theme@gnome-shell-extensions.gcampax.github.com.shell-extension.zip",
                         "assets/icons/WhiteSur-dark.tar.gz",
                         "assets/fonts/Inter-Variable.ttf"):
            with self.subTest(required=required):
                self.assertIn(f"{prefix}/{required}", names)

    def test_entry_points_are_executable(self):
        with tarfile.open(self.result["archive"]) as tf:
            for name in ("install.sh", "uninstall.sh", "verify.sh",
                         "repair.sh", "export.sh"):
                member = tf.getmember(f"macos-tahoe-ubuntu-v1.1.1/{name}")
                self.assertTrue(member.mode & 0o100, f"{name} is not executable")

    def test_proprietary_assets_excluded_by_default(self):
        with tarfile.open(self.result["archive"]) as tf:
            names = tf.getnames()
        self.assertFalse(any("assets/references/" in n for n in names))
        self.assertFalse(any("assets/wallpapers/apple/" in n for n in names))
        self.assertTrue(any(n.endswith("assets/wallpapers/fallback/tahoe-dark.jpg")
                            for n in names))

    def test_archive_is_self_contained_for_offline_install(self):
        with tarfile.open(self.result["archive"]) as tf:
            names = tf.getnames()
        # Everything the offline installer needs is inside the archive.
        for required in ("assets/themes/tpct-dist/TPCT-Mac-Dark/gnome-shell/gnome-shell.css",
                         "assets/themes/tpct-dist/gtk-4.0/gtk-dark.css",
                         "assets/cursors/WhiteSur-cursors",
                         "assets/icons/WhiteSur-light.tar.gz",
                         "assets/cache/apt/rofi_2.0.0-0.2_amd64.deb"):
            with self.subTest(required=required):
                self.assertTrue(any(name.endswith(required) for name in names), required)


if __name__ == "__main__":
    unittest.main()
