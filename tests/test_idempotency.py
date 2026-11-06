from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT
from engine import theme_manager, utilities as u
from engine.state_manager import State


class ThemeIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tahoe-idem-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.patches = [
            mock.patch.object(u, "data_home", lambda: self.tmp / ".local/share"),
            mock.patch.object(u, "config_home", lambda: self.tmp / ".config"),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_gtk_layers_are_stable(self):
        theme_manager.install_gtk_layers(ROOT)
        gtk3 = self.tmp / ".config/gtk-3.0/gtk.css"
        gtk4 = self.tmp / ".config/gtk-4.0/gtk.css"
        first3 = gtk3.read_text()
        first4 = gtk4.read_text()
        theme_manager.install_gtk_layers(ROOT)
        self.assertEqual(gtk3.read_text(), first3)
        self.assertEqual(gtk4.read_text(), first4)
        self.assertEqual(first3.count("macos-tahoe-ubuntu: begin"), 1)
        self.assertEqual(first3.count("macos-tahoe-ubuntu: end"), 1)
        self.assertEqual(first4.count("/* tpct-mac-theme */"), 1)

    def test_gtk3_block_preserves_foreign_rules(self):
        gtk3 = self.tmp / ".config/gtk-3.0/gtk.css"
        gtk3.parent.mkdir(parents=True)
        gtk3.write_text("/* user custom rule */\n.my-app { color: red; }\n")
        theme_manager.install_gtk_layers(ROOT)
        text = gtk3.read_text()
        self.assertIn("user custom rule", text)
        self.assertIn("macos-tahoe-ubuntu: begin", text)
        theme_manager.install_gtk_layers(ROOT)
        self.assertEqual(gtk3.read_text().count("macos-tahoe-ubuntu: begin"), 1)
        self.assertIn(".my-app", gtk3.read_text())

    def test_fonts_wallpapers_and_rofi_stable(self):
        theme_manager.install_fonts(ROOT)
        theme_manager.install_wallpapers(ROOT)
        theme_manager.install_rofi_theme(ROOT)
        font = self.tmp / ".local/share/fonts/Inter-Variable.ttf"
        digest = u.sha256_file(font)
        wallpaper_dir = self.tmp / ".local/share/backgrounds/macos-tahoe"
        wallpapers = sorted(wallpaper_dir.glob("*.jpg"))
        self.assertEqual(len(wallpapers), 2)
        self.assertTrue(all(p.stat().st_size > 1000 for p in wallpapers))
        rasi = (self.tmp / ".config/rofi/tahoe-dark.rasi").read_text()
        theme_manager.install_fonts(ROOT)
        theme_manager.install_wallpapers(ROOT)
        theme_manager.install_rofi_theme(ROOT)
        self.assertEqual(u.sha256_file(font), digest)
        self.assertEqual(len(list((self.tmp / ".local/share/backgrounds/macos-tahoe").glob("*.jpg"))), 2)
        self.assertEqual((self.tmp / ".config/rofi/tahoe-dark.rasi").read_text(), rasi)


class StateIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tahoe-state-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = State(self.tmp)

    def test_setting_recorded_once(self):
        self.state.record_setting("org.test", "key", "'a'", "'b'")
        self.state.record_setting("org.test", "key", "'a'", "'c'")
        entries = self.state.settings["settings"]
        self.assertEqual(len(entries), 1)
        entry = next(iter(entries.values()))
        self.assertEqual(entry["before"], "'a'")
        self.assertEqual(entry["after"], "'c'")

    def test_phase_bookkeeping_is_idempotent(self):
        self.state.start_phase("assets")
        self.state.finish_phase("assets")
        self.state.finish_phase("assets")
        self.assertEqual(self.state.installation["completed_phases"], ["assets"])
        self.assertEqual(self.state.installation["phases"]["assets"]["status"], "ok")

    def test_interrupted_phase_is_reconciled(self):
        self.state.start_phase("desktop")
        reloaded = State(self.tmp)
        self.assertEqual(reloaded.installation["phases"]["desktop"]["status"], "interrupted")
        self.assertTrue(reloaded.installation["resume_required"])
        self.assertIn("desktop", reloaded.installation["failed_phases"])

    def test_fresh_run_clears_transaction_but_keeps_data(self):
        self.state.record_setting("org.test", "key", "'a'", "'b'")
        self.state.start_phase("assets")
        self.state.finish_phase("assets")
        self.state.installation["backup_dir"] = "/tmp/backup"
        self.state.begin_fresh_run()
        self.assertEqual(self.state.installation["completed_phases"], [])
        self.assertIsNone(self.state.installation["backup_dir"])
        self.assertEqual(len(self.state.settings["settings"]), 1)

    def test_components_are_updated_not_duplicated(self):
        self.state.set_component("dock", "pending")
        self.state.set_component("dock", "applied", position="BOTTOM")
        self.assertEqual(len(self.state.components["components"]), 1)
        self.assertEqual(self.state.components["components"]["dock"]["status"], "applied")


if __name__ == "__main__":
    unittest.main()
