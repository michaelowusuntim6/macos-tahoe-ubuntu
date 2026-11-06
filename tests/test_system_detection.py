from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import ROOT
from engine import system_detect, utilities as u


class OsReleaseTests(unittest.TestCase):
    def test_parse_real_os_release(self):
        data = u.parse_os_release()
        self.assertEqual(data.get("ID"), "ubuntu")
        self.assertIn("VERSION_ID", data)

    def test_parse_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "os-release"
            path.write_text(
                '# comment\nNAME="Test OS"\nID=testos\n'
                "VERSION_ID='1.2'\nEMPTY=\nBADLINE\n")
            data = u.parse_os_release(path)
            self.assertEqual(data["NAME"], "Test OS")
            self.assertEqual(data["VERSION_ID"], "1.2")
            self.assertEqual(data["EMPTY"], "")
            self.assertNotIn("BADLINE", data)

    def test_missing_file(self):
        with self.assertRaises(u.ConfigError):
            u.parse_os_release(Path("/nonexistent/os-release"))


class DetectTests(unittest.TestCase):
    def test_detect_shape(self):
        system = system_detect.detect()
        for key in ("os", "desktop", "hardware", "extensions", "interface", "tools"):
            self.assertIn(key, system)
        self.assertEqual(system["os"]["id"], "ubuntu")
        self.assertIsInstance(system["desktop"]["gnome_major"], int)
        self.assertIn(system["desktop"]["session"], ("wayland", "x11"))
        self.assertGreater(system["hardware"]["ram_mb"], 0)
        self.assertIn("enabled", system["extensions"])
        self.assertIsInstance(system["extensions"]["enabled"], list)

    def test_gnome_major_matches_binary(self):
        version = u.gnome_shell_version()
        self.assertIsNotNone(version)
        self.assertTrue(version[0].isdigit())

    def test_extension_state_is_consistent(self):
        system = system_detect.detect()
        self.assertIsInstance(system["extensions"]["installed"], dict)
        self.assertIsInstance(system["extensions"]["disabled"], list)


if __name__ == "__main__":
    unittest.main()
