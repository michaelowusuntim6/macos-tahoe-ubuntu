from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import ROOT, read_json
from engine import utilities as u

CONFIG_FILES = sorted((ROOT / "config").glob("*.json"))
MANIFEST_FILES = sorted((ROOT / "manifests").glob("*.json"))


class JsonValidityTests(unittest.TestCase):
    def test_all_config_and_manifests_parse(self):
        self.assertTrue(CONFIG_FILES)
        self.assertTrue(MANIFEST_FILES)
        for path in CONFIG_FILES + MANIFEST_FILES:
            with self.subTest(path=path.name):
                data = json.loads(path.read_text())
                self.assertIsInstance(data, dict)

    def test_expected_manifests_exist(self):
        for name in ("components.lock.json", "repositories.json", "assets.json",
                     "supported-systems.json"):
            self.assertTrue((ROOT / "manifests" / name).is_file(), name)
        for name in ("desktop.json", "hardware-profiles.json",
                     "extension-manifest.json", "package-manifest.json",
                     "appearance-profiles.json"):
            self.assertTrue((ROOT / "config" / name).is_file(), name)


class SupportedSystemTests(unittest.TestCase):
    def test_primary_profile(self):
        data = read_json(ROOT / "manifests/supported-systems.json")
        profiles = data["profiles"]
        primary = [p for p in profiles if p["release"] == "26.04"]
        self.assertEqual(len(primary), 1)
        self.assertEqual(primary[0]["gnome_major"], 50)
        self.assertIn("wayland", primary[0]["sessions"])
        self.assertEqual(primary[0]["status"], "validated")

    def test_requirements_present(self):
        data = read_json(ROOT / "manifests/supported-systems.json")
        reqs = data["requirements"]
        for key in ("required_commands", "required_schemas", "min_ram_mb",
                    "min_free_disk_mb"):
            self.assertIn(key, reqs)


class LockfileTests(unittest.TestCase):
    def test_pins_are_exact(self):
        lock = read_json(ROOT / "manifests/components.lock.json")
        components = lock["components"]
        self.assertRegex(components["tpct-mac-theme"]["commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(components["whiteSur-icon-theme"]["commit"], r"^[0-9a-f]{40}$")
        for name in ("user-theme-extension", "blur-my-shell"):
            versions = components[name]["shell_versions"]
            self.assertIn("50", [str(v) for v in versions])
            self.assertIsInstance(components[name]["version"], int)

    def test_all_pinned_checksums_are_real(self):
        assets = read_json(ROOT / "manifests/assets.json")["assets"]
        checked = 0
        for name, asset in assets.items():
            expected = asset.get("sha256")
            if not expected or expected in ("PENDING", "computed-at-install"):
                continue
            path = ROOT / asset["local"]
            with self.subTest(asset=name):
                self.assertTrue(path.exists(), f"missing {path}")
                self.assertEqual(u.sha256_file(path), expected)
                checked += 1
        self.assertGreaterEqual(checked, 6)

    def test_lock_extension_files_exist(self):
        lock = read_json(ROOT / "manifests/components.lock.json")["components"]
        for name in ("tpct-mac-theme", "whiteSur-icon-theme", "whiteSur-cursors",
                     "inter-font", "user-theme-extension", "blur-my-shell"):
            entry = lock[name]
            if "bundled" in entry:
                with self.subTest(component=name):
                    self.assertTrue((ROOT / entry["bundled"]).exists(),
                                    f"missing bundled {entry['bundled']}")

    def test_no_pending_hashes(self):
        text = (ROOT / "manifests/assets.json").read_text()
        self.assertNotIn('"PENDING"', text)


class ExtensionManifestTests(unittest.TestCase):
    def test_required_extensions_have_gnome50(self):
        config = read_json(ROOT / "config/extension-manifest.json")
        for uuid in ("tpct-mac-shell@tpct",
                     "user-theme@gnome-shell-extensions.gcampax.github.com"):
            self.assertIn(uuid, config["extensions"])
        meta = json.loads((ROOT / "extensions/tpct-mac-shell@tpct/metadata.json").read_text())
        self.assertIn("50", [str(v) for v in meta["shell-version"]])

    def test_dock_conflicts_documented(self):
        config = read_json(ROOT / "config/extension-manifest.json")
        self.assertTrue(config["extensions"]["ubuntu-dock@ubuntu.com"])
        self.assertTrue(config["rejected"])


class GtkCssTests(unittest.TestCase):
    def test_gtk_css_avoids_unsupported_important(self):
        """GTK's CSS parser rejects !important; it must only appear in St CSS."""
        for path in sorted((ROOT / "assets/gtk").glob("*.css")):
            with self.subTest(path=path.name):
                text = path.read_text()
                self.assertNotIn("!important", text)
                self.assertIn("generate_glass.py", text)

    def test_popover_outer_layer_is_reset(self):
        css = (ROOT / "assets/gtk/liquid-gtk-dark.css").read_text()
        self.assertIn("popover.background", css)
        self.assertIn("background-color: transparent", css)


class AutoHideTests(unittest.TestCase):
    def test_dock_autohide_polls_pointer(self):
        js = (ROOT / "extensions/macos-dock@vinnytherobot.github.io/lib/dockVisibility.js").read_text()
        self.assertIn("_startPointerPoll", js)
        self.assertIn("autoHideDelay", js)
        # The hide delay must not be the old hard-coded 120 ms debounce.
        self.assertNotIn("PRIORITY_DEFAULT, 120", js)

    def test_autohide_delay_is_exposed_and_configured(self):
        schema = (ROOT / "extensions/macos-dock@vinnytherobot.github.io/schemas/"
                  "org.gnome.shell.extensions.macosdock.gschema.xml").read_text()
        self.assertIn('name="auto-hide-delay"', schema)
        motion = read_json(ROOT / "config/motion.json")
        self.assertGreaterEqual(motion["dock"]["auto_hide_delay_ms"], 0)


class BundledPackageTests(unittest.TestCase):
    def test_checksum_list_matches_debs(self):
        apt = ROOT / "assets/cache/apt"
        sums = apt / "SHA256SUMS"
        self.assertTrue(sums.exists())
        entries = {}
        for line in sums.read_text().splitlines():
            if line.strip():
                digest, name = line.split(maxsplit=1)
                entries[name.strip()] = digest
        self.assertIn("rofi_2.0.0-0.2_amd64.deb", entries)
        for name, digest in entries.items():
            with self.subTest(deb=name):
                self.assertEqual(u.sha256_file(apt / name), digest)


if __name__ == "__main__":
    unittest.main()
