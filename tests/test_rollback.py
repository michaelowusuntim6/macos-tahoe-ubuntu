from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT  # noqa: F401
from engine import rollback_manager, utilities as u
from engine.state_manager import State

SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.tahoe.test" path="/org/tahoe/test/">
    <key name="greeting" type="s">
      <default>'default-value'</default>
    </key>
    <key name="enabled" type="b">
      <default>false</default>
    </key>
    <key name="count" type="i">
      <default>3</default>
    </key>
  </schema>
</schemalist>
"""


class RollbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tahoe-rollback-test-"))
        cls.schemas = cls.tmp / "schemas"
        cls.schemas.mkdir()
        (cls.schemas / "org.tahoe.test.gschema.xml").write_text(SCHEMA)
        u.run(["glib-compile-schemas", "--strict", str(cls.schemas)], timeout=30)
        cls.state = State(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        u.gsettings_reset("org.tahoe.test", "greeting", cls.schemas)
        u.gsettings_reset("org.tahoe.test", "enabled", cls.schemas)
        u.gsettings_reset("org.tahoe.test", "count", cls.schemas)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_restore_raw_string(self):
        before = u.gsettings_get("org.tahoe.test", "greeting", self.schemas)
        u.gsettings_set_raw("org.tahoe.test", "greeting", "'changed'", self.schemas)
        self.assertEqual(
            u.gsettings_get("org.tahoe.test", "greeting", self.schemas), "'changed'")
        self.state.record_setting("org.tahoe.test", "greeting", before,
                                  "'changed'", self.schemas)
        restored = rollback_manager.restore_managed_settings(self.state)
        self.assertTrue(restored)
        self.assertEqual(
            u.gsettings_get("org.tahoe.test", "greeting", self.schemas), before)

    def test_restore_boolean_and_integer(self):
        b_before = u.gsettings_get("org.tahoe.test", "enabled", self.schemas)
        i_before = u.gsettings_get("org.tahoe.test", "count", self.schemas)
        u.gsettings_set_raw("org.tahoe.test", "enabled", "true", self.schemas)
        u.gsettings_set_raw("org.tahoe.test", "count", "42", self.schemas)
        self.state.record_setting("org.tahoe.test", "enabled", b_before,
                                  "true", self.schemas)
        self.state.record_setting("org.tahoe.test", "count", i_before,
                                  "42", self.schemas)
        rollback_manager.restore_managed_settings(self.state)
        self.assertEqual(
            u.gsettings_get("org.tahoe.test", "enabled", self.schemas), b_before)
        self.assertEqual(
            u.gsettings_get("org.tahoe.test", "count", self.schemas), i_before)

    def test_reset_when_key_did_not_exist(self):
        u.gsettings_set_raw("org.tahoe.test", "greeting", "'temporary'", self.schemas)
        self.state.record_setting("org.tahoe.test", "greeting", None,
                                  "'temporary'", self.schemas)
        rollback_manager.restore_managed_settings(self.state)
        self.assertEqual(
            u.gsettings_get("org.tahoe.test", "greeting", self.schemas),
            "'default-value'")

    def test_state_journal_is_persisted(self):
        path = self.tmp / "state/applied-settings.json"
        self.assertTrue(path.exists())
        data = u.read_json(path)
        self.assertIn("settings", data)

    def test_dry_run_changes_nothing(self):
        before = u.gsettings_get("org.tahoe.test", "greeting", self.schemas)
        u.gsettings_set_raw("org.tahoe.test", "greeting", "'x'", self.schemas)
        self.state.record_setting("org.tahoe.test", "greeting", before, "'x'", self.schemas)
        plan = rollback_manager.restore_managed_settings(self.state, dry_run=True)
        self.assertTrue(any("dry-run" in p for p in plan))
        self.assertEqual(
            u.gsettings_get("org.tahoe.test", "greeting", self.schemas), "'x'")
        rollback_manager.restore_managed_settings(self.state)
        self.assertEqual(
            u.gsettings_get("org.tahoe.test", "greeting", self.schemas), before)


if __name__ == "__main__":
    unittest.main()
