from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT, read_json
from engine import (downloader, extension_manager, package_manager,
                    system_detect, verifier)
from engine import utilities as u


class InstalledSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installed = (Path.home() / ".local/share/themes/TPCT-Mac-Dark").exists()
        cls.system = system_detect.detect() if cls.installed else None

    def setUp(self):
        if not self.installed:
            self.skipTest("desktop is not installed on this machine")

    def test_verification_has_no_failures(self):
        report = verifier.verify(ROOT, None, self.system)  # state unused by checks
        self.assertFalse(report.failures,
                         [f"{c.name}: {c.detail}" for c in report.failures])
        self.assertGreater(report.counts()["pass"], 50)

    def test_required_files_installed(self):
        home = Path.home()
        for relative in (
            ".local/share/themes/TPCT-Mac-Dark/gnome-shell/gnome-shell.css",
            ".local/share/icons/WhiteSur-dark/index.theme",
            ".local/share/icons/WhiteSur-cursors/cursors/default",
            ".local/share/fonts/Inter-Variable.ttf",
            ".local/share/backgrounds/macos-tahoe/tahoe-dark.jpg",
            ".config/gtk-4.0/gtk.css",
            ".config/gtk-3.0/gtk.css",
        ):
            with self.subTest(path=relative):
                self.assertTrue((home / relative).exists(), relative)

    def test_extensions_are_gnome50_compatible(self):
        for uuid in ("tpct-mac-shell@tpct",
                     "user-theme@gnome-shell-extensions.gcampax.github.com"):
            meta = extension_manager.metadata(uuid)
            self.assertIsNotNone(meta, uuid)
            self.assertIn("50", [str(v) for v in meta["shell-version"]])

    def test_only_one_dock(self):
        enabled = u.gsettings_array(u.gsettings_get(
            "org.gnome.shell", "enabled-extensions"))
        self.assertIn("macos-dock@vinnytherobot.github.io", enabled)
        self.assertNotIn("ubuntu-dock@ubuntu.com", enabled)

    def test_blur_and_glass_assets_installed(self):
        self.assertIn("blur-my-shell@aunetx",
                      u.gsettings_array(u.gsettings_get(
                          "org.gnome.shell", "enabled-extensions")))
        for path in ("assets/themes/overrides/liquid-dark.css",
                     "assets/themes/overrides/liquid-light.css",
                     "assets/dock/liquid-dock-dark.css",
                     "config/palette-dark.json",
                     "config/palette-light.json"):
            self.assertTrue((ROOT / path).exists(), path)


class MissingInstallTests(unittest.TestCase):
    def test_missing_theme_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            with mock.patch.object(verifier, "_data", lambda *p: fake_home.joinpath(*p)), \
                 mock.patch.object(verifier, "_config", lambda *p: fake_home.joinpath(*p)), \
                 mock.patch.object(verifier, "_home", lambda *p: fake_home.joinpath(*p)):
                report = verifier.Report()
                verifier.verify_files(report)
        self.assertTrue(report.failures)
        names = [c.id for c in report.failures]
        self.assertIn("theme-Dark", names)


class OfflineBundleTests(unittest.TestCase):
    def test_every_referenced_asset_exists(self):
        assets = read_json(ROOT / "manifests/assets.json")["assets"]
        for name, asset in assets.items():
            with self.subTest(asset=name):
                self.assertTrue((ROOT / asset["local"]).exists(), asset["local"])

    def test_bundled_rofi_packages_verify(self):
        debs = package_manager._bundled_debs(ROOT)
        self.assertEqual(len(debs), 10)
        names = {d.name for d in debs}
        self.assertIn("rofi_2.0.0-0.2_amd64.deb", names)

    def test_bundled_extension_zips(self):
        for uuid, version in (
            ("user-theme@gnome-shell-extensions.gcampax.github.com", 79),
            ("blur-my-shell@aunetx", 77),
        ):
            path = (ROOT / "assets/cache/extensions"
                    / f"{uuid}.shell-extension.zip")
            self.assertTrue(path.exists())
            meta = compatibility_meta(path)
            self.assertEqual(meta["uuid"], uuid)
            self.assertEqual(meta["version"], version)
            self.assertIn("50", [str(v) for v in meta["shell-version"]])

    def test_icon_tarballs_extract(self):
        for name in ("WhiteSur-dark.tar.gz", "WhiteSur-light.tar.gz",
                     "WhiteSur-icons-src.tar.gz"):
            with tempfile.TemporaryDirectory() as tmp:
                u.safe_extract_tar(ROOT / "assets/icons" / name, Path(tmp))
                self.assertTrue(any(Path(tmp).iterdir()))


def compatibility_meta(path: Path) -> dict:
    from engine import compatibility
    return compatibility.read_zip_metadata(path)


class DownloaderTests(unittest.TestCase):
    def test_http_is_refused(self):
        dl = downloader.Downloader(Path(tempfile.mkdtemp()), offline=False)
        with self.assertRaises(u.EngineError):
            dl.fetch("http://example.com/x", filename="x")

    def test_offline_uncached_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl = downloader.Downloader(Path(tmp), offline=True)
            with self.assertRaises(downloader.OfflineUnavailable):
                dl.fetch("https://example.com/x", filename="x")

    def test_offline_cached_file_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            cached = cache / "x.bin"
            cached.write_bytes(b"data")
            dl = downloader.Downloader(cache, offline=True)
            self.assertEqual(dl.fetch("https://example.com/x", filename="x.bin"),
                             cached)


class UninstallSafetyTests(unittest.TestCase):
    def test_dry_run_removes_nothing(self):
        from engine import rollback_manager
        from engine.state_manager import State
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            result = rollback_manager.uninstall(ROOT, state, backup_dir=None,
                                                dry_run=True, restore_backup=False)
            self.assertIsInstance(result, dict)
            # The real installed theme must still be present.
            self.assertTrue((Path.home() / ".local/share/themes/TPCT-Mac-Dark").exists())


if __name__ == "__main__":
    unittest.main()
