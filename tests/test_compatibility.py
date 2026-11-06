from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from helpers import ROOT, fake_system
from engine import compatibility


class EvaluateTests(unittest.TestCase):
    def test_validated_machine(self):
        result = compatibility.evaluate(ROOT, fake_system())
        self.assertEqual(result.status, "validated")
        self.assertEqual(result.profile_id, "ubuntu-26.04-gnome50")
        self.assertFalse(result.reasons)
        self.assertEqual(result.recommended_profile, "lightweight")
        self.assertFalse(result.effects.get("panel_blur", True))

    def test_new_point_release_is_untested_and_gated(self):
        result = compatibility.evaluate(ROOT, fake_system(release="26.10"))
        self.assertEqual(result.status, "unsupported")
        self.assertTrue(any("untested" in reason for reason in result.reasons))
        allowed = compatibility.evaluate(ROOT, fake_system(release="26.10"),
                                         allow_untested=True)
        self.assertEqual(allowed.status, "untested")

    def test_new_gnome_major_is_refused(self):
        result = compatibility.evaluate(ROOT, fake_system(gnome_major=52))
        self.assertEqual(result.status, "unsupported")
        self.assertTrue(result.reasons)

    def test_forced_unsupported_is_warned(self):
        result = compatibility.evaluate(ROOT, fake_system(gnome_major=52),
                                        force_unsupported=True)
        self.assertEqual(result.status, "untested")
        self.assertTrue(any("force-unsupported" in w for w in result.warnings))

    def test_non_ubuntu_is_refused(self):
        result = compatibility.evaluate(ROOT, fake_system(distro="fedora"))
        self.assertEqual(result.status, "unsupported")

    def test_low_ram_is_refused(self):
        result = compatibility.evaluate(ROOT, fake_system(ram=2048))
        self.assertEqual(result.status, "unsupported")
        self.assertTrue(any("RAM" in r for r in result.reasons))

    def test_low_disk_is_refused(self):
        result = compatibility.evaluate(ROOT, fake_system(free_disk=100))
        self.assertEqual(result.status, "unsupported")
        self.assertTrue(any("disk" in r.lower() for r in result.reasons))

    def test_x11_is_accepted(self):
        result = compatibility.evaluate(ROOT, fake_system(session="x11"))
        self.assertEqual(result.status, "validated")

    def test_high_end_hardware_gets_full_profile(self):
        system = fake_system(ram=32768)
        system["hardware"]["gpu"] = {"names": ["NVIDIA GeForce RTX 4060"],
                                     "driver": "nvidia", "renderer": "RTX 4060"}
        result = compatibility.evaluate(ROOT, system)
        self.assertEqual(result.recommended_profile, "full")
        self.assertTrue(result.effects.get("panel_blur"))


class ExtensionCompatibilityTests(unittest.TestCase):
    def test_supported(self):
        ok, _ = compatibility.extension_supported(
            {"shell-version": ["46", "50", "51"]}, 50)
        self.assertTrue(ok)

    def test_unsupported_refuses(self):
        ok, reason = compatibility.extension_supported(
            {"shell-version": ["45", "46"]}, 50)
        self.assertFalse(ok)
        self.assertIn("refusing to modify", reason)

    def test_unknown_gnome_version(self):
        ok, _ = compatibility.extension_supported({"shell-version": ["50"]}, None)
        self.assertFalse(ok)

    def test_zip_metadata_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ext.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("metadata.json", json.dumps(
                    {"uuid": "test@example", "shell-version": ["50"]}))
            meta = compatibility.read_zip_metadata(archive)
            self.assertEqual(meta["uuid"], "test@example")

    def test_bad_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.zip"
            archive.write_text("not a zip")
            with self.assertRaises(Exception):
                compatibility.read_zip_metadata(archive)


if __name__ == "__main__":
    unittest.main()
