from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT  # noqa: F401
from engine import backup_manager, utilities as u


class BackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tahoe-backup-test-"))
        cls.backup = backup_manager.create_backup(cls.tmp, "unit-test")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_backup_layout(self):
        for name in ("MANIFEST.json", "dconf.ini", "extensions.json",
                     "packages.txt", "system-info.json", "files-snapshot.json",
                     "managed-paths.json", "gsettings-recursive.json",
                     "wallpapers.json"):
            with self.subTest(file=name):
                self.assertTrue((self.backup / name).exists(), name)

    def test_manifest_checksums(self):
        ok, problems = backup_manager.verify_backup(self.backup)
        self.assertTrue(ok, problems)
        manifest = u.read_json(self.backup / "MANIFEST.json")
        self.assertEqual(manifest["project"], "macos-tahoe-ubuntu")
        self.assertEqual(manifest["reason"], "unit-test")
        self.assertTrue(manifest["files"])

    def test_never_overwrites(self):
        second = backup_manager.create_backup(self.tmp, "unit-test")
        self.assertNotEqual(second, self.backup)
        self.assertTrue(second.exists())
        self.assertTrue(self.backup.exists())
        shutil.rmtree(second, ignore_errors=True)

    def test_list_and_latest(self):
        backups = backup_manager.list_backups(self.tmp)
        self.assertIn(self.backup, backups)
        self.assertEqual(backup_manager.latest_backup(self.tmp), sorted(backups)[-1])

    def test_resolve_missing(self):
        with self.assertRaises(u.EngineError):
            backup_manager.resolve_backup(self.tmp, "does-not-exist")

    def test_corruption_detected(self):
        target = self.backup / "dconf.ini"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"\n# tampered\n")
            ok, problems = backup_manager.verify_backup(self.backup)
            self.assertFalse(ok)
            self.assertTrue(any("checksum" in p for p in problems))
        finally:
            target.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
